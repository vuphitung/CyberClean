"""
CyberClean — Linux Cleaner (3.1)
════════════════════════════════════════════════════════════════
Thiết kế:
  • AUTO   — tái tạo được, tick sẵn, được phép chạy nền (IdleScheduler).
  • REVIEW — liệt kê từng mục cho người dùng tự chọn; KHÔNG BAO GIỜ tick sẵn,
             KHÔNG BAO GIỜ chạy nền, KHÔNG BAO GIỜ đi qua clean(dry=False) —
             chỉ qua review_clean() sau khi người dùng đã tick từng mục.
  • Path-based targets nằm trong rules/linux.toml (rules → plan → execute có
    guard: tuổi · tiến trình · file đang mở · symlink · mount · socket).
  • Lệnh hệ thống (pacman/apt/dnf/journal...) chạy qua core/privileged.py →
    packaging/cyber-clean-helper, KHÔNG dùng shell, KHÔNG có lối 'raw'.

Hỗ trợ: pacman · apt · dnf (+ Fedora Atomic rpm-ostree) · zypper · xbps · apk · nix
Extras: Flatpak · Docker/Podman · yay/paru AUR cache · snap · journal
"""
import os
import re
import shutil
import stat
import subprocess
import time
from typing import Callable, Dict, List, Optional, Tuple

from . import engine as E
from . import privileged as P
from . import rules as R
from .base_cleaner import (BaseCleaner, PlanCleanerMixin, CleanTarget, CleanResult,
                           ReviewItem, ReviewScan)
from .os_detect import (PKG_MANAGER, HAS_FLATPAK, HAS_DOCKER, CONTAINER_TOOL, HAS_JOURNALCTL,
                        HAS_SNAP, HAS_XBPS, HAS_APK, HAS_NIX, HAS_RPM_OSTREE, real_uid)

JOURNAL_DAYS = 7
JOURNAL_MAX_MB = 500
PACMAN_KEEP = 2                     # giữ 2 bản gần nhất → còn đường downgrade
LOG_ROOT = '/var/log'
CRASH_ROOT = '/var/crash'
COREDUMP_ROOT = '/var/lib/systemd/coredump'
RECENT_SEC = 3600
ROTATED_RE = re.compile(r'(\.(gz|bz2|xz|zst|old|bak|archived)|\.\d{1,2})$')
PKG_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9+._:@-]{0,127}$')
DOCKER_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$')
FLATPAK_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$')


# ══════════════════════════════════════════════════════════════
# Subprocess helpers (argv only — never a shell)
# ══════════════════════════════════════════════════════════════

def _cmd(argv: List[str], timeout: int = 30, input_text: Optional[str] = None) -> Tuple[str, str, int]:
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, input=input_text,
                           env={**os.environ, 'LC_ALL': 'C', 'LANG': 'C'})
        return r.stdout, r.stderr, r.returncode
    except FileNotFoundError:
        return '', f'{argv[0]}: not found', 127
    except subprocess.TimeoutExpired:
        return '', 'timeout', 124
    except Exception as e:                                         # pragma: no cover
        return '', str(e), 1


_UNITS = {'': 1, 'B': 1, 'K': 1024, 'M': 1024**2, 'G': 1024**3, 'T': 1024**4,
          'KIB': 1024, 'MIB': 1024**2, 'GIB': 1024**3, 'TIB': 1024**4,
          'KB': 1000, 'MB': 1000**2, 'GB': 1000**3, 'TB': 1000**4}


def parse_size(text: str) -> int:
    """'1.2G' / '803.5 MB' / '12 MiB' / '4096' → bytes. 0 nếu không đọc được."""
    m = re.search(r'([\d]+(?:[.,]\d+)?)\s*([KMGT]?(?:i?B)?)\b', text or '', re.I)
    if not m:
        return 0
    try:
        v = float(m.group(1).replace(',', '.'))
    except ValueError:
        return 0
    return int(v * _UNITS.get(m.group(2).upper(), 1))


def ensure_privileged_session(log_cb=None) -> bool:
    """Giữ tên cũ cho ui_widgets — thực tế dùng P.ensure_session (kiểm tra bằng `ping`)."""
    return P.ensure_session(log_cb)


def run_privileged(action: str, *args: str, stdin: Optional[str] = None, timeout: int = 120):
    """(output, exit_code) — tương thích tên cũ nhưng KHÔNG còn lối 'raw'."""
    r = P.run_helper(action, *args, stdin=stdin, timeout=timeout)
    return (r.out if r.ok else r.message), r.code


def _dir_bytes(paths) -> int:
    total = 0
    for p in paths:
        ts = E.tree_stats(p)
        total += ts.size + ts.shared
    return total


def _rb(label: str, path: str, size: int, note: str = '') -> dict:
    return {'time': time.strftime('%Y-%m-%dT%H:%M:%S'), 'type': label, 'path': path, 'size': size,
            'note': note}


# ══════════════════════════════════════════════════════════════
# LinuxCleaner
# ══════════════════════════════════════════════════════════════

