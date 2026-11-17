"""드레스룸 얼굴 꾸미기 — 게임 캐릭터 만들기의 선택지(시트)와 부품 모델 값(StageObjectModel)을 모은다 (읽기만).

시트 (Starter Sheetdata_Client, 필드 순서는 게임 행 클래스 MM.Client.PluginLeaf.SheetDatas.Generated.*SheetData):
  CharacterHead        얼굴형. preload (FI Id, 모델 넷) · 행 (이름, 최소 나이, 환생 해금, 소모품 해금, 숨김, 아이콘)
  CharacterEyes        눈. preload (FI 그룹, FI 얼굴형, 모델 넷) · 행 (이름, 최소 나이, 해금 둘, 숨김, 아이콘 둘(남·여),
                       색 바꿈, FI 제한, 숨길 기간 둘). 모델은 얼굴형과 상관없이 같다 → 그룹마다 하나로 줄인다
  CharacterMouth       입. 눈과 같은 열쇠 · 행 (이름, 최소 나이, 해금 둘, 숨김, 아이콘 둘, 숨길 기간 둘). 모델이 얼굴형마다 다르다
  CharacterBeard       수염 · CharacterFaceTattoo 얼굴 문신(흉터·홍조·점·주름 포함) · CharacterBodyTattoo 몸 문신
                       preload (FI Id, 모델 넷) · 행 (이름, 최소 나이, 해금 둘, 숨김, 아이콘 둘[, 숨길 기간 둘 — 얼굴 문신])
  Character*Color      색. preload FI Id · 행 (이름[, 설명], 해금 둘, 숨김[, 머리색 종류], Color32 하나·둘)
  CharacterHair        머리 (게임 캐릭터 불러오기용 — 고르기는 옷 목록의 '머리'). preload (FI 그룹, FI 체형, 모델 넷).
                       체형(셰이프)마다 한 줄씩이지만 모델은 같다 → 그룹마다 첫 줄
  CharacterBodyTypes   체형(셰이프). preload (FI Id, 블렌드셰이프 이름 '_'·Thin·Fat·Muscular)
모델 칸 순서는 Male·Female·InfantMale·InfantFemale, 없으면 'Invalid'.

부품 모델 (ResourcesPackage StageObjectModels/ModelParts/<부위>/<모델>.StageObjectModel.sjon.bin, SJON):
  AssetPathToLoad      메시 부품(얼굴형·눈·수염)은 prefab, 데칼(입·문신)은 tga
  TextureInfo          데칼 자리 BaseTexcoord(ScalePosition)·Rotation — 뷰어의 표 좌표 식에 그대로 넣는다
  DyeInfo.Slots        칸 이름 — 문신(FaceTattoo·BodyTattoo)은 회색 그림에 색을 입힌다.
                       부위(AppearanceSlot)가 FaceScar·BodyScar 인 데칼(흉터·홍조·점)은 뷰어가 밝기를 피부에서 받는다.
                       메시 부품은 염색 채널마다 칸 이름(ch — 머리는 Hair·Hair1(투톤)·HairAccessory 가 모델마다 다른 채널)

id 는 게임 패킷의 캐릭터 외형 값과 같은 시트 id 다 (눈·입은 그룹 id).
부품 모델은 Starter 목차와 본 목차 둘 다에서 찾는다 (투톤 긴 머리 등 본 목차에만 있는 머리가 있다).
결과는 데이터 폴더 dressroom\\face.json 에 두고 두 목차 stamp·FORMAT 이 바뀌면 다시 만든다 (gamesheet.cached).
"""
from __future__ import annotations

import logging
from pathlib import Path

from .. import gamefiles as gf
from .. import gamesheet as G
from .. import sjon
from . import cover as CV
from . import names as NM

log = logging.getLogger("mabi")

FORMAT = 3   # 2: 게임 캐릭터 불러오기용 hairs·shapes, 3: 부품 값을 본 목차에서도
PRE = "Assets/PatchableAssets/"
SOM_DIR = "StageObjectModels/ModelParts/"
# 시트 모델 칸 → 드레스룸 체형 id (catalog.BODIES)
COLUMNS = (("Male", "Male"), ("Female", "Female"), ("InfantMale", "Boy"), ("InfantFemale", "Girl"))
DYED = ("FaceTattoo", "BodyTattoo")   # 회색 그림에 색을 입히는 데칼 칸
KINDS = ("heads", "eyes", "mouths", "beards", "ftats", "btats")   # 선택지 종류 (표 열쇠)
FLAT = tuple(k for k in KINDS if k != "mouths")   # m 이 {체형: 모델} 인 종류 (입은 {얼굴형: {체형: 모델}})


# ---------------------------------------------------------------- 시트 행
def _models(pre: G.Reader) -> dict[str, str]:
    """preload 의 모델 칸 넷 → {체형: 모델} (없는 칸은 뺀다)."""
    out = {}
    for _col, body in COLUMNS:
        m = pre.s()
        if m and m != "Invalid":
            out[body] = m
    return out


