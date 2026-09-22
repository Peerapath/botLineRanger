# ดัก API ของเกมบน MuMu Player ด้วย mitmproxy

โปรเจคนี้ตั้งค่าให้ mitmproxy อ่าน HTTPS traffic ของ `com.linecorp.LGRGS`
ที่รันอยู่บน MuMu Player แล้วบันทึกทุก request/response ลงไฟล์ที่อ่านย้อนหลังได้

## สภาพแวดล้อมที่ตรวจสอบแล้ว

ค่าพวกนี้ถูกทดสอบจริงตอนเซ็ตอัพ และถูกใส่ไว้ใน `config.ps1` แล้ว

| อย่าง | ค่า |
| --- | --- |
| MuMu Player | `D:\Program Files\Netease\MuMuPlayer` (Global 12) |
| adb | `nx_main\adb.exe` (สคริปต์หา instance ที่รันอยู่เอง) |
| device | `127.0.0.1:16416` — Android 12 (SDK 32), x86_64, root ใช้ได้ |
| mitmproxy | 12.2.2 |
| proxy | emulator มองเห็นเครื่องคุณเป็น `10.0.2.2:8080` |
| CA certificate | ติดตั้งลง `/system/etc/security/cacerts/c8750f0d.0` แล้ว |

ทดสอบแล้วว่า `curl https://example.com` ผ่าน proxy จากใน emulator ได้ **200**
แปลว่า Android เชื่อถือ certificate ของ mitmproxy ในระดับระบบเรียบร้อย

## เริ่มใช้งาน

```powershell
cd d:\Programing\ranger\Test-Mitmproxy-Api
.\scripts\capture.ps1
```

สคริปต์เดียวจบ: เช็ค certificate → ตั้ง proxy ให้ emulator → เปิด mitmproxy
ในหน้าต่างใหม่ → รีสตาร์ทเกม จากนั้นเล่นเกมส่วนที่อยากดู แล้วดู traffic ได้ที่
mitmweb UI <http://127.0.0.1:8081> หรือในไฟล์ transcript

> **สำคัญ:** ตอนนี้คุณมี mitmproxy เปิดค้างอยู่แล้วบนพอร์ต 8080 ตัวนั้น
> **ไม่มี addon ติดอยู่** จึงไม่บันทึกอะไรลงไฟล์ ปิดตัวเก่าก่อน หรือสั่ง
> `.\scripts\capture.ps1 -Force` เพื่อให้หยุดตัวเก่าให้อัตโนมัติ

พอเล่นเสร็จ อย่าลืมคืนค่า ไม่งั้น emulator จะเน็ตไม่ติดเพราะยังชี้ไป proxy ที่ปิดไปแล้ว

```powershell
.\scripts\stop-capture.ps1 -StopProxy
```

## จับ traffic ที่ไม่ผ่าน proxy

การตั้ง `http_proxy` มีผลเฉพาะแอปที่ใช้ HTTP stack ของ Android เท่านั้น
โค้ด native ของเกมไม่สนใจค่านี้ และต่อตรงออกไปเอง จึงต้อง redirect ที่ระดับ
network แทน ปลายทางที่เจอจากการวิเคราะห์จริงถูกใส่ไว้ใน `$NativeTargets`
ใน `config.ps1` แล้ว

| ปลายทาง | พอร์ตในเครื่อง | หมายเหตุ |
| --- | --- | --- |
| `147.92.243.243:443` (`rangers-api.line-apps.com`) | 9443 | HTTPS ปกติ ถอดรหัสได้ |
| `147.92.240.68:15508` | 9508 | TLS เวอร์ชันเก่ากว่า TLS 1.2 ต้องตั้ง `tls_version_client_min=UNBOUNDED` |

```powershell
.\scripts\start-reverse.ps1        # เปิด listener ทั้งสองตัว ตัวละหน้าต่าง
.\scripts\redirect-native.ps1      # ใส่กฎ iptables DNAT ใน emulator
.\scripts\launch-game.ps1          # รีสตาร์ทเกมให้ต่อใหม่ผ่านเส้นทางนี้
```

