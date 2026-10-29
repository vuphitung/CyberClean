#!/usr/bin/env python3
"""
CyberClean — Build Script
VERSION được đọc tự động từ version.py — không bao giờ hardcode ở đây nữa.

Usage:
  python3 build.py              → auto-detect platform
  python3 build.py --windows    → build .exe  (run on Windows)
  python3 build.py --inno       → build .exe + generate Inno Setup script
  python3 build.py --linux      → build tar.gz  (run on Linux)
  python3 build.py --appimage   → build AppImage
  python3 build.py --deb        → build .deb  (Debian/Ubuntu)
  python3 build.py --check      → check dependencies only
"""
import sys, os, shutil, subprocess, platform, re
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8')
except (AttributeError, OSError):
    pass

OS   = platform.system()
ROOT = Path(__file__).parent
DIST = ROOT / 'dist'
BUILD = ROOT / 'build'

# ── Version đọc từ version.py (single source of truth) ───
def _read_version() -> str:
    """
    Đọc version từ version.py — không hardcode ở đây.
    Fallback về '0.0.0' nếu không tìm thấy để build không crash.
    """
    vfile = ROOT / 'version.py'
    if not vfile.exists():
        print(f"  ⚠  version.py not found — using 0.0.0 (create it!)")
        return '0.0.0'
    src = vfile.read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*["\'](.+?)["\']', src)
    if not m:
        print(f"  ⚠  __version__ not found in version.py — using 0.0.0")
        return '0.0.0'
    return m.group(1)

VERSION = _read_version()

APP    = 'CyberClean'
AUTHOR = 'vuphitung'
URL    = f'https://github.com/{AUTHOR}/{APP}'

ICON_ICO = ROOT / 'assets' / 'logo.ico'
ICON_PNG = ROOT / 'assets' / 'logo.png'

# ── Colors ────────────────────────────────────────────────
G = '\033[0;32m'; Y = '\033[1;33m'; R = '\033[0;31m'
C = '\033[0;36m'; B = '\033[0;34m'; NC = '\033[0m'

def ok(msg):   print(f'  {G}✓{NC}  {msg}')
def warn(msg): print(f'  {Y}⚠{NC}  {msg}')
def err(msg):  print(f'  {R}✗{NC}  {msg}')
def head(msg): print(f'\n{B}━━━ {msg} ━━━{NC}')

def run(cmd, **kw):
    return subprocess.run(cmd, shell=True, **kw)

def _pyinstaller_bin() -> str:
    if shutil.which('pyinstaller'):
        return 'pyinstaller'
    local = Path.home() / '.local/bin/pyinstaller'
    if local.exists():
        return str(local)
    return f'{sys.executable} -m PyInstaller'

def _has_pyinstaller() -> bool:
    try:
        __import__('PyInstaller')
        return True
    except ImportError:
        return False

# ── Dependency check ──────────────────────────────────────
def check_deps():
    head(f'Checking dependencies  [v{VERSION}]')
    ok_all = True
    for pkg, hint in {
        'psutil':       'sudo pacman -S python-psutil  OR  pip install psutil --break-system-packages',
        'PyQt6':        'sudo pacman -S python-pyqt6   OR  pip install PyQt6  --break-system-packages',
        'cryptography': 'pip install cryptography --break-system-packages',
        'send2trash':   'pip install send2trash --break-system-packages  '
                         '(REQUIRED — without it, deletes silently become permanent instead of going to Trash)',
    }.items():
        try:
            __import__(pkg); ok(pkg)
        except ImportError:
            err(f'{pkg} missing - {hint}'); ok_all = False

    if _has_pyinstaller():
        ok(f'PyInstaller  ({_pyinstaller_bin()})')
    else:
        err('PyInstaller missing - python3 -m pip install pyinstaller --break-system-packages')
        ok_all = False
    return ok_all

