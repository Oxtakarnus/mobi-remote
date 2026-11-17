"""드레스룸 — 번호 0 번들·항목, 실행용 메시 파일(modular), fbx 없는 모델 목록·내보내기. 합성 바이트로만 (게임 파일 없이)."""
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

import numpy as np

from mabi import gamefiles as gf
from mabi.dress import assets as A
from mabi.dress import catalog as C
from mabi.dress import export as E
from mabi.dress import modular as MD

H = C.H


# ── 묶음 파일 ──
def _unityfs(body: bytes) -> bytes:
    """UnityFS 머리(판 6) + body. 머리의 size 가 전체 길이."""
    head = b"UnityFS\0" + struct.pack(">I", 6) + b"5.x.x\0" + b"2022.3.0f1\0"
    size = len(head) + 20 + len(body)
    return head + struct.pack(">qIII", size, 0, 0, 0) + body


def _asset_blob(bundles: list[bytes]) -> bytes:
    """u32 0 | u32 n | 오프셋 표 (번들 1… 시작, 끝) | 번들 0 | 번들 1 …"""
    n = 8 + 4 * len(bundles)
    pos, offs = n, []
    for b in bundles:
        pos += len(b)
        offs.append(pos)
    return struct.pack("<II", 0, n) + struct.pack("<%dI" % len(offs), *offs) + b"".join(bundles)


def _res_blob(items: list[bytes]) -> bytes:
    """ResourcesPackage 묶음 — 항목 = XOR(4바이트 원래 크기 + raw deflate). 번호 0 항목은 표 바로 뒤."""
    n = 8 + 4 * len(items)
    raws = []
    for it in items:
        c = zlib.compressobj(9, zlib.DEFLATED, -15)
        raws.append(struct.pack("<I", len(it)) + c.compress(it) + c.flush())
    pos, offs, body = n, [], b""
    for r in raws:
        body += gf._unxor(r, pos, len(r))   # XOR 라 같은 함수로 감싼다
        pos += len(r)
        offs.append(pos)
    return struct.pack("<II", 0, n) + struct.pack("<%dI" % len(offs), *offs) + body + b"\0" * 8


