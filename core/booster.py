"""
CyberClean v2.0 — System Booster
Cross-platform performance optimizer.
Fixed: safe kill logic, throttle instead of suspend,
       smart RAM free, Flatpak cache, helper fallback.
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
CURRENT_UID = os.getuid() if IS_LINUX else -1


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
            for p in psutil.process_iter(["pid", "name", "status"]):
                try:
                    if p.pid == skip_pid: continue
                    if p.info["name"].lower() in SKIP_RAM: continue
                    if p.info["status"] == psutil.STATUS_RUNNING: continue
                    # 0x0500 = QUERY_INFORMATION|SET_QUOTA — minimum needed for EmptyWorkingSet
                    # 0x1F0FFF (ALL_ACCESS) triggers Defender & gets denied on most processes
                    h = ctypes.windll.kernel32.OpenProcess(0x0500, False, p.pid)
                    if h:
                        ctypes.windll.psapi.EmptyWorkingSet(h)
                        ctypes.windll.kernel32.CloseHandle(h)
                        count += 1
                except: pass
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
    result = BoostResult("memory_tune")
    log("Tuning memory settings...", "head")

    if IS_LINUX:
        for param, val, label in [
            ("swappiness", "10", "swappiness = 10"),
            ("dirty_ratio", "10", "dirty_ratio = 10"),
            ("dirty_background_ratio", "5", "dirty_background_ratio = 5"),
        ]:
            try:
                p = Path(f"/proc/sys/vm/{param}")
                cur = p.read_text().strip()
                p.write_text(val)
                log(f"  + {label}  [{cur} -> {val}]", "ok")
            except:
                _, code = _run_helper(param.replace("_", "-"), timeout=10)
                if code == 0:
                    log(f"  + {label} (via helper)", "ok")
                else:
                    log(f"  ~ {param}: no write access", "warn")
        _, code = _run_helper("compact-memory", timeout=10)
        if code == 0:
            log("  + Memory compacted", "ok")

    elif IS_WINDOWS:
        # EmptyWorkingSet is done by free_ram — no need to repeat it here
        # (duplicating it causes mouse stutter without extra benefit)
        import gc; gc.collect()
        log("  + Python GC collected", "ok")

    if HAS_PSUTIL:
        mem = psutil.virtual_memory()
        log(f"+ Memory tune done -- {mem.percent:.1f}% used, {mem.available//1024//1024} MB free", "ok")
    return result


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
    except: pass
    return False


def kill_bloat(log):
    result = BoostResult("kill_bloat")
    if not HAS_PSUTIL:
        log("  x psutil not installed", "err")
        result.success = False; return result

    log("Scanning for background bloat...", "head")
    SAFE_SKIP = {
        "python", "python3", "cyberclean", "systemd", "init",
        "kwin_wayland", "kwin_x11", "hyprland", "sway", "i3",
        "openbox", "xfwm4", "plasmashell", "gnome-shell",
        "Xorg", "Xwayland", "pipewire", "wireplumber", "pulseaudio",
        "sddm", "gdm", "lightdm", "dbus-daemon", "dbus-broker",
        "explorer", "dwm", "csrss", "smss", "wininit",
        "services", "lsass", "winlogon", "fontdrvhost", "svchost",
    }

    killed = 0
    for p in psutil.process_iter():
        try:
            with p.oneshot():
                nm = p.name().lower().replace(".exe", "")
                if nm in SAFE_SKIP: continue
                if p.pid <= 10: continue

                if IS_LINUX:
                    try:
                        if p.uids().real != CURRENT_UID: continue
                    except: continue
                    oom = _get_oom_score(p.pid)
                    if oom < 200: continue
                    if _has_active_children(p.pid): continue
                    status  = p.status()
                    cpu_pct = p.cpu_percent(interval=0)
                    mem_pct = p.memory_percent()
                    is_zombie = (status == psutil.STATUS_ZOMBIE)
                    is_bloat  = (oom >= 300 and
                                 status in (psutil.STATUS_SLEEPING, psutil.STATUS_IDLE) and
                                 cpu_pct < 0.1 and mem_pct > 3.0)
                elif IS_WINDOWS:
                    cpu_pct = p.cpu_percent(interval=0)
                    mem_pct = p.memory_percent()
                    is_zombie = False
                    # Windows doesn't reliably report SLEEPING — trust CPU+RAM only
                    is_bloat  = (cpu_pct < 0.1 and mem_pct > 4.0 and
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
                        except: pass
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
        except: pass

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


def _apply_cpu_affinity(log):
    """
    CPU Affinity jail (Process Lasso style):
    Locks background apps to last 1-2 cores, freeing faster cores for game.
    """
    if not HAS_PSUTIL: return {}
    cores = psutil.cpu_count(logical=True) or 1
    if cores < 4:
        log("  ~ CPU affinity skipped (< 4 cores)", "warn")
        return {}

    # Jail logic: sacrifice 1 core on weak machines, 2 on strong ones
    if cores <= 4:
        jail_cores = [cores - 1]        # 4-core: only last 1 core — keep 75% for game
    else:
        jail_cores = list(range(cores - 2, cores))  # 8+ cores: last 2 cores
    bg_apps = BACKGROUND_APPS_WIN if IS_WINDOWS else BACKGROUND_APPS_LX
    saved_affinity = {}

    for p in psutil.process_iter():
        try:
            with p.oneshot():
                nm = p.name().lower().replace(".exe", "")
                if not any(app in nm for app in bg_apps): continue
                orig = p.cpu_affinity()
                p.cpu_affinity(jail_cores)
                saved_affinity[p.pid] = orig
                log(f"  v Jailed: {p.name()} → cores {jail_cores}", "warn")
        except (psutil.NoSuchProcess, psutil.AccessDenied, NotImplementedError):
            pass

    log(f"  + CPU affinity: {len(saved_affinity)} apps jailed to cores {jail_cores}", "ok")
    return saved_affinity


def _restore_cpu_affinity(saved_affinity, log):
    if not HAS_PSUTIL: return
    restored = 0
    for pid, orig in saved_affinity.items():
        try:
            psutil.Process(pid).cpu_affinity(orig)
            restored += 1
        except: pass
    log(f"  + CPU affinity restored for {restored} processes", "ok")


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
    Ultimate Game Mode — 3-layer optimization:
    1. Kernel governor → performance power plan
    2. CPU affinity jail → background apps locked to last cores
    3. Windows service freeze → stops Update/Superfetch/Search
    """
    log("⚡ CYBER BOOST — ULTIMATE GAME MODE", "head")
    saved = {"affinity": {}, "services": [], "power": None}

    # Layer 1: Kernel performance
    saved["power"] = _enable_kernel_performance(log)

    # Layer 2: CPU affinity jail
    if HAS_PSUTIL:
        saved["affinity"] = _apply_cpu_affinity(log)

    # Layer 3: Freeze Windows services (Windows only, needs admin)
    if IS_WINDOWS:
        saved["services"] = _freeze_windows_services(log)

    count = len(saved["affinity"]) + len(saved["services"])
    log(f"✓ GAME MODE ON — {count} optimizations applied", "ok")
    return saved


