# รื้อบอทเป็น engine เธรดเดียวไร้ ADB

วันที่: 2026-09-23 · สถานะ: อนุมัติดีไซน์แล้ว รอแผนลงมือ

## 1. เป้าหมาย

เอาระบบ ADB ออกทั้งหมด แล้วเปลี่ยนจาก "128 โปรเซส × 1 บัญชี" เป็น "1 โปรเซส × N เธรด"
พร้อมลดจำนวน request ต่อบัญชี และทำให้การเพิ่ม proxy เป็นเรื่องของการเติมบรรทัดใน config
ไม่ใช่การแก้สถาปัตยกรรม

**สิ่งที่ห้ามเสีย:**

1. ผลลัพธ์ยังเก็บเป็น **ไฟล์** `.xml` ในโฟลเดอร์ `input/` `execute/` `output/` `backup/` `login failed/`
   ชื่อไฟล์ยังเป็น `{rangers}_Rb{ruby}_Tk{ticket}_{gameId}_Lv{level}.xml` เหมือนเดิม
2. ยัง **build เป็น .exe** ได้ด้วย `bot/build.bat` และ updater เดิมยังอัปเดตได้
3. license/hwid/protection ยังทำงานเหมือนเดิม
4. คีย์ใน `config.ini` ที่มีอยู่แล้วห้ามเปลี่ยนชื่อ (ผู้ใช้มีไฟล์ config ของตัวเองอยู่)
5. play mode ทั้ง 4 ตัวยังอยู่ครบ: `ranger_api_GenID` `ranger_api_Login` `ranger_api_Level3`
   `ranger_api_Stage`

   `ranger_api_Quest` (พร้อม `apiNewbieQuest` และ `apiSkipTutorial`) ถูกพักไว้ที่ branch
   `wip/quest-mode` คอมมิต `77688b2` เพราะยังไม่เสร็จและอยู่ในไฟล์เดียวกับที่งานรื้อจะรื้อทั้งก้อน
   **`engine/flows.py` ต้องออกแบบให้เพิ่มโหมดที่ห้าได้โดยไม่แก้ `pool.py` หรือ `queue.py`**
   แล้วค่อย port งานนั้นกลับเข้ามาเป็นงานแยกรอบหลัง — `git cherry-pick wip/quest-mode` จะชนแน่นอน
   เพราะโครงไฟล์เปลี่ยน ให้ใช้เป็น *ข้อมูลอ้างอิง* ว่าโหมดนั้นเรียกอะไรบ้าง ไม่ใช่เอาแพตช์มาแปะ

## 2. หลักฐานที่ดีไซน์นี้ตั้งอยู่บน

วัดจากโค้ดจริงและรอบทดสอบจริง ไม่ใช่การประมาณ

| ข้อเท็จจริง | ที่มา |
|---|---|
| ทุก play mode ที่เปิดใช้เป็น headless API ล้วน `AutoSetup` ซึ่งเป็นตัวเดียวที่ใช้ ADB ถูกคอมเมนต์ปิด | `bot/main.py:67-73` |
| `botLineRanger.py` มี 202 ฟังก์ชัน แต่ผิวที่ headless ใช้จริงมี ~30 ตัว | `grep '^def '` |
| มีการอ้าง ADB/vision 121 จุดในไฟล์เดียว และ `from ppadb.client import Client` อยู่ระดับโมดูล | `bot/botLineRanger.py:12` |
| import ที่ worker ไม่ได้ใช้: uiautomator2 1,189 ms · customtkinter 944 ms · cv2 831 ms · ppadb 202 ms | วัดบนเครื่องนี้ 2026-09-23 |
| build เป็น **onefile + UPX ขนาด 87 MB** และ worker ทุกตัว re-exec `sys.executable` | `bot/BotLineRanger.spec:184-206`, `bot/main.py:1818-1823` |
| `dist/BotLineRanger.zip` = 150 MB (มี Tesseract-OCR และ adb.exe อยู่ข้างใน) | `ls -l bot/dist` |
| worker ทิ้ง stderr ลง devnull | `bot/bot_worker.py:30-34` |
| `claim_all()` วน 3 รอบ และทุกรอบ `survey()` ยิง GET ครบ 7 แหล่งใหม่หมด | `tools/rewards.py:258-324` |
| `/home` ถูกยิง 3 ครั้งต่อบัญชี (`check_session` · `survey_attendance_package` · `getAccoutInfo`) | `tools/rewards.py:69,180` + `bot/botLineRanger.py:7814` |
| วัดจริง: 128 worker = 181.5 บัญชี/นาที · RAM 5.5 GB · p50 40 วิ | รอบทดสอบ 2026-09-23 |
| งบ 80 req/s ÷ 3.02 บัญชี/วิ = **26.4 request ต่อบัญชี** | คำนวณจากรอบเดียวกัน |
| ยกงบเป็น 200 req/s ที่ 192 เธรด → ≥264.8/นาที p50 กลับมา 41 วิ = คอขวดคือ bucket ของเราเอง | รอบทดสอบเดียวกัน |
| ตอนนี้มี 24,279 ไฟล์ใน `input/` · 19,769 ใน `output/` · **128 ไฟล์ค้างใน `execute/`** | `ls` |

