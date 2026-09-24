# -*- mode: python ; coding: utf-8 -*-

# ===============================================
# Enhanced Security Configuration for PyInstaller
# ===============================================

block_cipher = None


a = Analysis(
    ['main.py'],                    # entry point จริง (apply_pyarmor_patch จะ swap เป็น obfuscated)
    pathex=['.', 'dist_pyarmor'],   # ค้นหา modules จาก dist_pyarmor ด้วย
    binaries=[
        # tkinter DLLs (จำเป็นสำหรับ GUI)
        (r'C:\Users\Benz\AppData\Local\Programs\Python\Python311\DLLs\_tkinter.pyd', '.'),
        (r'C:\Users\Benz\AppData\Local\Programs\Python\Python311\DLLs\tcl86t.dll', '.'),
        (r'C:\Users\Benz\AppData\Local\Programs\Python\Python311\DLLs\tk86t.dll', '.'),
    ],
    datas=[
        # PyArmor runtime ถูก inject โดย apply_pyarmor_patch() แล้ว ไม่ต้องใส่ที่นี่
        # tcl/tk data folders (จำเป็นสำหรับ GUI rendering)
        (r'C:\Users\Benz\AppData\Local\Programs\Python\Python311\tcl\tcl8.6', 'tcl/tcl8.6'),
        (r'C:\Users\Benz\AppData\Local\Programs\Python\Python311\tcl\tk8.6', 'tcl/tk8.6'),
        # customtkinter themes/fonts (ขาดแล้ว UI จะ crash)
        (r'C:\Users\Benz\AppData\Local\Programs\Python\Python311\Lib\site-packages\customtkinter', 'customtkinter'),
        # PIL/Pillow (customtkinter ต้องการ) - tried replacing this blanket copy with the
        # official hook-PIL.py + hiddenimports (which should be equivalent and ~16 MB
        # smaller) while chasing the 60 MB target; it instead crashes PyInstaller itself
        # with "re.error: invalid group reference 2" inside depend/bytecode.py's ctypes-DLL
        # scan of main.py - a PyInstaller/Python-3.11 adaptive-bytecode bug, not a bug in
        # this project. Reverted: a slightly bigger working build beats a smaller broken one.
        (r'C:\Users\Benz\AppData\Local\Programs\Python\Python311\Lib\site-packages\PIL', 'PIL'),
    ],
    hiddenimports=[
        # Obfuscated local modules (pathex=dist_pyarmor ทำให้ PyInstaller หาเจอ)
        'config_secure',
        'hwid',
        'protection',
        'botLineRanger',
        'pyarmor_runtime_009939',
        # GUI
        'tkinter',
        'tkinter.filedialog',
        'tkinter.messagebox',
        'customtkinter',
        'PIL',
        'PIL.Image',
        'PIL.ImageTk',
        'PIL.ImageDraw',
        'PIL.ImageFont',
        # Network
        'requests',
        'requests.adapters',
        'requests.auth',
        'requests.exceptions',
        # System / Security
        'ctypes',
        'ctypes.wintypes',
        'atexit',   # botLineRanger.py still imports this (nemu_capture, its old user, is gone - Task 11)
        'psutil',
        'cryptography',
        'cryptography.fernet',
        'cryptography.hazmat.primitives',
        # default_backend is a function inside this package, not a submodule of its own -
        # naming it here (pre-existing, predates Task 12) always logged a build-time
        # "ERROR: Hidden import ... not found"; harmless (the package above already covers
        # the real dependency) but noisy enough to look like a real failure, so it's gone.
        'cryptography.hazmat.backends',
        # Standard library (dynamic import ใน protection.py)
        'platform',
        'subprocess',
        'configparser',
        'uuid',
        'hashlib',
        'hmac',
        'base64',
        'multiprocessing',
        'threading',
        'webbrowser',
        # ..\tools\*.py: the reverse-engineered API layer, obfuscated by build.bat's
        # `pyarmor gen` step into dist_pyarmor\ (flat, alongside the bot/ targets - see that
        # step's own comment) instead of shipping as plain, readable .py beside the exe the
        # way it used to. sys.path.insert(..., "tools") in botLineRanger.py's TOOLSDIR /
        # engine/*.py / engine_main.py / main.py still runs (harmless no-op once frozen: no
        # such directory exists beside the exe any more, and Python's path-based finder
        # just skips a sys.path entry that does not exist) but is no longer what makes these
        # imports resolve - pathex=['.', 'dist_pyarmor'] above is. They are listed here
        # explicitly because nothing PyInstaller's own Analysis can already see resolves
        # them on its own: engine/*.py imports them by bare name (`import rangers_api`,
        # `from device_session import decrypt_lfac`, ...), which Analysis reads from
        # plaintext bot/engine/*.py (pathex '.' comes first) but - before this build's fix -
        # could never find on ANY search path, so it always fell through to the loose-file
        # copy at runtime rather than ever landing in a.pure. Explicit hiddenimports makes
        # that resolution happen regardless of search-path order or timing.
        #
        # Deliberately NOT listed (and not passed to pyarmor gen either): device_snapshot,
        # export_account, extract_battles, gifts, newbie_quest, ratelimit_probe, sevendays,
        # summarize. grep across bot/ and every module below turns up no import of any of
        # them - they are CLI-only tools a human runs by hand, not code this build ships.
        'account_file',
        'device_session',
        'gacha',
        'new_account',
        'pull_roster',
        'rangers_api',
        'ratelimit',
        'relogin',
        'rewards',
        'stage_forge',
        'tutorial',
        # Everything below is a stdlib or third-party import collected straight from the 11
        # modules above's own `import` lines, so the frozen runtime carries it even though
        # no bundled module visibly asks for it (same reasoning as those 11 themselves).
        # Verified by building: without this block, `BotLineRanger.exe --engine` dies with
        # "ModuleNotFoundError: No module named 'concurrent'" the moment engine.flows
        # imports relogin, which is always (every mode - flows.py imports
        # rangers_api/relogin/rewards/device_session at module level, not lazily).
        'concurrent',
        'concurrent.futures',
        'argparse',
        'gzip',
        'http.client',
        'json',
        'random',
        'urllib.error',
        'urllib.request',
        'urllib.parse',
        'glob',
        'io',
        're',
        'csv',
        'difflib',
        'secrets',
        'tempfile',
        'html',
        'shutil',
        'os',
        'sys',
        'time',
        # pycryptodome: tools/stage_forge.py does `from Crypto.Cipher import AES` /
        # `from Crypto.Util.Padding import pad`, reached from engine/flows.py's Stage and
        # Level3 paths. (An earlier version of this comment blamed tools/new_account.py -
        # wrong: that file's own docstring says stdlib only, and it has no Crypto import.
        # The hiddenimports below were right either way, the reason was not.)
        # Found by audit, not by this task's --engine smoke test: the import runs lazily
        # inside the mode's function, and an empty input/ never reaches it. Confirmed
        # missing by `import Crypto` under the Python 3.11 build environment directly
        # (ModuleNotFoundError), though it is installed under the dev Python on PATH.
        'Crypto',
        'Crypto.Cipher',
        'Crypto.Cipher.AES',
        'Crypto.Util',
        'Crypto.Util.Padding',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'unittest',
        'pydoc',
        # ไม่มีโหมดไหนใช้แล้วตั้งแต่ลบ ADB - ใส่ไว้กันการถูกลากเข้ามาทางอ้อม
        'cv2', 'numpy', 'pytesseract', 'uiautomator2', 'adbutils', 'ppadb',
    ],
    noarchive=False,
    # numpy (the original reason this was pinned to 0) is gone from the build entirely now -
    # kept at 0 anyway because pyarmor's obfuscated runtime leans on assert/docstring tricks
    # that -O/-OO can strip, and there is no upside left to chase since numpy is not in this
    # bundle to begin with.
    optimize=0,
)

