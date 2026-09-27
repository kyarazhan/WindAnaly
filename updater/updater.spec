# -*- mode: python ; coding: utf-8 -*-
# updater.exe 独立打包脚本（--onefile，仅 stdlib）
# 用法: pyinstaller updater.spec

a = Analysis(
    ['updater_main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='updater',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon='updater_icon.ico',
)