เอกสารอ้างอิงฝั่ง eFootball_API (`D:\Programing\eFootball\eFootball_API\docs\LESSONS.md`) ที่ยืมบทเรียนมา:
ข้อ 2.8 (stderr ห้ามลง DEVNULL) · ข้อ 2.10 (แยก "รอคิว" ออกจาก "พัง") · ข้อ 3.7 (keep-alive:
handshake กิน 697 ms ของทุก call) · ข้อ 8.2 (วัดปลายทางก่อนดันเธรด) · ข้อ 8.4 (อย่าพึ่ง state
ระดับโมดูล)

## 3. สถาปัตยกรรม

```
tools/                      โปรโตคอลเกม — เก็บไว้ทั้งหมด แก้ 3 ไฟล์
  rangers_api.py              + รับ ProxyLane ต่อเธรด แทน PROXY_PARTS ระดับโมดูล
  ratelimit.py                bucket/pacer ย้ายจาก lock file มาเป็น threading.Lock
  rewards.py                  ลดรอบสำรวจ + รับ /home ที่ดึงมาแล้ว
  relogin.py new_account.py gacha.py stage_forge.py newbie_quest.py   ไม่แก้

bot/
  engine/                   ใหม่ทั้งหมด
    session.py                AccountSession — state ของ 1 บัญชี
    flows.py                  login / level3 / genid / stage / quest
    queue.py                  WorkQueue + journal
    proxy.py                  ProxyLane + ProxyPool
    pool.py                   ThreadPool + ตัวรายงานผล
    report.py                 progress → JSONL บน stdout
  engine_main.py            entry ของ engine (ไม่ import GUI)
  main.py                   GUI เดิม ตัดส่วน ADB สปอว์น engine 1 ตัว
  botLineRanger.py          ลบส่วน ADB/vision ย้าย API flow เข้า engine/
  ADB.py nemu_capture.py bot_worker.py    ลบทิ้ง
```

**กฎที่ห้ามละเมิด**

1. `engine/` ห้ามมีความรู้เรื่องโปรโตคอลเกม ต้องเรียกผ่าน `tools/` เท่านั้น
2. `bot/main.py` (GUI) ห้ามมีลอจิกงาน หน้าที่เดียวคือตั้งค่า สปอว์น engine และแสดงผล
3. **ห้ามมี mutable state ระดับโมดูล** ในอะไรที่เธรดแตะ ทุกอย่างส่งผ่านพารามิเตอร์หรือ instance
4. ทุกฟังก์ชันใน `engine/flows.py` รับ `AccountSession` เป็นพารามิเตอร์แรกและไม่อ่าน global

## 4. AccountSession — แกนของการทำให้เป็นเธรดได้

ปัญหาปัจจุบัน: `botLineRanger.py` เก็บ `LFACCACHE` `GAMEID` `FILENAME` `LASTGACHASTATUS`
เป็น global ระดับโมดูล สองบัญชีในโปรเซสเดียวกันจึงเขียนทับกัน นี่คือเหตุผล**เดียว**ที่ต้องแยกโปรเซส
ต่อ worker และเป็นต้นทางของ RAM 5.5 GB

```python
@dataclass
class AccountSession:
    src: str                      # path ของไฟล์ใน execute/
    lane: ProxyLane               # proxy ที่บัญชีนี้ใช้ตลอด session
    cookie: str = ""              # "LF_AC=..."
    rsn: str = ""                 # GAME_ID
    home: dict | None = None      # /home ดึงครั้งเดียว ใช้ซ้ำทั้ง session
    gacha_units: list = field(default_factory=list)
    gacha_status: str = "-"
    level: int = 0
    attempts: int = 0
    error: str = ""
```

