"""드레스룸 의상 이펙트 (mabi/dress/fx.py) 와 그 주변 (본 목차·소켓 노드·메시 없는 옷)."""
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

import numpy as np

from mabi import gamefiles as gf
from mabi.dress import catalog as C
from mabi.dress import export as E
from mabi.dress import fx as FX


def _rot(axis: str, deg: float) -> np.ndarray:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return {"x": np.array([[1, 0, 0], [0, c, -s], [0, s, c]]),
            "y": np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]]),
            "z": np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])}[axis]


def _qmat(q) -> np.ndarray:
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def _key(t, v, i=0.0, o=0.0):
    return {"time": t, "value": v, "inSlope": i, "outSlope": o}


def _mmc(state=0, scalar=1.0, mn=0.0, hi=None, lo=None):
    flat = {"m_Curve": []}
    return {"minMaxState": state, "scalar": scalar, "minScalar": mn,
            "maxCurve": {"m_Curve": hi or []} if hi is not None else flat, "minCurve": {"m_Curve": lo or []} if lo is not None else flat}


def _grad(colors, alphas, mode=0):
    """colors [(t, r, g, b)], alphas [(t, a)] → Unity Gradient typetree."""
    g = {"m_NumColorKeys": len(colors), "m_NumAlphaKeys": len(alphas), "m_Mode": mode}
    for i in range(8):
        c = colors[i] if i < len(colors) else (0, 0, 0, 0)
        a = alphas[i] if i < len(alphas) else (0, 0)
        g[f"key{i}"] = {"r": c[1], "g": c[2], "b": c[3], "a": a[1]}
        g[f"ctime{i}"] = int(c[0] * 65535)
        g[f"atime{i}"] = int(a[0] * 65535)
    return g


def _col(r, g, b, a=1.0):
    return {"r": r, "g": g, "b": b, "a": a}


def _mmg(state=0, mx=(1, 1, 1, 1), mn=(0, 0, 0, 0), gmax=None, gmin=None):
    return {"minMaxState": state, "maxColor": _col(*mx), "minColor": _col(*mn),
            "maxGradient": gmax or _grad([(0, 1, 1, 1)], [(0, 1)]), "minGradient": gmin or _grad([(0, 0, 0, 0)], [(0, 1)])}


class CurveTest(unittest.TestCase):
    def test_euler_order_zxy(self):
        e = (30, 50, 70)
        want = _rot("y", 50) @ _rot("x", 30) @ _rot("z", 70)   # Unity: z → x → y
        np.testing.assert_allclose(_qmat(FX.euler_quat(e)), want, atol=1e-4)
        self.assertEqual(FX.euler_quat((0, 0, 0)), [0.0, 0.0, 0.0, 1.0])

    def test_curve_at(self):
        self.assertEqual(FX.curve_at([], 0.5), 0.0)
        keys = [_key(0.2, 1.0, o=0.0), _key(0.8, 3.0, i=0.0)]
        self.assertEqual(FX.curve_at(keys, 0.0), 1.0)        # 범위 밖은 끝 값
        self.assertEqual(FX.curve_at(keys, 1.0), 3.0)
        self.assertAlmostEqual(FX.curve_at(keys, 0.5), 2.0)  # 평평한 접선 — 가운데는 반
        line = [_key(0, 0, o=1), _key(1, 1, i=1)]
        self.assertAlmostEqual(FX.curve_at(line, 0.3), 0.3)
        step = [_key(0, 5, o=math.inf), _key(1, 9, i=math.inf)]
        self.assertEqual(FX.curve_at(step, 0.5), 5.0)        # 계단 접선

    def test_mm(self):
        self.assertEqual(FX.mm(_mmc(0, 2.0)), 2.0)
        self.assertEqual(FX.mm(_mmc(3, 2.0, 0.5), k=2), [1.0, 4.0])
        c = FX.mm(_mmc(1, 2.0, hi=[_key(0, 0, o=1), _key(1, 1, i=1)]))
        self.assertEqual(len(c["c"]), FX.N + 1)
        self.assertEqual((c["c"][0], c["c"][-1]), (0.0, 2.0))
        self.assertNotIn("c2", c)
        c = FX.mm(_mmc(2, 1.0, hi=[_key(0, 1)], lo=[_key(0, 0.25)]))
        self.assertEqual((c["c"][3], c["c2"][3]), (1.0, 0.25))

    def test_gradient(self):
        g = _grad([(0, 0, 0, 0), (1, 1, 0.5, 0)], [(0, 1), (1, 0)])
        self.assertEqual(FX.gradient_at(g, 0.5), [0.5, 0.25, 0.0, 0.5])
        fixed = _grad([(0, 0, 0, 0), (0.5, 1, 1, 1)], [(0, 1)], mode=1)
        self.assertEqual(FX.gradient_at(fixed, 0.25)[:3], [1, 1, 1])   # 계단 — 다음 키 값

    def test_mg(self):
        self.assertEqual(FX.mg(_mmg(0, mx=(1, 0.5, 0, 1))), [1.0, 0.5, 0.0, 1.0])
        self.assertEqual(FX.mg(_mmg(2, mx=(1, 1, 1, 1), mn=(0, 0, 0, 0)))["c"][0], [0.0, 0.0, 0.0, 0.0])
        self.assertEqual(len(FX.mg(_mmg(1))["g"]), FX.N + 1)
        self.assertEqual(set(FX.mg(_mmg(3))), {"g", "g2"})
        self.assertEqual(set(FX.mg(_mmg(4))), {"r"})


