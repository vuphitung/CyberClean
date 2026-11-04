"""Read-only telemetry comparison with independent Win32 counter calls.

Run from the source root: python tools/windows_metrics_check.py --output report.json
No cleanup, priority changes, driver loading, or temperature host is performed.
"""
import argparse
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class MemoryStatus(ctypes.Structure):
    _fields_ = [('length', wintypes.DWORD), ('load', wintypes.DWORD)] + [
        (name, ctypes.c_ulonglong) for name in (
            'total_physical', 'available_physical', 'total_page_file',
            'available_page_file', 'total_virtual', 'available_virtual',
            'available_extended_virtual')]


class PerformanceInformation(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD)] + [
        (name, ctypes.c_size_t) for name in (
            'commit_total', 'commit_limit', 'commit_peak', 'physical_total',
            'physical_available', 'system_cache', 'kernel_total', 'kernel_paged',
            'kernel_nonpaged', 'page_size')
    ] + [(name, wintypes.DWORD) for name in ('handles', 'processes', 'threads')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=5)
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('This comparison requires native Windows')
    if args.samples < 2:
        parser.error('--samples must be at least 2')

    import psutil
    from utils.windows_telemetry import WindowsTelemetry
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    kernel.GetSystemTimes.argtypes = [ctypes.POINTER(wintypes.FILETIME)] * 3
    kernel.GetSystemTimes.restype = wintypes.BOOL
    kernel.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MemoryStatus)]
    kernel.GlobalMemoryStatusEx.restype = wintypes.BOOL
    kernel.GetTickCount64.restype = ctypes.c_ulonglong
    kernel.GetDiskFreeSpaceExW.argtypes = [wintypes.LPCWSTR] + [ctypes.POINTER(ctypes.c_ulonglong)] * 3
    kernel.GetDiskFreeSpaceExW.restype = wintypes.BOOL
    psapi.GetPerformanceInfo.argtypes = [ctypes.POINTER(PerformanceInformation), wintypes.DWORD]
    psapi.GetPerformanceInfo.restype = wintypes.BOOL

    def cpu_times():
        values = [wintypes.FILETIME() for _ in range(3)]
        if not kernel.GetSystemTimes(*(ctypes.byref(value) for value in values)):
            raise ctypes.WinError(ctypes.get_last_error())
        return [(value.dwHighDateTime << 32) | value.dwLowDateTime for value in values]

    service = WindowsTelemetry()
    service._slow()
    rows = []
    previous = None
    for index in range(args.samples):
        native_cpu = cpu_times()
        service._fast()
        snapshot = service.snapshot()
        memory = MemoryStatus()
        memory.length = ctypes.sizeof(memory)
        if not kernel.GlobalMemoryStatusEx(ctypes.byref(memory)):
            raise ctypes.WinError(ctypes.get_last_error())
        performance = PerformanceInformation()
        performance.size = ctypes.sizeof(performance)
        if not psapi.GetPerformanceInfo(ctypes.byref(performance), performance.size):
            raise ctypes.WinError(ctypes.get_last_error())
        cpu = None
        if previous is not None:
            idle, kernel_time, user = [now - old for now, old in zip(native_cpu, previous)]
            total = kernel_time + user
            cpu = 100 * (total - idle) / total if total else None
        previous = native_cpu
        native_commit = performance.commit_total * performance.page_size
        native_limit = performance.commit_limit * performance.page_size
        rows.append(dict(
            cpu_app=snapshot.cpu_percent, cpu_win32=cpu,
            cpu_difference_percentage_points=(abs(snapshot.cpu_percent - cpu) if cpu is not None else None),
            ram_total_app=snapshot.ram_total, ram_total_win32=memory.total_physical,
            ram_available_app=snapshot.ram_available, ram_available_win32=memory.available_physical,
            ram_available_difference_bytes=snapshot.ram_available - memory.available_physical,
            commit_used_app=snapshot.swap_used, commit_used_win32=native_commit,
            commit_limit_app=snapshot.swap_total, commit_limit_win32=native_limit,
            commit_difference_bytes=snapshot.swap_used - native_commit,
            uptime_app_seconds=snapshot.uptime_seconds, uptime_win32_seconds=kernel.GetTickCount64() / 1000,
            network_interfaces=snapshot.network_interfaces, errors=snapshot.errors))
        if index < args.samples - 1:
            time.sleep(1)

    service._slow()
    disks = []
    for disk in service.snapshot().disks:
        available, total, free = [ctypes.c_ulonglong() for _ in range(3)]
        if not kernel.GetDiskFreeSpaceExW(disk.path, ctypes.byref(available), ctypes.byref(total), ctypes.byref(free)):
            disks.append(dict(path=disk.path, error=str(ctypes.WinError(ctypes.get_last_error()))))
            continue
        disks.append(dict(path=disk.path, app_total=disk.total, win32_total=total.value,
                          app_used=disk.used, app_free=disk.free,
                          win32_available=available.value, win32_free=free.value,
                          free_difference_bytes=disk.free - available.value))
    service.close()
    result = dict(platform=platform.platform(), python=sys.version, psutil=psutil.__version__,
                  logical_cpus=psutil.cpu_count(), physical_cpus=psutil.cpu_count(logical=False),
                  samples=rows, disks=disks,
                  interpretation='Sequential samples can differ while other processes allocate memory or write files. '
                    'CPU uses GetSystemTimes busy time; Task Manager CPU utility may use a different model. '
                    'Network rates are calculated from psutil raw counters; not independently validated against an external traffic meter. '
                    'No temperature/Boost/cleanup/installer validation is performed by this script.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(args.output.resolve())


if __name__ == '__main__':
    main()
