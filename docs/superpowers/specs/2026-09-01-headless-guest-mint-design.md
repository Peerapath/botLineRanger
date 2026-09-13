# Headless Guest Mint — สร้าง guest แบบไม่ง้อแอป เพื่อสุ่มกาชาให้เร็วขึ้น

วันที่: 2026-09-01
สถานะ: design (รออนุมัติก่อนเขียน implementation plan)

---

## 1. เป้าหมาย และจุดที่ทำให้ปัญหาเล็กลง

สร้าง LINE Rangers guest account **จาก Python ล้วน** — ไม่ต้องเปิด emulator ไม่ต้องมีแอปในลูป —
เพื่อให้ขั้นตอน "สร้างบัญชี" เลิกเป็นคอขวดของการสุ่มกาชา (reroll)

**ข้อค้นพบสำคัญที่ตัด scope ทิ้งไปครึ่งหนึ่ง:** ไม่ต้องถึง level 3 สำหรับงานนี้
บัญชี guest level 1 ที่เพิ่งสร้าง (`70a1ae86`) รับตั๋วกาชาฟรี 5 ใบจาก gift box แล้วสุ่มได้จริงตั้งแต่ level 1
ดังนั้นลูป reroll ต้องการแค่ *บัญชี level 1 ที่ล๊อกอินเข้าเกมสำเร็จ* เท่านั้น — ไม่ต้องเล่นด่าน ไม่ต้องผ่านบทสอน
ไม่ต้องแตะ gameplay call ที่ pinned เลย ปัญหายากทั้งก้อนนั้นหลุด scope ไป

เหลือกำแพงเดียวสำหรับงานหลัก: **rangers `/login` ของ guest ที่เพิ่งเกิด** ซึ่ง native client เซ็นด้วย header
`X-LINEGAME-APPSECRET` แกะตัวนี้ออกได้ = headless สำเร็จ

ผู้ใช้ขอเพิ่ม: ถ้าปั๊มถึง level 3 แบบ headless ได้จะดีมาก (ไม่บังคับ) -> ทำเป็น Phase 2 stretch ในข้อ 7
เพราะตอนนี้มี Frida ที่ใช้งานได้บนมือถือ root ไม้ตายเดียวกับที่แกะ login (hook SSL_write) จึงใช้ดัก
`/stage/save` ได้ด้วย แต่เสี่ยงกว่ามาก (อาจโดน server-authoritative ปฏิเสธ) จึงห้ามให้มาบล็อกงานหลัก

## 2. มีอะไรแล้ว vs ขาดอะไร

```
Trident mint chain (new_account.py)      OK  ทำ offline ได้ (cracked HMAC signature)
  check -> authentication(terms) -> refresh -> authorize -> userKey/cc/udid
rangers GET /login  (fresh guest)        XX  401 — ต้องมี X-LINEGAME-APPSECRET  <- จุดที่ต้องแกะ
rewards claim_all / gacha roll / XML     OK  headless ได้ (เพิ่งสร้าง+เทสต์เสร็จ)
```

ที่ทราบจาก RE รอบก่อน (memory `headless-account-creation-lgrgs`):
- native rangers login builder อยู่ที่ ~0x1256638 ใน `libgame.so`; format string ของ cookie
  `Cookie: <name>=<token>; udid=<udid>;` อยู่ที่ ~0x6be6e2
- ส่ง header: `X-LINEGAME-APPID / APPSECRET / USERKEY / MCC / MNC / TIMESTAMP`
- `appSecret` ตั้งผ่าน Java `setAppSecret` ใน classes5.dex อ่านจาก object member ตอน runtime
- login เป็น native libcurl แบบ pinned + dial IP ตรง — proxy มองไม่เห็น (จับด้วย mitmproxy ไม่ได้)

**ข้อควรระวังเรื่องข้อสรุปเก่า:** memory สรุปแบบ "น่าจะ" ว่า appSecret เป็นค่า dynamic หลัง JNI
ข้อสรุปนี้ทำภายใต้เวลาจำกัด จะ **ไม่เชื่อทันที** — การ hook สดครั้งเดียวจะฟันธงได้ว่าจริงหรือไม่

## 3. วิธีแกะ — Frida-first บนมือถือจริง (root arm64)

จับครั้งเดียว หลังจากนั้นเป็น Python ล้วนตลอดไป:

1. **Hook `SSL_write` ใน BoringSSL** (ไม้ตาย เชื่อถือได้สุด): dump request `/login` เป็น plaintext
   *ก่อน* ถูก TLS เข้ารหัส จับ native call ที่ pinned ได้ไม่ว่ามันถูกประกอบมายังไง และไม่ต้องรู้ชื่อ Java class
   - fallback: hook `curl_easy_setopt` (option == CURLOPT_HTTPHEADER แล้วเดิน curl_slist พิมพ์ทุก header),
     หรือ hook Java `setAppSecret` (หาตำแหน่งด้วย jadx ก่อน)
2. สร้าง guest ใหม่ **2 ตัว** ผ่าน UI ตามสูตรที่ใช้ได้ (WARP + guest login + terms) จับ request `/login` ทั้งสอง
3. **diff ค่า `appSecret` ของสองตัว:**
   - เหมือนกันทั้งข้ามบัญชีและข้ามเวลา -> เป็น **ค่าคงที่ต่อ app version** -> hardcode -> จบ
   - ต่างกัน -> จับ input ของมัน (appId, timestamp, userKey, udid, device props) แล้ว static-trace
     หา derivation ใน dex/`libtrident.so`; น่าจะใช้ HMAC primitive ตัวเดียวกับที่แกะไว้แล้ว
     (`linegame-trident-auth-signature`)

