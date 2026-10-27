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

import signal

_tls = threading.local()
_active_lock = threading.Lock()
_active_procs: set = set()
_active_tasks: set = set()
_active_count: int = 0
_cancel_event = threading.Event()
_ORIG_SUBPROCESS_RUN = subprocess.run

# Các action giao dịch gói/cập nhật cần kết thúc an toàn (chỉ gửi tín hiệu dừng hợp tác SIGTERM,
# không cưỡng bức SIGKILL cây tiến trình đang giữ khóa DB / đổi thư mục cài đặt).
_SAFE_TX_ACTIONS = frozenset({
    "update-apply", "install-helper",
    "apt-remove", "apt-autoremove",
    "dnf-remove", "dnf-autoremove",
    "pacman-remove", "pacman-orphans",
    "zypper-remove", "xbps-remove", "xbps-orphans",
    "snap-remove-rev", "rpm-ostree-cleanup",
})


def _scan_proc_table() -> tuple[dict[int, int], dict[int, int], dict[int, str]]:
    """Đọc bảng tiến trình từ /proc (Linux): trả về (parent_map, pgrp_map, state_map)."""
    parent_map: dict[int, int] = {}
    pgrp_map: dict[int, int] = {}
    state_map: dict[int, str] = {}
    if not os.path.isdir("/proc"):
        return parent_map, pgrp_map, state_map
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            pid = int(entry)
            try:
                with open(f"/proc/{pid}/stat", "r", encoding="utf-8", errors="replace") as f:
                    data = f.read()
                rparen = data.rfind(")")
                if rparen < 0:
                    continue
                fields = data[rparen + 2:].split()
                if len(fields) < 3:
                    continue
                state_map[pid] = fields[0]
                parent_map[pid] = int(fields[1])
                pgrp_map[pid] = int(fields[2])
            except (OSError, ValueError):
                continue
    except OSError:
        pass
    return parent_map, pgrp_map, state_map


class _ManagedTask:
    """Theo dõi vòng đời tiến trình helper cùng toàn bộ nhóm tiến trình (pgid) và cây tiến trình con."""

    def __init__(self, proc: subprocess.Popen, action: str = "") -> None:
        self.proc = proc
        self.action = action
        self.pid: int = getattr(proc, "pid", 0) or 0
        self.pgid: int = self.pid
        if os.name == "posix" and self.pid > 0 and hasattr(os, "getpgid"):
            try:
                self.pgid = os.getpgid(self.pid)
            except OSError:
                self.pgid = self.pid
        self.known_pids: set[int] = {self.pid} if self.pid > 0 else set()
        self._signaled_pids: set[int] = set()
        self._pgid_signaled: bool = False
        self.finished_communicate: bool = False
        self._lock = threading.Lock()
        self.discover_descendants()

    def discover_descendants(self) -> set[int]:
        """Cập nhật danh sách toàn bộ PID con/cháu và cùng process group; trả về tập PID còn đang chạy."""
        try:
            self.proc.poll()
        except Exception:
            pass
        parent_map, pgrp_map, state_map = _scan_proc_table()
        with self._lock:
            if parent_map:
                if self.pgid > 1:
                    for pid, pgrp in pgrp_map.items():
                        if pgrp == self.pgid:
                            self.known_pids.add(pid)
                added = True
                while added:
                    added = False
                    for pid, ppid in parent_map.items():
                        if ppid in self.known_pids and pid not in self.known_pids:
                            self.known_pids.add(pid)
                            added = True
                live = {
                    pid for pid in self.known_pids
                    if pid in state_map and state_map[pid] != "Z"
                }
                return live
            # Fallback khi không có /proc
            live_fb: set[int] = set()
            if self.proc.poll() is None and self.pid > 0:
                live_fb.add(self.pid)
            try:
                import psutil
                for p in list(self.known_pids):
                    try:
                        pr = psutil.Process(p)
                        if pr.is_running() and pr.status() != psutil.STATUS_ZOMBIE:
                            live_fb.add(p)
                        for ch in pr.children(recursive=True):
                            self.known_pids.add(ch.pid)
                            if ch.is_running() and ch.status() != psutil.STATUS_ZOMBIE:
                                live_fb.add(ch.pid)
                    except Exception:
                        continue
            except ImportError:
                pass
            return live_fb

    def is_alive(self) -> bool:
        live = self.discover_descendants()
        try:
            if self.proc.poll() is None:
                return True
        except Exception:
            pass
        return bool(live)

    def terminate_gracefully(self) -> None:
        """
        Gửi tín hiệu dừng hợp tác (SIGTERM) một lần cho mỗi tiến trình trong nhóm/cây tiến trình con
        (tránh gửi lặp lại làm ngắt quãng handler dọn dẹp an toàn của tiến trình con).
        Không dùng SIGKILL để bảo đảm tiến trình con / package manager kết thúc an toàn.
        """
        live = self.discover_descendants()
        with self._lock:
            first_pgid = not self._pgid_signaled
            self._pgid_signaled = True
            unsignaled = {pid for pid in live if pid > 1 and pid not in self._signaled_pids}
            self._signaled_pids.update(unsignaled)
        pgid_killed = False
        if first_pgid:
            if os.name == "posix" and self.pgid > 1 and hasattr(os, "killpg"):
                try:
                    os.killpg(self.pgid, signal.SIGTERM)
                    pgid_killed = True
                except OSError:
                    pass
            if not pgid_killed:
                try:
                    if self.proc.poll() is None:
                        self.proc.terminate()
                except Exception:
                    pass
        if not pgid_killed:
            for pid in unsignaled:
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass
        # Quét lại một lần nữa phòng trường hợp helper vừa fork tiến trình con ngay lúc nhận tín hiệu
        live_after = self.discover_descendants()
        with self._lock:
            newly_forked = {pid for pid in live_after if pid > 1 and pid not in self._signaled_pids}
            self._signaled_pids.update(newly_forked)
        for pid in newly_forked:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass


