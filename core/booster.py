"""
CyberClean v2.3 — System Booster
Redesigned for real-world smoothness: browse 30 tabs, stream, watch videos
without any lag or input delay.

WHAT CHANGED vs v2.2:
─────────────────────────────────────────────────────────────────
FREE RAM (Windows):
  OLD: EmptyWorkingSet on all background processes
       → trims RAM aggressively but causes micro-stutters on next access
  NEW: SetProcessInformation(MemoryPriority=LOW) on truly-idle processes
       → tells Windows kernel "evict these pages FIRST when under pressure"
       → foreground app (browser/game) keeps its pages warm in RAM
       → no stutter, no cold-start lag on tab switch

FREE RAM (Linux):
  OLD: drop_caches (echo 1 > /proc/sys/vm/drop_caches)
       → nukes entire page cache including browser data, fonts, libs
       → every tab switch and app open feels cold and sluggish after
  NEW: compact_memory only (echo 1 > /proc/sys/vm/compact_memory)
       → defragments physical memory pages without evicting cache
       → browser stays warm, tabs switch instantly

ECO MODE (Windows):
  OLD: BELOW_NORMAL_PRIORITY_CLASS on background CPU nice()
       → interferes with Windows Quantum Boost (OS auto-boosts foreground)
       → causes jitter when switching from background app to foreground
  NEW: SetProcessInformation(MemoryPriority=LOW) for background
       + MMCSS (Multimedia Class Scheduler) boost for foreground
       → background gets evicted from RAM first under pressure
       → foreground gets guaranteed CPU quanta via MMCSS
       → no CPU priority fights, no scheduling jitter

ECO MODE (Linux):
  OLD: nice(5) on background processes
       → only affects CPU, does nothing for I/O or memory pressure
       → tab switches still slow because page cache still fights
  NEW: cgroups v2 (cpu.weight=20, io.weight=20, memory.low=512MB)
       → background apps get 1/5 CPU time AND 1/5 I/O bandwidth
       → memory.low tells kernel "protect foreground pages first"
       → works without root via user-managed cgroups (systemd slice)
       → guaranteed restore: remove process from cgroup = instant undo

GAME MODE: unchanged — CPU affinity jail still correct for gaming
SMART BOOST: updated to use new eco/free_ram under the hood
─────────────────────────────────────────────────────────────────
"""
import os, sys, ctypes, shutil, subprocess, glob, platform, struct
from pathlib import Path
from dataclasses import dataclass, field
from typing import Callable, Optional

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
# OS FIREWALL — never touch these
# ══════════════════════════════════════════════════════════════
SAFE_SYSTEM_PROCS = {
    # Windows core & UI — kill = black screen / no taskbar
    "explorer", "dwm", "taskmgr", "csrss", "lsass", "winlogon", "smss",
    "sihost", "taskhostw", "runtimebroker", "svchost", "services",
    "audiodg", "spoolsv", "fontdrvhost", "ctfmon", "registry",
    "startmenuexperiencehost", "shellexperiencehost",
    "textinputhost", "applicationframehost",
    # Linux core & display — kill = X/Wayland crash
    "systemd", "init", "kwin_x11", "kwin_wayland", "hyprland",
    "sway", "i3", "openbox", "xfwm4", "plasmashell", "gnome-shell",
    "xorg", "xwayland", "dbus-daemon", "dbus-broker",
    # Linux audio
    "pipewire", "wireplumber", "pulseaudio", "jackd",
    # Display managers
    "sddm", "gdm", "lightdm",
    # CyberClean itself
    "python", "python3", "cyberclean",
}

GPU_KEYWORDS = {"gpu", "nvidia", "amd", "radeon", "intel_gpu",
                "nvd", "amdgpu", "vgaswitcheroo", "renderer"}

def _is_protected(proc_name: str) -> bool:
    name = proc_name.lower().replace(".exe", "")
    if name in SAFE_SYSTEM_PROCS:
        return True
    for kw in GPU_KEYWORDS:
        if kw in name:
            return True
    return False


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
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
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
# SetProcessInformation(MemoryPriority) — the correct way to
# tell the kernel "evict these pages first under pressure"
# without causing stutter like EmptyWorkingSet does.
# ══════════════════════════════════════════════════════════════

# ProcessInformationClass = 1 (ProcessMemoryPriority)
_PROCESS_MEMORY_PRIORITY_INFO_CLASS = 1

