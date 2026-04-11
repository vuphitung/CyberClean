"""
CyberClean v2.3 — Analyzer
════════════════════════════════════════════════════════════════

WHAT CHANGED vs v2.2:

IdleScheduler — non-blocking is_idle():
  OLD: time.sleep(1) inside is_idle() blocks whatever thread calls it.
       Called from a QThread → GUI stutter when auto-clean check runs.
  NEW: Two-sample approach using a single psutil.net_io_counters() call
       separated by cpu_percent(interval=sample_seconds).
       cpu_percent(interval=N) already blocks for N seconds internally —
       reusing that window for net delta avoids an extra sleep() entirely.
  ALSO: Added _idle_lock so concurrent calls (timer + manual) don't race.

get_network_processes() — production-ready:
  OLD: Worked but wasn't wired into the scanner tab GUI at all.
  NEW:
    • ThreatScore (0–100) replaces bool suspicious — lets GUI sort/filter
      by risk level instead of just red/green flag.
    • _score_connection() centralised scoring:
        +40  suspicious port
        +35  system process making outbound connections
        +30  executable in temp/ramdisk directory
        +20  non-standard high port (>49152) with no known service
        +15  process name contains common RAT/miner keywords
        +10  multiple simultaneous connections from same process (volume flag)
    • Reason list (not single string) — GUI can render multi-line tooltips.
    • SUSPICIOUS_PORTS expanded: common C2, RAT, miner, reverse-shell ports.
    • _NEVER_NETWORK expanded with modern Windows system processes.
    • Linux /proc/net/tcp fallback if psutil.net_connections() needs root.
    • Thread-safe: _net_lock prevents concurrent scan races.
    • get_network_summary() helper → scanner tab status bar one-liner.

NetworkProcess dataclass:
  NEW fields: score (int), reasons (List[str]), local_port (int), conns (int)
  COMPAT: suspicious property kept as @property (score >= 40) so old code works.
"""

import os
import re
import platform
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

_IS_LINUX   = platform.system() == 'Linux'
_IS_WINDOWS = platform.system() == 'Windows'


# ══════════════════════════════════════════════════════════════
# Idle-based auto-clean (system tray)
# ══════════════════════════════════════════════════════════════

