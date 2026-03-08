# -*- mode: python ; coding: utf-8 -*-
# CyberClean v2.0 — PyInstaller spec
# Build: pyinstaller CyberClean.spec
# Output: dist/CyberClean.exe (Windows) or dist/CyberClean (Linux)

import sys
from pathlib import Path

block_cipher = None
IS_WIN = sys.platform == 'win32'

a = Analysis(
    ['main.py'],
    pathex=[str(Path('.').resolve())],
    binaries=[],
    datas=[
        ('core/*.py',  'core'),
        ('utils/*.py', 'utils'),
    ],
    hiddenimports=[
        'psutil',
        'PyQt6.QtWidgets',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'core.os_detect',
        'core.base_cleaner',
        'core.linux_cleaner',
        'core.windows_cleaner',
        'core.optimizer',
        'utils.sysinfo',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'scipy'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='CyberClean',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # No console window on Windows
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='assets/icon.ico',   # Uncomment when icon is added
)
