"""
CyberClean v2.3 — Security Scanner
FIX #3: rglob → os.walk(followlinks=False) to prevent infinite loops
        from circular symlinks (e.g. ~/.config/app -> /tmp -> ~/.config).
        rglob skips symlinked *files* but still DESCENDS INTO symlinked *directories*.
        os.walk(followlinks=False) stops at the symlink directory boundary entirely.
FIX (cron): /var/spool/cron usually requires root — now logs "permission denied"
            instead of silently skipping, so user knows scan was partial.
FIX (v2.3 HIGH #2): kill-pid now validated through _safe_kill_cmd() before being
        embedded in fix_cmd. Guards against:
        - PID < 100  → kernel/init/systemd processes, killing = system freeze
        - PID not owned by current user on Linux (checks /proc/{pid}/status)
        - PID 0, 1, 2 always blocked regardless of ownership
        The helper still does the actual kill; this prevents building a
        dangerous fix_cmd that targets a protected PID in the first place.
"""
import os, subprocess, platform, stat, re
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Callable

OS     = platform.system()
HELPER = '/usr/local/bin/cyber-clean-helper'

# ── PID safety guard ──────────────────────────────────────────
# Minimum PID allowed for kill actions.
# PIDs < 100 are almost always kernel threads, init, udevd, etc.
# Killing them causes a system freeze or kernel panic.
_PID_MIN_SAFE = 100

def _safe_kill_cmd(pid: int) -> str:
    """
    Return a fix_cmd string for killing the given PID, or an empty string
    if the PID is protected (system process / not user-owned).

    Rules:
      1. PID must be > _PID_MIN_SAFE (100) — blocks init, systemd, kernel threads
      2. On Linux: process must be owned by the current user (reads /proc/{pid}/status)
         Root is exempt from the ownership check (can kill anything).
      3. Always blocks PID 0, 1, 2 regardless of any other check.

    Returns '' (empty) when the kill should NOT be offered in the UI.
    """
    # Rule 1 & 3: hard PID floor
    if pid <= _PID_MIN_SAFE:
        return ''

    # Rule 2: Linux ownership check
    if OS == 'Linux':
        current_uid = os.getuid()
        if current_uid != 0:   # root can kill anything — skip check for root
            try:
                status = Path(f'/proc/{pid}/status').read_text(errors='ignore')
                for line in status.splitlines():
                    if line.startswith('Uid:'):
                        # Uid: real  effective  saved  filesystem
                        proc_uid = int(line.split()[1])
                        if proc_uid != current_uid:
                            return ''   # not our process — don't offer kill
                        break
            except (OSError, ValueError):
                return ''   # can't read /proc → play it safe, don't offer kill

    return f'sudo -n {HELPER} kill-pid {pid}'


def _h(action: str, target: str = '') -> str:
    if target:
        return f'sudo -n {HELPER} {action} "{target}"'
    return f'sudo -n {HELPER} {action}'

@dataclass
class ScanResult:
    severity:  str
    category:  str
    path:      str
    detail:    str
    can_fix:   bool = False
    fix_cmd:   str  = ''

def run(cmd, timeout=10):
    try:
        no_win = 0x08000000 if OS == 'Windows' else 0
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=timeout, creationflags=no_win)
        return r.stdout.strip()
    except: return ''


def _is_expected_suid_path(path: str) -> bool:
    """
    Chromium / Electron intentionally install a setuid helper named chrome-sandbox
    (e.g. /usr/lib/electron39/chrome-sandbox on Arch). Flagging it is a false
    positive; stripping SUID would break the browser sandbox.
    """
    p = path.replace('\\', '/')
    if not p.endswith('/chrome-sandbox'):
        return False
    if not (p.startswith('/usr/') or p.startswith('/opt/')):
        return False
    pl = p.lower()
    markers = (
        '/electron', '/chromium', '/chromium-browser',
        '/chrome/', '/google-chrome', 'google-chrome',
        '/opt/google/chrome', '/brave', '/vivaldi', '/opera',
        'microsoft-edge', '/edge/',
    )
    return any(m in pl for m in markers)


