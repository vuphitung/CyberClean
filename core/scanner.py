"""
CyberClean v2.4 — Security Scanner  (Threat Scoring Engine)
════════════════════════════════════════════════════════════════

WHAT CHANGED vs v2.3  (full rewrite of scoring logic):

OLD approach — "bắt quả tang":
  Thấy cổng 12345 → báo ngay HIGH. Thấy .exe trong /tmp → báo ngay.
  Không biết đó là Bot trade, WireGuard, AppImage, hay Docker.
  → false positive liên tục, không phân biệt được người lành / kẻ xấu.

NEW approach — "điều tra lý lịch" (Threat Scoring Matrix):
  Mỗi tiến trình / file đi qua 5 bước:
    1. Evidence Gathering  — thu thập exe path, cmdline, CPU%, connections
    2. Whitelist bypass    — miễn tử bài cho Chromium gpu-process, AppImage,
                             PyInstaller bundle, Docker, user custom whitelist
    3. Threat scoring      — cộng/trừ điểm đa chiều (ma trận bên dưới)
    4. Watchlist           — score 40-69 → ghi watchlist.json, theo dõi tiếp
    5. Verdict             — < 40 bỏ qua, 40-69 warn, >= 70 critical + offer kill

Threat Score Matrix (additive, capped at 100):
  +60  known crypto miner name
  +50  fake system process name (svchost.exe không ở System32)
  +40  exe trong /tmp /dev/shm %TEMP% (không phải AppImage/PyInstaller)
  +40  cmdline pattern: reverse shell, curl|bash, base64 eval, LD_PRELOAD
  +35  cổng C2 / miner / RAT đã biết (4444, 1337, 31337, 3333, v.v.)
  +30  CPU > 80% liên tục (miner behavior)
  +20  cổng ephemeral cao > 49151 + không phải localhost
  +20  multiple network connections từ cùng 1 process (botnet behavior)
  -15  python / node / java / ruby (known runtime interpreters)
  -20  exe trong /usr /bin /opt /Program Files (installed location)
  -30  Windows: file có valid digital signature
  -40  AppImage mount /tmp/.mount_* (legitimate Linux AppImage)
  -40  PyInstaller bundle /tmp/_MEI* (legitimate bundled app)
  -50  path khớp user_whitelist.json (user đã đánh dấu false positive)

Watchlist (watchlist.json):
  Process score 40-69 → ghi vào watchlist với timestamp + score + reasons.
  _run_auto_clean trong main.py check watchlist mỗi 5 phút.
  Nếu process trở lại với score cao hơn → escalate lên critical.
  User có thể xem watchlist trong scanner tab.

User whitelist (user_whitelist.json):
  User click "Mark as safe" trên false positive → path vào whitelist.
  Lần scan sau: -50 điểm, hầu như không bao giờ bị flag lại.
  Cho phép user dạy scanner về môi trường cụ thể của họ.

Hash cache (exe_hash_cache.json):
  SHA-256 của mỗi exe sau lần scan đầu.
  Lần sau chỉ rescan exe có hash thay đổi → nhanh hơn ~3x.
  Phát hiện binary bị patch/replace giữa các lần scan.

Honest note về giới hạn:
  CyberClean KHÔNG thể phát hiện rootkit Ring-0, UEFI implant, kernel
  driver exploit — những thứ này hoạt động bên dưới Python/psutil.
  Thứ CyberClean làm tốt: miners, scripts độc trong /tmp, cron backdoor,
  hosts hijack, process từ temp dir — threats phổ biến và thực tế.

Cross-platform: Windows 10/11 + tất cả Linux distros.
"""

import hashlib
import json
import os
import platform
import re
import stat
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

OS     = platform.system()
HELPER = '/usr/local/bin/cyber-clean-helper'

# ── Persistent storage paths ──────────────────────────────────
if OS == 'Windows':
    _DATA_DIR = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'CyberClean'
else:
    _DATA_DIR = Path.home() / '.local/share/cyber-clean'

WATCHLIST_FILE   = _DATA_DIR / 'watchlist.json'
USER_WHITELIST   = _DATA_DIR / 'user_whitelist.json'
HASH_CACHE_FILE  = _DATA_DIR / 'exe_hash_cache.json'


# ══════════════════════════════════════════════════════════════
# PID SAFETY GUARD (unchanged from v2.3)
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
    severity:  str           # 'critical' | 'high' | 'medium' | 'info'
    category:  str
    path:      str
    detail:    str
    can_fix:   bool = False
    fix_cmd:   str  = ''
    score:     int  = 0      # NEW: threat score 0–100
    reasons:   List[str] = field(default_factory=list)  # NEW: scoring reasons


@dataclass
class WatchlistEntry:
    path:       str
    pid:        int
    score:      int
    reasons:    List[str]
    first_seen: float   # timestamp
    last_seen:  float
    seen_count: int = 1


# ══════════════════════════════════════════════════════════════
# THREAT SCORE CONSTANTS
# ══════════════════════════════════════════════════════════════

