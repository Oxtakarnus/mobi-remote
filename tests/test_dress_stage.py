"""환생 무대·조명 프리셋 (mabi.dress.stage) — 가짜 자료와 임시 폴더로. 게임 파일은 쓰지 않는다."""
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from mabi.dress import service as S
from mabi.dress import stage as ST

# 환생 볼륨(IngameCustomize) MainLight.Rotation
REBIRTH_Q = [-0.5148915, -0.6255671, 0.5804638, -0.08132947]


def _close(tc, a, b, places=3):
    tc.assertEqual(len(a), len(b))
    for x, y in zip(a, b):
        tc.assertAlmostEqual(x, y, places=places)


class DirectionTest(unittest.TestCase):
    def test_rebirth_direction(self):
        # 앞 = q·(0,0,1), 빛 쪽 = −앞, 뷰어는 x 를 뒤집는다 → 참고 뷰어의 기본 방향과 같다
        _close(self, ST.forward(REBIRTH_Q), [-0.496, -0.810, -0.313])
        _close(self, ST.light_direction(REBIRTH_Q), [-0.496, 0.810, 0.313])

    def test_identity_points_back(self):
        _close(self, ST.light_direction([0, 0, 0, 1]), [0.0, 0.0, -1.0])

    def test_unit_length(self):
        d = ST.light_direction([0.3, -0.2, 0.5, 0.7])   # 정규화 안 된 쿼터니언도
        self.assertAlmostEqual(math.sqrt(sum(v * v for v in d)), 1.0, places=6)


class SampleTest(unittest.TestCase):
    def test_single_key(self):
        self.assertEqual(ST.sample([(0.3, [1, 2, 3])], 0.9), [1, 2, 3])
        self.assertIsNone(ST.sample([], 0.5))

    def test_linear(self):
        keys = [(0.2, 0.0), (0.6, 4.0)]
        self.assertAlmostEqual(ST.sample(keys, 0.4), 2.0)
        self.assertAlmostEqual(ST.sample(keys, 0.2), 0.0)
        _close(self, ST.sample([(0.0, [0, 0, 0]), (0.5, [1, 2, 4])], 0.25), [0.5, 1.0, 2.0])

    def test_wraps_day(self):
        keys = [(0.25, 0.0), (0.75, 1.0)]
        # 0.75 → 다음 날 0.25 사이 (반 바퀴): 0.0 은 그 가운데, 0.9 는 0.15/0.5 지점
        self.assertAlmostEqual(ST.sample(keys, 0.0), 0.5)
        self.assertAlmostEqual(ST.sample(keys, 0.9), 0.7)
        self.assertAlmostEqual(ST.sample(keys, 1.0), 0.5)

    def test_rotation_slerp(self):
        h = math.sqrt(0.5)
        q = ST.sample([(0.0, [0, 0, 0, 1]), (0.5, [0, h, 0, h])], 0.25, rot=True)   # 0° → y 축 90° 의 절반
        _close(self, q, [0, math.sin(math.pi / 8), 0, math.cos(math.pi / 8)], places=5)
        # 부호 반대인 같은 회전은 짧은 쪽으로
        q2 = ST.sample([(0.0, [0, 0, 0, 1]), (0.5, [0, 0, 0, -1])], 0.25, rot=True)
        _close(self, q2, [0, 0, 0, 1], places=5)

    def test_mismatched_values_step(self):
        self.assertEqual(ST.sample([(0.0, "a"), (0.5, "b")], 0.2), "a")
        self.assertEqual(ST.sample([(0.0, "a"), (0.5, "b")], 0.4), "b")


class VolumeTest(unittest.TestCase):
    def test_tracks(self):
        v = ST.Volume({"GlobalGroup": {"KeyFrames": [
            {"Time": 0.5, "MainLight": {"Intensity": 2.0, "Color": None}, "Skybox": None},
            {"Time": 0.0, "MainLight": {"Intensity": 1.0}},
            {"Time": 0.1, "GlobalEnvironment": {"Night2Day": 1}},
        ]}})
        self.assertEqual(v.tracks["MainLight.Intensity"], [(0.0, 1.0), (0.5, 2.0)])
        self.assertNotIn("MainLight.Color", v.tracks)
        self.assertAlmostEqual(v.at(0.25)["MainLight.Intensity"], 1.5)
        self.assertEqual(v.at(0.9)["GlobalEnvironment.Night2Day"], 1)

    def test_empty(self):
        self.assertEqual(ST.Volume({}).at(0.5), {})


