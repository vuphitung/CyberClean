"""Isolated Qt lifecycle tests. No native priority/registry/cleanup mutations."""
import os
from pathlib import Path
import subprocess
import sys


def _run(script):
    result = subprocess.run(
        [sys.executable, '-X', 'utf8', '-c', script],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'},
        capture_output=True, text=True, encoding='utf-8', timeout=15)
    assert result.returncode == 0, result.stderr


def test_shutdown_waits_for_boost_result_before_restore_without_starting_monitors():
    _run('''
import time
from PyQt6.QtWidgets import QApplication
from core import game_boost_widget as G
app=QApplication([])
G.IS_WINDOWS=True;G.IS_LINUX=False
G._recover_stale_boost_on_startup=lambda:None
G._load_boost_state_disk=lambda:{}
G._save_boost_state_disk=lambda state:None
G.GameBoostPage._setup_ui=lambda self:None
page=G.GameBoostPage()
restored=[]
def restore(state,*args):
    assert not page._worker.isRunning()
    restored.append(dict(state))
    state.clear()
    return True
G._restore_boost_state=restore
def work(*args):
    time.sleep(.2)
    return {'timer_set':True}
page._worker=G.BoostWorker(work)
page._worker.done_sig.connect(page._on_done)
page._worker.start()
page.shutdown()
assert restored==[{'timer_set':True}],restored
assert page._gpu_thread is None and page._watcher is None
assert page._saved_state is None
assert not page._worker.isRunning()
page.deleteLater();app.processEvents()
''')


def test_game_priority_events_run_serially_outside_gui_and_ignore_shutdown_signals():
    _run('''
import sys,time,threading
from types import SimpleNamespace as N
from PyQt6.QtWidgets import QApplication
from core import game_boost_widget as G
app=QApplication([]);main_id=threading.get_ident()
G.IS_WINDOWS=True;G.IS_LINUX=False
G._recover_stale_boost_on_startup=lambda:None
G._load_boost_state_disk=lambda:{}
G._save_boost_state_disk=lambda state:None
G.GameBoostPage._setup_ui=lambda self:None
page=G.GameBoostPage();page._active=True;page._saved_state={}
card=N(set_value=lambda *a:None,set_lit=lambda *a:None)
page._mc_game=page._mc_bg=card
page._chk_prio=N(isChecked=lambda:True)
page._log=N(append_line=lambda *a:None)
calls=[]
def apply(proc,pid,saved):
    assert threading.get_ident()!=main_id
    time.sleep(.12)
    calls.append('apply')
    saved['game_nice']={pid:{'orig_nice':32,'name':'test','create_time':1}}
    return True
def restore(saved,*args):
    assert threading.get_ident()!=main_id
    calls.append('restore');saved.clear();return 1
G._apply_game_nice=apply
G._restore_process_priorities=restore
G._get_boost_skip_set=lambda:set()
sys.modules['psutil']=N(Process=lambda pid:N(pid=pid),process_iter=lambda *a:[],
                        NoSuchProcess=ProcessLookupError,AccessDenied=PermissionError)
start=time.monotonic()
page._on_game_found([123],'test',[123])
assert time.monotonic()-start<.1
page._on_game_lost()
deadline=time.monotonic()+3
while time.monotonic()<deadline:
    app.processEvents();time.sleep(.01)
    if not page._priority_events and not page._priority_worker.isRunning():break
assert calls==['apply','restore'],calls
page.shutdown()
page._on_game_found([456],'late',[456])
assert not page._priority_events
page.deleteLater();app.processEvents()
''')


def test_startup_recovery_does_not_end_previous_process_timer_request(tmp_path):
    import json
    # Use a subprocess so no page/atexit state escapes this test.
    state_file = tmp_path / 'state.json'
    state_file.write_text(json.dumps({'timer_set': True, 'gamedvr_orig': 1}), encoding='utf-8')
    _run(f'''
from pathlib import Path
from core import game_boost_widget as G
G.IS_WINDOWS=True
G._boost_state_file=lambda:Path({str(state_file)!r})
def restore(state):
    assert 'timer_set' not in state
    assert state['gamedvr_orig']==1
    return True
G._restore_boost_state=restore
assert G._recover_stale_boost_on_startup()
''')
