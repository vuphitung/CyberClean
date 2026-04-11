"""
CyberClean v2.3 — System Info (psutil-based, cross-platform)
════════════════════════════════════════════════════════════════

WHAT CHANGED vs v2.2:

NEW: NetworkSpeed — per-tick bytes/s for upload and download.
     get_snapshot() now includes net_up_bps and net_down_bps,
     computed from two net_io_counters() samples separated by the
     cpu_percent(interval) window.
     Dashboard can display "↑ 1.2 MB/s  ↓ 4.8 MB/s" in real time.

NEW: fmt_uptime() — human-readable uptime string.
     "3 days 4h 12m" instead of raw seconds.

NEW: SystemSnapshot.uptime_str property — convenience for UI labels.

NEW: get_process_by_pid() — fetch a single ProcessInfo by PID.
     Used by scanner tab to enrich findings with live CPU/mem data
     without fetching the full process list.

IMPROVED: _SKIP_NAMES extended — added more Windows kernel pseudo-processes
     that report spurious CPU% (Memory Compression, Secure System, etc.)
     and more Linux kernel threads to reduce list noise.

IMPROVED: Process CPU normalisation — Windows multi-core fix was present but
     only applied to _IS_WIN. Now also applied to Linux when psutil returns
     per-process% > 100 (happens with some kernel versions).

FIX: get_snapshot() — net_io_counters() can return None on some Linux VMs
     (e.g. inside WSL1 or minimal containers). Added None guard.

FIX: _disk_cache — snap-mounted paths (/snap/...) were excluded by string match
     but /var/snap/... is the actual mount on Ubuntu. Extended filter.
"""
import time, platform, threading
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

_OS = platform.system()


# ── Data classes ───────────────────────────────────────────────

@dataclass
class DiskInfo:
    path:    str
    total:   int
    used:    int
    free:    int
    percent: float


@dataclass
class ProcessInfo:
    pid:    int
    name:   str
    cpu:    float
    mem:    float
    status: str


@dataclass
class SystemSnapshot:
    cpu_percent:    float = 0.0
    cpu_per_core:   List[float] = field(default_factory=list)
    ram_percent:    float = 0.0
    ram_used:       int   = 0
    ram_total:      int   = 0
    swap_percent:   float = 0.0
    swap_total:     int   = 0
    swap_used:      int   = 0
    disks:          List[DiskInfo] = field(default_factory=list)
    temp_max:       Optional[float] = None
    temp_all:       dict = field(default_factory=dict)
    top_cpu_procs:  List[ProcessInfo] = field(default_factory=list)
    top_mem_procs:  List[ProcessInfo] = field(default_factory=list)
    net_sent:       int   = 0
    net_recv:       int   = 0
    net_up_bps:     int   = 0   # NEW: upload bytes/sec this tick
    net_down_bps:   int   = 0   # NEW: download bytes/sec this tick
    uptime_seconds: int   = 0

    @property
    def uptime_str(self) -> str:
        """Human-readable uptime: '3d 4h 12m' or '42m 5s'."""
        return fmt_uptime(self.uptime_seconds)


# ── Formatters ─────────────────────────────────────────────────

def fmt_size(n: int) -> str:
    n = max(0, n)
    for u in ['B', 'KB', 'MB', 'GB', 'TB']:
        if n < 1024 or u == 'TB':
            return f'{n:.1f} {u}'
        n /= 1024


def fmt_speed(bps: int) -> str:
    """Format bytes/sec as human-readable speed string."""
    bps = max(0, bps)
    if bps < 1024:
        return f'{bps} B/s'
    if bps < 1024 ** 2:
        return f'{bps/1024:.1f} KB/s'
    if bps < 1024 ** 3:
        return f'{bps/1024**2:.1f} MB/s'
    return f'{bps/1024**3:.2f} GB/s'


def fmt_uptime(seconds: int) -> str:
    """Format uptime seconds → readable string."""
    seconds = max(0, int(seconds))
    days    = seconds // 86400
    hours   = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs    = seconds % 60
    if days > 0:
        return f'{days}d {hours}h {minutes}m'
    if hours > 0:
        return f'{hours}h {minutes}m'
    if minutes > 0:
        return f'{minutes}m {secs}s'
    return f'{secs}s'


