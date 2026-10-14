"""
CyberClean — Analyzer
════════════════════════════════════════════════════════════════
Idle-based auto-clean scheduling.

IdleScheduler — non-blocking is_idle():
  Two-sample approach using a single psutil.net_io_counters() call
  separated by cpu_percent(interval=sample_seconds).
  cpu_percent(interval=N) already blocks for N seconds internally —
  reusing that window for net delta avoids an extra sleep() entirely.
  _idle_lock ensures concurrent calls (timer + manual) don't race.

NOTE: this module previously also contained network-process threat
scoring (get_network_processes / get_network_summary / NetworkProcess),
used only by the Security Scanner's network tab. That feature has been
removed from CyberClean; the scoring code was removed along with it.
"""

import threading
import time
import platform
from pathlib import Path

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

