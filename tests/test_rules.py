import dataclasses
import os
import socket
from pathlib import Path

import pytest

from core import engine as E
from core import rules as R
from tests.helpers import DAY, FakeGuards, age, tree

SAFE_NEVER = {
    "Cookies", "Local Storage", "IndexedDB", "Session Storage", "Login Data", "Web Data", "History",
    "Preferences", "Local State", "Extensions", "databases", "leveldb", "Network",
}


@pytest.fixture(scope="module")
def builtin():
    rs = R.RuleSet()
    for f in sorted(R.rules_dir().glob("*.toml")):
        rs.load_file(f)
    return rs


def lctx(home, **env):
    return R.RuleContext(os_name="linux", home=str(home), env=dict(env), which=lambda c: "/usr/bin/" + c)


@pytest.fixture(autouse=True)
def _not_ram(monkeypatch):
    monkeypatch.setattr(E, "is_ram_backed", lambda p: False)


def plan_for(rs, ctx, target, *, unattended=False, guards=None):
    return rs.plan(target, ctx, unattended=unattended, guards=guards or FakeGuards())


# ── nạp + bất biến an toàn của luật built-in ─────────────────────────────────
def test_builtin_rules_load_and_cross_validate(builtin):
    assert builtin.validate() == []
    assert len(builtin.rules) > 20


def test_every_target_shape(builtin):
    for defs in builtin.targets.values():
        for t in defs:
            assert t.tier in ("auto", "review")
            if t.tier == "auto":
                assert t.safety == "safe"
            else:
                assert not t.scheduled, f"{t.id}: review target không được chạy nền"


def test_auto_targets_never_include_user_data_paths(builtin):
    """Tier auto chỉ được chứa cache tái tạo được — không thư mục dữ liệu người dùng."""
    forbidden_components = {"Documents", "Downloads", "Pictures", "Desktop", "Music", "Videos", ".ssh",
                            ".gnupg", "Trash", ".m2", ".mozilla", "Steam", ".wine", "Dropbox", "OneDrive"}
    for r in builtin.rules:
        t = next(t for defs in builtin.targets.values() for t in defs if t.id == r.target)
        if t.tier != "auto":
            continue
        for p in (*r.paths, *r.user_data, *r.cache_roots):
            comps = set(p.replace("\\", "/").split("/"))
            assert not (comps & forbidden_components), (r.id, p)


def test_review_only_for_risky_targets(builtin):
    review_ids = {t.id for defs in builtin.targets.values() for t in defs if t.tier == "review"}
    assert {"dev_cache", "app_cache"} <= review_ids
    auto_ids = {t.id for defs in builtin.targets.values() for t in defs if t.tier == "auto"}
    assert not ({"dev_cache", "app_cache", "empty_trash"} & auto_ids)


def test_chromium_subpaths_never_touch_sensitive_names(builtin):
    for r in builtin.rules:
        if r.kind != "chromium":
            continue
        for sp in r.subpaths:
            parts = set(sp.replace("\\", "/").split("/"))
            assert not (parts & SAFE_NEVER), (r.id, sp)
            assert not (parts & set(r.never)), (r.id, sp)
        assert SAFE_NEVER <= set(r.never)


def test_no_rule_path_is_a_system_root(builtin):
    ctx = lctx("/home/u")
    wctx = R.RuleContext(os_name="windows", home="C:\\Users\\u",
                         env={"LOCALAPPDATA": "C:\\Users\\u\\AppData\\Local",
                              "APPDATA": "C:\\Users\\u\\AppData\\Roaming", "USERPROFILE": "C:\\Users\\u"})
    for r in builtin.rules:
        c = wctx if "windows" in r.os else ctx
        for pat in r.paths:
            exp = c.expand(pat)
            if exp and not any(ch in exp for ch in "*?["):
                if r.mode in ("tree", "contents") or r.id not in ("tmp-children", "vartmp-children", "app-cache-children"):
                    assert not R.forbidden_root(exp, c), (r.id, exp)


def test_tmp_rule_protects_runtime_dirs(builtin):
    r = next(x for x in builtin.rules if x.id == "tmp-children")
    for must in (".X11-unix", ".ICE-unix", "systemd-private-*", "ssh-*", "tmux-*", ".mount_*"):
        assert must in r.skip_names


