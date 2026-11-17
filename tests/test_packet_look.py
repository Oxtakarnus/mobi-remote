"""내 캐릭터 외형 요약 (mabi/packet_monitor/look.py) — 만든 바이트로. 실제 패킷은 쓰지 않는다."""
import struct
import unittest
from types import SimpleNamespace as NS

from mabi.packet_monitor import look as L
from mabi.packet_monitor.monitor import PacketMonitor

FEMALE = 0x0CD5CF74
GIRL = 0x72666BA4
TYPE = {v: k for k, v in L.COSTUME_TYPE.items()}


def costume(uid, sheet, colors=(), size=96) -> bytes:
    """의상 구조 — [u64 고유 번호][u32 시트][u64 얻은 때][u32 등급][u8][u32] +29 색 있음 ×6 · +35 RGBA ×6, 뒤는 0."""
    has = bytes(1 if i < len(colors) and colors[i] else 0 for i in range(6))
    cols = [struct.unpack("<I", bytes(c) + b"\xff")[0] if i < len(colors) and colors[i] else 0 for i, c in
            enumerate((list(colors) + [None] * 6)[:6])]
    b = struct.pack("<QIQI", uid, sheet, 123, 2) + b"\x01" + struct.pack("<I", 0) + has + struct.pack("<6I", *cols)
    return b + b"\0" * (size - len(b))


def appearance(gender=1, height=-0.5, model=FEMALE, vals=None) -> bytes:
    vals = vals or [11, 12, 0, 14, 15, 16, 0, 18, 19, 20, 21, 22]
    return struct.pack("<hfI", gender, height, model) + struct.pack("<12I", *vals)


WORN = [("Top", 101, 5001, [(1, 2, 3), (4, 5, 6)]), ("Shoes", 102, 5002, []), ("Robe", 103, 5003, [(9, 9, 9)])]


def personal(size=96, worn=WORN, ap=None, current=1, storage=0) -> bytes:
    b = struct.pack("<Q", 777) + b"\x07" * 40
    b += struct.pack("<I", 1) + struct.pack("<I", 104) + b"\x00" * 60          # 장비 목록 (슬롯 번호는 의상 종류가 아니다)
    b += struct.pack("<I", len(worn)) + b"".join(struct.pack("<I", TYPE[t]) + costume(u, s, c, size) for t, u, s, c in worn)
    b += b"\x05" * 300
    owned = [(u, costume(u, s, c, size)) for _, u, s, c in worn] + [(104, costume(104, 5004, (), size))]
    b += struct.pack("<III", 3, current, len(owned)) + b"".join(struct.pack("<Q", u) + c for u, c in owned)
    b += struct.pack("<I", storage)
    eq = [(101, 1, 1), (102, 1, 1), (103, 1, 0), (103, 2, 1)]
    b += struct.pack("<I", len(eq)) + b"".join(struct.pack("<QIB", u, p, s) for u, p, s in eq)
    b += b"\x05" * 500 + (ap if ap is not None else appearance()) + b"\x09" * 200
    return b


