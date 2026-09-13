# -*- mode: python ; coding: utf-8 -*-

# ===============================================
# Enhanced Security Configuration for Updater
# ===============================================

block_cipher = None

a = Analysis(
    ['updater.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'unittest',
        'pydoc',
    ],
    noarchive=False,
    optimize=2,  # เพิ่มระดับ optimization
)

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='updater',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,  # ปิดเนื่องจาก strip ไม่มีใน Windows (ใช้ UPX แทน)
    upx=True,     # Compress
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=True,  # ปิด traceback
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
