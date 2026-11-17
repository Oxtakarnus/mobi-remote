"""드레스룸 (mabi.dress · gui_app.dressroom) — 가짜 Unity 객체와 임시 폴더로. 게임 파일은 쓰지 않는다."""
import json
import math
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

import numpy as np

from mabi.dress import anim as N
from mabi.dress import assets as A
from mabi.dress import catalog as C
from mabi.dress import cover as CV
from mabi.dress import dyeslots as DS
from mabi.dress import export as E
from mabi.dress import service as S

H = C.H


class CatalogTest(unittest.TestCase):
    def test_pretty(self):
        self.assertEqual(C.pretty("Female_BalloonLineCarpentry_Helmet_01", "Female", "Helmet"), "Balloon Line Carpentry 01")
        self.assertEqual(C.pretty("Male_Acheron_Top_00", "Male", "Top"), "Acheron")
        self.assertEqual(C.pretty("InfantMale_HTMLStyle_Shoes_02", "Infant", "Shoes"), "HTML Style 02")

    def test_build(self):
        paths = [
            H + "Female/Top/ForAssetBundle/Female_Maid_Top_00.prefab",
            H + "FBX/Human/Female/Top/Female_Maid_Top_00.fbx",
            H + "Female/Bottom/ForAssetBundle/Female_Alps_Bottom_00.prefab",
            H + "FBX/Human/Female/Bottom/Female_Alps_Bottom_00.fbx",
            H + "Female/Top/ForAssetBundle/Female_NoFbx_Top_00.prefab",                 # fbx 없음
            H + "Female/Top/ForAssetBundle/Female_TestDigger_Top_00.prefab",            # 개발용
            H + "FBX/Human/Female/Top/Female_TestDigger_Top_00.fbx",
            H + "Female/Weapon/ForAssetBundle/Female_Sword_Weapon_00.prefab",           # 부위 아님
            H + "FBX/Human/Female/Weapon/Female_Sword_Weapon_00.fbx",
        ]
        items = C.build(paths)
        self.assertEqual([i.id for i in items], ["Female_Maid_Top_00", "Female_Alps_Bottom_00"])   # 부위 순서
        self.assertEqual(items[0].fbx, H + "FBX/Human/Female/Top/Female_Maid_Top_00.fbx")
        self.assertEqual(items[1].to_dict()["name"], "Alps")
        self.assertEqual(items[1].to_dict()["colors"], [])   # 시트에 없는 옷은 기본 염색 없음
        named = C.build(paths, {"Female_Maid_Top_00": {"name": "메이드", "colors": ["#35414D", None]}})
        self.assertEqual(named[0].to_dict()["colors"], ["#35414D", None])   # 게임 시트 기본 염색

    def test_shared_asset(self):
        """자기 prefab 이 없는 모델은 모델 정의가 가리키는 다른 모델의 자산으로 (여성 풍선껌 → 아이 prefab)."""
        acc = H + "Facial/Customize/"
        paths = [acc + "Infant/Acc/ForAssetBundle/Infant_Gum_00.prefab", acc + "Infant/FBX/Infant_Gum_00.fbx"]
        names = {"Infant_Gum_00": {"name": "껌", "slot": "얼굴 장식"}, "Female_Gum_00": {"name": "껌", "slot": "얼굴 장식"},
                 "Female_Lost_00": {"name": "없음"}}
        som = {"Female_Gum_00": {"AssetPathToLoad": "Character/Player/Human/Facial/Customize/Infant/Acc/ForAssetBundle/"
                                                    "Infant_Gum_00.prefab"},
               "Female_Lost_00": {"AssetPathToLoad": "Character/Nowhere/Female_Lost_00.prefab"}}
        items = {i.id: i for i in C.build(paths, names, som=som.get)}
        self.assertEqual(set(items), {"Infant_Gum_00", "Female_Gum_00"})
        g = items["Female_Gum_00"]
        self.assertEqual((g.folder, g.part, g.fbx, g.kor), ("Female", "FaceDeco", acc + "Infant/FBX/Infant_Gum_00.fbx", "껌"))

    def test_body_paths(self):
        p = C.body_paths("Boy")
        self.assertEqual(p["body"], H + "FBX/InfantMale_Body_00.fbx")
        self.assertTrue(p["eye"].endswith("Facial/Customize/Infant/FBX/Infant_Eye_Default_00.fbx"))
        self.assertTrue(p["head"].endswith("Infant_Head_Default_00.fbx"))

    def test_stand_path(self):
        self.assertEqual(C.stand_path("Male", "Muscular"),
                         C.ANIM + "Male/Customize/HM@Customize_Stand_Muscle.fbx")
        self.assertTrue(C.stand_path("Girl", "모름").endswith("Infant/Customize/HC@Customize_Stand_Default.fbx"))


def _col(r, g, b, a=1.0):
    return NS(r=r, g=g, b=b, a=a)


def _mat(name, tex=None, cols=None, floats=None, kw=None, ikw=None):
    """가짜 머티리얼 가리킴 — 텍스처 자리에 이름을 바로 둔다 (Exporter.textures.ref 를 바꿔 쓴다)."""
    env = [("_BaseMap", NS(m_Texture=tex))] if tex else []
    sp = NS(m_TexEnvs=env, m_Colors=list((cols or {}).items()), m_Floats=list((floats or {}).items()))
    m = NS(m_Name=name, m_SavedProperties=sp, m_ValidKeywords=kw or [], m_InvalidKeywords=ikw or [])
    return NS(m_PathID=1, deref=lambda: NS(read=lambda: m))


