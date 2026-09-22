r"""ต่ออายุ LF_AC ในไฟล์บัญชี GUEST ทั้งโฟลเดอร์แบบไม่ใช้เกม แล้วเขียนทับไฟล์เดิม.

เซิร์ฟเวอร์ระบุผู้เล่นจาก LF_AC เก่าที่เก็บในไฟล์ (guestCookie) ไม่ใช่จากเครื่อง จึง
ยิง GET /v12.3/login ด้วย cc (userToken ของ guest ที่ mint จาก API) + udid + guestCookie
เพื่อขอ LF_AC ใหม่ แล้วเข้ารหัสด้วย udid เดิมทับเฉพาะค่า _ENC_LF_AC_KEY ในไฟล์.

Standard library เท่านั้น (account_file/device_session ใช้ cryptography อยู่แล้ว).

    python tools/relogin.py bot/input/15-3 --workers 4
    python tools/relogin.py bot/input/15-3 --limit 3
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import html
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from account_file import encrypt_lfac, _wrapped  # noqa: E402
from device_session import decrypt_lfac  # noqa: E402

import new_account as na  # noqa: E402
import rangers_api  # noqa: E402
import ratelimit  # noqa: E402

ENC_RE = re.compile(r'(<string name="_ENC_LF_AC_KEY">)(.*?)(</string>)', re.S)

UA_GAME = "LGRGS/%s (Linux; U; Android 12; en-US; SM-S9110 Build/V417IR)" % rangers_api.CLIENT_VERSION
APP_VERSION = "LGRGS/%s;android/12" % rangers_api.CLIENT_VERSION
RANGERS_HOST = rangers_api.HOST
LOGIN_PATH = rangers_api.API + "/login"
PROVEN_WINDOW = 60.0  # วินาที: cc ที่เพิ่งสำเร็จภายในช่วงนี้ ถือว่า 401 = ไฟล์เสียเอง
RETRY_WAITS = (2, 4, 8)  # backoff เมื่อเจอ 429 / app-429 / 5xx (network error: na._do retry ให้เองแล้ว)


class BadFile(Exception):
    """ไฟล์อ่านไม่ได้ หรือไม่มีคีย์ที่จำเป็น"""


def _field(text, name):
    m = re.search(r'<string name="%s">(.*?)</string>' % re.escape(name), text, re.S)
    return html.unescape(m.group(1)).strip() if m else None


def read_account_from_text(text):
    udid = _field(text, "_DEVICE_UUID_KEY")
    enc = _field(text, "_ENC_LF_AC_KEY")
    if not udid or not enc:
        raise BadFile("missing _DEVICE_UUID_KEY or _ENC_LF_AC_KEY")
    return {
        "udid": udid,
        "enc": enc,
        "nation": _field(text, "USER_NATION_CODE") or "TH",
        "language": _field(text, "LANGUAGE_TYPE_SETTING_KEY") or "en",
        "text": text,
    }


def read_account(path):
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
        return read_account_from_text(fh.read())


def replace_enc(text, udid, lf_ac):
    """แทนที่เฉพาะค่า _ENC_LF_AC_KEY ด้วย blob ใหม่ คงส่วนอื่นทุกไบต์"""
    wrapped = _wrapped(encrypt_lfac(udid, lf_ac))
    return ENC_RE.sub(lambda m: m.group(1) + wrapped + m.group(3), text, count=1)


class Transient(Exception):
    """error ชั่วคราวที่ retry แล้วยังไม่หาย -> ให้ตัวเรียกนับเป็น error"""


def login(cc, udid, guest_cookie, nation, language="en"):
    """ยิง GET /v12.3/login คืน (status, result_or_None, lf_ac_or_None).

    retry เองเมื่อเจอ 429 / app-429 (HTTP 400+errorCode 429) / 5xx (RETRY_WAITS). ถ้ายังไม่หายหลัง
    retry ครบ -> raise Transient ให้ process_file นับเป็น error. network error -> raise Transient
    ทันที (na._do retry ให้แล้ว). 401 ไม่ retry (เป็นคำตอบจริงของเซิร์ฟเวอร์ ไม่ใช่ปัญหาชั่วคราว).
    """
    cookie = "cc=%s; udid=%s; guestCookie=%s;" % (cc, udid, guest_cookie)
    last = None
    for attempt in range(len(RETRY_WAITS) + 1):
        ts_ms = str(int(time.time() * 1000))
        headers = {
            "App-Version": APP_VERSION,
            "userType": "",
            "Nation-Code": nation,
            "Accept-Language": language,
            "User-Agent": UA_GAME,
            "marketId": "",
            "useLGC": "true",
            "X-LINEGAME-MCC": "000",
            "X-LINEGAME-MNC": "00",
            "X-LINEGAME-TIMESTAMP": ts_ms,
            "Host": RANGERS_HOST,
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip",
            "Cookie": cookie,
        }
        req = urllib.request.Request("https://" + RANGERS_HOST + LOGIN_PATH,
                                     headers=headers, method="GET")
        try:
            status, res, cookies = na._do(req)
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            # na._do already retried the network error with backoff (_NET_ATTEMPTS); looping
            # again here would multiply the wait (8 x 4 ~ 16 min per file when the net is down).
            raise Transient("network: %s" % exc)
        else:
            if (status == 429 or ratelimit.is_app_429(status, res) is not None
                    or (isinstance(status, int) and 500 <= status < 600)):
                last = status
            else:
                lf_ac = na._cookie_value(cookies, "LF_AC")
                result = res.get("result") if isinstance(res, dict) and "result" in res else None
                if not result or not lf_ac:
                    return status, None, None
                return status, result, lf_ac
        if attempt < len(RETRY_WAITS):
            time.sleep(RETRY_WAITS[attempt])
    raise Transient("transient after retries: %s" % last)


class CcPool:
    """เก็บ cc ที่ทุก thread ใช้ร่วมกัน สร้างใหม่แค่ครั้งเดียวต่อ cc ที่ตายแล้ว"""

    def __init__(self):
        self._lock = threading.Lock()
        self._cc = None
        self._proven_at = 0.0
        self._mint()

    def _mint(self):
        try:
            self._cc = na.register_guest(secrets.token_hex(16))["userToken"]
        except (Exception, SystemExit) as exc:
            raise Transient("guest mint failed: %s" % type(exc).__name__)
        self._proven_at = 0.0

    def get(self):
        with self._lock:
            return self._cc

    def renew(self, old_cc):
        with self._lock:
            if self._cc == old_cc:   # ยังไม่มีใคร renew cc ตัวนี้ -> สร้างใหม่
                self._mint()
            return self._cc

    def mark_proven(self):
        with self._lock:
            self._proven_at = time.monotonic()

    def is_proven(self):
        with self._lock:
            return (time.monotonic() - self._proven_at) < PROVEN_WINDOW


def parse_log(log_path):
    """อ่าน log เดิม คืน map rel-path -> status ล่าสุด (บรรทัดท้ายชนะ)"""
    done = {}
    if not os.path.exists(log_path):
        return done
    with open(log_path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if row.get("path"):
                done[row["path"]] = row.get("status", "")
    return done


def iter_targets(root, done, force, limit):
    """คืน path เต็มของ .xml ที่ต้องทำ เรียงตาม rel-path ข้ามที่ ok แล้ว"""
    rels = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith(".xml"):
                full = os.path.join(dirpath, name)
                rels.append((os.path.relpath(full, root).replace("\\", "/"), full))
    rels.sort(key=lambda t: t[0])
    out = []
    for rel, full in rels:
        if not force and done.get(rel) == "ok":
            continue
        out.append(full)
        if limit is not None and len(out) >= limit:
            break
    return out


def atomic_write(full_path, text):
    d = os.path.dirname(full_path)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp, full_path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def backup_once(full_path, root, backup_root):
    rel = os.path.relpath(full_path, root)
    dest = os.path.join(backup_root, rel)
    if os.path.exists(dest):
        return
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy2(full_path, dest)


def process_file(full_path, root, pool, backup_root):
    rel = os.path.relpath(full_path, root).replace("\\", "/")
    try:
        acct = read_account(full_path)
    except (BadFile, OSError):
        return {"rel": rel, "status": "bad_file", "rsn": "", "level": ""}
    try:
        guest_cookie = decrypt_lfac(acct["udid"], acct["enc"])
    except Exception:
        return {"rel": rel, "status": "bad_file", "rsn": "", "level": ""}

    cc = pool.get()
    try:
        status, result, lf_ac = login(cc, acct["udid"], guest_cookie, acct["nation"], acct["language"])
        if status == 401 and not result:
            if pool.is_proven():
                return {"rel": rel, "status": "rejected", "rsn": "", "level": ""}
            cc = pool.renew(cc)
            status, result, lf_ac = login(cc, acct["udid"], guest_cookie, acct["nation"], acct["language"])
            if status == 401 and not result:
                return {"rel": rel, "status": "rejected", "rsn": "", "level": ""}
    except Transient:
        return {"rel": rel, "status": "error", "rsn": "", "level": ""}
    if not result or not lf_ac:
        return {"rel": rel, "status": "error", "rsn": "", "level": ""}

    pool.mark_proven()

    def _restore():
        try:
            atomic_write(full_path, acct["text"])
        except OSError:
            pass

    try:
        backup_once(full_path, root, backup_root)
        new_text = replace_enc(acct["text"], acct["udid"], lf_ac)
        atomic_write(full_path, new_text)
        check = read_account(full_path)
        verified = decrypt_lfac(check["udid"], check["enc"]) == lf_ac
    except Exception:
        _restore()
        return {"rel": rel, "status": "error", "rsn": "", "level": ""}
    if not verified:
        _restore()
        return {"rel": rel, "status": "error", "rsn": "", "level": ""}
    return {"rel": rel, "status": "ok",
            "rsn": result.get("rsn", ""), "level": result.get("level", "")}


REJECT_STOP = 10   # rejected ติดกันเท่านี้ = น่าจะเซิร์ฟเวอร์ปิดปรับปรุง -> หยุด
ERROR_STOP = 60    # error ติดกันเท่านี้ -> หยุด


class StopTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self._rejected = 0
        self._error = 0

    def record(self, status):
        with self._lock:
            if status == "rejected":
                self._rejected += 1
                self._error = 0
            elif status == "error":
                self._error += 1
                self._rejected = 0
            else:  # ok, bad_file คั่น streak การหยุด
                self._rejected = 0
                self._error = 0
            if self._rejected >= REJECT_STOP:
                return "maintenance"
            if self._error >= ERROR_STOP:
                return "errors"
            return None


def _fmt_summary(counts):
    return " ".join("%s=%d" % (k, counts.get(k, 0))
                    for k in ("ok", "rejected", "error", "bad_file"))


def run(root, workers, limit, force):
    root = os.path.abspath(root)
    log_path = root.rstrip("/\\") + ".relogin.csv"
    backup_root = root.rstrip("/\\") + "_backup"
    done = parse_log(log_path)
    targets = iter_targets(root, done, force, limit)
    total = len(targets)
    print("targets: %d (skipped %d already ok)" % (total, sum(1 for s in done.values() if s == "ok")))
    if not total:
        return {}

    try:
        pool = CcPool()
    except Transient:
        print("cannot mint an initial guest cc (game auth may be down) - aborting; rerun later")
        return {}
    tracker = StopTracker()
    counts = {}
    log_lock = threading.Lock()
    new_log = (not os.path.exists(log_path)) or os.path.getsize(log_path) == 0
    stop_reason = [None]

    log_fh = open(log_path, "a", encoding="utf-8", newline="")
    writer = csv.writer(log_fh)
    if new_log:
        writer.writerow(["path", "status", "rsn", "level", "time"])

    done_n = [0]

    def worker(path):
        if stop_reason[0]:
            return None
        rel = os.path.relpath(path, root).replace("\\", "/")
        try:
            res = process_file(path, root, pool, backup_root)
        except Exception:
            res = {"rel": rel, "status": "error", "rsn": "", "level": ""}
        with log_lock:
            counts[res["status"]] = counts.get(res["status"], 0) + 1
            done_n[0] += 1
            try:
                writer.writerow([res["rel"], res["status"], res["rsn"], res["level"],
                                 time.strftime("%Y-%m-%dT%H:%M:%S")])
                log_fh.flush()
            except Exception:
                pass
            if done_n[0] % 100 == 0:
                print("[%d/%d] %s" % (done_n[0], total, _fmt_summary(counts)))
        reason = tracker.record(res["status"])
        if reason and not stop_reason[0]:
            stop_reason[0] = reason
        return res

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(worker, p) for p in targets]
            cancelled = False
            for _ in concurrent.futures.as_completed(futures):
                if stop_reason[0] and not cancelled:
                    for f in futures:
                        f.cancel()
                    cancelled = True
    finally:
        log_fh.close()

    if stop_reason[0] == "maintenance":
        print("STOP: rejected %d ครั้งติดกัน — น่าจะเซิร์ฟเวอร์ปิดปรับปรุง (ทุกคำขอ 401). รันซ้ำภายหลังได้" % REJECT_STOP)
    elif stop_reason[0] == "errors":
        print("STOP: error ติดกันมากเกินไป — หยุดไว้ก่อน ตรวจเน็ต/เซิร์ฟเวอร์แล้วรันซ้ำ")
    print("done: %s" % _fmt_summary(counts))
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", help="โฟลเดอร์ที่มีไฟล์ .xml (รวมโฟลเดอร์ย่อย)")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true", help="ทำซ้ำแม้เคย ok แล้ว")
    args = parser.parse_args(argv)
    run(args.folder, args.workers, args.limit, args.force)


if __name__ == "__main__":
    main()
