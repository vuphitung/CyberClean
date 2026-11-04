"""Exercise late results and running-thread lifetime without machine changes."""
import time

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication

from utils.windows_workers import drain_threads


def test_drain_waits_for_late_result_before_owner_teardown():
    app = QApplication.instance() or QApplication([])
    results = []

    class SlowResult(QThread):
        result = pyqtSignal(object)

        def run(self):
            time.sleep(.15)
            self.result.emit({'original_priority': 32})

    worker = SlowResult()
    worker.result.connect(results.append)
    worker.start()
    drain_threads([worker, None, worker], app)
    assert not worker.isRunning()
    assert results == [{'original_priority': 32}]


def test_window_shutdown_restores_only_after_late_boost_result(monkeypatch):
    from types import SimpleNamespace
    import main as M
    from utils import windows_telemetry
    app = QApplication.instance() or QApplication([])
    order = []
    owner = SimpleNamespace(setEnabled=lambda enabled: None, _game_active=True)

    class LateBoost(QThread):
        done = pyqtSignal(object)

        def run(self):
            time.sleep(.15)
            self.done.emit({'original': 32})

    owner._booster_worker = LateBoost()
    owner._booster_worker.done.connect(lambda saved: setattr(owner, '_game_frozen_pids', saved))
    monkeypatch.setattr(M, 'stage', lambda message: None, raising=False)
    monkeypatch.setattr(windows_telemetry, 'close_windows_telemetry', lambda: order.append('closed'))

    def restore(saved, log):
        assert not owner._booster_worker.isRunning()
        assert saved == {'original': 32}
        order.append('restored')

    monkeypatch.setattr(M, 'game_mode_off', restore)
    owner._booster_worker.start()
    M.CyberCleanApp._shutdown_windows(owner)
    assert order == ['closed', 'restored']
    M.CyberCleanApp._shutdown_windows(owner)
    assert order == ['closed', 'restored']


def test_delayed_window_callbacks_start_no_work_after_shutdown():
    from types import SimpleNamespace
    import main as M
    owner = SimpleNamespace(_shutting_down=True)
    for name in ('_refresh_now', '_start_sysinfo', '_one_click_fix', '_load_uninstall',
                 '_show_preview_files', '_run_clean', '_kill_selected_proc',
                 '_check_helper_async', '_upgrade_helper', '_do_uninstall',
                 '_toggle_game_mode', '_toggle_eco_mode', '_toggle_smart_boost',
                 '_run_auto_clean', '_do_background_clean', '_check_update_async', '_show_from_tray'):
        # No widget/worker attributes are available: any work attempted here
        # would fail instead of being silently accepted by a mock worker.
        getattr(M.CyberCleanApp, name)(owner)
    M.CyberCleanApp._run_booster_action(owner, lambda: None)
    M.CyberCleanApp._nav(owner, 'uninstall')


def test_replaced_page_thread_stays_owned_until_finished():
    from PyQt6.QtWidgets import QWidget
    from utils.windows_workers import track_thread, tracked_threads
    app = QApplication.instance() or QApplication([])
    owner = QWidget()
    class Scan(QThread):
        def run(self): time.sleep(.15)
    prior, current = Scan(), Scan()
    owner._worker = track_thread(owner, prior)
    prior.start()
    owner._worker = track_thread(owner, current)
    current.start()
    assert prior in tracked_threads(owner)
    drain_threads(tracked_threads(owner), app)
    assert not prior.isRunning() and not current.isRunning()
    assert tracked_threads(owner) == []


def test_review_cleanup_result_cannot_restart_scan_after_shutdown(monkeypatch):
    from types import SimpleNamespace
    import ui_pages
    app = QApplication.instance() or QApplication([])
    panel = ui_pages.ReviewPanel(SimpleNamespace())
    panel._t = SimpleNamespace(id='temporary-cache')
    panel._shutting_down = True
    monkeypatch.setattr(ui_pages, '_ScanWorker', lambda *args: (_ for _ in ()).throw(
        AssertionError('a new scan was started while closing')))
    result = SimpleNamespace(freed_bytes=0, files_removed=0, measured_bytes=None,
                             notes=[], skipped=[], error='')
    panel._on_cleaned(panel._t, result)
    assert panel._worker is None


def test_smart_off_worker_delivers_failed_restore_result(monkeypatch):
    import core.booster as booster
    from ui_widgets import _SmartOffWorker
    monkeypatch.setattr(booster, 'smart_boost_off', lambda saved, log: False)
    worker = _SmartOffWorker({'pending-original': 32})
    outcomes = []
    worker.done.connect(outcomes.append)
    worker.run()
    assert outcomes == [False]


def test_smart_off_ui_preserves_originals_and_retry_when_restore_fails(monkeypatch):
    from types import SimpleNamespace
    import main as M
    class Button:
        def __init__(self): self.checked = False; self.enabled = True; self.text = ''
        def isChecked(self): return self.checked
        def setChecked(self, value): self.checked = value
        def setEnabled(self, value): self.enabled = value
        def setText(self, value): self.text = value
    class Signal:
        def connect(self, slot): self.slot = slot
    class OffWorker:
        def __init__(self, saved): self.log_signal = Signal(); self.done = Signal()
        def start(self): self.done.slot(False)
    original = {'pending-original': 32}
    owner = SimpleNamespace(_smart_saved=original, _smart_active=True, _smart_trans=False,
                            _smart_btn=Button(), _game_btn=Button(), _eco_btn=Button(),
                            _blog=lambda *args: None)
    monkeypatch.setattr(M, 'IS_WINDOWS', True)
    monkeypatch.setattr(M, '_SmartOffWorker', OffWorker)
    M.CyberCleanApp._toggle_smart_boost(owner)
    assert owner._smart_saved is original
    assert owner._smart_active and owner._smart_btn.checked
    assert 'RESTORE PENDING' in owner._smart_btn.text
    assert not owner._game_btn.enabled and not owner._eco_btn.enabled
