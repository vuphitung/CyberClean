"""Windows-only cache service. Consumers never advance sampling baselines.

Fast counters: 1 s. Processes/disks: 5 s, independent worker. All rates use
monotonic time. Process CPU is 0–100% of the whole machine, not one core.
"""
import atexit
import ctypes
from copy import deepcopy
from functools import lru_cache
import logging
import os
import threading
import time
from typing import NamedTuple

log = logging.getLogger('cyberclean.telemetry')


class _PerformanceInformation(ctypes.Structure):
    _fields_ = [('cb', ctypes.c_uint32)] + [
        (name, ctypes.c_size_t) for name in (
            'CommitTotal', 'CommitLimit', 'CommitPeak', 'PhysicalTotal',
            'PhysicalAvailable', 'SystemCache', 'KernelTotal', 'KernelPaged',
            'KernelNonpaged', 'PageSize')
    ] + [(name, ctypes.c_uint32) for name in ('HandleCount', 'ProcessCount', 'ThreadCount')]


class CommitInfo(NamedTuple):
    used: int
    total: int
    percent: float


@lru_cache(maxsize=1)
def _performance_reader():
    reader = ctypes.WinDLL('psapi', use_last_error=True).GetPerformanceInfo
    reader.argtypes = [ctypes.POINTER(_PerformanceInformation), ctypes.c_uint32]
    reader.restype = ctypes.c_int
    return reader


