"""Cooperative Qt shutdown: a timeout must never destroy a running QThread."""
import logging
import weakref


def track_thread(owner, worker):
    """Retain replaced page workers until Qt reports that they have finished."""
    pending = getattr(owner, '_windows_pending_workers', None)
    if pending is None:
        pending = owner._windows_pending_workers = set()
    pending.add(worker)
    owner_ref, worker_ref = weakref.ref(owner), weakref.ref(worker)
    def release():
        current_owner, current_worker = owner_ref(), worker_ref()
        if current_owner is not None:
            current_owner._windows_pending_workers.discard(current_worker)
    worker.finished.connect(release)
    return worker


def tracked_threads(owner):
    return list(getattr(owner, '_windows_pending_workers', ()))


def drain_threads(workers, app=None):
    """Keep owners alive until their work ends, while delivering queued results.

    Call stop/requestInterruption before this for cancellable workers. Native
    operations already in progress must finish before their state is restored.
    User input is excluded so another action cannot start during teardown.
    """
    from PyQt6.QtCore import QEventLoop
    if app is None:
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
    seen = set()
    for worker in workers:
        if worker is None or id(worker) in seen:
            continue
        seen.add(id(worker))
        waits = 0
        while worker.isRunning():
            worker.wait(50)
            if app is not None:
                app.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
            waits += 1
            if waits % 100 == 0:
                logging.getLogger('cyberclean').info(
                    'Waiting cooperatively for %s during shutdown', type(worker).__name__)
    if app is not None:
        # A worker can finish between isRunning() and the last queued signal.
        app.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