# Cổng C2 / miner / RAT / reverse shell đã biết
_SUSPICIOUS_PORTS = {
    # Classic RAT / backdoor
    4444, 1337, 31337, 12345, 54321, 31338, 4445, 4446, 5555,
    # Cobalt Strike, Metasploit
    50050, 4443, 8443,
    # IRC botnet
    6666, 6667, 6668, 6669,
    # Crypto miner stratum
    3333, 7777, 14444, 14433, 45560,
    # Tor proxy
    9050, 9150,
    # Remote admin non-standard
    2222, 9001, 9999,
    # NetBus / BackOrifice
    12346, 65535, 54320,
}

# Process names không bao giờ nên có network connection
_NEVER_NETWORK = {
    'explorer', 'winlogon', 'csrss', 'smss', 'lsass', 'dwm',
    'wininit', 'services', 'taskhostw', 'sihost', 'fontdrvhost',
    'Xorg', 'gnome-session', 'ksmserver', 'plasmashell',
}

# Crypto miner names
KNOWN_MINERS = {
    'xmrig', 'xmrig-notls', 'minerd', 'cpuminer-multi', 'nbminer',
    'teamredminer', 'lolminer', 'gminer', 't-rex', 'nanominer',
    'claymore', 'ethminer', 'phoenixminer', 'kawpow', 'xmr-stak',
}

# Script patterns chỉ ra hành vi độc hại
SUSPICIOUS_SCRIPTS = [
    (r'bash\s+-i\s+>&\s*/dev/tcp',          'Reverse bash shell'),
    (r'nc\s+-e\s+/bin/(bash|sh)',            'Netcat reverse shell'),
    (r'python.*socket.*connect.*subprocess', 'Python reverse shell pattern'),
    (r'curl\s+.*\|\s*(bash|sh)',             'Remote code exec via curl|bash'),
    (r'wget\s+.*-O-\s*\|',                  'Remote code exec via wget|pipe'),
    (r'eval\s*\(\s*base64_decode',           'PHP base64 eval (webshell)'),
    (r'eval\s*\(\s*gzinflate',               'PHP obfuscated eval (webshell)'),
    (r'(xmrig|minerd|cpuminer)',             'Crypto miner binary reference'),
    (r'stratum\+tcp://',                     'Mining pool connection string'),
    (r'LD_PRELOAD\s*=',                      'LD_PRELOAD manipulation'),
    (r'/proc/\d+/mem',                       'Direct process memory access'),
    (r'powershell.*-enc\s+[A-Za-z0-9+/=]{20}', 'Encoded PowerShell command'),
    (r'certutil.*-decode',                   'CertUtil decode (bypass)'),
    (r'bitsadmin.*transfer',                 'BITSAdmin download (bypass)'),
    (r'regsvr32.*scrobj',                    'Regsvr32 script execution'),
    (r'mshta\s+http',                        'MSHTA remote script exec'),
]

DANGEROUS_EXTENSIONS = {
    '.sh', '.py', '.rb', '.pl', '.php', '.exe', '.elf', '.bin',
    '.bat', '.ps1', '.vbs', '.cmd', '.dll', '.scr', '.pif',
}

SCAN_DIRS_LINUX = [
    '/tmp', '/var/tmp', '/dev/shm',
    str(Path.home() / '.local/bin'),
    str(Path.home() / '.config'),
    '/etc/cron.d', '/etc/cron.daily', '/etc/cron.hourly', '/etc/cron.weekly',
]

SCAN_DIRS_WINDOWS = [
    os.environ.get('TEMP', ''), os.environ.get('APPDATA', ''),
    'C:/Windows/Temp', 'C:/ProgramData',
]


# ══════════════════════════════════════════════════════════════
# PERSISTENT STATE HELPERS
# ══════════════════════════════════════════════════════════════

