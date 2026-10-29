"""Child entry point, JSON Lines on stdout. Windows/native validation required."""
import hashlib
import json
from pathlib import Path
import sys
import threading
import time
import traceback


_output_lock = threading.Lock()


def diagnose_backend(hardware, report='', *, admin=False, pawnio=None):
    """Explain missing CPU data using raw sensors and the backend's own report.

    Keep only the Ring0 status excerpt; the full hardware report may include
    identifiers unrelated to temperature and must not be sent to the GUI.
    """
    sensors = []
    cpus = 0
    def inspect(hw):
        nonlocal cpus
        if str(hw.HardwareType) == 'Cpu':
            cpus += 1
            for sensor in hw.Sensors:
                if str(sensor.SensorType) == 'Temperature':
                    sensors.append(dict(id=str(sensor.Identifier), name=str(sensor.Name),
                                        has_value=sensor.Value is not None))
        for sub in hw.SubHardware:
            inspect(sub)
    for hw in hardware:
        inspect(hw)
    text = str(report)
    start = text.find('Ring0')
    ring0 = text[start:start+1800] if start >= 0 else ''
    separator = ring0.find('------------------------------------------------------------------------')
    if separator >= 0:
        ring0 = ring0[:separator]
    access_denied = ('OpenSCManager' in ring0 and
                     ('00000005' in ring0 or 'access is denied' in ring0.lower()))
    from utils.windows_temperature import classify_sensor
    if any(sensor['has_value'] and classify_sensor('Cpu', sensor['name']) for sensor in sensors):
        code = 'cpu_sensor_available'
    elif pawnio is not None and not pawnio.get('installed'):
        code = 'pawnio_missing'
    elif pawnio is not None and pawnio.get('access_error') == 5:
        code = 'cpu_access_denied'
    elif pawnio is not None and pawnio.get('access_error') in (577, 1275):
        code = 'cpu_driver_blocked'
    elif pawnio is not None and pawnio.get('access_error'):
        code = 'cpu_driver_unavailable'
    elif access_denied:
        code = 'cpu_access_denied'
    elif 'failed' in ring0.lower() or 'error' in ring0.lower():
        code = 'cpu_driver_unavailable'
    elif not cpus:
        code = 'cpu_hardware_missing'
    elif not sensors:
        code = 'cpu_sensor_missing'
    else:
        code = 'cpu_sensor_no_value'
    needs_admin = access_denied if pawnio is None else pawnio.get('installed') and pawnio.get('access_error') == 5
    return dict(reason_code=code, requires_admin=bool(code != 'cpu_sensor_available' and needs_admin and not admin),
                administrator=bool(admin), cpu_hardware_count=cpus, raw_cpu_sensors=sensors,
                driver_status=ring0.strip(), driver_backend='legacy_winring0' if pawnio is None else 'pawnio',
                pawnio=dict(pawnio or {}), setup_required=code == 'pawnio_missing',
                elevation_supported=False)


def probe_pawnio():
    """Read installation metadata and test an existing device handle; never install.

    The access mask matches the official PawnIO client. No DeviceIoControl or
    hardware writes are performed here. LHM owns subsequent CPU read modules.
    """
    import ctypes
    from ctypes import wintypes
    from LibreHardwareMonitor.PawnIo import PawnIo
    installed = bool(PawnIo.IsInstalled)
    result = dict(installed=installed, version=str(PawnIo.Version) if installed else None,
                  access_error=None)
    if not installed:
        return result
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,
                       wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = create(r'\\?\GLOBALROOT\Device\PawnIO',0xC0000000,3,None,3,0x80,None)
    if handle == ctypes.c_void_p(-1).value:
        result['access_error'] = ctypes.get_last_error()
    else:
        kernel.CloseHandle(handle)
    return result


def emit(message):
    with _output_lock:
        print(json.dumps(message, allow_nan=False), flush=True)


def _sample_group(group, selected, read, stop, send=emit, clock=time.monotonic):
    """Keep the child responsive without native polling for absent sensors.

    Empty heartbeats clear that group's readings. They never reuse/refresh an
    older temperature. Retry native detection within ten seconds of no data.
    """
    next_probe = 0.
    reason = ''
    while not stop.is_set():
        now = clock()
        readings, errors = [], []
        sampled = now >= next_probe
        if sampled:
            for hardware in selected:
                read(hardware, readings, errors)
            next_probe = now+(1. if readings else 10.)
            reason = '; '.join(errors)
            if not readings:
                reason = (reason+'; ' if reason else '') + f'No {group.upper()} temperature sensors; hardware retry within 10s'
        send({'type': 'sample', 'group': group, 'readings': readings, 'reason': reason,
              'hardware_sampled': sampled})
        stop.wait(1.)


