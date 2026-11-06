"""Temperature protocol tests: fake child, no CLR/WMI/hardware access."""
import hashlib
import json
from pathlib import Path
import sys
import time
from utils.windows_temperature import (TemperatureHost, classify_sensor, select_readings,
                                       temperature_status_text)


def wait_for(predicate, timeout=3):
    end = time.monotonic()+timeout
    while time.monotonic() < end:
        if predicate(): return
        time.sleep(.01)
    assert predicate()


def test_classification_never_substitutes_gpu_or_distance_for_cpu():
    assert classify_sensor('Cpu', 'CPU Package') == 'cpu_package'
    assert classify_sensor('Cpu', 'Core Max') == 'cpu_core_max'
    assert classify_sensor('Cpu', 'Core #1 Distance to TjMax') is None
    assert classify_sensor('Cpu', 'Core Average') is None
    assert classify_sensor('GpuIntel', 'GPU Core') == 'gpu'
    assert classify_sensor('Motherboard', 'CPU') is None
    readings = [dict(id='old', kind='cpu_package', value=95, received=1),
                dict(id='new', kind='cpu_core', value=55, received=5),
                dict(id='gpu', kind='gpu', value=75, received=5)]
    cpu, values = select_readings(readings, 6)
    assert cpu == 55 and 'old' not in values
    assert select_readings(readings[2:], 6)[0] is None
    assert select_readings(readings, 10) == (None, {})


def test_fake_host_handshake_cache_and_terminal_close():
    script = '''import json,sys,time
print(json.dumps({'type':'READY'}),flush=True)
print(json.dumps({'type':'sample','group':'cpu','readings':[{'id':'cpu','kind':'cpu_package','value':51}]}),flush=True)
print(json.dumps({'type':'sample','group':'gpu','readings':[{'id':'gpu','kind':'gpu','value':70}]}),flush=True)
for line in sys.stdin:
    if line.strip() == 'STOP': break
'''
    host = TemperatureHost([sys.executable, '-u', '-c', script])
    host.start()
    try:
        wait_for(lambda: len(host.snapshot()['readings']) == 2)
        assert host.snapshot()['cpu'] == 51
        assert host.snapshot()['age_seconds'] < 1
    finally:
        host.close()
    thread = host._thread
    assert not thread.is_alive()
    assert host.snapshot()['state'] == 'closed'
    assert host.snapshot()['cpu'] is None
    host.start()
    assert host._thread is thread


def test_ready_deadline_is_independent_of_sample_deadline():
    script = "import time; time.sleep(.15); print('{\"type\":\"READY\"}',flush=True); time.sleep(10)"
    host = TemperatureHost([sys.executable, '-u', '-c', script], startup_timeout=.7, sample_timeout=.1)
    host.start()
    try:
        wait_for(lambda: 'sample deadline exceeded' in host.snapshot()['reason'])
        assert host.snapshot()['cpu'] is None
    finally:
        host.close()
    assert not host._thread.is_alive()


def test_pinned_vendor_hashes_and_packaging():
    root = Path(__file__).resolve().parents[1]
    vendor = root / 'vendor/lhm'
    manifest = json.loads((vendor/'manifest.json').read_text(encoding='utf-8'))
    assert manifest['release'] == 'v0.9.6'
    assert set(manifest['sha256']) == {'HidSharp.dll', 'LibreHardwareMonitorLib.dll',
        'BlackSharp.Core.dll', 'DiskInfoToolkit.dll', 'RAMSPDToolkit-NDD.dll',
        'System.Numerics.Vectors.dll', 'System.Memory.dll', 'System.Buffers.dll',
        'System.Runtime.CompilerServices.Unsafe.dll'}
    assert set(manifest['load_order']) == set(manifest['sha256'])
    for name, digest in manifest['sha256'].items():
        assert hashlib.sha256((vendor/name).read_bytes()).hexdigest() == digest
    pawnio = manifest['pawnio']
    assert pawnio['version'] == '2.2.0'
    assert pawnio['installer'] == 'PawnIO_setup.exe'
    assert pawnio['sha256'] == '1f519a22e47187f70a1379a48ca604981c4fcf694f4e65b734aaa74a9fba3032'
    spec_text = (root/'CyberClean.spec').read_text(encoding='utf-8')
    assert 'vendor/lhm' in spec_text
    assert 'uac_admin=True' in spec_text
    build_text = (root/'build.py').read_text(encoding='utf-8')
    assert 'vendor/lhm' in build_text
    assert '--uac-admin' in build_text
    iss_text = (root/'CyberClean.iss').read_text(encoding='utf-8')
    assert 'PawnIO_setup.exe' in iss_text
    assert 'ShouldInstallPawnIO' in iss_text
    assert 'DisplayVersion' in iss_text