def _load_json(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _save_json(path: Path, data: dict):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    except OSError:
        pass


def load_user_whitelist() -> set:
    """Load user-defined safe paths. Returns set of lowercase paths."""
    data = _load_json(USER_WHITELIST)
    return {k.lower() for k in data.keys()}


def add_to_user_whitelist(path: str, reason: str = 'user marked safe'):
    """Mark a path as safe. Called from GUI when user clicks 'Mark as safe'."""
    data = _load_json(USER_WHITELIST)
    data[path] = {'reason': reason, 'added': time.strftime('%Y-%m-%dT%H:%M:%S')}
    _save_json(USER_WHITELIST, data)


def load_watchlist() -> Dict[str, dict]:
    return _load_json(WATCHLIST_FILE)


def save_watchlist(data: dict):
    _save_json(WATCHLIST_FILE, data)


def _exe_sha256(path: str) -> str:
    """Compute SHA-256 of an executable. Returns '' on error."""
    try:
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                h.update(chunk)
        return h.hexdigest()
    except (OSError, PermissionError):
        return ''


def _load_hash_cache() -> dict:
    return _load_json(HASH_CACHE_FILE)


def _save_hash_cache(cache: dict):
    _save_json(HASH_CACHE_FILE, cache)


# ══════════════════════════════════════════════════════════════
# WHITELIST BYPASS CHECKS
# ══════════════════════════════════════════════════════════════

def _is_expected_suid_path(path: str) -> bool:
    """Chromium / Electron chrome-sandbox — intentional SUID, not malware."""
    p = path.replace('\\', '/')
    if not p.endswith('/chrome-sandbox'):
        return False
    if not (p.startswith('/usr/') or p.startswith('/opt/')):
        return False
    markers = (
        '/electron', '/chromium', '/chromium-browser', '/chrome/',
        '/google-chrome', 'google-chrome', '/opt/google/chrome',
        '/brave', '/vivaldi', '/opera', 'microsoft-edge', '/edge/',
    )
    return any(m in p.lower() for m in markers)


def _is_whitelisted_process(exe: str, cmdline: str) -> Tuple[bool, str]:
    """
    Check if a process is a known-safe pattern that should bypass all scoring.
    Returns (is_whitelisted, reason).

    Covers:
    - Chromium/Electron gpu-process, renderer, utility subprocesses
    - AppImage mounts (/tmp/.mount_*)
    - PyInstaller bundles (/tmp/_MEI*)
    - Docker/Podman container runtimes
    - Known system processes that legitimately run from non-standard paths
    """
    exe_l = (exe or '').lower().replace('\\', '/')
    cmd_l = (cmdline or '').lower()

    # Chromium / Electron subprocess types — gpu/renderer handle WebGL, camera, etc.
    _chromium_flags = (
        '--type=gpu-process', '--type=renderer', '--type=ppapi',
        '--type=utility', 'video-capture', '--gpu-process',
        '--type=crashpad-handler',
    )
    if any(flag in cmd_l for flag in _chromium_flags):
        return True, 'Chromium/Electron subprocess (gpu/renderer/utility)'

    # AppImage mount — legitimate Linux app format, always in /tmp/.mount_
    if re.search(r'/tmp/\.mount_[^/]+/', exe_l):
        return True, 'AppImage mount (legitimate Linux AppImage)'

    # PyInstaller bundle — legitimate bundled Python app
    if re.search(r'/tmp/_mei[^/]+/', exe_l):
        return True, 'PyInstaller bundle (legitimate bundled app)'

    # Docker / Podman / containerd runtime
    _container_names = ('docker', 'containerd', 'dockerd', 'podman', 'runc', 'crun')
    if any(exe_l.endswith('/' + n) or exe_l.endswith('\\' + n) for n in _container_names):
        return True, 'Container runtime (Docker/Podman/containerd)'

    # Snap runtime
    if '/snap/' in exe_l and '/snap/bin/' not in exe_l:
        return True, 'Snap package runtime'

    return False, ''


# ══════════════════════════════════════════════════════════════
# CORE THREAT SCORING ENGINE
# ══════════════════════════════════════════════════════════════

def _score_process(
    pid: int,
    name: str,
    exe: str,
    cmdline: str,
    user_whitelist: set,
    listen_ports: set,
    established_conns: int,
) -> Tuple[int, List[str]]:
    """
    Score a single process. Returns (score, reasons).
    Score 0-100. Higher = more suspicious.

    Completely replaces the old binary if/else logic.
    """
    score   = 0
    reasons = []
    name_l  = name.lower().replace('.exe', '')
    exe_l   = (exe or '').lower().replace('\\', '/')
    cmd_l   = cmdline.lower()

    # ── USER WHITELIST: strong negative evidence (-50) ──────────────
    if exe_l and exe_l in user_whitelist:
        score -= 50
        reasons.append('User marked as safe')

    # ── KNOWN MINER: strongest positive evidence (+60) ──────────────
    if name_l in {m.lower() for m in KNOWN_MINERS}:
        score += 60
        reasons.append(f'Known crypto miner process: {name}')

    # ── FAKE SYSTEM PROCESS (+50) ────────────────────────────────────
    # svchost.exe / explorer.exe NOT in Windows system dirs = process hijack
    _win_sys_names = {'svchost', 'explorer', 'lsass', 'winlogon', 'csrss', 'smss'}
    if name_l in _win_sys_names and exe_l:
        _win_sys_dirs = ('c:/windows/system32/', 'c:/windows/syswow64/', 'c:/windows/')
        if not any(exe_l.startswith(d) for d in _win_sys_dirs):
            score += 50
            reasons.append(f'System process name ({name}) running from non-system path')

    # ── EXE IN TEMP / RAMDISK (+40) ──────────────────────────────────
    _temp_roots = ('/tmp/', '/var/tmp/', '/dev/shm/')
    if OS == 'Windows':
        _temp_roots += (
            os.environ.get('TEMP', '').lower().replace('\\', '/') + '/',
            os.environ.get('TMP', '').lower().replace('\\', '/') + '/',
            'c:/windows/temp/',
        )
    if exe_l and any(exe_l.startswith(t) for t in _temp_roots if t):
        score += 40
        reasons.append(f'Executable running from temp/ramdisk directory')

    # ── SUSPICIOUS CMDLINE PATTERNS (+40 each, max 1 trigger) ────────
    for pattern, desc in SUSPICIOUS_SCRIPTS:
        if re.search(pattern, cmd_l, re.I):
            score += 40
            reasons.append(f'Suspicious cmdline: {desc}')
            break   # one pattern is enough to add +40 once

    # ── LISTENING ON SUSPICIOUS PORT (+35) ───────────────────────────
    matching_ports = listen_ports & _SUSPICIOUS_PORTS
    if matching_ports:
        score += 35
        reasons.append(f'Listening on known C2/miner port(s): {sorted(matching_ports)}')

    # ── HIGH CPU (miner behaviour) (+30) ─────────────────────────────
    # Caller passes cpu_pct — if process was > 80% at sample time
    # (This is passed via established_conns=-1 sentinel when cpu is high)
    if established_conns == -999:   # sentinel: high CPU detected
        score += 30
        reasons.append('Sustained high CPU usage (crypto miner behavior)')

    # ── MANY OUTBOUND CONNECTIONS (+20) ─────────────────────────────
    if established_conns >= 8:
        score += 20
        reasons.append(f'High outbound connection count: {established_conns}')

    # ── LISTENING ON EPHEMERAL HIGH PORT + EXTERNAL (+20) ────────────
    _hi_ports = {p for p in listen_ports if p > 49151} - _SUSPICIOUS_PORTS
    if _hi_ports:
        score += 20
        reasons.append(f'Listening on non-standard high port(s): {sorted(_hi_ports)[:3]}')

    # ── SYSTEM PROCESS MAKING NETWORK CONNECTIONS (+25) ──────────────
    if name_l in {n.lower() for n in _NEVER_NETWORK} and (listen_ports or established_conns > 0):
        score += 25
        reasons.append(f'{name} should not make network connections')

    # ── KNOWN RUNTIME (python/node/java) — context, not inherently bad (-15) ──
    # SECURITY FIX (Gemini / v2.4.1):
    # Discount ONLY applies when exe is in a real installation path.
    # A virus renamed to "python.exe" and placed in C:\Temp or /tmp still gets
    # +40 from the temp-dir rule above — we must NOT cancel that with -15.
    # Legitimate runtimes are NEVER installed in temp/ramdisk directories.
    _runtimes = {'python', 'python3', 'node', 'nodejs', 'java', 'ruby', 'perl', 'php'}
    _temp_roots_check = ('/tmp/', '/var/tmp/', '/dev/shm/')
    if OS == 'Windows':
        _temp_roots_check += (
            (os.environ.get('TEMP', '') + '/').lower().replace('\\', '/'),
            (os.environ.get('TMP', '')  + '/').lower().replace('\\', '/'),
            'c:/windows/temp/',
        )
    _exe_in_temp = exe_l and any(exe_l.startswith(t) for t in _temp_roots_check if t and t != '/')
    if name_l in _runtimes and not _exe_in_temp:
        # Legitimate runtime in a real install path — reduce suspicion
        score -= 15
        reasons.append(f'Known runtime interpreter ({name}) in valid location — likely legitimate')
    elif name_l in _runtimes and _exe_in_temp:
        # Runtime name BUT running from temp — fake name trick, no discount
        score += 20   # extra penalty: using runtime name as camouflage
        reasons.append(f'Runtime name ({name}) running from temp dir — possible impersonation (+20)')

    # ── INSTALLED LOCATION: system/program dirs (-20) ────────────────
    _safe_roots = (
        '/usr/', '/bin/', '/sbin/', '/opt/',
        'c:/program files/', 'c:/program files (x86)/',
        'c:/windows/system32/', 'c:/windows/syswow64/',
    )
    if exe_l and any(exe_l.startswith(r) for r in _safe_roots):
        score -= 20
        reasons.append('Executable in system/program directory')

    return max(0, min(100, score)), reasons


def _check_digital_signature_windows(exe_path: str) -> bool:
    """
    Check if a Windows exe has a valid digital signature.
    Uses Get-AuthenticodeSignature PowerShell — non-blocking, 5s timeout.
    Returns True if signed by a valid publisher.
    """
    if OS != 'Windows' or not exe_path:
        return False
    try:
        _NO_WIN = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        r = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             f'(Get-AuthenticodeSignature "{exe_path}").Status'],
            capture_output=True, text=True, timeout=5,
            creationflags=_NO_WIN,
        )
        return r.stdout.strip().lower() == 'valid'
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════
# WATCHLIST ENGINE
# ══════════════════════════════════════════════════════════════

