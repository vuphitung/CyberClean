# -*- mode: python ; coding: utf-8 -*-
# CyberClean v2.2.3 -- PyInstaller spec
# Build: pyinstaller CyberClean.spec  (or: python build.py --linux / --windows)

import sys
from pathlib import Path

block_cipher = None

# Icon: use relative path so spec works on any machine
_icon = str(Path('assets/logo.ico')) if sys.platform == 'win32' else str(Path('assets/logo.png'))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('version.py', '.'),
        ('core/*.py', 'core'),
        ('utils/*.py', 'utils'),
        ('assets', 'assets'),
    ],
    hiddenimports=[
        'psutil',
        'PyQt6',
        'PyQt6.QtWidgets',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        # updater imports -- must be explicit so PyInstaller bundles them
        'utils.updater',
        'json',
        'urllib.request',
        'urllib.error',
        'tarfile',
        'tempfile',
        # Optional -- only on Windows
        'clr',
        'clr._extra',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CyberClean',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # console=False for release; set True temporarily to see crash errors
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='CyberClean',
)