def test_gpu_heartbeat_does_not_hide_hung_cpu_sampler():
    script = '''import json,time
print(json.dumps({'type':'READY'}),flush=True)
while True:
    print(json.dumps({'type':'sample','group':'gpu','readings':[]}),flush=True)
    time.sleep(.02)
'''
    host = TemperatureHost([sys.executable, '-u', '-c', script], sample_timeout=.15)
    host.start()
    try:
        wait_for(lambda: 'sample deadline exceeded' in host.snapshot()['reason'])
        assert host.snapshot()['cpu'] is None
    finally:
        host.close()
    assert not host._thread.is_alive()


def test_sensorless_hardware_is_retried_within_ten_seconds_with_empty_heartbeats():
    from utils.windows_temperature_host import _sample_group
    class Stop:
        now = 0
        def is_set(self):return self.now >= 12
        def wait(self,seconds):self.now += seconds
    stop=Stop();probes=[];messages=[]
    def read(hardware,readings,errors):probes.append(stop.now)
    _sample_group('cpu',[object()],read,stop,send=messages.append,clock=lambda:stop.now)
    assert probes == [0,10]
    assert len(messages)==12 and all(message['readings']==[] for message in messages)
    assert [i for i,message in enumerate(messages) if message['hardware_sampled']] == [0,10]
    assert all('retry within 10s' in message['reason'] for message in messages)


def test_sample_group_never_emits_empty_heartbeat_on_early_wakeup_when_sensors_active():
    from utils.windows_temperature_host import _sample_group

    class EarlyWakeStop:
        def __init__(self):
            self.now = 0.0
            self.steps = 0

        def is_set(self):
            return self.steps >= 4

        def wait(self, seconds):
            self.steps += 1
            self.now += max(0.0, seconds - 0.008)

    stop = EarlyWakeStop()
    messages = []

    def read(hardware, readings, errors):
        stop.now += 0.015
        readings.append({'id': '/cpu/0/temp/0', 'label': 'CPU Package', 'kind': 'cpu_package', 'value': 62.0})

    _sample_group('cpu', [object()], read, stop, send=messages.append, clock=lambda: stop.now)
    assert len(messages) == 4
    assert all(m['hardware_sampled'] is True for m in messages)
    assert all(len(m['readings']) == 1 and m['readings'][0]['value'] == 62.0 for m in messages)


def test_empty_heartbeats_clear_temperature_without_refreshing_value_age():
    script = '''import json,time,sys
print(json.dumps({'type':'READY'}),flush=True)
print(json.dumps({'type':'sample','group':'cpu','readings':[{'id':'cpu','kind':'cpu_package','value':51}]}),flush=True)
time.sleep(.05)
for i in range(30):
    for group in ('cpu','gpu'):
        print(json.dumps({'type':'sample','group':group,'readings':[]}),flush=True)
    time.sleep(.02)
for line in sys.stdin:
    if line.strip()=='STOP':break
'''
    host=TemperatureHost([sys.executable,'-u','-c',script])
    host.start()
    try:
        wait_for(lambda: host.snapshot()['age_seconds'] is not None and
                 host.snapshot()['age_seconds'] > .2 and not host.snapshot()['readings'])
        assert host.snapshot()['cpu'] is None
        assert host.snapshot()['state']=='unavailable'
    finally:
        host.close()


def test_backend_diagnosis_reports_exact_missing_access_without_faking_temperature():
    from types import SimpleNamespace as N
    from utils.windows_temperature_host import diagnose_backend
    cpu=N(HardwareType='Cpu',SubHardware=[],Sensors=[
        N(Identifier='/intelcpu/0/temp/0',Name='CPU Package',SensorType='Temperature',Value=None),
        N(Identifier='/intelcpu/0/load/0',Name='CPU Total',SensorType='Load',Value=12.)])
    result=diagnose_backend([cpu], 'Ring0\nStatus: Installing driver failed\n'
                            'First Exception: OpenSCManager returned the error code: 00000005.', admin=False)
    assert result['reason_code']=='cpu_access_denied'
    assert result['requires_admin'] and not result['elevation_supported']
    assert result['raw_cpu_sensors']==[dict(id='/intelcpu/0/temp/0',name='CPU Package',has_value=False)]


def test_backend_diagnosis_keeps_non_permission_failure_distinct():
    from types import SimpleNamespace as N
    from utils.windows_temperature_host import diagnose_backend
    cpu=N(HardwareType='Cpu',SubHardware=[],Sensors=[
        N(Identifier='package',Name='CPU Package',SensorType='Temperature',Value=None)])
    result=diagnose_backend([cpu], 'Ring0\nStatus: driver load failed: code 577',admin=True)
    assert result['reason_code']=='cpu_driver_unavailable'
    assert not result['requires_admin']


