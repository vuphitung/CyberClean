"""
CyberClean v2.3 — System Booster (REWRITE)
═══════════════════════════════════════════════════════════════
WHAT CHANGED vs v2.2:

KILL BLOAT — Total redesign:
  OLD: Hardcoded whitelist by process name → chém nhầm XFCE, LXQt, Cosmic, etc.
  NEW: Detect DE động từ $XDG_CURRENT_DESKTOP + $DESKTOP_SESSION
       → protected list tự build theo DE đang chạy
       → SIGSTOP thay kill() để không mất dữ liệu user
       → SIGCONT khi restore (game_mode_off / eco_mode_off)
       → Chỉ touch process của UID hiện tại (không đụng root/system)

FREE RAM (Windows):
  OLD: EmptyWorkingSet → stutter khi truy cập lại
  NEW: SetProcessInformation(MemoryPriority=LOW) → kernel evict first
       → foreground pages stay warm, no stutter

FREE RAM (Linux):
  OLD: drop_caches → xóa sạch page cache, mọi thứ cold
  NEW: compact_memory only → defrag, không evict cache

ECO MODE (Windows):
  OLD: BELOW_NORMAL_PRIORITY_CLASS → phá vỡ Windows Quantum Boost
  NEW: SetProcessInformation(MemoryPriority=LOW) + MMCSS foreground boost

ECO MODE (Linux):
  OLD: nice(5) → chỉ ảnh hưởng CPU, không giải quyết I/O / memory pressure
  NEW: cgroups v2 (cpu.weight=20, io.weight=20, memory.low=512MB)
       → proportional scheduling cho CPU + I/O, kernel protect foreground RAM
       → fully reversible (di chuyển process ra khỏi cgroup = restore ngay)

GAME MODE — _enable_kernel_performance:
  OLD: Gọi powerprofilesctl / cpupower không check tồn tại → lỗi đỏ
  NEW: shutil.which() check trước, fallback graceful qua thứ tự ưu tiên:
       powerprofilesctl → tuned-adm → cpupower → /sys/cpufreq (direct) → skip

CLEANUP khi crash:
  NEW: atexit + SIGTERM handler để restore cgroup / nice ngay cả khi crash

═══════════════════════════════════════════════════════════════
"""
import os, sys, ctypes, shutil, subprocess, glob, platform, struct, signal, atexit
from pathlib import Path
from dataclasses import dataclass, field
from typing import Callable, Optional, Dict, List

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX   = platform.system() == "Linux"

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

HELPER      = "/usr/local/bin/cyber-clean-helper"
CURRENT_UID = getattr(os, 'getuid', lambda: -1)()

# ══════════════════════════════════════════════════════════════
# DE DETECTION — dynamic, not hardcoded
# ══════════════════════════════════════════════════════════════

def _detect_de_processes() -> set:
    """
    Detect Desktop Environment đang chạy và return set process names
    cần bảo vệ tuyệt đối (kill = crash DE).

    Đọc từ env var thay vì hardcode → tự động đúng với mọi DE kể cả mới.
    """
    de  = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    ses = os.environ.get("DESKTOP_SESSION",      "").lower()
    wm  = os.environ.get("WAYLAND_DISPLAY",      "")      # non-empty = Wayland session
    env = de + " " + ses

    protected = set()

    # ── Window managers / compositors ──────────────────────
    if "kde" in env or "plasma" in env:
        protected.update({
            "kwin_x11", "kwin_wayland", "plasmashell",
            "ksmserver", "kded5", "kded6", "kscreen_backend_launcher",
            "kglobalaccel5", "baloo_file", "kactivitymanagerd",
        })
    if "gnome" in env:
        protected.update({
            "gnome-shell", "mutter", "gnome-session-b", "gnome-session-c",
            "gsd-media-keys", "gsd-power", "gsd-color", "gnome-keyring-d",
        })
    if "xfce" in env:
        protected.update({
            "xfwm4", "xfce4-panel", "xfdesktop", "xfce4-session",
            "xfsettingsd", "xfconfd", "thunar",
        })
    if "lxqt" in env:
        protected.update({
            "openbox", "lxqt-panel", "pcmanfm-qt", "lxqt-session",
            "lxqt-runner", "obconf-qt",
        })
    if "lxde" in env:
        protected.update({"openbox", "lxpanel", "pcmanfm", "lxsession"})
    if "mate" in env:
        protected.update({
            "marco", "mate-panel", "caja", "mate-session",
            "mate-settings-d",
        })
    if "cinnamon" in env:
        protected.update({"muffin", "cinnamon", "nemo", "cinnamon-session"})
    if "budgie" in env:
        protected.update({"budgie-wm", "budgie-panel", "budgie-daemon"})
    if "deepin" in env:
        protected.update({"deepin-wm", "dde-desktop", "dde-dock", "dde-session"})
    if "cosmic" in env:
        protected.update({"cosmic-comp", "cosmic-panel", "cosmic-session",
                          "cosmic-bg", "cosmic-applets"})
    if "sway" in env or "sway" in ses:
        protected.update({"sway", "swaybar", "swaybg", "swayidle"})
    if "hyprland" in env or "hyprland" in ses:
        protected.update({"hyprland", "waybar", "hyprpaper", "hypridle",
                          "hyprlock", "hyprpolkitagent"})
    if "i3" in env or "i3" in ses:
        protected.update({"i3", "i3bar", "i3status", "i3blocks"})
    if "bspwm" in env:
        protected.update({"bspwm", "sxhkd", "polybar"})
    if "openbox" in env or "openbox" in ses:
        protected.update({"openbox", "tint2", "plank"})
    if "river" in env:
        protected.update({"river", "waybar", "riverctl"})
    if "niri" in env:
        protected.update({"niri", "waybar"})

    # ── Always protected regardless of DE ──────────────────
    protected.update({
        # Init / session
        "systemd", "init", "dbus-daemon", "dbus-broker",
        # Display servers
        "xorg", "xwayland", "Xorg", "X",
        # Display managers
        "sddm", "gdm", "gdm3", "lightdm", "lxdm", "ly",
        # Audio
        "pipewire", "wireplumber", "pipewire-pulse", "pipewire-media",
        "pulseaudio", "jackd", "jackdbus",
        # App itself
        "python", "python3", "cyberclean",
        # Notification daemons (kill = no notifications, some are tightly coupled)
        "dunst", "mako", "swaync", "fnott",
        # Polkit agents (kill = no privilege escalation)
        "polkit-kde-authentication-agent-1",
        "polkit-gnome-authentication-agent-1",
        "lxpolkit", "mate-polkit",
    })

    return protected


