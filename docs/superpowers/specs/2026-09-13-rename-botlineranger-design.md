# Rename KaiRubyClearMission → BotLineRanger (bot code + build pipeline)

Date: 2026-09-13
Status: Approved

## Goal
โปรเจคนี้ถูกคัดลอกมาจากต้นแบบ `D:\Programing\ranger\BotKaiByClearMission` เพื่อสร้างโปรเจคใหม่
ชื่อ **BotLineRanger** ต้องเปลี่ยนตัวตนของโปรเจค (ชื่อโมดูล/หน้าต่าง/ไอคอน/exe/zip/URL อัปเดต/
salt เข้ารหัส) จาก KaiRubyClearMission / KaiByClearMission ให้เป็น BotLineRanger และคัดลอกไฟล์
build-support ที่ `build.bat` เรียกใช้แต่ยังขาดจาก `bot/` มาให้ครบ

**ไม่ใช่การเปลี่ยน logic ของบอท** — เป็นการ rebrand + เติมไฟล์ build ให้ครบเท่านั้น

## Naming
- โมดูล/ไฟล์ Python หลัก: `botLineRanger.py` (camelCase, ตรงกับของเดิม `botKaiRubyClearMission.py`)
- ชื่อที่แสดงผล / exe / zip / spec / โฟลเดอร์ dist / service ในสายตาผู้ใช้: `BotLineRanger`
- GitHub repo placeholder สำหรับ update/version: `Peerapath/BotLineRanger` (ยังไม่มี repo จริง)

## A. คัดลอกไฟล์ build-support จากต้นแบบเข้า `bot/`
`build.bat` (cd /d %~dp0 → รันใน `bot/`) เรียกใช้ไฟล์เหล่านี้ ซึ่งปัจจุบัน `bot/` มีแค่ `build.bat`

คัดลอกตรงๆ (ไม่มีชื่อเก่าในเนื้อไฟล์ — ยืนยันด้วย grep แล้ว):
- `get_version.py`, `server_version.py`, `find_unused_modules.py`, `update_version.py`, `reset_config.py`
- `updater.spec` (name='updater' ไม่มีชื่อเก่า)
- `exclude_modules.txt`, `requirements.txt`, `SECURITY_NOTES.md`
- `default_config/config.ini`, `default_config/configRanger.ini`, `default_config/latest_version.json`

คัดลอกแล้วแก้:
- `encrypt_config.py` — แก้ `EMBEDDED_SALT` + `version_url` (ดู C)
- `updater.py` — แก้ repo/ชื่อไฟล์/label/process (ดู D)
- `safe_modules.txt` — `botKaiRubyClearMission` → `botLineRanger`
- `KaiByClearMission.spec` → คัดลอกเป็น **`BotLineRanger.spec`** แก้ `name='BotLineRanger'`,
  `icon=['src\\image\\home\\BotLineRanger_128.ico']`, hiddenimport `botKaiRubyClearMission` → `botLineRanger`

## B. เปลี่ยนชื่อในโค้ดบอทที่มีอยู่แล้วใน `bot/`
1. `bot/botKaiRubyClearMission.py` → rename เป็น `bot/botLineRanger.py`
   - แก้คอมเมนต์บรรทัด 1 (`# botKaiRubyClearMission.py` → `# botLineRanger.py`)
   - ลบ `bot/__pycache__/botKaiRubyClearMission.*.pyc` (stale)
2. `bot/main.py`
   - บรรทัด 5: `from botKaiRubyClearMission import *` → `from botLineRanger import *`
   - บรรทัด 303: `self.title("KaiByClearMission")` → `self.title("BotLineRanger")`
   - บรรทัด 307: iconbitmap `Ruby_128.ico` → `BotLineRanger_128.ico`
   - บรรทัด 440–443: ป้ายเวอร์ชัน — เอา `cursor="hand2"` และ `.bind("<Button-1>", ... open_gethub())` ออก
   - บรรทัด 1871–1873: ลบฟังก์ชัน `open_gethub()`
   - บรรทัด 2135: module-hash list `'botKaiRubyClearMission'` → `'botLineRanger'`
3. `bot/src/image/home/Ruby_128.ico` → `BotLineRanger_128.ico`, `Ruby_64.ico` → `BotLineRanger_64.ico`
   (คงรูปเดิม เปลี่ยนแค่ชื่อไฟล์; `_64` ไม่มีโค้ดอ้างถึงแต่เปลี่ยนให้สอดคล้อง)

