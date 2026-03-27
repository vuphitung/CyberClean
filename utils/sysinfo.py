"""
CyberClean v2.2 — System Info (psutil-based, cross-platform)
Provides CPU, RAM, Disk, Temp, Network, Processes
FIX: _temp_cache and _disk_cache are now protected by threading.Lock
     to prevent race conditions when GUI timer and user refresh hit simultaneously.
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

@dataclass
class DiskInfo:
    path:       str
    total:      int
    used:       int
    free:       int
    percent:    float

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
    ram_used:       int = 0
    ram_total:      int = 0
    swap_percent:   float = 0.0
    swap_total:     int   = 0
    swap_used:      int   = 0
    disks:          List[DiskInfo] = field(default_factory=list)
    temp_max:       Optional[float] = None
    temp_all:       dict = field(default_factory=dict)
    top_cpu_procs:  List[ProcessInfo] = field(default_factory=list)
    top_mem_procs:  List[ProcessInfo] = field(default_factory=list)
    net_sent:       int = 0
    net_recv:       int = 0
    uptime_seconds: int = 0

def fmt_size(n: int) -> str:
    for u in ['B','KB','MB','GB','TB']:
        if n < 1024 or u == 'TB':
            return f'{n:.1f} {u}'
        n /= 1024

_OS = platform.system()
_temp_cache: tuple = (None, {}, 0.0)   # (max_temp, all_temps, timestamp)
_temp_lock  = threading.Lock()          # FIX: protects _temp_cache from race conditions
_TEMP_CACHE_TTL = 60.0   # seconds — PowerShell/WMI is expensive, don't call every 4s
_disk_cache: tuple = ([], 0.0)          # (disks, timestamp)
_disk_lock  = threading.Lock()          # FIX: protects _disk_cache from race conditions
_DISK_CACHE_TTL = 60.0  # seconds — disk_partitions() wakes sleeping/network drives!

def _read_temperature():
    """
    Multi-source temperature chain with 60s cache.
    Priority order:
      0. LibreHardwareMonitor DLL (pythonnet) — real MSR kernel driver, most accurate
      1. psutil sensors_temperatures()        — works on Linux + some Windows setups
      2. Linux /sys/class/thermal             — thermal zones
      3. Linux /sys/class/hwmon               — hwmon fallback
      4. Windows WMI MSAcpi                   — motherboard ACPI (less accurate)
      5. Windows WMI OpenHardwareMonitor      — if OHM service is running
      6. Windows PowerShell CIM fallback      — last resort

    LHM cache TTL = 4s (fast kernel read, safe to call often)
    WMI/PowerShell cache TTL = 60s (expensive, avoid calling every 4s)
    FIX: _temp_lock prevents race condition when GUI timer + user refresh run concurrently.
    """
    global _temp_cache
    with _temp_lock:
        max_cached, all_cached, ts = _temp_cache
        if time.time() - ts < _TEMP_CACHE_TTL and (all_cached or max_cached is not None):
            return all_cached, max_cached
    all_temps = {}
    max_temp  = None

    # ── Source 0: LibreHardwareMonitor DLL (Windows — real CPU core temp) ──
    # Reads directly from MSR via kernel driver — same method as HWMonitor/MSI Afterburner
    # Requires: pip install pythonnet  +  LibreHardwareMonitorLib.dll in app folder
    if _OS == 'Windows':
        try:
            import os as _os

            # FIX: pythonnet 3.0+ defaults to .NET Core but LHM DLL is built on .NET Framework.
            # Mixing runtimes causes a silent segfault (app dies with no error message).
            # Force .NET Framework ("netfx") BEFORE importing clr — must be called once only.
            try:
                from pythonnet import load as _pn_load
                _pn_load("netfx")
            except Exception:
                pass  # already loaded or not available — continue anyway

            import clr as _clr  # pythonnet — now using .NET Framework runtime

            # Search for DLL: next to main.py, next to sysinfo.py, or PyInstaller _MEIPASS
            _dll_candidates = [
                _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'LibreHardwareMonitorLib.dll'),
                _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', 'LibreHardwareMonitorLib.dll'),
            ]
            # PyInstaller onefile unpacks to _MEIPASS
            _meipass = getattr(__import__('sys'), '_MEIPASS', None)
            if _meipass:
                _dll_candidates.insert(0, _os.path.join(_meipass, 'LibreHardwareMonitorLib.dll'))

            _dll_path = next((p for p in _dll_candidates if _os.path.exists(p)), None)

            if _dll_path:
                _clr.AddReference(_dll_path)
                from LibreHardwareMonitor import Hardware as _HW  # type: ignore

                _computer = _HW.Computer()
                _computer.IsCpuEnabled = True
                _computer.IsGpuEnabled = True   # bonus: GPU temp too
                _computer.Open()

                for hw in _computer.Hardware:
                    hw.Update()
                    hw_name = str(hw.Name)
                    for sensor in hw.Sensors:
                        if sensor.SensorType == _HW.SensorType.Temperature:
                            val = sensor.Value
                            if val is not None and 1 < float(val) < 150:
                                label = f'{hw_name}/{sensor.Name}'
                                all_temps[label] = float(val)

                _computer.Close()

                if all_temps:
                    max_temp = max(all_temps.values())
                    # LHM reads fast — use shorter cache so sparkline updates smoothly
                    with _temp_lock:
                        _temp_cache = (max_temp, all_temps, time.time())
                    return all_temps, max_temp
        except ImportError:
            pass   # pythonnet not installed — fall through to WMI chain
        except Exception:
            pass   # DLL load failed or hardware not supported — fall through

    # ── Source 1: psutil (works on Linux + some Windows setups) ──
    try:
        if HAS_PSUTIL:
            raw = psutil.sensors_temperatures()
            if raw:
                for name, entries in raw.items():
                    for e in entries:
                        if e.current and 1 < e.current < 150:
                            key = f'{name}/{e.label or "core"}'
                            all_temps[key] = e.current
                if all_temps:
                    max_temp = max(all_temps.values())
                    return all_temps, max_temp
    except Exception:
        pass

    # ── Source 2: Linux /sys thermal zones ────────────────────────
    if _OS == 'Linux':
        try:
            for f in sorted(Path('/sys/class/thermal').glob('thermal_zone*/temp')):
                try:
                    v = int(f.read_text().strip()) / 1000
                    if 1 < v < 150:
                        zone = f.parent.name
                        type_f = f.parent / 'type'
                        label = type_f.read_text().strip() if type_f.exists() else zone
                        all_temps[label] = v
                except Exception:
                    pass
            if all_temps:
                max_temp = max(all_temps.values())
                return all_temps, max_temp
        except Exception:
            pass

        # Linux hwmon fallback
        try:
            for hwmon in Path('/sys/class/hwmon').glob('hwmon*'):
                name_f = hwmon / 'name'
                dev_name = name_f.read_text().strip() if name_f.exists() else hwmon.name
                for temp_f in sorted(hwmon.glob('temp*_input')):
                    try:
                        v = int(temp_f.read_text().strip()) / 1000
                        if 1 < v < 150:
                            label_f = temp_f.parent / temp_f.name.replace('_input', '_label')
                            label = label_f.read_text().strip() if label_f.exists() else temp_f.name
                            all_temps[f'{dev_name}/{label}'] = v
                    except Exception:
                        pass
            if all_temps:
                max_temp = max(all_temps.values())
                return all_temps, max_temp
        except Exception:
            pass

    # ── Source 3: Windows WMI MSAcpi (builtin, reads motherboard ACPI) ───
    # Note: this reads the board sensor, NOT individual CPU cores — often fixed value
    if _OS == 'Windows':
        try:
            import wmi as _wmi
            w = _wmi.WMI(namespace='root\\wmi')
            zones = w.MSAcpi_ThermalZoneTemperature()
            for i, z in enumerate(zones):
                v = (z.CurrentTemperature / 10.0) - 273.15
                if 1 < v < 150:
                    all_temps[f'acpi/zone{i}'] = v
            if all_temps:
                max_temp = max(all_temps.values())
                return all_temps, max_temp
        except Exception:
            pass

        # ── Source 4: Windows WMI OpenHardwareMonitor (if OHM service running) ─
        try:
            import wmi as _wmi
            w = _wmi.WMI(namespace='root\\OpenHardwareMonitor')
            sensors = w.Sensor()
            for s in sensors:
                if s.SensorType == 'Temperature' and s.Value is not None:
                    v = float(s.Value)
                    if 1 < v < 150:
                        all_temps[f'ohm/{s.Name}'] = v
            if all_temps:
                max_temp = max(all_temps.values())
                return all_temps, max_temp
        except Exception:
            pass

        # ── Source 5: PowerShell CIM fallback (no extra modules needed) ───
        try:
            import subprocess
            _NO_WIN = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            ps_cmd = (
                'Get-CimInstance -Namespace root/WMI '
                '-ClassName MSAcpi_ThermalZoneTemperature '
                '-ErrorAction SilentlyContinue | '
                'Select-Object -ExpandProperty CurrentTemperature'
            )
            r = subprocess.run(
                ['powershell', '-NoProfile', '-Command', ps_cmd],
                capture_output=True, text=True, timeout=6,
                creationflags=_NO_WIN,
            )
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
    return all_temps, max_temp   # None → UI shows "–°C"


def get_snapshot(interval: float = 0.5) -> SystemSnapshot:
    """Get full system snapshot. interval = CPU measurement window."""
    s = SystemSnapshot()
    if not HAS_PSUTIL:
        return _fallback_snapshot()

    # CPU
    s.cpu_percent   = psutil.cpu_percent(interval=interval)
    s.cpu_per_core  = psutil.cpu_percent(percpu=True)

    # RAM
    ram = psutil.virtual_memory()
    s.ram_percent = ram.percent
    s.ram_used    = ram.used
    s.ram_total   = ram.total

    swap = psutil.swap_memory()
    s.swap_percent = swap.percent
    s.swap_total   = swap.total
    s.swap_used    = swap.used

    # Disks — 2-level cache strategy:
    #   disk_partitions() cached 60s (wakes sleeping HDDs — expensive)
    #   disk_usage()      called every tick (fast, no HDD wakeup)
    global _disk_cache
    with _disk_lock:
        _cached_parts, _part_ts = _disk_cache
    now_ts = time.time()
    IGNORE_FS = {'tmpfs', 'squashfs', 'devtmpfs', 'overlay', 'aufs'}
    if not _cached_parts or (now_ts - _part_ts) > _DISK_CACHE_TTL:
        # Re-scan partitions only every 60s
        _cached_parts = [
            p for p in psutil.disk_partitions(all=False)
            if p.fstype not in IGNORE_FS
            and 'loop' not in p.device
            and 'snap' not in p.mountpoint
        ]
        with _disk_lock:
            _disk_cache = (_cached_parts, now_ts)
    fresh_disks = []
    for part in _cached_parts:
        try:
            # disk_usage is fast — safe to call every 4s
            usage = psutil.disk_usage(part.mountpoint)
            fresh_disks.append(DiskInfo(
                path    = part.mountpoint,
                total   = usage.total,
                used    = usage.used,
                free    = usage.free,
                percent = usage.percent,
            ))
        except: pass
    s.disks = fresh_disks

    # Temperature — multi-source fallback chain
    s.temp_all, s.temp_max = _read_temperature()

    # Top processes
    # Skip: our own app, shell tools, AND Windows/Linux pseudo-processes
    _SKIP_NAMES = {
        'python3', 'python', 'py.exe', 'ps', 'grep', 'pgrep',
        # Windows pseudo-processes that report bogus CPU% (e.g. 370%)
        'system idle process', 'system', 'registry', 'memory compression',
        'secure system', 'smss.exe',
        # Linux kernel threads (show 0% anyway but clutter the list)
        'kthreadd', 'kworker', 'ksoftirqd', 'migration', 'rcu_sched',
        'rcu_bh', 'watchdog', 'kswapd', 'kdevtmpfs',
    }
    import platform as _pf
    _IS_WIN = _pf.system() == 'Windows'
    _ncpus  = psutil.cpu_count() or 1

    procs = []
    for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'status']):
        try:
            pname = p.info['name'] or ''
            # Skip PID 0 (System Idle) and PID 4 (System) on Windows
            if _IS_WIN and p.info['pid'] in (0, 4):
                continue
            if pname.lower() in _SKIP_NAMES:
                continue
            # Normalize: psutil returns per-core %, cap at 100%
            raw_cpu = p.info['cpu_percent'] or 0
            cpu_pct = min(raw_cpu / _ncpus, 100.0) if _IS_WIN else raw_cpu
            procs.append(ProcessInfo(
                pid    = p.info['pid'],
                name   = pname,
                cpu    = cpu_pct,
                mem    = p.info['memory_percent'] or 0,
                status = p.info['status'],
            ))
        except:
            pass

    s.top_cpu_procs = sorted(procs, key=lambda x: x.cpu, reverse=True)[:8]
    s.top_mem_procs = sorted(procs, key=lambda x: x.mem, reverse=True)[:8]

    # Network
    try:
        net = psutil.net_io_counters()
        s.net_sent = net.bytes_sent
        s.net_recv = net.bytes_recv
    except: pass

    # Uptime
    try:
        s.uptime_seconds = int(time.time() - psutil.boot_time())
    except: pass

    return s

def _fallback_snapshot() -> SystemSnapshot:
    """Fallback when psutil not available — Linux only."""
    s = SystemSnapshot()
    try:
        with open('/proc/meminfo') as f:
            lines = f.readlines()
        mem = {l.split(':')[0]: int(l.split()[1])*1024 for l in lines if ':' in l}
        total = mem.get('MemTotal', 0)
        avail = mem.get('MemAvailable', 0)
        s.ram_total   = total
        s.ram_used    = total - avail
        s.ram_percent = (s.ram_used / total * 100) if total else 0
    except: pass
    try:
        import shutil
        u = shutil.disk_usage('/')
        s.disks = [DiskInfo('/', u.total, u.used, u.free, u.used/u.total*100)]
    except: pass
    return s

def get_startup_items() -> List[dict]:
    """Get startup programs — cross-platform."""
    items = []
    os_name = platform.system()

    if os_name == 'Linux':
        # systemd user services
        import subprocess
        out = subprocess.run(
            ['systemctl','--user','list-unit-files','--type=service','--state=enabled'],
            capture_output=True, text=True
        ).stdout
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2:
                items.append({'name': parts[0], 'type': 'systemd-user',
                              'enabled': True, 'platform': 'Linux'})
        # XDG autostart
        for d in [Path.home()/'.config/autostart', Path('/etc/xdg/autostart')]:
            if d.exists():
                for f in d.glob('*.desktop'):
                    enabled = True
                    name    = f.stem
                    try:
                        txt = f.read_text()
                        if 'Hidden=true' in txt or 'X-GNOME-Autostart-enabled=false' in txt:
                            enabled = False
                        for line in txt.splitlines():
                            if line.startswith('Name='): name = line.split('=',1)[1]
                    except: pass
                    items.append({'name': name, 'type': 'xdg-autostart',
                                  'enabled': enabled, 'platform': 'Linux',
                                  'path': str(f)})

    elif os_name == 'Windows':
        import winreg
        keys = [
            (winreg.HKEY_CURRENT_USER,  r'Software\Microsoft\Windows\CurrentVersion\Run'),
            (winreg.HKEY_LOCAL_MACHINE, r'Software\Microsoft\Windows\CurrentVersion\Run'),
        ]
        for hive, key_path in keys:
            try:
                key = winreg.OpenKey(hive, key_path)
                i = 0
                while True:
                    try:
                        name, val, _ = winreg.EnumValue(key, i)
                        items.append({'name': name, 'type': 'registry',
                                      'enabled': True, 'platform': 'Windows',
                                      'path': val})
                        i += 1
                    except OSError: break
                winreg.CloseKey(key)
            except: pass

    return items

def toggle_startup_linux(name: str, item_type: str, enable: bool, path: str = ''):
    """Enable/disable a Linux startup item."""
    import subprocess
    if item_type == 'systemd-user':
        action = 'enable' if enable else 'disable'
        subprocess.run(['systemctl','--user', action, name], capture_output=True)
    elif item_type == 'xdg-autostart' and path:
        p = Path(path)
        if p.exists():
            import re
            txt = p.read_text()
            if enable:
                # Regex handles case-insensitive variants (hidden=true, Hidden=True, etc.)
                txt = re.sub(r'(?i)^Hidden=true\n?', '', txt, flags=re.MULTILINE)
                txt = re.sub(r'(?i)^X-GNOME-Autostart-enabled=false',
                             'X-GNOME-Autostart-enabled=true', txt, flags=re.MULTILINE)
            else:
                if not re.search(r'(?i)^Hidden=', txt, flags=re.MULTILINE):
                    txt += '\nHidden=true\n'
            p.write_text(txt)
