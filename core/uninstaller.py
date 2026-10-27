"""
CyberClean v2.3 — App Uninstaller
════════════════════════════════════════════════════════════════
Linux:   pacman · apt · dnf · zypper · xbps · flatpak
Windows: Registry (fast) + winget enrichment — NO wmic product get

WHAT CHANGED vs v2.0:

FIX: bare except → typed except (PermissionError, OSError, Exception)
     Silent swallowing masked bugs; now errors surface via UninstallResult.

FIX: dpkg-query parse — handle packages with empty Installed-Size field
     (virtual packages, meta-packages) without crashing float().

FIX: winget parse — skip separator/header lines more robustly.
     Previous split(r'  +') broke when winget output used different spacing
     on localized Windows (e.g. non-ASCII column headers).

NEW: zypper support — Linux distros: OpenSUSE Leap / Tumbleweed.
     _get_linux() now detects PKG_MANAGER == 'zypper' and lists via
     'zypper packages --installed-only'.

NEW: xbps support — Void Linux.
     Lists via 'xbps-query -l' (already partly in helper but not in list).

NEW: InstalledApp.uninstall_preview dict — structured data the GUI can
     show in a confirmation dialog BEFORE running uninstall:
       size_mb, version, source, estimated_dependencies (Linux only),
       reversible (bool — registry uninstall is reversible via restore point).

NEW: get_dependencies_linux() — lightweight 'apt-cache depends' / 'pacman -Qi'
     pass to populate the preview without blocking the main thread.

NEW: UninstallResult dataclass — structured return value from uninstall_app().
     Replaces bare bool / 'UI_OPENED' string sentinel.
     Fields: success, ui_opened, output, error_msg.

COMPAT: uninstall_app() still returns bool | 'UI_OPENED' for old call sites.
"""

import subprocess, platform, re, time, shlex, fnmatch
from dataclasses import dataclass, field
from typing import List, Callable, Optional

OS = platform.system()

@dataclass
class InstalledApp:
    name:    str
    version: str   = ''
    size_mb: float = 0.0
    source:  str   = ''   # 'pacman'|'apt'|'dnf'|'zypper'|'xbps'|'flatpak'|'winget'|'registry'
    pkg_id:  str   = ''   # id used to uninstall

    @property
    def protected(self) -> bool:
        return is_protected(self)

    @property
    def uninstall_preview(self) -> dict:
        """Structured data for confirmation dialog — safe to call from GUI thread."""
        return {
            'name':        self.name,
            'version':     self.version,
            'size_mb':     round(self.size_mb, 1),
            'source':      self.source,
            'reversible':  self.source not in ('pacman', 'apt', 'dnf', 'zypper', 'xbps'),
        }


@dataclass
class UninstallResult:
    """Structured return value from uninstall_app()."""
    success:    bool   = False
    ui_opened:  bool   = False   # True → user must interact with separate window
    output:     str    = ''
    error_msg:  str    = ''


_NO_WIN = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0


