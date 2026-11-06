"""PawnIO driver verification, installation, and state probe tests."""
import hashlib
from pathlib import Path
import sys
import types

import pytest

from utils import windows_sensor_access as access


def test_find_pawnio_installer_verifies_sha256_in_bundled_locations(tmp_path, monkeypatch):
    payload = b'official-pawnio-setup-fixture'
    digest = hashlib.sha256(payload).hexdigest()

    pf_dir = tmp_path / 'Program Files'
    install_dir = pf_dir / 'CyberClean'
    install_dir.mkdir(parents=True)
    installer = install_dir / access.PAWNIO_FILENAME
    installer.write_bytes(payload)

    monkeypatch.setattr(access.sys, 'platform', 'win32')
    monkeypatch.setenv('ProgramFiles', str(pf_dir))
    monkeypatch.delenv('ProgramW6432', raising=False)
    monkeypatch.delenv('ProgramFiles(x86)', raising=False)

    assert access.find_pawnio_installer(expected_sha256=digest) == installer.resolve()
    assert access.find_pawnio_installer(expected_sha256='0' * 64) is None

    installer.unlink()
    assert access.find_pawnio_installer(expected_sha256=digest) is None


def test_pawnio_installer_sha256_verification_and_exit_code_3010(tmp_path, monkeypatch):
    payload = b'fake-pawnio-installer-binary'
    digest = hashlib.sha256(payload).hexdigest()
    installer = tmp_path / 'PawnIO_setup.exe'
    installer.write_bytes(payload)

    assert access.verify_file_sha256(installer, digest) is True
    assert access.verify_file_sha256(installer, '0' * 64) is False

    monkeypatch.setattr(access.sys, 'platform', 'win32')
    monkeypatch.setattr(access, 'PAWNIO_SHA256', digest)

    executed = []
    next_exit_code = [0]

    class FakeProc:
        def wait(self, timeout=None):
            return next_exit_code[0]

    def fake_launch(cmd):
        executed.append(cmd)
        return FakeProc()

    # Exit code 0 -> INSTALLED
    res0 = access.install_pawnio_driver(
        installer_path=installer, allow_download=False, silent=True, launch=fake_launch
    )
    assert bool(res0) is True
    assert res0.status == access.PawnIOInstallStatus.INSTALLED
    assert res0.reboot_required is False
    assert res0.exit_code == 0
    assert executed == [[str(installer.resolve()), '-install', '-silent']]

    # Exit code 3010 (ERROR_SUCCESS_REBOOT_REQUIRED) -> REBOOT_REQUIRED, not an exception!
    next_exit_code[0] = 3010
    res3010 = access.install_pawnio_driver(
        installer_path=installer, allow_download=False, silent=True, launch=fake_launch
    )
    assert bool(res3010) is True
    assert res3010.status == access.PawnIOInstallStatus.REBOOT_REQUIRED
    assert res3010.reboot_required is True
    assert res3010.exit_code == 3010

    # Non-zero, non-3010 exit code -> raises RuntimeError
    next_exit_code[0] = 1603
    with pytest.raises(RuntimeError, match='1603'):
        access.install_pawnio_driver(
            installer_path=installer, allow_download=False, silent=True, launch=fake_launch
        )

    # Corrupted binary must be rejected before launch
    installer.write_bytes(b'tampered')
    with pytest.raises(ValueError, match='SHA-256'):
        access.install_pawnio_driver(
            installer_path=installer, allow_download=False, launch=fake_launch
        )


def test_downloaded_temp_pawnio_installer_is_cleaned_up_in_finally(tmp_path, monkeypatch):
    payload = b'downloaded-pawnio-setup-payload'
    digest = hashlib.sha256(payload).hexdigest()

    monkeypatch.setattr(access.sys, 'platform', 'win32')
    monkeypatch.setattr(access, 'PAWNIO_SHA256', digest)
    monkeypatch.setattr(access, 'find_pawnio_installer', lambda *a, **kw: None)

    created_temp_dirs = []

    def fake_download(*, expected_sha256=digest, **kw):
        temp_dir = tmp_path / 'cyberclean-pawnio-test123'
        temp_dir.mkdir(parents=True, exist_ok=True)
        target = temp_dir / access.PAWNIO_FILENAME
        target.write_bytes(payload)
        created_temp_dirs.append(temp_dir)
        return target

    monkeypatch.setattr(access, 'download_pawnio_installer', fake_download)

    observed_during_run = []

    class FakeProc:
        def wait(self, timeout=None):
            return 3010

    def fake_launch(cmd):
        exe_path = Path(cmd[0])
        observed_during_run.append(exe_path.is_file())
        return FakeProc()

    result = access.install_pawnio_driver(allow_download=True, launch=fake_launch)
    assert result.reboot_required is True
    assert observed_during_run == [True]
    assert len(created_temp_dirs) == 1
    assert not created_temp_dirs[0].exists(), 'Temporary installer directory must be deleted in finally'


