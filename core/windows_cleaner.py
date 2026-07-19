"""
CyberClean v2.4 — Windows Cleaner
════════════════════════════════════════════════════════════════

WHAT CHANGED vs v2.3:

NEW targets:
  win_winsxs        — WinSxS component store analysis + DISM /StartComponentCleanup
                      (does NOT touch live components; DISM only removes superseded ones)
  win_font_cache    — FontCache*.dat / FNTCACHE.DAT (auto-rebuilds on next boot)
  win_shader_cache  — DirectX / GPU shader cache per-user (safe; rebuilt on next launch)
  vivaldi_cache     — Vivaldi browser cache
  coccoc_cache      — Cốc Cốc browser cache (common in Vietnam / SE Asia)

IMPROVED:
  _win_temp         — also scans %SYSTEMROOT%\\Temp separately with same guards
  _browser_cache    — handles multi-profile Chrome/Edge/Brave more robustly:
                      iterates all profile dirs (Profile 1, Profile 2…) not just Default
  _win_updates      — guards against partial stop failure: if 'net stop wuauserv' fails
                      (e.g. not admin), skip delete instead of crashing

FIX (v2.4):
  _win_winsxs       — never deletes anything directly; only calls DISM which has its own
                      safety logic. Estimate = Dism /Online /Cleanup-Image /AnalyzeComponentStore
                      Parse "Component Store Size (Estimated Reduction)" line.
  _win_font_cache   — stops FontCache service before delete, restarts after.
                      Without this, files are locked and delete fails silently.
  All browser paths — extended to Profile 1 / Profile 2 etc. via glob instead of
                      hardcoded /Default only.
"""

import os, re, shutil, subprocess, time, stat as _stat
from pathlib import Path
from .base_cleaner import BaseCleaner, CleanTarget, CleanResult

_NO_WIN = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0


def run_win(cmd, timeout=30):
    """
    Run a shell command, return (stdout_stripped, returncode).
    Guards:
    - encoding='utf-8' errors='replace' — prevents crash on CJK/Vietnamese locale output
    - TimeoutExpired → return ('timeout', 1) instead of raising
    - All other exceptions caught and returned as error string
    """
    try:
        r = subprocess.run(
            cmd, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, creationflags=_NO_WIN,
            encoding='utf-8', errors='replace',
        )
        return r.stdout.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return f'timeout after {timeout}s', 1
    except Exception as e:
        return str(e), 1