# ── Temperature (unchanged from v2.2, cached + thread-safe) ───

_temp_cache: tuple = (None, {}, 0.0)
_temp_lock   = threading.Lock()
_TEMP_CACHE_TTL = 60.0

_disk_cache: tuple = ([], 0.0)
_disk_lock   = threading.Lock()
_DISK_CACHE_TTL = 60.0

# ── Network speed — persistent globals (fix "kẹp chả" sampling) ──────────────
# Thay vì đo 2 sample cách nhau 0.5s (mất CPU, bỏ lỡ traffic ngoài window),
# ta lưu counter của lần gọi TRƯỚC và tính delta theo wallclock thực tế.
# Kết quả: đo đúng 100% traffic, 0 extra blocking, ăn ~0% CPU thêm.
_last_net_io   = None   # psutil._common.snetio | None
_last_net_time = 0.0    # float timestamp của lần đo trước


def _read_temperature():
    """
    Multi-source temperature chain with 60s cache.
    Priority: LHM DLL → psutil → /sys/thermal → /sys/hwmon → WMI → PowerShell CIM
    Unchanged from v2.2; documented here for reference.
    """
    global _temp_cache
    with _temp_lock:
        max_cached, all_cached, ts = _temp_cache
        if time.time() - ts < _TEMP_CACHE_TTL and (all_cached or max_cached is not None):
            return all_cached, max_cached
    all_temps = {}
    max_temp  = None

    # Source 0: LibreHardwareMonitor DLL
    if _OS == 'Windows':
        try:
            import os as _os
            try:
                from pythonnet import load as _pn_load
                _pn_load("netfx")
            except Exception:
                pass
            import clr as _clr
            _dll_candidates = [
                _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'LibreHardwareMonitorLib.dll'),
                _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', 'LibreHardwareMonitorLib.dll'),
            ]
            _meipass = getattr(__import__('sys'), '_MEIPASS', None)
            if _meipass:
                import os as _os2
                _dll_candidates.insert(0, _os2.path.join(_meipass, 'LibreHardwareMonitorLib.dll'))
            _dll_path = next((p for p in _dll_candidates if _os.path.exists(p)), None)
            if _dll_path:
                _clr.AddReference(_dll_path)
                from LibreHardwareMonitor import Hardware as _HW  # type: ignore
                _computer = _HW.Computer()
                _computer.IsCpuEnabled = True
                _computer.IsGpuEnabled = True
                _computer.Open()
                for hw in _computer.Hardware:
                    hw.Update()
                    hw_name = str(hw.Name)
                    for sensor in hw.Sensors:
                        if sensor.SensorType == _HW.SensorType.Temperature:
                            val = sensor.Value
                            if val is not None and 1 < float(val) < 150:
                                all_temps[f'{hw_name}/{sensor.Name}'] = float(val)
                _computer.Close()
                if all_temps:
                    max_temp = max(all_temps.values())
                    with _temp_lock:
                        _temp_cache = (max_temp, all_temps, time.time())
                    return all_temps, max_temp
        except Exception:
            pass

    # Source 1: psutil
    try:
        if HAS_PSUTIL:
            raw = psutil.sensors_temperatures()
            if raw:
                for name, entries in raw.items():
                    for e in entries:
                        if e.current and 1 < e.current < 150:
                            all_temps[f'{name}/{e.label or "core"}'] = e.current
                if all_temps:
                    max_temp = max(all_temps.values())
                    return all_temps, max_temp
    except Exception:
        pass

    # Source 2: Linux /sys/class/thermal
    if _OS == 'Linux':
        try:
            for f in sorted(Path('/sys/class/thermal').glob('thermal_zone*/temp')):
                try:
                    v = int(f.read_text().strip()) / 1000
                    if 1 < v < 150:
                        zone   = f.parent.name
                        type_f = f.parent / 'type'
                        label  = type_f.read_text().strip() if type_f.exists() else zone
                        all_temps[label] = v
                except Exception:
                    pass
            if all_temps:
                max_temp = max(all_temps.values())
                return all_temps, max_temp
        except Exception:
            pass

        # Source 3: Linux /sys/class/hwmon
        try:
            for hwmon in Path('/sys/class/hwmon').glob('hwmon*'):
                name_f   = hwmon / 'name'
                dev_name = name_f.read_text().strip() if name_f.exists() else hwmon.name
                for temp_f in sorted(hwmon.glob('temp*_input')):
                    try:
                        v = int(temp_f.read_text().strip()) / 1000
                        if 1 < v < 150:
                            label_f = temp_f.parent / temp_f.name.replace('_input', '_label')
                            label   = label_f.read_text().strip() if label_f.exists() else temp_f.name
                            all_temps[f'{dev_name}/{label}'] = v
                    except Exception:
                        pass
            if all_temps:
                max_temp = max(all_temps.values())
                return all_temps, max_temp
        except Exception:
            pass

    # Source 4: Windows WMI MSAcpi
    if _OS == 'Windows':
        try:
            import wmi as _wmi
            w = _wmi.WMI(namespace='root\\wmi')
            for i, z in enumerate(w.MSAcpi_ThermalZoneTemperature()):
                v = (z.CurrentTemperature / 10.0) - 273.15
                if 1 < v < 150:
                    all_temps[f'acpi/zone{i}'] = v
            if all_temps:
                max_temp = max(all_temps.values())
                return all_temps, max_temp
        except Exception:
            pass

        # Source 5: Windows WMI OpenHardwareMonitor
        try:
            import wmi as _wmi
            w = _wmi.WMI(namespace='root\\OpenHardwareMonitor')
            for s in w.Sensor():
                if s.SensorType == 'Temperature' and s.Value is not None:
                    v = float(s.Value)
                    if 1 < v < 150:
                        all_temps[f'ohm/{s.Name}'] = v
            if all_temps:
                max_temp = max(all_temps.values())
                return all_temps, max_temp
        except Exception:
            pass

        # Source 6: PowerShell CIM fallback
        try:
            import subprocess as _sp
            _NW = _sp.CREATE_NO_WINDOW if hasattr(_sp, 'CREATE_NO_WINDOW') else 0
            ps_cmd = (
                'Get-CimInstance -Namespace root/WMI '
                '-ClassName MSAcpi_ThermalZoneTemperature '
                '-ErrorAction SilentlyContinue | '
                'Select-Object -ExpandProperty CurrentTemperature'
            )
            r = _sp.run(['powershell', '-NoProfile', '-Command', ps_cmd],
                        capture_output=True, text=True, timeout=6, creationflags=_NW)
            for i, line in enumerate(r.stdout.strip().splitlines()):
                try:
                    v = (float(line.strip()) / 10.0) - 273.15
                    if 1 < v < 150:
                        all_temps[f'cim/zone{i}'] = v
                except Exception:
                    pass
            if all_temps:
                max_temp = max(all_temps.values())
                return all_temps, max_temp
        except Exception:
            pass

    with _temp_lock:
        _temp_cache = (max_temp, all_temps, time.time())
    return all_temps, max_temp