def _rebirth_raw():
    return {
        "MainLight.Rotation": REBIRTH_Q, "MainLight.Color": [0.95, 0.95, 0.95, 1], "MainLight.Intensity": 1,
        "MainLight.ShadowIntensity": 1, "GlobalEnvironment.GILightColor": [0.15, 0.15, 0.15, 1],
        "GlobalEnvironment.Night2Day": 1, "GlobalEnvironment.FogColor": [0.0039, 0.0353, 0.1216, 1],
        "GlobalEnvironment.FogStartDistance": 2, "GlobalEnvironment.FogEndDistance": 10.95,
        "GlobalEnvironment.DimFogRange": 8.34, "GlobalEnvironment.DimFogPower": 0.7,
        "CharacterLight.LightColor": [0, 0, 0, 0], "CharacterLight.GIColor": [0, 0, 0, 0],
        "CharacterLight.SilhouetteColor": [0, 0, 0, 0],
        "Skybox.SkyColorTop": [0.0566, 0, 0.0148, 1], "Skybox.SkyPosition1": -0.3, "Skybox.SkyPosition4": 0.5,
        "PostProcessing.AmbientGradientDarkSideColor": [0, 0.197, 0.509, 1],
        "PostProcessing.AmbientGradientLightSideColor": [0.643, 0.0657, 0, 1],
    }


class PresetTest(unittest.TestCase):
    def test_rebirth_values(self):
        p = ST.preset(_rebirth_raw())
        _close(self, p["direction"], [-0.496, 0.810, 0.313])
        _close(self, p["direct"], [0.95] * 3)
        _close(self, p["indirect"], [0.15] * 3)
        self.assertNotIn("character_light", p)   # 알파 0 = 덮어쓰지 않음
        self.assertEqual(p["silhouette"], [0.0, 0.0, 0.0, 0.0])
        self.assertEqual(p["fog"], {"color": [0.0039, 0.0353, 0.1216], "start": 2.0, "end": 10.95,
                                    "dim_range": 8.34, "dim_power": 0.7})
        self.assertEqual(p["sky"]["positions"], [-0.3, 0.0, 0.0, 0.5])
        _close(self, p["gradient"]["dark"], [0, 0.197, 0.509])
        _close(self, p["gradient"]["main"], p["direct"])
        _close(self, p["background_srgb"], [ST.srgb(c) for c in p["fog"]["color"]])
        self.assertEqual(p["ambient_sh"], ST.flat_sh())
        self.assertEqual(p["lights"], [])
        json.dumps(p)

    def test_intensity_and_character_light(self):
        raw = dict(_rebirth_raw(), **{"MainLight.Intensity": 2.0, "CharacterLight.LightColor": [0.5, 0.5, 0.5, 1.0],
                                      "CharacterLight.GIColor": [0.35, 0.15, 0.15, 0.5]})
        p = ST.preset(raw)
        _close(self, p["direct"], [1.9] * 3)
        _close(self, p["character_light"]["direct"], [0.5] * 3)
        _close(self, p["character_light"]["indirect"], [0.25, 0.15, 0.15])

    def test_missing_values_default(self):
        p = ST.preset({})
        _close(self, p["direction"], [0, 0, -1])
        self.assertEqual(p["direct"], [1.0, 1.0, 1.0])
        self.assertEqual(p["gradient"]["dark"], [1.0, 1.0, 1.0])

    def test_srgb_roundtrip(self):
        for c in (0.0, 0.002, 0.2, 0.5, 1.0):
            self.assertAlmostEqual(ST.linear(ST.srgb(c)), c, places=6)
        self.assertAlmostEqual(ST.linear(0.5), 0.2140, places=4)


