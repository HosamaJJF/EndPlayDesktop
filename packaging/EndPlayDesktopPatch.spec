# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import json
from PyInstaller.utils.hooks import copy_metadata, collect_dynamic_libs

root = Path(SPECPATH).parent
assets = root / ".cache/app-assets"
metadata = json.loads((assets / "distribution.json").read_text())
datas = [
    (str(assets / "distribution.json"), "."),
    (str(assets / "payloads.zip"), "."),
    (str(assets / "EndPlayDesktop-source.zip"), "."),
    (str(assets / "runtime_source"), "runtime_source"),
    (str(root / "LICENSE"), "licenses"),
    (str(root / "THIRD_PARTY_NOTICES.md"), "licenses"),
]
for package in ("numpy", "Pillow", "json5", "maafw", "pyobjc-core", "pyobjc-framework-Cocoa", "pyinstaller"):
    datas += copy_metadata(package)

analysis = Analysis(
    [str(root / "packaging/launcher.py")],
    pathex=[str(root)],
    binaries=collect_dynamic_libs("maa"),
    datas=datas,
    hiddenimports=["AppKit", "Foundation", "PyObjCTools.AppHelper"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "matplotlib", "IPython"],
    noarchive=False,
)
archive = PYZ(analysis.pure)
gui = EXE(archive, analysis.scripts, [], exclude_binaries=True,
          name="EndPlayDesktopPatch", console=False, debug=False,
          strip=False, upx=False, target_arch="arm64")
runtime = EXE(archive, analysis.scripts, [], exclude_binaries=True,
              name="EndPlayDesktopRuntime", console=True, debug=False,
              strip=False, upx=False, target_arch="arm64")
collection = COLLECT(gui, runtime, analysis.binaries, analysis.datas,
                     name="EndPlayDesktopPatch", strip=False, upx=False)
application = BUNDLE(collection, name="EndPlayDesktopPatch.app",
                     bundle_identifier="io.endplaydesktop.patcher",
                     version=metadata["version"], info_plist={
                         "CFBundleDisplayName": "EndPlayDesktop 补丁工具",
                         "CFBundleShortVersionString": metadata["version"],
                         "CFBundleVersion": metadata["version"],
                         "NSHighResolutionCapable": True,
                         "LSMinimumSystemVersion": "14.0",
                         "NSHumanReadableCopyright": "EndPlayDesktop contributors. AGPL-3.0.",
                     })
