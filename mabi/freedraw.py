"""캐시샵 매일 무료 상품 표 — 패킷이 알려 주는 세 칸(시트 행 id)을 이름·희귀도·직업·부위·색으로 바꾸고, 멈출 상품인지 본다.

패킷 shop.free_draw: 상품 갱신 한 번마다 세 칸의 CashShopDailyFreeDraw 행 id (caps/freedraw1, 2026-11-27).
시트 행 (필드 이름은 데이터에 없다 — 2026-11-27 실측으로 맞춤):
  S 보상 종류(Costume·Consumable·Money) · S 보상 이름 · FI 화폐 · VI 값(뜻 미확인) · VU 개수 · S 배너 그림 · S 색('#718C41', 지정 염색약만) …
보상 이름은 다른 시트 행의 심볼 이름이다. 심볼 id = md5(UTF-8 이름) 앞 4바이트를 부호 있는 정수로 읽은 절댓값.
  Costume    → CostumeRewardPreset 행 (FI 의상 id 가 4바이트째부터) → Costume 행 이름
               보상 이름 'FreeDraw_<희귀도>_Fashion_<직업>_<부위>[_00]' — 희귀도·직업·부위가 이름에 들어 있다
  Consumable → Consumable 행 (preload FI id · S 이름 · S 설명, 행 첫 칸 S 희귀도)
  Money      → 화폐 (이름은 시트에서 아직 못 찾음 — MONEY_NAMES)
같은 의상이 희귀도 넷(일반·고급·레어·엘리트)으로 따로 나온다.

결과는 데이터 폴더 freedraw.json 에 두고, 시트가 든 ResourcesPackage 목차 stamp 나 FORMAT 이 바뀌면 다시 만든다.
"""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path

from . import gamesheet as G

FORMAT = 1
SHEET = "CashShopDailyFreeDraw"

RARITY = ("Common", "Uncommon", "Rare", "Elite", "Epic", "Legendary")
RARITY_KO = {"Common": "일반", "Uncommon": "고급", "Rare": "레어", "Elite": "엘리트", "Epic": "에픽", "Legendary": "전설"}
STOP_RARITY = "Elite"   # 목표와 상관없이 이 희귀도 이상이면 멈춘다 (사용자 2026-11-27)
# 목표와 상관없이 뜨면 멈추는 물품 (연금술 촉매·미가공 골드 원석·미가공 데카 원석 — 사용자 2026-11-27)
SPECIAL_PREFIX = ("AlchemyCatalyst_", "RawGoldStone", "RedElixir")
FIXED_DYE = "DyeAmpoule_FixedColor"
MONEY_NAMES = {"Coin_SouthRegionToken": "하트 토큰"}   # 화면 이름 (2026-11-27 캐시샵 화면)
PART_KO = {"head": "머리", "helmet": "투구", "top": "상의", "bottom": "하의", "onepiece": "한벌옷", "hand": "장갑",
           "gloves": "장갑", "shoes": "신발", "shose": "신발", "foot": "신발"}   # 게임 이름의 오타(Shose·Onepiece)도 같이


def symbol_id(name: str) -> int:
    """시트 심볼 이름 → 행 id (preload 의 u32)."""
    v = struct.unpack("<i", hashlib.md5(name.encode("utf-8")).digest()[:4])[0]
    return abs(v)


def rank(rarity: str | None) -> int:
    return RARITY.index(rarity) if rarity in RARITY else -1


def _ids(sheet: G.Sheet) -> dict[int, int]:
    """preload 가 행마다 FI id 하나뿐인 시트 → id → 행 번호."""
    r = sheet.preload()
    return {r.fi(): i for i in range(sheet.count)}


def _consumables(sh: G.Sheets) -> dict[int, tuple[str, str]]:
    """Consumable id → (이름, 희귀도). preload 는 행마다 FI id · S 이름 · S 설명, 행 첫 칸이 희귀도."""
    s = sh.sheet("Consumable")
    pre = s.preload()
    out = {}
    for i in range(s.count):
        cid, name, _ = pre.fi(), pre.s(), pre.s()
        out[cid] = (name, i)
    return {cid: (name, s.reader(i).s()) for cid, (name, i) in out.items()}


def _job_names(sh: G.Sheets) -> dict[str, str]:
    """직업 키(Warrior·HighHealer …) → 한국어 직업 이름. CombatJob 행 2바이트째의 문자열 (2026-11-27 실측:
    '견습 전사'·'기사'·'대검전사'). 못 읽으면 그 직업은 빠진다."""
    from .dress.names import combat_jobs
    if "CombatJob" not in sh:
        return {}
    s = sh.sheet("CombatJob")
    rows = _ids(s)
    out = {}
    for jid, k in combat_jobs(sh).items():
        try:
            out[k] = G.Reader(s.row(rows[jid]), 2, sh.text).s()
        except (G.SheetError, IndexError, KeyError, ValueError):
            pass
    return out