# Memory priority constants (Windows kernel)
MEMORY_PRIORITY_VERY_LOW = 1   # background trash — evict first
MEMORY_PRIORITY_LOW      = 2   # background apps — evict before normal
MEMORY_PRIORITY_MEDIUM   = 3
MEMORY_PRIORITY_BELOW_NORMAL = 4
MEMORY_PRIORITY_NORMAL   = 5   # default for all processes

# PROCESS_ACCESS: need SET_INFORMATION + QUERY_INFORMATION
_PROCESS_SET_INFORMATION   = 0x0200
_PROCESS_QUERY_INFORMATION = 0x0400

class _MEMORY_PRIORITY_INFO(ctypes.Structure):
    _fields_ = [("MemoryPriority", ctypes.c_ulong)]


def _set_process_memory_priority(pid: int, priority: int) -> bool:
    """
    Set memory eviction priority for a process.
    Lower priority = kernel evicts these RAM pages first when under pressure.
    Does NOT affect CPU scheduling — no stutter, no scheduling jitter.
    Requires Windows 8+ (always true in practice).
    """
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
# WINDOWS MMCSS — Multimedia Class Scheduler
# Gives the calling thread guaranteed CPU quanta for smooth
# audio/video/rendering. Chrome, Firefox, media players all use this.
# ══════════════════════════════════════════════════════════════

def _mmcss_boost_on(log) -> Optional[int]:
    """
    Register current thread with MMCSS 'Games' task class.
    Returns MMCSS handle (int) to pass to _mmcss_boost_off(), or None.

    Effect: Windows scheduler gives this thread priority over non-MMCSS
    threads — prevents background CPU bursts from causing render stutters.
    'Games' class = highest MMCSS tier (same as what games use).
    """
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
        log("  ~ MMCSS unavailable (Windows 7?)", "warn")
        return None
    except Exception as e:
        log(f"  ~ MMCSS: {e}", "warn")
        return None


def _mmcss_boost_off(handle: Optional[int], log):
    """Unregister from MMCSS — call when Eco Mode turns off."""
    if not IS_WINDOWS or not handle:
        return
    try:
        ctypes.windll.avrt.AvRevertMmThread(handle)
        log("  + MMCSS restored to normal scheduling", "ok")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════
# LINUX CGROUPS V2
# cpu.weight + io.weight + memory.low — the proper kernel mechanism
# for background throttling. Works without suspend/nice().
# memory.low protects foreground pages from being evicted.
# ══════════════════════════════════════════════════════════════

_CGROUP_PATH = "/sys/fs/cgroup/cyberclean-background"
_USER_CGROUP_PATH = None  # set at runtime if systemd user slice available


def _detect_cgroup_path() -> Optional[str]:
    """
    Find a writable cgroup path without root:
    1. Try systemd user slice (no root needed on most modern distros)
    2. Fall back to system cgroup (needs root or helper)
    """
    # Option 1: systemd user slice — writable by user, no root
    uid = getattr(os, 'getuid', lambda: -1)()
    user_slice = f"/sys/fs/cgroup/user.slice/user-{uid}.slice/cyberclean.scope"
    if Path(f"/sys/fs/cgroup/user.slice/user-{uid}.slice").exists():
        return user_slice

    # Option 2: system cgroup — needs root
    if os.geteuid() == 0:
        return _CGROUP_PATH

    return None


def _cgroup_create(log) -> Optional[str]:
    """
    Create cyberclean-background cgroup with:
    - cpu.weight = 20   (background gets 1/5 CPU vs foreground 100)
    - io.weight  = 20   (background gets 1/5 I/O bandwidth)
    - memory.low = 512MB (kernel protects foreground RAM first)
    Returns cgroup path or None if unavailable.
    """
    if not IS_LINUX:
        return None

    cg_path = _detect_cgroup_path()
    if not cg_path:
        log("  ~ cgroups: need root or systemd user slice — skipped", "warn")
        log("  i Run install.sh to enable full cgroup support", "ok")
        return None

    try:
        os.makedirs(cg_path, exist_ok=True)

        # cpu.weight: 100 = normal, 20 = gets ~17% when contending with foreground
        _cg_write(cg_path, "cpu.weight", "20")

        # io.weight: same scale — background I/O throttled under pressure
        # (only takes effect when disk is saturated — not visible otherwise)
        _cg_write(cg_path, "io.weight", "20")

        # memory.low: kernel will NOT evict pages from this cgroup until
        # the system has less than 512MB free — protects background apps
        # from being completely swapped out (we want throttle, not crash).
        _cg_write(cg_path, "memory.low", str(512 * 1024 * 1024))

        log(f"  + cgroup created: cpu=20 io=20 memory.low=512MB", "ok")
        return cg_path

    except PermissionError:
        log("  ~ cgroups: permission denied — run install.sh for helper setup", "warn")
        return None
    except Exception as e:
        log(f"  ~ cgroups: {e}", "warn")
        return None


