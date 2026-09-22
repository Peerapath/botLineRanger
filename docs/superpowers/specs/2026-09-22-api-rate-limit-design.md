# ตัวคุมอัตราการยิง API ของ rangers-api (per-account pacer + per-IP bucket + proxy hook)

วันที่: 2026-09-22

## เป้าหมาย

ให้บอทที่รัน 50–300 worker (subprocess ของ `bot_worker.py`) บนเครื่องเดียว/IP เดียว ยิง
`rangers-api.line-apps.com` ได้โดยไม่ชน rate limit ของเซิร์ฟเวอร์ ทั้งในโหมด Login/GenID/Stage
และเครื่องมือ CLI ใน `tools/` (tutorial, gifts, stage_forge, relogin, new_account) โดยแก้ที่จุดเดียว
และเผื่อช่องต่อ proxy ไว้สำหรับกระจายหลาย IP ในอนาคต

## ที่มา (วัดกับเซิร์ฟเวอร์จริง 2026-09-22 ด้วย guest 200 ไอดี จาก IP เดียว)

เซิร์ฟเวอร์มี rate limit 2 ชั้นที่แยกจากกัน:

### ชั้น 1: ต่อไอดี (userKey) — ห้ามยิงซ้ำภายใน ~300 ms หลังคำตอบก่อนหน้า

```
HTTP 400
{"errorCode":429,"extras":{"current":1790091337516,"previous":1790091337314,"userKey":"r7x1o4..."},...}
```

- `current - previous` คือช่วงห่างที่เซิร์ฟเวอร์เห็น: ทุกเคสที่โดนอยู่ในช่วง 0–300 ms
- นับรวมทุก endpoint (ยิง `/stage/last` แล้วต่อด้วย `/giftbox/list` ทันทีก็โดน)
- request ที่ถูกปฏิเสธก็ถูกนับเป็น `previous` ด้วย → ยิงรัวต่อ = โดนต่อเนื่อง (20 connection ไอดีเดียว โดน 95/100)
- ทดลอง client sleep หลังได้คำตอบ: 0 ms โดน 3/3 (gap ≈ 203 ms = RTT), 100 ms โดน 2/3 (gap 297–298),
  ≥ 200 ms ผ่านทั้งหมด (gap ≥ ~400 ms)
- endpoint ช้าอย่าง `/home` (~2.4 วิ) ไม่เคยโดนเพราะ gap ยาวเอง; endpoint เร็ว (~200 ms) โดนทันทีถ้ายิงต่อกัน
- **`tools/rangers_api.py` และ `new_account._do` retry เฉพาะ HTTP 429/503** ชั้นนี้ตอบ HTTP 400 จึงหลุดเป็น
  error ของ caller ทันที (loop ใน `tutorial.py`, `gifts.py` ล้มเพราะเหตุนี้)

### ชั้น 2: ต่อ IP (nginx `limit_req`) — เกิน ~100 req/s

```
HTTP 429  Content-Type: text/html  Server: nginx  (ไม่มี Retry-After)
<html><head><title>429 Too Many Requests</title></head>...
```

| thread (ไอดีแยก, เว้น 450 ms ต่อไอดี) | req/s รวม | nginx 429 |
|---|---|---|
| 25 | 30 | 0 |
| 50 | 61 | 0 |
| 100 | 106 | 3 / 852 (0.4%) |
| 150 | 140 | 22 / 1120 (2%) |
| 198 | 169 | 48 / 1354 (3.5%) |

- ยิงทีละ request บน connection เดียว 39 ครั้งติดไม่โดน (ชั้น 2 ขึ้นกับอัตรารวมของ IP เท่านั้น)
- ยังไม่ได้ยืนยันจาก IP ที่สอง แต่หน้า HTML นี้คือคำตอบมาตรฐานของ nginx `limit_req` ที่ key ด้วย client address

### อื่น ๆ
- HTTP 400 `{"errorCode":500}` โผล่ประปราย (1/39) บน `/home` แม้ยิงช้า — transient ไม่เกี่ยวกับ rate limit
- latency: `/home` ≈ 2.4 วิ, `/stage/last` `/player/item` `/giftbox/list` ≈ 200 ms

## ขอบเขต

ทำ:
- โมดูลใหม่ `tools/ratelimit.py` (standard library เท่านั้น): per-account pacer, per-IP token bucket
  ข้ามโปรเซส, ตัวตรวจ app-429
- ต่อเข้า `tools/rangers_api.py::call` และ `tools/new_account.py::_do` ให้ทุก request ผ่านตัวคุม และ
  retry เมื่อเจอ app-429 (HTTP 400 + `errorCode 429`) เหมือน 429/503
- `relogin.login` และ `stage_forge.enter` นับ app-429 เป็น transient
- proxy hook ผ่าน env `LGRGS_PROXY` (ทั้ง http.client tunnel และ urllib opener) bucket แยกต่อ proxy
- ค่าตั้งใน `config.ini [settings]`: `apirps`, `apiproxies`; `main.py::_spawn_worker` ส่งค่าเป็น env ให้ worker
- unit test + integration probe

