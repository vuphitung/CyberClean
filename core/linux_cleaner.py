"""
CyberClean v2.0 — Linux Cleaner
Supports: pacman (Arch), apt (Ubuntu/Debian), dnf (Fedora), zypper (openSUSE)
"""
import subprocess, re, time, shutil
from pathlib import Path
from .base_cleaner import BaseCleaner, CleanTarget, CleanResult
from .os_detect import PKG_MANAGER, HAS_POLKIT, IS_ROOT, SUDO

JOURNAL_DAYS = 7
PACMAN_KEEP  = 1
TMP_DAYS     = 3

def run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode
    except Exception as e:
        return str(e), 1

def run_privileged(action, stdin_data=None):
    """Call polkit helper or fall back to sudo."""
    if HAS_POLKIT and not IS_ROOT:
        cmd = ['pkexec', '/usr/local/bin/cyber-clean-helper', action]
        try:
            r = subprocess.run(cmd, input=stdin_data, capture_output=True,
                               text=True, timeout=120)
            return r.stdout.strip(), r.returncode
        except Exception as e:
            return str(e), 1
    else:
        return run(f'{SUDO}{action}', timeout=120)

class LinuxCleaner(BaseCleaner):

    def get_targets(self):
        targets = []

        # Package manager cache
        if PKG_MANAGER == 'pacman':
            targets += [
                CleanTarget('pacman_cache',   'Pacman Cache',        f'Old package versions — keeps latest {PACMAN_KEEP}', 'safe',    needs_root=True),
                CleanTarget('pacman_broken',  'Broken Downloads',    'Interrupted download-* files in /var/cache/pacman', 'safe',    needs_root=True),
                CleanTarget('orphaned_pkgs',  'Orphaned Packages',   'Packages no longer needed by anything',             'caution', needs_root=True),
            ]
        elif PKG_MANAGER == 'apt':
            targets += [
                CleanTarget('apt_cache',      'APT Cache',           'Downloaded .deb packages in /var/cache/apt',         'safe',    needs_root=True),
                CleanTarget('apt_autoremove', 'APT Autoremove',      'Unused packages and old kernels',                    'caution', needs_root=True),
            ]
        elif PKG_MANAGER == 'dnf':
            targets += [
                CleanTarget('dnf_cache',      'DNF Cache',           'Downloaded RPM packages and metadata',               'safe',    needs_root=True),
            ]
        elif PKG_MANAGER == 'zypper':
            targets += [
                CleanTarget('zypper_cache',   'Zypper Cache',        'Downloaded packages in /var/cache/zypp',             'safe',    needs_root=True),
            ]

        # Common Linux targets
        targets += [
            CleanTarget('journal',       'Journal Logs',       f'systemd logs older than {JOURNAL_DAYS} days',       'safe'),
            CleanTarget('user_cache',    'User Cache (~/.cache)', 'App caches in home directory',                    'safe'),
            CleanTarget('chrome_cache',  'Chrome Cache',       'Browser cache — auto-rebuilds on next launch',       'safe'),
            CleanTarget('firefox_cache', 'Firefox Cache',      'Browser cache — auto-rebuilds on next launch',       'safe'),
            CleanTarget('thumbnails',    'Thumbnails',         'File manager previews — auto-rebuilds',              'safe'),
            CleanTarget('tmp_files',     'Temp Files',         f'/tmp files older than {TMP_DAYS} days, not in use', 'safe'),
        ]
        return targets

    def estimate(self, target_id: str) -> int:
        return self._run_target(target_id, dry=True).freed_bytes

    def clean(self, target_id: str, dry: bool = True) -> CleanResult:
        return self._run_target(target_id, dry=dry)

    def _run_target(self, tid: str, dry: bool) -> CleanResult:
        result = CleanResult(target_id=tid)
        try:
            if tid == 'pacman_cache':
                result = self._pacman_cache(dry)
            elif tid == 'pacman_broken':
                result = self._pacman_broken(dry)
            elif tid == 'orphaned_pkgs':
                result = self._orphaned_pkgs(dry)
            elif tid == 'apt_cache':
                result = self._apt_cache(dry)
            elif tid == 'apt_autoremove':
                result = self._apt_autoremove(dry)
            elif tid == 'dnf_cache':
                result = self._dnf_cache(dry)
            elif tid == 'zypper_cache':
                result = self._zypper_cache(dry)
            elif tid == 'journal':
                result = self._journal(dry)
            elif tid == 'user_cache':
                result = self._user_cache(dry)
            elif tid in ('chrome_cache', 'firefox_cache', 'thumbnails'):
                result = self._browser_or_thumbs(tid, dry)
            elif tid == 'tmp_files':
                result = self._tmp_files(dry)
        except Exception as e:
            result.error = str(e)
        return result

    # ── Pacman ────────────────────────────────────────────
    def _pacman_cache(self, dry):
        r = CleanResult('pacman_cache')
        out, _ = run(f'paccache -dk{PACMAN_KEEP} 2>/dev/null')
        m = re.search(r'([\d.]+)\s*(MiB|GiB|KiB)', out)
        sz = 0
        if m:
            v, u = float(m.group(1)), m.group(2)
            sz = int(v * (1024**2 if 'MiB' in u else 1024**3 if 'GiB' in u else 1024))
        if not dry:
            run_privileged(f'paccache -rk{PACMAN_KEEP} 2>/dev/null')
        r.freed_bytes = sz
        return r

    def _pacman_broken(self, dry):
        r = CleanResult('pacman_broken')
        broken = list(Path('/var/cache/pacman/pkg').glob('download-*'))
        r.freed_bytes = sum(f.stat().st_size for f in broken if f.exists())
        r.files_removed = len(broken)
        if not dry:
            run_privileged('find /var/cache/pacman/pkg -name "download-*" -delete 2>/dev/null')
        return r

    def _orphaned_pkgs(self, dry):
        r = CleanResult('orphaned_pkgs')
        out, _ = run('pacman -Qdtq 2>/dev/null')
        pkgs = [l.strip() for l in out.splitlines() if l.strip()]
        r.files_removed = len(pkgs)
        if pkgs and not dry:
            run_privileged(f'pacman -Rns --noconfirm {" ".join(pkgs)} 2>/dev/null')
            r.rollback.append({
                'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                'type': 'orphaned_packages',
                'path': ' '.join(pkgs),
                'size': 0,
                'note': f'Restore: sudo pacman -S {" ".join(pkgs)}'
            })
        return r

    # ── APT ───────────────────────────────────────────────
    def _apt_cache(self, dry):
        r = CleanResult('apt_cache')
        out, _ = run('du -sb /var/cache/apt/archives 2>/dev/null')
        try: r.freed_bytes = int(out.split()[0])
        except: pass
        if not dry:
            run_privileged('apt-get clean 2>/dev/null')
        return r

    def _apt_autoremove(self, dry):
        r = CleanResult('apt_autoremove')
        out, _ = run('apt-get autoremove --dry-run 2>/dev/null | grep "^Remv" | wc -l')
        try: r.files_removed = int(out)
        except: pass
        if not dry:
            run_privileged('apt-get autoremove -y 2>/dev/null')
        return r

    # ── DNF ───────────────────────────────────────────────
    def _dnf_cache(self, dry):
        r = CleanResult('dnf_cache')
        out, _ = run('du -sb /var/cache/dnf 2>/dev/null')
        try: r.freed_bytes = int(out.split()[0])
        except: pass
        if not dry:
            run_privileged('dnf clean all 2>/dev/null')
        return r

    # ── Zypper ────────────────────────────────────────────
    def _zypper_cache(self, dry):
        r = CleanResult('zypper_cache')
        out, _ = run('du -sb /var/cache/zypp 2>/dev/null')
        try: r.freed_bytes = int(out.split()[0])
        except: pass
        if not dry:
            run_privileged('zypper clean --all 2>/dev/null')
        return r

    # ── Journal ───────────────────────────────────────────
    def _journal(self, dry):
        r = CleanResult('journal')
        out, _ = run('journalctl --disk-usage 2>/dev/null')
        m = re.search(r'([\d.]+)\s*(M|G|K)', out)
        before = 0
        if m:
            v, u = float(m.group(1)), m.group(2)
            before = int(v * (1024**2 if u == 'M' else 1024**3 if u == 'G' else 1024))
        if not dry:
            run(f'journalctl --vacuum-time={JOURNAL_DAYS}d 2>/dev/null')
            out2, _ = run('journalctl --disk-usage 2>/dev/null')
            m2 = re.search(r'([\d.]+)\s*(M|G|K)', out2)
            after = 0
            if m2:
                v, u = float(m2.group(1)), m2.group(2)
                after = int(v * (1024**2 if u == 'M' else 1024**3 if u == 'G' else 1024))
            r.freed_bytes = max(before - after, 0)
        else:
            r.freed_bytes = max(before - 50*1024*1024, 0)
        return r

    # ── User cache ────────────────────────────────────────
    def _user_cache(self, dry):
        r = CleanResult('user_cache')
        cache = Path.home() / '.cache'
        # Exclude critical subdirs
        exclude = {'mesa_shader_cache', 'nvidia', 'fontconfig'}
        for item in cache.iterdir():
            if item.name in exclude: continue
            try:
                sz = self.dir_size(item)
                r.freed_bytes += sz
                if not dry:
                    r.rollback.append({
                        'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                        'type': 'user_cache',
                        'path': str(item),
                        'size': sz,
                        'note': 'auto-rebuilds'
                    })
                    if item.is_dir(): shutil.rmtree(item, ignore_errors=True)
                    else: item.unlink(missing_ok=True)
                    r.files_removed += 1
            except: pass
        return r

    # ── Browser / thumbnails ──────────────────────────────
    def _browser_or_thumbs(self, tid, dry):
        r = CleanResult(tid)
        paths = {
            'chrome_cache':  [Path.home()/'.cache/google-chrome', Path.home()/'.cache/chromium'],
            'firefox_cache': [Path.home()/'.cache/mozilla'],
            'thumbnails':    [Path.home()/'.cache/thumbnails'],
        }
        for path in paths.get(tid, []):
            if not path.exists(): continue
            sz = self.dir_size(path)
            r.freed_bytes += sz
            if not dry:
                self.remove_dir_contents(path, r.rollback, tid)
        return r

    # ── Tmp files ─────────────────────────────────────────
    def _tmp_files(self, dry):
        import time as _time
        r = CleanResult('tmp_files')
        now = _time.time()
        for f in Path('/tmp').iterdir():
            try:
                if (now - f.stat().st_mtime) / 86400 < TMP_DAYS: continue
                if f.is_socket() or f.is_block_device(): continue
                lsof, _ = run(f'lsof +D {f} 2>/dev/null | wc -l')
                if int(lsof or 0) > 0: continue
                sz = self.dir_size(f) if f.is_dir() else f.stat().st_size
                r.freed_bytes += sz
                r.files_removed += 1
                if not dry:
                    r.rollback.append({'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                       'type': 'tmp', 'path': str(f), 'size': sz,
                                       'note': 'tmp — cannot restore'})
                    if f.is_dir(): shutil.rmtree(f, ignore_errors=True)
                    else: f.unlink(missing_ok=True)
            except: pass
        return r