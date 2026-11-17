"""드레스룸 이름·아이콘 (mabi.gamesheet · mabi.dress.names · icons · catalog · service) — 가짜 바이트로. 게임 파일은 쓰지 않는다."""
import json
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

import numpy as np

from mabi import gamesheet as G
from mabi.dress import catalog as C
from mabi.dress import icons as I
from mabi.dress import names as N
from mabi.dress import service as S

H = C.H


# ---------------------------------------------------------------- 가짜 시트 만들기
def vu(v: int) -> bytes:
    out = bytearray()
    while True:
        b, v = v & 0x7F, v >> 7
        if v:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def vi(v: int) -> bytes:
    neg = v < 0
    r = ~v if neg else v
    first = (r & 0x3F) | (0x40 if neg else 0)
    r >>= 6
    out = bytearray([first | (0x80 if r else 0)])
    while r:
        b, r = r & 0x7F, r >> 7
        out.append(b | (0x80 if r else 0))
    return bytes(out)


def fi(v: int) -> bytes:
    return struct.pack("<I", v)


class Text:
    """sheettext 만들기 — 문자열마다 (길이 바이트 + 원문) 조각들 + 0. 오프셋 0 은 빈 문자열."""

    def __init__(self):
        self.b = bytearray(b"\0")
        self.at = {"": 0}

    def s(self, s: str) -> bytes:
        if s not in self.at:
            self.at[s] = len(self.b)
            raw = s.encode("utf-8")
            for i in range(0, len(raw), 0x7F):
                chunk = raw[i:i + 0x7F]
                self.b.append(len(chunk))
                self.b += chunk
            self.b.append(0)
        return vu(self.at[s])

    def many(self, xs) -> bytes:
        return vu(len(xs)) + b"".join(self.s(x) for x in xs)


def color(c) -> bytes:
    if c is None:
        return b"\0"
    return bytes([0xB0, *c])


def costume_bytes(t: Text, name, kind="Top", gender="None", set_id=0, hiding=(), colors=(None,) * 6,
                  models=None, icons=("", "")) -> bytes:
    models = models or {}
    b = t.s(name) + t.s("설명") + fi(set_id) + t.s(kind) + t.s("Default") + t.many(hiding)
    b += vu(1) + vu(1) + vu(0) + vi(-1) + t.s("UTC") + t.s("1999-01-01 00:00:00")
    b += vu(0) + fi(0x4C019769) + vu(0) + t.s("KST") + t.s("2026-10-01 06:00:00") + t.s("Character")
    b += vu(1) + fi(123456) + t.s(gender) + t.s("None") + vu(0) + t.s("Default")
    b += fi(0) + t.s("") + fi(0)
    b += b"".join(color(c) for c in colors)
    b += b"".join(t.many(models.get(g, [])) for g in N.GENDERS)
    b += t.s(icons[0]) + t.s(icons[1]) + vu(0)
    return b


def hair_bytes(t: Text, name, icons=("", "")) -> bytes:
    return (t.s(name) + vi(10) + vu(1) + vu(1) + vu(0) + t.s("OneColor") + t.s("Hair") + t.s(icons[0]) + t.s(icons[1])
            + vu(1) + fi(0) + b"\0" + t.s("UTC") + t.s("2026-01-01 00:00:00"))


def equip_bytes(t: Text, name, kind, models, icons, colors=((1, 2, 3),) + (None,) * 5) -> bytes:
    # 앞쪽 필드는 해석하지 않는다 — 아무 바이트나 둔다
    head = t.s(name) + t.s("설명") + t.s(kind) + bytes([0x00, 0x01, 0x05, 0x00]) + t.s("DefencePower") + bytes([0x19, 0x19])
    tail = b"".join(color(c) for c in colors) + b"".join(t.many(models.get(g, [])) for g in N.GENDERS)
    tail += t.s(icons[0]) + t.s(icons[1]) + t.s("UTC") + t.s("1999-01-01 00:00:00") + vu(0) + fi(0)
    return head + tail


