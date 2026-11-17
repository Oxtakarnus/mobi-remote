"""모델 하나(fbx 또는 prefab 자산) → 뷰어가 읽는 메시 묶음 (json + bin) + 텍스처 png.

prefab 은 렌더러의 메시 칸이 비어 있다 (게임이 실행 중에 채운다). 그 칸은 parts(게임 실행용 메시 파일, modular)에서
같은 이름의 메시로 채운다 — fbx 가 없는 모델(같은 메시를 쓰는 무늬 바꿈 옷 등)도 그릴 수 있다.

  <id>.json  {"version", "skeleton", "meshes", "materials", "bin": <id>.bin 이름} + 있을 때만 rules·fit(가림·겹침, cover)
             · fx(의상 이펙트) · cloth(흔들림) · attach(패션 무기) — 메시 항목의 숫자 칸은 bin 안 위치(바이트)
  <id>.bin   메시마다 삼각형 u32(재질 묶음마다) · 위치 f32×3n · 법선 f32×3n · UV f32×2n · 셰이프 위치 차이 f32×3n · (UV1)
             · 스킨(뼈 번호 u16×4n · 무게 f32×4n · 바인드포즈 f32×16 뼈마다) — 4바이트 정렬, 읽는 쪽은 json 의 위치를 따른다
  tex/<이름>.png  재질 그림 (바탕·입 표정·눈알·발광·잡음·마스크·보석 등 — textures.TextureStore)

좌표는 Unity 원래 값 그대로다 (메시는 자기 좌표, 뼈대는 부모 기준 TRS). 뷰어가 뼈대를 세우고 스키닝한 뒤
루트에서 x 를 뒤집어 오른손 좌표로 바꾼다. 옷마다 바인드 포즈가 달라(몸은 팔 내린 A, 옷은 T) 메시를 그대로
겹치면 어긋난다 — 같은 뼈대(몸)로 스키닝해야 맞는다.

뼈대(skeleton)는 루트 GameObject 아래 노드 전부: path(루트 빼고 '/' 로 이은 이름 — 애니메이션 바인딩 경로와 같다)·
parent 번호·t·r(x,y,z,w)·s. 몸에 없는 뼈(치마·머리카락 물리 뼈, 얼굴 뼈)는 뷰어가 부모 경로 밑에 붙인다.
prefab 에 흔들림(Magica BoneCloth)이 있으면 json cloth 로 담는다 (cloth.py — 계산은 web/dressroom/cloth.js).

손에 드는 도구(패션 무기, run_mounted)는 자기 뼈대가 따로라, prefab 루트를 몸 뼈(손·등 소켓) 밑 노드 하나로 두고
그 아래에 도구 뼈대를 잇는다 — 노드 경로가 '<소켓 경로>/<prefab 이름>/…' 이라 뷰어는 옷과 똑같이 그린다.
소켓까지의 몸 노드들(chain)도 같이 넣는다 (뷰어는 이미 있는 경로는 건너뛴다).

메시 이름 규칙 (확인한 것):
  Mesh_BP_*                        몸 자르는 고리 (신발·장갑 윗단 — 그 너머 몸은 옷이 자기 피부로 대신한다) → cut, 그리지 않는다
  Mesh_SP_*                        옷 자르는 판 (밑단·윗단 — 바깥 옷이 그 너머 안쪽 옷을 숨긴다) → sep, 그리지 않는다
  Cage_*                           충돌용 (안 꺼낸다)
  Mesh_Skin_*                      피부 → skin
  Mesh_Hair_00_H<k>                모자 종류 k 에 맞춘 머리 (H0 = 모자 없음) → hair = k
  Mesh_Helmet_*_C<k>               모자가 가리는 종류 → cover = k
  *Hood_On* · *Hood_Off_Pressed* · *Hood_Off*   후드 쓴 모양 · 벗었는데 머리에 눌린 모양 · 벗은 모양 → hood = on · pressed · off
                                   (뷰어가 후드 쓰기와 입은 머리로 하나만 보인다 — web/dressroom/cover.js)
  Mesh_EyeBasePlane                표정용 눈 판 → 숨김
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..fileio import write_atomic, write_json
from . import assets as A
from . import cloth as CL
from . import textures as T


class ExportError(Exception):
    pass


@dataclass
class _Src:
    """렌더러 하나의 메시 — fbx(UnityPy) 에서 꺼냈든 실행용 메시 파일에서 읽었든 같은 꼴."""
    pos: np.ndarray            # (n, 3)
    nrm: np.ndarray            # (n, 3)
    uv: np.ndarray | None      # (n, 2)
    uv1: np.ndarray | None
    tris: list                 # 서브메시 순서대로 삼각형 정점 번호
    shapes: dict               # 이름 → 위치 차이 (n, 3)
    skin: tuple | None         # (뼈 경로들, 뼈 번호 (n,4) u16, 무게 (n,4) f32, 바인드포즈 (뼈 수,16) 행 우선)


def hex_color(c) -> str:
    return "#%02X%02X%02X" % tuple(int(round(min(1.0, max(0.0, v)) * 255)) for v in (c.r, c.g, c.b))


# 뷰어가 쓰는 머티리얼 값 — 표 좌표·눈동자·입 표정, 명암(게임 캐릭터 셰이더의 값)
_VEC = re.compile(r"Atlas|ScalePosition|Eyeball_TS|EyePosition|^_(TintColor|SilhouetteTintColor|OutlineColor)$")
_FLOAT = ("_Alpha", "_RenderMode", "_MouthShowType", "_EyeRotationOffset", "_UseDyeMaskMap",
          "_ShadingType", "_FlatShadingAmountTop", "_FlatShadingAmountBottom", "_ReceiveShadowStrength",
          "_BackFaceDarkenAmount", "_SilhouetteOff", "_OutlineColorMode", "_OutlineOff", "_CullType",
          "_IsMetal", "_IsLeather", "_Smoothness", "_LeatherSmoothness",
          "_AlphaOverride", "_AlphaScaleMin", "_AlphaScaleMax", "_EffectAlphaValue", "_ZWrite")   # 반투명(_RenderMode 1)
_KEYWORDS = ("_ALPHATEST_ON", "_METAL_FEATURE", "_LEATHER_FEATURE")
_EMIT_COLORS = ("_EmissionColor", "_EmissionColorG", "_EmissionColorB")   # 발광 그림 R·G·B 가 받는 색 (HDR 선형 값)
_DYE_KEYWORDS = {"_ISDYABLE_ON", "_DYE_ON"}   # 염색 셰이더 키워드 — 대개 무효 키워드 쪽에 들어 있다
# 비치는 배경 셰이더 → 불투명도. 사물 재질을 빌려 쓰는 모자(어항의 유리·물)에 나온다.
# 셰이더 식을 볼 수 없어 값을 정해 근사하고, 뷰어의 반투명(_RenderMode 1) 길로 그린다
_SEE = {"WindowGlassAlphablend": 0.25, "Water": 0.45}


def _see_through(shader: str | None) -> float | None:
    """셰이더 이름(MMN/BG/Water) 또는 자산 경로(…/MMN_Water.shader) → 비치는 셰이더면 불투명도, 아니면 None."""
    tail = (shader or "").rsplit("/", 1)[-1].removesuffix(".shader").removeprefix("MMN_")
    return _SEE.get(tail)


def _keywords(m) -> set[str] | None:
    """머티리얼에 걸린 키워드 (유효·무효 모두). 키워드 칸 자체가 없으면 None."""
    names = ("m_ValidKeywords", "m_InvalidKeywords")
    if not any(hasattr(m, n) for n in names):
        return None
    return {k for n in names for k in (getattr(m, n, None) or [])}


class Out:
    def __init__(self):
        self.buf = bytearray()

    def put(self, a: np.ndarray) -> int:
        while len(self.buf) % 4:
            self.buf.append(0)
        at = len(self.buf)
        self.buf += np.ascontiguousarray(a).tobytes()
        return at


def transform_ptr(go):
    """GameObject 의 Transform 가리킴 (없으면 None)."""
    return A.component_ptr(go, "Transform")


def skeleton(root) -> tuple[list[dict], dict[int, str]]:
    """루트 GameObject 아래 노드 → ([{path, parent, t, r, s}], Transform 경로 id → path)."""
    nodes: list[dict] = []
    by_id: dict[int, str] = {}

    def walk(t, path, parent):
        for ch in t.m_Children:
            try:
                c = ch.deref().read()
                name = c.m_GameObject.deref().read().m_Name
            except Exception:
                continue
            p = f"{path}/{name}" if path else name
            q, v, s = c.m_LocalRotation, c.m_LocalPosition, c.m_LocalScale
            nodes.append({"path": p, "parent": parent, "t": [v.x, v.y, v.z], "r": [q.x, q.y, q.z, q.w], "s": [s.x, s.y, s.z]})
            by_id[ch.m_PathID] = p
            walk(c, p, len(nodes) - 1)

    ptr = transform_ptr(root)
    if ptr is not None:
        walk(ptr.deref().read(), "", -1)
    return nodes, by_id


def add_nodes(nodes: list[dict], more) -> None:
    """뼈대 nodes 에 노드 [{path, t, r, s}] 를 더한다 — 같은 경로는 건너뛰고, 부모 경로가 없는 노드도 버린다."""
    have = {n["path"]: i for i, n in enumerate(nodes)}
    for n in more:
        if n["path"] in have:
            continue
        up = n["path"].rpartition("/")[0]
        if up and up not in have:
            continue
        have[n["path"]] = len(nodes)
        nodes.append({"path": n["path"], "parent": have[up] if up else -1, "t": list(n["t"]), "r": list(n["r"]), "s": list(n["s"])})


def mesh_of(go, r):
    """렌더러가 그리는 메시 (없으면 None) — MeshRenderer 는 같은 GameObject 의 MeshFilter 것."""
    if hasattr(r, "m_Mesh"):
        return r.m_Mesh.deref().read() if r.m_Mesh.m_PathID else None
    mf = next((o for o in A.components(go) if o.type.name == "MeshFilter"), None)
    if mf is None:
        return None
    mf = mf.read()
    return mf.m_Mesh.deref().read() if mf.m_Mesh.m_PathID else None


def _shapes(mesh, n: int) -> dict[str, np.ndarray]:
    """채널 이름 → 마지막 프레임(가중치 100)의 위치 차이 (n, 3), 메시 자기 좌표."""
    out = {}
    sh = getattr(mesh, "m_Shapes", None)
    if not sh or not sh.channels:
        return out
    for ch in sh.channels:
        if ch.frameCount < 1 or ch.name.startswith("Mesh_"):
            continue
        fr = sh.shapes[ch.frameIndex + ch.frameCount - 1]
        d = np.zeros((n, 3), np.float32)
        for v in sh.vertices[fr.firstVertex:fr.firstVertex + fr.vertexCount]:
            if v.index < n:
                d[v.index] = (v.vertex.x, v.vertex.y, v.vertex.z)
        if np.any(d):
            out[ch.name] = d
    return out


def _four(a, n: int, dtype, fill) -> np.ndarray:
    """뼈 번호·무게 → (n, 4) (2개만 있는 메시도 있다)."""
    out = np.full((n, 4), fill, dtype)
    try:
        arr = np.asarray(a, dtype)
    except (TypeError, ValueError):
        return out
    if arr.ndim == 2 and len(arr) == n:
        k = min(4, arr.shape[1])
        out[:, :k] = arr[:, :k]
    return out


def _fill_empty(idx: np.ndarray, w: np.ndarray) -> None:
    """무게가 없는 정점(모자 등 통째로 붙는 메시)은 첫 뼈에 붙인다."""
    empty = w.sum(1) <= 1e-6
    w[empty, 0] = 1.0
    idx[empty, 0] = 0


def _cols(rows, n: int, k: int) -> np.ndarray:
    """정점 n 개의 값 목록 → (n, k) — 칸이 더 많으면 앞 k 칸만."""
    return np.ascontiguousarray(np.asarray(rows, np.float32).reshape(n, -1)[:, :k])


def _unity_src(r, mesh, by_id, cut: bool) -> _Src | None:
    """UnityPy Mesh → _Src."""
    from UnityPy.helpers.MeshHelper import MeshHandler
    h = MeshHandler(mesh)
    h.process()
    n = len(h.m_Vertices)
    if not n:
        return None
    pos = _cols(h.m_Vertices, n, 3)
    # 법선이 4칸(x,y,z,w)으로 든 메시가 있다 (베일문 가디언 아머(아이 여성)·남성 중갑신발) — 앞 칸만 쓴다
    nrm = _cols(h.m_Normals, n, 3) if h.m_Normals and len(h.m_Normals) == n else np.zeros((n, 3), np.float32)
    uv = None
    if h.m_UV0:
        uv = _cols(h.m_UV0, n, 2) if len(h.m_UV0) == n else np.zeros((n, 2), np.float32)
    uv1 = _cols(h.m_UV1, n, 2) if h.m_UV1 and len(h.m_UV1) == n else None
    skin = None
    bones = list(getattr(r, "m_Bones", None) or [])
    binds = list(getattr(mesh, "m_BindPose", None) or [])
    paths = [by_id.get(b.m_PathID) for b in bones]
    if bones and len(binds) == len(bones) and all(p is not None for p in paths):
        idx = _four(h.m_BoneIndices, n, np.uint16, 0)
        w = _four(h.m_BoneWeights, n, np.float32, 0.0)
        _fill_empty(idx, w)
        bind = np.array([[getattr(m, f"e{i}{j}") for i in range(4) for j in range(4)] for m in binds], np.float32)
        skin = (paths, idx, w, bind)
    return _Src(pos, nrm, uv, uv1, [] if cut else h.get_triangles(), _shapes(mesh, n), skin)


def _bone_paths(names: list[str], r, by_id, nodes) -> list[str] | None:
    """실행용 메시의 뼈 이름 → 뼈대 경로. 렌더러의 m_Bones 가 같은 이름·순서면 그것을, 아니면 뼈대에서 끝 이름으로
    찾는다. 하나라도 못 찾으면 None."""
    bones = list(getattr(r, "m_Bones", None) or [])
    paths = [by_id.get(b.m_PathID) for b in bones]
    if len(paths) == len(names) and all(p is not None and p.rsplit("/", 1)[-1] == nm for p, nm in zip(paths, names)):
        return paths
    tail: dict[str, str] = {}
    for nd in nodes:
        tail.setdefault(nd["path"].rsplit("/", 1)[-1], nd["path"])
    out = [tail.get(nm) for nm in names]
    return None if any(p is None for p in out) else out


def _part_src(p, r, by_id, nodes) -> _Src:
    """modular.Part → _Src. 뼈를 뼈대에서 못 찾으면 스킨 없이 (자기 노드에 붙는다)."""
    tris = [p.subs.get(i) for i in range(max(p.subs) + 1)] if p.subs else []
    skin = None
    if p.bones and len(p.bind) == len(p.bones):
        paths = _bone_paths(p.bones, r, by_id, nodes)
        if paths is not None:
            idx, w = p.idx.copy(), p.w.copy()
            _fill_empty(idx, w)
            skin = (paths, idx, w, np.asarray(p.bind, np.float32))
    return _Src(p.pos, p.nrm, p.uv, p.uv1, tris, dict(p.shapes), skin)


def _readable(ptr) -> bool:
    """포인터가 가리키는 것을 읽을 수 있나 (그 번들이 안 열렸으면 False)."""
    try:
        ptr.deref().read()
        return True
    except Exception:
        return False


def _flags(name: str) -> dict:
    f = {}
    m = re.search(r"_H(\d)$", name)
    if name.startswith("Mesh_Hair") and m:
        f["hair"] = int(m.group(1))
    m = re.search(r"_C(\d)$", name)
    if name.startswith("Mesh_Helmet") and m:
        f["cover"] = int(m.group(1))
    if "Hood_On" in name:
        f["hood"] = "on"
    elif "Hood_Off_Pressed" in name:
        f["hood"] = "pressed"
    elif "Hood_Off" in name:
        f["hood"] = "off"
    if name == "Mesh_EyeBasePlane":
        f["hidden"] = True
    if name.startswith("Mesh_Skin"):
        f["skin"] = True
    return f


class Exporter:
    def __init__(self, pack: A.AssetPack, tex_dir: Path):
        self.pack = pack
        self.textures = T.TextureStore(tex_dir)
        self._mats: dict[tuple, int] = {}
        self._wiring: dict | None = None
        self._pmats: dict[str, list] = {}   # 게임 prefab 의 렌더러 이름 → 재질 포인터들 (run 의 prefab)
        self._proot = None                  # 그 prefab 루트 (포인터가 가리키는 번들을 붙잡아 둔다)

    def run(self, fbx: str, out_json: Path, parts=None, extra: dict | None = None, wiring: dict | None = None,
            more: list[dict] | None = None, prefab: str | None = None) -> dict:
        """fbx: fbx 또는 prefab 자산 경로. parts: 메시 칸이 빈 렌더러를 채울 {메시 이름: modular.Part} 를 돌려주는
        함수 (빈 칸을 처음 만날 때 한 번 부른다). extra 는 json 에 그대로 더한다 (의상의 가림 규칙 rules).
        wiring: 염색 칸 배선 {(메시 이름, 재질 칸): [채널마다 칸]} (dyeslots.wiring) — 재질 slots 로 싣는다.
        more: 뼈대에 더할 노드 [{path, t, r, s}] (부모가 앞 — 이펙트 소켓, fx.sockets). 이미 있거나 부모가 없는 것은 건너뛴다.
        prefab: 게임이 그리는 prefab — 메시는 fbx 로 꺼내도 재질 배정은 이걸 따른다 (_prefab_mats). 흔들림도 여기서 읽는다."""
        root = self._root(fbx)
        self._pmats = self._prefab_mats(prefab) if prefab and prefab != fbx else {}
        nodes, by_id = skeleton(root)
        out = Out()
        mats: list = []
        self._mats = {}
        self._wiring = wiring
        try:
            meshes = self._meshes(root, by_id, nodes, out, mats, parts)
            cloth = self._cloth(self._proot if self._proot is not None else root if prefab else None, nodes)
        finally:
            self._pmats, self._proot = {}, None
        if not meshes:
            raise ExportError(f"그릴 메시가 없습니다: {fbx.rsplit('/', 1)[-1]}")
        add_nodes(nodes, more or ())
        if cloth:
            extra = {**(extra or {}), "cloth": cloth}
        return self.write(out_json, out, nodes, meshes, mats, extra)

    @staticmethod
    def _cloth(src, nodes: list) -> list[dict]:
        """prefab 루트의 흔들림 팀 (없으면 []). 흔드는 뼈가 fbx 뼈대에 없으면 prefab 의 그 뼈(와 조상)를 nodes 에 더한다."""
        if src is None:
            return []
        pnodes, pby = skeleton(src)
        teams = CL.read(src, pby)
        need = {p for t in teams for p in t["verts"]}
        if need:
            add_nodes(nodes, [n for n in pnodes if n["path"] in need or any(p.startswith(n["path"] + "/") for p in need)])
        return teams

    def run_mounted(self, mounts: list[dict], out_json: Path, chain: list[dict] = ()) -> dict:
        """여러 prefab 을 몸 뼈에 붙여 한 모델로 (패션 무기).
        mounts: [{path: 자산 경로, at: 붙일 노드 경로('' = 뼈대 루트), t, r(x,y,z,w), s: 붙는 자세, hidden: 안 보임,
                  parts: run 과 같은 함수 또는 None, info: json attach 에 실을 값}]. chain: 소켓까지의 몸 노드 [{path, t, r, s}].
        메시마다 piece(mounts 번호)를 단다. json attach[k] = info + node(그 prefab 루트 노드 경로, 못 꺼냈으면 None).
        그릴 메시가 하나도 없으면 ExportError."""
        nodes = [{"path": c["path"], "parent": -1, "t": list(c["t"]), "r": list(c["r"]), "s": list(c["s"])} for c in chain]
        index = {n["path"]: i for i, n in enumerate(nodes)}
        for n in nodes:
            n["parent"] = index.get(n["path"].rpartition("/")[0], -1)
        out = Out()
        mats: list = []
        self._mats = {}
        self._wiring = None
        meshes = []
        attach = [dict(mt.get("info") or {}, node=None) for mt in mounts]
        for k, mt in enumerate(mounts):
            try:
                root = self._root(mt["path"])
            except ExportError:
                continue
            sub, by_id = skeleton(root)
            base = f"{mt['at']}/{root.m_Name}" if mt.get("at") else root.m_Name
            if base in index:   # 같은 prefab 을 두 번 붙이지 않는다
                continue
            attach[k]["node"] = base
            at = len(nodes)
            nodes.append({"path": base, "parent": index.get(mt.get("at") or "", -1),
                          "t": list(mt["t"]), "r": list(mt["r"]), "s": list(mt["s"])})
            index[base] = at
            moved = []
            for nd in sub:
                q = dict(nd, path=f"{base}/{nd['path']}", parent=at if nd["parent"] < 0 else at + 1 + nd["parent"])
                index[q["path"]] = len(nodes)
                nodes.append(q)
                moved.append(q)
            ids = {i: f"{base}/{p}" for i, p in by_id.items()}
            tp = transform_ptr(root)
            if tp is not None:   # 루트에 바로 붙은 렌더러·뼈
                ids[tp.m_PathID] = base
            for m in self._meshes(root, ids, moved, out, mats, mt.get("parts")):
                m["piece"] = k
                if mt.get("hidden"):
                    m["hidden"] = True
                meshes.append(m)
        if not meshes:
            raise ExportError(f"그릴 메시가 없습니다: {mounts[0]['path'].rsplit('/', 1)[-1] if mounts else '-'}")
        return self.write(out_json, out, nodes, meshes, mats, {"attach": attach})

    def _prefab_mats(self, path: str) -> dict[str, list]:
        """prefab 렌더러 이름 → 재질 포인터 목록. fbx 의 재질 배정은 작업 파일 것이라 게임과 다를 수 있다
        (폼폼 소다 웨어 비키니에 반투명 셔츠 재질, 검사학교·하이스쿨 크러쉬 교복 피부 조각에 천·빈 재질). 못 열면 {}."""
        try:
            self._proot = self._root(path)
        except ExportError:
            return {}
        return {go.m_Name: list(r.m_Materials) for go, r in A.renderers(self._proot) if r.m_Materials}

    def _root(self, path: str):
        env = self.pack.open([path])
        gos = A.roots(env, path)
        if not gos:
            raise ExportError(f"모델을 찾지 못했습니다: {path.rsplit('/', 1)[-1]}")
        return gos[0]

    @staticmethod
    def write(out_json: Path, out: Out, nodes: list, meshes: list, mats: list, extra: dict | None = None) -> dict:
        """모델 bin → json 순서로 쓴다 (json 이 있으면 다 쓴 모델 — 서비스가 그것으로 캐시를 본다)."""
        out_json = Path(out_json)
        write_atomic(out_json.with_suffix(".bin"), bytes(out.buf))
        meta = {"version": 2, "skeleton": nodes, "meshes": meshes, "materials": mats,
                "bin": out_json.with_suffix(".bin").name, **(extra or {})}
        write_json(out_json, meta)
        return meta

    def _meshes(self, root, by_id: dict, nodes: list, out: Out, mats: list, parts=None) -> list[dict]:
        """루트 아래 렌더러들 → 메시 항목들 (버퍼는 out, 머티리얼은 mats 에 더한다)."""
        meshes = []
        got = None
        for go, r in A.renderers(root):
            name = go.m_Name
            if name.startswith("Cage_"):
                continue
            cut = name.startswith("Mesh_BP_")   # 몸 자르는 고리 — 그리지 않고 자리만 (뷰어가 그 너머 몸을 숨긴다)
            sep = name.startswith("Mesh_SP_")   # 옷 자르는 판 — 그리지 않고 자리만 (뷰어가 그 너머 안쪽 옷을 숨긴다)
            ring = cut or sep
            mesh = mesh_of(go, r)
            if mesh is not None:
                src = _unity_src(r, mesh, by_id, ring)
            elif parts is not None:
                if got is None:
                    got = parts() or {}
                p = got.get(name)
                src = _part_src(p, r, by_id, nodes) if p is not None else None
            else:
                src = None
            if src is None:
                continue
            n = len(src.pos)
            if not n or not (src.uv is not None or ring):
                continue
            uv = src.uv if src.uv is not None else np.zeros((n, 2), np.float32)
            groups = []
            for si, tris in enumerate([] if ring else src.tris):
                if tris is None or not len(tris):
                    continue
                pm = self._pmats.get(name)
                ml = pm or r.m_Materials
                ptr = ml[min(si, len(ml) - 1)] if ml else None
                # 배선이 있는 옷에서 배선 없는 재질은 염색되지 않는다 (채널마다 None)
                slots = None if self._wiring is None else self._wiring.get((name, si), [None, None, None])
                mi = self._material(ptr, mats, slots)
                if mi is None and pm and r.m_Materials and not _readable(ptr):   # prefab 재질을 못 읽으면 fbx 배정으로
                    mi = self._material(r.m_Materials[min(si, len(r.m_Materials) - 1)], mats, slots)
                if mi is None:
                    continue
                t = np.asarray(tris, np.uint32).reshape(-1)
                groups.append({"mat": mi, "off": out.put(t), "count": int(t.size)})
            if not groups and not ring:
                continue
            m = {"name": name, "n": n, "pos": out.put(src.pos), "nrm": out.put(src.nrm), "uv": out.put(uv),
                 "groups": groups, "shapes": {k: out.put(v) for k, v in src.shapes.items()}}
            if cut:
                m["cut"] = True
            if sep:
                m["sep"] = True
            if src.uv1 is not None:
                m["uv1"] = out.put(src.uv1)
            if src.skin:
                paths, idx, w, bind = src.skin
                m["rig"] = {"bones": paths, "idx": out.put(idx), "w": out.put(w), "bind": out.put(bind)}
            else:   # 뼈 없는 메시 — 자기 노드에 붙는다
                tp = transform_ptr(go)
                m["node"] = by_id.get(tp.m_PathID) if tp is not None else None
            m.update(_flags(name))
            meshes.append(m)
        return meshes

    def _material(self, ptr, mats: list, slots: list | None = None) -> int | None:
        """머티리얼 → mats 번호. 그림자용(Hair_Shadow…)·못 읽는 것은 None.
        slots: 염색 채널 0~2 가 받는 의상 색 칸 — 같은 재질도 칸이 다르면 따로 싣는다."""
        if ptr is None or not ptr.m_PathID:
            return None
        try:
            m = ptr.deref().read()
        except Exception as e:
            T.problem("재질을 읽지 못했습니다", e)
            return None
        key = (m.m_Name, tuple(slots) if slots is not None else None)
        if key in self._mats:
            return self._mats[key]
        if "Shadow" in m.m_Name:
            return None
        sp = m.m_SavedProperties
        tex = {k: v.m_Texture for k, v in sp.m_TexEnvs}
        cols = dict(sp.m_Colors)
        floats = dict(sp.m_Floats) if getattr(sp, "m_Floats", None) else {}
        envs = dict(sp.m_TexEnvs)
        tname = self.textures.ref(tex.get("_BaseMap")) or self.textures.ref(tex.get("_EyeballTexture"))
        emotion = self.textures.ref(tex.get("_EmotionMouthMap"))
        # 염색인지는 칸 색(_DyeColor1)과 염색 키워드로 본다 — 코(Female_Nose)는 이름에 DyeMap 이 없어도 염색이고,
        # 흰자(Eye_Base)는 DyeMap 을 쓰지만 칸 색이 없어 그림 그대로다. 염색 불가 의상(콜라보·부엉곰 깃장식 등)은
        # 칸 색은 흰색으로 있지만 키워드가 없고, 텍스처가 DyeMap 이 아니라 색 그림이라 그대로 그린다
        kws = _keywords(m)
        dyed = "_DyeColor1" in cols and (kws is None or bool(kws & _DYE_KEYWORDS))
        kind = ("dye" if dyed else "tex") if tname else "color"
        see = _see_through(A.shader_name(m)) if kind == "color" else None
        # 문신 자리 값(_TattooMapScalePosition)은 피부 재질에만 있다 — 옷의 피부 조각 bodymap_*·뉴비 옷 _Skin 처럼 이름으로 못 가리는 것
        skin = bool(re.search(r"(^|_)(Body|Head|HeadA)(_|$)", m.m_Name)) or bool(tname and tname.startswith(("Body_", "Face_"))) \
            or ("_TattooMapScalePosition" in cols and not m.m_Name.startswith("Eye_"))
        d = {"name": m.m_Name, "kind": kind, "tex": tname, "skin": skin,
             "dye": [hex_color(cols[k]) if k in cols else "#FFFFFF" for k in ("_DyeColor1", "_DyeColor2", "_DyeColor3")],
             "color": hex_color(cols["_BaseColor"]) if "_BaseColor" in cols else "#FFFFFF"}
        if emotion:
            d["emotion"] = emotion
        if slots is not None and kind == "dye":
            d["slots"] = list(slots)
        vec = {k: [c.r, c.g, c.b, c.a] for k, c in cols.items() if _VEC.search(k)}
        if vec:
            d["vec"] = vec
        fl = {k: float(floats[k]) for k in _FLOAT if k in floats}
        if see is not None:
            fl.update(_RenderMode=1.0, _AlphaScaleMin=0.0, _AlphaScaleMax=see, _AlphaOverride=1.0,
                      _EffectAlphaValue=1.0, _ZWrite=0.0)
            if "_ScatterColor1" in cols:   # 물은 바탕색이 흰색이고 물빛은 산란 색에 있다
                d["color"] = hex_color(cols["_ScatterColor1"])
        if fl:
            d["float"] = fl
        kw = [k for k in (getattr(m, "m_ValidKeywords", None) or []) if k in _KEYWORDS]   # 뷰어 키워드는 유효한 것만
        if kw:
            d["kw"] = kw
        emit = self._emission(envs, cols, floats)
        if emit:
            d["emit"] = emit
        if "_Denier" in floats:
            d["stocking"] = self._stocking(envs, floats)
        if floats.get("_IsGem", 0) > 0.5:
            d["gem"] = self._gem(envs, floats)
        fc = cols.get("_FresnelColor")
        if fc is not None and fc.r + fc.g + fc.b > 1e-3 and floats.get("_FresnelPower", 0) > 0:
            # 가장자리 빛 — 비스듬히 보이는 곳에 이 색을 더한다 ([색 sRGB, 지수 _FresnelRange, 세기, 상한])
            d["fresnel"] = [fc.r, fc.g, fc.b, float(floats.get("_FresnelRange", 2)), float(floats["_FresnelPower"]),
                            float(floats.get("_FresnelMaxIntensity", 1))]
        mats.append(d)
        self._mats[key] = len(mats) - 1
        return len(mats) - 1

    def _emission(self, envs: dict, cols: dict, floats: dict) -> dict | None:
        """발광 — 그림의 R 은 _EmissionColor, G·B 는 _EmissionColorG·B 색으로 빛난다 (게임 캐릭터 셰이더).
        숨 쉬듯 밝기가 오가는 옷(_IsBreathingEmissionMode)은 흐르는 잡음 그림을 같이 싣는다.
        게임 캐릭터 셰이더가 아닌 재질(기본 Lit 등)·색이 다 검은 재질·그림이 없는 재질은 None."""
        if "_IsBreathingEmissionMode" not in floats and "_IsDyable" not in floats:
            return None
        colors = [cols.get(k) for k in _EMIT_COLORS]
        if not any(c is not None and c.r + c.g + c.b > 1e-3 for c in colors):
            return None
        env = envs.get("_EmissionMap")
        name = self.textures.ref(env.m_Texture) if env is not None else None
        if not name:
            return None
        out = {"tex": name, "srgb": T.TextureStore.srgb(env.m_Texture),
               "colors": [[c.r, c.g, c.b] if c is not None else [0, 0, 0] for c in colors],
               # (세기, 숨쉬기 최소 밝기, 숨쉬기 주기 초, 잡음 흐름 속도)
               "wave": [float(floats.get(k, d)) for k, d in (("_EmissionIntensity", 1), ("_BreathingEmissionMinBright", 0),
                                                              ("_BreathingEmissionModePeriod", 0), ("_EmissionNoiseSpeed", 0))]}
        if floats.get("_IsEnableEmissionAtNight", 0) > 0.5:
            out["night"] = True   # 밤에만 빛나는 몫(R) — 밝은 무대에선 끈다
        nenv = envs.get("_EmissionNoiseMap") if floats.get("_IsBreathingEmissionMode", 0) > 0.5 else None
        noise = self.textures.ref(nenv.m_Texture) if nenv is not None else None
        if noise:
            out.update(noise=noise, noiseSrgb=T.TextureStore.srgb(nenv.m_Texture),
                       noiseST=[nenv.m_Scale.x, nenv.m_Scale.y, nenv.m_Offset.x, nenv.m_Offset.y])
        return out

    def _stocking(self, envs: dict, floats: dict) -> dict:
        """스타킹 재질(_Denier) — 비치는 정도·점 반짝임, 무늬 마스크(_DyeMaskMap: R 칸 1 색 · G 칸 2 색 자리)를 쓰면 그 그림.
        채널 0 은 피부색이다 (뷰어가 몸 피부색을 넣는다)."""
        out = {"denier": float(floats["_Denier"]), "point": float(floats.get("_PointColorSpecular", 0)),
               "useMask": floats.get("_UseDyeMaskMap", 0) > 0.5}
        env = envs.get("_DyeMaskMap")
        mask = self.textures.ref(env.m_Texture) if env is not None and out["useMask"] else None
        if mask:
            out.update(mask=mask, maskSrgb=T.TextureStore.srgb(env.m_Texture))
        else:   # 마스크 그림이 없으면 칸 2 도 없다 (뷰어의 색 칸·셰이더가 같은 값을 본다)
            out["useMask"] = False
        return out

    def _gem(self, envs: dict, floats: dict) -> dict:
        """보석 재질(_IsGem, 패션 무기의 수정) — 면 반사 그림(_GemMatCapMap, 보는 방향의 법선으로 짚는다)·내포물 그림
        (_GemInclusionMap, uv 반복)과 세기 값. 못 읽은 그림은 빼고, 뷰어가 그 몫을 끈다."""
        f = lambda k, v: round(float(floats.get(k, v)), 4)
        out = {"base": [f("_GemBaseColorStrength", 1), f("_GemBaseStrength", 0.5)],
               "reflect": [f("_GemBrightColorReflection", 0.4), f("_GemDarkColorReflection", 0.2), f("_GemReflectionGloss", 0.4)],
               "matcap": [f("_GemMatCapBlend", 0.3), f("_GemMatCapIntensity", 1), f("_GemMatCapScale", 1)],
               "tiling": [f("_GemInclusionMapTilingX", 1), f("_GemInclusionMapTilingY", 1)]}
        for key, prop in (("capTex", "_GemMatCapMap"), ("incTex", "_GemInclusionMap")):
            env = envs.get(prop)
            name = self.textures.ref(env.m_Texture) if env is not None else None
            if name:
                out[key] = name
                out[key + "Srgb"] = T.TextureStore.srgb(env.m_Texture)
        return out

    def decal(self, path: str, out_json: Path) -> dict:
        """데칼 그림(입·문신 tga 자산) → tex/<이름>.png, out_json 에 {"tex": 이름}."""
        texs = A.objects(self.pack.open([path]), path, "Texture2D")
        if not texs:
            raise ExportError(f"그림을 찾지 못했습니다: {path.rsplit('/', 1)[-1]}")
        meta = {"tex": self.textures.save(texs[0])}
        write_json(out_json, meta)
        return meta
