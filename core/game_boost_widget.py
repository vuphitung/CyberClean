"""
core/game_boost_widget.py — CyberClean System Booster UI & Lifecycle (v4.0)
═══════════════════════════════════════════════════════════════════════════
• Collision-Free OrbitButton HUD (4 corner badges outside rings + non-overlapping sphere text)
• Elevated MetricCards + PhaseBar + Interactive Pill Module Toggles + One-shot Tools
• Full state capture & deterministic restoration (CPU governor/power plan, swappiness,
  Hyprland misc:vfr & misc:no_direct_scanout, process niceness, environment variables)
• Crash-safe state persistence (boost_state.json) + synchronous shutdown() hook
• Full EN/VI internationalization via _t() and retranslate()
"""
import atexit
import json
import os
import platform
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QRectF, QSize, QPointF
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont,
    QTextCursor, QTextCharFormat, QPainterPath,
)
try:
    from PyQt6.QtGui import QRadialGradient, QLinearGradient
except ImportError:
    QRadialGradient = QLinearGradient = object
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QGridLayout, QCheckBox,
    QSizePolicy, QBoxLayout, QTextEdit,
)

IS_LINUX   = platform.system() == "Linux"
IS_WINDOWS = platform.system() == "Windows"

try:
    import psutil as _psutil_check  # noqa: F401
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

try:
    from ui_widgets import (
        C, MONO, UI, _btn, _t, is_dark_theme, _rgba,
        ElevatedCard, apply_elevation_shadow, _global_check_icon_path,
    )
except ImportError:
    C = {
        'bg': '#060911', 'bg2': '#0E1626', 'bg3': '#152036', 'bg4': '#1E2D4A',
        'well_bg': '#05080F',
        'cyan': '#00E5FF', 'cyan2': '#38BDF8', 'cyan_dim': '#062838',
        'red': '#FF2E63', 'red_dim': '#3B0A19',
        'yellow': '#FFB300', 'yel_dim': '#382405',
        'green': '#00E676', 'grn_dim': '#05331E',
        'purple': '#A855F7', 'magenta': '#EC4899',
        'text': '#F8FAFC', 'text2': '#CBD5E1', 'text3': '#94A3B8',
        'dim': '#64748B', 'border': '#152033', 'border2': '#1E2D47', 'border3': '#2E446B',
        'radius': '10px',
    }
    MONO = "'JetBrains Mono','Cascadia Code','Fira Code','Consolas',monospace"
    UI   = "'Inter','Noto Sans','Segoe UI','Ubuntu','Cantarell',sans-serif"

    def is_dark_theme() -> bool:
        return True

    def _rgba(hexcolor: str, alpha: float) -> str:
        h = str(hexcolor).lstrip('#')
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f'rgba({r},{g},{b},{max(0.0, min(1.0, float(alpha))):.2f})'

    def _global_check_icon_path() -> str:
        return ""

    def apply_elevation_shadow(w, **_):
        pass

    class ElevatedCard(QFrame):
        def __init__(self, border_color=None, accent_color=None, top_accent=None, shadow=True, parent=None):
            super().__init__(parent)

    def _t(key: str, default: str = "") -> str:
        try:
            from utils.i18n import _t as _t_real
            return _t_real(key, default)
        except Exception:
            return default or key

    def _btn(text, color='cyan', small=False):
        return QPushButton(text)


# ── Crash-safe state file & Hyprland helpers ─────────────────
def _boost_state_file() -> Path:
    base = Path.home() / ".local/share/cyber-clean"
    try:
        base.mkdir(parents=True, exist_ok=True)
        return base / "boost_state.json"
    except OSError:
        return Path(tempfile.gettempdir()) / "cyberclean_boost_state.json"


_PERSIST_KEYS = (
    "power", "swappiness_orig", "hyprland_vfr",
    "hyprland_vfr_orig", "hyprland_scanout_orig",
    "game_nice", "bg_nice", "env_orig",
    "timer_set", "gamedvr_orig", "gpu_perf_orig",
    "io_sched_orig", "game_core_affinity",
    "compositor_bypassed", "xprop_bypass_set",
    "services", "nagle_changed", "dns_changed",
    "thp_orig", "visuals_orig", "oom_protected", "rt_sched",
)


def _load_boost_state_disk() -> dict:
    st_file = _boost_state_file()
    if not st_file.exists():
        return {}
    try:
        data = json.loads(st_file.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _merge_unrestored_state(prior=None, current=None) -> dict:
    """
    Merge any un-restored state from a prior session into `current` so original pre-boost
    settings are never overwritten or dropped if Boost is toggled on again before full recovery.
    """
    merged = dict(current or {})
    if not isinstance(prior, dict) or not prior:
        return merged
    for k, old_val in prior.items():
        if old_val is None:
            continue
        if isinstance(old_val, dict):
            cur_val = merged.get(k)
            if isinstance(cur_val, dict):
                # Keep prior original values if the same key/PID was touched again
                combined = dict(cur_val)
                combined.update(old_val)
                merged[k] = combined
            elif old_val:
                merged[k] = dict(old_val)
        elif isinstance(old_val, list):
            cur_val = merged.get(k)
            if isinstance(cur_val, list):
                combined_list = list(old_val)
                for item in cur_val:
                    if item not in combined_list:
                        combined_list.append(item)
                merged[k] = combined_list
            elif old_val:
                merged[k] = list(old_val)
        else:
            # Scalar original setting (e.g. gamedvr_orig, power, swappiness_orig): prior holds the true pre-boost original
            merged[k] = old_val
    return merged


def _save_boost_state_disk(saved: dict) -> None:
    if not saved:
        return
    serializable = {}
    for k in _PERSIST_KEYS:
        if k in saved and saved[k] is not None:
            if k in ("game_nice", "bg_nice") and isinstance(saved[k], dict):
                serializable[k] = {
                    str(pid): (dict(val) if isinstance(val, dict) else int(val))
                    for pid, val in saved[k].items()
                }
            elif k == "game_core_affinity" and isinstance(saved[k], dict):
                serializable[k] = {str(pid): list(cores) for pid, cores in saved[k].items()}
            else:
                serializable[k] = saved[k]
    try:
        _boost_state_file().write_text(json.dumps(serializable), encoding="utf-8")
    except OSError:
        pass


def _get_boost_skip_set() -> set:
    """Build comprehensive cross-platform protected process set so audio, DE/WM, Xwayland, and launchers are never throttled."""
    skip = {
        "xwayland", "xorg", "x", "wineserver", "winedevice", "plugplay", "services",
        "gamescope", "gamemoded", "mangohud", "goverlay",
        "steam", "steamwebhelper", "epicgameslauncher", "riotclientservices", "riotclientux",
        "vgc", "vgctray", "beservice", "easyanticheat", "easyanticheat_eos", "battleye",
        "audiodg", "dwm", "explorer", "csrss", "winlogon", "wininit", "lsass", "svchost",
        "smss", "sihost", "taskhostw", "fontdrvhost", "runtimebroker", "spoolsv",
        "searchindexer", "ctfmon", "conhost", "dllhost", "wmiprvse",
        "obs", "obs64", "obs32", "pulseaudio", "pipewire", "wireplumber",
        "pipewire-pulse", "pipewire-media", "jackd", "jackdbus",
        "gnome-shell", "mutter", "kwin_x11", "kwin_wayland", "plasmashell",
        "xfwm4", "cinnamon", "muffin", "marco", "openbox", "cosmic-comp",
        "niri", "river", "hyprland", "sway", "waybar", "ags", "dunst", "mako", "swaync",
        "fcitx", "fcitx5", "ibus", "ibus-daemon", "dbus-daemon", "dbus-broker",
        "systemd", "init", "polkitd", "rtkit-daemon", "upowerd", "udisksd",
        "networkmanager", "wpa_supplicant", "iwd", "bluetoothd",
        "discord", "vesktop", "telegram", "signal", "slack", "zalo", "teams", "zoom",
        "firefox", "chrome", "chromium", "msedge", "brave", "vivaldi", "opera",
        "spotify", "code", "cursor", "cyberclean", "python", "python3",
    }
    try:
        from core.booster import get_de_protected, _NEVER_GAME, _BLOAT_SKIP_ALWAYS, _WIN_RAM_SKIP
        skip.update(n.lower().replace(".exe", "") for n in get_de_protected())
        skip.update(n.lower().replace(".exe", "") for n in _NEVER_GAME)
        skip.update(n.lower().replace(".exe", "") for n in _BLOAT_SKIP_ALWAYS)
        skip.update(n.lower().replace(".exe", "") for n in _WIN_RAM_SKIP)
    except Exception:
        pass
    return skip


def _should_skip_bg_proc(p, skip_set: set, game_pids: set) -> bool:
    """Return True if process `p` must NOT have its priority lowered."""
    try:
        if p.pid in game_pids or p.pid <= 10:
            return True
        nm = ((p.info.get("name") if hasattr(p, "info") and isinstance(p.info, dict) else None) or p.name() or "").lower()
        nm_clean = nm[:-4] if nm.endswith(".exe") else nm
        if not nm_clean or nm_clean in skip_set or nm in skip_set:
            return True
        try:
            from core.booster import _is_protected
            if _is_protected(nm_clean):
                return True
        except Exception:
            pass
        if IS_WINDOWS:
            try:
                uname = (p.username() or "").upper()
                if any(sys_acct in uname for sys_acct in ("SYSTEM", "LOCAL SERVICE", "NETWORK SERVICE", "DWM-", "UMFD-", "FONT DRIVER")):
                    return True
            except Exception:
                return True
        try:
            cmdline_str = " ".join(p.cmdline() or ()).lower()
            if any(k in cmdline_str for k in ("--type=gpu-process", "--type=renderer", "--utility-sub-type=audio", "xwayland", "wineserver", "proton", "steam")):
                return True
        except Exception:
            pass
    except Exception:
        return True
    return False


def _record_proc_nice_entry(p, orig_nice: int) -> dict:
    from core.booster import _proc_identity
    nm, ct = _proc_identity(p)
    return {"orig_nice": int(orig_nice), "name": nm, "create_time": ct}


def _apply_game_nice(p, pid: int, saved: dict) -> bool:
    """Boost priority of a game process; on Linux falls back to privileged helper `renice-game` when user lacks CAP_SYS_NICE."""
    try:
        import psutil as _psu
        orig = p.nice()
        if IS_WINDOWS:
            if orig != _psu.HIGH_PRIORITY_CLASS:
                p.nice(_psu.HIGH_PRIORITY_CLASS)
                saved.setdefault("game_nice", {})[pid] = _record_proc_nice_entry(p, orig)
                return True
        else:
            if orig > -10:
                try:
                    p.nice(-10)
                    saved.setdefault("game_nice", {})[pid] = _record_proc_nice_entry(p, orig)
                    return True
                except (PermissionError, _psu.AccessDenied):
                    try:
                        from core import privileged as _PRIV
                        r = _PRIV.run_helper("renice-game", str(pid), timeout=5, use_pkexec=False)
                        if r.ok:
                            saved.setdefault("game_nice", {})[pid] = _record_proc_nice_entry(p, orig)
                            return True
                    except Exception:
                        pass
    except Exception:
        pass
    return False


def _restore_process_priorities(saved: dict, log=None) -> int:
    """
    Restore `game_nice`, `bg_nice`, and `game_core_affinity` when game ends or Boost turns off.
    Verifies process identity (name + create_time) to avoid PID reuse, and preserves any
    un-restored entries in `saved` when restoration fails.
    """
    if not saved:
        return 0
    if log is None:
        log = lambda m, l="text": None
    restored = 0
    try:
        if saved.get("game_core_affinity"):
            from core.booster import _restore_game_core_affinity
            norm_aff = {int(k): v for k, v in (saved.get("game_core_affinity") or {}).items()}
            aff_holder = {"game_core_affinity": norm_aff}
            ok_aff = _restore_game_core_affinity(aff_holder, log)
            if ok_aff and not aff_holder.get("game_core_affinity"):
                saved.pop("game_core_affinity", None)
            else:
                saved["game_core_affinity"] = {str(k): v for k, v in (aff_holder.get("game_core_affinity") or {}).items()}
    except Exception as e:
        log(f"  ~ affinity restore error: {e}", "warn")
    if HAS_PSUTIL:
        try:
            import psutil
            from core.booster import _same_process_identity
            for key_name in ("game_nice", "bg_nice"):
                bucket = saved.get(key_name)
                if not isinstance(bucket, dict):
                    saved.pop(key_name, None)
                    continue
                failed_pids = []
                for pid_k, rec in list(bucket.items()):
                    try:
                        pid_int = int(pid_k)
                        orig_val = int(rec["orig_nice"]) if isinstance(rec, dict) else int(rec)
                    except (KeyError, ValueError, TypeError):
                        bucket.pop(pid_k, None)
                        continue
                    try:
                        proc = psutil.Process(pid_int)
                        if isinstance(rec, dict) and not _same_process_identity(proc, rec):
                            # PID was reused by a different process — drop stale record without touching new process
                            bucket.pop(pid_k, None)
                            continue
                        proc.nice(orig_val)
                        bucket.pop(pid_k, None)
                        restored += 1
                    except psutil.NoSuchProcess:
                        bucket.pop(pid_k, None)
                    except (psutil.AccessDenied, PermissionError, ValueError, OSError) as e:
                        failed_pids.append(f"PID {pid_int}: {e}")
                if not bucket:
                    saved.pop(key_name, None)
                elif failed_pids:
                    log(
                        f"  ⚠ Could not restore {key_name} for {len(failed_pids)} process(es): "
                        f"{'; '.join(failed_pids[:3])}",
                        "warn",
                    )
        except ImportError:
            pass
    return restored


def _clear_boost_state_disk() -> None:
    try:
        _boost_state_file().unlink(missing_ok=True)
    except OSError:
        pass


def _hyprctl_get_bool(option_name: str, default: str = "true") -> str:
    """Read current boolean option from Hyprland before modifying it."""
    if not IS_LINUX or not shutil.which("hyprctl"):
        return default
    try:
        r = subprocess.run(
            ["hyprctl", "getoption", option_name, "-j"],
            capture_output=True, text=True, timeout=3
        )
        if r.returncode == 0 and r.stdout.strip():
            data = json.loads(r.stdout)
            if "int" in data:
                return "true" if int(data["int"]) != 0 else "false"
            if "set" in data:
                return "true" if data["set"] else "false"
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["hyprctl", "getoption", option_name],
            capture_output=True, text=True, timeout=3
        )
        out = (r.stdout or "").lower()
        if "int: 0" in out or "false" in out:
            return "false"
        if "int: 1" in out or "true" in out:
            return "true"
    except Exception:
        pass
    return default


