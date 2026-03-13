"""
CyberClean v2.0 — System Info (psutil-based, cross-platform)
Provides CPU, RAM, Disk, Temp, Network, Processes
"""
import time, platform
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
_TEMP_CACHE_TTL = 60.0   # seconds — PowerShell/WMI is expensive, don't call every 4s

def _read_temperature():
    """
    Multi-source temperature chain with 60s cache.
    PowerShell/WMI calls are expensive — caching prevents CPU spike every 4s.
    Returns (all_temps: dict, max_temp: float | None)
    """
    global _temp_cache
    max_cached, all_cached, ts = _temp_cache
    if time.time() - ts < _TEMP_CACHE_TTL and (all_cached or max_cached is not None):
        return all_cached, max_cached
    all_temps = {}
    max_temp  = None

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
                        # Try to get a friendly type label
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

    # ── Source 3: Windows WMI MSAcpi (needs admin, builtin) ───────
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

        # ── Source 4: Windows WMI OpenHardwareMonitor (if running) ─
        # OHM must be running as a service — it exposes data via WMI
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

        # ── Source 5: PowerShell CIM fallback (no extra modules) ───
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

    result = (all_temps, max_temp)
    _temp_cache = (max_temp, all_temps, time.time())
    return result   # None → UI shows "–°C"


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

    # Disks
    ignore_fs = {'tmpfs','squashfs','devtmpfs','overlay','aufs'}
    for part in psutil.disk_partitions():
        if part.fstype in ignore_fs: continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
            s.disks.append(DiskInfo(
                path    = part.mountpoint,
                total   = usage.total,
                used    = usage.used,
                free    = usage.free,
                percent = usage.percent,
            ))
        except: pass

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
            txt = p.read_text()
            if enable:
                txt = txt.replace('Hidden=true\n','').replace('X-GNOME-Autostart-enabled=false','X-GNOME-Autostart-enabled=true')
            else:
                if 'Hidden=' not in txt:
                    txt += '\nHidden=true'
            p.write_text(txt)
