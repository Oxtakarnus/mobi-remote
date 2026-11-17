"""옷이 가리는 것 — 모델 정의(StageObjectModel)의 숨김 값 → 뷰어 규칙 (web/dressroom/cover.js 가 쓴다).

  ModelPartInfo.Hide<부위>                 참이면 이 옷을 입었을 때 그 부위를 숨긴다
  ModelPartInfo.Hide<부위>ByHelmetCover    투구 덮개를 닫았을 때만 숨긴다
      부위: Hair · Head · Eye · LeftEye · RightEye · LeftEyebrow · RightEyebrow · Beard
            · Accessory0(얼굴 장식) · Accessory1(눈 장식) · Accessory2(귀 장식)
  InterModelInfo.AppearanceTuningInfo.PressHood · PressHoodH<k>
      이 머리(모자 단계 k)는 벗은 후드를 눌린 모양(Hood_Off_Pressed)으로 — 머리·가발에만 있다
  InterModelInfo.MouthControlInfo.OverrideEmotionIndex
      이 장식을 하면 입을 표정 표의 그 칸(1부터)으로 — 풍선껌

결과 {"hide": [부위], "cap": [부위], "press": [단계] | "all", "mouth": 칸} (빈 칸은 뺀다, 다 비면 None).
모델 json 의 rules 에 싣는다.

게임 부위·겹침 순서 fit(som) — ModelPartInfo.AppearanceSlot(Top·Bottom·OnePiece·Hand·Foot·Robe·AccessoryBody0…)과
JunctionPointInfo 의 이음새 크기(WaistSize·WristSize·AnkleSize: VeryLowest~VeryHighest). 게임 부위는 가림 판정에
(우리 부위와 다를 수 있다 — 백팩은 로브 칸이지만 AccessoryBody0), 이음새는 어느 옷이 바깥인지 정해 바깥 옷의 자르는 판
(Mesh_SP_*)으로 안쪽 옷을 자르는 데 쓴다 (web/dressroom/cover.js gameSlot·outside, fit.js). 모델 json 의 fit 에 싣는다.
"""
from __future__ import annotations

import re

_CAP = "ByHelmetCover"
_PRESS = re.compile(r"PressHoodH(\d)$")


def slot(som: dict | None) -> str:
    """모델 정의의 게임 부위 ModelPartInfo.AppearanceSlot (MainTool·Accessory0·AccessoryBody0 …, 없으면 "").
    목록(장식 부위·무기 대표)·얼굴 부품·겹침 순서가 모두 이것을 읽는다."""
    mpi = som.get("ModelPartInfo") if isinstance(som, dict) else None
    v = mpi.get("AppearanceSlot") if isinstance(mpi, dict) else None
    return v if isinstance(v, str) else ""


def fit(som: dict | None) -> dict | None:
    """모델 정의 → {"slot": 게임 부위, "junctions": {이음새: 크기}} (둘 다 없으면 None)."""
    if not isinstance(som, dict) or not isinstance(som.get("ModelPartInfo"), dict):
        return None
    mpi = som["ModelPartInfo"]
    jp = mpi.get("JunctionPointInfo") if isinstance(mpi.get("JunctionPointInfo"), dict) else {}
    junctions = {k: v for k, v in jp.items() if isinstance(v, str) and v}
    s = slot(som)
    if not junctions and not s:
        return None
    return {"slot": s, "junctions": junctions}


def rules(som: dict | None) -> dict | None:
    """모델 정의 dict → 가림 규칙 (없으면 None)."""
    if not isinstance(som, dict):
        return None
    mpi = som.get("ModelPartInfo")
    mpi = mpi if isinstance(mpi, dict) else {}
    hide, cap = set(), set()
    for k, v in mpi.items():
        if v is not True or not k.startswith("Hide"):
            continue
        slot = k[4:-len(_CAP)] if k.endswith(_CAP) else k[4:]
        if slot:
            (cap if k.endswith(_CAP) else hide).add(slot)
    imi = som.get("InterModelInfo") if isinstance(som.get("InterModelInfo"), dict) else {}
    tun = imi.get("AppearanceTuningInfo")
    tun = tun if isinstance(tun, dict) else {}
    mouth = (imi.get("MouthControlInfo") or {}).get("OverrideEmotionIndex") if isinstance(imi.get("MouthControlInfo"), dict) else None
    if tun.get("PressHood") is True:
        press = "all"
    else:
        press = sorted(int(m.group(1)) for k, v in tun.items() if v is True and (m := _PRESS.match(k)))
    out = {}
    if hide:
        out["hide"] = sorted(hide)
    if cap:
        out["cap"] = sorted(cap)
    if press:
        out["press"] = press
    if isinstance(mouth, int) and not isinstance(mouth, bool) and mouth > 0:
        out["mouth"] = mouth
    return out or None
