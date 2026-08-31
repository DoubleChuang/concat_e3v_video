# -*- mode: python ; coding: utf-8 -*-
import os
import platform
import sys

from PyInstaller.utils.hooks import collect_all

plat = {"Darwin": "mac", "Linux": "linux", "Windows": "windows"}[platform.system()]
suffix = ".exe" if plat == "windows" else ""
root = os.getcwd()
ffmpeg = os.path.join(root, "build", "bin", plat, f"ffmpeg{suffix}")
if not os.path.exists(ffmpeg):
    sys.exit(f"ffmpeg binary not found: {ffmpeg} — run the platform build script first")

# Vendored youtube-upload is bundled as data (loaded via sys.path at runtime),
# so PyInstaller cannot see its imports. Collect the google stack explicitly.
extra_datas, extra_binaries, extra_hiddenimports = [], [], []
for pkg in (
    "googleapiclient",
    "apiclient",
    "oauth2client",
    "httplib2",
    "google_auth_httplib2",
    "google.auth",
):
    d, b, h = collect_all(pkg)
    extra_datas += d
    extra_binaries += b
    extra_hiddenimports += h

# stdlib modules imported only by the vendored youtube-upload (optparse,
# collections, locale, time) are invisible to analysis; pull them in.
extra_hiddenimports += ["optparse", "collections", "locale", "time"]

a = Analysis(
    [os.path.join(root, "app", "main.py")],
    pathex=[root],
    binaries=[(ffmpeg, ".")] + extra_binaries,
    datas=[(os.path.join(root, "youtube-upload"), "youtube-upload")] + extra_datas,
    hiddenimports=extra_hiddenimports,
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