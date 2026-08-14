# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src/finsight/desktop_app.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets'), ('default_categories.json', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FinSight',
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
    icon=['assets/logo.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FinSight',
)
app = BUNDLE(
    coll,
    name='FinSight.app',
    icon='assets/logo.icns',
    bundle_identifier=None,
)
