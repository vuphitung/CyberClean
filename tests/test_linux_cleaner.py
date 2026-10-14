import os
import socket
import time
from pathlib import Path

import pytest

from core import engine as E
from core import linux_cleaner as L
from core import privileged as P
from tests.helpers import FakeGuards, age, tree


class Recorder:
    """Thay P.run_helper: ghi lại lời gọi, trả kết quả dựng sẵn, có thể mô phỏng việc xóa file."""

    def __init__(self, results=None, on_call=None):
        self.calls = []
        self.results = results or {}
        self.on_call = on_call

    def __call__(self, action, *args, stdin=None, timeout=120, use_pkexec=True):
        self.calls.append((action, args, stdin))
        if self.on_call:
            self.on_call(action, args, stdin)
        return self.results.get(action, P.HelperResult(0, out="ok"))


@pytest.fixture()
def cleaner(monkeypatch, tmp_path):
    monkeypatch.setattr(E, "is_ram_backed", lambda p: False)
    monkeypatch.setattr(E.Guards, "_load_procs", staticmethod(lambda: (set(), set(), set())))
    monkeypatch.setattr(E.Guards, "_load_open", lambda self: set())
    E.Guards._shared = None
    c = L.LinuxCleaner()
    c.ctx.home = str(tmp_path / "home")
    os.makedirs(c.ctx.home, exist_ok=True)
    c.ctx.env = {}
    return c


def targets(c):
    return {t.id: t for t in c.get_targets()}


# ── tier ─────────────────────────────────────────────────────────────────────
def test_only_auto_targets_are_scheduled(cleaner):
    for t in cleaner.get_targets():
        if t.tier != "auto":
            assert not t.scheduled, t.id
    assert not {"empty_trash", "dev_cache", "app_cache"} & {t.id for t in cleaner.get_targets() if t.tier == "auto"}


def test_empty_trash_is_review_not_safe_auto(cleaner):
    t = targets(cleaner)["empty_trash"]
    assert t.tier == "review" and t.safety == "caution" and not t.scheduled


def test_review_targets_refuse_real_clean_and_unattended(cleaner):
    for tid in ("empty_trash", "dev_cache", "app_cache"):
        r = cleaner.clean(tid, dry=False)
        assert r.error and "Review" in r.error
        r2 = cleaner.clean(tid, dry=True, unattended=True)
        assert r2.error and "unattended" in r2.error


def test_unattended_refuses_non_scheduled(cleaner):
    t = targets(cleaner)["thumbnails"]
    t.scheduled = False
    assert cleaner.clean("thumbnails", dry=True, unattended=True).error


def test_auto_scheduler_selection_matches_report_recommendation(cleaner):
    """Báo cáo: auto-clean chạy empty_trash, user_cache, tmp_files, aur_cache, pacman_broken."""
    sched = {t.id for t in cleaner.get_targets() if t.scheduled}
    assert "empty_trash" not in sched and "user_cache" not in sched and "app_cache" not in sched
    assert "dev_cache" not in sched


def test_unknown_and_info_targets(cleaner):
    assert cleaner.clean("nope").error
    assert cleaner.clean("_unknown_distro_warn").error


# ── parse_size ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,expected", [
    ("1.2G", int(1.2 * 1024**3)), ("803.5 MB", 803_500_000), ("12 MiB", 12 * 1024**2),
    ("543.21 MiB", int(543.21 * 1024**2)), ("4096", 4096), ("0B", 0), ("garbage", 0), ("1,5 GB", 1_500_000_000),
    ("take up 128.0M in the file system", 128 * 1024**2),
])
def test_parse_size(text, expected):
    assert L.parse_size(text) == expected


# ── pacman ───────────────────────────────────────────────────────────────────
def test_paccache_missing_reports_real_cause_not_need_root(cleaner, monkeypatch):
    monkeypatch.setattr(L.shutil, "which", lambda n: None)
    for dry in (True, False):
        r = cleaner._pacman_cache(dry)
        assert r.error and "pacman-contrib" in r.error and "Need root" not in r.error
    rec = Recorder()
    monkeypatch.setattr(P, "run_helper", rec)
    cleaner._pacman_cache(False)
    assert rec.calls == [], "không có paccache thì không được gọi helper rồi báo nhầm"


