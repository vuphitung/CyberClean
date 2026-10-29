import re
from pathlib import Path

import pytest

from core import privileged as P
from core import uninstaller as U

ROOT = Path(__file__).resolve().parent.parent


def helper_globs():
    text = (ROOT / "packaging" / "cyber-clean-helper").read_text(encoding='utf-8')
    block = re.search(r"PROTECTED_GLOBS=\((.*?)\n\)", text, re.S).group(1)
    out = []
    for tok in re.findall(r"'([^']+)'|(\S+)", block):
        out.append(tok[0] or tok[1])
    return out


def test_protected_lists_are_identical_to_the_helper():
    assert list(U.PROTECTED_PKG_GLOBS) == helper_globs(), "UI và helper phải dùng cùng danh sách gói lõi"


@pytest.mark.parametrize("pkg", ["linux", "linux-lts", "linux-image-6.8.0-31-generic", "grub", "grub-efi-amd64",
                                 "systemd", "sudo", "pacman", "glibc", "networkmanager", "NetworkManager", "bash",
                                 "mkinitcpio", "initramfs-tools", "polkit", "dbus", "linux-firmware", "plasma-desktop",
                                 "ubuntu-desktop-minimal"])
def test_core_packages_protected(pkg):
    assert U.is_protected_pkg(pkg)


@pytest.mark.parametrize("pkg", ["vlc", "firefox", "gimp", "libreoffice", "grub-customizer-gui-not", "htop", "code"])
def test_normal_packages_not_protected(pkg):
    if pkg == "grub-customizer-gui-not":
        pytest.skip("grub-* is deliberately broad")
    assert not U.is_protected_pkg(pkg)


def app(src="pacman", pkg="vlc"):
    return U.InstalledApp(name=pkg, source=src, pkg_id=pkg)


def test_uninstall_refuses_protected_without_calling_helper(monkeypatch):
    called = []
    monkeypatch.setattr(P, "run_helper", lambda *a, **k: called.append(a) or P.HelperResult(0))
    logs = []
    ran = []
    monkeypatch.setattr(U, "_run_argv", lambda *a, **k: ran.append(a) or ("", 0))
    monkeypatch.setattr(U, "run", lambda *a, **k: ran.append(a) or ("", 0))
    for src in ("pacman", "apt", "dnf", "zypper", "xbps"):
        assert U.uninstall_app(app(src, "linux"), lambda m, l="info": logs.append(m)) is False
    assert called == [] and ran == [], "không được chạy bất cứ lệnh nào (kể cả fallback sudo)"
    assert any("protected" in m for m in logs)


@pytest.mark.parametrize("src", ["pacman", "apt", "dnf", "zypper", "xbps"])
def test_uninstall_goes_only_through_helper(monkeypatch, src):
    seen = []
    monkeypatch.setattr(P, "run_helper", lambda action, *a, **k: seen.append((action, a)) or P.HelperResult(0))
    monkeypatch.setattr(U, "run", lambda *a, **k: pytest.fail("shell command used: %r" % (a,)))
    assert U.uninstall_app(app(src, "vlc"), lambda m, l="info": None) is True
    assert seen == [(f"{src}-remove", ("vlc",))]


def test_helper_refusal_does_not_fall_back_to_sudo(monkeypatch):
    monkeypatch.setattr(P, "run_helper", lambda *a, **k: P.HelperResult(3, err="refusing to remove protected system package: foo"))
    monkeypatch.setattr(U, "run", lambda *a, **k: pytest.fail("fallback to a shell command"))
    logs = []
    assert U.uninstall_app(app("apt", "weird-meta"), lambda m, l="info": logs.append(m)) is False
    assert any("refused" in m or "protected" in m for m in logs)


def test_flatpak_and_winget_use_argv_not_shell(monkeypatch):
    seen = []
    monkeypatch.setattr(U, "_run_argv", lambda argv, timeout=60: seen.append(argv) or ("", 0))
    monkeypatch.setattr(U, "run", lambda *a, **k: pytest.fail("shell"))
    assert U.uninstall_app(app("flatpak", "org.videolan.VLC"), lambda m, l="info": None) is True
    assert U.uninstall_app(U.InstalledApp("X", source="winget", pkg_id="Git.Git"), lambda m, l="info": None) is True
    assert seen[0] == ["flatpak", "uninstall", "-y", "--noninteractive", "org.videolan.VLC"]
    assert seen[1][:3] == ["winget", "uninstall", "--id"] and "Git.Git" in seen[1]


@pytest.mark.parametrize("src,pkg", [("flatpak", "x; rm -rf /"), ("flatpak", "-y"), ("winget", "--silent"), ("winget", "")])
def test_hostile_ids_rejected(monkeypatch, src, pkg):
    monkeypatch.setattr(U, "_run_argv", lambda *a, **k: pytest.fail("ran"))
    assert U.uninstall_app(U.InstalledApp("X", source=src, pkg_id=pkg), lambda m, l="info": None) is False


def test_protected_property_only_for_package_managers():
    assert app("pacman", "linux").protected
    assert not U.InstalledApp("linux", source="flatpak", pkg_id="linux").protected
