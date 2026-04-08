"""
CyberClean — In-app updater (Linux /opt install + Windows Inno).
Release notes from GitHub API body; download + replace + restart.
All UI strings go through _t() for full i18n support.
"""
from __future__ import annotations

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
from urllib.error import URLError

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
        req = Request(url, headers=headers)
        with urlopen(req, timeout=25) as resp:
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
            if tag and _version_is_newer(tag, cur):
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
            if not tag or not _version_is_newer(tag, cur):
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

    def _download(self, url: str, dest: Path):
        req = Request(url, headers={"User-Agent": f"CyberClean-Updater/{self.version}"})
        with urlopen(req, timeout=120) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            done  = 0
            with open(dest, "wb") as f:
                while not self._cancelled:
                    data = resp.read(65536)
                    if not data:
                        break
                    f.write(data)
                    done += len(data)
                    if total:
                        self.progress.emit(
                            min(60, int(done / total * 60)),
                            _t("upd_downloading", "Downloading…",
                               ver=self.version, done=done // 1024, total=total // 1024),
                        )

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

            self.progress.emit(65, _t("upd_extracting", "Extracting…"))
            extract_dir = tmp_dir / "extracted"
            extract_dir.mkdir()
            with tarfile.open(tar_path, "r:gz") as tf:
                # BUG FIX 2: filter='data' prevents path traversal attacks (Python 3.12+)
                try:
                    tf.extractall(extract_dir, filter="data")
                except TypeError:
                    tf.extractall(extract_dir)  # Python 3.11 fallback

            extracted_app = extract_dir / "CyberClean" / "CyberClean"
            if not extracted_app.exists():
                matches = [p for p in extract_dir.rglob("CyberClean") if p.is_file()]
                if not matches:
                    return False, _t("upd_err_no_binary",
                        "Could not find CyberClean binary in archive.")
                extracted_app = matches[0]

            self.progress.emit(75, _t("upd_installing", "Installing…"))
            install_src = extracted_app.parent
            staging     = Path("/tmp/cyberclean_staging")
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
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
                r2 = subprocess.run(
                    f"sudo -n rsync -a --delete {staging}/ {install_dst}/",
                    shell=True, capture_output=True, text=True, timeout=120,
                    creationflags=_no_window_flags(),
                )
                if r2.returncode != 0:
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

            self.progress.emit(70, _t("upd_launching", "Launching installer…"))
            # Use /SILENT so user vẫn thấy installer chạy, tránh cảm giác app "đơ".
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
            _s.setValue("upd_in_progress_until", int(time.time()) + 600)  # 10 minutes
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

        self._prog_lbl.setText(_t("upd_done", "✓  Done — restarting…"))
        self._prog_lbl.setStyleSheet(
            f"color:{C['green']};font-size:11px;font-family:{MONO};"
        )
        self._update_btn.setVisible(False)
        self._skip_btn.setEnabled(False)
        QTimer.singleShot(1200, _restart_app)

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
    """Replace current process with the newly-installed binary."""
    if sys.platform == "win32":
        # Windows Inno Setup installer chịu trách nhiệm mở app mới sau khi ghi đè.
        # Ở đây chỉ cần thoát hẳn process cũ để tránh "đụng xe" khi file đang bị ghi.
        from PyQt6.QtWidgets import QApplication
        QApplication.quit()
        sys.exit(0)

    # Linux: binary was replaced in-place — exec the new one
    exe_opt = _linux_opt_install_dir()
    if exe_opt is not None:
        bin_path = exe_opt / "CyberClean"
        if bin_path.is_file():
            os.execv(str(bin_path), [str(bin_path)] + sys.argv[1:])

    # Fallback: re-exec via python (running from source)
    try:
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except OSError:
        sys.exit(0)