# ── PyInstaller shared options ────────────────────────────
def _pyinstaller_cmd(onefile: bool, icon: Path | None) -> str:
    sep  = ';' if OS == 'Windows' else ':'
    mode = '--onefile' if onefile else '--onedir'

    if sys.platform == "win32":
        import json, hashlib
        vendor = ROOT / 'vendor' / 'lhm'
        manifest = json.loads((vendor / 'manifest.json').read_text(encoding='utf-8'))
        for name, expected in manifest['sha256'].items():
            if hashlib.sha256((vendor / name).read_bytes()).hexdigest() != expected:
                raise RuntimeError(f'Missing or mismatched Windows dependency: {name}')

    parts = [
        f'{_pyinstaller_bin()} {mode} --noconsole --noconfirm',
        f'--name {APP}',
        f'--add-data "VERSION{sep}."',           # bundle VERSION file (matches CyberClean.spec)
        f'--add-data "rules/*.toml{sep}rules"',   # luật dọn rác khai báo (core/rules.py)
        f'--add-data "packaging/cyber-clean-helper{sep}packaging"',
        f'--add-data "assets{sep}assets"',
    ]

    if sys.platform == "win32":
        parts.append(f'--add-data "vendor/lhm{sep}vendor/lhm"')
        parts.extend(['--hidden-import pythonnet', '--hidden-import utils.windows_temperature_host'])

    parts += [
        '--hidden-import psutil',
        '--hidden-import PyQt6',
        '--hidden-import PyQt6.QtWidgets',
        '--hidden-import PyQt6.QtCore',
        '--hidden-import PyQt6.QtGui',
        '--hidden-import utils.updater',
        '--hidden-import json',
        '--hidden-import urllib.request',
        '--hidden-import urllib.error',
        '--hidden-import tarfile',
        '--hidden-import tempfile',
        '--hidden-import tomllib',
        '--hidden-import ui_widgets',
        '--hidden-import ui_pages',
        '--hidden-import core.game_boost_widget',
        '--hidden-import clr',
        '--hidden-import clr._extra',
        # send2trash is only ever imported inside a try/except inside a function
        # (core/os_detect.py) — PyInstaller's static scanner can miss that pattern.
        # Without it bundled, HAS_SEND2TRASH silently becomes False at runtime and
        # every "delete" becomes a permanent delete instead of going to Trash.
        '--hidden-import send2trash',
        '--hidden-import cryptography.hazmat.primitives.asymmetric.ed25519',
        '--exclude-module tkinter',
        '--exclude-module matplotlib',
        '--exclude-module numpy',
        '--exclude-module gi',
    ]
    if icon and icon.exists():
        parts.append(f'--icon "{icon}"')
        ok(f'Icon: {icon.name}')
    else:
        warn(f'No icon at {icon} - building without icon')

    parts.append('main.py')
    return ' '.join(parts)

# ── Windows build ─────────────────────────────────────────
def build_windows(make_inno: bool = False):
    head(f'Building Windows .exe  [v{VERSION}]')
    if not _has_pyinstaller():
        err('PyInstaller not found')
        return False

    DIST.mkdir(exist_ok=True)
    # onedir (not onefile): keeps DLLs next to exe instead of extracting to %TEMP%
    # onefile extracts python312.dll etc to %TEMP% at runtime -> AV blocks it
    cmd = _pyinstaller_cmd(onefile=False, icon=ICON_ICO)
    if run(cmd).returncode != 0:
        err('Build failed')
        return False

    app_dir = DIST / APP
    exe = app_dir / f'{APP}.exe'
    if not exe.exists():
        err(f'{exe} not found after build')
        return False

    if not _build_windows_sensor_host(app_dir):
        err('Protected temperature helper build failed')
        return False

    ok(f'Built: {app_dir}  ({sum(f.stat().st_size for f in app_dir.rglob("*") if f.is_file()) / 1024/1024:.1f} MB total)')
    if make_inno:
        _generate_inno_script(exe)
    return True


