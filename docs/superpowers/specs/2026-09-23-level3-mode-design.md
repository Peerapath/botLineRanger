# โหมด Login Lv3 (`ranger_api_Level3`) และ GenID เลเวล 3

วันที่: 2026-09-23 (ทำต่อเนื่องคืนเดียวตามคำขอ ไม่ได้ผ่านรอบถาม-ตอบ ข้อสมมติระบุไว้ท้ายเอกสาร)

## เป้าหมาย

1. โหมดใหม่ `ranger_api_Level3`: ทำงานเหมือน Login ทุกอย่าง แต่ถ้าบัญชียังเลเวลไม่ถึง 3 ให้เล่น stage 1 ซ้ำ
   จนถึงเลเวล 3 ถ้าถึงอยู่แล้วให้ login เฉย ๆ
2. `ranger_api_GenID`: บัญชีที่ออกมาต้องเป็นเลเวล 3 ไม่เอาเลเวล 1

## ที่มา (วัดกับเซิร์ฟเวอร์จริง 2026-09-23, guest ใหม่ 2 บัญชี)

- `stage_forge.clear_stage(cookie, "st01", rsn)` ใช้กับบัญชีใหม่ได้ทันที (enter ปกติหรือ fallback tutorial route)
  ไม่ต้อง `skip_tutorial` (ลองทั้งข้ามและไม่ข้าม ผลเท่ากัน)
- st01 ให้ 600 exp ทุกรอบ (`isFirstComplete` true/false เท่ากัน): เลเวล 1 -> 2 หลังรอบแรก, -> 3 หลังรอบสอง
- เลเวลอัพเติม heart: 5 -> 9 -> 13 จึงไม่มีทาง heart หมดก่อนถึงเลเวล 3
- ใช้เวลา ~7 วิ/รอบ (pt 1 + delay 3) รวม ~15 วิ ต่อบัญชี

## การออกแบบ

- `tools/stage_forge.level_up(cookie, rsn, target_level, stc="st01", max_plays=10, ...) -> (level, plays, reason)`
  วน `clear_stage` ด่านเดิมจนเลเวล >= เป้า อ่านเลเวลจาก `battleResult.afterRewardPlayer.level`
  เหตุหยุดชุดเดียวกับ `clear_range` (hearts/auth/flagged/locked/failed) + `maxplays`; ถึงอยู่แล้ว = (level, 0, "done")
- `bot/botLineRanger.py`
  - `LEVELTARGET` จาก `config.ini [settings] leveltarget` (fallback 3)
  - `apiLevelUpByStage1(targetLevel=None)` -> `{"level","plays","stop"}` ใช้ `getLFAC()` + `stage_forge.level_up`
  - `startBotLevel3_API_headless`: โครง Login เดิม + ขั้นดันเลเวลหลัง relogin/เช็คบัญชีซ้ำ ก่อนรับของ/กาชา
    ไม่ถึงเป้าหรือ flagged -> ย้ายไป `login failed/` (status LOWLV/FLAG) ไม่ส่งออก output/
  - GenID: หลัง signup ดันเลเวลก่อนรับของ/กาชา ไม่ถึงเป้า -> ย้ายไฟล์ไป `login failed/` แล้ว raise ให้ attempt ถัดไป
    สร้างบัญชีใหม่ (คิวโควตา mint 2/นาที/IP ทำงานอยู่แล้ว)
- GUI/worker: `ALL_PLAY_MODE_OPTIONS["🎮 Login Lv3"]`, แผงตั้งค่าใช้ชุดเดียวกับ Login, `_isHeadlessThreadMode`,
  `run_bot`/`bot_worker` dispatch, label GenID เป็น "เลเวล3"

## ข้อสมมติที่ตัดสินใจเอง

- "เลเวลมากกว่า 3" ตีความเป็น "ถึงเลเวล 3" ตามประโยคท้าย ("ถ้าเลเวล 3 อยู่แล้วให้ login เฉย ๆ") เป้าตั้งได้ที่ `leveltarget`
- ไอดี Level3 ที่ดันไม่ถึง ไปอยู่ `login failed/` (ไม่ส่งออกเลเวลต่ำปนใน output/) เพราะจุดประสงค์ของโหมดคือได้ไอดีเลเวล 3
- โหมดใหม่จะโผล่ใน dropdown ก็ต่อเมื่อ license API ส่ง `ranger_api_Level3` ใน `allowed_modes` (หรืออีเมล whitelist)