class LinuxCleaner(PlanCleanerMixin, BaseCleaner):

    def __init__(self):
        self.ctx = R.RuleContext.detect()
        E.set_owner_uid(real_uid())
        try:
            self.ruleset = R.load_default(self.ctx)
        except Exception as e:                       # luật built-in hỏng → app vẫn chạy, chỉ thiếu target
            self.ruleset = R.RuleSet()
            self._rules_error = str(e)
        else:
            self._rules_error = ''
        self._targets: Dict[str, CleanTarget] = {}
        self._refresh_targets()

    # ── target registry ────────────────────────────────────
    def _code_targets(self) -> List[CleanTarget]:
        t: List[CleanTarget] = []
        pm = PKG_MANAGER
        if pm == 'pacman':
            t += [
                CleanTarget('pacman_cache', 'Pacman Cache',
                            f'Old package versions — keeps the latest {PACMAN_KEEP} (needs pacman-contrib)',
                            'safe', needs_root=True),
                CleanTarget('pacman_broken', 'Broken Downloads',
                            'Interrupted download-* / *.part in the pacman cache (skipped while pacman runs)',
                            'safe', needs_root=True),
                CleanTarget('orphaned_pkgs', 'Orphaned Packages',
                            'Packages no longer needed by anything — pick which to remove',
                            'caution', needs_root=True, tier='review'),
            ]
        elif pm == 'apt':
            t += [
                CleanTarget('apt_cache', 'APT Cache', 'Downloaded .deb packages in /var/cache/apt',
                            'safe', needs_root=True),
                CleanTarget('apt_autoremove', 'APT Autoremove',
                            'Unused packages and old kernels — pick which to remove',
                            'caution', needs_root=True, tier='review'),
            ]
        elif pm == 'dnf':
            t += [
                CleanTarget('dnf_cache', 'DNF Cache', 'Downloaded RPM packages and metadata',
                            'safe', needs_root=True),
                CleanTarget('dnf_autoremove', 'DNF Autoremove',
                            'Unneeded dependencies — pick which to remove',
                            'caution', needs_root=True, tier='review'),
            ]
        elif pm == 'zypper':
            t.append(CleanTarget('zypper_cache', 'Zypper Cache', 'Downloaded packages in /var/cache/zypp',
                                 'safe', needs_root=True))
        elif pm == 'xbps' and HAS_XBPS:
            t += [
                CleanTarget('xbps_cache', 'XBPS Package Cache',
                            'Obsolete packages in /var/cache/xbps (xbps-remove -o)', 'safe', needs_root=True),
                CleanTarget('xbps_orphaned', 'XBPS Orphaned Packages',
                            'Packages no longer required (xbps-remove -O)', 'caution',
                            needs_root=True, tier='review'),
            ]
        elif pm == 'apk' and HAS_APK:
            t.append(CleanTarget('apk_cache', 'APK Cache', 'Package cache in /var/cache/apk (apk cache clean)',
                                 'safe', needs_root=True))
        elif pm == 'rpm-ostree' and HAS_RPM_OSTREE:
            t.append(CleanTarget('rpm_ostree', 'rpm-ostree Cache',
                                 'Base + rpm-md caches (rpm-ostree cleanup -bm) — deployments are kept',
                                 'safe', needs_root=True))
        elif pm == 'nix' and HAS_NIX:
            t.append(CleanTarget('nix_gc', 'Nix Garbage Collection',
                                 'Delete old user-profile generations and unreferenced store paths',
                                 'caution', tier='review'))

        if HAS_JOURNALCTL:
            t.append(CleanTarget('journal', 'Journal Logs',
                                 f'systemd logs older than {JOURNAL_DAYS} days (capped at {JOURNAL_MAX_MB} MB)',
                                 'safe', needs_root=True))
        t += [
            CleanTarget('system_logs', 'Old System Logs',
                        '/var/log rotated logs (.gz, .1, .old) — active logs kept', 'safe', needs_root=True),
            CleanTarget('crash_reports', 'Crash Reports',
                        '/var/crash dumps + ~/.local/share/apport + systemd coredumps (older than 1 h)',
                        'safe', needs_root=True),
            CleanTarget('empty_trash', 'Trash',
                        'Files you deleted — permanently removed only for the items YOU tick',
                        'caution', tier='review'),
        ]
        if HAS_FLATPAK:
            t.append(CleanTarget('flatpak', 'Flatpak Unused Runtimes',
                                 'Runtimes no installed app needs (user + system)', 'caution', tier='review'))
        if HAS_DOCKER:
            t.append(CleanTarget('docker', 'Docker/Podman',
                                 'Dangling images, stopped containers, build cache, unused volumes — pick items',
                                 'caution', tier='review'))
        if HAS_SNAP:
            t.append(CleanTarget('snap_old', 'Snap Old Revisions',
                                 'Disabled snap revisions only (current install kept)', 'caution',
                                 needs_root=True, tier='review'))
        return t

    def _refresh_targets(self) -> None:
        by: Dict[str, CleanTarget] = {}
        for td in self.ruleset.target_defs(self.ctx):
            by[td.id] = CleanTarget(td.id, td.name, td.desc, td.safety, needs_root=td.needs_root,
                                    tier=td.tier, scheduled=td.scheduled)
        for ct in self._code_targets():
            by[ct.id] = ct
        # crash_reports / system_logs có phần root → needs_root cho UI
        self._targets = by

    ORDER = ['pacman_cache', 'pacman_broken', 'apt_cache', 'dnf_cache', 'zypper_cache', 'xbps_cache',
             'apk_cache', 'rpm_ostree', 'aur_cache', 'journal', 'chromium_cache', 'firefox_cache',
             'thumbnails', 'pip_cache', 'tmp_files', 'system_logs', 'crash_reports',
             'orphaned_pkgs', 'apt_autoremove', 'dnf_autoremove', 'xbps_orphaned', 'flatpak',
             'flatpak_cache', 'docker', 'snap_old', 'nix_gc', 'dev_cache', 'app_cache', 'empty_trash']

    def get_targets(self) -> List[CleanTarget]:
        order = {tid: i for i, tid in enumerate(self.ORDER)}
        out = sorted(self._targets.values(), key=lambda t: (t.tier != 'auto', order.get(t.id, 999)))
        if not PKG_MANAGER:
            out.insert(0, CleanTarget(
                id='_unknown_distro_warn', name='⚠ Package Manager Not Detected',
                desc='Distro not recognized — package cache targets unavailable. Run: cat /etc/os-release',
                safety='caution', enabled=False, tier='auto', scheduled=False))
        return out

    # ── entry points ───────────────────────────────────────
    def estimate(self, target_id: str) -> int:
        return self.clean(target_id, dry=True).freed_bytes

    def clean(self, target_id: str, dry: bool = True, *, unattended: bool = False,
              plan: Optional[E.Plan] = None) -> CleanResult:
        result = CleanResult(target_id=target_id, dry=dry)
        if target_id.startswith('_'):
            result.error = 'Info-only target — nothing to clean'
            return result
        tgt = self._targets.get(target_id)
        if tgt is None:
            result.error = f'Unknown target: {target_id}'
            return result
        # Hàng rào cứng của tier — kể cả khi UI/scheduler gọi nhầm:
        if unattended and not tgt.scheduled:
            result.error = 'Not allowed to run unattended'
            return result
        if not dry and tgt.tier != 'auto':
            result.error = 'Review targets are cleaned item-by-item from the Review dialog'
            return result
        try:
            fn = self._handlers().get(target_id)
            if fn:
                return fn(dry, unattended)
            if tgt.tier == 'review' and not self.has_rules(target_id):       # chỉ để ước tính dung lượng
                scan = self.review_scan(target_id)
                result.freed_bytes = result.planned_bytes = sum(i.size for i in scan.items if not i.blocked)
                result.notes = list(scan.notes)
                return result
            if self.has_rules(target_id):
                return self.clean_rule_target(target_id, dry, unattended, plan, label=tgt.name)
            result.error = f'No implementation for target {target_id}'
        except Exception as e:
            result.error = str(e)
        return result

    def _handlers(self) -> Dict[str, Callable]:
        return {
            'pacman_cache': self._pacman_cache, 'pacman_broken': self._pacman_broken,
            'apt_cache': lambda d, u: self._simple_cache('apt_cache', d, ['/var/cache/apt/archives',
                                                         '/var/cache/apt/pkgcache.bin',
                                                         '/var/cache/apt/srcpkgcache.bin'], 'apt-clean'),
            'dnf_cache': lambda d, u: self._simple_cache('dnf_cache', d, ['/var/cache/dnf', '/var/cache/libdnf5'],
                                                         'dnf-clean'),
            'zypper_cache': lambda d, u: self._simple_cache('zypper_cache', d, ['/var/cache/zypp'], 'zypper-clean'),
            'xbps_cache': lambda d, u: self._simple_cache('xbps_cache', d, ['/var/cache/xbps'], 'xbps-clean-cache'),
            'apk_cache': lambda d, u: self._simple_cache('apk_cache', d, ['/var/cache/apk'], 'apk-clean'),
            'rpm_ostree': lambda d, u: self._simple_cache('rpm_ostree', d, [], 'rpm-ostree-cleanup'),
            'journal': self._journal,
            'system_logs': self._system_logs, 'crash_reports': self._crash_reports,
        }

    # ── mixin hooks ────────────────────────────────────────
    def build_plan(self, target_id: str, *, unattended: bool = False) -> E.Plan:
        plan = self.ruleset.plan(target_id, self.ctx, unattended=unattended) if self.has_rules(target_id) \
            else E.Plan(target_id)
        extra = {'crash_reports': self._crash_root_items, 'system_logs': self._log_items}.get(target_id)
        if extra:
            plan.items += extra()
        if target_id == 'empty_trash':
            return self._trash_plan()
        return plan

    def _execute(self, items: List[E.PlanItem]) -> E.ExecResult:
        """Mục có meta['helper'] chạy bằng helper root; phần còn lại qua engine."""
        mine = [i for i in items if not i.meta.get('helper')]
        helper = [i for i in items if i.meta.get('helper')]
        res = E.execute_plan(mine, guards=E.Guards(max_age=0)) if mine else E.ExecResult()
        meter = E.FreeSpaceMeter([i.path for i in helper]) if helper else None
        if meter:
            meter.begin()
        for it in helper:
            out = self._exec_helper_files(it)
            res.outcomes.append(out)
            if out.status in ('removed', 'partial'):
                res.freed += out.freed
                res.removed += out.removed
            if out.status in ('skipped', 'partial') and out.reason:
                res.skipped.append((it.path, out.reason))
            if out.status == 'failed':
                res.errors.append(f'{it.display}: {out.reason}')
        if meter:
            extra = meter.end()
            if extra is not None:
                res.measured = (res.measured or 0) + extra
        return res

    # ══════════════════════════════════════════════════════
    # Package-manager caches (helper chạy bằng root)
    # ══════════════════════════════════════════════════════
    def _simple_cache(self, tid: str, dry: bool, dirs: List[str], action: str) -> CleanResult:
        label = self._targets[tid].name
        r = CleanResult(tid, dry=dry)
        before = _dir_bytes([d for d in dirs if os.path.exists(d)])
        r.planned_bytes = before
        if dry:
            r.freed_bytes = before
            if before:
                r.rollback.append(_rb(label, ', '.join(d for d in dirs if os.path.exists(d)), before,
                                      'package cache — re-downloaded when needed'))
            return r
        h = P.run_helper(action, timeout=300)
        if not h.ok:
            r.error = h.message
            return r
        after = _dir_bytes([d for d in dirs if os.path.exists(d)])
        r.freed_bytes = max(before - after, 0)
        r.rollback.append(_rb(label, ', '.join(dirs), r.freed_bytes, 'package cache'))
        self._cache_invalidate(tid)
        return r

    @staticmethod
    def _pacman_cache_dirs() -> List[str]:
        out, _, code = _cmd(['pacman-conf', 'CacheDir'], 10)
        dirs = [l.strip().rstrip('/') for l in out.splitlines() if l.strip().startswith('/')] if code == 0 else []
        return dirs or ['/var/cache/pacman/pkg']

    @staticmethod
    def _pacman_busy() -> bool:
        if os.path.exists('/var/lib/pacman/db.lck'):
            return True
        return bool(E.Guards().running(['pacman']))

    def _pacman_cache(self, dry: bool, unattended: bool = False) -> CleanResult:
        r = CleanResult('pacman_cache', dry=dry)
        if not shutil.which('paccache'):
            # Trước đây: ước tính 0 B còn khi dọn thật báo nhầm "Need root". Nay nói đúng nguyên nhân.
            r.error = 'paccache not found — install pacman-contrib (sudo pacman -S pacman-contrib)'
            return r
        if self._pacman_busy():
            r.notes.append('pacman is running (db.lck) — skipped for now')
            return r
        dirs = [d for d in self._pacman_cache_dirs() if os.path.isdir(d)]
        before = _dir_bytes(dirs)
        est = 0
        for flags in (f'-dvk{PACMAN_KEEP}', '-duvk0'):
            out, _, _ = _cmd(['paccache', flags, *sum((['-c', d] for d in dirs), [])], 60)
            m = re.search(r'disk space saved:\s*([\d.,]+\s*[KMGT]?i?B)', out)
            if m:
                est += parse_size(m.group(1))
        r.planned_bytes = est
        if dry:
            r.freed_bytes = est
            if est:
                r.rollback.append(_rb('Pacman Cache', ', '.join(dirs), est,
                                      f'old versions beyond the latest {PACMAN_KEEP} + uninstalled packages'))
            return r
        h = P.run_helper('paccache', timeout=300)
        if not h.ok:
            r.error = h.message
            return r
        r.freed_bytes = max(before - _dir_bytes(dirs), 0)
        r.rollback.append(_rb('Pacman Cache', ', '.join(dirs), r.freed_bytes, 'old package versions'))
        self._cache_invalidate('pacman_cache')
        return r

    def _pacman_broken(self, dry: bool, unattended: bool = False) -> CleanResult:
        r = CleanResult('pacman_broken', dry=dry)
        if self._pacman_busy():
            r.notes.append('pacman is running (db.lck) — skipped for now')
            return r
        now = time.time()
        found: List[Tuple[str, int]] = []
        for d in self._pacman_cache_dirs():
            for e in E.iter_dir(d):
                if not (e.name.startswith('download-') or e.name.endswith('.part')):
                    continue
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if E.is_link_like(st) or now - st.st_mtime < RECENT_SEC:
                    continue
                ts = E.tree_stats(e.path)                    # download-XXXX/ là THƯ MỤC trên pacman ≥ 6
                found.append((e.path, ts.size + ts.shared))
        total = sum(s for _, s in found)
        r.planned_bytes = total
        if dry:
            r.freed_bytes = total
            r.rollback = [_rb('Broken Downloads', p, s, 'partial download') for p, s in found]
            return r
        if not found:
            return r
        h = P.run_helper('broken-downloads', timeout=120)
        if not h.ok:
            r.error = h.message
            return r
        gone = [(p, s) for p, s in found if not os.path.lexists(p)]
        r.freed_bytes = sum(s for _, s in gone)
        r.files_removed = len(gone)
        r.rollback = [_rb('Broken Downloads', p, s, 'partial download') for p, s in gone]
        self._cache_invalidate('pacman_broken')
        return r

    # ══════════════════════════════════════════════════════
    # Journal
    # ══════════════════════════════════════════════════════
    @staticmethod
    def _journal_usage() -> int:
        out, _, _ = _cmd(['journalctl', '--disk-usage'], 15)
        return parse_size(out.split('take up')[-1]) if 'take up' in out else parse_size(out)

    @staticmethod
    def _journal_estimate() -> int:
        """Ước tính từ file journal đã archive (đọc được cho mọi user): quá hạn + vượt trần dung lượng."""
        files: List[Tuple[float, int]] = []
        total = 0
        for base in ('/var/log/journal', '/run/log/journal'):
            for d in E.iter_dir(base):
                if not d.is_dir(follow_symlinks=False):
                    continue
                for f in E.iter_dir(d.path):
                    if not f.name.endswith(('.journal', '.journal~')):
                        continue
                    try:
                        st = f.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    total += st.st_size
                    if '@' in f.name:                          # archived: system@<id>.journal
                        files.append((st.st_mtime, st.st_size))
        cutoff = time.time() - JOURNAL_DAYS * 86400
        freed = sum(s for m, s in files if m < cutoff)
        remaining = total - freed
        cap = JOURNAL_MAX_MB * 1024 * 1024
        for m, s in sorted(f for f in files if f[0] >= cutoff):
            if remaining <= cap:
                break
            freed += s
            remaining -= s
        return freed

    def _journal(self, dry: bool, unattended: bool = False) -> CleanResult:
        r = CleanResult('journal', dry=dry)
        if not HAS_JOURNALCTL:
            r.error = 'journalctl not available (non-systemd / minimal init)'
            return r
        before = self._journal_usage()
        if dry:
            r.freed_bytes = r.planned_bytes = self._journal_estimate()
            if r.freed_bytes:
                r.rollback.append(_rb('Journal Logs', '/var/log/journal',
                                      r.freed_bytes, f'older than {JOURNAL_DAYS} days or above {JOURNAL_MAX_MB} MB'))
            return r
        # journalctl --vacuum chạy bằng quyền user KHÔNG dọn được journal hệ thống (và vẫn trả về 0),
        # nên trước đây nhánh helper hầu như không bao giờ được gọi. Luôn dùng helper.
        h = P.run_helper('journal', timeout=120)
        if not h.ok:
            r.error = h.message
            return r
        r.freed_bytes = max(before - self._journal_usage(), 0)
        r.rollback.append(_rb('Journal Logs', '/var/log/journal', r.freed_bytes, 'vacuumed'))
        self._cache_invalidate('journal')
        return r

    # ══════════════════════════════════════════════════════
    # Root-owned files listed by Python, VALIDATED again by the helper
    # ══════════════════════════════════════════════════════
    @staticmethod
    def _trusted(st) -> bool:
        return st.st_uid == 0 and not (st.st_mode & 0o022)

    def _files_item(self, root: str, files: List[Tuple[str, int, int, int, int]], label: str, helper: str,
                    note: str) -> Optional[E.PlanItem]:
        if not files:
            return None
        it = E.make_files_item(root, files, label=label, group=helper, note=note, basis='mtime')
        it.meta['helper'] = helper
        return it

    def _log_items(self) -> List[E.PlanItem]:
        if not os.path.isdir(LOG_ROOT):
            return []
        now = time.time()
        files: List[Tuple[str, int, int, int, int]] = []
        try:
            root_st = os.lstat(LOG_ROOT)
        except OSError:
            return []
        stack = [(LOG_ROOT, 0)]
        while stack:
            cur, depth = stack.pop()
            try:
                if cur != LOG_ROOT and not self._trusted(os.lstat(cur)):
                    continue                                   # helper cũng sẽ từ chối thư mục không đáng tin
            except OSError:
                continue
            for e in E.iter_dir(cur):
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if E.is_link_like(st) or '\n' in e.name:
                    continue
                if stat.S_ISDIR(st.st_mode):
                    if depth < 3 and st.st_dev == root_st.st_dev:
                        stack.append((e.path, depth + 1))
                elif stat.S_ISREG(st.st_mode) and ROTATED_RE.search(e.name) and st.st_nlink == 1:
                    if now - st.st_mtime >= RECENT_SEC:
                        files.append((e.path, st.st_mtime_ns, st.st_ino, st.st_size, st.st_ctime_ns))
        it = self._files_item(LOG_ROOT, files, '/var/log (rotated)', 'clean-rotated-logs', 'rotated / compressed logs')
        return [it] if it else []

    def _crash_root_items(self) -> List[E.PlanItem]:
        now = time.time()
        files: List[Tuple[str, int, int, int, int]] = []
        for root, ok_name in ((CRASH_ROOT, lambda n: n.endswith(('.crash', '.upload', '.uploaded'))),
                              (COREDUMP_ROOT, lambda n: n.startswith('core.'))):
            for e in E.iter_dir(root):
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if (stat.S_ISREG(st.st_mode) and not E.is_link_like(st) and ok_name(e.name)
                        and '\n' not in e.name and now - st.st_mtime >= RECENT_SEC):
                    files.append((e.path, st.st_mtime_ns, st.st_ino, st.st_size, st.st_ctime_ns))
        it = self._files_item('/var/crash', files, 'System crash dumps', 'clean-crash-dirs',
                              'crash / core dumps')
        return [it] if it else []

    def _exec_helper_files(self, item: E.PlanItem) -> E.Outcome:
        files = item.meta.get('files', [])
        keep = []
        for path, mtime_ns, ino, size, ctime_ns in files:
            try:
                st = os.lstat(path)
            except OSError:
                continue
            if st.st_ino == ino and st.st_mtime_ns == mtime_ns and st.st_ctime_ns == ctime_ns:
                keep.append((path, size))
        if not keep:
            return E.Outcome(item, 'gone', reason='nothing left to remove')
        h = P.run_helper(item.meta['helper'], stdin='\n'.join(p for p, _ in keep) + '\n', timeout=300)
        if not h.ok:
            return E.Outcome(item, 'failed', reason=h.message)
        gone = [(p, s) for p, s in keep if not os.path.lexists(p)]
        freed = sum(s for _, s in gone)
        status = 'removed' if len(gone) == len(keep) else 'partial'
        reason = '' if status == 'removed' else f'{len(keep) - len(gone)} files refused by the helper (not trusted / changed)'
        return E.Outcome(item, status, freed, len(gone), reason)

    def _system_logs(self, dry: bool, unattended: bool = False) -> CleanResult:
        plan = E.Plan('system_logs', self._log_items())
        return self.result_from_plan('system_logs', plan, dry=dry, label='Old System Logs')

    def _crash_reports(self, dry: bool, unattended: bool = False) -> CleanResult:
        plan = self.build_plan('crash_reports', unattended=unattended)
        return self.result_from_plan('crash_reports', plan, dry=dry, label='Crash Reports')

    # ══════════════════════════════════════════════════════
    # REVIEW tier
    # ══════════════════════════════════════════════════════
    def review_scan(self, target_id: str, progress_cb=None) -> ReviewScan:
        fn = {
            'orphaned_pkgs': self._rv_pacman_orphans, 'apt_autoremove': self._rv_apt_autoremove,
            'dnf_autoremove': self._rv_dnf_autoremove, 'xbps_orphaned': self._rv_xbps_orphans,
            'flatpak': self._rv_flatpak, 'docker': self._rv_docker, 'snap_old': self._rv_snap,
            'nix_gc': self._rv_nix, 'empty_trash': self._rv_trash, 'flatpak_cache': self._rv_flatpak_cache,
        }.get(target_id)
        tgt = self._targets.get(target_id)
        if tgt is None or tgt.tier != 'review':
            raise ValueError(f'{target_id} is not a review target')
        if fn:
            return fn()
        return PlanCleanerMixin.review_scan(self, target_id, progress_cb)

    def review_clean(self, target_id: str, item_ids: List[str], dry: bool = False) -> CleanResult:
        tgt = self._targets.get(target_id)
        if tgt is None or tgt.tier != 'review':
            r = CleanResult(target_id, dry=dry)
            r.error = f'{target_id} is not a review target'
            return r
        fn = {
            'orphaned_pkgs': self._rc_pacman_orphans, 'apt_autoremove': self._rc_apt_autoremove,
            'dnf_autoremove': self._rc_dnf_autoremove, 'xbps_orphaned': self._rc_xbps_orphans,
            'flatpak': self._rc_flatpak, 'docker': self._rc_docker, 'snap_old': self._rc_snap,
            'nix_gc': self._rc_nix, 'empty_trash': self._rc_trash,
        }.get(target_id)
        if fn:
            return fn(item_ids, dry)
        return PlanCleanerMixin.review_clean(self, target_id, item_ids, dry)

    # ── helpers for list-style review ─────────────────────
    @staticmethod
    def _pkg_items(names: List[str], sizes: Dict[str, int], detail: str = '') -> List[ReviewItem]:
        items = []
        for n in names:
            if PKG_RE.match(n):
                items.append(ReviewItem(id=n, label=n, size=sizes.get(n, 0), detail=detail,
                                        risk='low', payload={'pkg': n}))
        return sorted(items, key=lambda i: -i.size)

    def _simple_pkg_clean(self, target_id: str, names: List[str], dry: bool, helper_one: str,
                          size_of: Dict[str, int], label: str) -> CleanResult:
        r = CleanResult(target_id, dry=dry)
        names = [n for n in names if PKG_RE.match(n)]
        r.planned_bytes = sum(size_of.get(n, 0) for n in names)
        if dry:
            r.freed_bytes = r.planned_bytes
            r.rollback = [_rb(label, n, size_of.get(n, 0), 'package removal') for n in names]
            return r
        for n in names:
            h = P.run_helper(helper_one, n, timeout=300)
            if h.ok:
                r.freed_bytes += size_of.get(n, 0)
                r.files_removed += 1
                r.rollback.append(_rb(label, n, size_of.get(n, 0), 'package removed'))
            else:
                r.skipped.append((n, h.message))
                if not r.error:
                    r.error = f'{n}: {h.message}'
        return r

    # ── pacman orphans ──
    def _pacman_orphan_names(self) -> List[str]:
        out, _, _ = _cmd(['pacman', '-Qdtq'], 30)
        return [l.strip() for l in out.splitlines() if l.strip()]

    @staticmethod
    def _pacman_sizes(names: List[str]) -> Dict[str, int]:
        sizes: Dict[str, int] = {}
        if not names:
            return sizes
        out, _, _ = _cmd(['pacman', '-Qi', *names[:300]], 30)
        cur = ''
        for line in out.splitlines():
            if line.startswith('Name'):
                cur = line.split(':', 1)[1].strip()
            elif line.startswith('Installed Size') and cur:
                sizes[cur] = parse_size(line.split(':', 1)[1])
        return sizes

    def _rv_pacman_orphans(self) -> ReviewScan:
        names = self._pacman_orphan_names()
        scan = ReviewScan('orphaned_pkgs', permanent=True)
        scan.items = self._pkg_items(names, self._pacman_sizes(names), 'installed as a dependency, nothing needs it')
        scan.warning = ('Review the list: some orphans are things you use directly but installed as a dependency. '
                        'Removal uses pacman -Rns.')
        return scan

    def _rc_pacman_orphans(self, item_ids: List[str], dry: bool) -> CleanResult:
        r = CleanResult('orphaned_pkgs', dry=dry)
        current = set(self._pacman_orphan_names())
        names = [n for n in item_ids if n in current and PKG_RE.match(n)]
        sizes = self._pacman_sizes(names)
        r.planned_bytes = sum(sizes.values())
        if dry or not names:
            r.freed_bytes = r.planned_bytes
            r.rollback = [_rb('Orphaned Packages', n, sizes.get(n, 0), 'package removal') for n in names]
            return r
        h = P.run_helper('pacman-orphans', stdin='\n'.join(names) + '\n', timeout=600)
        if not h.ok:
            r.error = h.message
            return r
        r.freed_bytes, r.files_removed = r.planned_bytes, len(names)
        r.rollback = [_rb('Orphaned Packages', n, sizes.get(n, 0), 'package removed') for n in names]
        return r

    # ── apt autoremove ──
    def _apt_autoremove_names(self) -> List[str]:
        out, _, _ = _cmd(['apt-get', '-s', 'autoremove'], 60)
        return [m.group(1) for m in re.finditer(r'^Remv (\S+)', out, re.M)]

    @staticmethod
    def _dpkg_sizes(names: List[str]) -> Dict[str, int]:
        sizes: Dict[str, int] = {}
        if not names:
            return sizes
        out, _, _ = _cmd(['dpkg-query', '-W', '-f=${Package} ${Installed-Size}\n', *names[:400]], 30)
        for line in out.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].isdigit():
                sizes[parts[0]] = int(parts[1]) * 1024
        return sizes

    def _rv_apt_autoremove(self) -> ReviewScan:
        names = self._apt_autoremove_names()
        scan = ReviewScan('apt_autoremove')
        scan.items = self._pkg_items(names, self._dpkg_sizes(names), 'no longer required (apt autoremove)')
        scan.warning = 'Kernel images appear here too — the running kernel is never listed.'
        return scan

    def _rc_apt_autoremove(self, item_ids: List[str], dry: bool) -> CleanResult:
        current = set(self._apt_autoremove_names())
        names = [n for n in item_ids if n in current and PKG_RE.match(n)]
        sizes = self._dpkg_sizes(names)
        if names and set(names) == current and not dry:                # chọn hết → một giao dịch apt
            r = CleanResult('apt_autoremove', dry=False)
            h = P.run_helper('apt-autoremove', timeout=900)
            if not h.ok:
                r.error = h.message
                return r
            r.planned_bytes = r.freed_bytes = sum(sizes.values())
            r.files_removed = len(names)
            r.rollback = [_rb('APT Autoremove', n, sizes.get(n, 0), 'package removed') for n in names]
            return r
        return self._simple_pkg_clean('apt_autoremove', names, dry, 'apt-remove', sizes, 'APT Autoremove')

    # ── dnf autoremove ──
    def _dnf_unneeded(self) -> List[str]:
        out, _, code = _cmd(['dnf', 'repoquery', '--unneeded', '--queryformat', '%{name}\n'], 90)
        if code != 0:
            return []
        return sorted({l.strip() for l in out.splitlines() if PKG_RE.match(l.strip())})

    @staticmethod
    def _rpm_sizes(names: List[str]) -> Dict[str, int]:
        sizes: Dict[str, int] = {}
        if not names:
            return sizes
        out, _, _ = _cmd(['rpm', '-q', '--qf', '%{NAME} %{SIZE}\n', *names[:400]], 30)
        for line in out.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].isdigit():
                sizes[parts[0]] = int(parts[1])
        return sizes

    def _rv_dnf_autoremove(self) -> ReviewScan:
        names = self._dnf_unneeded()
        scan = ReviewScan('dnf_autoremove')
        scan.items = self._pkg_items(names, self._rpm_sizes(names), 'unneeded dependency')
        if not names:
            scan.notes.append('Nothing listed (or `dnf repoquery --unneeded` is unavailable).')
        return scan

    def _rc_dnf_autoremove(self, item_ids: List[str], dry: bool) -> CleanResult:
        current = set(self._dnf_unneeded())
        names = [n for n in item_ids if n in current and PKG_RE.match(n)]
        return self._simple_pkg_clean('dnf_autoremove', names, dry, 'dnf-remove', self._rpm_sizes(names),
                                      'DNF Autoremove')

    # ── xbps orphans ──
    def _xbps_orphans(self) -> List[str]:
        out, _, _ = _cmd(['xbps-remove', '-n', '-O'], 60)
        names = []
        for l in out.splitlines():
            m = re.match(r'^\s*(\S+?)-[\w.]+_\d+\b', l)
            if m and PKG_RE.match(m.group(1)):
                names.append(m.group(1))
        return sorted(set(names))

    def _rv_xbps_orphans(self) -> ReviewScan:
        names = self._xbps_orphans()
        scan = ReviewScan('xbps_orphaned')
        scan.items = self._pkg_items(names, {}, 'orphan (xbps-remove -O)')
        scan.notes.append('xbps removes all orphans in one transaction — select all to proceed.')
        return scan

    def _rc_xbps_orphans(self, item_ids: List[str], dry: bool) -> CleanResult:
        r = CleanResult('xbps_orphaned', dry=dry)
        current = set(self._xbps_orphans())
        names = [n for n in item_ids if n in current]
        if not names:
            return r
        if set(names) != current:
            r.error = 'xbps can only remove all orphans at once — select every item'
            return r
        r.files_removed = len(names)
        r.rollback = [_rb('XBPS Orphans', n, 0, 'package removal') for n in names]
        if dry:
            return r
        h = P.run_helper('xbps-orphans', timeout=600)
        if not h.ok:
            r.error, r.rollback, r.files_removed = h.message, [], 0
        return r

    # ── flatpak ──
    @staticmethod
    def _flatpak_unused() -> List[Tuple[str, str]]:
        for argv in (['flatpak', 'uninstall', '--unused', '--dry-run'],
                     ['flatpak', 'uninstall', '--unused', '--assumeno', '--noninteractive']):
            out, err, _ = _cmd(argv, 60)
            refs = []
            for l in (out + '\n' + err).splitlines():
                m = re.match(r'^\s*\d+\.\s+(\S+)\s+(\S+)', l)
                if m and FLATPAK_ID_RE.match(m.group(1)) and FLATPAK_ID_RE.match(m.group(2)):
                    refs.append((m.group(1), m.group(2)))
            if refs:
                return refs
        return []

    @staticmethod
    def _flatpak_sizes() -> Dict[Tuple[str, str], int]:
        out, _, _ = _cmd(['flatpak', 'list', '--runtime', '--columns=application,branch,size'], 30)
        sizes = {}
        for l in out.splitlines():
            parts = l.split('\t') if '\t' in l else re.split(r'\s{2,}', l.strip())
            if len(parts) >= 3:
                sizes[(parts[0].strip(), parts[1].strip())] = parse_size(parts[2])
        return sizes

    def _rv_flatpak(self) -> ReviewScan:
        refs = self._flatpak_unused()
        sizes = self._flatpak_sizes()
        scan = ReviewScan('flatpak')
        for rid, br in refs:
            scan.items.append(ReviewItem(id=f'{rid}//{br}', label=f'{rid}  ({br})', size=sizes.get((rid, br), 0),
                                         detail='unused runtime / extension', payload={'id': rid, 'branch': br}))
        scan.items.sort(key=lambda i: -i.size)
        if not refs:
            scan.notes.append('Nothing unused (or this flatpak version cannot list unused refs).')
        return scan

    def _rc_flatpak(self, item_ids: List[str], dry: bool) -> CleanResult:
        r = CleanResult('flatpak', dry=dry)
        current = {f'{a}//{b}' for a, b in self._flatpak_unused()}
        sizes = self._flatpak_sizes()
        for iid in item_ids:
            if iid not in current:
                continue
            rid, br = iid.split('//', 1)
            sz = sizes.get((rid, br), 0)
            r.planned_bytes += sz
            if dry:
                r.freed_bytes += sz
                continue
            _, err, code = _cmd(['flatpak', 'uninstall', '-y', '--noninteractive', f'{rid}//{br}'], 180)
            if code == 0:
                r.freed_bytes += sz
                r.files_removed += 1
                r.rollback.append(_rb('Flatpak', iid, sz, 'runtime removed'))
            else:
                r.skipped.append((iid, (err.strip().splitlines() or ['failed'])[-1]))
        return r

    def _rv_flatpak_cache(self) -> ReviewScan:
        return PlanCleanerMixin.review_scan(self, 'flatpak_cache')

    # ── docker / podman ──
    def _rv_docker(self) -> ReviewScan:
        tool = CONTAINER_TOOL
        scan = ReviewScan('docker')
        if not tool:
            scan.notes.append('No container runtime found.')
            return scan
        out, err, code = _cmd([tool, 'images', '-f', 'dangling=true', '--format',
                               '{{.ID}}\t{{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedSince}}'], 30)
        if code != 0 and 'permission denied' in (err or '').lower():
            scan.notes.append(f'Cannot talk to the {tool} daemon (permission denied) — add your user to the '
                              f'"{tool}" group or use rootless mode.')
            return scan
        for l in out.splitlines():
            p = l.split('\t')
            if len(p) >= 4 and DOCKER_ID_RE.match(p[0]):
                scan.items.append(ReviewItem(id=f'image:{p[0]}', label=f'image  {p[0][:12]}  {p[1]}',
                                             size=parse_size(p[2]), detail=f'dangling · created {p[3]}',
                                             payload={'kind': 'image', 'ref': p[0]}))
        out, _, _ = _cmd([tool, 'ps', '-a', '-f', 'status=exited', '-f', 'status=created', '--format',
                          '{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}'], 30)
        for l in out.splitlines():
            p = l.split('\t')
            if len(p) >= 4 and DOCKER_ID_RE.match(p[0]):
                scan.items.append(ReviewItem(id=f'container:{p[0]}', label=f'container  {p[1]}  ({p[2]})',
                                             detail=f'stopped · {p[3]} — its writable layer is deleted',
                                             risk='medium', payload={'kind': 'container', 'ref': p[0]}))
        out, _, _ = _cmd([tool, 'volume', 'ls', '-f', 'dangling=true', '--format', '{{.Name}}'], 30)
        for name in (l.strip() for l in out.splitlines()):
            if name and DOCKER_ID_RE.match(name):
                scan.items.append(ReviewItem(id=f'volume:{name}', label=f'volume  {name}',
                                             detail='NOT used by any container — may hold database / app data',
                                             risk='high', payload={'kind': 'volume', 'ref': name}))
        out, _, _ = _cmd([tool, 'system', 'df', '--format', '{{.Type}}\t{{.Reclaimable}}'], 30)
        for l in out.splitlines():
            p = l.split('\t')
            if len(p) == 2 and p[0].strip().lower().startswith('build cache') and parse_size(p[1]):
                scan.items.append(ReviewItem(id='buildcache:all', label='build cache  (all unused layers)',
                                             size=parse_size(p[1]), detail='re-built on the next docker build',
                                             payload={'kind': 'buildcache'}))
        scan.warning = 'Volumes are NOT recoverable. Nothing is selected by default.'
        scan.items.sort(key=lambda i: (-i.size, i.label))
        return scan

    def _rc_docker(self, item_ids: List[str], dry: bool) -> CleanResult:
        r = CleanResult('docker', dry=dry)
        tool = CONTAINER_TOOL
        if not tool:
            r.error = 'No container runtime found (docker/podman)'
            return r
        known = {i.id: i for i in self._rv_docker().items}
        for iid in item_ids:
            it = known.get(iid)
            if not it:
                continue
            kind, ref = it.payload.get('kind'), it.payload.get('ref', '')
            r.planned_bytes += it.size
            if dry:
                r.freed_bytes += it.size
                continue
            argv = {'image': [tool, 'rmi', ref], 'container': [tool, 'rm', ref],
                    'volume': [tool, 'volume', 'rm', ref],
                    'buildcache': [tool, 'builder', 'prune', '-f'] if tool == 'docker' else [tool, 'system', 'prune', '-f']
                    }.get(kind)
            if not argv or (ref and not DOCKER_ID_RE.match(ref)):
                continue
            _, err, code = _cmd(argv, 300)
            if code == 0:
                r.freed_bytes += it.size
                r.files_removed += 1
                r.rollback.append(_rb('Docker/Podman', it.label, it.size, f'{kind} removed'))
            else:
                r.skipped.append((it.label, (err.strip().splitlines() or ['failed'])[-1]))
        return r

    # ── snap ──
    @staticmethod
    def _snap_disabled() -> List[Tuple[str, str]]:
        out, _, code = _cmd(['snap', 'list', '--all'], 30)
        if code != 0:
            return []
        res = []
        for l in out.splitlines()[1:]:
            parts = l.split()
            if len(parts) >= 6 and 'disabled' in parts[-1].split(','):
                if re.match(r'^[a-z0-9][a-z0-9-]{0,39}$', parts[0]) and parts[2].isdigit():
                    res.append((parts[0], parts[2]))
        return res

    def _rv_snap(self) -> ReviewScan:
        scan = ReviewScan('snap_old')
        for name, rev in self._snap_disabled():
            try:
                size = os.stat(f'/var/lib/snapd/snaps/{name}_{rev}.snap').st_size       # kích thước thật, không đoán
            except OSError:
                size = 0
            scan.items.append(ReviewItem(id=f'{name}:{rev}', label=f'{name}  (revision {rev})', size=size,
                                         detail='disabled revision — only needed to roll back a refresh',
                                         payload={'name': name, 'rev': rev}))
        scan.items.sort(key=lambda i: -i.size)
        return scan

    def _rc_snap(self, item_ids: List[str], dry: bool) -> CleanResult:
        r = CleanResult('snap_old', dry=dry)
        known = {i.id: i for i in self._rv_snap().items}
        for iid in item_ids:
            it = known.get(iid)
            if not it:
                continue
            r.planned_bytes += it.size
            if dry:
                r.freed_bytes += it.size
                continue
            h = P.run_helper('snap-remove-rev', it.payload['name'], it.payload['rev'], timeout=300)
            if h.ok:
                r.freed_bytes += it.size
                r.files_removed += 1
                r.rollback.append(_rb('Snap', it.label, it.size, 'revision removed'))
            else:
                r.skipped.append((it.label, h.message))
        return r

    # ── nix ──
    def _rv_nix(self) -> ReviewScan:
        scan = ReviewScan('nix_gc')
        scan.items.append(ReviewItem(
            id='nix:gc30', label='User-profile generations older than 30 days + unreferenced store paths',
            detail='nix-collect-garbage --delete-older-than 30d', risk='medium', payload={'days': 30}))
        scan.notes.append('System generations (NixOS) need root: run `sudo nix-collect-garbage -d` yourself.')
        return scan

    def _rc_nix(self, item_ids: List[str], dry: bool) -> CleanResult:
        r = CleanResult('nix_gc', dry=dry)
        if 'nix:gc30' not in item_ids or dry:
            return r
        _, err, code = _cmd(['nix-collect-garbage', '--delete-older-than', '30d'], 1800)
        if code != 0:
            r.error = (err.strip().splitlines() or ['nix-collect-garbage failed'])[-1]
        else:
            r.rollback.append(_rb('Nix', 'user generations + store', 0, 'garbage collected'))
        return r

    # ── trash ──
    def _trash_dirs(self) -> List[str]:
        home = str(self.ctx.home)
        dirs = [os.path.join(self.ctx.expand('$XDG_DATA_HOME') or os.path.join(home, '.local/share'), 'Trash')]
        uid = real_uid()
        for base in ('/media', '/run/media', '/mnt'):
            for d1 in E.iter_dir(base):                                    # /media/<user>/<label>
                for d2 in E.iter_dir(d1.path):
                    for cand in (os.path.join(d2.path, f'.Trash-{uid}'), os.path.join(d2.path, '.Trash', str(uid))):
                        if os.path.isdir(os.path.join(cand, 'files')):
                            dirs.append(cand)
        return [d for d in dirs if os.path.isdir(os.path.join(d, 'files'))]

    @staticmethod
    def _trash_original(info_path: str) -> str:
        try:
            with open(info_path, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    if line.startswith('Path='):
                        from urllib.parse import unquote
                        return unquote(line[5:].strip())
        except OSError:
            pass
        return ''

    def _trash_plan(self) -> E.Plan:
        plan = E.Plan('empty_trash')
        guards = E.Guards()
        pol = E.Policy(min_age_sec=0, require_owner=True, allow_special=True)    # ổ lạ có thể có socket; rác là rác
        for tdir in self._trash_dirs():
            files_dir = os.path.join(tdir, 'files')
            info_dir = os.path.join(tdir, 'info')
            for e in E.iter_dir(files_dir):
                orig = self._trash_original(os.path.join(info_dir, e.name + '.trashinfo'))
                it, why = E.make_item(e.path, pol, guards=guards, group='trash', risk='medium',
                                      label=orig or e.name, note='permanently deleted — cannot be restored')
                if it is not None:
                    it.meta['info'] = os.path.join(info_dir, e.name + '.trashinfo')
                    it.meta['trash'] = tdir
                    plan.items.append(it)
                elif why and why != 'gone':
                    plan.skipped.append((e.path, why))
        return plan

    def _rv_trash(self) -> ReviewScan:
        plan = self._trash_plan()
        self._review_cache['empty_trash'] = (time.monotonic(), plan)
        scan = ReviewScan('empty_trash', permanent=True)
        items = sorted(plan.items, key=lambda i: -i.size)
        for it in items[:500]:
            scan.items.append(ReviewItem(id=it.id, label=it.display, size=it.size, files=it.files, newest=it.newest,
                                         detail=it.note, risk='medium', blocked=it.blocked,
                                         payload={'path': it.path}))
        rest = items[500:]
        if rest:
            scan.items.append(ReviewItem(id='__rest__', label=f'… and {len(rest)} more smaller items',
                                         size=sum(i.size for i in rest), files=sum(i.files for i in rest),
                                         detail='all remaining trash items', risk='medium',
                                         payload={'ids': [i.id for i in rest]}))
        scan.warning = 'Permanently deleted — NOT moved anywhere. Nothing is selected by default.'
        return scan

    def _rc_trash(self, item_ids: List[str], dry: bool) -> CleanResult:
        cached = self._review_cache.get('empty_trash')
        plan = cached[1] if cached and (time.monotonic() - cached[0]) < self.REVIEW_TTL else self._trash_plan()
        ids = set(item_ids)
        if '__rest__' in ids:
            top = {i.id for i in sorted(plan.items, key=lambda i: -i.size)[:500]}
            ids |= {i.id for i in plan.items if i.id not in top}
        sel = E.Plan('empty_trash', [i for i in plan.items if i.id in ids], list(plan.skipped))
        r = self.result_from_plan('empty_trash', sel, dry=dry, label='Trash')
        if not dry:
            for it in sel.items:
                if not os.path.lexists(it.path):
                    try:
                        os.unlink(it.meta['info'])
                    except OSError:
                        pass
            for tdir in {i.meta.get('trash') for i in sel.items if i.meta.get('trash')}:
                try:
                    os.unlink(os.path.join(tdir, 'directorysizes'))      # cache kích thước — được dựng lại
                except OSError:
                    pass
        return r