def test_pawnio_display_version_parsing_matches_lhm_and_three_state_probe(monkeypatch):
    monkeypatch.setattr(access.sys, 'platform', 'win32')
    registry_values = {}

    fake_winreg = types.ModuleType('winreg')
    fake_winreg.HKEY_LOCAL_MACHINE = 'HKLM'
    fake_winreg.KEY_READ = 1
    fake_winreg.KEY_WOW64_64KEY = 2

    class FakeKey:
        def __enter__(self): return self
        def __exit__(self, *a): pass

    def open_key(root, subkey, reserved, flags):
        if 'Uninstall\\PawnIO' not in subkey or not registry_values.get('key_exists'):
            raise FileNotFoundError(subkey)
        return FakeKey()

    def query_value(key, name):
        if name not in registry_values:
            raise FileNotFoundError(name)
        return registry_values[name], 1

    fake_winreg.OpenKey = open_key
    fake_winreg.QueryValueEx = query_value
    monkeypatch.setitem(sys.modules, 'winreg', fake_winreg)

    # 1. Key exists, but DisplayVersion is missing -> NOT installed (matches LHM PawnIo.cs)
    registry_values['key_exists'] = True
    assert access.is_pawnio_installed() is False
    state = access.probe_pawnio_state()
    assert state.status == access.PawnIOStatus.NOT_INSTALLED
    assert state.installed is False

    # 2. Key has invalid DisplayVersion -> NOT installed
    registry_values['DisplayVersion'] = 'not-a-version'
    assert access.is_pawnio_installed() is False

    # 3. Key has valid DisplayVersion ('2.2.0.0'), device missing (err=2) -> REBOOT_REQUIRED
    registry_values['DisplayVersion'] = '2.2.0.0'
    monkeypatch.setattr(access, '_probe_pawnio_device_error', lambda: 2)
    assert access.is_pawnio_installed() is True
    state = access.probe_pawnio_state()
    assert state.status == access.PawnIOStatus.REBOOT_REQUIRED
    assert state.reboot_required is True
    assert state.version == '2.2.0.0'

    # 4. If PawnIO was installed before the current OS boot and still returns err=2 -> DRIVER_UNAVAILABLE (no reboot loop)
    monkeypatch.setattr(access, '_was_pawnio_installed_before_boot', lambda: True)
    state_post_boot = access.probe_pawnio_state()
    assert state_post_boot.status == access.PawnIOStatus.DRIVER_UNAVAILABLE
    assert state_post_boot.reboot_required is False
    assert state_post_boot.access_error == 2
    monkeypatch.setattr(access, '_was_pawnio_installed_before_boot', lambda: False)

    # 5. If _probe_pawnio_device_error returns None (exception), fail-closed as UNKNOWN (not READY)
    monkeypatch.setattr(access, '_probe_pawnio_device_error', lambda: None)
    state_unknown = access.probe_pawnio_state()
    assert state_unknown.status == access.PawnIOStatus.UNKNOWN
    assert state_unknown.installed is True
    assert state_unknown.reboot_required is False

    # 6. Device returns ERROR_ACCESS_DENIED (5) -> ACCESS_DENIED (driver running, needs elevation)
    monkeypatch.setattr(access, '_probe_pawnio_device_error', lambda: 5)
    state = access.probe_pawnio_state()
    assert state.status == access.PawnIOStatus.ACCESS_DENIED
    assert state.installed is True

    # 7. Device opens cleanly (0) -> READY
    monkeypatch.setattr(access, '_probe_pawnio_device_error', lambda: 0)
    state = access.probe_pawnio_state()
    assert state.status == access.PawnIOStatus.READY
