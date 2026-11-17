"""의상 이펙트 — 게임이 옷에 붙여 트는 파티클·덧그리기 (드레스룸, 읽기만 한다).

  시트 StageObjectModelTimeline  행 키 = 모델 이름, 문자열 칸 6 개. 칸 2 는 늘 트는 타임라인, 칸 4 는 후드를 쓴 때만
                                 트는 타임라인 (드래곤 로브). 칸 3(끝날 때)·5(다른 판)는 쓰지 않는다.
  ResourcesPackage 본 목차  StageTimelines/<이름>.StageTimeline.sjon.bin
      Tracks[] Type Effect            Intervals[].Playable — PrefabPathGroups.Default.Lod0 (Fx/… prefab),
                                      PosRefBoneName·RotRefBoneName (옷 prefab 의 EffectSocket_* 노드나 몸 뼈, #MODEL_ROOT = 발밑),
                                      LocalOffset·LocalRotation(도, Unity 오일러), Rotation/PositionAttachmentInfo.EffectAttachmentType
               Type AdditiveRenderer  MaterialPath (Fx/… mat), TargetRendererNames — 그 메시를 이 재질로 한 번 더 그린다
  감정 표현도 동작마다 타임라인이 있다 (동작 표 timeline — motions). 구간마다 시작·끝 시각이 있어 동작 시간에 맞춰 튼다:
  timeline()  몸에 붙는 Effect 구간만 (소품에 붙는 것·소품·IK 는 아직) → {tracks (+ begin·end·follow), prefabs}
              begin·end 초 (IsInfinite 면 end 없음 — 동작이 다시 돌 때까지), follow = PositionAttachmentInfo 가 Attached
              (NotAttached 는 시작한 자리에 남는다)
AssetPackages  Fx/1_Effect/Character/0_Common/Fashion/FX_*.prefab · …/Emotion/FX_*.prefab (감정 표현) — ParticleSystem 노드 트리. 재질·그림·메시는 Fx/**/0_Resource/,
                 셰이더는 Shaders/MMN/FX/·Shaders/MMN/CH/MMN_CharacterFX* 에 있다. 이펙트용 CAB 표는 dressroom\\fx\\ 에 따로 둔다
                 (캐릭터 표를 키우지 않게 — 무대 stage 와 같은 방식).

이펙트 소켓 노드(EffectSocket_*·_Lip_Effect)는 옷 prefab 에만 있고 fbx 에는 없다 — sockets() 로 꺼내 모델 뼈대에 더한다.
다른 옷의 소켓을 쓰는 이펙트도 있어(꽃요정 모자) 뷰어는 이름으로 공용 뼈대 전체에서 찾는다.

모델 json 의 fx (뷰어 web/dressroom/fx.js):
  tracks    [{fx: prefabs 번호, bone, rbone ('' = 캐릭터 발밑), off, rot(x,y,z,w), turn(돌기도 뼈를 따른다), hood}]
  overlays  [{meshes, mat, hood}]
  prefabs   [{name, systems: [system()…], meshes: [기본 메시 이름 | {pos, nrm, uv, idx}]}] — 시스템 mesh 는 meshes 번호.
            prefab 안의 보통 메시(MeshRenderer)도 같은 칸의 시스템(STATIC — 늘 떠 있는 입자 하나)으로 싣는다.
좌표·값은 Unity 그대로다 (뷰어가 뼈대 루트에서 x 를 뒤집는다). 곡선은 0~1 을 N 등분한 표본, 그라디언트도 같다.
"""
from __future__ import annotations

import logging
import math
import threading
from pathlib import Path

import numpy as np

from .. import gamefiles as gf
from .. import gamesheet as G
from .. import sjon
from . import assets as A
from . import export as E
from . import stage as ST
from . import textures as T
from . import tools as TL

log = logging.getLogger("mabi")

SHEET = "StageObjectModelTimeline"
FORMAT = 1                  # fx.json 형식
COL_ALWAYS, COL_HOOD = 2, 4
FASHION = "/Fx/1_Effect/Character/0_Common/Fashion/"
EMOTION = "/Fx/1_Effect/Character/0_Common/Emotion/"
ASSET = "Assets/PatchableAssets/"
N = 16                      # 곡선·그라디언트 표본 칸 (N+1 개)
_TL = "StageTimelines/"
_TL_END = ".StageTimeline.sjon.bin"
_WEARABLE = ("Female_", "Male_", "Infant_")
# Unity 기본 메시 (unity default resources 의 경로 id)
_BUILTIN = {10202: "cube", 10206: "cylinder", 10207: "sphere", 10208: "capsule", 10209: "plane", 10210: "quad"}
# 셰이더 이름 끝 → 뷰어 셰이더 종류
_KIND = {"FX_Default": "default", "FX_Default_VertexOffset": "vertexoffset", "FX_Dissolve_Div_01": "dissolve",
         "FX_Dissolve_Div_Offset_Fresnel": "fresnel", "FX_Dissolve_Div_Distortion_2C_AddNoise": "addnoise",
         "FX_HornFlame": "horn"}