def is_admin():
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _is_locked_win(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        with open(path, 'rb+'):
            return False
    except (PermissionError, OSError):
        return True


def _safe_path_str(path) -> str:
    """BUG FIX #3: Convert path sang string an toàn với Unicode.
    Username Tiếng Việt (Nguyễn, Trần...) hoặc Chinese characters
    gây UnicodeEncodeError trên một số Windows locale (cp1252).
    Dùng os.fspath() + errors='replace' để tránh crash.
    """
    try:
        return os.fspath(path)
    except Exception:
        try:
            return str(path).encode('utf-8', errors='replace').decode('utf-8')
        except Exception:
            return repr(path)


def _expand_env_path(env_var: str, fallback: str) -> Path:
    """Expand env var an toàn với Unicode path.
    os.environ.get() đôi khi trả về bytes thay vì str trên Windows locale lỗi.
    """
    try:
        val = os.environ.get(env_var, fallback)
        if isinstance(val, bytes):
            val = val.decode('utf-8', errors='replace')
        return Path(val)
    except Exception:
        return Path(fallback)


def _dir_size_safe(path, _limit=500_000_000_000) -> int:
    """
    Walk tree without following NTFS junctions/symlinks.
    FAST PATH: uses os.scandir() instead of os.walk() — ~3x faster on large dirs
    because scandir caches inode info, avoiding a second stat() per entry.
    Also applies a 500 GB ceiling to prevent hanging on huge dirs.
    """
    total = 0
    try:
        stack = [str(path)]
        while stack:
            current = stack.pop()
            try:
                with os.scandir(current) as it:
                    for entry in it:
                        try:
                            if entry.is_symlink():
                                continue
                            if entry.is_file(follow_symlinks=False):
                                total += entry.stat(follow_symlinks=False).st_size
                                if total > _limit:
                                    return total
                            elif entry.is_dir(follow_symlinks=False):
                                stack.append(entry.path)
                        except OSError:
                            pass
            except OSError:
                pass
    except OSError:
        pass
    return total


def _real_freed(size_before: int, path) -> int:
    size_after = _dir_size_safe(path) if Path(path).exists() else 0
    return max(0, size_before - size_after)


def _chromium_profile_cache_dirs(base: Path, cache_subfolders: list) -> list:
    """
    Return cache dirs for ALL Chromium profiles (Default + Profile N).
    Old code only checked /Default — misses users with multiple profiles.
    """
    dirs = []
    if not base.exists():
        return dirs
    for profile in base.iterdir():
        if not profile.is_dir():
            continue
        # Chromium profile dirs: 'Default', 'Profile 1', 'Profile 2', 'System Profile'
        name = profile.name
        if name == 'Default' or re.match(r'^Profile \d+$', name):
            for sub in cache_subfolders:
                p = profile / sub
                if p.exists():
                    dirs.append(p)
    return dirs


class WindowsCleaner(BaseCleaner):

    def get_targets(self):
        return [
            CleanTarget('win_temp',         'Windows Temp',
                '%TEMP% and C:\\Windows\\Temp — files older than 24h',       'safe'),
            CleanTarget('win_prefetch',     'Prefetch Cache',
                'App launch prefetch (.pf files older than 7 days)',          'safe',    needs_root=True),
            CleanTarget('win_recycle',      'Recycle Bin',
                'All items in Recycle Bin',                                   'caution'),
            CleanTarget('win_updates',      'Windows Update Cache',
                'Downloaded update files in SoftwareDistribution\\Download',  'safe',    needs_root=True),
            CleanTarget('win_delivery',     'Delivery Optimization',
                'Windows Update P2P cache in DeliveryOptimization',           'safe',    needs_root=True),
            CleanTarget('win_thumbcache',   'Thumbnail Cache',
                'Explorer thumbcache_*.db — auto-rebuilds',                   'safe'),
            CleanTarget('win_font_cache',   'Font Cache',
                'FontCache*.dat — auto-rebuilds on next boot',                'safe',    needs_root=True),
            CleanTarget('win_shader_cache', 'GPU Shader Cache',
                'DirectX/GPU per-user shader cache — rebuilt on next launch', 'safe'),
            CleanTarget('win_dns',          'DNS Cache',
                'Flush Windows DNS resolver cache',                           'safe',    needs_root=True),
            CleanTarget('win_winsxs',       'WinSxS Cleanup',
                'DISM removes superseded components only — safe',             'caution', needs_root=True),
            CleanTarget('win_eventlog',     'Event Logs',
                'Clear all Windows Event Viewer logs (wevtutil)',             'caution', needs_root=True),
            CleanTarget('win_error_reports','Windows Error Reports',
                'App crash dumps and WER report files',                       'safe'),
            CleanTarget('win_crash_dumps',  'Crash Dumps (Minidump)',
                'C:\\Windows\\Minidump + %LOCALAPPDATA%\\CrashDumps',         'safe',
                needs_root=True),
            CleanTarget('chrome_cache',     'Chrome Cache',
                'All Chrome profiles — cache auto-rebuilds',                  'safe'),
            CleanTarget('firefox_cache',    'Firefox Cache',
                'All Firefox profiles — cache auto-rebuilds',                 'safe'),
            CleanTarget('edge_cache',       'Edge Cache',
                'All Edge profiles — cache auto-rebuilds',                    'safe'),
            CleanTarget('brave_cache',      'Brave Cache',
                'All Brave profiles — cache auto-rebuilds',                   'safe'),
            CleanTarget('opera_cache',      'Opera / Opera GX Cache',
                'Opera and Opera GX caches — auto-rebuild',                   'safe'),
            CleanTarget('vivaldi_cache',    'Vivaldi Cache',
                'Vivaldi browser cache — auto-rebuilds',                      'safe'),
            CleanTarget('coccoc_cache',     'Cốc Cốc Cache',
                'Cốc Cốc browser cache — auto-rebuilds',                      'safe'),
        ]

    def estimate(self, target_id):
        return self._run_target(target_id, dry=True).freed_bytes

    def clean(self, target_id, dry=True):
        return self._run_target(target_id, dry=dry)

    def _run_target(self, tid, dry):
        r = CleanResult(target_id=tid)
        try:
            fn = {
                'win_temp':          self._win_temp,
                'win_prefetch':      self._win_prefetch,
                'win_recycle':       self._win_recycle,
                'win_updates':       self._win_updates,
                'win_delivery':      self._win_delivery,
                'win_thumbcache':    self._win_thumbcache,
                'win_font_cache':    self._win_font_cache,
                'win_shader_cache':  self._win_shader_cache,
                'win_dns':           self._win_dns,
                'win_winsxs':        self._win_winsxs,
                'win_eventlog':      self._win_eventlog,
                'win_error_reports': self._win_error_reports,
                'win_crash_dumps':   self._win_crash_dumps,
                'chrome_cache':      lambda d: self._browser_cache('chrome_cache',  d),
                'firefox_cache':     lambda d: self._browser_cache('firefox_cache', d),
                'edge_cache':        lambda d: self._browser_cache('edge_cache',    d),
                'brave_cache':       lambda d: self._browser_cache('brave_cache',   d),
                'opera_cache':       lambda d: self._browser_cache('opera_cache',   d),
                'vivaldi_cache':     lambda d: self._browser_cache('vivaldi_cache', d),
                'coccoc_cache':      lambda d: self._browser_cache('coccoc_cache',  d),
            }.get(tid)
            if fn:
                r = fn(dry)
        except Exception as e:
            r.error = str(e)
        return r

    # ── Temp ──────────────────────────────────────────────────
    def _win_temp(self, dry):
        r = CleanResult('win_temp')
        dirs = list({
            _expand_env_path('TEMP', 'C:/Windows/Temp'),
            _expand_env_path('TMP',  'C:/Windows/Temp'),
            Path('C:/Windows/Temp'),
            Path(os.environ.get('SystemRoot', 'C:\\Windows')) / 'Temp',
        })
        now = time.time()

        SKIP_DIR_PREFIXES = (
            'scoped_dir', 'chrome_', 'msedge_', 'discord',
            'vscode', 'electron', 'squirrel',
            'tmp', 'clr', 'msi', 'msp',
        )
        SKIP_EXTENSIONS = {'.lnk', '.lock', '.msi'}

        for d in dirs:
            if not d.exists():
                continue
            safe_path = str(d).lower().replace(os.sep, '/')
            if safe_path.rstrip('/') in ('c:', 'c:/', 'c:/windows', 'c:/users'):
                continue

            size_before = _dir_size_safe(d)
            if not dry:
                for item in list(d.iterdir()):
                    try:
                        mtime = item.stat().st_mtime
                        age_secs = now - mtime
                        if age_secs < 86400:
                            continue
                        # FIX: khi ổ C gần đầy (< 2GB free), Discord/Chrome
                        # đang extract update vào %TEMP%. Chỉ xóa file > 2 ngày.
                        try:
                            import shutil as _sh
                            _free_bytes = _sh.disk_usage(str(d.anchor)).free
                            if _free_bytes < 2 * 1024**3 and age_secs < 172800:
                                continue  # disk critical: giữ file < 2 ngày
                        except OSError:
                            pass
                        if item.is_dir() and item.name.lower().startswith(SKIP_DIR_PREFIXES):
                            continue
                        if item.is_file() and item.suffix.lower() in SKIP_EXTENSIONS:
                            continue
                        if item.is_file() and _is_locked_win(item):
                            continue
                        sz = _dir_size_safe(item) if item.is_dir() else item.stat().st_size
                        if item.is_dir():
                            shutil.rmtree(item, ignore_errors=True)
                        else:
                            item.unlink(missing_ok=True)
                        r.freed_bytes   += sz
                        r.files_removed += 1
                    except (PermissionError, OSError):
                        pass
            else:
                for item in d.iterdir():
                    try:
                        if (now - item.stat().st_mtime) < 86400:
                            continue
                        if item.is_dir() and item.name.lower().startswith(SKIP_DIR_PREFIXES):
                            continue
                        if item.is_file() and item.suffix.lower() in SKIP_EXTENSIONS:
                            continue
                        r.freed_bytes += _dir_size_safe(item) if item.is_dir() else item.stat().st_size
                    except (OSError, PermissionError):
                        pass
        return r

    # ── Prefetch ──────────────────────────────────────────────
    def _win_prefetch(self, dry):
        r = CleanResult('win_prefetch')
        pf = Path('C:/Windows/Prefetch')
        if not pf.exists():
            return r
        now = time.time()
        old_files = [f for f in pf.glob('*.pf') if (now - f.stat().st_mtime) > 604800]
        r.freed_bytes   = sum(f.stat().st_size for f in old_files)
        r.files_removed = len(old_files)
        if not dry and is_admin():
            deleted = 0
            for f in old_files:
                try:
                    sz = f.stat().st_size
                    f.unlink()
                    deleted += sz
                except (PermissionError, OSError):
                    pass
            r.freed_bytes   = deleted
            r.files_removed = len([f for f in old_files if not f.exists()])
        elif not dry and not is_admin():
            r.error = 'Needs admin — relaunch as Administrator'
        return r

    # ── Recycle Bin ───────────────────────────────────────────
    def _win_recycle(self, dry):
        r = CleanResult('win_recycle')
        out, _ = run_win(
            'PowerShell -NoProfile -Command "'
            '(New-Object -ComObject Shell.Application).Namespace(10).Items()'
            ' | Where-Object {$_.Size -ne $null}'
            ' | Measure-Object -Property Size -Sum -ErrorAction SilentlyContinue'
            ' | Select-Object -ExpandProperty Sum" 2>$null'
        )
        try:
            val = out.strip() if out else ''
            r.freed_bytes = int(float(val)) if val and val.lower() not in ('', 'null', 'none') else 0
        except (ValueError, TypeError):
            r.freed_bytes = 0
        if not dry:
            run_win('PowerShell -NoProfile -Command "Clear-RecycleBin -Force -EA SilentlyContinue" 2>$null')
        return r

    # ── Windows Update Cache ──────────────────────────────────
    def _win_updates(self, dry):
        r = CleanResult('win_updates')
        sd = Path('C:/Windows/SoftwareDistribution/Download')
        if not sd.exists():
            return r
        size_before = _dir_size_safe(sd)
        r.freed_bytes = size_before
        if not dry and is_admin():
            # Use 'sc stop' — more reliable than 'net stop' on managed/office machines.
            # Also stop BITS (Background Intelligent Transfer) which holds file locks.
            # Try both; proceed if at least wuauserv stopped (return code 0 or 1062=already stopped).
            _ALREADY_STOPPED = ('1062', '1060', 'already')

            def _stop_svc(name) -> bool:
                out, code = run_win(f'sc stop {name}', timeout=20)
                if code == 0:
                    return True
                # 1062 = service not running — that's fine for our purposes
                return any(s in out for s in _ALREADY_STOPPED)

            def _start_svc(name):
                run_win(f'sc start {name}', timeout=20)

            stopped_wu   = _stop_svc('wuauserv')
            _stop_svc('bits')
            _stop_svc('dosvc')

            if stopped_wu:
                try:
                    for item in list(sd.iterdir()):
                        try:
                            sz = _dir_size_safe(item) if item.is_dir() else item.stat().st_size
                            r.rollback.append({
                                'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                'type': 'win_updates', 'path': str(item),
                                'size': sz, 'note': 're-downloads when needed',
                            })
                            if item.is_dir():
                                shutil.rmtree(item, ignore_errors=True)
                            else:
                                item.unlink(missing_ok=True)
                        except (PermissionError, OSError):
                            pass
                finally:
                    _start_svc('bits')
                    _start_svc('wuauserv')
                r.freed_bytes = _real_freed(size_before, sd)
            else:
                _start_svc('bits')
                _start_svc('wuauserv')
                r.error = (
                    'Could not stop Windows Update service — '
                    'try running CyberClean as Administrator'
                )
        elif not dry and not is_admin():
            r.error = 'Needs admin'
        return r

    # ── Delivery Optimization ─────────────────────────────────
    def _win_delivery(self, dry):
        r = CleanResult('win_delivery')
        do_path = Path('C:/Windows/SoftwareDistribution/DeliveryOptimization')
        if not do_path.exists():
            return r
        size_before = _dir_size_safe(do_path)
        r.freed_bytes = size_before
        if not dry and is_admin():
            # FIX v2.5: wrap in try/finally so dosvc ALWAYS restarts even if
            # shutil.rmtree raises unexpectedly (mirrors the _win_updates pattern).
            run_win('net stop dosvc /y', timeout=10)
            try:
                shutil.rmtree(do_path, ignore_errors=True)
            finally:
                run_win('net start dosvc', timeout=10)
            r.freed_bytes = _real_freed(size_before, do_path)
        elif not dry and not is_admin():
            r.error = 'Needs admin'
        return r

    # ── Thumbnail Cache ───────────────────────────────────────
    def _win_thumbcache(self, dry):
        r = CleanResult('win_thumbcache')
        _local = os.environ.get('LOCALAPPDATA', '')
        if not _local:
            r.error = 'LOCALAPPDATA not set — skipping'
            return r
        thumb_dir = Path(_local) / 'Microsoft/Windows/Explorer'
        if not thumb_dir.exists():
            return r
        files = list(thumb_dir.glob('thumbcache_*.db'))
        r.freed_bytes   = sum(f.stat().st_size for f in files if f.exists())
        r.files_removed = len(files)
        if not dry:
            # FIX v2.5: NEVER kill explorer.exe — doing so causes the black screen
            # flash and taskbar/desktop disappearing that users reported.
            # Instead: try direct delete first; if a file is locked, use
            # MoveFileExW(MOVEFILE_DELAY_UNTIL_REBOOT) to schedule it for removal
            # on the next Windows boot. This is exactly what Windows Disk Cleanup does.
            import ctypes
            _kernel32 = ctypes.windll.kernel32
            MOVEFILE_DELAY_UNTIL_REBOOT = 0x4

            deleted = 0
            locked  = 0
            for f in files:
                try:
                    sz = f.stat().st_size
                    try:
                        f.unlink()
                        deleted += sz
                        r.rollback.append({
                            'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                            'type': 'thumbcache', 'path': str(f),
                            'size': sz, 'note': 'auto-rebuilds',
                        })
                    except PermissionError:
                        # File is locked by Explorer — schedule for next boot
                        ok = _kernel32.MoveFileExW(str(f), None, MOVEFILE_DELAY_UNTIL_REBOOT)
                        if ok:
                            locked += 1  # will be cleaned on next boot
                            r.rollback.append({
                                'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                'type': 'thumbcache', 'path': str(f),
                                'size': sz, 'note': 'scheduled for deletion on next boot',
                            })
                        # Either way, count in estimate (will be gone after reboot)
                        deleted += sz
                except OSError:
                    pass

            r.freed_bytes   = deleted
            r.files_removed = len([f for f in files if not f.exists()])
            if locked > 0:
                r.error = (
                    f'{locked} file(s) scheduled for deletion on next Windows boot '
                    '(still locked by Explorer — no action needed, fully automatic).'
                )
        return r

    # ── Font Cache (NEW) ──────────────────────────────────────
    def _win_font_cache(self, dry):
        r = CleanResult('win_font_cache')
        sysroot = os.environ.get('SystemRoot', 'C:\\Windows')
        targets = [
            Path(sysroot) / 'System32' / 'FNTCACHE.DAT',
            *Path(sysroot).glob('ServiceProfiles/LocalService/AppData/Local/FontCache/FontCache*.dat'),
            *Path(sysroot).glob('ServiceProfiles/LocalService/AppData/Local/FontCache-System/FontCache*.dat'),
        ]
        existing = [f for f in targets if f.exists()]
        size_before = sum(f.stat().st_size for f in existing)
        r.freed_bytes   = size_before
        r.files_removed = len(existing)
        if not dry and is_admin():
            # FIX v2.5: Two-phase strategy — avoids the font rendering glitch caused
            # by stopping the service while the UI is live.
            #
            # Phase 1: Try direct delete first (works if service already released file).
            # Phase 2: For still-locked files, rename to .old — Windows allows renaming
            #          open files (unlike deletion). On next boot, FontCache rebuilds
            #          fresh and the .old files are left orphaned (and we clean those
            #          in Phase 3 on the next run).
            # Phase 3: Schedule any remaining .old files for boot-time deletion via
            #          MoveFileExW(MOVEFILE_DELAY_UNTIL_REBOOT).
            import ctypes
            _kernel32 = ctypes.windll.kernel32
            MOVEFILE_DELAY_UNTIL_REBOOT = 0x4

            deleted = 0
            for f in existing:
                try:
                    sz = f.stat().st_size
                    try:
                        f.unlink()   # Phase 1: direct delete
                        deleted += sz
                        r.rollback.append({
                            'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                            'type': 'font_cache', 'path': str(f),
                            'size': sz, 'note': 'auto-rebuilds on next boot',
                        })
                    except (PermissionError, OSError):
                        # Phase 2: rename to .old (permitted even on locked files)
                        old_path = Path(str(f) + '.old')
                        try:
                            f.rename(old_path)
                            # Phase 3: schedule the .old for deletion at next boot
                            _kernel32.MoveFileExW(str(old_path), None, MOVEFILE_DELAY_UNTIL_REBOOT)
                            deleted += sz
                            r.rollback.append({
                                'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                'type': 'font_cache', 'path': str(f),
                                'size': sz, 'note': 'renamed to .old; auto-removed on next boot',
                            })
                        except OSError:
                            pass
                except OSError:
                    pass
            # Also clean up any leftover .old files from a previous run
            for stale in list(existing[0].parent.glob('*.old')) if existing else []:
                try:
                    stale.unlink(missing_ok=True)
                except OSError:
                    pass
            r.freed_bytes   = deleted
            r.files_removed = len([f for f in existing if not f.exists()])
        elif not dry and not is_admin():
            r.error = 'Needs admin'
        return r

    # ── GPU Shader Cache (NEW) ────────────────────────────────
    def _win_shader_cache(self, dry):
        r = CleanResult('win_shader_cache')
        _local = os.environ.get('LOCALAPPDATA', '')
        if not _local:
            return r
        local = Path(_local)
        shader_dirs = [
            local / 'D3DSCache',
            local / 'NVIDIA/DXCache',
            local / 'NVIDIA/GLCache',
            local / 'AMD/DXCache',
            local / 'Intel/ShaderCache',
            # Vulkan pipeline cache (common location)
            local / 'Temp/NVIDIA Corporation/Turing',
        ]
        existing = [d for d in shader_dirs if d.exists()]
        size_before = sum(_dir_size_safe(d) for d in existing)
        r.freed_bytes = size_before
        if not dry:
            total_freed = 0
            for d in existing:
                before = _dir_size_safe(d)
                shutil.rmtree(d, ignore_errors=True)
                total_freed += _real_freed(before, d)
                r.rollback.append({
                    'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                    'type': 'shader_cache', 'path': str(d),
                    'size': before,
                    'note': 'auto-rebuilds on next game launch (first launch slower)',
                })
            r.freed_bytes = total_freed
        return r

    # ── DNS ───────────────────────────────────────────────────
    def _win_dns(self, dry):
        r = CleanResult('win_dns')
        r.files_removed = 1
        if not dry:
            _, code = run_win('ipconfig /flushdns')
            if code != 0:
                r.error = 'DNS flush failed'
        return r

    # ── WinSxS (NEW) ──────────────────────────────────────────
    def _win_winsxs(self, dry):
        """
        Estimate via DISM /AnalyzeComponentStore (dry) or
        run DISM /StartComponentCleanup (real).
        DISM only removes superseded components — never touches active ones.
        This is exactly what Windows Update Cleanup in Disk Cleanup does.
        """
        r = CleanResult('win_winsxs')
        if not is_admin():
            r.error = 'Needs admin'
            return r

        if dry:
            # Estimate: parse DISM analyze output for estimated reduction
            out, code = run_win(
                'Dism /Online /Cleanup-Image /AnalyzeComponentStore 2>nul',
                timeout=120,
            )
            if code != 0:
                r.error = 'DISM analysis failed — may not be supported on this edition'
                return r
            # Look for "Component Store Size (Estimated Reduction)" line
            for line in out.splitlines():
                if 'Estimated Reduction' in line or 'ReducedSize' in line:
                    m = re.search(r'([\d,]+)\s*MB', line)
                    if m:
                        try:
                            r.freed_bytes = int(m.group(1).replace(',', '')) * 1024 * 1024
                        except (ValueError, TypeError):
                            pass
                    break
        else:
            # FIX: removed /ResetBase — it deletes all update rollback backups,
            # which breaks Windows Update on managed/office machines (WSUS/SCCM).
            # /StartComponentCleanup alone is safe and still reclaims significant space.
            out, code = run_win(
                'Dism /Online /Cleanup-Image /StartComponentCleanup 2>nul',
                timeout=600,   # can take several minutes on first run
            )
            if code not in (0, 3010):
                # 3010 = success, restart required
                r.error = f'DISM cleanup failed (code {code})'
            else:
                r.freed_bytes   = 0
                r.files_removed = 1
                # FIX #1: Check pending reboot BEFORE returning.
                # DISM sometimes leaves pending ops that need a proper restart.
                # If user hard-shuts the PC → Windows detects incomplete component
                # store → triggers Startup Repair on next boot.
                # We warn them explicitly so they know to Restart (not Shutdown).
                _pending = False
                try:
                    import winreg as _wr
                    for _rp_key in (
                        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing",
                        r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired",
                        r"SYSTEM\CurrentControlSet\Control\Session Manager",
                    ):
                        try:
                            _k = _wr.OpenKey(_wr.HKEY_LOCAL_MACHINE, _rp_key, 0, _wr.KEY_READ)
                            try:
                                if 'Session Manager' in _rp_key:
                                    _v, _ = _wr.QueryValueEx(_k, 'PendingFileRenameOperations')
                                    if _v:
                                        _pending = True
                                else:
                                    _wr.QueryValueEx(_k, 'RebootPending')
                                    _pending = True
                            except OSError:
                                pass
                            _wr.CloseKey(_k)
                        except OSError:
                            pass
                        if _pending:
                            break
                except Exception:
                    pass
                if _pending or code == 3010:
                    r.error = (
                        '⚠ DISM xong — cần RESTART để hoàn tất. '
                        'Hãy RESTART đúng cách (Start → Restart), '
                        'KHÔNG tắt nguồn trực tiếp hoặc force shutdown. '
                        'Nếu tắt nguồn giữa chừng Windows sẽ chạy Startup Repair khi mở lại.'
                    )
        return r

    # ── Event Logs ────────────────────────────────────────────
    def _win_eventlog(self, dry):
        r = CleanResult('win_eventlog')
        evtx_dir = Path(os.environ.get('SystemRoot', 'C:\\Windows')) / 'System32/winevt/Logs'
        size_before = _dir_size_safe(evtx_dir) if evtx_dir.exists() else 0
        r.freed_bytes = size_before
        if not dry and is_admin():
            out, _ = run_win('wevtutil el', timeout=15)
            all_logs = [l.strip() for l in out.splitlines() if l.strip()]

            # FIX #4: KHÔNG xóa Security log và System log theo mặc định.
            # Trên máy văn phòng dùng SCCM/SIEM, xóa Security log vi phạm
            # compliance policy và trigger security alert cho IT department.
            # Chỉ xóa Application, Setup, và các log app thứ 3 an toàn.
            _SKIP_LOGS = {
                'Security',                          # audit/compliance log
                'System',                            # system events
                'Microsoft-Windows-Kernel-Power/Operational',  # power events
                'Microsoft-Windows-Kernel-Boot/Operational',
                'Microsoft-Windows-WindowsUpdateClient/Operational',
            }
            logs = [
                l for l in all_logs
                if not any(l == s or l.startswith(s + '/') for s in _SKIP_LOGS)
            ]

            cleared = 0
            for log in logs:
                try:
                    rc = subprocess.run(
                        ['wevtutil', 'cl', log],
                        capture_output=True, timeout=10,
                        creationflags=_NO_WIN,
                    ).returncode
                    if rc == 0:
                        cleared += 1
                except Exception:
                    pass
            r.freed_bytes   = _real_freed(size_before, evtx_dir)
            r.files_removed = cleared
        elif not dry and not is_admin():
            r.error = 'Needs admin'
        return r

    # ── Error Reports ─────────────────────────────────────────
    def _win_error_reports(self, dry):
        r = CleanResult('win_error_reports')
        _local = os.environ.get('LOCALAPPDATA', '')
        wer_dirs = []
        if _local:
            wer_dirs += [
                Path(_local) / 'Microsoft/Windows/WER/ReportArchive',
                Path(_local) / 'Microsoft/Windows/WER/ReportQueue',
            ]
        wer_dirs += [
            Path('C:/ProgramData/Microsoft/Windows/WER/ReportArchive'),
            Path('C:/ProgramData/Microsoft/Windows/WER/ReportQueue'),
        ]
        existing = [d for d in wer_dirs if d.exists()]
        size_before = sum(_dir_size_safe(d) for d in existing)
        r.freed_bytes = size_before
        if not dry:
            for d in existing:
                for item in list(d.iterdir()):
                    try:
                        sz = _dir_size_safe(item) if item.is_dir() else item.stat().st_size
                        r.rollback.append({
                            'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                            'type': 'win_error_reports', 'path': str(item),
                            'size': sz, 'note': 'crash dump — safe to remove',
                        })
                        if item.is_dir():
                            shutil.rmtree(item, ignore_errors=True)
                        else:
                            item.unlink(missing_ok=True)
                        r.files_removed += 1
                    except (PermissionError, OSError):
                        pass
            size_after  = sum(_dir_size_safe(d) for d in existing if d.exists())
            r.freed_bytes = max(0, size_before - size_after)
        return r

    # ── Browser Cache ─────────────────────────────────────────
    def _browser_cache(self, tid, dry):
        r = CleanResult(tid)
        _lc = os.environ.get('LOCALAPPDATA', '')
        _rm = os.environ.get('APPDATA', '')
        if not _lc and not _rm:
            return r

        # FIX: Bảo vệ Local Storage, IndexedDB, Databases của Discord/Slack/Teams.
        # Đây là nơi lưu cấu hình audio device, login token, server list.
        # Xóa nhầm → mất mic, mất đăng nhập, mất cài đặt.
        # Chỉ xóa GPUCache và Cache (rebuild được), KHÔNG xóa Local Storage.
        _COMMS_PROTECTED_DIRS = {
            'local storage', 'indexeddb', 'databases',
            'localstorage', 'session storage',
            'leveldb', 'protobuf', 'syncdata',
            'account manager', 'preferences',
        }

        def _is_safe_cache_dir(path_obj) -> bool:
            name_low = path_obj.name.lower()
            # Không xóa nếu tên thư mục là dữ liệu quan trọng
            if name_low in _COMMS_PROTECTED_DIRS:
                return False
            # Không xóa nếu là thư mục của comms apps (Discord, Slack, Teams)
            _COMMS_APPS = {'discord', 'slack', 'msteams', 'teams', 'zoom',
                           'telegram', 'signal', 'skype', 'zalo'}
            for part in path_obj.parts:
                if part.lower() in _COMMS_APPS:
                    return False
            return True
        local   = Path(_lc) if _lc else Path('C:/Users/Default/AppData/Local')
        roaming = Path(_rm) if _rm else Path('C:/Users/Default/AppData/Roaming')

        CHROMIUM_CACHE_SUBS = ['Cache', 'Code Cache', 'GPUCache']

        if tid == 'firefox_cache':
            cache_paths = []
            for base in [local / 'Mozilla/Firefox/Profiles',
                         roaming / 'Mozilla/Firefox/Profiles']:
                if base.exists():
                    for profile_dir in base.iterdir():
                        if profile_dir.is_dir():
                            c2 = profile_dir / 'cache2'
                            if c2.exists():
                                cache_paths.append(c2)

        elif tid == 'opera_cache':
            cache_paths = []
            for opera_dir in [
                roaming / 'Opera Software/Opera Stable',
                roaming / 'Opera Software/Opera GX Stable',
                local  / 'Opera Software/Opera Stable',
                local  / 'Opera Software/Opera GX Stable',
            ]:
                for sub in CHROMIUM_CACHE_SUBS:
                    p = opera_dir / sub
                    if p.exists():
                        cache_paths.append(p)

        else:
            # All Chromium-based browsers — iterate all profiles
            base_map = {
                'chrome_cache':  local / 'Google/Chrome/User Data',
                'edge_cache':    local / 'Microsoft/Edge/User Data',
                'brave_cache':   local / 'BraveSoftware/Brave-Browser/User Data',
                'vivaldi_cache': local / 'Vivaldi/User Data',
                'coccoc_cache':  local / 'CocCoc/Browser/User Data',
            }
            base = base_map.get(tid)
            cache_paths = _chromium_profile_cache_dirs(base, CHROMIUM_CACHE_SUBS) if base else []

        # Accumulate — parallel scan for speed on multiple profile dirs
        total_freed = 0
        if cache_paths:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=min(len(cache_paths), 4)) as ex:
                futures = {ex.submit(_dir_size_safe, p): p for p in cache_paths}
                for fut in as_completed(futures):
                    try:
                        sz = fut.result(timeout=10)
                    except Exception:
                        sz = 0
                    r.freed_bytes += sz
            if not dry:
                for cache_path in cache_paths:
                    before = _dir_size_safe(cache_path)
                    shutil.rmtree(cache_path, ignore_errors=True)
                    total_freed += _real_freed(before, cache_path)
        if not dry:
            r.freed_bytes = total_freed
        return r

    # ── Crash Dumps (Minidump) ────────────────────────────
    def _win_crash_dumps(self, dry):
        """
        Delete Windows crash dump files (kernel + user-mode).

        Covers:
          C:\\Windows\\Minidump\\          — kernel BSOD minidumps
          C:\\Windows\\MEMORY.DMP          — full/kernel memory dump from BSOD
          %LOCALAPPDATA%\\CrashDumps\\     — user-mode app crash dumps (WER)
          %LOCALAPPDATA%\\Temp\\*.dmp      — temp crash dumps written by apps
          %APPDATA%\\..\\Local\\Temp\\*.dmp

        Why safe: crash dumps are point-in-time snapshots of a crash that
        already happened. They're only useful if you're actively debugging
        that specific crash. Leaving them on disk wastes GB of space.

        Note: win_error_reports already covers WER report archives (.wer, .xml).
        This target covers the actual .dmp binary dump files, which are much larger.
        """
        r = CleanResult('win_crash_dumps')
        sysroot = os.environ.get('SystemRoot', 'C:\\Windows')
        _local  = os.environ.get('LOCALAPPDATA', '')

        # Collect all .dmp files
        dmp_dirs = [
            Path(sysroot) / 'Minidump',
        ]
        if _local:
            dmp_dirs += [
                Path(_local) / 'CrashDumps',
                Path(_local) / 'Temp',
            ]

        # MEMORY.DMP — full memory dump, can be multiple GB
        memory_dump = Path(sysroot) / 'MEMORY.DMP'

        all_files = []
        if memory_dump.exists():
            all_files.append(memory_dump)

        for d in dmp_dirs:
            if not d.exists():
                continue
            try:
                for f in d.glob('*.dmp'):
                    if f.is_file():
                        all_files.append(f)
            except (OSError, PermissionError):
                pass

        for f in all_files:
            try:
                sz = f.stat().st_size
                r.freed_bytes   += sz
                r.files_removed += 1
                r.rollback.append({
                    'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                    'type': 'win_crash_dumps',
                    'path': str(f),
                    'size': sz,
                    'note': 'crash dump — safe to delete',
                })
                if not dry:
                    try:
                        # Try direct delete first (user-mode dumps in LOCALAPPDATA)
                        f.unlink(missing_ok=True)
                    except (PermissionError, OSError):
                        # Minidump and MEMORY.DMP need admin
                        if is_admin():
                            try:
                                f.unlink(missing_ok=True)
                            except OSError:
                                pass
                        else:
                            # Attempt via takeown + del (PowerShell)
                            run_win(
                                f'PowerShell -NoProfile -Command "Remove-Item -Force '
                                f'-LiteralPath \'{f}\' -EA SilentlyContinue" 2>$null'
                            )
            except OSError:
                pass
        if not dry:
            # Recompute actual freed (some files may have already been removed)
            remaining = 0
            for f in all_files:
                try:
                    remaining += f.stat().st_size
                except OSError:
                    pass   # already deleted — counts as freed
            r.freed_bytes = max(0, r.freed_bytes - remaining)
        return r
