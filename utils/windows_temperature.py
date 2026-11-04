"""One persistent Windows temperature child. No CLR/WMI inside the GUI process."""
import json
import logging
import math
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

log = logging.getLogger('cyberclean.temperature')


def temperature_status_text(status, value=None):
    """Return a localized, evidence-based explanation for the dashboard tooltip."""
    from utils.i18n import _t

    status = status if isinstance(status, dict) else {}
    if value is not None:
        source = status.get('source') or {}
        label = source.get('label') or _t('temp_source_cpu', 'CPU sensor')
        age = source.get('age_seconds')
        if isinstance(age, (int, float)) and math.isfinite(age):
            return _t('temp_reading_ok', 'Source: {source}; latest sample {age:.1f}s ago.',
                      source=label, age=max(0., age))
        return _t('temp_reading_ok_no_age', 'Source: {source}.', source=label)

    code = status.get('reason_code')
    messages = {
        'pawnio_missing': ('temp_pawnio_missing',
            'LHM detected the CPU, but PawnIO is not installed. Windows needs administrator approval to install this sensor driver.'),
        'cpu_access_denied': ('temp_access_denied',
            'Windows denied access to the CPU sensor. This sensor needs administrator-level hardware access.'),
        'cpu_driver_blocked': ('temp_driver_blocked',
            'Windows blocked the hardware sensor driver. No temperature is shown; keep Windows security protections enabled.'),
        'cpu_driver_unavailable': ('temp_driver_unavailable',
            'The hardware sensor driver is unavailable. No temperature could be read.'),
        'cpu_hardware_missing': ('temp_hardware_missing',
            'LibreHardwareMonitor did not detect a CPU sensor device.'),
        'cpu_sensor_missing': ('temp_sensor_missing',
            'The CPU was detected, but it exposes no temperature sensor to LibreHardwareMonitor.'),
        'cpu_sensor_no_value': ('temp_sensor_no_value',
            'The CPU temperature sensor was detected, but returned no value.'),
        'cpu_data_stale': ('temp_data_stale',
            'The last CPU temperature sample is too old, so it is hidden.'),
        'sensor_helper_not_installed': ('temp_helper_not_installed',
            'The protected temperature reader is not installed. Install CyberClean to enable this sensor.'),
        'elevation_cancelled': ('temp_elevation_cancelled',
            'Windows administrator approval was cancelled. No temperature was read.'),
        'sensor_helper_failed': ('temp_helper_failed',
            'The protected temperature reader could not start. No temperature was read.'),
    }
    key, default = messages.get(code, ('temp_unavailable',
        'No fresh CPU temperature is available. The dashboard will not substitute GPU or estimated values.'))
    details = _t(key, default)
    backend = status.get('backend')
    return f'{details} ({backend})' if backend else details


def classify_sensor(hardware_type, name):
    name = name.lower()
    if 'distance' in name or 'tjmax' in name or 'tjunction' in name or 'average' in name:
        return None
    if hardware_type == 'Cpu':
        if 'package' in name:
            return 'cpu_package'
        if 'core max' in name:
            return 'cpu_core_max'
        if 'core' in name:
            return 'cpu_core'
        return None
    if hardware_type.startswith('Gpu'):
        return 'gpu'
    return None


def select_readings(readings, now, max_age=3.):
    fresh = [r for r in readings if 0 <= now-r['received'] <= max_age]
    cpu = None
    for kind in ('cpu_package', 'cpu_core_max', 'cpu_core'):
        candidates = [r['value'] for r in fresh if r['kind'] == kind]
        if candidates:
            cpu = max(candidates)
            break
    return cpu, {r['id']: r['value'] for r in fresh}