# ── Gói lõi KHÔNG được gỡ ────────────────────────────────────────────────────
# Pacman/apt/dnf tự từ chối gỡ gói đang được gói khác cần, nhưng kernel, bootloader, initramfs, init,
# sudo/polkit, trình quản lý mạng, DE meta-package... thường KHÔNG ai "require" nên vẫn gỡ được và có thể
# làm máy không khởi động. Danh sách này PHẢI giống PROTECTED_GLOBS trong packaging/cyber-clean-helper
# (tests/test_uninstaller.py đối chiếu) — helper là hàng rào thật; đây là hàng rào sớm cho UI.
PROTECTED_PKG_GLOBS = (
    'linux', 'linux-lts', 'linux-zen', 'linux-hardened', 'linux-rt', 'linux-rt-lts',
    'linux-cachyos*', 'linux-xanmod*', 'linux-firmware', 'linux-firmware-*',
    'linux-image-*', 'linux-modules-*', 'linux-generic*', 'linux-virtual*', 'linux-base',
    'kernel', 'kernel-core', 'kernel-modules*', 'kernel-default*',
    'grub', 'grub2*', 'grub-*', 'shim', 'shim-*', 'efibootmgr', 'systemd-boot*', 'refind', 'limine', 'syslinux',
    'mkinitcpio', 'mkinitcpio-*', 'dracut', 'dracut-*', 'initramfs-tools', 'initramfs-tools-*',
    'base', 'filesystem', 'glibc', 'libc6', 'libc-bin', 'bash', 'dash', 'coreutils', 'util-linux', 'util-linux-*',
    'systemd', 'systemd-sysv', 'systemd-sysvcompat', 'systemd-libs', 'systemd-resolved', 'systemd-timesyncd',
    'systemd-udev', 'libsystemd*', 'udev', 'libudev*',
    'dbus', 'dbus-broker', 'dbus-daemon', 'dbus-user-session',
    'pacman', 'pacman-*', 'libalpm*', 'archlinux-keyring',
    'apt', 'apt-*', 'libapt-*', 'dpkg', 'debian-archive-keyring', 'ubuntu-keyring',
    'dnf', 'dnf-*', 'dnf5', 'rpm', 'rpm-*', 'libdnf*', 'yum', 'zypper', 'libzypp', 'xbps',
    'sudo', 'doas', 'su', 'shadow', 'login', 'passwd', 'polkit', 'polkitd', 'policykit-1', 'pam', 'libpam*',
    'e2fsprogs', 'btrfs-progs', 'xfsprogs', 'dosfstools', 'lvm2', 'cryptsetup', 'mdadm',
    'networkmanager', 'NetworkManager', 'network-manager', 'iwd', 'wpa_supplicant', 'dhcpcd', 'dhclient',
    'plasma-desktop', 'plasma-meta', 'plasma-workspace', 'gnome-shell', 'gnome-session', 'gdm', 'gdm3', 'sddm', 'lightdm',
    'xorg-server', 'xwayland', 'xserver-xorg*', 'ubuntu-desktop*', 'ubuntu-minimal', 'ubuntu-standard',
    'kubuntu-desktop', 'xubuntu-desktop',
    'python', 'python3', 'python3-minimal', 'libpython3*',
    'cyberclean', 'cyber-clean',
)
_PM_SOURCES = ('pacman', 'apt', 'dnf', 'zypper', 'xbps')


_ARCH_SUFFIXES = (
    ".x86_64", ".i686", ".i586", ".i386", ".noarch",
    ".aarch64", ".armv7hl", ".ppc64le", ".s390x", ".riscv64", ".src",
)
_PKG_VER_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9+._-]*?)-[0-9][A-Za-z0-9+._:~-]*$")


def normalize_pkg_id(name: str) -> str:
    n = (name or "").strip()
    if "/" in n:
        n = n.rsplit("/", 1)[-1]
    if ":" in n:
        n = n.split(":", 1)[0]
    n_low = n.lower()
    for suf in _ARCH_SUFFIXES:
        if n_low.endswith(suf) and len(n) > len(suf):
            n = n[:-len(suf)]
            break
    return n


def is_protected_pkg(name: str) -> bool:
    raw = (name or "").strip()
    if not raw:
        return False
    norm = normalize_pkg_id(raw)
    m = _PKG_VER_RE.match(norm)
    stripped = m.group(1) if m else norm
    for cand in (raw, norm, stripped):
        cand_low = cand.lower()
        for g in PROTECTED_PKG_GLOBS:
            if fnmatch.fnmatchcase(cand, g) or fnmatch.fnmatchcase(cand_low, g.lower()):
                return True
    return False


def is_protected(app: 'InstalledApp') -> bool:
    return app.source in _PM_SOURCES and is_protected_pkg(app.pkg_id)


