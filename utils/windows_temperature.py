"""One persistent Windows temperature child running with the app's privileges."""
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
            'LHM detected the CPU, but the PawnIO sensor driver is not installed. Click this card to install PawnIO (requires administrator approval) or run the CyberClean installer.'),
        'pawnio_reboot_required': ('temp_pawnio_reboot_required',
            'PawnIO sensor driver is installed, but Windows requires a system restart to finish loading it.'),
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
        self._override_reason_code = None
        self._backend = ''
        self.startup_timeout, self.sample_timeout = startup_timeout, sample_timeout
        self._stop = threading.Event()
        self._restart_requested = threading.Event()
        self._lock = threading.Lock()
        self._thread = None
        self._readings = []
        self._reason = 'not started'
        self._last_sample = None

    def start(self):
        with self._lock:
            if self._stop.is_set() or (self._thread is not None and self._thread.is_alive()):
                return
            self._thread = threading.Thread(target=self._supervise, name='temperature-host', daemon=True)
            self._thread.start()

    def _set_reason(self, reason):
        with self._lock:
            self._reason = reason
        log.warning('%s', reason)

    def _set_backend_reason(self, code, reason):
        self.set_diagnostic_reason(code, reason, requires_admin=False)

    def set_diagnostic_reason(self, code, reason, *, requires_admin=False, setup_required=None):
        with self._lock:
            diag = dict(self._backend_diagnostics)
            diag['reason_code'] = code
            diag['requires_admin'] = bool(requires_admin)
            if setup_required is not None:
                diag['setup_required'] = bool(setup_required)
            elif code == 'pawnio_missing':
                diag['setup_required'] = True
            self._backend_diagnostics = diag
            self._override_reason_code = code
            self._reason = reason
        log.warning('%s (%s)', reason, code)

    def request_privileged_access(self):
        """Restart the child temperature reader (e.g. after PawnIO driver installation)."""
        if self._stop.is_set():
            return False
        with self._lock:
            if self._override_reason_code in ('pawnio_missing', 'cpu_access_denied'):
                self._override_reason_code = None
                if self._backend_diagnostics.get('reason_code') == 'pawnio_missing':
                    diag = dict(self._backend_diagnostics)
                    diag['setup_required'] = False
                    self._backend_diagnostics = diag
        self._restart_requested.set()
        self.start()
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
            self._restart_requested.clear()
            restart_immediately = False
            try:
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
                    if self._restart_requested.is_set():
                        restart_immediately = True
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
                            incoming = dict(message.get('diagnostics', {}))
                            incoming_code = incoming.get('reason_code')
                            if incoming_code == 'cpu_sensor_available':
                                self._override_reason_code = None
                            elif self._override_reason_code == 'pawnio_reboot_required':
                                incoming['reason_code'] = 'pawnio_reboot_required'
                                incoming['requires_admin'] = False
                            elif incoming_code in ('pawnio_missing', 'pawnio_reboot_required'):
                                self._override_reason_code = None
                            elif (incoming_code in ('cpu_access_denied', None, '')
                                  and self._override_reason_code in ('pawnio_missing', 'pawnio_reboot_required')):
                                incoming['reason_code'] = self._override_reason_code
                                incoming['requires_admin'] = False
                                if self._override_reason_code == 'pawnio_missing':
                                    incoming['setup_required'] = True
                            self._backend_diagnostics = incoming
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
                            group_deadlines = dict(cpu=now+self.sample_timeout,
                                                   gpu=now+self.sample_timeout)
                        deadline = min(group_deadlines.values())
                        backoff = 1.
            except Exception as exc:
                self._set_reason(f'{type(exc).__name__}: {exc}')
            finally:
                if proc is not None:
                    try:
                        if proc.poll() is None:
                            proc.stdin.write('STOP\n'); proc.stdin.flush()
                            proc.wait(timeout=1.5)
                    except (OSError, subprocess.TimeoutExpired):
                        if proc.poll() is None:
                            try:
                                proc.terminate()
                            except OSError:
                                pass
                            try:
                                proc.wait(timeout=1.)
                            except (OSError, subprocess.TimeoutExpired):
                                try:
                                    proc.kill()
                                except OSError:
                                    pass
                                try:
                                    proc.wait(timeout=1.)
                                except (OSError, subprocess.TimeoutExpired):
                                    pass
                    finally:
                        for stream in (proc.stdin, proc.stdout):
                            if stream:
                                try:
                                    stream.close()
                                except OSError:
                                    pass
                        if reader:
                            reader.join(timeout=.5)
            if restart_immediately:
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
