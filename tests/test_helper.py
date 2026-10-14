"""
Test cho packaging/cyber-clean-helper.

Helper chạy bằng root nên mọi hành vi "từ chối" đều phải được kiểm chứng.
Test chạy helper THẬT (bash) trong một cây thư mục giả: các hằng số đường dẫn
được thay bằng sed trên một bản sao, lệnh hệ thống (pacman, apt-get, snap...)
được thay bằng script ghi lại tham số. Cần chạy bằng root (chown/trusted_dir) —
test tự skip nếu không phải root.
"""
import base64
import os
import re
import shutil
import stat
import subprocess
import tarfile
import textwrap
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HELPER_SRC = ROOT / "packaging" / "cyber-clean-helper"

pytestmark = pytest.mark.skipif(os.geteuid() != 0, reason="helper tests need root")


# ── fixture: một "hệ thống" giả ──────────────────────────────────────────────
class Box:
    def __init__(self, base: Path):
        self.base = base
        self.log = base / "var/log"
        self.crash = base / "var/crash"
        self.core = base / "var/lib/systemd/coredump"
        self.pacman_cache = base / "var/cache/pacman/pkg"
        self.pacman_lock = base / "var/lib/pacman/db.lck"
        self.opt = base / "opt/CyberClean"
        self.app = self.opt / "CyberClean"
        self.etc = base / "etc"
        self.bin = base / "bin"
        self.calls = base / "calls.log"
        self.install_path = base / "usr/local/bin/cyber-clean-helper"
        self.sudoers_dir = base / "etc/sudoers.d"
        self.helper = base / "helper.sh"
        for d in (self.log, self.core, self.pacman_cache, self.pacman_lock.parent,
                  self.opt, self.etc, self.bin, self.install_path.parent):
            d.mkdir(parents=True, exist_ok=True)
            d.chmod(0o755)
        self.crash.mkdir(parents=True, exist_ok=True)
        self.crash.chmod(0o1777)
        self.orphans = base / "orphans.txt"
        self.orphans.write_text("")
        self._fake_cmds()

    def _fake_cmds(self):
        rec = f'echo "$(basename "$0") $*" >> {self.calls}'
        for name in ("apt-get", "dnf", "zypper", "snap", "journalctl", "fstrim"):
            self._script(name, rec)
        self._script("pacman", textwrap.dedent(f'''
            if [[ "$1" == "-Qdtq" ]]; then cat {self.orphans}; exit 0; fi
            {rec}
        '''))
        self._script("paccache", rec)
        # getent giả: đọc "CSDL" nhóm/người dùng của bài test (mặc định rỗng → mọi nhóm đều "không biết")
        self.groups, self.passwd = self.base / "groups.txt", self.base / "passwd.txt"
        self.groups.write_text("")
        self.passwd.write_text("")
        self._script("getent", textwrap.dedent(f'''
            db="$1"; key="${{2:-}}"
            case "$db" in
              group)  f={self.groups}; col=3 ;;
              passwd) f={self.passwd}; col=1 ;;
              *) exit 2 ;;
            esac
            if [[ -z "$key" ]]; then cat "$f"; exit 0; fi
            out=$(awk -F: -v k="$key" -v c="$col" '$c == k' "$f")
            [[ -n "$out" ]] && {{ echo "$out"; exit 0; }}
            if [[ "$db" == passwd ]]; then out=$(awk -F: -v k="$key" '$1 == k' "$f"); [[ -n "$out" ]] && {{ echo "$out"; exit 0; }}; fi
            exit 2
        '''))

    def _script(self, name, body):
        p = self.bin / name
        p.write_text("#!/bin/bash\n" + body + "\n")
        p.chmod(0o755)

    def build_helper(self, pubkey_pem: str | None = None) -> Path:
        s = HELPER_SRC.read_text()
        rep = {
            r"^LOG_ROOT=.*": f"LOG_ROOT={self.log}",
            r"^CRASH_ROOT=.*": f"CRASH_ROOT={self.crash}",
            r"^COREDUMP_ROOT=.*": f"COREDUMP_ROOT={self.core}",
            r"^PACMAN_LOCK=.*": f"PACMAN_LOCK={self.pacman_lock}",
            r"^PACMAN_CACHE_DEFAULT=.*": f"PACMAN_CACHE_DEFAULT={self.pacman_cache}",
            r"^APP_PARENT=.*": f"APP_PARENT={self.opt}",
            r"^APP_DIR=.*": f"APP_DIR={self.app}",
            r"^HELPER_INSTALL_PATH=.*": f"HELPER_INSTALL_PATH={self.install_path}",
            r"^SUDOERS_DIR=.*": f"SUDOERS_DIR={self.sudoers_dir}",
            r"^SUDOERS_FILE=.*": f"SUDOERS_FILE={self.sudoers_dir}/cyberclean",
            r"^PATH=.*": f"PATH={self.bin}:/usr/sbin:/usr/bin:/sbin:/bin",
        }
        for pat, val in rep.items():
            s, n = re.subn(pat, val, s, count=1, flags=re.M)
            assert n == 1, f"constant not found: {pat}"
        if pubkey_pem:
            s, n = re.subn(r"-----BEGIN PUBLIC KEY-----.*?-----END PUBLIC KEY-----",
                           pubkey_pem.strip(), s, count=1, flags=re.S)
            assert n == 1
        self.helper.write_text(s)
        self.helper.chmod(0o755)
        return self.helper

    def run(self, *args, stdin: str = "", env_extra=None):
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(self.base)}
        env.update(env_extra or {})
        return subprocess.run([str(self.helper), *args], input=stdin, text=True,
                              capture_output=True, env=env, timeout=60)

    def calls_text(self) -> str:
        return self.calls.read_text() if self.calls.exists() else ""