class ParseTest(unittest.TestCase):
    def test_personal(self):
        d = L.personal(personal())
        self.assertEqual((d["gender"], d["body"], d["height"]), ("Female", "Female", -0.5))
        self.assertEqual(d["sheet"]["hair"], 11)
        self.assertEqual(d["sheet"]["beard"], 0)                         # 수염 없음
        self.assertEqual(d["sheet"]["eye_color"], 22)
        self.assertEqual(d["costumes"], [
            {"type": "Top", "sheet": 5001, "colors": ["#010203", "#040506", None, None, None, None], "show": True},
            {"type": "Shoes", "sheet": 5002, "colors": [None] * 6, "show": True},
            {"type": "Robe", "sheet": 5003, "colors": ["#090909"] + [None] * 5, "show": False}])   # 지금 프리셋(1)에서 숨김

    def test_costume_size_changes(self):
        d = L.personal(personal(size=95))                                # 10-25 처럼 한 바이트 작은 의상
        self.assertEqual([c["sheet"] for c in d["costumes"]], [5001, 5002, 5003])

    def test_unknown_show(self):
        d = L.personal(personal(storage=2))                              # 보관 칸 항목 크기를 몰라 보이기를 모름
        self.assertEqual({c["show"] for c in d["costumes"]}, {None})
        d = L.personal(personal(current=2))
        self.assertEqual([c["show"] for c in d["costumes"]], [None, None, True])   # 프리셋 2 에는 로브만 있다

    def test_few_costumes(self):
        d = L.personal(personal(worn=WORN[:2]))                          # 둘 이하면 목록을 믿지 못한다
        self.assertEqual(d["costumes"], [])

    def test_appearance(self):
        self.assertIsNone(L.personal(personal(ap=b"")))
        self.assertIsNone(L.appearance(appearance(model=0x12345678) + b"\0" * 20))   # 모르는 몸 모델
        bad = appearance(vals=[11, 0, 0, 14, 15, 16, 0, 18, 19, 20, 21, 22])          # 눈이 0 — 외형이 아니다
        self.assertIsNone(L.appearance(b"\0" * 20 + bad + b"\0" * 20))
        two = b"\0" * 20 + appearance(height=0.25) + b"\0" * 8 + appearance(gender=1, height=1.0, model=GIRL) + b"\0" * 20
        d = L.appearance(two)                                            # 뒤의 것
        self.assertEqual((d["body"], d["height"]), ("Girl", 1.0))
        self.assertEqual(L.appearance(b"\0" * 20 + appearance(height=1.00004) + b"\0" * 20)["height"], 1.0)

    def test_age(self):
        head = struct.pack("<IhfI", 16, 1, -0.5, FEMALE)
        body = b"\x01" * 30 + struct.pack("<I", FEMALE) + b"\0" * 10 + head + b"\0" * 50
        self.assertEqual(L.age(body, FEMALE, "Female"), 16)               # 앞의 엉뚱한 자리는 건너뛴다
        self.assertIsNone(L.age(body, FEMALE, "Male"))
        self.assertIsNone(L.age(b"\0" * 64, FEMALE, "Female"))


class MyLookTest(unittest.TestCase):
    def test_snapshot(self):
        m = L.MyLook()
        self.assertIsNone(m.snapshot())
        m.appearing(b"\0" * 64)                                          # 외형 전 — 무시
        m.personal(personal())
        s = m.snapshot()
        self.assertIsNone(s["age"])
        self.assertNotIn("model", s)
        self.assertNotIn("uid", s["costumes"][0])                        # 고유 번호는 내보내지 않는다
        m.appearing(b"\0" * 8 + struct.pack("<IhfI", 15, 1, -0.5, FEMALE) + b"\0" * 8)
        self.assertEqual(m.snapshot()["age"], 15)
        s = m.snapshot()
        s["costumes"][0]["colors"][0] = "바꿈"                            # 사본이다
        self.assertEqual(m.snapshot()["costumes"][0]["colors"][0], "#010203")
        m.personal(personal())                                           # 같은 캐릭터 — 나이 그대로
        self.assertEqual(m.snapshot()["age"], 15)
        m.personal(struct.pack("<Q", 888) + personal()[8:])              # 다른 캐릭터 — 나이는 다시
        self.assertIsNone(m.snapshot()["age"])

    def test_bad_body_logs_once(self):
        m = L.MyLook()
        with self.assertLogs("mabi", "INFO") as cm:
            m.personal(b"\0" * 100)
            m.personal(b"\0" * 3)
        self.assertEqual(len(cm.output), 1)
        self.assertIsNone(m.snapshot())


class MonitorRouteTest(unittest.TestCase):
    """감시의 메시지 처리에서 개인 데이터·내 등장이 외형 요약으로 간다."""

    def test_handle(self):
        m = PacketMonitor(None)
        keys = {1: "char.personal_data", 2: "char.appearing"}
        m.table = NS(event=lambda p: NS(key=keys[p], fields=["x"]),
                     decode=lambda p, b: (None, {"char_id": 777} if p == 1 else {"actor": 5}))
        m._handle(1, 0, personal())
        self.assertEqual(m.look.snapshot()["sheet"]["hair"], 11)
        other = struct.pack("<IhfI", 13, 1, -0.5, FEMALE)
        m._handle(2, 0, b"\0" * 8 + other)                               # 남의 등장 — 나이로 안 쓴다
        self.assertIsNone(m.look.snapshot()["age"])
        mine = struct.pack("<QI", 777, 3) + b"\0" * 8 + struct.pack("<IhfI", 17, 1, -0.5, FEMALE)
        m._handle(2, 0, mine)
        self.assertEqual(m.look.snapshot()["age"], 17)


if __name__ == "__main__":
    unittest.main()
