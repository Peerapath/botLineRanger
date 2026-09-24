# botLineRanger.py
# จำกัด thread pool ของ OpenBLAS/OMP ก่อน import numpy/cv2 (ทั้งคู่ลิงก์ OpenBLAS)
# สำคัญมากตอนรัน headless หลายร้อย/พันโปรเซส: ดีฟอลต์ OpenBLAS จอง thread = จำนวน core (เช่น 28)
# ต่อทุกโปรเซส -> 1024 โปรเซส x 28 thread = หมื่นกว่า thread + buffer -> OOM
# ("OpenBLAS error: Memory allocation still failed"). งาน headless ไม่ใช้ BLAS เลย 1 thread พอ
import os
for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "OPENBLAS_MAIN_FREE"):
    os.environ.setdefault(_v, "1")

from datetime import datetime
from time import sleep
import time
import sys
import json
import atexit
import importlib
from bot_version import CURRENT_VERSION   # แทน 'import main as mai' เดิม (เลี่ยง customtkinter ใน worker)

# Windows console/พื้นฐานเป็น cp1252: พอ print ข้อความไทย/emoji (เช่น log [SESSION], ชื่อ ranger,
# ข้อความ error) ลง console จะโยน UnicodeEncodeError ('charmap' codec can't encode characters ...)
# แล้ว worker พังทั้ง session (เห็นใน src/log/genid-sessions.csv เป็น FAIL). บังคับ UTF-8 ที่
# stdout/stderr เหมือนที่ tools/*.py ทุกไฟล์ทำ. guard ไว้เผื่อ stream ถูก redirect เป็น devnull/
# object ที่ไม่มี reconfigure(). ต้องทำก่อนมี print แรกของบอท
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

####################################################### function ########################################################
####################################################### function ########################################################
####################################################### function ########################################################


# DEVICE/U2DEVICE อยู่ที่ None เสมอ (setUp/adb ถูกลบไปแล้ว - Task 11)
DEVICESERIAL = ""
DEVICE = None
U2DEVICE = None

########## config ##########
STAGEEND = 150
LEVELTARGET = 3        # โหมด Level3/GenID: เล่น st01 ซ้ำผ่าน API จนเลเวลถึงค่านี้ (config: leveltarget)
CHANGEID = True
AUTOUSEITEM = True
RANGERINTEAM = 5
MAXMINERALCOST = 1300
LOSTCOUNT = 3
GIFTBOX = True
TIMEINTERVAL = 5
BUYFRIEND = "everyTime"
AUTOTEAM = False
CLOSEPOPUP = True
AUTOMODE = "bot"

GACHARANGERGROUP = ""
GACHARANGER = False
RSELCTIONEVENT = 1
RSTOPWHENFOUND = True
RGACHAMODE = "giveItAll"
RGACHACYCLES = 5
RUSERUBY = False
EXCHANGEGACHATICKET = True

ACCEPT7DAY = True
ACCEPTPASS = True
BUYLEONARD9 = True
BUYRUBY = True
BUYTICKET = True
UPDATERBTK = False

GSELECTIONEVENT = 1
GSTOPWHENFOUND = True
GUSE200RUBY = True
GGACHAMODE = "giveItAll"
GGACHACYCLES = 200

########## game ##########
GAMEID = ""
FILENAME = ""
RBTK = ""
RBTKPOSITION= "front"
STAGENUMBER = 0
HIGHERSTAGE = 0
RANGERSCONFIG = {}
LFACCACHE = None            # LF_AC ของ session ปัจจุบัน ล้างทิ้งใน force_stop_LINE_Rangers()
IMPORTEDENCLFAC = None      # _ENC_LF_AC_KEY ของไฟล์ที่ import เข้าเครื่อง = token เก่า ห้ามเอาไปยิง API
HEADLESS = False            # True = โหมด headless แท้: mint LF_AC เองจากไฟล์ ไม่แตะ device/เกม
_HEADLESSCCPOOL = None      # guest cc (relogin.CcPool) mint ครั้งเดียวใช้ทั้งรอบ renew ตอนโดน 401
LASTGACHASTATUS = ""        # ผลกาชารอบล่าสุด ใช้เขียนลง log สรุป session
GEARS = {}

REIMPORTFILE = ""


current_gacha_cycles = 0


######################################################### logic #########################################################
######################################################### logic #########################################################
######################################################### logic #########################################################


def log(values:object, end="\n", flush=True):
    formatted_datetime = datetime.now().strftime("%H:%M:%S")
    # print(f"{formatted_datetime} {device_serial}: {values}", end=end, flush=flush)
    print(f"{formatted_datetime} {values}", end=end, flush=flush)


######################################################### game api #########################################################
######################################################### game api #########################################################
######################################################### game api #########################################################

# เครื่องมือ API อยู่ที่ ../tools (rangers_api / rewards / gacha / device_session)
# ยิงตรงไปที่ rangers-api.line-apps.com ด้วย LF_AC ที่อ่านจาก shared_prefs บนเครื่อง
# ไม่ต้องใช้ proxy และไม่ต้องเปิดเกมค้างไว้ ดู tools/device_session.py สำหรับที่มาของอัลกอริทึม
#
# ราก path ของ tools/ และ roster/: เมื่อ frozen (PyInstaller) โมดูลถูกฝังใน _internal/_MEIPASS
# แต่ build.bat วาง tools/ และเขียน roster/ ไว้ข้าง exe จึงต้องอิง sys.executable ไม่ใช่ __file__
if getattr(sys, "frozen", False):
    _APP_ROOT = os.path.dirname(sys.executable)
else:
    _APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLSDIR = os.path.join(_APP_ROOT, "tools")

# {unitCode: {"grade": ..., "summonEnergy": ...}} - ข้อมูลกลางของเกม ไม่ใช่ของบัญชีใคร
# ตัวเดียวกันคนละบัญชีค่าเท่ากันเสมอ จึงไม่ต้องล้างตอนสลับ ID (ต่างจาก LFACCACHE)
# เก็บลงไฟล์ด้วยเพราะการอ่านสเปกต้องเอาตัวไปวางในทีมทีละ 5 (ดู apiUnitSpecs) บัญชี 227 ตัว
# ใช้เวลาเกือบ 2 นาที ถ้าไม่เก็บไว้ข้ามโปรเซส ทุกครั้งที่เปิดบอทใหม่จะต้องไล่วางใหม่หมด
UNITSPECCACHE = {}
UNITSPECPATH = os.path.join(_APP_ROOT, "roster", "unit_specs.json")


UNITSPECLOADED = False


