# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

_icon_file = 'assets/logo.ico' if sys.platform == 'win32' else 'assets/logo.png'
_icon_arg = [_icon_file] if Path(_icon_file).exists() else []

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('version.py', '.'),
        ('VERSION', '.'),
        ('ui_widgets.py', '.'),
        ('ui_pages.py', '.'),
        ('core/*.py', 'core'),
        ('utils/*.py', 'utils'),
        ('rules/*.toml', 'rules'),
        ('packaging/cyber-clean-helper', 'packaging'),
        ('assets', 'assets'),
        *( [('LibreHardwareMonitorLib.dll', '.')] if Path('LibreHardwareMonitorLib.dll').exists() else [] ),
    ],
    hiddenimports=[
        'psutil',
        'PyQt6',
        'PyQt6.QtWidgets',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'utils.updater',
        'json',
        'urllib.request',
        'urllib.error',
        'tarfile',
        'tempfile',
        'tomllib',
        'ui_widgets',
        'ui_pages',
        'core.game_boost_widget',
        'send2trash',
        'cryptography.hazmat.primitives.asymmetric.ed25519',
        'clr',
        'clr._extra',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'gi'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

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
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon_arg,
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
