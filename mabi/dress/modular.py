"""게임이 실행 중에 쓰는 메시 파일 (ResourcesPackage `StageObjectModels/ModelParts/<폴더>/`) — 읽기만 한다.

옷 prefab 의 SkinnedMeshRenderer 는 메시 칸이 비어 있고(게임이 실행 중에 채운다), 같은 이름의 fbx 가 없는
모델이 있다. 그런 모델은 여기 파일에서 메시를 읽어 export 가 fbx 메시 대신 쓴다.

  <모델>_<N>.SkinnedModularMesh.bytes   메시 하나 (옷·모자 등). 문자열은 u8 길이 + utf-8.
      이름 | u32 flags | u32 셰이프 수 | 셰이프 이름… | u32 정점 수
      | 정점마다: 위치 f32×3 · 법선 f32×3 · 16바이트 묶음 g 개 · u32 뼈 수 · (뼈 이름, 무게 f32)… · 16바이트 c 개
                  · 셰이프마다 위치 f32×3 · 셰이프마다 법선 f32×3
      | u32 삼각형 수 | (u32 서브메시, u32 정점 번호×3)… | u32 뼈 수 | (뼈 이름, 바인드포즈 f32×16 열 우선)…
      16바이트 묶음은 [f32 0, x, y, z] — 접선(x,y,z 단위 벡터, 있을 때 맨 앞) 다음에 UV 들(u, v, 0).
      g·c 는 flags 로 정해진다 (0x2·0x4·0x8·0x10 가 묶음 하나씩, 0x20·0x40 이 있으면 뒤 묶음 하나(정점 색),
      0x20 이 0x8·0x10 과 같이 있으면 앞 묶음 하나 더). 모르는 flags 는 파일이 딱 끝나는 배치를 찾는다.
      좌표는 Unity 위(y) 기준 — fbx 메시 좌표(z 위)로 (x, -z, y) 바꿔 쓴다.
  <모델>.meshes                          머리카락·일부 모자. 'MESHCOLL' | u32 1 | u32 n | u32 n | (오프셋, 크기)×n 머리
                                         | (오프셋, 크기)×n 데이터.
      머리 = 이름 | u32 정점 수 | u32 속성 수 | (속성, 형식, 차원, 스트림, 오프셋)×… (Unity VertexAttribute·Format 번호)
             | u32 스트림 수 | (보폭, 번호)… | u32 번호 총수 | u32 번호 형식 | u32 서브메시 수 | (시작, 개수, 조각 번호)… | u32 0
      데이터 = u32 조각 수 | (i32 -1, i32 -1, u32 크기, 바이트)… (정점 스트림들, 서브메시 번호 조각들)
             | u32 바인드포즈 수 | f32×16 열 우선… | 루트 뼈 (u16 길이 + 62바이트) | u32 뼈 수 | 뼈 이름 (u16 길이 + 62바이트)…
      좌표는 fbx 메시 좌표 그대로.

결과는 Part (fbx 메시에서 꺼낸 것과 같은 꼴 — 위치·법선·UV·서브메시별 삼각형·뼈 이름·바인드포즈(행 우선)·뼈 번호·무게·셰이프 차이).
"""
from __future__ import annotations

import re
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .. import gamefiles as gf
from .. import sjon
from . import textures as TX

ROOT = "StageObjectModels/ModelParts/"
_SMM = ".SkinnedModularMesh.bytes"
_COLL = ".meshes"
_SOM = ".StageObjectModel.sjon.bin"
_N = re.compile(r"_(\d+)$")

# Unity 메시 좌표(y 위) → fbx 메시 좌표(z 위)
_TO_FBX = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], np.float32)


class PartError(Exception):
    pass


@dataclass
class Part:
    name: str
    pos: np.ndarray                     # (n, 3) f32
    nrm: np.ndarray                     # (n, 3) f32
    uv: np.ndarray | None               # (n, 2) f32
    uv1: np.ndarray | None
    subs: dict[int, np.ndarray]         # 서브메시 번호 → 삼각형 정점 번호 (3k,) u32
    bones: list[str]                    # 뼈 이름 (경로 아님)
    bind: np.ndarray                    # (뼈 수, 16) f32, 행 우선
    idx: np.ndarray                     # (n, 4) u16
    w: np.ndarray                       # (n, 4) f32
    shapes: dict[str, np.ndarray] = field(default_factory=dict)   # 이름 → 위치 차이 (n, 3)


