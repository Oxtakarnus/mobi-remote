"""옷·머리 흔들림 자료 꺼내기 (mabi.dress.cloth) — 가짜 typetree·가짜 UnityPy 객체로. 게임 파일은 쓰지 않는다."""
import unittest
from types import SimpleNamespace as NS
from unittest import mock

from mabi.dress import cloth as CL


def P(obj, pid=0):
    """가리킴 — deref() 로 obj."""
    return NS(deref=lambda: obj, m_PathID=pid)


class R:
    """ObjectReader 흉내 — read() 는 값, read_typetree() 는 사전."""

    def __init__(self, tname, val=None, tt=None, f=None):
        self.type = NS(name=tname)
        self._val, self._tt, self.assets_file = val, tt, f

    def read(self):
        return self._val

    def read_typetree(self):
        return self._tt


def mono(script, tt=None, f=None):
    return R("MonoBehaviour", NS(m_Script=P(NS(read=lambda: NS(m_ClassName=script)))), tt, f)


def V(x, y, z):
    """read() 값의 벡터."""
    return NS(x=x, y=y, z=z)


def T(x, y, z):
    """typetree 의 벡터 (사전)."""
    return {"x": x, "y": y, "z": z}


def node(name, gid, tid, comps=(), children=(), t=(0.0, 0.0, 0.0)):
    """GameObject 하나와 그 Transform — children 은 node 결과."""
    tr = R("Transform")
    go = NS(m_Name=name, m_Component=[NS(component=P(tr))] + [NS(component=P(c)) for c in comps])
    tr._val = NS(m_LocalPosition=V(*t), m_LocalRotation=NS(x=0.0, y=0.0, z=0.0, w=1.0), m_LocalScale=V(1.0, 1.0, 1.0),
                 m_Children=[P(c.tr, c.tid) for c in children], m_GameObject=P(NS(read=lambda: go), gid))
    return NS(tr=tr, tid=tid, go=go, gid=gid)


def curve(a, b=0.0, use_end=0, c=0.0, use_curve=0):
    return {"startValue": a, "endValue": b, "useEndValue": use_end, "curveValue": c, "useCurveValue": use_curve}


def data_tt():
    """뼈 셋(골반 고정 → 치마 두 마디) 의 ClothData."""
    return {
        "useVertexList": [0, 1, 2],
        "selectionData": [2, 1, 1],
        "vertexDepthList": [0.0, 0.5, 1.0],
        "parentList": [-1, 0, 1],
        "structDistanceDataList": [{"vertexIndex": 1, "targetVertexIndex": 0, "length": 0.1},
                                   {"vertexIndex": 2, "targetVertexIndex": 1, "length": 0.12}],
        "rootDistanceDataList": [{"vertexIndex": 2, "targetVertexIndex": 0, "length": 0.22}],
        "compositeRotationDataList": [{"vertexIndex": 1, "parentVertexIndex": 0, "localPos": T(0.0, -1.0, 0.0),
                                       "localRot": {"value": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}}}],
        "triangleBendDataList": [],
        "penetrationDataList": [
            {"vertexIndex": 1, "colliderIndex": 0, "localPos": T(0.0, 0.0, 0.1), "localDir": T(0.0, 0.0, 1.0), "distance": 0.02},
            {"vertexIndex": 2, "colliderIndex": 1, "localPos": T(0.0, 0.0, 0.1), "localDir": T(0.0, 0.0, 1.0), "distance": 0.03},
        ],
    }


class TestPieces(unittest.TestCase):
    def test_params(self):
        out = CL.params({"algorithm": 1, "gravity": curve(-2.0), "radius": curve(0.01, 0.05, 1, -0.5, 1),
                         "gravityDirection": {"x": 0, "y": 1, "z": 0}, "virtualParent": {"m_FileID": 0, "m_PathID": 9},
                         "useCollision": 1})
        self.assertEqual(out["algorithm"], 1)
        self.assertEqual(out["gravity"], [-2.0, 0.0, 0, 0.0, 0])
        self.assertEqual(out["radius"], [0.01, 0.05, 1, -0.5, 1])
        self.assertEqual(out["gravityDirection"], [0.0, 1.0, 0.0])
        self.assertNotIn("virtualParent", out)          # 가리킴은 뺀다

    def test_collider(self):
        cap = CL.collider("capsule", {"center": T(0, 0.1, 0), "axis": 1, "length": 0.15, "startRadius": 0.06, "endRadius": 0.04},
                          "_COM/_Pelvis/_L Thigh", {"t": [0, 0, 0], "r": [0, 0, 0, 1], "s": [1, 1, 1]})
        self.assertEqual((cap["kind"], cap["axis"], cap["length"], cap["r0"], cap["r1"]), ("capsule", 1, 0.15, 0.06, 0.04))
        self.assertEqual(cap["bone"], "_COM/_Pelvis/_L Thigh")
        sph = CL.collider("sphere", {"center": T(0, 0, 0), "radius": 0.1}, "_Head", {"t": [0, 0, 0], "r": [0, 0, 0, 1], "s": [1, 1, 1]})
        self.assertEqual((sph["r0"], sph["r1"], sph["length"]), (0.1, 0.1, 0.0))

    def test_team_flat_lists(self):
        paths = ["_COM/_Pelvis", "_COM/_Pelvis/S0", "_COM/_Pelvis/S0/S1"]
        t = CL.team("치마", {"clothParams": {"mass": curve(10.0, 1.0, 1)}}, data_tt(), paths, [{"kind": "capsule"}, None])
        self.assertEqual(t["verts"], paths)
        self.assertEqual(t["sel"], [2, 1, 1])
        self.assertEqual(t["struct"], [1, 0, 0.1, 2, 1, 0.12])
        self.assertEqual(t["root"], [2, 0, 0.22])
        self.assertEqual(t["comp"], [1, 0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0, 1.0])
        # 못 읽은 콜라이더(1번)를 가리키는 파고들기 줄은 빠진다
        self.assertEqual(t["pen"], [1, 0, 0.0, 0.0, 0.1, 0.0, 0.0, 1.0, 0.02])
        self.assertEqual(t["params"]["mass"], [10.0, 1.0, 1, 0.0, 0])

    def test_team_errors(self):
        with self.assertRaises(CL.ClothError):
            CL.team("x", {}, data_tt(), ["a", None, "c"], [])
        for k, v in (("selectionData", [2, 1]), ("vertexDepthList", [0.0]), ("parentList", [-1, 0])):
            bad = data_tt()
            bad[k] = v
            with self.assertRaises(CL.ClothError, msg=k):
                CL.team("x", {}, bad, ["a", "b", "c"], [])


