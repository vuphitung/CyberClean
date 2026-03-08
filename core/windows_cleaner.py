"""
CyberClean v2.0 — Windows Cleaner
Cleans: %TEMP%, Prefetch, Recycle Bin, Windows Update Cache,
        browser caches, thumbnail cache, DNS cache, event logs
"""
import os, shutil, subprocess, ctypes, time
from pathlib import Path
from .base_cleaner import BaseCleaner, CleanTarget, CleanResult

def run_win(cmd, shell=True, timeout=30):
    try:
        r = subprocess.run(cmd, shell=shell, capture_output=True,
                           text=True, timeout=timeout,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        return r.stdout.strip(), r.returncode
    except Exception as e:
        return str(e), 1

def is_admin():
    try:    return ctypes.windll.shell32.IsUserAnAdmin()
    except: return False

class WindowsCleaner(BaseCleaner):

    def get_targets(self):
        return [
            CleanTarget('win_temp',       'Windows Temp',        '%TEMP% and C:\\Windows\\Temp folder',             'safe'),
            CleanTarget('win_prefetch',   'Prefetch Cache',      'App launch prefetch files — Windows auto-rebuilds','safe',    needs_root=True),
            CleanTarget('win_recycle',    'Recycle Bin',         'All items in Recycle Bin',                        'caution'),
            CleanTarget('win_updates',    'Windows Update Cache','Downloaded update files in SoftwareDistribution',  'safe',    needs_root=True),
            CleanTarget('win_thumbcache', 'Thumbnail Cache',     'Explorer thumbnail database — auto-rebuilds',      'safe'),
            CleanTarget('win_dns',        'DNS Cache',           'Flush DNS resolver cache',                        'safe',    needs_root=True),
            CleanTarget('win_eventlog',   'Event Logs',          'Clear Windows Event Viewer logs',                 'caution', needs_root=True),
            CleanTarget('chrome_cache',   'Chrome Cache',        'Browser cache — auto-rebuilds',                   'safe'),
            CleanTarget('firefox_cache',  'Firefox Cache',       'Browser cache — auto-rebuilds',                   'safe'),
            CleanTarget('edge_cache',     'Edge Cache',          'Microsoft Edge browser cache',                    'safe'),
        ]

    def estimate(self, target_id: str) -> int:
        return self._run_target(target_id, dry=True).freed_bytes

    def clean(self, target_id: str, dry: bool = True) -> CleanResult:
        return self._run_target(target_id, dry=dry)

    def _run_target(self, tid, dry):
        result = CleanResult(target_id=tid)
        try:
            if tid == 'win_temp':       result = self._win_temp(dry)
            elif tid == 'win_prefetch': result = self._win_prefetch(dry)
            elif tid == 'win_recycle':  result = self._win_recycle(dry)
            elif tid == 'win_updates':  result = self._win_updates(dry)
            elif tid == 'win_thumbcache': result = self._win_thumbcache(dry)
            elif tid == 'win_dns':      result = self._win_dns(dry)
            elif tid == 'win_eventlog': result = self._win_eventlog(dry)
            elif tid in ('chrome_cache','firefox_cache','edge_cache'):
                result = self._browser_cache(tid, dry)
        except Exception as e:
            result.error = str(e)
        return result

    # ── Windows Temp ──────────────────────────────────────
    def _win_temp(self, dry):
        r = CleanResult('win_temp')
        dirs = [
            Path(os.environ.get('TEMP', '')),
            Path(os.environ.get('TMP', '')),
            Path('C:/Windows/Temp'),
        ]
        for d in dirs:
            if not d.exists(): continue
            sz = self.dir_size(d)
            r.freed_bytes += sz
            if not dry:
                self.remove_dir_contents(d, r.rollback, 'win_temp')
        return r

    # ── Prefetch ──────────────────────────────────────────
    def _win_prefetch(self, dry):
        r = CleanResult('win_prefetch')
        pf = Path('C:/Windows/Prefetch')
        if not pf.exists(): return r
        r.freed_bytes = self.dir_size(pf)
        r.files_removed = sum(1 for _ in pf.glob('*.pf'))
        if not dry and is_admin():
            for f in pf.glob('*.pf'):
                try: f.unlink(); r.rollback.append({'time': time.strftime('%Y-%m-%dT%H:%M:%S'),'type':'prefetch','path':str(f),'size':0,'note':'auto-rebuilds'})
                except: pass
        return r

    # ── Recycle Bin ───────────────────────────────────────
    def _win_recycle(self, dry):
        r = CleanResult('win_recycle')
        # Use SHEmptyRecycleBin to get size estimate
        out, _ = run_win('PowerShell -Command "(New-Object -ComObject Shell.Application).Namespace(10).Items() | Measure-Object -Property Size -Sum | Select-Object -ExpandProperty Sum"')
        try: r.freed_bytes = int(float(out or 0))
        except: pass
        if not dry:
            run_win('PowerShell -Command "Clear-RecycleBin -Force -ErrorAction SilentlyContinue"')
        return r

    # ── Windows Update Cache ──────────────────────────────
    def _win_updates(self, dry):
        r = CleanResult('win_updates')
        sd = Path('C:/Windows/SoftwareDistribution/Download')
        if not sd.exists(): return r
        r.freed_bytes = self.dir_size(sd)
        if not dry and is_admin():
            # Stop Windows Update service first
            run_win('net stop wuauserv /y', timeout=15)
            self.remove_dir_contents(sd, r.rollback, 'win_updates')
            run_win('net start wuauserv', timeout=15)
        return r

    # ── Thumbnail cache ───────────────────────────────────
    def _win_thumbcache(self, dry):
        r = CleanResult('win_thumbcache')
        thumb_dir = Path(os.environ.get('LOCALAPPDATA','')) / 'Microsoft/Windows/Explorer'
        if not thumb_dir.exists(): return r
        files = list(thumb_dir.glob('thumbcache_*.db'))
        r.freed_bytes = sum(f.stat().st_size for f in files)
        r.files_removed = len(files)
        if not dry:
            # Explorer must be stopped first
            run_win('taskkill /F /IM explorer.exe', timeout=10)
            for f in files:
                try: f.unlink()
                except: pass
            run_win('start explorer.exe', timeout=5)
        return r

    # ── DNS cache ─────────────────────────────────────────
    def _win_dns(self, dry):
        r = CleanResult('win_dns')
        r.freed_bytes = 0   # DNS cache size not easily measurable
        r.files_removed = 1
        if not dry:
            run_win('ipconfig /flushdns')
        return r

    # ── Event logs ────────────────────────────────────────
    def _win_eventlog(self, dry):
        r = CleanResult('win_eventlog')
        out, _ = run_win('PowerShell -Command "Get-EventLog -List | Measure-Object -Property MaximumKilobytes -Sum | Select-Object -ExpandProperty Sum"')
        try: r.freed_bytes = int(float(out or 0)) * 1024
        except: pass
        if not dry and is_admin():
            run_win('PowerShell -Command "Get-EventLog -List | ForEach-Object { Clear-EventLog $_.Log -ErrorAction SilentlyContinue }"')
        return r

    # ── Browser caches ────────────────────────────────────
    def _browser_cache(self, tid, dry):
        r = CleanResult(tid)
        local = Path(os.environ.get('LOCALAPPDATA', ''))
        roaming = Path(os.environ.get('APPDATA', ''))
        paths = {
            'chrome_cache': [
                local / 'Google/Chrome/User Data/Default/Cache',
                local / 'Google/Chrome/User Data/Default/Code Cache',
            ],
            'firefox_cache': [
                local / 'Mozilla/Firefox/Profiles',
            ],
            'edge_cache': [
                local / 'Microsoft/Edge/User Data/Default/Cache',
                local / 'Microsoft/Edge/User Data/Default/Code Cache',
            ],
        }
        for path in paths.get(tid, []):
            if not path.exists(): continue
            sz = self.dir_size(path)
            r.freed_bytes += sz
            if not dry:
                self.remove_dir_contents(path, r.rollback, tid)
        return r