ทุกฟังก์ชันใน `flows.py` มีลายเซ็น `def login(s: AccountSession, cfg: Config) -> Outcome`
`Outcome` บอกว่าไฟล์ต้องไปไหน (`output` / `backup` / `login failed` / `retry`) และเหตุผล

## 5. ลด request ต่อบัญชี 26 → ~15

ทั้ง 5 ข้อนี้**ไม่ทำให้เก็บของได้น้อยลง** เป็นการเลิกถามซ้ำสิ่งที่รู้คำตอบแล้ว

ต้นทุนวันนี้แยกตามเส้นทาง (นับจากโค้ดใน `tools/rewards.py` + `tools/gacha.py`):

| | บัญชีที่ไม่มีของให้เก็บ | บัญชีที่มีของเก็บครบทุกรอบ |
|---|---|---|
| relogin + `check_session` | 2 | 2 |
| survey pass 1 (7 แหล่งขนาน) | 7 | 7 |
| claim pass 1 | 0 | ~5 |
| survey pass 2 + claim | 0 | ~10 |
| survey pass 3 | 0 | 7 |
| gacha | ~5 | ~5 |
| `getAccoutInfo` | 2 | 2 |
| **รวม** | **16** | **38** |

ค่าเฉลี่ยที่วัดได้จริงคือ **26.4** ซึ่งอยู่ระหว่างสองเส้นทางนี้พอดี ยืนยันว่าตัวเลขสอดคล้องกัน

| แก้อะไร | ประหยัด (เส้นทางหนัก) | ประหยัด (เส้นทางเบา) |
|---|---|---|
| `/home` ดึงครั้งเดียวเก็บใน `session.home` แล้วส่งต่อให้ `check_session` `survey_attendance_package` `getAccoutInfo` | −2 | −2 |
| pass 2 สำรวจแค่ `giftbox` ไม่ใช่ครบ 7 แหล่ง — ระบบอื่นจ่ายของ *เข้า* giftbox ไม่ได้จ่ายเข้าหากัน | −6 | 0 |
| pass 3 ไม่ทำ เว้นแต่ pass 2 เก็บได้จริง | −7 | 0 |
| `claim_giftbox()` เรียก `_pending_gifts()` สองครั้ง (ก่อนและหลัง) → ใช้รายการที่ `survey_giftbox` ดึงมาแล้ว และอ่านผลจาก response ของ `receive/all` | −2 | 0 |
| `apiGachaWithTicket` ยิง `/gacha/info` สองครั้ง → cache ใน session | −1 | −1 |
| **รวม** | **38 → 20** | **16 → 13** |

ค่าเฉลี่ยใหม่จึงอยู่ราว **15** (จาก 26.4) = **ลดลง ~43%**

ตั้งค่าใหม่ใน `[settings]`: `rewardpasses = 2` (ค่าเดิมคือ 3 ตายตัวในโค้ด) ตั้ง 3 ได้ถ้าอยากได้
พฤติกรรมเดิมเป๊ะ

**ผลต่อความเร็ว:** งบ 90 req/s ต่อ IP (เผื่อขอบจากเพดาน nginx ~100) ÷ 15 request =
**6.0 บัญชี/วิ = ~360/นาที ต่อ 1 IP** เทียบกับ 181/นาที ตอนนี้ = **2.0×**

## 6. ProxyLane และ ProxyPool

```python
class ProxyLane:
    """1 proxy = 1 IP = 1 งบ req/s = กลุ่มเธรดของตัวเอง"""
    name: str                  # "direct" หรือ "host:port"
    parts: tuple | None        # (host, port, auth) หรือ None = ต่อตรง
    bucket: TokenBucket        # งบ req/s ของ IP นี้
    threads: int               # จำนวนเธรดที่วิ่งบน lane นี้
    fails: int                 # connect fail ติดกัน
```

- จำนวนเธรดต่อ lane มาจากกฎของ Little: `concurrency = latency × rate` ที่ 15 request/บัญชี
  latency ราว 22 วิ (วันนี้ p50 = 40 วิ ที่ 26 request) × 6.0 บัญชี/วิ ≈ **132 เธรด/IP**
  ตั้งค่าเริ่มต้น `threadsperproxy = 96` แล้ววัดของจริงค่อยปรับ (กฎเดียวกับ eFootball:
  ตัวเลขที่คำนวณคือจุดตั้งต้น ไม่ใช่คำตอบสุดท้าย)