# ── Process skip list ──────────────────────────────────────────
_SKIP_NAMES = {
    'python3', 'python', 'python.exe', 'py.exe', 'ps', 'grep', 'pgrep',
    # Windows pseudo-processes with bogus CPU%
    'system idle process', 'system', 'registry', 'memory compression',
    'secure system', 'smss.exe', 'ntoskrnl.exe',
    'wininit.exe', 'wininit',
    # Linux kernel threads (0% anyway but clutter)
    'kthreadd', 'kworker', 'ksoftirqd', 'migration', 'rcu_sched',
    'rcu_bh', 'watchdog', 'kswapd', 'kdevtmpfs', 'ksmd', 'khugepaged',
    'kcompactd', 'irq/', 'kblockd', 'bioset',
}


def get_snapshot(interval: float = 0.5) -> SystemSnapshot:
    """
    Full system snapshot.
    interval = CPU measurement window in seconds.

    NET SPEED FIX (v2.3.1):
    Cách cũ "kẹp chả" (đo _n1, block 0.5s, đo _n2) bỏ lỡ traffic ngoài window
    -> số liệu chập chờn lúc 0 lúc không.
    Cách mới: dùng global _last_net_io / _last_net_time lưu counter lần trước.
    Delta = (counter_hiện_tại - counter_lần_trước) / (thời_gian_thực_tế_giữa_2_lần_gọi).
    Không block thêm, không bỏ lỡ 1 byte, ăn ~0% CPU thêm.
    """
    global _last_net_io, _last_net_time
    s = SystemSnapshot()
    if not HAS_PSUTIL:
        return _fallback_snapshot()

    # ── CPU ───────────────────────────────────────────────────────────────────
    s.cpu_percent  = psutil.cpu_percent(interval=interval)
    s.cpu_per_core = psutil.cpu_percent(percpu=True)

    # ── Network speed — persistent global counter (không kẹp chả) ─────────────
    try:
        current_io   = psutil.net_io_counters()
        current_time = time.time()

        if current_io is not None:
            s.net_sent = current_io.bytes_sent
            s.net_recv = current_io.bytes_recv

            if _last_net_io is not None:
                dt = current_time - _last_net_time
                if dt > 0.05:   # tránh chia cho dt quá nhỏ nếu gọi liên tiếp nhanh
                    s.net_up_bps   = max(0, int(
                        (current_io.bytes_sent - _last_net_io.bytes_sent) / dt
                    ))
                    s.net_down_bps = max(0, int(
                        (current_io.bytes_recv - _last_net_io.bytes_recv) / dt
                    ))

            # Lưu lại cho lần gọi tiếp theo
            _last_net_io   = current_io
            _last_net_time = current_time
    except Exception:
        pass

    # RAM
    ram           = psutil.virtual_memory()
    s.ram_percent = ram.percent
    s.ram_used    = ram.used
    s.ram_total   = ram.total

    swap          = psutil.swap_memory()
    s.swap_percent= swap.percent
    s.swap_total  = swap.total
    s.swap_used   = swap.used

    # Disks — partition list cached 60s, usage read every tick
    global _disk_cache
    with _disk_lock:
        _cached_parts, _part_ts = _disk_cache
    now_ts    = time.time()
    IGNORE_FS = {'tmpfs', 'squashfs', 'devtmpfs', 'overlay', 'aufs', 'ramfs'}
    if not _cached_parts or (now_ts - _part_ts) > _DISK_CACHE_TTL:
        _cached_parts = [
            p for p in psutil.disk_partitions(all=False)
            if p.fstype not in IGNORE_FS
            and 'loop' not in p.device
            and '/snap/' not in p.mountpoint       # Ubuntu snap mounts
            and '/var/snap/' not in p.mountpoint   # FIX: extended snap filter
            and 'snap' not in p.device             # snap loop devices
        ]
        with _disk_lock:
            _disk_cache = (_cached_parts, now_ts)

    fresh_disks = []
    for part in _cached_parts:
        try:
            usage = psutil.disk_usage(part.mountpoint)
            fresh_disks.append(DiskInfo(
                path=part.mountpoint, total=usage.total,
                used=usage.used, free=usage.free, percent=usage.percent,
            ))
        except Exception:
            pass
    s.disks = fresh_disks

    # Temperature
    s.temp_all, s.temp_max = _read_temperature()

    # Processes
    _IS_WIN = _OS == 'Windows'
    _ncpus  = psutil.cpu_count() or 1
    procs   = []
    for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'status']):
        try:
            pname = p.info['name'] or ''
            if _IS_WIN and p.info['pid'] in (0, 4):
                continue
            if pname.lower().rstrip('.exe') in {n.lower().rstrip('.exe') for n in _SKIP_NAMES}:
                continue
            raw_cpu = p.info['cpu_percent'] or 0
            # Normalise: psutil can report > 100% on multi-core systems
            cpu_pct = min(raw_cpu / _ncpus, 100.0) if raw_cpu > 100 else raw_cpu
            procs.append(ProcessInfo(
                pid=p.info['pid'], name=pname,
                cpu=cpu_pct, mem=p.info['memory_percent'] or 0,
                status=p.info['status'],
            ))
        except Exception:
            pass

    s.top_cpu_procs = sorted(procs, key=lambda x: x.cpu, reverse=True)[:8]
    s.top_mem_procs = sorted(procs, key=lambda x: x.mem, reverse=True)[:8]

    # Uptime
    try:
        s.uptime_seconds = int(time.time() - psutil.boot_time())
    except Exception:
        pass

    return s