class ZeroEntryTest(unittest.TestCase):
    def test_asset_starts_and_read(self):
        b0, b1 = _unityfs(b"zero"), _unityfs(b"one-one")
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "AssetPackages").mkdir()
            (Path(d) / "AssetPackages" / "0003.blob").write_bytes(_asset_blob([b0, b1]) + b"tail")
            with open(Path(d) / "AssetPackages" / "0003.blob", "rb") as fh:
                self.assertEqual(A._starts(fh), (16, 16 + len(b0), 16 + len(b0) + len(b1)))
            pack = A.AssetPack.__new__(A.AssetPack)
            pack.root = Path(d) / "AssetPackages"
            self.assertEqual(pack.read(("", 3, 0)), b0)   # 번호 0 = 표 바로 뒤
            self.assertEqual(pack.read(("", 3, 1)), b1)

    def test_open_names_each_bundle(self):
        """번들마다 이름을 준다 — 이름이 없으면 UnityPy 가 BytesIO 주소로 지어 앞 번들을 덮어쓸 수 있다."""
        import UnityPy

        class Env:
            def __init__(self):
                self.files, self.names = {}, []

            def load_file(self, f, name=None):
                self.names.append(name)
                self.files[name] = NS(files={})

        pack = A.AssetPack.__new__(A.AssetPack)
        pack.paths = {"a": ("", 1, 0), "b": ("Starter", 1, 0)}
        pack.read = lambda b: b"x"
        pack.cabs = lambda: {}
        with mock.patch.object(UnityPy, "Environment", Env):
            env = pack.open(["a", "b"])
        self.assertEqual(len(set(env.names)), 2)
        self.assertNotIn(None, env.names)

    def test_resources_entry_zero(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "0001.blob"
            f.write_bytes(_res_blob([b"first item", b"second"]))
            self.assertEqual(gf._entry(f, -1), b"first item")   # 목차 번호 0
            self.assertEqual(gf._entry(f, 0), b"second")        # 목차 번호 1


# ── SkinnedModularMesh ──
def _s(t: str) -> bytes:
    b = t.encode("utf-8")
    return bytes([len(b)]) + b


def _smm(flags, verts, tris, bones, shapes=(), groups=0, colors=0) -> bytes:
    """verts: [(pos, nrm, [묶음 4f…], [(뼈, 무게)…], [셰이프 위치…])], tris: [(서브메시, a, b, c)], bones: [(이름, 16f)]."""
    out = _s("Mesh_Top_00") + struct.pack("<II", flags, len(shapes)) + b"".join(_s(x) for x in shapes)
    out += struct.pack("<I", len(verts))
    for pos, nrm, grp, ws, sp in verts:
        assert len(grp) == groups and len(sp) == len(shapes)
        out += struct.pack("<6f", *pos, *nrm)
        for g in grp:
            out += struct.pack("<4f", *g)
        out += struct.pack("<I", len(ws)) + b"".join(_s(n) + struct.pack("<f", w) for n, w in ws)
        out += b"\x11" * 16 * colors
        for p in sp:
            out += struct.pack("<3f", *p)
        out += struct.pack("<%df" % (3 * len(sp)), *([0.0] * 3 * len(sp)))
    out += struct.pack("<I", len(tris)) + b"".join(struct.pack("<4I", *t) for t in tris)
    out += struct.pack("<I", len(bones)) + b"".join(_s(n) + struct.pack("<16f", *m) for n, m in bones)
    return out


def _bind_unity():
    """Unity 바인드포즈 하나 (z 축 90도 회전 + 이동) — 파일에는 열 우선으로."""
    m = np.array([[0, -1, 0, 0.5], [1, 0, 0, -0.25], [0, 0, 1, 2.0], [0, 0, 0, 1]], np.float32)
    return m, m.T.reshape(-1).tolist()


class SmmTest(unittest.TestCase):
    def test_layout(self):
        self.assertEqual(MD._layout(0x1), (0, 0))
        self.assertEqual(MD._layout(0x7), (2, 0))
        self.assertEqual(MD._layout(0x85), (1, 0))
        self.assertEqual(MD._layout(0x45), (1, 1))
        self.assertEqual(MD._layout(0x2F), (4, 1))   # 0x20 이 0x8 과 같이 있으면 앞 묶음 하나 더

    def test_plain_coords_weights_bind(self):
        mu, col = _bind_unity()
        ws = [("Hips", 0.5), ("Spine", 0.2), ("A", 0.15), ("B", 0.1), ("C", 0.05)]   # 5개 → 상위 4개, 다시 정규화
        verts = [((1, 2, 3), (0, 1, 0), [], ws, []),
                 ((4, 5, 6), (0, 0, 1), [], [("Hips", 1.0)], []),
                 ((7, 8, 9), (1, 0, 0), [], [("Spine", 1.0)], [])]
        bones = [(n, col) for n in ("Hips", "Spine", "A", "B", "C")]
        p = MD.read_smm(_smm(0x1, verts, [(0, 0, 1, 2)], bones))
        self.assertEqual(p.name, "Mesh_Top_00")
        np.testing.assert_allclose(p.pos[0], [1, -3, 2])    # Unity (x,y,z) → fbx (x,-z,y)
        np.testing.assert_allclose(p.nrm[0], [0, 0, 1])
        self.assertIsNone(p.uv)
        self.assertEqual(p.subs[0].tolist(), [0, 1, 2])
        self.assertEqual(p.bones, ["Hips", "Spine", "A", "B", "C"])
        self.assertAlmostEqual(float(p.w[0].sum()), 1.0, places=6)
        self.assertEqual(p.idx[0, 0], 0)                    # 가장 무거운 뼈가 앞
        self.assertNotIn(4, p.idx[0].tolist())              # 가장 가벼운 C 는 빠진다
        # 바인드: fbx 좌표 정점에 바꾼 바인드를 곱하면 Unity 정점에 원래 바인드를 곱한 것과 같다
        bf = p.bind[0].reshape(4, 4)
        vu = np.array([1, 2, 3, 1], np.float32)
        vf = np.array([*p.pos[0], 1], np.float32)
        np.testing.assert_allclose(bf @ vf, mu @ vu, atol=1e-5)

    def test_tangent_then_uv(self):
        tan = (0.0, 0.0, 1.0, 0.7)   # [0, x, y, z] — z 칸이 0 이 아니면 접선
        verts = [((0, 0, 0), (0, 1, 0), [tan, (0, 0.25, 0.75, 0)], [("Hips", 1.0)], []),
                 ((1, 0, 0), (0, 1, 0), [(0, 1, 0, 0), (0, 0.5, 0.5, 0)], [("Hips", 1.0)], [])]
        p = MD.read_smm(_smm(0x7, verts, [(0, 0, 1, 1)], [("Hips", _bind_unity()[1])], groups=2))
        np.testing.assert_allclose(p.uv, [[0.25, 0.75], [0.5, 0.5]])
        self.assertIsNone(p.uv1)

    def test_uv_and_shapes(self):
        verts = [((0, 0, 0), (0, 1, 0), [(0, 0.1, 0.2, 0)], [("Hips", 1.0)], [(0, 1, 0)]),
                 ((1, 0, 0), (0, 1, 0), [(0, 0.3, 0.4, 0)], [("Hips", 1.0)], [(1, 0, 0)])]
        p = MD.read_smm(_smm(0x85, verts, [(1, 0, 1, 1)], [("Hips", _bind_unity()[1])], shapes=("Fat",), groups=1))
        np.testing.assert_allclose(p.uv, [[0.1, 0.2], [0.3, 0.4]], atol=1e-6)
        self.assertEqual(list(p.subs), [1])
        self.assertEqual(list(p.shapes), ["Fat"])           # 변화 없는 정점은 0
        np.testing.assert_allclose(p.shapes["Fat"], [[0, 0, 1], [0, 0, 0]], atol=1e-6)   # Unity y+1 → fbx z+1

    def test_colors_and_unknown_flags(self):
        verts = [((0, 0, 0), (0, 1, 0), [(0, 0.1, 0.2, 0)], [("Hips", 1.0)], []),
                 ((1, 0, 0), (0, 1, 0), [(0, 0.3, 0.4, 0)], [("Hips", 1.0)], [])]
        b = _smm(0x45, verts, [(0, 0, 1, 1)], [("Hips", _bind_unity()[1])], groups=1, colors=1)
        np.testing.assert_allclose(MD.read_smm(b).uv, [[0.1, 0.2], [0.3, 0.4]], atol=1e-6)
        # flags 로 정한 배치가 틀려도 파일이 딱 끝나는 배치를 찾는다
        odd = _smm(0x1, verts, [(0, 0, 1, 1)], [("Hips", _bind_unity()[1])], groups=1, colors=1)
        np.testing.assert_allclose(MD.read_smm(odd).uv, [[0.1, 0.2], [0.3, 0.4]], atol=1e-6)
        with self.assertRaises(MD.PartError):
            MD.read_smm(odd[:-3])


# ── MESHCOLL ──
def _fixed64(t: str) -> bytes:
    b = t.encode("utf-8")
    return struct.pack("<H", len(b)) + b + b"\0" * (62 - len(b))


def _meshes(name="Mesh_Hair_00_H0") -> bytes:
    nv = 3
    # 스트림 0: 위치·법선·UV (보폭 32), 스트림 1: 무게 f32×4 · 뼈 번호 u32×4 (보폭 32)
    s0 = b"".join(struct.pack("<8f", i, 0, 0, 0, 0, 1, 0.1 * i, 0.2 * i) for i in range(nv))
    s1 = b"".join(struct.pack("<4f4I", 1, 0, 0, 0, i % 2, 0, 0, 0) for i in range(nv))
    ix = struct.pack("<3H", 0, 1, 2)
    attrs = [(0, 0, 3, 0, 0), (1, 0, 3, 0, 12), (4, 0, 2, 0, 24), (12, 0, 4, 1, 0), (13, 10, 4, 1, 16)]
    head = bytes([len(name)]) + name.encode()
    vals = [nv, len(attrs), *[x for a in attrs for x in a], 2, 32, 0, 32, 1, 3, 8, 1, 0, 3, 2, 0]
    head += struct.pack("<%dI" % len(vals), *vals)
    data = struct.pack("<I", 3)
    for ch in (s0, s1, ix):
        data += struct.pack("<iiI", -1, -1, len(ch)) + ch
    binds = [np.eye(4, dtype=np.float32), np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 5, 1]], np.float32)]
    data += struct.pack("<I", 2) + b"".join(m.tobytes() for m in binds)   # 열 우선 = 위 행렬의 전치
    data += _fixed64("Root") + struct.pack("<I", 2) + _fixed64("Bip_Head") + _fixed64("Bip_Hair_01")
    n = 1
    base = 20 + 16 * n
    return b"MESHCOLL" + struct.pack("<III", 1, n, n) + struct.pack("<II", base, len(head)) \
        + struct.pack("<II", base + len(head), len(data)) + head + data