class ShTest(unittest.TestCase):
    def _coef(self, **kw):
        c = [0.0] * 27
        for k, v in kw.items():   # r0=… 처럼 색·번호
            c["rgb".index(k[0]) * 9 + int(k[1:])] = v
        return c

    def test_constant(self):
        t = ST.sh_terms(self._coef(r0=1.0, g0=0.5, b0=0.25))
        _close(self, ST.eval_sh(t, (0, 1, 0)), [1.0, 0.5, 0.25])

    def test_axes_and_flip(self):
        # Unity 계수 3 = x, 1 = y, 2 = z. 뷰어 축은 x 가 뒤집혀 Unity +x 가 뷰어 −x
        t = ST.sh_terms(self._coef(r0=1.0, r3=0.5, r1=0.25, r2=0.125))
        self.assertAlmostEqual(ST.eval_sh(t, (-1, 0, 0))[0], 1.5)
        self.assertAlmostEqual(ST.eval_sh(t, (0, 1, 0))[0], 1.25)
        self.assertAlmostEqual(ST.eval_sh(t, (0, 0, 1))[0], 1.125)

    def test_zz_term(self):
        # 상수 = c0 − c6, zz = 3·c6 → z 방향은 c0 + 2·c6, 옆은 c0 − c6
        t = ST.sh_terms(self._coef(g0=1.0, g6=0.1))
        self.assertAlmostEqual(ST.eval_sh(t, (0, 0, 1))[1], 1.2)
        self.assertAlmostEqual(ST.eval_sh(t, (0, 1, 0))[1], 0.9)

    def test_cross_terms_flip(self):
        h = math.sqrt(0.5)
        t = ST.sh_terms(self._coef(b4=0.4, b7=0.2, b8=0.1))   # xy, xz, x²−y²
        # Unity n = (h, h, 0) 은 뷰어 (−h, h, 0): xy 항 0.4·h·h, c 항 0
        self.assertAlmostEqual(ST.eval_sh(t, (-h, h, 0))[2], 0.2)
        self.assertAlmostEqual(ST.eval_sh(t, (-h, 0, h))[2], 0.1 + 0.05)

    def test_probe_coefs(self):
        tree = {"m_Data": {"m_Positions": [{"x": 1, "y": 2, "z": 3}]},
                "m_BakedCoefficients": [{f"sh[{i:2d}]": float(i) for i in range(27)}]}
        pos, coefs = ST.probe_coefs(tree)
        self.assertEqual(pos, [[1.0, 2.0, 3.0]])
        self.assertEqual(coefs, [[float(i) for i in range(27)]])


class GeometryTest(unittest.TestCase):
    def test_world_matrices(self):
        h = math.sqrt(0.5)
        nodes = [{"path": "a", "parent": -1, "t": [1, 0, 0], "r": [0, h, 0, h], "s": [1, 1, 1]},   # y 축 90°
                 {"path": "a/b", "parent": 0, "t": [0, 0, 2], "r": [0, 0, 0, 1], "s": [1, 1, 1]}]
        w = ST.world_matrices(nodes)
        _close(self, w["a/b"][:3, 3], [3.0, 0.0, 0.0], places=6)   # 자식 +z 2 가 부모 회전으로 +x 2
        base = np.eye(4)
        base[1, 3] = 5
        _close(self, ST.world_matrices(nodes, base)["a"][:3, 3], [1.0, 5.0, 0.0], places=6)

    def test_cols(self):
        nrm4 = [(0.0, 1.0, 0.0, 0.0)] * 3   # 4성분으로 저장된 법선
        a = ST._cols(nrm4, 3, 3)
        self.assertEqual(a.shape, (3, 3))
        self.assertTrue(a.flags["C_CONTIGUOUS"])
        self.assertIsNone(ST._cols(nrm4, 4, 3))      # 개수가 다르면 없음
        self.assertIsNone(ST._cols([(1.0, 2.0)] * 3, 3, 3))   # 성분이 모자라면 없음
        self.assertIsNone(ST._cols(None, 3, 3))


class _FakeRes:
    def __init__(self, files):
        self.files = files
        self.paths = {p: (0, 0) for p in files}

    def find(self, tail):
        return next((p for p in self.paths if p.endswith(tail)), None)

    def read(self, path):
        return path


def _vol(keys):
    return {"GlobalGroup": {"KeyFrames": keys}}


