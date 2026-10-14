"""
CyberClean — cổng duy nhất tới helper đặc quyền (Linux)
════════════════════════════════════════════════════════════════
Mọi nơi cần quyền root (cleaner, uninstaller, booster, updater) gọi qua đây:

  • Không bao giờ dùng shell / f-string để dựng lệnh — chỉ argv.
  • Tham số được kiểm tra lại ở phía root (packaging/cyber-clean-helper); đây chỉ
    là lớp tiện lợi + phân loại lỗi để thông báo ĐÚNG nguyên nhân (trước đây mọi
    lỗi đều bị gói thành "Need root").
  • Không có lối 'raw' (sudo -n <lệnh tùy ý>): mọi thứ chạy bằng root đều phải là
    một action đã được helper định nghĩa.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

IS_LINUX = sys.platform.startswith("linux")
IS_ROOT = IS_LINUX and os.geteuid() == 0

HELPER = "/usr/local/bin/cyber-clean-helper"
EXPECTED_PROTOCOL = 2

# Mã thoát của helper (khớp packaging/cyber-clean-helper)
EXIT_USAGE, EXIT_REFUSED, EXIT_NO_VERIFIER, EXIT_PACMAN_BUSY, EXIT_MISSING_TOOL = 2, 3, 4, 75, 127

_tls = threading.local()


def set_unattended(flag: bool) -> None:
    """Thread-local: chạy nền không được bật prompt (pkexec / sudo -v) vì không có người ngồi trước máy."""
    _tls.unattended = bool(flag)


def is_unattended() -> bool:
    return bool(getattr(_tls, "unattended", False))


_REASONS = {
    EXIT_USAGE:        "invalid arguments",
    EXIT_REFUSED:      "refused by the privileged helper (protected package / invalid signature)",
    EXIT_NO_VERIFIER:  "OpenSSL >= 3.0 is required to verify the update signature",
    EXIT_PACMAN_BUSY:  "pacman is busy (db.lck) — try again when it has finished",
}


@dataclass
class HelperResult:
    code: int
    out: str = ""
    err: str = ""
    kind: str = "ok"        # ok | failed | no_helper | no_sudo | password | timeout | old_helper

    @property
    def ok(self) -> bool:
        return self.code == 0

    @property
    def message(self) -> str:
        """Thông báo lỗi dành cho người dùng — nói đúng nguyên nhân thật."""
        if self.ok:
            return ""
        if self.kind == "no_helper":
            return f"Privileged helper not installed ({HELPER}) — run install.sh"
        if self.kind == "no_sudo":
            return "sudo is not available — run install.sh or start CyberClean with sudo"
        if self.kind == "password":
            return ("Not authorised: the NOPASSWD helper rule is missing — re-run install.sh "
                    "(or accept the password prompt)")
        if self.kind == "old_helper":
            return "The privileged helper is out of date — update it (see the notice in the Clean tab)"
        if self.kind == "timeout":
            return "The privileged operation timed out"
        if self.code == EXIT_MISSING_TOOL:
            return self.err.strip().splitlines()[-1] if self.err.strip() else "required tool is not installed"
        if self.code in _REASONS:
            detail = self.err.strip().splitlines()[-1] if self.err.strip() else ""
            return f"{_REASONS[self.code]}" + (f": {detail}" if detail else "")
        tail = (self.err or self.out).strip().splitlines()
        return tail[-1] if tail else f"helper exited with code {self.code}"


def _packaged_helper() -> Optional[str]:
    """Bản helper đi kèm app / source checkout (dùng khi chạy bằng root mà chưa cài helper)."""
    here = Path(__file__).resolve().parent.parent
    for cand in (here / "cyber-clean-helper", here / "packaging" / "cyber-clean-helper"):
        if cand.is_file():
            return str(cand)
    return None


def _classify(r: subprocess.CompletedProcess) -> str:
    err = (r.stderr or "")
    if r.returncode == 0:
        return "ok"
    low = err.lower()
    if "a password is required" in low or "a terminal is required" in low or "no tty present" in low:
        return "password"
    if "is not in the sudoers file" in low or "may not run sudo" in low or "not allowed to execute" in low:
        return "password"
    if "unknown action" in low or "unknown command" in low:
        return "old_helper"
    return "failed"


def run_helper(action: str, *args: str, stdin: Optional[str] = None, timeout: int = 120,
               use_pkexec: bool = True) -> HelperResult:
    """Chạy một action của helper. Không bao giờ raise."""
    argv_tail = [action, *[str(a) for a in args]]
    if is_unattended():
        use_pkexec = False
    try:
        if IS_ROOT:
            exe = HELPER if os.path.exists(HELPER) else _packaged_helper()
            if not exe:
                return HelperResult(1, kind="no_helper")
            cmd = [exe, *argv_tail]
        else:
            if not os.path.exists(HELPER):
                return HelperResult(1, kind="no_helper")
            if not shutil.which("sudo"):
                return HelperResult(1, kind="no_sudo")
            cmd = ["sudo", "-n", HELPER, *argv_tail]
        r = subprocess.run(cmd, input=stdin if stdin is not None else "", capture_output=True,
                           text=True, timeout=timeout)
        kind = _classify(r)
        res = HelperResult(r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip(), kind)

        # NOPASSWD chưa cấu hình → thử pkexec (có prompt đồ họa) NẾU có polkit agent
        if kind == "password" and use_pkexec and not IS_ROOT and shutil.which("pkexec"):
            try:
                from core.os_detect import HAS_POLKIT_AGENT
            except Exception:                                  # pragma: no cover
                HAS_POLKIT_AGENT = False
            if HAS_POLKIT_AGENT:
                r2 = subprocess.run(["pkexec", HELPER, *argv_tail], input=stdin or "",
                                    capture_output=True, text=True, timeout=max(timeout, 90))
                return HelperResult(r2.returncode, (r2.stdout or "").strip(), (r2.stderr or "").strip(),
                                    "ok" if r2.returncode == 0 else "failed")
        return res
    except subprocess.TimeoutExpired:
        return HelperResult(124, kind="timeout")
    except Exception as e:                                     # pragma: no cover
        return HelperResult(1, err=str(e), kind="failed")


# ── Trạng thái helper (cache ngắn) ────────────────────────────────────────────
@dataclass
class HelperInfo:
    installed: bool = False
    protocol: int = 0           # 0 = không gọi được, 1 = bản cũ (chưa có ping), >=2 hiện hành
    nopasswd: bool = False

    @property
    def current(self) -> bool:
        return self.installed and self.protocol >= EXPECTED_PROTOCOL

    @property
    def outdated(self) -> bool:
        return self.installed and 0 < self.protocol < EXPECTED_PROTOCOL


_info_lock = threading.Lock()
_info_cache: Optional[tuple] = None


def helper_info(max_age: float = 60.0, refresh: bool = False) -> HelperInfo:
    """
    Kiểm tra helper bằng action `ping` (an toàn, không đổi gì).
    Lưu ý: KHÔNG dùng `sudo -n true` — rule sudoers chỉ cho phép helper nên lệnh đó
    luôn đòi mật khẩu dù NOPASSWD đã cấu hình đúng (lỗi cũ của ensure_privileged_session).
    """
    global _info_cache
    with _info_lock:
        if not refresh and _info_cache and (time.monotonic() - _info_cache[0]) <= max_age:
            return _info_cache[1]
    info = HelperInfo(installed=os.path.exists(HELPER))
    if info.installed and IS_LINUX:
        r = run_helper("ping", timeout=10, use_pkexec=False)
        if r.ok:
            m = re.search(r"protocol=(\d+)", r.out)
            info.protocol = int(m.group(1)) if m else 1
            info.nopasswd = True
        elif r.kind == "old_helper":
            info.protocol, info.nopasswd = 1, True        # chạy được (NOPASSWD ok) nhưng chưa có ping
        elif r.kind == "password":
            info.nopasswd = False
    with _info_lock:
        _info_cache = (time.monotonic(), info)
    return info


def invalidate_helper_info() -> None:
    global _info_cache
    with _info_lock:
        _info_cache = None


def ensure_session(log_cb=None) -> bool:
    """
    Gọi MỘT lần trước một loạt target cần root. Nếu NOPASSWD chưa hoạt động và có
    TTY thì hỏi mật khẩu đúng một lần (`sudo -v`) để các lệnh sau trong cùng phiên
    không hỏi lại. Trả về True nếu sẽ gọi được helper không cần prompt.
    """
    if IS_ROOT:
        return True
    if is_unattended():
        return helper_info().nopasswd
    info = helper_info(refresh=True)
    if info.nopasswd:
        return True
    if not sys.stdin or not sys.stdin.isatty():
        if log_cb:
            log_cb("  i  No NOPASSWD helper and no terminal — falling back to a graphical prompt if available.",
                   "mute")
        return False
    if log_cb:
        log_cb("  ⚠  NOPASSWD helper not configured — asking for your password once "
               "(re-run install.sh to avoid this).", "warn")
    try:
        ok = subprocess.run(["sudo", "-v"], timeout=120).returncode == 0
    except Exception:
        return False
    invalidate_helper_info()
    return ok


# ── Nâng cấp helper cũ (3.0.x) bằng pkexec: cần mật khẩu admin, chạy từ bundle trong /opt ──
def packaged_helper_in_app() -> Optional[str]:
    cand = "/opt/CyberClean/CyberClean/cyber-clean-helper"
    return cand if os.path.isfile(cand) else None


def upgrade_helper_with_pkexec(timeout: int = 180) -> HelperResult:
    src = packaged_helper_in_app()
    if not src:
        return HelperResult(1, err="packaged helper not found in /opt/CyberClean", kind="no_helper")
    if not shutil.which("pkexec"):
        return HelperResult(1, err="pkexec is not available", kind="no_sudo")
    try:
        r = subprocess.run(["pkexec", src, "install-helper"], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return HelperResult(124, kind="timeout")
    invalidate_helper_info()
    return HelperResult(r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip(),
                        "ok" if r.returncode == 0 else "failed")