def test_modern_pawnio_diagnostics_distinguish_setup_reboot_permission_and_driver_errors():
    from types import SimpleNamespace as N
    from utils.windows_temperature_host import diagnose_backend

    cpu=N(HardwareType='Cpu',SubHardware=[],Sensors=[
        N(Identifier='package',Name='CPU Package',SensorType='Temperature',Value=None)])
    missing=diagnose_backend([cpu],admin=False,pawnio=dict(installed=False))
    assert missing['reason_code']=='pawnio_missing' and missing['setup_required']
    assert not missing['requires_admin']
    reboot=diagnose_backend([cpu],admin=True,pawnio=dict(installed=True,access_error=2,reboot_required=True))
    assert reboot['reason_code']=='pawnio_reboot_required' and reboot['reboot_required']
    assert not reboot['requires_admin']
    post_reboot_unavail=diagnose_backend([cpu],admin=True,pawnio=dict(installed=True,access_error=2,reboot_required=False))
    assert post_reboot_unavail['reason_code']=='cpu_driver_unavailable'
    assert not post_reboot_unavail['reboot_required'] and not post_reboot_unavail['setup_required']
    denied=diagnose_backend([cpu],admin=False,pawnio=dict(installed=True,access_error=5))
    assert denied['reason_code']=='cpu_access_denied' and denied['requires_admin']
    blocked=diagnose_backend([cpu],admin=True,pawnio=dict(installed=True,access_error=577))
    assert blocked['reason_code']=='cpu_driver_blocked' and not blocked['requires_admin']

    unknown_no_sensors=diagnose_backend([N(HardwareType='Cpu',SubHardware=[],Sensors=[])],
                                        admin=True, pawnio=dict(installed=None, version=None, access_error=None))
    assert unknown_no_sensors['reason_code']=='cpu_sensor_missing'
    assert not unknown_no_sensors['setup_required']


def test_host_probe_pawnio_uses_pure_python_probe_pawnio_state(monkeypatch):
    from utils import windows_sensor_access as access
    from utils.windows_temperature_host import probe_pawnio

    monkeypatch.setattr(
        access,
        'probe_pawnio_state',
        lambda: access.PawnIOState(access.PawnIOStatus.READY, True, '2.2.0.0', None),
    )
    res = probe_pawnio()
    assert res == dict(
        installed=True,
        version='2.2.0.0',
        access_error=None,
        reboot_required=False,
        status='ready',
    )


def test_protocol_preserves_backend_reason_and_reports_exact_fresh_cpu_source():
    script='''import json,sys
print(json.dumps({'type':'READY','backend':'fixture','diagnostics':{'reason_code':'cpu_access_denied','requires_admin':True}}),flush=True)
for group in ('cpu','gpu'):
    print(json.dumps({'type':'sample','group':group,'readings':[]}),flush=True)
for line in sys.stdin:
    if line.strip()=='STOP':break
'''
    host=TemperatureHost([sys.executable,'-u','-c',script]);host.start()
    try:
        wait_for(lambda:host.snapshot()['reason_code']=='cpu_access_denied')
        result=host.snapshot()
        assert result['requires_admin'] and result['cpu'] is None and result['source'] is None
    finally:host.close()
    host=TemperatureHost(clock=lambda:10.)
    host._readings=[dict(id='core',label='Core Max',kind='cpu_core_max',value=66.,received=9.5),
                    dict(id='package',label='CPU Package',kind='cpu_package',value=65.,received=9.5)]
    result=host.snapshot()
    assert result['cpu']==65 and result['source']==dict(id='package',label='CPU Package',kind='cpu_package',age_seconds=.5)


def test_restart_clears_pawnio_missing_override_and_restarts_child():
    script = '''import json,sys
print(json.dumps({'type':'READY','backend':'lhm','diagnostics':{'reason_code':'cpu_sensor_available'}}),flush=True)
print(json.dumps({'type':'sample','group':'cpu','readings':[{'id':'cpu','kind':'cpu_package','value':58}]}),flush=True)
for line in sys.stdin:
    if line.strip()=='STOP': break
'''
    host = TemperatureHost([sys.executable, '-u', '-c', script])
    host.set_diagnostic_reason('pawnio_missing', 'PawnIO not installed')
    assert host._override_reason_code == 'pawnio_missing'

    assert host.request_privileged_access() is True
    assert host._override_reason_code is None
    try:
        wait_for(lambda: host.snapshot()['cpu'] == 58, timeout=4)
    finally:
        host.close()


def test_temperature_tooltip_explains_missing_pawnio_in_current_language(monkeypatch):
    from utils.i18n import T
    monkeypatch.setattr(T, 'lang', 'vi')
    status = dict(reason_code='pawnio_missing', backend='LHM v0.9.6 net472')
    text = temperature_status_text(status)
    assert 'đã nhận diện CPU' in text
    assert 'PawnIO' in text and 'quyền quản trị' in text
    assert 'LHM v0.9.6' in text