def test_pacman_cache_estimate_and_real(cleaner, monkeypatch, tmp_path):
    cache = tmp_path / "pkg"
    cache.mkdir()
    (cache / "a.pkg.tar.zst").write_bytes(b"x" * 5000)
    monkeypatch.setattr(L.shutil, "which", lambda n: "/usr/bin/" + n)
    monkeypatch.setattr(L.LinuxCleaner, "_pacman_cache_dirs", staticmethod(lambda: [str(cache)]))
    monkeypatch.setattr(L.LinuxCleaner, "_pacman_busy", staticmethod(lambda: False))
    outs = iter([("==> finished: 4 candidates (disk space saved: 2.00 MiB)\n", "", 0),
                 ("==> finished: 1 candidates (disk space saved: 1.00 MiB)\n", "", 0)])
    monkeypatch.setattr(L, "_cmd", lambda argv, timeout=30, input_text=None: next(outs))
    d = cleaner._pacman_cache(True)
    assert d.freed_bytes == 3 * 1024**2 and not d.error

    def delete(action, args, stdin):
        (cache / "a.pkg.tar.zst").unlink()
    rec = Recorder(on_call=delete)
    monkeypatch.setattr(P, "run_helper", rec)
    monkeypatch.setattr(L, "_cmd", lambda *a, **k: ("", "", 0))
    r = cleaner._pacman_cache(False)
    assert rec.calls[0][0] == "paccache" and r.freed_bytes == 5000, "phải đo thực tế, không lấy ước tính"


def test_pacman_cache_helper_failure_shows_helper_reason(cleaner, monkeypatch):
    monkeypatch.setattr(L.shutil, "which", lambda n: "/usr/bin/" + n)
    monkeypatch.setattr(L.LinuxCleaner, "_pacman_busy", staticmethod(lambda: False))
    monkeypatch.setattr(L.LinuxCleaner, "_pacman_cache_dirs", staticmethod(lambda: ["/nonexistent"]))
    monkeypatch.setattr(L, "_cmd", lambda *a, **k: ("", "", 0))
    monkeypatch.setattr(P, "run_helper", Recorder({"paccache": P.HelperResult(75, err="pacman is running (db.lck present)")}))
    r = cleaner._pacman_cache(False)
    assert "busy" in r.error and "Need root" not in r.error


def test_pacman_busy_skips_with_note(cleaner, monkeypatch):
    monkeypatch.setattr(L.LinuxCleaner, "_pacman_busy", staticmethod(lambda: True))
    monkeypatch.setattr(L.shutil, "which", lambda n: "/usr/bin/" + n)
    rec = Recorder()
    monkeypatch.setattr(P, "run_helper", rec)
    for fn in (cleaner._pacman_cache, cleaner._pacman_broken):
        r = fn(False)
        assert not r.error and any("pacman is running" in n for n in r.notes)
    assert rec.calls == []


def test_pacman_broken_counts_real_size_of_download_dirs(cleaner, monkeypatch, tmp_path):
    cache = tmp_path / "pkg"
    d = tree(cache / "download-AbC123", {"foo.pkg.tar.zst.part": 7000, "bar.part": 300})
    tree(cache / "download-fresh", {"x.part": 99}, days=0)           # đang tải dở → không đụng
    (cache / "vlc.pkg.tar.zst").write_bytes(b"z" * 10)
    old = cache / "stale.part"
    old.write_bytes(b"q" * 11)
    age(old, 5)
    monkeypatch.setattr(L.LinuxCleaner, "_pacman_cache_dirs", staticmethod(lambda: [str(cache)]))
    monkeypatch.setattr(L.LinuxCleaner, "_pacman_busy", staticmethod(lambda: False))
    dry = cleaner._pacman_broken(True)
    assert dry.freed_bytes == 7300 + 11, "thư mục download-* phải được tính theo NỘI DUNG, không phải 4096"

    def delete(action, args, stdin):
        import shutil
        shutil.rmtree(d)
        old.unlink()
    rec = Recorder(on_call=delete)
    monkeypatch.setattr(P, "run_helper", rec)
    real = cleaner._pacman_broken(False)
    assert rec.calls[0][0] == "broken-downloads"
    assert real.freed_bytes == 7311 and (cache / "download-fresh").exists()


