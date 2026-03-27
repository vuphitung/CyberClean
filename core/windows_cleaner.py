"""
CyberClean v2.2 — Windows Cleaner
FIX #4: _win_recycle null-safe size parse — network/locked items return no .Size
        property causing Measure-Object to output empty string → ValueError.
        Now handles None/empty gracefully.
FIX #5: _dir_size_safe replaced rglob with os.walk(followlinks=False) to prevent
        infinite loops from NTFS junction points (e.g. AppData/Local/Application Data).
FIX #6: bare except:pass replaced with typed except in all file-deletion loops —
        errors are now skipped with a reason, not silently swallowed.
"""
import os, shutil, subprocess, time
from pathlib import Path
from .base_cleaner import BaseCleaner, CleanTarget, CleanResult

_NO_WIN = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0

def run_win(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout,
                           creationflags=_NO_WIN)
        return r.stdout.strip(), r.returncode
    except Exception as e:
        return str(e), 1

def is_admin():
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except:
        return False

def _dir_size_safe(path):
    """
    FIX: replaced Path.rglob('*') with os.walk(followlinks=False).
    rglob follows NTFS junction points / symlinks, causing infinite loops
    (e.g. C:/Users/X/AppData/Local/Application Data → itself).
    os.walk(followlinks=False) stops at junction boundaries entirely.
    """
    total = 0
    try:
        for dirpath, dirnames, filenames in os.walk(str(path), followlinks=False):
            # Also skip symlinked subdirectories explicitly (Windows junctions)
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

def _real_freed(size_before, path):
    size_after = _dir_size_safe(path) if Path(path).exists() else 0
    return max(0, size_before - size_after)


