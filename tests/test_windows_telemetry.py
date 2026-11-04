"""Deterministic Windows counter contracts. Fake API, not native validation."""
from collections import namedtuple
from types import SimpleNamespace as NS
import os
import pytest
from utils import windows_telemetry as telemetry
from utils.windows_telemetry import NetworkSampler, WindowsTelemetry, cpu_usage

CPU = namedtuple('CPU', 'user system idle interrupt dpc')


def test_cpu_total_and_cores_share_one_window():
    old = [CPU(1, 1, 8, 0, 0), CPU(1, 1, 8, 0, 0)]
    new = [CPU(3, 2, 15, 100, 100), CPU(2, 2, 16, 100, 100)]
    assert cpu_usage(None, old) == (None, [])
    total, cores = cpu_usage(old, new)
    assert cores == [30, 20]
    assert total == 25


def test_network_priming_zero_reset_reconnect_and_adapter_change():
    sampler = NetworkSampler()
    stats = {'Wi-Fi': NS(isup=True, speed=300)}
    def sample(sent, now):
        return sampler.sample({'Wi-Fi': NS(bytes_sent=sent, bytes_recv=sent)}, stats, now)['Wi-Fi']
    assert sample(100, 1)['up_bps'] is None
    assert sample(100, 2)['up_bps'] == 0
    assert sample(180, 4)['up_bps'] == 40
    assert sample(1, 5)['state'].startswith('counter reset')
    stats['Wi-Fi'].isup = False
    assert sample(1, 6)['state'] == 'disconnected'
    stats['Wi-Fi'].isup = True
    assert sample(30, 7)['up_bps'] is None
    assert sampler.sample({}, {}, 8) == {}
    assert sample(70, 9)['up_bps'] is None
    assert sample(70, 10)['link_mbps'] == 300


class FakeAPI:
    NoSuchProcess = ProcessLookupError
    AccessDenied = PermissionError
    def __init__(self):
        self.total = 10
        self.created = 1
    def cpu_count(self): return 4
    def process_iter(self, attrs):
        info = dict(pid=100, name='game.exe', create_time=self.created,
                    cpu_times=NS(user=self.total, system=0), memory_percent=5, status='running')
        return [NS(info=info)]
    def disk_partitions(self, **kwargs): return []


def test_process_cpu_always_machine_scale_and_pid_reuse_primes():
    api = FakeAPI(); clock = [10.]
    service = WindowsTelemetry(api, lambda: clock[0])
    service._slow()
    assert service.snapshot().top_cpu_procs[0].cpu is None
    api.total += .8; clock[0] += 1
    service._slow()
    assert round(service.snapshot().top_cpu_procs[0].cpu) == 20
    api.total += 1.2; clock[0] += 1
    service._slow()
    assert round(service.snapshot().top_cpu_procs[0].cpu) == 30
    api.created = 2; clock[0] += 1
    service._slow()
    assert service.snapshot().top_cpu_procs[0].cpu is None
    service.close()
    service.start()
    assert not service._threads
    assert service.snapshot().errors['service'] == 'closed'


def test_snapshot_is_detached_and_stale_inventory_is_removed():
    clock = [10.]
    service = WindowsTelemetry(FakeAPI(), lambda: clock[0])
    service._slow()
    snapshot = service.snapshot()
    snapshot.top_cpu_procs.clear()
    assert service.snapshot().top_cpu_procs
    clock[0] += 16
    assert service.snapshot().top_cpu_procs == []


def test_windows_commit_pages_are_converted_to_bytes(monkeypatch):
    def read(pointer, size):
        info = pointer._obj
        assert size == info.cb
        info.CommitTotal, info.CommitLimit, info.PageSize = 37, 100, 4096
        return 1
    monkeypatch.setattr(telemetry, '_performance_reader', lambda: read)
    commit = telemetry.read_windows_commit()
    assert commit == (37 * 4096, 100 * 4096, 37)


def test_windows_commit_rejects_missing_limit(monkeypatch):
    monkeypatch.setattr(telemetry, '_performance_reader', lambda: lambda *args: 1)
    with pytest.raises(ValueError, match='commit limit'):
        telemetry.read_windows_commit()