ลำดับสำคัญ ต้องเปิด listener ก่อนใส่กฎ iptables เสมอ ไม่งั้นเกมจะติดต่อ
เซิร์ฟเวอร์ไม่ได้เลย ตรวจสถานะกฎด้วย `.\scripts\redirect-native.ps1 -Show`
และถอนด้วย `-Remove` (`stop-capture.ps1` ถอนให้อัตโนมัติอยู่แล้ว)

listener แต่ละตัวเขียนไฟล์ของตัวเอง ชื่อไฟล์ลงท้ายด้วย pid เพื่อไม่ให้ชนกัน

## ดูผลลัพธ์

ทุก request ถูกเขียนลง `captures\api-<เวลา>.jsonl` บรรทัดละ 1 request
พร้อม header และ body เต็ม (body ที่เป็น binary เก็บเป็น base64)

```powershell
python tools\summarize.py                    # สรุป endpoint ทั้งหมดจากไฟล์ล่าสุด
python tools\summarize.py --host lgrgs       # เฉพาะ host ที่ชื่อมี lgrgs
python tools\summarize.py --show /api/user   # ดู body เต็มของ path ที่สนใจ
```

`summarize.py` จะยุบ path ที่เป็น id/uuid/hex ให้เป็น `{id}` `{uuid}` `{hex}`
เพื่อให้ endpoint เดียวกันที่ถูกเรียกหลายรอบรวมเป็นบรรทัดเดียว

ไฟล์ `captures\flows-<เวลา>.mitm` เป็นฟอร์แมตของ mitmproxy เอง เปิดซ้ำหรือ
replay ได้ด้วย `mitmproxy -r captures\flows-<เวลา>.mitm`

## สคริปต์แต่ละตัว

| สคริปต์ | หน้าที่ |
| --- | --- |
| `scripts\status.ps1` | เช็คทุกจุดในเส้นทางว่าพังตรงไหน — รันได้ตลอด ไม่แก้อะไร |
| `scripts\capture.ps1` | ทำครบทุกขั้นในคำสั่งเดียว |
| `scripts\install-cert.ps1` | ติดตั้ง CA ลง system trust store (ต้อง root) |
| `scripts\remove-cert.ps1` | ถอน CA ออก |
| `scripts\set-proxy.ps1` | ชี้ proxy ของ emulator ไปที่ `10.0.2.2:8080` |
| `scripts\clear-proxy.ps1` | ล้างค่า proxy |
| `scripts\start-proxy.ps1` | เปิด mitmproxy พร้อม addon (รันค้างใน terminal) |
| `scripts\launch-game.ps1` | force-stop แล้วเปิดเกมใหม่ |
| `scripts\stop-capture.ps1` | ล้าง proxy + ปิดเกม (`-StopProxy` ปิด mitmproxy ด้วย) |

`start-proxy.ps1` มี option ที่ใช้บ่อย

```powershell
.\scripts\start-proxy.ps1 -Dump              # แสดงผลใน console อย่างเดียว ไม่เปิด UI
.\scripts\start-proxy.ps1 -Focus lgrgs       # console แสดงเฉพาะ host ที่ตรง
.\scripts\start-proxy.ps1 -Force             # หยุดโปรเซสที่ยึดพอร์ต 8080 อยู่
```

ตัวกรองมีผลกับ console เท่านั้น ไฟล์ `.jsonl` เก็บทุกอย่างเสมอ ดังนั้นถ้ากรอง
ผิดไปก็ไม่มีข้อมูลหาย

## เมื่อไม่เห็น traffic ของเกม

**เกมทำ certificate pinning** — เป็นสาเหตุที่พบบ่อยที่สุด addon จะเตือนว่า
`[tls] handshake failed with <host>` และสรุป host ที่ล้มเหลวให้ตอนปิดโปรแกรม
ถ้าเห็นข้อความนี้ แปลว่า certificate ติดตั้งถูกแล้วแต่ตัวเกมปฏิเสธเอง
การแก้ต้องใช้ Frida hook ฝั่งเกม ซึ่งอยู่นอกขอบเขตของโปรเจคนี้

**เกมไม่ได้ใช้ HTTP** — ถ้าคุยผ่าน TCP socket ดิบ proxy แบบ HTTP จะไม่เห็น
ต้องเปลี่ยนไปใช้ transparent mode

