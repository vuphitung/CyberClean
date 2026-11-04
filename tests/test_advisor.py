import ast
import os
import sys
import time
from pathlib import Path

import pytest

from core import advisor as A
from tests.helpers import age, tree

MB = 1024 ** 2


@pytest.fixture(autouse=True)
def isolate_windows_system_collectors(monkeypatch):
    # These tests describe their temporary home only. Native system inventory
    # has its own tests and must not add the real machine's findings here.
    if sys.platform == 'win32':
        monkeypatch.setattr(A, 'collect_windows', lambda *args: [])
        monkeypatch.setattr(A, 'collect_wsl_docker_desktop', lambda *args: [])


def big(path: Path, mb: int, days=10):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.truncate(mb * MB)
    age(path, days)
    return path


def test_advisor_module_is_read_only_by_construction():
    """Advisor KHÔNG được xóa/ghi gì: không import shutil.rmtree/os.remove/unlink... và không gọi chúng."""
    src = Path(A.__file__).read_text(encoding='utf-8')
    tree_ = ast.parse(src)
    banned_anywhere = {"unlink", "rmdir", "rmtree", "removedirs", "write_text", "write_bytes", "truncate",
                       "chmod", "chown", "symlink_to", "hardlink_to", "mkdir", "makedirs", "remove_path",
                       "system", "popen", "touch", "utime"}
    banned_on_modules = {"remove", "rename", "replace", "link", "symlink", "copy", "copy2", "copyfile", "move"}
    for node in ast.walk(tree_):
        if isinstance(node, ast.Attribute):
            if node.attr in banned_anywhere:
                pytest.fail(f"advisor.py uses .{node.attr} on line {node.lineno}")
            if (node.attr in banned_on_modules and isinstance(node.value, ast.Name)
                    and node.value.id in ("os", "shutil", "E", "engine")):
                pytest.fail(f"advisor.py uses {node.value.id}.{node.attr} on line {node.lineno}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("open",):
            modes = [a for a in node.args[1:2]] + [k.value for k in node.keywords if k.arg == "mode"]
            for m in modes:
                if isinstance(m, ast.Constant) and any(c in str(m.value) for c in "wax+"):
                    pytest.fail(f"advisor.py opens a file for writing on line {node.lineno}")
    assert "PyQt" not in src


def test_human():
    assert A.human(0) == "0 B" and A.human(1536) == "1.5 KB" and A.human(5 * 1024**3) == "5.0 GB"


def test_big_files_classified(tmp_path):
    home = tmp_path
    big(home / "VMs/win10.qcow2", 600)
    big(home / "Downloads/ubuntu.iso", 700)
    big(home / ".local/share/Steam/steamapps/common/Game/data.pak", 650)
    big(home / "Videos/movie.mkv", 800)
    big(home / "small.bin", 1)
    rep = A.scan(str(home), seconds=30, big_min_mb=500)
    cats = {f.title: f.category for f in rep.findings}
    assert cats["win10.qcow2"] == "vm" and cats["ubuntu.iso"] == "vm"
    assert cats["data.pak"] == "games" and cats["movie.mkv"] == "large"
    assert "small.bin" not in cats
    vm = next(f for f in rep.findings if f.title == "win10.qcow2")
    assert vm.size == 600 * MB and vm.age_days == 10 and vm.open_path.endswith("VMs")


@pytest.mark.skipif(sys.platform == 'win32', reason='Linux .cache exclusion and Unix symlink fixture')
def test_walker_never_follows_symlinks_or_crosses_into_cache(tmp_path):
    outside = tmp_path / "outside"
    big(outside / "huge.bin", 900)
    home = tmp_path / "home"
    home.mkdir()
    (home / "link").symlink_to(outside)
    big(home / ".cache/thing/blob.bin", 900)
    rep = A.scan(str(home), seconds=20, big_min_mb=500)
    assert not [f for f in rep.findings if f.title in ("huge.bin", "blob.bin")]


def test_project_artifacts_only_old_and_big(tmp_path):
    home = tmp_path
    old = home / "code/oldapp"
    big(old / "node_modules/pkg/lib.bin", 120)
    (old / "package.json").write_text("{}")
    age(old / "package.json", 200)
    age(old, 200)
    active = home / "code/active"
    big(active / "node_modules/pkg/lib.bin", 120)
    (active / "package.json").write_text("{}")                                # vừa sửa → dự án còn sống
    rust = home / "code/oldrust"
    big(rust / "target/debug/app", 90)
    (rust / "Cargo.toml").write_text("[package]")
    age(rust / "Cargo.toml", 120)
    venv = home / "code/oldpy"
    big(venv / ".venv/lib/x.so", 80)
    (venv / ".venv/pyvenv.cfg").write_text("home = /usr")
    (venv / "main.py").write_text("print(1)")
    age(venv / "main.py", 90)
    tiny = home / "code/tiny"
    big(tiny / "node_modules/a.bin", 1)
    age(tiny, 300)
    rep = A.scan(str(home), seconds=30)
    proj = {Path(f.path).parts[-2]: f for f in rep.findings if f.category == "projects"}
    assert set(proj) == {"oldapp", "oldrust", "oldpy"}
    assert "rebuilds" in proj["oldapp"].advice or "npm" in proj["oldapp"].advice
    assert proj["oldapp"].age_days >= 199


def test_downloads_summary_and_hints(tmp_path):
    d = tmp_path / "Downloads"
    big(d / "setup.exe", 120, days=200)
    big(d / "backup.zip", 90, days=5)
    big(d / "tiny.txt", 0, days=300)
    rep = A.scan(str(tmp_path), seconds=20, big_min_mb=5000)
    dl = [f for f in rep.findings if f.category == "downloads"]
    summary = dl[0]
    assert "3 items" in summary.title and "older than 90 days" in summary.advice
    by = {f.title: f for f in dl[1:]}
    assert "installer" in by["setup.exe"].advice and "archive" in by["backup.zip"].advice


def test_xdg_download_dir_is_respected(tmp_path, monkeypatch):
    monkeypatch.setattr(A, 'IS_WINDOWS', False)
    (tmp_path / ".config").mkdir()
    (tmp_path / ".config/user-dirs.dirs").write_text('XDG_DOWNLOAD_DIR="$HOME/Telechargements"\n')
    big(tmp_path / "Telechargements/x.iso", 60)
    rep = A.scan(str(tmp_path), seconds=20, big_min_mb=5000)
    assert any(f.category == "downloads" and "Telechargements" in f.path for f in rep.findings)


def test_time_budget_and_cancel_give_partial_report(tmp_path):
    for i in range(300):
        (tmp_path / f"d{i}").mkdir()
        (tmp_path / f"d{i}" / "f").write_bytes(b"x")
    start = time.monotonic()
    rep = A.scan(str(tmp_path), seconds=0.0001)
    assert rep.truncated and time.monotonic() - start < 5
    rep2 = A.scan(str(tmp_path), seconds=30, stop=lambda: True)
    assert rep2.truncated


def test_collector_failure_does_not_break_report(tmp_path, monkeypatch):
    collector = 'collect_windows' if A.IS_WINDOWS else 'collect_opt'
    monkeypatch.setattr(A, collector, lambda *args: (_ for _ in ()).throw(RuntimeError("boom")))
    rep = A.scan(str(tmp_path), seconds=20)
    assert any("boom" in n for n in rep.notes)


def test_report_grouping_and_total(tmp_path):
    big(tmp_path / "a.qcow2", 600)
    big(tmp_path / "b.mkv", 700)
    rep = A.scan(str(tmp_path), seconds=20)
    groups = rep.by_category()
    order = list(groups)
    assert order.index("vm") < order.index("large")
    assert rep.total >= 1300 * MB


def test_collect_heavy_packages_parsers(monkeypatch):
    monkeypatch.setattr(A, "_run", lambda argv, timeout=25: "libfoo 300000\nsmall 100\n" if argv[0] == "dpkg-query" else "")
    got = A.collect_heavy_packages("apt")
    assert [f.title for f in got] == ["libfoo"] and got[0].size == 300000 * 1024
    pacman_out = "Name            : big\nInstalled Size  : 1.50 GiB\n\nName            : tiny\nInstalled Size  : 5.00 MiB\n"
    monkeypatch.setattr(A, "_run", lambda argv, timeout=25: pacman_out)
    got = A.collect_heavy_packages("pacman")
    assert [f.title for f in got] == ["big"] and got[0].size == int(1.5 * 1024**3)