@pytest.fixture()
def box(tmp_path):
    b = Box(tmp_path)
    b.build_helper()
    return b


def feed(*lines) -> str:
    """stdin cho helper: mỗi đường dẫn một dòng, KẾT THÚC bằng newline (như app thật gửi)."""
    return "\n".join(map(str, lines)) + "\n"


def counts(r) -> dict:
    return dict(re.findall(r"(\w+)=(\d+)", r.stdout))


def old(path: Path, hours=24 * 30):
    t = time.time() - hours * 3600
    os.utime(path, (t, t), follow_symlinks=False)


# ── basic ────────────────────────────────────────────────────────────────────
def test_ping(box):
    r = box.run("ping")
    assert r.returncode == 0 and "protocol=2" in r.stdout


def test_unknown_and_missing_action(box):
    assert box.run("rm", "-rf", "/").returncode == 2
    assert box.run().returncode == 2


def test_removed_dangerous_actions_are_gone(box):
    for act in ("update-replace", "stop-service", "drop-cache", "one-click-fix"):
        r = box.run(act, "a", "b", "c")
        assert r.returncode == 2, act
        assert "unknown action" in r.stderr


def test_extra_args_rejected_for_simple_actions(box):
    assert box.run("paccache", "--evil").returncode == 2
    assert box.run("fstrim", "-a").returncode == 2


# ── clean-rotated-logs ───────────────────────────────────────────────────────
def mk(p: Path, content="x", age_h=24 * 30):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    old(p, age_h)
    return p


def test_rotated_logs_deletes_only_valid(box):
    good = [mk(box.log / "syslog.1"), mk(box.log / "kern.log.2.gz"),
            mk(box.log / "sub" / "app.log.old")]
    (box.log / "sub").chmod(0o755)
    keep_active = mk(box.log / "syslog")
    keep_recent = mk(box.log / "fresh.log.1", age_h=0)
    r = box.run("clean-rotated-logs", stdin=feed(*good, keep_active, keep_recent))
    assert r.returncode == 0, r.stderr
    assert all(not g.exists() for g in good)
    assert keep_active.exists() and keep_recent.exists()
    assert counts(r) == {"removed": "3", "skipped": "2"}