def _loadUnitSpecs():
    """โหลด cache สเปกจากไฟล์ครั้งเดียวตอนใช้ครั้งแรก ไฟล์เสีย/ไม่มี = เริ่มจากว่าง ห้าม raise

    สเปกเป็นแค่ตัวช่วยจัดอันดับ ไม่มีก็แค่ต้องไปอ่านใหม่ ไม่คุ้มที่จะทำให้บอททั้งตัวล้ม
    กันอ่านซ้ำด้วย flag ไม่ใช่ "cache ว่าง = ยังไม่ได้โหลด" เพราะรอบแรกสุดไฟล์ยังไม่มี
    จะกลายเป็นเตือนเรื่องเดิมทุกครั้งที่เรียก
    """
    global UNITSPECLOADED
    if UNITSPECLOADED:
        return UNITSPECCACHE
    UNITSPECLOADED = True
    try:
        with open(UNITSPECPATH, encoding="utf-8") as f:
            UNITSPECCACHE.update(json.load(f))
    except Exception as e:
        log(f"unit spec cache: เริ่มจากว่าง ({e})")
    return UNITSPECCACHE


def _saveUnitSpecs():
    """เขียน cache กลับลงไฟล์ เขียนไม่ได้ก็แค่เสียเวลาอ่านใหม่รอบหน้า ไม่ใช่เรื่องคอขาดบาดตาย"""
    try:
        os.makedirs(os.path.dirname(UNITSPECPATH), exist_ok=True)
        with open(UNITSPECPATH, "w", encoding="utf-8") as f:
            json.dump(UNITSPECCACHE, f, ensure_ascii=False, indent=1, sort_keys=True)
    except Exception as e:
        log(f"unit spec cache: เซฟไม่ได้ ({e})")


def _apiCall(function, *args, **kwargs):
    """เรียกฟังก์ชันฝั่ง tools/ แล้วแปลง SystemExit เป็น Exception ธรรมดา

    tools/ เขียนมาเป็น CLI เวลา token ตายหรือ adb หาไม่เจอมันจะ raise SystemExit
    ซึ่งไม่ได้สืบทอดจาก Exception บอทจะ catch ไม่ติดแล้วดับทั้งโปรเซส
    """
    try:
        return function(*args, **kwargs)
    except SystemExit as e:
        raise Exception(f"api: {e}")


def stageCodeOf(stage):
    """แปลงเลขด่านเป็นรหัส stageCode ของ API เช่น 2 -> 'st02', 151 -> 'st151'

    รับรหัสที่เป็น string อยู่แล้ว (ขึ้นต้น st) ส่งผ่านตรง ๆ จะเรียกด้วยเลขหรือรหัสก็ได้
    %02d เติมศูนย์ให้อย่างน้อย 2 หลัก ด่าน 3 หลักขึ้นไปไม่โดนตัด (st151 ก็ได้ st151)
    """
    if isinstance(stage, str):
        return stage if stage.startswith("st") else "st" + stage
    return "st%02d" % int(stage)


def apiEnterStage(stage, teamType="team1", cancel=True):
    """เข้าด่านผ่าน API เพื่ออ่านบริบทการรบ คืน dict (enterable, enemyTowerHp, teamUnits, ...)

    body ถอดจาก libgame.so (ตัวสร้างที่ 0xb6c6a0) ครบ 8 ฟิลด์ teamType เป็นชื่อ "กลุ่มทีม"
    ('team1' สำหรับด่านปกติ ดู [[lgrgs-team-save-api]]) ไม่ใช่ชนิดทีม ต้องส่งไม่งั้นได้ 500

    ⚠️ enter เปิด battle session จริง (ได้ battleSn) ไม่ใช่ read เฉย ๆ — แต่ทดสอบกับเซิร์ฟเวอร์
    แล้วว่า (ก) ไม่กิน heart จนกว่าจะ save สำเร็จ (ข) เปิดซ้อนกันได้ ไม่ชนกับ enter ของ UI
    default cancel=True จึงยิง /stage/cancel/{battleSn}/{stageCode} ปิด session ทันทีหลังอ่าน
    ค่า ไม่ให้ค้างบนเซิร์ฟเวอร์ (ปิดไม่ได้ก็ไม่เป็นไร session หมดอายุเอง ไม่มี heart ค้าง)

    ฟังก์ชันนี้ "อ่านบริบท/เช็คก่อนเล่น" เท่านั้น — ตัวการรบจริงต้องเล่นผ่าน UI
    (playMainStageAtNumber) เพราะ save ต้องมี battle log ที่เซิร์ฟเวอร์เอาไปจำลองซ้ำเพื่อ
    กันโกง ปลอมไม่ได้ (มี rsaKeyBase ต่อการรบ ดู [[lgrgs-stage-battle-api]])

    enterable=False เมื่อ enter ไม่ผ่าน (เช่น heart หมด/ด่านยังไม่ปลด) ดูเหตุผลใน reason
    """
    if TOOLSDIR not in sys.path:
        sys.path.insert(0, TOOLSDIR)
    import rangers_api

    code = stageCodeOf(stage)
    cookie = getLFAC()
    body = {
        "stageCode": code, "itemCodes": [], "friendUid": "", "mercenaryUid": "",
        "guildMemberUid": "", "mercenaryLevel": 0, "multiplePlayCount": 1, "teamType": teamType,
    }
    status, data = _apiCall(rangers_api.call, cookie, "/stage/enter/%s" % code, "POST", body)
    if status != 200 or not isinstance(data, dict) or "result" not in data:
        return {"enterable": False, "stageCode": code, "battleSn": None,
                "reason": f"enter failed (HTTP {status}): {str(data)[:140]}"}

    r = data["result"]
    battleSn = r.get("battleSn")
    if cancel and battleSn is not None:
        try:
            _apiCall(rangers_api.call, cookie,
                     "/stage/cancel/%s/%s" % (battleSn, code), "POST", {})
        except Exception as e:
            log(f"apiEnterStage: cancel ไม่สำเร็จ (ปล่อยหมดอายุเอง): {e}")

    return {
        "enterable": bool(r.get("isEnterable", True)),
        "stageCode": code,
        "battleSn": battleSn,
        "enemyTowerHp": r.get("enemyTowerHp"),
        "needEnergy": r.get("needEnergy"),
        "maxEnergy": r.get("maxEnergy"),
        "machine": r.get("machine"),
        "battleItems": [it.get("itemCode") for it in (r.get("battleGameItem") or [])],
        "teamUnits": [u.get("unitCode") for u in ((r.get("playerUnitTeams") or {}).get("1") or [])],
        "reason": "",
    }


# reinforceType (ชื่อที่ส่งเข้า API) -> ชื่อ field เลเวลใน playerUpgradeLevelStatus
# ถอดชื่อ enum จาก libgame.so แล้วยืนยันกับเซิร์ฟเวอร์จริง (ส่ง level=0 ได้ 102010=ชื่อถูก,
# 500=ชื่อผิด) ชื่อ enum ไม่ตรงกับชื่อ field เป๊ะ ๆ (energyLimitLevel <-> ENERGY_MAX_LIMIT)
# ตัวที่ยังไม่ได้ยืนยัน live (UNIT_*/TOWER_RESIST) ใส่ไว้ตาม string ในไบนารี ถ้า type ผิดจะ
# ได้ 500 แล้วฟังก์ชันโยน error ออกเอง ไม่เงียบ
MACHINE_UPGRADE_TYPES = {
    "ENERGY_MAX_LIMIT": "energyLimitLevel",        # UI "max limit" (พลังงานสูงสุด) - คิด coin
    "ENERGY_PRODUCTION": "energyProductionLevel",  # UI "production rate" (อัตราผลิต) - คิด coin
    "MACHINE_ATTACK": "machineAttackLevel",
    "MACHINE_ATTACK_SCOPE": "machineAttackScopeLevel",
    "MACHINE_CHARGE": "machineChargeSpeedLevel",
    "MACHINE_HP": "machineHpLevel",
    "ACQUIRE_ENERGY": "acquireEnergyLevel",
    "UNIT_HP": "unitHpLevel",
    "UNIT_ATTACK": "unitAttackLevel",
    "TOWER_RESIST": "towerResistRateLevel",
}


