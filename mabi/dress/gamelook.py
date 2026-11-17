"""게임 캐릭터 외형(리모콘 패킷 감시의 요약 — mabi/packet_monitor/look.py) → 드레스룸 코디.

요약의 값은 대부분 게임 시트 id 다. 이어 주는 표:
  체형·나이·키   요약 그대로 (키 -1..1 은 드레스룸 키 조절값과 같은 뜻 — Short..Tall, 나이는 화면이 체형 범위로 자른다)
  셰이프         face.json shapes (CharacterBodyTypes)
  얼굴           face.json 선택지 id 그대로 (얼굴형·눈 그룹·입 그룹·수염·문신 — 0 은 없음), 눈동자·피부색은 색 표에서
  머리           face.json hairs (그룹 → 체형별 모델). 색은 그 모델의 염색 채널 칸 이름(Hair·Hair1·HairAccessory)대로
  의상           names.json ids 를 거꾸로 (Costume 행 id → 체형별 모델). 색 칸 1~6 = 게임 색 0~5, 안 바꾼 칸은 시트 기본색
결과는 화면의 코디 꼴 {name, body, shape, age, height, skin, face, worn} 과 드레스룸에 없어 못 입힌 것 이름들.
장비(갑옷) 외형은 아직 읽지 않는다 — 의상을 안 입은 부위는 비어 있다.
"""
from __future__ import annotations

from . import catalog as C
from .names import SLOT_KOR

NAME = "게임 캐릭터"
_FACE = (("heads", "head"), ("eyes", "eyes"), ("mouths", "mouth"), ("beards", "beard"), ("ftats", "ftat"),
         ("btats", "btat"))
_HAIR_CH = ("Hair", None, None)   # 부품 값이 없는 머리 — 채널 0 만 머리색
COLOR_SLOTS = 6                   # 의상 색 칸 수


class LookError(ValueError):
    """요약 꼴이 이상하다."""


def _color(face: dict, kind: str, sid) -> dict | None:
    return next((c for c in (face.get("colors") or {}).get(kind, ()) if c.get("id") == sid), None)


def _hair_colors(face: dict, model: str, sheet: dict) -> list | None:
    hc = _color(face, "hair", sheet.get("hair_color"))
    if hc is None:
        return None
    acc = _color(face, "hairacc", sheet.get("hairacc_color"))
    by_slot = {"Hair": hc["c"], "Hair1": hc.get("c2") or hc["c"], "HairAccessory": acc["c"] if acc else None}
    ch = ((face.get("parts") or {}).get(model) or {}).get("ch") or _HAIR_CH
    return [by_slot.get(s) if s else None for s in ch]


def _costume_colors(game: list, defaults: list | None) -> list | None:
    """게임 색 0~5 (안 바꾼 칸은 None) → 칸 1~6. 시트 기본색으로 채우고, 그래도 없으면 None (화면이 모델 기본색).
    뒤쪽 빈 칸은 뺀다 — 모델이 가진 칸 수는 화면이 안다."""
    out = []
    for i in range(COLOR_SLOTS):
        c = game[i] if i < len(game) else None
        if not c and defaults and i < len(defaults):
            c = defaults[i]
        out.append(c or None)
    while out and out[-1] is None:
        out.pop()
    return out or None


def _label(c: dict, models: list, names: dict) -> str:
    for m in models:
        n = names.get(m) or {}
        if n.get("name"):
            return n["name"]
    return SLOT_KOR.get(c.get("type"), c.get("type") or "의상")


def convert(snap: dict, face: dict | None, names: dict, items: dict, by_sheet: dict) -> tuple[dict, list[str]]:
    """요약 → (코디, 못 입힌 것 이름들). items: 모델 id → catalog.Item, by_sheet: names.by_sheet 결과."""
    if not isinstance(snap, dict) or snap.get("body") not in C.BODIES:
        raise LookError("게임 캐릭터 체형을 모릅니다")
    face = face or {}
    body = snap["body"]
    sheet = snap.get("sheet") if isinstance(snap.get("sheet"), dict) else {}
    skin = _color(face, "skin", sheet.get("skin"))
    eye = _color(face, "eye", sheet.get("eye_color"))
    worn: dict[str, dict] = {}
    miss: list[str] = []

    hair = ((face.get("hairs") or {}).get(str(sheet.get("hair"))) or {}).get(body)
    if hair in items:
        worn["Hair"] = {"id": hair, "colors": _hair_colors(face, hair, sheet)}
    elif sheet.get("hair"):
        miss.append("머리")

    for c in snap.get("costumes") or []:
        if not isinstance(c, dict) or c.get("show") is False:   # 숨긴 의상
            continue
        models = (by_sheet.get(c.get("sheet")) or {}).get(body) or []
        got = [m for m in models if m in items]
        if not got:
            miss.append(_label(c, models, names))
            continue
        for m in got:
            worn[items[m].part] = {"id": m, "colors": _costume_colors(c.get("colors") or [], (names.get(m) or {}).get("colors"))}
    if "OnePiece" in worn:   # 한 벌이 상·하의를 가린다
        worn.pop("Top", None)
        worn.pop("Bottom", None)

    h = snap.get("height")
    age = snap.get("age")
    look = {
        "name": NAME, "body": body,
        "shape": (face.get("shapes") or {}).get(str(sheet.get("shape")), ""),
        "age": age if isinstance(age, int) and not isinstance(age, bool) else None,
        "height": max(-1.0, min(1.0, float(h))) if isinstance(h, (int, float)) and not isinstance(h, bool) else 0.0,
        "skin": skin["c"] if skin else None,
        "face": {**{k: sheet.get(src) or None for k, src in _FACE}, "eye": eye["c"] if eye else None, "tat": None},
        "worn": worn,
    }
    return look, miss
