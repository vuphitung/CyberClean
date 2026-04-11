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
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, creationflags=_NO_WIN,
        )
        return r.stdout.strip(), r.returncode
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


def _dir_size_safe(path) -> int:
    """Walk tree without following NTFS junctions/symlinks."""
    total = 0
    try:
        for dirpath, dirnames, filenames in os.walk(str(path), followlinks=False):
            dirnames[:] = [
                d for d in dirnames
                if not os.path.islink(os.path.join(dirpath, d))
            ]
            for fname in filenames:
                fpath = os.path.join(dirpath, fname)
                try:
                    if not os.path.islink(fpath):
                        total += os.path.getsize(fpath)
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
            Path(os.environ.get('TEMP', 'C:/Windows/Temp')),
            Path(os.environ.get('TMP',  'C:/Windows/Temp')),
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
                        if (now - mtime) < 86400:
                            continue
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
            _, stop_code = run_win('net stop wuauserv /y', timeout=20)
            run_win('net stop bits /y', timeout=20)
            # FIX: only delete if we successfully stopped the service
            if stop_code == 0:
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
                    run_win('net start bits', timeout=20)
                    run_win('net start wuauserv', timeout=20)
                r.freed_bytes = _real_freed(size_before, sd)
            else:
                run_win('net start bits', timeout=20)
                run_win('net start wuauserv', timeout=20)
                r.error = 'Could not stop Windows Update service — skipped'
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
            run_win('net stop dosvc /y', timeout=10)
            shutil.rmtree(do_path, ignore_errors=True)
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
            deleted = 0
            locked  = 0
            for f in files:
                try:
                    sz = f.stat().st_size
                    f.unlink()
                    deleted += sz
                    r.rollback.append({
                        'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                        'type': 'thumbcache', 'path': str(f),
                        'size': sz, 'note': 'auto-rebuilds',
                    })
                except PermissionError:
                    locked += 1
                except OSError:
                    pass
            r.freed_bytes   = deleted
            r.files_removed = len([f for f in files if not f.exists()])
            if locked > 0:
                r.error = (
                    f'{locked} file(s) locked by Explorer — sign out and back in, '
                    'then run again to clear the remaining cache.'
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
            # Stop FontCache service to release lock on files
            run_win('net stop "Windows Font Cache Service" /y', timeout=15)
            run_win('sc stop FontCache', timeout=10)
            deleted = 0
            for f in existing:
                try:
                    sz = f.stat().st_size
                    f.unlink()
                    deleted += sz
                    r.rollback.append({
                        'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                        'type': 'font_cache', 'path': str(f),
                        'size': sz, 'note': 'auto-rebuilds on next boot',
                    })
                except (PermissionError, OSError):
                    pass
            run_win('net start "Windows Font Cache Service"', timeout=10)
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
            out, code = run_win(
                'Dism /Online /Cleanup-Image /StartComponentCleanup /ResetBase 2>nul',
                timeout=600,   # can take several minutes
            )
            if code not in (0, 3010):
                # 3010 = success, restart required
                r.error = f'DISM cleanup failed (code {code})'
            else:
                # Can't measure exact freed bytes after DISM — report nominal
                r.freed_bytes   = 0
                r.files_removed = 1
        return r

    # ── Event Logs ────────────────────────────────────────────
    def _win_eventlog(self, dry):
        r = CleanResult('win_eventlog')
        evtx_dir = Path(os.environ.get('SystemRoot', 'C:\\Windows')) / 'System32/winevt/Logs'
        size_before = _dir_size_safe(evtx_dir) if evtx_dir.exists() else 0
        r.freed_bytes = size_before
        if not dry and is_admin():
            out, _ = run_win('wevtutil el', timeout=15)
            logs    = [l.strip() for l in out.splitlines() if l.strip()]
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

        # Accumulate
        total_freed = 0
        for cache_path in cache_paths:
            size_before = _dir_size_safe(cache_path)
            r.freed_bytes += size_before
            if not dry:
                shutil.rmtree(cache_path, ignore_errors=True)
                total_freed += _real_freed(size_before, cache_path)
        if not dry:
            r.freed_bytes = total_freed
        return r