def read_windows_commit():
    """System commit charge/limit in bytes, independent of psutil swap semantics.

    GetPerformanceInfo returns pages, including committed memory resident in RAM.
    This is Task Manager's Committed metric, not page-file occupancy.
    """
    info = _PerformanceInformation()
    info.cb = ctypes.sizeof(info)
    if not _performance_reader()(ctypes.byref(info), info.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    if not info.PageSize or not info.CommitLimit:
        raise ValueError('Windows returned no commit limit/page size')
    used, total = info.CommitTotal * info.PageSize, info.CommitLimit * info.PageSize
    return CommitInfo(used, total, 100.0 * used / total)


class NetworkSampler:
    """Per-interface raw counters. Loopback excluded; virtual NICs included/labeled."""
    def __init__(self):
        self.previous = {}

    def sample(self, counters, stats, now):
        result, previous = {}, {}
        for name, counter in counters.items():
            status = stats.get(name)
            if name.lower().startswith(('loopback', 'lo ')) or name == 'lo':
                continue
            up = status is not None and status.isup
            old = self.previous.get(name)
            sent, recv = counter.bytes_sent, counter.bytes_recv
            entry = dict(up_bps=None, down_bps=None, state='priming' if up else 'disconnected',
                         sent=sent, recv=recv, link_mbps=getattr(status, 'speed', None))
            if up:
                previous[name] = (sent, recv, now)
                if old and now > old[2]:
                    if sent >= old[0] and recv >= old[1]:
                        entry.update(up_bps=int((sent-old[0])/(now-old[2])),
                                     down_bps=int((recv-old[1])/(now-old[2])), state='fresh')
                    else:
                        entry['state'] = 'counter reset; priming'
            result[name] = entry
        self.previous = previous
        return result


def cpu_usage(previous, current):
    """Windows system includes DPC/interrupt time: total = user + system + idle."""
    if previous is None or len(previous) != len(current):
        return None, []
    totals, busy, cores = [], [], []
    for old, new in zip(previous, current):
        delta = [getattr(new, key)-getattr(old, key) for key in ('user', 'system', 'idle')]
        if min(delta) < 0 or sum(delta) <= 0:
            return None, []
        total = sum(delta)
        used = total-delta[2]
        totals.append(total); busy.append(used)
        cores.append(100*used/total)
    return (100*sum(busy)/sum(totals), cores) if totals else (None, [])


class WindowsTelemetry:
    def __init__(self, api=None, clock=time.monotonic, commit_reader=read_windows_commit):
        self._process_reader = None
        if api is None:
            import psutil
            api = psutil
            from utils.windows_process_snapshot import read_windows_processes
            self._process_reader = read_windows_processes
        from utils.sysinfo import SystemSnapshot
        self.api, self.clock, self.commit_reader = api, clock, commit_reader
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._snapshot = SystemSnapshot()
        self._snapshot.cpu_percent = None
        self._snapshot.ram_used = self._snapshot.ram_total = None
        self._snapshot.ram_percent = None
        self._snapshot.swap_percent = None
        self._snapshot.swap_used = self._snapshot.swap_total = None
        self._snapshot.net_up_bps = self._snapshot.net_down_bps = None
        self._snapshot.errors = {'cpu': 'priming', 'ram': 'not sampled', 'network': 'priming'}
        self._snapshot.network_interfaces = {}
        self._snapshot.ram_available = None
        self._snapshot.sample_time = 0.0
        self._cpu_previous = None
        self._network = NetworkSampler()
        self._process_previous = {}
        self._threads = []
        self._temperature = None

    def start(self):
        with self._lock:
            if self._threads or self._stop.is_set():
                return
            for name, target, interval in [('counters', self._fast, 1.0), ('inventory', self._slow, 5.0)]:
                thread = threading.Thread(target=self._loop, args=(target, interval),
                                          name='windows-'+name, daemon=True)
                self._threads.append(thread)
                thread.start()

    def _loop(self, target, interval):
        while not self._stop.is_set():
            started = self.clock()
            try:
                target()
            except Exception:
                log.exception('Telemetry worker %s failed', target.__name__)
            self._stop.wait(max(0.05, interval-(self.clock()-started)))

    def _fast(self):
        api, now = self.api, self.clock()
        updates, errors = {}, {}
        try:
            current = api.cpu_times(percpu=True)
            updates['cpu_percent'], updates['cpu_per_core'] = cpu_usage(self._cpu_previous, current)
            self._cpu_previous = current
            if updates['cpu_percent'] is None:
                errors['cpu'] = 'priming CPU baseline'
        except Exception as exc:
            updates.update(cpu_percent=None, cpu_per_core=[])
            self._cpu_previous = None
            errors['cpu'] = str(exc)
        try:
            ram = api.virtual_memory()
            updates.update(ram_used=ram.used, ram_total=ram.total, ram_percent=ram.percent,
                           ram_available=ram.available)
        except Exception as exc:
            updates.update(ram_percent=None, ram_available=None, ram_used=None, ram_total=None)
            errors['ram'] = str(exc)
        try:
            swap = self.commit_reader()
            updates.update(swap_used=swap.used, swap_total=swap.total, swap_percent=swap.percent)
        except Exception as exc:
            updates.update(swap_percent=None, swap_used=None, swap_total=None)
            errors['swap'] = str(exc)
        try:
            interfaces = self._network.sample(api.net_io_counters(pernic=True, nowrap=False), api.net_if_stats(), now)
            updates['network_interfaces'] = interfaces
            active = [e for e in interfaces.values() if e['state'] != 'disconnected']
            if active and all(e['state'] == 'fresh' for e in active):
                updates['net_up_bps'] = sum(e['up_bps'] for e in active)
                updates['net_down_bps'] = sum(e['down_bps'] for e in active)
            else:
                updates['net_up_bps'] = updates['net_down_bps'] = None
                errors['network'] = 'priming/reset' if active else 'no connected interfaces'
            updates['net_sent'] = sum(e['sent'] for e in interfaces.values())
            updates['net_recv'] = sum(e['recv'] for e in interfaces.values())
        except Exception as exc:
            self._network.previous = {}
            updates.update(net_up_bps=None, net_down_bps=None, network_interfaces={})
            errors['network'] = str(exc)
        try:
            updates['uptime_seconds'] = int(time.time()-api.boot_time())
        except Exception as exc:
            errors['uptime'] = str(exc)
        with self._lock:
            for name, value in updates.items():
                setattr(self._snapshot, name, value)
            self._snapshot.errors = {**{k:v for k,v in self._snapshot.errors.items()
                                       if k in ('inventory',)}, **errors}
            self._snapshot.sample_time = now

    def _slow(self):
        from utils.sysinfo import ProcessInfo, DiskInfo, _is_kernel_or_skipped_proc, _strip_exe
        api, now = self.api, self.clock()
        procs, previous, disks, errors = [], {}, [] , []
        ncpus = api.cpu_count() or 1
        try:
            records = None
            physical_total = None
            if self._process_reader is not None:
                try:
                    records = self._process_reader()
                    physical_total = api.virtual_memory().total
                except Exception as exc:
                    errors.append(f'native process inventory unavailable; psutil fallback: {exc}')
            if records is None:
                # status() enumerates all threads for each process on Windows;
                # the dashboard does not display it, so do not request it.
                records = (p.info for p in api.process_iter([
                    'pid', 'name', 'create_time', 'cpu_times', 'memory_percent']))
            for info in records:
                try:
                    # A different Python workload is a real process. The shared
                    # legacy skip list hides every interpreter by name.
                    interpreter = _strip_exe(str(info['name'] or '')) in ('python', 'python3', 'py')
                    if info['pid'] == os.getpid() or (not interpreter and
                            _is_kernel_or_skipped_proc(info['pid'], info['name'])):
                        continue
                    memory_percent = (100*info['memory_rss']/physical_total if physical_total else
                                      info.get('memory_percent'))
                    if info['create_time'] is None or info['cpu_times'] is None or memory_percent is None:
                        continue
                    identity = (info['pid'], info['create_time'])
                    times = info['cpu_times']
                    total = times.user+times.system
                    old = self._process_previous.get(identity)
                    cpu = None
                    if old and now > old[1] and total >= old[0]:
                        cpu = min(100., 100*(total-old[0])/(now-old[1])/ncpus)
                    previous[identity] = (total, now)
                    procs.append(ProcessInfo(info['pid'], info['name'], cpu,
                                             memory_percent, 'unknown'))
                except (api.NoSuchProcess, api.AccessDenied):
                    continue
            self._process_previous = previous
        except Exception as exc:
            self._process_previous = {}
            errors.append(f'processes: {exc}')
        try:
            seen = set()
            for part in api.disk_partitions(all=False):
                key = part.device.lower()
                if key in seen:
                    continue
                seen.add(key)
                try:
                    usage = api.disk_usage(part.mountpoint)
                    disks.append(DiskInfo(part.mountpoint, usage.total, usage.used, usage.free, usage.percent))
                except OSError as exc:
                    errors.append(f'disk {part.mountpoint}: {exc}')
        except Exception as exc:
            errors.append(f'disks: {exc}')
        with self._lock:
            s = self._snapshot
            s.top_cpu_procs = sorted(procs, key=lambda p: p.cpu if p.cpu is not None else -1, reverse=True)[:8]
            s.top_mem_procs = sorted(procs, key=lambda p: p.mem or 0, reverse=True)[:8]
            s.disks = disks
            s.inventory_time = now
            if errors:
                s.errors['inventory'] = '; '.join(errors)
            else:
                s.errors.pop('inventory', None)

    def snapshot(self):
        with self._lock:
            s = deepcopy(self._snapshot)
        if self._stop.is_set() or self.clock()-s.sample_time > 3:
            s.cpu_percent = s.ram_percent = s.swap_percent = None
            s.cpu_per_core = []
            s.ram_used = s.ram_total = s.ram_available = None
            s.swap_used = s.swap_total = None
            s.net_up_bps = s.net_down_bps = None
            for interface in s.network_interfaces.values():
                interface.update(up_bps=None, down_bps=None, state='unavailable/stale')
            s.errors['service'] = 'closed' if self._stop.is_set() else 'counters unavailable/stale'
        if self.clock()-getattr(s, 'inventory_time', 0) > 15:
            s.disks = []; s.top_cpu_procs = []; s.top_mem_procs = []
            s.errors['inventory'] = 'inventory unavailable/stale'
        if self._temperature is not None:
            temp = self._temperature.snapshot()
            s.temp_all, s.temp_max = temp['readings'], temp['cpu']
            s.temperature_status = temp
        return s

    def close(self):
        self._stop.set()
        if self._temperature:
            self._temperature.close()
        for thread in self._threads:
            thread.join(timeout=1.5)
            if thread.is_alive():
                log.error('Worker did not finish: %s (no force termination)', thread.name)


_service = None
_service_lock = threading.Lock()


def get_windows_snapshot():
    global _service
    with _service_lock:
        if _service is None:
            _service = WindowsTelemetry()
            from utils.windows_temperature import TemperatureHost
            _service._temperature = TemperatureHost()
            _service._temperature.start()
            _service.start()
            atexit.register(_service.close)
        service = _service
    return service.snapshot()


def request_windows_temperature_access():
    """Switch only the temperature sampler to the protected read-only helper."""
    if os.name != 'nt':
        return False
    get_windows_snapshot()  # ensure the service and sensor supervisor exist
    with _service_lock:
        service = _service
    return bool(service and service._temperature and
                service._temperature.request_privileged_access())


def close_windows_telemetry():
    if _service is not None:
        _service.close()