**MuMu รีเซ็ต `/system`** — ถ้า restart instance แล้ว certificate หาย
ให้รัน `install-cert.ps1` ใหม่ `status.ps1` จะบอกให้เองถ้าเกิดขึ้น

**เกมยังไม่ได้รีสตาร์ท** — Android อ่าน trust store ตอนโปรเซสเริ่ม
`launch-game.ps1` จึง force-stop ก่อนเปิดเสมอ

## ข้อควรระวัง

ไฟล์ใน `captures\` มี access token, session id และข้อมูลบัญชีของคุณอยู่จริง
`.gitignore` กันไว้ให้แล้ว อย่าแชร์ไฟล์พวกนี้ตรง ๆ

## คลัง Rangers ที่คุณมี (ผลลัพธ์จริง)

**API เส้นที่ให้ข้อมูลคลัง:**

```
GET https://rangers-api.line-apps.com/v12.3/player/units/equip?inven=true&team=true&deck=true
Cookie: LF_AC=<session token>
UID:    <session uid>
```

ยืนยันจาก `libgame.so` (เรียกโดย `UnitManager::requestPlayerUnit()`) response เป็น JSON
`result.playerUnits[]` — ตัวละครที่เป็นเจ้าของทั้งหมด แต่ละตัวมี `invenId`, `unitCode`
(เช่น `u32-brown`), `unitLevel`, `playerUnitMaxLevel`, `talentGrade`, `equipMap`

ผลที่ดึงได้: **377 ตัว** (ตรงกับ 377/700 บนหน้า TEAM) เก็บไว้ที่ `roster/`

### ทำไมต้อง replay เอง แทนที่จะดักผ่าน proxy

game API ทำ **certificate pinning ใน native code** (libcurl `CURLOPT_PINNEDPUBLICKEY`,
มี hash ฝังใน libgame.so + error `SSL: public key does not match pinned public key!`)
mitmproxy จึงถอดไม่ได้ — pinning ไม่สนใจว่า CA จะ trust หรือไม่

แต่ pinning เป็นการที่ **client ตรวจ server** ถ้าเราเป็น client เองต่อตรงไปเซิร์ฟเวอร์จริง
ไม่มี MITM ก็ไม่มี pinning มาขวาง เราแค่ต้องมี session token (`LF_AC` + `UID`) ที่เกม
ส่งตอน bootstrap ซึ่ง bootstrap calls (`login/platform`, `nation.nhn`) ใช้ Android HTTP
stack ผ่าน proxy ปกติ จึงดักเก็บ token ได้

### ดึงคลังซ้ำ

token อายุสั้น (~1 ชม.) ขั้นตอน:

```powershell
.\scripts\start-proxy.ps1 -Dump          # 1) เปิด proxy
# 2) เปิด/รีสตาร์ทเกม ให้มัน authenticate ผ่าน proxy หนึ่งรอบ
python tools\pull_roster.py               # 3) ดึง token ล่าสุดอัตโนมัติแล้วดึงคลัง
```

ได้ไฟล์ `roster\rangers_roster-<เวลา>.csv` (เปิดใน Excel ได้) และ raw JSON

> ชื่อที่แสดงเป็นชื่อภายใน (`leonard`, `sally`, `brown`, `cony`, `moon`...) ซึ่งก็คือ
> ตัวละคร LINE ชื่อเต็มสวย ๆ อยู่ใน `unit.db` ที่เข้ารหัสด้วย SQLCipher (ยังไม่ถอด)

## กาชา (ทรัพยากร + สุ่ม)

ใช้กลไก replay เดียวกับการดึงคลัง (ต้องมี token สดจาก proxy ก่อน) เครื่องมือ:
[tools/gacha.py](tools/gacha.py)

```powershell
python tools\gacha.py resources    # ruby + จำนวน gacha ticket ของ account ปัจจุบัน
python tools\gacha.py list         # banner ทั้งหมด + ราคา (idx1=50ruby/5tkt, idx2=300ruby)
```

**API เช็คทรัพยากร**
- ruby: `GET /v12.3/player/units/equip?...` → `result.rubyBalance.total`
- ticket: `GET /v12.3/player/item?pGacha=true&etGacha=true&...`
  → `result.premiumGachaTicketItems[].amount` (ni-06 = gacha ticket), `eventGachaTicketItems[].amount` (ni-16)
  (`amount` = freeAmount+paidAmount — **ห้ามอ่าน `rewardAmount`** เพราะเป็นขนาดต่อการได้รับ ไม่ใช่จำนวนที่ถือครอง)

**API สุ่ม** — 2 จังหวะ reserve → confirm ต่อ 1 banner (`groupId`) มี 2 แบบ:
- `gachaIndex 1` = สุ่ม 1 ครั้ง จ่ายได้ **50 ruby หรือ 5 ticket**
- `gachaIndex 2` = สุ่ม 6+1 = 7 ครั้ง จ่าย **300 ruby**

```
POST /v12.3/gacha/group/reserve   {"groupId","gachaIndex","useTicket":false}
    -> {"result":{"reserveSeq":..,"status":"reserved",..}}   # จองเฉย ๆ ยังไม่หัก