def apiUpgradeStatus():
    """คืนระดับอัปเกรดปัจจุบันทั้งหมด (dict ชื่อ field -> level) จาก /player/upgrade/status"""
    if TOOLSDIR not in sys.path:
        sys.path.insert(0, TOOLSDIR)
    import rangers_api

    status, data = _apiCall(rangers_api.call, getLFAC(), "/player/upgrade/status")
    if status != 200 or not isinstance(data, dict):
        raise Exception(f"apiUpgradeStatus failed (HTTP {status}): {str(data)[:200]}")
    return (data.get("result") or {}).get("playerUpgradeLevelStatus") or {}


def _apiBalance(cookie):
    """อ่านยอด coin/gem/crystal ปัจจุบัน ไว้วัด delta หลังอัปเกรด (คนละแหล่งแล้วแต่ type)"""
    if TOOLSDIR not in sys.path:
        sys.path.insert(0, TOOLSDIR)
    import rangers_api
    _s, d = _apiCall(rangers_api.call, cookie, "/home")
    p = (d.get("result") or {}).get("player") or {}
    return {"coin": (p.get("coin") or {}).get("total", 0), "gem": p.get("gem", 0),
            "crystal": dict(p.get("crystal") or {})}


def _balanceDelta(before, after):
    """ผลต่างที่ใช้ไป (before - after) เฉพาะตัวที่ลด แสดงเป็น dict สั้น ๆ"""
    spent = {}
    if before["coin"] - after["coin"]:
        spent["coin"] = before["coin"] - after["coin"]
    if before["gem"] - after["gem"]:
        spent["gem"] = before["gem"] - after["gem"]
    for k in before["crystal"]:
        diff = before["crystal"].get(k, 0) - after["crystal"].get(k, 0)
        if diff:
            spent[k] = diff
    return spent


def apiUpgradeMachine(reinforceType, target=None, steps=1, toMax=False, confirm=False):
    """อัปเกรดค่าหอ/machine ผ่าน API หลักการเดียวกับ upgradeCrystal() แต่ยิง API ตรง

    body ถอดจาก libgame.so (ตัวสร้าง 0xe5db90): POST /player/upgrade/
        {"reinforceType": "<ENUM>", "reinforceLevel": <target>}
    reinforceLevel = "เลเวลปลายทาง" ที่อยากไปถึง ต้อง > เลเวลปัจจุบัน เซิร์ฟเวอร์คิดค่าใช้จ่าย
    สะสมจาก current+1 ถึง target ในครั้งเดียวแบบ atomic (ทดสอบแล้ว 88->91 หัก coin 85,800
    = ผลรวม 3 เลเวล) ถ้าจ่ายไม่ไหว/ยังไม่ปลดจะไม่ขยับเลย ไม่ใช่อัปเกรดครึ่ง ๆ

    ค่าใช้จ่ายแล้วแต่ type: ENERGY_* หัก coin, MACHINE_*/UNIT_* หัก crystal ฟังก์ชันวัดจาก
    ยอดจริงก่อน-หลัง (_apiBalance) ไม่เดา รหัส error: 102010=target<=ปัจจุบัน,
    102009=ยังไม่ปลด (extras บอก minRequiredLevel เช่นต้อง level 100), 500=ชื่อ type ผิด

    เลือกเป้าหมายได้ 3 แบบ:
      target=<n>  ไปเลเวล n ตรง ๆ (jump ทีเดียว เร็ว ใช้เมื่อรู้ว่าจ่ายไหว)
      steps=<n>   ขึ้นทีละ 1 จนครบ n เลเวล (หยุดทันทีถ้าเจอ error - ปลอดภัยกับงบ)
      toMax=True  ขึ้นทีละ 1 จนกว่าจะอัปไม่ได้ (จ่ายไม่ไหว/ตันแม็กซ์) เหมือน UI กด +max

    confirm=False (ดีฟอลต์) = dry-run บอกแค่จะทำอะไร ไม่ยิงจริง ตามคอนเวนชันโปรเจกต์ว่า
    mutation ต้อง confirm ก่อน กันเผลอถลุง coin/crystal
    คืน dict: {type, field, before, after, spent, steps, ok, reason}
    """
    if reinforceType not in MACHINE_UPGRADE_TYPES:
        raise Exception(f"apiUpgradeMachine: ไม่รู้จัก reinforceType {reinforceType!r} "
                        f"(ใช้ได้: {', '.join(MACHINE_UPGRADE_TYPES)})")
    if TOOLSDIR not in sys.path:
        sys.path.insert(0, TOOLSDIR)
    import rangers_api

    field = MACHINE_UPGRADE_TYPES[reinforceType]
    cookie = getLFAC()
    before = apiUpgradeStatus().get(field, 0)
    plan = target if target is not None else (10 ** 9 if toMax else before + steps)

    if not confirm:
        howto = ("ถึงแม็กซ์ที่จ่ายไหว" if toMax else f"ถึงเลเวล {plan}")
        log(f"[dry-run] apiUpgradeMachine {reinforceType}: ตอนนี้ {before} -> จะอัป{howto} "
            f"(ใส่ confirm=True เพื่อทำจริง)")
        return {"type": reinforceType, "field": field, "before": before, "after": before,
                "spent": {}, "steps": 0, "ok": False, "reason": "dry-run"}

    bal0 = _apiBalance(cookie)
    current = before
    done = 0
    reason = "ok"
    # jump ตรงถ้าระบุ target ชัด ไม่ใช่ toMax - ยิงครั้งเดียวเซิร์ฟเวอร์คิดสะสมให้
    if target is not None and not toMax:
        status, data = _apiCall(rangers_api.call, cookie, "/player/upgrade/", "POST",
                                {"reinforceType": reinforceType, "reinforceLevel": target})
        if status != 200:
            reason = f"HTTP {status}: {str(data)[:150]}"
        else:
            current = (data.get("result") or {}).get("playerUpgradeLevelStatus", {}).get(field, current)
            done = current - before
    else:
        # ขึ้นทีละ 1 (steps หรือ toMax) หยุดทันทีที่ยิงไม่ผ่าน - กันถลุงงบ
        cap = 500 if toMax else steps
        for _ in range(cap):
            status, data = _apiCall(rangers_api.call, cookie, "/player/upgrade/", "POST",
                                    {"reinforceType": reinforceType, "reinforceLevel": current + 1})
            if status != 200:
                reason = f"หยุดที่เลเวล {current} (HTTP {status}: {str(data)[:120]})"
                break
            current = (data.get("result") or {}).get("playerUpgradeLevelStatus", {}).get(field, current + 1)
            done += 1

    bal1 = _apiBalance(cookie)
    spent = _balanceDelta(bal0, bal1)
    ok = current > before
    log(f"apiUpgradeMachine {reinforceType}: {before} -> {current} (+{done}) ใช้ {spent or 'ฟรี'} | {reason}")
    return {"type": reinforceType, "field": field, "before": before, "after": current,
            "spent": spent, "steps": done, "ok": ok, "reason": reason}