def make_sheets(t: Text, sheets: dict) -> G.Sheets:
    """{시트 이름: (preload 바이트, [행 바이트])} → Sheets."""
    meta = bytearray(vu(len(sheets)))
    data = bytearray()
    for name, (pre, rows) in sheets.items():
        block = sum(len(r) for r in rows)
        meta += t.s(name) + vu(1) + vu(len(rows)) + vu(len(pre)) + vu(block)
    for name, (pre, rows) in sheets.items():
        for r in rows:
            meta += vu(len(r))
            data += r
    for name, (pre, rows) in sheets.items():
        meta += pre
    return G.Sheets(bytes(meta), bytes(data), bytes(t.b))


# ---------------------------------------------------------------- 값 디코더
class ReaderTest(unittest.TestCase):
    def test_numbers(self):
        r = G.Reader(vu(0) + vu(300) + vu(2 ** 31) + vi(5) + vi(-1) + vi(-1000) + vi(70000) + fi(0xDEADBEEF))
        self.assertEqual([r.vu(), r.vu(), r.vu()], [0, 300, 2 ** 31])
        self.assertEqual(vu(300), bytes([0xAC, 0x02]))
        self.assertEqual([r.vi(), r.vi(), r.vi(), r.vi()], [5, -1, -1000, 70000])
        self.assertEqual(r.fi(), 0xDEADBEEF)
        self.assertTrue(r.done)
        with self.assertRaises(IndexError):
            r.fi()

    def test_vi_matches_game_bytes(self):
        self.assertEqual(G.Reader(bytes([0x0A])).vi(), 10)
        self.assertEqual(G.Reader(bytes([0x69])).vi(), ~0x29)   # bit6 = 부호

    def test_string(self):
        t = Text()
        b = t.s("개굴개굴 레이니 코트 (여성용)") + t.s("") + t.s("가" * 60)   # 길면 조각 여럿
        r = G.Reader(b, 0, bytes(t.b))
        self.assertEqual([r.s(), r.s(), r.s()], ["개굴개굴 레이니 코트 (여성용)", "", "가" * 60])
        with self.assertRaises(G.SheetError):
            G.Reader(vu(0)).s()   # 문자열 표 없이

    def test_colors(self):
        b = bytes([0x00, 0x93, 0x9F, 0x90, 0xA0, 0xB5, 0xA4, 0xFD, 0xFB, 0xA8, 0x49, 0x6B, 0xAC, 0xB0, 0xAA,
                   0xB0, 0x2B, 0x39, 0x56])
        r = G.Reader(b)
        got = [r.color() for _ in range(8)]
        self.assertEqual(got, [None, (0x33,) * 3, (0xFF,) * 3, (0, 0, 0), (0xB5,) * 3, (0xFD, 0xFD, 0xFB),
                               (0x49, 0x6B, 0x49), (0xB0, 0xAA, 0xAA)])
        self.assertEqual(G.hex_color(r.color()), "#2B3956")
        self.assertTrue(r.done)
        self.assertIsNone(G.hex_color(None))
        with self.assertRaises(G.SheetError):
            G.Reader(bytes([0x58])).color()

    def test_many(self):
        r = G.Reader(vu(3) + fi(1) + fi(2) + fi(3) + vu(0))
        self.assertEqual(r.many(r.fi), [1, 2, 3])
        self.assertEqual(r.many(r.fi), [])


class SheetsTest(unittest.TestCase):
    def test_index_rows_preload(self):
        t = Text()
        sh = make_sheets(t, {"A": (fi(7) + fi(8), [b"\x01\x02", b"\x03"]), "B": (b"", [b"\x09\x09\x09"])})
        self.assertEqual(sh.names(), ["A", "B"])
        self.assertIn("A", sh)
        self.assertNotIn("Z", sh)
        a = sh.sheet("A")
        self.assertEqual(a.count, 2)
        self.assertEqual([a.row(0), a.row(1)], [b"\x01\x02", b"\x03"])
        p = a.preload()
        self.assertEqual([p.fi(), p.fi()], [7, 8])
        self.assertTrue(p.done)
        self.assertEqual(sh.sheet("B").row(0), b"\x09\x09\x09")   # 앞 시트 블록 뒤에서 시작
        with self.assertRaises(G.SheetError):
            sh.sheet("Z")

    def test_data_text_read_lazily(self):
        t = Text()
        good = make_sheets(t, {"A": (b"", [b"\x05"])})
        calls = []
        sh = G.Sheets(good.meta, lambda: calls.append("data") or good.data, lambda: calls.append("text") or good.text)
        self.assertEqual(calls, [])
        sh.names()
        self.assertEqual(calls, ["text"])
        sh.sheet("A").row(0)
        sh.sheet("A").row(0)
        self.assertEqual(calls, ["text", "data"])   # 한 번만 읽는다

    def test_bad_meta(self):
        t = Text()
        good = make_sheets(t, {"A": (b"\x01", [b"\x05"])})
        with self.assertRaises(G.SheetError):
            G.Sheets(good.meta + b"\x00", good.data, good.text)