def _build_windows_sensor_host(app_dir: Path) -> bool:
    """Bundle the minimal read-only elevated helper beside the normal GUI."""
    helper_name = 'CyberCleanSensorHost'
    helper_dist = BUILD / 'sensor-host-dist'
    helper_work = BUILD / 'sensor-host-work'
    if helper_dist.exists():
        shutil.rmtree(helper_dist)
    if helper_work.exists():
        shutil.rmtree(helper_work)
    helper_dist.mkdir(parents=True)
    helper_work.mkdir(parents=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    sep = ';'
    vendor_dir = ROOT / 'vendor' / 'lhm'
    entrypoint = ROOT / 'sensor_host_entry.py'
    cmd = ' '.join([
        f'{_pyinstaller_bin()} --onedir --noconsole --clean',
        f'--name {helper_name}',
        f'--distpath "{helper_dist}"',
        f'--workpath "{helper_work}"',
        f'--specpath "{BUILD}"',
        f'--add-data "{vendor_dir}{sep}vendor/lhm"',
        '--hidden-import pythonnet',
        '--hidden-import utils.windows_temperature_host',
        '--hidden-import clr',
        f'"{entrypoint}"',
    ])
    if run(cmd).returncode != 0:
        return False
    built = helper_dist / helper_name
    if not (built / f'{helper_name}.exe').is_file():
        return False
    internal = built / '_internal'
    if not (internal / 'vendor' / 'lhm' / 'manifest.json').is_file():
        return False
    destination = app_dir / 'sensor-host'
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(built, destination)
    ok(f'Bundled protected sensor helper: {destination / (helper_name + ".exe")}')
    return True


def _generate_inno_script(exe: Path):
    head('Generating Inno Setup script')

    # Resolve icon path to absolute (Inno needs absolute or relative-to-script path)
    if ICON_ICO.exists():
        # Use relative path from project root — works when .iss is in project root
        icon_line = f'SetupIconFile=assets\\logo.ico'
    else:
        icon_line = '; SetupIconFile=assets\\logo.ico  (file not found — add logo.ico)'

    iss_lines = [
        f'; CyberClean v{VERSION} — Inno Setup Script',
        '; AUTO-GENERATED by build.py — do not edit VERSION here, edit version.py',
        '; Build: Open in Inno Setup Compiler → Compile (F9)',
        '; Download Inno Setup: https://jrsoftware.org/isinfo.php',
        '',
        '[Setup]',
        f'AppName={APP}',
        f'AppVersion={VERSION}',
        f'AppPublisher={AUTHOR}',
        f'AppPublisherURL={URL}',
        f'AppSupportURL={URL}/issues',
        f'AppUpdatesURL={URL}/releases',
        r'DefaultDirName={autopf}' + f'\\{APP}',
        f'DefaultGroupName={APP}',
        'AllowNoIcons=yes',
        'OutputDir=dist',
        f'OutputBaseFilename={APP}_Setup_v{VERSION}',
        icon_line,
        'Compression=lzma',
        'CloseApplications=yes',                    # Báo Setup đóng app đang chạy
        'RestartApplications=no',                   # Không tự restart app sau khi cài
        'AppMutex=CyberClean_Single_Instance_Lock', # Tên mutex — Setup dùng để detect process cũ
        'SolidCompression=yes',
        'WizardStyle=modern',
        'PrivilegesRequired=admin',
        f'UninstallDisplayName={APP}',
        r'UninstallDisplayIcon={app}' + f'\\{APP}.exe',
        f'VersionInfoVersion={VERSION}.0',   # Windows needs 4-part: 2.2.0.0
        'VersionInfoDescription=Smart Disk Cleaner',
        'VersionInfoCompany=' + AUTHOR,
        'VersionInfoProductName=' + APP,
        '',
        '[Languages]',
        'Name: "english"; MessagesFile: "compiler:Default.isl"',
        '',
        '[Tasks]',
        'Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"',
        '',
        '[Files]',
        f'Source: "dist\\{APP}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs',
        '',
        '[Icons]',
        '; Shortcut trực tiếp vào .exe — không dùng schtasks',
        '; schtasks /rl highest dễ bị Defender/EDR đánh dấu hành vi đáng ngờ',
        f'Name: "{{group}}\\{APP}"; Filename: "{{app}}\\{APP}.exe"',
        f'Name: "{{group}}\\Uninstall {APP}"; Filename: "{{uninstallexe}}"',
        f'Name: "{{userdesktop}}\\{APP}"; Filename: "{{app}}\\{APP}.exe"; Tasks: desktopicon',
        '',
        '[Run]',
        '; Launch app sau khi cài xong',
        f'Filename: "{{app}}\\{APP}.exe"; Description: "Launch {APP}"; Flags: nowait postinstall',
        '',
        '[UninstallDelete]',
        f'Type: filesandordirs; Name: "{{localappdata}}\\{APP}"',
        f'Type: filesandordirs; Name: "{{userappdata}}\\{APP}"',
    ]

    iss_path = ROOT / f'{APP}.iss'
    iss_path.write_text('\n'.join(iss_lines) + '\n', encoding='utf-8')
    ok(f'Inno script: {iss_path}')
    print(f'\n  {C}Next:{NC}')
    print(f'  1. Open {APP}.iss in Inno Setup Compiler')
    print(f'  2. Press Compile (F9) → dist/{APP}_Setup_v{VERSION}.exe')
    print(f'  3. Upload .exe to GitHub Releases\n')


# ── Linux AppImage ────────────────────────────────────────
def build_linux_appimage():
    head(f'Building Linux AppImage  [v{VERSION}]')
    if not _has_pyinstaller():
        err('PyInstaller not found')
        return False

    cmd = _pyinstaller_cmd(onefile=False, icon=ICON_PNG)
    if run(cmd).returncode != 0:
        err('PyInstaller step failed')
        return False

    appdir = BUILD / 'AppDir'
    if appdir.exists():
        shutil.rmtree(appdir)
    appdir.mkdir(parents=True)

    bundle_dir = appdir / 'usr/bin' / APP
    shutil.copytree(DIST / APP, bundle_dir)
    helper_src = ROOT / 'packaging' / 'cyber-clean-helper'
    if helper_src.exists():
        shutil.copy2(helper_src, bundle_dir / 'cyber-clean-helper')
        (bundle_dir / 'cyber-clean-helper').chmod(0o755)
    (bundle_dir / 'VERSION').write_text(VERSION + '\n', encoding='utf-8')

    apprun = appdir / 'AppRun'
    apprun.write_text(
        '#!/bin/bash\n'
        f'exec "$APPDIR/usr/bin/{APP}/{APP}" "$@"\n',
        encoding='utf-8')
    apprun.chmod(0o755)

    (appdir / f'{APP}.desktop').write_text(
        f'[Desktop Entry]\n'
        f'Name={APP}\n'
        f'Exec={APP}\n'
        f'Icon={APP}\n'
        f'Type=Application\n'
        f'Categories=System;Utility;\n'
        f'Comment=Smart Disk Cleaner v{VERSION}\n',
        encoding='utf-8')

    if ICON_PNG.exists():
        shutil.copy(ICON_PNG, appdir / f'{APP}.png')
    else:
        warn(f'No icon at {ICON_PNG}')

    MIN_SIZE = 1_000_000
    tool = Path('/tmp/appimagetool')
    if not tool.exists() or tool.stat().st_size < MIN_SIZE:
        warn('Downloading appimagetool...')
        run(
            'wget -q -O /tmp/appimagetool '
            '"https://github.com/AppImage/AppImageKit/releases/download/'
            'continuous/appimagetool-x86_64.AppImage"'
        )
        if not tool.exists() or tool.stat().st_size < MIN_SIZE:
            err('appimagetool download failed — check internet / GitHub status')
            return False
        tool.chmod(0o755)

    out = DIST / f'{APP}-{VERSION}-x86_64.AppImage'
    DIST.mkdir(exist_ok=True)
    result = run(f'ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 /tmp/appimagetool {appdir} {out}')
    if result.returncode == 0 and out.exists():
        out.chmod(0o755)
        ok(f'Built: {out}  ({out.stat().st_size/1024/1024:.1f} MB)')
        _print_release_note(out)
        return True

    err('AppImage packaging failed')
    return False


# ── Linux .deb ────────────────────────────────────────────
def build_linux_deb():
    head(f'Building Linux .deb  [v{VERSION}]')
    if not _has_pyinstaller():
        err('PyInstaller not found')
        return False

    cmd = _pyinstaller_cmd(onefile=False, icon=ICON_PNG)
    if run(cmd).returncode != 0:
        err('PyInstaller step failed')
        return False

    pkg_name = APP.lower()
    deb_root = BUILD / f'{pkg_name}_{VERSION}'
    if deb_root.exists():
        shutil.rmtree(deb_root)

    install_dir = deb_root / f'opt/{APP}'
    install_dir.mkdir(parents=True)
    bundle_dir = install_dir / APP
    shutil.copytree(DIST / APP, bundle_dir)
    helper_src = ROOT / 'packaging' / 'cyber-clean-helper'
    if helper_src.exists():
        shutil.copy2(helper_src, bundle_dir / 'cyber-clean-helper')
        (bundle_dir / 'cyber-clean-helper').chmod(0o755)
    (bundle_dir / 'VERSION').write_text(VERSION + '\n', encoding='utf-8')

    apps_dir = deb_root / 'usr/share/applications'
    apps_dir.mkdir(parents=True)
    icon_dest = deb_root / f'usr/share/pixmaps/{APP}.png'
    icon_dest.parent.mkdir(parents=True)
    if ICON_PNG.exists():
        shutil.copy(ICON_PNG, icon_dest)

    (apps_dir / f'{APP}.desktop').write_text(
        f'[Desktop Entry]\n'
        f'Name={APP}\n'
        f'Exec=/opt/{APP}/{APP}/{APP}\n'
        f'Icon={APP}\n'
        f'Type=Application\n'
        f'Categories=System;Utility;\n'
        f'Comment=Smart Disk Cleaner v{VERSION}\n'
        f'Terminal=false\n',
        encoding='utf-8')

    debian_dir = deb_root / 'DEBIAN'
    debian_dir.mkdir()
    (debian_dir / 'control').write_text(
        f'Package: {pkg_name}\n'
        f'Version: {VERSION}\n'
        f'Architecture: amd64\n'
        f'Maintainer: {AUTHOR} <{AUTHOR}@users.noreply.github.com>\n'
        f'Description: Smart Disk Cleaner\n'
        f' CyberClean — safe, fast disk cleaning for Linux.\n'
        f'Homepage: {URL}\n'
        f'Section: utils\n'
        f'Priority: optional\n'
        f'Depends: libxcb-cursor0\n',     # Qt6 runtime dep on Ubuntu 22.04+
        encoding='utf-8')

    postinst = debian_dir / 'postinst'
    postinst.write_text(
        '#!/bin/bash\n'
        'set -e\n'
        f'chown -R root:root /opt/{APP}\n'
        f'chmod +x /opt/{APP}/{APP}/{APP}\n'
        f'if [[ -f /opt/{APP}/{APP}/cyber-clean-helper ]]; then\n'
        f'    chmod 0755 /opt/{APP}/{APP}/cyber-clean-helper\n'
        f'    /opt/{APP}/{APP}/cyber-clean-helper install-helper || true\n'
        'fi\n'
        f'ln -sf /opt/{APP}/{APP}/{APP} /usr/local/bin/cyberclean 2>/dev/null || true\n'
        'update-desktop-database /usr/share/applications 2>/dev/null || true\n',
        encoding='utf-8')
    postinst.chmod(0o755)

    postrm = debian_dir / 'postrm'
    postrm.write_text(
        '#!/bin/bash\n'
        f'rm -rf /opt/{APP}\n'
        'rm -f /usr/local/bin/cyberclean /usr/local/bin/cyber-clean-helper /etc/sudoers.d/cyberclean 2>/dev/null || true\n'
        'update-desktop-database /usr/share/applications 2>/dev/null || true\n',
        encoding='utf-8')
    postrm.chmod(0o755)

    DIST.mkdir(exist_ok=True)
    out = DIST / f'{pkg_name}_{VERSION}_amd64.deb'
    if run(f'dpkg-deb --build {deb_root} {out}').returncode == 0 and out.exists():
        ok(f'Built: {out}  ({out.stat().st_size/1024/1024:.1f} MB)')
        print(f'\n  {C}Install:{NC}  sudo apt install ./{out.name}')
        print(f'  {C}Remove:{NC}   sudo apt remove {pkg_name}\n')
        return True

    err('.deb build failed — is dpkg-deb installed?  (sudo apt install dpkg)')
    return False


# ── Linux tar.gz ──────────────────────────────────────────
def build_linux_targz():
    head(f'Building Linux tar.gz  [v{VERSION}]')
    if not _has_pyinstaller():
        err('PyInstaller not found')
        return False

    cmd = _pyinstaller_cmd(onefile=False, icon=ICON_PNG)
    if run(cmd).returncode != 0:
        err('PyInstaller step failed')
        return False

    DIST.mkdir(exist_ok=True)
    # Helper đặc quyền + VERSION nằm CẠNH file thực thi, bên trong gói được ký:
    #   • install.sh / `update-apply` lấy helper từ đây (một nguồn duy nhất, đã xác minh chữ ký);
    #   • `update-apply` dùng VERSION để chống replay/downgrade.
    bundle = DIST / APP
    helper_src = ROOT / 'packaging' / 'cyber-clean-helper'
    if not helper_src.exists():
        err('packaging/cyber-clean-helper missing')
        return False
    shutil.copy2(helper_src, bundle / 'cyber-clean-helper')
    (bundle / 'cyber-clean-helper').chmod(0o755)
    (bundle / 'VERSION').write_text(VERSION + '\n', encoding='utf-8')
    out = DIST / f'{APP}-{VERSION}-linux-x86_64.tar.gz'
    run(f'tar -czf {out} -C {DIST} {APP}')
    if out.exists():
        ok(f'Built: {out}  ({out.stat().st_size/1024/1024:.1f} MB)')
        _print_release_note(out)
        return True

    err('tar.gz build failed')
    return False


# ── Linux zip fallback ────────────────────────────────────
def build_linux_zip():
    head(f'Building source zip fallback  [v{VERSION}]')
    DIST.mkdir(exist_ok=True)
    out = DIST / f'{APP}-{VERSION}-linux-source.zip'
    run(f'zip -r {out} main.py ui_widgets.py ui_pages.py version.py core/ utils/ rules/ packaging/ assets/ requirements.txt install.sh README.md README_vi.md CHANGELOG.md LICENSE 2>/dev/null')
    if out.exists():
        ok(f'Built: {out}')
        return True
    return False


def _print_release_note(path: Path):
    print(f'\n  {C}Upload to GitHub Releases:{NC}')
    print(f'  gh release create v{VERSION} {path} \\')
    print(f'      --title "v{VERSION}" --notes "See CHANGELOG"\n')


# ── Main ──────────────────────────────────────────────────
def main():
    print(f'\n{C}  ⚡ {APP} Build Tool — v{VERSION}{NC}\n')
    args = sys.argv[1:]

    if '--check' in args:
        check_deps()
        return

    if not check_deps():
        print(f'\n{R}Fix dependencies first, then re-run.{NC}')
        return

    make_inno = '--inno'     in args
    make_deb  = '--deb'      in args
    make_aimg = '--appimage' in args

    if   '--windows' in args or make_inno:  target = 'Windows'
    elif '--linux'   in args or make_deb or make_aimg: target = 'Linux'
    else: target = OS

    success = False

    if target == 'Windows':
        success = build_windows(make_inno=make_inno)
    elif target == 'Linux':
        if make_deb:
            success = build_linux_deb()
        elif make_aimg:
            success = build_linux_appimage()
        else:
            success = build_linux_targz()
    else:
        warn(f'Platform "{target}" not recognized — use --windows or --linux')

    status = f'{G}✅ Done → {DIST}{NC}' if success else f'{R}✗ Build failed{NC}'
    print(f'\n  {status}\n')


if __name__ == '__main__':
    main()