- **เพดานเธรดรวม `maxthreads = 4096`** — eFootball วัดแล้วว่าเกินระดับนี้งานเริ่ม *ลดลง*
  ไม่ใช่แค่ไม่เพิ่ม ถ้า `จำนวน lane × threadsperproxy` เกิน ให้หารเฉลี่ยลงมาและ**บอกผู้ใช้
  ว่าโดนตัด** ไม่ใช่ตัดเงียบ ๆ ที่ 50 proxy จะได้ ~82 เธรด/lane ซึ่งยังพอ ถ้าเกินกว่านั้น
  ต้องไปทาง "หลาย engine process + SqliteQueue" ตามข้อ 8
- บัญชีหนึ่งผูกกับ lane เดียวตลอด session — ไม่ใช่เพราะเซิร์ฟเวอร์บังคับ แต่เพื่อให้การนับงบ
  ของ bucket ตรงกับ IP ที่ออกไปจริง
- lane ที่ connect ไม่สำเร็จ **3 ครั้งติด** ถูกถอดออกจาก pool งานที่ค้างบน lane นั้นโยนกลับคิว
  และรายงานขึ้น GUI · lane ที่ถอดแล้วจะถูกลองใหม่ทุก 5 นาที
- **ถ้า pool ว่างทั้งหมด engine หยุดและรายงาน** ไม่ใช่วิ่งต่อแบบไม่มี proxy เงียบ ๆ
- ไม่มี proxy เลย = มี lane เดียวชื่อ `direct` ใช้ IP ของเครื่อง พฤติกรรมเหมือนวันนี้

config: `apiproxies` รูปแบบเดิม (`host:port` หรือ `host:port:user:pass` คั่นด้วย comma/newline)
รองรับ 50 ตัวขึ้นไปโดยไม่ต้องแก้อะไร

## 7. rate limit ย้ายเข้าแรม

`tools/ratelimit.py` วันนี้ใช้ lock file + `msvcrt.locking` เพราะต้องกันข้าม 128 โปรเซส
เหลือโปรเซสเดียวแล้วสิ่งเหล่านี้หายไปทั้งคลาส:

- `LockTimeout` และเส้นทาง fail-closed
- `_disabled` หลังพลาด 3 ครั้ง
- การเปิด/ปิดไฟล์ทุกครั้งที่ขอ token

แทนด้วย `TokenBucket` ที่ใช้ `threading.Lock` ธรรมดา และ `AccountPacer` ที่เป็น dict ในแรมอยู่แล้ว

**เก็บโค้ดเดิมไว้** ในชื่อ `FileTokenBucket` พร้อมเทสต์ เผื่อวันหนึ่งต้องกลับไปหลายโปรเซส
(เช่นรันสองเครื่องแชร์ proxy pool เดียวกัน) — ลบทิ้งแล้วจะต้องเขียนใหม่ทั้งหมด

`SlidingQuota` (โควตา mint 2/นาที/IP) ย้ายเข้าแรมเหมือนกัน แต่**ผูกกับ lane** ไม่ใช่ทั้งโปรแกรม
เพราะโควตานี้เป็นของ IP: 50 proxy = mint ได้ 100 บัญชี/นาที

## 8. WorkQueue และ journal

เลิกใช้ `src/split-ID/worker-N.txt` และไฟล์ `.lock` ทั้งหมด

```python
class WorkQueue:
    def __init__(self, root: str, journal: str): ...
    def recover(self) -> int      # เรียกก่อนเริ่ม: คืนไฟล์ค้างจาก execute/ กลับ input/
    def claim(self) -> str | None # input/x.xml -> execute/x.xml + เขียน journal
    def finish(self, src, dest, newname) -> str
    def fail(self, src, err) -> str
    def remaining(self) -> int
```

- สแกน `input/*.xml` ครั้งเดียวตอนเริ่มเข้า `collections.deque` (24k ชื่อไฟล์ ≈ 5 MB ในแรม
  สแกนไม่ถึงวินาที) ระหว่างรันไม่สแกนซ้ำ
- `claim()` / `finish()` ป้องกันด้วย `threading.Lock` ตัวเดียว — การย้ายไฟล์ใช้เวลาไมโครวินาที
  เทียบกับ 13 วิที่ใช้รอเน็ต จึงไม่ใช่คอขวด
