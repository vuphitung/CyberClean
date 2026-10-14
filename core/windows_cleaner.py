"""
CyberClean — Windows Cleaner (3.1)
════════════════════════════════════════════════════════════════

3.1 — tiers + shared engine (see core/base_cleaner.py, core/engine.py, rules/windows.toml):

  AUTO    win_temp · win_thumbcache · win_error_reports · win_dns  + browser caches (rules)
  REVIEW  win_recycle · win_prefetch · win_updates · win_delivery · win_font_cache · win_shader_cache ·
          win_winsxs · win_eventlog · win_crash_dumps + dev_cache (rules) — shown as explicit items,
          never pre-ticked, never run unattended.

  win_temp / win_error_reports go through the engine: age is judged by the NEWEST file inside an item
  (a folder an installer is still extracting into is skipped), junctions/symlinks are never followed,
  freed bytes are measured, locked files are "skipped", not errors.
  Per-browser targets (chrome/edge/brave/opera/vivaldi/coccoc) were replaced by one Chromium rule that
  also covers Electron apps; it only ever touches cache folders — never cookies / Local Storage / IndexedDB.

  Windows-only calls (DISM, wevtutil, services, MoveFileEx) are unchanged apart from: dosvc is restarted
  after cleaning, Delivery Optimization keeps its root folder (service ACLs), Windows Update cleaning is
  skipped while TiWorker/wusa/msiexec run, thumbcache files held by Explorer are reported as "deleted on
  next boot" instead of being counted as freed.

NOTE: this file could not be executed on a real Windows machine while producing 3.1.0.
"""

import os, re, shutil, subprocess, time
from pathlib import Path
from typing import Dict, List
from . import engine as E
from . import rules as R
from .base_cleaner import (BaseCleaner, PlanCleanerMixin, CleanTarget, CleanResult,
                           ReviewItem, ReviewScan)

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


def run_powershell(ps_script: str, timeout: int = 30):
    """
    Run a PowerShell script WITHOUT going through cmd.exe (shell=False,
    argv list). Safer than building `f'PowerShell -Command "...{path}..."'`
    strings and passing them through run_win(shell=True): that approach
    means a path gets parsed twice (once by cmd.exe, once by PowerShell)
    and any embedded path segment isn't escaped for either layer, so a
    filename/folder containing a single quote, backtick, or `&`/`|` can
    break the command or, in the worst case, get interpreted as a second
    command. Here PowerShell is invoked directly as the process, so there's
    only one layer of parsing to worry about (PowerShell's own quoting).
    """
    try:
        r = subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps_script],
            shell=False,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, creationflags=_NO_WIN,
            encoding='utf-8', errors='replace',
        )
        return r.stdout.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return f'timeout after {timeout}s', 1
    except Exception as e:
        return str(e), 1


def _ps_literal_path(path) -> str:
    """
    Escape a filesystem path for use inside a PowerShell single-quoted
    literal string. In PowerShell, a single quote inside a '...' literal is
    escaped by doubling it ('' ), same rule as SQL — NOT a backslash.
    Using this instead of raw f-string interpolation is what makes paths
    with apostrophes (e.g. "C:\\Users\\O'Brien\\...") or stray `$`, `&`,
    backtick characters safe to embed.
    """
    return str(path).replace("'", "''")


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