class MeshesTest(unittest.TestCase):
    def test_read(self):
        (p,) = MD.read_meshes(_meshes())
        self.assertEqual(p.name, "Mesh_Hair_00_H0")
        np.testing.assert_allclose(p.pos[:, 0], [0, 1, 2])
        np.testing.assert_allclose(p.nrm[0], [0, 0, 1])
        np.testing.assert_allclose(p.uv[2], [0.2, 0.4], atol=1e-6)
        self.assertEqual(p.subs[0].tolist(), [0, 1, 2])
        self.assertEqual(p.bones, ["Bip_Head", "Bip_Hair_01"])
        self.assertEqual(p.idx[:, 0].tolist(), [0, 1, 0])
        self.assertEqual(p.w[:, 0].tolist(), [1, 1, 1])
        self.assertEqual(p.bind[1].reshape(4, 4)[2, 3], 5.0)   # 행 우선으로 바꿔 둔다 (이동이 4번째 열)

    def test_not_meshcoll(self):
        with self.assertRaises(MD.PartError):
            MD.read_meshes(b"NOTCOLL!" + b"\0" * 16)


class LibraryTest(unittest.TestCase):
    def test_models(self):
        lib = MD.Library.__new__(MD.Library)
        lib.paths, lib._by, lib._som = {}, {"Female_A_Top_00": ["x"]}, {"Female_Hat_Helmet_00": "S/Hat.som"}
        self.assertTrue(lib.has("Female_A_Top_00"))
        self.assertTrue(lib.has("Female_Hat_Helmet_00"))   # 모델 정의만 있어도 (메시는 다른 번들)
        self.assertFalse(lib.has("Female_None_Top_00"))

    def test_parts_skips_broken_file(self):
        lib = MD.Library.__new__(MD.Library)
        good = _smm(0x1, [((0, 0, 0), (0, 1, 0), [], [("Hips", 1.0)], [])], [], [("Hips", _bind_unity()[1])])
        files = {"M/Female_A_Top_00_0" + MD._SMM: b"broken", "M/Female_A_Top_00_1" + MD._SMM: good,
                 "M/Female_A_Top_00" + MD._COLL: _meshes("Mesh_Top_00")}
        lib._by = {"Female_A_Top_00": list(files)}
        lib.read = files.__getitem__
        parts = lib.parts("Female_A_Top_00")
        self.assertEqual(list(parts), ["Mesh_Top_00"])
        self.assertIsNone(parts["Mesh_Top_00"].uv)          # SkinnedModularMesh 가 먼저 (.meshes 는 없는 이름만)