# ---------------------------------------------------------------- 행 해석
class RowTest(unittest.TestCase):
    def test_costume_row(self):
        t = Text()
        b = costume_bytes(t, "우드워커 쇼츠 (여성용)", kind="Bottom", gender="Female", set_id=42, hiding=["Shoes"],
                          colors=[(0xD8, 0xC8, 0xBA), (1, 2, 3), None, None, None, None],
                          models={"Female": ["Female_X_Bottom_02"], "Girl": ["Infant_X_F_Bottom_02"]},
                          icons=("Icons/m.asset", "Icons/f.asset"))
        c = N.costume_row(G.Reader(b, 0, bytes(t.b)))
        self.assertEqual(c["name"], "우드워커 쇼츠 (여성용)")
        self.assertEqual((c["type"], c["gender"], c["set"], c["hiding"]), ("Bottom", "Female", 42, ["Shoes"]))
        self.assertEqual(c["colors"], ["#D8C8BA", "#010203", None, None, None, None])
        self.assertEqual(c["models"], {"Male": [], "Female": ["Female_X_Bottom_02"], "Boy": [], "Girl": ["Infant_X_F_Bottom_02"]})
        self.assertEqual(c["icons"], ("Icons/m.asset", "Icons/f.asset"))
        with self.assertRaises(G.SheetError):   # 패치로 필드가 늘면 행 끝이 안 맞는다
            N.costume_row(G.Reader(b + b"\x00", 0, bytes(t.b)))

    def test_hair_row(self):
        t = Text()
        h = N.hair_row(G.Reader(hair_bytes(t, "소프트 스윕 숏 헤어", ("Sprites/a.asset", "Sprites/b.asset")), 0, bytes(t.b)))
        self.assertEqual(h, {"name": "소프트 스윕 숏 헤어", "icons": ("Sprites/a.asset", "Sprites/b.asset")})

    def test_equipment_tail(self):
        t = Text()
        b = equip_bytes(t, "기본 갑옷", "Top", {"Male": ["Male_A_Top_00"], "Female": ["Female_A_Top_00"]},
                        ("TempIconPath", "Icons/x.asset"))
        got = N.equipment_tail(b, bytes(t.b))
        self.assertEqual(got["models"]["Female"], ["Female_A_Top_00"])
        self.assertEqual(got["icons"], ("TempIconPath", "Icons/x.asset"))
        self.assertEqual(got["colors"][0], "#010203")
        self.assertIsNone(N.equipment_tail(b[:-1], bytes(t.b)))   # 끝이 안 맞으면 쓰지 않는다


# ---------------------------------------------------------------- 고르기·모으기
def hit(name, src="Costume", icon="Icons/a.asset", slot="상의", colors=None, set_=""):
    return {"src": src, "name": name, "slot": slot, "set": set_, "icon": icon, "colors": colors or [None] * 6}


