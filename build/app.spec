# -*- mode: python ; coding: utf-8 -*-
import os
import platform
import sys

plat = {"Darwin": "mac", "Linux": "linux", "Windows": "windows"}[platform.system()]
suffix = ".exe" if plat == "windows" else ""
root = os.getcwd()
ffmpeg = os.path.join(root, "build", "bin", plat, f"ffmpeg{suffix}")
if not os.path.exists(ffmpeg):
    sys.exit(f"ffmpeg binary not found: {ffmpeg} — run the platform build script first")

a = Analysis(
    [os.path.join(root, "app", "main.py")],
    pathex=[root],
    binaries=[(ffmpeg, ".")],
    datas=[(os.path.join(root, "youtube-upload"), "youtube-upload")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="concat-e3v",
    debug=False,
    strip=False,
    upx=False,
    console=False,
)
if plat == "mac":
    app = BUNDLE(
        exe,
        name="concat-e3v.app",
        bundle_identifier="com.concat-e3v.app",
        info_plist={
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
        },
    )