def apiUpgradeEnergy(toMax=True, steps=1, confirm=False):
    """อัปเกรดพลังงานทั้งสองตัวเหมือน upgradeCrystal() ใน UI: max limit + production rate

    ยิงผ่าน API ตรงแทนการลาก UI + OCR สองตัวคือ ENERGY_MAX_LIMIT กับ ENERGY_PRODUCTION
    (คิดเป็น coin) toMax=True อัปจนงบหมดเหมือนกด +max ทั้งคู่ ใส่ steps แทนถ้าอยากขึ้นทีละนิด
    confirm=False = dry-run ตามเดิม คืน dict ผลของแต่ละตัว
    """
    out = {}
    for t in ("ENERGY_MAX_LIMIT", "ENERGY_PRODUCTION"):
        out[t] = apiUpgradeMachine(t, steps=steps, toMax=toMax, confirm=confirm)
    return out


# ชื่อ group ใน URL ไม่ใช่ "ทีมที่ 1..5" แต่เป็น "ชุดทีม" คนละระบบกัน ในหนึ่ง group มีหลายทีม
# ย่อย (teamNo 1,2,3...) ซึ่งก็คือ A1/A2/A3 ที่เห็นในเกม ส่วนตัวเลขท้าย group คือชุด A/B/C/D/E
# player มีฟิลด์บอกว่า "ทีมย่อยไหนของ group นั้นเป็นตัวแทน" แยกกันคนละฟิลด์ ต้องอ่านให้ถูกตัว
# ไม่งั้นส่ง representalTeamNo ผิดแล้วโดน 102113 (ดู apiSaveTeamGroup)
# ตัวละครที่อยู่ในคลังแต่ลงทีมไม่ได้ (เป็นของไว้ป้อน/อัปเกรด ไม่ใช่ ranger) UI เดิมกันด้วยการ
# กดฟิลเตอร์ "ranger" ก่อนเลือก ฝั่ง API ไม่มีฟิลด์ไหนแยกได้เลย - record หน้าตาเหมือน ranger
# ทุกอย่าง รู้ได้ตอนเซฟแล้วโดน 102124 เท่านั้น อันนี้แค่ seed ไว้กันเสียรอบ ที่เหลือให้
# เซิร์ฟเวอร์สอนเอาผ่าน extras.unitCode (ดู setUpTeamA1)
NONDEPLOYABLENAMES = ("leonard",)

TEAMGROUPREPFIELD = {
    "team1": "useTeamNo",
    "team2": "useSecondTeamNo",
    "team3": "useThirdTeamNo",
    "team4": "useFourthTeamNo",
    "team5": "useFifthTeamNo",
    "pvpteam": "usePvPTeamNo",
    "labyrinth": "useLabyrinthTeamNo",
}


class TeamUnitRejected(Exception):
    """เซิร์ฟเวอร์ไม่ยอมให้ตัวนี้ลงทีม (errorCode 102124)

    แยกเป็น exception ของตัวเองเพราะคนเรียกต้องรู้ว่า "ตัวไหน" ถึงจะคัดออกแล้วลองใหม่ได้
    ถ้าโยน Exception เปล่า ๆ จะเหลือแค่ข้อความ ต้องมา parse string เอาซึ่งเปราะ
    """

    def __init__(self, unitCode, message):
        super().__init__(message)
        self.unitCode = unitCode


def apiReadTeamGroup(group="team1"):
    """คืนทุกทีมย่อยใน group เป็น {"<teamNo>": {"<slot>": "<invenId>"}}

    ต้องเก็บ slot จริงไว้ ไม่ใช่แค่ลำดับ เพราะทีมมีช่องว่างกลาง ๆ ได้ (ของจริงเคยเจอ
    ทีมที่มีแค่ slot 2 กับ 3) ถ้าอ่านเป็น list แล้วเซฟกลับด้วย enumerate จะกลายเป็น
    slot 0,1 = ย้ายตำแหน่งตัวละครโดยไม่ได้ตั้งใจ

    คืนเป็น string ทั้ง key และ value ให้ตรงกับรูปร่างที่ apiSaveTeamGroup ต้องส่ง
    จะได้เอาผลลัพธ์วนกลับไปเซฟต่อได้เลยโดยไม่ต้องแปลงชนิดซ้ำ
    """
    if TOOLSDIR not in sys.path:
        sys.path.insert(0, TOOLSDIR)
    import rangers_api

    status, data = _apiCall(rangers_api.call, getLFAC(),
                            "/player/units/equip?inven=false&team=true&deck=false")
    if status != 200 or not isinstance(data, dict):
        raise Exception(f"apiReadTeamGroup failed (HTTP {status}): {str(data)[:200]}")
    groups = (data.get("result") or {}).get("playerUnitTeamGroupMap") or {}
    return {str(teamNo): {str(u["slot"]): str(u["invenId"]) for u in (units or [])}
            for teamNo, units in (groups.get(group) or {}).items()}


def apiReadTeam(group="team1", teamNo=1):
    """คืนทีมย่อยเดียวเป็น list ของ invenId (int) เรียงตาม slot - ไว้เช็คผลแบบอ่านง่าย ๆ"""
    deck = apiReadTeamGroup(group).get(str(teamNo)) or {}
    return [int(deck[slot]) for slot in sorted(deck, key=int)]