class PickTest(unittest.TestCase):
    def test_drops_junk(self):
        for junk in ("커스터마이징 전용 의상", "(임시) 럭키박스 선조립용 신발", "[테스트용] 중년헤어", "<사용하지 않음>",
                     "전투복 상의 (심볼용 데이터)", "경갑_표준방어구_Lv1", "Fashion_HerbCollector_Head_00", "(미사용)"):
            self.assertIsNone(N.pick([hit(junk)]), junk)
        self.assertEqual(N.pick([hit("커스터마이징 전용 의상"), hit("파이터 아머")])["name"], "파이터 아머")

    def test_order_and_alt(self):
        p = N.pick([hit("사슬 갑옷 투구", src="Equipment"), hit("광전사의 면갑", set_="광전사"),
                    hit("사슬 갑옷 투구S", src="Equipment")])
        self.assertEqual((p["name"], p["alt"], p["set"]), ("광전사의 면갑", ["사슬 갑옷 투구"], "광전사"))   # 의상 먼저, 단계 꼬리는 떼고 하나로
        p = N.pick([hit("잔영의 전투복 상의ZZ", src="Equipment"), hit("전투복 상의S", src="Equipment"),
                    hit("전투복 상의", src="Equipment")])
        self.assertEqual(p["name"], "전투복 상의")
        self.assertEqual(N.pick([hit("럭셔리 봄의 축제 크라운"), hit("봄의 축제 크라운")])["name"], "봄의 축제 크라운")
        self.assertEqual(N.pick([hit("헤어", src="CharacterHair"), hit("장비", src="Equipment")])["name"], "헤어")

    def test_icon_from_first_usable(self):
        cols = ["#111111"] + [None] * 5
        p = N.pick([hit("철판 갑옷 신발", icon="TempIconPath"), hit("철판 갑옷 신발", icon="", src="Equipment"),
                    hit("철판 갑옷 신발", icon="Icons/s.asset", src="Equipment", colors=cols)])
        self.assertEqual((p["icon"], p["colors"]), ("Icons/s.asset", cols))
        self.assertEqual(N.pick([hit("이름", icon="")])["icon"], "")

    def test_collect_build(self):
        t = Text()
        cos = [costume_bytes(t, "개굴개굴 레이니 코트\xa0(여성용)", gender="Female", set_id=9, hiding=["Bottom"],
                             colors=[(0xAD, 0xBD, 0x27)] + [None] * 5,
                             models={"Female": ["Female_Frog_OnePiece_00"], "Girl": ["Infant_Frog_F_OnePiece_00"]},
                             icons=("Icons/m.asset", "Icons/f.asset")),
               costume_bytes(t, "개굴개굴 레이니 스트랩", kind="Gloves",
                             models={g: ["Female_Frog_Gloves_00" if g == "Female" else "Male_Frog_Gloves_00"] for g in N.GENDERS},
                             icons=("Icons/gm.asset", "Icons/gf.asset")),
               b"\x01\x02"]   # 못 읽는 행은 건너뛴다
        sets_pre = fi(9)
        hair_pre = fi(1) + fi(2) + t.s("Male_Hair_A") + t.s("Female_Hair_A") + t.s("Invalid") + t.s("Infant_Hair_A")
        eq = equip_bytes(t, "가죽 갑옷 상의ZZ", "Top", {"Male": ["Male_Leather_Top_00"]}, ("Icons/l.asset", "Icons/l.asset"))
        sh = make_sheets(t, {
            "CostumeSetInfo": (sets_pre, [t.s("개굴개굴 레이니")]),
            "Costume": (fi(1) + fi(2) + fi(3), cos),
            "CharacterHair": (hair_pre, [hair_bytes(t, "헤어 A", ("Sprites/hm.asset", "Sprites/hf.asset"))]),
            "Equipment": (fi(5), [eq]),
        })
        with self.assertLogs("mabi", "WARNING"):
            names = N.build(sh)
        f = names["Female_Frog_OnePiece_00"]
        self.assertEqual((f["name"], f["slot"], f["set"], f["icon"]), ("개굴개굴 레이니 코트 (여성용)", "상의", "개굴개굴 레이니", "Icons/f.asset"))
        self.assertEqual(f["colors"][0], "#ADBD27")
        self.assertEqual(names["Infant_Frog_F_OnePiece_00"]["icon"], "Icons/f.asset")   # 소녀 = 여성용 아이콘
        self.assertEqual(names["Male_Frog_Gloves_00"]["icon"], "Icons/gm.asset")         # 남성·소년 = 남성용 아이콘
        self.assertEqual(names["Male_Frog_Gloves_00"]["slot"], "장갑")
        self.assertEqual(names["Female_Hair_A"], {"name": "헤어 A", "alt": [], "slot": "헤어", "set": "",
                                                  "icon": "Sprites/hf.asset", "colors": [None] * 6, "ids": {}})
        # 의상 시트 id → 체형별 모델 (게임 캐릭터 불러오기)
        self.assertEqual(f["ids"], {"Female": [1]})
        by = N.by_sheet(names)
        self.assertEqual(by[1], {"Female": ["Female_Frog_OnePiece_00"], "Girl": ["Infant_Frog_F_OnePiece_00"]})
        self.assertEqual(by[2]["Boy"], ["Male_Frog_Gloves_00"])
        self.assertNotIn(3, by)                                                          # 못 읽은 행
        self.assertEqual(names["Male_Leather_Top_00"]["ids"], {})                        # 장비는 아직 없음
        self.assertEqual(names["Male_Hair_A"]["icon"], "Sprites/hm.asset")
        self.assertNotIn("Invalid", names)
        self.assertEqual(names["Male_Leather_Top_00"]["name"], "가죽 갑옷 상의")
        self.assertEqual(names["Male_Leather_Top_00"]["slot"], "상의")


class LoadCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.stamp = [1, 2]
        self.calls = 0
        p = mock.patch.object(G, "stamp", lambda gd: list(self.stamp))
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def opener(self, gd):
        self.calls += 1
        return "sheets"

    def load(self):
        with mock.patch.object(N, "build", lambda sh: {"M": {"name": f"이름{self.calls}"}}):
            return N.load(self.dir, "game", self.opener)

    def test_rebuild_only_when_stamp_or_format_changes(self):
        self.assertEqual(self.load(), ({"M": {"name": "이름1"}}, True))
        self.assertEqual(self.load(), ({"M": {"name": "이름1"}}, False))   # 저장한 표
        self.assertEqual(self.calls, 1)
        self.stamp = [1, 3]                                                  # 게임 패치
        self.assertEqual(self.load(), ({"M": {"name": "이름2"}}, True))
        with mock.patch.object(N, "FORMAT", N.FORMAT + 1):                   # 고르는 규칙이 바뀜
            self.assertTrue(self.load()[1])
        (self.dir / "names.json").write_text("깨짐", encoding="utf-8")
        self.assertTrue(self.load()[1])
        self.assertEqual(self.calls, 4)

    def test_sheet_error_gives_empty(self):
        def bad(gd):
            raise G.SheetError("없음")
        with self.assertLogs("mabi", "WARNING"):
            self.assertEqual(N.load(self.dir, "game", bad), ({}, False))
        self.assertFalse((self.dir / "names.json").exists())


# ---------------------------------------------------------------- 목록
class CatalogNamesTest(unittest.TestCase):
    PATHS = [
        H + "Female/Top/ForAssetBundle/Female_Maid_Top_00.prefab", H + "FBX/Human/Female/Top/Female_Maid_Top_00.fbx",
        H + "Female/Top/ForAssetBundle/Female_Zeta_Top_00.prefab", H + "FBX/Human/Female/Top/Female_Zeta_Top_00.fbx",
        H + "Female/Top/ForAssetBundle/Female_Alpha_Top_00.prefab", H + "FBX/Human/Female/Top/Female_Alpha_Top_00.fbx",
        H + "Female/Top/Female_Loose_Top_00.prefab", H + "FBX/Human/Female/Top/Female_Loose_Top_00.fbx",   # 상의는 바로 밑 안 받음
        H + "Female/Helmet/Female_Crew_Helmet_00.prefab", H + "FBX/Human/Female/Helmet/Female_Crew_Helmet_00.fbx",
        H + "Male/Helmet/ForAssetBundle/Male_Dup_Helmet_00.prefab", H + "Male/Helmet/Male_Dup_Helmet_00.prefab",
        H + "FBX/Human/Male/Helmet/Male_Dup_Helmet_00.fbx",
        H + "Male/Helmet/Male_Test_Helmet_03.prefab", H + "FBX/Human/Male/Helmet/Male_Test_Helmet_03.fbx",
    ]
    LOOSE_HAIR = [   # 머리는 바로 밑 prefab 이라도 게임 시트가 쓰는 것만
        H + "Female/Hair/Female_Hair_Oldman_00.prefab", H + "FBX/Human/Female/Hair/Female_Hair_Oldman_00.fbx",
        H + "Female/Hair/Female_Hair_Guide_00.prefab", H + "FBX/Human/Female/Hair/Female_Hair_Guide_00.fbx",
    ]
    NAMES = {"Female_Zeta_Top_00": {"name": "가나 셔츠", "alt": ["다른 이름"], "slot": "상의", "set": "가나", "icon": "Icons/z.asset"},
             "Female_Maid_Top_00": {"name": "하녀 상의", "alt": [], "slot": "상의", "set": "", "icon": ""},
             "Female_Crew_Helmet_00": {"name": "페도라", "alt": [], "slot": "모자", "set": "", "icon": "Icons/c.asset"}}

    def test_names_and_sort(self):
        items = C.build(self.PATHS, self.NAMES)
        self.assertEqual([i.id for i in items], ["Female_Zeta_Top_00", "Female_Maid_Top_00", "Female_Alpha_Top_00",
                                                 "Female_Crew_Helmet_00", "Male_Dup_Helmet_00"])
        d = items[0].to_dict()
        self.assertEqual({k: d[k] for k in ("name", "kor", "alt", "slot", "set", "icon", "named")},
                         {"name": "Zeta", "kor": "가나 셔츠", "alt": ["다른 이름"], "slot": "상의", "set": "가나",
                          "icon": "Icons/z.asset", "named": True})
        self.assertNotIn("set_name", d)
        a = items[2].to_dict()
        self.assertEqual((a["kor"], a["named"], a["alt"], a["icon"]), ("", False, [], ""))
        json.dumps(d, ensure_ascii=False)   # 화면으로 그대로 보낸다

    def test_loose_only_named(self):
        names = {"Female_Hair_Oldman_00": {"name": "머리", "alt": [], "slot": "", "set": "", "icon": ""}}
        self.assertEqual([i.id for i in C.build(self.LOOSE_HAIR, names)], ["Female_Hair_Oldman_00"])
        self.assertEqual(C.build(self.LOOSE_HAIR), [])

    def test_without_names(self):
        self.assertEqual([i.id for i in C.build(self.PATHS)][:3], ["Female_Alpha_Top_00", "Female_Maid_Top_00", "Female_Zeta_Top_00"])
        self.assertEqual(C.build(self.PATHS)[-1].part, "Helmet")


