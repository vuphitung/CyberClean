"""
WindowsCleaner không chạy thật được trong sandbox Linux (DISM, wevtutil, dịch vụ Windows...).
Những gì test được: bảng tier/scheduled, hàng rào clean(), review dạng một-mục, và phần
dùng engine (win_temp, win_error_reports) với thư mục giả.
"""
import os
import time
from pathlib import Path

import pytest

from core import engine as E
from core import rules as R
from core import windows_cleaner as W
from tests.helpers import age, tree


@pytest.fixture()
def wc(monkeypatch, tmp_path):
    monkeypatch.setattr(E, "is_ram_backed", lambda p: False)
    monkeypatch.setattr(E.Guards, "_load_procs", staticmethod(lambda: (set(), set(), set())))
    E.Guards._shared = None
    wctx = R.RuleContext(os_name="windows", home="C:\\Users\\u",
                         env={"LOCALAPPDATA": "C:\\Users\\u\\AppData\\Local", "APPDATA": "C:\\Users\\u\\AppData\\Roaming"})
    monkeypatch.setattr(R.RuleContext, "detect", classmethod(lambda cls: wctx))
    return W.WindowsCleaner()


def by_id(c):
    return {t.id: t for t in c.get_targets()}


def test_tiers_and_schedule(wc):
    t = by_id(wc)
    auto = {i for i, x in t.items() if x.tier == "auto"}
    review = {i for i, x in t.items() if x.tier == "review"}
    assert {"win_temp", "chromium_cache", "firefox_cache", "win_thumbcache", "win_error_reports", "win_dns"} == auto
    assert {"win_recycle", "win_prefetch", "win_updates", "win_delivery", "win_font_cache", "win_shader_cache",
            "win_winsxs", "win_eventlog", "win_crash_dumps", "dev_cache"} == review
    for i in review:
        assert not t[i].scheduled and t[i].safety == "caution", i
    assert not t["win_dns"].scheduled and not t["win_thumbcache"].scheduled
    assert t["win_temp"].scheduled and t["chromium_cache"].scheduled


def test_old_per_browser_targets_are_replaced_by_one_rule_target(wc):
    ids = set(by_id(wc))
    assert not ids & {"chrome_cache", "edge_cache", "brave_cache", "opera_cache", "vivaldi_cache", "coccoc_cache"}


def test_gate_review_and_unattended(wc, monkeypatch):
    called = []
    monkeypatch.setattr(wc, "_win_recycle", lambda dry: called.append(dry) or W.CleanResult("win_recycle"))
    r = wc.clean("win_recycle", dry=False)
    assert r.error and not called
    assert wc.clean("win_eventlog", dry=True, unattended=True).error
    assert wc.clean("win_dns", dry=True, unattended=True).error      # auto nhưng không scheduled
    assert wc.clean("nope").error


def test_review_monolith_is_one_explicit_item(wc, monkeypatch):
    est = W.CleanResult("win_recycle", freed_bytes=5 * 1024**3, files_removed=12)
    monkeypatch.setattr(wc, "_win_recycle", lambda dry: est)
    scan = wc.review_scan("win_recycle")
    assert len(scan.items) == 1 and scan.items[0].id == "all" and scan.items[0].size == 5 * 1024**3
    assert scan.items[0].risk == "high" and scan.warning
    # review_clean chỉ chạy khi người dùng tick đúng mục
    ran = []
    monkeypatch.setattr(wc, "_win_recycle", lambda dry: ran.append(dry) or W.CleanResult("win_recycle"))
    wc.review_clean("win_recycle", [], dry=False)
    assert ran == []
    wc.review_clean("win_recycle", ["all"], dry=False)
    assert ran == [False]


def test_review_scan_rejects_auto(wc):
    with pytest.raises(ValueError):
        wc.review_scan("win_temp")


