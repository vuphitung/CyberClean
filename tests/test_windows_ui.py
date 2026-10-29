"""Offscreen Windows layout branches, fake telemetry; not native DPI validation."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

SCRIPT = r'''
import json, time
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QSettings, Qt, QPoint
from PyQt6.QtTest import QTest
app=QApplication([])
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, CONFIG)
app.setOrganizationName('CyberCleanTest');app.setApplicationName('CyberCleanTest')
import main as M
from core.windows_cleaner import WindowsCleaner
M.IS_WINDOWS=True;M.IS_LINUX=False;M.CLEANER=WindowsCleaner()
M.stage=lambda m:None
from utils import sysinfo
from utils.windows_telemetry import WindowsTelemetry
snapshot=WindowsTelemetry().snapshot()
sysinfo.get_snapshot=lambda **kwargs:snapshot
M.get_snapshot=sysinfo.get_snapshot
win=M.CyberCleanApp()
assert isinstance(win._stat_cards['temp'],M.TemperatureStatCard)
temp_card=M.TemperatureStatCard('NHIỆT ĐỘ','N/A')
temp_card.resize(220,76);temp_card.show();clicks=[]
temp_card.accessRequested.connect(lambda:clicks.append(True))
QTest.mouseClick(temp_card,Qt.MouseButton.LeftButton,pos=QPoint(10,10))
assert clicks==[True]
temp_card.close()
win.resize(WIDTH,768);win.show()
for _ in range(25):app.processEvents();time.sleep(.01)
scroll=win._dash_scroll
from utils.sysinfo import DiskInfo
snapshot.disks=[DiskInfo('C:\\',1000,400,600,40.)]
win._on_snapshot(snapshot)
cell=win.disk_table.cellWidget(0,3)
win._on_snapshot(snapshot)
assert win.disk_table.cellWidget(0,3) is cell
win.dash_holo_core._hover=False
win.dash_holo_core._intro_ticks=61
win.dash_holo_core._tick()
assert win.dash_holo_core._timer.interval()==33
win.showMinimized();app.processEvents()
assert not win.dash_holo_core._timer.isActive()
win.showNormal();app.processEvents()
assert win.dash_holo_core._timer.isActive()
win.grab().save(CONFIG+'/dashboard.png')
out={'width':win.width(),'viewport':scroll.viewport().width(),'content':scroll.widget().width(),
     'horizontal_max':scroll.horizontalScrollBar().maximum()}
win._shutdown()
if hasattr(win,'tray'):win.tray.hide()
win.deleteLater();app.processEvents();app.quit()
print('RESULT:'+json.dumps(out),flush=True)
'''

@pytest.mark.parametrize('width,scale', [(1024,'1'), (1366,'1'), (1024,'1.25'), (1024,'1.5'), (1024,'2')])
def test_dashboard_fits_viewport_and_shutdown_returns(tmp_path,width,scale):
    source = SCRIPT.replace('CONFIG',repr(str(tmp_path))).replace('WIDTH',str(width))
    env={**os.environ, 'QT_QPA_PLATFORM':'offscreen','QT_SCALE_FACTOR':scale,
         'HOME':str(tmp_path), 'XDG_CONFIG_HOME':str(tmp_path)}
    result=subprocess.run([sys.executable,'-c',source],cwd=Path(__file__).resolve().parents[1],env=env,
                          capture_output=True,text=True,timeout=45)
    assert result.returncode == 0, result.stderr[-4000:]
    line=next(l for l in result.stdout.splitlines() if l.startswith('RESULT:'))
    data=json.loads(line[7:])
    assert data['width']==width
    assert data['content'] <= data['viewport'],data
    assert data['horizontal_max']==0,data