class CoverRulesTest(unittest.TestCase):
    def test_rules(self):
        som = {"ModelPartInfo": {"HideHair": True, "HideBeard": False, "HideLeftEyeByHelmetCover": True,
                                 "HideHeadByHelmetCover": True, "AppearanceSlot": "Helmet"},
               "InterModelInfo": {"AppearanceTuningInfo": {"PressHood": False, "PressHoodH0": True, "PressHoodH3": True,
                                                           "PressHoodH5": False}}}
        self.assertEqual(CV.rules(som), {"hide": ["Hair"], "cap": ["Head", "LeftEye"], "press": [0, 3]})
        self.assertEqual(CV.rules({"InterModelInfo": {"AppearanceTuningInfo": {"PressHood": True}}}), {"press": "all"})
        self.assertIsNone(CV.rules({"ModelPartInfo": {"HideHair": False}}))
        self.assertIsNone(CV.rules(None))
        self.assertIsNone(CV.rules({"ModelPartInfo": [], "InterModelInfo": 3}))
        gum = {"InterModelInfo": {"MouthControlInfo": {"OverrideEmotionIndex": 32}, "AppearanceTuningInfo": None}}
        self.assertEqual(CV.rules(gum), {"mouth": 32})
        self.assertIsNone(CV.rules({"InterModelInfo": {"MouthControlInfo": {"OverrideEmotionIndex": 0}}}))

    def test_fit(self):
        som = {"ModelPartInfo": {"AppearanceSlot": "Foot",
                                 "JunctionPointInfo": {"AnkleSize": "Medium", "WaistSize": "", "WristSize": None}}}
        self.assertEqual(CV.fit(som), {"slot": "Foot", "junctions": {"AnkleSize": "Medium"}})
        self.assertEqual(CV.fit({"ModelPartInfo": {"AppearanceSlot": "Robe"}}), {"slot": "Robe", "junctions": {}})
        self.assertEqual(CV.fit({"ModelPartInfo": {"AppearanceSlot": "AccessoryBody0", "JunctionPointInfo": {}}}),
                         {"slot": "AccessoryBody0", "junctions": {}})   # 게임 부위만 (백팩)
        self.assertIsNone(CV.fit({"ModelPartInfo": {"JunctionPointInfo": {}}}))
        self.assertIsNone(CV.fit({"ModelPartInfo": []}))
        self.assertIsNone(CV.fit(None))


class DyeSlotsTest(unittest.TestCase):
    def test_wiring(self):
        w = lambda mi, ma, ch: {"MeshIndex": mi, "MaterialIndex": ma, "ChannelIndex": ch}
        som = {"SkinnedMeshList": [{"MeshName": "Mesh_Top_00"}, {"MeshName": "Mesh_BP_LArm"}, {"MeshName": "Mesh_Skirt_00"}],
               "DyeInfo": {"Slots": [
                   {"Slot": "Skin", "Wirings": [w(2, 1, 0)]},                       # 이름 칸은 피부·머리 — 안 다룬다
                   {"Slot": "Slot0", "Wirings": [w(0, 0, 0), w(2, 0, 0)]},
                   {"Slot": "Slot4", "Wirings": [w(0, 1, 1), w(9, 0, 0), w(0, 0, 5)]},   # 없는 메시·채널은 버린다
                   {"Slot": "Slot5", "Wirings": [w(0, 1, 2), {"MeshIndex": "x"}]}]}}
        self.assertEqual(DS.wiring(som), {("Mesh_Top_00", 0): [0, None, None], ("Mesh_Skirt_00", 0): [0, None, None],
                                          ("Mesh_Top_00", 1): [None, 4, 5]})
        self.assertIsNone(DS.wiring({"DyeInfo": {"Slots": [{"Slot": "Hair", "Wirings": []}]}}))   # 번호 칸 없음
        self.assertIsNone(DS.wiring(None))
        self.assertEqual(DS.wiring({"DyeInfo": {"Slots": [{"Slot": "Slot0", "Wirings": []}]}}), {})   # 칸은 있는데 배선 없음


