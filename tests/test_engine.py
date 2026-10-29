import os
import socket
import stat
import subprocess
import time
from pathlib import Path

import pytest

from core import engine as E
from core.engine import Guards, Policy

from tests.helpers import DAY, FakeGuards, age, tree  # noqa: E402


# ── tree_stats ───────────────────────────────────────────────────────────────
def test_tree_stats_basic(tmp_path):
    d = tree(tmp_path / "c", {"a.bin": 100, "sub/b.bin": 250, "sub/deep/c.bin": 50})
    ts = E.tree_stats(d)
    assert ts.size == 400 and ts.files == 3 and ts.exists
    assert not ts.has_special and not ts.crosses_mount
    assert abs(ts.newest - (time.time() - 30 * DAY)) < 5


def test_tree_stats_missing(tmp_path):
    assert not E.tree_stats(tmp_path / "nope").exists


def test_tree_stats_never_follows_symlinks(tmp_path):
    outside = tree(tmp_path / "outside", {"big.bin": 10_000})
    d = tmp_path / "c"
    d.mkdir()
    (d / "f").write_bytes(b"x" * 10)
    (d / "link_dir").symlink_to(outside)
    (d / "link_file").symlink_to(outside / "big.bin")
    ts = E.tree_stats(d)
    assert ts.size == 10 and ts.files == 1


def test_tree_stats_detects_socket_and_fifo(tmp_path):
    d = tmp_path / "c"
    d.mkdir()
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(d / "app.sock"))
    try:
        assert E.tree_stats(d).has_special
    finally:
        s.close()
    d2 = tmp_path / "c2"
    d2.mkdir()
    os.mkfifo(d2 / "pipe")
    assert E.tree_stats(d2).has_special


def test_tree_stats_hardlinks_counted_only_when_all_links_inside(tmp_path):
    store = tmp_path / "store"
    proj = tmp_path / "proj"
    store.mkdir(); proj.mkdir()
    (store / "blob").write_bytes(b"x" * 1000)
    os.link(store / "blob", proj / "blob")
    only_store = E.tree_stats(store)
    assert only_store.size == 0 and only_store.shared == 1000     # xóa store không giải phóng gì
    # cả hai nhóm link cùng nằm trong một cây → giải phóng thật
    both = tmp_path / "both"
    both.mkdir()
    (both / "a").write_bytes(b"y" * 500)
    os.link(both / "a", both / "b")
    ts = E.tree_stats(both)
    assert ts.size == 500 and ts.shared == 0


def test_tree_stats_crosses_mount(tmp_path):
    d = tmp_path / "c"
    (d / "m").mkdir(parents=True)
    r = subprocess.run(["mount", "-t", "tmpfs", "tmpfs", str(d / "m")], capture_output=True)
    if r.returncode != 0:
        pytest.skip("cannot mount tmpfs here")
    try:
        (d / "m" / "f").write_bytes(b"x" * 100)
        ts = E.tree_stats(d)
        assert ts.crosses_mount and ts.size == 0
        item, why = E.make_item(d, Policy(), guards=None)
        assert item is None and "mount" in why
    finally:
        subprocess.run(["umount", str(d / "m")], capture_output=True)


# ── make_item / policy ───────────────────────────────────────────────────────
def test_make_item_age_policy(tmp_path):
    old = tree(tmp_path / "old", {"f": 10}, days=40)
    new = tree(tmp_path / "new", {"f": 10}, days=2)
    pol = Policy(min_age_sec=30 * DAY)
    it, why = E.make_item(old, pol)
    assert it is not None and why == "" and it.size == 10
    it, why = E.make_item(new, pol)
    assert it is None and "days ago" in why


def test_recent_guard_applies_even_with_zero_age(tmp_path):
    d = tmp_path / "c"
    d.mkdir()
    (d / "f").write_bytes(b"x")            # vừa tạo
    it, why = E.make_item(d, Policy(min_age_sec=0))
    assert it is None and "10 minutes" in why


