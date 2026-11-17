"""드레스룸 — 장식·패션 무기: 모델 정의 해석(tools), 목록(catalog), 몸 소켓에 붙여 내보내기(run_mounted). 합성 값으로만."""
import json
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

from mabi.dress import catalog as C
from mabi.dress import cover as CV
from mabi.dress import export as E
from mabi.dress import modular as MD
from mabi.dress import tools as T

ACC = "Assets/PatchableAssets/Character/Player/Human/Facial/Customize/"
ITEM = "Assets/PatchableAssets/Item/"
W = "패션 무기"


def _mul(a, b):
    """사원수 곱 a·b ([x, y, z, w])."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return [aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz]


def _axis(i, deg):
    q = [0.0, 0.0, 0.0, math.cos(math.radians(deg) / 2)]
    q[i] = math.sin(math.radians(deg) / 2)
    return q


def _tf(infant, gender, t=(0, 0, 0), r=(0, 0, 0), s=(1, 1, 1)):
    return {"IsInfant": infant, "Gender": gender, "Position": list(t), "Rotation": list(r), "LocalScale": list(s)}


SOM = {"ModelPartInfo": {
    "AppearanceSlot": "MainTool", "DefaultAttachPointState": "Undrawn",
    "AttachPointInfo": [
        {"State": "Undrawn", "AttachTo": "_Backtool", "ModelPartVisibleState": "Default",
         "Transforms": [_tf(False, "Female", (1, 2, 3)), _tf(True, "None", (4, 5, 6), (90, 0, 0), (2, 2, 2))]},
        {"State": "Drawn", "AttachTo": "#MODEL_ROOT", "ModelPartVisibleState": "AlwaysInvisible", "Transforms": []},
        {"State": "Undrawn", "AttachTo": "_Other"},           # 같은 상태 두 번째는 버린다
        {"State": "Throw", "AttachTo": "_HandtoolR"},         # 모르는 상태
    ]}}


class ToolsTest(unittest.TestCase):
    def assertQuat(self, a, b):
        if sum(x * y for x, y in zip(a, b)) < 0:   # q 와 -q 는 같은 회전
            b = [-x for x in b]
        for x, y in zip(a, b):
            self.assertAlmostEqual(x, y, places=6)

    def test_quat_axes(self):
        h = math.sqrt(0.5)
        self.assertQuat(T.quat([90, 0, 0]), [h, 0, 0, h])
        self.assertQuat(T.quat([0, 90, 0]), [0, h, 0, h])
        self.assertQuat(T.quat([0, 0, 90]), [0, 0, h, h])
        self.assertQuat(T.quat([]), [0, 0, 0, 1])

    def test_quat_unity_order(self):
        # Unity 는 z → x → y 순 (q = qy·qx·qz)
        want = _mul(_mul(_axis(1, 40), _axis(0, 30)), _axis(2, 50))
        self.assertQuat(T.quat([30, 40, 50]), want)

    def test_info(self):
        inf = T.info(SOM)
        self.assertEqual(CV.slot(SOM), "MainTool")
        self.assertEqual(sorted(inf["states"]), ["Drawn", "Undrawn"])
        un, dr = inf["states"]["Undrawn"], inf["states"]["Drawn"]
        self.assertEqual((un["to"], un["visible"]), ("_Backtool", True))
        self.assertEqual((dr["to"], dr["visible"], dr["tf"]), ("", False, []))   # #MODEL_ROOT → ''
        a, b = un["tf"]
        self.assertEqual((a["infant"], a["gender"], a["t"], a["s"]), (False, "Female", [1.0, 2.0, 3.0], [1.0, 1.0, 1.0]))
        self.assertEqual((b["infant"], b["gender"], b["s"]), (True, "None", [2.0, 2.0, 2.0]))
        self.assertQuat(b["r"], [math.sqrt(0.5), 0, 0, math.sqrt(0.5)])
        self.assertEqual(T.info(None), {"states": {}})
        self.assertEqual(CV.slot(None), "")
        self.assertEqual(CV.slot({"ModelPartInfo": {"AppearanceSlot": 3}}), "")   # 문자열이 아니면 모름
        bad = T.info({"ModelPartInfo": {"AttachPointInfo": [{"State": "Drawn", "Transforms": [{"Position": "x"}]}]}})
        self.assertEqual(bad["states"]["Drawn"]["tf"][0]["t"], [0.0, 0.0, 0.0])   # 깨진 값은 기본값

    def test_pick_tf(self):
        tf = [{"infant": False, "gender": "Male"}, {"infant": False, "gender": "None"},
              {"infant": True, "gender": "Female"}]
        self.assertIs(T.pick_tf(tf, False, "Male"), tf[0])
        self.assertIs(T.pick_tf(tf), tf[1])                  # 어른 여성 없음 → 같은 나이 'None'
        self.assertIs(T.pick_tf(tf, True, "Male"), tf[2])    # 같은 나이 아무거나
        self.assertIs(T.pick_tf(tf[:1], True), tf[0])        # 그것도 없으면 첫 것
        self.assertIsNone(T.pick_tf([]))

    def test_state_of(self):
        vis = {"to": "", "visible": True, "tf": []}
        hid = dict(vis, visible=False)
        self.assertEqual(T.state_of({"states": {"Undrawn": vis, "Drawn": vis}}), "Undrawn")
        self.assertEqual(T.state_of({"states": {"Undrawn": hid, "Drawn": vis}}), "Drawn")   # 부채처럼 넣으면 안 보임
        self.assertEqual(T.state_of({"states": {"Drawn": vis}}), "Drawn")
        self.assertEqual(T.state_of({"states": {}}), "Undrawn")

    def test_groups(self):
        names = {
            "Tool_Sword_A": {"slot": W, "ids": {"Female": [10, 40], "Male": [10]}},
            "Tool_Shield_A": {"slot": W, "ids": {"Female": [10]}},
            "Tool_Bow_A": {"slot": W, "ids": {"Female": [20, 21]}},
            "Tool_Quiver_A": {"slot": W, "ids": {"Female": [20, 21]}},
            "Tool_Arrow_00": {"slot": W, "ids": {"Female": [20, 21, 30]}},   # 여러 무기가 같이 쓰는 화살
            "Tool_Bow_B": {"slot": W, "ids": {"Female": [30]}},
            "Female_Hat_Helmet_00": {"slot": "모자", "ids": {"Female": [10]}},   # 무기가 아님
            "broken": "x",
        }
        slot = {"Tool_Sword_A": "MainTool", "Tool_Shield_A": "SubTool", "Tool_Bow_A": "MainTool",
                "Tool_Quiver_A": "SubTool"}
        got = T.groups(names, lambda m: slot.get(m, ""))
        self.assertEqual(got, [
            T.Group("Tool_Bow_A", ("Tool_Arrow_00", "Tool_Quiver_A")),   # 20·21 행은 같은 묶음 → 하나
            T.Group("Tool_Bow_B", ("Tool_Arrow_00",)),                   # 둘 다 모르면 같이 안 쓰는 쪽이 대표
            T.Group("Tool_Sword_A", ("Tool_Shield_A",)),
        ])                                                               # 40 행(검만)은 대표가 겹쳐 버린다

    def test_socket_chain(self):
        sk = [{"path": p, "t": [0, 0, i], "r": [0, 0, 0, 1], "s": [1, 1, 1], "parent": i - 1}
              for i, p in enumerate(["_COM", "_COM/_Spine", "_COM/_Spine/_Backtool", "_COM/_Spine/_R Hand"])]
        path, chain = T.socket_chain(sk, "_Backtool")
        self.assertEqual(path, "_COM/_Spine/_Backtool")
        self.assertEqual([c["path"] for c in chain], ["_COM", "_COM/_Spine", "_COM/_Spine/_Backtool"])
        self.assertEqual(chain[2]["t"], [0, 0, 2])
        self.assertNotIn("parent", chain[0])
        self.assertEqual(T.socket_chain(sk, ""), ("", []))
        self.assertIsNone(T.socket_chain(sk, "_HandtoolL"))
        self.assertIsNone(T.socket_chain(sk[1:], "_Backtool"))   # 중간 노드가 빠진 뼈대


class LibrarySomTest(unittest.TestCase):
    def test_som_cached(self):
        lib = MD.Library.__new__(MD.Library)
        lib._by, lib._som_cache = {}, {}
        lib._som = {"Tool_A": "S/Tool_A.som", "Tool_Bad": "S/Tool_Bad.som", "Tool_Disk": "S/Tool_Disk.som"}
        reads = []

        def read(p):
            reads.append(p)
            if "Disk" in p:
                raise OSError("디스크")
            return p.encode()
        lib.read = read

        def load(b):
            if b"Bad" in b:
                raise MD.sjon.SjonError("broken")
            return {"ModelPartInfo": {"AppearanceSlot": "MainTool"}}

        with mock.patch.object(MD.sjon, "load", load):
            self.assertEqual(lib.som("Tool_A")["ModelPartInfo"]["AppearanceSlot"], "MainTool")
            lib.som("Tool_A")
            self.assertIsNone(lib.som("Tool_Bad"))
            self.assertIsNone(lib.som("Tool_None"))
            with MD.TX.collect() as problems, self.assertLogs("mabi", "WARNING"):
                self.assertIsNone(lib.som("Tool_Disk"))
                self.assertIsNone(lib.som("Tool_Disk"))
            self.assertEqual(len(problems), 2)                       # 환경 탓은 반쪽 표시, 기억하지 않는다
        self.assertEqual(reads, ["S/Tool_A.som", "S/Tool_Bad.som", "S/Tool_Disk.som", "S/Tool_Disk.som"])   # 한 번씩만 읽는다 (디스크 오류는 다시)
        self.assertTrue(lib.has("Tool_A"))


class CatalogDecoWeaponTest(unittest.TestCase):
    PATHS = [
        ACC + "Female/Acc/Female_Party_Mask_00.prefab",
        ACC + "Female/FBX/Female_Party_Mask_00.fbx",
        ACC + "Female/Acc/ForAssetBundle/Female_Ring_EarRings_00.prefab",   # 이름 없음·fbx 없음 → 모델 정의 부위, prefab
        ACC + "Infant/Acc/Female_Gum_00.prefab",                            # 부위를 모름
        ACC + "Male/Acc/Male_Nose_00.prefab",                               # fbx 도 실행용 자료도 없음
        ITEM + "Sword/Tool_Sword_A.prefab",
        ITEM + "Sword/FBX/Tool_Sword_A.fbx",
        ITEM + "Shield/Tool_Shield_A.prefab",                               # fbx 없음, 실행용 자료 있음
        ITEM + "Bow/Tool_Bow_B.prefab",                                     # 아무것도 없음 → 목록에 없음
        ACC + "Female/Acc/ForAssetBundle/Female_Cat_BackPack_01.prefab",   # 백팩 — 로브 칸
        ACC + "Female/Acc/ForAssetBundle/Female_BackPack_00.prefab",       # 이름 없는 옛 백팩(부위 Robe) — 안 받는다
    ]
    NAMES = {
        "Female_Party_Mask_00": {"name": "파티 가면", "slot": "눈 장식"},
        "Male_Nose_00": {"name": "코", "slot": "얼굴 장식"},
        "Tool_Sword_A": {"name": "검", "slot": W, "ids": {"Female": [1]}},
        "Tool_Shield_A": {"name": "검", "slot": W, "ids": {"Female": [1]}},
        "Tool_Bow_B": {"name": "활", "slot": W, "ids": {"Female": [2]}},
        "Female_Cat_BackPack_01": {"name": "고양이 백팩", "slot": "로브"},
    }
    SOM = {"Female_Ring_EarRings_00": {"ModelPartInfo": {"AppearanceSlot": "Accessory2"}},
           "Female_Party_Mask_00": {"ModelPartInfo": {"AppearanceSlot": "Accessory0"}},   # 이름 표가 먼저
           "Tool_Sword_A": {"ModelPartInfo": {"AppearanceSlot": "MainTool"}},
           "Tool_Shield_A": {"ModelPartInfo": {"AppearanceSlot": "SubTool"}},
           "Female_Cat_BackPack_01": {"ModelPartInfo": {"AppearanceSlot": "AccessoryBody0"}},
           "Female_BackPack_00": {"ModelPartInfo": {"AppearanceSlot": "Robe"}}}

    def test_build(self):
        run = {"Female_Ring_EarRings_00", "Tool_Shield_A", "Female_Cat_BackPack_01", "Female_BackPack_00"}.__contains__
        by = {i.id: i for i in C.build(self.PATHS, self.NAMES, run, self.SOM.get)}
        self.assertEqual(sorted(by), ["Female_Cat_BackPack_01", "Female_Party_Mask_00", "Female_Ring_EarRings_00", "Tool_Sword_A"])
        self.assertEqual((by["Female_Cat_BackPack_01"].part, by["Female_Cat_BackPack_01"].folder), ("Robe", "Female"))
        mask, ring, sword = by["Female_Party_Mask_00"], by["Female_Ring_EarRings_00"], by["Tool_Sword_A"]
        self.assertEqual((mask.part, mask.folder, mask.kor, mask.fbx), ("EyeDeco", "Female", "파티 가면", self.PATHS[1]))
        self.assertEqual((ring.part, ring.kor, ring.fbx), ("EarDeco", "", self.PATHS[2]))
        self.assertEqual((sword.part, sword.folder, sword.fbx), ("Weapon", "", self.PATHS[6]))
        self.assertEqual(sword.extra, (("Tool_Shield_A", self.PATHS[7]),))
        self.assertNotIn("extra", sword.to_dict())
        self.assertEqual(C.PART_KOR["Weapon"], "패션 무기")
        for p in C.DECO + ("Weapon",):
            self.assertIn(p, C.PARTS)

    def test_build_without_som(self):
        # 모델 정의가 없으면 이름 표만으로 — 이름 없는 장식은 빠지고, 무기 대표는 이름순
        by = {i.id: i for i in C.build(self.PATHS, self.NAMES, {"Tool_Shield_A"}.__contains__)}
        self.assertEqual(sorted(by), ["Female_Party_Mask_00", "Tool_Shield_A"])
        self.assertEqual(by["Tool_Shield_A"].extra, (("Tool_Sword_A", self.PATHS[6]),))


class MountedExportTest(unittest.TestCase):
    ID = [0, 0, 0, 1]
    CHAIN = [{"path": "Bip", "t": [0, 0, 0], "r": ID, "s": [1, 1, 1]},
             {"path": "Bip/_Backtool", "t": [0, 1, 0], "r": ID, "s": [1, 1, 1]}]

    def _run(self, mounts, d):
        roots = {"sword": NS(m_Name="Tool_Sword_A"), "shield": NS(m_Name="Tool_Shield_A"), "arrow": NS(m_Name="Tool_Arrow")}
        bones = {"Tool_Sword_A": "_Sword_Root", "Tool_Shield_A": "_Shield_Root", "Tool_Arrow": "_Root"}
        calls = []

        def skel(root):
            b = bones[root.m_Name]
            return [{"path": b, "parent": -1, "t": [0, 0, 0], "r": self.ID, "s": [1, 1, 1]}], {5: b}

        def meshes(ex, root, ids, moved, out, mats, parts=None):
            calls.append((root.m_Name, dict(ids), [n["path"] for n in moved], parts))
            return [{"name": f"Mesh_{root.m_Name}"}]

        with mock.patch.object(E.A, "roots", lambda env, path: [roots[path]] if path in roots else []), \
                mock.patch.object(E, "skeleton", skel), \
                mock.patch.object(E, "transform_ptr", lambda root: NS(m_PathID=9)), \
                mock.patch.object(E.Exporter, "_meshes", meshes):
            ex = E.Exporter(NS(open=lambda paths: None), Path(d) / "tex")
            meta = ex.run_mounted(mounts, Path(d) / "m.json", self.CHAIN)
        return meta, calls

    def test_mount(self):
        mounts = [
            {"path": "sword", "at": "Bip/_Backtool", "t": [1, 2, 3], "r": self.ID, "s": [1, 1, 1], "parts": "P",
             "info": {"model": "Tool_Sword_A"}},
            {"path": "shield", "at": "Bip/_Backtool", "t": [0, 0, 0], "r": self.ID, "s": [2, 2, 2], "hidden": True,
             "info": {"model": "Tool_Shield_A"}},
            {"path": "gone", "at": "Bip", "t": [0, 0, 0], "r": self.ID, "s": [1, 1, 1], "info": {"model": "Tool_Gone"}},
            {"path": "sword", "at": "Bip/_Backtool", "t": [0, 0, 0], "r": self.ID, "s": [1, 1, 1]},   # 같은 자리 두 번
            {"path": "arrow", "at": "", "t": [0, 0, 0], "r": self.ID, "s": [1, 1, 1], "info": {"model": "Tool_Arrow"}},
        ]
        with tempfile.TemporaryDirectory() as d:
            meta, calls = self._run(mounts, d)
            saved = json.loads((Path(d) / "m.json").read_text(encoding="utf-8"))
        sk = meta["skeleton"]
        self.assertEqual([n["path"] for n in sk], [
            "Bip", "Bip/_Backtool",
            "Bip/_Backtool/Tool_Sword_A", "Bip/_Backtool/Tool_Sword_A/_Sword_Root",
            "Bip/_Backtool/Tool_Shield_A", "Bip/_Backtool/Tool_Shield_A/_Shield_Root",
            "Tool_Arrow", "Tool_Arrow/_Root"])
        self.assertEqual([n["parent"] for n in sk], [-1, 0, 1, 2, 1, 4, -1, 6])
        self.assertEqual(sk[2]["t"], [1, 2, 3])            # prefab 루트는 붙는 자세로
        self.assertEqual(sk[4]["s"], [2, 2, 2])
        # 메시 쪽 뼈 id 는 붙인 경로로, 루트 Transform 도 이어진다
        self.assertEqual(calls[0], ("Tool_Sword_A", {5: "Bip/_Backtool/Tool_Sword_A/_Sword_Root",
                                                     9: "Bip/_Backtool/Tool_Sword_A"},
                                    ["Bip/_Backtool/Tool_Sword_A/_Sword_Root"], "P"))
        self.assertEqual([(m["name"], m["piece"], m.get("hidden", False)) for m in meta["meshes"]],
                         [("Mesh_Tool_Sword_A", 0, False), ("Mesh_Tool_Shield_A", 1, True), ("Mesh_Tool_Arrow", 4, False)])
        self.assertEqual([a["node"] for a in meta["attach"]],
                         ["Bip/_Backtool/Tool_Sword_A", "Bip/_Backtool/Tool_Shield_A", None, None, "Tool_Arrow"])
        self.assertEqual(meta["attach"][1]["model"], "Tool_Shield_A")
        self.assertEqual(saved["attach"], meta["attach"])

    def test_nothing_drawn(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(E.ExportError):
                self._run([{"path": "gone", "at": "", "t": [0, 0, 0], "r": self.ID, "s": [1, 1, 1]}], d)
            with self.assertRaises(E.ExportError):
                self._run([], d)


if __name__ == "__main__":
    unittest.main()