def apiSaveTeamGroup(decks, group="team1"):
    """เซฟทั้ง group ทีเดียว decks = {"<teamNo>": {"<slot>": "<invenId>"}}

    รูปร่าง body ถอดมาจาก libgame.so (ฟังก์ชันที่ 0xf96288) ไม่ได้เดา เพราะเซิร์ฟเวอร์
    ตอบ errorCode เดียวกันหมดเวลาคีย์ผิด เดาเองไม่มีทางรู้ว่าใกล้หรือไกล ตัวจริงคือ
    CCDictionary แล้วค่อยแปลงเป็น JSON:
        {"deck<teamNo>": {"<slot>": "<invenId>", ...}, ..., "representalTeamNo": <n>}
    ข้อควรระวังที่ทดสอบกับเซิร์ฟเวอร์จริงแล้ว:
      - invenId ต้องเป็น "string" ส่ง unitCode แทนจะได้ 500
      - คีย์สะกดว่า representalTeamNo (ตกตัว i) ไม่ใช่ representative ไม่ส่ง = 102113
      - ชื่อ deck ต้องต่อท้ายด้วยเลขทีมย่อย (deck1/deck2) ไม่ใช่ deck เฉย ๆ

    **การเซฟคือ "แทนที่ทั้ง group"** ไม่ใช่แก้เฉพาะทีมที่ส่งไป ทีมย่อยไหนไม่อยู่ใน body
    จะถูกลบทิ้ง (เจอของจริงมาแล้ว: ส่งแค่ deck2 ไป ทีม 1 หายเกลี้ยง) จึงต้องอ่าน
    apiReadTeamGroup() มาก่อนเสมอ แก้เฉพาะทีมที่ต้องการ แล้วส่งกลับไปทั้งชุด

    representalTeamNo ต้องชี้ไปที่ teamNo ที่ "มีอยู่ใน body นี้" ไม่ใช่แค่ค่าเดิมของ player
    บัญชีที่ useTeamNo=2 แล้วส่งไปแค่ deck1 พร้อม representalTeamNo=2 จะโดน 102113
    (extras บอก representativeTeamNo กลับมาให้ด้วย) เพราะทีมตัวแทนจะกลายเป็นทีมว่าง

    ส่งไม่ครบ 5 ตัวได้ (ทดสอบแล้ว 3 ตัวและ 1 ตัวก็ 200) ช่องที่เหลือจะว่าง
    แต่ห้ามมีตัวละครซ้ำในทีมย่อยเดียวกัน เซิร์ฟเวอร์ตอบ 400 errorCode 102110 แล้วไม่แก้อะไรเลย
    """
    if TOOLSDIR not in sys.path:
        sys.path.insert(0, TOOLSDIR)
    import rangers_api

    if not decks:
        raise Exception("apiSaveTeamGroup: decks ว่าง จะลบทีมทิ้งทั้ง group")

    cookie = getLFAC()
    status, data = _apiCall(rangers_api.call, cookie, "/home")
    if status != 200 or not isinstance(data, dict):
        raise Exception(f"apiSaveTeamGroup failed to read player (HTTP {status}): {str(data)[:200]}")
    player = (data.get("result") or {}).get("player") or {}
    repNo = player.get(TEAMGROUPREPFIELD.get(group, "useTeamNo")) or 1

    if str(repNo) not in decks:
        # ทีมตัวแทนเดิมไม่มีตัวละครอยู่เลย (ไม่มีใน group) เก็บไว้ไม่ได้ ต้องย้ายไปทีมที่มีจริง
        # ไม่งั้นเซิร์ฟเวอร์ตีกลับ 102113 ทั้ง request บอกไว้ใน log เพราะเป็นการเปลี่ยน state
        repNo = min(decks, key=int)
        log(f"apiSaveTeamGroup: ทีมตัวแทนเดิมของ {group} ว่าง ย้ายไปทีม {repNo}")

    body = {"deck%s" % teamNo: dict(deck) for teamNo, deck in decks.items()}
    body["representalTeamNo"] = int(repNo)
    status, data = _apiCall(rangers_api.call, cookie,
                            "/player/units/save/%s" % group, "POST", body)
    if status != 200:
        extras = (data.get("extras") or {}) if isinstance(data, dict) else {}
        if isinstance(data, dict) and data.get("errorCode") == 102124 and extras.get("unitCode"):
            raise TeamUnitRejected(extras["unitCode"],
                                   f"unit {extras['unitCode']} ลงทีมไม่ได้: {str(data)[:200]}")
        raise Exception(f"apiSaveTeamGroup failed (HTTP {status}): {str(data)[:200]}")
    return True


def apiSaveTeam(invenIds, group="team1", teamNo=1):
    """เซฟทีมย่อยเดียว invenIds = list ของ invenId เรียงตาม slot 0..4

    เป็นตัวห่อ apiSaveTeamGroup() ที่อ่าน group เดิมมาก่อนแล้วแก้แค่ teamNo ที่ระบุ
    ห้ามยิง endpoint ตรง ๆ ด้วยทีมเดียว เพราะการเซฟคือแทนที่ทั้ง group ทีมอื่นจะหาย
    """
    decks = apiReadTeamGroup(group)
    decks[str(teamNo)] = {str(slot): str(invenId) for slot, invenId in enumerate(invenIds)}
    return apiSaveTeamGroup(decks, group)


def apiUnitSpecs():
    """คืน {unitCode: {"grade": ..., "summonEnergy": ...}} ของตัวที่ "อยู่ในทีม" ตอนนี้

    endpoint คลังปกติไม่เคยส่ง grade/summonEnergy มาเลย มีแต่ unitCode/unitLevel/maxLevel
    ตัวที่ส่งสเปกเต็มคือ /player/units/team/battle/uid/<uid> (อันเดียวกับที่เกมใช้ตอน
    จะเข้าฉาก) แต่มันส่งมาเฉพาะตัวที่ถูกจัดอยู่ในทีมใดทีมหนึ่ง ไม่ใช่ทั้งคลัง
    setUpTeamA1() จึงต้องเอาตัวที่ยังไม่รู้สเปกไปวางในทีมก่อนแล้วค่อยอ่าน

    grade = ดาว/ความหายาก (มากคือดี) summonEnergy = ค่า mineral ที่ต้องจ่ายตอนเรียกลงสนาม
    (น้อยคือดี) สองค่านี้ผูกกับ unitCode ไม่ผูกกับ invenId ตัวซ้ำจึงใช้ค่าเดียวกันได้
    และไม่ขึ้นกับเลเวล (sally lv1 ก็ 1310 เท่าเดิม) จึงเก็บลง UNITSPECCACHE ข้าม ID ได้
    """
    if TOOLSDIR not in sys.path:
        sys.path.insert(0, TOOLSDIR)
    import rangers_api

    cookie = getLFAC()
    status, data = _apiCall(rangers_api.call, cookie, "/home")
    if status != 200 or not isinstance(data, dict):
        raise Exception(f"apiUnitSpecs failed to read player (HTTP {status}): {str(data)[:200]}")
    uid = ((data.get("result") or {}).get("player") or {}).get("uid")
    if not uid:
        raise Exception("apiUnitSpecs: no uid in /home")

    status, data = _apiCall(rangers_api.call, cookie,
                            "/player/units/team/battle/uid/%s" % uid)
    if status != 200 or not isinstance(data, dict):
        raise Exception(f"apiUnitSpecs failed (HTTP {status}): {str(data)[:200]}")

    specs = {}
    groups = (data.get("result") or {}).get("playerUnitTeamGroupMap") or {}
    for teams in groups.values():
        for units in (teams or {}).values():
            for unit in units or []:
                if "summonEnergy" in unit:
                    specs[unit["unitCode"]] = {
                        "grade": unit.get("grade"),
                        "summonEnergy": unit.get("summonEnergy"),
                    }
    _loadUnitSpecs()
    new = {code: spec for code, spec in specs.items() if UNITSPECCACHE.get(code) != spec}
    if new:
        UNITSPECCACHE.update(new)
        _saveUnitSpecs()
    return specs