def _restore_boost_state(saved: dict, log=None) -> bool:
    """
    Deterministic restoration of all system states modified by GameBoostPage.
    Safe to call from worker thread, synchronous shutdown(), or startup crash recovery.
    Each restoration step runs in its own isolated try/except so a failure in one step
    never skips subsequent steps. Returns True only if all steps succeeded; if any step
    fails, preserves the remaining un-restored state in `boost_state.json`.
    """
    if log is None:
        log = lambda m, l="text": None
    if not saved:
        return True

    had_error = False
    from core.booster import (
        _restore_kernel_performance, smart_boost_off,
        _timer_resolution_restore, _restore_gamedvr,
        _bypass_compositor_off, _restore_io_scheduler,
        _restore_gpu_performance, _restore_screensaver,
    )

    from core.booster import (
        _restore_nagle, _restore_windows_services, _restore_dns_windows,
        _restore_thp, _restore_game_oom, _restore_realtime_scheduling,
    )

    if saved.get("power"):
        try:
            if _restore_kernel_performance(saved["power"], log) is not False:
                saved.pop("power", None)
            else:
                had_error = True
        except Exception as e:
            had_error = True
            log(f"  ~ power restore failed: {e}", "warn")

    if saved.get("timer_set"):
        try:
            if _timer_resolution_restore(bool(saved.get("timer_set")), log) is not False:
                saved.pop("timer_set", None)
            else:
                had_error = True
        except Exception as e:
            had_error = True
            log(f"  ~ timer resolution restore failed: {e}", "warn")

    if saved.get("gamedvr_orig") is not None:
        try:
            if _restore_gamedvr(saved.get("gamedvr_orig"), log) is not False:
                saved.pop("gamedvr_orig", None)
            else:
                had_error = True
        except Exception as e:
            had_error = True
            log(f"  ~ GameDVR restore failed: {e}", "warn")

    if saved.get("services"):
        try:
            if _restore_windows_services(saved["services"], log) is not False and not saved.get("services"):
                saved.pop("services", None)
            else:
                had_error = True
        except Exception as e:
            had_error = True
            log(f"  ~ Windows services restore failed: {e}", "warn")

    if saved.get("nagle_changed"):
        try:
            if _restore_nagle(saved["nagle_changed"], log) is not False and not saved.get("nagle_changed"):
                saved.pop("nagle_changed", None)
            else:
                had_error = True
        except Exception as e:
            had_error = True
            log(f"  ~ Nagle restore failed: {e}", "warn")

    if saved.get("dns_changed"):
        try:
            if _restore_dns_windows(saved["dns_changed"], log) is not False:
                saved.pop("dns_changed", None)
            else:
                had_error = True
        except Exception as e:
            had_error = True
            log(f"  ~ DNS restore failed: {e}", "warn")

    if saved.get("compositor_bypassed") or saved.get("xprop_bypass_set"):
        try:
            if _bypass_compositor_off(saved, log) is False or saved.get("compositor_bypassed") or saved.get("xprop_bypass_set"):
                had_error = True
        except Exception as e:
            had_error = True
            log(f"  ~ compositor restore failed: {e}", "warn")

    if saved.get("io_sched_orig"):
        try:
            if _restore_io_scheduler(saved, log) is False or saved.get("io_sched_orig"):
                had_error = True
        except Exception as e:
            had_error = True
            log(f"  ~ I/O scheduler restore failed: {e}", "warn")

    if saved.get("gpu_perf_orig"):
        try:
            if _restore_gpu_performance(saved, log) is False or saved.get("gpu_perf_orig"):
                had_error = True
        except Exception as e:
            had_error = True
            log(f"  ~ GPU performance restore failed: {e}", "warn")

    if saved.get("inhibit_proc"):
        try:
            if _restore_screensaver(saved, log) is False or saved.get("inhibit_proc"):
                had_error = True
        except Exception as e:
            had_error = True
            log(f"  ~ screensaver restore failed: {e}", "warn")

    if saved.get("thp_orig"):
        try:
            if _restore_thp(saved, log) is False or saved.get("thp_orig"):
                had_error = True
        except Exception as e:
            had_error = True
            log(f"  ~ THP restore failed: {e}", "warn")

    if saved.get("oom_protected"):
        try:
            if _restore_game_oom(saved, log) is False or saved.get("oom_protected"):
                had_error = True
        except Exception as e:
            had_error = True
            log(f"  ~ OOM score restore failed: {e}", "warn")

    if saved.get("rt_sched"):
        try:
            if _restore_realtime_scheduling(saved, log) is False or saved.get("rt_sched"):
                had_error = True
        except Exception as e:
            had_error = True
            log(f"  ~ realtime scheduling restore failed: {e}", "warn")

    if saved.get("game") or saved.get("eco") or saved.get("visuals_orig") is not None:
        try:
            if smart_boost_off(saved, log) is False or saved.get("game") or saved.get("eco") or saved.get("visuals_orig") is not None:
                had_error = True
        except Exception as e:
            had_error = True
            log(f"  ~ smart boost restore failed: {e}", "warn")

    try:
        legacy_env = Path.home() / ".config/environment.d/cyber-boost.conf"
        legacy_env.unlink(missing_ok=True)
    except OSError:
        pass

    env_orig = saved.get("env_orig")
    if isinstance(env_orig, dict):
        try:
            for k, prev in env_orig.items():
                if prev is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = str(prev)
            saved.pop("env_orig", None)
        except Exception as e:
            had_error = True
            log(f"  ~ env restore failed: {e}", "warn")

    sw = saved.get("swappiness_orig")
    if sw and IS_LINUX:
        sw_ok = False
        try:
            Path("/proc/sys/vm/swappiness").write_text(str(sw))
            log(f"  + vm.swappiness → {sw} [RESTORED]", "ok")
            sw_ok = True
        except (PermissionError, OSError):
            try:
                from core import privileged as _PRIV
                r_sw = _PRIV.run_helper("set-swappiness", str(sw), timeout=5, use_pkexec=False)
                if getattr(r_sw, "ok", False):
                    log(f"  + vm.swappiness → {sw} [RESTORED]", "ok")
                    sw_ok = True
            except Exception:
                pass
        if sw_ok:
            saved.pop("swappiness_orig", None)
        else:
            had_error = True
            log(f"  ⚠ Could not restore vm.swappiness to {sw}", "warn")

    if saved.get("hyprland_vfr") and IS_LINUX:
        if not shutil.which("hyprctl"):
            had_error = True
            log("  ⚠ hyprctl not found to restore Hyprland VFR/scanout settings", "warn")
        else:
            vfr_orig = str(saved.get("hyprland_vfr_orig", "true"))
            scan_orig = str(saved.get("hyprland_scanout_orig", "true"))
            try:
                r1 = subprocess.run(
                    ["hyprctl", "keyword", "misc:vfr", vfr_orig],
                    capture_output=True, timeout=3
                )
                r2 = subprocess.run(
                    ["hyprctl", "keyword", "misc:no_direct_scanout", scan_orig],
                    capture_output=True, timeout=3
                )
                if getattr(r1, "returncode", 1) == 0 and getattr(r2, "returncode", 1) == 0:
                    saved.pop("hyprland_vfr", None)
                    saved.pop("hyprland_vfr_orig", None)
                    saved.pop("hyprland_scanout_orig", None)
                    log(f"  + Hyprland: misc:vfr={vfr_orig}, misc:no_direct_scanout={scan_orig} [RESTORED]", "ok")
                else:
                    had_error = True
                    log("  ⚠ Hyprland settings restore returned non-zero status", "warn")
            except (OSError, subprocess.TimeoutExpired) as e:
                had_error = True
                log(f"  ~ Hyprland restore failed: {e}", "warn")

    try:
        _restore_process_priorities(saved, log)
        if saved.get("game_nice") or saved.get("bg_nice") or saved.get("game_core_affinity"):
            had_error = True
    except Exception as e:
        had_error = True
        log(f"  ~ process priority restore failed: {e}", "warn")

    if had_error:
        _save_boost_state_disk(saved)
        log("  ⚠ Some boost settings could not be restored — state kept for retry", "warn")
        return False

    _clear_boost_state_disk()
    return True