# ── context / expansion ──────────────────────────────────────────────────────
def test_expand_linux(tmp_path):
    c = lctx(tmp_path, XDG_CACHE_HOME=str(tmp_path / "xc"))
    assert c.expand("~/a") == f"{tmp_path}/a"
    assert c.expand("$XDG_CACHE_HOME/b") == f"{tmp_path}/xc/b"
    assert c.expand("${XDG_DATA_HOME}/c") == f"{tmp_path}/.local/share/c"
    assert c.expand("$NOPE/x") is None
    assert c.expand("relative/x") is None
    assert lctx(tmp_path).expand("$XDG_CACHE_HOME") == f"{tmp_path}/.cache"


def test_expand_windows():
    c = R.RuleContext(os_name="windows", home="C:\\Users\\u", env={"LOCALAPPDATA": "C:\\Users\\u\\AppData\\Local"})
    assert c.expand("%LOCALAPPDATA%\\x/y") == "C:\\Users\\u\\AppData\\Local\\x\\y"
    assert c.expand("%APPDATA%\\x") is None


def test_tilde_and_os_filters(tmp_path):
    c = lctx(tmp_path)
    assert c.tilde(f"{tmp_path}/a/b") == "~/a/b"
    assert c.os_ok(("linux",)) and not c.os_ok(("windows",))


# ── Chromium / Electron ──────────────────────────────────────────────────────
def make_chrome(home, cfg=".config/google-chrome", profiles=("Default", "Profile 1")):
    base = home / cfg
    spec = {"Local State": 10}
    for p in profiles:
        spec.update({f"{p}/Cache/Cache_Data/f_001": 5000, f"{p}/Code Cache/js/a": 300,
                     f"{p}/GPUCache/data_0": 100, f"{p}/Service Worker/CacheStorage/x/y": 70,
                     f"{p}/Service Worker/Database/CURRENT": 20,
                     f"{p}/Cookies": 40, f"{p}/Login Data": 41, f"{p}/History": 42,
                     f"{p}/Local Storage/leveldb/000003.log": 50, f"{p}/IndexedDB/https_x/1.blob": 60,
                     f"{p}/Preferences": 12})
    return tree(base, spec)


def test_chromium_cleans_all_profiles_but_never_user_data(builtin, tmp_path):
    chrome = make_chrome(tmp_path)
    ctx = lctx(tmp_path)
    pl = plan_for(builtin, ctx, "chromium_cache")
    # A9: Service Worker/CacheStorage is moved to Review (dev_cache), so AUTO chromium_cache has 3 subpaths × 2 profiles = 6
    assert len(pl.deletable) == 6
    res = E.execute_plan(pl.deletable, guards=FakeGuards())
    assert res.freed == 2 * (5000 + 300 + 100)
    for prof in ("Default", "Profile 1"):
        assert not (chrome / prof / "Cache").exists()
        assert not (chrome / prof / "Code Cache").exists()
        assert not (chrome / prof / "GPUCache").exists()
        assert (chrome / prof / "Service Worker" / "CacheStorage" / "x" / "y").exists()
        for keep in ("Cookies", "Login Data", "History", "Preferences",
                     "Local Storage/leveldb/000003.log", "IndexedDB/https_x/1.blob",
                     "Service Worker/Database/CURRENT"):
            assert (chrome / prof / keep).exists(), keep
    assert (chrome / "Local State").exists()
    # Service Worker/CacheStorage is available under Review target (dev_cache) with medium risk
    rev_pl = plan_for(builtin, ctx, "dev_cache")
    sw_items = [i for i in rev_pl.deletable if "CacheStorage" in i.path]
    assert len(sw_items) == 2 and all(i.risk == "medium" for i in sw_items)


def test_chromium_electron_apps_discovered_by_fingerprint(builtin, tmp_path):
    code = tree(tmp_path / ".config/Code", {"Cache/Cache_Data/a": 1000, "Code Cache/js/b": 200,
                                            "GPUCache/c": 30, "Local Storage/leveldb/x": 5, "Cookies": 4,
                                            "User/settings.json": 77, "User/globalStorage/state.vscdb": 99})
    foo = tree(tmp_path / ".config/foo", {"Cache/important.db": 500, "config.ini": 3})   # KHÔNG phải Chromium
    pl = plan_for(builtin, lctx(tmp_path), "chromium_cache")
    paths = {i.path for i in pl.deletable}
    assert str(code / "Cache") in paths and str(code / "Code Cache") in paths
    assert str(foo / "Cache") not in paths, "thư mục 'Cache' của app không phải Chromium bị đưa vào plan!"
    E.execute_plan(pl.deletable, guards=FakeGuards())
    assert (code / "User/settings.json").exists() and (code / "User/globalStorage/state.vscdb").exists()
    assert (foo / "Cache/important.db").exists()


