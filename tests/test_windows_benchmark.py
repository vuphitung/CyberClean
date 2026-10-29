"""Observer attribution contracts; no real GUI or system changes."""
import ast
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace as NS
from tools import windows_benchmark as benchmark
from tools import windows_runtime_check as runtime


def test_external_observer_excludes_own_cpu_and_omits_expensive_thread_queries():
    now=[0.]
    class Process:
        def __init__(self,pid,rate):self.pid=pid;self.rate=rate
        def create_time(self):return 10.
        def is_running(self):return now[0]<3
        def children(self,**kwargs):return [child]
        def cpu_times(self):return NS(user=self.rate*now[0],system=0)
        def memory_info(self):return NS(rss=100)
        def name(self):return 'fixture.exe'
        def num_handles(self):return 10
        def num_threads(self):raise AssertionError('expensive full-table query')
    target=Process(101,.8);child=Process(102,.4);observer=Process(os.getpid(),.2)
    api=NS(Process=lambda pid:observer if pid==os.getpid() else target,cpu_count=lambda:4,
           NoSuchProcess=ProcessLookupError,AccessDenied=PermissionError)
    result=benchmark.observe_process(101,seconds=10,clock=lambda:now[0],
                                     sleeper=lambda seconds:now.__setitem__(0,now[0]+seconds),api=api)
    assert round(result['cpu_mean'])==30
    assert round(result['observer_cpu_mean'])==5
    assert result['duration_seconds']==3
    assert all(row['threads'] is None and row['processes']==2 for row in result['samples'])
    assert result['measurement']['observer_cpu_excluded']
    assert 'target exited' in result['exit_reason']


def test_gui_sample_callback_only_reads_cached_or_widget_metadata():
    module=ast.parse(Path(runtime.__file__).read_text(encoding='utf-8'))
    sample=next(node for node in ast.walk(module) if isinstance(node,ast.FunctionDef) and node.name=='sample')
    attributes={node.attr for node in ast.walk(sample) if isinstance(node,ast.Attribute)}
    assert not attributes & {'cpu_times','children','memory_info','num_threads','num_handles','process_iter'}


def test_parent_merges_external_resources_only_after_normal_gui_close(monkeypatch,tmp_path):
    output=tmp_path/'result.json'
    output.write_text(json.dumps(dict(measurement_started_monotonic=100.,
                                     samples=[dict(elapsed_seconds=1.,page=0,minimized=False)])),encoding='utf-8')
    resources=dict(cpu_mean=20.,observer_cpu_mean=1.,measurement=dict(observer_cpu_excluded=True),
                   samples=[dict(monotonic=150.,elapsed_seconds=50.,cpu_machine_percent=20.,
                                 process_details=[dict(pid=99999999,create_time=10.)])])
    monkeypatch.setitem(sys.modules,'windows_benchmark',NS(observe_process=lambda *a,**k:resources))
    def launch(command,**kwargs):
        assert '--gui-child' in command
        return NS(pid=99999999,poll=lambda:0)
    monkeypatch.setattr(runtime.subprocess,'Popen',launch)
    runtime.run_observed_gui(NS(offscreen=True),60,output)
    result=json.loads(output.read_text(encoding='utf-8'))
    assert result['cpu_machine_mean']==result['idle_cpu_machine_mean']==20
    assert result['observer_cpu_machine_mean']==1
    assert result['samples'][0]['page']==0
    assert result['children_after_shutdown']==[]
    assert output.with_suffix('.resources.json').exists()
