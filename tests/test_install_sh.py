import sys
"""
Chạy install.sh THẬT trong một cây thư mục giả (mọi đường dẫn hệ thống được sed sang sandbox,
curl/wget được thay bằng bản giả phục vụ file cục bộ). Không đụng /opt, /usr/local hay /etc thật.
"""
import base64
import os
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INSTALL = ROOT / "install.sh"
HELPER = ROOT / "packaging" / "cyber-clean-helper"

pytestmark = pytest.mark.skipif(sys.platform != "linux" or getattr(os, "geteuid", lambda: -1)() != 0, reason="install.sh needs root")


def _keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    priv = Ed25519PrivateKey.generate()
    raw = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    der = bytes.fromhex("302a300506032b6570032100") + raw
    pem = "-----BEGIN PUBLIC KEY-----\n" + base64.encodebytes(der).decode() + "-----END PUBLIC KEY-----"
    return priv, pem


class Env:
    def __init__(self, base: Path):
        self.base = base
        self.opt = base / "opt/CyberClean"
        self.bin = base / "usr/local/bin"
        self.sudoers = base / "etc/sudoers.d"
        self.web = base / "web"
        self.fakebin = base / "fakebin"
        for d in (self.bin, self.sudoers, self.web, self.fakebin, base / "usr/share/icons", base / "usr/share/applications"):
            d.mkdir(parents=True, exist_ok=True)
        self.opt.parent.mkdir(parents=True, exist_ok=True)
        (self.fakebin / "curl").write_text(
            '#!/bin/bash\nout=""; url=""\nwhile [[ $# -gt 0 ]]; do case "$1" in -o) out=$2; shift 2;; '
            f'-*) shift;; *) url=$1; shift;; esac; done\nf={self.web}/$(basename "$url")\n'
            '[[ -n "$out" && -f "$f" ]] || exit 22\ncp "$f" "$out"\n')
        (self.fakebin / "curl").chmod(0o755)
        self.priv, self.pem = _keypair()

    # ── release giả ──
    def release(self, version="3.1.0", *, helper=True, sign=True, tamper=False, sign_with=None, stale=False):
        src = self.base / f"rel-{version}"
        shutil.rmtree(src, ignore_errors=True)
        app = src / "CyberClean"
        app.mkdir(parents=True)
        (app / "CyberClean").write_text("#!/bin/sh\necho CyberClean\n")
        (app / "CyberClean").chmod(0o755)
        (app / "pad.bin").write_bytes(os.urandom(120_000))
        (app / "VERSION").write_text(version + "\n")
        if helper:
            txt = HELPER.read_text()
            rep = {r"^APP_PARENT=.*": f"APP_PARENT={self.opt}", r"^APP_DIR=.*": f"APP_DIR={self.opt}/CyberClean",
                   r"^HELPER_INSTALL_PATH=.*": f"HELPER_INSTALL_PATH={self.bin}/cyber-clean-helper",
                   r"^SUDOERS_DIR=.*": f"SUDOERS_DIR={self.sudoers}",
                   r"^SUDOERS_FILE=.*": f"SUDOERS_FILE={self.sudoers}/cyberclean"}
            for pat, val in rep.items():
                txt = re.sub(pat, val, txt, count=1, flags=re.M)
            (app / "cyber-clean-helper").write_text(txt)
            (app / "cyber-clean-helper").chmod(0o755)
        name = f"CyberClean-{version}-linux-x86_64.tar.gz"
        out = self.web / name
        with tarfile.open(out, "w:gz") as tf:
            tf.add(app, arcname="CyberClean")
        if sign:
            sig = (sign_with or self.priv).sign(out.read_bytes())
            (self.web / (name + ".sig")).write_text(base64.b64encode(sig).decode() + "\n")
        else:
            (self.web / (name + ".sig")).unlink(missing_ok=True)
        if tamper:
            data = bytearray(out.read_bytes())
            data[3000] ^= 0xFF
            out.write_bytes(bytes(data))
        return out

    def script(self) -> Path:
        s = INSTALL.read_text()
        rep = {r'^BIN=.*': f'BIN="{self.bin}/cyberclean"', r'^INSTALL_DIR=.*': f'INSTALL_DIR="{self.opt}"',
               r'^ICON_DEST=.*': f'ICON_DEST="{self.base}/usr/share/icons/cyberclean.png"',
               r'^DESKTOP_DEST=.*': f'DESKTOP_DEST="{self.base}/usr/share/applications/cyberclean.desktop"',
               r'^HELPER=.*': f'HELPER="{self.bin}/cyber-clean-helper"',
               r'^SUDOERS_FILE=.*': f'SUDOERS_FILE="{self.sudoers}/cyberclean"'}
        for pat, val in rep.items():
            s, n = re.subn(pat, val, s, count=1, flags=re.M)
            assert n == 1, pat
        s = re.sub(r"-----BEGIN PUBLIC KEY-----.*?-----END PUBLIC KEY-----", self.pem, s, count=1, flags=re.S)
        p = self.base / "install_test.sh"
        p.write_text(s)
        return p

    def run(self, *args, env_extra=None):
        env = {"PATH": f"{self.fakebin}:/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(self.base),
               "CYBERCLEAN_VERSION": "3.1.0"}
        env.update(env_extra or {})
        return subprocess.run(["bash", str(self.script()), *args], capture_output=True, text=True,
                              env=env, timeout=120)


