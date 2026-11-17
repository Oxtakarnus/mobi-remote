"""드레스룸 몸 다양성(나이·키) 자료 — 게임 ResourcesPackage 의 BDC 를 뷰어용 JSON 으로 (읽기만).

  StageObjectModels/ActorModels/<Female|Male|Infant>/<몸 모델>.StageObjectModel.sjon.bin
      MorphableAssets.TargetBdcModelName — 이 몸이 쓰는 BDC 모델 (아이 몸은 Reference 로 어른 모델도 적혀 있다)
  StageObjectModels/ActorModels/<…>/<BDC 모델>.bdc.sjon.bin   (SJON, mabi/sjon.py)
      HeightDiversityDatapointCollection[]: {Age, BlendshapeName(Default·Thin·Fat·Muscular),
        HeightDiversityDatapoints[]: {HeightHint(cm), HeightEnum(Short·Medium·Tall), BoneLocalScales[]: {BoneName, LocalScale*, LocalPosition*}}}

나이는 어른 14~17, 아이 10~13 이다. 기준(어른 17·아이 10, Default·Medium)에서 뼈 크기가 전부 1 이고 위치는 FBX 휴식 자세와
같다 — 뷰어는 기준 대비 비율로 뼈 크기·위치를 바꾼다 (web/dressroom/body.js). 머리의 Adolescent 모프 무게는
기준 나이에서 0, 반대 끝 나이에서 1 이다 (게임 코드 이름 GetAdolescentBlendShapeWeight — 식은 참고한 웹 드레스룸 것).

내보내는 꼴: {model, min_age, max_age, base_age, adolescent: [무게 0 나이, 1 나이],
             states: [{age, body, points: {Short|Medium|Tall: {height_hint, bones: {뼈: {p, s}}}}}]}
"""
from __future__ import annotations

from pathlib import Path

from .. import gamefiles as gf
from .. import sjon
from ..fileio import write_json

# 드레스룸 체형 id (catalog.BODIES) → (폴더, 몸 모델)
MODELS = {
    "Female": ("Female", "Female_Body_00"),
    "Male": ("Male", "Male_Body_00"),
    "Girl": ("Infant", "InfantFemale_Body_00"),
    "Boy": ("Infant", "InfantMale_Body_00"),
}
SHAPES = ("Default", "Thin", "Fat", "Muscular")
HEIGHTS = ("Short", "Medium", "Tall")


class BodyError(Exception):
    """BDC 가 없거나 생각한 모양이 아니다 (게임 패치로 바뀌었을 때)."""


def _path(folder: str, model: str, kind: str) -> str:
    return f"StageObjectModels/ActorModels/{folder}/{model}.{kind}.sjon.bin"


def convert(root: dict, model: str) -> dict:
    """BodyDiversityContainer 루트 → 뷰어용 dict."""
    states, bone_set = [], None
    for c in root.get("HeightDiversityDatapointCollection") or []:
        pts = {}
        for p in c["HeightDiversityDatapoints"]:
            bones = {b["BoneName"]: {"p": [b["LocalPositionX"], b["LocalPositionY"], b["LocalPositionZ"]],
                                     "s": [b["LocalScaleX"], b["LocalScaleY"], b["LocalScaleZ"]]}
                     for b in p["BoneLocalScales"]}
            if bone_set is None:
                bone_set = set(bones)
            elif set(bones) != bone_set:
                raise BodyError(f"{model}: 점마다 뼈 목록이 다릅니다")
            pts[p["HeightEnum"]] = {"height_hint": p["HeightHint"], "bones": bones}
        if set(pts) != set(HEIGHTS):
            raise BodyError(f"{model}: {c['Age']}세 {c['BlendshapeName']} 에 키 점이 모자랍니다")
        states.append({"age": c["Age"], "body": c["BlendshapeName"], "points": pts})
    if not states:
        raise BodyError(f"{model}: 자료가 비었습니다")
    states.sort(key=lambda s: (s["age"], SHAPES.index(s["body"]) if s["body"] in SHAPES else 9))
    ages = sorted({s["age"] for s in states})
    if any(not any(s["age"] == a and s["body"] == b for s in states) for a in ages for b in SHAPES):
        raise BodyError(f"{model}: 빠진 나이·체형이 있습니다")
    # 기준 = Default·Medium 의 뼈 크기가 전부 1 인 나이 (어른 17, 아이 10)
    base = [s["age"] for s in states if s["body"] == "Default"
            and all(v == 1 for b in s["points"]["Medium"]["bones"].values() for v in b["s"])]
    if len(base) != 1:
        raise BodyError(f"{model}: 기준 나이를 정하지 못했습니다")
    lo, hi = ages[0], ages[-1]
    return {"model": model, "min_age": lo, "max_age": hi, "base_age": base[0],
            "adolescent": [base[0], hi if base[0] == lo else lo], "states": states}


def export(game_dir, body: str, out: Path) -> None:
    """체형 하나의 BDC → out (json)."""
    if body not in MODELS:
        raise BodyError(f"모르는 체형: {body}")
    folder, model = MODELS[body]
    som_p = _path(folder, model, "StageObjectModel")
    try:
        res = gf.Resources(Path(game_dir), lambda p: p.startswith("StageObjectModels/ActorModels/") and p.endswith(".sjon.bin"))
        som = sjon.load(res.read(som_p)) if som_p in res.paths else {}
        target = ((som or {}).get("MorphableAssets") or {}).get("TargetBdcModelName") or model
        for f in (folder, "Female", "Male", "Infant"):   # 다른 폴더의 모델을 가리킬 수도 있다
            bdc_p = _path(f, target, "bdc")
            if bdc_p in res.paths:
                break
        else:
            raise BodyError(f"게임 리소스에 {target} 몸 자료가 없습니다")
        d = convert(sjon.load(res.read(bdc_p)), target)
    except (OSError, sjon.SjonError, KeyError, TypeError) as e:
        raise BodyError(f"몸 자료를 읽지 못했습니다 ({type(e).__name__}: {e})") from e
    write_json(out, d, separators=(",", ":"))