_OPAQUE = "FX_Opaque"       # 기본 식으로 그리되 불투명
_FLOATS = ("_Use_G_Channel_Alpha", "_Intensity_Color", "_Intensity_Alpha", "_EffectAlpha", "_Use_VretexColor",
           "_UVType", "_Twist", "_Noise_X_Speed", "_Noise_Y_Speed", "_ColorGradation", "_Color_Offset", "_Color_Range",
           "_LerpColor_Offset", "_LerpColor_Range", "_LerpColor_Intensity", "_Fresnel_OneMinus", "_DefaultValues",
           "_RimMin", "_RimMax", "_SequenceX", "_SequenceY", "_AddNoise_X_Speed", "_AddNoise_Y_Speed",
           "_Distortion_Offset", "_Distortion_X_Power", "_Distortion_Y_Power", "_VertexOffset_Speed", "_VertexOffset_Power",
           "_FlameDistortionStrength", "_FlameInsideCenter", "_FlameInsideSoftness", "_FlameOuterEdgeFade",
           "_FlameAlphaIntensity", "_FlameAlphaThreshold", "_FlameAlphaSoftness", "_FlameWidth", "_FlameDepthPush")
_COLORS = ("_Color", "_MainColor", "_SubColor", "_LerpColor", "_FlameColorBase", "_FlameColorTip", "_FlameNoiseTiling",
           "_FlameNoiseSpeed")
_MAPS = ("_MainTex", "_NoiseTex", "_AddNoiseTex", "_AlphaTex", "_MaskTex", "_FlameNoiseMap")


# prefab 안의 보통 메시 — 주기마다 하나씩 내지만 상한 1, 수명이 끝없어 처음 하나가 늘 떠 있다 (system() 과 같은 칸)
STATIC = {"dur": 1.0, "loop": True, "prewarm": False, "delay": 0.0, "space": 0, "scaling": 0, "life": 1e9, "speed": 0.0,
          "size": 1.0, "rot": 0.0, "flipRot": 0.0, "color": [1.0, 1.0, 1.0, 1.0], "gravity": 0.0, "max": 1,
          "emit": {"rate": 0.0, "dist": 0.0, "bursts": [[0.0, 1.0, 1, 0.01, 1.0]]}, "streams": [],
          "render": {"mode": 4, "align": 2, "len": 1.0, "vscale": 0.0, "max": 0.0, "min": 0.0, "pivot": [0.0, 0.0, 0.0],
                     "flip": [0.0, 0.0], "sort": 0}}


def keep(p: str) -> bool:
    """이펙트용 CAB 표가 기억할 자산 경로 (바꾸면 assets._CAB_VER 를 올린다 — 표를 다시 만든다)."""
    return (FASHION in p or EMOTION in p or ("/Fx/" in p and "/0_Resource/" in p) or "/Shaders/MMN/FX/" in p
            or "/Shaders/MMN/CH/MMN_CharacterFX" in p)


# ---------------------------------------------------------------- 시트
def table(sh: G.Sheets) -> dict[str, list]:
    """시트 → 의상 모델 이름 → [[타임라인 이름, 후드를 쓴 때만?], …]."""
    s = sh.sheet(SHEET)
    pre = s.preload()
    out: dict[str, list] = {}
    for i in range(s.count):
        key = pre.s()
        if not key.startswith(_WEARABLE):
            continue
        r = s.reader(i)
        cols: list[str] = []
        while not r.done and len(cols) <= COL_HOOD:
            cols.append(r.s())
        got = [[cols[c], c == COL_HOOD] for c in (COL_ALWAYS, COL_HOOD) if c < len(cols) and cols[c]]
        if got:
            out[key] = got
    return out


# ---------------------------------------------------------------- 값 바꾸기
def _r(v: float) -> float:
    """유효 숫자 5 자리 (json 크기)."""
    v = float(v)
    return float(f"{v:.5g}") if math.isfinite(v) else 0.0


def euler_quat(e) -> list[float]:
    """Unity 오일러(도) → 사원수 (x, y, z, w), 유효 숫자 5 자리 — 식은 tools.quat 하나."""
    return [_r(v) for v in TL.quat(e)]


