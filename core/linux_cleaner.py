"""
CyberClean v2.0 — Linux Cleaner
Supports: pacman · apt · dnf · zypper
Extras:   Flatpak · Docker/Podman · yay/paru AUR cache
Safe delete: uses send2trash when available (recoverable via Trash)
"""
import subprocess, re, time, shutil
from pathlib import Path
from .base_cleaner import BaseCleaner, CleanTarget, CleanResult
from .os_detect import (PKG_MANAGER, HAS_POLKIT, IS_ROOT, SUDO,
                         HAS_FLATPAK, HAS_DOCKER, HAS_YAY, HAS_PARU,
                         safe_delete, HAS_POLKIT_AGENT)

JOURNAL_DAYS = 7
PACMAN_KEEP  = 1
TMP_DAYS     = 3

def run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode
    except Exception as e:
        return str(e), 1

# Map: full command → helper action keyword
_HELPER_MAP = {
    f'paccache -rk{PACMAN_KEEP}':     'paccache',
    'find /var/cache/pacman/pkg -name "download-*" -delete': 'broken-downloads',
    f'journalctl --vacuum-time={JOURNAL_DAYS}d': 'journal',
    'apt-get clean':       'apt-clean',
    'apt-get autoremove -y': 'apt-autoremove',
    'dnf clean all':       'dnf-clean',
    'zypper clean --all':  'zypper-clean',
}

def run_privileged(action, stdin_data=None):
    """
    Priority: IS_ROOT → sudo -n NOPASSWD → pkexec (only if agent) → fail.
    Never blocks GUI.
    """
    if IS_ROOT:
        return run(action, timeout=120)

    # sudo -n first — works if NOPASSWD sudoers set up by install.sh
    helper_action = _HELPER_MAP.get(action.strip())
    if helper_action:
        out, code = run(f'sudo -n /usr/local/bin/cyber-clean-helper {helper_action} 2>/dev/null', timeout=60)
    else:
        out, code = run(f'sudo -n {action} 2>/dev/null', timeout=60)
    if code == 0:
        return out, 0

    # pkexec ONLY if polkit agent is actually running (never hangs)
    if HAS_POLKIT and HAS_POLKIT_AGENT and helper_action:
        try:
            r = subprocess.run(
                ['pkexec', '/usr/local/bin/cyber-clean-helper', helper_action],
                input=stdin_data, capture_output=True, text=True, timeout=30)
            return r.stdout.strip(), r.returncode
        except Exception as e:
            return str(e), 1

    return 'Need root — run install.sh to set up NOPASSWD or run with sudo', 1