def run(cmd, timeout=20):
    """
    FIX: encoding='utf-8' errors='replace' — prevents UnicodeDecodeError crash
    on Vietnamese/CJK Windows locales where app names contain non-ASCII chars.
    FIX: TimeoutExpired handled explicitly — was silently returning ('exc_str', 1)
    which masked slow-command issues.
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


def _run_argv(argv, timeout=60):
    """subprocess không qua shell. Trả về (output, returncode)."""
    try:
        r = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout,
                           creationflags=_NO_WIN, encoding='utf-8', errors='replace')
        return (r.stdout or '').strip(), r.returncode
    except subprocess.TimeoutExpired:
        return f'timeout after {timeout}s', 1
    except Exception as e:
        return str(e), 1


def get_installed_apps() -> List[InstalledApp]:
    if OS == 'Linux':   return _get_linux()
    if OS == 'Windows': return _get_windows()
    return []


# ── Dependency preview (non-blocking, best-effort) ────────────
def get_dependencies_linux(app: 'InstalledApp') -> List[str]:
    """
    Return list of packages that depend on this one (reverse deps).
    Used to populate the confirmation dialog warning.
    Returns [] on any failure — non-critical.
    """
    try:
        from .os_detect import PKG_MANAGER
    except ImportError:
        try:
            from os_detect import PKG_MANAGER
        except ImportError:
            return []

    try:
        if PKG_MANAGER == 'apt':
            pkg = shlex.quote(app.pkg_id)
            out, _ = run(f'apt-cache rdepends --installed {pkg} 2>/dev/null', timeout=8)
            return [l.strip().lstrip('|').strip() for l in out.splitlines()
                    if l.strip() and not l.strip().startswith(app.pkg_id)][:10]
        elif PKG_MANAGER == 'pacman':
            out, _ = run(f'pacman -Qi {shlex.quote(app.pkg_id)} 2>/dev/null', timeout=8)
            for line in out.splitlines():
                if line.startswith('Required By'):
                    val = line.split(':', 1)[1].strip()
                    return [v.strip() for v in val.split() if v.strip() != 'None'][:10]
    except Exception:
        pass
    return []


# ── LINUX ──────────────────────────────────────────────────────
def _get_linux() -> List[InstalledApp]:
    apps = []
    try:
        from .os_detect import PKG_MANAGER, HAS_FLATPAK, HAS_XBPS
    except ImportError:
        try:
            from os_detect import PKG_MANAGER, HAS_FLATPAK, HAS_XBPS
        except ImportError:
            PKG_MANAGER = ''; HAS_FLATPAK = False; HAS_XBPS = False

    if PKG_MANAGER == 'pacman':
        out, _ = run('pacman -Qi 2>/dev/null', timeout=30)
        current: dict = {}
        for line in out.splitlines():
            if line.startswith('Name '):
                current['name'] = line.split(':', 1)[1].strip()
            elif line.startswith('Version '):
                current['version'] = line.split(':', 1)[1].strip()
            elif line.startswith('Installed Size '):
                sz_str = line.split(':', 1)[1].strip()
                try:
                    val, unit = sz_str.split()[:2]
                    mult = {'B': 1/1024/1024, 'KiB': 1/1024, 'MiB': 1, 'GiB': 1024}.get(unit, 0)
                    current['size_mb'] = float(val) * mult
                except (ValueError, TypeError):
                    current['size_mb'] = 0.0
            elif line.strip() == '' and current.get('name'):
                apps.append(InstalledApp(
                    name=current['name'], version=current.get('version', ''),
                    size_mb=current.get('size_mb', 0.0),
                    source='pacman', pkg_id=current['name'],
                ))
                current = {}
        if current.get('name'):
            apps.append(InstalledApp(
                name=current['name'], version=current.get('version', ''),
                size_mb=current.get('size_mb', 0.0),
                source='pacman', pkg_id=current['name'],
            ))

    elif PKG_MANAGER == 'apt':
        # FIX: single quotes so ${...} fields are not expanded by bash.
        # FIX: coerce empty Installed-Size to 0 before float() — virtual packages
        #      return empty string → float('') raises ValueError.
        out, _ = run(
            "dpkg-query -W -f='${Package}\t${Version}\t${Installed-Size}\n' 2>/dev/null",
            timeout=30,
        )
        for line in out.splitlines():
            parts = line.split('\t')
            if len(parts) < 2 or not parts[0].strip():
                continue
            try:
                sz_raw = parts[2].strip() if len(parts) > 2 else ''
                sz = float(sz_raw) / 1024 if sz_raw else 0.0
            except (ValueError, TypeError):
                sz = 0.0
            apps.append(InstalledApp(
                name=parts[0].strip(), version=parts[1].strip(),
                size_mb=sz, source='apt', pkg_id=parts[0].strip(),
            ))

    elif PKG_MANAGER == 'dnf':
        out, _ = run('rpm -qa --queryformat "%{NAME}\t%{VERSION}\t%{SIZE}\n" 2>/dev/null', timeout=30)
        for line in out.splitlines():
            parts = line.split('\t')
            if not parts or not parts[0].strip():
                continue
            try:
                sz = float(parts[2]) / 1024 / 1024 if len(parts) > 2 and parts[2].strip() else 0.0
            except (ValueError, TypeError):
                sz = 0.0
            apps.append(InstalledApp(
                name=parts[0].strip(),
                version=parts[1].strip() if len(parts) > 1 else '',
                size_mb=sz, source='dnf', pkg_id=parts[0].strip(),
            ))

    elif PKG_MANAGER == 'zypper':
        # NEW: OpenSUSE Leap / Tumbleweed support
        # 'zypper packages --installed-only' output:
        #   S | Repository | Name | Version | Arch
        # Skip header lines (start with '-' or 'S |')
        out, _ = run('zypper packages --installed-only 2>/dev/null', timeout=30)
        for line in out.splitlines():
            line = line.strip()
            if not line or line.startswith('-') or line.startswith('S '):
                continue
            parts = [p.strip() for p in line.split('|')]
            if len(parts) < 4:
                continue
            # parts[0] = status flag, [1] = repo, [2] = name, [3] = version
            name = parts[2]
            ver  = parts[3]
            if not name or name.lower() in ('name', 'package'):
                continue
            apps.append(InstalledApp(
                name=name, version=ver,
                size_mb=0.0, source='zypper', pkg_id=name,
            ))

    elif PKG_MANAGER == 'xbps' and HAS_XBPS:
        # NEW: Void Linux
        # 'xbps-query -l' output: ii package-name-version description
        out, _ = run('xbps-query -l 2>/dev/null', timeout=30)
        for line in out.splitlines():
            parts = line.split(None, 2)   # ['ii', 'pkg-version', 'description']
            if len(parts) < 2:
                continue
            pkg_ver = parts[1]
            # Split name-version: last hyphen-separated part that starts with digit is version
            m = re.match(r'^(.+?)-(\d[\d.]*\w*)$', pkg_ver)
            if m:
                name, ver = m.group(1), m.group(2)
            else:
                name, ver = pkg_ver, ''
            apps.append(InstalledApp(
                name=name, version=ver,
                size_mb=0.0, source='xbps', pkg_id=name,
            ))

    # Flatpak (all distros)
    try:
        from .os_detect import HAS_FLATPAK as _HAS_FP
    except ImportError:
        try:
            from os_detect import HAS_FLATPAK as _HAS_FP
        except ImportError:
            _HAS_FP = HAS_FLATPAK
    if _HAS_FP:
        out, _ = run('flatpak list --app --columns=application,name,version,size 2>/dev/null', timeout=20)
        import re as _re
        for line in out.splitlines():
            parts = line.split('\t')
            if len(parts) < 2:
                continue
            app_id = parts[0].strip()
            if not app_id or app_id.lower() in ('application id', 'application', 'app id'):
                continue
            name   = parts[1].strip() if len(parts) > 1 else app_id
            ver    = parts[2].strip() if len(parts) > 2 else ''
            sz_str = parts[3].strip() if len(parts) > 3 else '0'
            try:
                m2 = _re.match(r'([\d.]+)\s*(MB|GB|KB)', sz_str)
                if m2:
                    mult = {'MB': 1, 'GB': 1024, 'KB': 1/1024}.get(m2.group(2), 1)
                    sz = float(m2.group(1)) * mult
                else:
                    sz = 0.0
            except (ValueError, TypeError):
                sz = 0.0
            apps.append(InstalledApp(name=name, version=ver,
                                     size_mb=sz, source='flatpak', pkg_id=app_id))

    # Standalone user games & portable apps (~/Games, ~/game, Wine prefixes, Steam common, ~/.local/share/applications)
    try:
        apps.extend(_scan_linux_local_games())
    except Exception:
        pass

    return sorted(apps, key=lambda a: a.size_mb, reverse=True)


def _dir_size_mb_fast(path: 'Path', max_files: int = 8000) -> float:
    import os as _os
    total = 0
    seen = 0
    stack = [str(path)]
    while stack and seen < max_files:
        cur = stack.pop()
        try:
            with _os.scandir(cur) as it:
                for entry in it:
                    seen += 1
                    if seen > max_files:
                        break
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                        elif entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                    except OSError:
                        pass
        except OSError:
            pass
    return round(total / (1024 * 1024), 1)


def _scan_linux_local_games() -> List[InstalledApp]:
    from pathlib import Path as _P
    try:
        from .os_detect import real_home
        home = _P(real_home())
    except Exception:
        home = _P.home()

    found: List[InstalledApp] = []
    seen_paths: set = set()

    _WIN_BUILTIN_DIRS = {
        'common files', 'internet explorer', 'windows media player',
        'windows nt', 'windows photo viewer', 'windows mail',
        'windows defender', 'windows portable devices', 'msbuild',
        'reference assemblies', 'uninstall information',
    }

    search_roots = [
        (home / 'Games', 'local-game'),
        (home / 'games', 'local-game'),
        (home / 'game', 'local-game'),
        (home / 'Game', 'local-game'),
        (home / '.local/share/Steam/steamapps/common', 'steam-local'),
        (home / '.steam/steam/steamapps/common', 'steam-local'),
        (home / '.wine/drive_c/Program Files', 'wine-app'),
        (home / '.wine/drive_c/Program Files (x86)', 'wine-app'),
    ]
    # Also check Bottles prefixes if present
    bottles_root = home / '.var/app/com.usebottles.bottles/data/bottles/bottles'
    if bottles_root.is_dir():
        for bdir in bottles_root.iterdir():
            if bdir.is_dir():
                search_roots.append((bdir / 'drive_c/Program Files', 'wine-app'))
                search_roots.append((bdir / 'drive_c/Program Files (x86)', 'wine-app'))

    for root_dir, src_tag in search_roots:
        if not root_dir.is_dir():
            continue
        try:
            for child in root_dir.iterdir():
                if not child.is_dir() or child.is_symlink():
                    continue
                if child.name.startswith('.'):
                    continue
                _NON_GAME_DIRS = {
                    'screenshots', 'screenshot', 'saves', 'savegames', 'save',
                    'mods', 'mod', 'captures', 'recordings', 'videos',
                    'backups', 'backup', 'configs', 'config', 'shader_cache',
                    'shadercache', 'prefixes', 'logs', 'downloads', 'isos', 'roms',
                }
                if src_tag == 'local-game' and child.name.lower() in _NON_GAME_DIRS:
                    continue
                if src_tag == 'wine-app' and child.name.lower() in _WIN_BUILTIN_DIRS:
                    continue
                real_p = str(child.resolve())
                if real_p in seen_paths:
                    continue
                sz = _dir_size_mb_fast(child)
                if sz < 5.0:
                    continue
                seen_paths.add(real_p)
                found.append(InstalledApp(
                    name=child.name,
                    version='portable' if src_tag == 'local-game' else src_tag.split('-')[0],
                    size_mb=sz,
                    source=src_tag,
                    pkg_id=real_p,
                ))
        except OSError:
            pass

    return found


# ── WINDOWS — Registry (fast, no wmic) ────────────────────────
def _get_windows() -> List[InstalledApp]:
    apps = []
    seen: set = set()

    try:
        import winreg
        from concurrent.futures import ThreadPoolExecutor, as_completed

        reg_paths = [
            (winreg.HKEY_LOCAL_MACHINE,
             r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'),
            (winreg.HKEY_LOCAL_MACHINE,
             r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'),
            (winreg.HKEY_CURRENT_USER,
             r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'),
        ]

        def _read_hive(hive_path):
            hive, path = hive_path
            results = []
            try:
                key = winreg.OpenKey(hive, path)
            except OSError:
                return results
            num_subkeys, _, _ = winreg.QueryInfoKey(key)
            for i in range(num_subkeys):
                try:
                    sub_name = winreg.EnumKey(key, i)
                    sub_key  = winreg.OpenKey(key, sub_name)

                    def _val(k, default=''):
                        try:
                            return winreg.QueryValueEx(sub_key, k)[0]
                        except OSError:
                            return default

                    name = _val('DisplayName')
                    if not name:
                        continue
                    if _val('SystemComponent', 0) == 1:
                        continue
                    if sub_name.startswith('KB') and len(sub_name) < 15:
                        continue

                    version       = _val('DisplayVersion')
                    uninstall_str = _val('UninstallString', '').strip()
                    quiet_str     = _val('QuietUninstallString', '').strip()

                    try:
                        sz_kb   = winreg.QueryValueEx(sub_key, 'EstimatedSize')[0]
                        size_mb = sz_kb / 1024
                    except OSError:
                        size_mb = 0.0

                    results.append(InstalledApp(
                        name=name, version=version, size_mb=size_mb,
                        source='registry',
                        pkg_id=f'{sub_name}|||{uninstall_str}|||{quiet_str}',
                    ))
                except OSError:
                    continue
            return results

        # Read all three registry hives in parallel — ~3x faster than serial
        with ThreadPoolExecutor(max_workers=3) as ex:
            futures = [ex.submit(_read_hive, hp) for hp in reg_paths]
            for fut in as_completed(futures):
                try:
                    for app in fut.result(timeout=10):
                        if app.name not in seen:
                            seen.add(app.name)
                            apps.append(app)
                except Exception:
                    pass

    except ImportError:
        pass   # not on Windows

    _enrich_with_winget(apps)
    return sorted(apps, key=lambda a: a.name.lower())


def _enrich_with_winget(apps: List[InstalledApp]):
    """Run 'winget list' để enrich source info — chạy với timeout ngắn.

    FIX: timeout 10s thay vì 45s.
    Winget enrichment là nice-to-have, không critical.
    Trên máy văn phòng chưa chạy winget → winget refresh source mất 30s+.
    Thà hiện danh sách ngay (dù thiếu winget info) còn hơn đợi 45s.
    Winget info sẽ được refresh lần sau khi winget đã cache source rồi.
    """
    if OS != 'Windows':
        return
    import shutil
    if not shutil.which('winget'):
        return
    try:
        out, code = run(
            'winget list --disable-interactivity --accept-source-agreements --no-upgrade 2>nul',
            timeout=10,   # FIX: 10s thay vì 45s — trả về nhanh cho user
        )
        if code != 0:
            return

        winget_map: dict = {}
        lines = out.splitlines()

        # FIX: find the header line to skip it robustly regardless of locale
        # Header contains 'Name' and 'Id' columns — find by checking for 'Id' keyword
        data_start = 0
        for idx, line in enumerate(lines):
            if re.search(r'\bId\b', line):
                data_start = idx + 2   # skip header + separator
                break

        for line in lines[data_start:]:
            line = line.strip()
            if not line or line.startswith('-'):
                continue
            # winget list uses variable-width columns — split on 2+ spaces
            parts = re.split(r'  +', line)
            if len(parts) >= 2:
                wname = parts[0].strip().lower()
                wid   = parts[1].strip()
                if wid:
                    winget_map[wname] = wid

        for app in apps:
            wid = winget_map.get(app.name.lower())
            if wid:
                app.source = 'winget'
                app.pkg_id = wid
    except Exception:
        pass


def _clean_path(s: str) -> str:
    return s.strip().strip('"').strip("'")


def _win_argv(cmd_str: str) -> list:
    """
    Split a Windows command-line string (as stored verbatim in registry
    UninstallString / QuietUninstallString values) into an argv list,
    WITHOUT ever handing the string to a shell for parsing.

    SECURITY: every call site in this module used to build an f-string like
    f'"{exe}" /S {args}' and run it via subprocess.run(cmd, shell=True) or
    subprocess.Popen(uninstall_str, shell=True) — with shell=True on Windows
    that string is handed to cmd.exe, which interprets &, |, ^, and stray "
    as shell metacharacters. uninstall_str/quiet_str come straight from a
    registry value under the app's own Uninstall key; on a clean system
    that's effectively developer-controlled data, but if malware/a PUA (or a
    corrupted/hand-edited installer entry) ever writes a value containing
    e.g. `"C:\\x.exe" & calc.exe & echo "`, the injected command runs with
    whatever privileges CyberClean has — this is the same CWE-78 class every
    Linux branch in this file already avoids via shlex.quote(). Splitting
    into argv and calling subprocess with shell=False removes cmd.exe from
    the picture entirely: CreateProcess receives the arguments directly, so
    there is no shell metacharacter interpretation left to exploit.

    shlex.split(cmd_str, posix=False) is used (not posix mode) because
    Windows paths use '\\' as a directory separator, which POSIX mode would
    treat as an escape character and mangle. posix=False keeps quoted
    segments intact and doesn't touch backslashes; we still need to strip
    the surrounding quote characters it leaves on each token.
    """
    if not cmd_str or not cmd_str.strip():
        return []
    try:
        tokens = shlex.split(cmd_str, posix=False)
    except ValueError:
        # Unbalanced quotes etc. — fall back to a single-token best-effort
        # split so callers still get *something* runnable via argv rather
        # than silently doing nothing; still never touches a shell.
        tokens = cmd_str.split()
    return [t[1:-1] if len(t) >= 2 and t[0] == '"' and t[-1] == '"' else t
            for t in tokens]


def _run_win_uninstall(
    app_name: str, reg_key: str, uninstall_str: str,
    quiet_str: str, log_cb: Callable
) -> tuple:
    """
    Smart Windows uninstall — tries multiple strategies in order.
    Handles: MSI GUIDs, Inno Setup, NSIS, QuietUninstallString, generic EXE.
    Returns (output: str, returncode: int).
    """
    _NW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0

    def _run(argv: list, timeout=120):
        """Run a command directly (no shell), given as an argv list."""
        if not argv:
            return '', 1
        try:
            r = subprocess.run(argv, shell=False, capture_output=True, text=True,
                               timeout=timeout, creationflags=_NW)
            return r.stdout.strip() + r.stderr.strip(), r.returncode
        except Exception as e:
            return str(e), 1

    # Strategy 1: QuietUninstallString (cleanest)
    if quiet_str:
        log_cb('  → Trying QuietUninstallString...', 'info')
        out, code = _run(_win_argv(quiet_str))
        if code == 0:
            return out, code

    # Strategy 2: MSI GUID
    guid_src = uninstall_str or reg_key
    guid_match = re.search(
        r'\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}',
        guid_src, re.IGNORECASE,
    )
    if guid_match or uninstall_str.upper().startswith('MSIEXEC'):
        guid = guid_match.group(0) if guid_match else ''
        if guid:
            log_cb(f'  → MSI uninstall {guid}...', 'info')
            out, code = _run(['msiexec', '/x', guid, '/qb-', 'REBOOT=ReallySuppress'])
            if code in (0, 3010):
                return out, 0
            out, code = _run(['msiexec', '/x', guid, '/qn', 'REBOOT=ReallySuppress'])
            if code in (0, 3010):
                return out, 0
            log_cb(f'  ✗ msiexec failed ({code}) — trying EXE fallback', 'warn')

    # Strategy 3: EXE uninstall_str
    if uninstall_str and not uninstall_str.upper().startswith('MSIEXEC'):
        from pathlib import Path as _Path

        exe_match = re.match(r'^"([^"]+)"(.*)$', uninstall_str)
        if exe_match:
            exe  = exe_match.group(1).strip()
            args = exe_match.group(2).strip()
        else:
            m = re.match(r'^(.*?\.exe)\s*(.*)$', uninstall_str, re.IGNORECASE)
            if m:
                exe  = m.group(1).strip()
                args = m.group(2).strip()
            else:
                exe, args = uninstall_str, ''

        if not _Path(exe).exists():
            log_cb(f'  ✗ Uninstaller not found: {exe}', 'err')
            return '', 1

        fname = _Path(exe).name.lower()
        existing_args_lower = args.lower()
        # args (the trailing portion of uninstall_str after the exe path)
        # can itself contain quoted segments, so it goes through _win_argv
        # too rather than a plain .split() — same reasoning as above.
        args_argv = _win_argv(args)

        if any(flag in existing_args_lower for flag in ('/s', '/silent', '/quiet', '/q', '--quiet')):
            log_cb('  → Running with existing silent flags...', 'info')
            out, code = _run([exe] + args_argv)
            if code == 0:
                return out, code

        if 'unins' in fname or 'inno' in fname:
            log_cb('  → Inno Setup silent uninstall...', 'info')
            out, code = _run([exe, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'] + args_argv)
            if code == 0: return out, code
            out, code = _run([exe, '/SILENT', '/NORESTART'] + args_argv)
            if code == 0: return out, code

        if 'nsis' in fname or fname in ('uninst.exe', 'uninstall.exe'):
            log_cb('  → NSIS silent uninstall...', 'info')
            out, code = _run([exe, '/S'] + args_argv)
            if code == 0: return out, code

        for flag in ['/S', '/silent', '/quiet', '/Q', '--quiet', '/VERYSILENT']:
            log_cb(f'  → Trying {flag}...', 'info')
            out, code = _run([exe, flag] + args_argv)
            if code == 0: return out, code

        log_cb('  → Running uninstaller (may show UI)...', 'warn')
        out, code = _run([exe] + args_argv)
        return out, code

    return '', 1


# ── UNINSTALL ──────────────────────────────────────────────────
def uninstall_app(app: InstalledApp, log_cb: Callable):
    """
    Uninstall an app. Returns:
      True              — success (silent uninstall completed)
      False             — failure
      'UI_OPENED'       — interactive uninstaller launched (compat sentinel)
      UninstallResult   — structured result (new call sites)

    Old call sites checking `== True` / `== False` / `== 'UI_OPENED'` still work.
    """
    log_cb(f'Uninstalling {app.name}...', 'info')
    out, code = '', 1

    if app.source in _PM_SOURCES:
        # Hàng rào sớm cho UI; helper (chạy bằng root) kiểm tra lại độc lập.
        if is_protected(app):
            log_cb(f'  ✗ {app.pkg_id} is a protected system package (kernel / bootloader / init / sudo / '
                   f'network…) — refusing to remove it.', 'err')
            return False
        # KHÔNG còn fallback `sudo pacman -Rns …` / `sudo apt-get remove …`: nếu helper từ chối (gói lõi, tên
        # không hợp lệ) mà fallback vẫn chạy được (máy có sudo NOPASSWD: ALL) thì hàng rào bị vô hiệu hóa.
        from . import privileged as P
        r = P.run_helper(f'{app.source}-remove', app.pkg_id, timeout=300)
        out, code = (r.out if r.ok else r.message), r.code

    elif app.source == 'flatpak':
        if not re.match(r'^[A-Za-z0-9][A-Za-z0-9_.\-]{0,254}$', app.pkg_id or ''):
            log_cb('  ✗ Invalid Flatpak id', 'err')
            return False
        out, code = _run_argv(['flatpak', 'uninstall', '-y', '--noninteractive', app.pkg_id], timeout=180)

    elif app.source == 'winget':
        # argv, không shell: tên gói lấy từ output của `winget list` — không được phép trở thành câu lệnh.
        if not app.pkg_id or app.pkg_id.startswith('-'):
            log_cb('  ✗ Invalid winget id', 'err')
            return False
        out, code = _run_argv(['winget', 'uninstall', '--id', app.pkg_id, '--exact', '--silent'], timeout=180)

    elif app.source == 'registry':
        parts         = app.pkg_id.split('|||', 2)
        reg_key       = parts[0].strip() if len(parts) > 0 else ''
        uninstall_str = parts[1].strip() if len(parts) > 1 else ''
        quiet_str     = parts[2].strip() if len(parts) > 2 else ''

        if not quiet_str and uninstall_str:
            # FIX: Popen với CREATE_NO_WINDOW flag để không flash console.
            # Thêm check uninstall_str hợp lệ trước khi Popen.
            # Nếu uninstall_str trỏ tới file không tồn tại → báo lỗi rõ ràng
            # thay vì mở process lỗi → user thấy app biến khỏi list nhưng
            # thực ra chưa gỡ được.
            from pathlib import Path as _P
            import re as _re
            _exe_m = _re.match(r'^"([^"]+)"', uninstall_str) or _re.match(r'^(\S+\.exe)', uninstall_str, _re.IGNORECASE)
            if _exe_m:
                _exe_path = _P(_exe_m.group(1))
                if not _exe_path.exists():
                    log_cb(f'  ✗ Uninstaller not found: {_exe_path}', 'err')
                    log_cb(f'  i App may already be partially uninstalled.', 'warn')
                    return False
            try:
                _argv = _win_argv(uninstall_str)
                if not _argv:
                    log_cb(f'  ✗ Empty uninstall command for {app.name}.', 'err')
                    return False
                subprocess.Popen(
                    _argv, shell=False,
                    creationflags=_NO_WIN,
                )
                log_cb(f'  ✓ Opened uninstaller for {app.name}.', 'ok')
                log_cb('  ℹ  Complete the uninstall in the new window, then click REFRESH.', 'warn')
            except Exception as _e:
                log_cb(f'  ✗ Cannot launch uninstaller: {_e}', 'err')
                return False
            return 'UI_OPENED'

        out, code = _run_win_uninstall(app.name, reg_key, uninstall_str, quiet_str, log_cb)

    elif app.source in ('local-game', 'wine-app', 'steam-local'):
        from pathlib import Path as _P
        import shutil as _sh
        try:
            from .os_detect import real_home
            home = _P(real_home()).resolve()
        except Exception:
            home = _P.home().resolve()
        target_p = _P(app.pkg_id or '').resolve()
        # Strict safety guard: must be a subdirectory at least 2 levels inside $HOME
        if not target_p.exists() or not target_p.is_dir():
            log_cb(f'  ✗ Folder not found: {target_p}', 'err')
            return False
        if home not in target_p.parents or target_p.parent == home:
            log_cb(f'  ✗ Refusing to delete top-level folder: {target_p}', 'err')
            return False
        try:
            if app.source == 'local-game':
                from .os_detect import safe_delete
                res_del = safe_delete(target_p, use_trash=True)
                if isinstance(res_del, tuple):
                    ok_del = bool(res_del[0])
                    err_del = str(res_del[2]) if len(res_del) > 2 else ""
                else:
                    ok_del = bool(res_del)
                    err_del = ""
                if ok_del:
                    out, code = f'Moved {target_p} to Trash', 0
                else:
                    out, code = err_del or f'Failed to move {target_p} to Trash (data kept intact)', 1
            else:
                _sh.rmtree(target_p)
                out, code = f'Removed {target_p}', 0
        except Exception as e:
            out, code = str(e), 1

    else:
        log_cb(f'  ✗ Unknown source: {app.source}', 'err')
        return False

    if code == 0:
        log_cb(f'  ✓ Uninstalled {app.name}', 'ok')
        return True
    else:
        log_cb(f'  ✗ Failed ({code}): {out[:200]}', 'err')
        return False