def test_rotated_logs_path_traversal_blocked(box):
    victim = mk(box.etc / "shadow.gz", "secret")
    sneaky = f"{box.log}/../../etc/shadow.gz"
    # đảm bảo đường dẫn "lách" thực sự trỏ tới victim
    assert Path(os.path.realpath(sneaky)) == victim.resolve()
    r = box.run("clean-rotated-logs", stdin=feed(sneaky))
    assert r.returncode == 0 and counts(r) == {"removed": "0", "skipped": "1"}, "dòng phải được ĐỌC rồi mới bị từ chối"
    assert victim.exists(), "path traversal đã xóa được file ngoài /var/log!"


def test_rotated_logs_symlink_file_and_dir_blocked(box):
    target = mk(box.etc / "passwd.1", "root:x:0:0")
    link = box.log / "evil.1"
    link.symlink_to(target)
    old(link)                      # symlink phải đủ "cũ" — nếu không, kiểm tra 'file mới' sẽ che mất lỗi của kiểm tra symlink
    d = box.log / "linkdir"
    d.symlink_to(box.etc)
    r = box.run("clean-rotated-logs", stdin=feed(link, f"{d}/passwd.1"))
    assert r.returncode == 0 and counts(r) == {"removed": "0", "skipped": "2"}
    assert target.exists() and link.is_symlink()


def test_rotated_logs_untrusted_dir_blocked(box):
    d = box.log / "writable"
    d.mkdir()
    d.chmod(0o777)  # group/other ghi được → có thể hoán đổi symlink
    f = mk(d / "x.log.1")
    r = box.run("clean-rotated-logs", stdin=feed(f))
    assert r.returncode == 0 and counts(r) == {"removed": "0", "skipped": "1"} and f.exists()


def test_rotated_logs_rejects_outside_root_and_odd_paths(box):
    outside = mk(box.etc / "foo.gz")
    r = box.run("clean-rotated-logs", stdin=feed(outside, f"{box.log}//syslog.1", f"{box.log}/./syslog.1",
                                                "relative.gz", "../x.gz"))
    assert r.returncode == 0 and counts(r) == {"removed": "0", "skipped": "5"} and outside.exists()


# ── clean-crash-dirs ─────────────────────────────────────────────────────────
def test_crash_dirs_valid_and_traversal(box):
    c1 = mk(box.crash / "_usr_bin_x.1000.crash")
    c2 = mk(box.core / "core.firefox.1000.abc.1.2.zst")
    shadow = mk(box.etc / "shadow", "secret")
    sneaky = f"{box.core}/../../../../etc/shadow"
    sneaky2 = f"{box.core}/../../../../etc/core.shadow"
    mk(box.etc / "core.shadow")
    other = mk(box.core / "not-a-core-name")
    r = box.run("clean-crash-dirs", stdin=feed(c1, c2, sneaky, sneaky2, other))
    assert r.returncode == 0, r.stderr
    assert counts(r) == {"removed": "2", "skipped": "3"}
    assert not c1.exists() and not c2.exists()
    assert shadow.exists() and (box.etc / "core.shadow").exists() and other.exists()


def test_crash_dir_symlink_refused(box):
    secret = mk(box.etc / "secret")
    link = box.crash / "x.crash"
    link.symlink_to(secret)
    old(link)
    r = box.run("clean-crash-dirs", stdin=feed(link))
    assert r.returncode == 0 and counts(r)["skipped"] == "1" and secret.exists() and link.is_symlink()


def test_crash_subdir_depth_limited(box):
    (box.crash / "sub").mkdir()
    (box.crash / "sub").chmod(0o755)
    f = mk(box.crash / "sub" / "deep.crash")
    r = box.run("clean-crash-dirs", stdin=feed(f))
    assert r.returncode == 0 and counts(r)["skipped"] == "1" and f.exists()