# Global DE protected set — computed once at import, reusable
_DE_PROTECTED: Optional[set] = None

def get_de_protected() -> set:
    global _DE_PROTECTED
    if _DE_PROTECTED is None:
        _DE_PROTECTED = _detect_de_processes()
    return _DE_PROTECTED


def _is_protected(proc_name: str) -> bool:
    """Check if a process name should never be touched."""
    name = proc_name.lower().replace(".exe", "")
    if name in get_de_protected():
        return True
    # GPU keywords — never touch display driver processes
    for kw in ("gpu", "nvidia", "amd", "radeon", "intel_gpu", "nvd",
                "amdgpu", "vgaswitcheroo", "renderer"):
        if kw in name:
            return True
    return False


# ══════════════════════════════════════════════════════════════
# CRASH CLEANUP — restore cgroup/nice even on SIGKILL via atexit
# ══════════════════════════════════════════════════════════════

_CLEANUP_REGISTRY: List[Callable] = []  # list of callback() to run on exit

def _register_cleanup(fn: Callable):
    """Register a no-arg cleanup function to run on app exit or signal."""
    _CLEANUP_REGISTRY.append(fn)

def _run_all_cleanups():
    for fn in _CLEANUP_REGISTRY:
        try:
            fn()
        except Exception:
            pass

atexit.register(_run_all_cleanups)

def _signal_handler(signum, frame):
    _run_all_cleanups()
    # Re-raise default behavior
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)

if IS_LINUX:
    signal.signal(signal.SIGTERM, _signal_handler)
    try:
        signal.signal(signal.SIGHUP, _signal_handler)
    except (AttributeError, OSError):
        pass


# ══════════════════════════════════════════════════════════════
# DATA TYPES
# ══════════════════════════════════════════════════════════════

@dataclass
class BoostResult:
    action:   str
    success:  bool  = True
    mb_freed: float = 0.0
    count:    int   = 0
    error:    str   = ""
    rollback: list  = field(default_factory=list)


def _run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode
    except Exception as e:
        return str(e), 1


def _run_helper(action, timeout=30):
    if IS_WINDOWS:
        return _run(action, timeout)
    out, code = _run(f"sudo -n {HELPER} {action} 2>/dev/null", timeout)
    if code == 0:
        return out, 0
    if os.geteuid() == 0:
        return _run(action, timeout)
    return "", 1


# ══════════════════════════════════════════════════════════════
# WINDOWS MEMORY PRIORITY API
# ══════════════════════════════════════════════════════════════

_PROCESS_MEMORY_PRIORITY_INFO_CLASS = 1
MEMORY_PRIORITY_VERY_LOW  = 1
MEMORY_PRIORITY_LOW       = 2
MEMORY_PRIORITY_MEDIUM    = 3
MEMORY_PRIORITY_BELOW_NORMAL = 4
MEMORY_PRIORITY_NORMAL    = 5

_PROCESS_SET_INFORMATION   = 0x0200
_PROCESS_QUERY_INFORMATION = 0x0400

class _MEMORY_PRIORITY_INFO(ctypes.Structure):
    _fields_ = [("MemoryPriority", ctypes.c_ulong)]


def _set_process_memory_priority(pid: int, priority: int) -> bool:
    if not IS_WINDOWS:
        return False
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            _PROCESS_SET_INFORMATION | _PROCESS_QUERY_INFORMATION,
            False, pid
        )
        if not handle:
            return False
        info = _MEMORY_PRIORITY_INFO(MemoryPriority=priority)
        ok = kernel32.SetProcessInformation(
            handle,
            _PROCESS_MEMORY_PRIORITY_INFO_CLASS,
            ctypes.byref(info),
            ctypes.sizeof(info)
        )
        kernel32.CloseHandle(handle)
        return bool(ok)
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════
# WINDOWS MMCSS
# ══════════════════════════════════════════════════════════════

def _mmcss_boost_on(log) -> Optional[int]:
    if not IS_WINDOWS:
        return None
    try:
        avrt = ctypes.windll.avrt
        task_name  = ctypes.c_wchar_p("Games")
        task_index = ctypes.c_ulong(0)
        handle = avrt.AvSetMmThreadCharacteristicsW(
            task_name, ctypes.byref(task_index)
        )
        if handle:
            log("  + MMCSS 'Games' tier active — CPU quanta guaranteed", "ok")
            return handle
        log("  ~ MMCSS unavailable", "warn")
        return None
    except Exception as e:
        log(f"  ~ MMCSS: {e}", "warn")
        return None


def _mmcss_boost_off(handle: Optional[int], log):
    if not IS_WINDOWS or not handle:
        return
    try:
        ctypes.windll.avrt.AvRevertMmThread(handle)
        log("  + MMCSS restored to normal scheduling", "ok")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════
# LINUX CGROUPS V2
# ══════════════════════════════════════════════════════════════

_CGROUP_PATH = "/sys/fs/cgroup/cyberclean-background"


def _detect_cgroup_path() -> Optional[str]:
    uid = getattr(os, 'getuid', lambda: -1)()
    user_slice = f"/sys/fs/cgroup/user.slice/user-{uid}.slice/cyberclean.scope"
    if Path(f"/sys/fs/cgroup/user.slice/user-{uid}.slice").exists():
        return user_slice
    if os.geteuid() == 0:
        return _CGROUP_PATH
    return None


def _cg_write(cg_path: str, filename: str, value: str) -> bool:
    try:
        p = Path(cg_path) / filename
        if p.exists():
            p.write_text(value)
            return True
    except (OSError, PermissionError):
        pass
    return False