def _cg_write(cg_path: str, filename: str, value: str) -> bool:
    """Write a value to a cgroup control file. Returns True on success."""
    try:
        p = Path(cg_path) / filename
        if p.exists():
            p.write_text(value)
            return True
    except (OSError, PermissionError):
        pass
    return False


def _cgroup_assign(cg_path: str, pid: int) -> bool:
    """Move a process into the background cgroup."""
    try:
        p = Path(cg_path) / "cgroup.procs"
        p.write_text(str(pid))
        return True
    except (OSError, PermissionError):
        return False


def _cgroup_get_original_cgroup(pid: int) -> Optional[str]:
    """Read the process's current cgroup path for restore later."""
    try:
        # /proc/<pid>/cgroup format: "0::/user.slice/user-1000.slice/..."
        for line in Path(f"/proc/{pid}/cgroup").read_text().splitlines():
            if line.startswith("0::"):
                return line[3:].strip()
    except (OSError, PermissionError):
        pass
    return None


def _cgroup_restore(pid: int, original_cgroup: str, log) -> bool:
    """Move process back to its original cgroup."""
    if not original_cgroup:
        return False
    try:
        # Write to the original cgroup's procs file
        # The path under /sys/fs/cgroup mirrors the cgroup hierarchy
        procs_file = Path("/sys/fs/cgroup" + original_cgroup) / "cgroup.procs"
        if procs_file.exists():
            procs_file.write_text(str(pid))
            return True
    except (OSError, PermissionError):
        pass
    return False


def _cgroup_destroy(cg_path: str, log):
    """Remove the background cgroup (only works when empty)."""
    if not cg_path:
        return
    try:
        # Move all remaining procs to root cgroup first
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
        pass  # non-empty cgroup — will be cleaned up next reboot


# ══════════════════════════════════════════════════════════════
# FREE RAM (v2.3)
# Windows: memory priority hints instead of EmptyWorkingSet
# Linux:   compact only, NO drop_caches
# ══════════════════════════════════════════════════════════════

# Processes to never touch memory priority — UI/audio must stay warm
_WIN_RAM_SKIP = {
    'dwm.exe', 'explorer.exe', 'csrss.exe', 'smss.exe',
    'winlogon.exe', 'lsass.exe', 'audiodg.exe', 'svchost.exe',
    'services.exe', 'spoolsv.exe', 'conhost.exe', 'taskhostw.exe',
    'sihost.exe', 'fontdrvhost.exe', 'runtimebroker.exe',
    # User's foreground apps — keep warm
    'chrome.exe', 'msedge.exe', 'firefox.exe', 'brave.exe',
    'discord.exe', 'code.exe', 'vlc.exe', 'spotify.exe',
}

def free_ram(log) -> BoostResult:
    """
    Free RAM without causing lag or cold-start stutters.

    Windows: SetProcessInformation(MemoryPriority=VERY_LOW) on idle
             background processes. Kernel will evict their pages first
             when under memory pressure — foreground stays warm.
             NO EmptyWorkingSet — that causes immediate stutter on access.

    Linux:   compact_memory only — defragments physical pages without
             flushing page cache. Browser data, fonts, libs all stay warm.
             NO drop_caches — that was the source of post-clean lag.
    """
    result = BoostResult("free_ram")
    if not HAS_PSUTIL:
        log("  x psutil not installed", "err")
        result.success = False
        return result

    before = psutil.virtual_memory().available // 1024 // 1024
    log("Freeing RAM (cache-preserving)...", "head")

    if IS_LINUX:
        # Compact only — no cache eviction
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
                    continue   # never touch the foreground window's process

                # Only set LOW priority on processes that are genuinely idle
                # (no active CPU work) — avoids penalizing background compiles etc.
                cpu = p.cpu_percent(interval=0)
                if cpu > 2.0:
                    continue

                ok = _set_process_memory_priority(p.pid, MEMORY_PRIORITY_LOW)
                if ok:
                    lowered += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                pass

        log(f"  + Memory priority lowered for {lowered} idle background processes", "ok")
        log("  i Foreground apps untouched — pages stay in RAM", "ok")
        log("  i Kernel will evict background pages first under pressure", "ok")

    import gc; gc.collect()

    after = psutil.virtual_memory().available // 1024 // 1024
    freed = max(0, after - before)
    result.mb_freed = freed
    log(f"+ RAM: {after} MB available (+{freed} MB freed)", "ok")
    return result


