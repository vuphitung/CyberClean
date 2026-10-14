import subprocess

import pytest

from core import privileged as P
from core.base_cleaner import CleanTarget
from core import rules as R


# ── tier invariants (bắt mutant L3) ──────────────────────────────────────────
@pytest.mark.parametrize("tier", ["review", "advisor"])
def test_non_auto_targets_can_never_be_scheduled(tier):
    t = CleanTarget("x", "X", "d", "caution", tier=tier, scheduled=True)
    assert t.scheduled is False


def test_auto_default_scheduled_and_explicit_opt_out():
    assert CleanTarget("x", "X", "d", "safe").scheduled is True
    assert CleanTarget("x", "X", "d", "safe", scheduled=False).scheduled is False
    assert CleanTarget("x", "X", "d", "caution").tier == "review"      # tier suy ra từ safety khi không nêu
    with pytest.raises(ValueError):
        CleanTarget("x", "X", "d", "safe", tier="nonsense")


# ── forbidden_root (bắt mutant L7) ───────────────────────────────────────────
def test_forbidden_roots_linux():
    ctx = R.RuleContext(os_name="linux", home="/home/u")
    for bad in ("/", "/usr", "/etc", "/home", "/home/u", "/var", "/opt", "/root", "/home/u/", "/boot"):
        assert R.forbidden_root(bad, ctx), bad
    for ok in ("/home/u/.cache/x", "/tmp", "/var/tmp", "/home/u/.config/google-chrome/Default/Cache"):
        if ok in ("/tmp", "/var/tmp"):
            assert not R.forbidden_root(ok, ctx), ok
        else:
            assert not R.forbidden_root(ok, ctx), ok


def test_forbidden_roots_windows():
    ctx = R.RuleContext(os_name="windows", home="C:\\Users\\u", env={"SystemRoot": "C:\\Windows"})
    for bad in ("C:\\", "C:\\Windows", "C:\\Windows\\System32", "C:\\Users", "C:\\Users\\u", "C:\\Program Files",
                "C:\\ProgramData"):
        assert R.forbidden_root(bad, ctx), bad
    assert not R.forbidden_root("C:\\Users\\u\\AppData\\Local\\Temp\\x", ctx)


def test_forbidden_root_is_enforced_when_planning(tmp_path):
    rs = R.RuleSet()
    rs.load_text('schema = 1\n[[target]]\nid="t"\ntier="review"\n[[rule]]\nid="r"\ntarget="t"\nmode="tree"\npaths=["~"]\n',
                 "user", "u.toml") if False else None
    rs.load_text('schema = 1\n[[target]]\nid="t"\ntier="auto"\n[[rule]]\nid="r"\ntarget="t"\nmode="tree"\npaths=["/etc"]\n',
                 "builtin", "b.toml")
    ctx = R.RuleContext(os_name="linux", home=str(tmp_path))
    plan = rs.plan("t", ctx)
    assert not plan.items and any("protected" in why for _, why in plan.skipped)


# ── error classification + messages ──────────────────────────────────────────
@pytest.mark.parametrize("stderr,code,kind", [
    ("sudo: a password is required", 1, "password"),
    ("sudo: no tty present and no askpass program specified", 1, "password"),
    ("alice is not in the sudoers file.", 1, "password"),
    ("cyber-clean-helper: unknown action: ping", 2, "old_helper"),
    ("cyber-clean-helper: refusing to remove protected system package: sudo", 3, "failed"),
])
def test_classify(stderr, code, kind):
    r = subprocess.CompletedProcess([], code, "", stderr)
    assert P._classify(r) == kind


