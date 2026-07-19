"""
CyberClean v2.7 — System Booster (Activity-Aware CPU Scheduling)
═══════════════════════════════════════════════════════════════
WHAT CHANGED vs v2.6:

FIX: Roblox / OpenGL games — black screen when enabling Game Mode mid-game
  OLD: _set_gpu_performance() ran immediately at game_mode_on() start,
       BEFORE checking if a game was already running.
       Forcing DPM transition (auto → high) while GPU render engine is active
       = driver state shock = black screen (Roblox, any OpenGL/Vulkan game).
  NEW: GPU performance level is set ONLY if no game is currently running.
       If a game is active: skip DPM change, log advice to enable before launch.
  Also added: robloxplayerbeta, roblox, robloxplayerlauncher to _KNOWN_GAME_PROCS
  so Roblox processes are never killed by kill_bloat or CPU-jailed.

FIX: Zalo Web QR scan broken / frozen after kill_bloat
  OLD: kill_bloat lacked the GPU_RENDERER_FLAGS cmdline check that game_mode_on had.
       Chromium/Electron gpu-process and video-capture subprocesses sit at 0% CPU
       when idle → kill_bloat targeted them as bloat → killed the camera/QR worker.
  NEW: kill_bloat now has the full _RENDERER_FLAGS guard (same as game_mode_on):
       --type=gpu-process, --type=renderer, video-capture, zalo, etc.
       These subprocess types are now ALWAYS skipped in kill_bloat, regardless of
       CPU usage or memory usage.

FIX: kill_bloat killing terminals (Alacritty, Kitty, etc.) and modern IDEs
  OLD: _BLOAT_SKIP_ALWAYS only had bash/zsh/fish terminals.
       Alacritty, Kitty, WezTerm, Konsole, GNOME Terminal all missing.
       Cursor, Windsurf, Zed, Lapce (modern AI IDEs) also missing.
  NEW: Added all common terminal emulators + modern AI editors to BLOAT_SKIP_ALWAYS.

NEW: _kill_runaway_widgets() — zombie widget killer
  Hunts eww, waybar, polybar, conky, dunst, AGS when they exceed 85% CPU
  (runaway loop from script errors, IPC crashes, config mistakes).
  Uses 0.2s CPU sample to distinguish real runaway from startup burst.
  SIGKILL (not SIGTERM) because looping processes ignore SIGTERM.
  Called at the START of game_mode_on before CPU jail, so the zombie
  doesn't steal cores from the game. Logs instructions to restart manually.

NEW: _bypass_compositor_on/off() — FPS unlocker
  Linux X11: Detects and SIGSTOPs picom/compton/xcompmgr.
    Compositors force VSync via redirect mode → hard 60fps cap.
    Suspending them allows direct framebuffer rendering → uncapped FPS.
    Restored with SIGCONT on game_mode_off.
    Also sets _NET_WM_BYPASS_COMPOSITOR root property via xprop.
    For Wayland: cannot bypass (compositor IS display server) — logs
    per-compositor instructions (KWin, Hyprland, Sway).
  Windows: Sets SwapEffectUpgradeEnable=0 in DirectX registry key.
    Prevents Windows from overriding Exclusive Fullscreen with flip model.
    Allows DXGI games to enter true exclusive fullscreen → DWM bypassed.
    Also instructs user to use Fullscreen (not Borderless Windowed).

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
# WINDOWS TIMER RESOLUTION — timeBeginPeriod(1)
# ══════════════════════════════════════════════════════════════
# Default Windows scheduler tick = 15.6ms.
# Games need 1ms for precise frame timing, reduces micro-stutter.
# Used by Steam, Epic, MSI Afterburner — safe, no admin needed.

def _timer_resolution_set(log) -> bool:
    """Set Windows timer resolution to 1ms. Returns True if applied."""
    if not IS_WINDOWS:
        return False
    # FIX W3: winmm.dll is unavailable on Windows ARM64 (emulation layer does not
    # expose the timer resolution API). Guard with a platform check so the app
    # doesn't crash on ARM64 devices (Surface Pro X, Snapdragon laptops, etc.).
    import platform as _plat
    if _plat.machine().lower() in ('arm64', 'aarch64'):
        log("  ~ Timer resolution: skipped on ARM64 (winmm unavailable)", "warn")
        return False
    try:
        ctypes.windll.winmm.timeBeginPeriod(1)
        log("  + Timer resolution: 1ms (default 15.6ms) — smoother frame timing", "ok")
        return True
    except OSError:
        # Handles AttributeError / DLL not found on unusual Windows editions
        log("  ~ Timer resolution: winmm not available on this system", "warn")
        return False
    except Exception as e:
        log(f"  ~ Timer resolution: {e}", "warn")
        return False


def _timer_resolution_restore(was_set: bool, log):
    """Restore Windows timer resolution."""
    if not IS_WINDOWS or not was_set:
        return
    import platform as _plat
    if _plat.machine().lower() in ('arm64', 'aarch64'):
        return
    try:
        ctypes.windll.winmm.timeEndPeriod(1)
        log("  + Timer resolution: restored to default", "ok")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════
# WINDOWS ECOQOS — PROCESS_POWER_THROTTLING_STATE (Win 11+)
# ══════════════════════════════════════════════════════════════
# Sets hardware efficiency mode on background processes.
# CPU runs at lower power state for background work.
# Only works on Windows 11 (build 22000+) with modern Intel/AMD CPUs.

_PROCESS_INFORMATION_CLASS_POWER = 4   # ProcessPowerThrottling
_PROCESS_POWER_THROTTLING_CURRENT_VERSION = 1
_PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 0x1


class _PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
    _fields_ = [
        ("Version",    ctypes.c_ulong),
        ("ControlMask",ctypes.c_ulong),
        ("StateMask",  ctypes.c_ulong),
    ]


def _set_ecoqos(pid: int, enable: bool) -> bool:
    """Apply or remove EcoQoS (power efficiency mode) for a process."""
    if not IS_WINDOWS:
        return False
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x0200 | 0x0400, False, pid)
    if not handle:
        return False
    try:
        state = _PROCESS_POWER_THROTTLING_STATE(
            Version=_PROCESS_POWER_THROTTLING_CURRENT_VERSION,
            ControlMask=_PROCESS_POWER_THROTTLING_EXECUTION_SPEED,
            StateMask=_PROCESS_POWER_THROTTLING_EXECUTION_SPEED if enable else 0,
        )
        ok = kernel32.SetProcessInformation(
            handle,
            _PROCESS_INFORMATION_CLASS_POWER,
            ctypes.byref(state),
            ctypes.sizeof(state),
        )
        return bool(ok)
    finally:
        kernel32.CloseHandle(handle)  # ALWAYS close handle to prevent leak


def _is_windows_11() -> bool:
    """
    Check if running on Windows 11 (build 22000+).
    Uses sys.getwindowsversion() — official CPython API, never wrong format.
    platform.version() can return non-standard strings on some deployments.
    """
    if not IS_WINDOWS:
        return False
    try:
        v = sys.getwindowsversion()
        return v.major >= 10 and v.build >= 22000
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════
# GAME PROCESS DETECTION — v3.0 (generic, behavior-based)
# ══════════════════════════════════════════════════════════════
# Detect if a real game is running before applying aggressive CPU jail.
# Prevents browsers from being crippled when user is just browsing.
#
# REDESIGN RATIONALE (fixes v2.x false-positive/false-negative bugs):
#
#   BUG 1 (false positive): "bwrap"/"wine"/"proton" were in the
#   no-CPU-check name list. ANY Flatpak app (Discord, Spotify, GIMP...)
#   spawns via bwrap too — so the watcher kept reporting "game detected"
#   forever, even with zero games running.
#
#   BUG 2 (false negative): psutil's children(recursive=True) walks
#   /proc ppid relationships from the HOST pid namespace. Sandboxes
#   that unshare the PID namespace (bwrap --unshare-pid, which Flatpak
#   uses, including Sober/Roblox) can reparent the inner process so it
#   does NOT show up as a "child" of bwrap from the host's point of
#   view. Result: nice(-10) was applied to the empty wrapper shell,
#   never to the actual GPU-heavy RobloxPlayer process — no FPS gain.
#
#   FIX: two-tier detection.
#     Tier A — WRAPPER processes (bwrap, wine, proton, sober, ...) are
#       only a *signal*, never a verdict by themselves. We use them to
#       find the right corner of the process tree to search, but we
#       still require CPU evidence before calling anything "the game".
#     Tier B — Inside that corner (or system-wide as fallback) we pick
#       the heaviest process whose name isn't a known infra/IDE/tool
#       name. This works for ANY game, including ones we've never
#       heard of, on both Windows and Linux — no hardcoded title list
#       needed for the common case.
#
#   The hardcoded title list (_KNOWN_GAME_PROCS) is kept as a fast-path
#   for well-known engines/launchers, but it no longer includes generic
#   sandbox/wrapper binaries — those are handled by _WRAPPER_PROCS with
#   a CPU gate instead.

# Known game launchers — their child processes are likely games
_GAME_LAUNCHERS = {
    "steam", "steamwebhelper", "epicgameslauncher", "gog-galaxy",
    "battle.net", "upc", "origin", "riotclientux", "leagueclient",
    "riotclientservices",
}

# Process names that are themselves games (not launchers) — fast path,
# safe to trust by name alone because nothing else realistically uses
# these exact binary names.
_KNOWN_GAME_PROCS = {
    # Common engines / overlays
    "unrealcefsubprocess", "cef-subprocess", "gameoverlayui",
    # Popular titles
    "csgo", "cs2", "dota2", "gta5", "gtav", "cyberpunk2077",
    "eldenring", "baldursgate3", "bg3", "valorant", "fortnite",
    "minecraft", "terraria", "stardewvalley", "factorio",
    "rdr2", "witcher3", "witcher2", "witcher",
    "overwatch", "overwatch2", "diablo4",
    # Roblox Windows
    "robloxplayerbeta", "roblox", "robloxplayerlauncher", "robloxcrashhandler",
}

# Generic sandbox / wrapper / compatibility-layer processes. These run
# games but ALSO run countless non-game apps (any Flatpak, any Wine
# tool, etc.) — so name match alone is meaningless. They are only used
# as a STARTING POINT to search for a heavy descendant; the wrapper
# PID itself is never treated as "the game".
_WRAPPER_PROCS = {
    "bwrap",          # bubblewrap sandbox — used by ALL Flatpak apps
    "wine", "wine64", "wineserver",
    "proton",
    "steam-runtime",
    "gamescope",      # Valve gaming compositor
    "lutris",
    # Known game-specific launchers that are themselves thin wrappers
    # around a real game binary — same treatment as bwrap/wine.
    "sober", "sober_services",   # Roblox-on-Linux launcher
    "grapejuice", "vinegar",     # legacy Roblox Wine wrappers
}

# Minimum CPU usage (%) for a process found *under* a wrapper to be
# considered "the actual game" rather than an idle helper/IPC thread.
_WRAPPER_CHILD_CPU_THRESHOLD = 8.0
# Delay (seconds) between first CPU reading and the confirmation re-check
# in _find_heavy_descendant. Filters out one-off spikes (a launcher
# rendering its UI once) from sustained game/render activity. Kept short
# so game detection still feels instant to the user.
_WRAPPER_CPU_RECHECK_DELAY = 0.3

# FIX v2.5: Heavy non-game processes — would trigger false "game detected"
# if we used a bare CPU>30% heuristic. Never treat these as games.
_KNOWN_HEAVY_NON_GAMES = {
    # Video encoding / transcoding
    "ffmpeg", "ffplay", "ffprobe", "handbrake", "handbrakeenv",
    "x264", "x265", "nvenc", "amf",
    # Build tools / compilers
    "cargo", "rustc", "cc", "c++", "gcc", "g++", "clang", "clang++",
    "make", "ninja", "cmake", "msbuild", "devenv", "cl",
    "webpack", "esbuild", "rollup", "parcel", "tsc",
    "node", "npm", "yarn", "pnpm", "bun",
    "java", "javac", "kotlinc", "mvn", "gradle",
    # Backup / sync
    "robocopy", "rsync", "rclone", "restic", "duplicati",
    # Antivirus / security scanners
    "mpcmdrun", "msmpeng", "mbam", "avgnt", "avgsvc",
    # AI / ML training
    "python", "python3",   # already in _NEVER_GAME but extra safety
    "jupyter", "ipython",
}

# Single source of truth for "never a game" process names, used by
# EVERY detection tier (Tier 1/3 main loop AND Tier 2 wrapper-descendant
# search). A previous version kept two separate blocklists (_NON_GAME
# for the main loop, _WRAPPER_CHILD_SKIP for wrapper descendants) that
# went out of sync — _WRAPPER_CHILD_SKIP didn't include "chrome" or
# "hyprland", so when cgroup-based descendant search found the desktop
# compositor or browser sharing a cgroup with a wrapper, nothing blocked
# them, and they got reported as "game detected". Merging into one set
# closes that gap for good — any name added here is excluded everywhere.
_NEVER_GAME = {
    # Browsers
    "chrome", "chromium", "msedge", "firefox", "brave", "opera", "vivaldi",
    # Chat / collab
    "discord", "slack", "teams", "zoom",
    # IDEs
    "code", "idea", "pycharm",
    # Windows system processes
    "explorer", "svchost", "dwm", "csrss", "winlogon", "lsass",
    "plugplay.exe", "services.exe", "winedevice.exe",
    "explorer.exe", "rpcss.exe", "svchost.exe",
    # Interpreters / this app
    "python", "python3", "cyberclean", "steamwebhelper",
    # Streaming
    "obs", "obs32", "obs64",
    # Desktop compositors / window managers — ALWAYS busy rendering the
    # whole screen, must never be mistaken for "the game" just because
    # they share a cgroup/session with a sandboxed app.
    "hyprland", "sway", "kwin_wayland", "kwin_x11", "kwin",
    "gnome-shell", "weston", "mutter", "xfwm4", "i3",
    # Sandbox/IPC plumbing seen as children of bwrap/wine/flatpak
    "bwrap", "xdg-dbus-proxy", "dbus-daemon", "dbus-broker",
    "pressure-vessel-wrap", "pressure-vessel-launcher",
    "bash", "sh", "env", "flatpak-portal", "wineserver",
} | _KNOWN_HEAVY_NON_GAMES

_GAME_CPU_THRESHOLD = 15.0   # % CPU — games usually use >15% when active


def _load_steam_game_names() -> set:
    """
    Parse Steam .acf manifests to get installed game executable names.
    Returns set of lowercased exe names (without .exe) for fast lookup.

    FIX v2.5: Steam library integration — detection is 100% accurate for
    installed Steam games instead of relying on a hardcoded list.
    """
    names = set()
    # Common Steam library paths
    steam_paths = []
    if IS_LINUX:
        home = Path.home()
        steam_paths = [
            home / ".steam/steam/steamapps",
            home / ".local/share/Steam/steamapps",
        ]
    elif IS_WINDOWS:
        import os as _os
        prog86 = _os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")
        prog   = _os.environ.get("ProgramFiles",       "C:/Program Files")
        steam_paths = [
            Path(prog86) / "Steam/steamapps",
            Path(prog)   / "Steam/steamapps",
        ]

    for steam_dir in steam_paths:
        if not steam_dir.exists():
            continue
        try:
            for acf in steam_dir.glob("appmanifest_*.acf"):
                try:
                    content = acf.read_text(errors="ignore")
                    # Extract "LaunchItems" executable entries
                    # Also extract "name" for display purposes
                    for line in content.splitlines():
                        line = line.strip()
                        # "executable" field in launch configs
                        if '"executable"' in line.lower():
                            # Value is like: "executable"    "game.exe"
                            parts = line.replace('"', '').split()
                            if len(parts) >= 2:
                                exe = parts[-1].lower()
                                # Strip path — only keep filename
                                exe = exe.split('/')[-1].split('\\')[-1]
                                exe = exe.replace('.exe', '')
                                if exe and len(exe) > 2:
                                    names.add(exe)
                except Exception:
                    pass
        except Exception:
            pass
    return names


# Module-level cache for Steam games — loaded once per session
_STEAM_GAME_NAMES: Optional[set] = None


def _get_steam_game_names() -> set:
    global _STEAM_GAME_NAMES
    if _STEAM_GAME_NAMES is None:
        _STEAM_GAME_NAMES = _load_steam_game_names()
    return _STEAM_GAME_NAMES


def _process_pidns_inode(pid: int) -> Optional[int]:
    """
    Return the inode number identifying a process's PID namespace, or None.
    Two processes are in the exact same PID namespace if and only if this
    inode matches — this is the kernel's own authoritative answer, not a
    heuristic over string paths.

    Why this replaces both the earlier SID and cgroup approaches:
    - SID grouping matched the whole desktop login session (Hyprland,
      chrome, everything) — far too broad.
    - cgroup-path grouping was meant to be narrower, but on real systems
      the "does this look like an app-specific scope" check
      (substring match for "app-"/".scope") is not reliable: window
      managers, launchers (rofi), file managers (nautilus) and the
      actual sandboxed process can all legitimately end up under
      scopes that pass that same shallow check, so they kept leaking
      through as false positives.
    - PID namespace membership has no such ambiguity: bwrap is one of
      the few things on a normal desktop that actually calls unshare()
      on the PID namespace. A regular app launched by rofi/the DE
      shares the SAME pid namespace as everything else on the desktop
      (the host's), so it can never collide with the sandbox's
      namespace by accident. This is the property we actually care
      about, checked directly instead of inferred from naming
      conventions that vary across distros/compositors.
    """
    if not IS_LINUX:
        return None
    try:
        return os.stat(f"/proc/{pid}/ns/pid").st_ino
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        return None


def _find_heavy_descendant(wrapper_pid: int, cpu_lookup: dict) -> Optional["psutil.Process"]:
    """
    Given a wrapper/sandbox PID (bwrap, wine, proton, sober, ...), find the
    actual heavy process running "inside" it — the one that should receive
    the priority boost. This is what _KNOWN_GAME_PROCS + children() failed
    to do for namespaced sandboxes (see module docstring, BUG 2).

    Strategy, in order:
      1. True descendants via psutil (works for normal cases — Wine without
         extra namespace tricks, Proton, etc.)
      2. Same PID-namespace inode as the wrapper (see _process_pidns_inode
         docstring) — survives bwrap's --unshare-pid reparenting WITHOUT
         the false positives that session-id and cgroup-path heuristics
         both produced in earlier versions (they matched ordinary desktop
         apps like Hyprland/chrome/rofi/nautilus that happen to share a
         session or a similarly-shaped cgroup scope, but never share an
         actual kernel PID namespace with the sandbox).
      3. If nothing qualifies, return None (caller falls back to not
         reporting anything for this wrapper — silence is safer than a
         wrong guess).

    A candidate only counts if its CPU usage clears _WRAPPER_CHILD_CPU_
    THRESHOLD on TWO samples taken _WRAPPER_CPU_RECHECK_DELAY apart, not
    just one instant reading — this filters out a process that merely
    spiked once while loading (e.g. a launcher rendering its UI) from one
    that is genuinely doing sustained game/render work.
    """
    if not HAS_PSUTIL:
        return None

    candidates = []

    # 1. Direct/recursive children (works when no PID-namespace tricks)
    try:
        wrapper = psutil.Process(wrapper_pid)
        candidates.extend(wrapper.children(recursive=True))
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    # 2. Same PID-namespace inode — the kernel-authoritative way to find
    #    processes that are actually inside the same sandbox invocation,
    #    immune to the false positives string-based grouping produced.
    wrapper_ns = _process_pidns_inode(wrapper_pid)
    host_ns = _process_pidns_inode(os.getpid())  # our own (host) namespace
    if wrapper_ns is not None and wrapper_ns != host_ns:
        # Wrapper actually unshared its PID namespace — search for other
        # processes sharing that SAME non-host namespace.
        try:
            for p in psutil.process_iter(["pid"]):
                if p.pid == wrapper_pid:
                    continue
                if _process_pidns_inode(p.pid) == wrapper_ns:
                    candidates.append(p)
        except Exception:
            pass
    # If wrapper_ns == host_ns (or unreadable), the wrapper did NOT create
    # an isolated namespace — there is nothing extra to search for beyond
    # its real children(), already covered by step 1. We deliberately do
    # NOT fall back to cgroup/session matching here anymore.

    best, best_cpu = None, 0.0
    seen_pids = set()
    for p in candidates:
        try:
            if p.pid in seen_pids:
                continue
            seen_pids.add(p.pid)
            nm = (p.name() or "").lower().replace(".exe", "")
            if nm in _NEVER_GAME:
                continue
            cpu = cpu_lookup.get(p.pid)
            if cpu is None:
                cpu = p.cpu_percent(interval=0)
            if cpu > best_cpu:
                best, best_cpu = p, cpu
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    if best is not None and best_cpu >= _WRAPPER_CHILD_CPU_THRESHOLD:
        # Require SUSTAINED cpu usage — re-check after a short delay so a
        # one-off spike (launcher UI render, brief decompression, etc.)
        # cannot pass as "the game". Real game/render loops stay busy.
        try:
            recheck_cpu = best.cpu_percent(interval=_WRAPPER_CPU_RECHECK_DELAY)
            if recheck_cpu >= _WRAPPER_CHILD_CPU_THRESHOLD:
                return best
            return None
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    # 3. Last resort: the wrapper itself, if IT is the one burning CPU
    #    (e.g. a simple Wine game with no extra subprocess, or a bwrap
    #    sandbox that didn't unshare PID namespace). We only get here if
    #    no descendant/cgroup-mate qualified, so this can't double-count.
    try:
        wrapper_cpu = cpu_lookup.get(wrapper_pid)
        if wrapper_cpu is None:
            wrapper_cpu = psutil.Process(wrapper_pid).cpu_percent(interval=0)
        if wrapper_cpu >= _WRAPPER_CHILD_CPU_THRESHOLD:
            return psutil.Process(wrapper_pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    return None


def _detect_running_games(cpu_samples: Optional[dict] = None) -> tuple:
    """
    Return (games_list, cpu_samples_dict).
    games_list = list of (pid, name) for the processes that should
                 actually receive the game-priority boost.
    cpu_samples_dict = {pid: cpu_pct} — reusable by kill_bloat to skip warm-up.

    v3.0 — generic, behavior-based, namespace-aware (see module docstring
    above _GAME_LAUNCHERS for the full rationale). Works for unknown/indie
    games and for sandboxed launchers (Sober/Roblox, any Flatpak-wrapped
    game) without needing their exact binary name in a hardcoded list.

    Strategy (3 tiers, in order — first match wins per process):
      1. Exact known game name (_KNOWN_GAME_PROCS) or Steam library name.
         Trusted by name alone — no CPU gate needed, these names aren't
         realistically used by anything else.
      2. Wrapper/sandbox process (_WRAPPER_PROCS: bwrap, wine, proton,
         sober, ...) — NOT trusted by name alone (false-positive source
         in older versions). We locate the heavy descendant running
         inside it via _find_heavy_descendant(); only THAT process is
         reported as the game. If no heavy descendant clears the CPU
         gate, the wrapper itself is not reported at all (fixes the
         "game detected" spam with no game running).
      3. Child of a known launcher (Steam, Epic, ...) with CPU above
         threshold — catches games launched via Steam without Proton.
    """
    if not HAS_PSUTIL:
        return [], {}

    all_game_names = _KNOWN_GAME_PROCS | _get_steam_game_names()

    games = []
    wrapper_pids = []
    launcher_pids = set()
    for p in psutil.process_iter(["pid", "name"]):
        try:
            nm = (p.info["name"] or "").lower().replace(".exe", "")
            if nm in _GAME_LAUNCHERS:
                launcher_pids.add(p.pid)
            if nm in _WRAPPER_PROCS:
                wrapper_pids.append(p.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # Warm up cpu_percent — or reuse provided samples
    new_samples: dict = {}
    all_procs = []
    if cpu_samples is None:
        for p in psutil.process_iter(["pid", "name", "ppid"]):
            try:
                p.cpu_percent(interval=0)
                all_procs.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        import time as _t; _t.sleep(0.5)
    else:
        for p in psutil.process_iter(["pid", "name", "ppid"]):
            try:
                all_procs.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    cpu_lookup: dict = {}
    matched_pids = set()

    for p in all_procs:
        try:
            with p.oneshot():
                nm = (p.name() or "").lower().replace(".exe", "")
                if cpu_samples and p.pid in cpu_samples:
                    cpu = cpu_samples[p.pid]
                else:
                    cpu = p.cpu_percent(interval=0)
                new_samples[p.pid] = cpu
                cpu_lookup[p.pid] = cpu

                if nm in _NEVER_GAME:
                    continue

                # Tier 1: exact known game name — trusted, no CPU gate
                if nm in all_game_names:
                    games.append((p.pid, p.name()))
                    matched_pids.add(p.pid)
                    continue

                # Tier 3: child of a launcher using significant CPU
                ppid = p.ppid()
                if ppid in launcher_pids and cpu > _GAME_CPU_THRESHOLD:
                    games.append((p.pid, p.name()))
                    matched_pids.add(p.pid)

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # Tier 2: wrapper/sandbox processes — NEVER trusted by name alone.
    # Only report the heavy descendant actually doing work, if any.
    for wpid in wrapper_pids:
        if wpid in matched_pids:
            continue
        heavy = _find_heavy_descendant(wpid, cpu_lookup)
        if heavy is not None and heavy.pid not in matched_pids:
            try:
                games.append((heavy.pid, heavy.name()))
                matched_pids.add(heavy.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    return games, new_samples


# ══════════════════════════════════════════════════════════════
# BATTERY CHECK
# ══════════════════════════════════════════════════════════════

def _is_on_battery() -> bool:
    """True if running on battery (not plugged in). False if desktop or plugged."""
    if not HAS_PSUTIL:
        return False
    try:
        bat = psutil.sensors_battery()
        if bat is None:
            return False   # No battery = desktop
        return not bat.power_plugged
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════
# SSD DETECTION
# ══════════════════════════════════════════════════════════════

_SSD_CACHE: Optional[bool] = None   # cached result — disk type never changes in session

def _has_only_ssd() -> bool:
    """
    True if all system disks appear to be non-rotational (SSD/NVMe).
    False if any HDD detected (rotational=True).
    Falls back to True (assume SSD) if detection fails.

    FIX v2.5: Result cached at module level — avoids PowerShell startup (~1-3s)
    on every game_mode_on() call.
    """
    global _SSD_CACHE
    if _SSD_CACHE is not None:
        return _SSD_CACHE

    if IS_LINUX:
        try:
            rotational_found = False
            for dev_path in Path("/sys/block").iterdir():
                rot_file = dev_path / "queue/rotational"
                if rot_file.exists():
                    val = rot_file.read_text().strip()
                    if val == "1":
                        rotational_found = True
                        break
            _SSD_CACHE = not rotational_found
            return _SSD_CACHE
        except Exception:
            _SSD_CACHE = True
            return True
    elif IS_WINDOWS:
        try:
            out = subprocess.run(
                'powershell -NoProfile -Command "Get-PhysicalDisk | Select-Object MediaType | ConvertTo-Csv -NoTypeInformation"',
                shell=True, capture_output=True, text=True,
                creationflags=0x08000000, timeout=8
            ).stdout
            _SSD_CACHE = "HDD" not in out
            return _SSD_CACHE
        except Exception:
            _SSD_CACHE = True
            return True
    _SSD_CACHE = True
    return True


# ══════════════════════════════════════════════════════════════
# GPU VRAM DETECTION
# ══════════════════════════════════════════════════════════════

_VRAM_CACHE: Optional[float] = None   # cached — GPU doesn't change during session

def _get_gpu_vram_gb() -> float:
    """Return GPU VRAM in GB. Returns 0.0 if detection fails. Result cached."""
    global _VRAM_CACHE
    if _VRAM_CACHE is not None:
        return _VRAM_CACHE
    if IS_LINUX:
        try:
            # Most reliable: sysfs drm
            for card in sorted(Path("/sys/class/drm").iterdir()):
                vram_file = card / "device/mem_info_vram_total"
                if vram_file.exists():
                    vram_bytes = int(vram_file.read_text().strip())
                    _VRAM_CACHE = vram_bytes / (1024 ** 3)
                    return _VRAM_CACHE
        except Exception:
            pass
        _VRAM_CACHE = 0.0
        return 0.0

    elif IS_WINDOWS:
        import platform as _plat
        _arm = _plat.machine().lower() in ("arm64", "aarch64")

        def _vram_from_wmic():
            out = subprocess.run(
                "wmic path Win32_VideoController get AdapterRAM /value",
                shell=True, capture_output=True, text=True,
                creationflags=0x08000000, timeout=8,
            ).stdout
            max_vram = 0
            for line in out.splitlines():
                if "AdapterRAM=" in line:
                    try:
                        val = int(line.split("=")[1].strip())
                        max_vram = max(max_vram, val)
                    except ValueError:
                        pass
            return max_vram / (1024**3) if max_vram else 0.0

        def _vram_from_cim():
            ps = (
                "(Get-CimInstance Win32_VideoController | "
                "ForEach-Object { $_.AdapterRAM } | Measure-Object -Maximum).Maximum"
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, text=True, creationflags=0x08000000, timeout=10,
            )
            txt = (r.stdout or "").strip()
            if r.returncode != 0 or not txt:
                return 0.0
            try:
                val = int(txt)
            except ValueError:
                return 0.0
            if val <= 0:
                return 0.0
            return val / (1024**3)

        try:
            if _arm:
                g = _vram_from_cim()
                _VRAM_CACHE = g if g > 0 else 0.0
            else:
                try:
                    _VRAM_CACHE = _vram_from_wmic()
                except OSError:
                    _VRAM_CACHE = _vram_from_cim()
            return _VRAM_CACHE
        except Exception:
            _VRAM_CACHE = 0.0
            return 0.0
    return 0.0


# ══════════════════════════════════════════════════════════════
# WINDOWS NETWORK TWEAK — Disable Nagle Algorithm
# ══════════════════════════════════════════════════════════════
# Nagle bundles small TCP packets → adds 20-40ms latency in online games.
# Disabling it improves online game responsiveness.
# Requires admin rights to write registry.

def _disable_nagle(log) -> list:
    """
    Disable Nagle algorithm on all active network adapters.
    Returns list of (reg_path, old_ack, old_nodelay) for restore.
    """
    if not IS_WINDOWS:
        return []
    try:
        import winreg
    except ImportError:
        return []

    changed = []
    base = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"

    # FIX v2.5: _read_val defined outside loop — was being redefined every iteration
    def _read_val(k, name, default):
        try:
            v, _ = winreg.QueryValueEx(k, name)
            return v
        except Exception:
            return default

    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base)
        i = 0
        while True:
            try:
                iface = winreg.EnumKey(root, i); i += 1
                iface_path = f"{base}\\{iface}"
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, iface_path, 0,
                                     winreg.KEY_READ | winreg.KEY_SET_VALUE)

                old_ack   = _read_val(key, "TcpAckFrequency", None)
                old_delay = _read_val(key, "TCPNoDelay", None)

                winreg.SetValueEx(key, "TcpAckFrequency", 0, winreg.REG_DWORD, 1)
                winreg.SetValueEx(key, "TCPNoDelay",       0, winreg.REG_DWORD, 1)
                winreg.CloseKey(key)
                changed.append((iface_path, old_ack, old_delay))
            except OSError:
                break
        winreg.CloseKey(root)
        if changed:
            log(f"  + Network: Nagle algorithm disabled on {len(changed)} adapters — lower ping", "ok")
        else:
            log("  ~ Network: no adapters found for Nagle tweak", "warn")
    except Exception as e:
        log(f"  ~ Network tweak: {e}", "warn")
    return changed


def _restore_nagle(changed: list, log):
    """Restore Nagle algorithm settings."""
    if not IS_WINDOWS or not changed:
        return
    try:
        import winreg
        for iface_path, old_ack, old_delay in changed:
            try:
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, iface_path, 0,
                                     winreg.KEY_SET_VALUE)
                if old_ack is None:
                    try: winreg.DeleteValue(key, "TcpAckFrequency")
                    except Exception: pass
                else:
                    winreg.SetValueEx(key, "TcpAckFrequency", 0, winreg.REG_DWORD, old_ack)
                if old_delay is None:
                    try: winreg.DeleteValue(key, "TCPNoDelay")
                    except Exception: pass
                else:
                    winreg.SetValueEx(key, "TCPNoDelay", 0, winreg.REG_DWORD, old_delay)
                winreg.CloseKey(key)
            except Exception:
                pass
        log("  + Network: Nagle algorithm restored", "ok")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════
# WINDOWS WORKING SET TRIM — real memory release
# ══════════════════════════════════════════════════════════════

def _trim_working_sets(log) -> int:
    """
    Trim working sets of idle background processes using SetProcessWorkingSetSizeEx.
    Forces Windows to move idle process pages to standby list →
    available for other processes without disk I/O.
    Returns count of trimmed processes.
    """
    if not IS_WINDOWS or not HAS_PSUTIL:
        return 0

    _TRIM_SKIP = {
        'dwm.exe', 'explorer.exe', 'csrss.exe', 'smss.exe', 'winlogon.exe',
        'lsass.exe', 'audiodg.exe', 'svchost.exe', 'services.exe',
        'chrome.exe', 'msedge.exe', 'firefox.exe', 'brave.exe',
        'discord.exe', 'code.exe',
    }

    trimmed = 0
    fg_pid = _get_foreground_pid()
    kernel32 = ctypes.windll.kernel32

    for p in psutil.process_iter(["pid", "name"]):
        try:
            nm = (p.info["name"] or "").lower()
            if nm in _TRIM_SKIP or p.pid == fg_pid:
                continue
            cpu = p.cpu_percent(interval=0)
            if cpu > 1.0:
                continue   # skip active processes
            # Open process with VM_OPERATION rights
            handle = kernel32.OpenProcess(0x0008 | 0x0400, False, p.pid)
            if not handle:
                continue
            try:
                # SetProcessWorkingSetSizeEx(-1, -1, 0) = trim to minimum
                ok = kernel32.SetProcessWorkingSetSizeEx(
                    handle,
                    ctypes.c_size_t(0xFFFFFFFFFFFFFFFF),   # SIZE_MAX = trim
                    ctypes.c_size_t(0xFFFFFFFFFFFFFFFF),
                    ctypes.c_ulong(0)
                )
                if ok:
                    trimmed += 1
            finally:
                kernel32.CloseHandle(handle)  # ALWAYS close handle
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            pass

    return trimmed

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
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(
        _PROCESS_SET_INFORMATION | _PROCESS_QUERY_INFORMATION,
        False, pid
    )
    if not handle:
        return False
    try:
        info = _MEMORY_PRIORITY_INFO(MemoryPriority=priority)
        ok = kernel32.SetProcessInformation(
            handle,
            _PROCESS_MEMORY_PRIORITY_INFO_CLASS,
            ctypes.byref(info),
            ctypes.sizeof(info)
        )
        return bool(ok)
    finally:
        kernel32.CloseHandle(handle)  # ALWAYS close handle to prevent leak


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


def _cg_write(cg_path: str, filename: str, value: str, log=None) -> bool:
    try:
        p = Path(cg_path) / filename
        if p.exists():
            p.write_text(value)
            return True
        elif log:
            log(f"  ~ cgroup file not found: {filename}", "warn")
    except (OSError, PermissionError) as e:
        if log:
            log(f"  ~ cgroup write failed {filename}: {e}", "warn")
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
        _cg_write(cg_path, "cpu.weight", "20", log)
        _cg_write(cg_path, "io.weight", "20", log)
        _cg_write(cg_path, "memory.low", str(512 * 1024 * 1024), log)
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
    "alacritty", "kitty", "wezterm", "konsole", "gnome-terminal",
    "xfce4-terminal", "lxterminal", "tilix", "foot", "st",
    # Modern IDEs / AI editors
    "cursor", "windsurf", "zed", "lapce",
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


# ══════════════════════════════════════════════════════════════
# RUNAWAY WIDGET KILLER
# ══════════════════════════════════════════════════════════════
# eww, waybar, polybar, conky etc. can enter infinite loops that consume
# 90-99% CPU. This is invisible to kill_bloat (which only targets IDLE
# processes). _kill_runaway_widgets() specifically hunts these known UI
# widget daemons when they're consuming abnormally high CPU.
#
# Run BEFORE kill_bloat and BEFORE CPU jail in game_mode_on so the rogue
# process doesn't steal cores from the game.
#
# Threshold: 85% CPU sustained over 0.2s sample — avoids false kills
# during legitimate short bursts (initial render, config reload).

_WIDGET_SUSPECTS = {
    "eww",        # Elkowar's Wacky Widgets — most common runaway
    "waybar",     # Wayland bar (can loop on ipc errors)
    "polybar",    # X11 bar
    "conky",      # Desktop widget (known to loop on script errors)
    "dunst",      # Notification daemon (can loop on malformed notif)
    "ags",        # Aylur's GTK Shell
    "astal",      # AGS successor
    "ignis",      # Another GTK shell
    "hyprpaper",  # Hyprland wallpaper daemon (rare but possible)
    "swaybar",    # sway bar (if custom scripts loop)
}

_WIDGET_CPU_THRESHOLD = 85.0   # % — sustained above this = zombie loop

def _kill_runaway_widgets(log) -> int:
    """
    Kill UI widget processes that are stuck in a CPU-consuming loop.

    Strategy:
    1. Find processes whose name matches _WIDGET_SUSPECTS
    2. Warm up cpu_percent (0.2s) — short enough to not delay game mode
    3. Kill only if STILL above threshold after warm-up (avoids killing
       legitimate startup bursts)
    4. SIGKILL not SIGTERM — a looping process ignores SIGTERM

    Returns count of processes killed.
    """
    if not IS_LINUX or not HAS_PSUTIL:
        return 0

    killed = 0
    candidates = []

    # Pass 1: find widget processes and start CPU measurement
    for p in psutil.process_iter(["pid", "name"]):
        try:
            nm = (p.info["name"] or "").lower()
            if nm in _WIDGET_SUSPECTS:
                p.cpu_percent(interval=0)   # warm up — start measurement
                candidates.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    if not candidates:
        return 0

    # Short sleep — just enough to get valid CPU reading
    import time as _t
    _t.sleep(0.2)

    # Pass 2: check actual CPU and kill if still runaway
    for p in candidates:
        try:
            cpu = p.cpu_percent(interval=0)
            nm  = p.name()
            if cpu > _WIDGET_CPU_THRESHOLD:
                # Double-check: read /proc/stat to confirm it's not a transient spike
                try:
                    status = p.status()
                    if status == psutil.STATUS_ZOMBIE:
                        # Already zombie — just reap, no SIGKILL needed
                        log(f"  ✕ Zombie widget (Z state): {nm} (pid {p.pid}) — already dead", "warn")
                        continue
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

                # True runaway loop — SIGKILL (SIGTERM is ignored by looping procs)
                p.kill()
                killed += 1
                log(f"  ✕ Killed runaway widget: {nm} (pid {p.pid}, {cpu:.0f}% CPU)", "warn")
                log(f"    → Restart {nm} manually after gaming session", "ok")
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    if killed == 0 and candidates:
        # Found widget processes but none were runaway — log quietly
        names = [p.name() for p in candidates if not p.status() == psutil.STATUS_ZOMBIE
                 if True]
        pass  # Don't spam log with "all good" for every widget

    return killed


# ══════════════════════════════════════════════════════════════
# COMPOSITOR BYPASS — Linux X11 + Windows DWM
# ══════════════════════════════════════════════════════════════
# The single biggest reason FPS is capped at 60 on Linux/Windows:
#
# Linux X11:  Picom/Compton forces VSync via redirect mode.
#             Every frame → compositor composites → display.
#             Bypassing it (killing picom during game) lets the game
#             write directly to the framebuffer → uncapped FPS.
#             Downside: screen tearing when looking around fast.
#             For competitive gaming: tearing < 60fps cap, always.
#
# Linux Wayland: Compositor cannot be bypassed (it IS the display server).
#             Wayland protocol has no equivalent of X11 unredirect.
#             Best we can do: hint apps with _MUTTER_HINTS / wp-fifo-v1.
#             Actual FPS unlock requires compositor-side config (KWin,
#             Sway, Hyprland all have their own "game mode" settings).
#
# Windows:   DWM cannot be fully bypassed on Win 8+.
#            BUT: running game in Exclusive Fullscreen mode bypasses DWM.
#            We set the registry hint that tells DWM to allow exclusive mode.
#            Per-app FSE flag (DXGI_SWAP_EFFECT_DISCARD) + disable MPOMX.

def _bypass_compositor_on(log, saved: dict):
    """
    Bypass compositor for maximum FPS.

    Linux X11:
      - Detect and suspend Picom/Compton (SIGSTOP, not kill — restores on game_mode_off)
      - Set _NET_WM_BYPASS_COMPOSITOR hint via xprop if available
      - Log warning for Wayland (cannot bypass — compositor IS display server)

    Windows:
      - Disable MPCOMPOSITING to allow exclusive fullscreen
      - Set DWM flush interval hint for lower latency
    """
    if IS_LINUX:
        session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
        wayland_display = os.environ.get("WAYLAND_DISPLAY", "")
        display = os.environ.get("DISPLAY", "")

        if wayland_display or session_type == "wayland":
            # Wayland: cannot bypass compositor — inform user
            log("  ~ Compositor: Wayland detected — cannot bypass (compositor = display server)", "warn")
            log("  i For uncapped FPS on Wayland:", "ok")
            log("    KWin:      System Settings → Display → Compositor → uncheck 'Enable compositor'", "ok")
            log("    Hyprland:  misc:no_vfr = false  in hyprland.conf", "ok")
            log("    Sway/wlroots: game runs at monitor refresh rate (no arbitrary cap)", "ok")
            saved["compositor_bypassed"] = None
            return

        if not display:
            log("  ~ Compositor: no DISPLAY set — skipping bypass", "warn")
            saved["compositor_bypassed"] = None
            return

        # X11: find and suspend running compositor
        COMPOSITOR_NAMES = [
            "picom", "compton", "xcompmgr", "compiz",
            "kwin_x11",   # only suspend if in game, restore after
        ]
        suspended_compositors = []

        for comp_name in COMPOSITOR_NAMES:
            for p in psutil.process_iter(["pid", "name"]) if HAS_PSUTIL else []:
                try:
                    if (p.info["name"] or "").lower() == comp_name:
                        # SIGSTOP: suspend, not kill — compositor state preserved
                        # kwin_x11: don't suspend (DE will break), just reduce its priority
                        if comp_name == "kwin_x11":
                            try:
                                p.nice(10)
                                suspended_compositors.append(("kwin_nice", p.pid, p.name(), 0))
                                log(f"  ~ KWin: niceness raised (full bypass not safe in KDE)", "warn")
                            except (psutil.AccessDenied, psutil.NoSuchProcess):
                                pass
                        else:
                            os.kill(p.pid, signal.SIGSTOP)
                            suspended_compositors.append(("sigstop", p.pid, p.name(), 0))
                            log(f"  + Compositor suspended: {p.name()} (pid {p.pid}) → direct render", "ok")
                except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
                    pass

        # Set _NET_WM_BYPASS_COMPOSITOR on root window so future windows know
        if shutil.which("xprop") and display:
            try:
                subprocess.run(
                    ["xprop", "-root", "-f", "_NET_WM_BYPASS_COMPOSITOR", "32c",
                     "-set", "_NET_WM_BYPASS_COMPOSITOR", "1"],
                    capture_output=True, timeout=3
                )
                log("  + _NET_WM_BYPASS_COMPOSITOR: set (future fullscreen apps go direct)", "ok")
                saved["xprop_bypass_set"] = True
            except Exception:
                saved["xprop_bypass_set"] = False
        else:
            saved["xprop_bypass_set"] = False

        saved["compositor_bypassed"] = suspended_compositors

        if not suspended_compositors:
            log("  i No compositor found running (picom/compton) — already direct render mode", "ok")
        else:
            log(f"  + {len(suspended_compositors)} compositor(s) suspended — FPS uncapped from VSync", "ok")
            log("  ⚠ Screen tearing may appear — normal in direct render mode", "warn")

    elif IS_WINDOWS:
        # Windows: disable MPCOMPOSITING for exclusive fullscreen support
        # This allows DXGI games to enter true exclusive fullscreen (bypasses DWM)
        # Lower DWM timer interval for reduced display latency
        try:
            import winreg
            changes = []

            # 1. Allow exclusive fullscreen (DXGI override)
            try:
                key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\DirectX\UserGpuPreferences",
                    0, winreg.KEY_READ | winreg.KEY_SET_VALUE
                )
                try:
                    orig, _ = winreg.QueryValueEx(key, "DirectXUserGlobalSettings")
                except Exception:
                    orig = None
                # SwapEffectUpgradeEnable=0 prevents Windows from overriding
                # exclusive fullscreen with flip model (which re-enables DWM composition)
                new_val = (orig or "") + ";SwapEffectUpgradeEnable=0"
                winreg.SetValueEx(key, "DirectXUserGlobalSettings", 0, winreg.REG_SZ, new_val)
                winreg.CloseKey(key)
                changes.append(("DirectXUserGlobalSettings", orig))
                log("  + DirectX: exclusive fullscreen allowed (DWM bypass enabled)", "ok")
            except Exception:
                pass

            saved["compositor_bypassed"] = changes
            if changes:
                log("  + DWM: exclusive fullscreen mode active — game draws directly", "ok")
                log("  i Launch game in Fullscreen (not Borderless Windowed) for effect", "ok")
            else:
                log("  ~ DWM bypass: registry not writable (needs admin for full effect)", "warn")
        except Exception as e:
            log(f"  ~ Compositor bypass: {e}", "warn")
            saved["compositor_bypassed"] = []


def _bypass_compositor_off(saved: dict, log):
    """Restore compositor after gaming session."""
    if IS_LINUX:
        bypassed = saved.get("compositor_bypassed") or []
        resumed = 0
        for entry in bypassed:
            method, pid, name, _ = entry
            try:
                if method == "sigstop":
                    os.kill(pid, signal.SIGCONT)
                    resumed += 1
                    log(f"  ▶ Compositor resumed: {name} (pid {pid})", "ok")
                elif method == "kwin_nice":
                    if HAS_PSUTIL:
                        psutil.Process(pid).nice(0)
            except (ProcessLookupError, psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # Restore _NET_WM_BYPASS_COMPOSITOR
        if saved.get("xprop_bypass_set") and shutil.which("xprop"):
            try:
                subprocess.run(
                    ["xprop", "-root", "-f", "_NET_WM_BYPASS_COMPOSITOR", "32c",
                     "-set", "_NET_WM_BYPASS_COMPOSITOR", "0"],
                    capture_output=True, timeout=3
                )
            except Exception:
                pass

        if resumed == 0 and bypassed:
            log("  i Compositor: process exited during session (normal if user restarted it)", "ok")

    elif IS_WINDOWS:
        changes = saved.get("compositor_bypassed") or []
        try:
            import winreg
            for key_name, orig_val in changes:
                try:
                    key = winreg.OpenKey(
                        winreg.HKEY_LOCAL_MACHINE,
                        r"SOFTWARE\Microsoft\DirectX\UserGpuPreferences",
                        0, winreg.KEY_SET_VALUE
                    )
                    if orig_val is None:
                        try:
                            winreg.DeleteValue(key, key_name)
                        except Exception:
                            pass
                    else:
                        winreg.SetValueEx(key, key_name, 0, winreg.REG_SZ, orig_val)
                    winreg.CloseKey(key)
                except Exception:
                    pass
        except Exception:
            pass
        if changes:
            log("  + DWM: exclusive fullscreen setting restored", "ok")


def kill_bloat(log, use_sigstop: bool = True, cpu_cache: Optional[dict] = None, protected_extra: Optional[set] = None) -> BoostResult:
    """
    Dừng (SIGSTOP) hoặc kill process bloat của USER HIỆN TẠI.

    FIX v2.4: Dynamic OOM threshold based on total RAM.
    FIX v2.4: Mem threshold 200MB → 150MB.
    NEW v2.5: cpu_cache param — when provided by game_mode_on(), skip 0.6s warm-up.
              game_mode_on() already warmed up cpu_percent via _detect_running_games().

    SIGSTOP thay kill() — Đóng băng, không mất data, SIGCONT khi restore.
    Linux: chỉ touch process của current UID.
    Windows: terminate() với timeout, fallback kill().
    """
    result = BoostResult("kill_bloat")
    if not HAS_PSUTIL:
        log("  x psutil not installed", "err")
        result.success = False
        return result

    log("Scanning for background bloat...", "head")

    protected         = get_de_protected()
    _protected_pids   = set(protected_extra) if protected_extra else set()
    frozen_pids: dict = {}

    # Dynamic threshold — scales with available RAM
    try:
        ram_gb = psutil.virtual_memory().total / (1024 ** 3)
    except Exception:
        ram_gb = 8.0
    OOM_THRESHOLD    = max(75, int(300 * 4 / ram_gb))
    MEM_THRESHOLD_MB = 150

    if cpu_cache is not None:
        # Reuse warm-up from game detection — skip sleep entirely
        log("  . Using cached CPU samples (skip warm-up)...", "text")
        _cpu_data = cpu_cache
    else:
        # Need to do our own warm-up
        log("  . Sampling CPU (warm-up)...", "text")
        _warmup = set()
        for p in psutil.process_iter(["pid", "name"]):
            try:
                p.cpu_percent(interval=0)
                _warmup.add(p.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        import time as _t; _t.sleep(0.6)
        _cpu_data = {}

    acted = 0
    for p in psutil.process_iter():
        try:
            with p.oneshot():
                nm = p.name().lower().replace(".exe", "")

                if nm in protected or _is_protected(nm):
                    continue
                if _protected_pids and p.pid in _protected_pids:
                    continue
                if nm in _BLOAT_SKIP_ALWAYS:
                    continue
                if p.pid <= 10:
                    continue

                # ── ZALO / BROWSER GPU-RENDERER GUARD ─────────────────────────
                # Chromium/Electron spawns subprocess workers with --type= flags.
                # These are responsible for: hardware GPU rendering, tab rendering,
                # camera access (QR scan in Zalo Web), video calls, WebGL, etc.
                # They sit at 0% CPU when idle → kill_bloat would normally target them.
                # Killing gpu-process = white screen, killing video-capture = QR frozen.
                # Fix: check cmdline before ANY further processing and skip entirely.
                _RENDERER_FLAGS = (
                    "--type=gpu-process",
                    "--type=renderer",
                    "--type=ppapi",
                    "--type=utility",
                    "--type=crashpad-handler",
                    "video-capture",
                    "--gpu-process",
                    "gpu_process",
                    "zalo",           # protect all Zalo helper processes by name
                )
                try:
                    _cmdline_parts = p.info.get("cmdline") or [] if hasattr(p, 'info') else p.cmdline()
                    _cmdline_str = " ".join(_cmdline_parts).lower() if _cmdline_parts else ""
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    _cmdline_str = ""
                if _cmdline_str and any(flag in _cmdline_str for flag in _RENDERER_FLAGS):
                    continue  # never touch GPU/renderer/camera workers

                if IS_LINUX:
                    try:
                        if p.uids().real != CURRENT_UID:
                            continue
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue

                    oom    = _get_oom_score(p.pid)
                    status = p.status()
                    # Use cached CPU if available
                    if cpu_cache and p.pid in cpu_cache:
                        cpu = cpu_cache[p.pid]
                    else:
                        cpu = p.cpu_percent(interval=0)
                    mem_mb = p.memory_info().rss / 1024 / 1024

                    is_zombie = (status == psutil.STATUS_ZOMBIE)
                    is_bloat  = (
                        oom >= OOM_THRESHOLD and
                        mem_mb >= MEM_THRESHOLD_MB and
                        status in (psutil.STATUS_SLEEPING, psutil.STATUS_IDLE) and
                        cpu < 0.5 and
                        not _has_active_children(p.pid)
                    )

                elif IS_WINDOWS:
                    if cpu_cache and p.pid in cpu_cache:
                        cpu = cpu_cache[p.pid]
                    else:
                        cpu = p.cpu_percent(interval=0)
                    mem_mb = p.memory_info().rss / 1024 / 1024
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
                    try:
                        os.kill(p.pid, signal.SIGSTOP)
                        frozen_pids[p.pid] = p.name()
                        acted += 1
                        result.mb_freed += mem_mb
                        log(f"  ⏸ Frozen [{tag}] {p.name()} — {mem_mb:.0f} MB", "warn")
                    except ProcessLookupError:
                        pass
                else:
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
        try:
            top3 = sorted(
                [(p.name(), p.memory_info().rss // 1024 // 1024)
                 for p in psutil.process_iter()
                 if p.pid > 10],
                key=lambda x: x[1], reverse=True
            )[:3]
            top_str = ", ".join(f"{n}({m}MB)" for n, m in top3 if m > 50)
        except Exception:
            top_str = ""
        log("  ✓ System is clean — no idle heavy processes found", "ok")
        if top_str:
            log(f"  i Top processes: {top_str} — all actively needed", "ok")
    else:
        log(f"✓ Done — {acted} processes suspended, ~{result.mb_freed:.0f} MB freed", "ok")
        if frozen_pids and IS_LINUX:
            log("  i Frozen processes will resume when Game Mode turns off", "ok")

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
    Windows: working set trim + memory priority hints.
    Linux:   compact_memory only (not drop_caches).

    FIX v2.4: Added _trim_working_sets() for Windows — actually releases physical pages.
    FIX v2.4: Better log message explains why "0 MB freed" is normal when RAM is plentiful.
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
        # Step 1: Trim working sets — actually releases physical pages
        trimmed = _trim_working_sets(log)
        if trimmed:
            log(f"  + Working set trimmed: {trimmed} idle processes", "ok")

        # Step 2: Memory priority hints — guides future eviction order
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

        log(f"  + Memory priority hints: {lowered} idle processes marked for eviction first", "ok")

    import gc; gc.collect()

    after = psutil.virtual_memory().available // 1024 // 1024
    freed = max(0, after - before)
    result.mb_freed = freed

    if freed > 10:
        log(f"  + RAM freed: +{freed} MB  (now {after} MB available)", "ok")
    else:
        # FIX UX: explain why 0 MB is expected and not a bug
        log(f"  + RAM available: {after} MB", "ok")
        log("  i No immediate number change — pages are marked for eviction under pressure.", "ok")
        log("  i This is normal when RAM is not under pressure. Effect felt when needed.", "ok")
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
        # FIX v2.4: gc.collect() was useless — only freed Python objects (~2MB).
        # Now: trim working sets of all idle processes → actual physical page release.
        trimmed = _trim_working_sets(log)
        import gc; gc.collect()
        log(f"  + Working set trimmed: {trimmed} idle processes — physical pages released", "ok")

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
    if result.count > 0:
        log("  ⚠ First game/browser launch after clearing will be slower", "warn")
        log("  i Shaders rebuild automatically (1–10 min depending on game). Normal, happens once.", "ok")
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

_UUID_RE = __import__('re').compile(
    r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
)

def _safe_guid(guid: str) -> str:
    """Validate that guid is a well-formed UUID before interpolating into shell cmd.
    Returns POWER_BALANCED as safe fallback if not valid."""
    if guid and _UUID_RE.match(guid.strip()):
        return guid.strip()
    return POWER_BALANCED


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
        # FIX v2.4: Skip power plan switch if on battery.
        # Laptop on battery + High Performance = CPU runs hot, throttles, net result slower.
        if _is_on_battery():
            log("  ~ Power Plan: on battery — keeping current plan (plug in for best perf)", "warn")
            # Still return a dummy guid so restore logic knows original plan
            try:
                out = subprocess.run(
                    "powercfg /getactivescheme", shell=True,
                    capture_output=True, text=True,
                    creationflags=0x08000000, timeout=5
                ).stdout
                orig_guid = POWER_BALANCED
                if "GUID:" in out:
                    orig_guid = out.split("GUID:")[1].split()[0].strip()
                return orig_guid
            except Exception:
                return POWER_BALANCED

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
                ["powercfg", "/setactive", _safe_guid(guid)],
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
                ["powercfg", "/setactive", _safe_guid(str(method))],
                # shell=False: method validated as UUID via _safe_guid
                capture_output=True, creationflags=0x08000000, timeout=5
            )
            log("  + Windows Power Plan: original restored", "ok")


def _freeze_windows_services(log):
    # FIX v2.4: Conditional SysMain — only stop on SSD.
    # SysMain (Superfetch) prefetches frequently-used apps.
    # On HDD: stopping it makes app launches SLOWER (prefetch is valuable on slow disks).
    # On SSD: neutral (SSD already fast enough, prefetch adds minimal value).
    on_ssd = _has_only_ssd()
    if not on_ssd:
        log("  ~ SysMain: HDD detected — keeping Superfetch active (helps app launch on HDD)", "warn")

    services_to_stop = []
    for svc in GAMING_FREEZE_SERVICES:
        if svc == "SysMain" and not on_ssd:
            continue   # Never stop Superfetch on HDD
        services_to_stop.append(svc)

    stopped = []
    for svc in services_to_stop:
        r = subprocess.run(
            ["net", "stop", svc, "/y"], capture_output=True,
            creationflags=0x08000000, timeout=15
        )
        if r.returncode == 0:
            stopped.append(svc)
            log(f"  v Froze service: {svc}", "warn")
    return stopped


def _restore_windows_services(stopped_services, log):
    for svc in stopped_services:
        subprocess.run(
            ["net", "start", svc], capture_output=True,
            creationflags=0x08000000, timeout=15
        )
    if stopped_services:
        log(f"  + Restored {len(stopped_services)} Windows services", "ok")


# ══════════════════════════════════════════════════════════════
# NEW v2.5 — WINDOWS GAME DVR / GAME BAR DISABLE
# ══════════════════════════════════════════════════════════════
# Xbox Game DVR records a video buffer continuously when it detects a game.
# This uses CPU + RAM + disk I/O constantly → can reduce FPS by 5-15%.
# Razer Cortex and Windows 11 Auto Game Mode both disable this.
# No admin required — HKCU key.

def _disable_gamedvr(log) -> Optional[int]:
    """Disable Windows GameDVR/Game Bar. Returns original value for restore."""
    if not IS_WINDOWS:
        return None
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\GameDVR"
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                             winreg.KEY_READ | winreg.KEY_SET_VALUE)
        try:
            orig, _ = winreg.QueryValueEx(key, "AppCaptureEnabled")
        except Exception:
            orig = 1
        winreg.SetValueEx(key, "AppCaptureEnabled", 0, winreg.REG_DWORD, 0)
        winreg.CloseKey(key)
        log("  + GameDVR: disabled — no background recording during game", "ok")
        return orig
    except Exception as e:
        log(f"  ~ GameDVR: {e}", "warn")
        return None


def _restore_gamedvr(orig_val: Optional[int], log):
    """Restore GameDVR to original state."""
    if not IS_WINDOWS or orig_val is None:
        return
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\GameDVR"
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                             winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, "AppCaptureEnabled", 0, winreg.REG_DWORD, int(orig_val))
        winreg.CloseKey(key)
        log("  + GameDVR: restored", "ok")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════
# NEW v2.5 — LINUX GPU PERFORMANCE LEVEL
# ══════════════════════════════════════════════════════════════
# AMD GPU defaults to "auto" power profile — downclock when load is intermittent
# (common in games with varying GPU usage). This causes micro-stutters.
# Setting "high" forces constant full clock. Feral GameMode does this.
# NVIDIA: uses nvidia-smi power profile (if available).

# Setting "high" forces constant full clock. Feral GameMode does this.
# NVIDIA: uses nvidia-smi power profile (if available).

# ══════════════════════════════════════════════════════════════
# GAME PROCESS REAL-TIME SCHEDULING (Linux SCHED_FIFO)
# ══════════════════════════════════════════════════════════════
# Linux default scheduler: CFS (Completely Fair Scheduler).
# CFS gives equal time slices to all processes — game can be
# preempted by ANY other process, causing micro-stutters.
#
# SCHED_FIFO: real-time class. Game thread runs until it
# voluntarily yields or blocks on I/O. NEVER preempted by
# normal processes. Used by Feral GameMode, Steam, ProtonGE.
#
# Priority 1 (lowest real-time) — safe. Priority 99 would
# starve the OS. Priority 1 is enough to beat CFS entirely.
#
# Needs: CAP_SYS_NICE or rlimit_rtprio > 0 in /etc/security/limits.conf
# install.sh should add: @gamegroup - rtprio 1
# Fallback: nice(-10) if no rt permission.

def _set_realtime_scheduling(game_pids: list, log, saved: dict):
    """
    Apply SCHED_FIFO / high nice to game process and its render threads.
    Stores originals in saved['rt_sched'] for restore.
    """
    if not IS_LINUX:
        return
    import ctypes as _ct

    SCHED_FIFO = 1
    RT_PRIORITY = 1   # lowest real-time — never starve OS

    class _sched_param(_ct.Structure):
        _fields_ = [("sched_priority", _ct.c_int)]

    libc_names = ["libc.so.6", "libc.so", "libc.musl-x86_64.so.1",
                  "libc.musl-aarch64.so.1"]
    libc = None
    for name in libc_names:
        try:
            libc = _ct.CDLL(name, use_errno=True)
            break
        except OSError:
            pass

    rt_entries = {}   # {pid: (orig_policy, orig_param)}
    used_rt = False

    for pid in game_pids:
        # Also grab all threads of the process for full effect
        tids = [pid]
        try:
            import os as _os
            task_dir = _os.listdir(f"/proc/{pid}/task")
            tids = [int(t) for t in task_dir]
        except (OSError, ValueError):
            pass

        for tid in tids:
            try:
                if libc:
                    param = _sched_param(0)
                    # Get current policy
                    orig_policy = libc.sched_getscheduler(tid)
                    libc.sched_getparam(tid, _ct.byref(param))
                    orig_prio = param.sched_priority

                    param.sched_priority = RT_PRIORITY
                    ret = libc.sched_setscheduler(tid, SCHED_FIFO, _ct.byref(param))
                    if ret == 0:
                        rt_entries[tid] = (orig_policy, orig_prio)
                        used_rt = True
                    else:
                        # No rt permission — fallback to nice
                        if HAS_PSUTIL:
                            p = psutil.Process(pid)
                            cur_nice = p.nice()
                            p.nice(-10)
                            rt_entries[tid] = ("nice", cur_nice)
            except Exception:
                pass

    if used_rt:
        log(f"  + Real-time scheduling: SCHED_FIFO/1 applied to {len(rt_entries)} threads — game never preempted", "ok")
    elif rt_entries:
        log("  + Game priority: nice(-10) applied (no rt permission — install.sh adds rtprio)", "warn")
    else:
        log("  ~ Real-time scheduling: failed (needs rtprio or root)", "warn")

    saved["rt_sched"] = rt_entries


def _restore_realtime_scheduling(saved: dict, log):
    """Restore original scheduling policy for game threads."""
    if not IS_LINUX:
        return
    import ctypes as _ct
    rt_entries = saved.get("rt_sched", {})
    if not rt_entries:
        return

    SCHED_OTHER = 0
    class _sched_param(_ct.Structure):
        _fields_ = [("sched_priority", _ct.c_int)]

    libc = None
    for name in ["libc.so.6", "libc.so"]:
        try:
            libc = _ct.CDLL(name)
            break
        except OSError:
            pass

    restored = 0
    for tid, (orig_policy, orig_prio) in rt_entries.items():
        try:
            if orig_policy == "nice":
                if HAS_PSUTIL:
                    psutil.Process(tid).nice(orig_prio)
                    restored += 1
            elif libc:
                param = _sched_param(orig_prio)
                policy = orig_policy if orig_policy >= 0 else SCHED_OTHER
                libc.sched_setscheduler(tid, policy, _ct.byref(param))
                restored += 1
        except Exception:
            pass
    if restored:
        log(f"  + Scheduling policy restored for {restored} threads", "ok")


# ══════════════════════════════════════════════════════════════
# OOM SCORE PROTECTION FOR GAME PROCESS
# ══════════════════════════════════════════════════════════════
# Linux OOM killer: when RAM is exhausted, it kills processes
# based on oom_score. High oom_score = killed first.
# Games with high memory usage get high scores → OOM kills the
# game mid-session (sudden crash, no warning).
#
# oom_score_adj = -1000: tells OOM killer "NEVER kill this process".
# Used by critical services (sshd, systemd). Safe for games.
# Needs root (CAP_SYS_RESOURCE) or helper.

def _protect_game_from_oom(game_pids: list, log, saved: dict):
    """Set oom_score_adj=-1000 so OOM killer never terminates the game."""
    if not IS_LINUX:
        return
    from pathlib import Path as _P

    orig_scores = {}
    protected = 0

    for pid in game_pids:
        adj_file = _P(f"/proc/{pid}/oom_score_adj")
        try:
            orig = adj_file.read_text().strip()
            adj_file.write_text("-1000\n")
            orig_scores[pid] = orig
            protected += 1
        except (OSError, PermissionError):
            # Try via helper (needs root)
            try:
                out, code = _run(
                    f"sudo -n tee /proc/{pid}/oom_score_adj <<< -1000", timeout=3
                )
                if code == 0:
                    orig_scores[pid] = "0"
                    protected += 1
            except Exception:
                pass

    if protected:
        log(f"  + OOM protection: {protected} game processes marked unkillable", "ok")
    saved["oom_protected"] = orig_scores


def _restore_game_oom(saved: dict, log):
    """Restore oom_score_adj for game processes."""
    if not IS_LINUX:
        return
    from pathlib import Path as _P
    for pid, orig in saved.get("oom_protected", {}).items():
        try:
            _P(f"/proc/{pid}/oom_score_adj").write_text(orig + "\n")
        except (OSError, PermissionError):
            pass


# ══════════════════════════════════════════════════════════════
# INTEL P-CORE DETECTION + GAME CPU PINNING
# ══════════════════════════════════════════════════════════════
# Intel 12th gen+: hybrid architecture with P-cores (fast) and
# E-cores (efficient but slow). OS scheduler knows about this,
# but may still schedule game threads on E-cores during bursts.
#
# Explicit affinity: pin game to P-cores only → never runs on
# E-cores → more consistent frame times, lower 1% lows.
#
# Detection: /sys/devices/system/cpu/cpuX/acpi_cppc/highest_perf
# P-cores have higher "highest_perf" value than E-cores.
# Fallback: first half of cores (generally P-cores on Intel hybrid).

_PERF_CORES_CACHE: Optional[list] = None

def _detect_performance_cores() -> list:
    """
    Return list of CPU IDs that are performance cores.
    For non-hybrid CPUs: returns all CPU IDs (no distinction).
    Result cached at module level.
    """
    global _PERF_CORES_CACHE
    if _PERF_CORES_CACHE is not None:
        return _PERF_CORES_CACHE

    if not IS_LINUX:
        _PERF_CORES_CACHE = []
        return []

    cpu_perf = {}   # {cpu_id: highest_perf_value}
    cpu_path = Path("/sys/devices/system/cpu")
    try:
        for cpu_dir in sorted(cpu_path.glob("cpu[0-9]*")):
            cpu_id_str = cpu_dir.name[3:]
            try:
                cpu_id = int(cpu_id_str)
            except ValueError:
                continue
            # Method 1: ACPI CPPC (Intel 12th gen+ / AMD Zen 4)
            cppc_file = cpu_dir / "acpi_cppc/highest_perf"
            if cppc_file.exists():
                try:
                    cpu_perf[cpu_id] = int(cppc_file.read_text().strip())
                    continue
                except (OSError, ValueError):
                    pass
            # Method 2: cpu_capacity (ARM big.LITTLE)
            cap_file = cpu_dir / "cpu_capacity"
            if cap_file.exists():
                try:
                    cpu_perf[cpu_id] = int(cap_file.read_text().strip())
                    continue
                except (OSError, ValueError):
                    pass
            # No hybrid info: assign equal weight
            cpu_perf[cpu_id] = 100
    except (OSError, PermissionError):
        _PERF_CORES_CACHE = []
        return []

    if not cpu_perf:
        _PERF_CORES_CACHE = []
        return []

    # If all cores have equal perf: not a hybrid CPU, return all
    values = set(cpu_perf.values())
    if len(values) <= 1:
        _PERF_CORES_CACHE = sorted(cpu_perf.keys())
        return _PERF_CORES_CACHE

    # Hybrid: return only cores with max performance value
    max_perf = max(cpu_perf.values())
    p_cores = [cpu_id for cpu_id, perf in cpu_perf.items() if perf == max_perf]
    _PERF_CORES_CACHE = sorted(p_cores)
    return _PERF_CORES_CACHE


def _pin_game_to_perf_cores(game_pids: list, log, saved: dict):
    """
    Pin game processes to P-cores (Intel hybrid) or all cores (uniform).
    Saves original affinity for restore.
    """
    if not IS_LINUX or not HAS_PSUTIL:
        return

    p_cores = _detect_performance_cores()
    if not p_cores:
        return

    all_cores = list(range(psutil.cpu_count(logical=True) or 1))
    # If all cores are P-cores: no pinning needed
    if set(p_cores) == set(all_cores):
        return

    pinned = 0
    orig_affinities = {}
    for pid in game_pids:
        try:
            p = psutil.Process(pid)
            orig = p.cpu_affinity()
            p.cpu_affinity(p_cores)
            orig_affinities[pid] = orig
            pinned += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied,
                NotImplementedError, AttributeError):
            pass

    if pinned:
        log(f"  + CPU pinning: {pinned} game process(es) → P-cores {p_cores} (E-cores excluded)", "ok")
        log(f"    → More consistent frame times, lower 1% lows", "ok")
    saved["game_core_affinity"] = orig_affinities


def _restore_game_core_affinity(saved: dict, log):
    """Restore original CPU affinity for game processes."""
    if not IS_LINUX or not HAS_PSUTIL:
        return
    restored = 0
    for pid, orig in saved.get("game_core_affinity", {}).items():
        try:
            psutil.Process(pid).cpu_affinity(orig)
            restored += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied,
                NotImplementedError, psutil.ZombieProcess):
            pass
    if restored:
        log(f"  + P-core pinning: restored affinity for {restored} game processes", "ok")


# ══════════════════════════════════════════════════════════════
# TRANSPARENT HUGE PAGES — GLOBAL MODE ONLY
# ══════════════════════════════════════════════════════════════
# THP: kernel maps memory in 2MB pages instead of 4KB for qualifying
# allocations. Reduces TLB misses → faster memory access for large,
# contiguous allocations (common in game engines, asset streaming).
#
# REDESIGN NOTE (v3.1): an earlier version of this function additionally
# tried to call libc.madvise(start, length, MADV_HUGEPAGE) directly on
# memory address ranges read from /proc/<game_pid>/maps — i.e. using the
# GAME's virtual addresses while calling madvise() from CYBERCLEAN's own
# process. This does not work: madvise() always operates on the calling
# process's own address space; it has no parameter to target another
# process's memory by PID. There is a real Linux syscall for that
# (process_madvise(), kernel ≥5.10, requires a pidfd + PTRACE_MODE_ATTACH
# permission) but this code was not using it — it was calling the
# ordinary single-process madvise() with foreign addresses, which the
# kernel validates and (correctly) ignores or no-ops on, since those
# addresses are not mapped in CyberClean's own address space. The
# function still logged "applied to N memory regions" because it never
# checked the syscall's return value — that log message was never an
# accurate description of what happened.
#
# Rather than reach for process_madvise() (meaningfully riskier: it
# requires elevated ptrace-equivalent permission on an arbitrary running
# process — exactly the kind of cross-process memory interference that
# is reasonable for anti-cheat software to flag, and reasonable for us
# to avoid touching at all), this version keeps ONLY the safe, standard
# part: setting the kernel's global THP policy to "madvise" via sysfs.
# In that mode, the kernel transparently grants huge pages to any
# process whose OWN allocator already calls madvise(MADV_HUGEPAGE) on
# itself (most modern game engines, JIT runtimes, and malloc
# implementations do this internally when it's enabled system-wide).
# We get the real-world benefit without writing into any other
# process's memory ourselves.

def _set_thp_game(game_pids: list, log, saved: dict):
    """
    Set the kernel's global Transparent Huge Page policy to 'madvise'.
    This does not touch any other process's memory directly — it only
    changes a kernel-wide setting that lets processes opt into huge
    pages for their own allocations. game_pids is accepted for logging/
    API-compatibility with callers but is not used to reach into other
    processes anymore (see module note above for why that was removed).
    """
    if not IS_LINUX:
        return

    thp_file = Path("/sys/kernel/mm/transparent_hugepage/enabled")
    orig_thp = None
    if thp_file.exists():
        try:
            content = thp_file.read_text().strip()
            # Parse active value: "always madvise [never]" → "never"
            active = next((s.strip("[]") for s in content.split() if s.startswith("[")), "")
            orig_thp = active
            if active != "madvise":
                try:
                    thp_file.write_text("madvise\n")
                    log("  + THP: global mode → madvise (huge pages for opted-in processes)", "ok")
                except PermissionError:
                    _, code = _run(
                        f"echo madvise | sudo -n tee {thp_file}", timeout=3
                    )
                    if code == 0:
                        log("  + THP: madvise set via helper", "ok")
        except Exception:
            pass

    saved["thp_orig"] = orig_thp


def _restore_thp(saved: dict, log):
    """Restore THP global setting."""
    if not IS_LINUX:
        return
    orig = saved.get("thp_orig")
    if not orig:
        return
    thp_file = Path("/sys/kernel/mm/transparent_hugepage/enabled")
    try:
        thp_file.write_text(orig + "\n")
    except PermissionError:
        _run(f"echo {orig} | sudo -n tee {thp_file}", timeout=3)


def _set_gpu_performance(log, saved: dict):
    """Set GPU to high performance mode. Stores originals in saved dict."""
    if not IS_LINUX:
        return

    gpu_orig = {}

    # AMD DRM sysfs — works without root on modern kernels with proper ACL
    try:
        for card in sorted(Path("/sys/class/drm").iterdir()):
            perf_file = card / "device/power_dpm_force_performance_level"
            if not perf_file.exists():
                continue
            try:
                orig = perf_file.read_text().strip()
                perf_file.write_text("high")
                gpu_orig[str(perf_file)] = orig
                log(f"  + GPU {card.name}: performance level → high", "ok")
            except PermissionError:
                # Try via sysfs with sudo helper
                try:
                    subprocess.run(
                        ["sudo", "-n", "tee", str(perf_file)],
                        input="high", text=True, capture_output=True, timeout=5
                    )
                    gpu_orig[str(perf_file)] = "auto"
                    log(f"  + GPU {card.name}: performance level → high (via sudo)", "ok")
                except Exception:
                    pass
            except Exception:
                pass
    except Exception:
        pass

    # NVIDIA smi — set persistence + performance mode
    if shutil.which("nvidia-smi"):
        try:
            r = subprocess.run(
                ["nvidia-smi", "--auto-boost-default=0"],
                capture_output=True, timeout=5
            )
            if r.returncode == 0:
                log("  + NVIDIA: auto-boost disabled — stable clock", "ok")
                gpu_orig["nvidia_autoboost"] = "1"
        except Exception:
            pass

    if gpu_orig:
        saved["gpu_perf_orig"] = gpu_orig
    else:
        log("  ~ GPU performance: no supported GPU found (AMD DRM / NVIDIA)", "warn")


def _restore_gpu_performance(saved: dict, log):
    """Restore GPU performance level."""
    if not IS_LINUX:
        return
    gpu_orig = saved.get("gpu_perf_orig", {})
    if not gpu_orig:
        return

    for path_str, orig_val in gpu_orig.items():
        if path_str == "nvidia_autoboost":
            try:
                subprocess.run(
                    ["nvidia-smi", "--auto-boost-default=1"],
                    capture_output=True, timeout=5
                )
            except Exception:
                pass
            continue
        try:
            Path(path_str).write_text(orig_val)
        except Exception:
            try:
                subprocess.run(
                    ["sudo", "-n", "tee", path_str],
                    input=orig_val, text=True, capture_output=True, timeout=5
                )
            except Exception:
                pass
    log("  + GPU performance level: restored", "ok")


# ══════════════════════════════════════════════════════════════
# NEW v2.5 — LINUX I/O SCHEDULER
# ══════════════════════════════════════════════════════════════
# kyber: latency-optimized scheduler — lowest I/O wait for gaming.
# mq-deadline: good alternative for NVMe.
# Feral GameMode does this — reduces game stutters from disk I/O.

def _set_io_scheduler(log, saved: dict):
    """Switch block device I/O scheduler to kyber or mq-deadline."""
    if not IS_LINUX:
        return

    io_orig = {}
    try:
        for dev_path in sorted(Path("/sys/block").iterdir()):
            sched_file = dev_path / "queue/scheduler"
            if not sched_file.exists():
                continue
            dev_name = dev_path.name
            # Skip virtual/loop/ram devices
            if any(dev_name.startswith(p) for p in ("loop", "ram", "zram", "dm-", "md")):
                continue
            try:
                current = sched_file.read_text().strip()
                # Parse active scheduler from "[kyber] mq-deadline none" format
                active = next((s.strip("[]") for s in current.split() if s.startswith("[")), current)
                io_orig[str(sched_file)] = active

                # Try kyber first (best for NVMe/SSD), fallback to mq-deadline
                set_ok = False
                for sched in ("kyber", "mq-deadline", "deadline"):
                    if sched not in current:
                        continue
                    try:
                        sched_file.write_text(sched)
                        set_ok = True
                        log(f"  + I/O scheduler {dev_name}: {active} → {sched}", "ok")
                        break
                    except PermissionError:
                        try:
                            subprocess.run(
                                ["sudo", "-n", "tee", str(sched_file)],
                                input=sched, text=True, capture_output=True, timeout=5
                            )
                            set_ok = True
                            log(f"  + I/O scheduler {dev_name}: {active} → {sched} (sudo)", "ok")
                            break
                        except Exception:
                            pass
                    except Exception:
                        pass
                if not set_ok:
                    log(f"  ~ I/O scheduler {dev_name}: kyber/mq-deadline not available", "warn")
                    del io_orig[str(sched_file)]   # don't try to restore if didn't change
            except Exception:
                pass
    except Exception:
        pass

    if io_orig:
        saved["io_sched_orig"] = io_orig


def _restore_io_scheduler(saved: dict, log):
    """Restore I/O schedulers."""
    if not IS_LINUX:
        return
    io_orig = saved.get("io_sched_orig", {})
    if not io_orig:
        return
    for sched_file, orig in io_orig.items():
        try:
            Path(sched_file).write_text(orig)
        except Exception:
            try:
                subprocess.run(
                    ["sudo", "-n", "tee", sched_file],
                    input=orig, text=True, capture_output=True, timeout=5
                )
            except Exception:
                pass
    log("  + I/O schedulers: restored", "ok")


# ══════════════════════════════════════════════════════════════
# NEW v2.5 — LINUX SCREENSAVER / SLEEP INHIBIT
# ══════════════════════════════════════════════════════════════
# Prevents screen from turning off or system from sleeping during a game.
# Uses systemd-inhibit — works on all systemd-based distros.
# Fallback: xdg-screensaver suspend (X11) or wayland-specific tools.

def _inhibit_screensaver(log, saved: dict):
    """Start screensaver/sleep inhibitor for gaming session."""
    if not IS_LINUX:
        return

    inhibit_proc = None

    # Method 1: systemd-inhibit (most universal — works on all systemd distros)
    if shutil.which("systemd-inhibit"):
        try:
            inhibit_proc = subprocess.Popen(
                ["systemd-inhibit",
                 "--what=idle:sleep:handle-lid-switch",
                 "--who=CyberClean",
                 "--why=Game running",
                 "--mode=block",
                 "sleep", "infinity"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            log("  + Screensaver/sleep: inhibited (systemd)", "ok")
        except Exception as e:
            log(f"  ~ systemd-inhibit: {e}", "warn")
            inhibit_proc = None

    # Method 2: xdg-screensaver (X11 fallback)
    if inhibit_proc is None and shutil.which("xdg-screensaver"):
        xdg_display = os.environ.get("DISPLAY", "")
        if xdg_display:
            try:
                subprocess.run(["xdg-screensaver", "suspend", "0"],
                               capture_output=True, timeout=5)
                log("  + Screensaver: suspended (xdg)", "ok")
                # Store sentinel so we know to resume on exit
                saved["inhibit_proc"] = "xdg"
                return
            except Exception:
                pass

    if inhibit_proc:
        saved["inhibit_proc"] = inhibit_proc


def _restore_screensaver(saved: dict, log):
    """Stop screensaver inhibitor."""
    if not IS_LINUX:
        return
    inhibit = saved.get("inhibit_proc")
    if inhibit is None:
        return
    if inhibit == "xdg":
        try:
            subprocess.run(["xdg-screensaver", "resume", "0"],
                           capture_output=True, timeout=5)
            log("  + Screensaver: resumed", "ok")
        except Exception:
            pass
    elif hasattr(inhibit, "terminate"):
        try:
            inhibit.terminate()
            inhibit.wait(timeout=3)
            log("  + Sleep inhibit: released", "ok")
        except Exception:
            try:
                inhibit.kill()
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════
# NEW v2.5 — DNS BOOST (Windows, opt-in)
# ══════════════════════════════════════════════════════════════
# Temporarily switches DNS to 1.1.1.1/1.0.0.1 (Cloudflare) for lower latency.
# Reduces DNS lookup time in online games. Opt-in: may break corporate/VPN DNS.
# Requires admin to change DNS via netsh.

def _boost_dns_windows(log) -> list:
    """
    Switch DNS to Cloudflare (1.1.1.1) on all active adapters.
    Returns list of (adapter_name, orig_dns_list) for restore.
    Only applies if running as admin — silently skips otherwise.
    """
    if not IS_WINDOWS:
        return []
    try:
        import ctypes as _ct
        if not bool(_ct.windll.shell32.IsUserAnAdmin()):
            log("  ~ DNS boost: skipped (needs admin — run as Administrator for this tweak)", "warn")
            return []
    except Exception:
        return []

    changed = []
    try:
        # Get active adapters
        out = subprocess.run(
            'netsh interface show interface',
            shell=True, capture_output=True, text=True,
            creationflags=0x08000000, timeout=8
        ).stdout

        adapters = []
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[1].lower() == "connected":
                adapter = " ".join(parts[3:])
                adapters.append(adapter)

        for adapter in adapters:
            # Read current DNS
            dns_out = subprocess.run(
                f'netsh interface ip show dns name="{adapter}"',
                shell=True, capture_output=True, text=True,
                creationflags=0x08000000, timeout=5
            ).stdout
            orig_dns = [l.strip() for l in dns_out.splitlines()
                        if l.strip() and any(c.isdigit() for c in l)]

            # Set Cloudflare DNS
            r1 = subprocess.run(
                f'netsh interface ip set dns name="{adapter}" static 1.1.1.1',
                shell=True, capture_output=True, creationflags=0x08000000, timeout=5
            )
            r2 = subprocess.run(
                f'netsh interface ip add dns name="{adapter}" 1.0.0.1 index=2',
                shell=True, capture_output=True, creationflags=0x08000000, timeout=5
            )
            if r1.returncode == 0:
                changed.append((adapter, orig_dns))
                log(f"  + DNS: {adapter} → 1.1.1.1/1.0.0.1 (Cloudflare)", "ok")

        if changed:
            # Flush DNS cache
            subprocess.run("ipconfig /flushdns", shell=True, capture_output=True,
                           creationflags=0x08000000, timeout=5)
            log("  + DNS cache flushed", "ok")
    except Exception as e:
        log(f"  ~ DNS boost: {e}", "warn")
    return changed


def _restore_dns_windows(changed: list, log):
    """Restore DNS settings."""
    if not IS_WINDOWS or not changed:
        return
    for adapter, orig_dns in changed:
        try:
            if not orig_dns:
                subprocess.run(
                    f'netsh interface ip set dns name="{adapter}" dhcp',
                    shell=True, capture_output=True, creationflags=0x08000000, timeout=5
                )
            else:
                subprocess.run(
                    f'netsh interface ip set dns name="{adapter}" static {orig_dns[0].split()[-1]}',
                    shell=True, capture_output=True, creationflags=0x08000000, timeout=5
                )
        except Exception:
            pass
    subprocess.run("ipconfig /flushdns", shell=True, capture_output=True,
                   creationflags=0x08000000, timeout=5)
    log("  + DNS: restored", "ok")


# ══════════════════════════════════════════════════════════════
# NEW v2.5 — PSI MEMORY PRESSURE MONITOR (Linux)
# ══════════════════════════════════════════════════════════════
# Linux kernel 4.20+: /proc/pressure/memory provides PSI metrics.
# "some avg10" = % of time ANY task was stalled waiting for memory (last 10s).
# When pressure is high → proactively call kill_bloat() instead of waiting
# for OOM killer. Smarter than static OOM threshold.

_PSI_MONITOR_THREAD: Optional[object] = None
_PSI_STOP_EVENT: Optional[object] = None
import threading
_PSI_LOCK = threading.Lock()  # Thread safety for PSI monitor


def _start_psi_monitor(log_queue=None):
    """
    Start background thread monitoring /proc/pressure/memory PSI.
    When 'some avg10 > 40' → trigger kill_bloat() proactively.
    Only starts if PSI is available (kernel 4.20+).
    """
    if not IS_LINUX:
        return None, None

    psi_file = Path("/proc/pressure/memory")
    if not psi_file.exists():
        return None, None

    import threading
    stop_event = threading.Event()

    def _monitor():
        import time as _t
        while not stop_event.wait(timeout=5.0):   # check every 5s
            try:
                content = psi_file.read_text()
                for line in content.splitlines():
                    if line.startswith("some"):
                        # "some avg10=X.XX avg60=X.XX avg300=X.XX total=XXXXXX"
                        parts = dict(p.split("=") for p in line.split() if "=" in p)
                        avg10 = float(parts.get("avg10", 0))
                        if avg10 > 40.0:
                            # High memory pressure — safely kill bloat with lock
                            with _PSI_LOCK:
                                logs = []
                                kill_bloat(lambda m, l='text': logs.append(m),
                                           use_sigstop=True)
            except Exception:
                pass

    t = threading.Thread(target=_monitor, daemon=True, name="CyberClean-PSI")
    t.start()
    return t, stop_event


def _stop_psi_monitor():
    global _PSI_MONITOR_THREAD, _PSI_STOP_EVENT
    if _PSI_STOP_EVENT:
        _PSI_STOP_EVENT.set()
    _PSI_MONITOR_THREAD = None
    _PSI_STOP_EVENT = None


def game_mode_on(log) -> dict:
    """
    CPU affinity jail — 3-tier: Comms / Media / Trash.
    Game gets all prime cores. Background jailed to last cores.

    FIX v2.4: browser jail only when game running, battery check, timer res,
              game priority boost, Nagle, SysMain guard, Feral GameMode, nice() log.

    NEW v2.5:
    - GameDVR/Game Bar disable (Windows) — stops background recording, improves FPS
    - AMD/Intel GPU performance level (Linux sysfs) — prevents GPU downclocking
    - I/O scheduler → kyber/mq-deadline (Linux) — lower disk latency in games
    - Screensaver/sleep inhibit (Linux) — screen won't turn off during game
    - Merged CPU warm-up with game detection — saves 0.6s
    """
    if not HAS_PSUTIL:
        return {}
    log("⚡ GAME MODE ON", "head")
    saved = {
        "affinity": {}, "nice": {}, "services": [],
        "power": None, "frozen": {},
        "timer_set": False,
        "nagle_changed": [],
        "game_priority": {},
        "gamedvr_orig": None,        # Windows GameDVR original value
        "gpu_perf_orig": {},          # Linux GPU performance level originals
        "io_sched_orig": {},          # Linux I/O scheduler originals
        "inhibit_proc": None,         # Linux screensaver inhibit process
        "compositor_bypassed": None,   # compositor bypass state (X11/Windows)
        "xprop_bypass_set": False,     # _NET_WM_BYPASS_COMPOSITOR was set
        "rt_sched": {},                # real-time scheduling: {tid: (orig_policy, orig_prio)}
        "oom_protected": {},           # OOM protection: {pid: orig_oom_score_adj}
        "game_core_affinity": {},      # P-core pinning: {pid: orig_affinity_list}
        "thp_orig": None,              # THP global setting before override
    }

    log("  . Detecting system configuration...", "text")

    # ── Linux: Feral GameMode integration ─────────────────────
    if IS_LINUX and shutil.which("gamemoded"):
        log("  i Feral GameMode detected — deferring CPU governor to gamemoded", "ok")
        log("  i Run games with: gamemoderun <game>  for best effect", "ok")
        saved["power"] = None
    else:
        log("  . Setting performance mode...", "text")
        saved["power"] = _enable_kernel_performance(log)

    # ── Linux: GPU performance level boost ────────────────────
    # NOTE: Moved BELOW game detection — we must not force GPU state
    # transition (auto → high) while a game's render engine is active.
    # Forcing DPM level mid-render = driver shock = black screen (Roblox bug).
    # Will be applied conditionally after running_games check below.

    # ── Linux: I/O scheduler → kyber/mq-deadline ──────────────
    if IS_LINUX:
        _set_io_scheduler(log, saved)

    # ── Linux: Inhibit screensaver / sleep ────────────────────
    if IS_LINUX:
        _inhibit_screensaver(log, saved)

    # ── Bypass compositor (Linux X11: suspend picom/compton; Windows: FSE) ─
    _bypass_compositor_on(log, saved)

    # ── Windows: Timer Resolution ──────────────────────────────
    if IS_WINDOWS:
        saved["timer_set"] = _timer_resolution_set(log)

    # ── Windows: Disable GameDVR / Game Bar ───────────────────
    if IS_WINDOWS:
        saved["gamedvr_orig"] = _disable_gamedvr(log)

    # ── Detect running games (includes CPU warm-up) ────────────
    log("  . Checking for active game processes...", "text")
    running_games, cpu_samples = _detect_running_games()
    running_game_names = {g_nm.lower().replace(".exe", "") for _, g_nm in running_games}
    has_game = len(running_games) > 0

    if has_game:
        game_names = ", ".join(n for _, n in running_games[:3])
        log(f"  + Game detected: {game_names}", "ok")
    else:
        log("  i No game running — browser/media apps will NOT be jailed", "ok")
        log("  i Start your game, then toggle Smart Boost for full effect", "ok")

    # ── Kill runaway widget zombies (eww, waybar, polybar, etc.) ──────────
    # Must run BEFORE CPU jail so zombie processes don't consume cores
    # that games need. Also prevents false positives in kill_bloat scan.
    _kill_runaway_widgets(log)

    # ── Linux: GPU performance level boost (NOW safe — after game check) ──
    # Only apply if NO game is currently running. If a game is mid-render
    # (Roblox, any OpenGL/Vulkan game), forcing DPM level transition while
    # the GPU driver is actively rendering causes driver state corruption
    # → black screen. User must restart the game after enabling Game Mode.
    # If no game running yet, safe to set high now; game will launch into it.
    if IS_LINUX and not has_game:
        _set_gpu_performance(log, saved)
    elif IS_LINUX and has_game:
        log("  ~ GPU: game already running — skipping DPM transition to prevent black screen", "warn")
        log("  i For max GPU performance: enable Game Mode BEFORE launching your game", "ok")

    # ── CPU Affinity jail (v2.6 — Activity-Aware Smart Scheduling) ──────────
    # FIX v2.6: Old approach hard-jailed Discord/Chrome onto 1 weak core regardless
    # of what the user was doing. This broke screen share, calls, YouTube, music.
    #
    # NEW APPROACH — 3 tiers, activity-aware:
    #
    # Tier 0 — ACTIVE (do NOT touch):
    #   Any app currently using > ACTIVE_CPU_THRESHOLD % CPU is actively serving
    #   the user (call encoding, streaming audio/video, rendering web page).
    #   We NEVER jail it. OS scheduler will give game priority via nice() difference.
    #
    # Tier 1 — IDLE BACKGROUND (soft throttle via nice only, no affinity jail):
    #   Known comms/media apps that are running but idle (<= threshold).
    #   Lower their priority so game wins CPU contention, but keep all cores
    #   available so they can burst when needed (Discord receiving a message, etc).
    #
    # Tier 2 — KNOWN BLOAT (hard jail: affinity + idle priority):
    #   Sync daemons, update services, telemetry — apps that should NEVER
    #   need burst CPU while user is gaming. Hard-jail these onto 1 weak core.
    #
    # Result: game gets highest priority, Discord call stays smooth,
    # YouTube music keeps playing, OneDrive gets strangled. Win-win.

    ACTIVE_CPU_THRESHOLD = 2.0   # % — anything above this = user is actively using it

    cores  = psutil.cpu_count(logical=True) or 1
    jailed = 0
    soft_throttled = 0

    # Only 1 core → skip entirely, nothing useful we can do
    if cores > 2:
        # Bloat jail: last core only (weakest logical core, often efficiency core)
        trash_cores = [cores - 1]

        # Comms/media apps: known to be user-facing, but may be idle right now
        COMMS_MEDIA_APPS = {
            "discord", "obs", "obs32", "obs64", "telegram",
            "skype", "teams", "mumble", "teamspeak", "signal",
            "chrome", "chromium", "msedge", "firefox", "brave",
            "opera", "spotify", "zalo", "vivaldi", "coccoc",
            "twitch", "streamlabs", "xsplit",
        }

        # True bloat: sync, update, telemetry — never needs burst CPU during gaming
        TRASH_APPS = {
            "onedrive", "dropbox", "googledrivefs", "googledrive",
            "microsoftedgeupdate", "googleupdate", "compattelrunner",
            "diagtrack", "wermgr", "searchindexer", "msiexec",
            "steamwebhelper", "epicwebhelper",
        }

        protected = get_de_protected()

        # Warm up CPU samples for activity detection (reuse game detection samples)
        # cpu_samples already populated from _detect_running_games() above
        import time as _t
        # Take a second sample 0.3s after game detection warm-up for accuracy
        _t.sleep(0.3)

        # PERFORMANCE FIX: Collect all processes first to avoid O(n²) nested iteration
        # FIX: thêm "cmdline" vào iter để detect GPU/renderer subprocess của Chromium/Electron
        # (các subprocess này ăn 0% CPU khi idle nên Tier logic tưởng là rác → bóp cổ nhầm)
        all_processes = list(psutil.process_iter(["pid", "name", "cmdline"]))
        for p in all_processes:
            try:
                nm = (p.info["name"] or "").lower().replace(".exe", "")
                if nm in protected or _is_protected(nm):
                    continue

                # ── DYNAMIC GPU/RENDERER GUARD ─────────────────────────────────
                # Chromium / Electron / CEF spawns subprocess với --type= flag.
                # Những subprocess này đảm nhận:
                #   gpu-process  → render WebGL, hardware video decode, camera QR scan
                #   renderer     → render HTML/JS của từng tab / app window
                #   ppapi        → Flash/NaCl plugins (hiếm nhưng vẫn có)
                #   video-capture → camera feed cho QR scan, video call
                #   utility      → network service, storage service
                # Khi idle chúng ăn 0% CPU → Tier logic sẽ tưởng là bloat và jail.
                # Jail gpu-process = màn hình trắng khi quét QR, video call đơ, WebGL đen.
                # Fix: detect bằng cmdline, bypass HOÀN TOÀN mọi Tier nếu khớp.
                _GPU_RENDERER_FLAGS = (
                    "--type=gpu-process",
                    "--type=renderer",
                    "--type=ppapi",
                    "--type=utility",
                    "video-capture",
                    "--gpu-process",       # format thay thế một số Electron build dùng
                    "gpu_process",
                )
                try:
                    _cmdline = p.info.get("cmdline") or []
                    _cmdline_str = " ".join(_cmdline).lower() if _cmdline else ""
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    _cmdline_str = ""

                if _cmdline_str and any(flag in _cmdline_str for flag in _GPU_RENDERER_FLAGS):
                    # Subprocess này đang đảm nhận GPU/rendering — không đụng vào
                    # dù nó thuộc app nào, dù đang idle hay active
                    continue

                with p.oneshot():
                    # Measure actual CPU activity right now
                    try:
                        cpu_now = p.cpu_percent(interval=0)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue

                    if nm in TRASH_APPS:
                        # Hard jail bloat regardless of activity — these should never
                        # be doing useful work during gaming
                        saved["affinity"][p.pid] = p.cpu_affinity()
                        p.cpu_affinity(trash_cores)
                        saved["nice"][p.pid] = p.nice()
                        if IS_WINDOWS:
                            p.nice(psutil.IDLE_PRIORITY_CLASS)
                        elif IS_LINUX and os.geteuid() == 0:
                            p.nice(19)
                        jailed += 1
                        log(f"  v Bloat: {nm} → core {trash_cores} + idle", "warn")

                    elif nm in running_game_names:
                        # This is a detected game process — NEVER touch its affinity.
                        # It gets boosted below in the game_priority block.
                        continue

                    elif nm in COMMS_MEDIA_APPS and has_game:
                        if cpu_now > ACTIVE_CPU_THRESHOLD:
                            # App is ACTIVELY being used (call encoding, music decoding,
                            # streaming video, etc). DO NOT jail it — only lower priority
                            # softly so OS gives game preference during contention.
                            saved["nice"][p.pid] = p.nice()
                            if IS_WINDOWS:
                                # Active comms on Windows: do NOT lower priority.
                                # WASAPI audio threads need normal priority.
                                pass
                            elif IS_LINUX and os.geteuid() == 0:
                                p.nice(5)
                            soft_throttled += 1
                            log(f"  ~ Active: {nm} ({cpu_now:.1f}% CPU) → untouched (audio-safe)", "ok")
                        else:
                            # Idle comms/media can still suddenly become active (voice/chat/video).
                            # On Windows, avoid affinity jail to prevent capture/overlay instability.
                            saved["nice"][p.pid] = p.nice()
                            if IS_WINDOWS:
                                # Keep NORMAL priority for comms/media on Windows.
                                # BELOW_NORMAL deprioritizes WASAPI audio threads
                                # -> Discord voice stutters, Spotify/YouTube cuts out.
                                # Just track it as soft-throttled without touching priority.
                                soft_throttled += 1
                                log(f"  ~ Kept: {nm} → normal priority (audio-safe on Windows)", "ok")
                            elif IS_LINUX and os.geteuid() == 0:
                                if cores >= 6:
                                    idle_cores = list(range(cores // 2, cores))
                                else:
                                    idle_cores = [cores - 1]
                                saved["affinity"][p.pid] = p.cpu_affinity()
                                p.cpu_affinity(idle_cores)
                                p.nice(10)
                                jailed += 1
                                log(f"  v Idle: {nm} → cores {idle_cores} (was idle at {cpu_now:.1f}%)", "warn")
                            else:
                                soft_throttled += 1
                                log(f"  ~ Idle: {nm} → priority only", "ok")

            except (psutil.NoSuchProcess, psutil.AccessDenied,
                    NotImplementedError, AttributeError):
                pass

        # Boost detected game processes
        if has_game:
            for game_pid, game_name in running_games:
                try:
                    gp = psutil.Process(game_pid)
                    saved["game_priority"][game_pid] = gp.nice()
                    if IS_WINDOWS:
                        gp.nice(psutil.ABOVE_NORMAL_PRIORITY_CLASS)
                    elif IS_LINUX and os.geteuid() == 0:
                        gp.nice(-5)
                    log(f"  ↑ Boosted: {game_name} → above-normal priority", "ok")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

        # ── Deep game-process optimizations (Linux) ───────────────────
        if has_game and IS_LINUX:
            all_game_pids = []
            for game_pid, _ in running_games:
                all_game_pids.append(game_pid)
                try:
                    children = psutil.Process(game_pid).children(recursive=True)
                    all_game_pids += [c.pid for c in children]
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            log("  . Applying deep process optimizations...", "text")

            # 1. SCHED_FIFO: game threads never preempted by normal processes
            _set_realtime_scheduling(all_game_pids, log, saved)

            # 2. OOM protection: kernel never kills game under memory pressure
            _protect_game_from_oom(all_game_pids, log, saved)

            # 3. P-core pinning: pin to performance cores on Intel hybrid CPUs
            _pin_game_to_perf_cores(all_game_pids, log, saved)

            # 4. Transparent Huge Pages: reduce TLB misses → faster memory access
            _set_thp_game(all_game_pids, log, saved)

        elif has_game and IS_WINDOWS:
            all_game_pids = []
            for game_pid, _ in running_games:
                all_game_pids.append(game_pid)

            # Windows: REALTIME priority class for game
            import ctypes as _wct
            for pid in all_game_pids:
                try:
                    PROCESS_ALL_ACCESS = 0x1F0FFF
                    REALTIME_PRIORITY_CLASS = 0x00000100
                    h = _wct.windll.kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
                    if h:
                        _wct.windll.kernel32.SetPriorityClass(h, REALTIME_PRIORITY_CLASS)
                        _wct.windll.kernel32.CloseHandle(h)
                        saved["game_priority"][pid] = "realtime"
                        log(f"  ↑ Windows: game process set to REALTIME priority class", "ok")
                except Exception:
                    pass

        # Kill bloat — reuse cpu_samples to skip 0.6s warm-up
        log("  . Scanning for idle background processes...", "text")
        # Pass detected game PIDs so kill_bloat never freezes them
        _game_pid_set = set()
        for game_pid, _ in running_games:
            _game_pid_set.add(game_pid)
            try:
                gp = psutil.Process(game_pid)
                for child in gp.children(recursive=True):
                    _game_pid_set.add(child.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        bloat_result = kill_bloat(log, use_sigstop=IS_LINUX, cpu_cache=cpu_samples,
                                  protected_extra=_game_pid_set)
        if bloat_result.rollback:
            saved["frozen"] = bloat_result.rollback[0].get("frozen_pids", {})

        log(f"  + CPU Matrix: {jailed} apps jailed, {soft_throttled} soft-throttled (active apps protected)", "ok")
    else:
        log("  ~ CPU ≤2 cores — CPU jail skipped", "warn")

    if IS_WINDOWS:
        log("  . Freezing background services...", "text")
        saved["services"] = _freeze_windows_services(log)
        saved["nagle_changed"] = _disable_nagle(log)

    log(f"✓ GAME MODE ON — {jailed} apps jailed", "ok")
    return saved


def game_mode_off(saved: dict, log):
    log("↺ Restoring system...", "head")

    # Resume frozen (SIGSTOP) processes first
    if saved.get("frozen") and IS_LINUX:
        restore_bloat(saved["frozen"], log)

    # Linux: restore new v2.5 features
    if IS_LINUX:
        _restore_screensaver(saved, log)
        _restore_io_scheduler(saved, log)
        _restore_gpu_performance(saved, log)
        _bypass_compositor_off(saved, log)
        # Restore deep game-process optimizations
        _restore_realtime_scheduling(saved, log)
        _restore_game_oom(saved, log)
        _restore_game_core_affinity(saved, log)
        _restore_thp(saved, log)

    if IS_WINDOWS:
        if saved.get("services"):
            _restore_windows_services(saved["services"], log)
        if saved.get("nagle_changed"):
            _restore_nagle(saved["nagle_changed"], log)
        _timer_resolution_restore(saved.get("timer_set", False), log)
        _restore_gamedvr(saved.get("gamedvr_orig"), log)
        if saved.get("dns_changed"):
            _restore_dns_windows(saved["dns_changed"], log)
        _bypass_compositor_off(saved, log)

    # Restore game process priority
    for pid, orig_nice in saved.get("game_priority", {}).items():
        try:
            psutil.Process(pid).nice(orig_nice)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    if saved.get("game_priority"):
        log(f"  + Game priority restored for {len(saved['game_priority'])} processes", "ok")

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
        "cgroup_path": None, "cgroup_procs": {},
        "eco_pids": [],
    }

    if IS_WINDOWS:
        # FIX v2.4: Removed MMCSS — AvSetMmThreadCharacteristicsW() boosts the
        # cyberclean.exe thread, NOT the game. Useless misapplication of API.
        # Replaced with EcoQoS (Win11+) which actually throttles background processes.
        win11 = _is_windows_11()
        if win11:
            log("ECO MODE ON — EcoQoS + memory hints (Windows 11)", "head")
        else:
            log("ECO MODE ON — memory hints (Windows 10)", "head")

        lowered = 0
        eco_pids = []
        protected = get_de_protected()
        for p in psutil.process_iter(["pid", "name"]):
            try:
                nm = (p.info["name"] or "").lower().replace(".exe", "")
                if nm in _ECO_SKIP or nm in protected or _is_protected(nm):
                    continue
                # Memory priority hint (works on all Windows)
                if _set_process_memory_priority(p.pid, MEMORY_PRIORITY_LOW):
                    saved["mem_lowered"].append(p.pid)
                    lowered += 1
                # EcoQoS: hardware power efficiency mode (Windows 11 only)
                if win11:
                    _set_ecoqos(p.pid, True)
                    eco_pids.append(p.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        saved["mode"] = "windows_memprio"
        saved["eco_pids"] = eco_pids
        log(f"  + Memory priority: {lowered} background processes marked for eviction", "ok")
        if win11 and eco_pids:
            log(f"  + EcoQoS: {len(eco_pids)} processes set to hardware efficiency mode", "ok")

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
        log("ECO MODE OFF — restoring background processes...", "head")
        # FIX v2.4: Removed _mmcss_boost_off() — MMCSS was boosting wrong thread.
        # Restore EcoQoS if was applied (Win11+)
        for pid in saved.get("eco_pids", []):
            _set_ecoqos(pid, False)
        if saved.get("eco_pids"):
            log(f"  + EcoQoS restored for {len(saved['eco_pids'])} processes", "ok")
        # Restore memory priority
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
    """
    Classify machine as high/mid/low for smart_boost strategy selection.

    FIX v2.4: Added GPU VRAM to classification.
    A machine with 32GB RAM + weak GPU is a workstation, not a gaming rig.
    A machine with 8GB RAM + RTX 3080 (8GB VRAM) should get full game treatment.
    """
    if not HAS_PSUTIL:
        return 'mid'
    try:
        ram_gb  = psutil.virtual_memory().total / (1024 ** 3)
        cores   = psutil.cpu_count(logical=False) or 2
        vram_gb = _get_gpu_vram_gb()

        # Gaming GPU boost: VRAM > 6GB = dedicated gaming/workstation GPU
        vram_bump = vram_gb >= 6.0

        if (ram_gb > 16 and cores > 6) or (ram_gb > 8 and cores > 4 and vram_bump):
            return 'high'
        elif (ram_gb > 8 and cores > 4) or (ram_gb > 4 and vram_bump):
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

    NEW v2.5:
    - PSI memory pressure monitor starts on Linux (proactive kill_bloat)
    - DNS boost opt-in on Windows (pass dns_boost=True via caller)
    """
    log("  . Detecting PC tier (RAM / CPU / GPU)...", "text")
    tier = detect_pc_tier()
    saved = {
        'tier': tier, 'game': {}, 'eco': {},
        'visuals_orig': None, 'freed_mb': 0,
        'psi_monitor': None, 'psi_stop': None,
    }

    tier_labels = {
        'high': 'HIGH-END — Gaming rig',
        'mid':  'MID — Solid machine',
        'low':  'LOW-END — Potato mode',
    }
    log(f'Smart Boost ON  [{tier_labels.get(tier, tier)}]', 'head')

    # NEW v2.5: Start PSI memory pressure monitor (Linux)
    if IS_LINUX:
        psi_t, psi_stop = _start_psi_monitor()
        if psi_t:
            saved['psi_monitor'] = psi_t
            saved['psi_stop']    = psi_stop
            log("  + PSI monitor: active — auto kill-bloat on memory pressure", "ok")

    if tier == 'low' and IS_WINDOWS:
        log("  . Tweaking visual effects...", "text")
        saved['visuals_orig'] = _tweak_windows_visuals(low_end=True, log=log)

    log("  . Starting Game Mode...", "text")
    saved['game'] = game_mode_on(log)

    if tier in ('mid', 'low'):
        log("  . Starting Eco Mode...", "text")
        saved['eco'] = eco_mode_on(log)

    if tier == 'low':
        log("  . Freeing RAM...", "text")
        result = free_ram(log)
        saved['freed_mb'] = getattr(result, 'mb_freed', 0)

    log(f'✓ Smart Boost ON [{tier}] — all layers applied', 'ok')
    return saved


def smart_boost_off(saved: dict, log):
    if not saved:
        return
    tier = saved.get('tier', 'mid')
    log(f'Smart Boost OFF — restoring [{tier}]...', 'head')

    # Stop PSI monitor
    if saved.get('psi_stop'):
        saved['psi_stop'].set()

    if saved.get('eco'):
        eco_mode_off(saved['eco'], log)
    if saved.get('game') is not None:
        game_mode_off(saved['game'], log)
    if saved.get('visuals_orig') is not None:
        _restore_windows_visuals(saved['visuals_orig'], log)
    log('✓ Smart Boost OFF — system restored', 'ok')
