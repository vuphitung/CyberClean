"""Linux CPU temperature selection (regression: stuck 74°C from max-of-all-sensors)."""
import time
import utils.sysinfo as si


def _mk(root, idx, chip, entries):
    d = root / 'hwmon' / f'hwmon{idx}'
    d.mkdir(parents=True)
    (d / 'name').write_text(chip + '\n')
    for n, (label, val) in enumerate(entries, 1):
        (d / f'temp{n}_input').write_text(str(int(val * 1000)) + '\n')
        if label:
            (d / f'temp{n}_label').write_text(label + '\n')


def _run(tmp_path, monkeypatch, setup):
    (tmp_path / 'hwmon').mkdir()
    (tmp_path / 'thermal').mkdir()
    setup(tmp_path)
    monkeypatch.setattr(si, '_SYS_HWMON', tmp_path / 'hwmon')
    monkeypatch.setattr(si, '_SYS_THERMAL', tmp_path / 'thermal')
    monkeypatch.setattr(si, '_linux_temp_cache', ({}, None, {}, 0.0))
    return si._read_linux_temperature()


def test_intel_ignores_stuck_acpi_and_hot_nvme(tmp_path, monkeypatch):
    def setup(r):
        _mk(r, 0, 'acpitz', [(None, 74.0)])
        _mk(r, 1, 'nvme', [('Composite', 68.0)])
        _mk(r, 2, 'coretemp', [('Package id 0', 45.0), ('Core 0', 44.0)])
    _all, cpu = _run(tmp_path, monkeypatch, setup)
    assert cpu == 45.0 and 'acpitz/temp1' in _all


def test_amd_prefers_tdie_over_tctl(tmp_path, monkeypatch):
    _all, cpu = _run(tmp_path, monkeypatch,
                     lambda r: _mk(r, 0, 'k10temp', [('Tctl', 61.0), ('Tdie', 51.0)]))
    assert cpu == 51.0


def test_no_sensor_returns_none(tmp_path, monkeypatch):
    _all, cpu = _run(tmp_path, monkeypatch, lambda r: None)
    assert cpu is None and si._linux_temp_meta['reason_code'] == 'no_cpu_sensor'


def test_value_follows_hardware_after_ttl(tmp_path, monkeypatch):
    _run(tmp_path, monkeypatch, lambda r: _mk(r, 0, 'coretemp', [('Package id 0', 40.0)]))
    (tmp_path / 'hwmon' / 'hwmon0' / 'temp1_input').write_text('66000\n')
    monkeypatch.setattr(si, '_linux_temp_cache', ({}, None, {}, time.time() - 10))
    assert si._read_linux_temperature()[1] == 66.0
