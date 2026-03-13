"""
CyberClean v2.0 — Security Scanner
Quét malware, suspicious files, SUID/SGID, world-writable, cron backdoors.
Cross-platform: Linux + Windows
KHÔNG tự xóa — chỉ báo cáo để người dùng quyết định.
"""
import os, subprocess, hashlib, platform, stat, re
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Callable

OS     = platform.system()
HELPER = '/usr/local/bin/cyber-clean-helper'

def _h(action: str, target: str = '') -> str:
    """Build sudo -n helper command. Never prompts password."""
    if target:
        return f'sudo -n {HELPER} {action} "{target}"'
    return f'sudo -n {HELPER} {action}'

@dataclass
class ScanResult:
    severity:  str       # 'critical' | 'high' | 'medium' | 'info'
    category:  str       # 'malware' | 'suspicious' | 'suid' | 'writable' | 'cron' | 'network'
    path:      str
    detail:    str
    can_fix:   bool = False
    fix_cmd:   str  = ''

def run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except: return ''

# ── Suspicious patterns ───────────────────────────────────────
SUSPICIOUS_SCRIPTS = [
    # Reverse shells
    (r'bash\s+-i\s+>&\s*/dev/tcp',          'Reverse bash shell'),
    (r'nc\s+-e\s+/bin/(bash|sh)',            'Netcat reverse shell'),
    (r'python.*socket.*connect.*subprocess', 'Python reverse shell'),
    # Credential harvesting
    (r'curl\s+.*\|\s*(bash|sh)',             'Remote code execution via curl|bash'),
    (r'wget\s+.*-O-\s*\|',                  'Remote code execution via wget|pipe'),
    (r'eval\s*\(\s*base64_decode',           'PHP base64 eval (webshell pattern)'),
    (r'eval\s*\(\s*gzinflate',               'PHP obfuscated eval (webshell)'),
    # Miners
    (r'(xmrig|minerd|cpuminer)',             'Crypto miner binary/reference'),
    (r'stratum\+tcp://',                     'Mining pool connection string'),
    # Rootkit indicators
    (r'LD_PRELOAD.*=',                       'LD_PRELOAD manipulation'),
    (r'/proc/\d+/mem',                       'Direct process memory access'),
]

DANGEROUS_EXTENSIONS = {'.sh', '.py', '.rb', '.pl', '.php', '.exe', '.elf', '.bin'}
SCAN_DIRS_LINUX   = ['/tmp', '/var/tmp', '/dev/shm', str(Path.home()/'.local/bin'),
                     str(Path.home()/'.config'), '/etc/cron.d', '/etc/cron.daily',
                     '/etc/cron.hourly', '/etc/cron.weekly']
SCAN_DIRS_WINDOWS = [
    os.environ.get('TEMP',''), os.environ.get('APPDATA',''),
    'C:/Windows/Temp', 'C:/ProgramData',
]