def update_watchlist(exe: str, pid: int, score: int, reasons: List[str]) -> dict:
    """
    Add or update a watchlist entry. Returns the current watchlist.
    Called when score is in the 40-69 'suspicious but not confirmed' range.
    """
    data = load_watchlist()
    key  = exe.lower() if exe else f'pid:{pid}'
    now  = time.time()

    if key in data:
        entry = data[key]
        entry['last_seen']  = now
        entry['seen_count'] = entry.get('seen_count', 1) + 1
        # Escalate score if process keeps appearing with same flags
        entry['score']      = max(entry.get('score', score), score)
        entry['reasons']    = reasons   # update to latest
        entry['pid']        = pid
    else:
        data[key] = {
            'path':       exe,
            'pid':        pid,
            'score':      score,
            'reasons':    reasons,
            'first_seen': now,
            'last_seen':  now,
            'seen_count': 1,
        }
    save_watchlist(data)
    return data


def check_watchlist_escalations() -> List[dict]:
    """
    Called by auto-clean timer in main.py.
    Returns entries that should now be escalated to critical:
    - seen_count >= 3 (persistent) AND score >= 50
    - OR entry is still alive AND score has grown to >= 70
    """
    data    = load_watchlist()
    escalate = []
    for key, entry in data.items():
        score = entry.get('score', 0)
        count = entry.get('seen_count', 1)
        if (score >= 70) or (score >= 50 and count >= 3):
            escalate.append(entry)
    return escalate