def setUpTeamA1(slot=5, maxMineralCost=1300, group="team1", teamNo=1):
    """จัดทีม A1 จากตัวที่มีในคลัง เอา rarity สูงสุด ใช้ mineral น้อยสุด

    แทน autoChangeTeam() ที่ลาก UI ทีละตัวแล้ว OCR ค่า mineral จากจอ อันนี้ยิง API ตรง
    ผลลัพธ์เป้าหมายเดียวกัน: เรียงตาม grade มาก->น้อย ตัด grade เท่ากันด้วย mineral น้อย->มาก

    A1 = group "team1" (ชุด A) ทีมย่อยที่ 1 อยากได้ A2 ก็ teamNo=2 อยากได้ชุด B ก็ group="team2"

    maxMineralCost คือเพดานเดียวกับ autoChangeTeam (ดีฟอลต์ 1300) กันไม่ให้ได้ทีมที่
    แพงจนเรียกลงสนามไม่ทัน ถ้ากรองแล้วเหลือไม่ครบ slot จะเติมด้วยตัวที่ถูกที่สุดที่เหลือ
    เพราะทีมขาดคนแย่กว่าทีมแพง ใส่ None ถ้าอยากได้ grade สูงสุดล้วน ๆ ไม่สนราคา
    (เพดาน 1300 ตัด u1630e-sally ที่ grade 8 ทิ้งได้ เพราะมันกิน 1310)

    เลือกได้ตัวละครละ 1 ตัวต่อทีม กันด้วย base_name (u32-brown กับ u32e-brown = brown)
    ที่ยืนยันกับเซิร์ฟเวอร์แล้วคือ unitCode เดียวกันซ้ำในทีม = 102110 ส่วนคนละร่างของ
    ตัวเดียวกันยังไม่ได้ลอง เลือกทางที่ปลอดภัยกว่าไว้ก่อนเพราะในเกมก็ลงซ้ำตัวไม่ได้อยู่แล้ว

    สเปก (grade/summonEnergy) อ่านได้เฉพาะตัวที่อยู่ในทีม (ดู apiUnitSpecs) ตัวที่ยังไม่รู้
    จึงต้องเอาไปวางในทีมเป้าหมายเป็นรอบ ๆ รอบละ 5 ตัวเพื่ออ่านสเปก ระหว่างนี้ทีมนั้นจะถูก
    เขียนทับ ซึ่งไม่เสียหายเพราะปลายทางคือเขียนทับอยู่แล้ว ถ้าพังกลางทางจะคืนทีมเดิมให้
    บัญชี 227 ตัวใช้เวลาไล่อ่านราว 2 นาทีรอบแรก รอบต่อ ๆ ไปอ่านจาก UNITSPECPATH เหลือ ~7 วิ

    ทีมอื่นใน group จะถูกส่งกลับไปด้วยเสมอ (endpoint เซฟแบบแทนที่ทั้ง group ส่งทีมเดียว
    ทีมที่เหลือหายหมด) แต่ถ้าตัวที่เลือกไปจอดอยู่ทีมอื่น จะถูก "ย้าย" มา ทีมนั้นจึงเปลี่ยนได้
    ซึ่งบอกไว้ใน log ทุกครั้ง ไม่ได้เงียบ ๆ
    """
    roster = getTeanInfo()
    if not roster:
        log("setUpTeamA1: คลังว่าง ไม่มีตัวให้จัดทีม")
        return []

    original = apiReadTeamGroup(group)
    specs = dict(_loadUnitSpecs())
    specs.update(apiUnitSpecs())

    # unitCode ที่ลงทีมไม่ได้ เริ่มจากที่รู้อยู่แล้ว ที่เหลือเรียนเอาจาก 102124 ระหว่างทาง
    blocked = {r["unitCode"] for r in roster if r["name"] in NONDEPLOYABLENAMES}

    def saveTeam(rows):
        """เซฟทีม ถ้าโดนปฏิเสธรายตัวให้ตัดตัวนั้นออกแล้วลองใหม่ คืน rows ที่เซฟได้จริง

        ลองใหม่ได้เรื่อย ๆ เพราะเซิร์ฟเวอร์บอกมาทีละตัว ทีมที่มีของแปลก 3 ตัวจะวนสามรอบ
        request ที่ถูกปฏิเสธไม่แก้อะไรเลย (เหมือน 102110) จึงวนซ้ำได้ไม่ต้องกลัวเขียนครึ่ง ๆ

        ตัวเดียวกัน (invenId เดียวกัน) อยู่สองทีมใน group เดียวกันไม่ได้ เซิร์ฟเวอร์ตอบ 102110
        ทดสอบแล้วว่าชนกันที่ invenId ไม่ใช่ตัวละคร (brown คนละตัวอยู่คนละทีมได้ 200)
        จึงย้ายออกจากทีมอื่นให้ ไม่ใช่ข้ามตัวนั้นทิ้ง เพราะตัวเก่ง ๆ มักถูกจอดไว้ที่ A2 อยู่แล้ว
        ถ้าข้ามจะได้ทีมที่แย่ลงโดยไม่จำเป็น (UI เดิมเจอ popup แล้วเลื่อนข้ามไปตัวถัดไป)
        """
        rows = [r for r in rows if r["unitCode"] not in blocked]
        while rows:
            moving = {str(r["invenId"]) for r in rows}
            decks = {}
            for no, deck in original.items():
                if no == str(teamNo):
                    continue
                kept = {slot: inven for slot, inven in deck.items() if inven not in moving}
                # ทีมที่ว่างเปล่าไม่ต้องส่ง คีย์ deck ที่ไม่มีตัวเลยไม่มีความหมาย
                # และถ้ามันเป็นทีมตัวแทน apiSaveTeamGroup จะย้ายตัวแทนให้พร้อม log
                if kept:
                    decks[no] = kept
            decks[str(teamNo)] = {str(i): str(r["invenId"]) for i, r in enumerate(rows)}
            try:
                apiSaveTeamGroup(decks, group)
                return rows
            except TeamUnitRejected as rejected:
                blocked.add(rejected.unitCode)
                log(f"setUpTeamA1: {rejected.unitCode} ลงทีมไม่ได้ ตัดออกแล้วลองใหม่")
                rows = [r for r in rows if r["unitCode"] != rejected.unitCode]
        return []

    # ตัวที่ยังไม่รู้สเปก เอาไปวางทีม 1 ทีละไม่เกิน 5 (ทีมมี 5 ช่อง) แล้วอ่านกลับ
    # ใช้ unitCode เป็น key เพราะสเปกผูกกับ unitCode ตัวซ้ำอ่านรอบเดียวพอ
    unknown = []
    for row in roster:
        if (row["unitCode"] not in specs and row["unitCode"] not in blocked
                and row["unitCode"] not in [u["unitCode"] for u in unknown]):
            unknown.append(row)
    try:
        while unknown:
            # ทีมเดียวห้ามมีตัวละครซ้ำ รอบนี้จึงหยิบได้เฉพาะคนละตัวละครกัน
            batch, seen = [], set()
            for row in list(unknown):
                if len(batch) >= 5:
                    break
                if row["name"] in seen:
                    continue
                seen.add(row["name"])
                batch.append(row)
                unknown.remove(row)
            log(f"setUpTeamA1: อ่านสเปก {len(batch)} ตัว ({', '.join(r['unitCode'] for r in batch)})")
            if saveTeam(batch):
                specs.update(apiUnitSpecs())
    except Exception:
        # คืนทีมเดิมแบบ best-effort ถ้าคืนไม่สำเร็จก็ห้ามกลบ error ต้นทาง ไม่งั้น traceback
        # จะชี้ไปที่ขั้นตอนคืนค่า แล้วหาสาเหตุจริงไม่เจอ
        log("setUpTeamA1: อ่านสเปกไม่สำเร็จ คืนทีมเดิมให้ก่อน")
        try:
            if original:
                apiSaveTeamGroup(original, group)
        except Exception as restoreError:
            log(f"setUpTeamA1: คืนทีมเดิมไม่สำเร็จด้วย: {restoreError}")
        raise

    candidates = [r for r in roster if r["unitCode"] not in blocked]
    for row in candidates:
        spec = specs.get(row["unitCode"]) or {}
        # ไม่รู้สเปก = ถือว่าแย่ที่สุด (grade -1, mineral มหาศาล) จะได้ไม่ถูกเลือกก่อนตัวที่รู้
        row["grade"] = spec.get("grade", -1)
        row["summonEnergy"] = spec.get("summonEnergy", 10 ** 9)

    # grade มาก->น้อย ก่อน แล้วค่อย mineral น้อย->มาก ตรงกับ autoChangeTeam ที่ sort by grade
    # แล้วค่อยข้ามตัวที่ mineral เกินเพดาน ท้ายสุดใช้ maxLevel/level กันลำดับแกว่งเวลาค่าเท่ากัน
    order = sorted(candidates, key=lambda r: (-r["grade"], r["summonEnergy"],
                                              -(r["maxLevel"] or 0), -(r["level"] or 0)))

    def pick(rows):
        chosen, used = [], set()
        for row in rows:
            if len(chosen) >= slot:
                break
            if row["name"] in used:
                continue
            used.add(row["name"])
            chosen.append(row)
        return chosen

    team = pick([r for r in order
                 if maxMineralCost is None or r["summonEnergy"] <= maxMineralCost])
    if len(team) < slot:
        # เพดานทำให้ได้ไม่ครบ เติมด้วยตัวที่ mineral ถูกสุดในบรรดาที่เหลือ (ทีมขาดคนแย่กว่า)
        names = {r["name"] for r in team}
        filler = sorted((r for r in order if r["name"] not in names),
                        key=lambda r: (r["summonEnergy"], -r["grade"]))
        team += pick(filler)[:slot - len(team)]

    team = saveTeam(team)
    if not team:
        raise Exception("setUpTeamA1: ไม่มีตัวไหนลงทีมได้เลย (โดนปฏิเสธหมด)")

    # เช็คด้วยการอ่านกลับ ไม่เชื่อ HTTP 200 อย่างเดียว เพราะเซิร์ฟเวอร์เมินคีย์ที่ไม่รู้จักเงียบ ๆ
    # เช็คทีมอื่นใน group ด้วย เพราะ endpoint นี้เซฟแบบแทนที่ทั้ง group ถ้าพลาดจะลบทีมอื่นทิ้ง
    after = apiReadTeamGroup(group)
    saved = [int(inven) for _, inven in sorted((after.get(str(teamNo)) or {}).items(), key=lambda kv: int(kv[0]))]
    if saved != [r["invenId"] for r in team]:
        raise Exception(f"setUpTeamA1: เซฟแล้วแต่อ่านกลับไม่ตรง (ต้องการ "
                        f"{[r['invenId'] for r in team]} แต่ได้ {saved})")
    # ทีมอื่นใน group อาจโดนดึงตัวไปจริง ๆ (ดู saveTeam) ไม่ใช่ error แต่ต้องเห็นใน log
    # ไม่งั้นคนใช้จะงงว่าทำไมทีม A2 หายไปเอง
    for no, deck in original.items():
        if no != str(teamNo) and (after.get(no) or {}) != deck:
            log(f"setUpTeamA1: ทีม {no} ของ {group} เปลี่ยนไปเพราะถูกดึงตัวมาเข้าทีม {teamNo}")

    log("Team A1: " + ", ".join("%s(g%s/m%s)" % (r["unitCode"], r["grade"], r["summonEnergy"])
                                for r in team))
    return team