# ── journal ──────────────────────────────────────────────────────────────────
def test_journal_real_clean_always_uses_helper_and_measures(cleaner, monkeypatch):
    monkeypatch.setattr(L, "HAS_JOURNALCTL", True)
    usage = iter([300 * 1024**2, 120 * 1024**2])
    monkeypatch.setattr(L.LinuxCleaner, "_journal_usage", staticmethod(lambda: next(usage)))
    rec = Recorder()
    monkeypatch.setattr(P, "run_helper", rec)
    r = cleaner._journal(False)
    assert rec.calls[0][0] == "journal" and r.freed_bytes == 180 * 1024**2 and not r.error


def test_journal_estimate_from_archived_files(monkeypatch, tmp_path):
    j = tmp_path / "journal" / "abc"
    j.mkdir(parents=True)
    (j / "system.journal").write_bytes(b"x" * 1000)
    old, fresh = j / "system@old.journal", j / "system@new.journal"
    old.write_bytes(b"x" * 4000)
    fresh.write_bytes(b"x" * 2000)
    age(old, 30)
    age(fresh, 1)
    real_iter = E.iter_dir
    monkeypatch.setattr(E, "iter_dir", lambda p: real_iter(str(tmp_path / "journal") if p == "/var/log/journal" else
                                                         (str(j) if p == str(tmp_path / "journal" / "abc") else p)))
    assert L.LinuxCleaner._journal_estimate() == 4000


# ── logs + crash dumps: Python lập danh sách, helper kiểm tra lại và xóa ──────
@pytest.fixture()
def fake_var(monkeypatch, tmp_path):
    log, crash, core = tmp_path / "log", tmp_path / "crash", tmp_path / "core"
    for d in (log, crash, core):
        d.mkdir()
        d.chmod(0o755)
    monkeypatch.setattr(L, "LOG_ROOT", str(log))
    monkeypatch.setattr(L, "CRASH_ROOT", str(crash))
    monkeypatch.setattr(L, "COREDUMP_ROOT", str(core))
    monkeypatch.setattr(L.LinuxCleaner, "_trusted", staticmethod(lambda st: True))
    return log, crash, core


def put(p: Path, size=100, days=30):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)
    age(p, days)
    return p


def test_system_logs_list_only_rotated_and_old(cleaner, fake_var, monkeypatch):
    log, _, _ = fake_var
    a, b = put(log / "syslog.1", 100), put(log / "kern.log.2.gz", 200)
    put(log / "syslog", 999)                                   # đang dùng
    put(log / "fresh.log.1", 50, days=0)                       # mới
    put(log / "sub" / "app.log.old", 300)
    link = log / "evil.1"
    link.symlink_to("/etc/passwd")
    d = cleaner._system_logs(True)
    assert d.freed_bytes == 600 and d.files_removed == 3

    def delete(action, args, stdin):
        for l in stdin.splitlines():
            if os.path.lexists(l):
                os.unlink(l)
    rec = Recorder(on_call=delete)
    monkeypatch.setattr(P, "run_helper", rec)
    r = cleaner._system_logs(False)
    action, _, stdin = rec.calls[0]
    assert action == "clean-rotated-logs"
    sent = set(stdin.split())
    assert str(a) in sent and str(b) in sent and str(link) not in sent
    assert r.freed_bytes == 600 and not a.exists() and (log / "syslog").exists()


def test_system_logs_skips_untrusted_dirs_like_helper(cleaner, fake_var, monkeypatch):
    log, _, _ = fake_var
    monkeypatch.setattr(L.LinuxCleaner, "_trusted", staticmethod(lambda st: not (st.st_mode & 0o022)))
    put(log / "ok" / "a.1", 10)
    (log / "ok").chmod(0o755)
    put(log / "bad" / "b.1", 10)
    (log / "bad").chmod(0o777)
    assert cleaner._system_logs(True).files_removed == 1


def test_system_logs_helper_failure_reports_reason(cleaner, fake_var, monkeypatch):
    log, _, _ = fake_var
    put(log / "a.1", 10)
    monkeypatch.setattr(P, "run_helper", Recorder({"clean-rotated-logs": P.HelperResult(1, kind="no_helper")}))
    r = cleaner._system_logs(False)
    assert r.error and "install.sh" in r.error