def _done(r: G.Reader, name: str) -> None:
    if not r.done:
        raise G.SheetError(f"{name} 행 끝이 맞지 않습니다 (게임 패치로 필드가 바뀐 것)")


def _parts(sh: G.Sheets, name: str, keyed=False, icons=2, color_flag=False, hide_time=False) -> list[dict]:
    """모델 칸 넷이 preload 에 있는 꾸미기 부위 시트 → [{id, head?, m, name, age, hide, icon}]."""
    s = sh.sheet(name)
    pre = s.preload()
    out = []
    for i in range(s.count):
        d = {"id": pre.fi()}
        if keyed:
            d["head"] = pre.fi()
        d["m"] = _models(pre)
        r = s.reader(i)
        d["name"] = NM.clean(r.s())
        d["age"] = r.vi()
        r.vu(), r.vu()                        # 환생·소모품 해금
        d["hide"] = bool(r.vu())
        d["icon"] = [r.s() for _ in range(icons)]
        if color_flag:
            d["color"] = bool(r.vu())         # 눈동자 색을 바꿀 수 있나
            r.fi()                            # 꾸미기 제한
        if hide_time:
            r.s(), r.s()                      # 숨길 기간 (시간대, 시각)
        _done(r, name)
        out.append(d)
    if not pre.done:
        raise G.SheetError(f"{name} preload 길이가 맞지 않습니다")
    return out


def _colors(sh: G.Sheets, name: str, n=1, desc=True, hair=False) -> list[dict]:
    s = sh.sheet(name)
    pre = s.preload()
    out = []
    for i in range(s.count):
        d = {"id": pre.fi()}
        r = s.reader(i)
        d["name"] = NM.clean(r.s())
        if desc:
            r.s()
        r.vu(), r.vu()
        hide = r.vu()
        two = r.s() == "TwoColor" if hair else False
        cols = [G.hex_color(r.color()) for _ in range(n)]
        _done(r, name)
        if hide or not cols[0]:
            continue
        d["c"] = cols[0]
        if n > 1 and (two or not hair) and cols[1]:
            d["c2"] = cols[1]                 # 머리 투톤의 둘째 색 · 피부 손바닥 색
        out.append(d)
    if not pre.done:
        raise G.SheetError(f"{name} preload 길이가 맞지 않습니다")
    return out


def _icon(d: dict, body: str) -> str:
    """체형에 맞는 아이콘 (남·여 둘이면 고른다)."""
    p = NM.icon_for(d["icon"], body)
    return p if p.startswith(("Sprites/", "Icons/")) else ""


def _visible(rows: list[dict]) -> list[dict]:
    return [r for r in rows if not r["hide"] and r["m"] and not r["name"].startswith("[")]


def _entry(r: dict) -> dict:
    return {"id": r["id"], "name": r["name"], "age": r["age"], "m": r["m"],
            "icon": {b: _icon(r, b) for b in r["m"]}}


def _hairs(sh: G.Sheets) -> dict[str, dict]:
    """CharacterHair preload → 그룹 id(문자열) → {체형: 모델}. 시트가 없으면 빈 표."""
    if "CharacterHair" not in sh:
        return {}
    s = sh.sheet("CharacterHair")
    pre = s.preload()
    out: dict[str, dict] = {}
    for _ in range(s.count):
        group = pre.fi()
        pre.fi()                              # 체형(셰이프) — 모델은 같다
        out.setdefault(str(group), _models(pre))
    if not pre.done:
        raise G.SheetError("CharacterHair preload 길이가 맞지 않습니다")
    return {g: m for g, m in out.items() if m}


def _shapes(sh: G.Sheets) -> dict[str, str]:
    """CharacterBodyTypes → 체형 id(문자열) → 드레스룸 셰이프 이름 ('' 기본·Thin·Fat·Muscular). 시트가 없으면 빈 표."""
    if "CharacterBodyTypes" not in sh:
        return {}
    s = sh.sheet("CharacterBodyTypes")
    pre = s.preload()
    out = {}
    for _ in range(s.count):
        sid = pre.fi()
        blend = pre.s()
        out[str(sid)] = "" if blend in ("_", "", "None") else blend
    if not pre.done:
        raise G.SheetError("CharacterBodyTypes preload 길이가 맞지 않습니다")
    return out


