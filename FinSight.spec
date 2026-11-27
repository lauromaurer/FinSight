# -*- mode: python ; coding: utf-8 -*-
# The one build definition for Windows and macOS. Build with:
#     python -m PyInstaller --noconfirm --clean FinSight.spec
# Windows -> dist/FinSight/FinSight.exe (ship the whole folder)
# macOS   -> dist/FinSight.app
# The only platform branches are the icon format and the macOS app bundle.
import sys

IS_MAC = sys.platform == "darwin"
ICON = "assets/logo.icns" if IS_MAC else "assets/logo.ico"

a = Analysis(
    ["src/finsight/desktop_app.py"],
    pathex=["src"],
    binaries=[],
    datas=[("assets", "assets"), ("default_categories.json", ".")],
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
    name="FinSight",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[ICON],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="FinSight",
)

if IS_MAC:
    app = BUNDLE(
        coll,
        name="FinSight.app",
        icon=ICON,
        bundle_identifier=None,
    )