- **journal** `src/log/run.jsonl` เขียน 1 บรรทัดตอน claim และ 1 บรรทัดตอนปิด
  `{"t":"claim","f":"a.xml","ts":...}` / `{"t":"done","f":"a.xml","dest":"output","ts":...}`
- `recover()` อ่าน journal หาไฟล์ที่ claim แล้วไม่ปิด แล้วย้ายกลับ `input/` —
  **แก้ปัญหา 128 ไฟล์ที่ค้างอยู่ใน `execute/` ตอนนี้** และกันไม่ให้เกิดซ้ำ
- ไฟล์ที่อยู่ใน `execute/` แต่ไม่มีใน journal (ตกค้างจากยุคเก่า) ก็ย้ายกลับ input/ เหมือนกัน
  พร้อมนับจำนวนรายงานขึ้น GUI

**ทำไมไม่ใช้ SQLite:** ที่ eFootball ชนะเพราะคลัง 700,000 บัญชีทำให้การย้ายไฟล์เป็นคอขวดจริง
ของเราอยู่ที่ 44,000 บัญชี × 13 วิ/บัญชี ซึ่งเน็ตกินเวลา 99.9% และเมทาดาทาที่ต้องใช้ค้นหา
(ruby/ticket/level/gameId) อยู่ในชื่อไฟล์อยู่แล้ว ไม่ต้องเปิดอ่าน การเพิ่มฐานข้อมูลจึงเพิ่ม
"ความจริงสองที่" โดยไม่ได้ความเร็วกลับมา

แต่ `WorkQueue` ถูกออกแบบเป็น interface (`claim`/`finish`/`fail`/`remaining`) เพื่อให้เปลี่ยน
เป็น `SqliteQueue` ได้ในวันที่ต้องรันหลายเครื่อง โดย `flows.py` ไม่ต้องแก้

## 9. GUI ↔ engine

- GUI สปอว์น engine **1 ตัว** ด้วย `[sys.executable, "--engine", mode]` ตอน frozen
  หรือ `[sys.executable, "bot/engine_main.py", mode]` ตอนรันจากซอร์ส (แบบเดียวกับ `--worker`
  วันนี้ จึงไม่ต้องแตะ updater หรือ spec เรื่อง entry point)
- engine เขียน **JSONL ลง stdout** บรรทัดละเหตุการณ์:
  - `{"t":"acct","status":"OK","rsn":"...","lv":3,"ms":12840,"dest":"output"}`
  - `{"t":"stat","done":1204,"fail":3,"left":23075,"rate":7.9,"threads":512,"lanes":8}`
  - `{"t":"lane","name":"1.2.3.4:8000","state":"dead","reason":"connect x3"}`
- GUI อ่านด้วยเธรดเดียว **สะสมแล้วอัปเดตจอทุก 1 วินาที** ไม่ใช่ทุกบรรทัด (บทเรียนจาก
  eFootball: กราฟที่โตทุก log line ทำให้หน้าเว็บช้าลงเรื่อย ๆ ระหว่างบอทรัน)
- `{"t":"stat"}` ส่งทุก 2 วินาที ไม่ผูกกับจำนวนบัญชีที่เสร็จ
- **stderr ของ engine ลงไฟล์ `src/log/engine.err`** ไม่ใช่ devnull และไฟล์ที่ว่างถูกลบตอนจบรอบ
- GUI สั่งหยุดด้วยการเขียนไฟล์ธง `src/log/stop.flag`; engine เห็นแล้วหยุดรับงานใหม่
  รอให้บัญชีที่ค้างอยู่จบ (มีเวลาจำกัด 60 วิ) แล้วรายงานยอดสุดท้ายก่อนออก —
  **ไม่ใช่ `terminate()` ทันที** ซึ่งทำให้ยอดสุดท้ายหาย (eFootball เคยขาดไป 1,427 ใบเพราะข้อนี้)

## 10. การลบ ADB

ลบทั้งไฟล์: `bot/ADB.py` · `bot/nemu_capture.py` · `bot/bot_worker.py`

ลบ dependency ออกจาก `bot/requirements.txt`: `pure-python-adb` · `uiautomator2` ·
`opencv-python` · `numpy` · `pytesseract`

ลบออกจาก dist: `src/Tesseract-OCR/` · `src/adb/` · `src/image/` ทุกโฟลเดอร์ที่ใช้ทำ
image matching (เหลือเฉพาะ icon ที่ GUI ใช้)

ใน `botLineRanger.py` เก็บเฉพาะผิวที่ headless เรียกจริง แล้วย้ายเข้า `engine/flows.py`:

```
setUpHeadless · getLFAC · getLFACHeadless · getLFACFromFile · getAccoutInfo · apiGetPlayer
apiAcceptAllRewards · apiGachaWithTicket · apiEnterStage · apiForceStage · apiLevelUpByStage1
apiReadTeamGroup · apiReadTeam · apiSaveTeamGroup · apiSaveTeam · apiUnitSpecs
apiUpgradeStatus · apiUpgradeMachine · apiUpgradeEnergy
_headlessCreateAccount · logSession · importFileFromInputToExecute · exportFileFromExecuteTo*
startBot{Login,Level3,GenID,Stage}_API_headless
```

(`apiSkipTutorial` และ `apiNewbieQuest` ไม่อยู่ในลิสต์เพราะถูกพักไปกับ `wip/quest-mode` แล้ว
ลอจิกของมันยังอยู่ครบใน `tools/tutorial.py` และ `tools/newbie_quest.py` ซึ่งคอมมิตแล้ว)

ที่เหลือ (ราว 170 จาก 202 ฟังก์ชัน) เป็น ADB/vision/OCR — ลบ **แต่ต้องตรวจทีละตัวว่าไม่มี
ผู้เรียกที่ยังมีชีวิต** ไม่ใช่ลบตามชื่อ (บทเรียน eFootball ข้อ 2.5: ของที่ตายแล้วยังมีปุ่ม 15 ปุ่ม
เรียกอยู่ พังเงียบทั้งคู่) วิธีตรวจ: หลังลบต้อง `grep` ชื่อฟังก์ชันทั้งรีโปรวม `main.py` แล้วไม่เจอ

`force_stop_LINE_Rangers()` ในโหมด headless ทำแค่ล้าง `LFACCACHE` → กลายเป็น
`session.cookie = ""` ไม่ต้องมีฟังก์ชัน

## 11. build

| | ก่อน | หลัง |
|---|---|---|
| โหมด | onefile + UPX 87 MB | **onedir** ไม่ UPX |
| ที่ต้องแตะ | `BotLineRanger.spec` เพิ่ม `COLLECT(...)` ต่อท้าย `EXE(...)` และเอา `upx=True` ออก | |
| `binaries` | cv2 DLL, AdbWinApi, u2 | เหลือ `_tkinter.pyd` `tcl86t.dll` `tk86t.dll` |
| `datas` | + ppadb, pytesseract, u2 apk | เหลือ tcl/tk, customtkinter, PIL |
| `hiddenimports` | + ADB, cv2, numpy | เอา `ADB` `nemu_capture` ออก |
| pyarmor | obfuscate `main.py botLineRanger.py config_secure.py hwid.py protection.py ADB.py nemu_capture.py` | เอา `ADB.py nemu_capture.py` ออก เพิ่ม `engine_main.py` และไฟล์ใน `engine/` |
| `build.bat` xcopy | `src` ทั้งก้อน | ข้าม `src/Tesseract-OCR` และ `src/adb` |
| zip | 150 MB | ~25 MB (ประมาณ ลบ Tesseract ~100 MB + adb 6.4 MB + cv2/numpy ในบันเดิล) |

**ทำไม onedir:** onefile แตกตัวเองลง `%TEMP%\_MEIxxxx` ใหม่ทุกครั้งที่โปรเซสเริ่ม วันนี้จ่าย
128 ครั้ง หลังรื้อจะเหลือ 2 ครั้ง ซึ่งไม่แพงแล้ว — แต่ onedir ยังดีกว่าเพราะ start เร็วกว่ามาก
ไม่กิน temp และโปรแกรมป้องกันไวรัสไม่หวาดระแวงเท่า onefile+UPX

**ใช้ exe เดียว** (flag `--engine`) ไม่แยกเป็นสองไฟล์ เพื่อไม่ต้องแตะ `updater.py`
`latest_version.json` และการเช็ค hash ของ exe ใน `server_version.py`

## 12. เทสต์

`bot/` วันนี้ไม่มีเทสต์เลย (มีแต่ `tools/tests/`) เพิ่ม `bot/tests/` ที่ **ไม่แตะเน็ต ไม่แตะ
โฟลเดอร์จริง**:

- `test_queue.py` — claim/finish/fail/recover, ไฟล์ค้างถูกคืน, สอง "เธรด" ไม่ได้ไฟล์เดียวกัน
- `test_journal.py` — บรรทัดเปิดที่ไม่มีบรรทัดปิดถูกกู้, journal ที่พังกลางบรรทัดอ่านต่อได้
- `test_proxy.py` — lane ตาย 3 ครั้งถูกถอด, งานถูกโยนกลับคิว, pool ว่างแล้ว engine หยุด
- `test_ratelimit.py` — TokenBucket ปล่อย token ตามอัตราจริง (ป้อนนาฬิกาปลอม), quota ผูกกับ lane
- `test_session.py` — `flows.login` กับ client ปลอม: `/home` ถูกเรียกครั้งเดียว,
  pass 2 ยิงแค่ giftbox, เส้นทางหนักนับได้ ≤ 20 request เส้นทางเบา ≤ 13
- `bench_engine.py` — รัน pool จริงด้วย client ปลอมที่หน่วงเวลาคงที่ เพื่อวัด**เพดานฝั่งเรา**
  โดยไม่ยิงเซิร์ฟเวอร์เกมสักครั้ง (ลอกแนวจาก `tools/efb_bench.py` ของ eFootball)

**กฎ:** ตัวปลอมต้อง *ขาด* สิ่งที่กำลังพิสูจน์ และเทสต์ต้องยืนยัน *ตัวตน* ไม่ใช่ *จำนวน*
(eFootball เสียเวลากับสองข้อนี้ซ้ำหลายรอบ)

## 13. ตัวเลขที่คาดหวังและวิธีพิสูจน์

| | ก่อน (วัดแล้ว) | หลัง (คาด) | พิสูจน์ด้วย |
|---|---|---|---|
| RAM ตอนเต็มกำลัง | 5,500 MB (128 proc) | ~400–700 MB (2 proc) | `psutil` บน engine + GUI ระหว่างรอบจริง |
| request/บัญชี (เฉลี่ย) | 26.4 | ~15 | นับใน `test_session.py` + `bench_engine.py` |
| บัญชี/นาที @ 1 IP | 181 | ~360 | รอบจริงกับ `input/` ชุดที่แยกไว้ |
| บัญชี/นาที @ 10 proxy | ทำไม่ได้ (ต้อง 1,280 proc) | ~3,600 | รอบจริงเมื่อมี proxy |
| เวลาระบาย 24,279 ไฟล์ @ 1 IP | 2 ชม. 14 นาที | ~68 นาที | จับเวลาจนคิวหมด |
| dist zip | 150 MB | ~25 MB | `ls -l` หลัง build |
| ไฟล์ค้างหลัง kill | ค้างถาวร (128 ไฟล์ตอนนี้) | 0 | ฆ่า engine กลางรอบแล้วเริ่มใหม่ |

ตัวเลข RAM เผื่อไว้ถึง 700 MB เพราะเธรด 4,096 ตัวมีต้นทุน stack ของตัวเอง — ต้องวัด ไม่ใช่เดา

**วิธีวัดที่ต้องทำตาม:** อย่าวัดตอนเครื่องไม่ว่าง · จับเวลาที่ใช้ระบายคิวจนหมด ไม่ใช่
ขนาดคิว ÷ เวลา · ใช้ไฟล์บัญชีคนละชุดกับรอบก่อนเสมอ (รอบหลังจะได้เปรียบเพราะของถูกเก็บไปแล้ว)

## 14. ข้อจำกัดที่รื้อแล้วก็ยังอยู่

1. **nginx ฝั่งเกมจำกัด ~100 req/s ต่อ IP** → เพดานคือ ~6.7 บัญชี/วิ/IP ที่ 15 request/บัญชี
   ทางเดียวที่จะเกินคือเพิ่ม IP · ตัวเลขนี้เป็นเพดานของ*ปลายทาง* การเขียนโค้ดดีขึ้นไม่ช่วย
2. **per-account min-gap ~300 ms** (ตอบเป็น HTTP 400 + `errorCode 429`) → 15 request =
   อย่างน้อย 4.5 วินาทีต่อบัญชี ต่อให้เน็ตเร็วเป็นศูนย์ ซึ่งแปลว่าการลด request ต่ำกว่านี้
   ให้ผลน้อยลงเรื่อย ๆ — ต่ำกว่า ~10 request ไม่คุ้มกับความเสี่ยงที่จะเก็บของไม่ครบ
3. **guest mint = 2 call/IP/นาที** → GenID ผูกกับจำนวน proxy ล้วน ๆ 50 proxy = 100 บัญชี/นาที
   เป็นเพดานแข็ง ไม่เกี่ยวกับเธรด