def _ps(**over):
    """파티클 시스템 typetree 최소 값 — 모듈은 다 꺼져 있다."""
    off = {"enabled": False}
    ps = {"lengthInSec": 5.0, "looping": True, "prewarm": False, "startDelay": _mmc(0, 0.0), "moveWithTransform": 1,
          "scalingMode": 0,
          "InitialModule": {"startLifetime": _mmc(3, 2.0, 1.0), "startSpeed": _mmc(0, 1.0), "startSize": _mmc(0, 0.1),
                            "startRotation": _mmc(0, 0.0), "startColor": _mmg(0), "gravityModifier": _mmc(0, 0.0),
                            "maxNumParticles": 50, "size3D": False, "rotation3D": False},
          "EmissionModule": off, "ShapeModule": off, "VelocityModule": off, "ClampVelocityModule": off, "SizeModule": off,
          "RotationModule": off, "ColorModule": off, "UVModule": off, "CustomDataModule": off}
    ps.update(over)
    return ps


def _rd(**over):
    r = {"m_RenderMode": 0, "m_RenderAlignment": 0, "m_LengthScale": 2.0, "m_VelocityScale": 0.0, "m_MaxParticleSize": 0.5,
         "m_MinParticleSize": 0.0, "m_Pivot": {"x": 0, "y": 0.5, "z": 0}, "m_Flip": {"x": 0, "y": 0}, "m_SortMode": 0,
         "m_UseCustomVertexStreams": False, "m_VertexStreams": [0, 1, 3, 4, 31]}
    r.update(over)
    return r


class SystemTest(unittest.TestCase):
    def test_basic(self):
        d = FX.system(_ps(), _rd())
        self.assertEqual((d["dur"], d["loop"], d["space"], d["max"]), (5.0, True, 1, 50))
        self.assertEqual(d["life"], [1.0, 2.0])
        for k in ("emit", "shape", "vel", "limit", "sizeOL", "rotOL", "colorOL", "uv", "custom", "size3"):
            self.assertNotIn(k, d)
        self.assertEqual(d["streams"], [])             # 사용자 흐름을 안 쓰면 비운다
        self.assertEqual(d["render"]["pivot"], [0.0, 0.5, 0.0])

    def test_modules(self):
        em = {"enabled": True, "rateOverTime": _mmc(0, 4.0), "rateOverDistance": _mmc(0, 0.0), "m_BurstCount": 1,
              "m_Bursts": [{"time": 0.5, "countCurve": _mmc(0, 3.0), "cycleCount": 2, "repeatInterval": 0.25}, {"time": 9}]}
        vm = {"enabled": True, "inWorldSpace": False, **{k: _mmc(0, 0.0) for k in (
            "x", "y", "z", "radial", "orbitalX", "orbitalY", "orbitalZ", "orbitalOffsetX", "orbitalOffsetY", "orbitalOffsetZ")},
            "speedModifier": _mmc(0, 1.0)}
        vm["orbitalY"] = _mmc(0, 2.0)
        uv = {"enabled": True, "mode": 0, "tilesX": 4, "tilesY": 2, "animationType": 0, "rowIndex": 0,
              "frameOverTime": _mmc(0, 0.0), "startFrame": _mmc(0, 0.0), "cycles": 1.0}
        cd = {"enabled": True, "mode0": 1, "vectorComponentCount0": 2, "vector0_0": _mmc(0, 0.5), "vector0_1": _mmc(0, 1.0),
              "mode1": 2, "color1": _mmg(0)}
        d = FX.system(_ps(EmissionModule=em, VelocityModule=vm, UVModule=uv, CustomDataModule=cd),
                      _rd(m_UseCustomVertexStreams=True))
        self.assertEqual(d["emit"]["bursts"], [[0.5, 3.0, 2, 0.25, 1.0]])   # 개수만큼만
        self.assertEqual(d["vel"]["orb"][1], 2.0)
        self.assertEqual(d["uv"]["tiles"], [4, 2])
        self.assertEqual(d["custom"][0], [0.5, 1.0])
        self.assertIn("color", d["custom"][1])
        self.assertEqual(d["streams"], [0, 1, 3, 4, 31])
        # 궤도가 다 0 이면 싣지 않는다
        vm["orbitalY"] = _mmc(0, 0.0)
        self.assertNotIn("orb", FX.system(_ps(VelocityModule=vm), _rd())["vel"])

    def test_static_has_system_fields(self):
        d = FX.system(_ps(EmissionModule={"enabled": True, "rateOverTime": _mmc(0, 1.0), "rateOverDistance": _mmc(0, 0.0),
                                          "m_BurstCount": 0, "m_Bursts": []}), _rd())
        missing = {k for k in d if k not in ("shape",)} - set(FX.STATIC) - {"name", "m", "mat", "mesh"}
        self.assertEqual(missing, set())                # 보통 메시도 뷰어가 같은 칸으로 읽는다
        self.assertEqual(FX.STATIC["max"], 1)