KNOWN_MINERS = {'xmrig','xmrig-notls','minerd','cpuminer-multi','nbminer',
                'teamredminer','lolminer','gminer','t-rex','nanominer'}

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

        # Summary
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

                    # Known miners
                    if name in KNOWN_MINERS:
                        r = ScanResult('critical','malware', exe or name,
                            f'Crypto miner running: {name} (PID {p.pid})',
                            can_fix=True, fix_cmd=f'sudo -n /usr/local/bin/cyber-clean-helper kill-pid {p.pid}')
                        self.results.append(r)
                        log_cb(f'  ⛔  MINER: {name} PID={p.pid}', 'err')
                        continue

                    # Process running from /tmp or /dev/shm (suspicious)
                    if exe and any(exe.startswith(d) for d in ['/tmp','/dev/shm','/var/tmp']):
                        r = ScanResult('high','suspicious', exe,
                            f'Process running from temp dir: {exe} (PID {p.pid})',
                            can_fix=True, fix_cmd=f'sudo -n /usr/local/bin/cyber-clean-helper kill-pid {p.pid}')
                        self.results.append(r)
                        log_cb(f'  ⚠  Suspicious exec from tmp: {exe}', 'warn')

                    # Reverse shell patterns in cmdline
                    for pattern, desc in SUSPICIOUS_SCRIPTS:
                        if re.search(pattern, cmd, re.I):
                            r = ScanResult('critical','malware', exe or name,
                                f'{desc} in process cmdline (PID {p.pid})',
                                can_fix=True, fix_cmd=f'sudo -n /usr/local/bin/cyber-clean-helper kill-pid {p.pid}')
                            self.results.append(r)
                            log_cb(f'  ⛔  {desc}: PID {p.pid}', 'err')
                            break
                except: pass
        except ImportError:
            log_cb('  ~ psutil not available — process scan skipped', 'dim')

        found = [r for r in self.results if r.category in ('malware','suspicious')]
        if not found:
            log_cb('  ✓  No malicious processes detected', 'ok')

    # ── SUID/SGID (Linux) ─────────────────────────────────
    def _scan_suid_sgid(self, log_cb):
        log_cb('', 'info')
        log_cb('◆ Scanning SUID/SGID binaries...', 'info')
        # Known legitimate SUID binaries
        known_suid = {'/usr/bin/sudo','/usr/bin/su','/usr/bin/passwd','/usr/bin/newgrp',
                      '/usr/bin/chsh','/usr/bin/chfn','/usr/bin/gpasswd','/bin/ping',
                      '/usr/bin/ping','/usr/bin/pkexec','/usr/lib/polkit-1/polkit-agent-helper-1',
                      '/usr/bin/mount','/usr/bin/umount','/usr/sbin/unix_chkpwd'}
        out = run('find /usr /bin /sbin /tmp /home -perm /4000 -type f 2>/dev/null', timeout=15)
        found = 0
        for line in out.splitlines():
            f = line.strip()
            if not f or f in known_suid: continue
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
                     '/var/spool/cron',str(Path.home()/'.local/share/cron')]
        found = 0
        for d in cron_dirs:
            p = Path(d)
            if not p.exists(): continue
            for f in p.rglob('*'):
                if not f.is_file(): continue
                try:
                    txt = f.read_text(errors='ignore')
                    for pattern, desc in SUSPICIOUS_SCRIPTS:
                        if re.search(pattern, txt, re.I):
                            self.results.append(ScanResult('critical','cron', str(f),
                                f'Suspicious cron: {desc} in {f.name}'))
                            log_cb(f'  ⛔  Cron backdoor: {desc} in {f}', 'err')
                            found += 1
                            break
                except: pass
        # User crontab
        crontab = run('crontab -l 2>/dev/null')
        for pattern, desc in SUSPICIOUS_SCRIPTS:
            if re.search(pattern, crontab, re.I):
                self.results.append(ScanResult('critical','cron','crontab',
                    f'Suspicious user crontab: {desc}'))
                log_cb(f'  ⛔  Cron backdoor in user crontab: {desc}', 'err')
                found += 1
        if found == 0:
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
                for f in p.rglob('*'):
                    if not f.is_file(): continue
                    if f.stat().st_size > 50_000_000: continue  # skip large files
                    try:
                        # Check extension
                        if f.suffix.lower() in DANGEROUS_EXTENSIONS:
                            # Check executable bit
                            if OS == 'Linux' and (f.stat().st_mode & stat.S_IXUSR):
                                # Scan content
                                txt = f.read_text(errors='ignore')[:4096]
                                for pattern, desc in SUSPICIOUS_SCRIPTS:
                                    if re.search(pattern, txt, re.I):
                                        self.results.append(ScanResult('critical','malware',str(f),
                                            f'{desc}', can_fix=True, fix_cmd=f'sudo -n {HELPER} remove-file "{f}"'))
                                        log_cb(f'  ⛔  Malicious script: {f.name} — {desc}', 'err')
                                        found += 1
                                        break
                            # Executable in /tmp is suspicious even without bad content
                            if OS == 'Linux' and str(f).startswith('/tmp'):
                                self.results.append(ScanResult('medium','suspicious',str(f),
                                    f'Executable file in /tmp: {f.name}'))
                                log_cb(f'  ~  Exec in /tmp: {f.name}', 'warn')
                                found += 1
                    except: pass
            except: pass
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
        if lines:
            self.results.append(ScanResult('medium','suspicious',str(ak),
                f'{len(lines)} SSH authorized key(s) — review if unexpected'))
            log_cb(f'  ~  {len(lines)} SSH authorized key(s) in ~/.ssh/authorized_keys', 'warn')
            for i, line in enumerate(lines[:3]):
                log_cb(f'     key {i+1}: ...{line[-40:]}', 'dim')
        else:
            log_cb('  ✓  No SSH authorized keys', 'ok')

    # ── /etc/hosts tampering ─────────────────────────────
    def _scan_hosts_file(self, log_cb):
        log_cb('', 'info')
        log_cb('◆ Checking /etc/hosts for tampering...', 'info')
        if OS == 'Linux':
            hosts_path = Path('/etc/hosts')
        else:
            hosts_path = Path('C:/Windows/System32/drivers/etc/hosts')
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
            if ip in ('127.0.0.1','::1','0.0.0.0'): continue  # localhost entries OK
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
                except: pass
            if found == 0:
                log_cb('  ✓  No suspicious autoruns', 'ok')
        except ImportError:
            log_cb('  ~ winreg not available', 'dim')