class WindowsCleaner(BaseCleaner):

    def get_targets(self):
        return [
            CleanTarget('win_temp',         'Windows Temp',
                '%TEMP% and C:\\Windows\\Temp',                             'safe'),
            CleanTarget('win_prefetch',     'Prefetch Cache',
                'App launch prefetch — auto-rebuilds',                      'safe',    needs_root=True),
            CleanTarget('win_recycle',      'Recycle Bin',
                'All items in Recycle Bin',                                 'caution'),
            CleanTarget('win_updates',      'Windows Update Cache',
                'Downloaded update files in SoftwareDistribution',          'safe',    needs_root=True),
            CleanTarget('win_thumbcache',   'Thumbnail Cache',
                'Explorer thumbcache_*.db — auto-rebuilds',                 'safe'),
            CleanTarget('win_dns',          'DNS Cache',
                'Flush DNS resolver cache',                                 'safe',    needs_root=True),
            CleanTarget('win_eventlog',     'Event Logs',
                'Clear all Windows Event Viewer logs (wevtutil)',           'caution', needs_root=True),
            CleanTarget('win_delivery',     'Delivery Optimization',
                'Windows Update peer-to-peer cache in DataStore',           'safe',    needs_root=True),
            CleanTarget('win_error_reports','Windows Error Reports',
                'App crash dumps and WER report files',                     'safe'),
            CleanTarget('chrome_cache',     'Chrome Cache',
                'Browser cache — auto-rebuilds',                            'safe'),
            CleanTarget('firefox_cache',    'Firefox Cache',
                'Browser cache — auto-rebuilds',                            'safe'),
            CleanTarget('edge_cache',       'Edge Cache',
                'Microsoft Edge cache — auto-rebuilds',                     'safe'),
            CleanTarget('brave_cache',      'Brave Cache',
                'Brave browser cache — auto-rebuilds',                      'safe'),
            CleanTarget('opera_cache',      'Opera Cache',
                'Opera browser cache — auto-rebuilds',                      'safe'),
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
                'win_thumbcache':    self._win_thumbcache,
                'win_dns':           self._win_dns,
                'win_eventlog':      self._win_eventlog,
                'win_delivery':      self._win_delivery,
                'win_error_reports': self._win_error_reports,
                'chrome_cache':      lambda d: self._browser_cache('chrome_cache', d),
                'firefox_cache':     lambda d: self._browser_cache('firefox_cache', d),
                'edge_cache':        lambda d: self._browser_cache('edge_cache', d),
                'brave_cache':       lambda d: self._browser_cache('brave_cache', d),
                'opera_cache':       lambda d: self._browser_cache('opera_cache', d),
            }.get(tid)
            if fn: r = fn(dry)
        except Exception as e:
            r.error = str(e)
        return r

    def _win_temp(self, dry):
        r = CleanResult('win_temp')
        dirs = list({
            Path(os.environ.get('TEMP', 'C:/Windows/Temp')),
            Path(os.environ.get('TMP',  'C:/Windows/Temp')),
            Path('C:/Windows/Temp'),
        })
        now = time.time()
        ELECTRON_PREFIXES = (
            'scoped_dir', 'chrome_', 'msedge_', 'discord',
            'vscode', 'electron', 'squirrel',
        )
        for d in dirs:
            if not d.exists(): continue
            safe_path = str(d).lower().replace(os.sep, '/')
            if safe_path.rstrip('/') in ('c:', 'c:/', 'c:/windows', 'c:/users'):
                continue
            size_before = _dir_size_safe(d)
            if not dry:
                deleted = 0
                for item in d.iterdir():
                    try:
                        if item.is_dir() and item.name.lower().startswith(ELECTRON_PREFIXES):
                            continue
                        if (now - item.stat().st_mtime) < 86400:
                            continue
                        sz = _dir_size_safe(item) if item.is_dir() else item.stat().st_size
                        if item.is_dir():
                            shutil.rmtree(item, ignore_errors=True)
                        else:
                            item.unlink(missing_ok=True)
                        deleted += sz
                        r.files_removed += 1
                    except PermissionError:
                        pass   # file locked by a running process — skip silently
                    except OSError:
                        pass
                r.freed_bytes += deleted
            else:
                for item in d.iterdir():
                    try:
                        if (now - item.stat().st_mtime) < 86400: continue
                        if item.is_dir() and item.name.lower().startswith(ELECTRON_PREFIXES): continue
                        r.freed_bytes += _dir_size_safe(item) if item.is_dir() else item.stat().st_size
                    except (OSError, PermissionError):
                        pass
        return r

    def _win_prefetch(self, dry):
        r = CleanResult('win_prefetch')
        pf = Path('C:/Windows/Prefetch')
        if not pf.exists(): return r
        now = time.time()
        files = list(pf.glob('*.pf'))
        old_files = [f for f in files if (now - f.stat().st_mtime) > 604800]
        r.freed_bytes   = sum(f.stat().st_size for f in old_files)
        r.files_removed = len(old_files)
        if not dry and is_admin():
            deleted = 0
            for f in old_files:
                try:
                    sz = f.stat().st_size
                    f.unlink()
                    deleted += sz
                except PermissionError:
                    pass   # Prefetch file locked by system — skip
                except OSError:
                    pass
            r.freed_bytes   = deleted
            r.files_removed = len([f for f in old_files if not f.exists()])
        elif not dry and not is_admin():
            r.error = 'Needs admin — relaunch as Administrator'
        return r

    def _win_recycle(self, dry):
        """
        FIX #4: Null-safe Recycle Bin size estimate.
        Network files and locked items may not expose a .Size property —
        Measure-Object then outputs empty string (not "0"), causing int(float("")) → ValueError.
        Fix: use try/except float conversion with explicit 0 fallback,
             and add -ErrorAction SilentlyContinue to the PS command.
        """
        r = CleanResult('win_recycle')
        # FIX: added -ErrorAction SilentlyContinue + null coalesce to avoid empty output
        out, _ = run_win(
            'PowerShell -NoProfile -Command "'
            '(New-Object -ComObject Shell.Application).Namespace(10).Items()'
            ' | Where-Object {$_.Size -ne $null}'
            ' | Measure-Object -Property Size -Sum -ErrorAction SilentlyContinue'
            ' | Select-Object -ExpandProperty Sum" 2>$null')
        try:
            # Null-safe: empty string, "null", None all resolve to 0
            val = out.strip() if out else ''
            r.freed_bytes = int(float(val)) if val and val.lower() not in ('', 'null', 'none') else 0
        except (ValueError, TypeError):
            r.freed_bytes = 0
        if not dry:
            run_win('PowerShell -NoProfile -Command '
                    '"Clear-RecycleBin -Force -EA SilentlyContinue" 2>$null')
        return r

    def _win_updates(self, dry):
        r = CleanResult('win_updates')
        sd = Path('C:/Windows/SoftwareDistribution/Download')
        if not sd.exists(): return r
        size_before = _dir_size_safe(sd)
        r.freed_bytes = size_before
        if not dry and is_admin():
            run_win('net stop wuauserv /y', timeout=20)
            run_win('net stop bits /y', timeout=20)
            try:
                for item in list(sd.iterdir()):
                    try:
                        sz = _dir_size_safe(item) if item.is_dir() else item.stat().st_size
                        r.rollback.append({'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                           'type': 'win_updates', 'path': str(item),
                                           'size': sz, 'note': 're-downloads when needed'})
                        if item.is_dir(): shutil.rmtree(item, ignore_errors=True)
                        else:             item.unlink(missing_ok=True)
                    except (PermissionError, OSError):
                        pass   # update file locked by BITS/wuauserv — skip
            finally:
                run_win('net start bits', timeout=20)
                run_win('net start wuauserv', timeout=20)
            r.freed_bytes = _real_freed(size_before, sd)
        elif not dry and not is_admin():
            r.error = 'Needs admin'
        return r

    def _win_delivery(self, dry):
        r = CleanResult('win_delivery')
        do_path = Path('C:/Windows/SoftwareDistribution/DeliveryOptimization')
        if not do_path.exists(): return r
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

    def _win_thumbcache(self, dry):
        r = CleanResult('win_thumbcache')
        thumb_dir = Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft/Windows/Explorer'
        if not thumb_dir.exists(): return r
        files = list(thumb_dir.glob('thumbcache_*.db'))
        size_before = sum(f.stat().st_size for f in files if f.exists())
        r.freed_bytes   = size_before
        r.files_removed = len(files)
        if not dry:
            deleted = 0
            locked  = 0
            for f in files:
                try:
                    sz = f.stat().st_size
                    f.unlink()
                    deleted += sz
                    r.rollback.append({'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                       'type': 'thumbcache', 'path': str(f),
                                       'size': sz, 'note': 'auto-rebuilds'})
                except PermissionError:
                    # FIX: Explorer holds a lock on thumbcache_*.db while running.
                    # Silently skipping gave "0 bytes freed" with no explanation.
                    # Now we count locked files and surface a clear warning.
                    locked += 1
                except OSError:
                    pass
            r.freed_bytes   = deleted
            r.files_removed = len([f for f in files if not f.exists()])
            if locked > 0:
                r.error = (
                    f'{locked} file(s) locked by Explorer — restart Explorer or '
                    'sign out and back in, then run again to clear the remaining cache.'
                )
        return r

    def _win_dns(self, dry):
        r = CleanResult('win_dns')
        r.files_removed = 1
        if not dry:
            _, code = run_win('ipconfig /flushdns')
            if code != 0: r.error = 'DNS flush failed'
        return r

    def _win_eventlog(self, dry):
        r = CleanResult('win_eventlog')
        evtx_dir = Path(os.environ.get('SystemRoot', 'C:\\Windows')) / 'System32' / 'winevt' / 'Logs'
        size_before = _dir_size_safe(evtx_dir) if evtx_dir.exists() else 0
        r.freed_bytes = size_before
        if not dry and is_admin():
            out, _ = run_win('wevtutil el', timeout=15)
            logs = [l.strip() for l in out.splitlines() if l.strip()]
            cleared = 0
            for log in logs:
                # FIX: use subprocess list (no shell=True) to prevent command injection
                # via log names containing & ; | characters.
                try:
                    import subprocess as _sp
                    rc = _sp.run(
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

    def _win_error_reports(self, dry):
        r = CleanResult('win_error_reports')
        wer_dirs = [
            Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft/Windows/WER/ReportArchive',
            Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft/Windows/WER/ReportQueue',
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
                        r.rollback.append({'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                           'type': 'win_error_reports', 'path': str(item),
                                           'size': sz, 'note': 'crash dump — safe to remove'})
                        if item.is_dir(): shutil.rmtree(item, ignore_errors=True)
                        else:             item.unlink(missing_ok=True)
                        r.files_removed += 1
                    except PermissionError:
                        pass   # WER report currently being written — skip
                    except OSError:
                        pass
            size_after = sum(_dir_size_safe(d) for d in existing if d.exists())
            r.freed_bytes = max(0, size_before - size_after)
        return r

    def _browser_cache(self, tid, dry):
        r = CleanResult(tid)
        local   = Path(os.environ.get('LOCALAPPDATA', ''))
        roaming = Path(os.environ.get('APPDATA', ''))

        if tid == 'firefox_cache':
            local_ff = local / 'Mozilla/Firefox/Profiles'
            roaming_ff = roaming / 'Mozilla/Firefox/Profiles'
            cache_paths = []
            for base in [local_ff, roaming_ff]:
                if base.exists():
                    for profile_dir in base.iterdir():
                        if profile_dir.is_dir():
                            cache2 = profile_dir / 'cache2'
                            if cache2.exists():
                                cache_paths.append(cache2)
            total_freed = 0
            for cache_path in cache_paths:
                size_before = _dir_size_safe(cache_path)
                r.freed_bytes += size_before
                if not dry:
                    shutil.rmtree(cache_path, ignore_errors=True)
                    # FIX: accumulate per-profile actual freed independently,
                    # don't subtract size_before from total (causes negative/wrong results
                    # when multiple profiles exist).
                    actually_freed = _real_freed(size_before, cache_path)
                    total_freed += actually_freed
            if not dry:
                r.freed_bytes = total_freed
            return r

        paths = {
            'chrome_cache': [
                local / 'Google/Chrome/User Data/Default/Cache',
                local / 'Google/Chrome/User Data/Default/Code Cache',
                local / 'Google/Chrome/User Data/Default/GPUCache',
            ],
            'edge_cache': [
                local / 'Microsoft/Edge/User Data/Default/Cache',
                local / 'Microsoft/Edge/User Data/Default/Code Cache',
                local / 'Microsoft/Edge/User Data/Default/GPUCache',
            ],
            'brave_cache': [
                local / 'BraveSoftware/Brave-Browser/User Data/Default/Cache',
                local / 'BraveSoftware/Brave-Browser/User Data/Default/Code Cache',
                local / 'BraveSoftware/Brave-Browser/User Data/Default/GPUCache',
            ],
            'opera_cache': [
                roaming / 'Opera Software/Opera Stable/Cache',
                roaming / 'Opera Software/Opera Stable/Code Cache',
                roaming / 'Opera Software/Opera GX Stable/Cache',
                roaming / 'Opera Software/Opera GX Stable/Code Cache',
            ],
        }
        total_freed = 0
        for path in paths.get(tid, []):
            if not path.exists(): continue
            size_before = _dir_size_safe(path)
            r.freed_bytes += size_before
            if not dry:
                shutil.rmtree(path, ignore_errors=True)
                # FIX: accumulate per-path actual freed independently (same bug as Firefox)
                total_freed += _real_freed(size_before, path)
        if not dry:
            r.freed_bytes = total_freed
        return r