class FastAPI(FakeAPI):
    def cpu_times(self, **kwargs): return [CPU(self.total, 10, 100, 0, 0)]
    def virtual_memory(self): return NS(used=40, total=100, percent=40, available=60)
    def net_io_counters(self, **kwargs): return {'Ethernet': NS(bytes_sent=10, bytes_recv=20)}
    def net_if_stats(self): return {'Ethernet': NS(isup=True, speed=1000)}
    def boot_time(self): return 1
    def swap_memory(self): raise AssertionError('psutil swap is not the Windows commit metric')


def test_fast_uses_explicit_commit_and_clears_failed_values():
    clock = [10.]
    service = WindowsTelemetry(FastAPI(), lambda: clock[0],
                               commit_reader=lambda: telemetry.CommitInfo(80, 200, 40))
    service._fast()
    snapshot = service.snapshot()
    assert (snapshot.swap_used, snapshot.swap_total, snapshot.swap_percent) == (80, 200, 40)
    def denied(): raise PermissionError('commit unavailable')
    service.commit_reader = denied
    service._fast()
    snapshot = service.snapshot()
    assert snapshot.swap_used is snapshot.swap_total is snapshot.swap_percent is None
    assert snapshot.errors['swap'] == 'commit unavailable'


def test_stale_fast_snapshot_never_exposes_fresh_per_core_or_nic_rates():
    clock = [10.]
    service = WindowsTelemetry(FastAPI(), lambda: clock[0],
                               commit_reader=lambda: telemetry.CommitInfo(80, 200, 40))
    service._fast()
    clock[0] += 1
    service.api.total += 1
    service._fast()
    assert service.snapshot().cpu_per_core
    assert service.snapshot().network_interfaces['Ethernet']['state'] == 'fresh'
    clock[0] += 4
    snapshot = service.snapshot()
    assert snapshot.cpu_per_core == []
    assert snapshot.ram_used is snapshot.ram_total is snapshot.ram_available is None
    assert snapshot.swap_used is snapshot.swap_total is None
    assert snapshot.network_interfaces['Ethernet']['up_bps'] is None
    assert snapshot.network_interfaces['Ethernet']['state'] == 'unavailable/stale'


def test_another_python_workload_is_included_but_app_pid_is_hidden():
    api = FakeAPI()
    def processes(attrs):
        return [NS(info=dict(pid=pid, name='python.exe', create_time=1,
                             cpu_times=NS(user=10, system=0), memory_percent=5, status='running'))
                for pid in (os.getpid(), os.getpid() + 100000)]
    api.process_iter = processes
    service = WindowsTelemetry(api, clock=lambda: 10.)
    service._slow()
    assert [proc.pid for proc in service.snapshot().top_mem_procs] == [os.getpid() + 100000]


def test_native_inventory_avoids_per_pid_queries_and_preserves_machine_cpu():
    api=FastAPI();clock=[10.]
    api.process_iter=lambda *args:(_ for _ in ()).throw(AssertionError('per-PID query'))
    service=WindowsTelemetry(api,clock=lambda:clock[0])
    service._process_reader=lambda:[dict(pid=100,name='game.exe',create_time=123456789,
                                        cpu_times=NS(user=api.total,system=0),memory_rss=20)]
    service._slow()
    assert service.snapshot().top_cpu_procs[0].cpu is None
    api.total += .8;clock[0] += 1
    service._slow()
    row=service.snapshot().top_cpu_procs[0]
    assert round(row.cpu)==20 and row.mem==20 and row.status=='unknown'


def test_native_inventory_failure_uses_psutil_with_explicit_diagnostic():
    api=FakeAPI();seen=[];original=api.process_iter
    def processes(attrs):
        seen.extend(attrs)
        return original(attrs)
    api.process_iter=processes
    service=WindowsTelemetry(api,clock=lambda:10.)
    def unavailable():raise OSError('unsupported process layout')
    service._process_reader=unavailable
    service._slow()
    snapshot=service.snapshot()
    assert snapshot.top_cpu_procs
    assert 'psutil fallback' in snapshot.errors['inventory']
    assert 'status' not in seen