class ExportHelperTest(unittest.TestCase):
    def test_four_pads(self):
        a = E._four([[1, 2], [3, 4], [5, 6]], 3, np.uint16, 0)
        self.assertEqual(a.shape, (3, 4))
        self.assertEqual(a[1].tolist(), [3, 4, 0, 0])
        self.assertEqual(E._four(None, 2, np.float32, 0.5).tolist(), [[0.5] * 4] * 2)
        self.assertEqual(E._four([[1, 2]], 3, np.uint16, 7).tolist(), [[7] * 4] * 3)   # 정점 수가 다르면 버린다

    def test_cols(self):
        self.assertEqual(E._cols([[1, 2, 3, 9], [4, 5, 6, 9]], 2, 3).tolist(), [[1, 2, 3], [4, 5, 6]])   # 4칸 법선
        self.assertEqual(E._cols([1, 2, 3, 4], 2, 2).tolist(), [[1, 2], [3, 4]])                       # 납작한 목록
        self.assertEqual(E._cols([[1, 2]], 1, 2).shape, (1, 2))

    def test_flags(self):
        self.assertEqual(E._flags("Mesh_Hair_00_H2"), {"hair": 2})
        self.assertEqual(E._flags("Mesh_Helmet_00_C1"), {"cover": 1})
        self.assertEqual(E._flags("Mesh_Robe_Hood_On_00"), {"hood": "on"})
        self.assertEqual(E._flags("Mesh_Hood_Off_Pressed"), {"hood": "pressed"})
        self.assertEqual(E._flags("Mesh_Hood_Off"), {"hood": "off"})
        self.assertEqual(E._flags("Mesh_EyeBasePlane"), {"hidden": True})
        self.assertEqual(E._flags("Mesh_Skin_Head"), {"skin": True})
        self.assertEqual(E._flags("Mesh_Top_00"), {})

    def test_shapes(self):
        def v(i, x):
            return NS(index=i, vertex=NS(x=x, y=0.0, z=0.0))
        sh = NS(channels=[NS(name="Fat", frameIndex=0, frameCount=2),
                          NS(name="Mesh_BP_Arm", frameIndex=2, frameCount=1),
                          NS(name="Empty", frameIndex=3, frameCount=1)],
                shapes=[NS(firstVertex=0, vertexCount=1), NS(firstVertex=1, vertexCount=2),
                        NS(firstVertex=3, vertexCount=1), NS(firstVertex=4, vertexCount=1)],
                vertices=[v(0, 9.0), v(0, 1.0), v(2, 2.0), v(1, 5.0), v(0, 0.0)])
        out = E._shapes(NS(m_Shapes=sh), 3)
        self.assertEqual(list(out), ["Fat"])                        # Mesh_ 채널·변화 없는 채널은 뺀다
        self.assertEqual(out["Fat"][:, 0].tolist(), [1.0, 0.0, 2.0])   # 마지막 프레임

    def test_prefab_materials(self):
        # 재질 배정은 게임 prefab 렌더러 것 (fbx 의 배정은 작업 파일 것이라 다를 수 있다)
        ex = E.Exporter(None, Path("."))
        rs = [(NS(m_Name="Mesh_OnePiece_00"), NS(m_Materials=["opaque", "opaque"])),
              (NS(m_Name="Mesh_BP_Arm"), NS(m_Materials=[]))]
        ex._root = lambda path: "root"
        with mock.patch.object(E.A, "renderers", lambda root: rs):
            self.assertEqual(ex._prefab_mats("a.prefab"), {"Mesh_OnePiece_00": ["opaque", "opaque"]})

        def missing(path):
            raise E.ExportError("없음")
        ex._root = missing
        self.assertEqual(ex._prefab_mats("a.prefab"), {})   # prefab 을 못 열면 fbx 배정 그대로

    def _export_mat(self, ptr):
        ex = E.Exporter(None, Path("."))
        ex.textures.ref = lambda p: p
        mats = []
        i = ex._material(ptr, mats)
        return None if i is None else mats[i]

    def test_material_kind_by_dye_color(self):
        dye = {"_DyeColor1": _col(0.7, 0.54, 0.44), "_DyeColor2": _col(1, 1, 1), "_DyeColor3": _col(1, 1, 1)}
        nose = self._export_mat(_mat("Male_Head_Thin_Nose_00", "Female_Nose", dye, ikw=["_ISDYABLE_ON"]))
        self.assertEqual(nose["kind"], "dye")                  # 이름에 DyeMap 이 없어도 칸 색·염색 키워드가 있으면 염색
        white = {k: _col(1, 1, 1) for k in ("_DyeColor1", "_DyeColor2", "_DyeColor3")}
        pin = self._export_mat(_mat("Female_OwlBearFeatherPin_Helmet_00", "Female_OwlBearFeatherPin_Helmet_00", white,
                                    kw=["_ZWRITE_ON"]))
        self.assertEqual(pin["kind"], "tex")                   # 염색 불가 — 칸 색은 있어도 키워드가 없으면 그림 그대로
        top = self._export_mat(_mat("Top_00", "Top_00_DyeMap", white, kw=["_DYE_ON"]))
        self.assertEqual(top["kind"], "dye")                   # 유효 키워드여도 된다
        self.assertTrue(nose["skin"])
        self.assertEqual(nose["dye"][0], "#B28A70")
        sclera = self._export_mat(_mat("Eye_Base_00", "Female_Eye_00_DyeMap", {}, {"_AlphaOverride": 0.5}))
        self.assertEqual(sclera["kind"], "tex")                # DyeMap 이라도 칸 색이 없으면 그림 그대로
        self.assertEqual(sclera["dye"], ["#FFFFFF"] * 3)
        # 염색 칸 배선 — 같은 재질도 칸이 다르면 따로, 염색 재질에만 싣는다
        ex = E.Exporter(None, Path("."))
        ex.textures.ref = lambda p: p
        mats = []
        cloth = _mat("Top_01", "Top_01_DyeMap", white, kw=["_DYE_ON"])
        a, b, c = ex._material(cloth, mats, [3, 4, 5]), ex._material(cloth, mats, [3, 4, 5]), ex._material(cloth, mats)
        self.assertEqual((a, b), (0, 0))
        self.assertEqual(c, 1)
        self.assertEqual(mats[0]["slots"], [3, 4, 5])
        self.assertNotIn("slots", mats[1])
        self.assertNotIn("slots", mats[ex._material(_mat("Eye_Highlight"), mats, [0, 1, 2])])
        hl = self._export_mat(_mat("Eye_Highlight"))
        self.assertEqual(hl["kind"], "color")
        self.assertIsNone(self._export_mat(_mat("Hair_Shadow_00", "x")))

    def test_material_see_through(self):
        # 사물 재질을 빌려 쓰는 모자(어항) — 유리·물 셰이더는 뷰어의 반투명 길로, 물빛은 산란 색
        water = {"_BaseColor": _col(1, 1, 1), "_ScatterColor1": _col(0.682, 0.839, 0.851)}
        with mock.patch.object(E.A, "shader_name", return_value="MMN/BG/Water"):
            w = self._export_mat(_mat("Fishbowl_Water", None, water, {"_ZWrite": 1.0}))
        self.assertEqual(w["color"], "#AED6D9")
        self.assertEqual((w["float"]["_RenderMode"], w["float"]["_AlphaScaleMax"], w["float"]["_ZWrite"]), (1.0, 0.45, 0.0))
        path = "Assets/PatchableAssets/Shaders/MMN/BG/MMN_WindowGlassAlphablend.shader"   # 셰이더를 못 풀면 자산 경로
        with mock.patch.object(E.A, "shader_name", return_value=path):
            g = self._export_mat(_mat("Fishbowl_Glass", None, {"_BaseColor": _col(0.774, 0.774, 0.774)}))
        self.assertEqual((g["float"]["_AlphaScaleMax"], g["color"]), (0.25, "#C5C5C5"))
        with mock.patch.object(E.A, "shader_name", return_value="MMN/BG/SimpleLit") as sn:
            self.assertNotIn("float", self._export_mat(_mat("Radish", None, {})))
            self.assertNotIn("float", self._export_mat(_mat("Radish", "Radish_Tex", {})))
        self.assertEqual(sn.call_count, 1)                            # 그림 있는 재질은 셰이더를 안 본다
        self.assertIsNone(A.shader_name(NS(m_Name="x")))              # 셰이더 가리킴이 없는 재질

    def test_material_vec_float(self):
        cols = {"_DyeColor1": _col(1, 0, 0), "_BaseMapAtlasSize": _col(2, 2, 1, 0), "_EmissionColor": _col(1, 1, 1),
                "_TintColor": _col(0.5, 0.5, 0.5)}
        m = self._export_mat(_mat("Female_EyeBall_06", "Female_EyeBall_00_DyeMap", cols,
                                  {"_RenderMode": 0.0, "_Cutoff": 0.5, "_ShadingType": 1.0},
                                  ["_ALPHATEST_ON", "_NORMALMAP"]))
        self.assertEqual(m["vec"], {"_BaseMapAtlasSize": [2, 2, 1, 0], "_TintColor": [0.5, 0.5, 0.5, 1.0]})
        self.assertEqual(m["float"], {"_RenderMode": 0.0, "_ShadingType": 1.0})
        self.assertEqual(m["kw"], ["_ALPHATEST_ON"])                # 뷰어가 쓰는 키워드만
        self.assertNotIn("kw", self._export_mat(_mat("Top_00", "Top_00_DyeMap", cols)))

    def test_material_emission_fresnel(self):
        def mat(cols, floats, envs):
            sp = NS(m_TexEnvs=[("_BaseMap", NS(m_Texture="Robe_DyeMap"))] + envs, m_Colors=list(cols.items()),
                    m_Floats=list(floats.items()))
            m = NS(m_Name="Robe_00", m_SavedProperties=sp, m_ValidKeywords=["_METAL_FEATURE"], m_InvalidKeywords=[])
            return NS(m_PathID=1, deref=lambda: NS(read=lambda: m))
        st = lambda: NS(m_Scale=NS(x=2.0, y=3.0), m_Offset=NS(x=0.5, y=0.0))
        cols = {"_EmissionColor": _col(2.1, 1.3, 0.7), "_FresnelColor": _col(0.4, 1, 0.9)}
        fl = {"_IsDyable": 1.0, "_IsBreathingEmissionMode": 1.0, "_BreathingEmissionMinBright": 0.16,
              "_BreathingEmissionModePeriod": 2.0, "_EmissionNoiseSpeed": -0.07, "_FresnelPower": 5.0, "_FresnelRange": 1.5}
        envs = [("_EmissionMap", NS(m_Texture="Robe_Emission")), ("_EmissionNoiseMap", NS(m_Texture="FX_Noise_13_2", **vars(st())))]
        m = self._export_mat(mat(cols, fl, envs))
        e = m["emit"]
        self.assertEqual((e["tex"], e["noise"], e["noiseST"]), ("Robe_Emission", "FX_Noise_13_2", [2.0, 3.0, 0.5, 0.0]))
        self.assertEqual(e["colors"], [[2.1, 1.3, 0.7], [0, 0, 0], [0, 0, 0]])
        self.assertEqual(e["wave"], [1.0, 0.16, 2.0, -0.07])
        self.assertTrue(e["srgb"])                                  # 못 읽으면 색 그림으로
        self.assertNotIn("night", e)
        self.assertEqual(m["fresnel"], [0.4, 1, 0.9, 1.5, 5.0, 1.0])
        # 숨쉬기가 아니면 잡음 그림은 안 싣는다 · 색이 다 검으면 발광 없음 · 게임 셰이더가 아니면 없음
        self.assertNotIn("noise", self._export_mat(mat(cols, {**fl, "_IsBreathingEmissionMode": 0.0}, envs))["emit"])
        self.assertNotIn("emit", self._export_mat(mat({"_EmissionColor": _col(0, 0, 0)}, fl, envs)))
        self.assertNotIn("emit", self._export_mat(mat(cols, {"_Smoothness": 0.5}, envs)))
        self.assertNotIn("emit", self._export_mat(mat(cols, fl, [])))
        self.assertNotIn("fresnel", self._export_mat(mat({"_FresnelColor": _col(1, 1, 1)}, {**fl, "_FresnelPower": 0.0}, envs)))

    def test_material_stocking(self):
        def mat(floats, envs):
            sp = NS(m_TexEnvs=[("_BaseMap", NS(m_Texture="Shoes_DyeMap"))] + envs, m_Colors=[],
                    m_Floats=list(floats.items()))
            m = NS(m_Name="Stocking_00", m_SavedProperties=sp, m_ValidKeywords=[], m_InvalidKeywords=[])
            return NS(m_PathID=1, deref=lambda: NS(read=lambda: m))
        fl = {"_IsDyable": 1.0, "_Denier": 40.0, "_PointColorSpecular": 0.3, "_UseDyeMaskMap": 1.0}
        envs = [("_DyeMaskMap", NS(m_Texture="Stocking_Mask"))]
        st = self._export_mat(mat(fl, envs))["stocking"]
        self.assertEqual(st, {"denier": 40.0, "point": 0.3, "useMask": True, "mask": "Stocking_Mask", "maskSrgb": True})
        # 마스크를 안 쓰면 그림은 안 싣는다 · _Denier 가 없으면 스타킹이 아니다
        st = self._export_mat(mat({**fl, "_UseDyeMaskMap": 0.0}, envs))["stocking"]
        self.assertEqual(st, {"denier": 40.0, "point": 0.3, "useMask": False})
        self.assertNotIn("stocking", self._export_mat(mat({"_IsDyable": 1.0}, envs)))
        # 마스크를 쓰는데 그림을 못 꺼냈으면 칸 2 도 없다 (뷰어의 색 칸과 셰이더가 같은 값을 보게)
        st = self._export_mat(mat(fl, [("_DyeMaskMap", NS(m_Texture=None))]))["stocking"]
        self.assertEqual(st, {"denier": 40.0, "point": 0.3, "useMask": False})

    def test_material_gem(self):
        def mat(floats, envs):
            sp = NS(m_TexEnvs=[("_BaseMap", NS(m_Texture="Wand_DyeMap"))] + envs, m_Colors=[], m_Floats=list(floats.items()))
            m = NS(m_Name="Wand_Crystal", m_SavedProperties=sp, m_ValidKeywords=["_GEM_FEATURE"], m_InvalidKeywords=[])
            return NS(m_PathID=1, deref=lambda: NS(read=lambda: m))
        fl = {"_IsDyable": 1.0, "_IsGem": 1.0, "_GemBaseColorStrength": 1.15, "_GemMatCapBlend": 0.3,
              "_GemInclusionMapTilingX": 2.0}
        envs = [("_GemMatCapMap", NS(m_Texture="Crystal_MatCap")), ("_GemInclusionMap", NS(m_Texture="Crystal_01"))]
        g = self._export_mat(mat(fl, envs))["gem"]
        self.assertEqual(g["base"], [1.15, 0.5])                    # 없는 값은 게임 재질의 흔한 값으로
        self.assertEqual(g["matcap"], [0.3, 1.0, 1.0])
        self.assertEqual(g["tiling"], [2.0, 1.0])
        self.assertEqual((g["capTex"], g["incTex"], g["capTexSrgb"]), ("Crystal_MatCap", "Crystal_01", True))
        # 못 읽은 그림은 뺀다 · _IsGem 이 꺼져 있으면 보석이 아니다
        g = self._export_mat(mat(fl, envs[:1] + [("_GemInclusionMap", NS(m_Texture=None))]))["gem"]
        self.assertNotIn("incTex", g)
        self.assertNotIn("gem", self._export_mat(mat({**fl, "_IsGem": 0.0}, envs)))