POST /v12.3/gacha/group/confirm   {"groupId","gachaIndex","reserveSeq","useTicket":true|false}
    -> ผลสุ่ม + หักทรัพยากร                                  # จังหวะนี้เท่านั้นที่หักจริง
```

**`useTicket` คือตัวเลือกวิธีจ่าย** (`true` = 5 ticket, `false` = ruby) — ยืนยันด้วยการยิงจริงแล้ว

> ⚠️ **อย่าใช้ `gachaPlayType`** ถึงจะมีชื่อฟิลด์นี้ในแคตตาล็อก แต่ส่งไปใน confirm แล้ว
> เซิร์ฟเวอร์**ไม่สนใจ** และหัก ruby เงียบ ๆ แทน (บทเรียนจากการทดสอบ: ส่ง
> `gachaPlayType:"TICKET"` แล้วโดนหัก 50 ruby ส่วนตั๋วไม่ลด)
> แคตตาล็อกมี `gachaPlayType` แค่ `RUBY`/`FRDSH` ไม่มีค่า TICKET อยู่แล้ว

```powershell
# DRY RUN (reserve อย่างเดียว ไม่หักอะไร) — ดูว่าจะสุ่ม banner ไหน
python tools\gacha.py roll grp_gacha_6 1 RUBY

# ยิงจริง (หักทรัพยากร) — ต้องใส่ --confirm เอง
python tools\gacha.py roll grp_gacha_6 1 RUBY --confirm      # 50 ruby, สุ่ม 1
python tools\gacha.py roll grp_gacha_6 1 TICKET --confirm    # 5 ticket, สุ่ม 1
python tools\gacha.py roll grp_gacha_6 2 RUBY --confirm      # 300 ruby, สุ่ม 7
```

ผลสุ่มบันทึกที่ `roster\gacha-result-<เวลา>.json` ดูรายชื่อ banner ทั้งหมดด้วย `gacha.py list`

> **reserve ปลอดภัย** (ทดสอบแล้ว ruby ไม่ลด) — ใบจองที่ไม่ confirm จะหมดอายุเอง
> **confirm หักจริงย้อนไม่ได้** เครื่องมือจึงบังคับ `--confirm` และ default เป็น dry run

---

## สร้าง / ควบคุมบัญชีแบบ headless (ไม่ต้องดัก proxy)

งานนี้แยกเป็น 2 ส่วน — ส่วนที่ทำ headless แท้ได้แล้ว กับส่วนที่ยังต้องพึ่งแอป 1 ครั้ง

### 1) mint บัญชี LINE ใหม่ (headless แท้) — `tools/new_account.py`

chain สมัคร guest ของ LINE Game "Trident" SDK **ไม่ถูก pin** และ sign เองได้ทั้งหมด
ลายเซ็น `X-Linegame-Authorization` ถอดจาก `libtrident.so` แล้ว:

```
si  = urlencode( base64( HMAC-SHA256(key, body) ) )
key = urlencode("trident&" + appId + "&" + ts)  ==  "trident%26LGRGS%26<ts>"
ts  = str(int(time.time())) + "000"          # วินาที → มิลลิวินาที
body = ตัว msgpack ของ request (GET/ว่าง = body ว่าง)
```

```powershell
python tools\new_account.py            # สร้าง 1 บัญชี
python tools\new_account.py --count 5  # สร้าง 5 บัญชี
```

ได้ `userKey` (= GAME_ID `T0FF…`), `userToken`, `refreshUserToken` เก็บไว้ที่
`roster\accounts\account-*.json` — **deviceId สุ่ม 32 hex 1 ตัว = 1 บัญชีใหม่**

> ⚠️ **ข้อจำกัด:** first-login ฝั่งเกม (rangers) ของบัญชี "เกิดใหม่" เป็น native call
> ที่ **pin + ส่ง `X-LINEGAME-APPSECRET`** (ค่า runtime จาก SDK ข้าม JNI) ยัง reproduce
> นอกเครื่องไม่ได้ → บัญชีที่ mint ด้วย script ยัง login เข้าเกมเองไม่ได้ (คืน 401)
> ต้องให้แอปทำ first-login ให้ (ดูข้อ 2). จะปิด gap นี้ได้ต้อง hook native login
> 1 ครั้งบน **มือถือ arm64 root จริง** (Frida พังใต้ ARM-translation ของ MuMu)

### 2) ดึง session จากเครื่องที่ล็อกอินอยู่ (hybrid) — `tools/device_session.py`

พอ **แอป** ล็อกอินบัญชีไว้แล้ว (guest หรือผูก provider) เกมเก็บ token `LF_AC` ไว้บนเครื่อง
แบบเข้ารหัส AES เราถอดออกมาแล้วยิง API ได้เลย **ไม่ต้องใช้ proxy / ไม่ต้อง capture**

```powershell
$env:ADB = "D:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe"   # ถ้า auto หาไม่เจอ
python tools\device_session.py --device 127.0.0.1:16480 --save
```

วิธีถอด (จาก `SimpleCrypto.decrypt2` ใน dex): อ่าน `shared_prefs/_LINE_COCOS_PREF_KEY.xml`
ผ่าน `adb … su -c cat` แล้ว
`LF_AC = AES/CBC/PKCS5-decrypt( key=base64(_DEVICE_UUID_KEY), IV+ct=base64(_ENC_LF_AC_KEY) )`
(server ผูกผู้เล่นจาก LF_AC เอง — **ไม่ต้องส่ง header UID**)

จากนั้น tools อื่นรับ `--from-device` ได้เลย:

```powershell
python tools\pull_roster.py  --from-device --device 127.0.0.1:16480   # ดูคลัง rangers
python tools\gacha.py        --from-device resources                  # เช็ค ruby/ticket
python tools\gacha.py        --from-device list                       # ดูตู้กาชา
python tools\gacha.py        --from-device roll grp_gacha_6 1 TICKET --confirm
```

### สรุปโมเดลที่ใช้งานได้ตอนนี้

| ขั้นตอน | ใคร/อย่างไร |
| --- | --- |
| สร้างบัญชี LINE (guest) | `new_account.py` headless ได้ **หรือ** แอป |
| first-login เข้าเกม (ลงทะเบียน profile) | **แอป** (native pinned — ยังต้องพึ่งแอป) |
| ดึง `LF_AC` มาคุม | `device_session.py` (ถอดจากเครื่อง) |
| คลัง / กาชา / ทรัพยากร | headless ผ่าน API (`--from-device`) |
| รับ gift / tutorial / export | headless ผ่าน API — `gifts.py`, `tutorial.py`, `export_account.py` |

### 3) รับ gift / ทำ tutorial / export (headless) — ทดสอบสดแล้ว

ทุก tool รับ session ได้ 3 ทาง: `--cookie "LF_AC=..."`, `--from-device [--device]`
(ถอดจากเครื่อง root — guest), หรือ auto จาก capture ล่าสุด (ต้องมาก่อน subcommand)

```powershell
# รับของขวัญ (login bonus / event) — default dry run, ต้อง --confirm ถึงจะรับจริง
python tools\gifts.py --from-device list
python tools\gifts.py --from-device claim --confirm     # POST /giftbox/gift/receive/all