4. **GIL** — งานเป็น I/O ล้วนจึงไม่ควรเป็นปัญหา แต่การ parse JSON ของ response ใหญ่
   (`/player/units/equip` คืน roster ทั้งก้อน) ทำงานใต้ GIL **ต้องวัดก่อนแก้** ถ้าพบว่าเป็น
   คอขวดจริง ทางออกคือกลับไป 2–4 engine process แบ่ง lane กัน ซึ่ง interface ของ
   `WorkQueue` เผื่อไว้แล้ว
5. **`botLineRanger.py` 8,726 บรรทัดเป็นก้อนเดียว** — ย้ายทีละ flow แล้วเทียบผลกับของเดิม
   ด้วยบัญชีจริงก่อนลบของเก่า ไม่ใช่ลบก่อนแล้วค่อยหวังว่าเหมือนเดิม

## 15. ข้อสมมติที่ตัดสินใจเอง

- "เอาระบบ adb เก่าออกทั้งหมด" ตีความว่ารวมถึง image matching / OCR / emulator management
  ทั้งหมด เพราะทั้งหมดมีอยู่เพื่อป้อน ADB และไม่มี play mode ไหนเรียกแล้ว
- `rewardpasses` ตั้งค่าเริ่มต้นเป็น 2 (เดิม 3 ตายตัว) ผู้ใช้ตั้งกลับเป็น 3 ได้ถ้าอยากได้
  พฤติกรรมเดิมทุกประการ
- `threadsperproxy` เริ่มที่ 64 ไม่ใช่ 108 ตามสูตร เพราะตัวเลขที่คำนวณคือจุดตั้งต้น
  ต้องวัดกับของจริงแล้วปรับ
- ยังไม่ทำ autoscale อัตโนมัติในรอบนี้ — เพิ่มทีหลังได้เมื่อมีตัวเลขจากรอบจริงพอจะปรับเทียบ
  (eFootball เสียเวลากับ planner ที่ปรับเทียบตอนคอขวดอยู่คนละที่)

## 16. จุดเริ่มต้นของงาน (เคลียร์แล้ว 2026-09-23)

ก่อนเริ่มมีสองอย่างที่บล็อกอยู่ ทั้งคู่จัดการเรียบร้อยแล้ว:

| | ปัญหา | ทำอะไรไป |
|---|---|---|
| 16.1 | งานค้าง 301 บรรทัดยังไม่คอมมิต ในไฟล์ที่การรื้อจะแตะทั้งหมด (`ranger_api_Quest`) | พักไว้ที่ branch `wip/quest-mode` คอมมิต `77688b2` |
| 16.2 | ไฟล์ 16 ไฟล์ไม่ถูก track โดย git เลย รวม `tools/rewards.py` `tools/gacha.py` (สองไฟล์ที่ข้อ 5 จะแก้โดยตรง) และ `bot/hwid.py` `bot/protection.py` (ที่ `build.bat` เรียกตอน pyarmor) | คอมมิต `b569399` พร้อมขยาย `.gitignore` คลุม build output / runtime state / binary ที่ bundle มา |

**จุดเริ่มต้น:** branch `feat/engine-rewrite` แตกจาก `master` ที่ `b569399` working tree สะอาด

**กฎระหว่างทำงาน**

- `git add` เฉพาะไฟล์ที่ task ระบุ **ห้าม `git add -A`** — `bot/output/` มี 19,769 ไฟล์
  และ `bot/input/` มี 24,279 ไฟล์ที่ถือ LF_AC จริง
- **คอมมิตก่อนรันอะไรที่อาจต้อง revert** โดยเฉพาะ task ที่ลบโค้ดเป็นพันบรรทัด
- ห้ามฆ่าโปรเซสด้วยชื่อ image (`taskkill /IM python.exe`) ฆ่าได้เฉพาะ pid ที่ตัวเองสร้าง
- **ห้ามแตะ `bot/input/` `bot/output/` `bot/backup/` ในเทสต์** ใช้ `tmp_path` เสมอ
  และเทสต์ต้อง monkeypatch ทุก path ระดับโมดูลที่เอื้อมถึง (eFootball เคยเขียนทับไฟล์
  เครดิทเชียล 2,430 ไฟล์เพราะเทสต์โหลดโมดูลจริงผ่านตัวแปร path ที่ลืม patch)
