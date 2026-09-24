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


def _apiCall(function, *args, **kwargs):
    """เรียกฟังก์ชันฝั่ง tools/ แล้วแปลง SystemExit เป็น Exception ธรรมดา

    tools/ เขียนมาเป็น CLI เวลา token ตายหรือ adb หาไม่เจอมันจะ raise SystemExit
    ซึ่งไม่ได้สืบทอดจาก Exception บอทจะ catch ไม่ติดแล้วดับทั้งโปรเซส
    """
    try:
        return function(*args, **kwargs)
    except SystemExit as e:
        raise Exception(f"api: {e}")


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
