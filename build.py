#!/usr/bin/env python3
"""
CyberClean v2.0 — Build Script
Packages the app into distributable formats.

Usage:
  python3 build.py              → auto-detect platform
  python3 build.py --windows    → build .exe  (run on Windows)
  python3 build.py --inno       → build .exe + generate Inno Setup script
  python3 build.py --linux      → build AppImage  (run on Linux)
  python3 build.py --deb        → build .deb  (Debian/Ubuntu, run on Linux)
  python3 build.py --check      → just check dependencies
"""
import sys, os, shutil, subprocess, platform, textwrap
from pathlib import Path

OS      = platform.system()
ROOT    = Path(__file__).parent
DIST    = ROOT / 'dist'
BUILD   = ROOT / 'build'
VERSION = '2.0.0'
APP     = 'CyberClean'
AUTHOR  = 'vuphitung'
URL     = f'https://github.com/{AUTHOR}/{APP}'

# Icon paths — drop your logo here after generating it
ICON_ICO = ROOT / 'assets' / 'logo.ico'    # Windows
ICON_PNG = ROOT / 'assets' / 'logo.png'    # Linux

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
    """Return pyinstaller command — handles ~/.local/bin not in PATH (common on Arch)."""
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
    head('Checking dependencies')
    ok_all = True
    for pkg, hint in {
        'psutil': 'sudo pacman -S python-psutil  OR  pip install psutil --break-system-packages',
        'PyQt6':  'sudo pacman -S python-pyqt6   OR  pip install PyQt6  --break-system-packages',
    }.items():
        try:
            __import__(pkg); ok(pkg)
        except ImportError:
            err(f'{pkg} missing — {hint}'); ok_all = False

    if _has_pyinstaller():
        ok(f'PyInstaller  ({_pyinstaller_bin()})')
    else:
        err('PyInstaller missing — python3 -m pip install pyinstaller --break-system-packages')
        ok_all = False
    return ok_all

# ── PyInstaller shared options ────────────────────────────
def _pyinstaller_cmd(onefile: bool, icon: Path | None) -> str:
    sep   = ';' if OS == 'Windows' else ':'
    mode  = '--onefile' if onefile else '--onedir'
    parts = [
        f'{_pyinstaller_bin()} {mode} --noconsole',
        f'--name {APP}',
        f'--add-data "core/*.py{sep}core"',
        f'--add-data "utils/*.py{sep}utils"',
        '--hidden-import psutil',
        '--hidden-import PyQt6',
        '--hidden-import PyQt6.QtWidgets',
        '--hidden-import PyQt6.QtCore',
        '--hidden-import PyQt6.QtGui',
        '--exclude-module tkinter',
        '--exclude-module matplotlib',
        '--exclude-module numpy',
    ]
    if icon and icon.exists():
        parts.append(f'--icon "{icon}"')
        ok(f'Using icon: {icon.name}')
    else:
        warn(f'No icon found at {icon} — building without icon')
        warn('Drop your logo.ico / logo.png into assets/ to add it')
    parts.append('main.py')
    return ' '.join(parts)

# ── Windows build ─────────────────────────────────────────
def build_windows(make_inno: bool = False):
    head('Building Windows .exe')
    if not _has_pyinstaller():
        err('PyInstaller not found — python3 -m pip install pyinstaller --break-system-packages')
        return False

    DIST.mkdir(exist_ok=True)
    cmd = _pyinstaller_cmd(onefile=True, icon=ICON_ICO)
    result = run(cmd)
    if result.returncode != 0:
        err('Build failed — check output above')
        return False

    exe = DIST / f'{APP}.exe'
    if not exe.exists():
        err(f'{exe} not found after build')
        return False

    size_mb = exe.stat().st_size / 1024 / 1024
    ok(f'Built: {exe}  ({size_mb:.1f} MB)')

    if make_inno:
        _generate_inno_script(exe)

    return True