## C. ค่า backend / secrets
ไฟล์: `bot/config_secure.py` (runtime) และ `bot/encrypt_config.py` (build-time tool)

| ค่า | การกระทำ |
|---|---|
| salt | `KaiByClearMission_v2_secure_salt_2025` → `BotLineRanger_v2_secure_salt_2025` (ทั้งสองไฟล์) |
| version_url | เปลี่ยน repo → `https://raw.githubusercontent.com/Peerapath/BotLineRanger/refs/heads/main/latest_version.json` |
| api_url | คงเดิม |
| service_id (`bot_kai_by_clear_mission`) | คงเดิม — backend รู้จัก client ด้วยค่านี้ ถ้าเปลี่ยนจะ auth ไม่ผ่าน |
| master_password | คงเดิม |

ขั้นตอน:
1. แก้ `PLAINTEXT_CONFIG.version_url` + `EMBEDDED_SALT` ใน `encrypt_config.py`
2. รัน `python encrypt_config.py` (ใน `bot/`) → ได้ค่า encrypted 4 ตัวใหม่
3. วางค่าใหม่ลง `config_secure.py._ENCRYPTED_DATA` + เปลี่ยน `_SALT` ให้ตรงกัน

## D. updater.py + build.bat
`updater.py`:
- `DOWNLOAD_URL` → `https://github.com/Peerapath/BotLineRanger/releases/latest/download/BotLineRanger.zip`
- `CONFIG_URL`, `CONFIGRANGER_URL` → repo `Peerapath/BotLineRanger`
- `TARGET_PROCESSES`: `KaiByClearMission.exe` → `BotLineRanger.exe`
- ข้อความ `Update KaiRubyClearMission` → `Update BotLineRanger`

`build.bat`:
- `set NAME=BotLineRanger`, `set ICON=src\image\home\BotLineRanger_128.ico`
- title/echo `KaiByClearMission` → `BotLineRanger`
- pyarmor gen: `botKaiRubyClearMission.py` → `botLineRanger.py`
- `pyinstaller ... KaiByClearMission.spec` → `BotLineRanger.spec`
- ทุก path `dist\KaiByClearMission` → `dist\BotLineRanger`, zip `KaiByClearMission*.zip` → `BotLineRanger*.zip`,
  certutil hashfile path, `del config_secure.py/protection.py` paths

## ขอบเขต — ไม่แตะ
- `ruby`/`Rb` ที่เป็นสกุลเงินในเกม: `RUSERUBY`, `getRubyAndTicket`, `rubyBalance`, config keys
  (`ruseruby`, `buyruby`, `guse200ruby`), รูปแบบชื่อไฟล์บัญชี `_Rb{ruby}_`
- `pyarmor_runtime_009939` (ผูกกับ license), path `...Python311` ใน spec (เครื่องผู้ใช้)
- log / xml บัญชี / roster / captures เก่า
- logic การทำงานของบอท

## Verification
- `python encrypt_config.py` ถอดกลับด้วย salt ใหม่ได้ตรง plaintext ทั้ง 4 (ไม่ echo ค่าลับ)
- `cd bot && python -c "import botLineRanger, main"` import ผ่าน (เท่าที่ dependency บนเครื่องอนุญาต)
- grep `-i "kaiby\|kairuby\|clearmission"` ทั้ง repo (ยกเว้น `bot/src/log`, `.pyc`, ไฟล์บัญชี) → ไม่เจอ
- ไฟล์ที่ `build.bat` เรียกใช้ทุกตัวมีอยู่จริงใน `bot/`

## Risks / Known limitations
- repo `Peerapath/BotLineRanger` ยังไม่มีจริง → update/version-check จะ fail จนกว่าจะสร้าง repo (แก้ค่าทีหลังได้)
- ไม่ได้รัน build เต็ม (ต้องมี pyarmor/pyinstaller + license) — แก้ไฟล์ให้ถูกต้องเท่านั้น
- `updater.py` โหลด config repair จาก `config.ini`/`configRanger.ini` (singular) ซึ่งเป็น mechanism
  ของต้นแบบ ไม่ตรงกับ `configRangers.ini`/`configGears.ini` ใน `src/` — pre-existing ของต้นแบบ นอกขอบเขต rename