def test_chromium_cache_tree_structure_and_running_via_config_lock(builtin, tmp_path):
    cache = tree(tmp_path / ".cache/google-chrome", {"Default/Cache/Cache_Data/a": 900, "Default/GPUCache/b": 10})
    cfg = tree(tmp_path / ".config/google-chrome", {"Local State": 5, "Default/Preferences": 5})
    (cfg / "SingletonLock").symlink_to(f"host-{os.getpid()}")          # Chrome đang chạy
    pl = plan_for(builtin, lctx(tmp_path), "chromium_cache")
    mine = [i for i in pl.items if i.path.startswith(str(cache))]
    assert mine and all(i.blocked and "running" in i.blocked for i in mine)
    assert not [i for i in pl.deletable if i.path.startswith(str(cache))]
    res = E.execute_plan(pl.items, guards=FakeGuards())
    assert (cache / "Default/Cache/Cache_Data/a").exists()
    assert any("running" in r for _, r in res.skipped)
    (cfg / "SingletonLock").unlink()                                      # đã tắt
    pl2 = plan_for(builtin, lctx(tmp_path), "chromium_cache")
    assert [i for i in pl2.deletable if i.path.startswith(str(cache))]


def test_chromium_running_detected_by_user_data_dir_arg(builtin, tmp_path):
    code = tree(tmp_path / ".config/discord", {"Local Storage/x": 1, "Cache/a": 500})
    g = FakeGuards(udd=[str(code)])
    pl = plan_for(builtin, lctx(tmp_path), "chromium_cache", guards=g)
    assert pl.items and all(i.blocked for i in pl.items) and not pl.deletable
    assert any("running" in n for n in pl.notes)


def test_chromium_flatpak_and_snap_locations(builtin, tmp_path):
    fp = tree(tmp_path / ".var/app/com.google.Chrome/config/google-chrome", {"Local State": 4, "Default/Cache/a": 800})
    fc = tree(tmp_path / ".var/app/com.google.Chrome/cache/google-chrome", {"Default/Cache/b": 700})
    sn = tree(tmp_path / "snap/chromium/common/chromium", {"Local State": 4, "Default/GPUCache/c": 60})
    paths = {i.path for i in plan_for(builtin, lctx(tmp_path), "chromium_cache").deletable}
    assert str(fp / "Default/Cache") in paths and str(fc / "Default/Cache") in paths
    assert str(sn / "Default/GPUCache") in paths


def test_chromium_scheduled_mode_only_touches_abandoned_caches(builtin, tmp_path):
    used = tree(tmp_path / ".config/google-chrome", {"Local State": 4, "Default/Cache/a": 800}, days=1)
    stale = tree(tmp_path / ".config/BraveSoftware/Brave-Browser", {"Local State": 4, "Default/Cache/a": 600}, days=40)
    ctx = lctx(tmp_path)
    manual = {i.path for i in plan_for(builtin, ctx, "chromium_cache").deletable}
    sched = {i.path for i in plan_for(builtin, ctx, "chromium_cache", unattended=True).deletable}
    assert str(used / "Default/Cache") in manual
    assert str(used / "Default/Cache") not in sched
    assert str(stale / "Default/Cache") in sched


def test_chromium_symlinked_cache_dir_is_never_followed(builtin, tmp_path):
    victim = tree(tmp_path / "precious", {"doc.txt": 123})
    base = tree(tmp_path / ".config/chromium", {"Local State": 4, "Default/Preferences": 1})
    (base / "Default" / "Cache").symlink_to(victim)
    pl = plan_for(builtin, lctx(tmp_path), "chromium_cache")
    E.execute_plan(pl.deletable, guards=FakeGuards())
    assert (victim / "doc.txt").exists()