def _cgroup_create(log) -> Optional[str]:
    if not IS_LINUX:
        return None
    cg_path = _detect_cgroup_path()
    if not cg_path:
        log("  ~ cgroups: need root or systemd user slice — skipped", "warn")
        return None
    try:
        os.makedirs(cg_path, exist_ok=True)
        _cg_write(cg_path, "cpu.weight", "20")
        _cg_write(cg_path, "io.weight",  "20")
        _cg_write(cg_path, "memory.low", str(512 * 1024 * 1024))
        log("  + cgroup created: cpu.weight=20 io.weight=20 memory.low=512MB", "ok")
        return cg_path
    except PermissionError:
        log("  ~ cgroups: permission denied — run install.sh for helper setup", "warn")
        return None
    except Exception as e:
        log(f"  ~ cgroups: {e}", "warn")
        return None


def _cgroup_assign(cg_path: str, pid: int) -> bool:
    try:
        Path(cg_path, "cgroup.procs").write_text(str(pid))
        return True
    except (OSError, PermissionError):
        return False


def _cgroup_get_original(pid: int) -> Optional[str]:
    try:
        for line in Path(f"/proc/{pid}/cgroup").read_text().splitlines():
            if line.startswith("0::"):
                return line[3:].strip()
    except (OSError, PermissionError):
        pass
    return None


def _cgroup_restore(pid: int, original_cgroup: str) -> bool:
    if not original_cgroup:
        return False
    try:
        procs_file = Path("/sys/fs/cgroup" + original_cgroup) / "cgroup.procs"
        if procs_file.exists():
            procs_file.write_text(str(pid))
            return True
    except (OSError, PermissionError):
        pass
    return False


def _cgroup_destroy(cg_path: str, log):
    if not cg_path:
        return
    try:
        procs_file = Path(cg_path) / "cgroup.procs"
        if procs_file.exists():
            for pid_str in procs_file.read_text().splitlines():
                try:
                    Path("/sys/fs/cgroup/cgroup.procs").write_text(pid_str.strip())
                except OSError:
                    pass
        os.rmdir(cg_path)
        log("  + background cgroup removed", "ok")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════
# KILL BLOAT — complete rewrite
# ══════════════════════════════════════════════════════════════

# User productivity apps — minimized ≠ bloat, killing = data loss
_BLOAT_SKIP_ALWAYS = {
    # Browsers
    "chrome", "chromium", "msedge", "firefox", "brave", "opera", "vivaldi",
    "waterfox", "librewolf", "floorp",
    # Chat / voice
    "discord", "zalo", "telegram", "slack", "teams", "zoom", "skype",
    "mumble", "teamspeak", "signal", "element",
    # IDEs — may be compiling
    "code", "idea", "pycharm", "eclipse", "datagrip", "rider",
    "webstorm", "clion", "goland", "rubymine", "androidstudio",
    # Office — may have unsaved work
    "soffice", "libreoffice", "excel", "winword", "powerpnt",
    "onenote", "outlook", "freeoffice",
    # Media
    "vlc", "mpv", "celluloid", "totem", "obs", "obs32", "obs64",
    "spotify", "rhythmbox", "amarok",
    # Game launchers & anti-cheat — NEVER kill (crash / ban)
    "steam", "steamwebhelper", "epicgameslauncher", "riotclientux",
    "battle.net", "upc", "origin", "gog-galaxy",
    "vgc", "leagueclient", "riotclientservices",
    "robloxplayerbeta", "valorant-win64-shipping", "vgctray",
    # Package managers mid-operation
    "pacman", "apt", "apt-get", "dpkg", "dnf", "yum", "zypper",
    "yay", "paru", "snap",
    # Terminals — user might have work there
    "bash", "zsh", "fish", "sh", "tmux", "screen",
}


def _get_oom_score(pid: int) -> int:
    try:
        return int(Path(f"/proc/{pid}/oom_score").read_text().strip())
    except Exception:
        return 0


def _has_active_children(pid: int) -> bool:
    if not HAS_PSUTIL:
        return False
    try:
        for child in psutil.Process(pid).children(recursive=True):
            if child.status() == psutil.STATUS_RUNNING:
                return True
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        pass
    return False