def game_mode_off(saved, log):
    """Restore everything to normal state."""
    log("↺ Restoring system to normal...", "head")

    # Restore Windows services
    if IS_WINDOWS and saved.get("services"):
        _restore_windows_services(saved["services"], log)

    # Restore CPU affinity
    if saved.get("affinity"):
        _restore_cpu_affinity(saved["affinity"], log)

    # Restore power plan/governor
    if saved.get("power") is not None:
        _restore_kernel_performance(saved["power"], log)

    log("✓ GAME MODE OFF — system restored", "ok")


def eco_mode_on(log):
    if not HAS_PSUTIL: return {}
    SKIP = {
        # Linux
        "python", "python3", "cyberclean", "systemd", "kwin",
        "hyprland", "plasmashell", "gnome-shell", "Xorg", "pipewire",
        "wireplumber", "dbus-daemon", "dbus-broker",
        # Windows UI/mouse/audio — never throttle
        "dwm", "explorer", "csrss", "lsass", "winlogon",
        "audiodg", "system", "registry", "smss",
        "sihost", "taskhostw", "ctfmon", "fontdrvhost",
        "startmenuexperiencehost", "shellexperiencehost",
        "textinputhost", "applicationframehost", "runtimebroker",
        # Service hosts — svchost runs HID/mouse/keyboard/audio services
        "svchost", "services", "spoolsv",
        # Gaming peripherals — Logitech/Razer/Corsair
        "lghub", "rzsynapse", "icue", "logioptionsplus",
        # Browsers & chat — user may switch to them anytime; throttling causes visible lag
        "chrome", "msedge", "firefox", "brave", "opera", "vivaldi",
        "discord", "telegram", "zalo", "slack", "teams", "zoom",
    }

    # Protect foreground app on Windows — don't throttle what user is actively using
    skip_pid = -1
    if IS_WINDOWS:
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            fg_pid = ctypes.c_ulong()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(fg_pid))
            skip_pid = fg_pid.value
        except: pass

    saved = {}
    for p in psutil.process_iter():
        try:
            with p.oneshot():
                if p.pid == skip_pid: continue  # Never throttle foreground app
                nm = p.name().lower().replace(".exe", "")
                if nm in SKIP: continue
                if IS_LINUX:
                    try:
                        if p.uids().real != CURRENT_UID: continue
                    except: continue
                cur = p.nice()
                if IS_WINDOWS:
                    if cur not in (psutil.IDLE_PRIORITY_CLASS, psutil.BELOW_NORMAL_PRIORITY_CLASS):
                        saved[p.pid] = cur
                        p.nice(psutil.IDLE_PRIORITY_CLASS)
                else:
                    if cur <= 10:
                        saved[p.pid] = cur
                        p.nice(19)
        except: pass
    log(f"ECO MODE ON -- {len(saved)} processes set to IDLE priority", "ok")
    return saved


def eco_mode_off(saved, log):
    if not HAS_PSUTIL: return
    restored = 0
    for pid, orig in saved.items():
        try: psutil.Process(pid).nice(orig); restored += 1
        except: pass
    log(f"ECO MODE OFF -- {restored} processes restored", "ok")