# ── package removal ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("bad", [
    "--hookdir=/tmp/evil", "-U", "-Rns", "--config=/tmp/x", "pkg name", "pkg;id",
    "$(id)", "../x", "a" * 200, "", ".hidden", "-oDpkg::Pre-Invoke::=x",
])
@pytest.mark.parametrize("act", ["pacman-remove", "apt-remove", "dnf-remove", "zypper-remove"])
def test_remove_rejects_option_injection(box, act, bad):
    r = box.run(act, bad)
    assert r.returncode == 2
    assert box.calls_text() == ""


@pytest.mark.parametrize("act", ["pacman-remove", "apt-remove", "dnf-remove", "zypper-remove"])
@pytest.mark.parametrize("pkg", ["linux", "sudo", "grub", "linux-image-6.8.0-generic",
                                 "systemd", "pacman", "glibc", "networkmanager", "bash"])
def test_remove_refuses_protected(box, act, pkg):
    r = box.run(act, pkg)
    assert r.returncode == 3 and "protected" in r.stderr
    assert box.calls_text() == ""


def test_remove_multiple_args_rejected(box):
    assert box.run("pacman-remove", "vlc", "--hookdir=/x").returncode == 2
    assert box.run("apt-remove", "vlc", "gimp").returncode == 2


def test_remove_valid_uses_double_dash(box):
    assert box.run("pacman-remove", "vlc").returncode == 0
    assert box.run("apt-remove", "vlc").returncode == 0
    assert box.run("dnf-remove", "vlc").returncode == 0
    t = box.calls_text()
    assert "pacman -Rns --noconfirm -- vlc" in t
    assert "apt-get remove -y -- vlc" in t
    assert "dnf remove -y -- vlc" in t


def test_pacman_remove_blocked_when_pacman_busy(box):
    box.pacman_lock.write_text("")
    r = box.run("pacman-remove", "vlc")
    assert r.returncode == 75


# ── orphans ──────────────────────────────────────────────────────────────────
def test_orphans_only_real_orphans(box):
    box.orphans.write_text("foo\nbar\n")
    r = box.run("pacman-orphans", stdin="foo\nbar\n")
    assert r.returncode == 0, r.stderr
    assert "pacman -Rns --noconfirm -- foo bar" in box.calls_text()


def test_orphans_refuses_non_orphan_and_injection(box):
    box.orphans.write_text("foo\n")
    assert box.run("pacman-orphans", stdin="foo\nvlc\n").returncode == 3
    assert box.run("pacman-orphans", stdin="--hookdir=/tmp/x\n").returncode == 2
    assert box.run("pacman-orphans", stdin="foo bar\n").returncode == 2
    assert "-Rns" not in box.calls_text()


def test_orphans_refuses_protected_even_if_listed(box):
    box.orphans.write_text("linux\nfoo\n")
    r = box.run("pacman-orphans", stdin="foo\nlinux\n")
    assert r.returncode == 3
    assert "-Rns" not in box.calls_text()


def test_orphans_empty_list_rejected(box):
    assert box.run("pacman-orphans", stdin="").returncode == 2


# ── snap / swappiness ────────────────────────────────────────────────────────
@pytest.mark.parametrize("args", [("--purge", "12"), ("firefox", "--purge"), ("Fire fox", "1"),
                                  ("firefox", "12x"), ("firefox", "-1"), ("", "1")])
def test_snap_remove_rev_validation(box, args):
    assert box.run("snap-remove-rev", *args).returncode == 2
    assert box.calls_text() == ""


def test_snap_remove_rev_ok(box):
    assert box.run("snap-remove-rev", "firefox", "4336").returncode == 0
    assert "snap remove firefox --revision=4336" in box.calls_text()


@pytest.mark.parametrize("val", ["", "abc", "10; id", "201", "-1", "1000", "1 2", "$(id)"])
def test_set_swappiness_rejects(box, val):
    assert box.run("set-swappiness", val).returncode == 2


# ── paccache / broken-downloads ──────────────────────────────────────────────
def test_paccache_missing_gives_real_reason(box):
    (box.bin / "paccache").unlink()
    r = box.run("paccache", env_extra={"PATH": str(box.bin)})
    # /usr/bin có thể có paccache thật; khi đó bỏ qua phần khẳng định
    if shutil.which("paccache", path="/usr/bin:/bin") is None:
        assert r.returncode == 127 and "not installed" in r.stderr


