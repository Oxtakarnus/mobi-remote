"""염색 재질 그림 (Cloth·Leather·Metal·Wood, 254×254) — 게임 리소스의 DyeMaterialColorPalettes/*.bmp.

게임 폴더에서 읽기만 해서 꺼내 데이터 폴더에 png 복사본으로 둔다 (mabi.gamefiles). 게임 목차가 바뀌면 다시 꺼낸다.
게임 폴더를 못 찾으면 있던 복사본을 쓴다.
"""
from __future__ import annotations

import json
import zlib
from pathlib import Path

import cv2
import numpy as np

from .. import gamefiles as gf

NAMES = ("Cloth", "Leather", "Metal", "Wood")
TEX = 254
_DIR = "DyeMaterialColorPalettes/"


def _read_cache(files) -> dict[str, np.ndarray] | None:
    out = {}
    for n, f in files.items():
        img = cv2.imdecode(np.fromfile(f, np.uint8), cv2.IMREAD_COLOR) if f.exists() else None  # 한글 경로
        if img is None or img.shape[:2] != (TEX, TEX):
            return None
        out[n] = img
    return out


def _extract(root: Path) -> dict[str, np.ndarray] | None:
    res = gf.Resources(root, lambda p: _DIR in p)
    out = {}
    for n in NAMES:
        p = res.find(f"{_DIR}{n}.bmp")
        if not p:
            return None
        img = cv2.imdecode(np.frombuffer(res.read(p), np.uint8), cv2.IMREAD_COLOR)
        if img is None or img.shape[:2] != (TEX, TEX):
            return None
        out[n] = img
    return out


def load(cache_dir: Path, game_dir: Path | None) -> dict[str, np.ndarray] | None:
    """재질 이름 → 그림 (BGR, bmp 그대로 = 행 위부터). 꺼낼 수도 없고 복사본도 없으면 None."""
    cache_dir = Path(cache_dir)
    files = {n: cache_dir / f"{n}.png" for n in NAMES}
    meta = cache_dir / "materials.json"
    have = _read_cache(files)
    idx = gf.index_of(game_dir) if game_dir else None
    if idx is None or not idx.is_file():
        return have
    stamp = gf.stamp_of(idx)
    try:
        old = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else None
    except (OSError, ValueError):
        old = None
    if have and old == stamp:
        return have
    try:
        out = _extract(game_dir)
    except (OSError, ValueError, KeyError, IndexError, zlib.error):
        out = None
    if out is None:
        return have
    cache_dir.mkdir(parents=True, exist_ok=True)
    for n, img in out.items():
        cv2.imencode(".png", img)[1].tofile(files[n])
    meta.write_text(json.dumps(stamp), encoding="utf-8")
    return out