@pytest.fixture()
def env(tmp_path):
    pytest.importorskip("cryptography")
    if subprocess.run("openssl pkeyutl -help 2>&1 | grep -q -- -rawin", shell=True).returncode != 0:
        pytest.skip("OpenSSL >= 3.0 required")
    return Env(tmp_path)


def test_happy_path_installs_app_helper_launcher(env):
    env.release()
    r = env.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Signature OK" in r.stdout
    assert (env.opt / "CyberClean/CyberClean").exists()
    helper = env.bin / "cyber-clean-helper"
    assert helper.exists() and os.access(helper, os.X_OK)
    assert subprocess.run([str(helper), "ping"], capture_output=True, text=True).stdout.strip() == "cyberclean-helper protocol=2"
    assert (env.bin / "cyberclean").exists()
    assert "Exec=" in (env.base / "usr/share/applications/cyberclean.desktop").read_text()
    st = (env.opt / "CyberClean/CyberClean").stat()
    assert st.st_uid == 0 and not st.st_mode & 0o022
    if shutil.which("visudo"):
        assert re.fullmatch(r"%(sudo|wheel) ALL=\(root\) NOPASSWD: .*/cyber-clean-helper\n",
                            (env.sudoers / "cyberclean").read_text())


def test_tampered_download_is_refused_and_nothing_installed(env):
    env.release(tamper=True)
    r = env.run()
    assert r.returncode != 0 and "SIGNATURE INVALID" in (r.stdout + r.stderr)
    assert not (env.opt / "CyberClean").exists() and not (env.bin / "cyber-clean-helper").exists()


def test_wrong_key_is_refused(env):
    other, _ = _keypair()
    env.release(sign_with=other)
    r = env.run()
    assert r.returncode != 0 and not (env.opt / "CyberClean").exists()


def test_missing_signature_is_refused_unless_explicitly_overridden(env):
    env.release(sign=False)
    r = env.run()
    assert r.returncode != 0 and "unverified" in (r.stdout + r.stderr).lower()
    assert not (env.opt / "CyberClean").exists()
    r2 = env.run(env_extra={"CYBERCLEAN_INSECURE_SKIP_VERIFY": "1"})
    assert r2.returncode == 0 and "UNVERIFIED" in r2.stdout
    assert (env.opt / "CyberClean/CyberClean").exists()


def test_release_without_helper_is_refused(env):
    env.release(helper=False)
    r = env.run()
    assert r.returncode != 0 and "privileged helper" in (r.stdout + r.stderr)
    assert not (env.opt / "CyberClean").exists()


def test_upgrade_replaces_instead_of_mixing_files(env):
    env.release()
    assert env.run().returncode == 0
    (env.opt / "CyberClean/stale-old-file.so").write_text("old")
    env.release(version="3.1.1")
    r = env.run(env_extra={"CYBERCLEAN_VERSION": "3.1.1"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (env.opt / "CyberClean/stale-old-file.so").exists()
    assert (env.opt / "CyberClean/VERSION").read_text().strip() == "3.1.1"
    assert not (env.opt / "_old").exists()


@pytest.mark.parametrize("bad", ["../../etc", "3.1.0; id", "latest", "", "3.1", "$(id)"])
def test_version_is_validated(env, bad):
    env.release()
    r = env.run(env_extra={"CYBERCLEAN_VERSION": bad})
    assert r.returncode != 0
    assert not (env.opt / "CyberClean").exists()


def test_no_fixed_tmp_path_and_no_leftovers(env):
    env.release()
    env.run()
    assert not Path("/tmp/CyberClean.tar.gz").exists()
    leftovers = [p for p in Path("/var/tmp").glob("cyberclean-install.*")]
    assert not leftovers


def test_uninstall_removes_helper_and_sudoers(env):
    env.release()
    env.run()
    r = env.run("--uninstall")
    assert r.returncode == 0
    assert not (env.bin / "cyber-clean-helper").exists() and not (env.sudoers / "cyberclean").exists()


def test_public_key_in_install_matches_updater():
    s = INSTALL.read_text()
    m = re.search(r"-----BEGIN PUBLIC KEY-----\n(.*?)\n-----END PUBLIC KEY-----", s, re.S)
    der = base64.b64decode(m.group(1))
    key_b64 = re.search(r'CYBERCLEAN_PUBLIC_KEY_B64\s*=\s*"([^"]+)"',
                        (ROOT / "utils" / "updater.py").read_text()).group(1)
    assert der[12:] == base64.b64decode(key_b64)


def test_install_sh_has_no_dangerous_leftovers():
    s = INSTALL.read_text()
    for bad in ("update-replace", "drop-cache", "stop-service", "/tmp/CyberClean.tar.gz", "pacman -Rns --noconfirm $pkgs"):
        assert bad not in s
    assert 'VERSION="3.0.1"' not in s
