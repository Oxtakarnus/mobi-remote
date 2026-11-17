"""SJON 읽기(mabi/sjon.py)와 드레스룸 몸 다양성 자료 변환(mabi/dress/body.py) — 게임 파일 없이 만든 바이트로."""
import struct
import tempfile
import unittest
from pathlib import Path

from mabi import sjon
from mabi.dress import body as B
from mabi.dress import service as S


class _Enc:
    """시험용 SJON 쓰기 — 객체는 ('형 이름', {필드: 값}) 으로 준다."""

    def __init__(self, types):
        self.strs, self.w = [], [0]
        self.types = types   # [(형 이름, [필드…])]

    def s(self, x):
        if x not in self.strs:
            self.strs.append(x)
        return self.strs.index(x)

    def block(self, n):
        j = len(self.w)
        self.w.extend([0] * n)
        return j

    def ptr(self, at, j, tag):
        self.w[at] = ((j - (at + 1)) << 3) | tag

    def put(self, at, v):
        if v is None:
            self.w[at] = 2
        elif isinstance(v, bool):
            self.w[at] = (int(v) << 3) | 3
        elif isinstance(v, (int, float)):
            e = 0 if float(v).is_integer() else 3
            m = round(v * 10 ** e)
            if -(1 << 25) <= m < (1 << 25):
                self.w[at] = ((m << 6) | (e << 3)) & 0xFFFFFFFF
            else:   # 긴 숫자
                j = self.block(2)
                q = ((m << 5) | e) & 0xFFFFFFFFFFFFFFFF
                self.w[j], self.w[j + 1] = q & 0xFFFFFFFF, q >> 32
                self.ptr(at, j, 1)
        elif isinstance(v, str):
            self.w[at] = (self.s(v) << 3) | 4
        elif isinstance(v, list):
            j = self.block(1 + len(v))
            self.w[j] = len(v)
            self.ptr(at, j, 5)
            for k, x in enumerate(v):
                self.put(j + 1 + k, x)
        elif isinstance(v, tuple):
            name, fields = v
            ti = [t[0] for t in self.types].index(name)
            names = self.types[ti][1]
            j = self.block(1 + len(names))
            self.w[j] = ti
            self.ptr(at, j, 6)
            for k, f in enumerate(names):
                self.put(j + 1 + k, fields[f])
        else:   # dict → 사전
            j = self.block(1 + 2 * len(v))
            self.w[j] = len(v)
            self.ptr(at, j, 7)
            for k, (key, x) in enumerate(v.items()):
                self.w[j + 1 + k] = self.s(key)
                self.put(j + 1 + len(v) + k, x)

    def bytes(self, root) -> bytes:
        top = self.block(3)
        self.w[top] = 2
        self.ptr(0, top, 5)
        nt = len(self.types)
        sj = self.block(1 + 2 * nt)
        self.w[sj] = nt
        self.ptr(top + 1, sj, 5)
        for k, (name, fields) in enumerate(self.types):
            self.w[sj + 1 + k] = self.s(name)
            d = self.block(1 + 2 * len(fields))
            self.w[d] = len(fields)
            self.ptr(sj + 1 + nt + k, d, 7)
            for f, fname in enumerate(fields):
                self.w[d + 1 + f] = self.s(fname)
                self.w[d + 1 + len(fields) + f] = (self.s("string") << 3) | 4
        self.put(top + 2, root)
        blob, ends = b"", []
        for x in self.strs:
            blob += x.encode("utf-8")
            ends.append(len(blob))
        blob += b"\0" * (-len(blob) % 4)
        head = b"SJON" + struct.pack("<3I", 1, len(self.strs), len(self.w)) + struct.pack(f"<{len(ends)}I", *ends)
        return head + blob + struct.pack(f"<{len(self.w)}I", *self.w)