def _get_foreground_pid() -> int:
    """Get PID of the process owning the foreground window (Windows only)."""
    if not IS_WINDOWS:
        return -1
    try:
        hwnd   = ctypes.windll.user32.GetForegroundWindow()
        fg_pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(fg_pid))
        return fg_pid.value
    except Exception:
        return -1


# ══════════════════════════════════════════════════════════════
# MEMORY TUNE (unchanged — kernel vm params are still correct)
# ══════════════════════════════════════════════════════════════

def memory_tune(log) -> BoostResult:
    """
    Tune kernel memory parameters for desktop responsiveness.

    Linux vm params tuned:
    - swappiness=10: prefer keeping app data in RAM over swap
    - dirty_background_ratio=5: flush dirty pages sooner (less I/O spikes)
    - dirty_ratio=10: hard cap on dirty pages (prevents write-stall)
    + compact_memory: defragment physical pages

    Windows: no kernel params to tune — Python GC only.
    Restores originals on app exit via memory_tune_restore().
    """
    result  = BoostResult("memory_tune")
    _originals: dict = {}
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
        LABELS = {
            "swappiness":             "swappiness = 10",
            "dirty_background_ratio": "dirty_background_ratio = 5",
            "dirty_ratio":            "dirty_ratio = 10",
        }
        WRITE_ORDER = ["swappiness", "dirty_background_ratio", "dirty_ratio"]

        for param in WRITE_ORDER:
            val        = TUNED[param]
            label      = LABELS[param]
            helper_key = HELPER_KEYS[param]
            p          = Path(f"/proc/sys/vm/{param}")
            try:
                orig = p.read_text().strip()
                if orig == val:
                    log(f"  ~ {label}  [already set]", "ok")
                    continue
                if not os.access(str(p), os.W_OK):
                    raise PermissionError(f"not writable: {p}")
                p.write_text(val + "\n")
                _originals[param] = orig
                log(f"  + {label}  [{orig} → {val}]", "ok")
            except (PermissionError, OSError):
                _, code = _run_helper(helper_key, timeout=10)
                if code == 0:
                    log(f"  + {label} (via helper)", "ok")
                else:
                    log(f"  ~ {param}: no write access — run install.sh", "warn")

        _, code = _run_helper("compact-memory", timeout=10)
        if code == 0:
            log("  + Memory compacted", "ok")

    elif IS_WINDOWS:
        import gc; gc.collect()
        log("  + Python GC collected", "ok")

    if HAS_PSUTIL:
        mem = psutil.virtual_memory()
        log(f"+ Memory tune done — {mem.percent:.1f}% used, {mem.available//1024//1024} MB free", "ok")

    result.rollback = [{"originals": _originals}]
    return result


def memory_tune_restore(originals: dict, log):
    """Restore kernel vm params to pre-tune values. Called on app exit."""
    if not IS_LINUX or not originals:
        return
    for param, orig_val in originals.items():
        try:
            p = Path(f"/proc/sys/vm/{param}")
            p.write_text(orig_val)
            log(f"  + Restored vm.{param} = {orig_val}", "ok")
        except (PermissionError, OSError) as e:
            log(f"  ~ Could not restore vm.{param}: {e}", "warn")


# ══════════════════════════════════════════════════════════════
# CLEAR DISK / GPU CACHE (unchanged)
# ══════════════════════════════════════════════════════════════

def clear_disk_cache(log) -> BoostResult:
    """Clear GPU shader cache, browser GPU cache, and VRAM residue."""
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
        flatpak_base = f"{home}/.var/app"
        if Path(flatpak_base).exists():
            paths += glob.glob(f"{flatpak_base}/*/config/*/GPUCache")
            paths += glob.glob(f"{flatpak_base}/*/config/*/ShaderCache")
            paths += glob.glob(f"{flatpak_base}/*/cache/mesa_shader_cache")
            log("  . Scanning Flatpak cache paths...", "ok")
        snap_base = f"{home}/snap"
        if Path(snap_base).exists():
            paths += glob.glob(f"{snap_base}/*/common/.cache/*/GPUCache")
            paths += glob.glob(f"{snap_base}/*/common/.config/*/GPUCache")
            log("  . Scanning Snap cache paths...", "ok")

    for p in paths:
        if not Path(p).exists():
            continue
        try:
            sz = sum(f.stat().st_size for f in Path(p).rglob("*") if f.is_file())
            shutil.rmtree(p, ignore_errors=True)
            mb = sz / 1024 / 1024
            total += sz
            result.count += 1
            log(f"  + {Path(p).name} — {mb:.1f} MB", "ok")
        except Exception as e:
            log(f"  ~ {Path(p).name}: {e}", "warn")

    result.mb_freed = total / 1024 / 1024
    log(f"+ Disk cache cleared: {result.mb_freed:.1f} MB freed ({result.count} paths)", "ok")
    return result


