"""Harness dry-run theo distro: chạy ngay trên máy hiện tại (bên trong container thì nó là distro đó)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_harness_runs_clean_and_dry_run_touches_nothing(tmp_path):
    home = tmp_path / "home"
    (home / ".cache/thumbnails/normal").mkdir(parents=True)
    f = home / ".cache/thumbnails/normal/a.png"
    f.write_bytes(b"x" * 100)
    old = 1_600_000_000
    os.utime(f, (old, old))
    cfg = home / ".config/google-chrome"
    (cfg / "Default/Cache").mkdir(parents=True)
    (cfg / "Local State").write_text("{}")
    (cfg / "Default/Cache/a").write_bytes(b"y" * 50)
    for q in ((cfg / "Default/Cache/a"), (cfg / "Default/Cache"), cfg / "Default", cfg):
        os.utime(q, (old, old))                 # tệp vừa tạo < 10 phút luôn bị engine bỏ qua
    env = {**os.environ, "HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run([sys.executable, str(ROOT / "tests/containers/dryrun_harness.py"), "--home", str(home)],
                       capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads(r.stdout)
    assert rep["errors"] == [] and rep["rules_error"] == ""
    tiers = {t["id"]: t for t in rep["targets"]}
    assert tiers["thumbnails"]["freed"] == 100 and tiers["chromium_cache"]["freed"] == 50
    assert f.exists() and (cfg / "Default/Cache/a").exists(), "dry-run đã thay đổi đĩa!"
    review = [t for t in rep["targets"] if t["tier"] == "review"]
    assert review and all(t.get("nothing_preticked") for t in review)


def test_harness_flags_wrong_package_manager(tmp_path):
    env = {**os.environ, "HOME": str(tmp_path), "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run([sys.executable, str(ROOT / "tests/containers/dryrun_harness.py"), "--expect-pm", "definitely-not",
                        "--home", str(tmp_path)], capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 1 and "expected package manager" in r.stdout