def curve_at(keys: list, t: float) -> float:
    """Unity AnimationCurve (에르미트 접선, 무게 없음) 의 t 값. 키가 없으면 0, 범위 밖은 끝 값."""
    if not keys:
        return 0.0
    if t <= keys[0]["time"]:
        return float(keys[0]["value"])
    if t >= keys[-1]["time"]:
        return float(keys[-1]["value"])
    a = b = keys[0]
    for a, b in zip(keys, keys[1:]):
        if t <= b["time"]:
            break
    dt = b["time"] - a["time"]
    if dt <= 1e-9:
        return float(b["value"])
    m0, m1 = a["outSlope"] * dt, b["inSlope"] * dt
    if not (math.isfinite(m0) and math.isfinite(m1)):   # 계단 접선
        return float(a["value"])
    s = (t - a["time"]) / dt
    s2, s3 = s * s, s * s * s
    return ((2 * s3 - 3 * s2 + 1) * a["value"] + (s3 - 2 * s2 + s) * m0 + (-2 * s3 + 3 * s2) * b["value"]
            + (s3 - s2) * m1)


def mm(c: dict, k: float = 1.0):
    """MinMaxCurve → 상수 | [작은, 큰] | {c: 표본} | {c: 큰 곡선, c2: 작은 곡선} (곡선은 scalar 를 곱한 값)."""
    st, s = c["minMaxState"], c["scalar"] * k
    if st == 0:
        return _r(s)
    if st == 3:
        return [_r(c["minScalar"] * k), _r(s)]
    hi = [_r(s * curve_at(c["maxCurve"]["m_Curve"], i / N)) for i in range(N + 1)]
    if st == 1:
        return {"c": hi}
    return {"c": hi, "c2": [_r(s * curve_at(c["minCurve"]["m_Curve"], i / N)) for i in range(N + 1)]}


def _zero(v) -> bool:
    return v == 0 or v == [0, 0] or (isinstance(v, dict) and not any(v.get("c", [])) and not any(v.get("c2", [])))


def _keys_at(times: list, vals: list, t: float, fixed: bool) -> tuple:
    if t <= times[0]:
        return vals[0]
    if t >= times[-1]:
        return vals[-1]
    for i in range(len(times) - 1):
        if t <= times[i + 1]:
            if fixed:
                return vals[i + 1]
            d = times[i + 1] - times[i]
            k = (t - times[i]) / d if d > 1e-9 else 1.0
            return tuple(a + (b - a) * k for a, b in zip(vals[i], vals[i + 1]))
    return vals[-1]


def gradient_at(g: dict, t: float) -> list[float]:
    """Unity Gradient 의 t 색 (r, g, b, a) — 색 키·알파 키를 따로 잇는다 (m_Mode 1 = 계단)."""
    nc, na = max(1, g["m_NumColorKeys"]), max(1, g["m_NumAlphaKeys"])
    keys = [g[f"key{i}"] for i in range(8)]
    fixed = g.get("m_Mode") == 1
    rgb = _keys_at([g[f"ctime{i}"] / 65535 for i in range(nc)], [(keys[i]["r"], keys[i]["g"], keys[i]["b"]) for i in range(nc)],
                   t, fixed)
    a = _keys_at([g[f"atime{i}"] / 65535 for i in range(na)], [(keys[i]["a"],) for i in range(na)], t, fixed)
    return [*rgb, a[0]]


def mg(g: dict):
    """MinMaxGradient → [r,g,b,a] | {g: 표본} | {c: [작은, 큰]} | {g, g2} | {r: 표본 — 그 안에서 아무 색}."""
    st = g["minMaxState"]

    def col(c):
        return [_r(c[k]) for k in "rgba"]

    def samp(gr):
        return [[_r(v) for v in gradient_at(gr, i / N)] for i in range(N + 1)]

    if st == 0:
        return col(g["maxColor"])
    if st == 1:
        return {"g": samp(g["maxGradient"])}
    if st == 2:
        return {"c": [col(g["minColor"]), col(g["maxColor"])]}
    if st == 3:
        return {"g": samp(g["maxGradient"]), "g2": samp(g["minGradient"])}
    return {"r": samp(g["maxGradient"])}


def _v3(d) -> list[float]:
    return [_r(d["x"]), _r(d["y"]), _r(d["z"])]


def _trs(t) -> np.ndarray:
    """Transform 의 로컬 행렬 (Unity 값 그대로)."""
    x, y, z, w = t.m_LocalRotation.x, t.m_LocalRotation.y, t.m_LocalRotation.z, t.m_LocalRotation.w
    r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    s = t.m_LocalScale
    m = np.eye(4)
    m[:3, :3] = r * [s.x, s.y, s.z]
    p = t.m_LocalPosition
    m[:3, 3] = [p.x, p.y, p.z]
    return m


