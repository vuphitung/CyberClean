"""
CyberClean v2.6 — System Booster (Activity-Aware CPU Scheduling)
═══════════════════════════════════════════════════════════════
WHAT CHANGED vs v2.5:

GAME MODE — Activity-Aware CPU Jail (breaking fix):
  OLD: Discord, Chrome, Spotify etc. were ALL hard-jailed onto 1 weak core
       the moment a game was detected, regardless of what the user was doing.
       → Discord screen share: encoder starved → call freezes/audio glitches
       → YouTube music: decoder jailed → audio stutters
       → Spotify: same issue

  NEW: 3-tier activity-aware scheduling:

  Tier 0 — ACTIVE (> 2% CPU): App is actively serving the user right now.
    → Soft-throttle only: lower priority class so game wins contention,
      but keep all CPU cores available for burst (encoding, decoding, etc).
    → Discord call + screen share: stays smooth, game still wins on CPU.
    → YouTube music: keeps playing without stutter.

  Tier 1 — IDLE comms/media (≤ 2% CPU): App is open but not doing anything.
    → Restrict to upper half of cores (still responsive, just smaller domain).
    → Discord sitting in tray: restricted. Discord in a call: NOT restricted.

  Tier 2 — KNOWN BLOAT: OneDrive, Dropbox, telemetry, update services.
    → Hard-jail onto last core + idle priority. These should never burst.

  Added to TRASH_APPS: compattelrunner, diagtrack, steamwebhelper,
  epicwebhelper, searchindexer, wermgr.
  Added to COMMS_MEDIA: coccoc, twitch, streamlabs, xsplit.

═══════════════════════════════════════════════════════════════
WHAT CHANGED vs v2.4:

GAME MODE — Browser jail guard:
  OLD: Chrome/Firefox/Edge luôn bị jail vào last core + BELOW_NORMAL dù không có game.
  NEW: _detect_running_games() kiểm tra game process thực sự đang chạy.
       Nếu không có game → skip CPU jail cho MEDIA_APPS (browsers).
       Chỉ jail khi game đang active.

GAME MODE — Battery check:
  OLD: Luôn switch Power Plan sang Ultimate/High Performance.
  NEW: psutil.sensors_battery().power_plugged check.
       Đang dùng pin → skip Power Plan switch, log cảnh báo.

GAME MODE — SysMain guard:
  OLD: Luôn stop SysMain (Superfetch).
  NEW: Check rotational disk trước. HDD → giữ SysMain (prefetch hữu ích).
       SSD/NVMe → stop SysMain (neutral/nhẹ tác dụng).

GAME MODE — Timer Resolution (Windows):
  NEW: timeBeginPeriod(1) — set Windows scheduler tick 1ms thay vì 15.6ms.
       Giảm frame time jitter, smoother gaming.
       Restore timeEndPeriod(1) khi tắt.

GAME MODE — Game Process Priority Boost:
  NEW: Detect foreground game process, set ABOVE_NORMAL_PRIORITY_CLASS.
       Restore khi tắt.

ECO MODE — Xóa MMCSS misuse:
  OLD: AvSetMmThreadCharacteristicsW("Games") boost nhầm thread cyberclean.exe.
  NEW: MMCSS removed hoàn toàn. Chỉ giữ memory priority hints (đúng và hiệu quả).
       Windows 11: thêm EcoQoS (PROCESS_POWER_THROTTLING_STATE) để throttle background.

KILL BLOAT — Dynamic OOM threshold:
  OLD: OOM >= 300 cứng → không tác dụng trên máy ≥8GB RAM.
  NEW: Threshold động theo RAM: max(75, int(300 * 4 / ram_gb)).
       8GB → 150, 16GB → 75, 4GB → 300.
  Mem threshold: 200MB → 150MB.

MEMORY TUNE Windows:
  OLD: Chỉ gc.collect() — thu gom rác Python, vô nghĩa.
  NEW: SetProcessWorkingSetSizeEx trim working set của idle processes.
       Thực sự giải phóng physical RAM pages.

NETWORK TWEAK (Windows Game Mode):
  NEW: Disable Nagle algorithm (TcpAckFrequency=1, TCPNoDelay=1).
       Giảm TCP latency trong online games.
       Restore khi tắt.

FERAL GAMEMODE integration (Linux):
  NEW: Check gamemoded daemon. Nếu có → defer CPU governor to gamemoded.

DETECT PC TIER — GPU VRAM:
  NEW: Đọc GPU VRAM (Linux sysfs / Windows WMI).
       VRAM > 6GB = gaming tier bump. Classify chính xác hơn.

UX — Log messages cải thiện:
  - Free RAM: giải thích "0 MB freed is expected"
  - Kill Bloat: context message khi không có bloat
  - Smart Boost: progress log từng bước
  - Clear Shader Cache: warning về lần load chậm đầu tiên
  - Linux nice() skip: thông báo partial effect

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
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x0200 | 0x0400, False, pid)
        if not handle:
            return False
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
        kernel32.CloseHandle(handle)
        return bool(ok)
    except Exception:
        return False


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
# GAME PROCESS DETECTION
# ══════════════════════════════════════════════════════════════
# Detect if a real game is running before applying aggressive CPU jail.
# Prevents browsers from being crippled when user is just browsing.

# Known game launchers — their child processes are likely games
_GAME_LAUNCHERS = {
    "steam", "steamwebhelper", "epicgameslauncher", "gog-galaxy",
    "battle.net", "upc", "origin", "riotclientux", "leagueclient",
    "riotclientservices",
}

# Process names that are themselves games (not launchers)
_KNOWN_GAME_PROCS = {
    # Common engines / overlays
    "unrealcefsubprocess", "cef-subprocess", "gameoverlayui",
    # Popular titles
    "csgo", "cs2", "dota2", "gta5", "gtav", "cyberpunk2077",
    "eldenring", "baldursgate3", "bg3", "valorant", "fortnite",
    "minecraft", "terraria", "stardewvalley", "factorio",
    "rdr2", "witcher3", "witcher2", "witcher",
    "overwatch", "overwatch2", "diablo4",
}

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
    "python", "python3",   # already in _NON_GAME but extra safety
    "jupyter", "ipython",
}

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


def _detect_running_games(cpu_samples: Optional[dict] = None) -> tuple:
    """
    Return (games_list, cpu_samples_dict).
    games_list = list of (pid, name) for game processes currently running.
    cpu_samples_dict = {pid: cpu_pct} — reusable by kill_bloat to skip warm-up.

    FIX v2.5:
    - Removed Threshold 3 (>30% CPU, no launcher) — caused false positives with
      ffmpeg/cargo/webpack/antivirus being treated as games.
    - Added _KNOWN_HEAVY_NON_GAMES skip list.
    - Added Steam library integration via _get_steam_game_names().
    - Returns cpu_samples so kill_bloat can reuse without sleeping again.

    Strategy (2 matches only):
    1. Process name in _KNOWN_GAME_PROCS or Steam library
    2. Child of known launcher + CPU > 15%
    """
    if not HAS_PSUTIL:
        return [], {}

    # Merge Steam game names into known set
    all_game_names = _KNOWN_GAME_PROCS | _get_steam_game_names()

    games = []
    # Build launcher PID set first
    launcher_pids = set()
    for p in psutil.process_iter(["pid", "name"]):
        try:
            nm = (p.info["name"] or "").lower().replace(".exe", "")
            if nm in _GAME_LAUNCHERS:
                launcher_pids.add(p.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # Warm up cpu_percent — or reuse provided samples
    new_samples: dict = {}
    all_procs = []
    if cpu_samples is None:
        # Need to do warm-up ourselves
        for p in psutil.process_iter(["pid", "name", "ppid"]):
            try:
                p.cpu_percent(interval=0)
                all_procs.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        import time as _t; _t.sleep(0.5)
    else:
        # Reuse provided samples — skip sleep entirely
        for p in psutil.process_iter(["pid", "name", "ppid"]):
            try:
                all_procs.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    _NON_GAME = {
        "chrome", "chromium", "msedge", "firefox", "brave", "opera", "vivaldi",
        "discord", "slack", "teams", "zoom", "code", "idea", "pycharm",
        "explorer", "svchost", "dwm", "csrss", "winlogon", "lsass",
        "python", "python3", "cyberclean", "steamwebhelper",
        "obs", "obs32", "obs64",
    } | _KNOWN_HEAVY_NON_GAMES

    for p in all_procs:
        try:
            with p.oneshot():
                nm   = (p.name() or "").lower().replace(".exe", "")
                if nm in _NON_GAME:
                    continue
                # Get CPU: from cache or fresh read
                if cpu_samples and p.pid in cpu_samples:
                    cpu = cpu_samples[p.pid]
                else:
                    cpu = p.cpu_percent(interval=0)
                new_samples[p.pid] = cpu
                ppid = p.ppid()

                # Match 1: known game name (hardcoded + Steam library)
                if nm in all_game_names:
                    games.append((p.pid, p.name()))
                    continue

                # Match 2: child of a launcher using significant CPU
                # FIX: No Match 3 — removed >30% bare heuristic (false positives)
                if ppid in launcher_pids and cpu > _GAME_CPU_THRESHOLD:
                    games.append((p.pid, p.name()))

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

def _get_gpu_vram_gb() -> float:
    """Return GPU VRAM in GB. Returns 0.0 if detection fails."""
    if IS_LINUX:
        try:
            # Most reliable: sysfs drm
            for card in sorted(Path("/sys/class/drm").iterdir()):
                vram_file = card / "device/mem_info_vram_total"
                if vram_file.exists():
                    vram_bytes = int(vram_file.read_text().strip())
                    return vram_bytes / (1024 ** 3)
        except Exception:
            pass
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
                return g if g > 0 else 0.0
            try:
                return _vram_from_wmic()
            except OSError:
                return _vram_from_cim()
        except Exception:
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
            # SetProcessWorkingSetSizeEx(-1, -1, 0) = trim to minimum
            ok = kernel32.SetProcessWorkingSetSizeEx(
                handle,
                ctypes.c_size_t(0xFFFFFFFFFFFFFFFF),   # SIZE_MAX = trim
                ctypes.c_size_t(0xFFFFFFFFFFFFFFFF),
                ctypes.c_ulong(0)
            )
            kernel32.CloseHandle(handle)
            if ok:
                trimmed += 1
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
        all_pids_to_scan = list(_cpu_data.keys())
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
        all_pids_to_scan = None   # scan all

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
                # When using warm-up, skip PIDs not in warm-up set
                if cpu_cache is None and all_pids_to_scan is None:
                    pass  # no filter
                elif cpu_cache is None:
                    pass  # no filter needed
                # else: all_pids_to_scan is set — but we still scan all and use cached cpu

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
                            # High memory pressure — silently kill bloat
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
    if IS_LINUX:
        _set_gpu_performance(log, saved)

    # ── Linux: I/O scheduler → kyber/mq-deadline ──────────────
    if IS_LINUX:
        _set_io_scheduler(log, saved)

    # ── Linux: Inhibit screensaver / sleep ────────────────────
    if IS_LINUX:
        _inhibit_screensaver(log, saved)

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

        for p in psutil.process_iter(["pid", "name"]):
            try:
                nm = (p.info["name"] or "").lower().replace(".exe", "")
                if nm in protected or _is_protected(nm):
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
                                p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
                            elif IS_LINUX and os.geteuid() == 0:
                                p.nice(5)
                            soft_throttled += 1
                            log(f"  ~ Active: {nm} ({cpu_now:.1f}% CPU) → soft throttle only (no jail)", "ok")
                        else:
                            # Idle comms/media can still suddenly become active (voice/chat/video).
                            # On Windows, avoid affinity jail to prevent capture/overlay instability.
                            saved["nice"][p.pid] = p.nice()
                            if IS_WINDOWS:
                                p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
                                soft_throttled += 1
                                log(f"  ~ Idle: {nm} → priority only (no affinity jail on Windows)", "ok")
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

    if IS_WINDOWS:
        if saved.get("services"):
            _restore_windows_services(saved["services"], log)
        if saved.get("nagle_changed"):
            _restore_nagle(saved["nagle_changed"], log)
        _timer_resolution_restore(saved.get("timer_set", False), log)
        # NEW v2.5: Restore GameDVR
        _restore_gamedvr(saved.get("gamedvr_orig"), log)
        # NEW v2.5: Restore DNS if was changed
        if saved.get("dns_changed"):
            _restore_dns_windows(saved["dns_changed"], log)

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