def set_unattended(flag: bool) -> None:
    """Thread-local: chạy nền không được bật prompt (pkexec / sudo -v) vì không có người ngồi trước máy."""
    _tls.unattended = bool(flag)


def is_unattended() -> bool:
    return bool(getattr(_tls, "unattended", False))


def request_cancel_helpers() -> None:
    """Yêu cầu dừng hợp tác các tiến trình helper (và tiến trình con của chúng) đang chạy."""
    _cancel_event.set()
    with _active_lock:
        tasks = list(_active_tasks)
        procs = list(_active_procs)
    for task in tasks:
        try:
            task.terminate_gracefully()
        except Exception:
            pass
    for proc in procs:
        try:
            if proc.poll() is None:
                proc.terminate()
        except Exception:
            pass


def clear_cancel_helpers() -> None:
    _cancel_event.clear()


def has_active_helper() -> bool:
    with _active_lock:
        tasks = list(_active_tasks)
        procs = list(_active_procs)
        cnt = _active_count
    any_task_alive = False
    dead_tasks = []
    for task in tasks:
        if task.is_alive():
            any_task_alive = True
        elif task.finished_communicate:
            dead_tasks.append(task)
    if dead_tasks:
        with _active_lock:
            for dt in dead_tasks:
                _active_tasks.discard(dt)
    if cnt > 0 or any_task_alive:
        return True
    return any(getattr(p, "poll", lambda: 0)() is None for p in procs)


def wait_active_helpers(timeout: float = 10.0) -> bool:
    """
    Chờ mọi tiến trình helper VÀ toàn bộ tiến trình con do helper tạo ra kết thúc hoàn toàn.
    Trả về True chỉ khi cả tiến trình cha và mọi tiến trình con đều đã dừng hẳn.
    """
    deadline = time.monotonic() + max(0.05, float(timeout))
    while has_active_helper() and time.monotonic() < deadline:
        if _cancel_event.is_set():
            with _active_lock:
                tasks = list(_active_tasks)
            for task in tasks:
                try:
                    task.terminate_gracefully()
                except Exception:
                    pass
        time.sleep(0.02)
    return not has_active_helper()