def _streamed(frames) -> list[int]:
    """[(시간, [(커브, c0, c1, c2, c3)])] → u32 낱말."""
    b = bytearray()
    for t, keys in frames:
        b += struct.pack("<fi", t, len(keys))
        for k in keys:
            b += struct.pack("<i4f", *k)
    return list(np.frombuffer(bytes(b), "<u4"))


def _rotate(q, v):
    x, y, z, w = q
    u = np.array([x, y, z])
    v = np.asarray(v, float)
    return v + 2 * np.cross(u, np.cross(u, v) + w * v)


class AnimTest(unittest.TestCase):
    def test_streamed_keys_drops_infinite(self):
        words = _streamed([(-math.inf, [(0, 0, 0, 0, 9)]),
                           (0.0, [(0, 0, 0, 1, 2), (1, 0, 0, 0, 3)]),
                           (1.0, [(0, 0, 0, 0, 5)]),
                           (math.inf, [(0, 0, 0, 0, 7)])])
        k = N.streamed_keys(words)
        self.assertEqual(sorted(k), [0, 1])
        self.assertEqual([t for t, _ in k[0]], [0.0, 1.0])
        self.assertEqual(k[1][0][1], (0.0, 0.0, 0.0, 3.0))

    def test_sample_streamed(self):
        keys = [(0.0, (0, 0, 1, 2)), (1.0, (0, 0, 0, 5))]
        out = N._sample_streamed(keys, np.array([0.0, 0.5, 1.0, 2.0]))
        self.assertEqual(out.tolist(), [2.0, 2.5, 5.0, 5.0])

    def test_euler_order_zxy(self):
        q = N._euler_to_quat(np.array([[0, 90, 0]], np.float32))[0]
        np.testing.assert_allclose(q, [0, math.sqrt(0.5), 0, math.sqrt(0.5)], atol=1e-6)
        # (90, 90, 0): X 로 먼저 돌고 Y 로 — z 축은 -y 로 간다 (Y 먼저면 x 로 간다)
        q = N._euler_to_quat(np.array([[90, 90, 0]], np.float32))[0]
        np.testing.assert_allclose(_rotate(q, [0, 0, 1]), [0, -1, 0], atol=1e-6)

    def test_decode(self):
        def bind(path, attr):
            return NS(path=path, attribute=attr, typeID=4)
        data = NS(m_StreamedClip=NS(curveCount=0, data=[]),
                  m_DenseClip=NS(m_CurveCount=3, m_FrameCount=2, m_SampleRate=30.0, m_BeginTime=0.0,
                                 m_SampleArray=[0, 0, 0, 1, 2, 3]),
                  m_ConstantClip=NS(data=[0, 0, 0, 1, 1, 1, 1]))
        clip = NS(m_MuscleClip=NS(m_StartTime=0.0, m_StopTime=1 / 30, m_Clip=NS(data=data)),
                  m_ClipBindingConstant=NS(genericBindings=[bind(111, 1), bind(222, 2), bind(333, 3)]))
        meta, buf = N.decode(clip, {111: "_COM", 222: "_COM/_Pelvis"})
        self.assertEqual(meta["frames"], 2)
        tr = {t["path"]: t for t in meta["tracks"]}
        self.assertEqual(set(tr), {"_COM", "_COM/_Pelvis"})   # 모르는 경로는 뺀다
        p = tr["_COM"]
        self.assertEqual((p["kind"], p["n"]), ("p", 2))
        self.assertEqual(np.frombuffer(buf, np.float32, 6, p["off"]).tolist(), [0, 0, 0, 1, 2, 3])
        r = tr["_COM/_Pelvis"]
        self.assertEqual((r["kind"], r["n"]), ("r", 1))           # 안 바뀌는 트랙은 한 프레임
        self.assertEqual(np.frombuffer(buf, np.float32, 4, r["off"]).tolist(), [0, 0, 0, 1])