class _Reader:
    def __init__(self, cols):
        self.cols = list(cols)

    @property
    def done(self):
        return not self.cols

    def s(self):
        return self.cols.pop(0)


class TableTest(unittest.TestCase):
    def test_table(self):
        rows = [("Female_A_Robe_00", ["x", "y", "TL_A", "", "TL_A_Hood"]), ("Monster_X", ["", "", "TL_M"]),
                ("Male_B_Helmet_00", ["", "", "", "", ""]), ("Infant_C_Top_00", ["", "", "TL_C"])]
        keys = iter(r[0] for r in rows)
        sheet = NS(count=len(rows), preload=lambda: NS(s=lambda: next(keys)), reader=lambda i: _Reader(rows[i][1]))
        got = FX.table(NS(sheet=lambda name: sheet))
        self.assertEqual(got, {"Female_A_Robe_00": [["TL_A", False], ["TL_A_Hood", True]], "Infant_C_Top_00": [["TL_C", False]]})

    def test_track(self):
        t = FX._track({"PosRefBoneName": "#MODEL_ROOT", "LocalOffset": [0, 1, 0],
                       "RotationAttachmentInfo": {"EffectAttachmentType": "World"}}, 2, False)
        self.assertEqual((t["fx"], t["bone"], t["rbone"], t["turn"], t["off"]), (2, "", "", False, [0.0, 1.0, 0.0]))
        t = FX._track({"PosRefBoneName": "EffectSocket_Robe_01"}, 0, True)
        self.assertEqual((t["bone"], t["rbone"], t["turn"], t["hood"]), ("EffectSocket_Robe_01", "EffectSocket_Robe_01", True, True))
        self.assertEqual(FX.bones({"tracks": [t, {"bone": "", "rbone": "_Head"}]}), {"EffectSocket_Robe_01", "_Head"})
        self.assertEqual(FX.bones(None), set())

    def test_keep(self):
        self.assertTrue(FX.keep("Assets/PatchableAssets/Fx/1_Effect/Character/0_Common/Fashion/FX_A.prefab"))
        self.assertTrue(FX.keep("Assets/PatchableAssets/Fx/0_Resource/Textures/FX_Noise.png"))
        self.assertTrue(FX.keep("Assets/PatchableAssets/Shaders/MMN/FX/Amplify shader/FX_Default.shader"))
        self.assertFalse(FX.keep("Assets/PatchableAssets/Fx/1_Effect/Monster/FX_B.prefab"))