def build(sh: G.Sheets) -> dict:
    """{'items': {행 id(문자열): 상품}, 'jobs': {직업 키: 한국어}}. 상품 = {kind, name, rarity, …}.
    kind: costume · dye(지정 염색약, color) · item(그 밖 소모품) · money. 읽지 못한 행은 kind '?' 로 남긴다."""
    s = sh.sheet(SHEET)
    pre = s.preload()
    row_ids = [pre.fi() for _ in range(s.count)]
    reward = sh.sheet("CostumeRewardPreset")
    rewards = _ids(reward)
    costume = sh.sheet("Costume")
    costumes = _ids(costume)
    cons = _consumables(sh)
    jobs = _job_names(sh)
    items = {}
    for i, rid in enumerate(row_ids):
        r = s.reader(i)
        kind, ref = r.s(), r.s()
        r.fi()
        r.vi()
        amount = r.vu()
        r.s()
        color = r.s()
        it = {"kind": "?", "name": ref, "rarity": None, "amount": amount, "ref": ref}
        if kind == "Costume":
            t = ref.split("_")
            rw = rewards.get(symbol_id(ref))
            cid = struct.unpack_from("<I", reward.row(rw), 3)[0] if rw is not None else None
            if cid in costumes and len(t) >= 5:
                it.update(kind="costume", name=costume.reader(costumes[cid]).s(), rarity=t[1], job=t[3],
                          part=PART_KO.get(t[4].lower(), t[4]))
        elif kind == "Consumable":
            name, rarity = cons.get(symbol_id(ref), (ref, None))
            it.update(kind="dye" if ref == FIXED_DYE else "item", name=name, rarity=rarity)
            if ref == FIXED_DYE:
                it["color"] = color.upper()
        elif kind == "Money":
            it.update(kind="money", name=MONEY_NAMES.get(ref, ref))
        items[str(rid)] = it
    return {"items": items, "jobs": jobs}


def load(cache_dir: Path, game_dir, opener=None) -> dict | None:
    """표 (없거나 못 읽으면 None). cache_dir\\freedraw.json 의 stamp·FORMAT 이 지금과 같으면 그대로 쓴다."""
    v, _ = G.cached(Path(cache_dir) / "freedraw.json", FORMAT, game_dir, build, opener, what="무료 상품 표")
    return v


# ---------------------------------------------------------------- 목표
def label(it: dict | None) -> str:
    """로그·화면용 한 줄 이름."""
    if not it:
        return "모르는 상품"
    if it["kind"] == "costume":
        return f"{it['name']} ({RARITY_KO.get(it['rarity'], it['rarity'])})"
    if it["kind"] == "dye":
        return f"{it['name']} {it['color']}"
    n = it.get("amount") or 1
    return f"{it['name']} ×{n}" if n > 1 else it["name"]


def special(it: dict | None) -> str | None:
    """목표와 상관없이 멈출 상품이면 그 까닭, 아니면 None."""
    if not it:
        return None
    if it.get("ref", "").startswith(SPECIAL_PREFIX):
        return "특수 물품"
    if rank(it.get("rarity")) >= rank(STOP_RARITY):
        return f"{RARITY_KO[STOP_RARITY]} 이상"
    return None


def wanted(it: dict | None, target: dict) -> bool:
    """목표에 맞나. target: {'type': 'costume', 'name', 'min'(희귀도)} · {'type': 'dye', 'color'} · {'type': 'none'}."""
    if not it:
        return False
    kind = target.get("type")
    if kind == "costume":
        return it["kind"] == "costume" and it["name"] == target.get("name") \
            and rank(it["rarity"]) >= rank(target.get("min") or RARITY[0])
    if kind == "dye":
        return it["kind"] == "dye" and it.get("color", "").upper() == str(target.get("color") or "").upper()
    return False


def target(pick: dict | None) -> dict:
    """화면에서 고른 것 {type, name, min, color} → wanted 가 보는 목표. 모르는 종류면 'none' (특수 물품·엘리트 이상만)."""
    pick = pick or {}
    if pick.get("type") == "costume" and pick.get("name"):
        return {"type": "costume", "name": pick["name"], "min": pick.get("min") if pick.get("min") in RARITY else RARITY[0]}
    if pick.get("type") == "dye" and pick.get("color"):
        return {"type": "dye", "color": str(pick["color"]).upper()}
    return {"type": "none"}


def judge(items: list[dict | None], target: dict) -> tuple[int, str] | None:
    """세 칸 중 멈출 칸 (칸 번호, 까닭) — 목표가 먼저. 없으면 None."""
    for n, it in enumerate(items):
        if wanted(it, target):
            return n, "목표"
    for n, it in enumerate(items):
        why = special(it)
        if why:
            return n, why
    return None


def choices(table: dict) -> dict:
    """화면 드롭다운: 의상(직업별, 이름마다 한 줄)·지정 염색약 색·희귀도."""
    jobs = table.get("jobs") or {}
    seen, costumes, colors = set(), [], set()
    for it in table.get("items", {}).values():
        if it["kind"] == "costume" and it["name"] not in seen:
            seen.add(it["name"])
            costumes.append({"name": it["name"], "job": jobs.get(it["job"], it["job"]), "part": it["part"]})
        elif it["kind"] == "dye":
            colors.add(it["color"])
    costumes.sort(key=lambda c: (c["job"], c["name"]))
    rarities = sorted({it["rarity"] for it in table.get("items", {}).values() if it["kind"] == "costume"}, key=rank)
    return {"costumes": costumes, "colors": sorted(colors),
            "rarities": [{"key": r, "name": RARITY_KO.get(r, r)} for r in rarities]}