# ── 목록 ──
class CatalogRuntimeTest(unittest.TestCase):
    PATHS = [
        H + "Female/Top/ForAssetBundle/Female_Maid_Top_00.prefab",
        H + "FBX/Human/Female/Top/Female_Maid_Top_00.fbx",
        H + "Female/Top/ForAssetBundle/Female_Print_Top_01.prefab",       # fbx 없음, 실행용 자료 있음
        H + "Female/Helmet/Female_Bag_Helmet_00.prefab",                  # fbx 없음, 실행용 자료 있음
        H + "Female/Top/ForAssetBundle/Female_Gone_Top_00.prefab",        # fbx 도 실행용 자료도 없음
    ]

    def test_runtime(self):
        self.assertEqual([i.id for i in C.build(self.PATHS)], ["Female_Maid_Top_00"])
        items = C.build(self.PATHS, runtime={"Female_Print_Top_01", "Female_Bag_Helmet_00", "Female_Maid_Top_00"}.__contains__)
        by = {i.id: i for i in items}
        self.assertEqual(sorted(by), ["Female_Bag_Helmet_00", "Female_Maid_Top_00", "Female_Print_Top_01"])
        self.assertTrue(by["Female_Maid_Top_00"].fbx.endswith(".fbx"))       # fbx 가 있으면 fbx
        self.assertEqual(by["Female_Print_Top_01"].fbx, self.PATHS[2])      # 없으면 prefab


# ── 내보내기 (실행용 메시로 채우기) ──
def _mat_ptr(name):
    sp = NS(m_TexEnvs=[], m_Colors=[], m_Floats=[])
    m = NS(m_Name=name, m_SavedProperties=sp, m_ValidKeywords=[])
    return NS(m_PathID=1, deref=lambda: NS(read=lambda: m))


def _part(name, bones, n=3, subs=None, w=None):
    idx = np.zeros((n, 4), np.uint16)
    ww = np.zeros((n, 4), np.float32) if w is None else w
    return MD.Part(name, np.arange(n * 3, dtype=np.float32).reshape(n, 3), np.zeros((n, 3), np.float32),
                   np.zeros((n, 2), np.float32), None, subs if subs is not None else {0: np.array([0, 1, 2], np.uint32)},
                   bones, np.tile(np.eye(4, dtype=np.float32).reshape(1, 16), (len(bones), 1)), idx, ww)


