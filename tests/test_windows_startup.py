"""Windows contracts exercised with fake APIs; no hardware/elevation involved."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import pytest
from core import os_detect


def test_failed_uac_keeps_current_process(monkeypatch):
    monkeypatch.setattr(os_detect, 'IS_WINDOWS', True)
    monkeypatch.setattr(os_detect, 'is_windows_admin', lambda: False)
    calls = []
    def execute(*args):
        calls.append(args)
        return 5
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(shell32=SimpleNamespace(ShellExecuteW=execute)), raising=False)
    assert os_detect.request_windows_admin() is False
    assert calls[0][1] == 'runas'


def test_successful_uac_records_exit(monkeypatch):
    monkeypatch.setattr(os_detect, 'IS_WINDOWS', True)
    monkeypatch.setattr(os_detect, 'is_windows_admin', lambda: False)
    def execute(*args):
        return 33
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(shell32=SimpleNamespace(ShellExecuteW=execute)), raising=False)
    with pytest.raises(SystemExit) as exc:
        os_detect.request_windows_admin()
    assert exc.value.code == 0


def test_early_python_and_worker_tracebacks_are_saved(tmp_path):
    env = {**os.environ, 'LOCALAPPDATA': str(tmp_path)}
    script = '''from utils.windows_diagnostics import install, stage
import threading
install()
stage('test-started')
def fail(): raise RuntimeError('worker-diagnostic')
t = threading.Thread(target=fail); t.start(); t.join()
raise RuntimeError('main-diagnostic')
'''
    result = subprocess.run([sys.executable, '-c', script], env=env, capture_output=True, timeout=10)
    assert result.returncode != 0
    text = next((tmp_path / 'CyberClean/logs').glob('runtime-*.log')).read_text(encoding='utf-8')
    assert 'test-started' in text
    assert 'worker-diagnostic' in text and 'main-diagnostic' in text
    assert 'Traceback' in text


def test_import_does_not_request_uac():
    source = Path('main.py').read_text(encoding='utf-8')
    assert '    request_windows_admin()' not in source