def test_system_logs_changed_file_is_not_sent(cleaner, fake_var, monkeypatch):
    log, _, _ = fake_var
    f = put(log / "a.1", 10)
    plan = E.Plan("system_logs", cleaner._log_items())
    f.write_bytes(b"app wrote to it again")
    rec = Recorder()
    monkeypatch.setattr(P, "run_helper", rec)
    cleaner.result_from_plan("system_logs", plan, dry=False)
    assert rec.calls == []


def test_crash_reports_freed_bytes_not_lost(cleaner, fake_var, monkeypatch, tmp_path):
    """Báo cáo: nhánh root của crash_reports luôn cộng 0 byte vì rollback chưa có size."""
    _, crash, core = fake_var
    c1, c2 = put(crash / "_usr_bin_x.1000.crash", 4000), put(core / "core.firefox.1000.x.zst", 9000)
    put(core / "readme.txt", 5)
    (cleaner.ctx.home and None)
    home_apport = tree(Path(cleaner.ctx.home) / ".local/share/apport", {"a.crash": 70})
    d = cleaner._crash_reports(True)
    assert d.freed_bytes == 4000 + 9000 + 70

    def delete(action, args, stdin):
        for l in stdin.splitlines():
            os.unlink(l)
    rec = Recorder(on_call=delete)
    monkeypatch.setattr(P, "run_helper", rec)
    r = cleaner._crash_reports(False)
    assert rec.calls[0][0] == "clean-crash-dirs"
    assert r.freed_bytes == 13070, "freed bytes của file root phải được cộng đúng"
    assert not c1.exists() and not c2.exists() and not (home_apport / "a.crash").exists()


# ── REVIEW: pacman orphans ───────────────────────────────────────────────────
def fake_cmd(mapping):
    def _c(argv, timeout=30, input_text=None):
        for key, val in mapping.items():
            if argv[:len(key)] == list(key):
                return val
        return "", "", 1
    return _c


def test_orphans_scan_and_clean(cleaner, monkeypatch):
    monkeypatch.setattr(L, "PKG_MANAGER", "pacman")
    monkeypatch.setattr(L, "_cmd", fake_cmd({
        ("pacman", "-Qdtq"): ("foo\nbar\n--evil\n", "", 0),
        ("pacman", "-Qi"): ("Name            : foo\nInstalled Size  : 2.00 MiB\n\nName            : bar\nInstalled Size  : 10.00 KiB\n", "", 0),
    }))
    scan = cleaner._rv_pacman_orphans()
    assert [i.id for i in scan.items] == ["foo", "bar"], "tên nguy hiểm (--evil) phải bị loại"
    assert scan.items[0].size == 2 * 1024**2 and scan.warning
    rec = Recorder()
    monkeypatch.setattr(P, "run_helper", rec)
    targets(cleaner)["orphaned_pkgs"] if "orphaned_pkgs" in targets(cleaner) else None
    r = cleaner._rc_pacman_orphans(["foo", "ghost", "--evil"], dry=False)
    action, args, stdin = rec.calls[0]
    assert action == "pacman-orphans" and stdin.split() == ["foo"], "chỉ gửi gói hiện đang là orphan và hợp lệ"
    assert r.files_removed == 1


def test_apt_autoremove_all_selected_uses_single_transaction(cleaner, monkeypatch):
    out = "Remv libfoo [1.0]\nRemv linux-image-6.1.0-old [6.1]\nInst x\n"
    monkeypatch.setattr(L, "_cmd", fake_cmd({
        ("apt-get", "-s"): (out, "", 0),
        ("dpkg-query",): ("libfoo 100\nlinux-image-6.1.0-old 300000\n", "", 0),
    }))
    scan = cleaner._rv_apt_autoremove()
    assert {i.id for i in scan.items} == {"libfoo", "linux-image-6.1.0-old"}
    rec = Recorder()
    monkeypatch.setattr(P, "run_helper", rec)
    cleaner._rc_apt_autoremove(["libfoo", "linux-image-6.1.0-old"], dry=False)
    assert [c[0] for c in rec.calls] == ["apt-autoremove"]
    rec.calls.clear()
    cleaner._rc_apt_autoremove(["libfoo"], dry=False)
    assert rec.calls == [("apt-remove", ("libfoo",), None)]


