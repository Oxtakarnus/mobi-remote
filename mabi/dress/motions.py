"""드레스룸 동작 목록 — 공통·꾸미기·감정 표현 (게임 시트 + 동작 파일 목차).

  공통      동작 상태 시트(AnimationStateSet)의 Player<체형 폴더> 상태 중 STATES 에 이름을 단 것.
            셰이프별 파일은 같은 시트의 'Gender:…, BodyType:<셰이프>' 줄. 직업 갈래('CombatJob:<직업>'·
            'CombatJob:<직업>, BodyType:<셰이프>')가 있는 상태는 무기를 든 동작이고 직업마다 파일이 다르다 (jobs —
            화면이 입은 패션 무기의 직업으로 고른다. 직업 폴더 파일이라 동작 폴더 밖이고, 다른 체형 폴더 파일도 있다).
  꾸미기    Customize 폴더 — <이름>_<셰이프>[_Start|_Loop] (시트 없이 파일 이름으로).
  감정 표현 SocialAction 시트(한글 이름·키) → PlayerCommon 아래 그 키의 파일. 시작(_Start)이 있으면 시작 → 반복.
            두 사람 동작은 Host 쪽만, 실패 동작(_Fail)은 뺀다.
  표정 짝   같은 폴더의 <파일>_Facial (게임의 표정 짝 시트도 이 규칙을 따른다) — 몸 동작과 같이 튼다.
  표정      Facial 시트(게임 표정 메뉴 — 이모지·이름·체형별 PlayerCommon_FaceOnly_*_Facial) — 얼굴 뼈만, 지금 동작 위에 얹는다.
  타임라인  감정 표현의 이펙트 (fx.timeline) — ActionStageTimeline 시트(동작 키·배우 Player<체형>·'Any' 갈래 → 타임라인들,
            단계 수와 같으면 단계마다, 아니면 첫 단계), 시트에 없으면 이름 규칙 Emotion_<키>[_HF·HM·HC]·
            PlayerCommon_Emotion_<키>·<단계 줄기에서 PlayerCommon_ 뺀 것>[_HF…]. 그릴 것이 있는 타임라인만 둔다.

표 (motions.json, 시트·동작 목차가 그대로면 다시 쓴다):
  {"list": [{"id", "cat", "name", "steps": {체형 폴더: {셰이프: [줄기…]}}}],   마지막 줄기를 반복한다
            공통 중 무기를 든 동작은 "drawn": true, "jobs": {직업: {체형 폴더: {셰이프: [줄기]}}} 도 둔다
   "clips": {줄기: 자산 경로}, "facial": {몸 줄기: 표정 줄기}, "timeline": {몸 줄기: 타임라인 이름}}
줄기 = 파일 이름에서 .fbx 를 뺀 것 (HF@PlayerCommon_Walk) — 모델 id 'clip:<줄기>'. 셰이프 '' 는 기본,
다른 셰이프는 기본과 다를 때만 둔다.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from .. import gamefiles as gf
from .. import gamesheet as G
from . import assets as A
from . import catalog as C
from . import names as NM

log = logging.getLogger("mabi")

FORMAT = 5   # 2: 표정(face) 갈래, 3: 무기를 꺼내 드는 공통 동작 drawn, 4: 직업별 동작 jobs·전투 자세·경계 걷기 등,
             # 5: 감정 표현 타임라인 timeline
CATS = (("common", "공통"), ("customize", "꾸미기"), ("emotion", "감정 표현"), ("face", "표정"))
FOLDERS = tuple(sorted({v[1] for v in C.BODIES.values()}))    # Female · Infant · Male
ACTORS = {"Female": "PlayerFemale", "Male": "PlayerMale", "Infant": "PlayerInfant"}   # 동작 타임라인 시트의 배우
SUFFIX = {"Female": "HF", "Male": "HM", "Infant": "HC"}                                # 타임라인 이름 끝
SHAPES = tuple(C.STAND)   # 뷰어 셰이프 이름 ('' 기본·Thin·Fat·Muscular)
_SHAPE_TOKEN = {"default": "", "thin": "Thin", "fat": "Fat", "muscle": "Muscular", "muscular": "Muscular"}

# 공통 — 상태 이름 → 보여 줄 이름 (이 순서로, 같은 파일은 앞 것만). 의자 앉기는 의자가 없어 뺀다
STATES = (("PeaceStand", "서 있기"), ("BodyDiversityCommonStand", "기본 자세"), ("AlertStand", "경계 자세"),
          ("CombatStand", "전투 자세"), ("InventoryPose", "가방 자세"),
          ("PeaceWalk", "걷기"), ("AlertWalk", "경계 걷기"), ("CombatWalk", "전투 걷기"),
          ("PeaceWalkBackward", "뒤로 걷기"), ("PeaceWalkWallPushing", "제자리 걷기"),
          ("PeaceRun", "달리기"), ("AlertRun", "경계 달리기"), ("CombatRun", "전투 달리기"),
          ("PeaceRunWallPushing", "제자리 달리기"), ("PeaceRunUpHill", "오르막 달리기"),
          ("PeaceRunUpHillSteep", "가파른 오르막 달리기"), ("PeaceRunDownHill", "내리막 달리기"),
          ("PeaceRunDownHillSteep", "가파른 내리막 달리기"), ("RunToStand", "달리다 멈추기"),
          ("HitBody", "맞기"), ("GroggyHit", "비틀거리기"), ("DownHit", "쓰러졌다 일어나기"))
# 무기를 꺼내 드는 동작 — 시트에 직업별(CombatJob:) 갈래가 있는 상태는 전투 중 무기를 든 동작이다 (2026-11-17 시트:
# 경계·전투 자세, 경계·전투 걷기·달리기, 가방 자세, 맞기·비틀거리기·쓰러졌다 일어나기 — 서 있기·걷기·달리기(Peace)는
# 직업 갈래가 없다). 목록 항목에 drawn 을 달고, 나머지 동작·대기는 무기를 넣은 모습 (motion.js).
# 무기 꺼내기·넣기(ToolDraw·ToolUndraw)는 동작 도중에 무기가 붙는 곳이 바뀌어 뺀다.
_DRAWN_BRANCH = "CombatJob:"
# 꾸미기 — 이름 앞부분 → 보여 줄 이름 (번호가 붙으면 뒤에 번호)
CUSTOM = (("Stand_Start_", "대기 시작"), ("Stand", "대기"), ("Pose_", "포즈"), ("Costume_", "의상 포즈"),
          ("Body_Start_", "체형 고르기"), ("Face_Start_", "얼굴 고르기"), ("Complete", "완성"), ("EnterStage", "등장"))
_CUSTOM = re.compile(r"^H[FMC]@Customize_(.+?)_(Default|Fat|Muscle|Thin)(?:_(Start|Loop))?$", re.I)
_PHASE = re.compile(r"_(start|loop|end)(?=_\d+$|$)")     # 단계 낱말 — 끝이나 끝 번호 앞 (Start_01)
_EMO_LOOSE = re.compile(r"^h[fmc]@playercommon_(emotion|dance|event)_")
_SPLIT = re.compile(r"[_@]|(?<=[a-z])(?=[A-Z])|(?<=\d)(?=\D)|(?<=\D)(?=\d)")


class Clips:
    """체형 폴더 하나의 동작 파일 — 줄기 → 경로, 셰이프를 뺀 이름(소문자) → {셰이프: 줄기}."""

    def __init__(self, paths: dict[str, str]):
        self.path = paths
        self.by_norm: dict[str, dict[str, str]] = {}
        for stem in sorted(paths):
            if stem.endswith("_Facial"):
                continue
            norm, shape = norm_of(stem)
            self.by_norm.setdefault(norm, {}).setdefault(shape, stem)

    def shaped(self, stem: str) -> dict[str, str]:
        """줄기 → {셰이프: 줄기} (기본 '' 은 늘 있다 — 셰이프 파일만 있으면 그중 하나)."""
        v = self.by_norm.get(norm_of(stem)[0], {})
        base = v.get("") or stem
        return {s: v.get(s) or base for s in SHAPES}


def norm_of(stem: str) -> tuple[str, str]:
    """줄기 → (셰이프 낱말을 뺀 소문자 이름, 셰이프)."""
    pre, _, name = stem.partition("@")
    shape, keep = "", []
    for tok in name.split("_"):
        k = tok.lower()
        if k in _SHAPE_TOKEN:
            shape = _SHAPE_TOKEN[k]
        else:
            keep.append(k)
    return f"{pre.lower()}@{'_'.join(keep)}", shape


def index(paths, every: bool = False) -> dict[str, dict[str, str]]:
    """자산 경로들 → 체형 폴더 → {줄기: 경로}. 기본은 목록 갈래가 보는 동작 폴더(A.ANIM_DIRS) 안 fbx 만,
    every 면 사람 동작 fbx 전부 (직업 폴더 — common 의 jobs)."""
    out: dict[str, dict[str, str]] = {f: {} for f in FOLDERS}
    for p in paths:
        if not (p.startswith(C.ANIM) and p.endswith(".fbx") and (every or any(d in p for d in A.ANIM_DIRS))):
            continue
        folder = p[len(C.ANIM):].split("/", 1)[0]
        if folder in out and "/TestPose/" not in p:
            out[folder].setdefault(p.rsplit("/", 1)[-1][:-4], p)
    return out


# ── 시트 ──
def state_rows(sh: G.Sheets) -> list[tuple[str, str, str, str]]:
    """AnimationStateSet → [(세트, 갈래, 상태, 파일 경로)]."""
    s = sh.sheet("AnimationStateSet")
    pre = s.preload()
    rows = []
    for i in range(s.count):
        st, branch, state = pre.s(), pre.s(), pre.s()
        r = s.reader(i)
        r.u8()
        rows.append((st, branch, state, r.s()))
    return rows


def social_rows(sh: G.Sheets) -> list[tuple[str, str]]:
    """SocialAction → [(한글 이름, 키)]."""
    s = sh.sheet("SocialAction")
    out = []
    for i in range(s.count):
        r = s.reader(i)
        name, _cat = r.s(), r.s()
        r.vu()
        r.s()            # 아이콘
        r.vu()
        r.s()            # 종류 (Normal·Random·Logic)
        r.vu()
        key = r.s()
        if key and key.isascii():
            out.append((NM.clean(name), key))
    return out


def action_rows(sh: G.Sheets, names: dict[str, str]) -> dict[tuple[str, str], list[str]]:
    """ActionStageTimeline → {(동작 키, 배우): [타임라인…]} — 'Any' 갈래만. 키·배우·갈래 뒤 칸 꼴을 다 몰라
    행 나머지에서 문자열로 읽히는 값 중 타임라인 이름(names — 소문자 → 이름)인 것을 차례대로 줍는다."""
    if "ActionStageTimeline" not in sh:
        return {}
    s = sh.sheet("ActionStageTimeline")
    text = sh.text
    out: dict[tuple[str, str], list[str]] = {}
    for i in range(s.count):
        r = s.reader(i)
        try:
            key, actor, branch = r.s(), r.s(), r.s()
        except (IndexError, ValueError, G.SheetError):
            continue
        if branch != "Any":
            continue
        rest, got = s.row(i)[r.o:], []
        for o in range(len(rest)):
            try:
                v = G.Reader(rest, o, text).s()
            except (IndexError, ValueError, G.SheetError):
                continue
            name = names.get(v.lower())
            if name and name not in got:
                got.append(name)
        if got:
            out.setdefault((key, actor), got)
    return out


def face_rows(sh: G.Sheets) -> list[tuple[str, str, list[str]]]:
    """Facial(표정 메뉴) → [(한글 이름, 이모지, [남·여·아이 표정 파일 이름(.fbx)])]. 시트가 없으면 []."""
    if "Facial" not in sh:
        return []
    s = sh.sheet("Facial")
    out = []
    for i in range(s.count):
        r = s.reader(i)
        name = r.s()
        r.vu()           # 설명 글
        icon = r.s()
        files = [r.s(), r.s(), r.s()]
        out.append((NM.clean(name), icon, files))
    return out


# ── 갈래별 ──
def _steps(clips: Clips, stems: list[str]) -> dict[str, list[str]]:
    """줄기 순서 → {셰이프: 줄기 순서} (기본과 같은 셰이프는 뺀다)."""
    shaped = [clips.shaped(s) for s in stems]
    base = [v[""] for v in shaped]
    out = {"": base}
    for sh in SHAPES[1:]:
        cur = [v[sh] for v in shaped]
        if cur != base:
            out[sh] = cur
    return out


def common(rows, folder: str, clips: Clips, every: dict[str, str] | None = None) -> list[dict]:
    """공통 동작. every: 줄기 → 경로 (사람 동작 전부 — 직업 갈래 파일을 찾는다, 없으면 clips 것만)."""
    st_name = "Player" + folder
    every = every if every is not None else clips.path
    base = {state: p for s, b, state, p in rows if s == st_name and b == "Any"}
    by_shape: dict[str, dict[str, str]] = {}
    jobs: dict[str, dict[str, dict[str, str]]] = {}   # 상태 → 직업 → {셰이프: 경로}
    for s, b, state, p in rows:
        if s != st_name:
            continue
        m = re.search(r"BodyType:(\w+)", b) if b.startswith("Gender:") else None
        if m and m.group(1) in SHAPES:
            by_shape.setdefault(m.group(1), {})[state] = p
        if b.startswith(_DRAWN_BRANCH):
            kv = dict(x.split(":", 1) for x in b.split(", ") if ":" in x)
            if set(kv) <= {"CombatJob", "BodyType"} and kv.get("BodyType", "") in SHAPES:
                jobs.setdefault(state, {}).setdefault(kv["CombatJob"], {}).setdefault(kv.get("BodyType", ""), p)
    drawn = {state for s, b, state, p in rows if s == st_name and b.startswith(_DRAWN_BRANCH)}
    out, seen = [], set()
    for state, label in STATES:
        stem = _stem(base.get(state), clips)
        if not stem:
            continue
        steps = _steps(clips, [stem])
        for sh, table in by_shape.items():   # 시트가 셰이프 파일을 따로 정해 두었으면 그것
            alt = _stem(table.get(state), clips)
            if alt and alt != steps[""][0]:
                steps[sh] = [alt]
        by_job = {}
        for job, shaped in sorted(jobs.get(state, {}).items()):
            st = {sh: [x] for sh, x in ((sh, _stem(p, every)) for sh, p in shaped.items()) if x}
            if "" in st:
                by_job[job] = {sh: v for sh, v in st.items() if sh == "" or v != st[""]}
        key = (stem, tuple(sorted((j, v[""][0]) for j, v in by_job.items())))   # 같은 동작이 이름만 다른 상태는 앞 것만
        if key in seen:
            continue
        seen.add(key)
        e = {"id": "s:" + state, "cat": "common", "name": label, "steps": steps}
        if state in drawn:
            e["drawn"] = True
        if by_job:
            e["jobs"] = by_job
        out.append(e)
    return out


def _stem(path: str | None, clips) -> str | None:
    """자산 경로 → 줄기 (clips 에 있을 때만 — Clips 나 {줄기: 경로})."""
    if not path:
        return None
    stem = path.rsplit("/", 1)[-1][:-4]
    return stem if stem in (clips.path if isinstance(clips, Clips) else clips) else None


def customize(clips: Clips) -> list[dict]:
    groups: dict[str, dict[str, dict[str, str]]] = {}
    for stem in clips.path:
        m = _CUSTOM.match(stem)
        if m and not stem.endswith("_Facial"):
            key, shape, phase = m.group(1), _SHAPE_TOKEN[m.group(2).lower()], (m.group(3) or "").title()
            groups.setdefault(key, {}).setdefault(shape, {})[phase] = stem
    out = []
    for key, shapes in groups.items():
        steps = {}
        for sh, ph in shapes.items():
            seq = [ph[k] for k in ("Start", "Loop") if k in ph] if "Loop" in ph else [ph.get("") or ph.get("Start")]
            steps[sh] = [s for s in seq if s]
        if "" not in steps:
            continue
        for sh in [s for s in steps if s and steps[s] == steps[""]]:
            del steps[sh]
        out.append({"id": "c:" + key, "cat": "customize", "name": _custom_name(key), "steps": steps})
    order = {p: i for i, (p, _) in enumerate(CUSTOM)}
    out.sort(key=lambda e: (min((order[p] for p, _ in CUSTOM if e["id"][2:].startswith(p)), default=99), e["id"]))
    return out


def _custom_name(key: str) -> str:
    for pre, label in CUSTOM:
        if key.startswith(pre):
            num = key[len(pre):].lstrip("_")
            return f"{label} {int(num)}" if num.isdigit() else label if not num else f"{label} {num}"
    return key


def emotion(social, clips: Clips) -> list[dict]:
    out = []
    for name, key in social:
        seq = match_social(key, clips)
        if seq:
            out.append({"id": "e:" + key, "cat": "emotion", "name": name, "steps": _steps(clips, seq)})
    return out


def faces(rows, clips: Clips) -> list[dict]:
    """표정 — 이 체형 폴더에 그 표정 파일이 있는 것. 단계는 표정 줄기 하나 (몸 동작이 아니다 — 화면이 얼굴에만 얹는다)."""
    out = []
    for name, icon, files in rows:
        stem = next((f[:-4] for f in files if f.endswith(".fbx") and f[:-4] in clips.path), None)
        if stem:
            key = stem.split("FaceOnly_", 1)[-1].removesuffix("_Facial")
            out.append({"id": "f:" + key, "cat": "face", "name": f"{icon} {name}".strip(), "steps": {"": [stem]}})
    return out


def tokens(name: str) -> set[str]:
    """이름 → 낱말 (밑줄·대소문자·숫자 경계로 자른 소문자)."""
    return {t.lower() for t in _SPLIT.split(name) if t}


def match_social(key: str, clips: Clips) -> list[str] | None:
    """감정 표현 키 → 줄기 순서 (시작 → 반복). 못 찾으면 None."""
    k = key.lower()
    strict = re.compile(rf"^h[fmc]@(?:playercommon_)?(?:emotion_|dance_)?{re.escape(k)}(?:_.+)?$")
    cands = [n for n in clips.by_norm if strict.match(n)]
    if not cands:   # 키와 파일 이름이 조금 다른 것 — 낱말이 다 들어 있는 감정·춤·이벤트 동작 (Bow90 → 90bow)
        want = tokens(key)
        for need in (want, {t for t in want if not t.startswith("0")}):   # 다음엔 붙은 번호(00·01) 없이
            cands = sorted({norm_of(st)[0] for st in clips.path
                            if not st.endswith("_Facial") and need <= tokens(st)} & set(filter(_EMO_LOOSE.match, clips.by_norm)))
            if cands:
                break
    groups: dict[str, dict[str, str]] = {}
    for n in cands:
        m = _PHASE.search(n)
        g = n[:m.start()] + n[m.end():] if m else n
        groups.setdefault(g, {})[m.group(1).title() if m else ""] = n
    names = [g for g in groups if "fail" not in g.split("_")]
    if any("host" in g.split("_") for g in names):   # 두 사람 동작은 한 사람 몫만
        names = [g for g in names if "guest" not in g.split("_")]
    for g in sorted(names, key=lambda g: (len(g), g)):
        ph = groups[g]
        main = ph.get("Loop") or ph.get("")
        seq = ([ph["Start"]] if "Start" in ph else []) + ([main] if main else [])
        if seq:
            return [clips.by_norm[n].get("") or next(iter(clips.by_norm[n].values())) for n in seq]
    return None


def _first(names: dict[str, str], cands) -> str | None:
    return next((names[c.lower()] for c in cands if c.lower() in names), None)


def timelines(lst: list[dict], acts: dict, tl) -> dict[str, str]:
    """감정 표현 단계 줄기 → 그릴 것이 있는 타임라인 이름 (머리 설명의 '타임라인'). tl: fx.Effects (timelines·useful)."""
    names = tl.timelines()
    good: dict[str, bool] = {}
    out: dict[str, str] = {}
    for e in lst:
        if e["cat"] != "emotion":
            continue
        key = e["id"].split(":", 1)[1]
        for folder, shapes in e["steps"].items():
            sfx = SUFFIX.get(folder, "")
            got = acts.get((key, ACTORS.get(folder, ""))) or []
            if not got:
                one = _first(names, (f"Emotion_{key}_{sfx}", f"Emotion_{key}", f"PlayerCommon_Emotion_{key}"))
                got = [one] if one else []
            for seq in shapes.values():
                for i, stem in enumerate(seq):
                    name = got[i] if len(got) == len(seq) else (got[0] if i == 0 and got else None)
                    if name is None:
                        base = stem.split("@", 1)[-1]
                        short = base.removeprefix("PlayerCommon_")
                        name = _first(names, (f"{short}_{sfx}", short, f"{base}_{sfx}", base))
                    if name is None:
                        continue
                    if name not in good:
                        good[name] = tl.useful(name)
                    if good[name]:
                        out.setdefault(stem, name)
    return out


# ── 표 ──
def build(sh: G.Sheets | None, paths, tl=None) -> dict:
    """시트(없으면 꾸미기만)·자산 경로 → 표. tl: 감정 표현 타임라인 (fx.Effects — 없으면 timeline 이 빈다)."""
    idx = index(paths)
    full = index(paths, every=True)
    every = {s: p for f in FOLDERS for s, p in full[f].items()}   # 직업 갈래는 다른 체형 폴더 파일도 쓴다
    rows = state_rows(sh) if sh is not None else []
    social = social_rows(sh) if sh is not None else []
    face = face_rows(sh) if sh is not None else []
    merged: dict[str, dict] = {}
    for folder in FOLDERS:
        clips = Clips(idx[folder])
        for e in common(rows, folder, clips, every) + customize(clips) + emotion(social, clips) + faces(face, clips):
            m = merged.setdefault(e["id"], {"id": e["id"], "cat": e["cat"], "name": e["name"], "steps": {}})
            m["steps"][folder] = e["steps"]
            if e.get("drawn"):
                m["drawn"] = True
            for job, st in (e.get("jobs") or {}).items():
                m.setdefault("jobs", {}).setdefault(job, {})[folder] = st
    used = {s for e in merged.values() for f in e["steps"].values() for seq in f.values() for s in seq}
    used |= {s for e in merged.values() for j in (e.get("jobs") or {}).values() for f in j.values()
             for seq in f.values() for s in seq}
    facial = {s: s + "_Facial" for s in used if s + "_Facial" in every}
    clip_paths = {s: every[s] for s in used | set(facial.values())}
    order = {c: i for i, (c, _) in enumerate(CATS)}
    lst = sorted(merged.values(), key=lambda e: order[e["cat"]])   # 갈래 안 순서는 만든 순서 그대로
    timeline: dict[str, str] = {}
    if sh is not None and tl is not None:
        try:
            timeline = timelines(lst, action_rows(sh, tl.timelines()), tl)
        except Exception as e:   # noqa: BLE001 — 이펙트는 덤이라 못 이어도 동작 표는 낸다
            log.warning(f"드레스룸 감정 표현 타임라인을 잇지 못했습니다: {type(e).__name__}: {e}")
    return {"list": lst, "clips": clip_paths, "facial": facial, "timeline": timeline}


def load(cache_dir: Path, game_dir, paths, pack_stamp, opener=None, tl=None) -> dict:
    """motions.json — 시트·동작 목차(·타임라인 목차)가 그대로면 저장한 것. 시트를 못 읽으면 꾸미기만 (저장 안 함)."""
    def stamper(gd):
        return G.stamp(gd) + list(pack_stamp) + (gf.res_stamp(Path(gd)) if tl is not None else [])
    t, _fresh = G.cached(Path(cache_dir) / "motions.json", FORMAT, game_dir, lambda sh: build(sh, paths, tl), opener,
                         what="드레스룸 동작 표", key="motions", stamper=stamper)
    return t if t is not None else build(None, paths)


def public(t: dict) -> dict:
    """화면에 줄 것 — 갈래·목록·표정 짝·타임라인 (자산 경로는 뺀다)."""
    return {"cats": [{"id": c, "name": n} for c, n in CATS], "list": t["list"], "facial": t["facial"],
            "timeline": t.get("timeline") or {}}