# ── Firefox ──────────────────────────────────────────────────────────────────
def test_firefox_cache_only(builtin, tmp_path):
    cache = tree(tmp_path / ".cache/mozilla/firefox/abc.default", {"cache2/entries/a": 400, "startupCache/b": 50})
    prof = tree(tmp_path / ".mozilla/firefox/abc.default", {"cookies.sqlite": 100, "places.sqlite": 200, "key4.db": 9})
    pl = plan_for(builtin, lctx(tmp_path), "firefox_cache")
    assert {Path(i.path).name for i in pl.deletable} == {"cache2", "startupCache"}
    E.execute_plan(pl.deletable, guards=FakeGuards())
    assert not (cache / "cache2").exists()
    assert all((prof / n).exists() for n in ("cookies.sqlite", "places.sqlite", "key4.db"))


def test_firefox_running_blocks(builtin, tmp_path):
    tree(tmp_path / ".cache/mozilla/firefox/p", {"cache2/a": 400})
    pl = plan_for(builtin, lctx(tmp_path), "firefox_cache", guards=FakeGuards(procs=["firefox"]))
    assert pl.items and not pl.deletable
    assert (tmp_path / ".cache/mozilla/firefox/p/cache2/a").exists()


def test_firefox_snap_and_flatpak_paths(builtin, tmp_path):
    tree(tmp_path / "snap/firefox/common/.cache/mozilla/firefox/p1", {"cache2/a": 400})
    tree(tmp_path / ".var/app/org.mozilla.firefox/cache/mozilla/firefox/p2", {"cache2/a": 400})
    assert len(plan_for(builtin, lctx(tmp_path), "firefox_cache").deletable) == 2


# ── thumbnails / pip / aur ───────────────────────────────────────────────────
def test_thumbnails_manual_vs_scheduled(builtin, tmp_path):
    t = tmp_path / ".cache/thumbnails"
    tree(t, {"normal/old.png": 100, "large/new.png": 50}, days=40)
    age(t / "large/new.png", 3)
    ctx = lctx(tmp_path)
    manual = plan_for(builtin, ctx, "thumbnails")
    sched = plan_for(builtin, ctx, "thumbnails", unattended=True)
    assert manual.total_files == 2          # thủ công: mọi thumbnail (đã > 10 phút)
    assert sched.total_files == 1           # chạy nền: chỉ cái ≥ 30 ngày


def test_aur_cache_keeps_vcs_json_and_blocks_when_building(builtin, tmp_path):
    y = tree(tmp_path / ".cache/yay", {"foo/PKGBUILD": 10, "foo/src/a.tar": 5000, "vcs.json": 20, "bar-git/x": 40})
    ctx = lctx(tmp_path)
    blocked = plan_for(builtin, ctx, "aur_cache", guards=FakeGuards(procs=["makepkg"]))
    assert not blocked.deletable and (y / "foo").exists()
    ok = plan_for(builtin, ctx, "aur_cache")
    assert len(ok.deletable) == 1
    res = E.execute_plan(ok.deletable, guards=FakeGuards())
    assert (y / "vcs.json").exists() and not (y / "foo").exists() and not (y / "bar-git").exists()
    assert res.freed == 5010 + 40


def test_pip_cache_closed_when_pip_running(builtin, tmp_path):
    tree(tmp_path / ".cache/pip", {"http/a": 100})
    ctx = lctx(tmp_path)
    assert plan_for(builtin, ctx, "pip_cache").deletable
    assert not plan_for(builtin, ctx, "pip_cache", guards=FakeGuards(procs=["pip"])).deletable


# ── tmp ──────────────────────────────────────────────────────────────────────
def _tmp_rule(builtin, root):
    rs = R.RuleSet()
    rs.targets = builtin.targets
    r = next(x for x in builtin.rules if x.id == "tmp-children")
    rs.rules = [dataclasses.replace(r, paths=(str(root),))]
    return rs