def test_dnf_autoremove_failure_to_list_is_benign(cleaner, monkeypatch):
    monkeypatch.setattr(L, "_cmd", fake_cmd({}))
    scan = cleaner._rv_dnf_autoremove()
    assert scan.items == [] and scan.notes


# ── REVIEW: flatpak / snap / docker ──────────────────────────────────────────
FLATPAK_OUT = """Uninstall:

   ID                                   Branch  Op
 1. org.freedesktop.Platform.GL.default 23.08   r
 2. org.gnome.Platform.Locale           45      r
"""


def test_flatpak_parse_and_clean(cleaner, monkeypatch):
    calls = []

    def _c(argv, timeout=30, input_text=None):
        calls.append(argv)
        if argv[:3] == ["flatpak", "uninstall", "--unused"]:
            return FLATPAK_OUT, "", 0
        if argv[:2] == ["flatpak", "list"]:
            return "org.freedesktop.Platform.GL.default\t23.08\t300.0 MB\norg.gnome.Platform.Locale\t45\t17.0 MB\n", "", 0
        return "", "", 0
    monkeypatch.setattr(L, "_cmd", _c)
    scan = cleaner._rv_flatpak()
    assert [i.id for i in scan.items] == ["org.freedesktop.Platform.GL.default//23.08", "org.gnome.Platform.Locale//45"]
    assert scan.items[0].size == 300_000_000
    r = cleaner._rc_flatpak(["org.gnome.Platform.Locale//45", "evil;rm//1"], dry=False)
    assert ["flatpak", "uninstall", "-y", "--noninteractive", "org.gnome.Platform.Locale//45"] in calls
    assert r.files_removed == 1 and not any("evil" in " ".join(c) for c in calls)


def test_snap_old_exact_size_and_removal(cleaner, monkeypatch, tmp_path):
    snaps = tmp_path / "snaps"
    snaps.mkdir()
    (snaps / "firefox_4336.snap").write_bytes(b"s" * 12345)
    real_stat = os.stat
    monkeypatch.setattr(L.os, "stat", lambda p, *a, **k: real_stat(str(snaps / Path(p).name)) if str(p).startswith("/var/lib/snapd/snaps/") else real_stat(p, *a, **k))
    listing = ("Name  Version  Rev   Tracking  Publisher  Notes\n"
               "firefox 120.0 4336 latest/stable mozilla✓ disabled\n"
               "firefox 121.0 4400 latest/stable mozilla✓ -\n"
               "core20 20231 2015 latest/stable canonical✓ base,disabled\n")
    monkeypatch.setattr(L, "_cmd", fake_cmd({("snap", "list"): (listing, "", 0)}))
    scan = cleaner._rv_snap()
    by = {i.id: i for i in scan.items}
    assert set(by) == {"firefox:4336", "core20:2015"} and by["firefox:4336"].size == 12345
    rec = Recorder()
    monkeypatch.setattr(P, "run_helper", rec)
    r = cleaner._rc_snap(["firefox:4336", "firefox:4400"], dry=False)
    assert rec.calls == [("snap-remove-rev", ("firefox", "4336"), None)] and r.freed_bytes == 12345


def test_docker_volumes_never_touched_unless_selected(cleaner, monkeypatch):
    monkeypatch.setattr(L, "CONTAINER_TOOL", "docker")
    calls = []

    def _c(argv, timeout=30, input_text=None):
        calls.append(argv)
        if argv[1] == "images":
            return "abc123def456\tfoo:latest\t1.2GB\t2 weeks ago\n", "", 0
        if argv[1] == "ps":
            return "c0ffee\tdb\tpostgres:16\tExited (0) 3 days ago\n", "", 0
        if argv[1:3] == ["volume", "ls"]:
            return "pgdata\nanon_1234\n", "", 0
        if argv[1:3] == ["system", "df"]:
            return "Images\t1GB\nBuild Cache\t900MB (100%)\n", "", 0
        return "", "", 0
    monkeypatch.setattr(L, "_cmd", _c)
    scan = cleaner._rv_docker()
    risk = {i.id: i.risk for i in scan.items}
    assert risk["volume:pgdata"] == "high" and risk["container:c0ffee"] == "medium" and risk["image:abc123def456"] == "low"
    assert any(i.id == "buildcache:all" and i.size == 900_000_000 for i in scan.items)
    assert scan.warning
    calls.clear()
    r = cleaner._rc_docker(["image:abc123def456", "buildcache:all"], dry=False)
    flat = [" ".join(c) for c in calls if c[1] in ("rmi", "rm", "volume", "builder")]
    assert "docker rmi abc123def456" in flat and "docker builder prune -f" in flat
    assert not any("volume rm" in f for f in flat), "volume không được chọn thì tuyệt đối không bị xóa"
    assert r.files_removed == 2