# ---------------------------------------------------------------- 아이콘
class IconTest(unittest.TestCase):
    def test_parts_pick_size(self):
        mono = {"keys": [64, 128, 256], "coloredIcons": [{"rid": 1}, {"rid": 2}, {"rid": 3}],
                "references": {"RefIds": [
                    {"rid": -2, "data": None},
                    {"rid": 2, "data": {"Base": {"rid": 20}, "DyeMask_0": {"rid": 21}, "DyeMask_1": {"rid": -2}}},
                    {"rid": 20, "data": {"path": "Icons/x/Base_128.png"}},
                    {"rid": 21, "data": {"path": "Icons/x/DyeMask_0_128.png"}}]}}
        self.assertEqual(I._parts(mono, 128), ("Icons/x/Base_128.png", ["Icons/x/DyeMask_0_128.png", None]))
        self.assertEqual(I._parts({"keys": [], "coloredIcons": []}, 128), (None, []))
        hair = dict(mono, keys=[128], coloredIcons=[{"rid": 2}])
        self.assertEqual(I._parts(hair, 64)[0], "Icons/x/Base_128.png")   # 맞는 크기가 없으면 있는 것

    def test_paint(self):
        base = np.zeros((2, 2, 4), np.uint8)
        base[..., 3] = [[255, 0], [255, 255]]
        base[1, 1, :3] = 40
        mask = np.zeros((2, 2, 4), np.uint8)
        mask[0, 0, 0] = 57          # 칸 0 최대 → 색 그대로
        mask[1, 0, 1] = 57          # 칸 1 (색 없음 → 중간 밤색)
        out = I.paint(base, [mask, None], [(1.0, 0.0, 0.0), None])
        self.assertEqual(out[0, 0].tolist(), [255, 0, 0, 255])
        self.assertEqual(out[1, 0, :3].tolist(), list(I.DEFAULT))
        self.assertEqual(out[0, 1, 3], 0)               # 알파는 Base 것
        self.assertEqual(out[1, 1, :3].tolist(), [40, 40, 40])

    def test_helpers(self):
        self.assertEqual(I.asset_path("Icons/a"), "Assets/PatchableAssets/Icons/a.asset")
        self.assertEqual(I.asset_path("Icons/a.asset"), "Assets/PatchableAssets/Icons/a.asset")
        self.assertEqual(I._rgb("#FF0000"), (1.0, 0.0, 0.0))
        self.assertEqual(I._rgb({"r": 0.5, "g": 0.25, "b": 0.0, "a": 1}), (0.5, 0.25, 0.0))
        self.assertIsNone(I._rgb(None))
        self.assertTrue(I.keep("Assets/PatchableAssets/Sprites/CustomizeIcon/Hair_Short_22_base.png"))
        self.assertFalse(I.keep("Assets/PatchableAssets/Character/Player/Human/FBX/Male_Body_00.fbx"))

    def test_export_missing_icon(self):
        self.assertFalse(I.export(NS(paths={}), "Icons/none.asset", [], Path("unused.png")))
        self.assertFalse(I.export(NS(paths={}), "", [], Path("unused.png")))