def test_paccache_keeps_two_and_blocks_when_busy(box):
    assert box.run("paccache").returncode == 0
    assert "paccache -rk2" in box.calls_text()
    box.pacman_lock.write_text("")
    assert box.run("paccache").returncode == 75


def test_broken_downloads(box):
    d1 = box.pacman_cache / "download-AbC123"
    d1.mkdir()
    (d1 / "foo.pkg.tar.zst.part").write_text("x")
    old(d1 / "foo.pkg.tar.zst.part")
    old(d1)
    d2 = box.pacman_cache / "download-fresh"
    d2.mkdir()
    pkg = mk(box.pacman_cache / "vlc-3.0-1-x86_64.pkg.tar.zst")
    r = box.run("broken-downloads")
    assert r.returncode == 0, r.stderr
    assert not d1.exists()
    assert d2.exists(), "thư mục download mới (đang tải) không được xóa"
    assert pkg.exists()


def test_broken_downloads_blocked_when_pacman_running(box):
    box.pacman_lock.write_text("")
    d1 = box.pacman_cache / "download-x"
    d1.mkdir()
    old(d1)
    assert box.run("broken-downloads").returncode == 75
    assert d1.exists()


# ── update-apply ─────────────────────────────────────────────────────────────
def _keypair(tmp: Path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    priv = Ed25519PrivateKey.generate()
    raw = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    der = bytes.fromhex("302a300506032b6570032100") + raw
    pem = ("-----BEGIN PUBLIC KEY-----\n" + base64.encodebytes(der).decode()
           + "-----END PUBLIC KEY-----")
    return priv, pem


def _release(tmp: Path, version="3.1.0", with_version=True, symlink_out=False, name="rel.tar.gz",
             with_helper=False):
    src = tmp / f"src-{name}"
    app = src / "CyberClean"
    app.mkdir(parents=True)
    exe = app / "CyberClean"
    exe.write_text("#!/bin/sh\necho hi\n")
    exe.chmod(0o755)
    (app / "pad.bin").write_bytes(os.urandom(120_000))
    if with_version:
        (app / "VERSION").write_text(version + "\n")
    if symlink_out:
        (app / "evil").symlink_to("/etc/passwd")
    if with_helper:
        (app / "cyber-clean-helper").write_text("#!/bin/bash\nHELPER_PROTOCOL=2\necho new\n")
    out = tmp / name
    with tarfile.open(out, "w:gz") as tf:
        tf.add(app, arcname="CyberClean")
    return out


def _sign(priv, path: Path) -> Path:
    sig = tmp = path.with_suffix(path.suffix + ".sig")
    sig.write_text(base64.b64encode(priv.sign(path.read_bytes())).decode() + "\n")
    return sig


@pytest.fixture()
def upd(tmp_path):
    pytest.importorskip("cryptography")
    if subprocess.run("openssl pkeyutl -help 2>&1 | grep -q -- -rawin", shell=True).returncode != 0:
        pytest.skip("OpenSSL >= 3.0 required")
    b = Box(tmp_path / "sys")
    priv, pem = _keypair(tmp_path)
    b.build_helper(pubkey_pem=pem)
    # bản đang cài: 3.0.3
    b.app.mkdir(parents=True)
    (b.app / "CyberClean").write_text("old")
    (b.app / "VERSION").write_text("3.0.3\n")
    work = tmp_path / "dl"
    work.mkdir()
    return b, priv, work


def test_update_apply_happy_path(upd):
    b, priv, work = upd
    tgz = _release(work)
    sig = _sign(priv, tgz)
    r = b.run("update-apply", str(tgz), str(sig), "3.1.0")
    assert r.returncode == 0, r.stderr
    assert (b.app / "CyberClean").read_text().startswith("#!/bin/sh")
    assert (b.app / "VERSION").read_text().strip() == "3.1.0"
    assert (b.opt / "_backup" / "VERSION").read_text().strip() == "3.0.3"
    st = (b.app / "CyberClean").stat()
    assert st.st_uid == 0 and not (st.st_mode & stat.S_IWOTH) and not (st.st_mode & stat.S_IWGRP)
    assert not [p for p in b.opt.iterdir() if p.name.startswith(".update.")], "staging còn sót"


def test_update_apply_rejects_bad_signature(upd):
    b, priv, work = upd
    tgz = _release(work)
    sig = _sign(priv, tgz)
    data = bytearray(tgz.read_bytes())
    data[2000] ^= 0xFF
    tgz.write_bytes(bytes(data))
    r = b.run("update-apply", str(tgz), str(sig), "3.1.0")
    assert r.returncode == 3 and "SIGNATURE INVALID" in r.stderr
    assert (b.app / "VERSION").read_text().strip() == "3.0.3"


def test_update_apply_rejects_wrong_key(upd):
    b, priv, work = upd
    other, _ = _keypair(work)
    tgz = _release(work)
    sig = _sign(other, tgz)
    assert b.run("update-apply", str(tgz), str(sig), "3.1.0").returncode == 3


@pytest.mark.parametrize("ver", ["3.0.3", "3.0.2", "2.9.9", "3.0.3-beta"])
def test_update_apply_rejects_downgrade_and_same(upd, ver):
    b, priv, work = upd
    tgz = _release(work, version=ver)
    sig = _sign(priv, tgz)
    r = b.run("update-apply", str(tgz), str(sig), ver)
    assert r.returncode == 3 and "not newer" in r.stderr
    assert (b.app / "VERSION").read_text().strip() == "3.0.3"


def test_update_apply_rejects_missing_or_mismatched_version(upd):
    b, priv, work = upd
    t1 = _release(work, with_version=False, name="a.tar.gz")
    assert b.run("update-apply", str(t1), str(_sign(priv, t1)), "3.1.0").returncode == 3
    t2 = _release(work, version="3.0.9", name="b.tar.gz")
    r = b.run("update-apply", str(t2), str(_sign(priv, t2)), "3.2.0")
    assert r.returncode == 3 and "does not match" in r.stderr


def test_update_apply_rejects_escaping_symlink(upd):
    b, priv, work = upd
    tgz = _release(work, symlink_out=True)
    r = b.run("update-apply", str(tgz), str(_sign(priv, tgz)), "3.1.0")
    assert r.returncode == 3 and "symlink escapes" in r.stderr
    assert (b.app / "VERSION").read_text().strip() == "3.0.3"


def test_update_apply_rejects_symlinked_inputs_and_bad_args(upd):
    b, priv, work = upd
    tgz = _release(work)
    sig = _sign(priv, tgz)
    ln = work / "link.tar.gz"
    ln.symlink_to(tgz)
    assert b.run("update-apply", str(ln), str(sig), "3.1.0").returncode == 2
    assert b.run("update-apply", str(tgz), str(sig), "latest").returncode == 2
    assert b.run("update-apply", str(tgz), str(sig)).returncode == 2
    assert b.run("update-apply", str(tgz), "/nonexistent", "3.1.0").returncode == 2


def test_update_apply_can_refresh_helper_from_signed_bundle(upd):
    b, priv, work = upd
    tgz = _release(work, with_helper=True)
    r = b.run("update-apply", str(tgz), str(_sign(priv, tgz)), "3.1.0")
    assert r.returncode == 0, r.stderr
    assert b.install_path.exists() and "echo new" in b.install_path.read_text()


# ── install-helper ───────────────────────────────────────────────────────────
def test_install_helper_refuses_outside_app_bundle(box):
    r = box.run("install-helper")
    assert r.returncode == 3 and "only runs from the installed app bundle" in r.stderr


def test_install_helper_from_bundle(box):
    box.app.mkdir(parents=True, exist_ok=True)
    box.app.chmod(0o755)
    inside = box.app / "cyber-clean-helper"
    shutil.copy(box.helper, inside)
    inside.chmod(0o755)
    r = subprocess.run([str(inside), "install-helper"], capture_output=True, text=True,
                       env={"PATH": f"{box.bin}:/usr/bin:/bin"})
    assert r.returncode == 0, r.stderr
    assert box.install_path.exists()
    assert os.access(box.install_path, os.X_OK)
    if shutil.which("visudo"):
        rule = (box.sudoers_dir / "cyberclean").read_text()
        assert re.fullmatch(rf"%(sudo|wheel) ALL=\(root\) NOPASSWD: {re.escape(str(box.install_path))}\n", rule)
    else:
        assert "SKIPPED" in r.stdout


# ── đồng bộ khóa công khai với updater.py ────────────────────────────────────
def test_public_key_matches_updater():
    helper = HELPER_SRC.read_text()
    m = re.search(r"-----BEGIN PUBLIC KEY-----\n(.*?)\n-----END PUBLIC KEY-----", helper, re.S)
    der = base64.b64decode(m.group(1))
    assert der[:12] == bytes.fromhex("302a300506032b6570032100")
    updater = (ROOT / "utils" / "updater.py").read_text()
    key_b64 = re.search(r'CYBERCLEAN_PUBLIC_KEY_B64\s*=\s*"([^"]+)"', updater).group(1)
    assert der[12:] == base64.b64decode(key_b64)


# ── thư mục group-writable (Ubuntu: /var/log là root:syslog 775) ──────────────
def _group_writable_log(box, gid=110, members="", humans_primary=False):
    box.log.chmod(0o775)
    os.chown(box.log, 0, gid)
    box.groups.write_text(f"syslog:x:{gid}:{members}\n")
    box.passwd.write_text("root:x:0:0::/root:/bin/sh\nsyslog:x:104:%d::/nonexistent:/usr/sbin/nologin\n"
                          "alice:x:1000:%d::/home/alice:/bin/bash\n" % (gid, gid if humans_primary else 1000))
    return mk(box.log / "syslog.1")


def test_group_writable_system_group_is_trusted(box):
    f = _group_writable_log(box)
    r = box.run("clean-rotated-logs", stdin=feed(f))
    assert r.returncode == 0 and counts(r)["removed"] == "1" and not f.exists(), "Ubuntu: /var/log root:syslog 775 phải dọn được"


def test_group_writable_with_human_member_is_refused(box):
    f = _group_writable_log(box, members="syslog,alice")
    r = box.run("clean-rotated-logs", stdin=feed(f))
    assert counts(r) == {"removed": "0", "skipped": "1"} and f.exists()


def test_group_writable_with_human_primary_group_is_refused(box):
    f = _group_writable_log(box, humans_primary=True)
    r = box.run("clean-rotated-logs", stdin=feed(f))
    assert counts(r) == {"removed": "0", "skipped": "1"} and f.exists()


def test_group_writable_with_user_gid_is_refused(box):
    f = _group_writable_log(box, gid=1000)
    r = box.run("clean-rotated-logs", stdin=feed(f))
    assert counts(r) == {"removed": "0", "skipped": "1"} and f.exists()


def test_group_writable_unknown_group_is_refused(box):
    box.log.chmod(0o775)
    os.chown(box.log, 0, 777)
    f = mk(box.log / "x.1")
    r = box.run("clean-rotated-logs", stdin=feed(f))
    assert counts(r) == {"removed": "0", "skipped": "1"} and f.exists()


def test_other_writable_never_trusted_even_for_system_group(box):
    f = _group_writable_log(box)
    box.log.chmod(0o777)
    r = box.run("clean-rotated-logs", stdin=feed(f))
    assert counts(r) == {"removed": "0", "skipped": "1"} and f.exists()


def test_non_root_owned_dir_is_refused(box):
    f = mk(box.log / "svc" / "a.log.1")
    os.chown(box.log / "svc", 33, 0)
    r = box.run("clean-rotated-logs", stdin=feed(f))
    assert counts(r) == {"removed": "0", "skipped": "1"} and f.exists()
