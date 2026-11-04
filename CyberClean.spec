# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('VERSION', '.'), ('rules/*.toml', 'rules'), ('packaging/cyber-clean-helper', 'packaging'), ('assets', 'assets'), ('vendor/lhm', 'vendor/lhm')],
    hiddenimports=['pythonnet', 'utils.windows_temperature_host', 'psutil', 'PyQt6', 'PyQt6.QtWidgets', 'PyQt6.QtCore', 'PyQt6.QtGui', 'utils.updater', 'json', 'urllib.request', 'urllib.error', 'tarfile', 'tempfile', 'tomllib', 'ui_widgets', 'ui_pages', 'core.game_boost_widget', 'clr', 'clr._extra', 'send2trash', 'cryptography.hazmat.primitives.asymmetric.ed25519'],
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
    icon=['C:\\Users\\WIN10\\Downloads\\CyberClean-Windows-Review\\CyberClean\\assets\\logo.ico'],
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