class AssetsTest(unittest.TestCase):
    def test_keep(self):
        self.assertTrue(A._keep(H + "FBX/Male_Body_00.fbx"))
        self.assertTrue(A._keep("Assets/PatchableAssets/Animation/Player/Human/Male/Customize/HM@Customize_Stand_Fat.fbx"))
        self.assertTrue(A._keep("Assets/PatchableAssets/Animation/Player/Human/Male/PlayerCommon/_Emotion/HM@PlayerCommon_Emotion_Bow.fbx"))
        self.assertFalse(A._keep("Assets/PatchableAssets/Animation/Player/Human/Male/Battle/HM@Attack.fbx"))
        # 남성 몸 머티리얼은 자동 생성 폴더에 있다
        self.assertTrue(A._keep("Assets/PatchableAssets/AutoGenerated/ActorPrefab/Actor_00/Material_01_Mesh_Skin_Body.mat"))
        self.assertFalse(A._keep("Assets/PatchableAssets/AutoGenerated/ActorPrefab/Actors/Mesh_60_Mesh_Skin_Body.mesh"))
        self.assertTrue(A._keep("Assets/PatchableAssets/Shaders/FromUniversalRP/Lit.mat"))   # 풍선껌의 기본 머티리얼
        self.assertFalse(A._keep("Assets/PatchableAssets/Shaders/FromUniversalRP/Lit.shader"))
        self.assertTrue(A._keep("Assets/PatchableAssets/Shaders/Texture/Crystal_MatCap.png"))   # 보석 그림
        self.assertFalse(A._keep("Assets/PatchableAssets/Shaders/Texture/Water_Normal.png"))
        # 오브젝트헤드 모자가 빌려 쓰는 사물 재질·그림 (메시·prefab 은 기억하지 않는다)
        self.assertTrue(A._keep("Assets/PatchableAssets/Environment/Gathering/FBX/Materials/Crop_HugeRadish_00.mat"))
        self.assertTrue(A._keep("Assets/PatchableAssets/Environment/Housing/Texture/Housing_PlantPot_Large_09.tga"))
        self.assertFalse(A._keep("Assets/PatchableAssets/Environment/Housing/FBX/Housing_PlantPot_Large_09.fbx"))
        self.assertFalse(A._keep("Assets/PatchableAssets/Environment/Field/Texture/Tree_00.tga"))
        self.assertTrue(A._keep("Assets/PatchableAssets/Shaders/MMN/BG/MMN_Water.shader"))   # 사물 재질 셰이더 이름
        self.assertFalse(A._keep("Assets/PatchableAssets/Shaders/MMN/FX/FX_Default.shader"))

    def test_cab_table_rebuilt_on_version(self):
        with tempfile.TemporaryDirectory() as d:
            pack = A.AssetPack.__new__(A.AssetPack)
            pack.cache_dir, pack._cab = Path(d), None
            pack.stamp = lambda: [5]
            scans = []
            pack._scan = lambda: scans.append(1) or {"cab-a": ("", 1, 2)}
            (Path(d) / "cab.json").write_text(json.dumps({"stamp": [5], "cab": {"cab-old": ["", 1, 1]}}))   # 판 없음
            self.assertEqual(pack.cabs(), {"cab-a": ("", 1, 2)})
            pack._cab = None
            self.assertEqual(pack.cabs(), {"cab-a": ("", 1, 2)})   # 이번엔 저장한 표를 쓴다
            self.assertEqual(len(scans), 1)


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.room = S.DressRoom(self.dir, game_dir=lambda: None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_stamp_clears_on_change(self):
        for d in ("models", "tex"):
            (self.dir / d).mkdir()
            (self.dir / d / "a").write_text("x")
        (self.dir / "cab.json").write_text("{}")
        (self.dir / "stamp.json").write_text(json.dumps({"format": S.FORMAT, "clips": S.CLIP_FORMAT, "meshes": S.MESH_FORMAT,
                                                       "stamp": [1]}))
        self.room._check_stamp([1])
        self.assertTrue((self.dir / "models" / "a").exists())
        self.room._check_stamp([2])
        self.assertFalse((self.dir / "models").exists())
        self.assertFalse((self.dir / "tex").exists())
        self.assertTrue((self.dir / "cab.json").exists())      # CAB 표는 assets 가 따로 본다
        self.assertEqual(json.loads((self.dir / "stamp.json").read_text()),
                         {"format": S.FORMAT, "clips": S.CLIP_FORMAT, "meshes": S.MESH_FORMAT, "stamp": [2]})
        self.assertNotIn("meshes", self.room._source)   # source 는 모델 json 형식과 상관없다

    def test_stamp_drops_clips_only(self):
        """동작 클립 형식만 바뀌면 동작 클립(clip_*·anim_*)만 지우고 옷·텍스처는 둔다."""
        (self.dir / "models").mkdir()
        for n in ("clip_HF@Walk.json", "clip_HF@Walk.bin", "anim_Female_.json", "Top_00.json"):
            (self.dir / "models" / n).write_text("x")
        (self.dir / "stamp.json").write_text(json.dumps({"format": S.FORMAT, "meshes": S.MESH_FORMAT, "stamp": [1]}))  # clips 없음
        self.room._check_stamp([1])
        self.assertEqual(sorted(p.name for p in (self.dir / "models").iterdir()), ["Top_00.json"])
        self.assertEqual(json.loads((self.dir / "stamp.json").read_text())["clips"], S.CLIP_FORMAT)

    def test_stamp_drops_meshes_only(self):
        """모델 json 형식만 바뀌면 동작 클립 밖의 모델만 지우고 동작 클립·텍스처·아이콘은 둔다."""
        for d in ("models", "tex", "icons"):
            (self.dir / d).mkdir()
        for n in ("clip_HF@Walk.json", "anim_Female_.json", "Top_00.json", "Top_00.bin", "bdc_Female.json"):
            (self.dir / "models" / n).write_text("x")
        (self.dir / "tex" / "a.png").write_text("x")
        (self.dir / "icons" / "b.png").write_text("x")
        (self.dir / "stamp.json").write_text(json.dumps({"format": S.FORMAT, "clips": S.CLIP_FORMAT, "stamp": [1]}))  # meshes 없음
        self.room._check_stamp([1])
        self.assertEqual(sorted(p.name for p in (self.dir / "models").iterdir()), ["anim_Female_.json", "clip_HF@Walk.json"])
        self.assertTrue((self.dir / "tex" / "a.png").exists())
        self.assertTrue((self.dir / "icons" / "b.png").exists())
        self.assertEqual(json.loads((self.dir / "stamp.json").read_text())["meshes"], S.MESH_FORMAT)

    def test_fbx(self):
        self.assertEqual(self.room._fbx("body:Female"), ("body", C.body_paths("Female")["body"]))
        self.assertEqual(self.room._fbx("eye:Girl"), ("eye", C.body_paths("Girl")["eye"]))
        self.assertEqual(self.room._fbx("anim:Male:Fat"), ("anim", C.stand_path("Male", "Fat")))
        self.assertEqual(self.room._fbx("anim:Male:"), ("anim", C.stand_path("Male", "")))
        item = C.Item("Female_Maid_Top_00", "Female", "Top", "Maid", "x.fbx")
        self.room._items = {item.id: item}
        self.assertEqual(self.room._fbx(item.id), ("item", "x.fbx"))
        for bad in ("anim:Male:Bogus", "body:Female:Fat", "head:Nobody", "skin:Female", "Female_None_Top_00"):
            with self.assertRaises(S.DressError, msg=bad):
                self.room._fbx(bad)

    def test_path_stays_inside(self):
        (self.dir / "models").mkdir()
        (self.dir / "models" / "a.json").write_text("{}")
        self.assertEqual(self.room.path("models/a.json"), (self.dir / "models" / "a.json").resolve())
        self.assertIsNone(self.room.path("models/none.json"))
        self.assertIsNone(self.room.path("../" + self.dir.name + "/models/a.json/.."))
        self.assertIsNone(self.room.path("../x"))

    def test_pack_without_game(self):
        with self.assertRaises(S.DressError):
            self.room.pack()

    def test_unknown_error_is_one_model(self):
        """처음 보는 오류는 서비스 한 곳(_guard)에서 DressError 로 — 창과 이 캐시를 쓰는 다른 프로그램이 같은 판정을 본다."""
        boom = ValueError("형식")
        with mock.patch.object(self.room, "_model", side_effect=boom), self.assertLogs("mabi", "WARNING") as cm:
            with self.assertRaises(S.DressError) as ctx:
                self.room.model("Female_A_Top_00")
        self.assertIn("ValueError", str(ctx.exception))
        self.assertIs(ctx.exception.__cause__, boom)              # 점검 도구는 처음 오류를 본다
        self.assertIn("Female_A_Top_00", cm.output[0])
        with mock.patch.object(self.room, "_icon", side_effect=ImportError("x", name="UnityPy.files")):
            with self.assertRaisesRegex(S.DressError, "UnityPy"):
                self.room.icon("a")
        with mock.patch.object(self.room, "_model", side_effect=S.DressError("모르는 모델: x")):
            with self.assertRaisesRegex(S.DressError, "^모르는 모델: x$"):
                self.room.model("x")

    def test_library_failure_marks_partial(self):
        """실행용 메시 목차를 못 읽은 채(환경 탓) 꺼낸 의상은 반쪽으로 표시해 다음에 다시 꺼낸다."""
        item = C.Item("Female_A_Top_00", "Female", "Top", "A", "x.fbx")
        self.room._items = {item.id: item}
        self.room._pack = NS()
        self.room._lib_err = OSError("디스크")

        def run(self_, fbx, out, **kw):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("{}")
        with (mock.patch.object(S.Exporter, "run", run),
              mock.patch.object(self.room, "_effects", return_value=(None, None)),
              self.assertLogs("mabi", "WARNING")):
            self.assertEqual(self.room.model(item.id), "models/Female_A_Top_00.json")
        self.assertTrue((self.dir / "models" / "Female_A_Top_00.partial").exists())


class DressWindowApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from gui_app import dressroom as D
        except ImportError as e:   # PySide6 없는 환경
            raise unittest.SkipTest(str(e))
        cls.D = D

    def test_one_window(self):
        """띄운 드레스룸이 살아 있으면 신호가 안 닿아도 두 번째 창을 띄우지 않는다 (11-16 두 창이 같이 돈 것)."""
        D = self.D
        la = D.Launcher()
        la.proc, la.started = mock.Mock(pid=1, **{"poll.return_value": None}), time.time() - 600
        with mock.patch.object(D, "_poke", return_value=False), mock.patch.object(D.subprocess, "Popen") as pop:
            self.assertEqual(la.open("dark"), {"ok": True})
            pop.assert_not_called()
            la.proc.poll.return_value = 0   # 닫혔으면 새로 띄운다
            pop.return_value = mock.Mock(pid=2)
            with mock.patch.object(D.threading, "Thread"):
                self.assertEqual(la.open("dark"), {"ok": True})
            pop.assert_called_once()

    def test_resolve(self):
        room = NS(path=lambda rel: ("cache", rel))
        D = self.D
        self.assertEqual(D.resolve(room, "/cache/models/a.json"), ("cache", "models/a.json"))
        self.assertEqual(D.resolve(room, "/"), (D.APP_DIR / "index.html").resolve())
        self.assertEqual(D.resolve(room, "/viewer.js"), (D.APP_DIR / "viewer.js").resolve())
        self.assertIsNone(D.resolve(room, "/../dressroom.py"))
        self.assertIsNone(D.resolve(room, "/nothing.js"))

    def test_api(self):
        """드레스룸 화면 → DressApi → 제어 통로 명령 → 리모콘 Api 까지 (파이프만 빼고)."""
        from gui_app import control
        from gui_app.api import Api
        calls = []

        class FakeApi:
            cfg = {"dressroom": "깨진 값"}
            dress_preset = Api.dress_preset

            def cfg_get(self):
                return self.cfg

            def cfg_set(self, k, v):
                self.cfg[k] = v

            def dye_add(self, name, cols):
                calls.append(("add", name, cols))
                return {"presets": [name]}

            def _retarget(self, r):
                calls.append(("retarget",))
                return r

            def _emit(self, ev, data):
                calls.append(("emit", ev))

            def dye_reach(self, colors, tols=None):
                return {"colors": colors}

        cmds = control.Commands(FakeApi())

        def call(cmd, args):   # control.call 대신 — 답 모양을 같게
            r = cmds.run(cmd, args)
            if not r["ok"]:
                raise RuntimeError(r["message"])
            return r["data"]

        def model(mid):   # 처음 보는 오류도 서비스가 DressError 로 바꿔 준다 (ServiceTest.test_unknown_error_is_one_model)
            if mid == "bad":
                raise S.DressError("없음")
            return "models/" + mid + ".json"

        room = NS(model=model, catalog=lambda: {"items": []})
        d = self.D.DressApi(room, call)
        self.assertEqual(d.prefs(), {})                                   # 깨진 값은 빈 것으로
        d.save_prefs({"body": "Male"})
        self.assertEqual(d.prefs(), {"body": "Male"})
        d.save_prefs("문자열")
        self.assertEqual(d.prefs(), {"body": "Male"})
        self.assertFalse(cmds.run("dress_prefs", {"set": "문자열"})["ok"])
        self.assertEqual(d.model("a"), {"url": "cache/models/a.json"})
        self.assertEqual(d.model("bad"), {"error": "없음"})
        self.assertEqual(d.reach(["#FFFFFF"]), {"colors": ["#FFFFFF"]})
        self.assertEqual(d.to_preset("이름", []), {"error": "색이 없습니다"})
        self.assertEqual(d.to_preset("", ["#111111", 3, "#222222", "#333333", "#444444"]), {"ok": True})
        self.assertEqual(calls, [("add", "드레스룸", ["#111111", "#222222", "#333333"]), ("retarget",),
                                 ("emit", "mm:dye-prefs")])

        def dead(cmd, args):   # 리모콘이 꺼졌다 — 창은 그대로, 오류만
            raise RuntimeError("리모콘에 붙지 못했습니다")
        d2 = self.D.DressApi(room, dead)
        with self.assertLogs("mabi", "WARNING"):
            self.assertIn("리모콘", d2.reach(["#FFFFFF"])["error"])
            self.assertEqual(d2.prefs(), {})
        self.assertEqual(d2.model("a"), {"url": "cache/models/a.json"})

    def test_game_look(self):
        """게임 캐릭터 불러오기 — DressApi → 제어 통로 dress_look → 패킷 감시의 외형 요약."""
        from unittest import mock
        from gui_app import control
        from mabi import packet_monitor
        cmds = control.Commands(NS())

        def call(cmd, args):
            r = cmds.run(cmd, args)
            if not r["ok"]:
                raise RuntimeError(r["message"])
            return r["data"]

        def game_look(snap):
            if snap.get("body") == "Elf":
                raise S.DressError("모르는 체형")
            return {"body": snap["body"]}, ["활"]
        d = self.D.DressApi(NS(game_look=game_look), call)
        with mock.patch.object(packet_monitor, "current", return_value=None):
            self.assertIn("패킷 감시", d.game_look()["error"])
        pm = NS(look=NS(snapshot=lambda: None))
        with mock.patch.object(packet_monitor, "current", return_value=pm):
            self.assertIn("아직", d.game_look()["error"])
            pm.look.snapshot = lambda: {"body": "Female", "at": "2026-11-15 12:00:00"}
            self.assertEqual(d.game_look(), {"look": {"body": "Female"}, "miss": ["활"], "at": "2026-11-15 12:00:00"})
            pm.look.snapshot = lambda: {"body": "Elf"}
            self.assertEqual(d.game_look(), {"error": "모르는 체형"})

    def test_look_files(self):
        """코디 내보내기·가져오기 — 파일 창은 가짜로 바꾸고 임시 폴더에 쓴다."""
        from unittest import mock
        D = self.D
        d = D.DressApi(None, None)
        self.assertEqual(d.look_import(), {"canceled": True})   # 창이 없으면 고른 것도 없다
        d.gui = NS(call=lambda fn: fn())
        look = {"name": "a", "body": "Female", "worn": {"Top": {"id": "x", "colors": ["#111111"] * 3}}}
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "코디.json"
            with mock.patch("PySide6.QtWidgets.QFileDialog.getSaveFileName", return_value=(str(f), "")) as save:
                self.assertEqual(d.look_export("a/b:c", look), {"ok": True, "file": "코디.json"})
                self.assertTrue(save.call_args[0][2].endswith("abc.json"))   # 파일 이름에 못 쓰는 글자는 뺀다
            self.assertEqual(json.loads(f.read_text(encoding="utf-8"))["format"], D.LOOK_FORMAT)
            with mock.patch("PySide6.QtWidgets.QFileDialog.getOpenFileName", return_value=(str(f), "")):
                r = d.look_import()
            self.assertEqual((r["file"], r["look"]["worn"]["Top"]["id"]), ("코디", "x"))
            other = Path(t) / "다른.json"
            other.write_text(json.dumps({"name": "a"}), encoding="utf-8")
            with mock.patch("PySide6.QtWidgets.QFileDialog.getOpenFileName", return_value=(str(other), "")):
                self.assertIn("코디 파일이 아닙니다", d.look_import()["error"])
            other.write_text("{깨짐", encoding="utf-8")
            with mock.patch("PySide6.QtWidgets.QFileDialog.getOpenFileName", return_value=(str(other), "")):
                self.assertIn("읽지 못했습니다", d.look_import()["error"])
            with mock.patch("PySide6.QtWidgets.QFileDialog.getOpenFileName", return_value=("", "")):
                self.assertEqual(d.look_import(), {"canceled": True})

    def test_child_argv(self):
        D = self.D
        a = D.child_argv("light")
        self.assertEqual(a[0], sys.executable)
        self.assertEqual(a[-2:], ["--dressroom", "--theme=light"])
        self.assertEqual(D._theme(a), "light")
        self.assertEqual(D._theme(["gui.py", "--dressroom"]), "dark")
        self.assertNotIn("--disable-gpu ", D.GPU_FLAGS + " ")


class AuditTest(unittest.TestCase):
    """전체 의상 점검(tools/dress_audit.py)이 잡는 것 — 기준선은 docs/DRESSROOM.md."""
    def test_check(self):
        from mabi.dress import audit as AU
        meta = {"materials": [{"name": "Top", "kind": "dye"}, {"name": "body", "kind": "color"},
                              {"name": "Female_Body_00", "kind": "dye", "skin": True},
                              {"name": "Glass", "kind": "color"}],
                "meshes": [{"name": "Mesh_Top", "groups": [{"mat": 0}, {"mat": 3}]},
                           {"name": "Mesh_Skin_Body", "skin": True, "groups": [{"mat": 1}]},
                           {"name": "Mesh_Skin_Top", "skin": True, "groups": [{"mat": 2}]}]}
        self.assertEqual(AU.check(meta, "Texture X: cab-ab12 없음\n둘째 줄"),
                         ["color-no-tex:Mesh_Top:Glass", "skin-mesh-not-skin:Mesh_Skin_Body:body",
                          "partial:Texture X: cab-ab12 없음"])
        self.assertEqual(AU.check(meta | {"meshes": meta["meshes"][2:]}), [])

    def test_rows_and_summary(self):
        from mabi.dress import audit as AU
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "audit_0.jsonl").write_text(
                '{"id": "a", "issues": ["partial:x", "color-no-tex:m:g"]}\n{"id": "b", "error": "E"}\n{"id": "c", "iss',
                encoding="utf-8")   # 끊길 때 반쯤 쓴 끝 줄은 버린다
            rs = AU.rows(Path(t))
        self.assertEqual([r["id"] for r in rs], ["a", "b"])
        self.assertEqual(AU.summary(rs), {"error": 1, "partial": 1, "skin-mesh-not-skin": 0, "color-no-tex": 1})


if __name__ == "__main__":
    unittest.main()