def test_docker_permission_denied_message(cleaner, monkeypatch):
    monkeypatch.setattr(L, "CONTAINER_TOOL", "docker")
    monkeypatch.setattr(L, "_cmd", lambda *a, **k: ("", "Got permission denied while trying to connect", 1))
    scan = cleaner._rv_docker()
    assert scan.items == [] and any("permission denied" in n for n in scan.notes)


# ── REVIEW: trash ────────────────────────────────────────────────────────────
def make_trash(tmp_path):
    t = tmp_path / "Trash"
    (t / "files").mkdir(parents=True)
    (t / "info").mkdir()
    (t / "files" / "big.iso").write_bytes(b"x" * 9000)
    (t / "info" / "big.iso.trashinfo").write_text("[Trash Info]\nPath=/home/u/Downloads/big%20file.iso\nDeletionDate=2024-01-01T00:00:00\n")
    tree(t / "files" / "docs", {"a.txt": 100, "b.txt": 200}, days=40)
    (t / "info" / "docs.trashinfo").write_text("[Trash Info]\nPath=/home/u/docs\n")
    (t / "directorysizes").write_text("300 1 docs\n")
    age(t / "files" / "big.iso", 40)
    return t


def test_trash_scan_labels_with_original_path_and_nothing_prechecked(cleaner, monkeypatch, tmp_path):
    t = make_trash(tmp_path)
    monkeypatch.setattr(cleaner, "_trash_dirs", lambda: [str(t)])
    scan = cleaner._rv_trash()
    assert scan.permanent and scan.warning
    labels = {i.label for i in scan.items}
    assert "/home/u/Downloads/big file.iso" in labels and "/home/u/docs" in labels


def test_trash_clean_only_selected_items_and_info(cleaner, monkeypatch, tmp_path):
    t = make_trash(tmp_path)
    monkeypatch.setattr(cleaner, "_trash_dirs", lambda: [str(t)])
    scan = cleaner._rv_trash()
    big = next(i for i in scan.items if i.label.endswith("big file.iso"))
    r = cleaner._rc_trash([big.id], dry=False)
    assert not (t / "files" / "big.iso").exists() and not (t / "info" / "big.iso.trashinfo").exists()
    assert (t / "files" / "docs").exists(), "mục không được chọn phải còn nguyên"
    assert r.freed_bytes == 9000 and not (t / "directorysizes").exists()


def test_trash_dry_run_changes_nothing(cleaner, monkeypatch, tmp_path):
    t = make_trash(tmp_path)
    monkeypatch.setattr(cleaner, "_trash_dirs", lambda: [str(t)])
    scan = cleaner._rv_trash()
    r = cleaner._rc_trash([i.id for i in scan.items], dry=True)
    assert r.freed_bytes == 9300 and (t / "files" / "big.iso").exists()


def test_trash_not_touched_by_auto_clean_entry_points(cleaner, monkeypatch, tmp_path):
    t = make_trash(tmp_path)
    monkeypatch.setattr(cleaner, "_trash_dirs", lambda: [str(t)])
    cleaner.clean("empty_trash", dry=False)
    cleaner.clean("empty_trash", dry=False, unattended=True)
    assert (t / "files" / "big.iso").exists()


