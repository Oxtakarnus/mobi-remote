"""옷·머리 흔들림 — 게임 prefab 의 Magica Cloth(1판) BoneCloth 설정과 미리 계산된 구속 자료를 모델 json 의 cloth 로 꺼낸다.

게임 의상·머리 prefab 에는 MagicaBoneCloth(흔드는 뼈 줄기·설정 clothParams·미리 계산한 구속 ClothData)와
몸 뼈 밑에 붙은 부딪힘 캡슐·공(MagicaCapsuleCollider·MagicaSphereCollider)이 있다. 값은 게임 것을 그대로 담고
움직임 계산은 web/dressroom/cloth.js 가 한다. 2026-11-17 아이템 표본 72개 중 13개에 있었고 전부 BoneCloth
알고리즘 2(algorithm 1), 부딪힘은 캡슐·공만이었다 — 다른 종류(MeshCloth·평면)는 아직 안 담는다.

json cloth = [팀, …] — 팀:
  name      BoneCloth 가 붙은 GameObject 이름
  verts     흔드는 뼈 경로 (모델 skeleton 경로 꼴 — _COM/_Pelvis/…). 정점 번호 = 이 순서
  sel       정점마다 0 안 씀 · 1 움직임 · 2 고정 (게임 SelectionData)
  depth     정점마다 뿌리에서의 깊이 0..1 (설정 곡선을 이 값으로 읽는다)
  parent    정점마다 부모 정점 번호 (-1 = 뿌리)
  params    clothParams 전부 — 곡선 값은 [시작, 끝, 끝 씀, 곡선, 곡선 씀], 벡터는 [x, y, z], 가리킴 값은 뺀다
  struct    거리 유지 [i, j, 길이] 를 이어 붙인 평평한 목록 (정점 i 쪽에서 본 것, 짝마다 양쪽에 있다)
  root      뿌리 거리 [i, 뿌리, 길이] …
  comp      회전 유지·제한 [i, 부모, 쉼 방향 xyz(부모 회전 기준), 쉼 회전 xyzw] … (알고리즘 2 의 CompositeRotation)
  bend      삼각형 굽힘 [날개0, 날개1, 모서리0, 모서리1, 쉼 각, 방향] …
  pen       파고들기 막기 [i, 콜라이더 번호, 위치 xyz, 방향 xyz, 거리] … (콜라이더 기준)
  colliders [{bone: 붙은 뼈 경로, t, r, s: 그 뼈 기준 자세, kind: capsule|sphere, center, axis: 0 x·1 y·2 z,
              length, r0, r1}] — 캡슐은 center ± axis × length, r0 이 − 쪽 반지름
"""
from __future__ import annotations

import logging

from . import assets as A

log = logging.getLogger("mabi")

CLOTH = "MagicaBoneCloth"
COLLIDERS = {"MagicaCapsuleCollider": "capsule", "MagicaSphereCollider": "sphere"}


class ClothError(Exception):
    pass


def _v3(v) -> list[float]:
    return [float(v["x"]), float(v["y"]), float(v["z"])]


def _q(v) -> list[float]:
    v = v.get("value", v)
    return [float(v["x"]), float(v["y"]), float(v["z"]), float(v["w"])]


def params(raw: dict) -> dict:
    """clothParams typetree → 담을 꼴 (곡선은 [시작, 끝, 끝 씀, 곡선, 곡선 씀], 가리킴 값은 뺀다)."""
    out: dict = {}
    for k, v in raw.items():
        if isinstance(v, dict):
            if "startValue" in v:
                out[k] = [float(v["startValue"]), float(v["endValue"]), int(v["useEndValue"]),
                          float(v["curveValue"]), int(v["useCurveValue"])]
            elif set(v) >= {"x", "y", "z"} and len(v) == 3:
                out[k] = _v3(v)
            # 가리킴(m_FileID·m_PathID)·그 밖의 묶음은 쓰지 않는다
        elif isinstance(v, (int, float)):
            out[k] = v
    return out


def _flat(rows, keys) -> list:
    out: list = []
    for r in rows:
        for k in keys:
            v = r[k]
            if isinstance(v, dict):
                out.extend(_q(v) if ("w" in v or "value" in v) else _v3(v))
            else:
                out.append(v)
    return out


def team(name: str, bone: dict, data: dict, paths: list[str], colliders: list[dict]) -> dict:
    """BoneCloth typetree 하나 → json 팀. bone: MagicaBoneCloth, data: 그 ClothData, paths: useTransformList 의 경로
    (못 찾은 칸은 None), colliders: teamData.colliderList 순서의 콜라이더 (못 읽은 것은 None)."""
    n = len(data.get("useVertexList") or ())
    if not n or len(paths) < n or any(p is None for p in paths[:n]):
        raise ClothError(f"{name}: 흔드는 뼈를 다 찾지 못했습니다")
    sel = list(data.get("selectionData") or ())
    depth = [float(x) for x in data.get("vertexDepthList") or [0.0] * n]
    parent = list(data.get("parentList") or [-1] * n)
    if len(sel) != n or len(depth) != n or len(parent) != n:
        raise ClothError(f"{name}: 정점 자료(선택·깊이·부모) 길이가 맞지 않습니다")
    # 파고들기 막기는 콜라이더 번호를 쓴다 — 못 읽은 콜라이더를 가리키는 줄은 뺀다
    pen = [r for r in data.get("penetrationDataList") or () if 0 <= r["colliderIndex"] < len(colliders)
           and colliders[r["colliderIndex"]] is not None]
    return {
        "name": name,
        "verts": paths[:n],
        "sel": sel,
        "depth": depth,
        "parent": parent,
        "params": params(bone.get("clothParams") or {}),
        "struct": _flat(data.get("structDistanceDataList") or (), ("vertexIndex", "targetVertexIndex", "length")),
        "root": _flat(data.get("rootDistanceDataList") or (), ("vertexIndex", "targetVertexIndex", "length")),
        "comp": _flat(data.get("compositeRotationDataList") or (), ("vertexIndex", "parentVertexIndex", "localPos", "localRot")),
        "bend": _flat(data.get("triangleBendDataList") or (), ("vindex0", "vindex1", "vindex2", "vindex3", "restAngle", "direction")),
        "pen": _flat(pen, ("vertexIndex", "colliderIndex", "localPos", "localDir", "distance")),
        "colliders": colliders,
    }


