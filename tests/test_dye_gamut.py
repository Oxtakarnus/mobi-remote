"""염색 재질 판정 (mabi.dye.gamut · materials · gamefiles) — 합성 재질 그림으로. 게임 파일은 쓰지 않는다."""
import struct
import tempfile
import time
import unittest
import zlib
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

from mabi import gamefiles as gf
from mabi.dye import gamut as G
from mabi.dye import materials as M
from mabi.dye.tracker import NOTE_EDGE, NOTE_NONE, NOTE_OFF, DyeTracker


def pal(rgb_rows) -> np.ndarray:
    """RGB 줄 목록 → BGR 그림 (materials.load 와 같은 모양)."""
    a = np.asarray(rgb_rows, np.uint8)
    return a[..., ::-1].copy()


def solid(rgb, n=8):
    return pal([[rgb] * n] * n)


class ReachTest(unittest.TestCase):
    def setUp(self):
        cloth = solid((100, 50, 50))
        cloth[0, :5] = (60, 60, 200)[::-1]            # 5 텍셀만 다른 색 (BGR 로 넣는다)
        self.g = G.Gamut({"Cloth": cloth, "Metal": solid((120, 120, 120))})

    def test_levels_by_area(self):
        r = self.g.reach((100, 50, 50), 3, "Cloth")
        self.assertEqual((r.level, r.count, r.near, r.diff), ("wide", 59, "#643232", 0))
        r = self.g.reach((60, 60, 200), 0, "Cloth")
        self.assertEqual((r.level, r.count), ("narrow", 5))   # 5개 < 6 = 좁음
        r = self.g.reach((100, 50, 50), 5, "Metal")
        self.assertEqual((r.level, r.count, r.near, r.diff), ("none", 0, "#787878", 70))

    def test_tolerance_is_per_channel(self):
        self.assertEqual(self.g.reach((104, 54, 46), 4, "Cloth").level, "wide")
        self.assertEqual(self.g.reach((105, 50, 50), 4, "Cloth").level, "none")

    def test_edge_between_neighbours(self):
        # 이웃 텍셀 (100,0,0)·(200,0,0) 사이 섞임은 나오지만, 떨어진 두 텍셀 사이는 아니다
        g = G.Gamut({"Wood": pal([[(100, 10, 10), (200, 10, 10), (100, 10, 10), (90, 90, 90)]])})
        self.assertEqual(g.reach((150, 10, 10), 2, "Wood").level, "edge")
        self.assertEqual(g.reach((150, 50, 50), 2, "Wood").level, "none")
        self.assertEqual(g.reach((95, 50, 50), 3, "Wood").level, "edge")   # (100,10,10)–(90,90,90) 사이

    def test_black_edge_column_dropped(self):
        p = solid((90, 90, 90), 4)
        p[:, -1] = 0                                   # Cloth.bmp 253열처럼 통째로 검정
        g = G.Gamut({"Cloth": p})
        self.assertEqual(g.reach((0, 0, 0), 5, "Cloth").level, "none")

    def test_judge_all_materials(self):
        rs = self.g.judge((120, 120, 120), 2)
        self.assertEqual([r.mat for r in rs], ["Cloth", "Metal"])
        d = rs[1].to_dict()
        self.assertEqual((d["name"], d["label"]), ("금속", "넉넉"))


class MaterialOfTest(unittest.TestCase):
    def test_band_pixels_pick_material(self):
        rng = np.random.default_rng(3)
        cloth = rng.integers(0, 256, (16, 16, 3), dtype=np.uint8)
        metal = np.repeat(rng.integers(100, 160, (16, 16, 1), dtype=np.uint8), 3, axis=2)   # 회색만
        g = G.Gamut({"Cloth": cloth, "Metal": metal})
        self.assertEqual(g.material_of(cloth[..., ::-1].reshape(-1, 3)), "Cloth")
        self.assertEqual(g.material_of(metal[..., ::-1].reshape(-1, 3)), "Metal")
        self.assertIsNone(g.material_of(np.zeros((0, 3), np.uint8)))

    def test_single_material_is_known(self):
        g = G.Gamut({"Cloth": solid((1, 2, 3))})
        self.assertEqual(g.material_of(np.full((5, 3), 250)), "Cloth")


class StoreTest(unittest.TestCase):
    def test_retries_after_failure_and_memoizes(self):
        s = G.GamutStore(Path("unused"), game_dir=lambda: None)
        with mock.patch.object(M, "load", side_effect=[None, {"Cloth": solid((9, 9, 9))}]) as ld:
            self.assertIsNone(s.get())
            self.assertIsNone(s.get())                 # RETRY 초 안에는 다시 안 꺼낸다
            s._tried = time.monotonic() - s.RETRY - 1
            self.assertIsNotNone(s.get())
            self.assertEqual(ld.call_count, 2)
        with mock.patch.object(G.Gamut, "reach", wraps=s._g.reach) as r:
            s.reach((9, 9, 9), 1, "Cloth")
            s.reach((9, 9, 9), 1, "Cloth")
            self.assertEqual(r.call_count, 1)
        self.assertIsNone(s.reach((9, 9, 9), 1, "Metal"))  # 없는 재질

    def test_broken_game_files_do_not_raise(self):
        s = G.GamutStore(Path("unused"), game_dir=lambda: None)
        with mock.patch.object(M, "load", side_effect=struct.error("bad index")):
            self.assertIsNone(s.get())


