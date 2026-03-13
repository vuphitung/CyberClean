"""
CyberClean v2.0 — Windows Cleaner
FIX: Accurate freed_bytes — measure AFTER delete, not before.
     wevtutil for eventlog (deeper than Clear-EventLog).
     Added win_error_reports target.
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
    total = 0
    try:
        for f in Path(path).rglob('*'):
            if f.is_file() and not f.is_symlink():
                try: total += f.stat().st_size
                except: pass
    except: pass
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
        for d in dirs:
            if not d.exists(): continue
            size_before = _dir_size_safe(d)
            r.freed_bytes += size_before
            if not dry:
                for item in list(d.iterdir()):
                    try:
                        sz = _dir_size_safe(item) if item.is_dir() else item.stat().st_size
                        r.rollback.append({'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                           'type': 'win_temp', 'path': str(item),
                                           'size': sz, 'note': 'temp — not needed'})
                        if item.is_dir(): shutil.rmtree(item, ignore_errors=True)
                        else:             item.unlink(missing_ok=True)
                        r.files_removed += 1
                    except: pass
                r.freed_bytes = r.freed_bytes - size_before + _real_freed(size_before, d)
        return r

    def _win_prefetch(self, dry):
        r = CleanResult('win_prefetch')
        pf = Path('C:/Windows/Prefetch')
        if not pf.exists(): return r
        files = list(pf.glob('*.pf'))
        size_before = sum(f.stat().st_size for f in files)
        r.freed_bytes   = size_before
        r.files_removed = len(files)
        if not dry and is_admin():
            deleted = 0
            for f in files:
                try:
                    sz = f.stat().st_size
                    r.rollback.append({'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                       'type': 'prefetch', 'path': str(f),
                                       'size': sz, 'note': 'auto-rebuilds'})
                    f.unlink()
                    deleted += sz
                except: pass
            r.freed_bytes   = deleted
            r.files_removed = len([f for f in files if not f.exists()])
        elif not dry and not is_admin():
            r.error = 'Needs admin — relaunch as Administrator'
        return r

    def _win_recycle(self, dry):
        r = CleanResult('win_recycle')
        out, _ = run_win(
            'PowerShell -NoProfile -Command "(New-Object -ComObject Shell.Application)'
            '.Namespace(10).Items() | Measure-Object -Property Size -Sum'
            ' | Select-Object -ExpandProperty Sum" 2>$null')
        try: r.freed_bytes = int(float(out or 0))
        except: pass
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
            for item in list(sd.iterdir()):
                try:
                    sz = _dir_size_safe(item) if item.is_dir() else item.stat().st_size
                    r.rollback.append({'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                       'type': 'win_updates', 'path': str(item),
                                       'size': sz, 'note': 're-downloads when needed'})
                    if item.is_dir(): shutil.rmtree(item, ignore_errors=True)
                    else:             item.unlink(missing_ok=True)
                except: pass
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
        size_before = sum(f.stat().st_size for f in files)
        r.freed_bytes   = size_before
        r.files_removed = len(files)
        if not dry:
            run_win('taskkill /F /IM explorer.exe 2>$null', timeout=10)
            deleted = 0
            for f in files:
                try:
                    sz = f.stat().st_size
                    r.rollback.append({'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                       'type': 'thumbcache', 'path': str(f),
                                       'size': sz, 'note': 'auto-rebuilds'})
                    f.unlink()
                    deleted += sz
                except: pass
            run_win('start explorer.exe', timeout=5)
            time.sleep(1.5)   # let Explorer rebuild skeleton files
            rebuilt = sum(f.stat().st_size for f in thumb_dir.glob('thumbcache_*.db') if f.exists())
            r.freed_bytes   = max(0, deleted - rebuilt)
            r.files_removed = len([f for f in files if not f.exists()])
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

        # Measure ACTUAL .evtx file sizes — NOT MaximumKilobytes (that is just a quota cap)
        size_before = _dir_size_safe(evtx_dir) if evtx_dir.exists() else 0
        r.freed_bytes = size_before

        if not dry and is_admin():
            # wevtutil is deeper than Clear-EventLog:
            #   - handles ALL logs (classic + modern channels)
            #   - does not require the log service to be running
            out, _ = run_win('wevtutil el', timeout=15)
            logs = [l.strip() for l in out.splitlines() if l.strip()]
            cleared = 0
            for log in logs:
                safe_name = log.replace('"', '').replace("'", '')
                _, rc = run_win(f'wevtutil cl "{safe_name}" 2>nul', timeout=10)
                if rc == 0:
                    cleared += 1
            # Windows keeps empty .evtx shells (~68 KB each) — measure real freed space
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
                    except: pass
            size_after = sum(_dir_size_safe(d) for d in existing if d.exists())
            r.freed_bytes = max(0, size_before - size_after)
        return r

    def _browser_cache(self, tid, dry):
        r = CleanResult(tid)
        local   = Path(os.environ.get('LOCALAPPDATA', ''))
        roaming = Path(os.environ.get('APPDATA', ''))
        paths = {
            'chrome_cache': [
                local / 'Google/Chrome/User Data/Default/Cache',
                local / 'Google/Chrome/User Data/Default/Code Cache',
                local / 'Google/Chrome/User Data/Default/GPUCache',
            ],
            'firefox_cache': [
                roaming / 'Mozilla/Firefox/Profiles',
            ],
            'edge_cache': [
                local / 'Microsoft/Edge/User Data/Default/Cache',
                local / 'Microsoft/Edge/User Data/Default/Code Cache',
                local / 'Microsoft/Edge/User Data/Default/GPUCache',
            ],
        }
        for path in paths.get(tid, []):
            if not path.exists(): continue
            size_before = _dir_size_safe(path)
            r.freed_bytes += size_before
            if not dry:
                self.remove_dir_contents(path, r.rollback, tid)
                # Re-measure: browser rewrites files instantly if still running
                r.freed_bytes = r.freed_bytes - size_before + _real_freed(size_before, path)
        return r
