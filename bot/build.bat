@echo off
setlocal ENABLEDELAYEDEXPANSION

REM ===============================================================================
REM Enhanced Security Build Script for BotLineRanger
REM - High security compilation with obfuscation
REM - URL and sensitive data encryption
REM - Strip debug symbols and optimize
REM ===============================================================================

cd /d %~dp0
title Building BotLineRanger [SECURE MODE]

set ENTRY=main.py
set ICON=src\image\home\BotLineRanger_128.ico
set NAME=BotLineRanger

echo.
echo ===============================================================================
echo  BotLineRanger - Secure Build Process
echo ===============================================================================
echo.

REM ลบ build / dist / cache เก่า
echo [1/8] Cleaning old builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist __pycache__ rmdir /s /q __pycache__
timeout /t 1 /nobreak >nul

REM ตรวจสอบว่ามี config_secure.py หรือไม่
echo [2/8] Checking security configuration...
if not exist config_secure.py (
    echo ERROR: config_secure.py not found!
    echo Please ensure config_secure.py exists before building.
    pause
    exit /b 1
)

REM ====================================
REM Pre-build: ดึง version และเช็คกับ server
REM ====================================
for /f "tokens=*" %%v in ('python get_version.py main.py') do set VERSION=%%v
echo    - Version: %VERSION%

echo [2.5/8] Checking version on server...
python server_version.py check %VERSION%
set CHECK_RESULT=!errorlevel!
if !CHECK_RESULT! equ 0 (
    echo.
    echo    WARNING: Version %VERSION% already exists on server!
    set /p CONTINUE_BUILD="    Continue build anyway? (Y/N): "
    if /i "!CONTINUE_BUILD!" neq "Y" (
        echo Build cancelled by user.
        pause
        exit /b 0
    )
) else if !CHECK_RESULT! equ 2 (
    echo.
    echo    WARNING: Could not reach server to check version.
    set /p CONTINUE_BUILD="    Continue build without check? (Y/N): "
    if /i "!CONTINUE_BUILD!" neq "Y" (
        echo Build cancelled.
        pause
        exit /b 1
    )
)

REM The "scan for unused modules" step that used to sit here is gone, along with
REM find_unused_modules.py, exclude_modules.txt and safe_modules.txt.
REM
REM It never worked. The script collected every module name imported ANYWHERE under bot/,
REM subtracted the stdlib and a hand-written whitelist, and wrote what was left out as
REM "modules to exclude" - so anything genuinely used but not on the whitelist was listed
REM for deletion. Its last run put engine, engine_main, new_account, gacha, cryptography
REM and protection in there: the engine itself, the API layer, and the licence check.
REM
REM Nothing was ever harmed because the loop below it read the file into EXCLUDE_ARGS and
REM then never passed it to pyinstaller. That made it a loaded gun rather than a wound -
REM the next person to notice an unused variable and "fix" it would have cut the engine
REM out of its own build.
REM
REM Real exclusions live in BotLineRanger.spec's own excludes=[] list, written by hand and
REM reviewed: cv2, numpy, pytesseract, uiautomator2, adbutils, ppadb.

REM ===============================
REM PyArmor Obfuscation
REM ===============================
echo [3/8] Obfuscating source code with PyArmor...

REM ลบ output เก่าของ PyArmor
if exist dist_pyarmor rmdir /s /q dist_pyarmor