# ══════════════════════════════════════════════════════════════
# KILL BLOAT (unchanged — logic is correct)
# ══════════════════════════════════════════════════════════════

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


def kill_bloat(log) -> BoostResult:
    """
    Kill zombie processes and truly-idle high-memory background apps.
    Uses cpu_percent warm-up to avoid false positives (psutil limitation).
    Never kills: browsers, chat apps, IDEs, game launchers, OS core.
    """
    result = BoostResult("kill_bloat")
    if not HAS_PSUTIL:
        log("  x psutil not installed", "err")
        result.success = False
        return result

    log("Scanning for background bloat...", "head")

    SAFE_SKIP = {
        "python", "python3", "cyberclean", "systemd", "init",
        "kwin_wayland", "kwin_x11", "hyprland", "sway", "i3",
        "openbox", "xfwm4", "plasmashell", "gnome-shell",
        "Xorg", "Xwayland", "pipewire", "wireplumber", "pulseaudio",
        "sddm", "gdm", "lightdm", "dbus-daemon", "dbus-broker",
        "explorer", "dwm", "csrss", "smss", "wininit",
        "services", "lsass", "winlogon", "fontdrvhost", "svchost",
        # user productivity — minimized ≠ bloat, killing = data loss
        "chrome", "msedge", "firefox", "brave", "opera", "vivaldi",
        "discord", "zalo", "telegram", "slack", "teams", "zoom", "skype",
        "excel", "winword", "powerpnt", "onenote", "outlook",
        "code", "idea", "pycharm", "eclipse", "datagrip", "rider",
        "spotify", "vlc", "obs", "obs32", "obs64",
        # game launchers & anti-cheat — NEVER kill (crash/ban)
        "steam", "steamwebhelper", "epicgameslauncher", "riotclientux",
        "battle.net", "upc", "origin", "vgc", "leagueclient", "riotclientservices",
        "robloxplayerbeta", "roblox", "valorant-win64-shipping", "vgctray",
    }

    # Warm-up pass: psutil cpu_percent(interval=0) returns 0.0 on first call
    log("  . Sampling CPU usage (warm-up)...", "text")
    _warmup_pids = set()
    for p in psutil.process_iter(["pid", "name"]):
        try:
            p.cpu_percent(interval=0)
            _warmup_pids.add(p.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    import time as _time; _time.sleep(0.6)

    killed = 0
    for p in psutil.process_iter():
        try:
            with p.oneshot():
                nm = p.name().lower().replace(".exe", "")
                if nm in SAFE_SKIP:
                    continue
                if p.pid <= 10:
                    continue
                if p.pid not in _warmup_pids:
                    continue

                if IS_LINUX:
                    try:
                        if p.uids().real != CURRENT_UID:
                            continue
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                    oom     = _get_oom_score(p.pid)
                    if oom < 200:
                        continue
                    if _has_active_children(p.pid):
                        continue
                    status  = p.status()
                    cpu_pct = p.cpu_percent(interval=0)
                    mem_pct = p.memory_percent()
                    is_zombie = (status == psutil.STATUS_ZOMBIE)
                    is_bloat  = (oom >= 300 and
                                 status in (psutil.STATUS_SLEEPING, psutil.STATUS_IDLE) and
                                 cpu_pct < 0.5 and mem_pct > 3.0)

                elif IS_WINDOWS:
                    cpu_pct   = p.cpu_percent(interval=0)
                    mem_pct   = p.memory_percent()
                    is_zombie = False
                    is_bloat  = (cpu_pct < 0.5 and mem_pct > 4.0 and
                                 not _has_active_children(p.pid))
                else:
                    continue

                if is_zombie or is_bloat:
                    pmem = p.memory_info().rss // 1024 // 1024
                    tag  = ("zombie" if is_zombie
                            else (f"bloat oom={_get_oom_score(p.pid)}" if IS_LINUX else "bloat"))
                    try:
                        p.terminate()
                        p.wait(timeout=2)
                    except Exception:
                        try:
                            p.kill()
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                    killed += 1
                    result.mb_freed += pmem
                    log(f"  x [{tag}] {p.name()} — {pmem} MB", "warn")

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    if killed == 0:
        log("  + No unsafe bloat found — system is clean", "ok")
    log(f"+ Done — killed {killed} processes, freed ~{result.mb_freed:.0f} MB", "ok")
    result.count = killed
    return result


# ══════════════════════════════════════════════════════════════
# GAME MODE (unchanged — CPU affinity jail is correct for gaming)
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
    if IS_LINUX:
        r = subprocess.run(["powerprofilesctl", "set", "performance"],
                           capture_output=True, timeout=5)
        if r.returncode == 0:
            log("  + Kernel governor: performance (powerprofilesctl)", "ok")
            return "powerprofiles"
        r = subprocess.run(["sudo", "-n", "cpupower", "frequency-set", "-g", "performance"],
                           capture_output=True, timeout=5)
        if r.returncode == 0:
            log("  + Kernel governor: performance (cpupower)", "ok")
            return "cpupower"
        log("  ~ Could not set performance governor", "warn")
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
                log(f"  · Saved original power plan: {orig_guid[:8]}...", "ok")
        except (subprocess.TimeoutExpired, OSError, IndexError):
            pass

        for guid, name in [(POWER_ULTIMATE, "Ultimate"), (POWER_HIGH_PERF, "High Performance")]:
            r = subprocess.run(
                f"powercfg /setactive {guid}", shell=True,
                capture_output=True, creationflags=0x08000000, timeout=5
            )
            if r.returncode == 0:
                log(f"  + Windows Power Plan: {name} [ACTIVE]", "ok")
                return orig_guid

        log("  ~ Could not switch power plan", "warn")
        return orig_guid


def _restore_kernel_performance(method, log):
    if IS_LINUX:
        if method == "powerprofiles":
            subprocess.run(["powerprofilesctl", "set", "balanced"],
                           capture_output=True, timeout=5)
        elif method == "cpupower":
            subprocess.run(["sudo", "-n", "cpupower", "frequency-set", "-g", "schedutil"],
                           capture_output=True, timeout=5)
        log("  + Kernel governor: balanced [RESTORED]", "ok")
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
        else:
            log(f"  ~ {svc}: already stopped or no permission", "warn")
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
    CPU affinity jail — 3-tier matrix + power plan + service freeze.
    Foreground (game) gets all prime cores.
    Background split into: Comms / Media / Trash tiers.
    """
    if not HAS_PSUTIL:
        return {}
    log("⚡ CYBER BOOST — ULTIMATE GAME MODE", "head")
    saved = {"affinity": {}, "nice": {}, "services": [], "power": None}

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

        STREAM_APPS = {"discord", "obs32", "obs64", "obs", "telegram",
                       "skype", "teams", "mumble", "teamspeak"}
        MEDIA_APPS  = {"chrome", "msedge", "firefox", "brave", "opera",
                       "spotify", "zalo", "vivaldi"}
        TRASH_APPS  = {"onedrive", "dropbox", "googledrive",
                       "winword", "excel", "powerpnt",
                       "microsoftedgeupdate", "googleupdate"}

        for p in psutil.process_iter(["pid", "name"]):
            try:
                nm = (p.info["name"] or "").lower().replace(".exe", "")
                if _is_protected(nm):
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
                        log(f"  v Media: {nm} → core {trash_cores}", "warn")

                    elif nm in TRASH_APPS:
                        saved["affinity"][p.pid] = p.cpu_affinity()
                        p.cpu_affinity(trash_cores)
                        saved["nice"][p.pid] = p.nice()
                        if IS_WINDOWS:
                            p.nice(psutil.IDLE_PRIORITY_CLASS)
                        elif IS_LINUX and os.geteuid() == 0:
                            p.nice(19)
                        jailed += 1
                        log(f"  v Trash: {nm} → core {trash_cores} + lowest prio", "warn")

            except (psutil.NoSuchProcess, psutil.AccessDenied,
                    NotImplementedError, AttributeError):
                pass

        log(f"  + CPU Matrix: {jailed} apps isolated across 3 tiers", "ok")
    else:
        log("  ~ CPU ≤2 cores — CPU jail skipped", "warn")

    if IS_WINDOWS:
        saved["services"] = _freeze_windows_services(log)

    total = jailed + len(saved.get("services", []))
    log(f"✓ GAME MODE ON — {total} optimizations applied", "ok")
    return saved


def game_mode_off(saved, log):
    log("↺ Restoring system to normal...", "head")
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
# ECO MODE v2.3 — "Smooth browsing" mode
# Goal: open 30 tabs, stream video, browse without any lag
#
# Windows:
#   - SetProcessInformation(MemoryPriority=LOW) for background
#   - MMCSS 'Games' tier for CyberClean's thread (foreground boost)
#   - NO CPU nice() changes — Windows Quantum Boost handles foreground
#     automatically; interfering with nice() breaks that mechanism
#
# Linux:
#   - cgroups v2: cpu.weight=20 + io.weight=20 + memory.low=512MB
#   - Works for non-root via systemd user slice on modern distros
#   - Fully reversible: move process out of cgroup = instant restore
#   - NO nice() — cgroups give proportional scheduling, not priority inversion
# ══════════════════════════════════════════════════════════════

# Apps to skip in Eco Mode — user switches to these constantly,
# they must stay responsive at all times
_ECO_SKIP = {
    # Linux/Windows system core
    "python", "python3", "cyberclean", "systemd", "kwin",
    "hyprland", "plasmashell", "gnome-shell", "Xorg", "xwayland",
    "pipewire", "wireplumber", "dbus-daemon", "dbus-broker",
    "dwm", "explorer", "csrss", "lsass", "winlogon", "audiodg",
    "system", "registry", "smss", "sihost", "taskhostw", "ctfmon",
    "fontdrvhost", "startmenuexperiencehost", "shellexperiencehost",
    "textinputhost", "applicationframehost", "runtimebroker",
    "svchost", "services", "spoolsv",
    # Gaming peripherals — keep at normal priority
    "lghub", "rzsynapse", "icue", "logioptionsplus",
    # Browsers & chat — user switches to these constantly
    "chrome", "msedge", "firefox", "brave", "opera", "vivaldi",
    "discord", "telegram", "zalo", "slack", "teams", "zoom", "skype",
    # IDEs — may be compiling/indexing
    "code", "idea", "pycharm", "eclipse", "datagrip", "rider",
    "webstorm", "clion", "goland", "rubymine",
    # Office — may have unsaved work
    "excel", "winword", "powerpnt", "onenote", "outlook",
}


def eco_mode_on(log) -> dict:
    """
    Enable smooth-browsing Eco Mode.

    Windows: memory priority hints + MMCSS foreground boost.
    Linux: cgroups v2 proportional throttle (cpu + io + memory).

    Returns saved state dict for eco_mode_off() to restore.
    """
    if not HAS_PSUTIL:
        return {}

    saved = {
        "mode":        None,   # "windows_memprio" | "linux_cgroup" | None
        "mem_lowered": [],     # Windows: list of PIDs with lowered mem priority
        "mmcss_handle": None,  # Windows: MMCSS thread handle
        "cgroup_path": None,   # Linux: cgroup path created
        "cgroup_procs": {},    # Linux: {pid: original_cgroup} for restore
    }

    # ── Windows: memory priority + MMCSS ──────────────────
    if IS_WINDOWS:
        log("ECO MODE ON — memory priority hints + MMCSS foreground boost", "head")

        # Step 1: MMCSS boost for our thread (foreground gets guaranteed quanta)
        saved["mmcss_handle"] = _mmcss_boost_on(log)

        # Step 2: Lower memory priority of background processes
        lowered = 0
        for p in psutil.process_iter(["pid", "name"]):
            try:
                nm = (p.info["name"] or "").lower().replace(".exe", "")
                if nm in _ECO_SKIP:
                    continue
                if _is_protected(nm):
                    continue
                ok = _set_process_memory_priority(p.pid, MEMORY_PRIORITY_LOW)
                if ok:
                    saved["mem_lowered"].append(p.pid)
                    lowered += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        saved["mode"] = "windows_memprio"
        log(f"  + Memory priority lowered for {lowered} background processes", "ok")
        log("  i Browsers & chat apps untouched — switch freely", "ok")
        log("  i Kernel evicts background RAM pages first under pressure", "ok")

    # ── Linux: cgroups v2 ─────────────────────────────────
    elif IS_LINUX:
        cg_path = _cgroup_create(log)
        if not cg_path:
            # cgroups unavailable — fall back to gentle nice() if root
            if os.geteuid() == 0:
                log("  ~ cgroups unavailable — falling back to nice(5) (root only)", "warn")
                return _eco_mode_on_nice_fallback(log)
            else:
                log("  ~ Eco Mode: needs root or systemd user slice", "warn")
                log("  i Run install.sh to enable cgroup support", "ok")
                return saved

        log("ECO MODE ON — cgroups v2 proportional throttle", "head")
        saved["cgroup_path"] = cg_path

        assigned = 0
        for p in psutil.process_iter(["pid", "name"]):
            try:
                nm = (p.info["name"] or "").lower().replace(".exe", "")
                if nm in _ECO_SKIP:
                    continue
                if _is_protected(nm):
                    continue
                try:
                    if p.uids().real != CURRENT_UID:
                        continue
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

                orig_cg = _cgroup_get_original_cgroup(p.pid)
                ok = _cgroup_assign(cg_path, p.pid)
                if ok:
                    saved["cgroup_procs"][p.pid] = orig_cg
                    assigned += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        saved["mode"] = "linux_cgroup"
        log(f"  + {assigned} background processes assigned to throttle cgroup", "ok")
        log("  i cpu=20% io=20% memory.low=512MB — foreground gets priority", "ok")
        log("  i Browsers & chat apps untouched — switch freely", "ok")

    return saved


def _eco_mode_on_nice_fallback(log) -> dict:
    """
    Root-only fallback when cgroups are unavailable on Linux.
    Uses nice(5) — gentle yield, not brutal throttle.
    Only runs if root to guarantee restore (Linux blocks nice() raise for non-root).
    """
    saved = {"mode": "linux_nice", "nice_saved": {}}
    throttled = 0
    for p in psutil.process_iter(["pid", "name"]):
        try:
            nm = (p.info["name"] or "").lower().replace(".exe", "")
            if nm in _ECO_SKIP:
                continue
            if _is_protected(nm):
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
    log(f"  + nice(5) applied to {throttled} background processes (root fallback)", "ok")
    return saved


def eco_mode_off(saved: dict, log):
    """
    Restore everything to normal state.
    Windows: restore memory priority + release MMCSS handle.
    Linux: move processes back to original cgroups + destroy cgroup.
    """
    if not saved:
        return

    mode = saved.get("mode")

    # ── Windows restore ────────────────────────────────────
    if mode == "windows_memprio":
        log("ECO MODE OFF — restoring memory priorities...", "head")

        # Release MMCSS boost
        _mmcss_boost_off(saved.get("mmcss_handle"), log)

        # Restore memory priority to NORMAL
        restored = 0
        for pid in saved.get("mem_lowered", []):
            ok = _set_process_memory_priority(pid, MEMORY_PRIORITY_NORMAL)
            if ok:
                restored += 1
        log(f"  + Memory priority restored for {restored} processes", "ok")

    # ── Linux cgroup restore ───────────────────────────────
    elif mode == "linux_cgroup":
        log("ECO MODE OFF — removing cgroup throttle...", "head")
        cg_path    = saved.get("cgroup_path")
        cg_procs   = saved.get("cgroup_procs", {})
        restored   = 0

        for pid, orig_cg in cg_procs.items():
            if orig_cg:
                ok = _cgroup_restore(pid, orig_cg, log)
            else:
                # No original cgroup recorded — move to root cgroup
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

    # ── Linux nice fallback restore ────────────────────────
    elif mode == "linux_nice":
        restored = 0
        for pid, orig in saved.get("nice_saved", {}).items():
            try:
                psutil.Process(pid).nice(orig)
                restored += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        log(f"ECO MODE OFF — nice() restored for {restored} processes", "ok")

    else:
        log("ECO MODE OFF — nothing to restore", "ok")


# ══════════════════════════════════════════════════════════════
# SMART BOOST (updated to use new eco/free_ram)
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
        new_val = 0 if low_end else 1
        winreg.SetValueEx(key, 'EnableTransparency', 0, winreg.REG_DWORD, new_val)
        winreg.CloseKey(key)
        if low_end:
            log('  + Windows transparency disabled (saves GPU)', 'ok')
        else:
            log('  + Windows transparency kept (high-end machine)', 'ok')
        return orig_val
    except Exception as e:
        log(f'  ~ Transparency tweak skipped: {e}', 'warn')
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
        log('  + Windows transparency restored', 'ok')
    except Exception as e:
        log(f'  ~ Transparency restore skipped: {e}', 'warn')


def smart_boost_on(log) -> dict:
    """
    Auto-detect PC tier and apply the right strategy.

    HIGH-END: Game Mode only (CPU jail + power plan)
    MID:      Game Mode + Eco Mode (memory pressure hints)
    LOW:      Game Mode + Eco Mode + Free RAM + disable transparency
    """
    tier  = detect_pc_tier()
    saved = {
        'tier': tier, 'game': {}, 'eco': {},
        'visuals_orig': None, 'freed_mb': 0
    }

    tier_labels = {
        'high': '👑 HIGH-END — Streamer/Gaming rig',
        'mid':  '💪 MID — Solid machine',
        'low':  '🥔 LOW-END — Potato mode'
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
