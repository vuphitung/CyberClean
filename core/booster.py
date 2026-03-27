"""
CyberClean v2.0 — System Booster
Cross-platform performance optimizer.
Fixed: safe kill logic, throttle instead of suspend,
       smart RAM free, Flatpak cache, helper fallback.
v2.1 fixes: cpu_percent warm-up (no false-positive kills),
            memory_tune saves originals + restore on exit,
            game/eco mode thread safety.
"""
import os, sys, shutil, subprocess, glob, platform
from pathlib import Path
from dataclasses import dataclass
from typing import Callable

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX   = platform.system() == "Linux"

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

HELPER = "/usr/local/bin/cyber-clean-helper"
# FIX: os.getuid() does not exist on Windows — use getattr with lambda fallback
# so importing this module on Windows never raises AttributeError.
CURRENT_UID = getattr(os, 'getuid', lambda: -1)()

# ══════════════════════════════════════════════════════════════
# LAYER 1: CROSS-PLATFORM OS FIREWALL
# Never touch these — causes black screen, mouse freeze, audio dropout
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
    # Linux audio — kill = no sound
    "pipewire", "wireplumber", "pulseaudio", "jackd",
    # Display managers
    "sddm", "gdm", "lightdm",
    # CyberClean itself
    "python", "python3", "cyberclean",
}

# GPU-related keywords — never throttle, kills FPS/display
GPU_KEYWORDS = {"gpu", "nvidia", "amd", "radeon", "intel_gpu",
                "nvd", "amdgpu", "vgaswitcheroo", "renderer"}


def _is_protected(proc_name: str) -> bool:
    """Check if a process is protected by the OS Firewall.
    Returns True for system/GPU processes that must never be throttled or jailed.
    """
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


def free_ram(log):
    result = BoostResult("free_ram")
    if not HAS_PSUTIL:
        log("  x psutil not installed", "err")
        result.success = False; return result

    before = psutil.virtual_memory().available // 1024 // 1024
    log("Freeing RAM...", "head")
    log("  ! Note: clearing page cache may cause brief slowdown while OS reloads data", "warn")

    if IS_LINUX:
        _, code = _run_helper("compact-memory", timeout=10)
        if code == 0:
            log("  + Memory compacted", "ok")
        _run("sync")
        _, code = _run_helper("drop-cache", timeout=15)
        if code == 0:
            log("  + Page cache dropped", "ok")
        else:
            import gc; gc.collect()
            log("  ~ No root — skipped kernel cache drop (user-space GC done)", "warn")
            log("  i Run install.sh to enable deep RAM optimization", "ok")

    elif IS_WINDOWS:
        try:
            import ctypes
            try:
                hwnd = ctypes.windll.user32.GetForegroundWindow()
                fg_pid = ctypes.c_ulong()
                ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(fg_pid))
                skip_pid = fg_pid.value
            except:
                skip_pid = -1
            # Never EmptyWorkingSet on UI/mouse/audio/service hosts — causes stutter
            SKIP_RAM = {
                'dwm.exe', 'explorer.exe', 'csrss.exe', 'smss.exe',
                'winlogon.exe', 'lsass.exe', 'audiodg.exe',
                'svchost.exe', 'services.exe', 'spoolsv.exe',
                'conhost.exe', 'taskhostw.exe', 'sihost.exe',
            }
            count = 0
            # psutil on Windows reports ALL processes as STATUS_RUNNING —
            # checking status here would skip the entire system and free zero RAM!
            # SKIP_RAM + skip_pid already protect what matters.
            for p in psutil.process_iter(["pid", "name"]):
                try:
                    if p.pid == skip_pid: continue
                    if p.info["name"].lower() in SKIP_RAM: continue
                    # 0x0500 = QUERY_INFORMATION|SET_QUOTA — minimum needed for EmptyWorkingSet
                    h = ctypes.windll.kernel32.OpenProcess(0x0500, False, p.pid)
                    if h:
                        ctypes.windll.psapi.EmptyWorkingSet(h)
                        ctypes.windll.kernel32.CloseHandle(h)
                        count += 1
                except (OSError, psutil.NoSuchProcess, psutil.AccessDenied):
                    pass   # process exited between iteration and handle open
            log(f"  + Trimmed {count} background working sets (UI/mouse/audio skipped)", "ok")
        except Exception as e:
            log(f"  ~ {e}", "warn")
        # NOTE: powershell [System.GC]::Collect() only cleans the spawned PS process itself
        # — it has zero effect on system-wide .NET memory. Removed to save CPU.

    import gc; gc.collect()
    after = psutil.virtual_memory().available // 1024 // 1024
    freed = max(0, after - before)
    result.mb_freed = freed
    log(f"+ RAM: {after} MB available (+{freed} MB freed)", "ok")
    return result