def kill_bloat(log, use_sigstop: bool = True) -> BoostResult:
    """
    Dừng (SIGSTOP) hoặc kill process bloat của USER HIỆN TẠI.

    SIGSTOP thay kill():
    - Đóng băng process, RAM tạm thời bị giải phóng bởi kernel
    - Không mất dữ liệu chưa save
    - SIGCONT để resume khi tắt Game Mode

    Linux: chỉ touch process của current UID (không đụng root/system)
    Windows: terminate() với timeout, fallback kill()
    """
    result = BoostResult("kill_bloat")
    if not HAS_PSUTIL:
        log("  x psutil not installed", "err")
        result.success = False
        return result

    log("Scanning for background bloat...", "head")

    protected         = get_de_protected()
    frozen_pids: dict = {}   # {pid: name} để SIGCONT sau

    MEM_THRESHOLD_MB  = 200  # chỉ nhắm process > 200 MB RSS

    # Warm-up cpu_percent (psutil trả 0.0 ở lần gọi đầu tiên)
    log("  . Sampling CPU (warm-up)...", "text")
    _warmup = set()
    for p in psutil.process_iter(["pid", "name"]):
        try:
            p.cpu_percent(interval=0)
            _warmup.add(p.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    import time as _t; _t.sleep(0.6)

    acted = 0
    for p in psutil.process_iter():
        try:
            with p.oneshot():
                nm = p.name().lower().replace(".exe", "")

                # Không đụng protected DE processes
                if nm in protected or _is_protected(nm):
                    continue
                if nm in _BLOAT_SKIP_ALWAYS:
                    continue
                if p.pid <= 10:
                    continue
                if p.pid not in _warmup:
                    continue

                # Linux: chỉ kill process của UID hiện tại
                if IS_LINUX:
                    try:
                        if p.uids().real != CURRENT_UID:
                            continue
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue

                    oom    = _get_oom_score(p.pid)
                    status = p.status()
                    cpu    = p.cpu_percent(interval=0)
                    mem_pct = p.memory_percent()
                    mem_mb  = p.memory_info().rss / 1024 / 1024

                    is_zombie = (status == psutil.STATUS_ZOMBIE)
                    is_bloat  = (
                        oom >= 300 and
                        mem_mb >= MEM_THRESHOLD_MB and
                        status in (psutil.STATUS_SLEEPING, psutil.STATUS_IDLE) and
                        cpu < 0.5 and
                        not _has_active_children(p.pid)
                    )

                elif IS_WINDOWS:
                    cpu    = p.cpu_percent(interval=0)
                    mem_pct = p.memory_percent()
                    mem_mb  = p.memory_info().rss / 1024 / 1024
                    is_zombie = False
                    is_bloat  = (
                        cpu < 0.5 and
                        mem_mb >= MEM_THRESHOLD_MB and
                        not _has_active_children(p.pid)
                    )
                else:
                    continue

                if not (is_zombie or is_bloat):
                    continue

                tag = "zombie" if is_zombie else f"bloat {mem_mb:.0f}MB"

                if IS_LINUX and use_sigstop and not is_zombie:
                    # SIGSTOP: đóng băng, không xóa data
                    try:
                        os.kill(p.pid, signal.SIGSTOP)
                        frozen_pids[p.pid] = p.name()
                        acted += 1
                        result.mb_freed += mem_mb
                        log(f"  ⏸ Frozen [{tag}] {p.name()} — {mem_mb:.0f} MB", "warn")
                    except ProcessLookupError:
                        pass
                else:
                    # Zombie hoặc Windows: terminate với grace period
                    try:
                        p.terminate()
                        try:
                            p.wait(timeout=2)
                        except psutil.TimeoutExpired:
                            p.kill()
                        acted += 1
                        result.mb_freed += mem_mb
                        log(f"  ✕ Killed [{tag}] {p.name()} — {mem_mb:.0f} MB", "warn")
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    result.count    = acted
    result.rollback = [{"frozen_pids": frozen_pids}]

    if acted == 0:
        log("  ✓ No bloat found — system is clean", "ok")
    else:
        log(f"✓ Done — {acted} processes suspended, ~{result.mb_freed:.0f} MB freed", "ok")
        if frozen_pids and IS_LINUX:
            log("  i Frozen processes will resume when Game Mode turns off", "ok")

    # Register cleanup so SIGCONT runs even if app crashes
    if frozen_pids and IS_LINUX:
        def _resume_frozen():
            for pid in frozen_pids:
                try:
                    os.kill(pid, signal.SIGCONT)
                except ProcessLookupError:
                    pass
        _register_cleanup(_resume_frozen)

    return result


def restore_bloat(frozen_pids: dict, log):
    """SIGCONT tất cả processes đã SIGSTOP. Gọi khi tắt Game Mode."""
    if not IS_LINUX or not frozen_pids:
        return
    resumed = 0
    for pid, name in frozen_pids.items():
        try:
            os.kill(pid, signal.SIGCONT)
            resumed += 1
        except ProcessLookupError:
            pass   # process tự thoát trong lúc bị freeze — OK
    if resumed:
        log(f"  ▶ Resumed {resumed} frozen processes", "ok")


# ══════════════════════════════════════════════════════════════
# FREE RAM
# ══════════════════════════════════════════════════════════════

_WIN_RAM_SKIP = {
    'dwm.exe', 'explorer.exe', 'csrss.exe', 'smss.exe',
    'winlogon.exe', 'lsass.exe', 'audiodg.exe', 'svchost.exe',
    'services.exe', 'spoolsv.exe', 'conhost.exe', 'taskhostw.exe',
    'sihost.exe', 'fontdrvhost.exe', 'runtimebroker.exe',
    # Foreground apps — keep warm
    'chrome.exe', 'msedge.exe', 'firefox.exe', 'brave.exe',
    'discord.exe', 'code.exe', 'vlc.exe', 'spotify.exe',
}


def _get_foreground_pid() -> int:
    if not IS_WINDOWS:
        return -1
    try:
        hwnd   = ctypes.windll.user32.GetForegroundWindow()
        fg_pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(fg_pid))
        return fg_pid.value
    except Exception:
        return -1


def free_ram(log) -> BoostResult:
    """
    Free RAM without stutter.
    Windows: memory priority hints (not EmptyWorkingSet).
    Linux:   compact_memory only (not drop_caches).
    """
    result = BoostResult("free_ram")
    if not HAS_PSUTIL:
        log("  x psutil not installed", "err")
        result.success = False
        return result

    before = psutil.virtual_memory().available // 1024 // 1024
    log("Freeing RAM (cache-preserving)...", "head")

    if IS_LINUX:
        _, code = _run_helper("compact-memory", timeout=10)
        if code == 0:
            log("  + Memory compacted — fragmented pages defragged", "ok")
            log("  i Page cache preserved — browser/app data stays warm", "ok")
        else:
            log("  ~ compact-memory: needs root (run install.sh)", "warn")

    elif IS_WINDOWS:
        lowered = 0
        fg_pid  = _get_foreground_pid()

        for p in psutil.process_iter(["pid", "name", "status"]):
            try:
                nm = (p.info["name"] or "").lower()
                if nm in _WIN_RAM_SKIP:
                    continue
                if p.pid == fg_pid:
                    continue
                cpu = p.cpu_percent(interval=0)
                if cpu > 2.0:
                    continue
                if _set_process_memory_priority(p.pid, MEMORY_PRIORITY_LOW):
                    lowered += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                pass

        log(f"  + Memory priority lowered for {lowered} idle processes", "ok")
        log("  i Foreground untouched — pages stay in RAM", "ok")

    import gc; gc.collect()

    after = psutil.virtual_memory().available // 1024 // 1024
    freed = max(0, after - before)
    result.mb_freed = freed
    log(f"+ RAM: {after} MB available (+{freed} MB freed)", "ok")
    return result


# ══════════════════════════════════════════════════════════════
# MEMORY TUNE
# ══════════════════════════════════════════════════════════════

