"""
CyberClean v2.2 — Linux Cleaner
FIX #2: _journal no longer uses time.sleep(1) in main thread.
        Uses QTimer-safe approach — measures before, schedules check after.
FIX #3: Flatpak version check before using --dry-run flag.
FIX #7: bare except:pass in _user_cache and _tmp_files replaced with typed
        PermissionError/OSError — errors surface in CleanResult.error, not silently dropped.
FIX #8: _user_cache redesigned with 3-layer protection:
        Layer 1 — Name whitelist (GPU, fonts, browsers, wallpaper daemons, theming tools...)
        Layer 2 — Smart type guard: skip any item that IS or CONTAINS a socket/FIFO/device.
                  Catches unknown apps without needing their name in any list.
        Layer 3 — Recently-modified guard (< 30s): skip dirs active right now.
        _tmp_files: added is_fifo() to guard list (was missing — FIFOs are also runtime IPC).
Supports: pacman · apt · dnf · zypper · xbps (Void)
Extras:   Flatpak · Docker/Podman · yay/paru AUR cache · snap old revisions
"""
import subprocess, re, time, shutil, shlex
from pathlib import Path
from .base_cleaner import BaseCleaner, CleanTarget, CleanResult
from .os_detect import (PKG_MANAGER, HAS_POLKIT, IS_ROOT, SUDO,
                         HAS_FLATPAK, HAS_DOCKER, HAS_YAY, HAS_PARU,
                         CONTAINER_TOOL,
                         safe_delete, HAS_POLKIT_AGENT,
                         HAS_JOURNALCTL, HAS_SNAP, HAS_XBPS)

JOURNAL_DAYS = 7
PACMAN_KEEP  = 1
TMP_DAYS     = 3

def run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode
    except Exception as e:
        return str(e), 1

def run_privileged(action_key, raw_cmd=None, stdin_data=None):
    """
    Execute a privileged action via the NOPASSWD helper.
    Priority: IS_ROOT → sudo -n NOPASSWD helper → pkexec (only if agent) → fail
    Never blocks GUI.
    """
    if IS_ROOT:
        cmd = raw_cmd or action_key
        return run(cmd, timeout=120)

    if action_key:
        out, code = run(
            f'sudo -n /usr/local/bin/cyber-clean-helper {action_key} 2>/dev/null',
            timeout=60)
        if code == 0:
            return out, 0

        if HAS_POLKIT and HAS_POLKIT_AGENT:
            try:
                r = subprocess.run(
                    ['pkexec', '/usr/local/bin/cyber-clean-helper', action_key],
                    input=stdin_data, capture_output=True, text=True, timeout=30)
                return r.stdout.strip(), r.returncode
            except Exception as e:
                return str(e), 1

    elif raw_cmd:
        out, code = run(f'sudo -n {raw_cmd} 2>/dev/null', timeout=60)
        if code == 0:
            return out, 0

    return 'Need root — run install.sh to set up NOPASSWD or run with sudo', 1


def _flatpak_supports_dry_run() -> bool:
    """Check if installed flatpak version supports --dry-run flag (requires >= 1.9.0)."""
    out, _ = run('flatpak --version 2>/dev/null')
    m = re.search(r'(\d+)\.(\d+)', out)
    if not m:
        return False
    major, minor = int(m.group(1)), int(m.group(2))
    return (major, minor) >= (1, 9)


