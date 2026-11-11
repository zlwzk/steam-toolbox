# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：one-folder，前端 dist 作为只读资源带入。

构建：pyinstaller SteamToolbox.spec
产物：packaged/SteamToolbox/SteamToolbox.exe
"""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = [("frontend/dist", "frontend/dist")]
hiddenimports = (
    collect_submodules("backend")
    + collect_submodules("uvicorn")
    + collect_submodules("playwright")
)
datas += collect_data_files("playwright")

a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "numpy", "pandas"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SteamToolbox",
    debug=False,
    bootloader_ignore_signals=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="SteamToolbox",
)