# Pyarmor patch start:

def apply_pyarmor_patch():
    import os

    srcpath = [os.path.abspath('.')]
    obfpath = os.path.abspath('dist_pyarmor')
    pkgname = 'pyarmor_runtime_009939'
    pkgpath = os.path.join(obfpath, pkgname)

    import glob
    extfiles = glob.glob(os.path.join(pkgpath, 'pyarmor_runtime*.pyd')) + \
               glob.glob(os.path.join(pkgpath, 'pyarmor_runtime*.so'))
    if not extfiles:
        raise RuntimeError('no found extension pyarmor_runtime in ' + pkgpath)
    extname = os.path.join(pkgname, os.path.basename(extfiles[0]))

    if hasattr(a.pure, '_code_cache'):
        code_cache = a.pure._code_cache
    else:
        from PyInstaller.config import CONF
        code_cache = CONF['code_cache'].get(id(a.pure))

    srclist = [os.path.normcase(x) for x in srcpath]

    def match_obfuscated_script(orgpath):
        for x in srclist:
            if os.path.normcase(orgpath).startswith(x):
                return os.path.join(obfpath, orgpath[len(x)+1:])

    count = 0
    for i in range(len(a.scripts)):
        x = match_obfuscated_script(a.scripts[i][1])
        if x and os.path.exists(x):
            a.scripts[i] = a.scripts[i][0], x, a.scripts[i][2]
            count += 1
    if count == 0:
        raise RuntimeError('No obfuscated script found in ' + obfpath)

    for i in range(len(a.pure)):
        x = match_obfuscated_script(a.pure[i][1])
        if x and os.path.exists(x):
            code_cache.pop(a.pure[i][0], None)
            a.pure[i] = a.pure[i][0], x, a.pure[i][2]

    a.pure.append((pkgname, os.path.join(pkgpath, '__init__.py'), 'PYMODULE'))
    a.binaries.append((extname, os.path.join(obfpath, extname), 'EXTENSION'))

apply_pyarmor_patch()

# Pyarmor patch end.

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher
)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,      # onedir: binaries/datas ไปอยู่ใน COLLECT ไม่ใช่ในตัว exe
    name='BotLineRanger',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                  # onefile+UPX ต้องแตกตัวเองลง %TEMP% ทุกครั้งที่โปรเซสเริ่ม
    console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['src\\image\\home\\BotLineRanger_128.ico'],
)

# onedir: ไฟล์ทั้งหมดวางข้าง exe ไม่ต้องแตกบันเดิล 87 MB ลง %TEMP% ตอนสตาร์ท
# และโปรแกรมป้องกันไวรัสไม่หวาดระแวงเท่า onefile ที่ถูกบีบด้วย UPX
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='BotLineRanger',
)