def test_deep_modification_is_detected(tmp_path):
    """Báo cáo: tmp_files chỉ xét mtime thư mục cấp 1 → xóa nhầm build dir có file vừa ghi."""
    d = tree(tmp_path / "build", {"obj/deep/a.o": 10, "x": 1}, days=30)
    (d / "obj/deep/fresh.o").write_bytes(b"new")      # file sâu vừa ghi, mtime thư mục cha thay đổi nhưng
    age(d / "obj/deep", 30)                            # giả lập: mtime dir cha cũ
    age(d / "obj", 30)
    age(d, 30)
    it, why = E.make_item(d, Policy(min_age_sec=3 * DAY))
    assert it is None, "đã đánh dấu xóa thư mục có file mới ghi bên trong"


def test_socket_inside_dir_blocks_item(tmp_path):
    """Báo cáo: tmp_files xóa /tmp/.X11-unix (chứa socket sống, dir cũ > 3 ngày)."""
    d = tmp_path / ".X11-unix"
    d.mkdir()
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(d / "X0"))
    try:
        age(d, 30)
        it, why = E.make_item(d, Policy(min_age_sec=3 * DAY))
        assert it is None and "socket" in why
    finally:
        s.close()


def test_closed_process_guard_blocks_with_reason(tmp_path):
    d = tree(tmp_path / "cache", {"f": 10})
    g = FakeGuards(procs=["chrome"])
    it, why = E.make_item(d, Policy(closed=("chrome", "chromium")), guards=g)
    assert it is not None and it.blocked and "chrome" in why
    it2, why2 = E.make_item(d, Policy(closed=("firefox",)), guards=g)
    assert it2 is not None and not it2.blocked


def test_open_file_guard(tmp_path):
    d = tree(tmp_path / "cache", {"sub/db.sqlite": 10})
    g = FakeGuards(open_paths=[str(d / "sub/db.sqlite")])
    it, why = E.make_item(d, Policy(), guards=g)
    assert it is not None and it.blocked and "in use" in why


def test_symlink_root_never_planned(tmp_path):
    target = tree(tmp_path / "t", {"f": 10})
    ln = tmp_path / "ln"
    ln.symlink_to(target)
    it, why = E.make_item(ln, Policy())
    assert it is None and "symlink" in why


# ── execute: kiểm tra lại ────────────────────────────────────────────────────
def plan_one(path, **kw):
    it, why = E.make_item(path, Policy(**kw))
    assert it is not None, why
    return it


def test_execute_removes_and_reports_real_freed(tmp_path):
    d = tree(tmp_path / "c", {"a": 100, "s/b": 200})
    it = plan_one(d)
    res = E.execute_plan([it])
    assert not d.exists()
    assert res.freed == 300 and res.removed == 2 and res.outcomes[0].status == "removed"


def test_execute_skips_if_modified_after_plan(tmp_path):
    d = tree(tmp_path / "c", {"a": 100})
    it = plan_one(d)
    (d / "a").write_bytes(b"changed")           # app ghi vào giữa lúc preview và execute
    res = E.execute_plan([it])
    assert d.exists()
    assert res.outcomes[0].status == "skipped" and "modified" in res.outcomes[0].reason


def test_execute_skips_if_inode_replaced(tmp_path):
    d = tree(tmp_path / "c", {"a": 100})
    it = plan_one(d)
    import shutil
    shutil.rmtree(d)
    d.mkdir()                                     # cùng tên, inode khác
    (d / "mine").write_bytes(b"precious")
    age(d / "mine", 30); age(d, 30)
    res = E.execute_plan([it])
    assert (d / "mine").exists() and res.outcomes[0].status == "skipped"


def test_execute_rechecks_running_app_after_plan(tmp_path):
    d = tree(tmp_path / "c", {"a": 100})
    it, _ = E.make_item(d, Policy(closed=("chrome",)), guards=FakeGuards())
    assert not it.blocked
    res = E.execute_plan([it], guards=FakeGuards(procs=["chrome"]))   # user mở lại Chrome
    assert d.exists() and "chrome" in res.outcomes[0].reason


def test_execute_file_kind(tmp_path):
    f = tmp_path / "x.log"
    f.write_bytes(b"z" * 77)
    age(f, 30)
    it = plan_one(f)
    assert it.kind == "file"
    res = E.execute_plan([it])
    assert not f.exists() and res.freed == 77


