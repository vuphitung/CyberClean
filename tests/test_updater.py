import base64
from pathlib import Path

import pytest

from core import privileged as P
from utils import updater as U


@pytest.fixture()
def worker(monkeypatch, tmp_path):
    w = U.UpdateWorker("3.1.0")
    monkeypatch.setattr(U, "_linux_opt_install_dir", lambda: Path("/opt/CyberClean/CyberClean"))

    def fake_download(self, url, dest, *a, **k):
        Path(dest).write_bytes(b"x" * 60_000)
    monkeypatch.setattr(U.UpdateWorker, "_download", fake_download)

    def fake_verify(file_path, base_url, version, sig_save_path=None):
        if sig_save_path is not None:
            sig_save_path.write_text(base64.b64encode(b"s" * 64).decode() + "\n")
        return True, "signature verified (Ed25519)"
    monkeypatch.setattr(U, "_verify_release", fake_verify)
    w.progress.connect(lambda *_: None)
    return w


class Rec:
    def __init__(self, result=None):
        self.calls, self.result = [], result or P.HelperResult(0, out="updated=3.1.0")

    def __call__(self, action, *args, **kw):
        self.calls.append((action, args, kw))
        return self.result


def info(monkeypatch, **kw):
    monkeypatch.setattr(P, "helper_info", lambda *a, **k: P.HelperInfo(**kw))


def test_update_uses_update_apply_with_tarball_sig_and_version(worker, monkeypatch):
    info(monkeypatch, installed=True, protocol=2, nopasswd=True)
    rec = Rec()
    monkeypatch.setattr(P, "run_helper", rec)
    ok, msg = worker._update_linux()
    assert ok and msg == "ok"
    action, args, _ = rec.calls[0]
    assert action == "update-apply"
    tar, sig, ver = args
    assert tar.endswith(".tar.gz") and sig.endswith(".tar.gz.sig") and ver == "3.1.0"


def test_old_update_replace_is_never_called(worker, monkeypatch):
    info(monkeypatch, installed=True, protocol=2, nopasswd=True)
    rec = Rec()
    monkeypatch.setattr(P, "run_helper", rec)
    worker._update_linux()
    assert all(c[0] != "update-replace" for c in rec.calls)
    assert "update-replace" not in Path(U.__file__).read_text(encoding='utf-8').replace("`update-replace`", "")


def test_outdated_helper_blocks_update_with_clear_message(worker, monkeypatch):
    info(monkeypatch, installed=True, protocol=1, nopasswd=True)
    rec = Rec()
    monkeypatch.setattr(P, "run_helper", rec)
    ok, msg = worker._update_linux()
    assert not ok and "out of date" in msg and rec.calls == []


def test_missing_helper_blocks_update(worker, monkeypatch):
    info(monkeypatch, installed=False)
    ok, msg = worker._update_linux()
    assert not ok and "install.sh" in msg


def test_helper_refusal_is_reported_with_real_reason(worker, monkeypatch):
    info(monkeypatch, installed=True, protocol=2, nopasswd=True)
    monkeypatch.setattr(P, "run_helper", Rec(P.HelperResult(3, err="SIGNATURE INVALID — update refused")))
    ok, msg = worker._update_linux()
    assert not ok and "SIGNATURE INVALID" in msg


def test_signature_verification_failure_stops_before_helper(worker, monkeypatch):
    monkeypatch.setattr(U, "_verify_release", lambda *a, **k: (False, "SIGNATURE INVALID"))
    rec = Rec()
    monkeypatch.setattr(P, "run_helper", rec)
    ok, msg = worker._update_linux()
    assert not ok and rec.calls == []


def test_non_opt_install_refuses(worker, monkeypatch):
    monkeypatch.setattr(U, "_linux_opt_install_dir", lambda: None)
    ok, msg = worker._update_linux()
    assert not ok and "/opt" in msg


def test_temp_dir_is_removed(worker, monkeypatch, tmp_path):
    import tempfile
    created = []
    real = tempfile.mkdtemp
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **k: created.append(real(**k)) or created[-1])
    info(monkeypatch, installed=True, protocol=2, nopasswd=True)
    monkeypatch.setattr(P, "run_helper", Rec())
    worker._update_linux()
    assert created and not Path(created[0]).exists()


def test_signature_file_is_saved_for_the_helper(monkeypatch, tmp_path):
    """_verify_ed25519 phải ghi .sig ra đĩa (để helper xác minh lại phía root)."""
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    priv = Ed25519PrivateKey.generate()
    raw = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    monkeypatch.setattr(U, "CYBERCLEAN_PUBLIC_KEY_B64", base64.b64encode(raw).decode())
    f = tmp_path / "pkg.tar.gz"
    f.write_bytes(b"payload" * 100)
    sig_b64 = base64.b64encode(priv.sign(f.read_bytes())).decode()

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return sig_b64.encode()
    monkeypatch.setattr(U, "urlopen", lambda *a, **k: Resp())
    out = tmp_path / "pkg.tar.gz.sig"
    ok, msg = U._verify_ed25519(f, "https://x/y.sig", "ua", out)
    assert ok, msg
    assert out.read_text().strip() == sig_b64
    ok2, _ = U._verify_ed25519(f.with_name("other"), "https://x/y.sig", "ua", None)
    assert not ok2


def test_updater_refuses_non_https_urls(tmp_path):
    for bad in ("file:///etc/passwd", "ftp://x/y", "http://github.com/x", "", None):
        with pytest.raises(ValueError):
            U._https(bad)
    assert U._https("https://github.com/x") == "https://github.com/x"
    f = tmp_path / "p.tar.gz"
    f.write_bytes(b"x")
    ok, msg = None, None
    try:
        ok, msg = U._verify_ed25519(f, "file:///etc/passwd", "ua")
    except ValueError:
        ok = False
    assert ok is False
