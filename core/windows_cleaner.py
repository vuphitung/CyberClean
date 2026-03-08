"""
CyberClean v2.0 — Windows Cleaner
FIX: CREATE_NO_WINDOW only on Windows (crashes on Linux otherwise)
"""
import os, shutil, subprocess, time
from pathlib import Path
from .base_cleaner import BaseCleaner, CleanTarget, CleanResult

# FIX: CREATE_NO_WINDOW only exists on Windows
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

class WindowsCleaner(BaseCleaner):

    def get_targets(self):
        return [
            CleanTarget('win_temp',       'Windows Temp',
                '%TEMP% and C:\\Windows\\Temp',                           'safe'),
            CleanTarget('win_prefetch',   'Prefetch Cache',
                'App launch prefetch — auto-rebuilds',                    'safe',    needs_root=True),
            CleanTarget('win_recycle',    'Recycle Bin',
                'All items in Recycle Bin',                               'caution'),
            CleanTarget('win_updates',    'Windows Update Cache',
                'Downloaded update files in SoftwareDistribution',        'safe',    needs_root=True),
            CleanTarget('win_thumbcache', 'Thumbnail Cache',
                'Explorer thumbcache_*.db — auto-rebuilds',               'safe'),
            CleanTarget('win_dns',        'DNS Cache',
                'Flush DNS resolver cache',                               'safe',    needs_root=True),
            CleanTarget('win_eventlog',   'Event Logs',
                'Clear Windows Event Viewer logs',                        'caution', needs_root=True),
            CleanTarget('win_delivery',   'Delivery Optimization',
                'Windows Update peer-to-peer cache in DataStore',         'safe',    needs_root=True),
            CleanTarget('chrome_cache',   'Chrome Cache',
                'Browser cache — auto-rebuilds',                          'safe'),
            CleanTarget('firefox_cache',  'Firefox Cache',
                'Browser cache — auto-rebuilds',                          'safe'),
            CleanTarget('edge_cache',     'Edge Cache',
                'Microsoft Edge cache — auto-rebuilds',                   'safe'),
        ]

    def estimate(self, target_id: str) -> int:
        return self._run_target(target_id, dry=True).freed_bytes

    def clean(self, target_id: str, dry: bool = True) -> CleanResult:
        return self._run_target(target_id, dry=dry)

    def _run_target(self, tid, dry):
        r = CleanResult(target_id=tid)
        try:
            fn = {
                'win_temp':       self._win_temp,
                'win_prefetch':   self._win_prefetch,
                'win_recycle':    self._win_recycle,
                'win_updates':    self._win_updates,
                'win_thumbcache': self._win_thumbcache,
                'win_dns':        self._win_dns,
                'win_eventlog':   self._win_eventlog,
                'win_delivery':   self._win_delivery,
                'chrome_cache':   lambda d: self._browser_cache('chrome_cache', d),
                'firefox_cache':  lambda d: self._browser_cache('firefox_cache', d),
                'edge_cache':     lambda d: self._browser_cache('edge_cache', d),
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
            r.freed_bytes += self.dir_size(d)
            if not dry:
                for item in d.iterdir():
                    try:
                        sz = self.dir_size(item) if item.is_dir() else item.stat().st_size
                        r.rollback.append({'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                           'type': 'win_temp', 'path': str(item),
                                           'size': sz, 'note': 'temp — not needed'})
                        if item.is_dir(): shutil.rmtree(item, ignore_errors=True)
                        else: item.unlink(missing_ok=True)
                        r.files_removed += 1
                    except: pass
        return r

    def _win_prefetch(self, dry):
        r = CleanResult('win_prefetch')
        pf = Path('C:/Windows/Prefetch')
        if not pf.exists(): return r
        files = list(pf.glob('*.pf'))
        r.freed_bytes   = sum(f.stat().st_size for f in files)
        r.files_removed = len(files)
        if not dry and is_admin():
            for f in files:
                try:
                    r.rollback.append({'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                       'type': 'prefetch', 'path': str(f),
                                       'size': f.stat().st_size, 'note': 'auto-rebuilds'})
                    f.unlink()
                except: pass
        elif not dry and not is_admin():
            r.error = 'Needs admin — relaunch as Administrator'
        return r

    def _win_recycle(self, dry):
        r = CleanResult('win_recycle')
        out, _ = run_win(
            'PowerShell -Command "(New-Object -ComObject Shell.Application)'
            '.Namespace(10).Items() | Measure-Object -Property Size -Sum'
            ' | Select-Object -ExpandProperty Sum" 2>$null')
        try: r.freed_bytes = int(float(out or 0))
        except: pass
        if not dry:
            run_win('PowerShell -Command "Clear-RecycleBin -Force -EA SilentlyContinue" 2>$null')
        return r

    def _win_updates(self, dry):
        r = CleanResult('win_updates')
        sd = Path('C:/Windows/SoftwareDistribution/Download')
        if not sd.exists(): return r
        r.freed_bytes = self.dir_size(sd)
        if not dry and is_admin():
            run_win('net stop wuauserv /y', timeout=20)
            for item in sd.iterdir():
                try:
                    sz = self.dir_size(item) if item.is_dir() else item.stat().st_size
                    r.rollback.append({'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                       'type': 'win_updates', 'path': str(item),
                                       'size': sz, 'note': 're-downloads when needed'})
                    if item.is_dir(): shutil.rmtree(item, ignore_errors=True)
                    else: item.unlink(missing_ok=True)
                except: pass
            run_win('net start wuauserv', timeout=20)
        elif not dry and not is_admin():
            r.error = 'Needs admin'
        return r

    def _win_delivery(self, dry):
        """Windows Delivery Optimization cache."""
        r = CleanResult('win_delivery')
        do_path = Path('C:/Windows/SoftwareDistribution/DeliveryOptimization')
        if not do_path.exists(): return r
        r.freed_bytes = self.dir_size(do_path)
        if not dry and is_admin():
            run_win('net stop dosvc /y', timeout=10)
            shutil.rmtree(do_path, ignore_errors=True)
            run_win('net start dosvc', timeout=10)
        elif not dry and not is_admin():
            r.error = 'Needs admin'
        return r

    def _win_thumbcache(self, dry):
        r = CleanResult('win_thumbcache')
        thumb_dir = Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft/Windows/Explorer'
        if not thumb_dir.exists(): return r
        files = list(thumb_dir.glob('thumbcache_*.db'))
        r.freed_bytes   = sum(f.stat().st_size for f in files)
        r.files_removed = len(files)
        if not dry:
            run_win('taskkill /F /IM explorer.exe 2>$null', timeout=10)
            for f in files:
                try:
                    r.rollback.append({'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                       'type': 'thumbcache', 'path': str(f),
                                       'size': f.stat().st_size, 'note': 'auto-rebuilds'})
                    f.unlink()
                except: pass
            run_win('start explorer.exe', timeout=5)
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
        out, _ = run_win(
            'PowerShell -Command "Get-EventLog -List | '
            'Measure-Object -Property MaximumKilobytes -Sum | '
            'Select-Object -ExpandProperty Sum" 2>$null')
        try: r.freed_bytes = int(float(out or 0)) * 1024
        except: pass
        if not dry and is_admin():
            run_win('PowerShell -Command "Get-EventLog -List | ForEach-Object '
                    '{ Clear-EventLog $_.Log -EA SilentlyContinue }" 2>$null', timeout=30)
        elif not dry and not is_admin():
            r.error = 'Needs admin'
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
                Path(os.environ.get('LOCALAPPDATA','')) / 'Mozilla/Firefox/Profiles',
            ],
            'edge_cache': [
                local / 'Microsoft/Edge/User Data/Default/Cache',
                local / 'Microsoft/Edge/User Data/Default/Code Cache',
                local / 'Microsoft/Edge/User Data/Default/GPUCache',
            ],
        }
        for path in paths.get(tid, []):
            if not path.exists(): continue
            r.freed_bytes += self.dir_size(path)
            if not dry:
                self.remove_dir_contents(path, r.rollback, tid)
        return r