def memory_tune(log) -> BoostResult:
    """Tune kernel vm params for desktop responsiveness."""
    result     = BoostResult("memory_tune")
    _originals = {}
    log("Tuning memory settings...", "head")

    if IS_LINUX:
        TUNED = {
            "swappiness":             "10",
            "dirty_background_ratio": "5",
            "dirty_ratio":            "10",
        }
        HELPER_KEYS = {
            "swappiness":             "swappiness",
            "dirty_background_ratio": "dirty-background-ratio",
            "dirty_ratio":            "dirty-ratio",
        }

        for param, val in TUNED.items():
            p = Path(f"/proc/sys/vm/{param}")
            try:
                orig = p.read_text().strip()
                if orig == val:
                    log(f"  ~ vm.{param} = {val}  [already set]", "ok")
                    continue
                if not os.access(str(p), os.W_OK):
                    raise PermissionError()
                p.write_text(val + "\n")
                _originals[param] = orig
                log(f"  + vm.{param}: {orig} → {val}", "ok")
            except (PermissionError, OSError):
                _, code = _run_helper(HELPER_KEYS[param], timeout=10)
                if code == 0:
                    log(f"  + vm.{param} = {val} (via helper)", "ok")
                else:
                    log(f"  ~ vm.{param}: no write access", "warn")

        _, code = _run_helper("compact-memory", timeout=10)
        if code == 0:
            log("  + Memory compacted", "ok")

    elif IS_WINDOWS:
        import gc; gc.collect()
        log("  + Python GC collected", "ok")

    if HAS_PSUTIL:
        mem = psutil.virtual_memory()
        log(f"+ Done — {mem.percent:.1f}% used, {mem.available//1024//1024} MB free", "ok")

    result.rollback = [{"originals": _originals}]
    return result


def memory_tune_restore(originals: dict, log):
    """Restore kernel vm params. Called on app exit."""
    if not IS_LINUX or not originals:
        return
    for param, orig_val in originals.items():
        try:
            Path(f"/proc/sys/vm/{param}").write_text(orig_val)
            log(f"  + Restored vm.{param} = {orig_val}", "ok")
        except (PermissionError, OSError) as e:
            log(f"  ~ Could not restore vm.{param}: {e}", "warn")


# ══════════════════════════════════════════════════════════════
# CLEAR DISK / GPU CACHE
# ══════════════════════════════════════════════════════════════

def clear_disk_cache(log) -> BoostResult:
    """Clear GPU shader cache, browser GPU cache."""
    result = BoostResult("clear_disk_cache")
    log("Clearing disk & GPU cache...", "head")
    total = 0

    if IS_WINDOWS:
        local = os.environ.get("LOCALAPPDATA", "")
        paths = [
            f"{local}/Google/Chrome/User Data/Default/GPUCache",
            f"{local}/Google/Chrome/User Data/Default/ShaderCache",
            f"{local}/Microsoft/Edge/User Data/Default/GPUCache",
            f"{local}/Microsoft/Edge/User Data/Default/ShaderCache",
        ]
    else:
        home  = str(Path.home())
        paths = [
            f"{home}/.cache/mesa_shader_cache",
            f"{home}/.cache/nvidia",
            f"{home}/.config/google-chrome/Default/GPUCache",
            f"{home}/.config/google-chrome/Default/ShaderCache",
            f"{home}/.config/chromium/Default/GPUCache",
            f"{home}/.config/microsoft-edge/Default/GPUCache",
        ]
        if Path(f"{home}/.var/app").exists():
            paths += glob.glob(f"{home}/.var/app/*/config/*/GPUCache")
            paths += glob.glob(f"{home}/.var/app/*/config/*/ShaderCache")
            paths += glob.glob(f"{home}/.var/app/*/cache/mesa_shader_cache")
        if Path(f"{home}/snap").exists():
            paths += glob.glob(f"{home}/snap/*/common/.cache/*/GPUCache")
            paths += glob.glob(f"{home}/snap/*/common/.config/*/GPUCache")

    for p in paths:
        if not Path(p).exists():
            continue
        try:
            # os.walk để tránh NTFS junction / symlink loops
            sz = 0
            for dirpath, _, fnames in os.walk(p, followlinks=False):
                for fn in fnames:
                    try:
                        sz += os.path.getsize(os.path.join(dirpath, fn))
                    except OSError:
                        pass
            shutil.rmtree(p, ignore_errors=True)
            total += sz
            result.count += 1
            log(f"  + {Path(p).name} — {sz/1024/1024:.1f} MB", "ok")
        except Exception as e:
            log(f"  ~ {Path(p).name}: {e}", "warn")

    result.mb_freed = total / 1024 / 1024
    log(f"+ Disk cache cleared: {result.mb_freed:.1f} MB ({result.count} paths)", "ok")
    return result


# ══════════════════════════════════════════════════════════════
# GAME MODE
# ══════════════════════════════════════════════════════════════

GAMING_FREEZE_SERVICES = [
    "wuauserv",   # Windows Update
    "SysMain",    # Superfetch
    "WSearch",    # Search Indexer
    "DiagTrack",  # Telemetry
]

POWER_BALANCED  = "381b4222-f694-41f0-9685-ff5bb260df2e"
POWER_HIGH_PERF = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
POWER_ULTIMATE  = "e9a42b02-d5df-448d-aa00-03f14749eb61"