# ── REVIEW: rule-based (dev_cache / app_cache) ───────────────────────────────
def test_dev_cache_review_roundtrip_and_selection(cleaner):
    home = Path(cleaner.ctx.home)
    tree(home / ".cache/go-build", {"aa/x": 100})
    tree(home / ".npm/_cacache", {"c/y": 50})
    tree(home / ".m2/repository", {"foo.jar": 3000})
    scan = cleaner.review_scan("dev_cache")
    ids = {Path(i.payload["path"]).name: i.id for i in scan.items}
    assert {"go-build", "_cacache", "repository"} <= set(ids)
    assert all(not i.blocked for i in scan.items)
    r = cleaner.review_clean("dev_cache", [ids["go-build"]])
    assert (home / ".cache/go-build").exists() is True        # mode contents: giữ thư mục gốc
    assert not (home / ".cache/go-build/aa").exists()
    assert (home / ".m2/repository/foo.jar").exists(), "mục không chọn không được đụng"
    assert r.freed_bytes == 100


def test_app_cache_review_exposes_unknown_only_and_cleans_selected(cleaner):
    home = Path(cleaner.ctx.home)
    tree(home / ".cache/mystery", {"x": 500}, days=40)
    tree(home / ".cache/borg", {"idx": 500}, days=40)
    scan = cleaner.review_scan("app_cache")
    assert [Path(i.payload["path"]).name for i in scan.items] == ["mystery"]
    cleaner.review_clean("app_cache", [scan.items[0].id])
    assert not (home / ".cache/mystery").exists() and (home / ".cache/borg").exists()


def test_review_clean_rejects_non_review_target(cleaner):
    r = cleaner.review_clean("thumbnails", ["x"])
    assert r.error
    with pytest.raises(ValueError):
        cleaner.review_scan("thumbnails")


# ── Auto thật sự chạy end-to-end ─────────────────────────────────────────────
def test_auto_targets_end_to_end_dry_equals_real(cleaner):
    home = Path(cleaner.ctx.home)
    tree(home / ".config/google-chrome", {"Local State": 4, "Default/Cache/a": 800, "Default/Cookies": 9})
    tree(home / ".cache/thumbnails", {"normal/a.png": 300}, days=40)
    for tid in ("chromium_cache", "thumbnails"):
        d = cleaner.clean(tid, dry=True)
        assert d.plan is not None and d.freed_bytes > 0 and not d.error
        r = cleaner.clean(tid, dry=False, plan=d.plan)
        assert r.freed_bytes == d.freed_bytes and not r.error
    assert (home / ".config/google-chrome/Default/Cookies").exists()


def test_cached_plan_is_revalidated_not_blindly_executed(cleaner):
    home = Path(cleaner.ctx.home)
    tree(home / ".config/chromium", {"Local State": 4, "Default/Cache/a": 800})
    d = cleaner.clean("chromium_cache", dry=True)
    (home / ".config/chromium/Default/Cache/a").write_bytes(b"browser wrote while you were reading the preview")
    r = cleaner.clean("chromium_cache", dry=False, plan=d.plan)
    assert (home / ".config/chromium/Default/Cache/a").exists()
    assert r.freed_bytes == 0 and r.skipped


def test_chrome_running_gives_note_not_error(cleaner):
    home = Path(cleaner.ctx.home)
    cfg = tree(home / ".config/google-chrome", {"Local State": 4, "Default/Cache/a": 800})
    (cfg / "SingletonLock").symlink_to(f"host-{os.getpid()}")
    r = cleaner.clean("chromium_cache", dry=False)
    assert r.error is None and r.freed_bytes == 0 and any("running" in n for n in r.notes)
    assert (cfg / "Default/Cache/a").exists()


def test_tmp_files_target_protects_sockets(cleaner, monkeypatch, tmp_path):
    t = tmp_path / "tmpdir"
    x11 = tree(t / ".X11-unix", {})
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(x11 / "X0"))
    age(x11, 30)
    tree(t / "junk", {"a": 10}, days=30)
    import dataclasses
    from core import rules as R
    rule = next(x for x in cleaner.ruleset.rules if x.id == "tmp-children")
    cleaner.ruleset.rules = [dataclasses.replace(rule, paths=(str(t),))]
    try:
        r = cleaner.clean("tmp_files", dry=False)
    finally:
        s.close()
    assert x11.exists() and not (t / "junk").exists() and r.freed_bytes == 10


def test_ensure_privileged_session_delegates_to_ping(monkeypatch):
    seen = []
    monkeypatch.setattr(P, "ensure_session", lambda log_cb=None: seen.append(1) or True)
    assert L.ensure_privileged_session() is True and seen
