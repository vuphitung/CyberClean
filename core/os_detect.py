"""
CyberClean v2.0 — OS Detection & Abstraction Layer
Detects OS, distro, package manager, polkit agent, privilege status.
"""
import os, sys, platform, shutil, subprocess
from pathlib import Path

OS   = platform.system()
ARCH = platform.machine()

IS_LINUX   = OS == 'Linux'
IS_WINDOWS = OS == 'Windows'
IS_MAC     = OS == 'Darwin'
IS_ROOT    = (os.geteuid() == 0) if IS_LINUX else False

# ── Distro + package manager ──────────────────────────────
DISTRO      = ''
PKG_MANAGER = ''

if IS_LINUX:
    try:
        import distro as _d; DISTRO = _d.id().lower()
    except ImportError:
        try:
            for line in Path('/etc/os-release').read_text().splitlines():
                if line.startswith('ID='):
                    DISTRO = line.split('=')[1].strip().strip('"').lower()
        except: pass

    _PM_MAP = {
        ('arch','manjaro','endeavouros','garuda','artix','cachyos'): 'pacman',
        ('ubuntu','debian','linuxmint','pop','elementary','zorin','kali','raspbian'): 'apt',
        ('fedora','nobara','centos','rhel','rocky','alma'): 'dnf',
        ('opensuse','opensuse-leap','opensuse-tumbleweed'): 'zypper',
        ('void',): 'xbps',
    }
    for distros, pm in _PM_MAP.items():
        if DISTRO in distros:
            PKG_MANAGER = pm; break
    if not PKG_MANAGER:
        for pm in ('pacman','apt','dnf','zypper','xbps-remove'):
            if shutil.which(pm):
                PKG_MANAGER = pm.split('-')[0]; break

# ── Polkit ────────────────────────────────────────────────
POLKIT_HELPER  = '/usr/local/bin/cyber-clean-helper'
POLKIT_POLICY  = '/usr/share/polkit-1/actions/com.nc2077.cyberclean.policy'
HAS_POLKIT     = IS_LINUX and Path(POLKIT_HELPER).exists() and Path(POLKIT_POLICY).exists()
SUDO           = '' if IS_ROOT else 'sudo '

def _polkit_agent_running() -> bool:
    try:
        out = subprocess.run(['pgrep','-f','polkit'], capture_output=True, text=True).stdout
        if out.strip(): return True
        dbus = subprocess.run(
            ['dbus-send','--print-reply','--dest=org.freedesktop.DBus',
             '/org/freedesktop/DBus','org.freedesktop.DBus.ListNames'],
            capture_output=True, text=True, timeout=3).stdout
        return any(k in dbus for k in ['policykit','polkit','lxpolkit'])
    except: return False

HAS_POLKIT_AGENT = IS_LINUX and (IS_ROOT or _polkit_agent_running())

# ── Windows UAC ───────────────────────────────────────────
def is_windows_admin() -> bool:
    if not IS_WINDOWS: return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except: return False

def request_windows_admin():
    """Re-launch with UAC elevation."""
    if not IS_WINDOWS or is_windows_admin(): return
    import ctypes
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable,
        ' '.join(f'"{a}"' for a in sys.argv), None, 1)
    sys.exit(0)

# ── Optional features ─────────────────────────────────────
HAS_FLATPAK    = IS_LINUX and bool(shutil.which('flatpak'))
HAS_DOCKER     = bool(shutil.which('docker') or shutil.which('podman'))
HAS_YAY        = IS_LINUX and bool(shutil.which('yay'))
HAS_PARU       = IS_LINUX and bool(shutil.which('paru'))

try:
    import send2trash as _s2t; HAS_SEND2TRASH = True
except ImportError: HAS_SEND2TRASH = False

def safe_delete(path: Path, use_trash: bool = True) -> bool:
    """Move to Trash (recoverable) if send2trash available, else permanent delete."""
    try:
        if HAS_SEND2TRASH and use_trash:
            import send2trash; send2trash.send2trash(str(path))
        else:
            if path.is_dir(): shutil.rmtree(path, ignore_errors=True)
            else: path.unlink(missing_ok=True)
        return True
    except: return False

def can_elevate() -> bool:
    if IS_WINDOWS: return True
    if IS_ROOT:    return True
    if HAS_POLKIT: return True
    return bool(shutil.which('sudo'))

def platform_info() -> dict:
    return {
        'os': OS, 'distro': DISTRO, 'pkg_manager': PKG_MANAGER,
        'arch': ARCH, 'is_root': IS_ROOT,
        'has_polkit': HAS_POLKIT, 'polkit_agent': HAS_POLKIT_AGENT,
        'can_elevate': can_elevate(),
        'has_flatpak': HAS_FLATPAK, 'has_docker': HAS_DOCKER,
        'has_yay': HAS_YAY, 'has_send2trash': HAS_SEND2TRASH,
        'python': platform.python_version(),
    }