class MaterialsCacheTest(unittest.TestCase):
    def test_cache_used_without_game_and_refreshed_on_patch(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            cache, game = d / "캐시", d / "game"
            idx = gf.index_of(game)
            idx.parent.mkdir(parents=True)
            idx.write_bytes(b"x")
            imgs = {n: np.full((M.TEX, M.TEX, 3), i * 40, np.uint8) for i, n in enumerate(M.NAMES)}
            self.assertIsNone(M.load(cache, None))
            with mock.patch.object(M, "_extract", return_value=imgs) as ex:
                out = M.load(cache, game)                  # 처음: 게임에서 꺼내 복사본을 둔다 (한글 경로)
                self.assertEqual(ex.call_count, 1)
                self.assertTrue((cache / "Cloth.png").exists())
                M.load(cache, game)                        # 목차 그대로 → 복사본
                self.assertEqual(ex.call_count, 1)
                idx.write_bytes(b"patched")                # 게임 패치 → 다시 꺼낸다
                M.load(cache, game)
                self.assertEqual(ex.call_count, 2)
            self.assertTrue(np.array_equal(M.load(cache, None)["Metal"], out["Metal"]))  # 게임이 없어도 복사본


class BlobTest(unittest.TestCase):
    def test_entry_roundtrip(self):
        """묶음 = [?, 오프셋 표 크기] + 오프셋 표 + 항목들, 항목 = XOR(4바이트 크기 + raw deflate)."""
        datas = [b"hello dye" * 20, b"second"]
        bodies = []
        for x in datas:
            c = zlib.compressobj(9, zlib.DEFLATED, -15)
            bodies.append(struct.pack("<I", len(x)) + c.compress(x) + c.flush())
        n = 4 * (len(bodies) + 1)
        offs, at = [], 8 + n
        for b in bodies:
            offs.append(at)
            at += len(b)
        offs.append(at)
        blob = struct.pack("<II", 0, n) + struct.pack("<%dI" % len(offs), *offs)
        for i, b in enumerate(bodies):
            blob += gf._unxor(b, offs[i], len(b))      # XOR 은 되풀이하면 원래대로
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "0001.blob"
            f.write_bytes(blob)
            self.assertEqual(gf._entry(f, 0), datas[0])
            self.assertEqual(gf._entry(f, 1), datas[1])


class FakeStore:
    def __init__(self, g):
        self.g = g

    def get(self):
        return self.g

    def reach(self, rgb, tol, mat):
        return self.g.reach(rgb, tol, mat)


class TrackerNoteTest(unittest.TestCase):
    def test_note_by_band_materials(self):
        g = G.Gamut({"Cloth": pal([[(100, 10, 10), (200, 10, 10)]] * 2), "Metal": solid((120, 120, 120))})
        t = DyeTracker()
        t.set_gamut(FakeStore(g))
        t.set_targets(["#646464", "#960A0A", "#787878"], [3, 3, 3])
        tg = t._targets
        t.mats = ["Cloth", "Cloth", "Cloth"]
        self.assertEqual(t._note(tg[0]), NOTE_NONE)      # 천에는 회색이 없다
        self.assertEqual(t._note(tg[1]), NOTE_EDGE)      # 천 두 색 사이 섞임뿐
        self.assertEqual(t._note(tg[2]), NOTE_NONE)
        t.mats = ["Cloth", "Metal", "Cloth"]
        self.assertEqual(t._note(tg[2]), NOTE_OFF)       # 금속 칸에는 있다 → 화면 밖
        t.mats = None
        self.assertEqual(t._note(tg[2]), "")             # 칸 재질을 모르면 아무 말 안 한다

    def test_chip_shows_note(self):
        from mabi.dye import draw
        from mabi.dye.tracker import DyeState
        st = DyeState("active", "x", "ok", chips=[("#123456", False, 0, NOTE_NONE), ("#654321", True, 1, "")])
        texts = [it.text for it in draw.overlay_items(st) if getattr(it, "kind", "") == "text"]
        self.assertIn("#123456 · 없음", texts)
        self.assertIn("#654321", texts)


class ApiReachTest(unittest.TestCase):
    def test_reach_per_color(self):
        from gui_app.api import Api
        a = Api.__new__(Api)
        a.gamut = FakeStore(G.Gamut({"Cloth": solid((10, 20, 30))}))
        a.gamut.judge = lambda rgb, tol: a.gamut.g.judge(rgb, tol)
        r = a.dye_reach(["#0A141E", "", "#FFFFFF"], [0, 5, 5])
        self.assertEqual([len(x) for x in r["colors"]], [1, 0, 1])
        self.assertEqual(r["colors"][0][0]["level"], "wide")
        self.assertEqual(r["colors"][2][0]["level"], "none")
        a.gamut.judge = lambda rgb, tol: None
        self.assertIn("error", a.dye_reach(["#0A141E"], [5]))


if __name__ == "__main__":
    unittest.main()
