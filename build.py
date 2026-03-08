#!/usr/bin/env python3
"""
CyberClean v2.0 — Build Script
Packages the app for distribution.

Usage:
  python3 build.py           → auto-detect platform
  python3 build.py --windows → force Windows .exe
  python3 build.py --linux   → force Linux AppImage
  python3 build.py --check   → just check dependencies
"""
import sys, os, shutil, subprocess, platform
from pathlib import Path

OS       = platform.system()
ROOT     = Path(__file__).parent
DIST     = ROOT / 'dist'
BUILD    = ROOT / 'build'
VERSION  = '2.0.0'

# ── Colors ────────────────────────────────────────────────
G = '\033[0;32m'; Y = '\033[1;33m'; R = '\033[0;31m'
C = '\033[0;36m'; B = '\033[0;34m'; NC = '\033[0m'

def ok(msg):  print(f'  {G}✓{NC}  {msg}')
def warn(msg):print(f'  {Y}⚠{NC}  {msg}')
def err(msg): print(f'  {R}✗{NC}  {msg}')
def head(msg):print(f'\n{B}━━━ {msg} ━━━{NC}')

def run(cmd, **kw):
    return subprocess.run(cmd, shell=True, **kw)

# ── Dependency check ──────────────────────────────────────
def check_deps():
    head('Checking dependencies')
    all_ok = True
    deps = {
        'psutil':      'python-psutil / pip install psutil',
        'PyQt6':       'python-pyqt6  / pip install PyQt6',
        'PyInstaller': 'pip install pyinstaller',
    }
    for pkg, hint in deps.items():
        try:
            __import__(pkg)
            ok(pkg)
        except ImportError:
            err(f'{pkg} missing — install: {hint}')
            all_ok = False
    return all_ok

# ── Windows build ─────────────────────────────────────────
def build_windows():
    head('Building Windows .exe')
    if not shutil.which('pyinstaller'):
        err('pyinstaller not found. Run: pip install pyinstaller')
        return False

    DIST.mkdir(exist_ok=True)
    cmd = (
        f'pyinstaller --noconsole --onefile '
        f'--name CyberClean '
        f'--add-data "core/*.py;core" '
        f'--add-data "utils/*.py;utils" '
        f'--hidden-import psutil '
        f'--hidden-import PyQt6 '
        f'main.py'
    )
    result = run(cmd)
    if result.returncode == 0:
        exe = DIST / 'CyberClean.exe'
        if exe.exists():
            size_mb = exe.stat().st_size / 1024 / 1024
            ok(f'Built: {exe} ({size_mb:.1f} MB)')
            return True
    err('Build failed — check output above')
    return False

# ── Linux AppImage ────────────────────────────────────────
def build_linux_appimage():
    head('Building Linux AppImage')

    # Step 1: PyInstaller onedir (not onefile — AppImage wraps it)
    if not shutil.which('pyinstaller'):
        err('pyinstaller not found. Run: pip install pyinstaller')
        return False

    cmd = (
        f'pyinstaller --noconsole --onedir '
        f'--name CyberClean '
        f'--add-data "core/*.py:core" '
        f'--add-data "utils/*.py:utils" '
        f'--hidden-import psutil '
        f'--hidden-import PyQt6 '
        f'main.py'
    )
    result = run(cmd)
    if result.returncode != 0:
        err('PyInstaller step failed')
        return False

    # Step 2: Build AppDir structure
    appdir = BUILD / 'AppDir'
    if appdir.exists(): shutil.rmtree(appdir)
    appdir.mkdir(parents=True)

    # Copy dist into AppDir
    shutil.copytree(DIST / 'CyberClean', appdir / 'usr/bin/CyberClean')

    # AppRun
    apprun = appdir / 'AppRun'
    apprun.write_text('#!/bin/bash\nexec "$APPDIR/usr/bin/CyberClean/CyberClean" "$@"\n')
    apprun.chmod(0o755)

    # Desktop entry
    desktop = appdir / 'CyberClean.desktop'
    desktop.write_text(
        '[Desktop Entry]\nName=CyberClean\nExec=CyberClean\n'
        'Icon=CyberClean\nType=Application\nCategories=System;Utility;\n'
    )

    # Step 3: Download appimagetool if needed
    tool = Path('/tmp/appimagetool')
    if not tool.exists():
        warn('Downloading appimagetool...')
        run('wget -q -O /tmp/appimagetool '
            '"https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"')
        tool.chmod(0o755)

    # Step 4: Package
    out = DIST / f'CyberClean-{VERSION}-x86_64.AppImage'
    result = run(f'ARCH=x86_64 /tmp/appimagetool {appdir} {out}')
    if result.returncode == 0 and out.exists():
        size_mb = out.stat().st_size / 1024 / 1024
        ok(f'Built: {out} ({size_mb:.1f} MB)')
        return True
    err('AppImage packaging failed')
    return False

# ── Linux simple zip ──────────────────────────────────────
def build_linux_zip():
    """Fallback: zip the source for easy distribution."""
    head('Building Linux distributable zip')
    DIST.mkdir(exist_ok=True)
    out = DIST / f'CyberClean-{VERSION}-linux.zip'
    include = ['main.py','core/','utils/','requirements.txt','install.sh','README.md']
    run(f'zip -r {out} {" ".join(include)} 2>/dev/null || '
        f'python3 -c "import zipfile,os; '
        f'z=zipfile.ZipFile(\'{out}\',\'w\'); '
        f'[z.write(f) for f in [\'{chr(39).join(include)}\']]; z.close()"')
    if out.exists():
        ok(f'Built: {out}')
        return True
    return False

# ── Main ──────────────────────────────────────────────────
def main():
    print(f'\n{C}  ⚡ CyberClean v{VERSION} — Build Tool{NC}\n')

    args = sys.argv[1:]

    if '--check' in args:
        check_deps()
        return

    if not check_deps():
        print(f'\n{R}Fix dependencies first, then re-run build.py{NC}')
        return

    target = OS
    if '--windows' in args: target = 'Windows'
    if '--linux'   in args: target = 'Linux'

    if target == 'Windows':
        success = build_windows()
    elif target == 'Linux':
        if shutil.which('appimagetool') or Path('/tmp/appimagetool').exists():
            success = build_linux_appimage()
        else:
            warn('appimagetool not found — building zip instead')
            warn('For AppImage: re-run after appimagetool is in PATH')
            success = build_linux_zip()
    else:
        warn(f'Platform "{target}" not supported for packaging yet')
        success = False

    if success:
        print(f'\n{G}  ✅ Build complete! Output in: {DIST}{NC}\n')
    else:
        print(f'\n{R}  ✗ Build failed{NC}\n')

if __name__ == '__main__':
    main()