def _remainText(ms):
    """แปลง ms ที่เหลือเป็นข้อความสั้น ๆ เช่น '3d 5h' / '2h 10m' / 'ถาวร/หมดแล้ว'"""
    if not ms or ms <= 0:
        return "ถาวร/หมดแล้ว"
    s = ms // 1000
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m = s // 60
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def printGachaBanners(rows):
    """พิมพ์รายการตู้กาชาแบบอ่านง่าย (ใช้ print เพราะเป็นบล็อกหลายบรรทัด ไม่ผ่าน log)"""
    if not rows:
        log("ไม่มีตู้กาชาที่เปิดอยู่")
        return
    print("\nGacha banners (%d):" % len(rows))
    for r in rows:
        end = datetime.fromtimestamp(r["end"] / 1000).strftime("%m/%d %H:%M") if r["end"] else "-"
        print("\n  %s  [%s]%s" % (r["groupId"], r["type"] or "-", "" if r["live"] else "  (CLOSED)"))
        print("    %s" % r["name"])
        if r["featured"]:
            print("    เด่น: %s" % ", ".join(r["featured"]))
        print("    เหลือ: %s (ถึง %s)" % (_remainText(r["remainMs"]), end))
        if r["banner"]:
            print("    banner: %s" % r["banner"])


GACHABANNERTYPES = ("ULTRA_RARE", "PICK_UP")