class TestRead(unittest.TestCase):
    """prefab 루트에서 BoneCloth·콜라이더를 찾아 팀으로."""

    def build(self, use=(12, 13, 14)):
        f = NS(objects={})
        col = mono("MagicaCapsuleCollider", {"m_GameObject": {"m_PathID": 205}, "center": T(0, 0, 0), "axis": 1,
                                             "length": 0.1, "startRadius": 0.05, "endRadius": 0.04})
        cloth = mono("MagicaBoneCloth", {
            "clothParams": {"algorithm": 1, "gravity": curve(-2.0)},
            "clothData": {"m_FileID": 0, "m_PathID": 500},
            "useTransformList": [{"m_FileID": 0, "m_PathID": p} for p in use],
            "teamData": {"colliderList": [{"m_FileID": 0, "m_PathID": 600}, {"m_FileID": 1, "m_PathID": 7}]},
        }, f)
        f.objects.update({500: R("MonoBehaviour", tt=data_tt()), 600: col})
        s1 = node("Skirt_01", 204, 14)
        s0 = node("Skirt_00", 203, 13, children=[s1])
        colgo = node("Magica Capsule Collider", 205, 15, comps=[col], t=(0.0, 0.2, 0.0))
        pelvis = node("_Pelvis", 202, 12, children=[s0, colgo])
        com = node("_COM", 201, 11, children=[pelvis])
        holder = node(" Skirt ", 206, 16, comps=[cloth])
        root = node("Prefab", 200, 10, children=[com, holder])
        by_id = {11: "_COM", 12: "_COM/_Pelvis", 13: "_COM/_Pelvis/Skirt_00", 14: "_COM/_Pelvis/Skirt_00/Skirt_01",
                 15: "_COM/_Pelvis/Magica Capsule Collider", 16: "Skirt"}
        return root.go, by_id

    def test_read(self):
        root, by_id = self.build()
        teams = CL.read(root, by_id)
        self.assertEqual(len(teams), 1)
        t = teams[0]
        self.assertEqual(t["name"], "Skirt")
        self.assertEqual(t["verts"], ["_COM/_Pelvis", "_COM/_Pelvis/Skirt_00", "_COM/_Pelvis/Skirt_00/Skirt_01"])
        c = t["colliders"][0]
        self.assertEqual(c["bone"], "_COM/_Pelvis")                 # 콜라이더 GameObject 의 부모 뼈
        self.assertEqual(c["t"], [0.0, 0.2, 0.0])                   # 그 뼈 기준 자세
        self.assertEqual((c["kind"], c["axis"], c["r0"]), ("capsule", 1, 0.05))
        self.assertIsNone(t["colliders"][1])                       # 다른 파일 콜라이더는 못 읽음
        self.assertEqual(len(t["pen"]), 9)

    def test_read_skips_broken_team(self):
        root, by_id = self.build(use=(12, 13, 99))                  # 없는 뼈
        with self.assertLogs("mabi", "INFO") as cm:
            self.assertEqual(CL.read(root, by_id), [])
        self.assertIn("흔들림 Skirt 은 뺍니다", cm.output[0])
        self.assertTrue(cm.output[0].startswith("INFO"))            # 자료가 빠진 것은 정보

    def test_read_warns_on_shape_change(self):
        root, by_id = self.build()
        with mock.patch.object(CL, "_team", side_effect=KeyError("teamData")), self.assertLogs("mabi", "WARNING") as cm:
            self.assertEqual(CL.read(root, by_id), [])
        self.assertIn("구조가 바뀐 듯", cm.output[0])


if __name__ == "__main__":
    unittest.main()