class WindowsCleaner(PlanCleanerMixin, BaseCleaner):
    """
    Tiers (see base_cleaner.py):
      auto   — win_temp, win_thumbcache, win_error_reports, win_dns + browser caches (rules/windows.toml)
      review — everything that stops services, forces a rebuild (slower next launch / next boot),
               deletes user data (Recycle Bin) or removes diagnostics (event logs, crash dumps).
               Shown as ONE item the user must explicitly tick; never run in the background.
    Untested on a real Windows box in this build — the Windows-only calls (DISM, wevtutil, services,
    MoveFileEx) are unchanged; what changed is tiering, guards (age/lock/running/junction) and
    reporting. Rule-driven caches go through the same engine as Linux (unit-tested).
    """

    # DISM component-store analysis (win_winsxs) can take 10-40s on its own
    # and the store barely changes minute to minute, so give it a much
    # longer cache TTL than the 60s default — no point re-running DISM every
    # time the user re-opens Smart Clean within the same session.
    TTL_OVERRIDES = {
        'win_winsxs': 900,   # 15 min
    }

    def __init__(self):
        self.ctx = R.RuleContext.detect()
        try:
            self.ruleset = R.load_default(self.ctx)
            self._rules_error = ''
        except Exception as e:                          # luật hỏng → vẫn chạy phần còn lại
            self.ruleset = R.RuleSet()
            self._rules_error = str(e)
        self._targets: Dict[str, CleanTarget] = {}
        self._refresh_targets()

    # ── target registry ─────────────────────────────────
    def _code_targets(self) -> List[CleanTarget]:
        return [
            CleanTarget('win_temp', 'Windows Temp',
                '%TEMP% and C:\\Windows\\Temp — items untouched for 24 h+, not locked, not in a protected app dir',
                'safe'),
            CleanTarget('win_thumbcache', 'Thumbnail Cache',
                'Explorer thumbcache_*.db — auto-rebuilds', 'safe', scheduled=False),
            CleanTarget('win_error_reports', 'Windows Error Reports',
                'WER report archives older than 7 days', 'safe'),
            CleanTarget('win_dns', 'DNS Cache',
                'Flush the DNS resolver cache (frees no disk space)', 'safe', needs_root=True, scheduled=False),
            # ── review: one explicit opt-in item each ──
            CleanTarget('win_recycle', 'Recycle Bin',
                'Permanently empties the Recycle Bin on all drives', 'caution', tier='review'),
            CleanTarget('win_prefetch', 'Prefetch Cache',
                'App-launch prefetch (.pf older than 7 days) — apps start slower once while it rebuilds',
                'caution', needs_root=True, tier='review'),
            CleanTarget('win_updates', 'Windows Update Cache',
                'SoftwareDistribution\\Download — stops Windows Update services while cleaning',
                'caution', needs_root=True, tier='review'),
            CleanTarget('win_delivery', 'Delivery Optimization',
                'Windows Update P2P cache — stops the DoSvc service while cleaning',
                'caution', needs_root=True, tier='review'),
            CleanTarget('win_font_cache', 'Font Cache',
                'FontCache*.dat — rebuilt on next boot (troubleshooting item)', 'caution',
                needs_root=True, tier='review'),
            CleanTarget('win_shader_cache', 'GPU Shader Cache',
                'DirectX/GPU shader caches — first launch of each game stutters while it rebuilds',
                'caution', tier='review'),
            CleanTarget('win_winsxs', 'WinSxS Cleanup',
                'DISM removes superseded components only — slow, may need a reboot', 'caution',
                needs_root=True, tier='review'),
            CleanTarget('win_eventlog', 'Event Logs',
                'Clears ALL Windows Event Viewer logs (wevtutil) — removes diagnostics', 'caution',
                needs_root=True, tier='review'),
            CleanTarget('win_crash_dumps', 'Crash Dumps (Minidump)',
                'Minidump + MEMORY.DMP + CrashDumps — the only evidence of a BSOD', 'caution',
                needs_root=True, tier='review'),
        ]

    def _refresh_targets(self) -> None:
        by: Dict[str, CleanTarget] = {}
        for td in self.ruleset.target_defs(self.ctx):
            by[td.id] = CleanTarget(td.id, td.name, td.desc, td.safety, needs_root=td.needs_root,
                                    tier=td.tier, scheduled=td.scheduled)
        for ct in self._code_targets():
            by[ct.id] = ct
        self._targets = by

    ORDER = ['win_temp', 'chromium_cache', 'firefox_cache', 'win_thumbcache', 'win_error_reports', 'win_dns',
             'win_recycle', 'win_prefetch', 'win_updates', 'win_delivery', 'win_font_cache',
             'win_shader_cache', 'win_winsxs', 'win_eventlog', 'win_crash_dumps', 'dev_cache']

    def get_targets(self):
        order = {tid: i for i, tid in enumerate(self.ORDER)}
        return sorted(self._targets.values(), key=lambda t: (t.tier != 'auto', order.get(t.id, 999)))

    def estimate(self, target_id):
        return self.clean(target_id, dry=True).freed_bytes

    def clean(self, target_id, dry=True, *, unattended=False, plan=None):
        r = CleanResult(target_id=target_id, dry=dry)
        tgt = self._targets.get(target_id)
        if tgt is None:
            r.error = f'Unknown target: {target_id}'
            return r
        if unattended and not tgt.scheduled:
            r.error = 'Not allowed to run unattended'
            return r
        if not dry and tgt.tier != 'auto':
            r.error = 'Review targets are cleaned from the Review dialog'
            return r
        return self._run_target(target_id, dry, unattended, plan)

    def _run_target(self, tid, dry, unattended=False, plan=None):
        r = CleanResult(target_id=tid, dry=dry)
        try:
            fn = {
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
                'win_crash_dumps':   self._win_crash_dumps,
            }.get(tid)
            if fn:
                r = fn(dry)
                r.dry = dry
            elif self.has_rules(tid) or tid in ('win_temp', 'win_error_reports'):
                label = self._targets[tid].name if tid in self._targets else tid
                r = self.clean_rule_target(tid, dry, unattended, plan, label=label)
            else:
                r.error = f'No implementation for target {tid}'
        except Exception as e:
            r.error = str(e)
        return r

    # ── plans for engine-driven targets ───────────────────
    def build_plan(self, target_id, *, unattended=False):
        if target_id == 'win_temp':
            return self._temp_plan(unattended)
        if target_id == 'win_error_reports':
            return self._wer_plan(unattended)
        return PlanCleanerMixin.build_plan(self, target_id, unattended=unattended)

    # ── review (monolithic targets = a single explicit item) ──
    _MONOLITH_RISK = {'win_recycle': 'high', 'win_eventlog': 'high', 'win_crash_dumps': 'medium'}

    def review_scan(self, target_id, progress_cb=None):
        tgt = self._targets.get(target_id)
        if tgt is None or tgt.tier != 'review':
            raise ValueError(f'{target_id} is not a review target')
        if self.has_rules(target_id):
            return PlanCleanerMixin.review_scan(self, target_id, progress_cb)
        est = self._run_target(target_id, True)
        scan = ReviewScan(target_id, permanent=target_id != 'win_prefetch')
        scan.items.append(ReviewItem(
            id='all', label=tgt.name, size=est.freed_bytes, files=est.files_removed, detail=tgt.desc,
            risk=self._MONOLITH_RISK.get(target_id, 'medium'),
            blocked=est.error or '', payload={}))
        scan.notes = list(est.notes)
        if target_id in ('win_recycle', 'win_eventlog'):
            scan.warning = 'This cannot be undone. Nothing is selected by default.'
        return scan

    def review_clean(self, target_id, item_ids, dry=False):
        tgt = self._targets.get(target_id)
        if tgt is None or tgt.tier != 'review':
            r = CleanResult(target_id, dry=dry)
            r.error = f'{target_id} is not a review target'
            return r
        if self.has_rules(target_id):
            return PlanCleanerMixin.review_clean(self, target_id, item_ids, dry)
        if 'all' not in item_ids:
            return CleanResult(target_id, dry=dry)
        r = self._run_target(target_id, dry)
        r.dry = dry
        if not dry:
            self._cache_invalidate(target_id)
        return r

    # ── Temp ──────────────────────────────────────────────────
    _TEMP_SKIP_DIR_PREFIXES = (
        'scoped_dir', 'chrome_', 'msedge_', 'discord',
        'vscode', 'electron', 'squirrel',
        'tmp', 'clr', 'msi', 'msp',
    )
    _TEMP_SKIP_EXTENSIONS = {'.lnk', '.lock', '.msi'}

    @classmethod
    def _temp_item_should_skip(cls, item, now: float, free_bytes) -> bool:
        """
        Single source of truth for "should this %TEMP% item be left alone?" —
        used by BOTH the dry-run estimate and the real clean. Previously this
        logic was duplicated in two places and had drifted: the real-clean
        branch had a low-disk-space guard (keep files <2 days old when the
        drive has <2GB free, since Chrome/Discord update-extraction writes
        there) that the dry-run branch didn't apply. That meant the
        estimated size shown to the user could be *higher* than what a real
        clean actually freed whenever the disk was nearly full — confusing
        and makes the app look untrustworthy. Now both paths call this same
        function, so the number shown always matches the number delivered.
        """
        try:
            mtime = item.stat().st_mtime
        except OSError:
            return True
        age_secs = now - mtime
        if age_secs < 86400:
            return True
        # Disk nearly full: Chrome/Discord etc. extract updates into %TEMP%.
        # Only touch files older than 2 days in that case.
        if free_bytes is not None and free_bytes < 2 * 1024**3 and age_secs < 172800:
            return True
        if item.is_dir() and item.name.lower().startswith(cls._TEMP_SKIP_DIR_PREFIXES):
            return True
        if item.is_file() and item.suffix.lower() in cls._TEMP_SKIP_EXTENSIONS:
            return True
        return False

    def _temp_dirs(self) -> List[Path]:
        dirs, seen = [], set()
        for d in (_expand_env_path('TEMP', 'C:/Windows/Temp'), _expand_env_path('TMP', 'C:/Windows/Temp'),
                  Path('C:/Windows/Temp'), Path(os.environ.get('SystemRoot', 'C:\\Windows')) / 'Temp'):
            key = str(d).lower().replace('/', '\\').rstrip('\\')
            if key in seen or key in ('c:', 'c:\\windows', 'c:\\users'):
                continue
            seen.add(key)
            if d.exists():
                dirs.append(d)
        return dirs

    def _temp_plan(self, unattended: bool) -> "E.Plan":
        """
        Cùng một bộ guard cho dry-run và chạy thật. Khác bản cũ:
          • tuổi tính theo thứ MỚI NHẤT bên trong (không chỉ mtime thư mục cấp 1) —
            thư mục installer đang giải nén sẽ không bị xóa nữa;
          • junction/symlink không bị đi theo (size không còn tính theo đích của junction);
          • số byte 'đã giải phóng' đo thật, không cộng cả phần xóa không được.
        """
        plan = E.Plan('win_temp')
        guards = E.Guards()
        now = time.time()
        for d in self._temp_dirs():
            try:
                free_bytes = shutil.disk_usage(str(d.anchor)).free
            except OSError:
                free_bytes = None
            base_age = 3 * 86400 if unattended else 86400
            if free_bytes is not None and free_bytes < 2 * 1024**3:
                base_age = max(base_age, 172800)       # đĩa gần đầy: Chrome/Discord giải nén update vào %TEMP%
            pol = E.Policy(min_age_sec=base_age)
            for e in E.iter_dir(d):
                name = e.name.lower()
                try:
                    is_dir = e.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                if is_dir and name.startswith(self._TEMP_SKIP_DIR_PREFIXES):
                    continue
                if not is_dir and Path(e.name).suffix.lower() in self._TEMP_SKIP_EXTENSIONS:
                    continue
                item, why = E.make_item(e.path, pol, now=now, guards=guards, group='win_temp',
                                        label=e.path, note='temp file — safe to remove')
                if item is not None:
                    plan.items.append(item)
                elif why and why != 'gone':
                    plan.skipped.append((e.path, why))
        return plan

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
        busy = E.Guards().running(['tiworker', 'wusa', 'msiexec', 'trustedinstaller'])
        if busy:
            # Dừng dịch vụ Windows Update giữa lúc đang cài update có thể làm hỏng trạng thái servicing.
            r.notes.append(f'{busy} is running (an update/installer is in progress) — try again later.')
            r.freed_bytes = 0
            return r
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
                    _start_svc('dosvc')               # đã dừng ở trên — trước đây không bao giờ bật lại
                r.freed_bytes = _real_freed(size_before, sd)
            else:
                _start_svc('bits')
                _start_svc('wuauserv')
                _start_svc('dosvc')
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
                for child in E.iter_dir(do_path):          # giữ thư mục gốc: nó mang ACL riêng của dịch vụ
                    try:
                        E.remove_path(child.path)
                    except OSError:
                        pass
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
            delayed = 0
            delayed_bytes = 0
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
                            delayed += 1
                            delayed_bytes += sz
                            r.rollback.append({
                                'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                'type': 'thumbcache', 'path': str(f),
                                'size': 0, 'note': 'scheduled for deletion on next boot',
                            })
                except OSError:
                    pass

            # Chỉ tính phần ĐÃ giải phóng. Phần bị Explorer giữ không phải lỗi và chưa giải phóng
            # cho tới khi khởi động lại → ghi chú (không còn là r.error màu đỏ, không còn cộng vào freed).
            r.freed_bytes   = deleted
            r.files_removed = len([f for f in files if not f.exists()])
            if delayed:
                r.notes.append(
                    f'{delayed} file(s) ({delayed_bytes // (1024 * 1024)} MB) are held by Explorer and will be '
                    'deleted on the next Windows boot — that space is NOT freed yet.')
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
    def _wer_plan(self, unattended: bool) -> "E.Plan":
        plan = E.Plan('win_error_reports')
        guards = E.Guards()
        _local = os.environ.get('LOCALAPPDATA', '')
        wer_dirs = []
        if _local:
            wer_dirs += [Path(_local) / 'Microsoft/Windows/WER/ReportArchive',
                         Path(_local) / 'Microsoft/Windows/WER/ReportQueue']
        wer_dirs += [Path('C:/ProgramData/Microsoft/Windows/WER/ReportArchive'),
                     Path('C:/ProgramData/Microsoft/Windows/WER/ReportQueue')]
        pol = E.Policy(min_age_sec=7 * 86400)
        for d in wer_dirs:
            if not d.exists():
                continue
            for e in E.iter_dir(d):
                item, why = E.make_item(e.path, pol, guards=guards, group='win_error_reports',
                                        label=e.path, note='crash report — safe to remove')
                if item is not None:
                    plan.items.append(item)
        return plan

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
                            # Attempt via PowerShell — path is escaped for
                            # PowerShell's own quoting rules (see
                            # _ps_literal_path) and run directly (shell=False),
                            # not built as a raw cmd.exe string.
                            run_powershell(
                                f"Remove-Item -Force -LiteralPath '{_ps_literal_path(f)}' -EA SilentlyContinue"
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
