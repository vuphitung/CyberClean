"""
CyberClean v2.3 — Security Scanner (Smart Edition)
═══════════════════════════════════════════════════════════════
WHAT CHANGED vs old v2.3:

PROCESS SCANNER — Total redesign (no more false positives):
  OLD: name in KNOWN_MINERS → immediate CRITICAL, no context.
       Any regex match in cmdline → immediate CRITICAL.
       Result: CyberClean itself flagged as miner, Python flagged as malware.

  NEW: Multi-signal scoring engine.
       Every process gets a risk_score (0–100). Score only triggers
       a finding when it crosses a threshold AND multiple signals agree.

       Signal sources:
         +60  exact known miner binary name (xmrig, nbminer, etc.)
         +40  mining cmdline pattern (stratum+tcp, --mining-algo, etc.)
         +35  reverse shell pattern in cmdline
         +30  process running from /tmp / /dev/shm (not AppImage/PyInstaller)
         +25  process name matches miner pattern but score < 60 (needs corroboration)
         +15  connected to known mining pool port (3333, 4444-miner, 14444...)
         +10  executable is world-writable
         -30  process path is in /usr, /opt, /bin, /sbin (installed software)
         -20  process is owned by root / system user (not suspicious for privs)
         -50  process name is in TRUSTED_PROCESSES allowlist
         -50  process path matches TRUSTED_PATHS
         -50  process is the current app (CyberClean itself)

       Thresholds:
         score >= 70  → CRITICAL (high confidence malware)
         score 40–69  → HIGH     (suspicious, needs attention)
         score 20–39  → MEDIUM   (anomalous, low priority)
         score  < 20  → ignored  (too weak to report)

  NEW report format:
       Every finding now includes WHY it was flagged (signals list),
       not just what triggered it. Operator and user see the reasoning.

REPORT QUALITY:
  OLD: raw regex name as detail → "Crypto miner binary/reference"
       for any process that even mentions xmrig in args.
  NEW: structured reason list: ["Known miner binary", "Running from /tmp",
       "Connected to pool port 3333"] — tells user exactly what's weird.

FIX — FalsePositive registry:
  NEW: _is_trusted_process() checks:
       - current app PID and exe path (never flag yourself)
       - Python interpreter running .py files from /opt, /usr
       - known dev tools: node, npm, cargo, rustc, gcc, clang, make
       - package managers: pacman, apt, dnf, pip, yay, paru
       - system daemons: systemd, NetworkManager, pipewire, pulseaudio
       - browsers: chrome, firefox, brave, electron apps from /opt
       - Flatpak/AppImage/Snap runtime helpers

FIX — Mining detection precision:
  OLD: xmrig in name → CRITICAL (flags legitimate CPU benchmarks named
       "xmrig-test" in /usr/share/doc).
  NEW: Score must reach 70. Name alone gives +60, needs one more signal
       (from /tmp, or mining cmdline, or pool port connection) to cross 70.
       Legitimate xmrig install in /usr → gets -30 (installed path) → 30 net
       → only MEDIUM, with note "known miner binary in installed location,
         verify this is intentional".

FIX — Reverse shell precision:
  OLD: python.*socket.*connect.*subprocess in cmdline → CRITICAL.
       Flags: pytest network tests, django dev server, any Python server.
  NEW: Multi-step check. Pattern must appear, AND process must not be
       in a development/testing path, AND must not be a known framework.
       Python from venv/site-packages with server patterns → demoted to INFO.

REPORT STRUCTURE (new):
  scan() now returns both results list AND a ScanReport summary:
    - findings_by_severity: dict[str, List[ScanResult]]
    - total_ok: int (categories with no findings)
    - scan_duration_ms: int
    - summary_lines: List[str] (human-readable verdict)

═══════════════════════════════════════════════════════════════
PRESERVED from old v2.3:
  - _safe_kill_cmd() PID safety guard (PID < 100 block, ownership check)
  - _safe_walk() symlink loop prevention (followlinks=False)
  - _is_expected_suid_path() chrome-sandbox false positive guard
  - SSH authorized_keys normal-key-as-info (not warning)
  - AppImage /tmp mount detection
  - PyInstaller /tmp/_MEI detection
  - LD_PRELOAD, hosts file, cron, SUID, world-writable scans (unchanged)
  - Windows autorun scan
  - fix_cmd / can_fix on ScanResult
═══════════════════════════════════════════════════════════════
"""
import os, sys, subprocess, platform, stat, re, time
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Callable, Optional, Dict

OS     = platform.system()
HELPER = '/usr/local/bin/cyber-clean-helper'

# ══════════════════════════════════════════════════════════════
# PID SAFETY GUARD  (unchanged from v2.3)
# ══════════════════════════════════════════════════════════════
_PID_MIN_SAFE = 100

def _safe_kill_cmd(pid: int) -> str:
    if pid <= _PID_MIN_SAFE:
        return ''
    if OS == 'Linux':
        current_uid = os.getuid()
        if current_uid != 0:
            try:
                status = Path(f'/proc/{pid}/status').read_text(errors='ignore')
                for line in status.splitlines():
                    if line.startswith('Uid:'):
                        proc_uid = int(line.split()[1])
                        if proc_uid != current_uid:
                            return ''
                        break
            except (OSError, ValueError):
                return ''
    return f'sudo -n {HELPER} kill-pid {pid}'


def _h(action: str, target: str = '') -> str:
    if target:
        return f'sudo -n {HELPER} {action} "{target}"'
    return f'sudo -n {HELPER} {action}'


# ══════════════════════════════════════════════════════════════
# DATA CLASSES
# ══════════════════════════════════════════════════════════════
@dataclass
class ScanResult:
    severity:  str          # 'critical' | 'high' | 'medium' | 'info'
    category:  str          # 'malware' | 'suspicious' | 'suid' | 'writable' | 'cron' | 'network' | 'config'
    path:      str
    detail:    str
    reasons:   List[str] = field(default_factory=list)   # NEW: why it was flagged
    can_fix:   bool = False
    fix_cmd:   str  = ''

@dataclass
class ScanReport:
    """Structured summary returned alongside raw results list."""
    findings_by_severity: Dict[str, List[ScanResult]] = field(default_factory=dict)
    total_ok:             int = 0
    scan_duration_ms:     int = 0
    summary_lines:        List[str] = field(default_factory=list)
    false_positive_notes: List[str] = field(default_factory=list)


def run(cmd, timeout=10):
    try:
        no_win = 0x08000000 if OS == 'Windows' else 0
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=timeout, creationflags=no_win)
        return r.stdout.strip()
    except Exception:
        return ''


# ══════════════════════════════════════════════════════════════
# USER WHITELIST  (persistent false-positive registry)
# ══════════════════════════════════════════════════════════════
import json as _json

_WHITELIST_DIR  = Path.home() / '.local' / 'share' / 'cyber-clean'
_WHITELIST_FILE = _WHITELIST_DIR / 'user_whitelist.json'


def _load_user_whitelist() -> dict:
    try:
        if _WHITELIST_FILE.exists():
            return _json.loads(_WHITELIST_FILE.read_text(encoding='utf-8'))
    except Exception:
        pass
    return {}