ไม่ทำ:
- proxy rotation / health check / ตรวจ IP โดนแฟลก
- ลดจำนวน call ใน flow ของบอท (แนวทาง C)
- limiter แบบ service/socket กลาง (lock file พอสำหรับ ≤ 100 req/s)

## การออกแบบ

### 1. `tools/ratelimit.py`

```python
MIN_GAP_MS   = int(os.environ.get("LGRGS_MIN_GAP_MS", "350"))   # ชั้น 1
RPS_BUDGET   = float(os.environ.get("LGRGS_RPS_BUDGET", "80"))  # ชั้น 2, 0 = ปิด
BURST        = int(os.environ.get("LGRGS_RPS_BURST", "20"))
RL_DIR       = os.environ.get("LGRGS_RL_DIR") or <bot/.ratelimit หรือ %TEMP%/lgrgs-ratelimit>
PROXY        = os.environ.get("LGRGS_PROXY", "")                # "host:port" หรือ "host:port:user:pass"
```

**`AccountPacer`** (ในโปรเซส, thread-safe)
- `wait(key)`: ถ้า `now < last_done[key] + MIN_GAP_MS` → sleep ส่วนต่าง
- `done(key)`: `last_done[key] = now` (เรียกหลังอ่าน response เสร็จ **ทุกกรณี** รวม 4xx/5xx เพราะ
  เซิร์ฟเวอร์นับ request ที่ถูกปฏิเสธด้วย; ถ้า socket พังก่อนได้คำตอบ ไม่เรียก `done` แต่ retry รอบถัดไป
  ยังผ่าน `wait` ตามค่าเดิม)
- key = ค่า cookie ทั้งก้อน (`LF_AC=...` หรือ `cc=...; udid=...; guestCookie=...`) — ไม่ต้อง parse
- เก็บ dict ธรรมดา ตัดทิ้งเมื่อเกิน 10,000 key (worker หนึ่งทำหลายไอดีต่อเนื่อง)

**`IpBucket`** (ข้ามโปรเซส)
- ไฟล์ `RL_DIR/bucket-<proxy_id>-<host>.txt` (`proxy_id` = `direct` หรือ sha1(PROXY)[:8], `host` = ปลายทาง
  เช่น `rangers-api.line-apps.com` / `game-api.line.me` เพราะแต่ละ host มี limit ของตัวเอง) เนื้อหา `"<tokens> <ts>"`
- `acquire()`: วนจนได้ตั๋ว
  1. เปิดไฟล์ `r+` (สร้างถ้าไม่มี) ล็อกทั้งไฟล์: Windows `msvcrt.locking(LK_LOCK)` (ตัว lib retry เอง 10 วิ
     ถ้าหมดเวลาให้วนล็อกใหม่), อื่น ๆ `fcntl.flock`
  2. อ่าน `tokens, ts`; ถ้าอ่านไม่ได้/ไฟล์เสีย → รีเซ็ตเป็น `BURST, now`
  3. `tokens = min(BURST, tokens + (now - ts) * RPS_BUDGET)`
  4. ถ้า `tokens >= 1` → `tokens -= 1`, เขียนกลับ, ปลดล็อก, คืนค่า
     ไม่งั้น เขียน `tokens, now` กลับ, ปลดล็อก, `sleep((1 - tokens) / RPS_BUDGET + jitter[0, 5 ms])`, วนใหม่
- `RPS_BUDGET <= 0` → `acquire()` คืนทันที (ปิด)
- ถ้าไฟล์/ล็อกใช้ไม่ได้เลย (เช่น permission) → log ครั้งเดียวแล้วทำงานแบบปิด ไม่ล้ม request

**`is_app_429(status, parsed_or_text) -> gap_ms | None`**
- คืน `current - previous` เมื่อ `status == 400` และ body เป็น dict ที่ `errorCode == 429`; อื่น ๆ คืน `None`

**`proxy_parts() -> (host, port, auth_header | None)`** แปลง `LGRGS_PROXY`

### 2. จุดเชื่อม

ลำดับต่อ request (เหมือนกันทั้ง `rangers_api.call` และ `new_account._do`):

```
pacer.wait(key) → bucket.acquire() → ส่ง → อ่าน body → pacer.done(key)
→ ถ้า status in (429, 503) หรือ is_app_429(...) → _retry_sleep(attempt, Retry-After) → วนใหม่ (ภายใน MAX_ATTEMPTS เดิม)
```

- `rangers_api.call`: key = `cookie`; เพิ่ม app-429 เข้าเงื่อนไข retry ที่มีอยู่ (บรรทัด `if status in RETRY_STATUSES`)
  หลัง retry หมดคืน `(400, body)` เหมือนเดิมให้ caller ตัดสิน
- `new_account._do(req)`: key = header `Cookie` ของ `req` (ถ้าไม่มี ใช้ `req.full_url` — signup/auth
  ไม่มี cookie แต่ยังต้องเข้า bucket ของ host นั้น); ตรวจ app-429 หลัง parse JSON