# ── SkinnedModularMesh ──
def _layout(flags: int) -> tuple[int, int]:
    g = bin(flags & 0x1E).count("1") + (1 if flags & 0x20 and flags & 0x18 else 0)
    return g, (1 if flags & 0x60 else 0)


class _Reader:
    def __init__(self, b: bytes):
        self.b, self.p = b, 0

    def u32(self) -> int:
        v = struct.unpack_from("<I", self.b, self.p)[0]
        self.p += 4
        return v

    def s(self) -> str:
        n = self.b[self.p]
        v = self.b[self.p + 1:self.p + 1 + n].decode("utf-8")
        self.p += 1 + n
        return v

    def f(self, n: int) -> tuple:
        v = struct.unpack_from("<%df" % n, self.b, self.p)
        self.p += 4 * n
        return v


def _smm_try(b: bytes, g: int, c: int):
    r = _Reader(b)
    name = r.s()
    r.u32()
    ns = r.u32()
    shape_names = [r.s() for _ in range(ns)]
    nv = r.u32()
    if nv > 200000:
        return None
    base = np.empty((nv, 6), np.float32)
    grp = np.empty((nv, g, 4), np.float32)
    weights: list[list[tuple[str, float]]] = []
    sp = np.empty((nv, ns, 3), np.float32)
    for i in range(nv):
        base[i] = r.f(6)
        if g:
            grp[i] = np.asarray(r.f(4 * g), np.float32).reshape(g, 4)
        nw = r.u32()
        if nw > 32:
            return None
        weights.append([(r.s(), r.f(1)[0]) for _ in range(nw)])
        r.p += 16 * c
        if ns:
            sp[i] = np.asarray(r.f(3 * ns), np.float32).reshape(ns, 3)
            r.p += 12 * ns
        if r.p > len(b):
            return None
    nt = r.u32()
    tris = np.frombuffer(b, "<u4", nt * 4, r.p).reshape(-1, 4) if nt else np.zeros((0, 4), np.uint32)
    r.p += 16 * nt
    nb = r.u32()
    bones = []
    binds = []
    for _ in range(nb):
        bones.append(r.s())
        binds.append(r.f(16))
    if r.p != len(b):
        return None
    return name, shape_names, base, grp, weights, sp, tris, bones, binds


def read_smm(b: bytes) -> Part:
    """SkinnedModularMesh 원문 → Part (fbx 메시 좌표)."""
    try:
        flags = struct.unpack_from("<I", b, 1 + b[0])[0]
    except (IndexError, struct.error) as e:
        raise PartError("메시 파일이 짧습니다") from e
    first = _layout(flags)
    tries = [first] + [(g, c) for g in range(7) for c in range(3) if (g, c) != first]
    got = None
    for g, c in tries:
        try:
            got = _smm_try(b, g, c)
        except (IndexError, struct.error, UnicodeDecodeError, ValueError):
            got = None
        if got is not None:
            break
    if got is None:
        raise PartError(f"메시 파일 형식을 모릅니다 (flags {flags:#x})")
    name, shape_names, base, grp, weights, sp, tris, bones, binds = got
    g = grp.shape[1]
    pos = base[:, :3] @ _TO_FBX.T
    nrm = base[:, 3:] @ _TO_FBX.T
    # 접선 묶음은 z 칸(4번째)이 0 이 아닌 정점이 있고, UV 묶음은 늘 0 이다
    start = 1 if g and np.any(np.abs(grp[:, 0, 3]) > 1e-6) else 0
    uvs = [grp[:, k, 1:3].copy() for k in range(start, g)]
    index = {nm: k for k, nm in enumerate(bones)}
    idx = np.zeros((len(base), 4), np.uint16)
    w = np.zeros((len(base), 4), np.float32)
    for i, ws in enumerate(weights):
        ws = sorted(((wt, index[nm]) for nm, wt in ws if nm in index), reverse=True)[:4]
        tot = sum(wt for wt, _ in ws)
        for k, (wt, bi) in enumerate(ws):
            idx[i, k] = bi
            w[i, k] = wt / tot if tot > 0 else 0.0
    m4 = np.eye(4, dtype=np.float32)
    m4[:3, :3] = _TO_FBX
    bind = np.array([np.asarray(m, np.float32).reshape(4, 4).T @ m4.T for m in binds], np.float32).reshape(-1, 16) \
        if binds else np.zeros((0, 16), np.float32)
    subs: dict[int, list] = {}
    for t in tris:
        subs.setdefault(int(t[0]), []).append(t[1:])
    shapes = {}
    for k, nm in enumerate(shape_names):
        d = sp[:, k, :] @ _TO_FBX.T - pos
        if np.any(np.abs(d) > 1e-7):
            shapes[nm] = d.astype(np.float32)
    return Part(name, pos.astype(np.float32), nrm.astype(np.float32), uvs[0] if uvs else None,
                uvs[1] if len(uvs) > 1 else None,
                {k: np.asarray(v, np.uint32).reshape(-1) for k, v in subs.items()},
                bones, bind, idx, w, shapes)