class TemperatureHost:
    def __init__(self, command=None, startup_timeout=12., sample_timeout=4., clock=time.monotonic):
        if command is None:
            command = [sys.executable, '--windows-temp-host'] if getattr(sys, 'frozen', False) else [
                sys.executable, str(Path(__file__).resolve().parents[1] / 'main.py'), '--windows-temp-host']
        self.command, self.clock = command, clock
        self._diagnostics = {}
        self._backend_diagnostics = {}
        self._backend = ''
        self.startup_timeout, self.sample_timeout = startup_timeout, sample_timeout
        self._stop = threading.Event()
        self._privileged_requested = threading.Event()
        self._lock = threading.Lock()
        self._thread = None
        self._readings = []
        self._reason = 'not started'
        self._last_sample = None

    def start(self):
        with self._lock:
            if self._thread is not None or self._stop.is_set():
                return
            self._thread = threading.Thread(target=self._supervise, name='temperature-host', daemon=True)
            self._thread.start()

    def _set_reason(self, reason):
        with self._lock:
            self._reason = reason
        log.warning('%s', reason)

    def _set_backend_reason(self, code, reason):
        with self._lock:
            self._backend_diagnostics = dict(reason_code=code, requires_admin=False)
            self._reason = reason
        log.warning('%s', reason)

    def request_privileged_access(self):
        """Ask for a one-session, sensor-only helper from the protected install path."""
        from utils.windows_sensor_access import installed_sensor_helper
        if installed_sensor_helper() is None:
            self._set_backend_reason('sensor_helper_not_installed',
                                     'Protected sensor helper is not installed')
            return False
        if self._stop.is_set():
            return False
        self._privileged_requested.set()
        return True

    @staticmethod
    def _read_pipe(stream, messages):
        try:
            for line in stream:
                messages.put(line)
        finally:
            messages.put(None)

    def _supervise(self):
        backoff = 1.
        while not self._stop.is_set():
            proc, reader = None, None
            elevated = self._privileged_requested.is_set()
            restart_for_elevation = False
            try:
                if elevated:
                    self._set_reason('requesting read-only sensor access')
                    from utils.windows_sensor_access import start_elevated_sensor_host
                    proc = start_elevated_sensor_host()
                else:
                    self._set_reason('starting LHM host')
                    proc = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
                                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                messages = queue.Queue(maxsize=64)
                reader = threading.Thread(target=self._read_pipe, args=(proc.stdout, messages), daemon=True)
                reader.start()
                ready = False
                deadline = self.clock()+self.startup_timeout
                while not self._stop.is_set():
                    if self._privileged_requested.is_set() and not elevated:
                        restart_for_elevation = True
                        break
                    if self.clock() >= deadline:
                        raise TimeoutError('sample deadline exceeded' if ready else 'READY handshake deadline exceeded')
                    try:
                        line = messages.get(timeout=.1)
                    except queue.Empty:
                        continue
                    if line is None:
                        raise RuntimeError(f'host pipe closed; exit={proc.poll()}')
                    message = json.loads(line)
                    if message.get('type') == 'error':
                        raise RuntimeError(message['reason'])
                    if message.get('type') == 'READY':
                        ready = True
                        with self._lock:
                            self._backend = str(message.get('backend', ''))
                            self._backend_diagnostics = dict(message.get('diagnostics', {}))
                        deadline = self.clock()+self.sample_timeout
                        group_deadlines = dict(cpu=deadline, gpu=deadline)
                    elif message.get('type') == 'sample' and ready:
                        now = self.clock()
                        readings = []
                        for r in message['readings']:
                            value = float(r['value'])
                            if math.isfinite(value) and 1 < value < 150 and r['kind'] in (
                                    'cpu_package', 'cpu_core_max', 'cpu_core', 'gpu', 'acpi'):
                                readings.append(dict(r, value=value, received=now))
                        group = message.get('group')
                        with self._lock:
                            if group in ('cpu', 'gpu'):
                                self._readings = [r for r in self._readings if not r['kind'].startswith(group)] + readings
                                self._diagnostics[group] = message.get('reason', '')
                            else:
                                self._readings = readings
                            if readings:
                                self._last_sample = now
                            self._reason = '; '.join(v for v in self._diagnostics.values() if v) or 'sample received'
                        if group in ('cpu', 'gpu'):
                            group_deadlines[group] = now+self.sample_timeout
                        else:
                            # Legacy/fake hosts may deliver a combined sample.
                            group_deadlines = dict(cpu=now+self.sample_timeout,
                                                   gpu=now+self.sample_timeout)
                        # A healthy GPU heartbeat cannot hide a hung CPU Update,
                        # or vice versa. Restart the dedicated child on either.
                        deadline = min(group_deadlines.values())
                        backoff = 1.
            except Exception as exc:
                if elevated:
                    self._privileged_requested.clear()
                    cancelled = getattr(exc, 'winerror', None) == 1223
                    code = 'elevation_cancelled' if cancelled else 'sensor_helper_failed'
                    message = ('Sensor permission was not approved' if cancelled else
                               f'{type(exc).__name__}: {exc}')
                    self._set_backend_reason(code, message)
                else:
                    self._set_reason(f'{type(exc).__name__}: {exc}')
            finally:
                if proc is not None:
                    try:
                        if proc.poll() is None:
                            proc.stdin.write('STOP\n'); proc.stdin.flush()
                            proc.wait(timeout=1.5)
                    except (OSError, subprocess.TimeoutExpired):
                        # This dedicated child may be stuck inside native CLR/Close.
                        # No QThread or GUI process is forcibly terminated.
                        if proc.poll() is None:
                            proc.terminate()
                            try:
                                proc.wait(timeout=1.)
                            except subprocess.TimeoutExpired:
                                proc.kill(); proc.wait(timeout=1.)
                    finally:
                        for stream in (proc.stdin, proc.stdout):
                            if stream: stream.close()
                        if reader: reader.join(timeout=.5)
            if restart_for_elevation:
                backoff = .1
                continue
            if self._stop.wait(backoff):
                break
            backoff = min(60., backoff*2)

    def snapshot(self):
        with self._lock:
            now = self.clock()
            cpu, readings = select_readings(self._readings, now)
            age = None if self._last_sample is None else max(0., now-self._last_sample)
            reason = self._reason
            if cpu is None:
                reason += '; no fresh CPU temperature (GPU/ACPI are not substitutes)'
            fresh_cpu = [r for r in self._readings if r['kind'].startswith('cpu_') and
                         0 <= now-r['received'] <= 3.]
            source = None
            for kind in ('cpu_package', 'cpu_core_max', 'cpu_core'):
                candidates = [r for r in fresh_cpu if r['kind'] == kind]
                if candidates:
                    selected = max(candidates, key=lambda reading: reading['value'])
                    source = dict(id=selected['id'], label=selected.get('label', selected['id']),
                                  kind=kind, age_seconds=max(0., now-selected['received']))
                    break
            code = ('cpu_sensor_available' if cpu is not None else
                    self._backend_diagnostics.get('reason_code', 'cpu_data_unavailable'))
            if cpu is None and code == 'cpu_sensor_available':
                code = 'cpu_data_stale'
            return dict(cpu=None if self._stop.is_set() else cpu,
                        readings={} if self._stop.is_set() else readings,
                        age_seconds=age, state='closed' if self._stop.is_set() else ('fresh' if cpu is not None else 'unavailable'),
                        reason=reason, reason_code=code,
                        requires_admin=bool(cpu is None and self._backend_diagnostics.get('requires_admin')),
                        backend=self._backend, source=None if self._stop.is_set() else source,
                        diagnostics=dict(self._backend_diagnostics),
                        sensors=[dict(r, age_seconds=max(0., now-r['received'])) for r in self._readings])

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5.)
            if self._thread.is_alive():
                log.error('Temperature supervisor did not finish within shutdown deadline')