def test_temperature_tooltip_explains_reboot_required_in_vietnamese(monkeypatch):
    from utils.i18n import T
    monkeypatch.setattr(T, 'lang', 'vi')
    status = dict(reason_code='pawnio_reboot_required', backend='LHM v0.9.6 net472')
    text = temperature_status_text(status)
    assert 'PawnIO' in text and 'khởi động lại' in text


def test_temperature_tooltip_names_real_sensor_and_sample_age(monkeypatch):
    from utils.i18n import T
    monkeypatch.setattr(T, 'lang', 'vi')
    text = temperature_status_text(
        {'source': {'label': 'CPU Package', 'age_seconds': .4}}, 62.0)
    assert 'CPU Package' in text and '0.4 giây' in text


def test_main_auto_request_temperature_access_three_state_flow(monkeypatch):
    import ast
    from types import SimpleNamespace
    from utils.i18n import _t
    from utils import windows_sensor_access as access
    from utils import windows_telemetry as telemetry

    main_path = Path(__file__).resolve().parents[1] / 'main.py'
    tree = ast.parse(main_path.read_text(encoding='utf-8'))
    app_cls = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == 'CyberCleanApp'
    )
    target_names = {
        '_update_temperature_card_feedback',
        '_set_temperature_reason',
        '_detect_pawnio_issue',
        '_is_pawnio_missing',
        '_request_temperature_access',
        '_auto_request_temperature_access',
    }
    selected_methods = [
        node for node in app_cls.body
        if isinstance(node, ast.FunctionDef) and node.name in target_names
    ]
    mod_ast = ast.Module(body=selected_methods, type_ignores=[])
    ast.fix_missing_locations(mod_ast)
    ns = {
        'IS_WINDOWS': True,
        '_t': _t,
        'temperature_status_text': temperature_status_text,
        'sys': sys,
    }
    exec(compile(mod_ast, str(main_path), 'exec'), ns)

    class DummyCard:
        def __init__(self):
            self.tooltip = ''
            self.hint = ''
        def setToolTip(self, text):
            self.tooltip = text
        def set_hint(self, text):
            self.hint = text

    class DummyApp:
        _shutting_down = False
        _update_temperature_card_feedback = ns['_update_temperature_card_feedback']
        _set_temperature_reason = ns['_set_temperature_reason']
        _detect_pawnio_issue = ns['_detect_pawnio_issue']
        _is_pawnio_missing = ns['_is_pawnio_missing']
        _request_temperature_access = ns['_request_temperature_access']
        _auto_request_temperature_access = ns['_auto_request_temperature_access']
        def __init__(self):
            self._snap = SimpleNamespace(temp_max=None, temperature_status={})
            self._stat_cards = {'temp': DummyCard()}

    recorded_reasons = []
    requested_access = []
    monkeypatch.setattr(
        telemetry,
        'set_windows_temperature_reason',
        lambda code, reason, **kw: recorded_reasons.append((code, reason)) or True,
    )
    monkeypatch.setattr(
        telemetry,
        'request_windows_temperature_access',
        lambda: requested_access.append(True) or True,
    )

    # State 1: PawnIO is missing -> sets pawnio_missing, updates tooltip and inline card hint
    monkeypatch.setattr(access, 'is_pawnio_installed', lambda: False)
    dummy = DummyApp()
    dummy._auto_request_temperature_access()
    assert dummy._snap.temperature_status['reason_code'] == 'pawnio_missing'
    assert recorded_reasons[-1][0] == 'pawnio_missing'
    assert 'PawnIO' in dummy._stat_cards['temp'].tooltip
    assert dummy._stat_cards['temp'].hint != ''
    assert not requested_access

    # State 2: PawnIO installed, but pending reboot -> sets pawnio_reboot_required
    monkeypatch.setattr(access, 'is_pawnio_installed', lambda: True)
    monkeypatch.setattr(
        access,
        'probe_pawnio_state',
        lambda: access.PawnIOState(access.PawnIOStatus.REBOOT_REQUIRED, True, '2.2.0.0', 2),
    )
    dummy_reboot = DummyApp()
    dummy_reboot._auto_request_temperature_access()
    assert dummy_reboot._snap.temperature_status['reason_code'] == 'pawnio_reboot_required'
    assert recorded_reasons[-1][0] == 'pawnio_reboot_required'
    assert not requested_access

    # State 3: PawnIO installed & active -> triggers temperature reader
    monkeypatch.setattr(
        access,
        'probe_pawnio_state',
        lambda: access.PawnIOState(access.PawnIOStatus.READY, True, '2.2.0.0', None),
    )
    dummy_ready = DummyApp()
    dummy_ready._auto_request_temperature_access()
    assert requested_access == [True]