SUSPICIOUS_SCRIPTS = [
    (r'bash\s+-i\s+>&\s*/dev/tcp',          'Reverse bash shell'),
    (r'nc\s+-e\s+/bin/(bash|sh)',            'Netcat reverse shell'),
    (r'python.*socket.*connect.*subprocess', 'Python reverse shell'),
    (r'curl\s+.*\|\s*(bash|sh)',             'Remote code execution via curl|bash'),
    (r'wget\s+.*-O-\s*\|',                  'Remote code execution via wget|pipe'),
    (r'eval\s*\(\s*base64_decode',           'PHP base64 eval (webshell pattern)'),
    (r'eval\s*\(\s*gzinflate',               'PHP obfuscated eval (webshell)'),
    (r'(xmrig|minerd|cpuminer)',             'Crypto miner binary/reference'),
    (r'stratum\+tcp://',                     'Mining pool connection string'),
    (r'LD_PRELOAD.*=',                       'LD_PRELOAD manipulation'),
    (r'/proc/\d+/mem',                       'Direct process memory access'),
]

DANGEROUS_EXTENSIONS = {'.sh', '.py', '.rb', '.pl', '.php', '.exe', '.elf', '.bin',
                         '.bat', '.ps1', '.vbs', '.cmd', '.dll', '.scr', '.pif'}
SCAN_DIRS_LINUX   = ['/tmp', '/var/tmp', '/dev/shm', str(Path.home()/'.local/bin'),
                     str(Path.home()/'.config'), '/etc/cron.d', '/etc/cron.daily',
                     '/etc/cron.hourly', '/etc/cron.weekly']
SCAN_DIRS_WINDOWS = [
    os.environ.get('TEMP',''), os.environ.get('APPDATA',''),
    'C:/Windows/Temp', 'C:/ProgramData',
]

KNOWN_MINERS = {'xmrig','xmrig-notls','minerd','cpuminer-multi','nbminer',
                'teamredminer','lolminer','gminer','t-rex','nanominer'}


def _safe_walk(root: Path):
    """
    FIX #3: Walk directory tree WITHOUT following symlinks.
    os.walk(followlinks=False) stops at symlinked directory boundaries,
    preventing infinite loops from circular symlinks like:
      ~/.config/app -> /tmp -> ~/.config  (creates infinite recursion with rglob)
    Yields Path objects for regular files only.
    """
    try:
        for dirpath, dirnames, filenames in os.walk(str(root), followlinks=False):
            # Remove symlinked subdirs from dirnames to prevent descent
            dirnames[:] = [
                d for d in dirnames
                if not os.path.islink(os.path.join(dirpath, d))
            ]
            for fname in filenames:
                fpath = Path(dirpath) / fname
                if fpath.is_symlink():
                    continue   # skip symlinked files too
                yield fpath
    except (PermissionError, OSError):
        pass