def prune_watchlist(max_age_hours: float = 24.0):
    """Remove stale watchlist entries older than max_age_hours."""
    data    = load_watchlist()
    cutoff  = time.time() - max_age_hours * 3600
    pruned  = {k: v for k, v in data.items() if v.get('last_seen', 0) > cutoff}
    if len(pruned) != len(data):
        save_watchlist(pruned)


# ══════════════════════════════════════════════════════════════
# UTILITY HELPERS
# ══════════════════════════════════════════════════════════════

def run(cmd, timeout=10):
    try:
        no_win = 0x08000000 if OS == 'Windows' else 0
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=timeout, creationflags=no_win)
        return r.stdout.strip()
    except Exception:
        return ''


def _safe_walk(root: Path):
    """Walk without following symlinks — prevents infinite loop on circular symlinks."""
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


def _get_process_connections(pid: int) -> Tuple[set, int]:
    """
    Return (listening_ports: set, established_count: int) for a PID.
    Uses psutil — non-blocking, handles AccessDenied gracefully.
    """
    listen_ports     = set()
    established_count = 0
    try:
        import psutil
        proc = psutil.Process(pid)
        for conn in proc.connections(kind='inet'):
            if conn.status == psutil.CONN_LISTEN and conn.laddr:
                listen_ports.add(conn.laddr.port)
            elif conn.status == psutil.CONN_ESTABLISHED:
                established_count += 1
    except Exception:
        pass
    return listen_ports, established_count


# ══════════════════════════════════════════════════════════════
# MAIN SCANNER CLASS
# ══════════════════════════════════════════════════════════════