จับ **ทุก header** ของ `/login` ไม่ใช่แค่ appSecret เพราะอาจมี field/signature อื่นที่ยังไม่ได้ reproduce

## 4. การต่อเข้าโค้ดเดิม (architecture)

- `tools/frida/dump_login.js` — สคริปต์ hook (ใหม่)
- runbook สั้น ๆ สำหรับขั้นตอนจับค่าบนมือถือครั้งเดียว
- `tools/new_account.py` — เพิ่มขั้น `rangers_login()` ต่อจาก `authorize()` ที่ประกอบ header
  `X-LINEGAME-*` (+ appSecret ที่ reconstruct มา) แล้วคืน `LF_AC`; อัป `SDK_VERSION`/`APP_VERSION`
  ให้ตรงกับ client ที่ติดตั้ง (**12.3.0**)
- `tools/reroll.py` — batch driver บาง ๆ: mint -> `rewards.claim_all` -> `gacha` สุ่ม 1 ครั้ง ->
  export XML + เขียนต่อท้าย `genid-sessions.csv` (ใช้รูปแบบ logSession เดิม) + throttle ระหว่าง mint
- `bot/botLineRanger.py::genIDLevel1` **ไม่แตะ** เก็บไว้เป็น hybrid fallback

## 5. การพิสูจน์ผล (วัด state จริง ห้ามเชื่อ HTTP 200)

- mint guest headless 1 ตัว -> assert `/home` คืน level 1 / ruby 20
- claim -> assert ตั๋ว 5 -> 0 และได้ยูนิตกลับมา 1 ตัว
- export XML แล้วโหลดกลับเข้าแอป **1 ครั้ง** ยืนยันว่าเป็นบัญชีจริงที่กู้คืนได้
- เทียบกับบัญชีที่สร้างจาก UI ว่า parity ตรงกัน

## 6. ความปลอดภัย

- `appSecret`, `LF_AC`, `userToken`, `refreshUserToken` ล้วน authenticate บัญชีจริงของผู้ใช้ ->
  เก็บใน scratch ที่ gitignore เท่านั้น ส่งไปที่ **เซิร์ฟเวอร์ของเกมเท่านั้น** ห้ามส่งที่อื่น
- throttle การ mint (memory: สร้าง guest รัว ~10 ตัวโดน abuse flag)
- anti-cheat telemetry อาจ log emulator+root แต่เรา replay ด้วย token ของผู้ใช้เอง —
  จะแจ้งตรง ๆ ถ้ามีอะไรเปลี่ยน
- งาน grep dex ซ้ำ ๆ ตอน static fallback -> delegate ให้ qwen

## 7. โครงสร้างเป็น 2 phase

**Phase 1 (งานหลัก, มั่นใจสูง) — headless mint + reroll ที่ level 1**
คือทุกอย่างในข้อ 1-6 ส่งมอบได้ครบด้วยตัวเอง ไม่ต้องรอ Phase 2

**Phase 2 (stretch, เสี่ยง/ไม่แน่นอน) — ปั๊มเลเวลถึง 3 แบบ headless**
เงื่อนไข: ต้องทำ Phase 1 เสร็จก่อน (รู้วิธี sign request ของ rangers แล้ว)
- Frida capture: hook `SSL_write` เล่น Valley-of-Wind ด่าน 1 (st01) ผ่านแอปให้ชนะ 1 รอบ
  dump ทั้ง sequence: `/stage/enter/{id}`, การรบ, และ `/stage/save/{}/{}` (path + body + header/signature เต็ม)
  จับ response ด้วย (exp ที่ได้, level up)
- Static: grep `libgame.so` หา route ของ stage-save + ชื่อ field (ห้ามเดา — กฎข้อ 1 ของ skill) ยืนยัน schema ของ body
- Replay จาก Python บน guest **ทิ้ง**: ส่ง stage-save ที่จับมา (ปรับ timestamp/signature)
  วัดผล: exp เพิ่มไหม? level 1->2 ไหม? replay ซ้ำ -> 2->3 (memory: st01 clear ~ +400 exp)
- ประตูความเสี่ยง: ถ้าเซิร์ฟเวอร์ปฏิเสธ (ผลรบคำนวณฝั่ง server) หรือบัญชีโดน flag -> **หยุด** บันทึกไว้
  แล้ว level 3 กลับไปใช้ hybrid (`genIDLevel1` เล่น 2 ด่าน ซึ่งเร็วอยู่แล้ว)
- Safety: stage-save เป็น mutation ที่ dry-run ไม่ได้ -> ทดสอบบน guest ทิ้งที่ยอมเสียได้เท่านั้น
  ห้ามแตะบัญชีเก็บ, throttle
- Integration: `reroll.py` เพิ่ม `--level 3` (optional) หลัง login จะ replay stage-save N ครั้งก่อน claim
  ถ้า Phase 2 ล้ม -> `--level 3` แจ้งว่า headless ไม่รองรับ แล้วผู้ใช้ใช้ `genIDLevel1` แทน

## 8. ความเสี่ยง / จุดที่อาจล้ม

- appSecret อาจเป็น device-attestation จริง ๆ ที่ผูกกับ device — reproduce ยากกว่าค่าคงที่
- 401 ของ fresh guest อาจมีสาเหตุร่วม (rate-limit / device gate) ไม่ใช่แค่ appSecret — การ hook สดจะเห็นชัด
- anti-tamper ชั้นสองอาจตอบโต้ Frida — บนมือถือจริงเสถียรกว่า MuMu แต่ยังเป็นความเสี่ยง
- APK ที่ pull มาต้องเป็น split arm64 (base.apk + split_config.arm64_v8a.apk) ให้ได้ `.so` ที่ถูก ABI