class SjonTest(unittest.TestCase):
    def test_round_trip(self):
        e = _Enc([("Pt", ["Name", "X", "Tags"])])
        root = {"list": [("Pt", {"Name": "가", "X": -1.25, "Tags": [1, 2]}), ("Pt", {"Name": "b", "X": 3, "Tags": []})],
                "big": 123456789012, "none": None, "yes": True}
        got = sjon.load(e.bytes(root))
        self.assertEqual(got["list"][0], {"Name": "가", "X": -1.25, "Tags": [1, 2]})
        self.assertEqual(got["list"][1]["X"], 3)
        self.assertEqual(got["big"], 123456789012)
        self.assertIsNone(got["none"])
        self.assertIs(got["yes"], True)

    def test_strings_and_errors(self):
        b = _Enc([]).bytes({"k": "값"})
        self.assertIn("값", sjon.strings(b))
        self.assertIsNone(sjon.strings(b[:20]))           # 잘린 패킷
        self.assertIsNone(sjon.strings(b"XXXX" + b[4:]))
        with self.assertRaises(sjon.SjonError):
            sjon.load(b[:-4])                             # 본문 길이가 안 맞다
        with self.assertRaises(sjon.SjonError):
            sjon.load(b"nope")


def _bdc(ages=(14, 15, 16, 17), base=17):
    """BodyDiversityContainer 모양 dict (기준 나이 Default·Medium 은 크기 1)."""
    cols = []
    for a in ages:
        for shape in B.SHAPES:
            pts = []
            for i, h in enumerate(B.HEIGHTS):
                s = 1.0 if (a == base and shape == "Default" and h == "Medium") else 0.9 + 0.05 * i
                pts.append({"HeightHint": 150 + 10 * i + a, "HeightEnum": h, "BoneLocalScales": [
                    {"BoneName": n, "LocalScaleX": s, "LocalScaleY": s, "LocalScaleZ": s,
                     "LocalPositionX": 0.1, "LocalPositionY": 0, "LocalPositionZ": 0} for n in ("_COM", "_Spine")]})
            cols.append({"Age": a, "BlendshapeName": shape, "HeightDiversityDatapoints": pts})
    return {"HeightDiversityDatapointCollection": cols}


class BodyTest(unittest.TestCase):
    def test_convert_adult_and_child(self):
        d = B.convert(_bdc(), "Female_Body_00")
        self.assertEqual((d["min_age"], d["max_age"], d["base_age"], d["adolescent"]), (14, 17, 17, [17, 14]))
        self.assertEqual(len(d["states"]), 16)
        st = d["states"][0]
        self.assertEqual((st["age"], st["body"]), (14, "Default"))
        self.assertEqual(st["points"]["Tall"]["bones"]["_Spine"]["p"], [0.1, 0, 0])
        kid = B.convert(_bdc((10, 11, 12, 13), 10), "InfantFemale_Body_00")
        self.assertEqual((kid["base_age"], kid["adolescent"]), (10, [10, 13]))

    def test_convert_rejects_broken(self):
        root = _bdc()
        root["HeightDiversityDatapointCollection"][0]["HeightDiversityDatapoints"].pop()
        with self.assertRaises(B.BodyError):
            B.convert(root, "x")                        # 키 점이 모자람
        with self.assertRaises(B.BodyError):
            B.convert({"HeightDiversityDatapointCollection": []}, "x")
        root = _bdc()
        root["HeightDiversityDatapointCollection"] = [c for c in root["HeightDiversityDatapointCollection"]
                                                     if not (c["Age"] == 15 and c["BlendshapeName"] == "Fat")]
        with self.assertRaises(B.BodyError):
            B.convert(root, "x")                        # 빠진 나이·체형

    def test_service_kind(self):
        with tempfile.TemporaryDirectory() as t:
            room = S.DressRoom(Path(t), game_dir=lambda: None)
            self.assertEqual(room._fbx("bdc:Girl"), ("bdc", "Girl"))
            with self.assertRaises(S.DressError):
                room._fbx("bdc:Nope")
            with self.assertRaises(S.DressError):
                room._fbx("bdc:Female:Fat")


if __name__ == "__main__":
    unittest.main()
