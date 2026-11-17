"""게임 동작 클립(AnimationClip, Generic) → 뷰어가 읽는 뼈 트랙 (json + bin).

  <id>.json  {"fps", "frames", "duration", "tracks": [{"path", "kind": p·r·s, "off", "n"}]}
  <id>.bin   트랙마다 f32 × n × (3|4)   (n 은 frames, 값이 안 바뀌는 트랙은 1)

클립 자료 (Unity Mecanim, 확인한 것):
  m_ClipBindingConstant.genericBindings  커브 묶음마다 path(뼈 경로 CRC32)·attribute(1 위치 · 2 회전 · 3 크기 · 4 오일러)
                                         — 위치·크기·오일러는 커브 3개, 회전(쿼터니언)은 4개를 차례로 쓴다
                                         오일러는 X → Y → Z 순서로 돈다 (Unity 기본 Z → X → Y 가 아니다 — 아래 _euler_to_quat)
  m_MuscleClip.m_Clip.data               커브 번호 순서대로 Streamed → Dense → Constant
    Streamed  u32 배열을 풀면 프레임(시간 f32, 키 수 i32, 키마다 커브 번호 i32·계수 f32×4) 반복.
              키 뒤 구간 값 = ((c0·dt + c1)·dt + c2)·dt + c3. 맨 앞·뒤 프레임은 ±무한 시간(기울기용) — 뺀다.
    Dense     m_SampleArray = 프레임 × 커브 (m_SampleRate, m_BeginTime 부터)
    Constant  커브마다 값 하나
뼈 경로는 클립 fbx 에 같이 든 뼈대(GameObject)에서 모든 경로의 CRC32 를 만들어 맞춘다.

표정 클립(<동작>_Facial)은 같은 방식의 뼈 동작이다 — 눈썹·눈·볼·턱·입술 뼈. 몸통 뼈 값도 들어 있어
머리 아래 뼈만 남긴다 (face_only). 몸 동작과 같이 틀면 얼굴만 표정을 따른다.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np

from ..fileio import write_atomic, write_json
from . import assets as A
from .export import ExportError, skeleton

FPS = 30
FACE = "/_Head/"   # 표정 클립에서 남길 뼈 — 머리 아래 (눈썹·눈·볼·턱·입술)
_KIND = {1: ("p", 3), 2: ("r", 4), 3: ("s", 3), 4: ("e", 3)}


def _width(b) -> int:
    if b.typeID == 4:   # Transform
        return _KIND.get(b.attribute, ("", 1))[1]
    return 1


def streamed_keys(words) -> dict[int, list[tuple[float, tuple]]]:
    """Streamed 자료 → 커브 번호 → [(시간, 계수 4)] (유한한 시간만)."""
    buf = np.asarray(words, "<u4").tobytes()
    out: dict[int, list] = {}
    p = 0
    while p + 8 <= len(buf):
        t, nk = struct.unpack_from("<fi", buf, p)
        p += 8
        for _ in range(nk):
            idx, c0, c1, c2, c3 = struct.unpack_from("<i4f", buf, p)
            p += 20
            if np.isfinite(t):
                out.setdefault(idx, []).append((t, (c0, c1, c2, c3)))
    return out


def _sample_streamed(keys, times: np.ndarray) -> np.ndarray:
    kt = np.array([k[0] for k in keys], np.float64)
    kc = np.array([k[1] for k in keys], np.float64)
    i = np.clip(np.searchsorted(kt, times, side="right") - 1, 0, len(kt) - 1)
    dt = np.maximum(times - kt[i], 0.0)
    c = kc[i]
    return ((c[:, 0] * dt + c[:, 1]) * dt + c[:, 2]) * dt + c[:, 3]


def face_only(path: str) -> bool:
    return FACE in path


def decode(clip, paths: dict[int, str], fps: int = FPS, keep=None) -> tuple[dict, bytes]:
    """AnimationClip → (json 메타, bin). paths: CRC32 → 뼈 경로. keep: 뼈 경로 → 남길까 (없으면 다)."""
    mc = clip.m_MuscleClip
    data = mc.m_Clip.data
    start, stop = float(mc.m_StartTime), float(mc.m_StopTime)
    frames = max(1, int(round((stop - start) * fps)) + 1)
    times = np.minimum(start + np.arange(frames) / fps, stop)
    gb = list(clip.m_ClipBindingConstant.genericBindings)
    ncurve = sum(_width(b) for b in gb)
    vals = np.zeros((frames, ncurve), np.float32)

    sc = data.m_StreamedClip
    ns = int(sc.curveCount)
    for idx, keys in streamed_keys(sc.data).items():
        if 0 <= idx < ns:
            vals[:, idx] = _sample_streamed(keys, times)
    dc = data.m_DenseClip
    nd = int(dc.m_CurveCount)
    if nd and dc.m_FrameCount:
        arr = np.asarray(dc.m_SampleArray, np.float32).reshape(int(dc.m_FrameCount), nd)
        f = np.clip((times - float(dc.m_BeginTime)) * float(dc.m_SampleRate), 0, len(arr) - 1)
        lo = np.floor(f).astype(int)
        hi = np.minimum(lo + 1, len(arr) - 1)
        w = (f - lo)[:, None]
        vals[:, ns:ns + nd] = arr[lo] * (1 - w) + arr[hi] * w
    const = np.asarray(data.m_ConstantClip.data, np.float32)
    vals[:, ns + nd:ns + nd + len(const)] = const[None, :ncurve - ns - nd]

    tracks, buf = [], bytearray()
    at = 0
    for b in gb:
        k = _width(b)
        cur, at = at, at + k
        if b.typeID != 4 or b.attribute not in _KIND or b.path not in paths:
            continue
        if keep is not None and not keep(paths[b.path]):
            continue
        kind = _KIND[b.attribute][0]
        v = vals[:, cur:cur + k]
        if kind == "e":   # 오일러(도) → 쿼터니언 (X → Y → Z)
            v = _euler_to_quat(v)
            kind = "r"
        if np.all(np.abs(v - v[0]) < 1e-6):
            v = v[:1]
        while len(buf) % 4:
            buf.append(0)
        tracks.append({"path": paths[b.path], "kind": kind, "off": len(buf), "n": int(len(v))})
        buf += np.ascontiguousarray(v, np.float32).tobytes()
    meta = {"fps": fps, "frames": frames, "duration": stop - start, "tracks": tracks}
    return meta, bytes(buf)


def _qmul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """(x, y, z, w) 쿼터니언 곱 a·b."""
    ax, ay, az, aw = a.T
    bx, by, bz, bw = b.T
    return np.stack([aw * bx + ax * bw + ay * bz - az * by,
                     aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw,
                     aw * bw - ax * bx - ay * by - az * bz], 1)


def _euler_to_quat(e: np.ndarray) -> np.ndarray:
    """동작 클립 오일러 커브(도) → 쿼터니언. X 다음 Y 다음 Z 로 돈다 (q = qz·qy·qx).
    클립의 오일러 커브는 모델링 도구의 회전 순서를 그대로 지닌다 — Unity 기본(Z → X → Y)으로 풀면 Y 가 ±90° 근처인
    뼈가 프레임마다 180° 가까이 뒤집힌다 (레트로댄스 골반: (-90, 90, 0) → (0, 90, 90) 은 XYZ 로는 같은 자세).
    2026-11-17 오일러 커브가 든 클립 35개를 순서 여섯 가지로 풀어 프레임 사이 각 변화를 비교 — 34개가 XYZ 에서
    가장 매끈했고 나머지 하나는 XYZ·ZXY 가 비슷했다. 바인딩의 customType 은 늘 0 이라 순서를 따로 적어 두지 않는다."""
    h = np.radians(np.asarray(e, np.float64)) / 2
    z0 = np.zeros(len(h))

    def axis(i):
        v = [z0, z0, z0, np.cos(h[:, i])]
        v[i] = np.sin(h[:, i])
        return np.stack(v, 1)
    return _qmul(_qmul(axis(2), axis(1)), axis(0)).astype(np.float32)


def pick_clip(clips: list, stem: str):
    """묶음(CAB) 안 클립들 → 파일 줄기 stem 의 클립. 한 묶음에 다른 파일의 클립이 여럿 들어 있어 첫 클립이 그 파일 것이 아닐 수 있다.
    같은 이름 → 대소문자만 다른 이름(Followme·FollowMe) → 하나뿐이면 그것(SnowSpray → SnowSpray_Loop)
    → 한 파일에 시작·반복이 함께 든 것 중 반복(<이름>_Loop[_Facial]) · 시작. 없으면 None."""
    by = {c.m_Name: c for c in clips}
    if stem in by:
        return by[stem]
    low = {n.lower(): c for n, c in by.items()}
    if stem.lower() in low:
        return low[stem.lower()]
    if len(clips) == 1:
        return clips[0]
    base, tail = (stem[:-7], "_Facial") if stem.endswith("_Facial") else (stem, "")
    for phase in ("_Loop", "_Start"):
        c = low.get((base + phase + tail).lower())
        if c is not None:
            return c
    return None


def export(pack: A.AssetPack, fbx: str, out_json: Path, keep=None, face: dict | None = None) -> dict:
    """동작 fbx → 클립 json + bin. keep: 남길 뼈 경로 거르기 (표정 짝은 face_only).
    face: 표정 키 (xaf.convert — 표정 짝만) — 있으면 meta["face"] 에 넣고, 뼈 트랙이 없어도 낸다."""
    env = pack.open([fbx])
    name = fbx.rsplit("/", 1)[-1]
    clip = pick_clip([o.read() for o in env.objects if o.type.name == "AnimationClip"], name.rsplit(".", 1)[0])
    if clip is None:
        raise ExportError(f"동작을 찾지 못했습니다: {name}")
    paths: dict[int, str] = {}
    for root in A.roots(env, fbx):
        for n in skeleton(root)[0]:
            paths[zlib.crc32(n["path"].encode("utf-8"))] = n["path"]
    meta, data = decode(clip, paths, keep=keep)
    if face:
        meta["face"] = face
    elif not meta["tracks"]:
        raise ExportError(f"동작의 뼈 경로를 맞추지 못했습니다: {fbx.rsplit('/', 1)[-1]}")
    out_json = Path(out_json)
    write_atomic(out_json.with_suffix(".bin"), data)
    meta["bin"] = out_json.with_suffix(".bin").name
    write_json(out_json, meta)
    return meta