class PartExportTest(unittest.TestCase):
    NODES = [{"path": "Bip"}, {"path": "Bip/Hips"}, {"path": "Bip/Hips/Spine"}]
    BY_ID = {1: "Bip", 2: "Bip/Hips", 3: "Bip/Hips/Spine"}

    def test_bone_paths(self):
        r = NS(m_Bones=[NS(m_PathID=3), NS(m_PathID=2)])
        self.assertEqual(E._bone_paths(["Spine", "Hips"], r, self.BY_ID, self.NODES), ["Bip/Hips/Spine", "Bip/Hips"])
        # 렌더러 뼈 순서가 다르면 뼈대에서 끝 이름으로
        self.assertEqual(E._bone_paths(["Hips", "Spine"], r, self.BY_ID, self.NODES), ["Bip/Hips", "Bip/Hips/Spine"])
        self.assertIsNone(E._bone_paths(["Hips", "Tail"], NS(m_Bones=[]), self.BY_ID, self.NODES))

    def test_part_src(self):
        p = _part("Mesh_Top_00", ["Hips"], subs={1: np.array([0, 1, 2], np.uint32)})
        src = E._part_src(p, NS(m_Bones=[]), self.BY_ID, self.NODES)
        self.assertIsNone(src.tris[0])                      # 비어 있는 서브메시 자리
        self.assertEqual(src.tris[1].tolist(), [0, 1, 2])
        paths, idx, w, bind = src.skin
        self.assertEqual(paths, ["Bip/Hips"])
        self.assertEqual(w[:, 0].tolist(), [1, 1, 1])        # 무게 없는 정점은 첫 뼈에
        self.assertEqual(p.w.sum(), 0)                       # Part 는 그대로
        self.assertIsNone(E._part_src(_part("M", ["Tail"]), NS(m_Bones=[]), self.BY_ID, self.NODES).skin)

    def test_run_fills_empty_mesh(self):
        go = NS(m_Name="Mesh_Top_00")
        cut = NS(m_Name="Mesh_BP_LArm")
        sep = NS(m_Name="Mesh_SP_LHand")
        cage = NS(m_Name="Cage_Top")
        r = NS(m_Bones=[NS(m_PathID=2)], m_Materials=[_mat_ptr("Cloth")])
        rc = NS(m_Bones=[NS(m_PathID=2)], m_Materials=[])
        calls = []
        parts = {n: _part(n, ["Hips"]) for n in ("Mesh_Top_00", "Mesh_BP_LArm", "Mesh_SP_LHand", "Cage_Top")}
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(E.A, "roots", lambda env, path: [NS()]), \
                mock.patch.object(E.A, "renderers",
                                  lambda root: [(go, r), (cut, rc), (sep, rc), (cage, rc), (NS(m_Name="Mesh_None"), r)]), \
                mock.patch.object(E, "skeleton", lambda root: (self.NODES, self.BY_ID)), \
                mock.patch.object(E, "mesh_of", lambda g, rr: None):
            ex = E.Exporter(NS(open=lambda paths: None), Path(d) / "tex")
            meta = ex.run("x.prefab", Path(d) / "m.json", parts=lambda: calls.append(1) or parts)
            binb = (Path(d) / "m.bin").read_bytes()
        self.assertEqual(calls, [1])                         # 한 번만 읽는다
        self.assertEqual([m["name"] for m in meta["meshes"]], ["Mesh_Top_00", "Mesh_BP_LArm", "Mesh_SP_LHand"])
        top, arm, hand = meta["meshes"]
        self.assertEqual(top["rig"]["bones"], ["Bip/Hips"])
        self.assertEqual(top["groups"][0]["count"], 3)
        self.assertEqual(meta["materials"][0]["name"], "Cloth")
        self.assertTrue(arm["cut"])
        self.assertEqual(arm["groups"], [])
        self.assertTrue(hand["sep"])                         # 옷 자르는 판 — 자리만, 그리지 않는다
        self.assertNotIn("cut", hand)
        self.assertEqual(hand["groups"], [])
        pos = np.frombuffer(binb, np.float32, 9, top["pos"]).reshape(3, 3)
        np.testing.assert_allclose(pos, parts["Mesh_Top_00"].pos)

    def test_run_without_parts_fails(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(E.A, "roots", lambda env, path: [NS()]), \
                mock.patch.object(E.A, "renderers", lambda root: [(NS(m_Name="Mesh_Top_00"), NS(m_Bones=[], m_Materials=[]))]), \
                mock.patch.object(E, "skeleton", lambda root: ([], {})), \
                mock.patch.object(E, "mesh_of", lambda g, rr: None):
            with self.assertRaises(E.ExportError):
                E.Exporter(NS(open=lambda paths: None), Path(d)).run("x.prefab", Path(d) / "m.json")


if __name__ == "__main__":
    unittest.main()