REM engine (package): tested by hand before writing this line - pyarmor gen DOES accept a
REM package directory alongside flat scripts (verified with pyarmor 9.2.5), so engine/*.py
REM gets obfuscated too instead of being left as plain source next to obfuscated callers.
REM
REM ..\tools\*.py (12 files): the reverse-engineered API layer - rangers_api, client_version, relogin,
REM rewards, device_session, account_file, ratelimit, gacha, pull_roster, stage_forge,
REM new_account, tutorial. Used to ship unobfuscated (xcopy'd beside the exe below - now
REM removed) because they live outside bot/ and PyInstaller could never resolve the bare
REM `import rangers_api` etc. it found in engine/*.py against them. Tested by hand: pyarmor
REM gen writes every input flat into --output regardless of its source directory (e.g.
REM `pyarmor gen --output X hwid.py ..\tools\account_file.py` produced X\account_file.py,
REM not X\tools\account_file.py), so these land as dist_pyarmor\rangers_api.py etc, exactly
REM where BotLineRanger.spec's pathex=['.', 'dist_pyarmor'] and hiddenimports expect a flat
REM top-level module - see that file's own comment on the hiddenimports entries.
REM
REM Deliberately NOT here: device_snapshot, export_account, extract_battles, gifts,
REM newbie_quest, ratelimit_probe, sevendays, summarize. grep confirms nothing in bot/, and
REM nothing in the 12 modules above, imports any of them - they are CLI-only and must not
REM ship at all, obfuscated or not (extract_battles also imports mitmproxy, not installed
REM in this build environment, so including it would break this very step).
pyarmor gen --output dist_pyarmor ^
    main.py botLineRanger.py engine_main.py config_secure.py hwid.py protection.py engine ^
    ..\tools\account_file.py ..\tools\client_version.py ..\tools\device_session.py ..\tools\gacha.py ^
    ..\tools\new_account.py ..\tools\pull_roster.py ..\tools\rangers_api.py ^
    ..\tools\ratelimit.py ..\tools\relogin.py ..\tools\rewards.py ..\tools\stage_forge.py ^
    ..\tools\tutorial.py

if %errorlevel% neq 0 (
    echo ERROR: PyArmor obfuscation failed!
    pause
    exit /b 1
)
echo    - PyArmor obfuscation complete
echo    - Obfuscated files in dist_pyarmor\

echo [4/8] Building main executable with enhanced security...
echo    - Source: PyArmor obfuscated files (dist_pyarmor\)
echo    - Optimization level: 0 (pyarmor runtime compatibility)
echo    - Symbol stripping: DISABLED (Windows compatibility)
echo    - UPX compression: DISABLED (onedir - see BotLineRanger.spec)
echo    - Traceback: DISABLED
echo    - Config encryption: ENABLED
echo.

REM ===============================
REM Build main .exe with spec file
REM (PyInstaller reads from dist_pyarmor\ via spec)
REM ===============================
pyinstaller ^
 --clean ^
 --noconfirm ^
 BotLineRanger.spec

if %errorlevel% neq 0 (
    echo ERROR: Main build failed!
    pause
    exit /b 1
)

REM ===============================
REM Build updater with spec file
REM ===============================
echo [5/8] Building updater executable...
pyinstaller ^
 --clean ^
 --noconfirm ^
 updater.spec

if %errorlevel% neq 0 (
    echo ERROR: Updater build failed!
    pause
    exit /b 1
)

echo [6/8] Organizing build output...

REM onedir: PyInstaller วาง dist\BotLineRanger\ ให้ครบแล้ว ไม่ต้องย้าย exe เอง
if exist "dist\updater.exe" (
    echo    - Moving updater.exe
    move /Y "dist\updater.exe" "dist\BotLineRanger\updater.exe" >nul
)

REM สร้าง sub-folders
echo    - Creating directory structure
mkdir "dist\BotLineRanger\input" 2>nul
mkdir "dist\BotLineRanger\output" 2>nul
mkdir "dist\BotLineRanger\execute" 2>nul
mkdir "dist\BotLineRanger\backup" 2>nul
mkdir "dist\BotLineRanger\login failed" 2>nul

REM copy src + README (skip Tesseract-OCR/adb/image/log/split-ID - see exclude_dist.txt;
REM they stay in the repo, they just do not belong in a shipped build)
xcopy "src" "dist\BotLineRanger\src" /E /H /C /I /Y /EXCLUDE:exclude_dist.txt >nul
if exist README.md copy /Y README.md dist\BotLineRanger >nul

REM exclude_dist.txt drops all of src\image\ (600+ old vision-template PNGs from the
REM deleted OCR stack, ~8.5 MB) - but main.py:317 still does self.iconbitmap() on
REM src\image\home\BotLineRanger_128.ico at GUI startup (try/except-guarded, so only the
REM title-bar icon is at stake, not a crash). Copy just that 871 KB folder back so the
REM window keeps its icon instead of silently falling back to the default Tk one.
if exist "src\image\home" xcopy "src\image\home" "dist\BotLineRanger\src\image\home\" /E /H /C /I /Y >nul

REM tools/ is no longer copied here - the API layer (rangers_api/relogin/rewards/
REM device_session/account_file/ratelimit/gacha/pull_roster/stage_forge/new_account/
REM tutorial) is now obfuscated by the pyarmor gen step above and bundled into the exe via
REM BotLineRanger.spec's hiddenimports, instead of shipping as plain, readable .py beside
REM it. Do not resurrect this xcopy - that is exactly the source leak this build hardens.

REM clean logs and temp files (src\log is excluded above already - this is now only a
REM backstop in case something writes into dist's own src\log before this line runs)
if exist "dist\BotLineRanger\src\log" del /Q "dist\BotLineRanger\src\log\*" 2>nul

REM ====================================
REM Security: Reset sensitive config
REM ====================================
echo [7/8] Applying security configurations...
set "CONFIG_FILE=dist\BotLineRanger\src\config.ini"

if exist "%CONFIG_FILE%" (
    echo    - Resetting email in config.ini
    python reset_config.py "%CONFIG_FILE%"
)

REM อัปเดตเวอร์ชันใน latest_version.json จาก main.py
echo    - Syncing version from main.py to latest_version.json
python update_version.py main.py default_config\latest_version.json

REM ลบไฟล์ที่ไม่จำเป็นออกจาก dist เพื่อความปลอดภัย
echo    - Removing unnecessary files...
del /Q "dist\BotLineRanger\config_secure.py" 2>nul
del /Q "dist\BotLineRanger\protection.py" 2>nul
del /Q "dist\BotLineRanger\*.spec" 2>nul

REM ====================================
REM Step 8: Create ZIP archives
REM ====================================
echo [8/8] Creating ZIP archives...

REM VERSION is already set at the pre-build step
echo    - Version: %VERSION%

REM ลบ zip เก่า (ถ้ามี)
if exist "dist\BotLineRanger.zip" del /Q "dist\BotLineRanger.zip"
if exist "dist\BotLineRanger_%VERSION%.zip" del /Q "dist\BotLineRanger_%VERSION%.zip"

REM สร้าง zip ใหม่ - bsdtar (System32\tar.exe, มากับ Windows 10 ขึ้นไป) ไม่ใช่ Compress-Archive
REM
REM สองเหตุผล วัดมาแล้วบนเครื่องนี้กับ dist ชุดจริง (2,472 ไฟล์ 84 MB):
REM   bsdtar            1.97 วินาที  ได้ zip 44 MB
REM   Compress-Archive  รันไม่จบ - powershell.exe แค่เปิดขึ้นมาแล้วออกก็ใช้เวลาเกิน 2 นาที
REM                     ในวันที่เครื่องมีโปรเซส powershell ค้างอยู่ 19 ตัว
REM Compress-Archive จ่ายต้นทุนต่อ "ไฟล์" สูง ไม่ใช่ต่อไบต์ และ onedir ทำให้ไฟล์เพิ่มจาก
REM exe ก้อนเดียวเป็น 2,367 ไฟล์ใน _internal\ ส่วน bsdtar เป็น native ไม่ต้องบูต .NET เลย
REM
REM -a เลือกรูปแบบจากนามสกุล .zip (libarchive) ผลลัพธ์เป็น zip จริง ขึ้นต้นด้วย PK
REM ต้องใช้ path เต็มของ System32 เพราะ Git for Windows ก็มี tar.exe ของตัวเอง (GNU tar)
REM ซึ่งสร้าง zip ไม่ได้ - มันจะเขียน tar ที่ตั้งชื่อว่า .zip ออกมาแทนโดยไม่เตือน
echo    - Creating BotLineRanger.zip
"%SystemRoot%\System32\tar.exe" -a -c -f "dist\BotLineRanger.zip" -C "dist\BotLineRanger" .
if %errorlevel% neq 0 (
    echo ERROR: zip creation failed!
    pause
    exit /b 1
)

REM ไฟล์ที่สองมีเนื้อหาเหมือนตัวแรกทุกไบต์ - copy เอา ไม่ต้องบีบซ้ำ
echo    - Creating BotLineRanger_%VERSION%.zip
copy /Y "dist\BotLineRanger.zip" "dist\BotLineRanger_%VERSION%.zip" >nul

REM คัดลอกไฟล์ zip ไปยังโฟลเดอร์ Version
echo    - Copying BotLineRanger_%VERSION%.zip to Version folder
if not exist "Version" mkdir "Version"
copy "dist\BotLineRanger_%VERSION%.zip" "Version\" /Y

REM ====================================
REM Step 8.5: Compute EXE Checksum
REM ====================================
echo.
echo [8.5] Computing EXE SHA-256 checksum for server registration...
echo -------------------------------------------------------------------------------
certutil -hashfile "dist\BotLineRanger\BotLineRanger.exe" SHA256
echo -------------------------------------------------------------------------------

REM ดึง hash จาก certutil (findstr ตัดบรรทัดที่มี ':' ออก เหลือเฉพาะ hash)
set "EXE_HASH="
for /f "tokens=*" %%h in ('certutil -hashfile "dist\BotLineRanger\BotLineRanger.exe" SHA256 ^| findstr /v ":"') do (
    if not defined EXE_HASH set "EXE_HASH=%%h"
)
set "EXE_HASH=!EXE_HASH: =!"
echo    - EXE Hash: !EXE_HASH!

echo.
set /p UPLOAD_HASH="Upload version %VERSION% + exe_hash to server? (Y/N): "
if /i "!UPLOAD_HASH!"=="Y" (
    python server_version.py register %VERSION% !EXE_HASH!
    set REG_RESULT=!errorlevel!
    if !REG_RESULT! equ 0 (
        echo    [OK] Version + exe_hash registered on server.
    ) else if !REG_RESULT! equ 1 (
        echo.
        echo    Version %VERSION% already exists on server.
        set /p OVERWRITE="    Overwrite existing exe_hash? (Y/N): "
        if /i "!OVERWRITE!"=="Y" (
            python server_version.py update %VERSION% !EXE_HASH!
            if !errorlevel! equ 0 (
                echo    [OK] exe_hash updated on server.
            ) else (
                echo    [ERROR] Failed to update exe_hash.
            )
        ) else (
            echo    Skipped upload.
        )
    ) else (
        echo    [ERROR] Failed to register version. You can upload manually via /exe-versions page.
    )
) else (
    echo    Skipped server upload. You can upload manually via /exe-versions page later.
)

echo.
echo ===============================================================================
echo  Build Completed Successfully!
echo ===============================================================================
echo.
echo Security Features Applied:
echo  [x] Fernet AES encryption for URLs and secrets
echo  [x] HMAC-SHA256 signed API requests
echo  [x] JWT session tokens (15 min expiry)
echo  [x] Hardware ID (HWID) binding
echo  [x] Challenge-response authentication
echo  [x] 5-minute heartbeat with strict failure policy
echo  [x] Anti-debugging detection (IsDebuggerPresent, NtQuery, timing)
echo  [x] Anti-RE tool detection (process and window scanning)
echo  [x] Module integrity and function tamper detection
echo  [x] Background protection guard (2-minute interval)
echo  [x] Python bytecode optimization (level 0 - pyarmor runtime compatible)
echo  [x] onedir build (no UPX, no self-extraction to %%TEMP%%)
echo  [x] Traceback disabled
echo  [x] Sensitive config reset
echo  [x] Unnecessary modules excluded
echo  [x] Version synced to latest_version.json
echo  [x] ZIP archives created
echo  [x] PyArmor obfuscation (Basic license)
echo.
echo Output:
echo  - dist\BotLineRanger\
echo  - dist\BotLineRanger.zip
echo  - dist\BotLineRanger_%VERSION%.zip
echo.
echo WARNING: This is a secured build. Reverse engineering is difficult but
echo          not impossible. Keep your source code and keys private!
echo.
echo ===============================================================================
pause