def _recover_stale_boost_on_startup() -> bool:
    """If CyberClean crashed or was killed while Boost was active, restore state on next launch."""
    try:
        legacy_env = Path.home() / ".config/environment.d/cyber-boost.conf"
        legacy_env.unlink(missing_ok=True)
    except OSError:
        pass
    st_file = _boost_state_file()
    if not st_file.exists():
        return True
    try:
        data = json.loads(st_file.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        _clear_boost_state_disk()
        return False
    if not isinstance(data, dict) or not data:
        _clear_boost_state_disk()
        return True
    return _restore_boost_state(data)


# ══════════════════════════════════════════════════════════════
# OrbitButton — Collision-Free 3D Orbital Gyroscope Reactor Button
# ══════════════════════════════════════════════════════════════
class OrbitButton(QPushButton):
    """
    3D Orbital Gyroscope Reactor Button:
      • 4 corner telemetry badges (GPU, CPU, RAM, NET) sit cleanly in the 4 outer
        corners completely outside the 3D gyroscope rings (zero overlap!).
      • Central 3D sphere houses a crisp lightning bolt in the upper half and
        auto-fitted status text (BOOST / ĐANG BẬT) in the lower half with
        generous clearance from the sphere border.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._active   = False
        self._phase    = 0.0
        self._dir      = 1
        self._rot_y    = 0.0
        self._rot_x    = 22.0
        self._target_x = 22.0
        self._target_y = 0.0
        self._hover    = False
        self._intro_ticks = 0
        self.setMouseTracking(True)
        self._timer    = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.setMinimumSize(148, 148)
        self.setMaximumSize(196, 196)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.setAccessibleName("Toggle system boost")
        self.setStyleSheet("background:transparent;border:none;")
        self._set_side(168)
        self._timer.start(33)

    def _set_side(self, side: int):
        side = max(148, min(196, int(side)))
        self.setFixedSize(side, side)

    def sizeHint(self):
        return QSize(168, 168)

    def showEvent(self, ev):
        self._intro_ticks = 0
        self._timer.start(33)
        super().showEvent(ev)

    def hideEvent(self, ev):
        self._timer.stop()
        super().hideEvent(ev)

    def enterEvent(self, ev):
        self._hover = True
        if self.isVisible():
            self._timer.setInterval(33)
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._hover = False
        self._target_x = 22.0
        self._target_y = 0.0
        if self._timer.isActive() and not self._active:
            self._timer.setInterval(120)
        super().leaveEvent(ev)

    def mouseMoveEvent(self, ev):
        w, h = max(1.0, float(self.width())), max(1.0, float(self.height()))
        rx = (ev.position().x() - w / 2.0) / (w / 2.0)
        ry = (ev.position().y() - h / 2.0) / (h / 2.0)
        self._target_y = rx * 28.0
        self._target_x = 22.0 - ry * 22.0
        super().mouseMoveEvent(ev)

    def set_active(self, v: bool):
        self._active = v
        if self.isVisible():
            self._timer.start(33 if v else 120)
        self.update()

    def _tick(self):
        if not self.isVisible():
            self._timer.stop()
            return
        win = self.window()
        if win is not None and win.isMinimized():
            self._timer.stop()
            return
        self._intro_ticks += 1
        if self._intro_ticks > 60 and not self._hover and not self._active and self._timer.interval() != 120:
            self._timer.setInterval(120)
        speed = 3.0 if self._active else (1.4 if self._hover else 1.8)
        self._rot_y = (self._rot_y + speed) % 360.0
        self._rot_x += (self._target_x - self._rot_x) * 0.14
        self._phase += self._dir * (0.04 if self._active else 0.025)
        if self._phase >= 1.0:
            self._dir = -1
        elif self._phase <= 0.0:
            self._dir = 1
        self.update()

    def paintEvent(self, _):
        import math as _m
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        cx, cy = w / 2.0, h / 2.0
        r = min(w, h) / 2.0 - 8.0
        dark = is_dark_theme()
        cyan    = QColor(C['cyan'])
        purple  = QColor(C.get('purple', '#A855F7'))
        green   = QColor(C['green'])

        # Ambient 3D radial aura
        glow = QRadialGradient(cx, cy, r * 0.96)
        g_col = green if self._active else cyan
        g1 = QColor(g_col)
        g1.setAlpha(int(52 + self._phase * 38) if self._active else (30 if self._hover else 16))
        g0 = QColor(g_col); g0.setAlpha(0)
        glow.setColorAt(0.0, g1)
        glow.setColorAt(1.0, g0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPointF(cx, cy), r * 0.96, r * 0.96)

        # Helper to project & draw a 3D gyroscope ring
        def draw_gyro_ring(rad_3d: float, tilt_z: float, rot_mult: float, col: QColor):
            n = 42
            pts = []
            ry = _m.radians(self._rot_y * rot_mult)
            rx = _m.radians(self._rot_x)
            rz = _m.radians(tilt_z)
            cy_r, sy_r = _m.cos(ry), _m.sin(ry)
            cx_r, sx_r = _m.cos(rx), _m.sin(rx)
            cz_r, sz_r = _m.cos(rz), _m.sin(rz)
            for i in range(n):
                a = (i / n) * _m.pi * 2.0
                x0, y0, z0 = rad_3d * _m.cos(a), 0.0, rad_3d * _m.sin(a)
                x1, y1, z1 = x0 * cz_r - y0 * sz_r, x0 * sz_r + y0 * cz_r, z0
                x2, y2, z2 = x1 * cy_r + z1 * sy_r, y1, -x1 * sy_r + z1 * cy_r
                x3, y3, z3 = x2, y2 * cx_r - z2 * sx_r, y2 * sx_r + z2 * cx_r
                fov, dist = 215.0, 245.0
                f = fov / max(1.0, dist + z3)
                pts.append((cx + x3 * f, cy + y3 * f, z3))
            for i in range(n):
                p1, p2 = pts[i], pts[(i + 1) % n]
                avg_z = (p1[2] + p2[2]) * 0.5
                alpha = int(max(40, min(245, (195 if self._active else 145) - avg_z * 1.6)))
                thick = max(1.1, min(3.2, (2.4 if self._active else 1.8) - avg_z * 0.018))
                sc = QColor(col.red(), col.green(), col.blue(), alpha)
                p.setPen(QPen(sc, thick, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(p1[0], p1[1]), QPointF(p2[0], p2[1]))

        c_ring1 = green if self._active else cyan
        c_ring2 = cyan if self._active else purple
        draw_gyro_ring(r * 0.74, 26.0, 1.0, c_ring1)
        draw_gyro_ring(r * 0.62, -32.0, -1.3, c_ring2)

        # Central 3D core sphere — sized so both bolt and label fit comfortably inside
        core_r = r * (0.47 + 0.018 * self._phase)
        core_col = green if self._active else (cyan if self._hover else QColor(C['cyan']))
        fill = QRadialGradient(cx - core_r * 0.22, cy - core_r * 0.22, core_r * 1.18)
        if dark:
            f0 = QColor(20, 32, 54, 246)
            f1 = QColor(8, 13, 24, 250)
            rim = QColor(core_col); rim.setAlpha(155 if self._active else 110)
        else:
            f0 = QColor(255, 255, 255, 252)
            f1 = QColor(238, 244, 252, 250)
            rim = QColor(core_col); rim.setAlpha(125 if self._active else 90)
        fill.setColorAt(0.0, f0)
        fill.setColorAt(0.75, f1)
        fill.setColorAt(1.0, rim)
        p.setBrush(QBrush(fill))
        p.setPen(QPen(core_col, 2.0 if self._active else 1.6))
        p.drawEllipse(QPointF(cx, cy), core_r, core_r)

        # Lightning Bolt cleanly in upper half of sphere
        bolt_cy = cy - core_r * 0.24
        bolt_sz = core_r * 0.34
        self._bolt(p, cx, bolt_cy, bolt_sz, core_col)

        # Status text cleanly in lower half of sphere (auto-sized so "ĐANG BẬT" never touches border)
        btn_txt = _t("boost_btn_active", "ACTIVE") if self._active else _t("boost_btn_idle", "BOOST")
        f_btn = QFont("JetBrains Mono" if not IS_WINDOWS else "Cascadia Code")
        f_btn.setPixelSize(9 if len(btn_txt) > 6 else 10)
        f_btn.setBold(True)
        p.setFont(f_btn)
        p.setPen(core_col if dark else QColor(C['text']))
        p.drawText(
            QRectF(cx - core_r * 0.84, cy + core_r * 0.14, core_r * 1.68, core_r * 0.44),
            Qt.AlignmentFlag.AlignCenter,
            btn_txt
        )

        # 4 Outer Corner Telemetry Pills (GPU, CPU, RAM, NET) — completely outside the 3D rings!
        f_tag = QFont("JetBrains Mono" if not IS_WINDOWS else "Cascadia Code")
        f_tag.setPixelSize(9)
        f_tag.setBold(True)
        p.setFont(f_tag)
        pill_w, pill_h = 32.0, 15.0
        corners = [
            (4.0, 4.0, "GPU"),
            (w - pill_w - 4.0, 4.0, "CPU"),
            (4.0, h - pill_h - 4.0, "NET"),
            (w - pill_w - 4.0, h - pill_h - 4.0, "RAM"),
        ]
        pill_bg = QColor(C['grn_dim'] if self._active else C['bg3'])
        pill_bg.setAlpha(210 if dark else 235)
        pill_border = QColor(green if self._active else C['border3'])
        pill_border.setAlpha(130)
        tag_fg = green if self._active else QColor(C['text3'])

        for px_c, py_c, tag_str in corners:
            crect = QRectF(px_c, py_c, pill_w, pill_h)
            p.setBrush(QBrush(pill_bg))
            p.setPen(QPen(pill_border, 1.0))
            p.drawRoundedRect(crect, 4.0, 4.0)
            p.setPen(tag_fg)
            p.drawText(crect, Qt.AlignmentFlag.AlignCenter, tag_str)

        p.end()

    def _bolt(self, p, cx, cy, s, color):
        path = QPainterPath()
        path.moveTo(cx + 3.5, cy - s)
        path.lineTo(cx - 2.0, cy - 1.5)
        path.lineTo(cx + 5.0, cy - 1.5)
        path.lineTo(cx - 3.5, cy + s)
        path.lineTo(cx + 2.0, cy + 1.5)
        path.lineTo(cx - 5.0, cy + 1.5)
        path.closeSubpath()
        p.fillPath(path, QBrush(color))


# ══════════════════════════════════════════════════════════════
# MetricCard — Elevated Telemetry Tile
# ══════════════════════════════════════════════════════════════
class MetricCard(ElevatedCard):
    def __init__(self, label: str, parent=None):
        super().__init__(top_accent=C['border3'], shadow=False, parent=parent)
        self.setObjectName("metricCard")
        self._bar_max = 200
        self.setMinimumHeight(74)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(4)

        self._lbl = QLabel(label.upper())
        self._lbl.setStyleSheet(
            f"color:{C['text3']};font-size:10px;letter-spacing:1.3px;"
            f"font-family:{UI};font-weight:700;border:none;background:transparent;"
        )
        self._val = QLabel("—")
        self._val.setStyleSheet(
            f"color:{C['text']};font-size:20px;font-weight:700;"
            f"font-family:{MONO};border:none;background:transparent;"
        )
        self._delta = QLabel("")
        self._delta.setStyleSheet(
            f"color:{C['cyan']};font-size:11px;font-family:{MONO};font-weight:700;"
            "border:none;background:transparent;"
        )
        row = QHBoxLayout()
        row.setSpacing(8)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._val)
        row.addWidget(self._delta)
        row.addStretch()

        self._bar_bg = QFrame(self)
        self._bar_bg.setFixedHeight(5)
        self._bar_bg.setStyleSheet(
            f"background:{C['bg3']};border:none;border-radius:2.5px;"
        )
        self._bar_fill = QFrame(self._bar_bg)
        self._bar_fill.setFixedHeight(5)
        self._bar_fill.setStyleSheet(
            f"background:{C['cyan']};border:none;border-radius:2.5px;"
        )
        self._bar_fill.setFixedWidth(0)

        lay.addWidget(self._lbl)
        lay.addLayout(row)
        lay.addStretch()
        lay.addWidget(self._bar_bg)

    def set_label(self, text: str):
        self._lbl.setText(text.upper())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._bar_bg.setFixedWidth(max(1, self.width() - 28))
        self._bar_max = max(1, self.width() - 28)

    def set_value(self, val: str, delta: str = "",
                  pct: float = 0, delta_color: str = None):
        self._val.setText(val)
        self._delta.setText(delta)
        col = delta_color or C['cyan']
        self._top_accent = col
        self._delta.setStyleSheet(
            f"color:{col};font-size:11px;font-family:{MONO};font-weight:700;"
            "border:none;background:transparent;"
        )
        w = int(self._bar_max * min(1.0, max(0.0, pct / 100)))
        self._bar_fill.setFixedWidth(w)
        self._bar_fill.setStyleSheet(
            f"background:{col};border:none;border-radius:2.5px;"
        )
        self.update()

    def set_lit(self, lit: bool):
        self._border_color = C['border3'] if lit else C['border2']
        if not lit:
            self._top_accent = C['border3']
        self.update()


# ══════════════════════════════════════════════════════════════
# PhaseBar
# ══════════════════════════════════════════════════════════════
class PhaseBar(QWidget):
    KEYS = [
        ("boost_phase_scan", "1 · SCAN"),
        ("boost_phase_apply", "2 · APPLY"),
        ("boost_phase_monitor", "3 · MONITOR"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cur_phase = -1
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self._pills = []
        for i, (k, default_txt) in enumerate(self.KEYS):
            pill = QLabel(_t(k, default_txt))
            pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pill.setMinimumHeight(32)
            pill.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            pill.setStyleSheet(self._style(False, False))
            self._pills.append(pill)
            lay.addWidget(pill, 1)
            if i < len(self.KEYS) - 1:
                sep = QLabel("›")
                sep.setAlignment(Qt.AlignmentFlag.AlignCenter)
                sep.setFixedWidth(14)
                sep.setStyleSheet(
                    f"color:{C['border3']};font-size:14px;border:none;background:transparent;font-family:{UI};"
                )
                lay.addWidget(sep, 0)

    def _style(self, active: bool, done: bool) -> str:
        r = C.get('radius', '8px')
        if active:
            return (f"color:{C['yellow']};font-size:11px;letter-spacing:1.2px;"
                    f"font-family:{UI};font-weight:700;border:1px solid {_rgba(C['yellow'], 0.50)};"
                    f"border-radius:{r};padding:5px 10px;background:{C['yel_dim']};")
        if done:
            return (f"color:{C['green']};font-size:11px;letter-spacing:1.2px;"
                    f"font-family:{UI};font-weight:700;border:1px solid {_rgba(C['green'], 0.40)};"
                    f"border-radius:{r};padding:5px 10px;background:{C['grn_dim']};")
        return (f"color:{C['text3']};font-size:11px;letter-spacing:1.2px;"
                f"font-family:{UI};font-weight:600;border:1px solid {C['border2']};"
                f"border-radius:{r};padding:5px 10px;background:{C['bg2']};")

    def set_phase(self, n: int):
        self._cur_phase = n
        for i, pill in enumerate(self._pills):
            pill.setStyleSheet(self._style(i == n, i < n))

    def retranslate(self):
        for pill, (k, default_txt) in zip(self._pills, self.KEYS):
            pill.setText(_t(k, default_txt))
        self.set_phase(self._cur_phase)


# ══════════════════════════════════════════════════════════════
# CyberLog
# ══════════════════════════════════════════════════════════════
class CyberLog(QTextEdit):
    MAX_LINES = 300
    COLORS = {
        "ok":   C['green'],
        "warn": C['yellow'],
        "head": C['cyan'],
        "err":  C['red'],
        "text": C['text'],
        "mute": C['text3'],
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setPlaceholderText(_t("boost_log_placeholder", "Press BOOST to scan GPU / RAM / background load…"))
        well_bg = C.get('well_bg', C['bg2'])
        self.setStyleSheet(f"""
            QTextEdit {{
                background:{well_bg};
                border:1px solid {C['border2']};
                border-radius:{C.get('radius', '10px')};
                color:{C['text']};
                font-family:{MONO};
                font-size:12px;
                padding:12px 16px;
            }}
            QTextEdit:focus {{
                border:1px solid {_rgba(C['cyan'], 0.45)};
            }}
            QScrollBar:vertical {{
                background:{well_bg};width:8px;border-radius:4px;
            }}
            QScrollBar::handle:vertical {{
                background:{C['border3']};border-radius:4px;
            }}
        """)

    def append_line(self, msg: str, level: str = "text"):
        if self.document().blockCount() > self.MAX_LINES:
            cur = self.textCursor()
            cur.movePosition(QTextCursor.MoveOperation.Start)
            for _ in range(50):
                cur.select(QTextCursor.SelectionType.BlockUnderCursor)
                cur.removeSelectedText()
                try:
                    cur.deleteChar()
                except Exception:
                    break
        cur = self.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        col_map = {
            "ok":   C['green'],
            "warn": C['yellow'],
            "head": C['cyan'],
            "err":  C['red'],
            "text": C['text'],
            "mute": C['text3'],
        }
        fmt.setForeground(QColor(col_map.get(level, C['text'])))
        cur.setCharFormat(fmt)
        cur.insertText(msg + "\n")
        self.setTextCursor(cur)
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())


# ══════════════════════════════════════════════════════════════
# GPU Monitor Thread
# ══════════════════════════════════════════════════════════════
def _linux_dgpu_is_sleeping() -> bool:
    """Avoid waking a suspended NVIDIA dGPU (D3cold) on hybrid Optimus laptops."""
    if not IS_LINUX:
        return False
    try:
        for p in Path("/sys/class/drm").glob("card*/device/power/runtime_status"):
            if p.read_text().strip() in ("suspended", "suspending"):
                vendor = p.parent.parent / "vendor"
                if vendor.exists() and "0x10de" in vendor.read_text().strip().lower():
                    return True
    except OSError:
        pass
    return False


class GpuMonitorThread(QThread):
    update = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self._stop = threading.Event()
        self.using_cpu_proxy = False

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.wait(4.0):
            if self._stop.is_set():
                break
            self.update.emit(self._read())

    def _read(self) -> int:
        if IS_LINUX:
            for p in sorted(Path("/sys/class/drm").glob("card*/device/gpu_busy_percent")):
                try:
                    val = int(p.read_text().strip())
                    self.using_cpu_proxy = False
                    return val
                except (OSError, ValueError):
                    pass

            for p in sorted(Path("/sys/class/drm").glob("card*/gt/gt0/rc6_residency_ms")):
                try:
                    v1 = int(p.read_text().strip())
                    if self._stop.wait(0.5):
                        return -1
                    v2 = int(p.read_text().strip())
                    delta_rc6 = v2 - v1
                    self.using_cpu_proxy = False
                    return max(0, min(100, 100 - int(delta_rc6 / 5)))
                except (OSError, ValueError):
                    pass

            if shutil.which("nvidia-smi") and not _linux_dgpu_is_sleeping():
                try:
                    r = subprocess.run(
                        ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                        capture_output=True, text=True, timeout=2
                    )
                    if r.returncode == 0 and r.stdout.strip():
                        self.using_cpu_proxy = False
                        return int(float(r.stdout.strip().splitlines()[0].strip()))
                except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
                    pass

            try:
                import psutil as _psu
                cpu = _psu.cpu_percent(interval=0.2)
                self.using_cpu_proxy = True
                return int(min(100, cpu))
            except ImportError:
                pass

        if IS_WINDOWS:
            if shutil.which("nvidia-smi"):
                try:
                    r = subprocess.run(
                        ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                        capture_output=True, text=True, timeout=2,
                        creationflags=0x08000000
                    )
                    if r.returncode == 0 and r.stdout.strip():
                        self.using_cpu_proxy = False
                        return int(float(r.stdout.strip().splitlines()[0].strip()))
                except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
                    pass

            try:
                import psutil as _psu
                self.using_cpu_proxy = True
                return int(min(100, _psu.cpu_percent(interval=0.15)))
            except ImportError:
                pass
        return -1


# ══════════════════════════════════════════════════════════════
# Game Watcher Thread — detect game AFTER boost is active
# ══════════════════════════════════════════════════════════════
class GameWatcherThread(QThread):
    game_found = pyqtSignal(list, str, list)   # (new_pids, game_name, all_known_pids)
    game_lost  = pyqtSignal()
    log_sig    = pyqtSignal(str, str)

    _FULL_RESCAN_EVERY = 10

    def __init__(self, saved: dict):
        super().__init__()
        self._saved  = saved
        self._stop   = threading.Event()
        self._known  = set(saved.get("game_pids") or [])
        self._had_game = bool(self._known)
        self._ticks_since_scan = 0

    def stop(self):
        self._stop.set()

    def run(self):
        if not HAS_PSUTIL:
            self.log_sig.emit("  ~ watcher: psutil not available — game auto-detect disabled", "warn")
            return
        import psutil as _psu
        while not self._stop.wait(4.0):
            if self._stop.is_set():
                break
            try:
                if self._known:
                    alive = {pid for pid in self._known if _psu.pid_exists(pid)}
                    if not alive and self._had_game:
                        self._known = set()
                        self._had_game = False
                        self._ticks_since_scan = 0
                        self.game_lost.emit()
                    else:
                        self._known = alive
                        self._ticks_since_scan += 1
                        if self._ticks_since_scan < self._FULL_RESCAN_EVERY:
                            continue
                        self._ticks_since_scan = 0

                from core.booster import _detect_running_games
                running, _ = _detect_running_games()
                if not running:
                    continue
                seen, pids = set(), []
                for pid, name in running:
                    if pid in seen:
                        continue
                    seen.add(pid)
                    pids.append(pid)
                    try:
                        for c in _psu.Process(pid).children(recursive=True):
                            if c.pid not in seen:
                                seen.add(c.pid)
                                pids.append(c.pid)
                    except (_psu.NoSuchProcess, _psu.AccessDenied):
                        pass
                new = set(pids) - self._known
                if new:
                    self._known |= set(pids)
                    self._had_game = True
                    new_names = [nm for pid, nm in running if pid in new]
                    name = new_names[0] if new_names else (running[0][1] if running else "game")
                    self.game_found.emit(list(new), name, list(self._known))
            except Exception as e:
                self.log_sig.emit(f"  ~ watcher: {e}", "warn")


# ══════════════════════════════════════════════════════════════
# Boost Worker
# ══════════════════════════════════════════════════════════════
class BoostWorker(QThread):
    log_sig    = pyqtSignal(str, str)
    phase_sig  = pyqtSignal(int)
    metric_sig = pyqtSignal(str, object)
    done_sig   = pyqtSignal(object)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        result = self._fn(
            lambda m, l="text": self.log_sig.emit(m, l),
            self.phase_sig,
            self.metric_sig
        )
        self.done_sig.emit(result)


# ══════════════════════════════════════════════════════════════
# GameBoostPage
# ══════════════════════════════════════════════════════════════
class GameBoostPage(QWidget):
    boost_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active         = False
        self._transitioning  = False
        self._saved_state    = None
        self._worker         = None
        self._tool_worker    = None
        self._gpu_thread     = None
        self._gpu_baseline   = -1
        self._watcher        = None
        self._status_key     = "standby"
        self._status_col     = C['dim']

        _recover_stale_boost_on_startup()
        atexit.register(self._atexit_cleanup)
        self._setup_ui()

    def _setup_ui(self):
        self.setStyleSheet(f"background:{C['bg']};")
        self._compact = None
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(10)

        hdr = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.setContentsMargins(0, 0, 0, 0)
        self._title_lbl = QLabel(_t("booster_title", "SYSTEM BOOSTER"))
        self._title_lbl.setStyleSheet(
            f"color:{C['text']};font-size:18px;letter-spacing:1.2px;"
            f"font-family:{UI};font-weight:700;border:none;background:transparent;"
        )
        self._sub_lbl = QLabel(_t("boost_hud_sub", "Tactical resource optimizer · automatic state snapshot & restore on exit"))
        self._sub_lbl.setStyleSheet(
            f"color:{C['text3']};font-size:12px;font-family:{UI};border:none;background:transparent;"
        )
        self._sub_lbl.setWordWrap(True)
        titles.addWidget(self._title_lbl)
        titles.addWidget(self._sub_lbl)

        self._sdot = QLabel("●")
        self._stxt = QLabel(_t("boost_state_standby", "STANDBY"))
        status = QFrame()
        status.setObjectName("boostStatusPill")
        status.setStyleSheet(
            f"QFrame#boostStatusPill{{background:{C['bg2']};border:1px solid {C['border2']};"
            f"border-radius:8px;}}"
            f"QFrame#boostStatusPill QLabel{{border:none;background:transparent;}}"
        )
        st_lay = QHBoxLayout(status)
        st_lay.setContentsMargins(10, 6, 12, 6)
        st_lay.setSpacing(6)
        for w in (self._sdot, self._stxt):
            w.setStyleSheet(
                f"color:{C['text3']};font-size:11px;letter-spacing:1px;"
                f"font-family:{MONO};font-weight:700;border:none;background:transparent;"
            )
        st_lay.addWidget(self._sdot)
        st_lay.addWidget(self._stxt)
        hdr.addLayout(titles, 1)
        hdr.addWidget(status, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(hdr)

        # ── Main HUD Card (OrbitButton + 4 MetricCards) ────────
        self._cmd = ElevatedCard(accent_color=C['cyan'], shadow=True)
        self._cmd.setObjectName("boostHud")
        self._cmd.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._cmd_lay = QHBoxLayout(self._cmd)
        self._cmd_lay.setContentsMargins(18, 14, 18, 14)
        self._cmd_lay.setSpacing(18)

        self._btn = OrbitButton()
        self._btn.clicked.connect(self._toggle)
        self._cmd_lay.addWidget(self._btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._metrics_wrap = QWidget()
        self._metrics_wrap.setStyleSheet("background:transparent;border:none;")
        grid = QGridLayout(self._metrics_wrap)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        self._mc_gpu  = MetricCard(_t("boost_mc_gpu", "GPU BUSY"))
        self._mc_ram  = MetricCard(_t("boost_mc_ram", "RAM FREED"))
        self._mc_bg   = MetricCard(_t("boost_mc_bg", "BACKGROUND"))
        self._mc_game = MetricCard(_t("boost_mc_game", "GAME DETECT"))
        grid.addWidget(self._mc_gpu,  0, 0)
        grid.addWidget(self._mc_ram,  0, 1)
        grid.addWidget(self._mc_bg,   1, 0)
        grid.addWidget(self._mc_game, 1, 1)
        self._cmd_lay.addWidget(self._metrics_wrap, 1)
        root.addWidget(self._cmd, 0)

        # ── Tactical Module Toggles & Standalone One-Shot Tools ─
        self._mods_frame = ElevatedCard(shadow=True)
        self._mods_frame.setObjectName("boostModsFrame")
        mods_lay = QVBoxLayout(self._mods_frame)
        mods_lay.setContentsMargins(14, 10, 14, 10)
        mods_lay.setSpacing(8)

        top_mods = QHBoxLayout()
        top_mods.setSpacing(8)
        self._lbl_profile = QLabel(_t("boost_profile_lbl", "ACTIVE MODULES:"))
        self._lbl_profile.setStyleSheet(
            f"color:{C['text3']};font-size:10px;letter-spacing:1.2px;font-weight:700;"
            f"font-family:{UI};border:none;background:transparent;"
        )
        top_mods.addWidget(self._lbl_profile)

        self._chk_ram = QCheckBox(_t("boost_mod_ram", "Compact / Free RAM"))
        self._chk_ram.setChecked(True)
        self._chk_gov = QCheckBox(_t("boost_mod_gov", "CPU Performance Mode"))
        self._chk_gov.setChecked(True)
        self._chk_prio = QCheckBox(_t("boost_mod_prio", "Process Priority (Nice)"))
        self._chk_prio.setChecked(True)
        self._chk_swap = QCheckBox(_t("boost_mod_swap", "Low Swappiness"))
        self._chk_swap.setChecked(True)
        self._chk_hypr = QCheckBox(_t("boost_mod_hypr", "Hyprland VFR / Scanout"))
        self._chk_hypr.setChecked(True)
        if not IS_LINUX:
            self._chk_swap.setVisible(False)
            self._chk_hypr.setVisible(False)
        elif not shutil.which("hyprctl"):
            self._chk_hypr.setVisible(False)

        chk_img = _global_check_icon_path()
        chk_img_rule = f'image:url("{chk_img}");' if chk_img else ''
        for chk in (self._chk_ram, self._chk_gov, self._chk_prio, self._chk_swap, self._chk_hypr):
            chk.setCursor(Qt.CursorShape.PointingHandCursor)
            chk.setStyleSheet(f"""
                QCheckBox {{
                    color:{C['text2']}; font-size:12px; font-family:{UI}; font-weight:600;
                    spacing:6px; background:{C['bg3']}; border:1px solid {C['border2']};
                    border-radius:6px; padding:5px 10px;
                }}
                QCheckBox:hover {{
                    border-color:{_rgba(C['cyan'], 0.55)}; color:{C['text']};
                }}
                QCheckBox::indicator {{
                    width:15px; height:15px; border:1.5px solid {C['border3']};
                    border-radius:4px; background:transparent;
                }}
                QCheckBox::indicator:checked {{
                    background:{C['cyan']}; border-color:{C['cyan']};
                    {chk_img_rule}
                }}
            """)
            top_mods.addWidget(chk)
        top_mods.addStretch()

        self._btn_shader = _btn(f"◈ {_t('btn_clear_cache', 'CLEAR SHADER CACHE')}", "cyan", small=True)
        self._btn_shader.clicked.connect(self._run_clear_shader_cache)
        self._btn_bloat = _btn(f"✕ {_t('btn_kill_bloat', 'SUSPEND BLOAT')}", "yellow", small=True)
        self._btn_bloat.clicked.connect(self._run_kill_bloat)
        top_mods.addWidget(self._btn_shader)
        top_mods.addWidget(self._btn_bloat)
        mods_lay.addLayout(top_mods)
        root.addWidget(self._mods_frame, 0)

        self._phases = PhaseBar()
        root.addWidget(self._phases, 0)

        self._log = CyberLog()
        self._log.append_line(_t("boost_log_ready", "[ ready — press BOOST to optimize ]"), "mute")
        root.addWidget(self._log, 1)

    def retranslate(self):
        self._title_lbl.setText(_t("booster_title", "SYSTEM BOOSTER"))
        self._sub_lbl.setText(_t("boost_hud_sub", "Tactical resource optimizer · automatic state snapshot & restore on exit"))
        if not getattr(self, "_using_cpu_proxy", False):
            self._mc_gpu.set_label(_t("boost_mc_gpu", "GPU BUSY"))
        else:
            self._mc_gpu.set_label(_t("boost_mc_cpu_proxy", "CPU LOAD"))
        self._mc_ram.set_label(_t("boost_mc_ram", "RAM FREED"))
        self._mc_bg.set_label(_t("boost_mc_bg", "BACKGROUND"))
        self._mc_game.set_label(_t("boost_mc_game", "GAME DETECT"))
        self._lbl_profile.setText(_t("boost_profile_lbl", "ACTIVE MODULES:"))
        self._chk_ram.setText(_t("boost_mod_ram", "Compact / Free RAM"))
        self._chk_gov.setText(_t("boost_mod_gov", "CPU Performance Mode"))
        self._chk_prio.setText(_t("boost_mod_prio", "Process Priority (Nice)"))
        self._chk_swap.setText(_t("boost_mod_swap", "Low Swappiness"))
        self._chk_hypr.setText(_t("boost_mod_hypr", "Hyprland VFR / Scanout"))
        self._btn_shader.setText(f"◈ {_t('btn_clear_cache', 'CLEAR SHADER CACHE')}")
        self._btn_bloat.setText(f"✕ {_t('btn_kill_bloat', 'SUSPEND BLOAT')}")
        self._phases.retranslate()
        self._log.setPlaceholderText(_t("boost_log_placeholder", "Press BOOST to scan GPU / RAM / background load…"))
        self._set_status(self._status_key, self._status_col)
        self._btn.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        compact = self.width() < 740
        side = 152 if compact else min(184, max(152, int(self.height() * 0.21)))
        self._btn._set_side(side)
        if compact:
            self._cmd.setMaximumHeight(440)
            self._metrics_wrap.setMinimumHeight(156)
            self._metrics_wrap.setMaximumHeight(220)
        else:
            self._cmd.setMaximumHeight(216)
            self._metrics_wrap.setMinimumHeight(0)
            self._metrics_wrap.setMaximumHeight(188)
        if compact == self._compact:
            return
        self._compact = compact
        direction = QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight
        self._cmd_lay.setDirection(direction)
        align = Qt.AlignmentFlag.AlignHCenter if compact else Qt.AlignmentFlag.AlignVCenter
        self._cmd_lay.setAlignment(self._btn, align)
        self._metrics_wrap.setMinimumHeight(160 if compact else 148)

    def _set_status(self, key: str, color: str):
        self._status_key = key
        self._status_col = color
        label_map = {
            "standby":    _t("boost_state_standby", "STANDBY"),
            "scanning":   _t("boost_state_scanning", "SCANNING"),
            "monitoring": _t("boost_state_monitoring", "MONITORING"),
            "restoring":  _t("boost_state_restoring", "RESTORING"),
        }
        s = (f"color:{color};font-size:11px;letter-spacing:1px;"
             f"font-family:{MONO};font-weight:700;border:none;background:transparent;")
        self._sdot.setStyleSheet(s)
        self._stxt.setStyleSheet(s)
        self._stxt.setText(label_map.get(key, key.upper()))

    # ── Standalone One-Shot Tools ─────────────────────────────
    def _run_one_shot(self, fn):
        if self._transitioning or (self._tool_worker is not None and self._tool_worker.isRunning()):
            return
        self._btn_shader.setEnabled(False)
        self._btn_bloat.setEnabled(False)

        def _wrap(log, _p, _m):
            try:
                fn(log)
            except Exception as exc:
                log(f"  ✗ {exc}", "err")
            return None

        def _done(_):
            self._btn_shader.setEnabled(True)
            self._btn_bloat.setEnabled(True)

        self._tool_worker = BoostWorker(_wrap)
        self._tool_worker.log_sig.connect(lambda m, l: self._log.append_line(m, l))
        self._tool_worker.done_sig.connect(_done)
        self._tool_worker.start()

    def _run_clear_shader_cache(self):
        from core.booster import clear_disk_cache
        self._run_one_shot(clear_disk_cache)

    def _run_kill_bloat(self):
        from core.booster import kill_bloat
        self._run_one_shot(kill_bloat)

    # ── Toggle Boost ──────────────────────────────────────────
    def _toggle(self):
        if self._transitioning:
            return
        self._transitioning = True
        self._btn.setEnabled(False)
        if not self._active:
            self._start()
        else:
            self._stop()

    def _start(self):
        self._active = True
        self._btn.set_active(True)
        self._phases.set_phase(0)
        self._set_status("scanning", C['yellow'])
        for chk in (self._chk_ram, self._chk_gov, self._chk_prio, self._chk_swap, self._chk_hypr):
            chk.setEnabled(False)
        self._log.clear()
        self._log.append_line("┌─ SYSTEM BOOST ───────────────────────────", "head")
        self.boost_toggled.emit(True)

        opts = {
            "ram":  self._chk_ram.isChecked(),
            "gov":  self._chk_gov.isChecked(),
            "prio": self._chk_prio.isChecked(),
            "swap": self._chk_swap.isChecked(),
            "hypr": self._chk_hypr.isChecked(),
        }
        self._worker = BoostWorker(lambda log, p, m: self._boost_logic(log, p, m, opts))
        self._worker.log_sig.connect(lambda m, l: self._log.append_line(m, l))
        self._worker.phase_sig.connect(self._phases.set_phase)
        self._worker.metric_sig.connect(self._on_metric)
        self._worker.done_sig.connect(self._on_done)
        self._worker.start()

    def _on_done(self, saved):
        prior = _merge_unrestored_state(_load_boost_state_disk(), self._saved_state)
        self._saved_state   = _merge_unrestored_state(prior, saved or {})
        _save_boost_state_disk(self._saved_state)
        self._transitioning = False
        self._btn.setEnabled(True)
        self._set_status("monitoring", C['cyan'])
        self._gpu_baseline = -1
        self._gpu_thread   = GpuMonitorThread()
        self._gpu_thread.update.connect(self._on_gpu)
        self._gpu_thread.start()

        self._watcher = GameWatcherThread(self._saved_state)
        self._watcher.game_found.connect(self._on_game_found)
        self._watcher.game_lost.connect(self._on_game_lost)
        self._watcher.log_sig.connect(lambda m, l: self._log.append_line(m, l))
        self._watcher.start()

    # ── STOP & SHUTDOWN ───────────────────────────────────────
    def _stop(self):
        self._set_status("restoring", C['yellow'])
        self._log.append_line("├─ RESTORE ────────────────────────────────", "warn")
        if self._gpu_thread:
            self._gpu_thread.stop()
            self._gpu_thread.wait(1500)
            self._gpu_thread = None
        if self._watcher:
            self._watcher.stop()
            self._watcher.wait(1500)
            self._watcher = None
        saved = self._saved_state

        def _restore(log, *_):
            ok = False
            try:
                ok = _restore_boost_state(saved, log)
                if ok:
                    log("└─ DONE ───────────────────────────────────", "head")
                else:
                    log("└─ PARTIAL RESTORE (SOME STEPS FAILED) ────", "warn")
            except Exception as e:
                log(f"  ~ restore: {e}", "warn")
            return ok

        self._worker = BoostWorker(_restore)
        self._worker.log_sig.connect(lambda m, l: self._log.append_line(m, l))
        self._worker.done_sig.connect(self._on_restore_done)
        self._worker.start()

    def _on_restore_done(self, ok):
        self._active        = False
        if ok:
            self._saved_state = None
        self._transitioning = False
        self._btn.set_active(False)
        self._btn.setEnabled(True)
        for chk in (self._chk_ram, self._chk_gov, self._chk_prio, self._chk_swap, self._chk_hypr):
            chk.setEnabled(True)
        self._phases.set_phase(-1)
        self._set_status("standby", C['dim'])
        for mc in (self._mc_gpu, self._mc_ram, self._mc_bg, self._mc_game):
            mc.set_value("—")
            mc.set_lit(False)
        self.boost_toggled.emit(False)

    def _atexit_cleanup(self):
        try:
            pending = _merge_unrestored_state(_load_boost_state_disk(), self._saved_state)
            if pending:
                if _restore_boost_state(pending):
                    self._saved_state = None
                else:
                    self._saved_state = pending
                self._active = False
        except Exception:
            pass

    def shutdown(self):
        """Synchronous teardown called by MainWindow._shutdown() on application exit."""
        if self._gpu_thread:
            self._gpu_thread.stop()
            self._gpu_thread.wait(1500)
            self._gpu_thread = None
        if self._watcher:
            self._watcher.stop()
            self._watcher.wait(1500)
            self._watcher = None
        if self._worker and self._worker.isRunning():
            self._worker.wait(3000)
        if self._tool_worker and self._tool_worker.isRunning():
            self._tool_worker.wait(2000)
        pending = _merge_unrestored_state(_load_boost_state_disk(), self._saved_state)
        if pending:
            if _restore_boost_state(pending):
                self._saved_state = None
            else:
                self._saved_state = pending
            self._active = False

    # ── Game found / lost handlers ────────────────────────────
    def _on_game_found(self, pids: list, name: str, all_known_pids: list = None):
        all_game_pids = set(all_known_pids) if all_known_pids else set(pids)
        self._mc_game.set_value(f"{len(pids)} PIDs", name[:12], 80, C['purple'])
        self._mc_game.set_lit(True)
        if not self._chk_prio.isChecked():
            self._log.append_line(f"  ◈ Game detected: {name} ({len(pids)} PIDs)", "ok")
            return

        boosted = 0
        bg_count = 0
        saved = self._saved_state if isinstance(self._saved_state, dict) else {}
        try:
            import psutil as _psu
            for pid in pids[:8]:
                try:
                    p = _psu.Process(pid)
                    if _apply_game_nice(p, pid, saved):
                        boosted += 1
                except (_psu.NoSuchProcess, _psu.AccessDenied, ValueError, OSError):
                    pass

            if IS_LINUX:
                try:
                    from core.booster import _pin_game_to_perf_cores
                    _pin_game_to_perf_cores(pids[:8], lambda m, l="text": self._log.append_line(m, l), saved)
                except Exception:
                    pass

            uid = os.getuid() if IS_LINUX else -1
            skip_set = _get_boost_skip_set()
            for p in _psu.process_iter(["pid", "name"]):
                try:
                    if IS_LINUX and uid >= 0:
                        try:
                            if p.uids().real != uid:
                                continue
                        except (_psu.NoSuchProcess, _psu.AccessDenied):
                            continue
                    if _should_skip_bg_proc(p, skip_set, all_game_pids):
                        continue
                    o = p.nice()
                    if IS_WINDOWS:
                        if o == _psu.NORMAL_PRIORITY_CLASS:
                            p.nice(_psu.BELOW_NORMAL_PRIORITY_CLASS)
                            saved.setdefault("bg_nice", {})[p.pid] = _record_proc_nice_entry(p, o)
                            bg_count += 1
                    else:
                        if o < 5:
                            from core.booster import _can_restore_linux_nice
                            if not _can_restore_linux_nice(o):
                                continue
                            p.nice(5)
                            saved.setdefault("bg_nice", {})[p.pid] = _record_proc_nice_entry(p, o)
                            bg_count += 1
                except Exception:
                    pass
            _save_boost_state_disk(saved)
        except ImportError:
            pass

        if boosted or bg_count:
            self._log.append_line(
                f"  ★ Game detected: {name} ({len(pids)} PIDs) — applying priority boost",
                "head"
            )
            if boosted:
                prio_lbl = "HIGH_PRIORITY" if IS_WINDOWS else "nice(-10)"
                self._log.append_line(f"  + {boosted} game process(es) → {prio_lbl}", "ok")
            if bg_count:
                bg_lbl = "BELOW_NORMAL" if IS_WINDOWS else "nice(+5)"
                self._log.append_line(f"  + {bg_count} background → {bg_lbl}", "ok")
                self._mc_bg.set_value(f"{bg_count} procs", bg_lbl, min(100, bg_count * 4), C['yellow'])
                self._mc_bg.set_lit(True)
        else:
            self._log.append_line(f"  ◈ Game detected: {name} ({len(pids)} PIDs)", "ok")

    def _on_game_lost(self):
        restored = 0
        if isinstance(self._saved_state, dict):
            restored = _restore_process_priorities(
                self._saved_state,
                lambda m, l="text": self._log.append_line(m, l),
            )
            _save_boost_state_disk(self._saved_state)
        self._log.append_line("  ○ Game ended — switching back to system-only boost", "mute")
        if restored:
            self._log.append_line(f"  + Restored priority for {restored} processes", "ok")
        self._mc_game.set_value("0 PIDs", _t("boost_no_game", "no game"), 0, C['text3'])
        self._mc_game.set_lit(False)
        self._mc_bg.set_value("0 procs", "standby", 0, C['text3'])
        self._mc_bg.set_lit(False)

    # ── Metrics / GPU ──────────────────────────────────────────
    def _on_metric(self, key, value):
        if key == "ram_freed_mb":
            mb = int(value)
            if mb > 0:
                self._mc_ram.set_value(f"{mb} MB", f"+{mb} MB", min(100, mb / 5), C['cyan'])
            else:
                self._mc_ram.set_value("compact", "✓ done", 40, C['cyan'])
            self._mc_ram.set_lit(True)
        elif key == "bg_count":
            n = int(value)
            bg_lbl = "BELOW_NORMAL" if IS_WINDOWS else "nice +5"
            self._mc_bg.set_value(f"{n} procs", bg_lbl, min(100, n * 4), C['yellow'])
            self._mc_bg.set_lit(True)
        elif key == "game_pids":
            pids = value
            if pids:
                self._mc_game.set_value(f"{len(pids)} PIDs", "", 80, C['purple'])
                self._mc_game.set_lit(True)

    def _on_gpu(self, pct: int):
        if pct < 0:
            return
        if self._gpu_baseline < 0:
            self._gpu_baseline = pct
            if self._gpu_thread is not None and hasattr(self._gpu_thread, "using_cpu_proxy"):
                self._using_cpu_proxy = bool(self._gpu_thread.using_cpu_proxy)
            else:
                has_gpu_busy_pct = any(
                    True for _ in Path("/sys/class/drm").glob("card*/device/gpu_busy_percent")
                ) if IS_LINUX else False
                has_rc6 = any(
                    True for _ in Path("/sys/class/drm").glob("card*/gt/gt0/rc6_residency_ms")
                ) if IS_LINUX else False
                self._using_cpu_proxy = not (has_gpu_busy_pct or has_rc6 or shutil.which("nvidia-smi"))

        delta = pct - self._gpu_baseline
        col   = C['green'] if delta >= 0 else C['red']
        dstr  = f"+{delta}%" if delta >= 0 else f"{delta}%"
        self._mc_gpu.set_value(f"{pct}%", dstr, pct, col)
        if getattr(self, "_using_cpu_proxy", False):
            self._mc_gpu.set_label(_t("boost_mc_cpu_proxy", "CPU LOAD"))
        else:
            self._mc_gpu.set_label(_t("boost_mc_gpu", "GPU BUSY"))
        self._mc_gpu.set_lit(True)

    # ══════════════════════════════════════════════════════════
    # BOOST LOGIC
    # ══════════════════════════════════════════════════════════
    def _boost_logic(self, log, phase_sig, metric_sig, opts: dict = None) -> dict:
        if opts is None:
            opts = {"ram": True, "gov": True, "prio": True, "swap": True, "hypr": True}
        prior_unrestored = _merge_unrestored_state(_load_boost_state_disk(), getattr(self, "_saved_state", None))
        saved = dict(prior_unrestored)

        # ── PHASE 0: SCAN ──────────────────────────────────────
        phase_sig.emit(0)
        log("│", "mute")
        log("├─ [1/3] SCAN ─────────────────────────────", "head")

        gpu_name = "unknown"
        if IS_LINUX:
            for pn in Path("/sys/class/drm").glob("card*/device/product_name"):
                try:
                    gpu_name = pn.read_text().strip()[:45]
                    break
                except OSError:
                    pass
            if gpu_name == "unknown":
                try:
                    r = subprocess.run(["lspci"], capture_output=True, text=True, timeout=3)
                    for ln in r.stdout.splitlines():
                        if "VGA" in ln or "3D" in ln:
                            gpu_name = ln.split(":")[-1].strip()[:58]
                            break
                except (OSError, subprocess.TimeoutExpired):
                    pass
        elif IS_WINDOWS:
            try:
                r = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                    capture_output=True, text=True, timeout=3,
                    creationflags=0x08000000
                )
                name = r.stdout.strip().splitlines()[0].strip() if r.stdout.strip() else ""
                if r.returncode == 0 and name:
                    gpu_name = name[:45]
            except Exception:
                pass
            if gpu_name == "unknown":
                try:
                    r = subprocess.run(
                        ["powershell", "-NoProfile", "-Command",
                         "(Get-CimInstance Win32_VideoController | "
                         "Where-Object { $_.CurrentHorizontalResolution -ne $null } | "
                         "Select-Object -First 1 -ExpandProperty Name)"],
                        capture_output=True, text=True, timeout=3,
                        creationflags=0x08000000
                    )
                    name = r.stdout.strip()
                    if r.returncode == 0 and name:
                        gpu_name = name[:45]
                except Exception:
                    pass
        self._gpu_name = gpu_name
        log(f"│  ◈ GPU: {gpu_name}", "mute")

        game_pids = []
        _running_games = []
        try:
            from core.booster import _detect_running_games
            _running_games, _ = _detect_running_games()
            if HAS_PSUTIL:
                import psutil as _psu
                _seen = set()
                for game_pid, _ in _running_games:
                    if game_pid in _seen:
                        continue
                    _seen.add(game_pid)
                    game_pids.append(game_pid)
                    try:
                        for child in _psu.Process(game_pid).children(recursive=True):
                            if child.pid not in _seen:
                                _seen.add(child.pid)
                                game_pids.append(child.pid)
                    except (_psu.NoSuchProcess, _psu.AccessDenied):
                        pass
        except Exception as e:
            log(f"│  ~ detect: {e}", "warn")

        if game_pids:
            log(f"│  ◈ game: {len(game_pids)} PIDs detected", "ok")
            metric_sig.emit("game_pids", game_pids)
        else:
            log("│  ◈ no active game — watcher will boost on launch", "mute")

        # ── PHASE 1: APPLY ─────────────────────────────────────
        phase_sig.emit(1)
        log("│", "mute")
        log("├─ [2/3] APPLY ────────────────────────────", "head")

        def _tlog(msg: str, lvl: str = "text"):
            if msg.startswith("│"):
                log(msg, lvl)
            elif msg.startswith("  "):
                log("│" + msg, lvl)
            else:
                log("│  " + msg, lvl)

        if opts.get("ram", True):
            try:
                from core.booster import free_ram
                res = free_ram(_tlog)
                mb  = getattr(res, "mb_freed", 0) or 0
                metric_sig.emit("ram_freed_mb", mb if mb > 10 else -1)
            except Exception as e:
                log(f"│  ~ free_ram: {e}", "warn")

        if opts.get("gov", True):
            try:
                from core.booster import (
                    _enable_kernel_performance, _set_io_scheduler,
                    _inhibit_screensaver, _set_gpu_performance,
                    _kill_runaway_widgets, _timer_resolution_set,
                    _disable_gamedvr, _bypass_compositor_on,
                )
                new_pwr = _enable_kernel_performance(_tlog)
                if not saved.get("power"):
                    saved["power"] = new_pwr
                if IS_LINUX:
                    _set_io_scheduler(_tlog, saved)
                    _inhibit_screensaver(_tlog, saved)
                    _kill_runaway_widgets(_tlog)
                    if not game_pids:
                        _set_gpu_performance(_tlog, saved)
                    if not os.environ.get("WAYLAND_DISPLAY"):
                        _bypass_compositor_on(_tlog, saved)
                elif IS_WINDOWS:
                    t_set = _timer_resolution_set(_tlog)
                    saved["timer_set"] = bool(saved.get("timer_set") or t_set)
                    dvr_orig = _disable_gamedvr(_tlog)
                    if saved.get("gamedvr_orig") is None:
                        saved["gamedvr_orig"] = dvr_orig
                    _bypass_compositor_on(_tlog, saved)
            except Exception as e:
                log(f"│  ~ governor/system tune: {e}", "warn")

        if IS_LINUX:
            try:
                legacy_env = Path.home() / ".config/environment.d/cyber-boost.conf"
                legacy_env.unlink(missing_ok=True)
            except OSError:
                pass
            env_vars = {
                "mesa_glthread":               "true",
                "__GL_THREADED_OPTIMIZATIONS": "1",
            }
            env_orig = {}
            for k, v in env_vars.items():
                env_orig[k] = os.environ.get(k)
                os.environ[k] = v
            saved["env_orig"] = env_orig
            log("│  + GL threaded optimizations enabled (session-scoped)", "ok")

        if IS_LINUX and opts.get("hypr", True) and shutil.which("hyprctl"):
            try:
                if "hyprland_vfr_orig" not in saved:
                    saved["hyprland_vfr_orig"] = _hyprctl_get_bool("misc:vfr", "true")
                if "hyprland_scanout_orig" not in saved:
                    saved["hyprland_scanout_orig"] = _hyprctl_get_bool("misc:no_direct_scanout", "true")
                subprocess.run(["hyprctl", "keyword", "misc:vfr", "false"],
                               capture_output=True, timeout=3)
                subprocess.run(["hyprctl", "keyword", "misc:no_direct_scanout", "false"],
                               capture_output=True, timeout=3)
                saved["hyprland_vfr"] = True
                log(
                    f"│  + Hyprland: VFR=false, no_direct_scanout=false "
                    f"(saved orig: vfr={saved['hyprland_vfr_orig']}, scanout={saved['hyprland_scanout_orig']})",
                    "ok"
                )
            except (OSError, subprocess.TimeoutExpired):
                pass

        if IS_LINUX and opts.get("swap", True):
            sw = Path("/proc/sys/vm/swappiness")
            real_orig = None
            try:
                real_orig = sw.read_text().strip()
            except (PermissionError, OSError):
                pass

            try:
                sw.write_text("1")
                if not saved.get("swappiness_orig"):
                    saved["swappiness_orig"] = real_orig if real_orig is not None else "60"
                log("│  + vm.swappiness → 1 (game pages stay in RAM)", "ok")
            except (PermissionError, OSError):
                try:
                    from core import privileged as _PRIV
                    r = _PRIV.run_helper("swappiness", timeout=5, use_pkexec=False)
                    if r.ok:
                        if not saved.get("swappiness_orig"):
                            saved["swappiness_orig"] = real_orig if real_orig is not None else "60"
                        log("│  + vm.swappiness → 10 (via helper)", "ok")
                except Exception:
                    pass

        bg_count = 0
        if opts.get("prio", True) and game_pids and HAS_PSUTIL:
            try:
                import psutil as _psu
                uid = os.getuid() if IS_LINUX else -1
                skip_set = _get_boost_skip_set()
                game_pid_set = set(game_pids)

                for pid in game_pids[:8]:
                    try:
                        p = _psu.Process(pid)
                        _apply_game_nice(p, pid, saved)
                    except (_psu.NoSuchProcess, _psu.AccessDenied, ValueError, OSError):
                        pass

                if IS_LINUX:
                    try:
                        from core.booster import _pin_game_to_perf_cores
                        _pin_game_to_perf_cores(game_pids[:8], log, saved)
                    except Exception:
                        pass

                for p in _psu.process_iter(["pid", "name"]):
                    try:
                        if IS_LINUX and uid >= 0:
                            try:
                                if p.uids().real != uid:
                                    continue
                            except (_psu.NoSuchProcess, _psu.AccessDenied):
                                continue
                        if _should_skip_bg_proc(p, skip_set, game_pid_set):
                            continue
                        o = p.nice()
                        if IS_WINDOWS:
                            if o == _psu.NORMAL_PRIORITY_CLASS:
                                p.nice(_psu.BELOW_NORMAL_PRIORITY_CLASS)
                                saved.setdefault("bg_nice", {})[p.pid] = _record_proc_nice_entry(p, o)
                                bg_count += 1
                        else:
                            if o < 5:
                                from core.booster import _can_restore_linux_nice
                                if not _can_restore_linux_nice(o):
                                    continue
                                p.nice(5)
                                saved.setdefault("bg_nice", {})[p.pid] = _record_proc_nice_entry(p, o)
                                bg_count += 1
                    except (PermissionError, _psu.NoSuchProcess, _psu.AccessDenied, ValueError, OSError):
                        pass

                bg_lbl = "BELOW_NORMAL" if IS_WINDOWS else "nice(+5)"
                log(f"│  + {bg_count} background → {bg_lbl}", "ok")
                metric_sig.emit("bg_count", bg_count)
            except ImportError:
                pass
        elif opts.get("prio", True):
            log("│  i no game yet — background priority left untouched until launch", "mute")

        saved["game_pids"] = game_pids
        _save_boost_state_disk(saved)
        log("│", "mute")
        log("└─ BOOST ACTIVE ───────────────────────────", "head")

        # ── PHASE 2: MONITOR ───────────────────────────────────
        phase_sig.emit(2)
        return saved
