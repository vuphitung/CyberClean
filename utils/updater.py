"""
CyberClean — In-app updater (Linux /opt install + Windows Inno).
Release notes from GitHub API body; download + replace + restart.
All UI strings go through _t() for full i18n support.

v2.3 additions:
  SHA-256 verify  — download .sha256 sidecar từ GitHub release, verify trước khi extract.
                    Backward compat: nếu .sha256 không tồn tại (release cũ), cho qua.
                    User v2.2.6 → v2.2.8 vẫn update được bình thường.
  Retry + backoff — tự retry 3 lần với exponential backoff (2s, 4s, 8s) khi network lỗi.
  Resume download — dùng Range header để tiếp tục download bị ngắt giữa chừng.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import sys
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal, QSettings
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QProgressBar,
    QTextEdit,
    QFrame,
)
from PyQt6.QtGui import QCursor

# i18n — imported lazily inside functions so updater can be imported
# before the Translator singleton is ready (e.g. during test).
def _t(key: str, default: str = '', **kwargs) -> str:
    """Translate key using the global Translator, format with kwargs."""
    try:
        from utils.i18n import _t as _translate
        text = _translate(key, default)
    except ImportError:
        try:
            from i18n import _t as _translate
            text = _translate(key, default)
        except ImportError:
            text = default or key
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, ValueError):
            pass
    return text

REPO = "vuphitung/CyberClean"

# ══════════════════════════════════════════════════════════════
# RELEASE SIGNING — Ed25519 (v2.4)
# ══════════════════════════════════════════════════════════════
# SECURITY: This public key is baked into the app at build time and is
# the actual root of trust for auto-update — NOT the .sha256 sidecar.
#
# WHY THIS MATTERS: SHA-256 alone only proves "the download wasn't
# corrupted in transit" — it says nothing about WHO produced the file,
# because both the artifact and its checksum come from the same GitHub
# release, i.e. the same trust boundary. If the GitHub account/repo is
# ever compromised, an attacker can upload a malicious build AND a
# matching .sha256 for it, and the old check would happily pass.
#
# Ed25519 fixes this because the PRIVATE key that produces a valid
# .sig file never touches GitHub at all (kept offline / in CI secrets).
# An attacker who fully compromises the GitHub account still cannot
# forge a signature that this public key will accept.
#
# DO NOT replace this constant by fetching a key from GitHub/the repo
# at runtime — that would just move the same trust problem one level
# up. The public key must ship inside the binary the user already has
# installed and already trusts.
CYBERCLEAN_PUBLIC_KEY_B64 = "0HIxLhJ7mZ31Bv7p6t1DK8gGC4/eyS6myJNYz9LYms0="


def _verify_ed25519(file_path: Path, sig_url: str, ua: str) -> tuple[bool, str]:
    """
    Download the .sig sidecar and verify it against CYBERCLEAN_PUBLIC_KEY_B64.

    Unlike _verify_sha256, this is NOT allowed to fail open on 404 or
    network errors for versions that ship with signing enabled — a
    missing/unreachable .sig on a release that is supposed to be signed
    is treated as a hard failure. (Backward compat for pre-signing
    releases is handled one layer up, in _verify_release, by falling
    back to the legacy SHA-256-only path when v2.4+ metadata is absent.)
    """
    import base64
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
    except ImportError:
        return False, "cryptography package missing — cannot verify signature"

    try:
        pub_raw = base64.b64decode(CYBERCLEAN_PUBLIC_KEY_B64)
        pubkey = Ed25519PublicKey.from_public_bytes(pub_raw)
    except Exception as e:
        return False, f"Invalid embedded public key: {e}"

    import ssl
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = True
    ssl_ctx.verify_mode = ssl.CERT_REQUIRED

    try:
        req = Request(sig_url, headers={"User-Agent": ua})
        with urlopen(req, timeout=30, context=ssl_ctx) as resp:
            sig_raw = resp.read().decode("utf-8", errors="replace").strip()
    except HTTPError as e:
        if e.code == 404:
            return False, "no .sig found — release is not signed"
        return False, f"HTTP {e.code} downloading .sig"
    except (URLError, OSError) as e:
        # Fail CLOSED here (unlike the legacy SHA-256 sidecar) — a
        # network hiccup must never be treated as "signature verified".
        return False, f"network error fetching .sig: {e}"

    try:
        signature = base64.b64decode(sig_raw)
    except Exception:
        return False, f"malformed .sig content: {sig_raw[:80]!r}"

    try:
        with open(file_path, "rb") as f:
            data = f.read()
    except OSError as e:
        return False, f"cannot read file for signature check: {e}"

    try:
        pubkey.verify(signature, data)
        return True, "signature verified (Ed25519)"
    except InvalidSignature:
        return False, (
            "SIGNATURE INVALID — this file was NOT signed with the real "
            "CyberClean release key. Do not install. Please report this."
        )
    except Exception as e:
        return False, f"signature check error: {e}"


def _verify_release(file_path: Path, base_url: str, version: str) -> tuple[bool, str]:
    """
    Combined verification, called by both the Linux and Windows update paths.

    Order of trust:
      1. Try Ed25519 .sig (real authenticity check) — if the target
         version is signing-eligible (>= SIGNING_INTRODUCED_VERSION), the
         .sig MUST be present and MUST pass. No fallback is possible for
         these versions, period.
      2. Only for versions strictly older than SIGNING_INTRODUCED_VERSION
         (genuinely pre-dating signing infrastructure) does this fall
         back to the legacy SHA-256 sidecar check, for real backward
         compatibility with users updating from very old installs.

    SECURITY — why this is NOT gated on "did the .sig request 404":
    A network-position attacker (MITM, malicious proxy, poisoned DNS,
    a compromised CDN edge) fully controls HTTP responses, including
    manufacturing a 404 for a .sig request that would otherwise have
    succeeded — for ANY release, signed or not. If "the server says no
    .sig exists" were the trigger for falling back to SHA-256-only
    checking, an attacker could force that fallback on every single
    update check, then supply a matching fake .sha256 alongside a
    tampered payload — completely defeating the Ed25519 signing scheme
    for every version, not just old ones. That was the previous behavior
    here and has been removed.

    The version string passed in comes from this app's own GitHub
    Releases API tag lookup, not from the .sig/.sha256 endpoints being
    verified — but more importantly, the decision of "is this version
    signing-eligible" is made by comparing against a version number
    hardcoded in THIS installed app's own code (SIGNING_INTRODUCED_VERSION
    below), which a network attacker cannot rewrite without already having
    arbitrary code execution on the machine (at which point the update
    mechanism is a moot point anyway). An attacker can still lie about
    which tag/version a payload corresponds to, but they cannot make this
    running app's code believe 3.0.3 is "pre-signing" — that threshold
    ships inside the binary being asked to verify, not on the network.
    """
    # Every release from this version onward is guaranteed, by this app's
    # own release process (see sign_release.py / the CI signing step),
    # to have been published with a valid .sig. Bump this only when a
    # NEW app release is cut — never in response to anything observed
    # over the network at verification time.
    SIGNING_INTRODUCED_VERSION = (3, 0, 2)
    is_signing_eligible = _parse_version_tuple(version) >= SIGNING_INTRODUCED_VERSION

    ua = f"CyberClean-Updater/{version}"
    sig_url = f"{base_url}.sig"
    ok_sig, sig_msg = _verify_ed25519(file_path, sig_url, ua)
    if ok_sig:
        return True, sig_msg

    if is_signing_eligible:
        # This version MUST be signed — no fallback exists for it, no
        # matter what the .sig request returned (404, network error, or
        # an actual invalid signature are all treated identically: fail
        # closed). This is the line that closes the downgrade attack.
        return False, (
            f"{sig_msg} — version {version} is required to be signed; "
            f"refusing to fall back to unsigned verification"
        )

    # Only reachable for versions older than SIGNING_INTRODUCED_VERSION —
    # genuinely pre-dates signing infra, legacy path is the real fallback.
    sha_url = f"{base_url}.sha256"
    ok_hash, hash_msg = _legacy_verify_sha256(file_path, sha_url, ua)
    if ok_hash:
        return True, f"[unsigned release — integrity only] {hash_msg}"
    return False, hash_msg


def _legacy_verify_sha256(file_path: Path, sha256_url: str, ua: str) -> tuple[bool, str]:
    """
    Legacy SHA-256-only check, kept ONLY for releases published before
    signing was added (backward compat for users on old app versions
    updating across the 3.0.1 -> 3.0.2 boundary, and for any release
    that for some reason has no .sig).

    NOTE: unlike the old _verify_sha256, network errors while fetching
    the sidecar now fail CLOSED, not open. The previous "skip on any
    network error" behavior was too permissive: it can't be exploited
    on its own (the main download still fails closed on TLS errors),
    but fail-closed is the correct default for anything with "verify"
    in the name, and there is no longer a good reason to be lenient
    here now that a hard failure just means "please retry", not
    "permanently blocked".
    """
    import ssl, hashlib
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = True
    ssl_ctx.verify_mode = ssl.CERT_REQUIRED

    sha256 = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha256.update(chunk)
        local_hash = sha256.hexdigest().lower()
    except OSError as e:
        return False, f"Cannot read file for verification: {e}"

    try:
        req = Request(sha256_url, headers={"User-Agent": ua})
        with urlopen(req, timeout=30, context=ssl_ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace").strip()
    except HTTPError as e:
        if e.code == 404:
            return True, "skipped — no .sha256 on server (pre-signing release, OK)"
        return False, f"HTTP {e.code} downloading .sha256"
    except (URLError, OSError) as e:
        return False, f"network error fetching .sha256: {e}"

    expected_hash = raw.split()[0].lower() if raw else ""
    if not expected_hash or len(expected_hash) != 64:
        return False, f"unexpected .sha256 format: {raw[:80]!r}"

    if local_hash == expected_hash:
        return True, f"verified OK ({local_hash[:16]}…)"
    return False, (
        f"SHA-256 MISMATCH — file may be corrupt or tampered!\n"
        f"  Expected: {expected_hash[:32]}…\n"
        f"  Got:      {local_hash[:32]}…\n"
        f"Please try again or download manually from GitHub."
    )


_VERSION_TAG_RE = re.compile(r"^\d+\.\d+\.\d+(?:[.\-][A-Za-z0-9]+)?$")


def _parse_version_tuple(ver: str) -> tuple:
    """Same rules as version.parse_version_tuple — duplicated so update check works in any thread/bundle."""
    s = (ver or "").strip().lstrip("v")
    parts: list = []
    for segment in s.split("."):
        num = ""
        for c in segment:
            if c.isdigit():
                num += c
            else:
                break
        if num:
            parts.append(int(num))
        else:
            break
    return tuple(parts) if parts else (0,)


def _version_is_newer(remote: str, current: str) -> bool:
    return _parse_version_tuple(remote) > _parse_version_tuple(current)


def _fetch_github_json(url: str, headers: dict) -> object | None:
    """GET JSON from GitHub API; returns dict/list or None on failure."""
    try:
        import ssl
        req = Request(url, headers=headers)
        # SECURITY: Create secure SSL context with proper validation
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = True
        ssl_context.verify_mode = ssl.CERT_REQUIRED
        with urlopen(req, timeout=25, context=ssl_context) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)
    except Exception:
        return None


def _github_api_headers(current_ver: str) -> dict[str, str]:
    """GitHub REST v3 requires a non-empty User-Agent; also request JSON explicitly."""
    return {
        "User-Agent": f"CyberClean/{current_ver} (in-app update check)",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


class UpdateCheckThread(QThread):
    """
    Fetch releases from GitHub in a real QThread (not threading.Thread).
    Emits found(version, body) when a non-draft release is newer than current.

    Uses /releases (not /releases/latest) so prereleases still show up — /latest
    ignores prerelease-only tags, which made local tests look like 'no update'.
    """
    found = pyqtSignal(str, str)

    def __init__(self, current_ver: str, repo: str = REPO, parent=None):
        super().__init__(parent)
        self._current = current_ver
        self._repo = repo

    def run(self):
        cur = (self._current or "").strip()
        headers = _github_api_headers(cur)

        # 1) /releases/latest — one object; works when "Latest" on GitHub is the new stable.
        latest_url = f"https://api.github.com/repos/{self._repo}/releases/latest"
        data = _fetch_github_json(latest_url, headers)
        if isinstance(data, dict) and data.get("tag_name"):
            tag = str(data["tag_name"]).lstrip("v").strip()
            # SECURITY: tag comes straight from the GitHub API and is used
            # to build download URLs later — reject anything that isn't a
            # plain semver-ish string before it ever touches a URL, so a
            # crafted tag_name (e.g. containing "/" or "..") can never be
            # used to redirect the download to an unexpected path.
            if tag and _VERSION_TAG_RE.match(tag) and _version_is_newer(tag, cur):
                self.found.emit(tag, data.get("body") or "")
            return

        # 2) Full list — prereleases, or if /latest failed (rate limit returns {message:...}).
        list_url = f"https://api.github.com/repos/{self._repo}/releases?per_page=30"
        data = _fetch_github_json(list_url, headers)
        if not isinstance(data, list):
            return
        best_tag = ""
        best_body = ""
        for rel in data:
            if not isinstance(rel, dict) or rel.get("draft"):
                continue
            tag = (rel.get("tag_name") or "").lstrip("v").strip()
            if not tag or not _VERSION_TAG_RE.match(tag) or not _version_is_newer(tag, cur):
                continue
            if not best_tag or _version_is_newer(tag, best_tag):
                best_tag = tag
                best_body = rel.get("body") or ""
        if best_tag:
            self.found.emit(best_tag, best_body)


# Design tokens — match main.py (no circular import)
C = {
    "bg": "#050a0f", "bg2": "#09121a", "bg3": "#0d1a26", "bg4": "#112032",
    "cyan": "#00e5ff", "cyan2": "#00bcd4", "cyan_dim": "#004d5c",
    "red": "#ff3d5a", "yellow": "#ffd740", "green": "#00e676",
    "text": "#def0f8", "text2": "#7eb8cc", "text3": "#3d6678",
    "border2": "#0f2a3d", "border3": "#1a3a52",
}
MONO    = "\'Cascadia Code\',\'JetBrains Mono\',\'Fira Code\',\'Consolas\',\'Share Tech Mono\',monospace"
DISPLAY = "\'Orbitron\',\'Rajdhani\',\'Oxanium\',\'Exo 2\',\'Share Tech Mono\',monospace"


class UpdateBadge(QLabel):
    """Clickable header pill — 'update available'."""
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


def _no_window_flags() -> int:
    if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return subprocess.CREATE_NO_WINDOW
    return 0


def _linux_opt_install_dir() -> Path | None:
    """Return /opt/CyberClean/CyberClean dir if this process IS that bundle."""
    try:
        exe = Path(sys.executable).resolve()
    except OSError:
        return None
    if exe.name != "CyberClean":
        return None
    if "/opt/CyberClean/CyberClean" not in str(exe):
        return None
    return exe.parent


# ══════════════════════════════════════════════════════════════
# DOWNLOAD WORKER
# ══════════════════════════════════════════════════════════════

class UpdateWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, version: str):
        super().__init__()
        self.version = version
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _download(self, url: str, dest: Path, progress_start: int = 10,
                  progress_end: int = 60):
        """
        Download url → dest với retry 3x exponential backoff + Range resume.
        - Retry: network error → chờ 2^attempt giây, tối đa 3 lần
        - Resume: nếu dest đã tồn tại một phần, dùng Range header để tiếp tục
        - Backward compat: server không support Range → download lại từ đầu
        """
        import ssl
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = True
        ssl_context.verify_mode = ssl.CERT_REQUIRED

        max_retries = 3
        for attempt in range(max_retries + 1):
            if self._cancelled:
                return

            # Resume: kiểm tra file đã download một phần chưa
            resume_pos = dest.stat().st_size if dest.exists() else 0
            headers = {"User-Agent": f"CyberClean-Updater/{self.version}"}
            if resume_pos > 0:
                headers["Range"] = f"bytes={resume_pos}-"

            try:
                req  = Request(url, headers=headers)
                with urlopen(req, timeout=120, context=ssl_context) as resp:
                    # 206 Partial Content = server hỗ trợ resume
                    # 200 OK = server không support Range → viết lại từ đầu
                    if resp.status == 200:
                        resume_pos = 0   # server trả về full file
                    total = int(resp.headers.get("Content-Length", 0))
                    done  = resume_pos
                    mode  = "ab" if resume_pos > 0 else "wb"
                    with open(dest, mode) as f:
                        while not self._cancelled:
                            data = resp.read(65536)
                            if not data:
                                break
                            f.write(data)
                            done += len(data)
                            total_real = total + resume_pos if total else 0
                            if total_real:
                                pct = progress_start + int(
                                    (done / total_real) * (progress_end - progress_start)
                                )
                                self.progress.emit(
                                    min(progress_end, pct),
                                    _t("upd_downloading", "Downloading…",
                                       ver=self.version,
                                       done=done // 1024,
                                       total=total_real // 1024),
                                )
                return   # download thành công

            except (URLError, HTTPError, OSError, TimeoutError) as e:
                if attempt >= max_retries:
                    raise   # hết retry, raise lên caller
                wait = 2 ** (attempt + 1)   # 2s, 4s, 8s
                self.progress.emit(
                    progress_start,
                    _t("upd_retry", f"Network error — retrying in {wait}s… ({attempt+1}/{max_retries})",
                       wait=wait, attempt=attempt+1, max=max_retries),
                )
                # Chờ có thể bị cancel
                for _ in range(wait * 10):
                    if self._cancelled:
                        return
                    import time as _t2
                    _t2.sleep(0.1)

    # ── Linux ────────────────────────────────────────────────
    def _update_linux(self):
        ver = self.version
        url = (
            f"https://github.com/{REPO}/releases/download/v{ver}/"
            f"CyberClean-{ver}-linux-x86_64.tar.gz"
        )

        install_dst = _linux_opt_install_dir()
        if install_dst is None:
            return False, _t("upd_err_no_opt",
                "In-app update requires the standard /opt install. Download .tar.gz from GitHub.")

        self.progress.emit(5, _t("upd_preparing", "Preparing download…"))
        tmp_dir  = Path(tempfile.mkdtemp(prefix="cyberclean_update_"))
        tar_path = tmp_dir / f"CyberClean-{ver}.tar.gz"

        try:
            self.progress.emit(10, _t("upd_downloading", "Downloading…",
                                      ver=ver, done=0, total=0))
            self._download(url, tar_path)

            if self._cancelled:
                return False, _t("upd_err_cancelled", "Update cancelled.")

            if tar_path.stat().st_size < 50_000:
                return False, _t("upd_err_small",
                    "Download too small — check release assets on GitHub.")

            # Signature verify (Ed25519, falls back to legacy SHA-256 only
            # for releases published before signing existed — see _verify_release)
            self.progress.emit(63, _t("upd_verifying", "Verifying signature…"))
            asset_base = (
                f"https://github.com/{REPO}/releases/download/v{ver}/"
                f"CyberClean-{ver}-linux-x86_64.tar.gz"
            )
            ok_verify, verify_msg = _verify_release(tar_path, asset_base, ver)
            if not ok_verify:
                return False, _t("upd_err_hash", verify_msg, msg=verify_msg)
            self.progress.emit(64, f"✓ {verify_msg}")

            self.progress.emit(65, _t("upd_extracting", "Extracting"))
            extract_dir = tmp_dir / "extracted"
            extract_dir.mkdir()
            
            # UI FEEDBACK: Hiên thông báo cho user yên tâm
            from PyQt6.QtWidgets import QApplication
            self.progress.emit(70, _t("upd_installing_optimizing", "Installing and optimizing... Will restart in 3 seconds!"))
            
            # LNH THN THÁNH: p giao diên update ngay lâp tuc trc khi bi ng bng
            QApplication.processEvents()
            
            with tarfile.open(tar_path, "r:gz") as tf:
                # SECURITY FIX: Path traversal protection for all Python versions
                try:
                    tf.extractall(extract_dir, filter="data")
                except TypeError:
                    # Manual path validation for Python < 3.12
                    for member in tf.getmembers():
                        # SECURITY: Block path traversal attempts
                        if '..' in member.name or member.name.startswith('/'):
                            continue
                        # SECURITY: Ensure resolved path stays within extract_dir
                        try:
                            target_path = (extract_dir / member.name).resolve()
                            if not str(target_path).startswith(str(extract_dir.resolve())):
                                continue
                        except (OSError, ValueError):
                            continue
                        tf.extract(member, extract_dir)

            extracted_app = extract_dir / "CyberClean" / "CyberClean"
            if not extracted_app.exists():
                matches = [p for p in extract_dir.rglob("CyberClean") if p.is_file()]
                if not matches:
                    return False, _t("upd_err_no_binary",
                        "Could not find CyberClean binary in archive.")
                extracted_app = matches[0]

            self.progress.emit(75, _t("upd_installing", "Installing…"))
            install_src = extracted_app.parent
            # SECURITY: staging now lives under tmp_dir, which was created
            # via tempfile.mkdtemp() a few lines above — random name, 0700
            # permissions, guaranteed fresh (never reused across runs).
            # This replaces the old fixed path Path("/tmp/cyberclean_staging"),
            # which was a predictable, world-visible location and a classic
            # TOCTOU/insecure-temp-file anti-pattern (CWE-377): a local
            # attacker could not swap it out after creation thanks to /tmp's
            # sticky bit, but relying on that incidental protection is
            # fragile — a future refactor (e.g. adding dirs_exist_ok=True
            # to make retries more robust) could silently reopen it. Using
            # mkdtemp's random path removes the predictability entirely,
            # so there's no fixed target for a local attacker to race against.
            staging = tmp_dir / "staging"
            shutil.copytree(str(install_src), str(staging))

            helper = "/usr/local/bin/cyber-clean-helper"
            backup = "/opt/CyberClean/_backup"
            r = subprocess.run(
                ["sudo", "-n", helper, "update-replace",
                 str(staging), str(install_dst), backup],
                capture_output=True, text=True, timeout=120,
                creationflags=_no_window_flags(),
            )
            if r.returncode != 0:
                # Fallback: plain non-privileged copy. NOTE: the previous
                # version of this fallback shelled out to `sudo -n rsync`
                # via shell=True with f-string-interpolated paths — that
                # command was never actually granted in sudoers (only the
                # helper binary is), so it could only ever "work" by
                # accident via an unrelated cached sudo ticket, while still
                # carrying shell=True + string-interpolation risk for no
                # real benefit. Removed; if the helper call fails, fall
                # straight through to the unprivileged copy below (works
                # for the ~/.local fallback install location; for /opt it
                # will simply fail loudly, which is correct — we should
                # not silently attempt more privileged shell commands that
                # were never actually authorized).
                try:
                    shutil.copytree(str(staging), str(install_dst), dirs_exist_ok=True)
                except OSError as e:
                    return False, _t("upd_err_install",
                        f"Install failed: {e}", err=str(e))

            self.progress.emit(95, _t("upd_restarting", "Restarting…"))
            return True, "ok"

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Windows ──────────────────────────────────────────────
    def _update_windows(self):
        ver = self.version
        url = (
            f"https://github.com/{REPO}/releases/download/v{ver}/"
            f"CyberClean_Setup_v{ver}.exe"
        )

        self.progress.emit(5, _t("upd_preparing", "Preparing download…"))
        tmp_dir   = Path(tempfile.mkdtemp(prefix="cyberclean_update_"))
        installer = tmp_dir / f"CyberClean_Setup_v{ver}.exe"
        success   = False   # BUG FIX 1: track success to decide cleanup

        try:
            self.progress.emit(10, _t("upd_dl_installer", "Downloading installer…",
                                      ver=ver, done=0, total=0))
            self._download(url, installer)

            if self._cancelled:
                return False, _t("upd_err_cancelled", "Update cancelled.")

            if installer.stat().st_size < 500_000:
                return False, _t("upd_err_small_win",
                    "Installer too small — asset name may differ on GitHub.")

            # Signature verify (Ed25519, falls back to legacy SHA-256 only
            # for releases published before signing existed)
            self.progress.emit(68, _t("upd_verifying", "Verifying signature…"))
            asset_base = (
                f"https://github.com/{REPO}/releases/download/v{ver}/"
                f"CyberClean_Setup_v{ver}.exe"
            )
            ok_verify, verify_msg = _verify_release(installer, asset_base, ver)
            if not ok_verify:
                return False, _t("upd_err_hash", verify_msg, msg=verify_msg)

            self.progress.emit(70, _t("upd_launching", "Launching installer…"))

            # ── XÓA FLAG TRƯỚC KHI GỌI INNO ──────────────────────────────
            # /CLOSEAPPLICATIONS khiến Inno kill app ngay lập tức (~0.5s).
            # Nếu xóa flag sau (trong _restart_app), code đó không bao giờ chạy.
            # Phải xóa ở đây, trước khi thả Inno ra.
            try:
                import winreg as _wr
                _k = _wr.OpenKey(_wr.HKEY_CURRENT_USER,
                                 r"Software\CyberClean\CyberClean",
                                 0, _wr.KEY_SET_VALUE)
                try:
                    _wr.DeleteValue(_k, "upd_in_progress_until")
                except FileNotFoundError:
                    pass
                _wr.CloseKey(_k)
            except Exception:
                pass
            # ── Fallback: QSettings ────────────────────────────────────────
            try:
                from PyQt6.QtCore import QSettings as _QS
                _s2 = _QS("CyberClean", "CyberClean")
                _s2.remove("upd_in_progress_until")
                _s2.sync()
            except Exception:
                pass
            # ───────────────────────────────────────────────────────────────

            subprocess.Popen(
                [str(installer), "/SILENT", "/NORESTART", "/CLOSEAPPLICATIONS"],
                creationflags=_no_window_flags(),
            )
            self.progress.emit(90, _t("upd_installer_run",
                "Installer running — closing app…"))
            success = True
            return True, "ok"

        except Exception as e:
            return False, str(e)

        finally:
            # BUG FIX 1: only clean up if installer was NOT successfully spawned.
            # If success=True, the installer is still running and needs the .exe.
            if not success:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Main ─────────────────────────────────────────────────
    def run(self):
        try:
            if sys.platform == "win32":
                ok, msg = self._update_windows()
            elif sys.platform.startswith("linux"):
                ok, msg = self._update_linux()
            else:
                self.finished.emit(False, _t("upd_err_unsupported",
                    "Auto-update not supported on this OS."))
                return
            self.finished.emit(ok, msg)
        except URLError as e:
            self.finished.emit(False, _t("upd_err_network",
                f"Network error: {e.reason}", reason=str(e.reason)))
        except Exception as e:
            self.finished.emit(False, str(e))


# ══════════════════════════════════════════════════════════════
# UPDATE DIALOG
# ══════════════════════════════════════════════════════════════

class UpdateDialog(QDialog):
    def __init__(self, parent, version: str, body: str):
        super().__init__(parent)
        self.version = version
        self.body    = body or ""
        self._worker: UpdateWorker | None = None
        self._installed_ver = ""

        self.setWindowTitle(f"CyberClean — Update v{version}")
        self.setMinimumWidth(640)
        self.setMinimumHeight(500)
        self.setModal(True)
        self._apply_style()
        self._build_ui()

    def _apply_style(self):
        self.setStyleSheet(f"""
            QDialog {{
                background: {C["bg2"]};
                color: {C["text"]};
            }}
            QLabel {{
                color: {C["text"]};
                font-family: {MONO};
            }}
            QTextEdit {{
                background: {C["bg3"]};
                color: {C["text2"]};
                border: 1px solid {C["border3"]};
                border-radius: 4px;
                font-family: {MONO};
                font-size: 11px;
                padding: 10px;
            }}
            QProgressBar {{
                background: {C["bg3"]};
                border: 1px solid {C["border3"]};
                border-radius: 2px;
                height: 10px;
                text-align: center;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {C["cyan_dim"]}, stop:1 {C["cyan"]});
                border-radius: 2px;
            }}
            QPushButton {{
                border-radius: 4px;
                padding: 8px 20px;
                font-family: {MONO};
                font-size: 12px;
                letter-spacing: 1px;
            }}
        """)

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(22, 22, 22, 22)

        hdr = QLabel(_t("upd_title", f"⬆  VERSION {self.version} AVAILABLE",
                        ver=self.version))
        hdr.setStyleSheet(
            f"color:{C['cyan']};font-size:13px;letter-spacing:3px;"
            f"font-family:{DISPLAY};font-weight:700;"
        )
        lay.addWidget(hdr)

        try:
            from version import __version__ as cur
        except ImportError:
            cur = "?"
        self._installed_ver = cur
        cur_lbl = QLabel(_t("upd_installed", f"Installed: v{cur}   →   New: v{self.version}",
                            cur=cur, ver=self.version))
        cur_lbl.setStyleSheet(f"color:{C['text3']};font-size:11px;font-family:{MONO};")
        lay.addWidget(cur_lbl)

        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet(f"background:{C['border3']};max-height:1px;border:none;")
        lay.addWidget(div)

        nt = QLabel(_t("upd_notes_label", "RELEASE NOTES"))
        nt.setStyleSheet(
            f"color:{C['text3']};font-size:10px;letter-spacing:4px;font-family:{MONO};"
        )
        lay.addWidget(nt)

        self._notes = QTextEdit()
        self._notes.setReadOnly(True)
        self._notes.setMinimumHeight(220)
        no_notes = _t("upd_no_notes", "(No release notes for this version.)")
        self._notes.setPlainText(_md_to_plain(self.body or no_notes))
        lay.addWidget(self._notes, 1)

        self._prog_bar = QProgressBar()
        self._prog_bar.setVisible(False)
        self._prog_bar.setRange(0, 100)
        lay.addWidget(self._prog_bar)

        self._prog_lbl = QLabel("")
        self._prog_lbl.setStyleSheet(f"color:{C['text3']};font-size:11px;font-family:{MONO};")
        self._prog_lbl.setVisible(False)
        lay.addWidget(self._prog_lbl)

        row = QHBoxLayout()
        row.addStretch()

        self._skip_btn = QPushButton(_t("upd_btn_later", "LATER"))
        self._skip_btn.setStyleSheet(
            f"background:transparent;color:{C['text3']};"
            f"border:1px solid {C['border3']};padding:8px 18px;"
        )
        self._skip_btn.clicked.connect(self.reject)
        row.addWidget(self._skip_btn)

        self._update_btn = QPushButton(_t("upd_btn_update", "UPDATE NOW"))
        self._update_btn.setStyleSheet(
            f"background:{C['cyan']}22;color:{C['cyan']};"
            f"border:1px solid {C['cyan']};padding:8px 22px;font-weight:700;"
        )
        self._update_btn.clicked.connect(self._start_update)
        row.addWidget(self._update_btn)
        lay.addLayout(row)

    def _start_update(self):
        # Mark update in progress so a user clicking the app again on Windows
        # doesn't trigger the "Background Process Detected" kill prompt.
        try:
            _s = QSettings()
            _s.setValue("upd_in_progress_until", int(time.time()) + 120)  # 2 minutes max
        except Exception:
            pass

        self._skip_btn.setText(_t("upd_btn_cancel", "CANCEL"))
        try:
            self._skip_btn.clicked.disconnect()
        except TypeError:
            pass
        self._skip_btn.clicked.connect(self._cancel_update)

        self._update_btn.setEnabled(False)
        self._update_btn.setText(_t("upd_btn_updating", "UPDATING…"))

        self._prog_bar.setVisible(True)
        self._prog_lbl.setVisible(True)
        self._prog_bar.setValue(0)

        self._worker = UpdateWorker(self.version)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _cancel_update(self):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
        try:
            QSettings().remove("upd_in_progress_until")
        except Exception:
            pass
        self.reject()

    def _on_progress(self, pct: int, msg: str):
        self._prog_bar.setValue(pct)
        self._prog_lbl.setText(msg)

    def _on_finished(self, ok: bool, msg: str):
        self._prog_bar.setValue(100)
        if not ok:
            self._prog_lbl.setText(f"✗  {msg}")
            self._prog_lbl.setStyleSheet(
                f"color:{C['red']};font-size:11px;font-family:{MONO};"
            )
            self._update_btn.setText(_t("upd_btn_retry", "RETRY"))
            self._update_btn.setEnabled(True)
            try:
                self._update_btn.clicked.disconnect()
            except TypeError:
                pass
            self._update_btn.clicked.connect(self._start_update)
            self._skip_btn.setText(_t("upd_btn_close", "CLOSE"))
            try:
                self._skip_btn.clicked.disconnect()
            except TypeError:
                pass
            self._skip_btn.clicked.connect(self.reject)
            try:
                QSettings().remove("upd_in_progress_until")
            except Exception:
                pass
            return

        self._prog_bar.setValue(100)
        self._update_btn.setVisible(False)
        self._skip_btn.setEnabled(False)
        self._prog_lbl.setText(_t("upd_done", "✓  Done — restarting…"))
        self._prog_lbl.setStyleSheet(
            f"color:{C['green']};font-size:11px;font-family:{MONO};"
        )
        # Use QTimer for countdown — NEVER sleep() on the Qt main thread.
        # sleep() blocks the event loop, freezes the UI, and can cause
        # the subsequent os._exit(0) to kill the subprocess before it detaches.
        self._countdown = 3
        self._tick()

    def _tick(self):
        if self._countdown > 0:
            self._prog_lbl.setText(
                f"{_t('upd_restart_countdown', 'Restarting in')} {self._countdown}…"
            )
            self._countdown -= 1
            QTimer.singleShot(800, self._tick)
        else:
            self._prog_lbl.setText(_t("upd_final_message", "Launching new version…"))
            QTimer.singleShot(400, _restart_app)

    # BUG FIX 3: override closeEvent so X button also cancels the worker
    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
        event.accept()


# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════

def _md_to_plain(md: str) -> str:
    """Lightweight markdown → plain text for the release notes box."""
    lines = md.splitlines()
    out   = []
    for line in lines:
        line = re.sub(r"^#{1,3}\s+", "", line)
        line = re.sub(r"\*\*(.*?)\*\*", r"\1", line)
        line = re.sub(r"\*(.*?)\*",   r"\1", line)
        line = re.sub(r"`([^`]+)`",    r"[\1]", line)
        line = re.sub(r"^\s*[-*+]\s+", "  • ", line)
        out.append(line)
    return "\n".join(out).strip()


def _restart_app():
    """
    Replace current process with the newly-installed binary.

    Linux: os.execv() atomically replaces the current process.
    No subprocess spawning, no shell, no race condition with os._exit().
    The flag 'upd_in_progress_until' is cleared first so the new instance
    starts clean without the "updating" block.

    Windows: ShellExecuteW runas launches new exe with UAC, then we exit.
    """
    import os, sys, ctypes
    from pathlib import Path

    # Clear update flag BEFORE exec/exit so the new instance never sees it
    try:
        from PyQt6.QtCore import QSettings
        s = QSettings('CyberClean', 'CyberClean')
        s.remove('upd_in_progress_until')
        s.sync()
    except Exception:
        pass

    if sys.platform == "win32":
        # DO NOT try to launch new exe here — it doesn't exist yet.
        # Inno Setup is still running and will launch the new exe itself
        # via its [Run] postinstall entry once installation completes.
        # All we need to do is:
        # 1. Clear the update flag via winreg (reliable even during shutdown)
        # 2. Exit the old app cleanly so Inno can overwrite it
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\CyberClean\CyberClean",
                0, winreg.KEY_SET_VALUE
            )
            try:
                winreg.DeleteValue(key, "upd_in_progress_until")
            except FileNotFoundError:
                pass
            winreg.CloseKey(key)
        except Exception:
            pass
        from PyQt6.QtWidgets import QApplication
        QApplication.quit()
        sys.exit(0)
        return

    # ── Linux ─────────────────────────────────────────────
    # Candidate binary locations (onedir bundle structure)
    candidates = [
        Path("/opt/CyberClean/CyberClean/CyberClean"),          # standard install.sh path
        Path.home() / ".local/CyberClean/CyberClean/CyberClean",# user-local fallback
    ]
    binary = next((p for p in candidates if p.is_file()), None)

    if binary:
        # os.execv() replaces this process in-place — atomic, no race condition.
        # The new process inherits the same PID slot; no zombie, no double-launch.
        os.execv(str(binary), [str(binary)] + sys.argv[1:])
        # execv never returns on success; only reaches here on error

    # Running from source (python main.py) — re-exec python
    try:
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except OSError:
        pass

    # Last resort if execv failed for any reason
    sys.exit(0)
