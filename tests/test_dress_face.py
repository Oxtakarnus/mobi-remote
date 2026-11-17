"""드레스룸 얼굴 꾸미기 (mabi.dress.face · gamesheet.cached · icons CommonIcon · service 의 face:/decal:/fi:)와
게임 캐릭터 불러오기 변환 (mabi.dress.gamelook) — 가짜 바이트로."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

from mabi import gamesheet as G
from mabi.dress import face as F
from mabi.dress import gamelook as GL
from mabi.dress import icons as I
from mabi.dress import service as S
from test_dress_body import _Enc
from test_dress_names import Text, color, fi, make_sheets, vi, vu

INV = "Invalid"


# ---------------------------------------------------------------- 가짜 시트
def models(t: Text, m=(INV, INV, INV, INV)) -> bytes:
    return b"".join(t.s(x) for x in m)


def part_row(t: Text, name, age=0, hide=0, icons=("", ""), color_flag=None, hide_time=False) -> bytes:
    b = t.s(name) + vi(age) + vu(0) + vu(0) + vu(hide) + b"".join(t.s(x) for x in icons)
    if color_flag is not None:
        b += vu(int(color_flag)) + fi(0)
    if hide_time:
        b += t.s("UTC") + t.s("")
    return b


def color_row(t: Text, name, cols, desc=True, hide=0, kind=None) -> bytes:
    b = t.s(name) + (t.s("설명") if desc else b"") + vu(0) + vu(0) + vu(hide)
    if kind is not None:
        b += t.s(kind)
    return b + b"".join(color(c) for c in cols)


def face_sheets() -> G.Sheets:
    t = Text()
    sheets = {}
    # 얼굴형 — 둘째는 숨김
    sheets["CharacterHead"] = (
        fi(1) + models(t, ("M_Head_A", "F_Head_A", INV, "G_Head_A")) + fi(2) + models(t, ("M_Head_B", INV, INV, INV)),
        [part_row(t, "계란형", icons=("Sprites/CustomizeIcon/Head_A_ColoredIcon.asset",)),
         part_row(t, "숨긴 얼굴", hide=1, icons=("",))])
    # 눈 — 같은 그룹이 얼굴형마다 한 줄씩 (모델은 같다) · 나이 제한 있는 것
    eyes_pre = (fi(10) + fi(1) + models(t, ("M_Eye_A", "F_Eye_A", INV, INV))
                + fi(10) + fi(2) + models(t, ("M_Eye_A", "F_Eye_A", INV, INV))
                + fi(11) + fi(1) + models(t, (INV, "F_Eye_B", INV, INV)))
    sheets["CharacterEyes"] = (eyes_pre, [
        part_row(t, "또렷한  눈", icons=("Sprites/CustomizeIcon/EyeM.asset", "Sprites/CustomizeIcon/EyeF.asset"),
                 color_flag=True, hide_time=True),
        part_row(t, "또렷한 눈", color_flag=True, hide_time=True),
        part_row(t, "어른 눈", age=16, color_flag=False, hide_time=True)])
    # 입 — 그룹 20 이 얼굴형 1·2 에, 얼굴형 2 는 숨김이라 빠진다
    sheets["CharacterMouth"] = (
        fi(20) + fi(1) + models(t, ("M_Mouth_A1", "F_Mouth_A1", INV, INV)) + fi(20) + fi(2) + models(t, ("M_Mouth_A2", INV, INV, INV)),
        [part_row(t, "미소", hide_time=True), part_row(t, "미소", hide_time=True)])
    sheets["CharacterBeard"] = (fi(30) + models(t, ("M_Beard_A", INV, INV, INV)) + fi(31) + models(t),
                                [part_row(t, "콧수염"), part_row(t, "모델 없음")])
    sheets["CharacterFaceTattoo"] = (
        fi(40) + models(t, ("M_Blush", "F_Blush", INV, INV)) + fi(41) + models(t, ("M_Test", "F_Test", INV, INV)),
        [part_row(t, "홍조", icons=("Icons/CommonIcon/Customize/Face_Blush_00.asset", "x/Bad.asset"), hide_time=True),
         part_row(t, "[개발] 시험", hide_time=True)])
    sheets["CharacterBodyTattoo"] = (fi(50) + models(t, ("M_Scar", "F_Scar", INV, INV)), [part_row(t, "흉터")])
    sheets["CharacterSkinColor"] = (fi(60) + fi(61), [color_row(t, "밝은", [(250, 220, 200), (240, 200, 190)]),
                                                     color_row(t, "숨김", [(1, 2, 3), None], hide=1)])
    sheets["CharacterEyeColor"] = (fi(70), [color_row(t, "갈색", [(120, 80, 40)])])
    sheets["CharacterHairColor"] = (fi(80) + fi(81), [
        color_row(t, "검정", [(10, 10, 10), (90, 90, 90)], desc=False, kind="OneColor"),
        color_row(t, "투톤", [(200, 0, 0), (0, 0, 200)], desc=False, kind="TwoColor")])
    sheets["CharacterHairAccessoryColor"] = (fi(90), [color_row(t, "금", [(220, 180, 60)])])
    # 머리 — 그룹 5 가 체형(셰이프)마다 한 줄씩, 모델은 같다. 그룹 6 은 모델이 없다
    hair = lambda g, bt, m: fi(g) + fi(bt) + models(t, m)
    sheets["CharacterHair"] = (hair(5, 700, ("M_Hair_A", "F_Hair_A", INV, "G_Hair_A"))
                               + hair(5, 701, ("M_Hair_A", "F_Hair_A", INV, "G_Hair_A")) + hair(6, 700, (INV,) * 4),
                               [b"\0"] * 3)
    sheets["CharacterBodyTypes"] = (fi(700) + t.s("_") + fi(701) + t.s("Thin"), [b"\0", b"\0"])
    return make_sheets(t, sheets)


def som(asset, st=None, rot=0, slots=()) -> dict:
    d = {"AssetPathToLoad": asset, "ModelPartInfo": {"AppearanceSlot": "Face"}}
    if st is not None:
        d["TextureInfo"] = {"BaseTexcoord": st, "Rotation": rot}
    d["DyeInfo"] = {"Slots": [{"Slot": s, "Wirings": [1]} for s in slots]}
    return d


class FakeRes:
    """gamefiles.Resources 꼴 — 경로 → SJON 바이트."""

    def __init__(self, soms: dict):
        self.data = {f"{F.SOM_DIR}Face/{k}.StageObjectModel.sjon.bin": _Enc([]).bytes(v) for k, v in soms.items()}
        self.data[f"{F.SOM_DIR}Face/Broken.StageObjectModel.sjon.bin"] = b"nope"
        self.paths = list(self.data)

    def read(self, p):
        return self.data[p]


# ---------------------------------------------------------------- 시트 → 선택지
class CollectTest(unittest.TestCase):
    def setUp(self):
        self.t = F.collect(face_sheets())

    def test_heads_and_eyes(self):
        t = self.t
        self.assertEqual([h["id"] for h in t["heads"]], [1])                      # 숨긴 얼굴형은 뺀다
        self.assertEqual(t["heads"][0]["m"], {"Male": "M_Head_A", "Female": "F_Head_A", "Girl": "G_Head_A"})
        self.assertEqual(t["heads"][0]["icon"]["Girl"], "Sprites/CustomizeIcon/Head_A_ColoredIcon.asset")
        self.assertEqual([e["id"] for e in t["eyes"]], [10, 11])                  # 그룹마다 하나
        e = t["eyes"][0]
        self.assertEqual((e["name"], e["color"]), ("또렷한 눈", True))             # 빈칸 정리
        self.assertEqual(e["icon"], {"Male": "Sprites/CustomizeIcon/EyeM.asset", "Female": "Sprites/CustomizeIcon/EyeF.asset"})
        self.assertEqual((t["eyes"][1]["age"], t["eyes"][1]["m"]), (16, {"Female": "F_Eye_B"}))

    def test_mouths_beards_tattoos(self):
        t = self.t
        self.assertEqual(t["mouths"], [{"id": 20, "name": "미소", "age": 0, "icon": {"Male": "", "Female": ""},
                                        "m": {"1": {"Male": "M_Mouth_A1", "Female": "F_Mouth_A1"}}}])   # 숨긴 얼굴형 것은 뺀다
        self.assertEqual([b["id"] for b in t["beards"]], [30])                     # 모델 없는 줄은 뺀다
        self.assertEqual([x["id"] for x in t["ftats"]], [40])                      # '[' 로 시작하는 개발용은 뺀다
        self.assertEqual(t["ftats"][0]["icon"], {"Male": "Icons/CommonIcon/Customize/Face_Blush_00.asset", "Female": ""})
        self.assertEqual(t["btats"][0]["m"], {"Male": "M_Scar", "Female": "F_Scar"})

    def test_colors(self):
        c = self.t["colors"]
        self.assertEqual(c["skin"], [{"id": 60, "name": "밝은", "c": "#FADCC8", "c2": "#F0C8BE"}])   # 숨김은 뺀다
        self.assertEqual(c["eye"], [{"id": 70, "name": "갈색", "c": "#785028"}])
        self.assertEqual(c["hair"], [{"id": 80, "name": "검정", "c": "#0A0A0A"},                      # 한 색이면 둘째 색은 버린다
                                     {"id": 81, "name": "투톤", "c": "#C80000", "c2": "#0000C8"}])
        self.assertEqual(c["hairacc"][0]["c"], "#DCB43C")

    def test_model_names(self):
        self.assertEqual(F.model_names(self.t), {"M_Head_A", "F_Head_A", "G_Head_A", "M_Eye_A", "F_Eye_A", "F_Eye_B",
                                                 "M_Mouth_A1", "F_Mouth_A1", "M_Beard_A", "M_Blush", "F_Blush",
                                                 "M_Scar", "F_Scar", "M_Hair_A", "F_Hair_A", "G_Hair_A"})

    def test_hairs_and_shapes(self):
        self.assertEqual(self.t["hairs"], {"5": {"Male": "M_Hair_A", "Female": "F_Hair_A", "Girl": "G_Hair_A"}})   # 모델 없는 그룹은 뺀다
        self.assertEqual(self.t["shapes"], {"700": "", "701": "Thin"})
        t = Text()
        empty = make_sheets(t, {"X": (b"", [])})
        self.assertEqual(F._hairs(empty), {})                                    # 시트가 없으면 빈 표
        self.assertEqual(F._shapes(empty), {})

    def test_broken_row_raises(self):
        t = Text()
        sh = make_sheets(t, {"CharacterBeard": (fi(1) + models(t), [part_row(t, "수염") + b"\x01"])})
        with self.assertRaises(G.SheetError):
            F._parts(sh, "CharacterBeard")


# ---------------------------------------------------------------- 부품 모델
class PartTest(unittest.TestCase):
    def test_part(self):
        self.assertEqual(F.part(som("Models/Head.prefab")), {"a": F.PRE + "Models/Head.prefab", "slot": "Face"})
        d = F.part(som("Tex/Mouth.tga", st=[0.5, 0.25, 0.1, 0.2], rot=90))
        self.assertEqual((d["st"], d["rot"], d["dye"]), ([0.5, 0.25, 0.1, 0.2], 90.0, False))
        self.assertTrue(F.part(som("Tex/Tat.tga", slots=("FaceTattoo",)))["dye"])   # 회색 문신 그림
        self.assertEqual(F.part(som("Tex/Blush.png"))["st"], [1, 1, 0, 0])            # 자리 값이 없으면 통째로
        self.assertIsNone(F.part({"AssetPathToLoad": ""}))
        hair = som("Hair/H.prefab")
        hair["DyeInfo"] = {"Slots": [{"Slot": "Skin", "Wirings": [{"ChannelIndex": 0, "MaterialIndex": 1}]},
                                     {"Slot": "Hair1", "Wirings": [{"ChannelIndex": 0, "MaterialIndex": 0}]},
                                     {"Slot": "Hair", "Wirings": [{"ChannelIndex": 1, "MaterialIndex": 0}]},
                                     {"Slot": "Slot0", "Wirings": [{"ChannelIndex": 5}]}]}
        self.assertEqual(F.part(hair)["ch"], ["Hair1", "Hair", None])            # 채널 → 칸 이름 (피부·범위 밖은 뺀다)

    def test_attach_parts_drops_missing(self):
        t = F.collect(face_sheets())
        res = FakeRes({"M_Head_A": som("H/M.prefab"), "F_Head_A": som("H/F.prefab"),
                       "F_Eye_A": som("E/F.prefab"), "F_Mouth_A1": som("T/m.tga", st=[1, 1, 0, 0]),
                       "F_Blush": som("T/b.tga"), "M_Scar": som("T/s.tga", slots=("BodyTattoo",))})
        with self.assertLogs("mabi", "WARNING"):
            res.data[f"{F.SOM_DIR}Face/F_Scar.StageObjectModel.sjon.bin"] = b"nope"   # 깨진 부품 값
            res.paths.append(f"{F.SOM_DIR}Face/F_Scar.StageObjectModel.sjon.bin")
            F.attach_parts(t, res)
        self.assertEqual(t["heads"][0]["m"], {"Male": "M_Head_A", "Female": "F_Head_A"})   # 부품 없는 소녀 칸은 뺀다
        self.assertEqual([e["id"] for e in t["eyes"]], [10])                                 # 부품 없는 눈 B 는 통째로
        self.assertEqual(t["mouths"][0]["m"], {"1": {"Female": "F_Mouth_A1"}})
        self.assertEqual(t["beards"], [])
        self.assertEqual(t["btats"][0]["m"], {"Male": "M_Scar"})
        self.assertEqual(set(t["parts"]), {"M_Head_A", "F_Head_A", "F_Eye_A", "F_Mouth_A1", "F_Blush", "M_Scar"})
        self.assertTrue(t["parts"]["M_Scar"]["dye"])


# ---------------------------------------------------------------- 캐시
class CachedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.f = Path(self.tmp.name) / "sub" / "x.json"
        self.stamp = [1, 2]
        self.calls = 0
        p = mock.patch.object(G, "stamp", lambda gd: list(self.stamp))
        p.start()
        self.addCleanup(p.stop)

    def build(self, sh):
        self.calls += 1
        return {"n": self.calls, "sh": sh}

    def cached(self, fmt=1, opener=lambda gd: "sheets", stamper=None):
        return G.cached(self.f, fmt, "game", self.build, opener, what="시험", key="k", stamper=stamper)

    def test_stamper(self):
        other = [5]
        self.assertTrue(self.cached(stamper=lambda gd: list(other))[1])
        self.assertFalse(self.cached(stamper=lambda gd: list(other))[1])
        other[0] = 6   # 시트 목차(stamp)는 그대로여도 다시 만든다
        self.assertTrue(self.cached(stamper=lambda gd: list(other))[1])

    def test_keeps_until_stamp_or_format_changes(self):
        self.assertEqual(self.cached(), ({"n": 1, "sh": "sheets"}, True))
        self.assertEqual(self.cached(), ({"n": 1, "sh": "sheets"}, False))
        self.stamp = [1, 3]
        self.assertEqual(self.cached()[0]["n"], 2)
        self.assertTrue(self.cached(fmt=2)[1])
        self.f.write_text("[1]", encoding="utf-8")   # 꼴이 다른 파일
        self.assertTrue(self.cached(fmt=2)[1])
        self.assertEqual(self.calls, 4)

    def test_failures_give_none(self):
        def bad(gd):
            raise G.SheetError("없음")
        with self.assertLogs("mabi", "WARNING"):
            self.assertEqual(self.cached(opener=bad), (None, False))
        with mock.patch.object(G, "stamp", side_effect=OSError("목차 없음")), self.assertLogs("mabi", "WARNING"):
            self.assertEqual(self.cached(), (None, False))
        self.assertFalse(self.f.exists())

    def test_face_load(self):
        res = FakeRes({"M_Head_A": som("H/M.prefab")})
        both = [1, 2, 7, 8]   # 부품은 본 목차에서도 찾으므로 캐시 기준도 두 목차
        with mock.patch.object(F.gf, "res_stamp", lambda gd: list(both)):
            t, fresh = F.load(Path(self.tmp.name), "game", lambda gd: face_sheets(), lambda gd: res)
            self.assertTrue(fresh)
            self.assertEqual([h["m"] for h in t["heads"]], [{"Male": "M_Head_A"}])
            self.assertTrue((Path(self.tmp.name) / "face.json").exists())
            self.assertEqual(F.load(Path(self.tmp.name), "game", None, None), (t, False))   # 저장한 표
            both[3] = 9   # 본 목차만 바뀐 패치
            self.assertTrue(F.load(Path(self.tmp.name), "game", lambda gd: face_sheets(), lambda gd: res)[1])


# ---------------------------------------------------------------- 아이콘 (CommonIcon)
class CommonIconTest(unittest.TestCase):
    def test_parts(self):
        mono = {"keys": [64, 128], "commonIcons": [{"rid": 1}, {"rid": 2}],
                "references": {"RefIds": [{"rid": 1, "data": {"path": "Icons/CommonIcon/Customize/a_64.png"}},
                                          {"rid": 2, "data": {"path": "Icons/CommonIcon/Customize/a_128.png"}}]}}
        self.assertEqual(I._parts(mono, 128), ("Icons/CommonIcon/Customize/a_128.png", []))
        self.assertTrue(I.keep("Assets/PatchableAssets/Icons/CommonIcon/Customize/a.asset"))
        self.assertFalse(I.keep("Assets/PatchableAssets/Icons/CommonIcon/Item/a.asset"))


# ---------------------------------------------------------------- 게임 캐릭터 불러오기
GL_FACE = {"colors": {"skin": [{"id": 60, "c": "#FADCC8"}], "eye": [{"id": 70, "c": "#785028"}],
                      "hair": [{"id": 80, "c": "#0A0A0A"}, {"id": 81, "c": "#C80000", "c2": "#0000C8"}],
                      "hairacc": [{"id": 90, "c": "#DCB43C"}]},
           "hairs": {"5": {"Female": "F_Hair_T", "Male": "M_Hair_T"}, "6": {"Female": "F_Hair_Plain"}},
           "shapes": {"700": "", "701": "Thin"},
           "parts": {"F_Hair_T": {"a": "x", "slot": "Hair", "ch": ["Hair1", "HairAccessory", None]}}}
GL_ITEMS = {m: NS(part=p) for m, p in (("F_Hair_T", "Hair"), ("F_Hair_Plain", "Hair"), ("F_Dress_OnePiece", "OnePiece"),
                                       ("F_Pants_Bottom", "Bottom"), ("F_Cap_Helmet", "Helmet"))}
GL_NAMES = {"F_Dress_OnePiece": {"name": "드레스", "colors": ["#111111", "#222222", None, None, None, None]},
            "F_Bow": {"name": "활"}}
GL_BY = {1: {"Female": ["F_Dress_OnePiece"]}, 2: {"Female": ["F_Pants_Bottom"]}, 3: {"Female": ["F_Bow", "F_Quiver"]},
         4: {"Female": ["F_Cap_Helmet"]}}


def gl_snap(**kw):
    s = {"body": "Female", "gender": "Female", "height": -2, "age": 16,
         "sheet": {"hair": 5, "eyes": 10, "beard": 0, "head": 1, "mouth": 20, "ftat": 40, "btat": 0, "shape": 701,
                   "skin": 60, "hair_color": 81, "hairacc_color": 90, "eye_color": 70},
         "costumes": [{"type": "Top", "sheet": 1, "colors": ["#AAAAAA"] + [None] * 5, "show": True},
                      {"type": "Bottom", "sheet": 2, "colors": [None] * 6, "show": None},
                      {"type": "Weapon", "sheet": 3, "colors": [None] * 6, "show": True},
                      {"type": "Hat", "sheet": 4, "colors": [None] * 6, "show": False},
                      {"type": "EarDeco", "sheet": 99, "colors": [None] * 6, "show": True}]}
    s.update(kw)
    return s


class GameLookTest(unittest.TestCase):
    def test_convert(self):
        look, miss = GL.convert(gl_snap(), GL_FACE, GL_NAMES, GL_ITEMS, GL_BY)
        self.assertEqual({k: look[k] for k in ("name", "body", "shape", "age", "height", "skin")},
                         {"name": GL.NAME, "body": "Female", "shape": "Thin", "age": 16, "height": -1.0, "skin": "#FADCC8"})
        self.assertEqual(look["face"], {"heads": 1, "eyes": 10, "mouths": 20, "beards": None, "ftats": 40, "btats": None,
                                        "eye": "#785028", "tat": None})
        self.assertEqual(look["worn"], {
            "Hair": {"id": "F_Hair_T", "colors": ["#0000C8", "#DCB43C", None]},    # 채널 칸 이름대로 (투톤 둘째 색·장식색)
            "OnePiece": {"id": "F_Dress_OnePiece", "colors": ["#AAAAAA", "#222222"]}})   # 안 바꾼 칸은 시트 기본색, 뒤 빈 칸은 뺀다
        self.assertEqual(miss, ["활", "귀 장식"])                                   # 하의는 한 벌이 가리고, 모자는 숨김
        six = [{"type": "Top", "sheet": 1, "colors": ["#AAAAAA", None, None, "#444444", None, "#666666"], "show": True}]
        look, _ = GL.convert(gl_snap(costumes=six), GL_FACE, GL_NAMES, GL_ITEMS, GL_BY)
        self.assertEqual(look["worn"]["OnePiece"]["colors"], ["#AAAAAA", "#222222", None, "#444444", None, "#666666"])   # 6칸

    def test_plain_hair_and_missing(self):
        look, miss = GL.convert(gl_snap(sheet={**gl_snap()["sheet"], "hair": 6, "hair_color": 80}, costumes=[]),
                                GL_FACE, {}, GL_ITEMS, {})
        self.assertEqual(look["worn"], {"Hair": {"id": "F_Hair_Plain", "colors": ["#0A0A0A", None, None]}})   # 부품 값 없으면 채널 0 만
        look, miss = GL.convert(gl_snap(sheet={"hair": 9}, costumes=[], age=True, height="x"), None, {}, {}, {})
        self.assertEqual(miss, ["머리"])
        self.assertEqual((look["age"], look["height"], look["skin"], look["shape"]), (None, 0.0, None, ""))
        self.assertEqual(look["worn"], {})
        for bad in (None, {"body": "Elf"}, "문자열"):
            with self.assertRaises(GL.LookError):
                GL.convert(bad, GL_FACE, {}, {}, {})


# ---------------------------------------------------------------- 서비스
class ServiceFaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.room = S.DressRoom(Path(self.tmp.name), game_dir=lambda: None)
        self.room._face = {"parts": {"M_Head": {"a": "Assets/H.prefab", "slot": "Face"},
                                     "Lips": {"a": "Assets/L.tga", "slot": "Face", "st": [1, 1, 0, 0], "rot": 0, "dye": False}}}

    def test_fbx(self):
        r = self.room
        self.assertEqual(r._fbx("face:M_Head"), ("item", "Assets/H.prefab"))
        self.assertEqual(r._fbx("decal:Lips"), ("decal", "Assets/L.tga"))
        for bad in ("face:Lips", "decal:M_Head", "face:Nope"):   # 메시·데칼 종류가 안 맞거나 없는 것
            with self.assertRaises(S.DressError):
                r._fbx(bad)

    def test_load_face_failure_is_none(self):
        with mock.patch.object(S.FC, "load", side_effect=RuntimeError("깨짐")), self.assertLogs("mabi", "WARNING"):
            self.assertIsNone(self.room._load_face("game"))
        t = {k: [] for k in F.KINDS}
        t["ftats"] = [{"icon": {"Male": "Icons/CommonIcon/Customize/a.asset", "Female": ""}}]
        with mock.patch.object(S.FC, "load", return_value=(t, False)):
            self.assertIs(self.room._load_face("game"), t)
        self.assertEqual(self.room._face_icons, {"Icons/CommonIcon/Customize/a.asset"})

    def test_icon(self):
        r = self.room
        r._face_icons = {"Icons/CommonIcon/Customize/a.asset"}
        calls = []

        def export(pk, icon, colors, out):
            calls.append((icon, colors))
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(b"png")
            return True
        with mock.patch.object(r, "pack"), mock.patch.object(r, "_icons", return_value=NS()), \
                mock.patch.object(S.I, "export", export):
            with self.assertRaises(S.DressError):
                r.icon("fi:Icons/Other.asset")                       # 표에 없는 아이콘은 안 꺼낸다
            rel = r.icon("fi:Icons/CommonIcon/Customize/a.asset")
            self.assertEqual(r.icon("fi:Icons/CommonIcon/Customize/a.asset"), rel)   # 두 번째는 있는 파일
        self.assertTrue(rel.startswith("icons/") and ":" not in rel and "/" not in rel[6:])
        self.assertEqual(calls, [("Icons/CommonIcon/Customize/a.asset", [])])

    def test_game_look(self):
        r = self.room
        r._face, r._items = GL_FACE, GL_ITEMS
        r._names = {"F_Dress_OnePiece": {**GL_NAMES["F_Dress_OnePiece"], "ids": {"Female": [1]}}}
        with mock.patch.object(r, "pack"):
            look, miss = r.game_look(gl_snap())
            self.assertEqual(set(look["worn"]), {"Hair", "OnePiece"})
            self.assertEqual(r._by_sheet, {1: {"Female": ["F_Dress_OnePiece"]}})   # 이름 표에서 한 번 만든다
            with self.assertRaises(S.DressError):
                r.game_look({"body": "Elf"})
        r.release()
        self.assertIsNone(r._by_sheet)

    def test_catalog_hides_load_only_tables(self):
        r = self.room
        r._face = {"heads": [], "hairs": {"5": {}}, "shapes": {}}
        with mock.patch.object(r, "pack"):
            self.assertEqual(r.catalog()["face"], {"heads": []})                    # 화면엔 불러오기용 표를 안 보낸다


if __name__ == "__main__":
    unittest.main()
