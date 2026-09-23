"""state ของบัญชีหนึ่งใบระหว่างที่กำลังถูกทำงาน

ทุกฟิลด์ในนี้เคยเป็นตัวแปรระดับโมดูลใน botLineRanger (LFACCACHE, GAMEID, FILENAME,
LASTGACHASTATUS) ซึ่งแปลว่าสองบัญชีในโปรเซสเดียวกันเขียนทับกัน บอทจึงต้องแยกโปรเซส
ต่อหนึ่ง worker และจ่ายแรม 5.5 GB เพื่อได้ 128 ช่องพร้อมกัน
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AccountSession:
    src: str                       # path ของไฟล์ใน execute/
    lane: object                   # ProxyLane ที่บัญชีนี้ใช้ตลอด session
    cookie: str = ""               # "LF_AC=..."
    rsn: str = ""                  # GAME_ID
    home: dict | None = None       # /home ดึงครั้งเดียว ใช้ซ้ำทั้ง session
    gacha_units: list = field(default_factory=list)
    gacha_status: str = "-"
    level: int = 0
    ruby: str = "NA"
    ticket: str = "NA"
    rangers: str = ""
    error: str = ""
    attempts: int = 0
    cache: dict = field(default_factory=dict)   # ที่เก็บของที่ยิงครั้งเดียวต่อบัญชี เช่น gacha/info

    def reset_token(self) -> None:
        """บังคับให้ relogin ใหม่ในความพยายามรอบถัดไป

        แทน force_stop_LINE_Rangers() ของโหมด headless เดิม ซึ่งไม่ได้ปิดเกมอะไรเลย
        มันแค่ล้าง LFACCACHE
        """
        self.cookie = ""
        self.home = None
        self.cache.clear()


@dataclass
class Outcome:
    dest: str                      # "output" | "backup" | "login failed"
    name: str = ""                 # ชื่อใหม่ของไฟล์ ไม่ใส่ = ใช้ชื่อเดิม
    status: str = "OK"
    error: str = ""