def test_execute_readonly_tree_like_go_modcache(tmp_path):
    """shutil.rmtree(ignore_errors=True) cũ để lại gần như nguyên Go module cache (0555)."""
    d = tree(tmp_path / "mod", {"pkg@v1/a.go": 100, "pkg@v1/sub/b.go": 100})
    for p in sorted(d.rglob("*"), key=lambda q: -len(q.parts)):
        p.chmod(0o444 if p.is_file() else 0o555)
    d.chmod(0o555)
    it = plan_one(d)
    if getattr(os, "geteuid", lambda: -1)() == 0:
        pytest.skip("root bỏ qua quyền ghi nên không tái hiện được")
    res = E.execute_plan([it])
    assert not d.exists() and res.freed == 200


def test_execute_keep_root_and_keep_names(tmp_path):
    d = tree(tmp_path / "yay", {"pkgA/PKGBUILD": 10, "pkgB/x": 20, "vcs.json": 5})
    it = plan_one(d)
    it.keep_root = True
    it.meta["keep"] = ("vcs.json",)
    res = E.execute_plan([it])
    assert d.exists() and (d / "vcs.json").exists()
    assert not (d / "pkgA").exists() and not (d / "pkgB").exists()
    assert res.outcomes[0].status == "removed" and res.freed == 30


def test_execute_hardlink_not_counted_as_freed(tmp_path):
    store = tmp_path / "store"
    proj = tmp_path / "proj"
    store.mkdir(); proj.mkdir()
    (store / "blob").write_bytes(b"x" * 1000)
    os.link(store / "blob", proj / "blob")
    age(store / "blob", 30); age(store, 30)
    it = plan_one(store)
    assert it.size == 0 and it.shared == 1000
    res = E.execute_plan([it])
    assert res.freed == 0 and (proj / "blob").exists()


def test_dry_run_does_not_touch_disk_and_matches_real(tmp_path):
    d = tree(tmp_path / "c", {"a": 100, "b/c": 50})
    it = plan_one(d)
    dry = E.execute_plan([it], dry=True)
    assert d.exists()
    real = E.execute_plan([it])
    assert dry.freed == real.freed == 150 and not d.exists()


def test_files_kind_old_files_only_and_prunes_empty_dirs(tmp_path):
    root = tmp_path / "thumbs"
    (root / "normal").mkdir(parents=True)
    (root / "large").mkdir()
    oldf = root / "normal" / "a.png"
    newf = root / "large" / "b.png"
    oldf.write_bytes(b"x" * 100)
    newf.write_bytes(b"y" * 50)
    age(oldf, 60)
    pol = Policy(min_age_sec=30 * DAY, basis="atime")
    it = E.plan_old_files(root, pol, label="thumbs", group="t")
    assert it is not None and it.files == 1 and it.size == 100
    res = E.execute_plan([it])
    assert not oldf.exists() and newf.exists() and root.exists()
    assert not (root / "normal").exists(), "thư mục rỗng phải được dọn"
    assert res.freed == 100


def test_files_kind_skips_file_changed_after_plan(tmp_path):
    root = tmp_path / "pip"
    root.mkdir()
    f = root / "w.whl"
    f.write_bytes(b"x" * 10)
    age(f, 60)
    it = E.plan_old_files(root, Policy(min_age_sec=30 * DAY), label="pip", group="p")
    f.write_bytes(b"newer content")
    res = E.execute_plan([it])
    assert f.exists() and res.outcomes[0].status == "skipped"


# ── fs / meter ───────────────────────────────────────────────────────────────
def test_fs_type_parsing(monkeypatch):
    mounts = [("/", "ext4"), ("/home", "btrfs"), ("/tmp", "tmpfs"), ("/home/u/Mount Dir", "ext4")]
    monkeypatch.setattr(E, "_MOUNTS_CACHE", mounts)
    monkeypatch.setattr(E.os.path, "realpath", lambda p: p)
    assert E.fs_type("/home/u/.cache") == "btrfs"
    assert E.fs_type("/tmp/x") == "tmpfs" and E.is_ram_backed("/tmp")
    assert E.fs_type("/var/log") == "ext4"
    assert E.fs_type("/home/u/Mount Dir/x") == "ext4"
    assert "snapshot" in E.snapshot_note("/home/u/.cache")
    assert E.snapshot_note("/var/log") == ""


def test_free_space_meter(tmp_path):
    m = E.FreeSpaceMeter([str(tmp_path / "does" / "not" / "exist")])
    m.begin()
    assert m.end() is not None


