"""
CyberClean — tray idle scheduling + network connection view for the security scanner.
(Former duplicate/SMART/HTML-report code lived here but was never wired into the GUI.)
"""
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List


# ══════════════════════════════════════════════════════════════
# Idle-based auto-clean (system tray)
# ══════════════════════════════════════════════════════════════


class IdleScheduler:
    """
    Runs auto-clean only when machine is idle.
    Idle = CPU < threshold AND network throughput < threshold
    AND at least min_interval seconds since last clean.
    """

    def __init__(
        self,
        cpu_threshold: float = 15.0,
        net_threshold_kb: float = 100.0,
        min_interval_hours: float = 4.0,
        sample_seconds: float = 3.0,
    ):
        self.cpu_threshold = cpu_threshold
        self.net_threshold_kb = net_threshold_kb
        self.min_interval_sec = min_interval_hours * 3600
        self.sample_seconds = sample_seconds
        self._last_clean_ts = 0.0
        self._history_file = Path.home() / '.local/share/cyber-clean/last_auto_clean'

        try:
            if self._history_file.exists():
                self._last_clean_ts = float(self._history_file.read_text().strip())
        except Exception:
            pass

    def is_idle(self) -> bool:
        try:
            import psutil

            cpu = psutil.cpu_percent(interval=self.sample_seconds)
            net1 = psutil.net_io_counters()
            time.sleep(1)
            net2 = psutil.net_io_counters()
            net_kbps = (
                (net2.bytes_sent + net2.bytes_recv)
                - (net1.bytes_sent + net1.bytes_recv)
            ) / 1024
            return cpu < self.cpu_threshold and net_kbps < self.net_threshold_kb
        except ImportError:
            return False

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
# Process ↔ outbound TCP (scanner tab)
# ══════════════════════════════════════════════════════════════


@dataclass
class NetworkProcess:
    pid: int
    name: str
    exe: str
    remote_ip: str
    remote_port: int
    protocol: str  # 'TCP' | 'UDP'
    suspicious: bool = False
    reason: str = ''

    @property
    def remote_display(self) -> str:
        return f'{self.remote_ip}:{self.remote_port}'

    @property
    def flag(self) -> str:
        return '🔴' if self.suspicious else '🟢'


_PRIVATE_PREFIXES = (
    '127.',
    '::1',
    '0.0.0.0',
    '10.',
    '172.16.',
    '172.17.',
    '172.18.',
    '172.19.',
    '172.20.',
    '172.21.',
    '172.22.',
    '172.23.',
    '172.24.',
    '172.25.',
    '172.26.',
    '172.27.',
    '172.28.',
    '172.29.',
    '172.30.',
    '172.31.',
    '192.168.',
    'fe80:',
    'fc',
    'fd',
)

_SUSPICIOUS_PORTS = {
    4444, 1337, 31337, 12345, 54321, 9001, 6666, 6667, 31338, 2222,
}

_NEVER_NETWORK = {
    'explorer', 'winlogon', 'csrss', 'smss', 'lsass', 'dwm', 'taskeng',
}


def get_network_processes(include_private: bool = False) -> List[NetworkProcess]:
    """
    Map established TCP connections to owning process.
    Filters localhost/private ranges by default; flags odd ports / temp-dir exes.
    """
    results: List[NetworkProcess] = []
    try:
        import psutil

        for conn in psutil.net_connections(kind='inet'):
            if conn.status != psutil.CONN_ESTABLISHED:
                continue
            if not conn.raddr:
                continue

            remote_ip = conn.raddr.ip
            remote_port = conn.raddr.port

            if not include_private:
                if any(remote_ip.startswith(p) for p in _PRIVATE_PREFIXES):
                    continue

            try:
                proc = psutil.Process(conn.pid)
                name = proc.name()
                exe = proc.exe()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                name = f'PID {conn.pid}'
                exe = ''

            suspicious = False
            reason = ''

            if remote_port in _SUSPICIOUS_PORTS:
                suspicious = True
                reason = f'Suspicious port {remote_port}'

            name_lower = name.lower().replace('.exe', '')
            if name_lower in _NEVER_NETWORK:
                suspicious = True
                reason = f'{name} should not make outbound connections'

            temp_roots = [
                t
                for t in ('/tmp', '/var/tmp', os.environ.get('TEMP', '').lower())
                if t
            ]
            if exe and any(exe.lower().startswith(t) for t in temp_roots):
                suspicious = True
                reason = 'Process executable in temp dir'

            results.append(
                NetworkProcess(
                    pid=conn.pid,
                    name=name,
                    exe=exe,
                    remote_ip=remote_ip,
                    remote_port=remote_port,
                    protocol='TCP',
                    suspicious=suspicious,
                    reason=reason,
                )
            )

    except ImportError:
        pass

    results.sort(key=lambda x: (not x.suspicious, x.name.lower()))
    return results
