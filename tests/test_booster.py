"""
Test cho các chỗ đã sửa trong core/booster.py: kill widget "chạy điên", oom_score_adj, _run_helper.
Dùng psutil giả để điều khiển CPU theo từng mẫu — không phụ thuộc máy chạy test.
"""
import os
import sys
import time
from types import SimpleNamespace

import pytest

from core import booster as B
from core import privileged as P

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux-only logic")


class NoSuchProcess(Exception): pass
class AccessDenied(Exception): pass
class ZombieProcess(Exception): pass
class TimeoutExpired(Exception): pass


class FakeProc:
    def __init__(self, pid, name, cpu_seq, uid=None, age=3600, status="running", ignores_term=False):
        self.pid, self._name, self._cpu = pid, name, list(cpu_seq)
        self._uid = os.getuid() if uid is None else uid
        self.info = {"pid": pid, "name": name, "create_time": time.time() - age}
        self._status, self.calls, self._ignores = status, [], ignores_term

    def uids(self): return SimpleNamespace(real=self._uid)
    def name(self): return self._name
    def status(self): return self._status

    def cpu_percent(self, interval=None):
        return self._cpu.pop(0) if self._cpu else 0.0

    def terminate(self): self.calls.append("terminate")
    def kill(self): self.calls.append("kill")

    def wait(self, timeout=None):
        if self._ignores:
            raise TimeoutExpired()


@pytest.fixture()
def fake_psutil(monkeypatch):
    procs = []
    ps = SimpleNamespace(process_iter=lambda attrs=None: iter(procs), NoSuchProcess=NoSuchProcess,
                         AccessDenied=AccessDenied, ZombieProcess=ZombieProcess, TimeoutExpired=TimeoutExpired,
                         STATUS_ZOMBIE="zombie")
    monkeypatch.setattr(B, "psutil", ps, raising=False)
    monkeypatch.setattr(B, "HAS_PSUTIL", True)
    return procs


def run(logs=None):
    slept = []
    sink = (lambda *a: logs.append(a)) if logs is not None else (lambda *a: None)
    n = B._kill_runaway_widgets(sink, _sleep=lambda s: slept.append(s))
    return n, slept


def test_no_candidates_costs_nothing(fake_psutil):
    fake_psutil.append(FakeProc(1, "firefox", [99, 99, 99]))
    n, slept = run()
    assert n == 0 and slept == []


def test_quiet_widget_only_pays_the_short_precheck(fake_psutil):
    p = FakeProc(1, "waybar", [0, 3.0])
    fake_psutil.append(p)
    n, slept = run()
    assert n == 0 and slept == [B._WIDGET_PRECHECK_SEC] and p.calls == []


def test_short_burst_is_not_killed(fake_psutil):
    """Báo cáo: chỉ ~0.4 s lấy mẫu là quá mỏng — burst reload config phải sống sót."""
    p = FakeProc(1, "waybar", [0, 95, 96, 40, 5])        # cao ở 2 mẫu đầu, rồi hạ xuống
    fake_psutil.append(p)
    n, slept = run()
    assert n == 0 and p.calls == []
    assert len(slept) >= 2


def test_sustained_runaway_is_stopped_with_term_first(fake_psutil):
    seq = [0, 96, 97, 98, 99, 97]
    p = FakeProc(1, "eww", seq)
    fake_psutil.append(p)
    logs = []
    n, slept = run(logs)
    assert n == 1 and p.calls == ["terminate"]             # tắt nhẹ nhàng, không SIGKILL ngay
    assert sum(slept[1:]) >= 2.0 - 1e-9                     # ~2 s liên tục
    assert any("runaway" in str(l) for l in logs)


def test_term_ignored_escalates_to_kill(fake_psutil):
    p = FakeProc(1, "conky", [0, 96, 97, 98, 99, 97], ignores_term=True)
    fake_psutil.append(p)
    n, _ = run()
    assert n == 1 and p.calls == ["terminate", "kill"]


def test_other_users_and_young_processes_are_never_touched(fake_psutil):
    other = FakeProc(1, "waybar", [0, 99, 99, 99, 99, 99], uid=os.getuid() + 1)
    young = FakeProc(2, "waybar", [0, 99, 99, 99, 99, 99], age=2)
    fake_psutil += [other, young]
    n, slept = run()
    assert n == 0 and other.calls == [] and young.calls == [] and slept == []


