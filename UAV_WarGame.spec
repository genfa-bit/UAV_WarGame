# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('data', 'data'), ('ui/qml', 'ui/qml'), ('ui/assets', 'ui/assets')],
    hiddenimports=['PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuickControls2', 'core', 'ui'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest'],
    noarchive=False,
    optimize=0,
)
# Qt uses Windows' ICU C ABI. Other tools may put an ICU build with versioned
# symbols on PATH; collecting it makes QtCore fail before the UI starts.
# Windows 10/11 also provide UCRT and API-set DLLs; use the system providers.
a.binaries = [entry for entry in a.binaries
              if not (Path(entry[0]).name.lower() in {'ucrtbase.dll', 'icuuc.dll'}
                      or Path(entry[0]).name.lower().startswith('api-ms-win-')
                      or (Path(entry[0]).name.lower().startswith('icudt')
                          and Path(entry[0]).suffix.lower() == '.dll'))]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='UAV_WarGame',
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
)
