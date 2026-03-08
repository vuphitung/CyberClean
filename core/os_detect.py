"""
CyberClean v2.0 — OS Detection & Abstraction Layer
Detects OS, distro, package manager automatically.
"""
import os, sys, platform, shutil
from pathlib import Path

OS   = platform.system()          # 'Linux' | 'Windows' | 'Darwin'
ARCH = platform.machine()

IS_LINUX   = OS == 'Linux'
IS_WINDOWS = OS == 'Windows'
IS_MAC     = OS == 'Darwin'
IS_ROOT    = (os.geteuid() == 0) if IS_LINUX else False

# ── Linux distro detection ────────────────────────────────
DISTRO      = ''
PKG_MANAGER = ''

if IS_LINUX:
    try:
        import distro as _distro
        DISTRO = _distro.id().lower()
    except ImportError:
        # fallback: read /etc/os-release
        try:
            txt = Path('/etc/os-release').read_text()
            for line in txt.splitlines():
                if line.startswith('ID='):
                    DISTRO = line.split('=')[1].strip().strip('"').lower()
        except: pass

    # Map distro → package manager
    if DISTRO in ('arch', 'manjaro', 'endeavouros', 'garuda', 'artix'):
        PKG_MANAGER = 'pacman'
    elif DISTRO in ('ubuntu', 'debian', 'linuxmint', 'pop', 'elementary', 'zorin', 'kali'):
        PKG_MANAGER = 'apt'
    elif DISTRO in ('fedora', 'nobara'):
        PKG_MANAGER = 'dnf'
    elif DISTRO in ('opensuse', 'opensuse-leap', 'opensuse-tumbleweed'):
        PKG_MANAGER = 'zypper'
    elif DISTRO in ('void',):
        PKG_MANAGER = 'xbps'
    else:
        # Try to detect by binary
        for pm in ('pacman','apt','dnf','zypper','xbps-remove'):
            if shutil.which(pm):
                PKG_MANAGER = pm.split('-')[0]
                break

# ── Privilege helper ──────────────────────────────────────
POLKIT_HELPER = '/usr/local/bin/cyber-clean-helper'
HAS_POLKIT    = IS_LINUX and Path(POLKIT_HELPER).exists()
SUDO          = '' if IS_ROOT else 'sudo '

def can_elevate() -> bool:
    """Can we run privileged commands?"""
    if IS_WINDOWS: return True   # UAC handled at runtime
    if IS_ROOT:    return True
    if HAS_POLKIT: return True
    return bool(shutil.which('sudo'))

def platform_info() -> dict:
    return {
        'os':          OS,
        'distro':      DISTRO,
        'pkg_manager': PKG_MANAGER,
        'arch':        ARCH,
        'is_root':     IS_ROOT,
        'has_polkit':  HAS_POLKIT,
        'can_elevate': can_elevate(),
        'python':      platform.python_version(),
    }