def reloginFromInput(rel_path=""):
    """relogin จากไฟล์บัญชีใน input/ แล้วคืน 'LF_AC=...' สด โดยไม่ต้องมี device/เกม

    ใช้ตอนต้องการ token สำหรับ "ดึงข้อมูลอย่างเดียว" (เช่นรายการตู้กาชา) แบบ headless
    rel_path = path เทียบกับ input/ ไม่ส่งมา = หยิบ .xml ไฟล์แรกที่เจอ (รวมโฟลเดอร์ย่อย)
    ไม่แก้ไฟล์ต้นฉบับและไม่แตะ session globals (LFACCACHE/GAMEID) เพราะเป็นการยืม token ชั่วคราว
    โทเค็นเก่าในไฟล์ตายแล้วก็ไม่เป็นไร relogin สร้างของสดให้ (โทเค็นเก่าใช้เป็น guestCookie)
    """
    global _HEADLESSCCPOOL
    if TOOLSDIR not in sys.path:
        sys.path.insert(0, TOOLSDIR)
    import relogin
    from device_session import decrypt_lfac

    target = ""
    if rel_path and os.path.isfile(os.path.join("input", rel_path)):
        target = os.path.join("input", rel_path)
    else:
        for root, dirs, files in os.walk("input"):
            xmls = sorted(f for f in files if f.endswith(".xml"))
            if xmls:
                target = os.path.join(root, xmls[0])
                break
        if not target:
            raise Exception("ไม่พบไฟล์บัญชี .xml ในโฟลเดอร์ input")

    acct = relogin.read_account(target)
    guestCookie = decrypt_lfac(acct["udid"], acct["enc"])
    if _HEADLESSCCPOOL is None:
        _HEADLESSCCPOOL = relogin.CcPool()
    cc = _HEADLESSCCPOOL.get()
    status, result, lfAc = relogin.login(cc, acct["udid"], guestCookie, acct["nation"], acct["language"])
    if status == 401 and not result:
        cc = _HEADLESSCCPOOL.renew(cc)
        status, result, lfAc = relogin.login(cc, acct["udid"], guestCookie, acct["nation"], acct["language"])
    if not result or not lfAc:
        raise Exception(
            f"relogin จาก input ล้มเหลว (HTTP {status}) - ไฟล์ {os.path.basename(target)} ใช้ไม่ได้")
    _HEADLESSCCPOOL.mark_proven()
    return "LF_AC=" + lfAc


def getGachaBanner(summary=True, includeClosed=False, types=GACHABANNERTYPES, eventOnly=True, cookie=None):
    """คืนรายการตู้กาชาจาก API เป็น list ของ dict — ไอดีตู้/ชื่อ/แบนเนอร์/ตัวเด่น/เวลาที่เหลือ

    ทั้งหมดมาจาก /gacha/info -> result.gachaGroupResponseList[].gachaGroup (endpoint เดียว
    กับ tools/gacha.py list) ตู้กาชาหนึ่งตู้ = หนึ่ง groupId ส่วน gachaIndex เป็นแค่ตัวเลือก
    จำนวนสุ่มข้างในตู้ ไม่ใช่คนละตู้

    types = กรองเฉพาะ gachaDisplayType ที่อยากได้ ดีฟอลต์เอาแค่ ULTRA_RARE/PICK_UP/CLASSIC
    (ตัดพวก SPECIAL_GEAR ฯลฯ ทิ้ง) ใส่ None ถ้าอยากได้ทุกประเภท

    eventOnly=True เอาเฉพาะตู้อีเวนต์จริง คือชื่อมี "[EVENT-" ตัดตู้บทสอน/pity (PITY_GACHA_TUTO)
    และตู้ถาวรที่ไม่ใช่อีเวนต์ทิ้ง หมายเหตุ: ตู้ CLASSIC ชื่อไม่มี [EVENT-] จะโดนตัดด้วย
    ถ้าอยากได้ CLASSIC กลับมาใส่ eventOnly=False

    banner: bgUrl เป็น dict แยกภาษา เลือก th ก่อน ไม่มีค่อย en (รูปพื้นหลังตู้เต็มใบ) ส่วน
      listBgUrl คือรูปเล็กในลิสต์ ถ้าอยากได้เพิ่มดึงเองจาก raw ได้
    featured: titleRewardCodes = unitCode ตัวเด่นของตู้ (เช่น u1630e-sally) featuredNames
      ตัดเหลือชื่อตัวละคร (sally) ด้วย pull_roster.base_name เผื่อเอาไปโชว์
    เวลา: exposureEndDate (ms) - ตอนนี้ = remainMs ตู้ถาวรบางตัวไม่มี end (remainMs=0)

    includeClosed=False เอาเฉพาะตู้ที่เปิดอยู่ (อยู่ในช่วง exposure ตอนนี้) True = เอาหมด
    เรียงตาม sortOrder เหมือนที่เกมเรียงโชว์
    summary=False ถ้าจะเอาไปใช้ต่อในโค้ด ไม่ต้องพ่นสรุปลง log
    """
    if TOOLSDIR not in sys.path:
        sys.path.insert(0, TOOLSDIR)
    import rangers_api
    import pull_roster

    if not cookie:
        raise Exception("getGachaBanner: requires cookie (getLFAC() was deleted in Task 11)")
    status, data = _apiCall(rangers_api.call, cookie, "/gacha/info")
    if status != 200 or not isinstance(data, dict):
        raise Exception(f"getGachaBanner failed (HTTP {status}): {str(data)[:200]}")

    now = int(time.time() * 1000)
    groups = sorted((data.get("result") or {}).get("gachaGroupResponseList") or [],
                    key=lambda g: (g.get("gachaGroup") or {}).get("sortOrder", 999))
    rows = []
    for group in groups:
        gg = group.get("gachaGroup") or {}
        # if types is not None and gg.get("gachaDisplayType") not in types:
        #     continue
        # if eventOnly and "[EVENT-" not in (gg.get("gachaName") or ""):
        #     continue
        start, end = gg.get("exposureStartDate"), gg.get("exposureEndDate")
        live = bool(start and end and start <= now <= end)
        if not includeClosed and not live:
            continue
        bg = gg.get("bgUrl") or {}
        featured = gg.get("titleRewardCodes") or []
        rows.append({
            "groupId": gg.get("groupId"),
            "name": gg.get("gachaName"),
            "banner": bg.get("th") or bg.get("en") or next(iter(bg.values()), None),
            "featured": featured,
            "featuredNames": [pull_roster.base_name(u) for u in featured],
            "type": gg.get("gachaDisplayType"),
            "resultType": gg.get("gachaResultType"),
            "start": start,
            "end": end,
            "remainMs": (end - now) if (end and end > now) else 0,
            "live": live,
        })

    if summary:
        printGachaBanners(rows)
    return rows


# <string name="_ENC_LF_AC_KEY">XlFUtmjasX4O0vMMM6Af9o5/2zDVVzXQK2bjNE+ZFXH3p/HdUJsHqam1BRwkQJlj/DNJ+DWwbBMp&#10;pba+UZZUHbFYW1hsiivxEAC8zT/SIUWsWu3yl0PDl8h/mMKo5jtNKExdeYoGSwBVzu1UuETTvBho&#10;qGPnZEdXHpwhK9pxHc0SJ+HcQNPS/qfGl/kawcyon9vvM3n0saMpjf6CT4yupsu6ppdYrSFxMHiB&#10;MPvB/wNEIEIBsH82VYYLgSSTUn+9kS0gvhKPTI3euoI4iQa0ENyH69NtLqfbdjICJ1WsEO3a/V/x&#10;oQo/1GmqCJuXnNCqDtj7llq3th49YNuA3UJk03JRzvjVgexjZYkY820sHfrYYczyTZT6PHd50X3n&#10;LPxpisIvgMWxxATs5SoFDsVYgQ==&#10;    </string>