def test_messages_name_the_real_cause_not_need_root():
    msgs = {
        "no_helper": P.HelperResult(1, kind="no_helper").message,
        "password": P.HelperResult(1, kind="password").message,
        "busy": P.HelperResult(75, err="pacman is running (db.lck present)").message,
        "refused": P.HelperResult(3, err="x\nrefusing to remove protected system package: sudo").message,
        "missing": P.HelperResult(127, err="paccache is not installed").message,
        "old": P.HelperResult(2, kind="old_helper").message,
    }
    assert "install.sh" in msgs["no_helper"] and "NOPASSWD" in msgs["password"]
    assert "busy" in msgs["busy"] and "protected" in msgs["refused"] and "paccache" in msgs["missing"]
    assert "out of date" in msgs["old"]
    assert not any("Need root" in m for m in msgs.values())
    assert P.HelperResult(0).message == ""


# ── unattended never prompts (bắt mutant L14) ────────────────────────────────
@pytest.fixture()
def fake_sudo(monkeypatch):
    calls = []
    monkeypatch.setattr(P.os.path, "exists", lambda p: True if p == P.HELPER else __import__("os").path.lexists(p))
    monkeypatch.setattr(P, "IS_ROOT", False)
    monkeypatch.setattr(P.shutil, "which", lambda n: "/usr/bin/" + n)
    import core.os_detect as O
    monkeypatch.setattr(O, "HAS_POLKIT_AGENT", True, raising=False)

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if cmd[0] == "sudo":
            return subprocess.CompletedProcess(cmd, 1, "", "sudo: a password is required")
        return subprocess.CompletedProcess(cmd, 0, "via-pkexec", "")
    monkeypatch.setattr(P.subprocess, "run", fake_run)
    return calls


def test_interactive_falls_back_to_pkexec(fake_sudo):
    P.set_unattended(False)
    r = P.run_helper("journal")
    assert r.ok and any(c[0] == "pkexec" for c in fake_sudo)


def test_unattended_never_uses_pkexec(fake_sudo):
    P.set_unattended(True)
    try:
        r = P.run_helper("journal", use_pkexec=True)
    finally:
        P.set_unattended(False)
    assert not r.ok and r.kind == "password"
    assert not any(c[0] == "pkexec" for c in fake_sudo)


def test_unattended_flag_is_thread_local():
    import threading
    P.set_unattended(True)
    seen = []
    t = threading.Thread(target=lambda: seen.append(P.is_unattended()))
    t.start(); t.join()
    P.set_unattended(False)
    assert seen == [False]


def test_helper_info_uses_ping_never_sudo_true(monkeypatch):
    """Báo cáo: `sudo -n true` không thể thành công khi sudoers chỉ cho phép helper."""
    monkeypatch.setattr(P, "IS_ROOT", False)
    monkeypatch.setattr(P.os.path, "exists", lambda p: p == P.HELPER)
    seen = []

    def fake_run_helper(action, *a, **k):
        seen.append(action)
        return P.HelperResult(0, out="cyberclean-helper protocol=2")
    monkeypatch.setattr(P, "run_helper", fake_run_helper)
    P.invalidate_helper_info()
    info = P.helper_info(refresh=True)
    assert seen == ["ping"] and info.current and info.nopasswd and not info.outdated
    # bản cũ (chưa có ping) nhưng NOPASSWD hoạt động → outdated, không phải "không có quyền"
    monkeypatch.setattr(P, "run_helper", lambda *a, **k: P.HelperResult(2, kind="old_helper"))
    old = P.helper_info(refresh=True)
    assert old.outdated and old.nopasswd and not old.current
    monkeypatch.setattr(P, "run_helper", lambda *a, **k: P.HelperResult(1, kind="password"))
    nop = P.helper_info(refresh=True)
    assert not nop.nopasswd and not nop.current
    P.invalidate_helper_info()


def test_ensure_session_never_runs_sudo_true(monkeypatch):
    monkeypatch.setattr(P, "IS_ROOT", False)
    monkeypatch.setattr(P, "helper_info", lambda *a, **k: P.HelperInfo(installed=True, protocol=2, nopasswd=True))
    ran = []
    monkeypatch.setattr(P.subprocess, "run", lambda *a, **k: ran.append(a) or subprocess.CompletedProcess(a, 0))
    assert P.ensure_session() is True and ran == []