- `relogin.login`: เงื่อนไข transient เป็น `status == 429 or app-429 or 5xx` (`_do` retry ให้ก่อนแล้ว
  บรรทัดนี้แค่กันกรณีหมด retry)
- `stage_forge.enter`: `status in (401, 429)` → เพิ่ม `or ratelimit.is_app_429(status, data) is not None`
  และใน `save` เช่นเดียวกันจัดเป็น retry-able (ไม่ใช่ 102205/102204)

### 3. Proxy hook

- `rangers_api._get_conn()`: ถ้ามี `LGRGS_PROXY` → `HTTPSConnection(proxy_host, proxy_port)` +
  `set_tunnel(HOST, 443, headers={"Proxy-Authorization": ...})` ไม่งั้นเหมือนเดิม
- `new_account._do`: ใช้ `urllib.request.build_opener(ProxyHandler({"https": "http://[user:pass@]host:port"}))`
  สร้างครั้งเดียวต่อโปรเซส; ไม่มี proxy → `urlopen` เดิม
- bucket แยกไฟล์ต่อ proxy อยู่แล้ว (ข้อ 1) จึงได้งบ `RPS_BUDGET` ต่อ IP โดยอัตโนมัติ
- worker/CLI หนึ่งตัวใช้ proxy เดียวตลอดอายุ

### 4. ค่าตั้งและ GUI

`config.ini [settings]`:
```
apirps = 80          ; งบ req/s ต่อ IP (0 = ปิด bucket)
apiproxies =         ; host:port[:user:pass] คั่นด้วยจุลภาค ว่าง = ต่อตรง
```

`main.py::_spawn_worker(device, mode)` ส่ง env ให้ worker (copy `os.environ` แล้วเพิ่ม):
- `LGRGS_RPS_BUDGET = apirps`
- `LGRGS_PROXY = apiproxies[i % n]` ตามลำดับ worker ที่สปอว์น (ว่างถ้าไม่มี)
- `LGRGS_RL_DIR = <bot>/.ratelimit`

GUI ไม่เพิ่มช่อง ค่าแก้ผ่านปุ่มเปิด `config.ini` ที่มีอยู่ CLI ใน `tools/` อ่าน env เดียวกัน ไม่เพิ่ม flag
`stage_forge --delay` คงค่าเริ่มต้น 3 วิ (กันโหลดเซิร์ฟเวอร์ต่อไอดี) แต่ `--delay 0` ปลอดภัยแล้ว
เพราะ pacer กันชั้น 1 ให้

### 5. การจัดการ error

- app-429 / nginx 429 / 503 → backoff+jitter+retry (ของเดิม) จน `LGRGS_MAX_RETRY` แล้วคืน status จริง
- bucket ล็อกไฟล์ไม่ได้ → ทำงานแบบปิด + log เตือนครั้งเดียว (ไม่ให้ตัวคุมเป็นสาเหตุให้ worker ตาย)
- `LGRGS_PROXY` ผิดรูปแบบ → `ValueError` ตอน import (fail fast ก่อนยิงอะไร)

## การทดสอบ

`tools/tests/test_ratelimit.py` (stdlib `unittest` ตามแบบ `test_relogin.py`):
1. `AccountPacer` กับนาฬิกา/`sleep` ฉีดเข้าไป: gap 0 → sleep 350 ms, gap 500 → ไม่ sleep, key ต่างกันไม่กระทบกัน
2. `IpBucket`: ตั้ง `RPS_BUDGET=50, BURST=10` สปอว์น 2 subprocess เรียก `acquire()` วนกัน 1 วิ
   → ตั๋วรวม ≤ 50 + 10 + ค่าเผื่อ และ ≥ 40
3. `is_app_429`: HTTP 400 + errorCode 429 → gap; HTTP 400 + errorCode 500 → None; HTTP 429 → None
4. `rangers_api.call` ด้วย `_get_conn` ปลอม: ตอบ 400/errorCode 429 สองครั้งแล้ว 200 → คืน 200 และ
   `_retry_sleep` ถูกเรียก 2 ครั้ง
5. `LGRGS_PROXY` ตั้งแล้ว `_get_conn` เรียก `set_tunnel(HOST, 443)` ด้วย host/port ของ proxy
6. `main._spawn_worker` แจก `LGRGS_PROXY` วนตามลำดับเมื่อมี proxy 2 ตัว

Integration (ทำมือหลัง implement): รันสคริปต์ probe เดิม (150 worker ไอดีแยก, endpoint `/stage/last`)
ผ่าน `rangers_api.call` ตัวใหม่ → คาดหวัง nginx429 = 0, app429 = 0, throughput ≈ 80 req/s

## เกณฑ์สำเร็จ

- โหมด Stage/Login/GenID ที่ 300 worker บน IP เดียว ไม่มี error จาก HTTP 429 หรือ `errorCode 429` ใน log
- loop ใน `tutorial.py` / `gifts.py` วิ่งจบโดยไม่ต้องใส่ `sleep` เอง
- ตั้ง `apiproxies` 2 ตัวแล้ว worker ครึ่งหนึ่งออกทาง proxy แต่ละตัว (ดูจาก access log ของ proxy)
