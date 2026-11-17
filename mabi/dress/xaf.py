"""표정 키 (XAF) — 표정 짝 클립(<파일>_Facial)에 딸린 얼굴 재질·메시 보이기·눈꺼풀 모프 키를 프레임마다 값으로 편다.

뼈 클립(fbx)은 얼굴 뼈만 움직이고, 입 모양 그림 칸·표정 눈 그림·눈 메시 숨김·깜빡임은 이 파일에 따로 있다
(게임이 3ds Max 의 XAF 를 sjon 으로 바꿔 둔 것).

자리  ResourcesPackage 본 목차  Animation/XafAnimation/<fbx 자산 경로에서 Assets/PatchableAssets/ 를 뺀 것>.xaf.sjon.bin
      (표정 짝 fbx 944개 중 942개에 있다 — 없으면 뼈만 튼다)
파일  {StartFrame, EndFrame, FrameRate, AnimationDatas: [{AnimationObjectName, KeyframeTracks: [
        {AnimationType: Shader·Visibility·Morpher, AnimationPropertyName, OutOfRange*Type, Keyframes: [
          {Time(프레임), Value, InTangentType, OutTangentType, ...}]}]}]}
      범위 밖은 늘 Constant (끝 키 값 그대로), Custom 탄젠트는 없다.

보간  키 사이는 앞 키의 Out · 뒤 키의 In 탄젠트로 정한다.
      Constant·Step   앞 키 값 그대로
      Flat            기울기 0
      Linear·Fast·Slow  이웃 키로 곧게 (Fast·Slow 는 근사)
      Auto·Smooth·Spline  양옆 키로 매끄럽게 (Auto 는 꼭짓점에서 0 — 넘침 없음)
      → 3차 에르미트.

내보내는 꼴  {"fps", "frames", "tracks": [{"o": 물체, "p": 속성, "t": 'shader'·'vis'·'morph', "v": [프레임마다 값]}]}
      값이 내내 같으면 v 는 하나. 모프는 0~1 (원본 %), 보이기는 원본 값 (뷰어가 0.5 로 가른다).
"""
from __future__ import annotations

from .. import gamefiles as gf
from .. import sjon

_DIR = "Animation/XafAnimation/"
_END = ".xaf.sjon.bin"
_PREFIX = "Assets/PatchableAssets/"
_TYPES = {"Shader": "shader", "Visibility": "vis", "Morpher": "morph"}
_HOLD = ("Constant", "Step")
_LINE = ("Linear", "Fast", "Slow")


def path_for(fbx: str) -> str:
    """표정 짝 fbx 자산 경로 → XAF 자리."""
    return _DIR + fbx.removeprefix(_PREFIX).rsplit(".", 1)[0] + _END


class Library:
    """XAF 목차 — 처음 쓸 때 연다 (0.5초쯤)."""

    def __init__(self, gd):
        self.gd = gd
        self._res: gf.Resources | None = None

    def keys(self, fbx: str) -> dict | None:
        """표정 짝 fbx → 내보낼 키 (없거나 못 읽으면 None)."""
        if self._res is None:
            self._res = gf.Resources(self.gd, lambda p: p.startswith(_DIR) and p.endswith("_Facial" + _END), main=True)
        p = path_for(fbx)
        if p not in self._res.paths:
            return None
        d = sjon.load(self._res.read(p))
        return convert(d) if isinstance(d, dict) else None


def _slope(keys: list, i: int, side: str) -> float:
    """키 i 의 기울기 (값/프레임) — side 'in' 은 앞 구간 쪽, 'out' 은 뒤 구간 쪽 탄젠트."""
    k = keys[i]
    kind = k.get(side.capitalize() + "TangentType")
    t, v = k["Time"], k["Value"]
    prev = keys[i - 1] if i > 0 else None
    nxt = keys[i + 1] if i + 1 < len(keys) else None
    if kind == "Flat" or kind in _HOLD:
        return 0.0
    if kind in _LINE:
        o = nxt if side == "out" else prev
        if o is None or o["Time"] == t:
            return 0.0
        return (o["Value"] - v) / (o["Time"] - t)
    # Auto·Smooth·Spline (그 밖의 모르는 이름도)
    a, b = prev or k, nxt or k
    if b["Time"] == a["Time"]:
        return 0.0
    if kind == "Auto" and prev and nxt and (v - prev["Value"]) * (nxt["Value"] - v) <= 0:
        return 0.0
    return (b["Value"] - a["Value"]) / (b["Time"] - a["Time"])


def sample(keys: list, frame: float) -> float:
    """키 목록 → frame 의 값 (범위 밖은 끝 키 값)."""
    if not keys:
        return 0.0
    if frame <= keys[0]["Time"]:
        return float(keys[0]["Value"])
    for i in range(len(keys) - 1):
        a, b = keys[i], keys[i + 1]
        if frame > b["Time"]:
            continue
        h = b["Time"] - a["Time"]
        if h <= 0:
            return float(b["Value"])
        if a.get("OutTangentType") in _HOLD or b.get("InTangentType") in _HOLD:
            return float(a["Value"]) if frame < b["Time"] else float(b["Value"])
        s = (frame - a["Time"]) / h
        m0, m1 = _slope(keys, i, "out") * h, _slope(keys, i + 1, "in") * h
        s2, s3 = s * s, s * s * s
        return float((2 * s3 - 3 * s2 + 1) * a["Value"] + (s3 - 2 * s2 + s) * m0
                     + (-2 * s3 + 3 * s2) * b["Value"] + (s3 - s2) * m1)
    return float(keys[-1]["Value"])


def convert(d: dict) -> dict | None:
    """XAF 내용 → 내보낼 키 (트랙이 없으면 None)."""
    start, end = int(d.get("StartFrame") or 0), int(d.get("EndFrame") or 0)
    n = max(1, end - start + 1)
    tracks = []
    for ad in d.get("AnimationDatas") or []:
        obj = ad.get("AnimationObjectName") or ""
        for tr in ad.get("KeyframeTracks") or []:
            kind = _TYPES.get(tr.get("AnimationType"))
            keys = sorted(tr.get("Keyframes") or [], key=lambda k: k["Time"])
            if kind is None or not keys:
                continue
            prop = tr.get("AnimationPropertyName") or ""
            if kind == "vis":
                prop = "Visibility"   # 'visibility' 로 적힌 것도 있다
            scale = 0.01 if kind == "morph" else 1.0
            v = [round(sample(keys, start + f) * scale, 4) for f in range(n)]
            if all(x == v[0] for x in v):
                v = v[:1]
            tracks.append({"o": obj, "p": prop, "t": kind, "v": v})
    if not tracks:
        return None
    return {"fps": float(d.get("FrameRate") or 30), "frames": n, "tracks": tracks}