def _generate_inno_script(exe: Path):
    """Generate an Inno Setup .iss script that creates a proper Windows installer."""
    head('Generating Inno Setup script')
    icon_line = f'SetupIconFile={ICON_ICO}' if ICON_ICO.exists() else '; SetupIconFile=assets\\logo.ico'

    iss_content = textwrap.dedent(f"""\
        ; CyberClean v{VERSION} — Inno Setup Script
        ; Build: Open this file in Inno Setup Compiler and press Compile
        ; Download Inno Setup: https://jrsoftware.org/isinfo.php

        [Setup]
        AppName={APP}
        AppVersion={VERSION}
        AppPublisher={AUTHOR}
        AppPublisherURL={URL}
        AppSupportURL={URL}/issues
        AppUpdatesURL={URL}/releases
        DefaultDirName={{autopf}}\\{APP}
        DefaultGroupName={APP}
        AllowNoIcons=yes
        OutputDir=dist
        OutputBaseFilename={APP}_Setup_v{VERSION}
        {icon_line}
        Compression=lzma
        SolidCompression=yes
        WizardStyle=modern
        PrivilegesRequired=admin
        UninstallDisplayName={APP}
        UninstallDisplayIcon={{app}}\\{APP}.exe
        VersionInfoVersion={VERSION}
        VersionInfoDescription=Smart Disk Cleaner

        [Languages]
        Name: "english"; MessagesFile: "compiler:Default.isl"

        [Tasks]
        Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

        [Files]
        Source: "dist\\{APP}.exe"; DestDir: "{{app}}"; Flags: ignoreversion

        [Icons]
        Name: "{{group}}\\{APP}";        DestName: "{APP}"; Filename: "{{app}}\\{APP}.exe"
        Name: "{{group}}\\Uninstall {APP}"; Filename: "{{uninstallexe}}"
        Name: "{{userdesktop}}\\{APP}";   Filename: "{{app}}\\{APP}.exe"; Tasks: desktopicon

        [Run]
        Filename: "{{app}}\\{APP}.exe"; Description: "Launch {APP}"; \\
            Flags: nowait postinstall skipifsilent runascurrentuser

        [UninstallDelete]
        ; Clean up app data on uninstall
        Type: filesandordirs; Name: "{{localappdata}}\\{APP}"
        Type: filesandordirs; Name: "{{userappdata}}\\{APP}"
    """)

    iss_path = ROOT / f'{APP}.iss'
    iss_path.write_text(iss_content, encoding='utf-8')
    ok(f'Inno Setup script: {iss_path}')
    print(f'\n  {C}Next steps:{NC}')
    print(f'  1. Download Inno Setup: https://jrsoftware.org/isinfo.php')
    print(f'  2. Open {APP}.iss in Inno Setup Compiler')
    print(f'  3. Press Compile → dist/{APP}_Setup_v{VERSION}.exe')
    print(f'  4. Upload that .exe to GitHub Releases\n')


# ── Linux AppImage ────────────────────────────────────────
def build_linux_appimage():
    head('Building Linux AppImage')
    if not _has_pyinstaller():
        err('PyInstaller not found — python3 -m pip install pyinstaller --break-system-packages')
        return False

    # PyInstaller onedir — AppImage wraps the directory
    cmd = _pyinstaller_cmd(onefile=False, icon=ICON_PNG)
    result = run(cmd)
    if result.returncode != 0:
        err('PyInstaller step failed')
        return False

    # Build AppDir structure
    appdir = BUILD / 'AppDir'
    if appdir.exists(): shutil.rmtree(appdir)
    appdir.mkdir(parents=True)

    shutil.copytree(DIST / APP, appdir / 'usr/bin' / APP)

    # AppRun
    apprun = appdir / 'AppRun'
    apprun.write_text(
        '#!/bin/bash\n'
        f'exec "$APPDIR/usr/bin/{APP}/{APP}" "$@"\n'
    )
    apprun.chmod(0o755)

    # .desktop entry
    (appdir / f'{APP}.desktop').write_text(
        f'[Desktop Entry]\n'
        f'Name={APP}\n'
        f'Exec={APP}\n'
        f'Icon={APP}\n'
        f'Type=Application\n'
        f'Categories=System;Utility;\n'
        f'Comment=Smart Disk Cleaner v{VERSION}\n'
    )

    # Copy icon into AppDir
    if ICON_PNG.exists():
        shutil.copy(ICON_PNG, appdir / f'{APP}.png')
    else:
        warn(f'No icon at {ICON_PNG} — AppImage will have no icon')

    # Download appimagetool if needed
    tool = Path('/tmp/appimagetool')
    if not tool.exists():
        warn('Downloading appimagetool...')
        run('wget -q -O /tmp/appimagetool '
            '"https://github.com/AppImage/AppImageKit/releases/download/continuous/'
            'appimagetool-x86_64.AppImage"')
        tool.chmod(0o755)

    out = DIST / f'{APP}-{VERSION}-x86_64.AppImage'
    result = run(f'ARCH=x86_64 /tmp/appimagetool {appdir} {out}')
    if result.returncode == 0 and out.exists():
        out.chmod(0o755)
        size_mb = out.stat().st_size / 1024 / 1024
        ok(f'Built: {out}  ({size_mb:.1f} MB)')
        _print_appimage_release_note(out)
        return True

    err('AppImage packaging failed')
    return False