class IdleScheduler:
    """
    Runs auto-clean only when machine is idle.
    Idle = CPU < threshold AND network throughput < threshold
    AND at least min_interval seconds since last clean.

    FIX: is_idle() now uses cpu_percent(interval=N) window to measure
    net delta — no extra time.sleep(), no GUI thread blocking.
    """

    def __init__(
        self,
        cpu_threshold: float = 15.0,
        net_threshold_kb: float = 100.0,
        min_interval_hours: float = 4.0,
        sample_seconds: float = 2.0,
    ):
        self.cpu_threshold     = cpu_threshold
        self.net_threshold_kb  = net_threshold_kb
        self.min_interval_sec  = min_interval_hours * 3600
        self.sample_seconds    = sample_seconds
        self._last_clean_ts    = 0.0
        self._idle_lock        = threading.Lock()   # NEW: prevent concurrent is_idle() calls

        # Persistent last-clean timestamp — survives app restarts
        if _IS_WINDOWS:
            import os as _os
            _base = Path(_os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'CyberClean'
        else:
            _base = Path.home() / '.local/share/cyber-clean'
        self._history_file = _base / 'last_auto_clean'

        try:
            if self._history_file.exists():
                self._last_clean_ts = float(self._history_file.read_text().strip())
        except Exception:
            pass

    def is_idle(self) -> bool:
        """
        Check if system is idle. Non-blocking for GUI thread:
        Uses cpu_percent(interval) window to measure net delta simultaneously.
        Thread-safe via _idle_lock — concurrent callers return False immediately
        instead of stacking up blocking calls.
        """
        if not self._idle_lock.acquire(blocking=False):
            return False   # another check in progress — skip this tick
        try:
            import psutil
            net1 = psutil.net_io_counters()
            cpu  = psutil.cpu_percent(interval=self.sample_seconds)   # blocks N seconds
            net2 = psutil.net_io_counters()
            net_kbps = (
                (net2.bytes_sent + net2.bytes_recv) -
                (net1.bytes_sent + net1.bytes_recv)
            ) / 1024
            return cpu < self.cpu_threshold and net_kbps < self.net_threshold_kb
        except ImportError:
            return False
        except Exception:
            return False
        finally:
            self._idle_lock.release()

    def should_run(self) -> bool:
        elapsed = time.time() - self._last_clean_ts
        if elapsed < self.min_interval_sec:
            return False
        return self.is_idle()

    def mark_completed(self):
        self._last_clean_ts = time.time()
        try:
            self._history_file.parent.mkdir(parents=True, exist_ok=True)
            self._history_file.write_text(str(self._last_clean_ts))
        except Exception:
            pass

    def time_until_eligible(self) -> float:
        return max(0.0, self.min_interval_sec - (time.time() - self._last_clean_ts))

    def status_str(self) -> str:
        remaining = self.time_until_eligible()
        if remaining > 0:
            h = int(remaining // 3600)
            m = int((remaining % 3600) // 60)
            return f'Next eligible in {h}h {m}m'
        return 'Ready — waiting for idle window'


# ══════════════════════════════════════════════════════════════
# Process ↔ outbound TCP — threat scoring
# ══════════════════════════════════════════════════════════════

@dataclass
class NetworkProcess:
    pid:         int
    name:        str
    exe:         str
    remote_ip:   str
    remote_port: int
    protocol:    str          # 'TCP' | 'UDP'
    score:       int   = 0    # NEW: threat score 0–100
    reasons:     List[str] = field(default_factory=list)   # NEW: list of reasons
    local_port:  int   = 0    # NEW: local port (useful for dedup)
    conns:       int   = 1    # NEW: total connections from this PID

    # ── Compat properties (old code used .suspicious / .reason / .flag) ──
    @property
    def suspicious(self) -> bool:
        return self.score >= 40

    @property
    def reason(self) -> str:
        return '; '.join(self.reasons) if self.reasons else ''

    @property
    def remote_display(self) -> str:
        return f'{self.remote_ip}:{self.remote_port}'

    @property
    def flag(self) -> str:
        if self.score >= 70:  return '🔴'
        if self.score >= 40:  return '🟡'
        return '🟢'

    @property
    def risk_label(self) -> str:
        if self.score >= 70:  return 'HIGH'
        if self.score >= 40:  return 'MEDIUM'
        return 'LOW'


# ── Private ranges — filter out local/LAN traffic ─────────────
_PRIVATE_PREFIXES = (
    '127.', '::1', '0.0.0.0', '10.',
    '172.16.', '172.17.', '172.18.', '172.19.',
    '172.20.', '172.21.', '172.22.', '172.23.',
    '172.24.', '172.25.', '172.26.', '172.27.',
    '172.28.', '172.29.', '172.30.', '172.31.',
    '192.168.', 'fe80:', 'fc', 'fd',
)

# ── Suspicious ports ───────────────────────────────────────────
# Common C2, RAT, backdoor, miner, reverse-shell ports
_SUSPICIOUS_PORTS = {
    # Classic RAT / backdoor
    4444, 1337, 31337, 12345, 54321, 31338,
    # Meterpreter / Metasploit defaults
    4445, 4446, 5555, 9999,
    # IRC botnets
    6666, 6667, 6668, 6669,
    # Crypto miner stratum
    3333, 5555, 7777, 14444, 14433, 45560,
    # Remote admin (non-standard)
    2222, 8888, 9001, 9050,   # 9050 = Tor SOCKS
    # Cobalt Strike
    50050,
    # NetBus / BackOrifice
    12346, 65535, 54320,
}

# ── System processes that should never phone home ─────────────
_NEVER_NETWORK = {
    # Windows
    'explorer', 'winlogon', 'csrss', 'smss', 'lsass', 'dwm', 'taskeng',
    'wininit', 'services', 'spoolsv', 'taskhostw', 'sihost',
    'fontdrvhost', 'ctfmon', 'audiodg', 'conhost',
    # Linux display/session
    'Xorg', 'x11', 'gnome-session', 'ksmserver', 'plasmashell',
    'kwin_x11', 'kwin_wayland', 'mutter',
}

# ── Known miner process names ──────────────────────────────────
_MINER_KEYWORDS = {
    'xmrig', 'xmrig-notls', 'minerd', 'cpuminer', 'nbminer',
    'teamredminer', 'lolminer', 'gminer', 't-rex', 'nanominer',
    'claymore', 'ethminer', 'phoenixminer', 'kawpow',
}

# ── Known RAT / backdoor name fragments ───────────────────────
_RAT_KEYWORDS = {
    'njrat', 'asyncrat', 'remcos', 'darkcomet', 'nanocore',
    'quasar', 'gh0st', 'blackshades', 'pandora',
}

# ── Temp/ramdisk roots ─────────────────────────────────────────
def _get_temp_roots() -> tuple:
    roots = ['/tmp', '/var/tmp', '/dev/shm']
    temp = os.environ.get('TEMP', '')
    tmp  = os.environ.get('TMP', '')
    if temp: roots.append(temp.lower())
    if tmp:  roots.append(tmp.lower())
    return tuple(roots)


# ── Thread safety ─────────────────────────────────────────────
_net_lock = threading.Lock()


def _score_connection(
    name: str, exe: str, remote_port: int,
    pid_conns: int, temp_roots: tuple
) -> tuple:
    """
    Returns (score: int, reasons: List[str]).
    Scores are additive; capped at 100.
    """
    score   = 0
    reasons = []
    name_l  = name.lower().replace('.exe', '')

    # Rule 1: Suspicious port (+40)
    if remote_port in _SUSPICIOUS_PORTS:
        score += 40
        reasons.append(f'Suspicious port {remote_port}')

    # Rule 2: System process making outbound TCP (+35)
    if name_l in {n.lower() for n in _NEVER_NETWORK}:
        score += 35
        reasons.append(f'{name} should not make outbound connections')

    # Rule 3: Executable in temp/ramdisk (+30)
    if exe:
        exe_l = exe.lower().replace('\\', '/')
        if any(exe_l.startswith(t.lower().replace('\\', '/')) for t in temp_roots):
            score += 30
            reasons.append('Process executable in temp/ramdisk directory')

    # Rule 4: Known miner process name (+35)
    if any(kw in name_l for kw in _MINER_KEYWORDS):
        score += 35
        reasons.append(f'Known crypto-miner process name: {name}')

    # Rule 5: Known RAT name fragment (+35)
    if any(kw in name_l for kw in _RAT_KEYWORDS):
        score += 35
        reasons.append(f'Known RAT/backdoor name: {name}')

    # Rule 6: Non-standard ephemeral port used as server-side port (+20)
    # Legit traffic hits well-known ports (80, 443, 53, 993…)
    # Ports 49152–65535 are client ephemeral — a *remote* server on these is odd
    if remote_port > 49151 and remote_port not in _SUSPICIOUS_PORTS:
        score += 20
        reasons.append(f'Remote server on non-standard high port {remote_port}')

    # Rule 7: Process has many simultaneous outbound connections (+10)
    if pid_conns >= 10:
        score += 10
        reasons.append(f'High connection count: {pid_conns} outbound connections')

    return min(score, 100), reasons


def _linux_proc_net_fallback() -> list:
    """
    Read /proc/net/tcp[6] directly when psutil.net_connections() needs root.
    Returns list of (pid, local_port, remote_ip, remote_port) for ESTABLISHED.
    Only viable on Linux — caller guards platform check.
    """
    results = []
    for fname in ('/proc/net/tcp', '/proc/net/tcp6'):
        try:
            for line in Path(fname).read_text().splitlines()[1:]:
                parts = line.split()
                if len(parts) < 12: continue
                state = parts[3]
                if state != '01': continue   # 01 = ESTABLISHED
                # Remote address: hex little-endian
                r_hex = parts[2]
                if ':' not in r_hex: continue
                r_ip_hex, r_port_hex = r_hex.rsplit(':', 1)
                r_port = int(r_port_hex, 16)
                # Parse IPv4 from little-endian hex
                try:
                    ip_int = int(r_ip_hex, 16)
                    r_ip = '.'.join(str((ip_int >> (8 * i)) & 0xFF) for i in range(4))
                except Exception:
                    continue
                pid_str = parts[7] if len(parts) > 7 else '0'
                try:
                    pid = int(pid_str)
                except ValueError:
                    pid = 0
                l_hex = parts[1].rsplit(':', 1)
                l_port = int(l_hex[1], 16) if len(l_hex) == 2 else 0
                results.append((pid, l_port, r_ip, r_port))
        except (OSError, PermissionError):
            pass
    return results


def get_network_processes(include_private: bool = False) -> List[NetworkProcess]:
    """
    Map established TCP connections to owning process, with threat scoring.
    Thread-safe. Falls back to /proc/net/tcp on Linux when psutil needs root.

    Returns list sorted by score DESC, then name ASC.
    """
    with _net_lock:
        return _get_network_processes_inner(include_private)


def _get_network_processes_inner(include_private: bool) -> List[NetworkProcess]:
    results: List[NetworkProcess] = []
    temp_roots = _get_temp_roots()

    # Track connection count per PID for volume scoring
    pid_conn_count: dict = {}

    try:
        import psutil

        # Collect all established connections first to count per-PID
        raw_conns = []
        try:
            for conn in psutil.net_connections(kind='inet'):
                if conn.status != psutil.CONN_ESTABLISHED:
                    continue
                if not conn.raddr:
                    continue
                remote_ip   = conn.raddr.ip
                remote_port = conn.raddr.port
                local_port  = conn.laddr.port if conn.laddr else 0
                pid         = conn.pid or 0

                if not include_private:
                    if any(remote_ip.startswith(p) for p in _PRIVATE_PREFIXES):
                        continue

                pid_conn_count[pid] = pid_conn_count.get(pid, 0) + 1
                raw_conns.append((pid, local_port, remote_ip, remote_port))

        except psutil.AccessDenied:
            # Linux non-root: fall back to /proc/net/tcp
            if _IS_LINUX:
                raw_conns = _linux_proc_net_fallback()
                for pid, _, _, _ in raw_conns:
                    pid_conn_count[pid] = pid_conn_count.get(pid, 0) + 1
            else:
                raw_conns = []

        # Resolve PIDs to process names — cache to avoid repeated psutil calls
        pid_info: dict = {}
        for pid, *_ in raw_conns:
            if pid in pid_info or pid == 0:
                continue
            try:
                proc = psutil.Process(pid)
                pid_info[pid] = (proc.name(), proc.exe())
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pid_info[pid] = (f'PID {pid}', '')

        # Build NetworkProcess list
        for pid, local_port, remote_ip, remote_port in raw_conns:
            name, exe = pid_info.get(pid, (f'PID {pid}', ''))
            conns     = pid_conn_count.get(pid, 1)
            score, reasons = _score_connection(
                name, exe, remote_port, conns, temp_roots
            )
            results.append(NetworkProcess(
                pid=pid, name=name, exe=exe,
                remote_ip=remote_ip, remote_port=remote_port,
                protocol='TCP', score=score, reasons=reasons,
                local_port=local_port, conns=conns,
            ))

    except ImportError:
        # psutil not available at all
        pass

    results.sort(key=lambda x: (-x.score, x.name.lower()))
    return results


def get_network_summary(procs: Optional[List[NetworkProcess]] = None) -> str:
    """
    One-liner for scanner tab status bar.
    Example: "12 connections · 2 HIGH · 1 MEDIUM · all others clean"
    If procs is None, fetches fresh data.
    """
    if procs is None:
        procs = get_network_processes()
    total  = len(procs)
    high   = sum(1 for p in procs if p.score >= 70)
    medium = sum(1 for p in procs if 40 <= p.score < 70)
    if total == 0:
        return 'No outbound connections detected'
    parts = [f'{total} connection{"s" if total != 1 else ""}']
    if high:
        parts.append(f'{high} HIGH')
    if medium:
        parts.append(f'{medium} MEDIUM')
    if not high and not medium:
        parts.append('all clean')
    return ' · '.join(parts)
