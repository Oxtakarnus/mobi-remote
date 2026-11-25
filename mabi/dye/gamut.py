"""재질 팔레트로 '이 색을 스포이드로 집을 수 있나' 를 미리 판정한다.

미니게임 팔레트는 재질 그림(materials, 254×254)의 텍셀을 판마다 사각형째 맞바꿔 섞은 것이라
텍셀 색의 집합은 그대로다. 스포이드는 텍셀 사이를 섞어 집으므로 이웃 두 텍셀 사이 색도 나오지만
그 자리는 텍셀 경계 한 줄뿐이라 '경계뿐' 으로 따로 센다. 오차는 화면과 같게 RGB 칸마다 ± (detect.rgb_diff).

  넉넉   오차 안 텍셀 24개 이상          보통   6개 이상          좁음   1개 이상
  경계뿐 텍셀은 없고 이웃 사이 섞임만     없음   그 재질로는 안 나온다

화면 칸 재질 판정(material_of): 재질 섞인 옷은 팔레트가 스포이드 수만큼 세로로 갈라져 칸마다 그 재질 그림이
보인다. 그 칸 픽셀 중 '그 재질에만 있는 색' 비율이 가장 큰 재질로 본다 (천·금속은 색이 겹쳐서).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import materials
from .materials import NAMES

KOR = {"Cloth": "천", "Leather": "가죽", "Metal": "금속", "Wood": "나무"}
LEVELS = (("wide", 24), ("some", 6), ("narrow", 1))
LEVEL_KOR = {"wide": "넉넉", "some": "보통", "narrow": "좁음", "edge": "경계뿐", "none": "없음"}
_Q = 4          # 재질 판정용 색 칸 (256/4 = 64 칸씩)
_SURE = 0.02    # 그 재질에만 있는 색이 이만큼도 안 되면 모른다


@dataclass(frozen=True)
class Reach:
    mat: str      # Cloth · Leather · Metal · Wood
    level: str    # wide · some · narrow · edge · none
    count: int    # 오차 안 텍셀 수
    near: str     # 가장 가까운 텍셀 색 (#RRGGBB)
    diff: int     # 그 색과 차이 (칸마다 차이 중 큰 것)

    def to_dict(self) -> dict:
        return {"mat": self.mat, "name": KOR[self.mat], "level": self.level, "label": LEVEL_KOR[self.level],
                "count": self.count, "near": self.near, "diff": self.diff}


def _hex(c) -> str:
    return "#%02X%02X%02X" % tuple(int(v) for v in c)


def _texels(bgr: np.ndarray) -> np.ndarray:
    """(H, W, 3) BGR → (H, W, 3) RGB int16. 통째로 검은 가장자리 열·행은 화면에 안 그려져 뺀다 (Cloth 253열)."""
    rgb = bgr[..., ::-1].astype(np.int16)
    keep_c = ~np.all(rgb == 0, axis=(0, 2))
    keep_r = ~np.all(rgb == 0, axis=(1, 2))
    return rgb[keep_r][:, keep_c]


def _occupancy(rgb: np.ndarray) -> np.ndarray:
    """색 칸(64³) 중 이 재질 텍셀이 있는 칸, 이웃 한 칸까지 (화면은 텍셀 경계를 조금 섞어 그린다)."""
    g = np.zeros((64, 64, 64), bool)
    c = rgb.reshape(-1, 3) // _Q
    g[c[:, 0], c[:, 1], c[:, 2]] = True
    out = g.copy()
    for ax in range(3):
        out = out | np.roll(out, 1, ax) | np.roll(out, -1, ax)
    return out


class Gamut:
    def __init__(self, pals: dict[str, np.ndarray]):
        """pals: 재질 이름 → BGR 그림 (materials.load). 원본 그림은 맞출 자리 계산(autofit)도 쓴다."""
        self.pals = dict(pals)
        self.tex: dict[str, np.ndarray] = {}
        self.pairs: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        self.occ: dict[str, np.ndarray] = {}
        for m in NAMES:
            if m not in pals:
                continue
            t = _texels(pals[m])
            flat = t.reshape(-1, 3)
            self.tex[m] = flat   # 넓이를 세므로 겹친 색도 그대로
            # 이웃(오른쪽·아래, 감싸기) 사이 섞임 — 색이 다른 쌍만, 같은 쌍은 한 번만
            a = np.concatenate([t.reshape(-1, 3), t.reshape(-1, 3)])
            b = np.concatenate([np.roll(t, -1, 1).reshape(-1, 3), np.roll(t, -1, 0).reshape(-1, 3)])
            diff = np.any(a != b, axis=1)
            ab = np.unique(np.concatenate([a[diff], b[diff]], axis=1), axis=0)
            self.pairs[m] = (ab[:, :3], ab[:, 3:])
            self.occ[m] = _occupancy(flat)

    @property
    def mats(self) -> list[str]:
        return list(self.tex)

    def reach(self, rgb, tol: float, mat: str) -> Reach:
        t = np.asarray(rgb, np.int16)
        tex = self.tex[mat]
        d = np.abs(tex - t).max(axis=1)
        count = int((d <= tol).sum())
        i = int(np.argmin(d))
        near, diff = _hex(tex[i]), int(d[i])
        if count:
            level = next(name for name, k in LEVELS if count >= k)
        elif self._edge(t, tol, mat):
            level = "edge"
        else:
            level = "none"
        return Reach(mat, level, count, near, diff)

    def judge(self, rgb, tol: float) -> list[Reach]:
        return [self.reach(rgb, tol, m) for m in self.mats]

    def _edge(self, t: np.ndarray, tol: float, mat: str) -> bool:
        """이웃 두 텍셀 A·B 사이 A + s(B − A), s∈[0,1] 중 칸마다 |· − t| ≤ tol 인 s 가 있나."""
        a, b = self.pairs[mat]
        a = a.astype(np.float32)
        d = b.astype(np.float32) - a
        lo = np.zeros(len(a), np.float32)
        hi = np.ones(len(a), np.float32)
        for c in range(3):
            dc, ac = d[:, c], a[:, c]
            z = dc == 0
            with np.errstate(divide="ignore", invalid="ignore"):
                s1 = (t[c] - tol - ac) / dc
                s2 = (t[c] + tol - ac) / dc
            lo = np.where(z, np.where(np.abs(ac - t[c]) <= tol, lo, 2), np.maximum(lo, np.minimum(s1, s2)))
            hi = np.where(z, hi, np.minimum(hi, np.maximum(s1, s2)))
        return bool(np.any(lo <= hi))

    def material_of(self, rgb: np.ndarray) -> str | None:
        """화면 픽셀 (k, 3) RGB → 그 칸의 재질. 재질이 하나뿐이면 그것, 모르겠으면 None."""
        if len(self.occ) == 1:
            return next(iter(self.occ))
        px = np.asarray(rgb).reshape(-1, 3)
        if not len(px):
            return None
        q = (px // _Q).astype(np.intp)
        hit = np.stack([self.occ[m][q[:, 0], q[:, 1], q[:, 2]] for m in self.occ], -1)
        only = hit & (hit.sum(-1, keepdims=True) == 1)
        share = only.mean(0)
        k = int(share.argmax())
        return list(self.occ)[k] if share[k] >= _SURE else None


class GamutStore:
    """재질 복사본을 꺼내 Gamut 을 한 번 만들어 둔다 (처음 부를 때, 스레드 안전).
    못 만들었으면(게임 폴더 없음 등) RETRY 초 뒤에 다시 해 본다."""
    RETRY = 60

    def __init__(self, cache_dir: Path, game_dir=None):
        """game_dir: 게임 폴더를 돌려주는 함수 (기본 gamefiles.game_dir)."""
        self.cache_dir = Path(cache_dir)
        self._game_dir = game_dir
        self._lock = threading.Lock()
        self._g: Gamut | None = None
        self._tried = 0.0
        self._memo: dict = {}

    def get(self) -> Gamut | None:
        with self._lock:
            if self._g is None and (not self._tried or time.monotonic() - self._tried >= self.RETRY):
                self._tried = time.monotonic()
                self._g = self._build()
            return self._g

    def _build(self) -> Gamut | None:
        if self._game_dir is None:
            from ..gamefiles import game_dir
            gd = game_dir()
        else:
            gd = self._game_dir()
        try:
            pals = materials.load(self.cache_dir, gd)
        except Exception:   # 게임 패치로 목차 형식이 바뀌는 등 — 판정만 빠지고 도우미는 그대로 돈다
            return None
        return Gamut(pals) if pals else None

    def reach(self, rgb, tol: float, mat: str) -> Reach | None:
        """같은 (색, 오차, 재질)은 한 번만 센다."""
        g = self.get()
        if g is None or mat not in g.tex:
            return None
        key = (tuple(int(v) for v in rgb), float(tol), mat)
        r = self._memo.get(key)
        if r is None:
            if len(self._memo) > 512:
                self._memo.clear()
            r = self._memo[key] = g.reach(rgb, tol, mat)
        return r

    def judge(self, rgb, tol: float) -> list[Reach] | None:
        g = self.get()
        return None if g is None else [self.reach(rgb, tol, m) for m in g.mats]