# ทำ tutorial ให้ผ่าน (บัญชีเกิดใหม่) — GET /tutorial/confirm/<STEP> idempotent
python tools\tutorial.py --from-device                  # dry run: ดูรายการ step
python tools\tutorial.py --from-device --confirm        # ยิงครบทุก step

# export ตัวตนบัญชี + snapshot (GAME_ID=rsn, mid, uid, ruby, tickets, จำนวน rangers)
python tools\export_account.py --from-device
python tools\export_account.py --cookie "LF_AC=..." --guest-file roster\accounts\account-*.json
```

> **โน้ต:** `device_session.py` (ถอด LF_AC จากดิสก์) ใช้ได้กับบัญชี **GUEST** เท่านั้น
> (guest เก็บ LF_AC เข้ารหัสไว้ในเครื่อง) บัญชี **GOOGLE/Apple** ไม่เก็บบนดิสก์ —
> ต้องดึง LF_AC ผ่าน proxy capture (`/v12.3/login/platform` → `Set-Cookie: LF_AC`)
> แล้วส่งให้ tool ด้วย `--cookie`. และถ้ามี **Cloudflare WARP (tun0)** เปิดอยู่ ต้องปิดก่อน
> capture ไม่งั้น traffic ไม่ผ่าน proxy

### 4) ดันด่าน main stage แบบ headless (ไม่ต้องเล่นจริง) — `tools/stage_forge.py`

ปลอม `/stage/save` ได้ครบแล้ว (ทดสอบสด 2026-09-19: guest ใหม่เคลียร์ st01→st151 รวดเดียว
level 1→86, heart ไม่เคยหมดเพราะเลเวลอัปเติมให้) ต้อง skip tutorial ก่อน (`new_account.py` ทำให้เอง)

```powershell
python tools\stage_forge.py --acct roster\accounts\account-T0FF....json            # dry run
python tools\stage_forge.py --acct roster\accounts\account-T0FF....json --confirm  # ต่อจากด่านล่าสุดถึง st150
python tools\stage_forge.py --xml bot\input\40d2cf61.xml --to 80 --confirm
```

ต่อ 1 ด่าน: `POST /stage/enter/{stc}` → ได้ `battleSn` + `rsaKeyBase` → ส่ง battleLog ต้นแบบ (log ชนะจริง
ของ st02 ใช้ซ้ำได้ทุกด่าน) + `stc`, `pt=1`, `atw`, `sn_e`/`win_e` (RSA ไม่มี padding ด้วยคีย์ของ enter นั้น),
`icu` = AES-128-CBC(key=HM16(HM16(rsn)+HM16(battleSn)), HM16(modulus)) โดย HM16 = md5 hex ตัวใหญ่ 16 ตัวแรก
→ รออย่างน้อย `pt` วินาทีหลัง enter → `POST /stage/save/{battleSn}/{stc}` (JSON compact เรียง key)

- **icu คือตัวที่เซิร์ฟเวอร์ตรวจจริง** ผิด/ไม่ส่ง = แพ้เงียบ ๆ (200, rewardExp 0, เสีย heart)
- `i_e` ต้องไม่ส่ง หรือเป็น RSA("[]"); `atw` จะไม่ส่งก็ได้ แต่ถ้าส่งต้อง ≥ HP ป้อมศัตรู
- save เร็วกว่า `pt` หรือ `atw` ต่ำกว่า HP ป้อม → 400/102205 (battle ยังเปิดอยู่ ไม่เสีย heart ยิงซ้ำได้)
- เซิร์ฟเวอร์มี rate limit 2 ชั้น (วัด 2026-09-22): ต่อไอดีห้ามยิงซ้ำภายใน ~300 ms หลังคำตอบก่อนหน้า
  (ตอบ HTTP 400 + `errorCode 429`) และต่อ IP ~100 req/s (nginx ตอบ HTTP 429) — `tools/ratelimit.py`
  คุมให้ทั้งสองชั้นแล้ว (pacer 350 ms ต่อไอดี + token bucket 80 req/s ต่อ IP ใช้ร่วมกันทุก worker)
  `--delay` จึงเป็นแค่จังหวะพักต่อไอดี ตั้ง `--delay 0` ได้ปลอดภัย
- exit code: 0 ครบ, 2 ด่านถัดไปล็อก, 3 heart หมด, 4 token ตาย (relogin), 5 โดนตีธง 102204, 6 อื่น ๆ
- เซิร์ฟเวอร์บันทึก `pt` เป็นเวลาเคลียร์ (firstClearSec) — `pt=1` = เคลียร์ 1 วินาทีติดประวัติ

โหมดในบอท (GUI): **🎯 Stage** (`ranger_api_Stage`) = headless thread-mode ตัวที่ 3 ต่อจาก Login/GenID —
แต่ละ thread หยิบ .xml จาก `input/` (แบ่งด้วย split-ID เหมือน Login) → relogin → ดันด่านถึงเลขใน
ช่อง "เล่นถึงด่าน" (เซฟเป็น `settings.stageend`) → ส่งออก `output/` พร้อม Lv ใหม่ในชื่อไฟล์
(ไอดีที่โดนตีธง 102204 จะถูกย้ายไป `login failed/` แทน) โหมดจะโผล่ใน dropdown ก็ต่อเมื่อ
license API คืน `ranger_api_Stage` มาใน `allowed_modes` (อีเมล whitelist = เห็นทุกโหมด)

### Rate limit (tools/ratelimit.py)

ทุก request ที่ผ่าน `rangers_api.call` และ `new_account._do` จะ (1) รอให้ห่างจากคำตอบก่อนหน้าของไอดีเดิม
≥ 350 ms (2) ขอตั๋วจาก token bucket ต่อ IP+host ที่ทุกโปรเซสในเครื่องใช้ร่วมกันผ่าน lock file
(3) ถ้าเจอ HTTP 429/503 หรือ HTTP 400 + `errorCode 429` จะ backoff แล้วยิงซ้ำเอง (สูงสุด `LGRGS_MAX_RETRY`)

| env | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `LGRGS_MIN_GAP_MS` | 350 | ช่วงห่างขั้นต่ำต่อไอดี |
| `LGRGS_RPS_BUDGET` | 80 | งบ req/s ต่อ IP (0 = ปิด bucket) |
| `LGRGS_RPS_BURST` | 20 | ความลึกของ bucket |
| `LGRGS_RL_DIR` | `%TEMP%/lgrgs-ratelimit` | โฟลเดอร์ lock file (บอทตั้งเป็นโฟลเดอร์ `.ratelimit` ข้างโปรแกรม: รากของ repo ตอนรันจากซอร์ส หรือข้าง exe ตอน build) |
| `LGRGS_PROXY` | ว่าง | `host:port[:user:pass]` ออกทาง proxy ตัวนี้ (bucket แยกต่อ proxy) |
| `LGRGS_MAX_RETRY` | 8 | จำนวนครั้งสูงสุดต่อ call (รวมครั้งแรก) ที่ rangers_api/new_account ยิงซ้ำเองเมื่อเจอ 429/503/app-429 — ตั้ง 1 เมื่อจะวัดพฤติกรรมดิบของเซิร์ฟเวอร์ |

บอท GUI อ่าน `config.ini [settings] apirps` และ `apiproxies` (คั่นด้วยจุลภาค แจกวนให้ worker ทีละตัว)
แล้วส่งเป็น env ให้ worker ทุกตัว ตรวจว่าตัวคุมทำงานด้วย
`python tools/ratelimit_probe.py --xml-dir bot/input --workers 150 --seconds 10` (ต้องได้ 0 ทั้ง 429 สองแบบ)
exit code 0 = ไม่มี 429 ทั้งสองแบบและไม่มี call ที่ throw, 1 = มี, 2 = ไม่มี token ใช้ได้/mint guest ไม่สำเร็จ
- ถ้ามี `bot/src/config.ini` อยู่แล้ว โปรแกรมไม่ merge คีย์ใหม่ให้ ต้องเติม `apirps` / `apiproxies` ใน `[settings]` เอง
  (ไม่เติมก็ใช้ค่าเริ่มต้น 80 / ต่อตรง)
- `tools/device_session.py::player_summary` และ `tools/pull_roster.py` ยิง `urlopen` ตรง ไม่ผ่านตัวคุมและไม่ใช้
  `LGRGS_PROXY` (ไม่อยู่ใน flow ของบอท ใช้เป็นเครื่องมือมือเท่านั้น)