def _print_appimage_release_note(path: Path):
    print(f'\n  {C}Upload to GitHub Releases:{NC}')
    print(f'  gh release create v{VERSION} {path} --title "v{VERSION}" --notes "See CHANGELOG"')
    print(f'  # or drag & drop on github.com/{AUTHOR}/{APP}/releases/new\n')


# ── Linux .deb ────────────────────────────────────────────
def build_linux_deb():
    """
    Build a .deb package (Debian / Ubuntu / Mint).
    Installs as: /opt/CyberClean/  with a desktop entry + uninstall path.
    User removes with: sudo apt remove cyberclean
    """
    head('Building Linux .deb')
    if not _has_pyinstaller():
        err('PyInstaller not found — python3 -m pip install pyinstaller --break-system-packages')
        return False

    # Step 1: PyInstaller onedir
    cmd = _pyinstaller_cmd(onefile=False, icon=ICON_PNG)
    result = run(cmd)
    if result.returncode != 0:
        err('PyInstaller step failed')
        return False

    # Step 2: Build debian package tree
    pkg_name = APP.lower()
    deb_root = BUILD / f'{pkg_name}_{VERSION}'
    if deb_root.exists(): shutil.rmtree(deb_root)

    install_dir = deb_root / f'opt/{APP}'
    install_dir.mkdir(parents=True)
    shutil.copytree(DIST / APP, install_dir / APP)

    # Desktop entry
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
        f'Terminal=false\n'
    )

    # DEBIAN control
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
    )

    # postinst — fix permissions
    postinst = debian_dir / 'postinst'
    postinst.write_text(
        '#!/bin/bash\n'
        f'chmod +x /opt/{APP}/{APP}/{APP}\n'
        'update-desktop-database /usr/share/applications 2>/dev/null || true\n'
    )
    postinst.chmod(0o755)

    # postrm — cleanup on apt remove
    postrm = debian_dir / 'postrm'
    postrm.write_text(
        '#!/bin/bash\n'
        f'rm -rf /opt/{APP}\n'
        'update-desktop-database /usr/share/applications 2>/dev/null || true\n'
    )
    postrm.chmod(0o755)

    # Step 3: Build .deb
    DIST.mkdir(exist_ok=True)
    out = DIST / f'{pkg_name}_{VERSION}_amd64.deb'
    result = run(f'dpkg-deb --build {deb_root} {out}')
    if result.returncode == 0 and out.exists():
        size_mb = out.stat().st_size / 1024 / 1024
        ok(f'Built: {out}  ({size_mb:.1f} MB)')
        print(f'\n  {C}Install:{NC}  sudo apt install ./{out.name}')
        print(f'  {C}Remove:{NC}   sudo apt remove {pkg_name}\n')
        return True

    err('.deb build failed — is dpkg-deb installed?  (sudo apt install dpkg)')
    return False


# ── Linux zip fallback ────────────────────────────────────
def build_linux_zip():
    head('Building Linux source zip (fallback)')
    DIST.mkdir(exist_ok=True)
    out = DIST / f'{APP}-{VERSION}-linux-source.zip'
    run(f'zip -r {out} main.py core/ utils/ requirements.txt install.sh README.md 2>/dev/null')
    if out.exists():
        ok(f'Built: {out}')
        return True
    return False


# ── Main ──────────────────────────────────────────────────
def main():
    print(f'\n{C}  ⚡ {APP} v{VERSION} — Build Tool{NC}\n')
    args = sys.argv[1:]

    if '--check' in args:
        check_deps()
        return

    if not check_deps():
        print(f'\n{R}Fix dependencies first, then re-run.{NC}')
        return

    target     = OS
    make_inno  = '--inno' in args
    make_deb   = '--deb'  in args

    if '--windows' in args or make_inno: target = 'Windows'
    if '--linux'   in args or make_deb:  target = 'Linux'

    success = False

    if target == 'Windows':
        success = build_windows(make_inno=make_inno)

    elif target == 'Linux':
        if make_deb:
            success = build_linux_deb()
        elif shutil.which('appimagetool') or Path('/tmp/appimagetool').exists():
            success = build_linux_appimage()
        else:
            warn('appimagetool not found — trying AppImage download first...')
            success = build_linux_appimage()   # it auto-downloads
            if not success:
                warn('Falling back to source zip')
                success = build_linux_zip()

    else:
        warn(f'Platform "{target}" not recognized — use --windows or --linux')

    status = f'{G}✅ Build complete! → {DIST}{NC}' if success else f'{R}✗ Build failed{NC}'
    print(f'\n  {status}\n')


if __name__ == '__main__':
    main()
