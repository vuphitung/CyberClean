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

    # Temperature
    try:
        temps = psutil.sensors_temperatures()
        all_temps = {}
        max_temp  = 0.0
        for name, entries in temps.items():
            for e in entries:
                if e.current and e.current > 0:
                    all_temps[f'{name}/{e.label or "core"}'] = e.current
                    if e.current > max_temp:
                        max_temp = e.current
        s.temp_all  = all_temps
        s.temp_max  = max_temp if max_temp > 0 else None
    except: pass

    # Fallback temp from /sys (Linux)
    if s.temp_max is None and platform.system() == 'Linux':
        best = 0
        for f in Path('/sys/class/thermal').glob('thermal_zone*/temp'):
            try:
                v = int(f.read_text()) // 1000
                if v > best: best = v
            except: pass
        if best > 0: s.temp_max = float(best)

    # Top processes
    skip = {'python3','python','py.exe','ps','grep','pgrep'}
    procs = []
    for p in psutil.process_iter(['pid','name','cpu_percent','memory_percent','status']):
        try:
            if p.info['name'].lower() in skip: continue
            procs.append(ProcessInfo(
                pid    = p.info['pid'],
                name   = p.info['name'],
                cpu    = p.info['cpu_percent'] or 0,
                mem    = p.info['memory_percent'] or 0,
                status = p.info['status'],
            ))
        except: pass

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