def test_chromium_singleton_lock(tmp_path):
    d = tmp_path / "chrome"
    d.mkdir()
    assert not E.chromium_profile_in_use(str(d))
    (d / "SingletonLock").symlink_to(f"host-{os.getpid()}")
    assert E.chromium_profile_in_use(str(d))
    (d / "SingletonLock").unlink()
    (d / "SingletonLock").symlink_to("host-999999999")
    assert not E.chromium_profile_in_use(str(d))        # lock cũ (crash)


def test_missing_psutil_fails_closed_for_closed_app_guard(tmp_path, monkeypatch):
    """Không có psutil thì không biết app đã tắt chưa → không được cho phép xóa cache của nó."""
    d = tree(tmp_path / "cache", {"f": 10})
    monkeypatch.setattr(Guards, "psutil_available", staticmethod(lambda: False))
    g = Guards(max_age=0)
    it, why = E.make_item(d, Policy(closed=("chrome",)), guards=g)
    assert it is not None and it.blocked and "psutil" in it.blocked
    # item không yêu cầu app đóng vẫn dọn được
    it2, _ = E.make_item(d, Policy(), guards=g)
    assert it2 is not None and not it2.blocked


def test_mount_point_is_detected_without_needing_mount_privileges(tmp_path, monkeypatch):
    """Bản test crosses_mount không cần quyền mount: giả st_dev khác cho một thư mục con."""
    d = tree(tmp_path / "c", {"keep.bin": 10, "m/inner.bin": 99})
    real_scandir = os.scandir

    class Entry:
        def __init__(self, e): self._e, self.name, self.path = e, e.name, e.path
        def stat(self, follow_symlinks=True):
            st = self._e.stat(follow_symlinks=follow_symlinks)
            if self.name == "m":
                vals = list(st)
                vals[2] = st.st_dev + 1                 # st_dev
                return os.stat_result(vals)
            return st
        def is_dir(self, **k): return self._e.is_dir(**k)

    class Wrap:
        def __init__(self, it): self._it = it
        def __enter__(self): self._it.__enter__(); return self
        def __exit__(self, *a): return self._it.__exit__(*a)
        def __iter__(self): return (Entry(e) for e in self._it)

    monkeypatch.setattr(E.os, "scandir", lambda p: Wrap(real_scandir(p)))
    ts = E.tree_stats(d)
    assert ts.crosses_mount and ts.size == 10, "thư mục trên thiết bị khác không được tính / không được xóa"
    it, why = E.make_item(d, Policy())
    assert it is None and "mount" in why


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="POSIX UID behavior")
def test_foreign_owned_items_are_skipped(tmp_path):
    d = tree(tmp_path / "c", {"a": 10})
    E.set_owner_uid(os.getuid() + 4242)                  # coi như mọi file thuộc người khác
    try:
        it, why = E.make_item(d, Policy())
        assert it is None and "another user" in why
        it2, _ = E.make_item(d, Policy(require_owner=False))
        assert it2 is not None
    finally:
        E.set_owner_uid(None)


def test_single_file_hardlink_is_not_counted_as_freed(tmp_path):
    f = tmp_path / "blob"
    f.write_bytes(b"x" * 700)
    os.link(f, tmp_path / "other-name")
    age(f, 30)
    ts = E.tree_stats(f)
    assert ts.size == 0 and ts.shared == 700
    it = plan_one(f)
    res = E.execute_plan([it])
    assert res.freed == 0 and (tmp_path / "other-name").exists()


def test_dry_run_on_single_file_does_not_delete(tmp_path):
    f = tmp_path / "x.log"
    f.write_bytes(b"z" * 55)
    age(f, 30)
    it = plan_one(f)
    dry = E.execute_plan([it], dry=True)
    assert f.exists() and dry.freed == 55
    assert not E.execute_plan([it]).errors and not f.exists()


def test_replacement_is_caught_even_if_only_inode_check_remains(tmp_path):
    """E9 sống sót vì ctime đã che; test này khóa luôn hành vi 'inode khác → bỏ qua' khi ctime trùng."""
    d = tree(tmp_path / "c", {"a": 10})
    it = plan_one(d)
    it.ino += 1                                    # mô phỏng: cùng ctime nhưng inode khác
    res = E.execute_plan([it])
    assert d.exists() and res.outcomes[0].status == "skipped" and "replaced" in res.outcomes[0].reason