# ---------------------------------------------------------------- 파티클 시스템
def system(ps: dict, r: dict) -> dict:
    """ParticleSystem·Renderer typetree → 뷰어 시스템 값 (재질·메시·행렬은 부르는 쪽이 더한다).

      dur loop prewarm delay space(0 로컬·1 월드) scaling life speed size [size3] rot [rot3] flipRot color gravity max
      emit {rate, dist, bursts: [[시각, 개수, 횟수, 간격, 확률]]} | None   shape {…} | None
      vel {x,y,z, orb, off, radial, mod, world} · limit {mag | x,y,z, damp, world} · sizeOL {x[,y,z]} · rotOL {z[,x,y]}
      colorOL · uv {tiles, type, row, rowMode, frame, start, cycles} · custom [[성분…], [성분…]] · streams
      render {mode, align, len, vscale, max, min, pivot, flip, sort}
    """
    im = ps["InitialModule"]
    d = {"dur": _r(ps["lengthInSec"]), "loop": bool(ps["looping"]), "prewarm": bool(ps["prewarm"]),
         "delay": mm(ps["startDelay"]), "space": int(ps["moveWithTransform"]), "scaling": int(ps["scalingMode"]),
         "life": mm(im["startLifetime"]), "speed": mm(im["startSpeed"]), "size": mm(im["startSize"]),
         "rot": mm(im["startRotation"]), "flipRot": _r(im.get("randomizeRotationDirection", 0)),
         "color": mg(im["startColor"]), "gravity": mm(im["gravityModifier"]), "max": int(im["maxNumParticles"])}
    if im.get("size3D"):
        d["size3"] = [mm(im["startSize"]), mm(im["startSizeY"]), mm(im["startSizeZ"])]
    if im.get("rotation3D"):
        d["rot3"] = [mm(im["startRotationX"]), mm(im["startRotationY"]), mm(im["startRotation"])]
    em = ps["EmissionModule"]
    if em["enabled"]:
        bursts = [[_r(b["time"]), mm(b["countCurve"]), int(b["cycleCount"]), _r(b["repeatInterval"]), _r(b.get("probability", 1))]
                  for b in em["m_Bursts"][:em["m_BurstCount"]]]
        d["emit"] = {"rate": mm(em["rateOverTime"]), "dist": mm(em["rateOverDistance"]), "bursts": bursts}
    sh = ps["ShapeModule"]
    if sh["enabled"]:
        d["shape"] = {"type": int(sh["type"]), "r": _r(sh["radius"]["value"]), "thick": _r(sh["radiusThickness"]),
                      "arc": _r(sh["arc"]["value"]), "arcMode": int(sh["arc"]["mode"]), "angle": _r(sh["angle"]),
                      "len": _r(sh["length"]), "box": _v3(sh["boxThickness"]), "pos": _v3(sh["m_Position"]),
                      "rot": _v3(sh["m_Rotation"]), "scale": _v3(sh["m_Scale"]), "randDir": _r(sh["randomDirectionAmount"]),
                      "sphDir": _r(sh["sphericalDirectionAmount"]), "randPos": _r(sh["randomPositionAmount"]),
                      "donut": _r(sh["donutRadius"])}
    vm = ps["VelocityModule"]
    if vm["enabled"]:
        v = {"x": mm(vm["x"]), "y": mm(vm["y"]), "z": mm(vm["z"]), "radial": mm(vm["radial"]),
             "mod": mm(vm["speedModifier"]), "world": bool(vm["inWorldSpace"])}
        orb = [mm(vm[k]) for k in ("orbitalX", "orbitalY", "orbitalZ")]
        if not all(_zero(o) for o in orb):
            v["orb"] = orb
            v["off"] = [mm(vm[k]) for k in ("orbitalOffsetX", "orbitalOffsetY", "orbitalOffsetZ")]
        d["vel"] = v
    cv = ps["ClampVelocityModule"]
    if cv["enabled"]:
        lim = {"damp": _r(cv["dampen"]), "world": bool(cv["inWorldSpace"])}
        if cv["separateAxis"]:
            lim.update(x=mm(cv["x"]), y=mm(cv["y"]), z=mm(cv["z"]))
        else:
            lim["mag"] = mm(cv["magnitude"])
        d["limit"] = lim
    sz = ps["SizeModule"]
    if sz["enabled"]:
        d["sizeOL"] = {"x": mm(sz["curve"])}
        if sz["separateAxes"]:
            d["sizeOL"].update(y=mm(sz["y"]), z=mm(sz["z"]))
    rm = ps["RotationModule"]
    if rm["enabled"]:
        d["rotOL"] = {"z": mm(rm["curve"])}
        if rm["separateAxes"]:
            d["rotOL"].update(x=mm(rm["x"]), y=mm(rm["y"]))
    cm = ps["ColorModule"]
    if cm["enabled"]:
        d["colorOL"] = mg(cm["gradient"])
    uv = ps["UVModule"]
    if uv["enabled"] and uv["mode"] == 0:   # 격자 그림 (스프라이트 목록 방식은 안 쓴다)
        d["uv"] = {"tiles": [int(uv["tilesX"]), int(uv["tilesY"])], "type": int(uv["animationType"]),
                   "row": int(uv["rowIndex"]), "rowMode": int(uv.get("rowMode", 1)), "frame": mm(uv["frameOverTime"]),
                   "start": mm(uv["startFrame"]), "cycles": _r(uv["cycles"])}
    cd = ps["CustomDataModule"]
    if cd["enabled"]:
        custom = []
        for k in (0, 1):
            mode = cd[f"mode{k}"]
            if mode == 1:
                custom.append([mm(cd[f"vector{k}_{i}"]) for i in range(int(cd[f"vectorComponentCount{k}"]))])
            elif mode == 2:
                custom.append({"color": mg(cd[f"color{k}"])})
            else:
                custom.append([])
        d["custom"] = custom
    d["streams"] = list(r.get("m_VertexStreams") or []) if r.get("m_UseCustomVertexStreams") else []
    d["render"] = {"mode": int(r["m_RenderMode"]), "align": int(r["m_RenderAlignment"]), "len": _r(r["m_LengthScale"]),
                   "vscale": _r(r["m_VelocityScale"]), "max": _r(r["m_MaxParticleSize"]), "min": _r(r["m_MinParticleSize"]),
                   "pivot": _v3(r["m_Pivot"]), "flip": [_r(r["m_Flip"]["x"]), _r(r["m_Flip"]["y"])],
                   "sort": int(r["m_SortMode"])}
    return d