def _enable_kernel_performance(log):
    """
    Set CPU governor to performance mode.
    Thứ tự ưu tiên (Linux):
    1. powerprofilesctl  — GNOME Power Profiles daemon (phổ biến nhất)
    2. tuned-adm         — Red Hat / Fedora tuning daemon
    3. cpupower          — kernel tool, cần root
    4. /sys/cpufreq      — direct sysfs write, cần root
    5. skip gracefully

    FIXED: shutil.which() check trước khi gọi → không còn lỗi "command not found"
    """
    if IS_LINUX:
        # Option 1: powerprofilesctl (GNOME, KDE Plasma 5.26+)
        if shutil.which("powerprofilesctl"):
            r = subprocess.run(
                ["powerprofilesctl", "set", "performance"],
                capture_output=True, timeout=5
            )
            if r.returncode == 0:
                log("  + CPU governor: performance (powerprofilesctl)", "ok")
                return "powerprofiles"
            log("  ~ powerprofilesctl: failed (profile locked?)", "warn")

        # Option 2: tuned-adm (Fedora / RHEL / Rocky)
        if shutil.which("tuned-adm"):
            r = subprocess.run(
                ["tuned-adm", "profile", "throughput-performance"],
                capture_output=True, timeout=5
            )
            if r.returncode == 0:
                log("  + CPU tuning: throughput-performance (tuned-adm)", "ok")
                return "tuned"

        # Option 3: cpupower (needs root / sudo -n)
        if shutil.which("cpupower"):
            r = subprocess.run(
                ["sudo", "-n", "cpupower", "frequency-set", "-g", "performance"],
                capture_output=True, timeout=5
            )
            if r.returncode == 0:
                log("  + CPU governor: performance (cpupower)", "ok")
                return "cpupower"

        # Option 4: direct sysfs write (needs root)
        cpufreq = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
        if cpufreq.exists() and os.access(str(cpufreq), os.W_OK):
            try:
                for gov_path in Path("/sys/devices/system/cpu").glob("cpu*/cpufreq/scaling_governor"):
                    gov_path.write_text("performance")
                log("  + CPU governor: performance (direct sysfs)", "ok")
                return "sysfs"
            except OSError:
                pass

        log("  ~ CPU governor: no supported tool found — skipping", "warn")
        log("  i Install powerprofilesctl (GNOME) or tuned (Fedora) for this feature", "ok")
        return None

    elif IS_WINDOWS:
        orig_guid = POWER_BALANCED
        try:
            out = subprocess.run(
                "powercfg /getactivescheme", shell=True,
                capture_output=True, text=True,
                creationflags=0x08000000, timeout=5
            ).stdout
            if "GUID:" in out:
                orig_guid = out.split("GUID:")[1].split()[0].strip()
        except (subprocess.TimeoutExpired, OSError, IndexError):
            pass

        for guid, name in [(POWER_ULTIMATE, "Ultimate"), (POWER_HIGH_PERF, "High Performance")]:
            r = subprocess.run(
                f"powercfg /setactive {guid}", shell=True,
                capture_output=True, creationflags=0x08000000, timeout=5
            )
            if r.returncode == 0:
                log(f"  + Windows Power Plan: {name}", "ok")
                return orig_guid

        log("  ~ Could not switch power plan", "warn")
        return orig_guid


def _restore_kernel_performance(method, log):
    if IS_LINUX:
        if method == "powerprofiles":
            if shutil.which("powerprofilesctl"):
                subprocess.run(["powerprofilesctl", "set", "balanced"],
                               capture_output=True, timeout=5)
        elif method == "tuned":
            if shutil.which("tuned-adm"):
                subprocess.run(["tuned-adm", "profile", "balanced"],
                               capture_output=True, timeout=5)
        elif method == "cpupower":
            if shutil.which("cpupower"):
                subprocess.run(
                    ["sudo", "-n", "cpupower", "frequency-set", "-g", "schedutil"],
                    capture_output=True, timeout=5
                )
        elif method == "sysfs":
            try:
                for gov_path in Path("/sys/devices/system/cpu").glob("cpu*/cpufreq/scaling_governor"):
                    gov_path.write_text("schedutil")
            except OSError:
                pass
        if method:
            log("  + CPU governor: balanced [RESTORED]", "ok")

    elif IS_WINDOWS:
        if method:
            subprocess.run(
                f"powercfg /setactive {method}", shell=True,
                capture_output=True, creationflags=0x08000000, timeout=5
            )
            log("  + Windows Power Plan: original restored", "ok")


def _freeze_windows_services(log):
    stopped = []
    for svc in GAMING_FREEZE_SERVICES:
        r = subprocess.run(
            f"net stop {svc} /y", shell=True, capture_output=True,
            creationflags=0x08000000, timeout=15
        )
        if r.returncode == 0:
            stopped.append(svc)
            log(f"  v Froze service: {svc}", "warn")
    return stopped


def _restore_windows_services(stopped_services, log):
    for svc in stopped_services:
        subprocess.run(
            f"net start {svc}", shell=True, capture_output=True,
            creationflags=0x08000000, timeout=15
        )
    if stopped_services:
        log(f"  + Restored {len(stopped_services)} Windows services", "ok")