def memory_tune(log):
    """
    Tune kernel memory params.
    Returns a dict of {param: original_value} so caller can restore on exit.
    On Windows: no kernel params to tune — returns empty dict.

    FIX: Validate dirty_ratio >= dirty_background_ratio + 2 (kernel constraint).
         Check file writability before attempting write — avoids silent PermissionError swallow.
         Order writes: swappiness first, then dirty_background_ratio, then dirty_ratio
         so we never end up in an invalid state mid-write.
    """
    result = BoostResult("memory_tune")
    log("Tuning memory settings...", "head")
    _originals: dict = {}

    if IS_LINUX:
        # Target values — dirty_ratio must be >= dirty_background_ratio + 2
        TUNED = {
            "swappiness":             "10",
            "dirty_background_ratio": "5",
            "dirty_ratio":            "10",   # must be >= 5 + 2 = 7; 10 is safe
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
        # Write order matters: background_ratio before ratio to avoid constraint violation
        WRITE_ORDER = ["swappiness", "dirty_background_ratio", "dirty_ratio"]

        for param in WRITE_ORDER:
            val = TUNED[param]
            label = LABELS[param]
            helper_key = HELPER_KEYS[param]
            p = Path(f"/proc/sys/vm/{param}")
            try:
                orig = p.read_text().strip()
                # Skip if already at target — no need to write
                if orig == val:
                    log(f"  ~ {label}  [already set]", "ok")
                    continue
                # Test writability before committing (avoids silent except-swallow)
                if not os.access(str(p), os.W_OK):
                    raise PermissionError(f"not writable: {p}")
                p.write_text(val + "\n")
                _originals[param] = orig
                log(f"  + {label}  [{orig} → {val}]", "ok")
            except (PermissionError, OSError):
                # Fall back to NOPASSWD helper
                _, code = _run_helper(helper_key, timeout=10)
                if code == 0:
                    log(f"  + {label} (via helper)", "ok")
                else:
                    log(f"  ~ {param}: no write access — run install.sh for full optimization", "warn")

        _, code = _run_helper("compact-memory", timeout=10)
        if code == 0:
            log("  + Memory compacted", "ok")

    elif IS_WINDOWS:
        import gc; gc.collect()
        log("  + Python GC collected", "ok")

    if HAS_PSUTIL:
        mem = psutil.virtual_memory()
        log(f"+ Memory tune done -- {mem.percent:.1f}% used, {mem.available//1024//1024} MB free", "ok")

    result.rollback = [{"originals": _originals}]
    return result


def memory_tune_restore(originals: dict, log):
    """Restore kernel vm params to their pre-tune values. Call on app exit."""
    if not IS_LINUX or not originals:
        return
    for param, orig_val in originals.items():
        try:
            p = Path(f"/proc/sys/vm/{param}")
            p.write_text(orig_val)
            log(f"  + Restored vm.{param} = {orig_val}", "ok")
        except (PermissionError, OSError) as e:
            log(f"  ~ Could not restore vm.{param}: {e}", "warn")


def clear_disk_cache(log):
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
        home = str(Path.home())
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
        if not Path(p).exists(): continue
        try:
            sz = sum(f.stat().st_size for f in Path(p).rglob("*") if f.is_file())
            shutil.rmtree(p, ignore_errors=True)
            mb = sz / 1024 / 1024
            total += sz
            result.count += 1
            log(f"  + {Path(p).name} -- {mb:.1f} MB", "ok")
        except Exception as e:
            log(f"  ~ {Path(p).name}: {e}", "warn")

    result.mb_freed = total / 1024 / 1024
    log(f"+ Disk cache cleared: {result.mb_freed:.1f} MB freed ({result.count} paths)", "ok")
    return result


def _get_oom_score(pid):
    try:
        return int(Path(f"/proc/{pid}/oom_score").read_text().strip())
    except:
        return 0


def _has_active_children(pid):
    """Check if process has actively running children.
    Note: cpu_percent(interval=0) always returns 0.0 on first call (psutil limitation).
    Using status() check instead — reliable cross-platform.
    """
    if not HAS_PSUTIL: return False
    try:
        for child in psutil.Process(pid).children(recursive=True):
            if child.status() == psutil.STATUS_RUNNING:
                return True
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        pass   # process exited or we lost access mid-scan
    return False


def kill_bloat(log):
    result = BoostResult("kill_bloat")
    if not HAS_PSUTIL:
        log("  x psutil not installed", "err")
        result.success = False; return result

    log("Scanning for background bloat...", "head")
    SAFE_SKIP = {
        # OS core — never kill
        "python", "python3", "cyberclean", "systemd", "init",
        "kwin_wayland", "kwin_x11", "hyprland", "sway", "i3",
        "openbox", "xfwm4", "plasmashell", "gnome-shell",
        "Xorg", "Xwayland", "pipewire", "wireplumber", "pulseaudio",
        "sddm", "gdm", "lightdm", "dbus-daemon", "dbus-broker",
        "explorer", "dwm", "csrss", "smss", "wininit",
        "services", "lsass", "winlogon", "fontdrvhost", "svchost",
        # User productivity apps — minimized = cpu 0%, but NOT bloat!
        # Killing these = data loss (unsaved Excel) or dropped calls (Discord)
        "chrome", "msedge", "firefox", "brave", "opera", "vivaldi",
        "discord", "zalo", "telegram", "slack", "teams", "zoom", "skype",
        "excel", "winword", "powerpnt", "onenote", "outlook",
        "code", "idea", "pycharm", "eclipse", "datagrip", "rider",
        "spotify", "vlc", "obs", "obs32", "obs64",
        # Game launchers — steamwebhelper uses 600-800MB RAM idle; killing = game crashes
        "steam", "steamwebhelper", "epicgameslauncher", "riotclientux",
        "battle.net", "upc", "origin", "vgc", "leagueclient", "riotclientservices",
        "gog galaxy", "bethesdanetlauncher", "ea app", "playnite",
        # Game clients & anti-cheat — NEVER kill (causes crash/ban)
        "robloxplayerbeta", "roblox", "league of legends",
        "valorant-win64-shipping", "vgctray",
    }

    # FIX #2: psutil.cpu_percent(interval=0) ALWAYS returns 0.0 on the FIRST call per process
    # (psutil limitation — it needs two samples to calculate a delta).
    # Warm-up pass: call cpu_percent(interval=0) on all processes once and discard,
    # then sleep briefly so the second call returns real values.
    log("  . Sampling CPU usage (warm-up)...", "text")
    _warmup_pids = set()
    for p in psutil.process_iter(["pid", "name"]):
        try:
            p.cpu_percent(interval=0)
            _warmup_pids.add(p.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    import time as _time; _time.sleep(0.6)   # 600ms window — enough for accurate delta

    killed = 0
    for p in psutil.process_iter():
        try:
            with p.oneshot():
                nm = p.name().lower().replace(".exe", "")
                if nm in SAFE_SKIP: continue
                if p.pid <= 10: continue
                # Only scan processes we warmed up — fresh ones have no valid CPU sample yet
                if p.pid not in _warmup_pids: continue

                if IS_LINUX:
                    try:
                        if p.uids().real != CURRENT_UID: continue
                    except (psutil.NoSuchProcess, psutil.AccessDenied): continue
                    oom = _get_oom_score(p.pid)
                    if oom < 200: continue
                    if _has_active_children(p.pid): continue
                    status  = p.status()
                    cpu_pct = p.cpu_percent(interval=0)   # real value on 2nd call
                    mem_pct = p.memory_percent()
                    is_zombie = (status == psutil.STATUS_ZOMBIE)
                    is_bloat  = (oom >= 300 and
                                 status in (psutil.STATUS_SLEEPING, psutil.STATUS_IDLE) and
                                 cpu_pct < 0.5 and mem_pct > 3.0)
                elif IS_WINDOWS:
                    cpu_pct = p.cpu_percent(interval=0)   # real value on 2nd call
                    mem_pct = p.memory_percent()
                    is_zombie = False
                    # Windows: use cpu < 0.5% (not 0.1%) to avoid fp from measurement jitter
                    is_bloat  = (cpu_pct < 0.5 and mem_pct > 4.0 and
                                 not _has_active_children(p.pid))
                else:
                    continue

                if is_zombie or is_bloat:
                    pmem = p.memory_info().rss // 1024 // 1024
                    tag  = "zombie" if is_zombie else (f"bloat oom={_get_oom_score(p.pid)}" if IS_LINUX else "bloat")
                    try:
                        p.terminate()  # SIGTERM first — let it clean up
                        p.wait(timeout=2)
                    except Exception:
                        try: p.kill()  # SIGKILL only if it refuses to die
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass   # process already gone between terminate and kill
                    killed += 1
                    result.mb_freed += pmem
                    log(f"  x [{tag}] {p.name()} -- {pmem} MB", "warn")

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    if killed == 0:
        log("  + No unsafe bloat found -- system is clean", "ok")
    log(f"+ Done -- killed {killed} processes, freed ~{result.mb_freed:.0f} MB", "ok")
    result.count = killed
    return result


# ══════════════════════════════════════════════════════════════
# ULTIMATE GAME MODE
# Inspired by: Process Lasso + Razer Cortex + Feral GameMode
# Strategy: CPU Affinity jail + freeze services + kernel governor
# Zero-crash: no kill, no suspend — only isolate and throttle
# ══════════════════════════════════════════════════════════════

# Background apps to jail into last CPU cores
BACKGROUND_APPS_WIN = {
    "chrome", "msedge", "firefox", "brave", "opera", "vivaldi",
    "discord", "slack", "teams", "telegram", "zalo",
    "spotify", "onedrive", "dropbox", "googledrive",
    "winword", "excel", "powerpnt", "outlook",
    "zoom", "webex", "skype",
}
BACKGROUND_APPS_LX = {
    "chrome", "chromium", "firefox", "brave",
    "discord", "slack", "teams", "telegram",
    "spotify", "dropbox", "onedrive",
    "libreoffice", "zoom",
}

# Windows services safe to freeze during gaming
GAMING_FREEZE_SERVICES = [
    "wuauserv",   # Windows Update — stops background downloads
    "SysMain",    # Superfetch — hammers disk with prefetch
    "WSearch",    # Search Indexer — scans files in background
    "DiagTrack",  # Telemetry — sends usage data, wastes I/O
]

# Windows power plan GUIDs
POWER_BALANCED     = "381b4222-f694-41f0-9685-ff5bb260df2e"
POWER_HIGH_PERF    = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
POWER_ULTIMATE     = "e9a42b02-d5df-448d-aa00-03f14749eb61"  # Windows 10/11


def _enable_kernel_performance(log):
    """Switch to performance power plan/governor.
    Windows: saves user's original plan GUID before switching — restores exact plan on exit.
    """
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
        log("  ~ Could not set performance governor (no cpupower/powerprofilesctl)", "warn")
        return None

    elif IS_WINDOWS:
        # Save user's CURRENT plan first (may be ASUS Turbo, AMD Balanced, etc.)
        orig_guid = POWER_BALANCED  # safe fallback
        try:
            out = subprocess.run(
                "powercfg /getactivescheme",
                shell=True, capture_output=True, text=True,
                creationflags=0x08000000, timeout=5
            ).stdout
            if "GUID:" in out:
                orig_guid = out.split("GUID:")[1].split()[0].strip()
                log(f"  · Saved original power plan: {orig_guid[:8]}...", "ok")
        except (subprocess.TimeoutExpired, OSError, IndexError):
            pass   # powercfg unavailable or output format changed

        # Switch to Ultimate → High Performance
        for guid, name in [(POWER_ULTIMATE, "Ultimate"), (POWER_HIGH_PERF, "High Performance")]:
            r = subprocess.run(
                f"powercfg /setactive {guid}",
                shell=True, capture_output=True,
                creationflags=0x08000000, timeout=5
            )
            if r.returncode == 0:
                log(f"  + Windows Power Plan: {name} [ACTIVE]", "ok")
                return orig_guid  # Return original GUID for restore

        log("  ~ Could not switch power plan", "warn")
        return orig_guid


def _restore_kernel_performance(method, log):
    """Restore original power plan/governor.
    Windows: restores exact user plan (ASUS Turbo, AMD Balanced, etc.) — not forced to Balanced.
    """
    if IS_LINUX:
        if method == "powerprofiles":
            subprocess.run(["powerprofilesctl", "set", "balanced"],
                           capture_output=True, timeout=5)
        elif method == "cpupower":
            subprocess.run(["sudo", "-n", "cpupower", "frequency-set", "-g", "schedutil"],
                           capture_output=True, timeout=5)
        log("  + Kernel governor: balanced [RESTORED]", "ok")

    elif IS_WINDOWS:
        # Restore user's ORIGINAL plan — not hardcoded Balanced
        if method:
            subprocess.run(
                f"powercfg /setactive {method}",
                shell=True, capture_output=True,
                creationflags=0x08000000, timeout=5
            )
        log("  + Windows Power Plan: original restored", "ok")


def _freeze_windows_services(log):
    """Stop non-critical Windows services during gaming (Razer Cortex style)."""
    stopped = []
    for svc in GAMING_FREEZE_SERVICES:
        r = subprocess.run(
            f"net stop {svc} /y",
            shell=True, capture_output=True,
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
            f"net start {svc}",
            shell=True, capture_output=True,
            creationflags=0x08000000, timeout=15
        )
    if stopped_services:
        log(f"  + Restored {len(stopped_services)} Windows services", "ok")


def game_mode_on(log):
    """
    Ultimate Game Mode — 3-tier CPU Matrix + kernel boost + service freeze.

    CPU Matrix tiers (scale by core count):
      Tier 1 — STREAM_APPS (Discord/OBS): 50% last cores — need decent perf for audio/video
      Tier 2 — MEDIA_APPS (Chrome/Firefox/Spotify): 1 last core — medium priority
      Tier 3 — TRASH_APPS (OneDrive/Dropbox): 1 last core + lowest priority
    Game gets ALL prime cores by default — no need to list games.
    """
    if not HAS_PSUTIL: return {}
    log("⚡ CYBER BOOST — ULTIMATE GAME MODE", "head")
    saved = {"affinity": {}, "nice": {}, "services": [], "power": None}

    # Layer 1: Kernel performance
    saved["power"] = _enable_kernel_performance(log)

    # Layer 2: CPU Matrix — 3 separate tiers, not 1 jail
    cores = psutil.cpu_count(logical=True) or 1
    jailed = 0

    if cores > 2:
        # Scale jail zones by core count
        if cores <= 4:
            # 4-core: stream gets last 1 core, trash gets last 1 core
            stream_cores = [cores - 1]
            trash_cores  = [cores - 1]
        else:
            # 6+ cores: stream gets last 2 cores, trash gets last 1 core
            stream_cores = list(range(max(1, cores // 2), cores))
            trash_cores  = [cores - 1]

        # Tier 1: Comms/stream — need decent cores for audio/video encoding
        STREAM_APPS = {"discord", "obs32", "obs64", "obs", "telegram",
                       "skype", "teams", "mumble", "teamspeak"}
        # Tier 2: Browsers/media — 1 core + below normal priority
        MEDIA_APPS  = {"chrome", "msedge", "firefox", "brave", "opera",
                       "spotify", "zalo", "vivaldi"}
        # Tier 3: Pure background trash — 1 core + idle/max-nice priority
        TRASH_APPS  = {"onedrive", "dropbox", "googledrive",
                       "winword", "excel", "powerpnt",
                       "microsoftedgeupdate", "googleupdate"}

        for p in psutil.process_iter(["pid", "name"]):
            try:
                nm = (p.info["name"] or "").lower().replace(".exe", "")
                if _is_protected(nm): continue

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
                            # FIX: Linux kernel blocks nice() restore for non-root users
                            # (can lower priority but CANNOT raise it back — one-way street)
                            # Only set nice if root so we can guarantee restore on exit
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
                            # FIX: same root-only guard — see MEDIA_APPS comment above
                            p.nice(19)
                        jailed += 1
                        log(f"  v Trash: {nm} → core {trash_cores} + lowest prio", "warn")

            except (psutil.NoSuchProcess, psutil.AccessDenied,
                    NotImplementedError, AttributeError): pass

        log(f"  + CPU Matrix: {jailed} apps isolated across 3 tiers", "ok")
    else:
        log("  ~ CPU ≤2 cores — CPU jail skipped (too few cores)", "warn")

    # Layer 3: Freeze Windows services
    if IS_WINDOWS:
        saved["services"] = _freeze_windows_services(log)

    total = jailed + len(saved.get("services", []))
    log(f"✓ GAME MODE ON — {total} optimizations applied", "ok")
    return saved


def game_mode_off(saved, log):
    """Restore everything to normal state."""
    log("↺ Restoring system to normal...", "head")

    # Restore Windows services first
    if IS_WINDOWS and saved.get("services"):
        _restore_windows_services(saved["services"], log)

    # Restore nice/priority
    for pid, orig in saved.get("nice", {}).items():
        try: psutil.Process(pid).nice(orig)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass   # process exited since game mode was enabled

    # Restore CPU affinity
    restored = 0
    for pid, orig in saved.get("affinity", {}).items():
        try: psutil.Process(pid).cpu_affinity(orig); restored += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass   # process exited since game mode was enabled
    if restored:
        log(f"  + CPU affinity restored for {restored} processes", "ok")

    # Restore power plan/governor
    if saved.get("power") is not None:
        _restore_kernel_performance(saved["power"], log)


    log("✓ GAME MODE OFF — system restored", "ok")


def eco_mode_on(log):
    """
    Soft throttle background apps — yield mode, not brutal IDLE.
    Windows: BELOW_NORMAL (not IDLE) — no stutter. Windows Quantum Boosting
             handles foreground automatically — no need to manually boost it.
    Linux:   nice(5) gentle yield — not brutal nice(19).
             REQUIRES root: Linux kernel blocks nice() restore for non-root users
             (can lower nice but not raise back = apps stay throttled forever).
             Non-root on Linux → logs a clear warning, returns empty dict (no-op).
    Never throttle: system procs, GPU, browsers, chat apps (user switches often).
    """
    if not HAS_PSUTIL: return {}

    # FIX: Surface clear warning for Linux non-root instead of silent no-op.
    # smart_boost_on() calls eco_mode for MID+LOW tiers but this is Linux-root-only.
    if IS_LINUX and os.geteuid() != 0:
        log("  ~ Eco Mode skipped on Linux — needs root to guarantee nice() restore", "warn")
        log("  i Run install.sh to enable NOPASSWD helper, then relaunch as root for full eco mode", "ok")
        return {}

    SKIP = {
        # Linux core
        "python", "python3", "cyberclean", "systemd", "kwin",
        "hyprland", "plasmashell", "gnome-shell", "Xorg", "pipewire",
        "wireplumber", "dbus-daemon", "dbus-broker",
        # Windows UI/mouse/audio
        "dwm", "explorer", "csrss", "lsass", "winlogon",
        "audiodg", "system", "registry", "smss",
        "sihost", "taskhostw", "ctfmon", "fontdrvhost",
        "startmenuexperiencehost", "shellexperiencehost",
        "textinputhost", "applicationframehost", "runtimebroker",
        "svchost", "services", "spoolsv",
        # Gaming peripherals
        "lghub", "rzsynapse", "icue", "logioptionsplus",
        # Browsers & chat — user switches to these constantly
        "chrome", "msedge", "firefox", "brave", "opera", "vivaldi",
        "discord", "telegram", "zalo", "slack", "teams", "zoom", "skype",
        # IDEs — may run heavy background tasks (compile, index, terminal)
        "code", "idea", "pycharm", "eclipse", "datagrip", "rider",
        "webstorm", "clion", "goland", "rubymine",
        # Office — may have unsaved work
        "excel", "winword", "powerpnt", "onenote", "outlook",
    }
    saved = {}
    throttled = 0
    for p in psutil.process_iter(["pid", "name"]):
        try:
            nm = (p.info["name"] or "").lower().replace(".exe", "")
            if nm in SKIP: continue
            if _is_protected(nm): continue
            with p.oneshot():
                if IS_LINUX:
                    try:
                        if p.uids().real != CURRENT_UID: continue
                    except (psutil.NoSuchProcess, psutil.AccessDenied): continue
                cur = p.nice()
                if IS_WINDOWS:
                    if cur not in (psutil.BELOW_NORMAL_PRIORITY_CLASS, psutil.IDLE_PRIORITY_CLASS):
                        saved[p.pid] = cur
                        p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
                        throttled += 1
                elif IS_LINUX:
                    if cur < 5:
                        saved[p.pid] = cur
                        p.nice(5)
                        throttled += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied): pass
    log(f"ECO MODE ON -- {throttled} background tasks soft-throttled (yield mode)", "ok")
    return saved


def eco_mode_off(saved, log):
    if not HAS_PSUTIL: return
    restored = 0
    for pid, orig in saved.items():
        try: psutil.Process(pid).nice(orig); restored += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass   # process exited during eco session
    log(f"ECO MODE OFF -- {restored} processes restored", "ok")


# ══════════════════════════════════════════════════════════════
# SMART BOOST — Tự động nhận diện cấu hình, tối ưu phù hợp
# ══════════════════════════════════════════════════════════════

def detect_pc_tier() -> str:
    """
    Phân loại máy tính dựa trên RAM và số nhân CPU thật (physical cores).
    Returns: 'high' | 'mid' | 'low'
    - high: RAM > 16GB VÀ CPU > 6 nhân  → Chiến thần / Streamer
    - mid:  RAM > 8GB  VÀ CPU > 4 nhân  → Máy ổn
    - low:  Còn lại                      → Khoai tây
    """
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
    except:
        return 'mid'


def _tweak_windows_visuals(low_end: bool, log):
    """
    Tắt/bật hiệu ứng trong suốt (Transparency/Acrylic) của Windows.
    - Chỉ tắt Transparency — KHÔNG tắt ClearType, font smoothing, shadow chuột.
    - Cần khởi động lại Explorer để áp dụng hoàn toàn (nhưng app vẫn nhận ngay).
    - Lưu giá trị gốc để restore khi tắt Game Mode.
    """
    if not IS_WINDOWS:
        return None
    try:
        import winreg
        key_path = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize'
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE)
        # Lưu giá trị gốc trước
        try:
            orig_val, _ = winreg.QueryValueEx(key, 'EnableTransparency')
        except Exception:
            orig_val = 1  # mặc định Windows = bật trong suốt
        # Set giá trị mới
        new_val = 0 if low_end else 1
        winreg.SetValueEx(key, 'EnableTransparency', 0, winreg.REG_DWORD, new_val)
        winreg.CloseKey(key)
        if low_end:
            log('  + Windows transparency disabled (saves GPU)', 'ok')
        else:
            log('  + Windows transparency kept (high-end machine)', 'ok')
        return orig_val  # trả về để restore sau
    except Exception as e:
        log(f'  ~ Transparency tweak skipped: {e}', 'warn')
        return None


def _restore_windows_visuals(orig_val, log):
    """Khôi phục giá trị Transparency về trạng thái ban đầu."""
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
    Smart Boost — tự phân tích cấu hình rồi áp chiến lược phù hợp.

    HIGH-END (RAM>16GB, CPU>6 cores):
      → Giữ nguyên đồ họa Windows
      → Game Mode đầy đủ (CPU jail 3 tầng + power plan)
      → Eco Mode KHÔNG bật (Discord/Spotify cần chạy tốt cho streamer)

    MID (RAM>8GB, CPU>4 cores):
      → Giữ nguyên đồ họa Windows
      → Game Mode đầy đủ
      → Eco Mode nhẹ (BELOW_NORMAL cho app nền)

    LOW (còn lại):
      → Tắt Windows Transparency (nhường GPU)
      → Game Mode đầy đủ
      → Eco Mode mạnh + Free RAM ngay

    Returns dict saved state để smart_boost_off() restore.
    """
    tier = detect_pc_tier()
    saved = {'tier': tier, 'game': {}, 'eco': {}, 'visuals_orig': None, 'freed_mb': 0}

    tier_labels = {'high': '👑 HIGH-END — Streamer/Gaming rig', 'mid': '💪 MID — Solid machine', 'low': '🥔 LOW-END — Potato mode'}
    log(f'Smart Boost ON  [{tier_labels.get(tier, tier)}]', 'head')

    # Layer 1: Visual tweak (chỉ máy yếu)
    if tier == 'low' and IS_WINDOWS:
        saved['visuals_orig'] = _tweak_windows_visuals(low_end=True, log=log)

    # Layer 2: Game Mode (tất cả tier)
    saved['game'] = game_mode_on(log)

    # Layer 3: Eco Mode (mid + low)
    if tier in ('mid', 'low'):
        saved['eco'] = eco_mode_on(log)

    # Layer 4: Free RAM ngay (chỉ máy yếu)
    if tier == 'low':
        result = free_ram(log)
        saved['freed_mb'] = getattr(result, 'mb_freed', 0)

    log(f'✓ Smart Boost ON [{tier}] — all layers applied', 'ok')
    return saved


def smart_boost_off(saved: dict, log):
    """Restore tất cả về trạng thái ban đầu."""
    if not saved:
        return
    tier = saved.get('tier', 'mid')
    log(f'Smart Boost OFF — restoring [{tier}]...', 'head')

    # Restore eco mode
    if saved.get('eco'):
        eco_mode_off(saved['eco'], log)

    # Restore game mode
    if saved.get('game') is not None:
        game_mode_off(saved['game'], log)

    # Restore visuals
    if saved.get('visuals_orig') is not None:
        _restore_windows_visuals(saved['visuals_orig'], log)

    log('✓ Smart Boost OFF — system restored', 'ok')
