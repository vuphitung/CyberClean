"""Read-only GUI/soak check with native telemetry and isolated settings.

No cleanup, Boost, uninstall, startup update request or stale-state recovery.
"""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time


def run_observed_gui(args, duration, output):
    """Parent harness observes a separate GUI, excluding its own CPU entirely."""
    import psutil
    from windows_benchmark import observe_process
    command = [sys.executable, '-X', 'utf8', str(Path(__file__).resolve()),
               '--gui-child', '--seconds', str(duration), '--output', str(output)]
    if args.offscreen:
        command.append('--offscreen')
    child = subprocess.Popen(command, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    resources = observe_process(child.pid, seconds=duration+60)
    resource_output = output.with_suffix('.resources.json')
    resource_output.write_text(json.dumps(resources, indent=2), encoding='utf-8')
    code = child.poll()
    if code is None:
        raise RuntimeError('GUI exceeded the bounded observation deadline; it was not forcibly terminated')
    if code != 0:
        raise RuntimeError(f'GUI child exited with code {code}; see diagnostics and {resource_output}')
    result = json.loads(output.read_text(encoding='utf-8'))
    gui_rows = result.pop('samples')
    origin = result['measurement_started_monotonic']
    rows = []
    for resource in resources['samples']:
        row = dict(resource)
        row['elapsed_seconds'] = resource['monotonic']-origin
        matches = [gui for gui in gui_rows if gui['elapsed_seconds'] <= row['elapsed_seconds']]
        if matches:
            row.update({key: value for key, value in matches[-1].items() if key != 'elapsed_seconds'})
        rows.append(row)
    idle = [row['cpu_machine_percent'] for row in rows if row['elapsed_seconds'] > 45
            and row['cpu_machine_percent'] is not None]
    remaining = []
    identities = {(detail['pid'], detail['create_time']) for row in rows
                  for detail in row['process_details'] if detail['pid'] != child.pid}
    for pid, created in identities:
        try:
            process = psutil.Process(pid)
            if process.create_time() == created and process.is_running():
                remaining.append(pid)
        except psutil.NoSuchProcess:
            pass
    result.update(cpu_machine_mean=resources['cpu_mean'],
                  idle_cpu_machine_mean=statistics.mean(idle) if idle else None,
                  observer_cpu_machine_mean=resources['observer_cpu_mean'],
                  children_after_shutdown=sorted(remaining), samples=rows, gui_samples=gui_rows,
                  resource_observation_file=str(resource_output),
                  measurement=resources['measurement'],
                  notes='Read-only source GUI, isolated settings; no cleanup/Boost/update request/stale recovery. '
                        'Resource observation runs in a separate parent process; its CPU is excluded and '
                        'reported separately. GUI timer only records latency/page/cache metadata. Thread '
                        'counts omitted. Shared working sets may count twice; short-lived children may be '
                        'missed. Observer and other apps can still contend for CPU. No FPS or universal '
                        'idle-performance claim; prior in-GUI resource measurements are not comparable.')
    output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(str(output), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=90)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--offscreen', action='store_true')
    parser.add_argument('--gui-child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    duration = max(45, args.seconds)
    if sys.platform != 'win32':
        parser.error('requires native Windows')
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if not args.gui_child:
        run_observed_gui(args, duration, output)
        return
    home = output.parent / (output.stem + '-profile')
    home.mkdir(exist_ok=True)
    for key, suffix in (('USERPROFILE', ''), ('HOME', ''), ('APPDATA', 'roaming'),
                        ('LOCALAPPDATA', 'local'), ('XDG_CONFIG_HOME', 'config')):
        target = home / suffix
        target.mkdir(exist_ok=True)
        os.environ[key] = str(target)
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    if args.offscreen:
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    else:
        os.environ.pop('QT_QPA_PLATFORM', None)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    started = time.monotonic()
    from PyQt6.QtCore import QSettings, QTimer
    from PyQt6.QtWidgets import QApplication
    app = QApplication([])
    app.setOrganizationName('CyberCleanReadOnlyQA')
    app.setApplicationName('CyberCleanReadOnlyQA')
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(home))
    import main as M
    # Keep system reads real. Disable only the outbound updater for repeatability.
    M.CyberCleanApp._check_update_async = lambda self: None
    win = M.CyberCleanApp()
    win.setWindowTitle('CyberClean - Windows read-only QA')
    win.show()
    rows, lags, visited = [], [], []
    first_snapshot = None
    last = time.monotonic()

    def tick():
        nonlocal last
        now = time.monotonic()
        lags.append(max(0., (now - last - .1) * 1000))
        last = now

    def sample():
        nonlocal first_snapshot
        snapshot = win._snap
        if snapshot is not None and snapshot.cpu_percent is not None and first_snapshot is None:
            first_snapshot = time.monotonic() - started
        rows.append(dict(elapsed_seconds=time.monotonic()-started,
                         page=win.stack.currentIndex(), minimized=win.isMinimized(),
                         holo_timer_interval_ms=win.dash_holo_core._timer.interval(),
                         holo_hover=win.dash_holo_core._hover,
                         telemetry_errors=dict(snapshot.errors) if snapshot else None))

    def visit(page):
        win._nav(page)
        visited.append(page)

    for index, (page, _, _) in enumerate(win.NAV_ITEMS):
        QTimer.singleShot(3000 + index * 2200, lambda page=page: visit(page))
    QTimer.singleShot(22000, lambda: visit('dashboard'))
    QTimer.singleShot(25000, win._refresh_now)
    QTimer.singleShot(30000, win.showMinimized)
    QTimer.singleShot(38000, win.showNormal)
    QTimer.singleShot(40000, win._refresh_now)

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(100)
    observer = QTimer()
    observer.timeout.connect(sample)
    observer.start(1000)

    def finish():
        timer.stop()
        observer.stop()
        sample()
        win._nav('dashboard')
        app.processEvents()
        win.grab().save(str(output.with_suffix('.png')))
        snapshot = asdict(win._snap) if win._snap else None
        shutdown_start = time.monotonic()
        win._shutdown()
        win.close()
        if hasattr(win, 'tray'):
            win.tray.hide()
        ordered_lags = sorted(lags)
        result = dict(platform=__import__('platform').platform(), pid=os.getpid(),
                      duration_seconds=duration, first_valid_snapshot_seconds=first_snapshot,
                      pages_visited=visited, measurement_started_monotonic=started,
                      event_loop_lag_p95_ms=ordered_lags[int(.95*(len(lags)-1))] if lags else None,
                      event_loop_lag_max_ms=max(lags, default=None),
                      shutdown_seconds=time.monotonic()-shutdown_start,
                      sysinfo_worker_stopped=not win._si_worker.isRunning(),
                      snapshot=snapshot, samples=rows,
                      notes='GUI-only lightweight timing/cache metadata. Parent observer merges resources after exit.')
        output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(str(output), flush=True)
        from utils.windows_diagnostics import normal_exit
        normal_exit(0, 'read-only runtime check completed')
        app.quit()

    QTimer.singleShot(duration*1000, finish)
    app.aboutToQuit.connect(win._shutdown)
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