def get_process_by_pid(pid: int) -> Optional[ProcessInfo]:
    """Fetch a single ProcessInfo. Returns None if process gone or no psutil."""
    if not HAS_PSUTIL:
        return None
    try:
        p = psutil.Process(pid)
        return ProcessInfo(
            pid=pid,
            name=p.name(),
            cpu=p.cpu_percent(interval=0.1),
            mem=p.memory_percent(),
            status=p.status(),
        )
    except Exception:
        return None


def _fallback_snapshot() -> SystemSnapshot:
    """Fallback when psutil not available — Linux /proc only."""
    s = SystemSnapshot()
    try:
        with open('/proc/meminfo') as f:
            lines = f.readlines()
        mem   = {l.split(':')[0]: int(l.split()[1]) * 1024 for l in lines if ':' in l}
        total = mem.get('MemTotal', 0)
        avail = mem.get('MemAvailable', 0)
        s.ram_total   = total
        s.ram_used    = total - avail
        s.ram_percent = (s.ram_used / total * 100) if total else 0
    except Exception:
        pass
    try:
        import shutil
        u     = shutil.disk_usage('/')
        s.disks = [DiskInfo('/', u.total, u.used, u.free, u.used / u.total * 100)]
    except Exception:
        pass
    try:
        with open('/proc/uptime') as f:
            s.uptime_seconds = int(float(f.read().split()[0]))
    except Exception:
        pass
    return s