def test_zombie_not_killed(fake_psutil):
    p = FakeProc(1, "polybar", [0, 99, 99, 99, 99, 99], status="zombie")
    fake_psutil.append(p)
    n, _ = run()
    assert n == 0 and p.calls == []


def test_one_dip_below_threshold_drops_the_suspect(fake_psutil):
    p = FakeProc(1, "waybar", [0, 99, 99, 50, 99, 99])
    fake_psutil.append(p)
    n, _ = run()
    assert n == 0 and p.calls == []


# ── helper gateway ───────────────────────────────────────────────────────────
def test_run_helper_goes_through_privileged_gateway_without_prompts(monkeypatch):
    seen = []
    monkeypatch.setattr(P, "run_helper", lambda action, *a, **k: seen.append((action, a, k)) or P.HelperResult(0, out="ok"))
    out, code = B._run_helper("compact-memory", timeout=7)
    assert (out, code) == ("ok", 0)
    action, args, kw = seen[0]
    assert action == "compact-memory" and kw["use_pkexec"] is False and kw["timeout"] == 7


def test_run_helper_failure_returns_nonzero(monkeypatch):
    monkeypatch.setattr(P, "run_helper", lambda *a, **k: P.HelperResult(1, kind="password"))
    assert B._run_helper("swappiness")[1] != 0


def test_booster_has_no_shell_based_sudo_left():
    src = open(B.__file__, encoding="utf-8").read()
    assert 'f"sudo -n' not in src and "sudo -n {HELPER}" not in src       # không còn lệnh sudo dựng bằng chuỗi
    assert '_run(\n                    f"sudo' not in src


def test_oom_protection_never_calls_sudo(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(B, "_run", lambda *a, **k: called.append(a) or ("", 1))
    logs, saved = [], {}
    B._protect_game_from_oom([999999999], lambda m, l="info": logs.append(m), saved)
    assert called == []
    assert saved["oom_protected"] == {}
    assert any("needs root" in m for m in logs)


# ── Windows DNS boost: tên adapter không được thành lệnh ─────────────────────
def test_dns_boost_skips_adapters_with_shell_metacharacters(monkeypatch):
    import subprocess as sp
    cmds = []

    def fake_run(cmd, **kw):
        cmds.append(cmd if isinstance(cmd, str) else " ".join(cmd))
        out = ""
        if cmd.startswith("netsh interface show interface"):
            out = ("Admin State  State  Type  Interface Name\n"
                   "Enabled  Connected  Dedicated  Ethernet 2\n"
                   'Enabled  Connected  Dedicated  x" & calc & "\n'
                   "Enabled  Connected  Dedicated  Wi-Fi\n")
        return SimpleNamespace(stdout=out, returncode=0)
    monkeypatch.setattr(B, "IS_WINDOWS", True)
    monkeypatch.setattr(B.subprocess, "run", fake_run)
    monkeypatch.setattr(B.ctypes, "windll", SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: 1)), raising=False)
    logs = []
    changed = B._boost_dns_windows(lambda m, l="info": logs.append(m))
    assert [a for a, _ in changed] == ["Ethernet 2", "Wi-Fi"]
    assert not any("calc" in c for c in cmds), cmds
    assert any("unusual characters" in m for m in logs)


def test_dns_restore_never_runs_unvalidated_values(monkeypatch):
    cmds = []
    monkeypatch.setattr(B, "IS_WINDOWS", True)
    monkeypatch.setattr(B.subprocess, "run", lambda cmd, **kw: cmds.append(cmd) or SimpleNamespace(stdout="", returncode=0))
    B._restore_dns_windows([("Ethernet", ["DNS servers: 8.8.8.8"]), ('evil" & calc', []),
                            ("Wi-Fi", ["DNS servers: 1.1.1.1 & del *"])], lambda *a, **k: None)
    joined = "\n".join(cmds)
    assert "calc" not in joined and "del *" not in joined
    assert 'name="Ethernet" static 8.8.8.8' in joined
    assert 'name="Wi-Fi" dhcp' in joined