# ── MESHCOLL (.meshes) ──
_FMT = {0: ("<f4", False), 1: ("<f2", False), 2: ("u1", 255.0), 3: ("i1", 127.0), 4: ("<u2", 65535.0),
        5: ("<i2", 32767.0), 6: ("u1", None), 7: ("i1", None), 8: ("<u2", None), 9: ("<i2", None),
        10: ("<u4", None), 11: ("<i4", None)}


def _fixed(b: bytes, p: int) -> str:
    n = struct.unpack_from("<H", b, p)[0]
    return b[p + 2:p + 2 + n].decode("utf-8")


def read_meshes(b: bytes) -> list[Part]:
    """MESHCOLL 원문 → Part 목록 (fbx 메시 좌표 그대로)."""
    if b[:8] != b"MESHCOLL":
        raise PartError("메시 묶음 파일이 아닙니다")
    _ver, n1, n2 = struct.unpack_from("<III", b, 8)
    heads = [struct.unpack_from("<II", b, 20 + 8 * i) for i in range(n1)]
    datas = [struct.unpack_from("<II", b, 20 + 8 * n1 + 8 * i) for i in range(n2)]
    out = []
    for (ho, hs), (do, ds) in zip(heads, datas):
        out.append(_coll_part(b[ho:ho + hs], b[do:do + ds]))
    return out


