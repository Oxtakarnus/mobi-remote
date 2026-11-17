"""드레스룸 이름 표 — 모델 이름(prefab) → 게임 아이템 이름·부위·세트·아이콘·기본 색 (게임 시트에서).

  Costume         의상. 모델 이름 칸 Male/Female/Boy/GirlModelName(목록 — 무기는 검·방패 둘)이 드레스룸 모델 id 와 같다
  CostumeSetInfo  세트 이름 (Costume.CostumeSetInfoId → preload FI Id, 행 첫 문자열)
  CharacterHair   꾸미기 머리. preload 에 행마다 (FI 그룹, FI 체형, 모델 이름 넷 — 없으면 'Invalid')
  Equipment       장비 외형. 앞쪽 필드를 다 풀지 않았다 — 뒤쪽 블록이 행 끝에 한 가지로만 맞는 행만 쓴다
  CombatJob       직업. Costume.EquippableCombatJobs(FI 목록 → preload FI Id)로 패션 무기마다 직업이 하나씩 붙는다
                  — 동작 표의 직업 갈래(CombatJob:<이름>) 이름은 combat_jobs 가 직업 아이콘 이름에서 만든다

아이콘 칸은 남성용(Male·Boy)·여성용(Female·Girl) 둘이다. 한 모델을 여러 행이 쓰면(재판매·장비 단계·커스터마이징 전용 행)
pick() 이 하나를 고르고 나머지 이름은 alt 로 둔다. 그 모델을 쓰는 Costume 행 id 는 체형별로 ids 에 둔다 — 게임 패킷의
입은 의상 값이 이 id 다 (by_sheet 로 거꾸로 찾는다).

결과는 데이터 폴더 dressroom\\names.json 에 두고, 시트가 든 ResourcesPackage 목차 stamp 나 FORMAT 이 바뀌면 다시 만든다
(assets 의 cab.json 과 같은 방식). 시트를 못 읽으면 빈 표 — 목록은 영어 이름으로 그대로 뜬다.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from .. import gamesheet as G

log = logging.getLogger("mabi")

FORMAT = 3   # names.json 형식·고르는 규칙 — 바뀌면 다시 만든다 (2: 의상 시트 id, 3: 패션 무기 직업 job)

# 게임 꾸미기·가방의 부위 이름 (InventorySubCategory 시트 FashionList 행과 같은 말)
SLOT_KOR = {"Hat": "모자", "Top": "상의", "Bottom": "하의", "Gloves": "장갑", "Shoes": "신발", "Robe": "로브",
            "FaceDeco": "얼굴 장식", "EarDeco": "귀 장식", "EyeDeco": "눈 장식", "Weapon": "패션 무기", "Hair": "헤어"}
EQUIP_SLOT = {"Weapon": "무기"}   # 장비 시트는 같은 이름이라도 패션 무기가 아니다
GENDERS = ("Male", "Female", "Boy", "Girl")
MALE_ICON = {"Male": True, "Boy": True, "Female": False, "Girl": False}   # 남·여 아이콘 둘 중 남성 것을 쓰는 체형

# 고르기: 개발용 이름(밑줄 든 내부 이름·테스트·미사용 등)은 버리고, 장비 단계 꼬리(상의S·상의ZZ)는 뗀 이름으로 본다
_JUNK = re.compile(r"커스터마이징 전용|\(임시\)|\(촬영용\)|테스트|미사용|사용하지 않음|심볼용|_|^[\x00-\x7f]*$")
_TIER = re.compile(r"(?<=[가-힣)])(?:S{1,2}|Z{1,2})$")
_RANK = {"Costume": 0, "CharacterHair": 1, "Equipment": 2}


def clean(name: str) -> str:
    """시트 이름 안의 줄 바꿈 없는 공백·전각 공백·탭을 보통 공백 하나로 (얼굴·동작 표도 쓴다)."""
    return " ".join(name.split())


def icon_for(icons, body: str) -> str:
    """시트의 아이콘 칸들 → 그 체형 것 (남·여 둘이면 고르고, 하나면 그것)."""
    return icons[0] if len(icons) == 1 or MALE_ICON[body] else icons[1]


def _warn_bad(sheet: str, count: int, bad: int) -> None:
    if bad:
        log.warning(f"드레스룸 이름: {sheet} 시트 {count}행 중 {bad}행을 읽지 못했습니다 (게임 패치로 형식이 바뀐 듯)")


def _icon_ok(p: str) -> bool:
    return p.startswith(("Icons/", "Sprites/")) and "TempIcon" not in p


# ---------------------------------------------------------------- 시트 행
def costume_row(r: G.Reader) -> dict:
    """Costume 행 하나 (preload 의 Id 는 빼고). 행 끝이 안 맞으면 SheetError — 게임 패치로 필드가 바뀐 것."""
    d = {"name": r.s()}
    r.s()                                    # FlavorText
    d["set"] = r.fi()                        # CostumeSetInfoId
    d["type"] = r.s()                        # CostumeType (Hat·Top·…)
    r.s()                                    # DyePolicy
    d["hiding"] = r.many(r.s)                # HidingParts (상의가 하의를 숨기면 한 벌)
    r.vu(), r.vu(), r.vu(), r.vi()           # IsAbleAlchemy·IsAbleDisassemble·CanTrade·CanTradeCount
    r.s(), r.s()                             # SalesStartTime (시간대, 시각)
    r.vu(), r.fi(), r.vu()                   # IsSellable·(SellingPrice 자리 — 뜻 미확인)
    r.s(), r.s()                             # MarketCollectionDiscloseTime
    r.s()                                    # StorageAvailability
    d["jobs"] = r.many(r.fi)                 # EquippableCombatJobs (CombatJob 행 id)
    d["gender"] = r.s()                      # EquippableGender (None·Male·Female)
    r.s()                                    # EquippableAgeType
    r.many(r.fi)                             # MagicEffectIds
    r.s()                                    # CostumeMagicEffectApplyPolicy
    r.fi(), r.s(), r.fi()                    # GenderChange·TransformGroupId·TransformResult
    d["colors"] = [G.hex_color(r.color()) for _ in range(6)]   # DyeColor0..5
    d["models"] = {g: r.many(r.s) for g in GENDERS}
    d["icons"] = (r.s(), r.s())              # MaleIconPath·FemaleIconPath
    r.many(r.fi)                             # (ExceptionModelName 자리 — 뜻 미확인)
    if not r.done:
        raise G.SheetError("Costume 행 끝이 맞지 않습니다")
    return d


def hair_row(r: G.Reader) -> dict:
    """CharacterHair 행 하나 (preload 칸 빼고) → 이름·아이콘."""
    d = {"name": r.s()}
    r.vi(), r.vu(), r.vu(), r.vu()           # MinAge·UnlockedByRebirth·UnlockedByConsumable·HideOnCustomize
    r.s(), r.s()                             # HairType·CapFrontHairDyeSlot
    d["icons"] = (r.s(), r.s())
    r.vu(), r.fi(), r.color()                # CanChangeColor·CustomizeRestriction·CustomizeFixedDyeColor
    r.s(), r.s()                             # HideForNonOwnerTime
    if not r.done:
        raise G.SheetError("CharacterHair 행 끝이 맞지 않습니다")
    return d


_ID = re.compile(r"\w+")
_PATH = re.compile(r"[\w/.]*")


def equipment_tail(b: bytes, text: bytes) -> dict | None:
    """Equipment 행 뒤쪽 [색 6][모델 목록 4][아이콘 2][공개 시각 2][VU][FI] 을 찾는다.
    행 끝에 꼭 맞고 값 모양이 맞는 시작 자리가 한 가지 결과로만 나올 때만 쓴다 (아니면 None)."""
    found = None
    for p in range(len(b)):
        r = G.Reader(b, p, text)
        try:
            colors = [G.hex_color(r.color()) for _ in range(6)]
            models = {g: r.many(r.s) for g in GENDERS}
            icons = (r.s(), r.s())
            tz = r.s()
            r.s(), r.vu(), r.fi()
        except (IndexError, G.SheetError):
            continue
        if not r.done or tz not in ("UTC", "KST", ""):
            continue
        if not all(_PATH.fullmatch(s) for s in icons) or not all(_ID.fullmatch(m) for v in models.values() for m in v):
            continue
        got = {"colors": colors, "models": models, "icons": icons}
        if found is not None and found != got:
            return None
        found = got
    return found


_JOB_ICON = re.compile(r"/Icon64_Class_(\w+)\.png$")


def job_key(icon: str) -> str:
    """직업 아이콘 이름 → 동작 상태 시트의 직업 이름 — 견습(Novice<X>)은 <X>, 상급(Expert<X>)은 High<X>, 그 밖은 그대로."""
    for pre, to in (("Novice", ""), ("Expert", "High")):
        if icon.startswith(pre) and len(icon) > len(pre):
            return to + icon[len(pre):]
    return icon


def _job_icon(b: bytes, text: bytes) -> str:
    """CombatJob 행 → 직업 아이콘 이름 (Icon64_Class_<이름>.png). 앞쪽 필드 길이가 행마다 달라 문자열 자리를 찾는다."""
    for p in range(len(b)):
        try:
            m = _JOB_ICON.search(G.Reader(b, p, text).s())
        except (IndexError, ValueError, G.SheetError):
            continue
        if m:
            return m.group(1)
    return ""


def combat_jobs(sh: G.Sheets) -> dict[int, str]:
    """CombatJob 시트 → 행 id → 동작 상태 시트(AnimationStateSet)의 직업 이름 (Warrior·HighWarrior·GreatSwordWarrior …).
    행에 그 이름 칸이 없어 직업 아이콘 이름에서 만든다 (job_key). 2026-11-17: 견습 전사 NoviceWarrior → Warrior,
    전사 ExpertWarrior → HighWarrior, 대검전사 GreatSwordWarrior. 아직 나오지 않은 직업 몇은 다른 직업 아이콘을 빌려 쓴다
    (바바리안 → SwordMaster) — 그 직업 무기는 아직 없다. 시트가 없으면 {}."""
    if "CombatJob" not in sh:
        return {}
    s = sh.sheet("CombatJob")
    pre = s.preload()
    out = {}
    for i in range(s.count):
        jid = pre.fi()
        icon = _job_icon(s.row(i), sh.text)
        if icon:
            out[jid] = job_key(icon)
    return out


# ---------------------------------------------------------------- 모으기·고르기
def collect(sh: G.Sheets) -> dict[str, list[dict]]:
    """모델 id → 그 모델을 쓰는 행들 [{src, name, slot, set, icon, colors[, sid, body, job]}] (시트 행 순서).
    Costume 행은 시트 id(sid)와 그 모델을 쓰는 체형(body)도 남기고, 직업이 붙은 행(패션 무기)은 그 직업 이름(job)도."""
    hits: dict[str, list[dict]] = {}

    def add(model, h):
        if model and model != "Invalid":
            hits.setdefault(model, []).append(h)

    sets = {}
    if "CostumeSetInfo" in sh:
        s = sh.sheet("CostumeSetInfo")
        pre = s.preload()
        for i in range(s.count):
            sets[pre.fi()] = s.reader(i).s()

    jobs = combat_jobs(sh)
    s = sh.sheet("Costume")
    pre = s.preload()
    bad = 0
    for i in range(s.count):
        sid = pre.fi()
        try:
            c = costume_row(s.reader(i))
        except (IndexError, G.SheetError):
            bad += 1
            continue
        job = next((jobs[j] for j in c["jobs"] if j in jobs), "")
        for g in GENDERS:
            icon = icon_for(c["icons"], g)
            for m in c["models"][g]:
                h = {"src": "Costume", "name": clean(c["name"]), "slot": SLOT_KOR.get(c["type"], c["type"]),
                     "set": sets.get(c["set"], ""), "icon": icon, "colors": c["colors"], "sid": sid, "body": g}
                if job:
                    h["job"] = job
                add(m, h)
    _warn_bad("Costume", s.count, bad)

    if "CharacterHair" in sh:
        s = sh.sheet("CharacterHair")
        pre = s.preload()
        bad = 0
        for i in range(s.count):
            pre.fi(), pre.fi()
            models = [pre.s() for _ in GENDERS]
            try:
                h = hair_row(s.reader(i))
            except (IndexError, G.SheetError):
                bad += 1
                continue
            for g, m in zip(GENDERS, models):
                add(m, {"src": "CharacterHair", "name": clean(h["name"]), "slot": SLOT_KOR["Hair"], "set": "",
                        "icon": icon_for(h["icons"], g), "colors": [None] * 6})
        _warn_bad("CharacterHair", s.count, bad)

    if "Equipment" in sh:
        s = sh.sheet("Equipment")
        for i in range(s.count):
            r = s.reader(i)
            try:
                name, _, kind = r.s(), r.s(), r.s()
            except (IndexError, G.SheetError):
                continue
            t = equipment_tail(s.row(i), sh.text)
            if t is None:
                continue
            slot = EQUIP_SLOT.get(kind) or SLOT_KOR.get(kind, kind)
            for g in GENDERS:
                for m in t["models"][g]:
                    add(m, {"src": "Equipment", "name": clean(name), "slot": slot, "set": "",
                            "icon": icon_for(t["icons"], g), "colors": t["colors"]})
    return hits


def _bare(name: str) -> str:
    return _TIER.sub("", name)


def pick(hits: list[dict]) -> dict | None:
    """한 모델의 행들 → {name, alt, slot, set, icon, colors, ids[, job]}. 쓸 이름이 없으면 None.
    ids: 체형 → 그 모델을 쓰는 Costume 행 id 들 (이름을 버린 행 것도 — 게임에서 입은 의상을 찾는 데 쓴다).
    job: 패션 무기의 직업 (동작 표 직업 갈래 이름 — 고른 행 순서로 처음 붙은 것, 없으면 칸이 없다).

    개발용 이름(커스터마이징 전용·임시·촬영용·테스트·미사용·심볼용·밑줄 든 이름·영문만)은 버리고, 의상 → 머리 → 장비 순,
    장비 단계 꼬리가 없는 것·'잔영의' 아닌 것·짧은 이름을 앞에 둔다. 아이콘·색은 앞에서부터 쓸 만한 아이콘이 있는 행 것."""
    good = [h for h in hits if not _JUNK.search(h["name"])]
    if not good:
        return None
    good.sort(key=lambda h: (_RANK.get(h["src"], 9), _bare(h["name"]) != h["name"], "잔영의" in h["name"],
                             len(_bare(h["name"]))))
    best = good[0]
    names: list[str] = []
    for h in good:
        n = _bare(h["name"])
        if n not in names:
            names.append(n)
    art = next((h for h in good if _icon_ok(h["icon"])), None)
    ids: dict[str, list[int]] = {}
    for h in hits:
        if "sid" in h and h["sid"] not in ids.setdefault(h["body"], []):
            ids[h["body"]].append(h["sid"])
    out = {"name": names[0], "alt": names[1:], "slot": best["slot"], "set": best["set"],
           "icon": art["icon"] if art else "", "colors": art["colors"] if art else [None] * 6, "ids": ids}
    job = next((h["job"] for h in good + hits if h.get("job")), "")
    if job:
        out["job"] = job
    return out


def by_sheet(names: dict[str, dict]) -> dict[int, dict[str, list[str]]]:
    """이름 표 → Costume 행 id → {체형: [모델]} (무기는 모델이 여럿)."""
    out: dict[int, dict[str, list[str]]] = {}
    for model, n in names.items():
        for body, sids in (n.get("ids") or {}).items():
            for sid in sids:
                out.setdefault(int(sid), {}).setdefault(body, []).append(model)
    return out


def build(sh: G.Sheets) -> dict[str, dict]:
    out = {}
    for model, hs in collect(sh).items():
        p = pick(hs)
        if p:
            out[model] = p
    return out


# ---------------------------------------------------------------- 캐시
def load(cache_dir: Path, game_dir, opener=None) -> tuple[dict[str, dict], bool]:
    """이름 표와 '이번에 새로 만들었나'. cache_dir\\names.json 의 stamp·FORMAT 이 지금과 같으면 그대로 쓴다.
    opener: 게임 폴더 → Sheets (기본 gamesheet.Sheets.open — 시험에서 바꾼다)."""
    names, fresh = G.cached(Path(cache_dir) / "names.json", FORMAT, game_dir, lambda sh: build(sh), opener,
                            what="드레스룸 이름", key="names")
    return (names or {}), fresh
