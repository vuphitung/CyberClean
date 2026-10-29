import os
from pathlib import Path

import pytest

from core import os_detect as O

FX = Path(__file__).parent / "fixtures" / "os-release"
EXPECT = {
    "ubuntu": "apt", "debian": "apt", "linuxmint": "apt", "pop": "apt", "zorin": "apt", "mx": "apt",
    "kali": "apt", "neon": "apt",
    "arch": "pacman", "manjaro": "pacman", "endeavouros": "pacman", "cachyos": "pacman", "garuda": "pacman",
    "steamos": "pacman", "unknown-derivative": "pacman",
    "fedora": "dnf", "nobara": "dnf", "bazzite": "dnf", "almalinux": "dnf", "rocky": "dnf", "rhel": "dnf",
    "silverblue": "dnf",
    "opensuse-tumbleweed": "zypper", "opensuse-leap": "zypper", "sles": "zypper",
    "void": "xbps", "alpine": "apk", "nixos": "nix",
}


def detect(name, *, binaries=(), files=()):
    osr = O.parse_os_release((FX / name).read_text())
    like = (osr.get("ID_LIKE") or "").split()
    return O.detect_pkg_manager(osr.get("ID", ""), like, which=lambda b: "/usr/bin/" + b if b in binaries else None,
                                exists=lambda p: p in files)


@pytest.mark.parametrize("name,pm", sorted(EXPECT.items()))
def test_package_manager_from_os_release(name, pm):
    assert detect(name) == pm, name


def test_every_fixture_is_covered():
    assert {p.name for p in FX.iterdir()} - set(EXPECT) == {"gentoo"}


def test_unrecognised_distro_falls_back_to_binary_probe():
    assert detect("gentoo") == ""
    assert detect("gentoo", binaries=("pacman",)) == "pacman"
    assert detect("gentoo", binaries=("apt-get",)) == "apt"
    assert detect("gentoo", binaries=("dnf",)) == "dnf"


def test_atomic_fedora_uses_rpm_ostree_not_dnf():
    ostree = ("/run/ostree-booted",)
    for name in ("silverblue", "bazzite", "fedora"):
        assert detect(name, binaries=("rpm-ostree", "dnf"), files=ostree) == "rpm-ostree"
    # Fedora thường (có dnf, không ostree) vẫn là dnf
    assert detect("fedora", binaries=("rpm-ostree",)) == "dnf"


def test_parse_os_release_quotes_comments_and_garbage():
    d = O.parse_os_release('# c\nID="ubuntu"\nID_LIKE=\'debian x\'\nNAME=A=B\nnoequals\n\n')
    assert d["ID"] == "ubuntu" and d["ID_LIKE"] == "debian x" and d["NAME"] == "A=B"
    assert O.parse_os_release("") == {} and O.parse_os_release(None) == {}


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="POSIX UID behavior")
def test_real_home_resolves_invoking_user_when_root_via_sudo(monkeypatch):
    import pwd
    monkeypatch.setattr(O.os, "geteuid", lambda: 0)
    me = pwd.getpwuid(0)
    monkeypatch.setenv("SUDO_USER", "nobody")
    monkeypatch.setenv("SUDO_UID", "65534")
    monkeypatch.delenv("PKEXEC_UID", raising=False)
    assert O.real_uid() == 65534
    assert str(O.real_home()) == pwd.getpwnam("nobody").pw_dir
    monkeypatch.delenv("SUDO_USER")
    monkeypatch.delenv("SUDO_UID")
    assert O.real_uid() == 0 and O.real_home() == O.Path.home()
    assert me is not None


def test_safe_delete_semantics(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("a")
    assert O.safe_delete(f, use_trash=False) is True and not f.exists()
    assert O.safe_delete(tmp_path / "missing", use_trash=False) is True
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep").write_text("k")
    link = tmp_path / "link"
    link.symlink_to(victim)
    assert O.safe_delete(link, use_trash=False) is True
    assert not link.exists() and (victim / "keep").exists(), "symlink bị theo → xóa nhầm đích"