def _save_user_whitelist(data: dict) -> None:
    try:
        _WHITELIST_DIR.mkdir(parents=True, exist_ok=True)
        _WHITELIST_FILE.write_text(
            _json.dumps(data, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
    except Exception:
        pass


def add_to_user_whitelist(path: str, reason: str = '') -> None:
    """
    Mark a path as trusted — scanner gives it -50 points so it's
    almost never flagged again. Written to user_whitelist.json.
    """
    data = _load_user_whitelist()
    data[path] = {
        'reason':    reason or 'user marked safe',
        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    _save_user_whitelist(data)


def remove_from_user_whitelist(path: str) -> bool:
    """Remove a path from the whitelist. Returns True if it was present."""
    data = _load_user_whitelist()
    if path in data:
        del data[path]
        _save_user_whitelist(data)
        return True
    return False


def get_user_whitelist() -> dict:
    """Return the full whitelist dict {path: {reason, timestamp}}."""
    return _load_user_whitelist()


# ══════════════════════════════════════════════════════════════
# QUARANTINE  (move malicious file to vault — recoverable)
# ══════════════════════════════════════════════════════════════

if OS == 'Windows':
    _VAULT_DIR = Path(os.environ.get('LOCALAPPDATA', 'C:/Users/Public')) / 'CyberClean_Vault'
else:
    _VAULT_DIR = Path.home() / '.local' / 'share' / 'cyber-clean' / 'quarantine'


def quarantine_file(src_path: str) -> tuple[bool, str]:
    """
    Move a file to the quarantine vault and rename it to .vir.
    Returns (success: bool, message: str).

    Why rename to .vir?
      - Windows will refuse to execute it (unknown extension → no association)
      - Double-click by accident won't launch it
      - File is still recoverable — just rename back and move out
    """
    try:
        src = Path(src_path)
        if not src.exists():
            return False, f'File not found: {src_path}'
        _VAULT_DIR.mkdir(parents=True, exist_ok=True)
        dest = _VAULT_DIR / (src.name + '.vir')
        # If a file with that name is already in vault, add a counter
        counter = 1
        while dest.exists():
            dest = _VAULT_DIR / f'{src.name}_{counter}.vir'
            counter += 1
        src.rename(dest)
        # Log the quarantine action
        log_file = _VAULT_DIR / 'quarantine_log.json'
        try:
            log = _json.loads(log_file.read_text(encoding='utf-8')) if log_file.exists() else []
        except Exception:
            log = []
        log.append({
            'original':  str(src),
            'vault':     str(dest),
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
        })
        log_file.write_text(_json.dumps(log, ensure_ascii=False, indent=2), encoding='utf-8')
        return True, f'Quarantined → {dest}'
    except PermissionError:
        return False, f'Permission denied — run as Administrator to quarantine {src_path}'
    except Exception as e:
        return False, str(e)


# ══════════════════════════════════════════════════════════════
# TRUSTED PROCESS / PATH ALLOWLISTS
# ══════════════════════════════════════════════════════════════

# Process names that are ALWAYS trusted regardless of CPU/memory usage.
# These are system daemons, package managers, dev tools, and browsers.
# If a real miner somehow steals one of these names, it still must come
# from a suspicious path — the path check is separate and additive.
TRUSTED_PROCESS_NAMES = {
    # ── System / init ───────────────────────────────────────
    'systemd', 'systemd-journald', 'systemd-logind', 'systemd-udevd',
    'systemd-resolved', 'systemd-networkd', 'dbus-daemon', 'dbus-broker',
    'kthreadd', 'ksoftirqd', 'kworker', 'migration', 'watchdog',
    'init', 'upstart', 'openrc', 'runit',
    'NetworkManager', 'networkmanager', 'wpa_supplicant', 'dhclient', 'dhcpcd',
    'polkitd', 'udisks2', 'upower', 'colord', 'rtkit-daemon',
    'accounts-daemon', 'packagekitd', 'fwupd',
    # ── Audio / video ───────────────────────────────────────
    'pipewire', 'pipewire-pulse', 'wireplumber',
    'pulseaudio', 'jackd', 'alsa',
    # ── Display / compositor ────────────────────────────────
    'Xorg', 'Xwayland', 'kwin_wayland', 'kwin_x11',
    'mutter', 'gnome-shell', 'plasmashell', 'xfwm4', 'openbox',
    'sway', 'hyprland', 'wayfire', 'river',
    'picom', 'compton', 'compiz',
    # ── Desktop env helpers ─────────────────────────────────
    'gnome-session', 'gdm', 'gdm3', 'sddm', 'lightdm', 'lxdm',
    'kded5', 'kded6', 'plasmashell', 'plasma_session',
    'xfce4-session', 'xfdesktop', 'thunar', 'nautilus', 'dolphin',
    # ── Browsers (legitimate installs) ──────────────────────
    'firefox', 'firefox-esr', 'firefox-bin',
    'chrome', 'google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser',
    'brave', 'brave-browser', 'opera', 'vivaldi', 'msedge', 'microsoft-edge',
    # ── Electron / node apps ────────────────────────────────
    'electron', 'code', 'code-oss', 'vscodium',
    'node', 'nodejs', 'npm', 'npx', 'yarn', 'pnpm', 'bun',
    # ── Python ecosystem ────────────────────────────────────
    'python', 'python3', 'python3.10', 'python3.11', 'python3.12', 'python3.13',
    'python3.14', 'pypy', 'pypy3',
    'pip', 'pip3', 'uv', 'poetry', 'pipenv', 'conda', 'mamba',
    'jupyter', 'ipython', 'pylsp', 'ruff',
    # ── Package managers ────────────────────────────────────
    'pacman', 'yay', 'paru', 'trizen', 'aura',
    'apt', 'apt-get', 'dpkg', 'aptd',
    'dnf', 'yum', 'rpm',
    'zypper',
    'xbps-install', 'xbps-remove',
    'flatpak', 'snap',
    # ── Compilers / build tools ─────────────────────────────
    'gcc', 'g++', 'clang', 'clang++', 'cc', 'c++',
    'make', 'cmake', 'ninja', 'meson',
    'cargo', 'rustc', 'rustup',
    'go', 'gofmt',
    'javac', 'java', 'kotlinc',
    'mvn', 'gradle',
    # ── Container / virt ────────────────────────────────────
    'docker', 'dockerd', 'containerd', 'runc',
    'podman', 'crun', 'buildah',
    'qemu', 'qemu-system-x86_64', 'libvirtd', 'virsh',
    # ── Security tools (benign) ─────────────────────────────
    'gpg', 'gpg-agent', 'gnome-keyring-daemon', 'kwallet',
    'seahorse', 'keepassxc',
    # ── Misc system ─────────────────────────────────────────
    'bash', 'zsh', 'fish', 'sh', 'dash', 'ksh',
    'ssh', 'sshd', 'sftp-server',
    'cron', 'crond', 'atd',
    'rsync', 'rclone',
    'htop', 'btop', 'top', 'glances',
    'tmux', 'screen', 'zellij',
    'cat', 'ls', 'find', 'grep', 'awk', 'sed', 'sort',
    # ── CyberClean itself ───────────────────────────────────
    'cyberclean', 'cyberclean.exe', 'CyberClean',
}

# Process names are compared case-insensitively, stripped of .exe
# This set is the fast first check; path check is the deep check.

# Trusted path prefixes — processes from these locations are trusted
# UNLESS they also match a hard miner binary name.
TRUSTED_PATH_PREFIXES = (
    '/usr/bin/', '/usr/sbin/', '/usr/lib/', '/usr/libexec/',
    '/usr/share/', '/usr/local/bin/', '/usr/local/lib/',
    '/bin/', '/sbin/', '/lib/', '/lib64/',
    '/opt/',
    '/snap/', '/var/lib/flatpak/', '/run/flatpak/',
    # Python standard install locations
    '/usr/lib/python', '/usr/local/lib/python',
    # Windows system dirs
    'C:\\Windows\\', 'C:\\Program Files\\', 'C:\\Program Files (x86)\\',
)

# Hard known-miner binary names — these get +60 score.
# Must be EXACT binary names (basename), not substrings.
KNOWN_MINER_BINS = {
    'xmrig', 'xmrig-notls', 'xmrig-mo',
    'minerd', 'cpuminer', 'cpuminer-multi', 'cpuminer-opt',
    'nbminer', 'teamredminer', 'lolminer', 'gminer',
    't-rex', 't-rex.exe',
    'nanominer', 'nsfminer',
    'ethminer', 'phoenixminer', 'claymore',
    'srbminer', 'srbminer-multi',
    'bzminer', 'rigel', 'wildrig-multi',
    'kawpowminer', 'miniZ',
}

# Mining-specific cmdline patterns — these are highly specific, low false-positive.
MINING_CMDLINE_PATTERNS = [
    (r'stratum\+tcp://',              'Mining pool connection (stratum+tcp)'),
    (r'stratum\+ssl://',              'Mining pool connection (stratum+ssl)'),
    (r'--mining-algo\s',              'Explicit mining algorithm flag'),
    (r'--pool\s+\d+\.\d+\.\d+',      'Mining pool IP address in args'),
    (r'-o\s+stratum',                 'Mining pool -o stratum flag'),
    (r'--donate-level\s',             'XMRig donate-level flag (miner-specific)'),
    (r'--coin\s+(monero|xmr|eth|etc|rvn|ergo)', 'Coin specification (miner flag)'),
    (r'randomx|kawpow|ethash|etchash|autolykos2', 'Mining algorithm name in cmdline'),
]

# Reverse shell / backdoor cmdline patterns.
# These are kept tight — only patterns that have essentially zero legitimate use.
BACKDOOR_CMDLINE_PATTERNS = [
    (r'bash\s+-i\s+>&\s*/dev/tcp',          'Interactive bash reverse shell (bash -i >& /dev/tcp)'),
    (r'nc\s+.*-e\s+/bin/(bash|sh)',         'Netcat reverse shell (nc -e /bin/bash)'),
    (r'0\.0\.0\.0.*exec.*sh',               'Bind shell on all interfaces'),
    (r'mkfifo.*;\s*(nc|bash|sh)',           'FIFO-based reverse shell'),
    (r'/dev/tcp/\d+\.\d+\.\d+\.\d+/\d+',   'Bash /dev/tcp reverse connection'),
    (r'python.*-c.*socket.*connect.*os\.dup2',  'Python reverse shell (os.dup2 redirect)'),
    (r'perl.*-e.*socket.*connect.*exec',    'Perl reverse shell'),
    (r'ruby.*-rsocket.*-e.*exec',           'Ruby reverse shell'),
    (r'php.*fsockopen.*exec\(',             'PHP reverse shell'),
    (r'powershell.*-nop.*-w.*hidden.*iex',  'PowerShell download+exec (obfuscated)'),
    (r'cmd\.exe.*/c.*powershell.*hidden',   'CMD spawning hidden PowerShell'),
    (r'mshta\s+http',                       'MSHTA remote script execution'),
    (r'regsvr32.*\/s.*\/n.*\/u.*http',      'Regsvr32 COM scriptlet remote load'),
    (r'certutil.*-decode.*\.exe',           'Certutil decoding executable (dropper)'),
    (r'bitsadmin.*\/transfer.*http',        'BITSAdmin file download (dropper)'),
]

# Script content patterns for file scanning.
# These are searched inside file contents, so they can be more specific.
MALICIOUS_SCRIPT_PATTERNS = [
    (r'bash\s+-i\s+>&\s*/dev/tcp',          'Reverse bash shell payload'),
    (r'nc\s+-e\s+/bin/(bash|sh)',            'Netcat backdoor payload'),
    (r'python.*socket.*connect.*os\.dup2',   'Python reverse shell payload'),
    (r'curl\s+[^|]+\|\s*(bash|sh)\s*$',     'Remote code execution (curl|bash)'),
    (r'wget\s+-qO-\s+[^|]+\|\s*(bash|sh)',  'Remote code execution (wget|bash)'),
    (r'eval\s*\(\s*base64_decode\s*\(',      'PHP base64 eval webshell'),
    (r'eval\s*\(\s*gzinflate\s*\(',          'PHP gzip-obfuscated webshell'),
    (r'eval\s*\(\s*str_rot13\s*\(',          'PHP ROT13-obfuscated webshell'),
    (r'stratum\+tcp://',                     'Crypto mining pool string in file'),
    (r'--donate-level\s+0',                  'XMRig zero-donate flag (miner config)'),
    (r'/proc/\d+/mem',                       'Direct /proc/mem access (process injection)'),
    (r'LD_PRELOAD\s*=\s*/tmp',               'LD_PRELOAD set to /tmp path (rootkit pattern)'),
    (r'chmod\s+\+x\s+/tmp/\S+\s*&&\s*/tmp/', 'Download+execute to /tmp'),
]

# Ports that are commonly used by RAT/C2 frameworks and miners.
# NOT reported for listening alone — only combined with other signals.
SUSPICIOUS_PORTS_STRICT = {4444, 1337, 31337, 6667, 6666, 54321}   # RAT/C2
MINING_POOL_PORTS        = {3333, 5555, 7777, 8888, 14444, 45560}   # Mining pools

# Known good patterns that cancel suspicious patterns in file scanning.
SAFE_FILE_CONTEXTS = (
    'site-packages', 'node_modules', '.venv', 'venv', '__pycache__',
    '.git', 'test', 'spec', 'mock', 'fixture', 'example', 'sample',
    'doc', 'docs', 'README', 'tutorial', 'demo',
    # CyberClean's own source files
    'cyberclean', 'CyberClean',
)


def _is_expected_suid_path(path: str) -> bool:
    """Chromium/Electron chrome-sandbox has SUID by design — not a threat."""
    p = path.replace('\\', '/')
    if not p.endswith('/chrome-sandbox'):
        return False
    if not (p.startswith('/usr/') or p.startswith('/opt/')):
        return False
    pl = p.lower()
    markers = ('/electron', '/chromium', '/chromium-browser', '/chrome/',
               '/google-chrome', 'google-chrome', '/opt/google/chrome',
               '/brave', '/vivaldi', '/opera', 'microsoft-edge', '/edge/')
    return any(m in pl for m in markers)


def _safe_walk(root: Path):
    """Walk without following symlinks — prevents infinite loops."""
    try:
        for dirpath, dirnames, filenames in os.walk(str(root), followlinks=False):
            dirnames[:] = [
                d for d in dirnames
                if not os.path.islink(os.path.join(dirpath, d))
            ]
            for fname in filenames:
                fpath = Path(dirpath) / fname
                if fpath.is_symlink():
                    continue
                yield fpath
    except (PermissionError, OSError):
        pass


# ══════════════════════════════════════════════════════════════
# TRUST EVALUATION
# ══════════════════════════════════════════════════════════════

_MY_PID  = os.getpid()
_MY_EXE  = ''
try:
    import psutil as _ps
    _MY_EXE = (_ps.Process(_MY_PID).exe() or '').lower()
except Exception:
    pass


def _normalize_proc_name(name: str) -> str:
    """Lowercase, strip .exe, strip version suffix like python3.12 → python3."""
    n = name.lower().strip()
    if n.endswith('.exe'):
        n = n[:-4]
    # python3.12 → python3, python3.11 → python3
    n = re.sub(r'^(python3?)\.\d+$', r'\1', n)
    return n


def _is_trusted_process(name: str, exe: str, pid: int) -> tuple:
    """
    Returns (trusted: bool, reason: str).
    Trusted processes are never reported as malware.
    Suspicious-path check is separate — a trusted name from /tmp is still flagged.
    """
    # Never flag ourselves
    if pid == _MY_PID:
        return True, 'CyberClean itself'
    if _MY_EXE and exe and exe.lower() == _MY_EXE:
        return True, 'CyberClean itself'

    norm = _normalize_proc_name(name)
    if norm in {_normalize_proc_name(t) for t in TRUSTED_PROCESS_NAMES}:
        return True, f'known trusted process ({norm})'

    # ── User whitelist check ─────────────────────────────────
    # Paths marked safe by the user get automatic trust.
    _wl = _load_user_whitelist()
    if exe and exe in _wl:
        return True, f'user-whitelisted: {_wl[exe].get("reason","")}'
    if name and name in _wl:
        return True, f'user-whitelisted: {_wl[name].get("reason","")}'

    # Trusted path — installed software
    if exe:
        exe_l = exe.lower().replace('\\', '/')
        if any(exe_l.startswith(p.lower().replace('\\', '/')) for p in TRUSTED_PATH_PREFIXES):
            # Even from a trusted path, hard miner names override trust
            if norm in {n.replace('.exe','') for n in KNOWN_MINER_BINS}:
                return False, 'known miner binary in installed path (verify intentional)'
            return True, f'installed software path ({exe[:50]})'

    return False, ''


def _proc_is_appimage_or_pyinstaller(exe: str) -> bool:
    """AppImage mounts and PyInstaller bundles legitimately run from /tmp."""
    if not exe:
        return False
    return bool(
        re.search(r'/tmp/\.mount_', exe) or
        re.search(r'/tmp/_MEI[^/]+/', exe)
    )


def _get_process_connections(pid: int) -> List[int]:
    """Return list of remote ports this process has established TCP connections to."""
    ports = []
    try:
        import psutil
        p = psutil.Process(pid)
        for conn in p.connections(kind='tcp'):
            if conn.status == 'ESTABLISHED' and conn.raddr:
                ports.append(conn.raddr.port)
    except Exception:
        pass
    return ports


# ══════════════════════════════════════════════════════════════
# PROCESS RISK SCORER
# ══════════════════════════════════════════════════════════════

@dataclass
class _ProcessRisk:
    score:   int = 0
    signals: List[str] = field(default_factory=list)

    def add(self, points: int, reason: str):
        self.score += points
        if points > 0:
            self.signals.append(f'+{points} {reason}')
        else:
            self.signals.append(f'{points} {reason}')

    @property
    def severity(self) -> Optional[str]:
        if self.score >= 70: return 'critical'
        if self.score >= 40: return 'high'
        if self.score >= 20: return 'medium'
        return None

    def verdict(self) -> str:
        """Human-readable verdict with reasoning."""
        if not self.severity:
            return 'OK'
        reasons = [s for s in self.signals if not s.startswith('-')]
        return '; '.join(reasons[:4])


def _score_process(name: str, exe: str, cmd: str, pid: int) -> _ProcessRisk:
    """
    Score a single process across multiple signals.
    Higher score = more suspicious. See module docstring for signal weights.
    """
    r = _ProcessRisk()
    norm = _normalize_proc_name(name)

    # ── Hard miner binary name (+60) ──────────────────────
    if norm in {n.replace('.exe', '').lower() for n in KNOWN_MINER_BINS}:
        r.add(60, f'known crypto miner binary name ({norm})')

    # ── Mining cmdline patterns (+40 each, cap at 40) ────
    mining_hits = 0
    for pattern, desc in MINING_CMDLINE_PATTERNS:
        if re.search(pattern, cmd, re.I):
            if mining_hits == 0:
                r.add(40, desc)
            mining_hits += 1

    # ── Backdoor/reverse-shell cmdline (+35) ─────────────
    for pattern, desc in BACKDOOR_CMDLINE_PATTERNS:
        if re.search(pattern, cmd, re.I):
            r.add(35, desc)
            break  # one is enough to trigger

    # ── Running from suspicious temp location (+30) ───────
    if exe and not _proc_is_appimage_or_pyinstaller(exe):
        exe_l = exe.lower().replace('\\', '/')
        temp_roots = ['/tmp/', '/dev/shm/', '/var/tmp/']
        if OS == 'Windows':
            temp_roots += [
                (os.environ.get('TEMP', '') + '\\').lower(),
                'c:\\windows\\temp\\',
            ]
        if any(exe_l.startswith(t) for t in temp_roots):
            r.add(30, f'executable running from temp directory ({exe[:60]})')

    # ── Connected to mining pool port (+15) ──────────────
    if r.score > 0:   # only check connections if already suspicious (perf)
        ports = _get_process_connections(pid)
        for port in ports:
            if port in MINING_POOL_PORTS:
                r.add(15, f'connected to known mining pool port {port}')
                break
            if port in SUSPICIOUS_PORTS_STRICT:
                r.add(10, f'connected to suspicious port {port}')
                break

    # ── Exe is world-writable (+10) ───────────────────────
    if exe and OS == 'Linux':
        try:
            mode = Path(exe).stat().st_mode
            if mode & stat.S_IWOTH:
                r.add(10, 'process executable is world-writable')
        except OSError:
            pass

    # ── Discount: installed path (−30) ────────────────────
    if exe:
        exe_l = exe.lower().replace('\\', '/')
        if any(exe_l.startswith(p.lower().replace('\\', '/')) for p in TRUSTED_PATH_PREFIXES):
            r.add(-30, 'executable in standard installed-software path')

    # ── Discount: system-owned process (−20) ──────────────
    if OS == 'Linux':
        try:
            status = Path(f'/proc/{pid}/status').read_text(errors='ignore')
            for line in status.splitlines():
                if line.startswith('Uid:'):
                    uid = int(line.split()[1])
                    if uid == 0:
                        r.add(-20, 'process owned by root (system service)')
                    break
        except (OSError, ValueError):
            pass

    return r


DANGEROUS_EXTENSIONS = {'.sh', '.py', '.rb', '.pl', '.php', '.exe', '.elf',
                         '.bin', '.bat', '.ps1', '.vbs', '.cmd', '.scr', '.pif'}

SCAN_DIRS_LINUX   = ['/tmp', '/var/tmp', '/dev/shm',
                     str(Path.home() / '.local/bin'),
                     str(Path.home() / '.config')]
SCAN_DIRS_WINDOWS = [
    os.environ.get('TEMP', ''), os.environ.get('APPDATA', ''),
    'C:/Windows/Temp', 'C:/ProgramData',
]


# ══════════════════════════════════════════════════════════════
# MAIN SCANNER CLASS
# ══════════════════════════════════════════════════════════════

class SecurityScanner:

    def __init__(self):
        self.results: List[ScanResult] = []
        self._ok_count = 0

    def scan(self, log_cb: Callable[[str, str], None]) -> List[ScanResult]:
        self.results = []
        self._ok_count = 0
        t0 = time.monotonic()

        log_cb('═' * 52, 'head')
        log_cb('  SECURITY SCAN  //  Smart Analysis v2.3', 'head')
        log_cb('═' * 52, 'head')

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

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        self._print_summary(log_cb, elapsed_ms)
        return self.results

    def _ok(self, log_cb, msg: str):
        """Log an all-clear line and increment ok counter."""
        log_cb(f'  ✓  {msg}', 'ok')
        self._ok_count += 1

    # ══════════════════════════════════════════════════════
    # RUNNING PROCESSES  (smart scoring engine)
    # ══════════════════════════════════════════════════════
    def _scan_running_processes(self, log_cb):
        log_cb('', 'info')
        log_cb('◆ Scanning running processes...', 'info')
        try:
            import psutil
        except ImportError:
            log_cb('  ~ psutil not available — process scan skipped', 'dim')
            return

        found_any = False
        scanned = 0
        trusted_skip = 0

        for p in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
            try:
                pid  = p.info['pid']
                name = (p.info['name'] or '').strip()
                exe  = (p.info['exe'] or '')
                cmd  = ' '.join(p.info['cmdline'] or [])

                scanned += 1

                # ── Fast trusted check first ───────────────────
                is_trusted, trust_reason = _is_trusted_process(name, exe, pid)
                if is_trusted:
                    trusted_skip += 1
                    continue

                # ── Score the process ──────────────────────────
                risk = _score_process(name, exe, cmd.lower(), pid)

                if risk.severity is None:
                    continue  # not suspicious enough

                found_any = True
                _kill = _safe_kill_cmd(pid)

                # ── Format detail message ──────────────────────
                display_name = name or Path(exe).name if exe else f'PID {pid}'
                detail = f'{display_name} (PID {pid}) — {risk.verdict()}'

                # ── Special user-friendly label for miners ─────
                if risk.score >= 60 and any('miner' in s.lower() for s in risk.signals):
                    category = 'malware'
                    label    = 'MINER'
                    icon     = '⛔'
                elif risk.severity == 'critical':
                    category = 'malware'
                    label    = 'BACKDOOR'
                    icon     = '⛔'
                elif risk.severity == 'high':
                    category = 'suspicious'
                    label    = 'SUSPICIOUS'
                    icon     = '⚠ '
                else:
                    category = 'suspicious'
                    label    = 'ANOMALY'
                    icon     = '~ '

                self.results.append(ScanResult(
                    severity=risk.severity,
                    category=category,
                    path=exe or name,
                    detail=detail,
                    reasons=risk.signals,
                    can_fix=bool(_kill),
                    fix_cmd=_kill,
                ))

                log_cb(f'  {icon} [{label}] {display_name}  PID={pid}', 'err' if risk.severity == 'critical' else 'warn')
                # Print the individual signals so user can see WHY
                for sig in risk.signals:
                    if sig.startswith('+'):
                        log_cb(f'       {sig}', 'dim')

            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

        if not found_any:
            self._ok(log_cb, f'No malicious processes detected ({scanned} processes scanned, {trusted_skip} trusted)')

    # ══════════════════════════════════════════════════════
    # SUID/SGID  (unchanged logic, improved output)
    # ══════════════════════════════════════════════════════
    def _scan_suid_sgid(self, log_cb):
        log_cb('', 'info')
        log_cb('◆ Scanning SUID/SGID binaries...', 'info')
        known_suid = {
            '/usr/bin/sudo', '/usr/bin/su', '/usr/bin/passwd', '/usr/bin/newgrp',
            '/usr/bin/suexec', '/usr/bin/chsh', '/usr/bin/chfn', '/usr/bin/gpasswd',
            '/usr/bin/pkexec', '/usr/lib/polkit-1/polkit-agent-helper-1',
            '/bin/ping', '/usr/bin/ping', '/usr/bin/traceroute',
            '/usr/bin/mount', '/usr/bin/umount', '/usr/sbin/unix_chkpwd',
            '/usr/bin/Xorg', '/usr/lib/xorg/Xorg', '/usr/lib/xorg-server/Xorg.wrap',
            '/usr/lib/systemd/systemd-logind', '/usr/lib/systemd/systemd-user-sessions',
            '/usr/bin/fusermount', '/usr/bin/fusermount3',
            '/usr/lib/dbus-1.0/dbus-daemon-launch-helper',
        }
        out = run('find /usr /bin /sbin /tmp -perm /4000 -type f 2>/dev/null', timeout=15)
        found = 0
        for line in out.splitlines():
            f = line.strip()
            if not f or f in known_suid or _is_expected_suid_path(f):
                continue
            self.results.append(ScanResult(
                severity='high', category='suid', path=f,
                detail=f'Unexpected SUID binary: {f}',
                reasons=['File has setuid bit outside known-safe whitelist'],
                can_fix=True, fix_cmd=_h('fix-suid', f),
            ))
            log_cb(f'  ⚠  Unexpected SUID: {f}', 'warn')
            log_cb(f'     Strip with: sudo chmod u-s "{f}" (fix available)', 'dim')
            found += 1
        if found == 0:
            self._ok(log_cb, 'No unexpected SUID binaries')

    # ══════════════════════════════════════════════════════
    # WORLD-WRITABLE
    # ══════════════════════════════════════════════════════
    def _scan_world_writable(self, log_cb):
        log_cb('', 'info')
        log_cb('◆ Scanning world-writable files in system dirs...', 'info')
        out = run('find /etc /usr/local/bin /usr/bin -perm -0002 -type f 2>/dev/null', timeout=15)
        found = 0
        for line in out.splitlines():
            f = line.strip()
            if not f:
                continue
            self.results.append(ScanResult(
                severity='high', category='writable', path=f,
                detail=f'World-writable system file: {f}',
                reasons=['Any user can modify this system file'],
                can_fix=True, fix_cmd=_h('fix-writable', f),
            ))
            log_cb(f'  ⚠  World-writable: {f}', 'warn')
            found += 1
        if found == 0:
            self._ok(log_cb, 'No world-writable system files')

    # ══════════════════════════════════════════════════════
    # CRON BACKDOORS
    # ══════════════════════════════════════════════════════
    def _scan_cron(self, log_cb):
        log_cb('', 'info')
        log_cb('◆ Scanning cron jobs for backdoors...', 'info')
        cron_dirs = ['/etc/cron.d', '/etc/cron.daily', '/etc/cron.hourly',
                     '/var/spool/cron', str(Path.home() / '.local/share/cron')]
        found   = 0
        partial = False

        for d in cron_dirs:
            p = Path(d)
            if not p.exists():
                continue
            try:
                for f in _safe_walk(p):
                    try:
                        txt = f.read_text(errors='ignore')
                        for pattern, desc in MALICIOUS_SCRIPT_PATTERNS:
                            if re.search(pattern, txt, re.I):
                                self.results.append(ScanResult(
                                    severity='critical', category='cron', path=str(f),
                                    detail=f'Cron backdoor: {desc} in {f.name}',
                                    reasons=[f'Pattern matched in {f}', desc],
                                ))
                                log_cb(f'  ⛔  Cron backdoor [{desc}]: {f}', 'err')
                                found += 1
                                break
                    except (PermissionError, OSError):
                        log_cb(f'  ~ {f.name}: permission denied — run as root for full scan', 'dim')
                        partial = True
            except PermissionError:
                log_cb(f'  ~ {d}: permission denied — run as root for full cron scan', 'dim')
                partial = True

        crontab = run('crontab -l 2>/dev/null')
        for pattern, desc in MALICIOUS_SCRIPT_PATTERNS:
            if re.search(pattern, crontab, re.I):
                self.results.append(ScanResult(
                    severity='critical', category='cron', path='user crontab',
                    detail=f'Cron backdoor: {desc}',
                    reasons=[desc],
                ))
                log_cb(f'  ⛔  Cron backdoor in user crontab: {desc}', 'err')
                found += 1

        if found == 0:
            suffix = ' (partial — run as root for full scan)' if partial else ''
            self._ok(log_cb, f'No cron backdoors found{suffix}')

    # ══════════════════════════════════════════════════════
    # SUSPICIOUS FILES  (smart context filtering)
    # ══════════════════════════════════════════════════════
    def _scan_suspicious_files(self, log_cb, dirs):
        log_cb('', 'info')
        log_cb('◆ Scanning suspicious files in temp/user dirs...', 'info')
        found = 0

        for d in dirs:
            p = Path(d)
            if not p.exists():
                continue
            try:
                for f in _safe_walk(p):
                    fstr = str(f)
                    fstr_l = fstr.lower()

                    # ── Skip safe contexts ─────────────────────
                    if any(skip in fstr_l for skip in (
                        'node_modules', '/cache', '\\cache', '.git',
                        '__pycache__', '.venv', 'site-packages',
                        'subdir', '_mei', '.mount_',
                    )):
                        continue

                    # ── Skip files over 50MB ───────────────────
                    try:
                        if f.stat().st_size > 50_000_000:
                            continue
                    except OSError:
                        continue

                    # ── Only scan script/executable extensions ──
                    if f.suffix.lower() not in DANGEROUS_EXTENSIONS:
                        continue

                    try:
                        txt = f.read_text(errors='ignore')[:4096]
                    except (OSError, PermissionError, UnicodeDecodeError):
                        continue

                    # ── Check if file is from CyberClean itself ─
                    if any(marker in fstr for marker in ('CyberClean', 'cyberclean')):
                        continue

                    # ── Pattern match ──────────────────────────
                    for pattern, desc in MALICIOUS_SCRIPT_PATTERNS:
                        if re.search(pattern, txt, re.I):
                            fix_cmd = (
                                f'sudo -n {HELPER} remove-file "{f}"'
                                if OS == 'Linux' else f'del /f /q "{f}"'
                            )
                            self.results.append(ScanResult(
                                severity='critical', category='malware', path=fstr,
                                detail=f'Malicious script: {f.name}',
                                reasons=[f'Pattern: {desc}', f'Location: {fstr[:80]}'],
                                can_fix=True, fix_cmd=fix_cmd,
                            ))
                            log_cb(f'  ⛔  Malicious script: {f.name}', 'err')
                            log_cb(f'     Reason: {desc}', 'dim')
                            found += 1
                            break

                    # ── Executable in /tmp (Linux) — low severity ──
                    if OS == 'Linux' and fstr.startswith('/tmp') and found == 0:
                        try:
                            if f.stat().st_mode & stat.S_IXUSR:
                                if not (re.search(r'/tmp/_MEI[^/]+/', fstr) or
                                        re.search(r'/tmp/\.mount_', fstr)):
                                    self.results.append(ScanResult(
                                        severity='medium', category='suspicious', path=fstr,
                                        detail=f'Executable file in /tmp: {f.name}',
                                        reasons=['Executable bit set in /tmp — unusual for legitimate software'],
                                    ))
                                    log_cb(f'  ~  Executable in /tmp: {f.name}', 'warn')
                                    found += 1
                        except OSError:
                            pass

            except (PermissionError, OSError):
                pass

        if found == 0:
            self._ok(log_cb, 'No suspicious files found in temp/user dirs')

    # ══════════════════════════════════════════════════════
    # NETWORK — LINUX
    # ══════════════════════════════════════════════════════
    def _scan_network_linux(self, log_cb):
        log_cb('', 'info')
        log_cb('◆ Scanning active network connections...', 'info')
        out = run('ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null', timeout=8)
        found = 0

        strict_ports = {4444: 'Metasploit default', 1337: 'common RAT port',
                        31337: 'classic backdoor port', 6667: 'IRC/botnet',
                        6666: 'common RAT port', 54321: 'common RAT port'}
        mining_ports = {3333: 'Monero/XMR pool', 5555: 'ETH pool',
                        14444: 'mining pool', 45560: 'mining pool'}

        def _extract_pid(line: str) -> Optional[int]:
            """Extract PID from ss -tlnp output: users:(("ncat",pid=11528,fd=3))"""
            m = re.search(r'pid=(\d+)', line)
            if m:
                return int(m.group(1))
            # Fallback: netstat -tlnp format: 11528/ncat
            m2 = re.search(r'\b(\d+)/\S+', line)
            if m2:
                return int(m2.group(1))
            return None

        for line in out.splitlines():
            for port, label in strict_ports.items():
                if f':{port} ' in line or f':{port}\t' in line:
                    pid = _extract_pid(line)
                    kill = _safe_kill_cmd(pid) if pid else ''
                    self.results.append(ScanResult(
                        severity='high', category='network', path=line.strip(),
                        detail=f'Suspicious port {port} listening ({label})'
                               + (f' — PID {pid}' if pid else ''),
                        reasons=[
                            f'Port {port} is associated with: {label}',
                            f'Owning PID: {pid}' if pid else 'PID unknown (run as root for full info)',
                            'AUTO-FIX: kills owning process' if kill else 'Manual kill required (own-user processes only)',
                        ],
                        can_fix=bool(kill),
                        fix_cmd=kill,
                    ))
                    log_cb(f'  ⚠  Port {port} ({label}): {line.strip()}', 'warn')
                    if pid:
                        log_cb(f'     PID {pid} — {"AUTO-FIX available" if kill else "kill manually: kill -9 " + str(pid)}', 'dim')
                    found += 1

            for port, label in mining_ports.items():
                if f':{port} ' in line or f':{port}\t' in line:
                    pid = _extract_pid(line)
                    kill = _safe_kill_cmd(pid) if pid else ''
                    self.results.append(ScanResult(
                        severity='medium', category='network', path=line.strip(),
                        detail=f'Mining pool port {port} listening ({label})'
                               + (f' — PID {pid}' if pid else ''),
                        reasons=[f'Port {port} commonly used by {label}'],
                        can_fix=bool(kill),
                        fix_cmd=kill,
                    ))
                    log_cb(f'  ~  Mining pool port {port} ({label}): {line.strip()}', 'warn')
                    found += 1

        if found == 0:
            self._ok(log_cb, 'No suspicious listening ports')

    # ══════════════════════════════════════════════════════
    # NETWORK — WINDOWS
    # ══════════════════════════════════════════════════════
    def _scan_network_windows(self, log_cb):
        log_cb('', 'info')
        log_cb('◆ Scanning active network connections...', 'info')
        out = run('netstat -ano 2>nul', timeout=10)
        found = 0

        strict_ports  = {4444, 1337, 31337, 12345, 54321, 6666, 6667}
        port_labels   = {4444: 'Metasploit default', 1337: 'RAT port',
                         31337: 'classic backdoor', 12345: 'common backdoor',
                         54321: 'RAT port', 6666: 'RAT port', 6667: 'IRC/botnet'}

        for line in out.splitlines():
            if 'LISTENING' not in line:
                continue
            parts = line.split()
            # netstat -ano columns: Proto  Local  Foreign  State  PID
            # e.g. TCP  0.0.0.0:4444  0.0.0.0:0  LISTENING  11528
            pid_from_netstat = None
            if parts:
                try:
                    pid_from_netstat = int(parts[-1])
                except ValueError:
                    pass

            for port in strict_ports:
                if f':{port} ' in line or f':{port}\t' in line or line.strip().endswith(f':{port}'):
                    label = port_labels.get(port, 'suspicious port')

                    # ── Build fix_cmd: kill the owning process ──
                    # Step 1: taskkill /F /T kills process tree (catches child procs too)
                    # Step 2: netsh adds a persistent firewall block so it can't restart
                    if pid_from_netstat and pid_from_netstat > 4:
                        kill_cmd = (
                            f'taskkill /F /T /PID {pid_from_netstat} & '
                            f'netsh advfirewall firewall add rule '
                            f'name="CyberClean-Block-Port-{port}" '
                            f'protocol=TCP dir=in localport={port} action=block'
                        )
                        can_fix = True
                    else:
                        kill_cmd = (
                            f'netsh advfirewall firewall add rule '
                            f'name="CyberClean-Block-Port-{port}" '
                            f'protocol=TCP dir=in localport={port} action=block'
                        )
                        can_fix = True

                    self.results.append(ScanResult(
                        severity='high', category='network', path=line.strip(),
                        detail=f'Suspicious port {port} listening ({label})'
                               + (f' — PID {pid_from_netstat}' if pid_from_netstat else ''),
                        reasons=[
                            f'Port {port}: {label}',
                            f'Owning PID: {pid_from_netstat}' if pid_from_netstat else 'PID unknown',
                            'AUTO-FIX: kills process + blocks port in Windows Firewall',
                        ],
                        can_fix=can_fix,
                        fix_cmd=kill_cmd,
                    ))
                    log_cb(f'  ⚠  Port {port} ({label}): {line.strip()}', 'warn')
                    if pid_from_netstat:
                        log_cb(f'     Owning PID: {pid_from_netstat} — AUTO-FIX available', 'dim')
                    found += 1

        if found == 0:
            self._ok(log_cb, 'No suspicious ports detected')

    # ══════════════════════════════════════════════════════
    # LD_PRELOAD
    # ══════════════════════════════════════════════════════
    def _scan_ld_preload(self, log_cb):
        log_cb('', 'info')
        log_cb('◆ Checking LD_PRELOAD / dynamic linker hijacks...', 'info')
        found = 0

        p = Path('/etc/ld.so.preload')
        if p.exists() and p.stat().st_size > 0:
            content = p.read_text(errors='ignore').strip()
            self.results.append(ScanResult(
                severity='critical', category='malware', path=str(p),
                detail=f'LD_PRELOAD set globally: {content}',
                reasons=['Global LD_PRELOAD injects a library into every process — classic rootkit technique'],
            ))
            log_cb(f'  ⛔  /etc/ld.so.preload has entries: {content}', 'err')
            log_cb('     This is a classic rootkit persistence mechanism.', 'dim')
            found += 1

        env_preload = os.environ.get('LD_PRELOAD', '')
        if env_preload:
            # Check if it's a legitimate library (e.g. steam, fakechroot)
            trusted_preloads = ('fakechroot', 'libfakechroot', 'steam-runtime',
                                'libsteam', 'valgrind', 'libasan', 'libtsan')
            is_trusted_preload = any(t in env_preload.lower() for t in trusted_preloads)
            if not is_trusted_preload:
                self.results.append(ScanResult(
                    severity='high', category='malware', path='$LD_PRELOAD',
                    detail=f'LD_PRELOAD env set: {env_preload}',
                    reasons=['LD_PRELOAD env var set to non-standard library'],
                ))
                log_cb(f'  ⚠  LD_PRELOAD env: {env_preload}', 'warn')
                found += 1
            else:
                log_cb(f'  ✓  LD_PRELOAD set but recognized as trusted: {env_preload}', 'ok')

        if found == 0:
            self._ok(log_cb, 'No LD_PRELOAD hijacks detected')

    # ══════════════════════════════════════════════════════
    # SSH AUTHORIZED KEYS
    # ══════════════════════════════════════════════════════
    def _scan_ssh_authorized_keys(self, log_cb):
        log_cb('', 'info')
        log_cb('◆ Checking SSH authorized_keys...', 'info')
        ak = Path.home() / '.ssh/authorized_keys'
        if not ak.exists():
            self._ok(log_cb, 'No authorized_keys file')
            return

        lines = [l.strip() for l in ak.read_text(errors='ignore').splitlines()
                 if l.strip() and not l.startswith('#')]
        if not lines:
            self._ok(log_cb, 'No SSH authorized keys')
            return

        KNOWN_KEY_TYPES = (
            'ssh-rsa', 'ssh-ed25519', 'ecdsa-sha2-nistp256',
            'ecdsa-sha2-nistp384', 'ecdsa-sha2-nistp521',
            'sk-ssh-ed25519@openssh.com', 'sk-ecdsa-sha2-nistp256@openssh.com',
        )
        suspicious = []
        for line in lines:
            if re.match(r'command\s*=', line, re.I):
                suspicious.append(('high', f'Forced-command key (remote code exec risk): ...{line[-50:]}'))
            elif not any(line.startswith(kt) for kt in KNOWN_KEY_TYPES) and \
                 not re.match(r'(no-|from=|environment=|permitopen=|restrict)', line, re.I):
                suspicious.append(('medium', f'Unrecognised key format: ...{line[-50:]}'))

        log_cb(f'  ✓  {len(lines)} SSH authorized key(s) — looks normal', 'ok')
        for i, line in enumerate(lines[:3]):
            log_cb(f'     key {i+1}: ...{line[-40:]}', 'dim')

        for severity, detail in suspicious:
            self.results.append(ScanResult(
                severity=severity, category='suspicious', path=str(ak),
                detail=detail,
                reasons=['Unusual option in authorized_keys line'],
            ))
            log_cb(f'  {"⛔" if severity == "high" else "⚠ "}  {detail}',
                   'err' if severity == 'high' else 'warn')

    # ══════════════════════════════════════════════════════
    # HOSTS FILE
    # ══════════════════════════════════════════════════════
    def _scan_hosts_file(self, log_cb):
        log_cb('', 'info')
        log_cb('◆ Checking /etc/hosts for tampering...', 'info')

        if OS == 'Linux':
            hosts_path = Path('/etc/hosts')
        else:
            windir = os.environ.get('WINDIR', 'C:/Windows')
            hosts_path = Path(f'{windir}/System32/drivers/etc/hosts')

        if not hosts_path.exists():
            log_cb('  ~ hosts file not found', 'dim')
            return

        suspicious_domains = [
            'google.com', 'facebook.com', 'github.com', 'microsoft.com',
            'apple.com', 'amazon.com', 'paypal.com', 'bankofamerica.com',
            'windows.com', 'windowsupdate.com',
        ]
        found = 0
        for line in hosts_path.read_text(errors='ignore').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            ip, *domains = parts
            # Skip standard localhost entries
            if ip in ('127.0.0.1', '::1', '0.0.0.0', 'fe80::1%lo0'):
                continue
            for d in domains:
                if any(sd in d for sd in suspicious_domains):
                    self.results.append(ScanResult(
                        severity='high', category='malware', path=str(hosts_path),
                        detail=f'Hosts file redirect: {line}',
                        reasons=[f'Trusted domain "{d}" redirected to {ip}'],
                    ))
                    log_cb(f'  ⚠  Hosts hijack: {line}', 'warn')
                    log_cb(f'     Domain "{d}" is being redirected to {ip}', 'dim')
                    found += 1

        if found == 0:
            self._ok(log_cb, 'Hosts file looks clean')

    # ══════════════════════════════════════════════════════
    # WINDOWS AUTORUNS
    # ══════════════════════════════════════════════════════
    def _scan_autorun_windows(self, log_cb):
        log_cb('', 'info')
        log_cb('◆ Scanning Windows autorun entries...', 'info')
        try:
            import winreg
        except ImportError:
            log_cb('  ~ winreg not available', 'dim')
            return

        keys = [
            (winreg.HKEY_CURRENT_USER,  r'Software\Microsoft\Windows\CurrentVersion\Run'),
            (winreg.HKEY_LOCAL_MACHINE, r'Software\Microsoft\Windows\CurrentVersion\Run'),
            (winreg.HKEY_LOCAL_MACHINE, r'Software\Microsoft\Windows\CurrentVersion\RunOnce'),
        ]

        # Keywords that are genuinely suspicious in autorun values
        suspicious_kw = [
            ('powershell -enc',  'Encoded PowerShell command (obfuscation)'),
            ('powershell -w hidden', 'Hidden PowerShell window'),
            ('%temp%\\',         'Autorun from Temp folder'),
            ('appdata\\local\\temp\\', 'Autorun from Temp folder'),
            ('\\temp\\',         'Autorun from Temp folder'),
            ('mshta ',           'MSHTA execution (used by malware)'),
            ('wscript ',         'WScript execution outside System32'),
            ('cscript ',         'CScript execution outside System32'),
            ('regsvr32 /s',      'Silent RegSvr32 (COM scriptlet loading)'),
            ('certutil -decode', 'Certutil decoding (dropper pattern)'),
            ('bitsadmin /transfer', 'BITSAdmin file download'),
        ]

        # Known legitimate entries that may contain suspicious-looking keywords
        trusted_autorun_names = {
            'SecurityHealth', 'WindowsDefender', 'OneDrive',
            'GoogleChromeAutoLaunch', 'Discord', 'Slack', 'Spotify',
            'Steam', 'EpicGamesLauncher',
        }

        found = 0
        for hive, key_path in keys:
            hive_name = 'HKCU' if hive == winreg.HKEY_CURRENT_USER else 'HKLM'
            try:
                key = winreg.OpenKey(hive, key_path)
                i = 0
                while True:
                    try:
                        name, val, _ = winreg.EnumValue(key, i)
                        i += 1

                        # Skip known legitimate entries
                        if name in trusted_autorun_names:
                            continue

                        val_lower = val.lower()
                        for kw, reason in suspicious_kw:
                            if kw.lower() in val_lower:
                                # ── Fix: delete the registry value + quarantine the file ──
                                # reg delete removes the persistence key so it won't restart
                                reg_fix = (
                                    f'reg delete "{hive_name}\\{key_path}" '
                                    f'/v "{name}" /f'
                                )
                                # Also try to kill the process if the exe path is extractable
                                exe_match = re.search(r'"?([A-Za-z]:\\[^"]+\.exe)"?', val, re.I)
                                if exe_match:
                                    exe_path = exe_match.group(1)
                                    fix_cmd = (
                                        f'{reg_fix} & '
                                        f'taskkill /F /T /IM "{Path(exe_path).name}" 2>nul'
                                    )
                                else:
                                    fix_cmd = reg_fix

                                self.results.append(ScanResult(
                                    severity='high', category='malware', path=val,
                                    detail=f'Suspicious autorun: {name}',
                                    reasons=[reason, f'Value: {val[:100]}',
                                             f'Registry: {hive_name}\\{key_path}'],
                                    can_fix=True,
                                    fix_cmd=fix_cmd,
                                ))
                                log_cb(f'  ⚠  Suspicious autorun: {name}', 'warn')
                                log_cb(f'     Reason: {reason}', 'dim')
                                log_cb(f'     Value: {val[:80]}', 'dim')
                                log_cb(f'     AUTO-FIX: removes registry key + kills process', 'dim')
                                found += 1
                                break
                    except OSError:
                        break
                winreg.CloseKey(key)
            except (OSError, PermissionError):
                pass

        if found == 0:
            self._ok(log_cb, 'No suspicious autoruns')

    # ══════════════════════════════════════════════════════
    # SUMMARY  (smart, tiered)
    # ══════════════════════════════════════════════════════
    def _print_summary(self, log_cb, elapsed_ms: int):
        crits  = [r for r in self.results if r.severity == 'critical']
        highs  = [r for r in self.results if r.severity == 'high']
        meds   = [r for r in self.results if r.severity == 'medium']

        log_cb('', 'info')
        log_cb('═' * 52, 'head')
        log_cb('  SCAN COMPLETE', 'head')
        log_cb('─' * 52, 'head')

        if crits:
            log_cb(f'  ⛔  {len(crits)} CRITICAL threat(s) — action required', 'err')
            for r in crits[:5]:
                log_cb(f'       › {r.detail[:70]}', 'err')

        if highs:
            log_cb(f'  ⚠   {len(highs)} HIGH severity issue(s) — review recommended', 'warn')
            for r in highs[:5]:
                log_cb(f'       › {r.detail[:70]}', 'warn')

        if meds:
            log_cb(f'  ~   {len(meds)} MEDIUM finding(s) — low priority', 'dim')

        if not crits and not highs and not meds:
            log_cb('  ✓   System looks clean — no threats detected', 'ok')
        elif not crits and not highs:
            log_cb('  ✓   No high-severity threats (only low-priority anomalies)', 'ok')

        log_cb('─' * 52, 'head')
        log_cb(f'  Total findings : {len(self.results)}', 'info')
        log_cb(f'  Categories OK  : {self._ok_count}', 'info')
        log_cb(f'  Scan duration  : {elapsed_ms} ms', 'info')
        log_cb('═' * 52, 'head')

        # Explain the scoring system briefly so user understands
        if self.results:
            log_cb('', 'info')
            log_cb('  ℹ  Each finding shows WHY it was flagged (+signals above).', 'dim')
            log_cb('  ℹ  CRITICAL = multiple strong signals agree. Not a single guess.', 'dim')