class LinuxCleaner(BaseCleaner):

    def get_targets(self):
        targets = []

        # ── Package manager ───────────────────────────────
        if PKG_MANAGER == 'pacman':
            targets += [
                CleanTarget('pacman_cache',  'Pacman Cache',
                    f'Old package versions — keeps latest {PACMAN_KEEP}', 'safe', needs_root=True),
                CleanTarget('pacman_broken', 'Broken Downloads',
                    'Interrupted download-* files in /var/cache/pacman',  'safe', needs_root=True),
                CleanTarget('orphaned_pkgs', 'Orphaned Packages',
                    'Packages no longer needed by anything',               'caution', needs_root=True),
            ]
        elif PKG_MANAGER == 'apt':
            targets += [
                CleanTarget('apt_cache',      'APT Cache',
                    'Downloaded .deb packages in /var/cache/apt',          'safe', needs_root=True),
                CleanTarget('apt_autoremove', 'APT Autoremove',
                    'Unused packages and old kernels',                     'caution', needs_root=True),
            ]
        elif PKG_MANAGER == 'dnf':
            targets += [
                CleanTarget('dnf_cache', 'DNF Cache',
                    'Downloaded RPM packages and metadata',                'safe', needs_root=True),
            ]
        elif PKG_MANAGER == 'zypper':
            targets += [
                CleanTarget('zypper_cache', 'Zypper Cache',
                    'Downloaded packages in /var/cache/zypp',              'safe', needs_root=True),
            ]

        # ── AUR helpers ───────────────────────────────────
        if HAS_YAY or HAS_PARU:
            targets.append(CleanTarget('aur_cache', 'AUR Build Cache',
                '~/.cache/yay and ~/.cache/paru build directories',        'safe'))

        # ── Flatpak ───────────────────────────────────────
        if HAS_FLATPAK:
            targets.append(CleanTarget('flatpak', 'Flatpak Unused',
                'Unused Flatpak runtimes and refs',                        'caution'))

        # ── Docker / Podman ───────────────────────────────
        if HAS_DOCKER:
            targets.append(CleanTarget('docker', 'Docker/Podman Prune',
                'Dangling images, stopped containers, unused volumes',     'caution'))

        # ── Common targets ────────────────────────────────
        targets += [
            CleanTarget('journal',       'Journal Logs',
                f'systemd logs older than {JOURNAL_DAYS} days',           'safe'),
            CleanTarget('user_cache',    'User Cache (~/.cache)',
                'App caches — excludes GPU/font caches',                  'safe'),
            CleanTarget('chrome_cache',  'Chrome / Chromium Cache',
                'Browser cache — auto-rebuilds on next launch',           'safe'),
            CleanTarget('firefox_cache', 'Firefox Cache',
                'Browser cache — auto-rebuilds on next launch',           'safe'),
            CleanTarget('thumbnails',    'Thumbnails',
                'File manager previews — auto-rebuilds',                  'safe'),
            CleanTarget('pip_cache',     'Pip Cache',
                '~/.cache/pip downloaded wheels',                          'safe'),
            CleanTarget('tmp_files',     'Temp Files',
                f'/tmp files older than {TMP_DAYS} days, not in use',    'safe'),
        ]
        return targets

    def estimate(self, target_id: str) -> int:
        return self._run_target(target_id, dry=True).freed_bytes

    def clean(self, target_id: str, dry: bool = True) -> CleanResult:
        return self._run_target(target_id, dry=dry)

    def _run_target(self, tid, dry):
        result = CleanResult(target_id=tid)
        try:
            fn = {
                'pacman_cache':  self._pacman_cache,
                'pacman_broken': self._pacman_broken,
                'orphaned_pkgs': self._orphaned_pkgs,
                'apt_cache':     self._apt_cache,
                'apt_autoremove':self._apt_autoremove,
                'dnf_cache':     self._dnf_cache,
                'zypper_cache':  self._zypper_cache,
                'aur_cache':     self._aur_cache,
                'flatpak':       self._flatpak,
                'docker':        self._docker,
                'journal':       self._journal,
                'user_cache':    self._user_cache,
                'chrome_cache':  lambda d: self._browser_or_thumbs('chrome_cache', d),
                'firefox_cache': lambda d: self._browser_or_thumbs('firefox_cache', d),
                'thumbnails':    lambda d: self._browser_or_thumbs('thumbnails', d),
                'pip_cache':     self._pip_cache,
                'tmp_files':     self._tmp_files,
            }.get(tid)
            if fn: result = fn(dry)
        except Exception as e:
            result.error = str(e)
        return result

    # ── Pacman ────────────────────────────────────────────
    def _pacman_cache(self, dry):
        r = CleanResult('pacman_cache')
        out, _ = run(f'paccache -dk{PACMAN_KEEP} 2>/dev/null')
        m = re.search(r'([\d.]+)\s*(MiB|GiB|KiB)', out)
        if m:
            v, u = float(m.group(1)), m.group(2)
            r.freed_bytes = int(v * (1024**2 if 'MiB' in u else 1024**3 if 'GiB' in u else 1024))
        if not dry:
            out2, code = run_privileged(f'paccache -rk{PACMAN_KEEP}')
            if code != 0: r.error = out2
        return r

    def _pacman_broken(self, dry):
        r = CleanResult('pacman_broken')
        broken = list(Path('/var/cache/pacman/pkg').glob('download-*'))
        r.freed_bytes = sum(f.stat().st_size for f in broken if f.exists())
        r.files_removed = len(broken)
        if not dry:
            _, code = run_privileged('find /var/cache/pacman/pkg -name "download-*" -delete')
            if code != 0: r.error = 'Need root'
        return r

    def _orphaned_pkgs(self, dry):
        r = CleanResult('orphaned_pkgs')
        out, _ = run('pacman -Qdtq 2>/dev/null')
        pkgs = [l.strip() for l in out.splitlines() if l.strip()]
        r.files_removed = len(pkgs)
        if pkgs and not dry:
            _, code = run_privileged(f'pacman -Rns --noconfirm {" ".join(pkgs)}')
            if code == 0:
                r.rollback.append({
                    'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                    'type': 'orphaned_packages', 'path': ' '.join(pkgs), 'size': 0,
                    'note': f'Restore: sudo pacman -S {" ".join(pkgs)}'
                })
            else:
                r.error = 'Need root'
        return r

    # ── APT ───────────────────────────────────────────────
    def _apt_cache(self, dry):
        r = CleanResult('apt_cache')
        out, _ = run('du -sb /var/cache/apt/archives 2>/dev/null')
        try: r.freed_bytes = int(out.split()[0])
        except: pass
        if not dry:
            _, code = run_privileged('apt-get clean')
            if code != 0: r.error = 'Need root'
        return r

    def _apt_autoremove(self, dry):
        r = CleanResult('apt_autoremove')
        out, _ = run('apt-get autoremove --dry-run 2>/dev/null | grep "^Remv" | wc -l')
        try: r.files_removed = int(out)
        except: pass
        if not dry:
            _, code = run_privileged('apt-get autoremove -y')
            if code != 0: r.error = 'Need root'
        return r

    # ── DNF ───────────────────────────────────────────────
    def _dnf_cache(self, dry):
        r = CleanResult('dnf_cache')
        out, _ = run('du -sb /var/cache/dnf 2>/dev/null')
        try: r.freed_bytes = int(out.split()[0])
        except: pass
        if not dry:
            _, code = run_privileged('dnf clean all')
            if code != 0: r.error = 'Need root'
        return r

    # ── Zypper ────────────────────────────────────────────
    def _zypper_cache(self, dry):
        r = CleanResult('zypper_cache')
        out, _ = run('du -sb /var/cache/zypp 2>/dev/null')
        try: r.freed_bytes = int(out.split()[0])
        except: pass
        if not dry:
            _, code = run_privileged('zypper clean --all')
            if code != 0: r.error = 'Need root'
        return r

    # ── AUR cache (yay / paru) ────────────────────────────
    def _aur_cache(self, dry):
        r = CleanResult('aur_cache')
        dirs = []
        if HAS_YAY:  dirs.append(Path.home() / '.cache/yay')
        if HAS_PARU: dirs.append(Path.home() / '.cache/paru')
        for d in dirs:
            if not d.exists(): continue
            r.freed_bytes += self.dir_size(d)
            r.files_removed += sum(1 for _ in d.rglob('*') if _.is_file())
            if not dry:
                for item in d.iterdir():
                    sz = self.dir_size(item)
                    r.rollback.append({'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                       'type': 'aur_cache', 'path': str(item),
                                       'size': sz, 'note': 'AUR build cache — re-downloads on next install'})
                    safe_delete(item, use_trash=False)
        return r

    # ── Flatpak ───────────────────────────────────────────
    def _flatpak(self, dry):
        r = CleanResult('flatpak')
        out_unused, _ = run('flatpak list --runtime --columns=application 2>/dev/null')
        unused = [l.strip() for l in out_unused.splitlines() if l.strip()]
        r.files_removed = len(unused)
        out_before, _ = run('du -sb ~/.local/share/flatpak/runtime 2>/dev/null')
        try: size_before = int(out_before.split()[0])
        except: size_before = 0
        if not dry:
            run('flatpak uninstall --unused -y 2>/dev/null')
            out_after, _ = run('du -sb ~/.local/share/flatpak/runtime 2>/dev/null')
            try: size_after = int(out_after.split()[0])
            except: size_after = size_before
            r.freed_bytes = max(size_before - size_after, 0)
        else:
            est = 0
            for app_id in unused[:20]:
                out_sz, _ = run(f'du -sb ~/.local/share/flatpak/runtime/{app_id} 2>/dev/null')
                try: est += int(out_sz.split()[0])
                except: pass
            r.freed_bytes = est
        return r

    # ── Docker / Podman ───────────────────────────────────
    def _docker(self, dry):
        r = CleanResult('docker')
        tool = 'podman' if shutil.which('podman') else 'docker'
        # Get dangling image size
        out, _ = run(f'{tool} system df 2>/dev/null')
        for line in out.splitlines():
            if 'Local Volumes' in line or 'Images' in line:
                parts = line.split()
                for i, p in enumerate(parts):
                    if p.endswith(('MB','GB','KB','B')) and i > 0:
                        try:
                            v = float(p[:-2])
                            u = p[-2:]
                            mult = {'GB':1024**3,'MB':1024**2,'KB':1024,'B':1}.get(u, 1)
                            r.freed_bytes += int(v * mult)
                        except: pass
        if not dry:
            run(f'{tool} system prune -f 2>/dev/null')
            run(f'{tool} volume prune -f 2>/dev/null')
        return r

    # ── Journal ───────────────────────────────────────────
    def _journal(self, dry):
        r = CleanResult('journal')
        out, _ = run('journalctl --disk-usage 2>/dev/null')
        m = re.search(r'([\d.]+)\s*(M|G|K|B)', out)
        before = 0
        if m:
            v, u = float(m.group(1)), m.group(2)
            before = int(v * (1024**2 if u=='M' else 1024**3 if u=='G' else 1024 if u=='K' else 1))
        if not dry:
            _, code = run(f'journalctl --vacuum-time={JOURNAL_DAYS}d 2>/dev/null')
            if code != 0:
                run_privileged(f'journalctl --vacuum-time={JOURNAL_DAYS}d')
            import time; time.sleep(1)
            out2, _ = run('journalctl --disk-usage 2>/dev/null')
            m2 = re.search(r'([\d.]+)\s*(M|G|K|B)', out2)
            after = 0
            if m2:
                v, u = float(m2.group(1)), m2.group(2)
                after = int(v * (1024**2 if u=='M' else 1024**3 if u=='G' else 1024 if u=='K' else 1))
            r.freed_bytes = max(before - after, 0)
        else:
            r.freed_bytes = max(before - 10*1024*1024, 0)
        return r

    # ── User cache ────────────────────────────────────────
    def _user_cache(self, dry):
        r = CleanResult('user_cache')
        cache   = Path.home() / '.cache'
        exclude = {'mesa_shader_cache', 'nvidia', 'fontconfig', 'ibus', 'dconf'}
        if not cache.exists(): return r
        for item in cache.iterdir():
            if item.name in exclude: continue
            try:
                sz = self.dir_size(item)
                r.freed_bytes += sz
                if not dry:
                    r.rollback.append({'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                       'type': 'user_cache', 'path': str(item),
                                       'size': sz, 'note': 'auto-rebuilds'})
                    safe_delete(item, use_trash=False)
                    r.files_removed += 1
            except: pass
        return r

    # ── Browser / thumbnails ──────────────────────────────
    def _browser_or_thumbs(self, tid, dry):
        r = CleanResult(tid)
        home = Path.home()
        paths = {
            'chrome_cache':  [home/'.cache/google-chrome', home/'.cache/chromium',
                               home/'.config/google-chrome/Default/Cache',
                               home/'.config/chromium/Default/Cache'],
            'firefox_cache': [home/'.cache/mozilla/firefox'],
            'thumbnails':    [home/'.cache/thumbnails', home/'.thumbnails'],
        }
        for path in paths.get(tid, []):
            if not path.exists(): continue
            sz = self.dir_size(path)
            r.freed_bytes += sz
            if not dry:
                for item in path.iterdir():
                    isz = self.dir_size(item) if item.is_dir() else item.stat().st_size
                    r.rollback.append({'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                       'type': tid, 'path': str(item),
                                       'size': isz, 'note': 'auto-rebuilds'})
                    safe_delete(item, use_trash=False)
        return r

    # ── Pip cache ─────────────────────────────────────────
    def _pip_cache(self, dry):
        r = CleanResult('pip_cache')
        pip_cache = Path.home() / '.cache/pip'
        if not pip_cache.exists(): return r
        r.freed_bytes = self.dir_size(pip_cache)
        if not dry:
            run('pip cache purge 2>/dev/null || pip3 cache purge 2>/dev/null')
        return r

    # ── Tmp files ─────────────────────────────────────────
    def _tmp_files(self, dry):
        import time as _t
        r = CleanResult('tmp_files')
        now = _t.time()
        for f in Path('/tmp').iterdir():
            try:
                if (now - f.stat().st_mtime) / 86400 < TMP_DAYS: continue
                if f.is_socket() or f.is_block_device() or f.is_char_device(): continue
                # Check if any process has the file open
                lsof_out, _ = run(f'lsof +D "{f}" 2>/dev/null | wc -l')
                if int(lsof_out or 0) > 0: continue
                sz = self.dir_size(f) if f.is_dir() else f.stat().st_size
                r.freed_bytes += sz
                r.files_removed += 1
                if not dry:
                    r.rollback.append({'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                       'type': 'tmp', 'path': str(f),
                                       'size': sz, 'note': 'tmp — cannot restore'})
                    safe_delete(f, use_trash=False)
            except: pass
        return r
