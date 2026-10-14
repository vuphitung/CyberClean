"""
CleanWorker end-to-end (không GUI thật): chạy run() trực tiếp trên dữ liệu giả và kiểm tra
log, kết quả, việc dùng lại plan đã xem trước, và việc đo thật.
"""
import os
from pathlib import Path

import pytest
from PyQt6.QtCore import QCoreApplication

from core import engine as E
from core import linux_cleaner as L
from tests.helpers import age, tree


@pytest.fixture(scope="module", autouse=True)
def _app():
    return QCoreApplication.instance() or QCoreApplication([])


@pytest.fixture()
def cleaner(monkeypatch, tmp_path):
    monkeypatch.setattr(E, "is_ram_backed", lambda p: False)
    monkeypatch.setattr(E.Guards, "_load_procs", staticmethod(lambda: (set(), set(), set())))
    monkeypatch.setattr(E.Guards, "_load_open", lambda self: set())
    E.Guards._shared = None
    c = L.LinuxCleaner()
    c.ctx.home = str(tmp_path / "home")
    os.makedirs(c.ctx.home)
    c.ctx.env = {}
    return c


def run_worker(cleaner, targets, dry):
    from ui_widgets import CleanWorker
    w = CleanWorker(targets, dry=dry, cleaner=cleaner)
    logs, done = [], []
    w.log.connect(lambda m, lvl: logs.append((lvl, m)))
    w.done.connect(lambda d: done.append(d))
    w.run()
    assert done, "done phải LUÔN được phát"
    return logs, done[0]


def seed(home):
    tree(home / ".config/google-chrome", {"Local State": 4, "Default/Cache/a": 5000, "Default/Cookies": 9})
    tree(home / ".cache/thumbnails", {"normal/a.png": 300}, days=40)


def test_dry_run_then_clean_reports_consistent_numbers(cleaner):
    home = Path(cleaner.ctx.home)
    seed(home)
    logs, dry = run_worker(cleaner, ["chromium_cache", "thumbnails"], dry=True)
    assert dry["dry"] and dry["freed"] == 5300
    assert (home / ".config/google-chrome/Default/Cache/a").exists(), "dry-run không được đụng đĩa"
    logs, real = run_worker(cleaner, ["chromium_cache", "thumbnails"], dry=False)
    assert not real["dry"] and real["freed"] == 5300 and real["planned"] == 5300
    assert not (home / ".config/google-chrome/Default/Cache").exists()
    assert (home / ".config/google-chrome/Default/Cookies").exists()
    assert real["rollback"] and {r["type"] for r in real["rollback"]} >= {"Browser & Electron Caches (Chromium)"}
    assert real["measured"] is not None            # shutil.disk_usage trước/sau


def test_real_clean_executes_the_previewed_plan_and_skips_changed_items(cleaner):
    home = Path(cleaner.ctx.home)
    seed(home)
    run_worker(cleaner, ["chromium_cache"], dry=True)                       # xem trước → plan được cache
    (home / ".config/google-chrome/Default/Cache/a").write_bytes(b"browser rewrote this after the preview")
    logs, real = run_worker(cleaner, ["chromium_cache"], dry=False)
    assert (home / ".config/google-chrome/Default/Cache/a").exists()
    assert real["freed"] == 0
    assert any("skipped" in m for lvl, m in logs)


def test_app_running_is_a_warning_not_an_error(cleaner):
    home = Path(cleaner.ctx.home)
    cfg = tree(home / ".config/google-chrome", {"Local State": 4, "Default/Cache/a": 5000})
    (cfg / "SingletonLock").symlink_to(f"host-{os.getpid()}")
    logs, real = run_worker(cleaner, ["chromium_cache"], dry=False)
    levels = [lvl for lvl, m in logs]
    assert "warn" in levels
    assert not any(lvl == "err" for lvl, m in logs), logs
    assert (cfg / "Default/Cache/a").exists() and real["freed"] == 0


def test_review_targets_cannot_be_cleaned_through_the_worker(cleaner):
    home = Path(cleaner.ctx.home)
    tree(home / ".cache/go-build", {"aa/x": 100})
    logs, real = run_worker(cleaner, ["dev_cache", "empty_trash"], dry=False)
    assert real["freed"] == 0 and (home / ".cache/go-build/aa/x").exists()
    assert any(lvl == "err" for lvl, m in logs)


def test_worker_always_emits_done_even_on_cleaner_crash(cleaner, monkeypatch):
    monkeypatch.setattr(cleaner, "clean", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    logs, res = run_worker(cleaner, ["thumbnails"], dry=False)
    assert "freed" in res


def test_auto_clean_worker_only_runs_scheduled_auto_and_unattended(cleaner, monkeypatch):
    from ui_widgets import _AutoCleanWorker
    calls = []
    real = cleaner.clean

    def spy(tid, dry=True, **kw):
        calls.append((tid, dry, kw.get("unattended")))
        return real(tid, dry=dry, **kw)
    monkeypatch.setattr(cleaner, "clean", spy)
    home = Path(cleaner.ctx.home)
    tree(home / ".cache/thumbnails", {"normal/a.png": 300}, days=40)
    tree(home / ".local/share/Trash/files", {"precious.docx": 5000}, days=90)
    ids = [t.id for t in cleaner.get_targets() if t.tier == "auto" and t.scheduled]
    w = _AutoCleanWorker(ids + ["empty_trash", "dev_cache"], cleaner)     # kể cả bị nhét nhầm vào danh sách
    out = []
    w.done.connect(lambda f, n: out.append((f, n)))
    w.run()
    assert all(c[1] is False and c[2] is True for c in calls)
    assert (home / ".local/share/Trash/files/precious.docx").exists(), "thùng rác bị xóa ngầm!"
    assert not (home / ".cache/thumbnails/normal/a.png").exists()          # thumbnails 40 ngày ≥ 30 → được dọn
    from core import privileged as P
    assert not P.is_unattended(), "cờ unattended phải được bỏ sau khi chạy"