# ── win_temp qua engine ──────────────────────────────────────────────────────
@pytest.fixture()
def temp_dir(monkeypatch, tmp_path):
    t = tmp_path / "Temp"
    t.mkdir()
    monkeypatch.setenv("TEMP", str(t))
    monkeypatch.setenv("TMP", str(t))
    monkeypatch.setattr(W.WindowsCleaner, "_temp_dirs", lambda self: [t])
    return t


def test_win_temp_guards(wc, temp_dir):
    stale = tree(temp_dir / "oldstuff", {"a.tmp": 500, "sub/b.tmp": 100}, days=10)
    installer = tree(temp_dir / "setup-run", {"x/y.bin": 10}, days=10)
    (installer / "x" / "fresh.bin").write_bytes(b"installer still extracting")   # file sâu mới ghi
    keep_prefix = tree(temp_dir / "chrome_update", {"a": 10}, days=10)
    lock = temp_dir / "app.lock"
    lock.write_bytes(b"l")
    age(lock, 10)
    msi = temp_dir / "inst.msi"
    msi.write_bytes(b"m")
    age(msi, 10)
    fresh = temp_dir / "new.tmp"
    fresh.write_bytes(b"n")
    old_file = temp_dir / "cache.dat"
    old_file.write_bytes(b"z" * 40)
    age(old_file, 10)
    target = temp_dir.parent / "precious"
    target.mkdir()
    (target / "keep.txt").write_bytes(b"k" * 999)
    if os.name == 'nt':
        import _winapi
        _winapi.CreateJunction(str(target), str(temp_dir / 'junction'))
    else:
        (temp_dir / "junction").symlink_to(target)
    d = wc.clean("win_temp", dry=True)
    assert d.freed_bytes == 600 + 40, d
    r = wc.clean("win_temp", dry=False, plan=d.plan)
    assert r.freed_bytes == 640 and not r.error
    for kept in (installer, keep_prefix, lock, msi, fresh, target / "keep.txt", temp_dir / "junction"):
        assert os.path.lexists(kept), kept
    assert not stale.exists() and not old_file.exists()


def test_win_temp_unattended_waits_three_days(wc, temp_dir):
    tree(temp_dir / "two-days", {"a": 10}, days=2)
    tree(temp_dir / "ten-days", {"a": 10}, days=10)
    manual = wc.clean("win_temp", dry=True)
    sched = wc.clean("win_temp", dry=True, unattended=True)
    assert manual.freed_bytes == 20 and sched.freed_bytes == 10


def test_win_temp_locked_file_is_skipped_not_error(wc, temp_dir, monkeypatch):
    f = temp_dir / "locked.tmp"
    f.write_bytes(b"x" * 10)
    age(f, 10)
    d = wc.clean("win_temp", dry=True)
    real = E.remove_path

    def locked(path):
        raise PermissionError(32, "The process cannot access the file because it is being used")
    monkeypatch.setattr(E, "remove_path", locked)
    r = wc.clean("win_temp", dry=False, plan=d.plan)
    monkeypatch.setattr(E, "remove_path", real)
    assert r.error is None and r.freed_bytes == 0 and any("locked" in why for _, why in r.skipped)


def test_wer_plan_age_7_days(wc, monkeypatch, tmp_path):
    q = tmp_path / "WER"
    old = tree(q / "Report_old", {"x.wer": 100}, days=10)
    tree(q / "Report_new", {"x.wer": 100}, days=2)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "nowhere"))
    monkeypatch.setattr(W, "Path", lambda *a: Path(*a) if not str(a[0]).startswith("C:/ProgramData") else q)
    plan = wc._wer_plan(False)
    names = {Path(i.path).name for i in plan.deletable}
    assert "Report_old" in names and "Report_new" not in names
    assert old.exists()


def test_rules_ctx_is_windows(wc):
    assert wc.ctx.os_name == "windows"
    assert {t.id for t in wc.ruleset.target_defs(wc.ctx)} == {"chromium_cache", "firefox_cache", "dev_cache"}
