"""Windows native smoke, isolated configuration; NEVER run cleanup/Boost.
Temperature availability is reported, not faked. Set CYBERCLEAN_REQUIRE_CPU_SENSOR=1
only for an explicit hardware validation run that requires a fresh CPU sensor.
"""
import os
from pathlib import Path
import subprocess
import sys
import pytest

pytestmark=pytest.mark.skipif(sys.platform!='win32',reason='requires native Windows')


def test_native_window_runtime_refresh_minimize_restore_and_cooperative_close(tmp_path):
    script=r'''
import sys,time,json
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QSettings,QTimer
from utils.windows_diagnostics import install,normal_exit
install()
app=QApplication([])
app.setOrganizationName('CyberCleanNativeTest');app.setApplicationName('CyberCleanNativeTest')
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,CONFIG)
import main as M
win=M.CyberCleanApp();win.show()
QTimer.singleShot(1000,win._refresh_now)
QTimer.singleShot(2000,win.showMinimized)
QTimer.singleShot(2500,win.showNormal)
QTimer.singleShot(3000,win._refresh_now)
def finish():
    assert win._snap is not None
    print('NATIVE_SNAPSHOT:'+json.dumps({'cpu':win._snap.cpu_percent,'ram':win._snap.ram_percent,
          'errors':win._snap.errors,'temperature':win._snap.temperature_status}),flush=True)
    win.close();app.quit()
QTimer.singleShot(6000,finish)
code=app.exec()
normal_exit(code,'native test event loop')
assert not win._si_worker.isRunning()
sys.exit(code)
'''.replace('CONFIG',repr(str(tmp_path)))
    env={**os.environ,'LOCALAPPDATA':str(tmp_path/'local'),'APPDATA':str(tmp_path/'roaming'),
         'USERPROFILE':str(tmp_path),'QT_QPA_PLATFORM':'offscreen'}
    result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],env=env,
                          capture_output=True,text=True,timeout=45)
    (tmp_path/'native-stdout.txt').write_text(result.stdout,encoding='utf-8')
    (tmp_path/'native-stderr.txt').write_text(result.stderr,encoding='utf-8')
    assert result.returncode==0,result.stderr[-5000:]
    assert 'NATIVE_SNAPSHOT:' in result.stdout


def test_native_cpu_temperature_if_explicitly_required():
    if os.environ.get('CYBERCLEAN_REQUIRE_CPU_SENSOR')!='1':
        pytest.skip('hardware availability is opt-in; default smoke accepts unavailable sensors')
    import time
    from utils.windows_temperature import TemperatureHost
    host=TemperatureHost();host.start()
    try:
        deadline=time.monotonic()+20
        while time.monotonic()<deadline and host.snapshot()['cpu'] is None:
            time.sleep(.1)
        result=host.snapshot()
        assert result['cpu'] is not None,result
        assert result['state']=='fresh',result
    finally:
        host.close()