def _flat(a, k: int) -> list:
    return [_r(v) for v in np.asarray(a, np.float64).reshape(-1)[: len(a) * k]]


# ---------------------------------------------------------------- 꺼내기
class Effects:
    """의상 이펙트 꺼내기. 표(fx.json)는 처음 부를 때, 이펙트용 CAB 표는 처음 꺼낼 때 만든다.
    화면 호출은 여러 스레드에서 오므로 표·목차 준비와 꺼내기를 잠금 하나로 줄 세운다
    (예전엔 준비 중인 목차를 다른 스레드가 반쯤 보고 이펙트 없는 옷을 캐시에 남길 수 있었다)."""

    def __init__(self, game_dir: Path, data_dir: Path):
        self.gd = Path(game_dir)
        self.dir = Path(data_dir)
        self._lock = threading.RLock()
        self._table: dict | None = None
        self._res: gf.Resources | None = None
        self._tls: dict[str, str] = {}
        self._pack: A.AssetPack | None = None
        self._tex: T.TextureStore | None = None
        self._prefabs: dict[str, dict | None] = {}
        self._mats: dict[str, dict | None] = {}
        self._shaders: dict[tuple, str] = {}

    def table(self) -> dict:
        with self._lock:
            if self._table is None:
                t, _fresh = G.cached(self.dir / "fx.json", FORMAT, self.gd, table, what="드레스룸 이펙트 표", key="fx")
                self._table = t or {}
            return self._table

    def has(self, model: str) -> bool:
        return model in self.table()

    def _open_res(self) -> None:
        if self._res is None:
            self._res = gf.Resources(self.gd, lambda p: _TL in p, main=True)
            self._tls = {p.rsplit("/", 1)[-1][: -len(_TL_END)]: p for p in self._res.paths if p.endswith(_TL_END)}

    def _timeline(self, name: str) -> dict | None:
        self._open_res()
        p = self._tls.get(name)
        if p is None:
            return None
        d = sjon.load(self._res.read(p))
        return d if isinstance(d, dict) else None

    def timelines(self) -> dict[str, str]:
        """타임라인 이름 (소문자 → 이름) — 동작 표가 감정 표현과 잇는다."""
        with self._lock:
            self._open_res()
            return {k.lower(): k for k in self._tls}

    def useful(self, name: str) -> bool:
        """감정 표현에 그릴 것이 있는 타임라인인가 (몸에 붙는 Effect 구간 — timeline 이 꺼내는 것)."""
        with self._lock:
            tl = self._timeline(name)
        return any(pl for _iv, pl in _effects_on_self(tl))

    def timeline(self, name: str) -> dict | None:
        """감정 표현 타임라인 → 모델 json 의 fx 값 (구간 시각 begin·end·follow 를 더한 tracks, prefabs). 없으면 None."""
        with self._lock:
            tl = self._timeline(name)
            tracks, prefabs, index = [], [], {}
            for iv, pl in _effects_on_self(tl):
                i = self._prefab_index(_effect_path(pl), index, prefabs)
                if i is None:
                    continue
                tr = _track(pl, i, False)
                tr["begin"] = float(iv.get("BeginTime") or 0)
                tr["end"] = None if iv.get("IsInfinite") else float(iv.get("EndTime") or 0)
                tr["follow"] = ((pl.get("PositionAttachmentInfo") or {}).get("EffectAttachmentType") or "Attached") == "Attached"
                tracks.append(tr)
            return {"tracks": tracks, "overlays": [], "prefabs": prefabs} if tracks else None

    def _prefab_index(self, path: str, index: dict, prefabs: list) -> int | None:
        """FX prefab 경로 → prefabs 번호 (처음이면 꺼내 더한다, 못 꺼내면 None)."""
        if not path:
            return None
        if path not in index:
            pf = self.prefab(ASSET + path)
            index[path] = len(prefabs) if pf else None
            if pf:
                prefabs.append(pf)
        return index[path]

    def _assets(self) -> tuple[A.AssetPack, T.TextureStore]:
        if self._pack is None:
            pack = A.AssetPack(self.gd, self.dir / "fx", keep=keep)
            pack.cabs()
            self._tex = T.TextureStore(self.dir / "tex")
            self._pack = pack   # 다 준비한 뒤에 (None 이 아니면 준비 끝)
        return self._pack, self._tex

    def export(self, model: str) -> dict | None:
        """모델 이름 → json 의 fx 값. 이펙트가 없거나 하나도 못 꺼내면 None."""
        with self._lock:
            return self._export(model)

    def _export(self, model: str) -> dict | None:
        rows = self.table().get(model)
        if not rows:
            return None
        tracks, overlays, prefabs, index = [], [], [], {}
        for name, hood in rows:
            tl = self._timeline(name)
            if tl is None:
                log.warning(f"드레스룸 이펙트: 타임라인을 찾지 못했습니다 ({name})")
                continue
            for t in tl.get("Tracks") or []:
                if not t.get("IsEnabled", True):
                    continue
                for iv in t.get("Intervals") or []:
                    pl = iv.get("Playable") or {}
                    if t.get("Type") == "Effect":
                        i = self._prefab_index(_effect_path(pl), index, prefabs)
                        if i is not None:
                            tracks.append(_track(pl, i, hood))
                    elif t.get("Type") == "AdditiveRenderer" and pl.get("MaterialPath"):
                        mat = self.material(ASSET + pl["MaterialPath"])
                        # 그림 없는 기본 재질(FX_Alp)은 메시 정점 색으로 그리는 덧칠이라 뺀다 — 정점 색을 꺼내지 않는다
                        if mat and (mat["kind"] != "default" or "_MainTex" in mat["t"]):
                            overlays.append({"meshes": list(pl.get("TargetRendererNames") or []), "mat": mat, "hood": hood})
        if not tracks and not overlays:
            return None
        return {"tracks": tracks, "overlays": overlays, "prefabs": prefabs}

    # ── prefab ──
    def prefab(self, path: str) -> dict | None:
        if path in self._prefabs:
            return self._prefabs[path]
        pack, _ = self._assets()
        out = None
        before = T.retries()
        if path in pack.paths:
            gos = A.roots(pack.open([path], limit=80), path)
            if gos:
                systems: list = []
                meshes: dict = {}
                self._walk(gos[0], np.eye(4), systems, meshes, root=True)
                if systems:
                    out = {"name": gos[0].m_Name, "systems": systems, "meshes": list(meshes.values())}
        if out is None:
            log.warning(f"드레스룸 이펙트: prefab 을 꺼내지 못했습니다 ({path.rsplit('/', 1)[-1]})")
        if T.retries() == before:   # 환경 탓으로 일부를 뺀 결과는 기억하지 않는다 (다음 옷이 다시 꺼낸다)
            self._prefabs[path] = out
        return out

    def _walk(self, go, parent: np.ndarray, out: list, meshes: dict, root: bool = False) -> None:
        if not getattr(go, "m_IsActive", True):
            return
        comps = {}
        for o in A.components(go):
            comps.setdefault(o.type.name, o)
        tr = comps.get("Transform")
        if tr is None:
            return
        t = tr.read()
        m = parent if root else parent @ _trs(t)   # prefab 루트 자리는 소켓이 정한다
        ps, rd = comps.get("ParticleSystem"), comps.get("ParticleSystemRenderer")
        mf, mr = comps.get("MeshFilter"), comps.get("MeshRenderer")
        if (ps is not None and rd is not None) or (mf is not None and mr is not None):
            try:
                s = self._system(go, ps, rd, m, meshes) if ps is not None else self._static(go, mf, mr, m, meshes)
            except Exception as e:   # 한 시스템이 이상해도 나머지는 그린다
                T.problem(f"이펙트 시스템을 건너뜁니다 ({go.m_Name})", e)
                s = None
            if s:
                out.append(s)
        for ch in t.m_Children:
            try:
                self._walk(ch.deref().read().m_GameObject.deref().read(), m, out, meshes)
            except Exception:
                continue

    def _system(self, go, ps, rd, m: np.ndarray, meshes: dict) -> dict | None:
        """meshes: 메시 그리기 파티클의 메시 (경로 id → 값) — 시스템은 그 번호(mesh)를 든다."""
        r = rd.read_typetree()
        if not r.get("m_Enabled", True):
            return None
        rr = rd.read()
        mats = [p for p in rr.m_Materials if p is not None and p.m_PathID]
        if not mats:
            return None
        try:
            mat = self._material_obj(mats[0].deref().read())
        except Exception as e:
            T.problem("이펙트 재질을 읽지 못했습니다", e)
            return None
        d = system(ps.read_typetree(), r)
        d["name"] = go.m_Name
        d["m"] = [_r(v) for v in m.T.reshape(-1)]   # 열 우선 (three Matrix4.fromArray)
        d["mat"] = mat
        if d["render"]["mode"] == 4:
            key = (rr.m_Mesh.m_FileID, rr.m_Mesh.m_PathID) if rr.m_Mesh is not None else None
            if key not in meshes:
                mesh = self._mesh(rr.m_Mesh)
                if mesh is None:
                    return None
                meshes[key] = mesh
            d["mesh"] = list(meshes).index(key)
        return d

    def _static(self, go, mf, mr, m: np.ndarray, meshes: dict) -> dict | None:
        """prefab 안의 보통 메시(MeshRenderer) → 늘 떠 있는 입자 하나로 그리는 시스템 (뷰어는 따로 다루지 않는다).
        크기는 노드 행렬 m 이 든다 (입자 크기 1)."""
        r = mr.read_typetree()
        if not r.get("m_Enabled", True):
            return None
        mats = [p for p in mr.read().m_Materials if p is not None and p.m_PathID]
        if not mats:
            return None
        mat = self._material_obj(mats[0].deref().read())
        ptr = mf.read().m_Mesh
        key = (ptr.m_FileID, ptr.m_PathID) if ptr is not None else None
        if key not in meshes:
            mesh = self._mesh(ptr)
            if mesh is None:
                return None
            meshes[key] = mesh
        return {**STATIC, "name": go.m_Name, "m": [_r(v) for v in m.T.reshape(-1)], "mat": mat,
                "mesh": list(meshes).index(key)}

    def _mesh(self, ptr):
        """메시 그리기 파티클의 메시 → 기본 메시 이름 | {pos, nrm, uv, idx}. 못 읽으면 None."""
        if ptr is None or not ptr.m_PathID:
            return None
        if ptr.m_FileID and ptr.m_PathID in _BUILTIN:
            try:
                ptr.deref()
            except Exception:
                return _BUILTIN[ptr.m_PathID]
        try:
            md = ST.static_mesh(ptr.deref().read())
        except Exception as e:
            T.problem("이펙트 메시를 읽지 못했습니다", e)
            return None
        if md is None or md["uv"] is None:
            return None
        tris = [t for sub in md["tris"] for t in sub]
        return {"pos": _flat(md["pos"], 3), "nrm": _flat(md["nrm"], 3), "uv": _flat(md["uv"], 2),
                "idx": [int(i) for tri in tris for i in (tri if isinstance(tri, (list, tuple)) else [tri])]}

    # ── 재질 ──
    def material(self, path: str) -> dict | None:
        """재질 자산 경로 → 뷰어 재질 값 (덧그리기)."""
        if path in self._mats:
            return self._mats[path]
        pack, _ = self._assets()
        out = None
        before = T.retries()
        if path in pack.paths:
            try:
                got = A.objects(pack.open([path], limit=20), path, "Material")
                out = self._material_obj(got[0]) if got else None
            except Exception as e:
                T.problem(f"이펙트 재질을 읽지 못했습니다 ({path.rsplit('/', 1)[-1]})", e)
        if T.retries() == before:
            self._mats[path] = out
        return out

    def _shader(self, m) -> str:
        key = (m.m_Shader.m_FileID, m.m_Shader.m_PathID)
        if key not in self._shaders:
            try:
                self._shaders[key] = m.m_Shader.deref().read().m_ParsedForm.m_Name
            except Exception:
                self._shaders[key] = ""
        return self._shaders[key]

    def _material_obj(self, m) -> dict:
        """{name, kind, blend: [src, dst] (Unity BlendMode), cull (0 끔·1 앞·2 뒤), f, c, t: {칸: {tex, srgb, st}}}."""
        _, tex = self._assets()
        shader = self._shader(m).rsplit("/", 1)[-1]
        kind = _KIND.get(shader, "default")
        sp = m.m_SavedProperties
        floats = dict(sp.m_Floats) if getattr(sp, "m_Floats", None) else {}
        cols = dict(sp.m_Colors)
        envs = dict(sp.m_TexEnvs)
        if kind == "horn":
            blend, cull = [floats.get("_SrcBlend", 5), floats.get("_DstBlend", 10)], 2
        elif shader == _OPAQUE:   # 섞지 않고 덮어 그린다 (뷰어는 깊이도 쓴다)
            blend, cull = [1, 0], floats.get("_CullMode", 2)
        else:
            blend, cull = [floats.get("_BlendSrc", 5), floats.get("_BlendDst", 10)], floats.get("_CullMode", 0)
        t = {}
        for k in _MAPS:
            env = envs.get(k)
            name = tex.ref(env.m_Texture) if env is not None else None
            if name:
                t[k] = {"tex": name, "srgb": T.TextureStore.srgb(env.m_Texture),
                        "st": [_r(env.m_Scale.x), _r(env.m_Scale.y), _r(env.m_Offset.x), _r(env.m_Offset.y)]}
        return {"name": m.m_Name, "kind": kind, "blend": [int(blend[0]), int(blend[1])], "cull": int(cull),
                "f": {k: _r(floats[k]) for k in _FLOATS if k in floats},
                "c": {k: [_r(c.r), _r(c.g), _r(c.b), _r(c.a)] for k, c in cols.items() if k in _COLORS}, "t": t}


