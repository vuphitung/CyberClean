from types import SimpleNamespace

import pytest

from core import analyzer


@pytest.mark.parametrize('received,expected', [(800*1024, True), (1200*1024, False), (-1, False)])
def test_windows_idle_network_threshold_is_bytes_per_second(monkeypatch, received, expected):
    import psutil
    monkeypatch.setattr(analyzer, '_IS_WINDOWS', True)
    times = iter([10., 12.])
    monkeypatch.setattr(analyzer.time, 'monotonic', lambda: next(times))
    counters = iter([SimpleNamespace(bytes_sent=0, bytes_recv=10),
                     SimpleNamespace(bytes_sent=0, bytes_recv=10+received)])
    monkeypatch.setattr(psutil, 'net_io_counters', lambda: next(counters))
    monkeypatch.setattr(psutil, 'cpu_percent', lambda **kwargs: 0.)
    scheduler = analyzer.IdleScheduler(net_threshold_kb=500, sample_seconds=2)
    assert scheduler.is_idle() is expected


def test_cancelled_oneclick_starts_no_windows_operation(monkeypatch):
    import subprocess
    import ui_widgets
    monkeypatch.setattr(ui_widgets, 'IS_LINUX', False)
    monkeypatch.setattr(ui_widgets.platform, 'system', lambda: 'Windows')
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: pytest.fail('started after cancellation'))
    worker = ui_widgets._OneClickWorker()
    worker.stop()
    worker.run()