# ---------------------------------------------------------------- service
class ServiceIconTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.room = S.DressRoom(self.dir, game_dir=lambda: None)
        item = C.Item("Female_Frog_OnePiece_00", "Female", "OnePiece", "Frog", "x.fbx", kor="개굴", icon="Icons/f.asset")
        bare = C.Item("Female_Acheron_Top_00", "Female", "Top", "Acheron", "y.fbx")
        self.room._pack = object()   # 게임 폴더 없이
        self.room._icon_pack = "icon-pack"
        self.room._items = {i.id: i for i in (item, bare)}
        self.room._names = {item.id: {"name": "개굴", "icon": "Icons/f.asset", "colors": ["#ADBD27"] + [None] * 5}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_icon_once(self):
        calls = []

        def export(pk, icon, colors, out):
            calls.append((pk, icon, colors[0]))
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(b"png")
            return True
        with mock.patch.object(S.I, "export", export):
            self.assertEqual(self.room.icon("Female_Frog_OnePiece_00"), "icons/Female_Frog_OnePiece_00.png")
            self.assertEqual(self.room.icon("Female_Frog_OnePiece_00"), "icons/Female_Frog_OnePiece_00.png")
        self.assertEqual(calls, [("icon-pack", "Icons/f.asset", "#ADBD27")])   # 이미 있으면 그대로
        self.assertIsNotNone(self.room.path("icons/Female_Frog_OnePiece_00.png"))

    def test_icon_none_and_unknown(self):
        self.assertIsNone(self.room.icon("Female_Acheron_Top_00"))            # 게임 아이템이 아님
        with mock.patch.object(S.I, "export", lambda *a: False):
            self.room._names["Female_Acheron_Top_00"] = {"icon": "Icons/none.asset", "colors": []}
            self.assertIsNone(self.room.icon("Female_Acheron_Top_00"))        # 게임 목차에 없는 아이콘
        with self.assertRaises(S.DressError):
            self.room.icon("Nobody_Top_00")

    def test_icons_cleared_with_stamp_and_new_names(self):
        (self.dir / "icons").mkdir()
        (self.dir / "icons" / "a.png").write_bytes(b"x")
        self.room._check_stamp([1])
        self.assertFalse((self.dir / "icons").exists())
        (self.dir / "icons").mkdir()
        (self.dir / "icons" / "a.png").write_bytes(b"x")
        with mock.patch.object(S.NM, "load", lambda d, gd: ({"M": {}}, False)):
            self.assertEqual(self.room._load_names("game"), {"M": {}})
        self.assertTrue((self.dir / "icons" / "a.png").exists())
        with mock.patch.object(S.NM, "load", lambda d, gd: ({"M": {}}, True)):   # 시트가 바뀌어 다시 만듦
            self.room._load_names("game")
        self.assertFalse((self.dir / "icons").exists())

    def test_names_failure_keeps_catalog(self):
        def boom(d, gd):
            raise KeyError("x")
        with mock.patch.object(S.NM, "load", boom), self.assertLogs("mabi", "WARNING"):
            self.assertEqual(self.room._load_names("game"), {})


class DressApiIconTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from gui_app import dressroom as D
        except ImportError as e:   # PySide6 없는 환경
            raise unittest.SkipTest(str(e))
        cls.D = D

    def test_icon(self):
        def icon(mid):
            if mid == "bad":
                raise S.DressError("모르는 모델: bad")
            return None if mid == "none" else f"icons/{mid}.png"
        d = self.D.DressApi(NS(icon=icon), lambda *a: None)
        self.assertEqual(d.icon("a"), {"url": "cache/icons/a.png"})
        self.assertEqual(d.icon("none"), {"url": None})
        self.assertEqual(d.icon("bad"), {"error": "모르는 모델: bad"})


if __name__ == "__main__":
    unittest.main()