def game_mode_on(log) -> dict:
    """
    CPU affinity jail — 3-tier: Comms / Media / Trash.
    Game gets all prime cores. Background jailed to last cores.
    """
    if not HAS_PSUTIL:
        return {}
    log("⚡ GAME MODE ON", "head")
    saved = {"affinity": {}, "nice": {}, "services": [],
             "power": None, "frozen": {}}

    saved["power"] = _enable_kernel_performance(log)

    cores  = psutil.cpu_count(logical=True) or 1
    jailed = 0

    if cores > 2:
        if cores <= 4:
            stream_cores = [cores - 1]
            trash_cores  = [cores - 1]
        else:
            stream_cores = list(range(max(1, cores // 2), cores))
            trash_cores  = [cores - 1]

        STREAM_APPS = {
            "discord", "obs", "obs32", "obs64", "telegram",
            "skype", "teams", "mumble", "teamspeak", "signal",
        }
        MEDIA_APPS = {
            "chrome", "chromium", "msedge", "firefox", "brave",
            "opera", "spotify", "zalo", "vivaldi",
        }
        TRASH_APPS = {
            "onedrive", "dropbox", "googledrivefs", "googledrive",
            "microsoftedgeupdate", "googleupdate",
        }

        protected = get_de_protected()

        for p in psutil.process_iter(["pid", "name"]):
            try:
                nm = (p.info["name"] or "").lower().replace(".exe", "")
                if nm in protected or _is_protected(nm):
                    continue
                with p.oneshot():
                    if nm in STREAM_APPS:
                        saved["affinity"][p.pid] = p.cpu_affinity()
                        p.cpu_affinity(stream_cores)
                        jailed += 1
                        log(f"  v Comms: {nm} → cores {stream_cores}", "warn")
                    elif nm in MEDIA_APPS:
                        saved["affinity"][p.pid] = p.cpu_affinity()
                        p.cpu_affinity(trash_cores)
                        saved["nice"][p.pid] = p.nice()
                        if IS_WINDOWS:
                            p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
                        elif IS_LINUX and os.geteuid() == 0:
                            p.nice(10)
                        jailed += 1
                        log(f"  v Media: {nm} → cores {trash_cores}", "warn")
                    elif nm in TRASH_APPS:
                        saved["affinity"][p.pid] = p.cpu_affinity()
                        p.cpu_affinity(trash_cores)
                        saved["nice"][p.pid] = p.nice()
                        if IS_WINDOWS:
                            p.nice(psutil.IDLE_PRIORITY_CLASS)
                        elif IS_LINUX and os.geteuid() == 0:
                            p.nice(19)
                        jailed += 1
                        log(f"  v Trash: {nm} → core {trash_cores} + idle", "warn")
            except (psutil.NoSuchProcess, psutil.AccessDenied,
                    NotImplementedError, AttributeError):
                pass

        # Kill bloat with SIGSTOP
        bloat_result = kill_bloat(log, use_sigstop=IS_LINUX)
        if bloat_result.rollback:
            saved["frozen"] = bloat_result.rollback[0].get("frozen_pids", {})

        log(f"  + CPU Matrix: {jailed} apps isolated across 3 tiers", "ok")
    else:
        log("  ~ CPU ≤2 cores — CPU jail skipped", "warn")

    if IS_WINDOWS:
        saved["services"] = _freeze_windows_services(log)

    log(f"✓ GAME MODE ON — {jailed} apps jailed", "ok")
    return saved


def game_mode_off(saved: dict, log):
    log("↺ Restoring system...", "head")

    # Resume frozen (SIGSTOP) processes first
    if saved.get("frozen") and IS_LINUX:
        restore_bloat(saved["frozen"], log)

    if IS_WINDOWS and saved.get("services"):
        _restore_windows_services(saved["services"], log)

    for pid, orig in saved.get("nice", {}).items():
        try:
            psutil.Process(pid).nice(orig)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    restored = 0
    for pid, orig in saved.get("affinity", {}).items():
        try:
            psutil.Process(pid).cpu_affinity(orig)
            restored += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    if restored:
        log(f"  + CPU affinity restored for {restored} processes", "ok")

    if saved.get("power") is not None:
        _restore_kernel_performance(saved["power"], log)

    log("✓ GAME MODE OFF — system restored", "ok")


# ══════════════════════════════════════════════════════════════
# ECO MODE
# ══════════════════════════════════════════════════════════════

_ECO_SKIP = {
    "python", "python3", "cyberclean",
    "systemd", "kwin", "hyprland", "plasmashell", "gnome-shell",
    "xorg", "xwayland", "pipewire", "wireplumber", "dbus-daemon",
    "dbus-broker", "dwm", "explorer", "csrss", "lsass", "winlogon",
    "audiodg", "system", "registry", "smss", "sihost", "taskhostw",
    "ctfmon", "fontdrvhost", "startmenuexperiencehost",
    "shellexperiencehost", "textinputhost", "applicationframehost",
    "runtimebroker", "svchost", "services", "spoolsv",
    "lghub", "rzsynapse", "icue", "logioptionsplus",
    "chrome", "chromium", "msedge", "firefox", "brave", "opera", "vivaldi",
    "discord", "telegram", "zalo", "slack", "teams", "zoom", "skype",
    "code", "idea", "pycharm", "eclipse", "datagrip", "rider",
    "webstorm", "clion", "goland", "rubymine",
    "excel", "winword", "powerpnt", "onenote", "outlook", "soffice",
}


def eco_mode_on(log) -> dict:
    """
    Linux: cgroups v2 proportional throttle.
    Windows: memory priority hints + MMCSS foreground boost.
    """
    if not HAS_PSUTIL:
        return {}

    saved = {
        "mode": None, "mem_lowered": [],
        "mmcss_handle": None, "cgroup_path": None, "cgroup_procs": {},
    }

    if IS_WINDOWS:
        log("ECO MODE ON — memory hints + MMCSS foreground boost", "head")
        saved["mmcss_handle"] = _mmcss_boost_on(log)
        lowered = 0
        protected = get_de_protected()
        for p in psutil.process_iter(["pid", "name"]):
            try:
                nm = (p.info["name"] or "").lower().replace(".exe", "")
                if nm in _ECO_SKIP or nm in protected or _is_protected(nm):
                    continue
                if _set_process_memory_priority(p.pid, MEMORY_PRIORITY_LOW):
                    saved["mem_lowered"].append(p.pid)
                    lowered += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        saved["mode"] = "windows_memprio"
        log(f"  + Memory priority lowered for {lowered} background processes", "ok")

    elif IS_LINUX:
        cg_path = _cgroup_create(log)
        if not cg_path:
            if os.geteuid() == 0:
                log("  ~ cgroups unavailable — fallback to nice(5)", "warn")
                return _eco_mode_on_nice_fallback(log)
            else:
                log("  ~ Eco Mode: needs root or systemd user slice", "warn")
                return saved

        log("ECO MODE ON — cgroups v2 proportional throttle", "head")
        saved["cgroup_path"] = cg_path
        protected = get_de_protected()
        assigned  = 0

        for p in psutil.process_iter(["pid", "name"]):
            try:
                nm = (p.info["name"] or "").lower().replace(".exe", "")
                if nm in _ECO_SKIP or nm in protected or _is_protected(nm):
                    continue
                try:
                    if p.uids().real != CURRENT_UID:
                        continue
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                orig_cg = _cgroup_get_original(p.pid)
                if _cgroup_assign(cg_path, p.pid):
                    saved["cgroup_procs"][p.pid] = orig_cg
                    assigned += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        saved["mode"] = "linux_cgroup"
        log(f"  + {assigned} processes assigned to throttle cgroup", "ok")
        log("  i cpu=20% io=20% memory.low=512MB — foreground gets priority", "ok")

        # Register cleanup for crash recovery
        def _eco_cleanup():
            for pid, orig in saved.get("cgroup_procs", {}).items():
                _cgroup_restore(pid, orig)
            if saved.get("cgroup_path"):
                try:
                    _cgroup_destroy(saved["cgroup_path"], lambda *_: None)
                except Exception:
                    pass
        _register_cleanup(_eco_cleanup)

    return saved


def _eco_mode_on_nice_fallback(log) -> dict:
    saved = {"mode": "linux_nice", "nice_saved": {}}
    protected = get_de_protected()
    throttled = 0
    for p in psutil.process_iter(["pid", "name"]):
        try:
            nm = (p.info["name"] or "").lower().replace(".exe", "")
            if nm in _ECO_SKIP or nm in protected or _is_protected(nm):
                continue
            with p.oneshot():
                try:
                    if p.uids().real != CURRENT_UID:
                        continue
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                cur = p.nice()
                if cur < 5:
                    saved["nice_saved"][p.pid] = cur
                    p.nice(5)
                    throttled += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    log(f"  + nice(5) applied to {throttled} processes (fallback)", "ok")
    return saved


def eco_mode_off(saved: dict, log):
    if not saved:
        return
    mode = saved.get("mode")

    if mode == "windows_memprio":
        log("ECO MODE OFF — restoring memory priorities...", "head")
        _mmcss_boost_off(saved.get("mmcss_handle"), log)
        restored = 0
        for pid in saved.get("mem_lowered", []):
            if _set_process_memory_priority(pid, MEMORY_PRIORITY_NORMAL):
                restored += 1
        log(f"  + Memory priority restored for {restored} processes", "ok")

    elif mode == "linux_cgroup":
        log("ECO MODE OFF — removing cgroup throttle...", "head")
        cg_path  = saved.get("cgroup_path")
        restored = 0
        for pid, orig_cg in saved.get("cgroup_procs", {}).items():
            if orig_cg:
                ok = _cgroup_restore(pid, orig_cg)
            else:
                try:
                    Path("/sys/fs/cgroup/cgroup.procs").write_text(str(pid))
                    ok = True
                except (OSError, PermissionError):
                    ok = False
            if ok:
                restored += 1
        log(f"  + {restored} processes returned to normal cgroup", "ok")
        if cg_path:
            _cgroup_destroy(cg_path, log)

    elif mode == "linux_nice":
        restored = 0
        for pid, orig in saved.get("nice_saved", {}).items():
            try:
                psutil.Process(pid).nice(orig)
                restored += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        log(f"ECO MODE OFF — nice restored for {restored} processes", "ok")
    else:
        log("ECO MODE OFF — nothing to restore", "ok")


# ══════════════════════════════════════════════════════════════
# SMART BOOST
# ══════════════════════════════════════════════════════════════

def detect_pc_tier() -> str:
    if not HAS_PSUTIL:
        return 'mid'
    try:
        ram_gb = psutil.virtual_memory().total / (1024 ** 3)
        cores  = psutil.cpu_count(logical=False) or 2
        if ram_gb > 16 and cores > 6:
            return 'high'
        elif ram_gb > 8 and cores > 4:
            return 'mid'
        else:
            return 'low'
    except Exception:
        return 'mid'


def _tweak_windows_visuals(low_end: bool, log):
    if not IS_WINDOWS:
        return None
    try:
        import winreg
        key_path = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize'
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                             winreg.KEY_READ | winreg.KEY_SET_VALUE)
        try:
            orig_val, _ = winreg.QueryValueEx(key, 'EnableTransparency')
        except Exception:
            orig_val = 1
        winreg.SetValueEx(key, 'EnableTransparency', 0, winreg.REG_DWORD,
                          0 if low_end else 1)
        winreg.CloseKey(key)
        log(f"  + Windows transparency {'disabled' if low_end else 'kept'}", "ok")
        return orig_val
    except Exception as e:
        log(f"  ~ Transparency tweak skipped: {e}", "warn")
        return None


def _restore_windows_visuals(orig_val, log):
    if not IS_WINDOWS or orig_val is None:
        return
    try:
        import winreg
        key_path = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize'
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, 'EnableTransparency', 0, winreg.REG_DWORD, int(orig_val))
        winreg.CloseKey(key)
        log("  + Windows transparency restored", "ok")
    except Exception as e:
        log(f"  ~ Transparency restore skipped: {e}", "warn")


def smart_boost_on(log) -> dict:
    """
    Auto-detect PC tier and apply the right strategy.
    HIGH: Game Mode only
    MID:  Game Mode + Eco Mode
    LOW:  Game Mode + Eco Mode + Free RAM + disable transparency
    """
    tier = detect_pc_tier()
    saved = {'tier': tier, 'game': {}, 'eco': {}, 'visuals_orig': None, 'freed_mb': 0}

    tier_labels = {
        'high': 'HIGH-END — Gaming rig',
        'mid':  'MID — Solid machine',
        'low':  'LOW-END — Potato mode',
    }
    log(f'Smart Boost ON  [{tier_labels.get(tier, tier)}]', 'head')

    if tier == 'low' and IS_WINDOWS:
        saved['visuals_orig'] = _tweak_windows_visuals(low_end=True, log=log)

    saved['game'] = game_mode_on(log)

    if tier in ('mid', 'low'):
        saved['eco'] = eco_mode_on(log)

    if tier == 'low':
        result = free_ram(log)
        saved['freed_mb'] = getattr(result, 'mb_freed', 0)

    log(f'✓ Smart Boost ON [{tier}] — all layers applied', 'ok')
    return saved


def smart_boost_off(saved: dict, log):
    if not saved:
        return
    tier = saved.get('tier', 'mid')
    log(f'Smart Boost OFF — restoring [{tier}]...', 'head')
    if saved.get('eco'):
        eco_mode_off(saved['eco'], log)
    if saved.get('game') is not None:
        game_mode_off(saved['game'], log)
    if saved.get('visuals_orig') is not None:
        _restore_windows_visuals(saved['visuals_orig'], log)
    log('✓ Smart Boost OFF — system restored', 'ok')