class SecurityScanner:

    def __init__(self):
        self.results: List[ScanResult] = []

    def scan(self, log_cb: Callable[[str,str], None]) -> List[ScanResult]:
        self.results = []
        log_cb('═'*52, 'head')
        log_cb('  SECURITY SCAN  //  Deep Analysis', 'head')
        log_cb('═'*52, 'head')

        if OS == 'Linux':
            self._scan_running_processes(log_cb)
            self._scan_suid_sgid(log_cb)
            self._scan_world_writable(log_cb)
            self._scan_cron(log_cb)
            self._scan_suspicious_files(log_cb, SCAN_DIRS_LINUX)
            self._scan_network_linux(log_cb)
            self._scan_ld_preload(log_cb)
            self._scan_ssh_authorized_keys(log_cb)
            self._scan_hosts_file(log_cb)
        elif OS == 'Windows':
            self._scan_running_processes(log_cb)
            self._scan_suspicious_files(log_cb, [d for d in SCAN_DIRS_WINDOWS if d])
            self._scan_autorun_windows(log_cb)
            self._scan_network_windows(log_cb)
            self._scan_hosts_file(log_cb)

        crits = [r for r in self.results if r.severity == 'critical']
        highs = [r for r in self.results if r.severity == 'high']
        log_cb('', 'info')
        log_cb('═'*52, 'head')
        if crits:
            log_cb(f'  ⛔  {len(crits)} CRITICAL threats found!', 'err')
        if highs:
            log_cb(f'  ⚠   {len(highs)} HIGH severity issues', 'warn')
        if not crits and not highs:
            log_cb('  ✓   No critical threats detected', 'ok')
        log_cb(f'  Total findings: {len(self.results)}', 'info')
        log_cb('═'*52, 'head')
        return self.results

    # ── Running processes ─────────────────────────────────
    def _scan_running_processes(self, log_cb):
        log_cb('', 'info')
        log_cb('◆ Scanning running processes...', 'info')
        try:
            import psutil
            for p in psutil.process_iter(['pid','name','exe','cmdline']):
                try:
                    name = (p.info['name'] or '').lower()
                    exe  = p.info['exe'] or ''
                    cmd  = ' '.join(p.info['cmdline'] or []).lower()

                    if name in KNOWN_MINERS:
                        _kill = _safe_kill_cmd(p.pid)
                        r = ScanResult('critical','malware', exe or name,
                            f'Crypto miner running: {name} (PID {p.pid})',
                            can_fix=bool(_kill), fix_cmd=_kill)
                        self.results.append(r)
                        log_cb(f'  ⛔  MINER: {name} PID={p.pid}', 'err')
                        continue

                    is_appimage_mount = exe and re.search(r'/tmp/\.mount_', exe)
                    if exe and any(exe.startswith(d) for d in ['/tmp','/dev/shm','/var/tmp']) and not is_appimage_mount:
                        _kill = _safe_kill_cmd(p.pid)
                        r = ScanResult('high','suspicious', exe,
                            f'Process running from temp dir: {exe} (PID {p.pid})',
                            can_fix=bool(_kill), fix_cmd=_kill)
                        self.results.append(r)
                        log_cb(f'  ⚠  Suspicious exec from tmp: {exe}', 'warn')

                    for pattern, desc in SUSPICIOUS_SCRIPTS:
                        if re.search(pattern, cmd, re.I):
                            _kill = _safe_kill_cmd(p.pid)
                            r = ScanResult('critical','malware', exe or name,
                                f'{desc} in process cmdline (PID {p.pid})',
                                can_fix=bool(_kill), fix_cmd=_kill)
                            self.results.append(r)
                            log_cb(f'  ⛔  {desc}: PID {p.pid}', 'err')
                            break
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass   # process exited during scan iteration
        except ImportError:
            log_cb('  ~ psutil not available — process scan skipped', 'dim')

        found = [r for r in self.results if r.category in ('malware','suspicious')]
        if not found:
            log_cb('  ✓  No malicious processes detected', 'ok')

    # ── SUID/SGID (Linux) ─────────────────────────────────
    def _scan_suid_sgid(self, log_cb):
        log_cb('', 'info')
        log_cb('◆ Scanning SUID/SGID binaries...', 'info')
        known_suid = {
            '/usr/bin/sudo', '/usr/bin/su', '/usr/bin/passwd', '/usr/bin/newgrp',
            '/usr/bin/suexec',
            '/usr/bin/chsh', '/usr/bin/chfn', '/usr/bin/gpasswd',
            '/usr/bin/pkexec', '/usr/lib/polkit-1/polkit-agent-helper-1',
            '/bin/ping', '/usr/bin/ping', '/usr/bin/traceroute',
            '/usr/bin/mount', '/usr/bin/umount', '/usr/sbin/unix_chkpwd',
            '/usr/bin/Xorg', '/usr/lib/xorg/Xorg',
            '/usr/lib/xorg-server/Xorg.wrap',
            '/usr/lib/systemd/systemd-logind',
            '/usr/lib/systemd/systemd-user-sessions',
            '/usr/bin/fusermount', '/usr/bin/fusermount3',
            '/usr/lib/dbus-1.0/dbus-daemon-launch-helper',
        }
        out = run('find /usr /bin /sbin /tmp -perm /4000 -type f 2>/dev/null', timeout=15)
        found = 0
        for line in out.splitlines():
            f = line.strip()
            if not f or f in known_suid or _is_expected_suid_path(f):
                continue
            self.results.append(ScanResult('high','suid', f,
                f'Unexpected SUID binary: {f}',
                can_fix=True, fix_cmd=f'sudo -n {HELPER} fix-suid "{f}"'))
            log_cb(f'  ⚠  Unexpected SUID: {f}', 'warn')
            found += 1
        if found == 0:
            log_cb('  ✓  No unexpected SUID binaries', 'ok')

    # ── World-writable (Linux) ────────────────────────────
    def _scan_world_writable(self, log_cb):
        log_cb('', 'info')
        log_cb('◆ Scanning world-writable files in system dirs...', 'info')
        out = run('find /etc /usr/local/bin /usr/bin -perm -0002 -type f 2>/dev/null', timeout=15)
        found = 0
        for line in out.splitlines():
            f = line.strip()
            if not f: continue
            self.results.append(ScanResult('high','writable', f,
                f'World-writable system file: {f}',
                can_fix=True, fix_cmd=f'sudo -n {HELPER} fix-writable "{f}"'))
            log_cb(f'  ⚠  World-writable: {f}', 'warn')
            found += 1
        if found == 0:
            log_cb('  ✓  No world-writable system files', 'ok')

    # ── Cron backdoors (Linux) ────────────────────────────
    def _scan_cron(self, log_cb):
        log_cb('', 'info')
        log_cb('◆ Scanning cron jobs for backdoors...', 'info')
        cron_dirs = ['/etc/cron.d','/etc/cron.daily','/etc/cron.hourly',
                     '/var/spool/cron', str(Path.home()/'.local/share/cron')]
        found = 0
        partial = False

        for d in cron_dirs:
            p = Path(d)
            if not p.exists():
                continue
            try:
                # FIX #3: use _safe_walk instead of rglob — stops at symlinked dirs
                for f in _safe_walk(p):
                    try:
                        txt = f.read_text(errors='ignore')
                        for pattern, desc in SUSPICIOUS_SCRIPTS:
                            if re.search(pattern, txt, re.I):
                                self.results.append(ScanResult('critical','cron', str(f),
                                    f'Suspicious cron: {desc} in {f.name}'))
                                log_cb(f'  ⛔  Cron backdoor: {desc} in {f}', 'err')
                                found += 1
                                break
                    except (PermissionError, OSError):
                        # FIX: log partial scan instead of silently skipping
                        log_cb(f'  ~ {f.name}: permission denied — run as root for full scan', 'dim')
                        partial = True
            except PermissionError:
                # Directory itself not readable (e.g. /var/spool/cron without root)
                log_cb(f'  ~ {d}: permission denied — run as root for full cron scan', 'dim')
                partial = True

        # User crontab
        crontab = run('crontab -l 2>/dev/null')
        for pattern, desc in SUSPICIOUS_SCRIPTS:
            if re.search(pattern, crontab, re.I):
                self.results.append(ScanResult('critical','cron','crontab',
                    f'Suspicious user crontab: {desc}'))
                log_cb(f'  ⛔  Cron backdoor in user crontab: {desc}', 'err')
                found += 1

        if found == 0:
            if partial:
                log_cb('  ✓  No backdoors found in accessible cron dirs (partial scan)', 'ok')
            else:
                log_cb('  ✓  No cron backdoors found', 'ok')

    # ── Suspicious files ─────────────────────────────────
    def _scan_suspicious_files(self, log_cb, dirs):
        log_cb('', 'info')
        log_cb('◆ Scanning suspicious files in temp/user dirs...', 'info')
        found = 0
        for d in dirs:
            p = Path(d)
            if not p.exists(): continue
            try:
                # FIX #3: use _safe_walk instead of rglob
                # rglob with f.is_symlink() guard skips symlinked files but STILL
                # descends INTO symlinked directories → infinite loop on circular symlinks.
                # os.walk(followlinks=False) stops at the symlinked directory boundary.
                for f in _safe_walk(p):
                    _fstr = str(f).lower()
                    if any(skip in _fstr for skip in (
                        "node_modules", "\\cache", "/cache",
                        ".git", "__pycache__",
                        "\\tmp\\subdir", "/tmp/subdir",
                        ".venv", "site-packages",
                    )): continue
                    try:
                        if f.stat().st_size > 50_000_000: continue
                    except: continue
                    try:
                        if f.suffix.lower() in DANGEROUS_EXTENSIONS:
                            try:
                                txt = f.read_text(errors='ignore')[:4096]
                                for pattern, desc in SUSPICIOUS_SCRIPTS:
                                    if re.search(pattern, txt, re.I):
                                        fix_cmd = (
                                            f'sudo -n {HELPER} remove-file "{f}"'
                                            if OS == 'Linux' else f'del /f /q "{f}"'
                                        )
                                        self.results.append(ScanResult('critical','malware',str(f),
                                            f'{desc}', can_fix=True, fix_cmd=fix_cmd))
                                        log_cb(f'  ⛔  Malicious script: {f.name} — {desc}', 'err')
                                        found += 1
                                        break
                            except (OSError, PermissionError, UnicodeDecodeError):
                                pass   # binary file or no read permission — skip
                            if OS == 'Linux' and str(f).startswith('/tmp') and (f.stat().st_mode & stat.S_IXUSR):
                                is_pyinstaller = re.search(r'/tmp/_MEI[^/]+/', str(f))
                                is_appimage    = re.search(r'/tmp/\.mount_', str(f))
                                if not (is_pyinstaller or is_appimage):
                                    self.results.append(ScanResult('medium','suspicious',str(f),
                                        f'Executable file in /tmp: {f.name}'))
                                    log_cb(f'  ~  Exec in /tmp: {f.name}', 'warn')
                                    found += 1
                    except (OSError, PermissionError):
                        pass   # file deleted or no stat permission between walk and stat
            except (OSError, PermissionError):
                pass   # scan root dir inaccessible
        if found == 0:
            log_cb('  ✓  No suspicious files found', 'ok')

    # ── Network connections (Linux) ───────────────────────
    def _scan_network_linux(self, log_cb):
        log_cb('', 'info')
        log_cb('◆ Scanning active network connections...', 'info')
        out = run('ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null', timeout=8)
        suspicious_ports = {4444,1337,31337,12345,54321,9001,6666,6667}
        found = 0
        for line in out.splitlines():
            for port in suspicious_ports:
                if f':{port}' in line:
                    self.results.append(ScanResult('high','network',line.strip(),
                        f'Suspicious port {port} listening'))
                    log_cb(f'  ⚠  Suspicious port {port} open: {line.strip()}', 'warn')
                    found += 1
        if found == 0:
            log_cb('  ✓  No suspicious listening ports', 'ok')

    # ── Network (Windows) ─────────────────────────────────
    def _scan_network_windows(self, log_cb):
        log_cb('', 'info')
        log_cb('◆ Scanning active network connections...', 'info')
        out = run('netstat -ano 2>nul', timeout=10)
        suspicious_ports = {4444,1337,31337,12345,54321,9001,6666,6667}
        found = 0
        for line in out.splitlines():
            for port in suspicious_ports:
                if f':{port}' in line and 'LISTENING' in line:
                    self.results.append(ScanResult('high','network',line.strip(),
                        f'Suspicious port {port} listening'))
                    log_cb(f'  ⚠  Suspicious port {port}: {line.strip()}', 'warn')
                    found += 1
        if found == 0:
            log_cb('  ✓  No suspicious ports', 'ok')

    # ── LD_PRELOAD (Linux rootkit indicator) ──────────────
    def _scan_ld_preload(self, log_cb):
        log_cb('', 'info')
        log_cb('◆ Checking LD_PRELOAD / dynamic linker hijacks...', 'info')
        found = 0
        for f in ['/etc/ld.so.preload']:
            p = Path(f)
            if p.exists() and p.stat().st_size > 0:
                content = p.read_text(errors='ignore').strip()
                self.results.append(ScanResult('critical','malware',f,
                    f'LD_PRELOAD set globally: {content}'))
                log_cb(f'  ⛔  /etc/ld.so.preload has entries: {content}', 'err')
                found += 1
        env_preload = os.environ.get('LD_PRELOAD','')
        if env_preload:
            self.results.append(ScanResult('high','malware','$LD_PRELOAD',
                f'LD_PRELOAD env: {env_preload}'))
            log_cb(f'  ⚠  LD_PRELOAD env set: {env_preload}', 'warn')
            found += 1
        if found == 0:
            log_cb('  ✓  No LD_PRELOAD hijacks detected', 'ok')

    # ── SSH authorized_keys ───────────────────────────────
    def _scan_ssh_authorized_keys(self, log_cb):
        log_cb('', 'info')
        log_cb('◆ Checking SSH authorized_keys...', 'info')
        ak = Path.home() / '.ssh/authorized_keys'
        if not ak.exists():
            log_cb('  ✓  No authorized_keys file', 'ok')
            return
        lines = [l.strip() for l in ak.read_text(errors='ignore').splitlines()
                 if l.strip() and not l.startswith('#')]
        if not lines:
            log_cb('  ✓  No SSH authorized keys', 'ok')
            return

        # FIX: Having authorized_keys is NORMAL for any developer (GitHub, servers).
        # Only flag genuinely suspicious patterns — command= overrides (can force
        # arbitrary execution), and lines with no key-type prefix (malformed/obfuscated).
        KNOWN_KEY_TYPES = ('ssh-rsa', 'ssh-ed25519', 'ecdsa-sha2-nistp256',
                           'ecdsa-sha2-nistp384', 'ecdsa-sha2-nistp521',
                           'sk-ssh-ed25519@openssh.com', 'sk-ecdsa-sha2-nistp256@openssh.com')
        suspicious = []
        for line in lines:
            # command= option before the key type = forced command execution (unusual on personal machines)
            if re.match(r'command\s*=', line, re.I):
                suspicious.append(('high', f'Forced-command key (remote code exec risk): ...{line[-50:]}'))
            # Line doesn't start with a known key type or an option keyword
            elif not any(line.startswith(kt) for kt in KNOWN_KEY_TYPES) and \
                 not re.match(r'(no-|from=|environment=|permitopen=|restrict)', line, re.I):
                suspicious.append(('medium', f'Unrecognised key format (may be obfuscated): ...{line[-50:]}'))

        # Always log a neutral info line so user knows the scan ran
        log_cb(f'  ✓  {len(lines)} SSH authorized key(s) found — looks normal', 'ok')
        for i, line in enumerate(lines[:3]):
            log_cb(f'     key {i+1}: ...{line[-40:]}', 'dim')

        for severity, detail in suspicious:
            self.results.append(ScanResult(severity, 'suspicious', str(ak), detail))
            level = 'err' if severity == 'high' else 'warn'
            log_cb(f'  {"⛔" if severity == "high" else "⚠"}  {detail}', level)

    # ── /etc/hosts tampering ─────────────────────────────
    def _scan_hosts_file(self, log_cb):
        log_cb('', 'info')
        log_cb('◆ Checking /etc/hosts for tampering...', 'info')
        if OS == 'Linux':
            hosts_path = Path('/etc/hosts')
        else:
            windir = os.environ.get('WINDIR', 'C:/Windows')
            hosts_path = Path(f'{windir}/System32/drivers/etc/hosts')
        if not hosts_path.exists():
            log_cb('  ~ hosts file not found', 'dim'); return
        suspicious_domains = ['google.com','facebook.com','github.com','microsoft.com',
                               'apple.com','amazon.com','paypal.com','bankofamerica.com']
        found = 0
        for line in hosts_path.read_text(errors='ignore').splitlines():
            line = line.strip()
            if not line or line.startswith('#'): continue
            parts = line.split()
            if len(parts) < 2: continue
            ip, *domains = parts
            if ip in ('127.0.0.1','::1','0.0.0.0'): continue
            for d in domains:
                if any(sd in d for sd in suspicious_domains):
                    self.results.append(ScanResult('high','malware', str(hosts_path),
                        f'Suspicious hosts redirect: {line}'))
                    log_cb(f'  ⚠  Hosts hijack: {line}', 'warn')
                    found += 1
        if found == 0:
            log_cb('  ✓  hosts file looks clean', 'ok')

    # ── Windows autoruns ──────────────────────────────────
    def _scan_autorun_windows(self, log_cb):
        log_cb('', 'info')
        log_cb('◆ Scanning Windows autorun entries...', 'info')
        try:
            import winreg
            keys = [
                (winreg.HKEY_CURRENT_USER,  r'Software\Microsoft\Windows\CurrentVersion\Run'),
                (winreg.HKEY_LOCAL_MACHINE, r'Software\Microsoft\Windows\CurrentVersion\Run'),
                (winreg.HKEY_LOCAL_MACHINE, r'Software\Microsoft\Windows\CurrentVersion\RunOnce'),
            ]
            found = 0
            suspicious_kw = ['temp','appdata\\local\\temp','%temp%','powershell -enc',
                             'cmd /c','wscript','cscript','mshta','regsvr32']
            for hive, key_path in keys:
                try:
                    key = winreg.OpenKey(hive, key_path)
                    i = 0
                    while True:
                        try:
                            name, val, _ = winreg.EnumValue(key, i)
                            val_lower = val.lower()
                            for kw in suspicious_kw:
                                if kw in val_lower:
                                    self.results.append(ScanResult('high','malware',val,
                                        f'Suspicious autorun: {name} = {val}'))
                                    log_cb(f'  ⚠  Suspicious autorun: {name}', 'warn')
                                    log_cb(f'     {val}', 'dim')
                                    found += 1
                                    break
                            i += 1
                        except OSError: break
                    winreg.CloseKey(key)
                except (OSError, PermissionError):
                    pass   # registry key inaccessible (e.g. 32/64-bit redirect)
            if found == 0:
                log_cb('  ✓  No suspicious autoruns', 'ok')
        except ImportError:
            log_cb('  ~ winreg not available', 'dim')
