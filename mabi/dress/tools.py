"""패션 무기 — 의상 시트 한 행(무기 하나)이 쓰는 도구 모델들과, 각 도구가 몸 어디에 어떻게 붙는지 (읽기만).

  묶음    Costume 행의 모델 목록 (검+방패, 활+화살통+화살, 부채 둘 …). 모델 정의의 AppearanceSlot 이
          MainTool 인 것을 대표(목록 id)로, 나머지는 같이 그린다. 화살(Tool_Arrow_00)처럼 여러 무기가 같이 쓰는 도구도 있다.
  붙는 곳 모델 정의(StageObjectModel) ModelPartInfo.AttachPointInfo — 상태(Undrawn 넣음·Drawn 꺼냄)마다
          AttachTo(몸 뼈 이름, '#MODEL_ROOT' 는 뼈대 루트) · ModelPartVisibleState(AlwaysInvisible 이면 안 보임) ·
          Transforms[(IsInfant, Gender — 아이는 'None' 이 기본) → Position·Rotation(오일러 도, Unity ZXY)·LocalScale].
          게임은 prefab 루트를 그 뼈 밑에 이 값으로 둔다 (prefab 루트 자기 TRS 는 쓰지 않는다).
  상태    서 있을 때는 넣은 상태(Undrawn). 대표 도구가 넣으면 안 보이는 무기(부채·너클 등)는 꺼낸 상태(Drawn)로 그린다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .names import SLOT_KOR

STATES = ("Undrawn", "Drawn")
ROOT = "#MODEL_ROOT"   # 붙는 곳·이펙트 소켓의 '뼈대 루트(발밑)' 이름 (fx 도 쓴다)
_RANK = {"MainTool": 0, "SubTool": 1, "SubSubTool": 2}


def quat(euler) -> list[float]:
    """Unity 오일러(도, x·y·z) → 사원수 [x, y, z, w]. Unity 는 z → x → y 순으로 돌린다 (q = qy·qx·qz)."""
    x, y, z = (math.radians(float(v)) / 2 for v in (list(euler) + [0, 0, 0])[:3])
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    return [cy * sx * cz + sy * cx * sz,
            sy * cx * cz - cy * sx * sz,
            cy * cx * sz - sy * sx * cz,
            cy * cx * cz + sy * sx * sz]


def _vec(v, n: int, fill: float) -> list[float]:
    try:
        out = [float(x) for x in v][:n]
    except (TypeError, ValueError):
        out = []
    return out + [fill] * (n - len(out))


def info(som: dict | None) -> dict:
    """모델 정의 → {states: {상태: {to, visible, tf: [{infant, gender, t, r, s}]}}} (부위는 cover.slot)."""
    mi = (som or {}).get("ModelPartInfo") or {}
    states = {}
    for a in mi.get("AttachPointInfo") or ():
        st = a.get("State")
        if st not in STATES or st in states:
            continue
        tf = [{"infant": bool(t.get("IsInfant")), "gender": str(t.get("Gender") or "None"),
               "t": _vec(t.get("Position"), 3, 0.0), "r": quat(_vec(t.get("Rotation"), 3, 0.0)),
               "s": _vec(t.get("LocalScale"), 3, 1.0)}
              for t in a.get("Transforms") or () if isinstance(t, dict)]
        to = str(a.get("AttachTo") or "")
        states[st] = {"to": "" if to == ROOT else to, "visible": a.get("ModelPartVisibleState") != "AlwaysInvisible",
                      "tf": tf}
    return {"states": states}


def pick_tf(tf: list[dict], infant: bool = False, gender: str = "Female") -> dict | None:
    """체형에 맞는 자세 — (아이?, 성별) 그대로 → 같은 나이의 'None' → 같은 나이 아무거나 → 첫 것."""
    for want in ((infant, gender), (infant, "None")):
        for t in tf:
            if (t["infant"], t["gender"]) == want:
                return t
    return next((t for t in tf if t["infant"] == infant), tf[0] if tf else None)


def state_of(main: dict) -> str:
    """서 있을 때 그릴 상태 — 대표 도구가 넣은 상태에서 보이면 Undrawn, 아니면 Drawn (둘 다 없으면 Undrawn)."""
    st = main.get("states") or {}
    if "Undrawn" in st and st["Undrawn"]["visible"]:
        return "Undrawn"
    if "Drawn" in st:
        return "Drawn"
    return "Undrawn"


@dataclass(frozen=True)
class Group:
    main: str                 # 대표 모델 (목록 id)
    others: tuple[str, ...]   # 같이 그리는 모델


def groups(names: dict, slot_of) -> list[Group]:
    """이름 표 → 패션 무기 묶음들. 같은 모델 묶음을 쓰는 행은 하나로. slot_of(모델) → AppearanceSlot ('' 이면 모름).
    대표는 MainTool → SubTool → SubSubTool 순, 같으면 다른 묶음과 같이 쓰지 않는 것, 이름순. 대표가 겹치면 뒤 묶음은 버린다."""
    rows: dict[int, set[str]] = {}
    for model, n in names.items():
        if not isinstance(n, dict) or n.get("slot") != SLOT_KOR["Weapon"]:
            continue
        for sids in (n.get("ids") or {}).values():
            for sid in sids:
                rows.setdefault(int(sid), set()).add(model)
    uniq = sorted({tuple(sorted(ms)) for ms in rows.values()})
    used: dict[str, int] = {}
    for ms in uniq:
        for m in ms:
            used[m] = used.get(m, 0) + 1
    out, seen = [], set()
    for ms in uniq:
        main = min(ms, key=lambda m: (_RANK.get(slot_of(m) or "", 9), used[m] > 1, m))
        if main in seen:
            continue
        seen.add(main)
        out.append(Group(main, tuple(m for m in ms if m != main)))
    return out


def socket_chain(skeleton: list[dict], bone: str) -> tuple[str, list[dict]] | None:
    """몸 뼈대 노드들에서 이름이 bone 인 뼈 → (경로, 루트부터 그 뼈까지의 노드들). '' 이면 ('', []). 없으면 None."""
    if not bone:
        return "", []
    by = {n["path"]: n for n in skeleton}
    hit = next((p for p in by if p.rsplit("/", 1)[-1] == bone), None)
    if hit is None:
        return None
    chain, parts = [], hit.split("/")
    for i in range(1, len(parts) + 1):
        n = by.get("/".join(parts[:i]))
        if n is None:
            return None
        chain.append({"path": n["path"], "t": n["t"], "r": n["r"], "s": n["s"]})
    return hit, chain
