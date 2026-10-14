"""
CyberClean — OS Detection & Abstraction Layer

FIXED vs v2.2:
- HAS_POLKIT chỉ check helper binary (đã đúng từ v2.1)
- Import version từ version.py thay vì hardcode
- safe_delete dùng Exception thay bare except
- platform_info() bổ sung thêm de_name, wayland flag
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
DISTRO_LIKE: list = []        # ID_LIKE trong /etc/os-release (vd: ['ubuntu', 'debian'])
PKG_MANAGER = ''
IS_OSTREE   = False           # Fedora Atomic / Silverblue / Bazzite / Kinoite...

# Họ distro → package manager. Tra theo ID rồi lần lượt từng phần tử ID_LIKE,
# nên các bản con (Pop!_OS, Zorin, MX, Nobara, Bazzite, CachyOS...) tự được nhận
# mà không phải liệt kê tay từng cái.
_FAMILY_PM = {
    'arch': 'pacman', 'manjaro': 'pacman', 'endeavouros': 'pacman', 'garuda': 'pacman',
    'artix': 'pacman', 'cachyos': 'pacman', 'arcolinux': 'pacman', 'steamos': 'pacman',
    'debian': 'apt', 'ubuntu': 'apt', 'linuxmint': 'apt', 'pop': 'apt', 'elementary': 'apt',
    'zorin': 'apt', 'kali': 'apt', 'raspbian': 'apt', 'parrot': 'apt', 'mx': 'apt', 'neon': 'apt',
    'fedora': 'dnf', 'rhel': 'dnf', 'centos': 'dnf', 'rocky': 'dnf', 'almalinux': 'dnf',
    'alma': 'dnf', 'ol': 'dnf', 'amzn': 'dnf', 'nobara': 'dnf',
    'opensuse': 'zypper', 'opensuse-leap': 'zypper', 'opensuse-tumbleweed': 'zypper',
    'suse': 'zypper', 'sles': 'zypper', 'sled': 'zypper',
    'void': 'xbps',
    'alpine': 'apk',
    'nixos': 'nix',
}
_PM_BINARIES = (('pacman', 'pacman'), ('apt-get', 'apt'), ('dnf', 'dnf'), ('zypper', 'zypper'),
                ('xbps-remove', 'xbps'), ('apk', 'apk'))


def parse_os_release(text: str) -> dict:
    """Parse /etc/os-release (KEY=value, có/không có nháy). Hàm thuần để test được."""
    out = {}
    for line in (text or '').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
            v = v[1:-1]
        out[k.strip()] = v
    return out


def detect_pkg_manager(distro_id: str, id_like, *, which=shutil.which,
                       exists=os.path.exists) -> str:
    """Hàm thuần: ID + ID_LIKE (+ dò binary nếu cần) → package manager."""
    # Fedora Atomic: dnf không áp dụng cho host, dùng rpm-ostree
    if exists('/run/ostree-booted') and which('rpm-ostree'):
        return 'rpm-ostree'
    for ident in [distro_id] + list(id_like or []):
        pm = _FAMILY_PM.get((ident or '').lower())
        if pm:
            return pm
    for binary, pm in _PM_BINARIES:
        if which(binary):
            return pm
    if which('nix-collect-garbage') and exists('/etc/NIXOS'):
        return 'nix'
    return ''


if IS_LINUX:
    _osr = {}
    try:
        _osr = parse_os_release(Path('/etc/os-release').read_text(encoding='utf-8', errors='replace'))
    except Exception:
        try:
            _osr = parse_os_release(Path('/usr/lib/os-release').read_text(encoding='utf-8', errors='replace'))
        except Exception:
            pass
    DISTRO = (_osr.get('ID') or '').lower()
    DISTRO_LIKE = [x.lower() for x in (_osr.get('ID_LIKE') or '').split()]
    if not DISTRO:
        try:
            import distro as _d
            DISTRO = _d.id().lower()
        except ImportError:
            pass
    IS_OSTREE = os.path.exists('/run/ostree-booted')
    PKG_MANAGER = detect_pkg_manager(DISTRO, DISTRO_LIKE)

# ── Desktop Environment detection ─────────────────────────
DE_NAME    = ''
IS_WAYLAND = False

if IS_LINUX:
    DE_NAME    = os.environ.get('XDG_CURRENT_DESKTOP', '') or \
                 os.environ.get('DESKTOP_SESSION', '')
    IS_WAYLAND = bool(os.environ.get('WAYLAND_DISPLAY') or
                      os.environ.get('XDG_SESSION_TYPE', '') == 'wayland')

# ── Polkit ────────────────────────────────────────────────
POLKIT_HELPER = '/usr/local/bin/cyber-clean-helper'
HAS_POLKIT    = IS_LINUX and Path(POLKIT_HELPER).exists()
SUDO          = '' if IS_ROOT else 'sudo '


def _polkit_agent_running() -> bool:
    try:
        out = subprocess.run(
            ['pgrep', '-f', 'polkit'],
            capture_output=True, text=True
        ).stdout
        if out.strip():
            return True
        dbus = subprocess.run(
            ['dbus-send', '--print-reply', '--dest=org.freedesktop.DBus',
             '/org/freedesktop/DBus', 'org.freedesktop.DBus.ListNames'],
            capture_output=True, text=True, timeout=3
        ).stdout
        return any(k in dbus for k in ['policykit', 'polkit', 'lxpolkit'])
    except Exception:
        return False


HAS_POLKIT_AGENT = IS_LINUX and (IS_ROOT or _polkit_agent_running())

# ── Windows UAC ───────────────────────────────────────────
def is_windows_admin() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def request_windows_admin():
    """Re-launch with UAC elevation."""
    if not IS_WINDOWS or is_windows_admin():
        return
    import ctypes, subprocess as _sp
    # subprocess.list2cmdline escapes args correctly for Windows
    args = _sp.list2cmdline(sys.argv)
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, args, None, 1
    )
    sys.exit(0)


# ── Optional features ─────────────────────────────────────
HAS_FLATPAK    = IS_LINUX and bool(shutil.which('flatpak'))
HAS_PODMAN     = IS_LINUX and bool(shutil.which('podman'))
HAS_DOCKER_BIN = IS_LINUX and bool(shutil.which('docker'))
HAS_DOCKER     = HAS_PODMAN or HAS_DOCKER_BIN
CONTAINER_TOOL = 'podman' if HAS_PODMAN else ('docker' if HAS_DOCKER_BIN else '')
HAS_YAY        = IS_LINUX and bool(shutil.which('yay'))
HAS_PARU       = IS_LINUX and bool(shutil.which('paru'))
HAS_JOURNALCTL = IS_LINUX and bool(shutil.which('journalctl'))
HAS_SNAP       = IS_LINUX and bool(shutil.which('snap'))
HAS_XBPS       = IS_LINUX and bool(shutil.which('xbps-remove'))
HAS_APK        = IS_LINUX and bool(shutil.which('apk'))
HAS_NIX        = IS_LINUX and bool(shutil.which('nix-collect-garbage'))
HAS_RPM_OSTREE = IS_LINUX and bool(shutil.which('rpm-ostree'))
HAS_PACCACHE   = IS_LINUX and bool(shutil.which('paccache'))


def _is_wsl() -> bool:
    try:
        return 'microsoft' in Path('/proc/version').read_text(encoding='utf-8', errors='ignore').lower()
    except OSError:
        return False


IS_WSL = IS_LINUX and _is_wsl()

try:
    import send2trash as _s2t
    HAS_SEND2TRASH = True
except Exception:
    # Some Linux/PyInstaller combos (notably GI/GLib overrides) raise
    # non-ImportError exceptions during send2trash import.
    HAS_SEND2TRASH = False


def safe_delete(path: Path, use_trash: bool = True) -> bool:
    """
    Chuyển vào Thùng rác (khôi phục được) nếu có send2trash, ngược lại xóa hẳn.
    Trả về True CHỈ KHI path thật sự không còn tồn tại. Symlink chỉ bị gỡ chính
    nó, không bao giờ xóa thứ nó trỏ tới.
    """
    p = Path(path)
    try:
        if not os.path.lexists(p):
            return True
        if HAS_SEND2TRASH and use_trash:
            try:
                import send2trash
                send2trash.send2trash(str(p))
                return not os.path.lexists(p)
            except Exception:
                pass            # backend Trash lỗi → rơi xuống xóa hẳn
        from core.engine import remove_path
        remove_path(str(p))
        return not os.path.lexists(p)
    except Exception:
        return False


def real_uid() -> int:
    """uid của user THẬT. Khi app chạy bằng sudo/pkexec (euid=0) → uid của người đã gọi."""
    if not IS_LINUX:
        return -1
    if os.geteuid() == 0:
        for var in ('PKEXEC_UID', 'SUDO_UID'):
            v = os.environ.get(var, '')
            if v.isdigit() and int(v) != 0:
                return int(v)
        name = os.environ.get('SUDO_USER', '')
        if name and name != 'root':
            try:
                import pwd
                return pwd.getpwnam(name).pw_uid
            except (KeyError, ImportError):
                pass
    return os.geteuid()


def real_home() -> Path:
    """
    Home của user THẬT. `sudo python3 main.py` có thể để Path.home() == /root (tùy
    env_reset/always_set_home của sudoers) → dọn nhầm /root thay vì home người dùng.
    """
    if IS_LINUX and os.geteuid() == 0:
        uid = real_uid()
        if uid != 0:
            try:
                import pwd
                return Path(pwd.getpwuid(uid).pw_dir)
            except (KeyError, ImportError):
                pass
    return Path.home()


def can_elevate() -> bool:
    if IS_WINDOWS:
        return True
    if IS_ROOT:
        return True
    if HAS_POLKIT:
        return True
    return bool(shutil.which('sudo'))


def platform_info() -> dict:
    return {
        'os':            OS,
        'distro':        DISTRO,
        'distro_like':   DISTRO_LIKE,
        'ostree':        IS_OSTREE,
        'pkg_manager':   PKG_MANAGER,
        'de_name':       DE_NAME,
        'is_wayland':    IS_WAYLAND,
        'arch':          ARCH,
        'is_root':       IS_ROOT,
        'has_polkit':    HAS_POLKIT,
        'polkit_agent':  HAS_POLKIT_AGENT,
        'can_elevate':   can_elevate(),
        'has_flatpak':   HAS_FLATPAK,
        'has_docker':    HAS_DOCKER,
        'has_yay':       HAS_YAY,
        'has_send2trash': HAS_SEND2TRASH,
        'python':        platform.python_version(),
        'is_wsl':        IS_WSL,
        'has_journalctl': HAS_JOURNALCTL,
        'has_snap':      HAS_SNAP,
    }