class PresetsTest(unittest.TestCase):
    def setUp(self):
        self.vols = {
            "VolumeData/IngameCustomize.volume.sjon.bin": _vol([{"Time": 0, "MainLight": {"Rotation": REBIRTH_Q}}]),
            "VolumeData/TirChonaillGlobal.volume.sjon.bin": _vol([
                {"Time": 0.0, "GlobalEnvironment": {"Night2Day": 0}},
                {"Time": 0.5, "GlobalEnvironment": {"Night2Day": 1}},
            ]),
        }
        self.reads = []

    def _load(self, path):
        self.reads.append(path)
        return self.vols[path]

    def test_presets(self):
        lighting = {"lights": [{"kind": "point", "position": [0, 1, 0], "color": [1, 1, 1], "range": 2}],
                    "ambient_sh": ST.flat_sh(0.5)}
        with mock.patch.object(ST.gf, "Resources", lambda gd, want: _FakeRes(self.vols)), \
                mock.patch.object(ST.sjon, "load", self._load):
            meta = ST.presets(Path("."), lighting)
        p = meta["presets"]
        self.assertEqual(set(p), {"rebirth", "noon", "night"})
        self.assertEqual(len(self.reads), 2)   # 야외 둘은 한 볼륨을 같이 쓴다
        _close(self, p["rebirth"]["direction"], [-0.496, 0.810, 0.313])
        self.assertEqual(p["rebirth"]["lights"], lighting["lights"])
        self.assertEqual(p["rebirth"]["ambient_sh"], ST.flat_sh(0.5))
        self.assertEqual(p["noon"]["lights"], [])
        self.assertEqual(p["noon"]["ambient_sh"], ST.flat_sh())
        self.assertEqual((p["noon"]["night2day"], p["night"]["night2day"]), (1.0, 0.0))
        self.assertEqual(p["night"]["source"], {"volume": "VolumeData/TirChonaillGlobal.volume.sjon.bin", "time": 0.0})
        self.assertIn("raw", p["noon"])
        self.assertIn("ambient_sh", meta["guess"])
        json.dumps(meta, ensure_ascii=False)

    def test_missing_volume(self):
        del self.vols["VolumeData/TirChonaillGlobal.volume.sjon.bin"]
        with mock.patch.object(ST.gf, "Resources", lambda gd, want: _FakeRes(self.vols)), \
                mock.patch.object(ST.sjon, "load", self._load):
            with self.assertRaises(ST.StageError):
                ST.presets(Path("."))


class ServiceHookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.room = S.DressRoom(self.dir, game_dir=lambda: Path("game"))
        self.room.pack = lambda: None   # 게임 목차 없이

    def tearDown(self):
        self.tmp.cleanup()

    def test_model_routes_to_stage(self):
        calls = []

        def fake(mid, gd, data, out):
            calls.append((mid, gd, data, out))
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("{}")

        with mock.patch.object(ST, "export", fake):
            self.assertEqual(self.room.model("light:presets"), "models/light_presets.json")
            self.assertEqual(self.room.model("light:presets"), "models/light_presets.json")   # 두 번째는 캐시
            self.assertEqual(self.room.model("stage:rebirth"), "models/stage_rebirth.json")
        self.assertEqual([c[0] for c in calls], ["light:presets", "stage:rebirth"])
        self.assertEqual(calls[0][1:], (Path("game"), self.dir, self.dir / "models" / "light_presets.json"))

    def test_stage_error_becomes_dress_error(self):
        def boom(*a):
            raise ST.StageError("무대 없음")

        with mock.patch.object(ST, "export", boom):
            with self.assertRaises(S.DressError):
                self.room.model("stage:rebirth")

    def test_unknown_stage_id(self):
        with self.assertRaises(ST.StageError):
            ST.export("stage:nowhere", Path("."), self.dir, self.dir / "x.json")

    def test_presets_cleared_with_names(self):
        (self.dir / "models").mkdir()
        for n in ("light_presets.json", "bdc_Female.json", "stage_rebirth.json"):
            (self.dir / "models" / n).write_text("{}")
        with mock.patch.object(S.NM, "load", lambda d, gd: ({}, True)):
            self.room._load_names(Path("game"))
        left = sorted(p.name for p in (self.dir / "models").iterdir())
        self.assertEqual(left, ["stage_rebirth.json"])   # 무대는 AssetPackages 쪽 stamp 로 비운다


if __name__ == "__main__":
    unittest.main()