def _effect_path(pl: dict) -> str:
    """Effect 구간 → FX prefab 경로 (Assets/PatchableAssets/ 뺀 것, 없으면 '')."""
    return ((pl.get("PrefabPathGroups") or {}).get("Default") or {}).get("Lod0") or ""


def _effects_on_self(tl: dict | None):
    """타임라인 → 몸(Self)에 붙는 Effect 구간 (구간, Playable) — 소품(TimelineProp)에 붙는 것은 뺀다."""
    for t in (tl or {}).get("Tracks") or []:
        if not t.get("IsEnabled", True) or t.get("Type") != "Effect":
            continue
        for iv in t.get("Intervals") or []:
            pl = iv.get("Playable") or {}
            if _effect_path(pl) and (pl.get("PosRefActor") or "Self") == "Self":
                yield iv, pl


def _track(pl: dict, fx: int, hood: bool) -> dict:
    """타임라인 Effect 구간 → {fx, bone, rbone, off, rot, turn, hood}."""
    bone = pl.get("PosRefBoneName") or ""
    rbone = pl.get("RotRefBoneName") or bone
    rot_att = ((pl.get("RotationAttachmentInfo") or {}).get("EffectAttachmentType") or "Attached")
    return {"fx": fx, "bone": "" if bone == TL.ROOT else bone, "rbone": "" if rbone == TL.ROOT else rbone,
            "off": [_r(v) for v in (pl.get("LocalOffset") or [0, 0, 0])],
            "rot": euler_quat(pl.get("LocalRotation") or [0, 0, 0]), "turn": rot_att == "Attached", "hood": hood}


def bones(fx: dict | None) -> set[str]:
    """fx 값이 붙는 뼈 이름들."""
    return {b for t in (fx or {}).get("tracks", ()) for b in (t["bone"], t["rbone"]) if b}


def sockets(pack: A.AssetPack, prefab: str, names: set[str]) -> list[dict]:
    """옷 prefab 노드 중 이름이 names 에 든 것과 그 조상들 → 뼈대 노드 [{path, t, r, s}] (부모가 앞).
    fbx 로 꺼내는 옷은 이펙트 소켓 노드가 없어 prefab 에서 가져온다."""
    if not prefab or not names or prefab not in pack.paths:
        return []
    gos = A.roots(pack.open([prefab], limit=8), prefab)
    if not gos:
        return []
    nodes, _ = E.skeleton(gos[0])
    want: set[int] = set()
    for i, n in enumerate(nodes):
        if n["path"].rsplit("/", 1)[-1] in names:
            j = i
            while j >= 0 and j not in want:
                want.add(j)
                j = nodes[j]["parent"]
    return [{k: nodes[i][k] for k in ("path", "t", "r", "s")} for i in sorted(want)]
