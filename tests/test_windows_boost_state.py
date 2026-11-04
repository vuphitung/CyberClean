"""Windows rollback fault injection; no external processes are changed."""
from contextlib import contextmanager
import pytest
from utils.windows_process_state import capture, apply, restore
from core import booster

class Proc:
    pid=123
    def __init__(self): self.created=10;self.priority=32
    def create_time(self):return self.created
    def name(self):return 'test.exe'
    def nice(self,value=None):
        if value is not None:self.priority=value
        return self.priority

class API:
    def __init__(self):
        self.values={'power':[0,0], 'memory':4};self.fail_read=False;self.fail_write=False
    @contextmanager
    def handle(self,pid):yield pid
    def read(self,handle,kind):
        if self.fail_read:raise OSError('read-back failed')
        value=self.values[kind]
        return list(value) if isinstance(value,list) else value
    def write(self,handle,kind,value):
        if self.fail_write:return False
        self.values[kind]=value
        return True


def test_applied_but_readback_failed_retains_original_and_retry():
    p=Proc();api=API()
    state=capture(p,api=api)
    # Fail only power read-back after mutation.
    original_read=api.read
    def read(handle,kind):
        if kind=='power' and api.values['power']==[1,1]:raise OSError('readback')
        return original_read(handle,kind)
    api.read=read
    with pytest.raises(OSError):apply(p,state,priority=16384,api=api)
    assert api.values['power']==[1,1]
    assert state['power']==[0,0] and 'power' in state['pending']
    assert 'power' in state['applied'] and 'power' not in state['verified']
    api.fail_write=True
    assert restore(p,state,api=api) is False
    assert state['pending']
    api.fail_write=False;api.read=original_read
    assert restore(p,state,api=api)
    assert api.values=={'power':[0,0], 'memory':4} and p.priority==32


@pytest.mark.parametrize('masks', [[0,0],[1,0],[1,1],[3,2]])
def test_full_original_masks_are_restored(masks):
    p=Proc();api=API();api.values['power']=masks
    state=capture(p,api=api)
    apply(p,state,api=api)
    assert restore(p,state,api=api)
    assert api.values['power']==masks


def test_pid_reuse_never_mutates_new_process():
    p=Proc();api=API();state=capture(p,api=api);apply(p,state,api=api)
    p.created=20;api.values['memory']=5
    assert restore(p,state,api=api)
    assert api.values['memory']==5


def test_windows_boost_does_not_increase_power_plan(monkeypatch):
    monkeypatch.setattr(booster,'IS_WINDOWS',True)
    monkeypatch.setattr(booster,'IS_LINUX',False)
    def unexpected(*a,**k):raise AssertionError('powercfg must not be called')
    monkeypatch.setattr(booster.subprocess,'run',unexpected)
    assert booster._enable_kernel_performance(lambda *a:None) is None