def collect(sh: G.Sheets) -> dict:
    """시트 → 선택지 (부품 모델 값은 아직 없이). hairs·shapes 는 게임 캐릭터 불러오기에만 쓴다."""
    heads = _visible(_parts(sh, "CharacterHead", icons=1))
    head_ids = {h["id"] for h in heads}
    eyes, seen = [], set()
    for r in _visible(_parts(sh, "CharacterEyes", keyed=True, color_flag=True, hide_time=True)):
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        e = _entry(r)
        e["color"] = r["color"]
        eyes.append(e)
    mouths: dict[int, dict] = {}
    for r in _visible(_parts(sh, "CharacterMouth", keyed=True, hide_time=True)):
        if r["head"] not in head_ids:
            continue
        e = mouths.setdefault(r["id"], {**_entry(r), "m": {}})
        e["m"][str(r["head"])] = r["m"]       # 얼굴형 id → {체형: 모델}
    return {
        "heads": [_entry(h) for h in heads],
        "eyes": eyes,
        "mouths": list(mouths.values()),
        "beards": [_entry(r) for r in _visible(_parts(sh, "CharacterBeard"))],
        "ftats": [_entry(r) for r in _visible(_parts(sh, "CharacterFaceTattoo", hide_time=True))],
        "btats": [_entry(r) for r in _visible(_parts(sh, "CharacterBodyTattoo"))],
        "colors": {
            "skin": _colors(sh, "CharacterSkinColor", n=2),
            "eye": _colors(sh, "CharacterEyeColor"),
            "hair": _colors(sh, "CharacterHairColor", n=2, desc=False, hair=True),
            "hairacc": _colors(sh, "CharacterHairAccessoryColor"),
        },
        "hairs": _hairs(sh),
        "shapes": _shapes(sh),
    }


def model_names(t: dict) -> set[str]:
    out = set()
    for k in FLAT:
        for e in t[k]:
            out.update(e["m"].values())
    for e in t["mouths"]:
        for by_body in e["m"].values():
            out.update(by_body.values())
    for m in (t.get("hairs") or {}).values():
        out.update(m.values())
    return out


# ---------------------------------------------------------------- 부품 모델
def part(som: dict) -> dict | None:
    """StageObjectModel → 뷰어가 쓰는 부품 값 {a: 자산 경로, slot, st, rot, dye | ch}. 자산 경로가 없으면 None.
    ch: 메시 부품의 염색 채널 0..2 → 칸 이름 (피부 칸은 뺀다 — 뷰어가 피부색으로 따로 칠한다). 염색이 없으면 없음."""
    a = som.get("AssetPathToLoad") or ""
    if not a:
        return None
    d = {"a": PRE + a, "slot": CV.slot(som)}
    ti = som.get("TextureInfo")
    if a.lower().endswith((".tga", ".png")):
        st = (ti or {}).get("BaseTexcoord") or [1, 1, 0, 0]
        d["st"] = [float(x) for x in st[:4]]
        d["rot"] = float((ti or {}).get("Rotation") or 0)
        slots = [s.get("Slot") for s in ((som.get("DyeInfo") or {}).get("Slots") or []) if s.get("Wirings")]
        d["dye"] = any(s in DYED for s in slots)
        return d
    ch = [None, None, None]
    for s in (som.get("DyeInfo") or {}).get("Slots") or []:
        if s.get("Slot") in (None, "Skin"):
            continue
        for w in s.get("Wirings") or []:
            c = w.get("ChannelIndex")
            if isinstance(c, int) and 0 <= c < 3 and ch[c] is None:
                ch[c] = s["Slot"]
    if any(ch):
        d["ch"] = ch
    return d


def attach_parts(t: dict, res) -> dict:
    """선택지 표에 부품 값(parts)을 붙이고, 부품을 못 찾은 모델은 선택지에서 뺀다. res: gamefiles.Resources 꼴."""
    paths = {}
    for p in res.paths:
        if p.startswith(SOM_DIR) and p.endswith(".StageObjectModel.sjon.bin"):
            paths.setdefault(p.rsplit("/", 1)[-1][: -len(".StageObjectModel.sjon.bin")], p)
    parts = {}
    for m in sorted(model_names(t)):
        p = paths.get(m)
        if not p:
            continue
        try:
            d = part(sjon.load(res.read(p)))
        except (sjon.SjonError, OSError, KeyError, TypeError, ValueError) as e:
            log.warning(f"드레스룸 얼굴: {m} 부품 값을 읽지 못했습니다 ({e})")
            continue
        if d:
            parts[m] = d

    def keep(m: dict) -> dict:
        return {b: x for b, x in m.items() if x in parts}

    for k in FLAT:
        for e in t[k]:
            e["m"] = keep(e["m"])
        t[k] = [e for e in t[k] if e["m"]]
    for e in t["mouths"]:
        e["m"] = {h: keep(by) for h, by in e["m"].items() if keep(by)}
    t["mouths"] = [e for e in t["mouths"] if e["m"]]
    t["parts"] = parts
    return t


def build(sh: G.Sheets, res) -> dict:
    return attach_parts(collect(sh), res)


# ---------------------------------------------------------------- 캐시
def load(cache_dir: Path, game_dir, opener=None, resources=None) -> tuple[dict | None, bool]:
    """얼굴 선택지 표와 '이번에 새로 만들었나'. 못 만들면 (None, False) — 드레스룸은 얼굴 고르기 없이 뜬다.
    opener: 게임 폴더 → Sheets, resources: 게임 폴더 → Resources (시험에서 바꾼다)."""
    def make(sh):
        res = (resources or (lambda gd: gf.Resources(Path(gd), lambda p: p.startswith(SOM_DIR), main=True)))(game_dir)
        return build(sh, res)
    return G.cached(Path(cache_dir) / "face.json", FORMAT, game_dir, make, opener, what="드레스룸 얼굴",
                    stamper=gf.res_stamp)