# ── Startup items (unchanged) ──────────────────────────────────

def get_startup_items() -> List[dict]:
    """Get startup programs — cross-platform."""
    items = []
    os_name = platform.system()

    if os_name == 'Linux':
        import subprocess
        out = subprocess.run(
            ['systemctl', '--user', 'list-unit-files', '--type=service', '--state=enabled'],
            capture_output=True, text=True,
        ).stdout
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2:
                items.append({'name': parts[0], 'type': 'systemd-user',
                              'enabled': True, 'platform': 'Linux'})
        for d in [Path.home() / '.config/autostart', Path('/etc/xdg/autostart')]:
            if d.exists():
                for f in d.glob('*.desktop'):
                    enabled = True
                    name    = f.stem
                    try:
                        txt = f.read_text()
                        if 'Hidden=true' in txt or 'X-GNOME-Autostart-enabled=false' in txt:
                            enabled = False
                        for line in txt.splitlines():
                            if line.startswith('Name='):
                                name = line.split('=', 1)[1]
                    except Exception:
                        pass
                    items.append({'name': name, 'type': 'xdg-autostart',
                                  'enabled': enabled, 'platform': 'Linux', 'path': str(f)})

    elif os_name == 'Windows':
        import winreg
        keys = [
            (winreg.HKEY_CURRENT_USER,  r'Software\Microsoft\Windows\CurrentVersion\Run'),
            (winreg.HKEY_LOCAL_MACHINE, r'Software\Microsoft\Windows\CurrentVersion\Run'),
        ]
        for hive, key_path in keys:
            try:
                key = winreg.OpenKey(hive, key_path)
                i   = 0
                while True:
                    try:
                        name, val, _ = winreg.EnumValue(key, i)
                        items.append({'name': name, 'type': 'registry',
                                      'enabled': True, 'platform': 'Windows', 'path': val})
                        i += 1
                    except OSError:
                        break
                winreg.CloseKey(key)
            except Exception:
                pass

    return items


def toggle_startup_linux(name: str, item_type: str, enable: bool, path: str = ''):
    """Enable/disable a Linux startup item."""
    import subprocess, re as _re
    if item_type == 'systemd-user':
        action = 'enable' if enable else 'disable'
        subprocess.run(['systemctl', '--user', action, name], capture_output=True)
    elif item_type == 'xdg-autostart' and path:
        p = Path(path)
        if p.exists():
            txt = p.read_text()
            if enable:
                txt = _re.sub(r'(?i)^Hidden=true\n?', '', txt, flags=_re.MULTILINE)
                txt = _re.sub(r'(?i)^X-GNOME-Autostart-enabled=false',
                              'X-GNOME-Autostart-enabled=true', txt, flags=_re.MULTILINE)
            else:
                if not _re.search(r'(?i)^Hidden=', txt, flags=_re.MULTILINE):
                    txt += '\nHidden=true\n'
            p.write_text(txt)