def test_tmp_cleaning_is_safe_for_live_runtime_state(builtin, tmp_path):
    t = tmp_path / "tmp"
    t.mkdir()
    x11 = tree(t / ".X11-unix", {})
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(x11 / "X0"))
    age(x11, 30)
    tmux = tree(t / "tmux-1000", {})
    s2 = socket.socket(socket.AF_UNIX)
    s2.bind(str(tmux / "default"))
    age(tmux, 30)
    ssh = tree(t / "ssh-XXXabc", {})
    s3 = socket.socket(socket.AF_UNIX)
    s3.bind(str(ssh / "agent.123"))
    age(ssh, 30)
    build = tree(t / "build-xyz", {"obj/deep/a.o": 10}, days=30)
    (build / "obj/deep/fresh.o").write_bytes(b"just written")              # build đang chạy
    junk = tree(t / "old-junk", {"a.txt": 1000, "sub/b": 200}, days=30)
    oldfile = t / "stale.log"
    oldfile.write_bytes(b"z" * 40)
    age(oldfile, 30)
    newfile = t / "fresh.tmp"
    newfile.write_bytes(b"y")
    inuse = tree(t / "open-dir", {"db.sqlite": 100}, days=30)
    rs = _tmp_rule(builtin, t)
    g = FakeGuards(open_paths=[str(inuse / "db.sqlite")])
    try:
        pl = rs.plan("tmp_files", lctx(tmp_path), guards=g)
        deletable = {Path(i.path).name for i in pl.deletable}
        assert deletable == {"old-junk", "stale.log"}, deletable
        E.execute_plan(pl.deletable, guards=g)
    finally:
        s.close(); s2.close(); s3.close()
    for keep in (x11, tmux, ssh, build, newfile, inuse):
        assert keep.exists(), keep
    assert not junk.exists() and not oldfile.exists()


def test_tmp_ram_backed_is_skipped_with_note(builtin, tmp_path, monkeypatch):
    t = tmp_path / "tmp"
    tree(t / "old", {"a": 10}, days=30)
    monkeypatch.setattr(E, "is_ram_backed", lambda p: True)
    pl = _tmp_rule(builtin, t).plan("tmp_files", lctx(tmp_path), guards=FakeGuards())
    assert not pl.items and any("RAM-backed" in n for n in pl.notes)


# ── app_cache (Review) ───────────────────────────────────────────────────────
def test_app_cache_lists_unknown_dirs_only(builtin, tmp_path):
    c = tmp_path / ".cache"
    tree(c / "someapp", {"x": 1000}, days=40)
    tree(c / "recent-app", {"x": 1000}, days=2)                      # < 14 ngày → không liệt kê
    tree(c / "mesa_shader_cache", {"x": 1000}, days=40)              # bảo vệ
    tree(c / "fontconfig", {"x": 10}, days=40)
    tree(c / "borg", {"idx": 99999}, days=40)                        # cache khó dựng lại
    tree(c / "google-chrome", {"Default/Cache/a": 10}, days=40)      # đã thuộc chromium_cache
    tree(c / "yay", {"x": 10}, days=40)                              # đã thuộc aur_cache
    tree(c / "Cypress", {"x": 10}, days=40)                          # đã thuộc dev_cache
    pl = plan_for(builtin, lctx(tmp_path), "app_cache")
    assert [Path(i.path).name for i in pl.deletable] == ["someapp"]
    assert all(i.risk == "medium" for i in pl.items)


def test_user_cache_regression_dev_caches_not_deleted_by_safe_tier(builtin, tmp_path):
    """Báo cáo: user_cache (tier safe) xóa go-build, yarn, Cypress, JetBrains, node-gyp, playwright."""
    c = tmp_path / ".cache"
    for n in ("go-build", "yarn", "Cypress", "JetBrains", "node-gyp", "ms-playwright", "unknown-app"):
        tree(c / n, {"x": 1000}, days=60)
    ctx = lctx(tmp_path)
    for tid in ("chromium_cache", "firefox_cache", "thumbnails", "pip_cache", "tmp_files", "crash_reports"):
        auto_paths = {i.path for i in plan_for(builtin, ctx, tid).deletable}
        assert not [p for p in auto_paths if p.startswith(str(c))], (tid, auto_paths)


def test_dev_cache_items_per_toolchain_with_risk(builtin, tmp_path):
    tree(tmp_path / ".m2/repository", {"com/foo/1.0/foo.jar": 3000})
    tree(tmp_path / ".cache/go-build", {"aa/x": 100})
    tree(tmp_path / ".npm/_cacache", {"content-v2/a": 50})
    pl = plan_for(builtin, lctx(tmp_path), "dev_cache")
    by = {Path(i.path).name: i for i in pl.deletable}
    assert by["repository"].risk == "high" and "mvn install" in by["repository"].note
    assert by["go-build"].risk == "low" and "_cacache" in by