class SecurityScanner:

    def __init__(self):
        self.results:       List[ScanResult] = []
        self._user_wl:      set  = load_user_whitelist()
        self._hash_cache:   dict = _load_hash_cache()
        self._hash_dirty:   bool = False
        self._watchlist_new: List[dict] = []   # entries added this scan run

    def scan(self, log_cb: Callable[[str, str], None]) -> List[ScanResult]:
        self.results        = []
        self._user_wl       = load_user_whitelist()
        self._watchlist_new = []

        log_cb('═' * 52, 'head')
        log_cb('  SECURITY SCAN  //  Threat Scoring Engine v2.4', 'head')
        log_cb('═' * 52, 'head')

        prune_watchlist()   # remove stale entries silently

        if OS == 'Linux':
            self._scan_processes_scored(log_cb)
            self._scan_suid_sgid(log_cb)
            self._scan_world_writable(log_cb)
            self._scan_cron(log_cb)
            self._scan_suspicious_files(log_cb, SCAN_DIRS_LINUX)
            self._scan_ld_preload(log_cb)
            self._scan_ssh_authorized_keys(log_cb)
            self._scan_hosts_file(log_cb)
        elif OS == 'Windows':
            self._scan_processes_scored(log_cb)
            self._scan_suspicious_files(log_cb, [d for d in SCAN_DIRS_WINDOWS if d])
            self._scan_autorun_windows(log_cb)
            self._scan_hosts_file(log_cb)

        # Save hash cache if updated
        if self._hash_dirty:
            _save_hash_cache(self._hash_cache)

        # Summary
        crits  = [r for r in self.results if r.severity == 'critical']
        highs  = [r for r in self.results if r.severity == 'high']
        mediums = [r for r in self.results if r.severity == 'medium']

        log_cb('', 'info')
        log_cb('═' * 52, 'head')
        if crits:
            log_cb(f'  ⛔  {len(crits)} CRITICAL threats found!', 'err')
        if highs:
            log_cb(f'  ⚠   {len(highs)} HIGH severity issues', 'warn')
        if mediums:
            log_cb(f'  ~   {len(mediums)} MEDIUM / watchlist entries', 'warn')
        if not crits and not highs:
            log_cb('  ✓   No critical threats detected', 'ok')
        if self._watchlist_new:
            log_cb(f'  👁   {len(self._watchlist_new)} process(es) added to watchlist', 'info')
        log_cb(f'  Total findings: {len(self.results)}', 'info')
        log_cb('═' * 52, 'head')
        return self.results

    # ══════════════════════════════════════════════════════
    # SCORED PROCESS SCANNER (replaces old _scan_running_processes
    # + _scan_network_linux + _scan_network_windows)
    # ══════════════════════════════════════════════════════

    def _scan_processes_scored(self, log_cb: Callable):
        """
        Single unified process scanner for Linux + Windows.
        Uses threat scoring matrix instead of binary if/else.
        """
        log_cb('', 'info')
        log_cb('◆ Scanning processes (threat scoring engine)...', 'info')

        try:
            import psutil
        except ImportError:
            log_cb('  ~ psutil not available — process scan skipped', 'dim')
            return

        # Collect CPU samples first (non-blocking call — will measure on second call below)
        for p in psutil.process_iter(['pid']):
            try:
                p.cpu_percent(interval=None)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # Brief wait for CPU measurement window
        import time as _t
        _t.sleep(0.4)

        critical_count = 0
        watchlist_count = 0
        clean_count    = 0

        for p in psutil.process_iter(['pid', 'name', 'exe', 'cmdline', 'status']):
            try:
                pid     = p.info['pid']
                name    = (p.info['name'] or '').strip()
                exe     = p.info['exe'] or ''
                cmdline = ' '.join(p.info['cmdline'] or [])

                # ── Whitelist bypass check ─────────────────────────
                is_wl, wl_reason = _is_whitelisted_process(exe, cmdline)
                if is_wl:
                    # Don't log every whitelisted process — too noisy
                    # Only log if it would have been suspicious by name
                    if name.lower().replace('.exe', '') in {m.lower() for m in KNOWN_MINERS}:
                        log_cb(f'  ✓  Whitelisted: {name} ({wl_reason})', 'dim')
                    clean_count += 1
                    continue

                # ── Get network info for this process ──────────────
                listen_ports, established = _get_process_connections(pid)

                # ── CPU sample ─────────────────────────────────────
                try:
                    cpu_pct = p.cpu_percent(interval=None)
                    high_cpu_sentinel = -999 if cpu_pct > 80 else 0
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    high_cpu_sentinel = 0

                # ── Score this process ─────────────────────────────
                score, reasons = _score_process(
                    pid, name, exe, cmdline,
                    self._user_wl,
                    listen_ports,
                    high_cpu_sentinel if high_cpu_sentinel else established,
                )

                # ── Windows: check digital signature ──────────────
                # Only for processes already scoring > 0 (avoid overhead for clean)
                if OS == 'Windows' and score > 0 and exe:
                    if _check_digital_signature_windows(exe):
                        score = max(0, score - 30)
                        reasons.append('Valid digital signature (-30)')

                # ── Hash cache: detect binary tampering ───────────
                if exe and score > 0:
                    old_hash = self._hash_cache.get(exe)
                    new_hash = _exe_sha256(exe)
                    if new_hash:
                        if old_hash and old_hash != new_hash:
                            score = min(100, score + 25)
                            reasons.append(f'Binary hash changed since last scan! (+25)')
                        if new_hash != old_hash:
                            self._hash_cache[exe] = new_hash
                            self._hash_dirty = True

                # ── Verdict ───────────────────────────────────────
                if score >= 70:
                    # CRITICAL — offer kill
                    _kill = _safe_kill_cmd(pid)
                    severity = 'critical' if score >= 80 else 'high'
                    detail = (
                        f'Score {score}/100  ·  PID {pid}\n'
                        f'Reasons: {"; ".join(reasons)}'
                    )
                    r = ScanResult(
                        severity=severity, category='malware',
                        path=exe or name, detail=detail,
                        can_fix=bool(_kill), fix_cmd=_kill,
                        score=score, reasons=reasons,
                    )
                    self.results.append(r)
                    icon = '⛔' if severity == 'critical' else '⚠'
                    log_cb(f'  {icon}  [{score}/100] {name} (PID {pid})', 'err' if severity == 'critical' else 'warn')
                    for reason in reasons[:3]:
                        log_cb(f'       • {reason}', 'dim')
                    critical_count += 1

                elif score >= 40:
                    # WATCHLIST — suspicious but not confirmed
                    update_watchlist(exe or name, pid, score, reasons)
                    self._watchlist_new.append({'path': exe or name, 'score': score})
                    detail = (
                        f'Score {score}/100  ·  PID {pid}  ·  Under observation\n'
                        f'Reasons: {"; ".join(reasons)}'
                    )
                    r = ScanResult(
                        severity='medium', category='watchlist',
                        path=exe or name, detail=detail,
                        can_fix=False, fix_cmd='',
                        score=score, reasons=reasons,
                    )
                    self.results.append(r)
                    log_cb(f'  ~  [{score}/100] {name} (PID {pid}) → watchlist', 'warn')
                    for reason in reasons[:2]:
                        log_cb(f'       • {reason}', 'dim')
                    watchlist_count += 1

                else:
                    # CLEAN
                    if score > 0:
                        # Has some minor flags but not enough to worry
                        log_cb(
                            f'  ✓  [{score}/100] {name} — low risk'
                            + (f' ({reasons[0]})' if reasons else ''),
                            'dim'
                        )
                    clean_count += 1

            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

        # Summary line
        if critical_count == 0 and watchlist_count == 0:
            log_cb('  ✓  All processes clean', 'ok')
        else:
            log_cb(
                f'  →  {critical_count} critical, {watchlist_count} watchlisted, '
                f'{clean_count} clean',
                'info',
            )

    # ══════════════════════════════════════════════════════
    # SUID/SGID (Linux) — unchanged logic, kept as-is
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
            self.results.append(ScanResult(
                'high', 'suid', f,
                f'Unexpected SUID binary: {f}',
                can_fix=True,
                fix_cmd=f'sudo -n {HELPER} fix-suid "{f}"',
            ))
            log_cb(f'  ⚠  Unexpected SUID: {f}', 'warn')
            found += 1
        if found == 0:
            log_cb('  ✓  No unexpected SUID binaries', 'ok')

    # ══════════════════════════════════════════════════════
    # WORLD-WRITABLE (Linux)
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
                'high', 'writable', f,
                f'World-writable system file: {f}',
                can_fix=True,
                fix_cmd=f'sudo -n {HELPER} fix-writable "{f}"',
            ))
            log_cb(f'  ⚠  World-writable: {f}', 'warn')
            found += 1
        if found == 0:
            log_cb('  ✓  No world-writable system files', 'ok')

    # ══════════════════════════════════════════════════════
    # CRON BACKDOORS (Linux)
    # ══════════════════════════════════════════════════════

    def _scan_cron(self, log_cb):
        log_cb('', 'info')
        log_cb('◆ Scanning cron jobs for backdoors...', 'info')
        cron_dirs = [
            '/etc/cron.d', '/etc/cron.daily', '/etc/cron.hourly',
            '/var/spool/cron', str(Path.home() / '.local/share/cron'),
        ]
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
                        for pattern, desc in SUSPICIOUS_SCRIPTS:
                            if re.search(pattern, txt, re.I):
                                self.results.append(ScanResult(
                                    'critical', 'cron', str(f),
                                    f'Suspicious cron: {desc} in {f.name}',
                                ))
                                log_cb(f'  ⛔  Cron backdoor: {desc} in {f}', 'err')
                                found += 1
                                break
                    except (PermissionError, OSError):
                        log_cb(f'  ~ {f.name}: permission denied', 'dim')
                        partial = True
            except PermissionError:
                log_cb(f'  ~ {d}: permission denied — run as root for full scan', 'dim')
                partial = True

        crontab = run('crontab -l 2>/dev/null')
        for pattern, desc in SUSPICIOUS_SCRIPTS:
            if re.search(pattern, crontab, re.I):
                self.results.append(ScanResult('critical', 'cron', 'crontab',
                    f'Suspicious user crontab: {desc}'))
                log_cb(f'  ⛔  Cron backdoor in user crontab: {desc}', 'err')
                found += 1

        if found == 0:
            msg = '(partial scan — run as root for full coverage)' if partial else ''
            log_cb(f'  ✓  No cron backdoors found {msg}', 'ok')

    # ══════════════════════════════════════════════════════
    # SUSPICIOUS FILES — with hash cache for speed
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
                    _fstr = str(f).lower()
                    # Skip known safe subdirectory patterns
                    if any(skip in _fstr for skip in (
                        'node_modules', '\\cache', '/cache', '.git',
                        '__pycache__', '.venv', 'site-packages',
                        '/tmp/_mei', '/tmp/.mount_',   # PyInstaller / AppImage
                    )):
                        continue
                    try:
                        if f.stat().st_size > 50_000_000:
                            continue
                    except (OSError, PermissionError):
                        continue

                    if f.suffix.lower() not in DANGEROUS_EXTENSIONS:
                        continue

                    try:
                        # Hash cache: skip if file unchanged since last scan
                        fpath_str = str(f)
                        old_hash  = self._hash_cache.get(fpath_str)
                        new_hash  = _exe_sha256(fpath_str)
                        if new_hash and old_hash == new_hash:
                            continue   # file unchanged — skip full text scan
                        if new_hash:
                            self._hash_cache[fpath_str] = new_hash
                            self._hash_dirty = True

                        txt = f.read_text(errors='ignore')[:4096]
                        for pattern, desc in SUSPICIOUS_SCRIPTS:
                            if re.search(pattern, txt, re.I):
                                # Score the file too (for consistency)
                                file_score = 70   # script pattern match = already suspicious
                                if _fstr.startswith(('/tmp', '/dev/shm', '/var/tmp')):
                                    file_score += 10
                                # Check user whitelist
                                if fpath_str.lower() in self._user_wl:
                                    file_score = max(0, file_score - 50)
                                if file_score >= 40:
                                    fix_cmd = (
                                        f'sudo -n {HELPER} remove-file "{f}"'
                                        if OS == 'Linux' else f'del /f /q "{f}"'
                                    )
                                    self.results.append(ScanResult(
                                        'critical', 'malware', str(f), desc,
                                        can_fix=True, fix_cmd=fix_cmd,
                                        score=file_score,
                                    ))
                                    log_cb(f'  ⛔  Malicious script [{file_score}/100]: {f.name} — {desc}', 'err')
                                    found += 1
                                break

                        # Executable in /tmp (Linux) — score it
                        if OS == 'Linux' and str(f).startswith('/tmp'):
                            try:
                                if f.stat().st_mode & stat.S_IXUSR:
                                    self.results.append(ScanResult(
                                        'medium', 'suspicious', str(f),
                                        f'Executable file in /tmp: {f.name}',
                                        score=35,
                                    ))
                                    log_cb(f'  ~  Exec in /tmp: {f.name}', 'warn')
                                    found += 1
                            except (OSError, PermissionError):
                                pass

                    except (OSError, PermissionError, UnicodeDecodeError):
                        pass
            except (OSError, PermissionError):
                pass

        if found == 0:
            log_cb('  ✓  No suspicious files found', 'ok')

    # ══════════════════════════════════════════════════════
    # LD_PRELOAD / rootkit indicator (Linux)
    # ══════════════════════════════════════════════════════

    def _scan_ld_preload(self, log_cb):
        log_cb('', 'info')
        log_cb('◆ Checking LD_PRELOAD / dynamic linker hijacks...', 'info')
        found = 0
        p = Path('/etc/ld.so.preload')
        if p.exists() and p.stat().st_size > 0:
            content = p.read_text(errors='ignore').strip()
            self.results.append(ScanResult(
                'critical', 'malware', str(p),
                f'LD_PRELOAD set globally: {content}',
                score=95,
            ))
            log_cb(f'  ⛔  /etc/ld.so.preload has entries: {content}', 'err')
            found += 1
        env_preload = os.environ.get('LD_PRELOAD', '')
        if env_preload:
            self.results.append(ScanResult(
                'high', 'malware', '$LD_PRELOAD',
                f'LD_PRELOAD env: {env_preload}',
                score=70,
            ))
            log_cb(f'  ⚠  LD_PRELOAD env set: {env_preload}', 'warn')
            found += 1
        if found == 0:
            log_cb('  ✓  No LD_PRELOAD hijacks detected', 'ok')

    # ══════════════════════════════════════════════════════
    # SSH AUTHORIZED KEYS
    # ══════════════════════════════════════════════════════

    def _scan_ssh_authorized_keys(self, log_cb):
        log_cb('', 'info')
        log_cb('◆ Checking SSH authorized_keys...', 'info')
        ak = Path.home() / '.ssh/authorized_keys'
        if not ak.exists():
            log_cb('  ✓  No authorized_keys file', 'ok')
            return

        lines = [
            l.strip() for l in ak.read_text(errors='ignore').splitlines()
            if l.strip() and not l.startswith('#')
        ]
        if not lines:
            log_cb('  ✓  No SSH authorized keys', 'ok')
            return

        KNOWN_KEY_TYPES = (
            'ssh-rsa', 'ssh-ed25519', 'ecdsa-sha2-nistp256',
            'ecdsa-sha2-nistp384', 'ecdsa-sha2-nistp521',
            'sk-ssh-ed25519@openssh.com', 'sk-ecdsa-sha2-nistp256@openssh.com',
        )
        log_cb(f'  ✓  {len(lines)} SSH authorized key(s) found', 'ok')
        for i, line in enumerate(lines[:3]):
            log_cb(f'     key {i+1}: ...{line[-40:]}', 'dim')

        for line in lines:
            if re.match(r'command\s*=', line, re.I):
                self.results.append(ScanResult(
                    'high', 'suspicious', str(ak),
                    f'Forced-command key (remote code exec risk): ...{line[-50:]}',
                    score=65,
                ))
                log_cb(f'  ⚠  Forced-command SSH key detected', 'warn')
            elif (not any(line.startswith(kt) for kt in KNOWN_KEY_TYPES) and
                  not re.match(r'(no-|from=|environment=|permitopen=|restrict)', line, re.I)):
                self.results.append(ScanResult(
                    'medium', 'suspicious', str(ak),
                    f'Unrecognised key format: ...{line[-50:]}',
                    score=40,
                ))
                log_cb(f'  ~  Unrecognised SSH key format', 'warn')

    # ══════════════════════════════════════════════════════
    # /etc/hosts TAMPERING
    # ══════════════════════════════════════════════════════

    def _scan_hosts_file(self, log_cb):
        log_cb('', 'info')
        log_cb('◆ Checking /etc/hosts for tampering...', 'info')
        if OS == 'Linux':
            hosts_path = Path('/etc/hosts')
        else:
            windir     = os.environ.get('WINDIR', 'C:/Windows')
            hosts_path = Path(f'{windir}/System32/drivers/etc/hosts')
        if not hosts_path.exists():
            log_cb('  ~ hosts file not found', 'dim')
            return
        suspicious_domains = [
            'google.com', 'facebook.com', 'github.com', 'microsoft.com',
            'apple.com', 'amazon.com', 'paypal.com', 'bankofamerica.com',
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
            if ip in ('127.0.0.1', '::1', '0.0.0.0'):
                continue   # ad blockers legitimately redirect to localhost — skip
            for d in domains:
                if any(sd in d for sd in suspicious_domains):
                    self.results.append(ScanResult(
                        'high', 'malware', str(hosts_path),
                        f'Suspicious hosts redirect: {line}',
                        score=80,
                    ))
                    log_cb(f'  ⚠  Hosts hijack: {line}', 'warn')
                    found += 1
        if found == 0:
            log_cb('  ✓  hosts file looks clean', 'ok')

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
        # Keywords that are highly suspicious in autorun values
        suspicious_kw = [
            'temp', 'appdata\\local\\temp', '%temp%',
            'powershell -enc', 'cmd /c', 'wscript', 'cscript',
            'mshta', 'regsvr32', 'certutil', 'bitsadmin',
            '/dev/shm', '/tmp/',
        ]
        found = 0
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
                                # Score the autorun entry
                                ar_score = 50
                                if 'powershell -enc' in val_lower or 'certutil' in val_lower:
                                    ar_score = 75
                                if val_lower.startswith(('c:/windows/', 'c:\\windows\\')):
                                    ar_score = max(0, ar_score - 20)

                                self.results.append(ScanResult(
                                    'high' if ar_score >= 70 else 'medium',
                                    'malware', val,
                                    f'Suspicious autorun [{ar_score}/100]: {name} = {val}',
                                    score=ar_score,
                                ))
                                log_cb(f'  ⚠  Suspicious autorun [{ar_score}/100]: {name}', 'warn')
                                log_cb(f'     {val}', 'dim')
                                found += 1
                                break
                        i += 1
                    except OSError:
                        break
                winreg.CloseKey(key)
            except (OSError, PermissionError):
                pass
        if found == 0:
            log_cb('  ✓  No suspicious autoruns', 'ok')
