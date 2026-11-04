"""Boost must survive a theme switch (the pages are rebuilt) and must never be 'recovered' while live."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PRELUDE = r'''
import sys, json
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication
from core import game_boost_widget as G
app = QApplication([])
G.IS_WINDOWS = False; G.IS_LINUX = True

class FakeThread(QObject):
    update = pyqtSignal(int); game_found = pyqtSignal(list, str, list); game_lost = pyqtSignal(); log_sig = pyqtSignal(str, str)
    started = []
    def __init__(self, *a): super().__init__(); self.running = False
    def start(self): self.running = True; FakeThread.started.append(self)
    def stop(self): self.running = False
    def wait(self, *a): return True
    def isRunning(self): return self.running
G.GpuMonitorThread = FakeThread; G.GameWatcherThread = FakeThread
restored = []
G._restore_boost_state = lambda saved, log=None: (restored.append(dict(saved)) or True)
'''


def _run(body, tmp_path):
    script = PRELUDE + f"\nG._boost_state_file = lambda: Path({str(tmp_path / 'boost_state.json')!r})\n" + body
    r = subprocess.run([sys.executable, '-X', 'utf8', '-c', script], cwd=ROOT, capture_output=True, text=True,
                       encoding='utf-8', timeout=60, env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'})
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-2500:]


def test_recovery_ignores_state_of_a_boost_that_is_live_in_this_process(tmp_path):
    _run('''
G._save_boost_state_disk({'power': 'powersave', 'gamedvr_orig': 1})
G._set_boost_live(True)
assert G._recover_stale_boost_on_startup() is True
assert restored == [], restored            # live session: a new page must not undo it
G._set_boost_live(False)
G._recover_stale_boost_on_startup()        # genuine leftovers (no live boost here) are still recovered
assert restored == [{'power': 'powersave', 'gamedvr_orig': 1}], restored
''', tmp_path)


def test_live_boost_is_handed_to_the_rebuilt_page_without_restoring(tmp_path):
    _run('''
old = G.GameBoostPage()
old._active = True; G._set_boost_live(True)
state = {'power': 'powersave', 'gamedvr_orig': 1}
old._saved_state = state; G._save_boost_state_disk(state)
old._begin_monitoring()
old._chk_swap.setChecked(False)
old._on_metric('bg_count', 4)
old._log.append_line('  + custom line kept across rebuild', 'ok')
assert old.can_hand_over()
snap = old.export_runtime()
assert snap is not None
assert old._saved_state is None and not old._active and old._shutting_down   # orphan is inert
assert not any(t.running for t in FakeThread.started)                        # monitors stopped, nothing restored
assert restored == []

new = G.GameBoostPage()                    # what _build_ui() does on a theme switch
assert restored == [], 'new page must not recover a live boost'
toggled = []; new.boost_toggled.connect(toggled.append)
new.adopt_runtime(snap)
assert new._active and new._saved_state == state and toggled == [True]
assert new._chk_swap.isChecked() is False and not new._chk_ram.isEnabled()
assert 'custom line kept across rebuild' in new._log.toPlainText()
assert new._metrics_seen.get('bg_count') == 4
assert new._watcher is not None and new._watcher.running and new._gpu_thread.running
assert restored == []

new._stop()                                # the user can still switch Boost off afterwards
new._worker.wait(5000); app.processEvents()
assert restored == [state], restored
assert not new._active and G._boost_live_in_process is False
''', tmp_path)


def test_boost_that_is_applying_or_restoring_is_not_handed_over(tmp_path):
    _run('''
page = G.GameBoostPage()
page._active = True; page._transitioning = True
assert not page.can_hand_over() and page.export_runtime() is None
page._transitioning = False; page._shutting_down = True
assert not page.can_hand_over()
''', tmp_path)