def collider(kind: str, tt: dict, bone: str, trs: dict) -> dict:
    """콜라이더 typetree → {bone, t, r, s, kind, center, axis, length, r0, r1}."""
    c = {"bone": bone, **trs, "kind": kind, "center": _v3(tt["center"])}
    if kind == "capsule":
        c.update(axis=int(tt.get("axis", 0)), length=float(tt.get("length", 0)),
                 r0=float(tt.get("startRadius", 0)), r1=float(tt.get("endRadius", 0)))
    else:
        r = float(tt.get("radius", 0))
        c.update(axis=0, length=0.0, r0=r, r1=r)
    return c


# ── UnityPy 쪽 (prefab 루트에서 읽기) ──

def _local(ptr, file) -> object | None:
    """같은 파일 안 가리킴 {m_FileID, m_PathID} → ObjectReader (다른 파일·빈 값이면 None)."""
    if ptr.get("m_FileID") or not ptr.get("m_PathID"):
        return None
    return file.objects.get(ptr["m_PathID"])


def read(root, by_id: dict[int, str]) -> list[dict]:
    """prefab 루트 GameObject(읽은 값) → cloth 팀 목록. by_id: Transform 경로 id → 경로 (export.skeleton 의 것).
    팀 하나를 못 읽으면 그 팀만 빼고 로그를 남긴다 (옷은 흔들림 없이 그린다). 자료가 빠진 팀(ClothError)은 정보,
    값 모양이 다른 것(키·형 오류 — 게임 패치로 Magica 구조가 바뀐 듯)은 경고."""
    found: list = []                 # (GameObject 이름, BoneCloth ObjectReader)
    go_path: dict[int, str] = {}     # GameObject 경로 id → 그 Transform 경로
    trs: dict[int, dict] = {}        # GameObject 경로 id → 부모 기준 자세

    def visit(go, gid):
        for o in A.components(go):
            tn = o.type.name
            if tn == "Transform":
                t = o.read()
                if gid is not None:
                    q, v, s = t.m_LocalRotation, t.m_LocalPosition, t.m_LocalScale
                    trs[gid] = {"t": [v.x, v.y, v.z], "r": [q.x, q.y, q.z, q.w], "s": [s.x, s.y, s.z]}
                for ch in t.m_Children:
                    try:
                        gp = ch.deref().read().m_GameObject
                        g = gp.deref().read()
                    except Exception:
                        continue
                    go_path[gp.m_PathID] = by_id.get(ch.m_PathID)
                    visit(g, gp.m_PathID)
            elif tn == "MonoBehaviour" and A.script_name(o) == CLOTH:
                found.append((go.m_Name, o))

    visit(root, None)
    teams: list[dict] = []
    for name, o in found:
        try:
            teams.append(_team(name.strip(), o, by_id, go_path, trs))
        except ClothError as e:
            log.info(f"드레스룸: 흔들림 {name.strip()} 은 뺍니다 ({e})")
        except (KeyError, AttributeError, TypeError, ValueError) as e:
            log.warning(f"드레스룸: 흔들림 {name.strip()} 을 읽지 못해 뺍니다 — 구조가 바뀐 듯 ({type(e).__name__}: {e})")
    return teams


def _team(name, o, by_id, go_path, trs) -> dict:
    tt = o.read_typetree()
    data = _local(tt.get("clothData") or {}, o.assets_file)
    if data is None:
        raise ClothError("구속 자료가 없습니다")
    paths = [by_id.get(p["m_PathID"]) for p in tt.get("useTransformList") or ()]
    cols: list = []
    for ptr in tt["teamData"]["colliderList"]:
        c = _local(ptr, o.assets_file)
        kind = COLLIDERS.get(A.script_name(c)) if c is not None else None
        if kind is None:
            cols.append(None)
            continue
        ctt = c.read_typetree()
        gid = ctt["m_GameObject"]["m_PathID"]
        path = go_path.get(gid)
        if path is None:
            cols.append(None)
            continue
        same = {"t": [0.0, 0.0, 0.0], "r": [0.0, 0.0, 0.0, 1.0], "s": [1.0, 1.0, 1.0]}
        cols.append(collider(kind, ctt, path.rpartition("/")[0], trs.get(gid) or same))
    return team(name, tt, data.read_typetree(), paths, cols)