def _coll_part(h: bytes, d: bytes) -> Part:
    ln = h[0]
    name = h[1:1 + ln].decode("utf-8")
    v = struct.unpack_from("<%dI" % ((len(h) - 1 - ln) // 4), h, 1 + ln)
    nv, na = v[0], v[1]
    attrs = [v[2 + 5 * i:7 + 5 * i] for i in range(na)]
    q = 2 + 5 * na
    nst = v[q]
    q += 1 + 2 * nst
    _total, ifmt, nsub = v[q], v[q + 1], v[q + 2]
    q += 3
    subs_h = [v[q + 3 * i:q + 3 * i + 3] for i in range(nsub)]
    # 데이터 조각
    nch = struct.unpack_from("<I", d, 0)[0]
    p = 4
    chunks = []
    for _ in range(nch):
        sz = struct.unpack_from("<I", d, p + 8)[0]
        chunks.append(d[p + 12:p + 12 + sz])
        p += 12 + sz
    nbind = struct.unpack_from("<I", d, p)[0]
    p += 4
    binds = np.frombuffer(d, "<f4", 16 * nbind, p).reshape(-1, 4, 4).transpose(0, 2, 1).reshape(-1, 16)
    p += 64 * nbind + 64          # 루트 뼈 이름은 안 쓴다
    nb = struct.unpack_from("<I", d, p)[0]
    p += 4
    bones = [_fixed(d, p + 64 * i) for i in range(nb)]

    def attr(code):
        for a, fmt, dim, st, off in attrs:
            if a != code:
                continue
            dt, norm = _FMT[fmt]
            buf = chunks[st]
            stride = len(buf) // nv if nv else 0
            raw = np.frombuffer(buf, np.uint8).reshape(nv, stride)[:, off:off + dim * np.dtype(dt).itemsize]
            arr = np.ascontiguousarray(raw).view(dt).reshape(nv, dim).astype(np.float32)
            if norm:
                arr /= norm
            return arr
        return None

    pos = attr(0)
    if pos is None:
        raise PartError(f"위치가 없는 메시: {name}")
    nrm = attr(1)
    uv = attr(4)
    uv1 = attr(5)
    wt = attr(12)
    bi = attr(13)
    n = len(pos)
    idx = np.zeros((n, 4), np.uint16)
    w = np.zeros((n, 4), np.float32)
    if bi is not None:
        k = min(4, bi.shape[1])
        idx[:, :k] = bi[:, :k].astype(np.uint16)
        if wt is not None:
            w[:, :min(4, wt.shape[1])] = wt[:, :4]
        else:
            w[:, 0] = 1.0
    idt = "<u2" if ifmt in (8, 0) else "<u4"
    subs = {}
    for si, (start, count, ch) in enumerate(subs_h):
        subs[si] = np.frombuffer(chunks[ch], idt, count).astype(np.uint32)
    return Part(name, pos[:, :3], nrm[:, :3] if nrm is not None else np.zeros((n, 3), np.float32),
                uv[:, :2] if uv is not None else None, uv1[:, :2] if uv1 is not None else None,
                subs, bones, binds.astype(np.float32), idx, w)


# ── 목차 ──
class Library:
    """ResourcesPackage 두 목차(본·Starter)에서 ModelParts 의 메시 파일·모델 정의만 기억한다 (0.5초 남짓).

    has(모델) — 게임이 실행 중에 쓰는 모델인가 (모델 정의 StageObjectModel 이나 메시 파일이 있다).
                fbx 없이 prefab 만 있는 모델 가운데 이게 거짓이면 게임에도 자료가 없다.
    parts(모델) — {메시 이름: Part}.
    som(모델) — 모델 정의(StageObjectModel, SJON) 를 푼 dict (없거나 못 읽으면 None, 한 번 읽으면 기억한다)."""

    def __init__(self, game_dir: Path):
        root = Path(game_dir) / "ResourcesPackage"

        def want(p):
            return p.startswith(ROOT) and p.endswith((_SMM, _COLL, _SOM))

        self._root = root
        self.paths: dict[str, tuple[int, int]] = {}
        for idx in (root / "index", root / "Starter" / "index"):
            if idx.is_file():
                self.paths.update(gf.parse_index(idx.read_bytes(), want))
        self._by: dict[str, list[str]] = {}
        self._som: dict[str, str] = {}      # 모델 → 모델 정의 경로
        self._som_cache: dict[str, dict | None] = {}
        for p in list(self.paths):
            base = p.rsplit("/", 1)[-1]
            if base.endswith(_SOM):
                self._som.setdefault(base[:-len(_SOM)], p)
                continue
            if base.endswith(_COLL):
                model = base[:-len(_COLL)]
            else:
                stem = base[:-len(_SMM)]
                m = _N.search(stem)
                if not m:
                    continue
                model = stem[:m.start()]
            self._by.setdefault(model, []).append(p)

    def has(self, model: str) -> bool:
        return model in self._by or model in self._som

    def som(self, model: str) -> dict | None:
        if model not in self._som_cache:
            p = self._som.get(model)
            d = None
            if p:
                try:
                    d = sjon.load(self.read(p))
                except OSError as e:   # 디스크·권한 — 기억하지 않고 이 모델을 반쪽으로 (다음에 다시 읽는다)
                    TX.problem(f"모델 정의를 읽지 못했습니다 ({model})", e)
                    return None
                except (sjon.SjonError, KeyError, ValueError, IndexError, struct.error, zlib.error):
                    d = None
            self._som_cache[model] = d if isinstance(d, dict) else None
        return self._som_cache[model]

    def read(self, path: str) -> bytes:
        bk, ix = self.paths[path]
        base = self._root / "Starter" if bk & 0x8000 else self._root
        return gf._entry(base / f"{bk & 0x7FFF:04d}.blob", ix - 1)

    def parts(self, model: str) -> dict[str, Part]:
        out: dict[str, Part] = {}
        files = sorted(self._by.get(model, ()), key=lambda p: (not p.endswith(_SMM), p))
        for p in files:   # SkinnedModularMesh 먼저, 없는 이름만 .meshes 에서
            try:
                b = self.read(p)
                got = [read_smm(b)] if p.endswith(_SMM) else read_meshes(b)
            except OSError as e:   # 디스크·권한 — 이 모델을 반쪽으로 표시해 다음에 다시 꺼낸다
                TX.problem(f"실행용 메시를 읽지 못했습니다 ({p.rsplit('/', 1)[-1]})", e)
                continue
            except (PartError, ValueError, IndexError, struct.error, zlib.error):
                continue      # 한 파일이 깨져도 나머지 메시는 쓴다
            for part in got:
                out.setdefault(part.name, part)
        return out