def _restore_redirected_streams():
    # Windowed PyInstaller/pythonw may set sys.std* to None even when the parent
    # supplied pipe handles. Bind those inherited handles explicitly for JSON IPC.
    if sys.platform != 'win32':
        return
    import ctypes
    import msvcrt
    import os
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetStdHandle.argtypes = [ctypes.c_uint32]
    kernel.GetStdHandle.restype = ctypes.c_void_p
    for name, identifier, flags, mode in [('stdin', -10, os.O_RDONLY, 'r'),
                                          ('stdout', -11, os.O_WRONLY, 'w'),
                                          ('stderr', -12, os.O_WRONLY, 'w')]:
        if getattr(sys, name) is None:
            handle = kernel.GetStdHandle(identifier & 0xffffffff)
            if handle in (None, ctypes.c_void_p(-1).value):
                raise OSError(f'No inherited {name} handle')
            fd = msvcrt.open_osfhandle(handle, flags)
            setattr(sys, name, os.fdopen(fd, mode, encoding='utf-8', buffering=1))


def run():
    _restore_redirected_streams()
    from utils.windows_temperature import classify_sensor
    stop = threading.Event()
    def commands():
        for line in sys.stdin:
            if line.strip() == 'STOP':
                break
        stop.set()
    threading.Thread(target=commands, daemon=True).start()
    comp = None
    try:
        base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1])) / 'vendor' / 'lhm'
        manifest = json.loads((base / 'manifest.json').read_text(encoding='utf-8'))
        for name, expected in manifest['sha256'].items():
            if hashlib.sha256((base/name).read_bytes()).hexdigest() != expected:
                raise RuntimeError(f'Bundled dependency hash mismatch: {name}')
        from pythonnet import load
        load('netfx')
        import clr
        for name in manifest.get('load_order', ['HidSharp.dll', 'LibreHardwareMonitorLib.dll']):
            clr.AddReference(str(base / name))
        from LibreHardwareMonitor import Hardware
        comp = Hardware.Computer()
        comp.IsCpuEnabled = True
        comp.IsGpuEnabled = True
        comp.Open()
        hardware = list(comp.Hardware)
        # One initial update is needed before asking whether sensor values exist.
        for hw in hardware:
            try:
                hw.Update()
            except Exception:
                pass
        import ctypes
        try:
            admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            admin = False
        try:
            report = str(comp.GetReport())
        except Exception as exc:
            report = 'Backend report unavailable: ' + str(exc)
        try:
            pawnio = probe_pawnio()
        except Exception as exc:
            pawnio = dict(installed=None, version=None, access_error=None, error=str(exc))
        diagnostics = diagnose_backend(hardware, report, admin=admin, pawnio=pawnio)
        emit({'type': 'READY', 'backend': 'LHM ' + manifest['release'] + ' net472', 'diagnostics': diagnostics})
        def read(hw, readings, errors):
            try:
                hw.Update()
                for sensor in hw.Sensors:
                    if sensor.SensorType != Hardware.SensorType.Temperature or sensor.Value is None:
                        continue
                    kind = classify_sensor(str(hw.HardwareType), str(sensor.Name))
                    if kind:
                        readings.append(dict(id=str(sensor.Identifier), label=f'{hw.Name}/{sensor.Name}',
                                             kind=kind, value=float(sensor.Value)))
            except Exception as exc:
                errors.append(f'{hw.Name}: {exc}')
            for sub in hw.SubHardware:
                read(sub, readings, errors)
        # Independent schedules: a GPU Update does not sit before the next CPU
        # sample in Python. Native driver/global CLR locks can still delay either.
        def sample_group(group):
            selected = [hw for hw in hardware if (
                str(hw.HardwareType) == 'Cpu' if group == 'cpu' else str(hw.HardwareType).startswith('Gpu'))]
            _sample_group(group, selected, read, stop)
        workers = [threading.Thread(target=sample_group, args=(group,), name='lhm-'+group)
                   for group in ('cpu', 'gpu')]
        for worker in workers:
            worker.start()
        # Close() only runs after both samplers have stopped using Computer.
        # If a native Update hangs, the parent enforces the child deadline.
        for worker in workers:
            worker.join()

        return 0
    except Exception:
        emit({'type': 'error', 'reason': traceback.format_exc()})
        return 1
    finally:
        if comp is not None:
            try:
                comp.Close()
            except Exception:
                # Parent owns the bounded lifetime even if native Close blocks.
                traceback.print_exc(file=sys.stderr)