def test_first_unverified_bloat_change_still_registers_cleanup(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace as NS
    from utils import windows_process_state as state_api
    p=Proc()
    p.info={}
    p.oneshot=lambda:nullcontext()
    p.memory_info=lambda:NS(rss=200*1024**2)
    fake=NS(process_iter=lambda *a:[p],virtual_memory=lambda:NS(total=8*1024**3,available=4*1024**3),
            NoSuchProcess=ProcessLookupError,AccessDenied=PermissionError,BELOW_NORMAL_PRIORITY_CLASS=16384)
    monkeypatch.setattr(booster,'psutil',fake)
    monkeypatch.setattr(booster,'IS_WINDOWS',True)
    monkeypatch.setattr(booster,'IS_LINUX',False)
    monkeypatch.setattr(booster,'get_de_protected',lambda:set())
    monkeypatch.setattr(booster,'_is_protected',lambda name:False)
    monkeypatch.setattr(booster,'_has_active_children',lambda pid:False)
    monkeypatch.setattr(booster,'_is_windows_11',lambda:True)
    original=dict(pid=p.pid,name=p.name(),create_time=p.create_time(),pending=[],power=[0,0])
    monkeypatch.setattr(state_api,'capture',lambda *a,**k:original)
    def apply(*a,**k):
        original['pending'].append('power')
        raise OSError('write applied but readback failed')
    monkeypatch.setattr(state_api,'apply',apply)
    cleanup=[]
    monkeypatch.setattr(booster,'_register_cleanup',cleanup.append)
    result=booster.kill_bloat(lambda *a:None,cpu_cache={p.pid:0.1})
    assert result.count==0
    assert result.rollback[0]['frozen_pids'][p.pid]['win_state']['pending']==['power']
    assert len(cleanup)==1


def test_failed_api_write_is_not_reported_as_verified_success():
    p=Proc();api=API();state=capture(p,api=api)
    api.fail_write=True
    assert apply(p,state,priority=16384,api=api) is False
    assert set(state['pending']) == {'nice','memory','power'}
    assert state['verified'] == ['nice']


def test_game_rollback_does_not_change_reused_pid(monkeypatch):
    p=Proc();p.created=10.5  # Same binary can reuse a PID inside two seconds.
    p.cpu_affinity=lambda *a:pytest.fail('must not change affinity of reused PID')
    fake=type('PS',(),dict(Process=lambda pid:p,NoSuchProcess=ProcessLookupError,
                          ZombieProcess=ChildProcessError,AccessDenied=PermissionError))
    monkeypatch.setattr(booster,'psutil',fake)
    monkeypatch.setattr(booster,'IS_WINDOWS',True)
    monkeypatch.setattr(booster,'IS_LINUX',False)
    monkeypatch.setattr(booster,'_bypass_compositor_off',lambda *a:True)
    state={'game_priority':{p.pid:dict(orig_nice=999,name=p.name(),create_time=10)},
           'nice':{p.pid:dict(orig_nice=888,name=p.name(),create_time=10)},
           'affinity':{p.pid:dict(original=[0],name=p.name(),create_time=10)}}
    assert booster.game_mode_off(state,lambda *a:None)
    assert p.priority==32 and not state


def test_cleanup_registry_survives_self_unregister(monkeypatch):
    calls=[]
    def first():
        calls.append('first')
        booster._unregister_cleanup(first)
    monkeypatch.setattr(booster,'_CLEANUP_REGISTRY',[first,lambda:calls.append('second')])
    booster._run_all_cleanups()
    assert calls==['first','second']


def test_working_set_trim_uses_real_cpu_interval_and_pointer_handles(monkeypatch):
    from types import SimpleNamespace as NS
    import ctypes
    import time
    class Fn:
        def __init__(self,fn):self.fn=fn
        def __call__(self,*a):return self.fn(*a)
    class Candidate:
        def __init__(self,pid,second_cpu):
            self.pid=pid;self.info={'name':'background-task.exe'};self.samples=[0,second_cpu]
        def create_time(self):return 1
        def cpu_percent(self,interval=0):return self.samples.pop(0)
    idle=Candidate(21123,0);active=Candidate(21124,90)
    calls=[];closed=[]
    handle=0x123456789
    def open_process(access,inherit,pid):
        assert access & 0x0100  # PROCESS_SET_QUOTA, required by the trim API
        calls.append(pid)
        return handle
    def trim(h,minimum,maximum,flags):
        assert h==handle
        assert minimum.value==maximum.value==ctypes.c_size_t(-1).value
        return 1
    kernel=NS(OpenProcess=Fn(open_process),SetProcessWorkingSetSizeEx=Fn(trim),
              CloseHandle=Fn(closed.append))
    monkeypatch.setattr(booster.ctypes,'WinDLL',lambda *a,**k:kernel,raising=False)
    monkeypatch.setattr(booster,'psutil',NS(process_iter=lambda *a:[idle,active],
                        NoSuchProcess=ProcessLookupError,AccessDenied=PermissionError))
    monkeypatch.setattr(booster,'IS_WINDOWS',True)
    monkeypatch.setattr(booster,'HAS_PSUTIL',True)
    monkeypatch.setattr(booster,'_is_protected',lambda name:False)
    monkeypatch.setattr(booster,'_get_foreground_pid',lambda:0)
    intervals=[]
    monkeypatch.setattr(time,'sleep',intervals.append)
    assert booster._trim_working_sets(lambda *a:None)==1
    assert calls==[idle.pid] and closed==[handle] and intervals==[.2]
    assert kernel.OpenProcess.restype is ctypes.c_void_p