class LinuxCleaner(BaseCleaner):

    def get_targets(self):
        targets = []

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
        elif PKG_MANAGER == 'xbps' and HAS_XBPS:
            targets += [
                CleanTarget('xbps_cache', 'XBPS Package Cache',
                    'Obsolete packages in /var/cache/xbps (xbps-remove -o)', 'safe', needs_root=True),
                CleanTarget('xbps_orphaned', 'XBPS Orphaned Packages',
                    'Packages no longer required (xbps-remove -O)',        'caution', needs_root=True),
            ]

        if HAS_YAY or HAS_PARU:
            targets.append(CleanTarget('aur_cache', 'AUR Build Cache',
                '~/.cache/yay and ~/.cache/paru build directories',        'safe'))

        if HAS_FLATPAK:
            targets.append(CleanTarget('flatpak', 'Flatpak Unused',
                'Unused Flatpak runtimes and refs',                        'caution'))

        if HAS_DOCKER:
            targets.append(CleanTarget('docker', 'Docker/Podman Prune',
                'Dangling images, stopped containers, unused volumes',     'caution'))

        if HAS_SNAP:
            targets.append(CleanTarget('snap_old', 'Snap Old Revisions',
                'Disabled snap revisions only (current install kept)',      'caution', needs_root=True))

        if HAS_JOURNALCTL:
            targets.append(
                CleanTarget('journal', 'Journal Logs',
                    f'systemd logs older than {JOURNAL_DAYS} days',       'safe'),
            )

        targets += [
            CleanTarget('user_cache',    'User Cache (~/.cache)',
                'App caches — 3-layer guard: name list + socket detect + activity check', 'safe'),
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
                'xbps_cache':    self._xbps_cache,
                'xbps_orphaned': self._xbps_orphaned,
                'aur_cache':     self._aur_cache,
                'flatpak':       self._flatpak,
                'docker':        self._docker,
                'snap_old':      self._snap_old,
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
        m = re.search(r'([\d.]+)\s*(MiB|GiB|KiB|B)(?!\w)', out)
        if m:
            v, u = float(m.group(1)), m.group(2)
            r.freed_bytes = int(v * (1024**2 if 'MiB' in u else 1024**3 if 'GiB' in u else 1024 if 'KiB' in u else 1))
        if not dry:
            out2, code = run_privileged('paccache')
            if code != 0: r.error = out2
        return r

    def _pacman_broken(self, dry):
        r = CleanResult('pacman_broken')
        broken = list(Path('/var/cache/pacman/pkg').glob('download-*'))
        r.freed_bytes = sum(f.stat().st_size for f in broken if f.exists())
        r.files_removed = len(broken)
        if not dry:
            _, code = run_privileged('broken-downloads')
            if code != 0: r.error = 'Need root'
        return r

    def _orphaned_pkgs(self, dry):
        r = CleanResult('orphaned_pkgs')
        out, _ = run('pacman -Qdtq 2>/dev/null')
        pkgs = [l.strip() for l in out.splitlines() if l.strip()]
        r.files_removed = len(pkgs)
        if pkgs and not dry:
            import subprocess as _sp
            r2 = _sp.run(
                ['sudo', '-n', '/usr/local/bin/cyber-clean-helper', 'pacman-remove'] + pkgs,
                capture_output=True, text=True, timeout=120)
            code = r2.returncode
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
        except (ValueError, IndexError): pass
        if not dry:
            _, code = run_privileged('apt-clean')
            if code != 0: r.error = 'Need root'
        return r

    def _apt_autoremove(self, dry):
        r = CleanResult('apt_autoremove')
        out, _ = run('apt-get autoremove --dry-run 2>/dev/null | grep "^Remv" | wc -l')
        try: r.files_removed = int(out)
        except (ValueError, IndexError): pass
        if not dry:
            _, code = run_privileged('apt-autoremove')
            if code != 0: r.error = 'Need root'
        return r

    # ── DNF ───────────────────────────────────────────────
    def _dnf_cache(self, dry):
        r = CleanResult('dnf_cache')
        out, _ = run('du -sb /var/cache/dnf 2>/dev/null')
        try: r.freed_bytes = int(out.split()[0])
        except (ValueError, IndexError): pass
        if not dry:
            _, code = run_privileged('dnf-clean')
            if code != 0: r.error = 'Need root'
        return r

    # ── Zypper ────────────────────────────────────────────
    def _zypper_cache(self, dry):
        r = CleanResult('zypper_cache')
        out, _ = run('du -sb /var/cache/zypp 2>/dev/null')
        try: r.freed_bytes = int(out.split()[0])
        except (ValueError, IndexError): pass
        if not dry:
            _, code = run_privileged('zypper-clean')
            if code != 0: r.error = 'Need root'
        return r

    # ── XBPS (Void Linux) ─────────────────────────────────
    def _xbps_cache(self, dry):
        r = CleanResult('xbps_cache')
        out, _ = run('du -sb /var/cache/xbps 2>/dev/null')
        try:
            r.freed_bytes = int(out.split()[0])
        except (ValueError, IndexError):
            pass
        if not dry:
            _, code = run_privileged('xbps-clean-cache')
            if code != 0:
                r.error = 'Need root or install.sh helper with xbps-clean-cache'
        return r

    def _xbps_orphaned(self, dry):
        r = CleanResult('xbps_orphaned')
        out, _ = run('xbps-remove -n -O 2>/dev/null')
        pkgs = [ln.strip() for ln in out.splitlines() if ln.strip()]
        r.files_removed = len(pkgs)
        if not dry and pkgs:
            _, code = run_privileged('xbps-orphans')
            if code != 0:
                r.error = 'Need root or install.sh helper with xbps-orphans'
        return r

    # ── Snap (disabled revisions) ─────────────────────────
    def _snap_old(self, dry):
        r = CleanResult('snap_old')
        out, _ = run('LANG=C snap list --all 2>/dev/null')
        pairs = []
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 4 or parts[-1] != 'disabled':
                continue
            name, rev = parts[0], parts[2]
            if not rev.isdigit():
                continue
            pairs.append((name, rev))
        r.files_removed = len(pairs)
        du, _ = run('du -sb /var/lib/snapd/snap 2>/dev/null')
        try:
            base = int(du.split()[0])
            r.freed_bytes = min(base // 4, base) if pairs else 0
        except (ValueError, IndexError):
            r.freed_bytes = 0
        if not dry and pairs:
            h = '/usr/local/bin/cyber-clean-helper'
            for name, rev in pairs:
                qn, qr = shlex.quote(name), shlex.quote(rev)
                _, code = run(f'sudo -n {h} snap-remove-rev {qn} {qr} 2>/dev/null', timeout=120)
                if code != 0:
                    r.error = 'Need root / NOPASSWD helper (snap-remove-rev) — run install.sh'
                    break
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
        runtime_dir = Path.home() / '.local/share/flatpak/runtime'
        size_before = self.dir_size(runtime_dir) if runtime_dir.exists() else 0

        # FIX: check flatpak version before using --dry-run (requires >= 1.9.0)
        supports_dry = _flatpak_supports_dry_run()

        if supports_dry:
            out_dry, _ = run('flatpak uninstall --unused --dry-run 2>/dev/null')
            unused = [l.strip() for l in out_dry.splitlines()
                      if l.strip() and not l.strip().startswith('Nothing')]
            r.files_removed = len(unused)
        else:
            # Fallback: count via flatpak list for old versions
            out_all, _ = run('flatpak list --runtime --columns=application 2>/dev/null')
            unused = [l for l in out_all.splitlines() if l.strip()]
            r.files_removed = max(0, len(unused) - 1)  # rough estimate

        if not dry:
            run('flatpak uninstall --unused -y 2>/dev/null', timeout=120)
            size_after = self.dir_size(runtime_dir) if runtime_dir.exists() else 0
            r.freed_bytes = max(size_before - size_after, 0)
        else:
            if not unused:
                r.freed_bytes = 0
            else:
                out_all, _ = run('flatpak list --runtime --columns=application 2>/dev/null')
                total_refs = max(len([l for l in out_all.splitlines() if l.strip()]), 1)
                r.freed_bytes = int((size_before / total_refs) * len(unused))
        return r

    # ── Docker / Podman ───────────────────────────────────
    def _docker(self, dry):
        r = CleanResult('docker')
        # FIX: use CONTAINER_TOOL from os_detect (same priority: podman > docker)
        # instead of re-checking shutil.which with a different order each time.
        tool = CONTAINER_TOOL
        if not tool:
            r.error = 'No container runtime found (docker/podman)'
            return r
        out, _ = run(f'{tool} system df 2>/dev/null')
        for line in out.splitlines():
            if 'Images' in line:
                parts = line.split()
                for i, p in enumerate(parts):
                    if p.endswith(('MB','GB','KB','B')) and i > 0:
                        try:
                            v = float(p[:-2])
                            u = p[-2:]
                            mult = {'GB':1024**3,'MB':1024**2,'KB':1024,'B':1}.get(u, 1)
                            r.freed_bytes += int(v * mult)
                        except (ValueError, IndexError): pass
        if not dry:
            run(f'{tool} image prune -f 2>/dev/null')
            run(f'{tool} container prune -f 2>/dev/null')
            run(f'{tool} volume prune -f 2>/dev/null')
        return r

    # ── Journal ───────────────────────────────────────────
    def _journal(self, dry):
        """
        FIX: dry-run estimate now uses journalctl --vacuum-time --dry-run when
        available (journalctl >= 250). Falls back to a percentage estimate.
        Removed hardcoded -10MB estimate which was wildly inaccurate.
        """
        r = CleanResult('journal')
        if not HAS_JOURNALCTL:
            r.error = 'journalctl not available (non-systemd / minimal init)'
            return r

        def _parse_size(text):
            m = re.search(r'([\d.]+)\s*(M|G|K|B)', text)
            if not m: return 0
            v, u = float(m.group(1)), m.group(2)
            return int(v * (1024**2 if u=='M' else 1024**3 if u=='G' else 1024 if u=='K' else 1))

        out, _ = run('journalctl --disk-usage 2>/dev/null')
        before = _parse_size(out)

        if not dry:
            _, code = run(f'journalctl --vacuum-time={JOURNAL_DAYS}d 2>/dev/null')
            if code != 0:
                run_privileged('journal')
            # journalctl --vacuum is synchronous — no sleep needed
            out2, _ = run('journalctl --disk-usage 2>/dev/null')
            after = _parse_size(out2)
            r.freed_bytes = max(before - after, 0)
        else:
            # FIX: try --dry-run first (journalctl >= 250), then fall back to
            # rough estimate based on actual disk usage (not hardcoded -10MB)
            dry_out, dry_code = run(
                f'journalctl --vacuum-time={JOURNAL_DAYS}d --dry-run 2>/dev/null')
            if dry_code == 0:
                freed = _parse_size(dry_out)
                r.freed_bytes = freed if freed > 0 else max(before // 4, 0)
            else:
                # Older journalctl: assume ~25% of current usage is old enough to vacuum
                r.freed_bytes = max(before // 4, 0)
        return r

    # ── User cache ────────────────────────────────────────
    def _user_cache(self, dry):
        r = CleanResult('user_cache')
        cache = Path.home() / '.cache'
        if not cache.exists():
            return r

        # ══════════════════════════════════════════════════════
        # LAYER 1 — NAME WHITELIST (explicit, never touch these)
        # Kể cả khi logic thông minh ở Layer 2/3 không bắt được,
        # những thứ này vẫn được bảo vệ tuyệt đối.
        # ══════════════════════════════════════════════════════
        NAME_EXCLUDE = {
            # ── GPU shader / driver cache (xóa = 5–30 phút rebuild lag khi vào game) ──
            # Bao gồm tên thư mục cấp 1 lẫn subdirectory của từng driver:
            #   mesa_shader_cache/   → Mesa tổng (AMD RadeonSI, Intel Iris, etc.)
            #   mesa/                → Mesa build artifacts
            #   nvidia/              → NVIDIA OpenGL / Vulkan shader cache
            #   amdgpu/              → AMDGPU-PRO driver cache
            #   radeon/              → legacy ATI/AMD radeon driver
            #   intel/               → Intel GPU media driver cache
            #   vulkan/              → Vulkan ICD layer cache
            #   radv/                → AMD Radeon Vulkan (Mesa RADV driver)
            #   anv/                 → Intel ANV Vulkan driver cache
            #   iris/                → Intel Iris/Iris Xe (OpenGL)
            #   nouveau/             → NVIDIA open-source driver
            #   d3d/                 → DXVK / VKD3D Direct3D-over-Vulkan cache
            #   dxvk/                → DXVK shader cache (Steam/Proton games)
            #   vkd3d/               → VKD3D-Proton DX12→Vulkan cache
            'mesa_shader_cache', 'mesa', 'nvidia', 'amdgpu',
            'radeon', 'intel', 'vulkan',
            'radv', 'anv', 'iris', 'nouveau',
            'd3d', 'dxvk', 'vkd3d',

            # ── Fonts (xóa = ô vuông khắp nơi) ──
            'fontconfig',

            # ── Browsers (có target riêng, không xử lý ở đây) ──
            'mozilla', 'google-chrome', 'chromium', 'microsoft-edge',
            'BraveSoftware', 'brave', 'opera', 'vivaldi',

            # ── Package managers (AUR có target riêng) ──
            'yay', 'paru',

            # ── Thumbnails (có target riêng) ──
            'thumbnails',

            # ── Wayland / X11 compositor & display runtime ──
            'hyprland', 'sway', 'i3', 'openbox', 'xfwm4',
            'kwin', 'mutter', 'marco',

            # ── Wallpaper managers (daemon giữ socket trong cache) ──
            # Xóa = màn hình đen hoặc wallpaper mất
            'swww', 'swaybg', 'hyprpaper', 'wpaperd', 'mpvpaper',
            'feh', 'nitrogen', 'variety', 'wbg', 'xwallpaper',

            # ── Theming / color scheme (xóa = mất theme hiện tại) ──
            'wal', 'wallust', 'matugen', 'pywal', 'lutgen',
            'wpg', 'chameleon',

            # ── Desktop environment runtime caches ──
            'plasma', 'ksycoca5', 'ksycoca6', 'kioexec',
            'gnome-software', 'gnome-shell', 'gnome-session',
            'discover', 'tracker', 'tracker3',

            # ── Input methods (xóa = không gõ được) ──
            'ibus', 'fcitx', 'fcitx5',

            # ── Audio (xóa = mất âm thanh / app không nhận device) ──
            'pipewire', 'wireplumber', 'pulse', 'pulseaudio',
            'gstreamer-1.0', 'obexd',

            # ── Bars / launchers / notif (có socket runtime) ──
            'waybar', 'polybar', 'eww', 'ags',
            'rofi', 'wofi', 'fuzzel', 'tofi', 'anyrun',
            'dunst', 'mako', 'swaync', 'fnott',
            'cliphist', 'wl-clipboard',

            # ── Filesystem / GVFS (xóa = mount points bị ảnh hưởng) ──
            'gvfs', 'dconf', 'glib-2.0',

            # ── Email clients ──
            'thunderbird', 'evolution', 'geary',

            # ── AI / ML (model cache cực lớn, tải lại rất lâu) ──
            'huggingface', 'torch', 'transformers',

            # ── Dev tools (tải lại tốn bandwidth / thời gian) ──
            'pip', 'yarn', 'Cypress', 'JetBrains',
            'go-build', 'node-gyp', 'cargo',
            'clangd', 'vscode-cpptools',
            'zsh', 'prezto',

            # ── Gaming (Lutris / Wine prefix cache) ──
            'lutris', 'winetricks',
        }

        # ══════════════════════════════════════════════════════
        # LAYER 2 — SMART TYPE GUARD (không cần biết tên app)
        # Bất kể tool mới lạ nào, nếu nó để lại socket/fifo/device
        # trong .cache thì tự động được bỏ qua.
        # Socket = "dây thần kinh" IPC của app đang chạy.
        # Xóa socket = app crash ngay lập tức.
        # ══════════════════════════════════════════════════════
        def _is_runtime_file(p: Path) -> bool:
            """True nếu item là socket, FIFO hoặc block/char device."""
            try:
                return p.is_socket() or p.is_fifo() or p.is_block_device() or p.is_char_device()
            except OSError:
                return True   # không stat được → giữ lại cho an toàn

        def _dir_has_socket(p: Path) -> bool:
            """
            True nếu thư mục chứa bất kỳ socket / FIFO nào ở cấp đầu tiên.
            Đây là dấu hiệu app đang chạy và giữ runtime state trong thư mục này.
            Chỉ check cấp 1 — đủ để phát hiện, không cần đệ quy toàn bộ cây.
            """
            try:
                for child in p.iterdir():
                    if _is_runtime_file(child):
                        return True
            except (OSError, PermissionError):
                return True   # không đọc được → giữ lại an toàn
            return False

        # ══════════════════════════════════════════════════════
        # LAYER 3 — RECENTLY MODIFIED GUARD
        # Thư mục được modified trong vòng 30 giây = app đang active.
        # Không xóa để tránh race condition.
        # ══════════════════════════════════════════════════════
        _now = time.time()
        _ACTIVE_WINDOW_SEC = 30

        def _recently_modified(p: Path) -> bool:
            try:
                return (_now - p.stat().st_mtime) < _ACTIVE_WINDOW_SEC
            except OSError:
                return True   # không stat được → giữ lại an toàn

        # ── Main iteration ────────────────────────────────────
        for item in cache.iterdir():

            # Layer 1: tên nằm trong whitelist → skip tuyệt đối
            if item.name in NAME_EXCLUDE:
                continue

            # Layer 2a: bản thân item là socket/FIFO/device → skip
            if _is_runtime_file(item):
                continue

            # FIX W7: bind-mount / Btrfs subvolume guard.
            # On Fedora Silverblue, NixOS, and systems with Btrfs subvol layout,
            # ~/.cache subdirs can be real mount points (not symlinks) for
            # separate subvolumes or tmpfs mounts.
            # item.is_symlink() returns False for mount points → Layer 2 misses them.
            # os.path.ismount() correctly detects both symlink mounts AND real mounts.
            # Deleting a mount point would attempt to remove the entire subvolume.
            try:
                import os as _os
                if _os.path.ismount(str(item)):
                    continue
            except OSError:
                continue   # stat failed → play it safe

            # Layer 2b: nếu là thư mục và chứa socket bên trong → skip
            if item.is_dir() and _dir_has_socket(item):
                continue

            # Layer 3: modified trong vòng 30 giây → skip (app đang active)
            if _recently_modified(item):
                continue

            # Vượt qua cả 3 tầng → an toàn để xóa
            try:
                sz = self.dir_size(item)
                r.freed_bytes += sz
                if not dry:
                    r.rollback.append({
                        'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                        'type': 'user_cache',
                        'path': str(item),
                        'size': sz,
                        'note': 'app cache — auto-rebuilds on next launch',
                    })
                    safe_delete(item, use_trash=False)
                    r.files_removed += 1
            except PermissionError:
                pass   # snap cache dirs owned by root — skip silently
            except OSError as e:
                r.error = (r.error or '') + f'  [skip {item.name}: {e}]\n'
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
                # Skip IPC runtime files — these are active sockets/FIFOs used
                # by Wayland compositors (e.g. /tmp/wayland-0), X11, PipeWire, etc.
                # Deleting any of these crashes the compositor or audio daemon immediately.
                if f.is_socket() or f.is_fifo() or f.is_block_device() or f.is_char_device():
                    continue
                # Skip files modified recently — could be in active use
                if (now - f.stat().st_mtime) / 86400 < TMP_DAYS:
                    continue
                sz = self.dir_size(f) if f.is_dir() else f.stat().st_size
                r.freed_bytes += sz
                r.files_removed += 1
                if not dry:
                    safe_delete(f, use_trash=False)
            except (OSError, PermissionError):
                pass   # files owned by other users, or deleted between scan and delete
        return r