def _run_managed_cmd(cmd: list, *, input_text: str, timeout: float, action: str = "") -> subprocess.CompletedProcess:
    """
    Chạy lệnh helper trong nhóm tiến trình riêng (start_new_session=True) và theo dõi toàn bộ
    cây tiến trình con để bảo đảm khi dừng/hoàn tất thì mọi tiến trình con cũng đã kết thúc.
    Tương thích với monkeypatch `P.subprocess.run` trong test.
    """
    if subprocess.run is not _ORIG_SUBPROCESS_RUN:
        return subprocess.run(cmd, input=input_text, capture_output=True, text=True, timeout=timeout)
    popen_kwargs: dict = {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
    }
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **popen_kwargs)
    task = _ManagedTask(proc, action=action)
    with _active_lock:
        _active_procs.add(proc)
        _active_tasks.add(task)
    start_m = time.monotonic()
    try:
        out, err = proc.communicate(input=input_text, timeout=timeout)
        return subprocess.CompletedProcess(cmd, proc.returncode, out, err)
    except subprocess.TimeoutExpired:
        try:
            task.terminate_gracefully()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                if action not in _SAFE_TX_ACTIONS:
                    proc.kill()
                    proc.wait(timeout=2)
        except Exception:
            pass
        raise
    finally:
        try:
            if _cancel_event.is_set():
                task.terminate_gracefully()
            if proc.poll() is None:
                task.terminate_gracefully()
                try:
                    proc.wait(timeout=2)
                except Exception:
                    if action not in _SAFE_TX_ACTIONS:
                        proc.kill()
                        proc.wait(timeout=1)
            # Chờ các tiến trình con do helper sinh ra kết thúc hoàn toàn trước khi rời _run_managed_cmd
            rem = max(0.2, min(5.0, float(timeout) - (time.monotonic() - start_m)))
            wait_deadline = time.monotonic() + rem
            while task.is_alive() and time.monotonic() < wait_deadline:
                if _cancel_event.is_set():
                    task.terminate_gracefully()
                time.sleep(0.02)
        except Exception:
            pass
        task.finished_communicate = True
        with _active_lock:
            _active_procs.discard(proc)
            if not task.is_alive():
                _active_tasks.discard(task)


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
    global _active_count
    if action not in ("ping", "version", "set-swappiness"):
        if _cancel_event.is_set():
            return HelperResult(130, err="Interrupted by user", kind="failed")
        try:
            from core import engine as _E
            if _E.is_stop_requested():
                return HelperResult(130, err="Interrupted by user", kind="failed")
        except Exception:
            pass
    argv_tail = [action, *[str(a) for a in args]]
    if is_unattended():
        use_pkexec = False
    with _active_lock:
        _active_count += 1
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
        r = _run_managed_cmd(cmd, input_text=stdin if stdin is not None else "", timeout=timeout, action=action)
        kind = _classify(r)
        res = HelperResult(r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip(), kind)

        # NOPASSWD chưa cấu hình → thử pkexec (có prompt đồ họa) NẾU có polkit agent
        if kind == "password" and use_pkexec and not IS_ROOT and shutil.which("pkexec") and not _cancel_event.is_set():
            try:
                from core.os_detect import HAS_POLKIT_AGENT
            except Exception:                                  # pragma: no cover
                HAS_POLKIT_AGENT = False
            if HAS_POLKIT_AGENT:
                r2 = _run_managed_cmd(["pkexec", HELPER, *argv_tail], input_text=stdin or "", timeout=max(timeout, 90), action=action)
                return HelperResult(r2.returncode, (r2.stdout or "").strip(), (r2.stderr or "").strip(),
                                    "ok" if r2.returncode == 0 else "failed")
        return res
    except subprocess.TimeoutExpired:
        return HelperResult(124, kind="timeout")
    except Exception as e:                                     # pragma: no cover
        return HelperResult(1, err=str(e), kind="failed")
    finally:
        with _active_lock:
            _active_count = max(0, _active_count - 1)


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