class SocketTest(unittest.TestCase):
    def test_sockets_with_ancestors(self):
        nodes = [{"path": "R", "parent": -1, "t": [0, 0, 0], "r": [0, 0, 0, 1], "s": [1, 1, 1]},
                 {"path": "R/A", "parent": 0, "t": [1, 0, 0], "r": [0, 0, 0, 1], "s": [1, 1, 1]},
                 {"path": "R/A/EffectSocket_Robe_01", "parent": 1, "t": [0, 2, 0], "r": [0, 0, 0, 1], "s": [1, 1, 1]},
                 {"path": "R/B", "parent": 0, "t": [0, 0, 3], "r": [0, 0, 0, 1], "s": [1, 1, 1]}]
        pack = NS(paths={"p.prefab": 1}, open=lambda paths, limit: [])
        with mock.patch.object(FX.A, "roots", return_value=["go"]), mock.patch.object(FX.E, "skeleton", return_value=(nodes, {})):
            got = FX.sockets(pack, "p.prefab", {"EffectSocket_Robe_01"})
        self.assertEqual([n["path"] for n in got], ["R", "R/A", "R/A/EffectSocket_Robe_01"])
        self.assertNotIn("parent", got[0])
        self.assertEqual(FX.sockets(pack, "", {"x"}), [])
        self.assertEqual(FX.sockets(pack, "none.prefab", {"x"}), [])

    def test_add_nodes(self):
        nodes = [{"path": "R", "parent": -1, "t": [0, 0, 0], "r": [0, 0, 0, 1], "s": [1, 1, 1]}]
        more = [{"path": "R", "t": [9, 9, 9], "r": [0, 0, 0, 1], "s": [1, 1, 1]},        # 이미 있다
                {"path": "R/S", "t": [1, 0, 0], "r": [0, 0, 0, 1], "s": [1, 1, 1]},
                {"path": "Q/T", "t": [1, 0, 0], "r": [0, 0, 0, 1], "s": [1, 1, 1]}]      # 부모가 없다
        E.add_nodes(nodes, more)
        self.assertEqual([(n["path"], n["parent"]) for n in nodes], [("R", -1), ("R/S", 0)])
        self.assertEqual(nodes[0]["t"], [0, 0, 0])

    def test_item_prefab_not_in_dict(self):
        item = C.Item("Female_A_Robe_00", "Female", "Robe", "A", "a.fbx", prefab="a.prefab")
        self.assertEqual(item.prefab, "a.prefab")
        self.assertNotIn("prefab", item.to_dict())


class ExportMoreTest(unittest.TestCase):
    def test_sockets_added_after_meshes(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "m.json"
            nodes = [{"path": "R", "parent": -1, "t": [0, 0, 0], "r": [0, 0, 0, 1], "s": [1, 1, 1]}]
            ex = E.Exporter(NS(), Path(d))
            with mock.patch.object(E.Exporter, "_root", return_value=None), \
                    mock.patch.object(E, "skeleton", return_value=(nodes, {})), \
                    mock.patch.object(E.Exporter, "_meshes", return_value=[{"name": "Mesh_A"}]):
                meta = ex.run("a/Item.fbx", out, extra={"fx": {"tracks": []}},
                              more=[{"path": "R/EffectSocket_Robe_01", "t": [0, 1, 0], "r": [0, 0, 0, 1], "s": [1, 1, 1]}])
                self.assertEqual([n["path"] for n in meta["skeleton"]], ["R", "R/EffectSocket_Robe_01"])
                self.assertIn("fx", meta)
                with mock.patch.object(E.Exporter, "_meshes", return_value=[]), self.assertRaises(E.ExportError):
                    ex.run("a/Item.fbx", out, extra={"fx": {"tracks": []}})   # 메시가 없으면 이펙트가 있어도 못 그린다


class ResourcesTest(unittest.TestCase):
    def test_main_index(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "ResourcesPackage" / "Starter").mkdir(parents=True)
            (root / "ResourcesPackage" / "Starter" / "index").write_bytes(b"S")
            (root / "ResourcesPackage" / "index").write_bytes(b"MM")
            tables = {b"S": {"a": (0x8001, 1), "b": (0x8001, 2)}, b"MM": {"b": (3, 9), "c": (4, 1)}}
            with mock.patch.object(gf, "parse_index", side_effect=lambda data, want: dict(tables[data])):
                only = gf.Resources(root)
                both = gf.Resources(root, main=True)
            self.assertEqual(set(only.paths), {"a", "b"})
            self.assertEqual(both.paths, {"a": (0x8001, 1), "b": (0x8001, 2), "c": (4, 1)})   # 같은 경로는 Starter 것
            self.assertEqual(len(only.stamp()), 2)
            self.assertEqual(len(both.stamp()), 4)
            self.assertEqual(both.stamp()[2], 2)          # 본 목차 크기
            self.assertEqual(gf.res_stamp(root), both.stamp())   # 캐시 기준 — 두 목차
            (root / "ResourcesPackage" / "index").unlink()
            self.assertEqual(gf.res_stamp(root), only.stamp())   # 본 목차가 없으면 Starter 것만


if __name__ == "__main__":
    unittest.main()