def test_go_modcache_readonly_is_really_removed(builtin, tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root bỏ qua quyền ghi")
    m = tree(tmp_path / "go/pkg/mod/cache", {"download/x/@v/v1.zip": 500, "download/y/@v/v2.zip": 500})
    for p in sorted(m.rglob("*"), key=lambda q: -len(q.parts)):
        p.chmod(0o444 if p.is_file() else 0o555)
    pl = plan_for(builtin, lctx(tmp_path), "dev_cache")
    res = E.execute_plan(pl.deletable, guards=FakeGuards())
    assert res.freed == 1000 and not any(m.rglob("*.zip"))


# ── dọn xong → đo thật khớp báo cáo ─────────────────────────────────────────
def test_dry_run_equals_real_run(builtin, tmp_path):
    make_chrome(tmp_path)
    tree(tmp_path / ".cache/thumbnails", {"normal/a.png": 300}, days=40)
    ctx = lctx(tmp_path)
    for tid in ("chromium_cache", "thumbnails"):
        pl = plan_for(builtin, ctx, tid)
        dry = E.execute_plan(pl.deletable, dry=True, guards=FakeGuards())
        real = E.execute_plan(pl.deletable, guards=FakeGuards())
        assert dry.freed == real.freed > 0 and dry.removed == real.removed


# ── luật người dùng ──────────────────────────────────────────────────────────
USER_OK = '''
schema = 1
[[target]]
id = "my_stuff"
name = "My stuff"
tier = "auto"
[[rule]]
id = "my-rule"
target = "my_stuff"
mode = "children"
paths = ["~/.cache/myapp"]
'''


def user_set(builtin, text):
    rs = R.RuleSet()
    rs.targets = {k: list(v) for k, v in builtin.targets.items()}
    rs.rules = list(builtin.rules)
    rs.load_text(text, "user", "user.toml")
    return rs


def test_user_rules_are_forced_to_review_tier(builtin):
    rs = user_set(builtin, USER_OK)
    t = rs.targets["my_stuff"][0]
    assert t.tier == "review" and not t.scheduled and t.safety == "caution"


@pytest.mark.parametrize("bad_path", ["/etc", "/home/other/x", "~/../../etc", "~/a/../../b", "C:\\Windows"])
def test_user_rules_reject_paths_outside_home(builtin, bad_path):
    with pytest.raises(R.RuleError):
        user_set(builtin, USER_OK.replace("~/.cache/myapp", bad_path))


@pytest.mark.parametrize("patch", [
    ('mode = "children"', 'mode = "contents"'),
    ('mode = "children"', 'mode = "old_files"'),
    ('target = "my_stuff"', 'kind = "chromium"\ntarget = "my_stuff"'),
])
def test_user_rules_restricted_modes_and_kinds(builtin, patch):
    with pytest.raises(R.RuleError):
        user_set(builtin, USER_OK.replace(*patch))


def test_user_rules_cannot_redefine_builtin_target(builtin):
    with pytest.raises(R.RuleError):
        user_set(builtin, USER_OK.replace("my_stuff", "dev_cache"))


def test_invalid_rule_files_are_rejected_cleanly(builtin):
    rs = R.RuleSet()
    for bad in ("schema = 2", "schema = 1\n[[target]]\nid = 'A B'", "schema = 1\n[[rule]]\nid='x'\ntarget='y'\nmode='nuke'\npaths=['~/x']",
                "schema = 1\n[[rule]]\nid='x'\ntarget='y'\npaths=['~/../x']",
                "schema = 1\n[[rule]]\nid='x'\ntarget='y'\npaths=['~/x']\nmin_age_days=-1",
                "schema = 1\n[[rule]]\nid='x'\ntarget='y'\npaths=['~/x']\nsurprise=1", "not toml ["):
        with pytest.raises(R.RuleError):
            rs.load_text(bad)


def test_auto_target_must_be_safe():
    with pytest.raises(R.RuleError):
        R.RuleSet().load_text('schema = 1\n[[target]]\nid="x"\ntier="auto"\nsafety="caution"\n')


def test_broken_user_file_does_not_break_app(tmp_path):
    f = tmp_path / "bad.toml"
    f.write_text("this is not toml [")
    rs = R.RuleSet()
    rs.load_file(f, "user")
    assert rs.errors and not rs.rules


def test_user_rule_executes_only_inside_home(builtin, tmp_path):
    tree(tmp_path / ".cache/myapp/old", {"a": 100}, days=30)
    tree(tmp_path / ".cache/myapp/new", {"a": 100}, days=0)
    rs = user_set(builtin, USER_OK)
    pl = rs.plan("my_stuff", lctx(tmp_path), guards=FakeGuards())
    assert [Path(i.path).name for i in pl.deletable] == ["old"]
