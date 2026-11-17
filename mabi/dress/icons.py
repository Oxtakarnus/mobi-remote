"""드레스룸 아이콘 — 시트 아이콘 경로(.asset) → 칠한 png 한 장 (게임 가방 아이콘과 같은 재료).

  Icons/ColoredIcon/…/<이름>_ColoredIcon.asset · Sprites/CustomizeIcon/…_ColoredIcon.asset   (AssetPackages)
    MonoBehaviour ColoredIcon 묶음: keys(크기 64·128·256), coloredIcons[크기마다] → Base · DyeMask_0 · DyeMask_1,
    references.RefIds[].data.path = 그림 경로 (PatchableAssets 기준). 그림마다 번들이 따로다 (CAB 표 필요 없음).
  칠하기: rgb = Base.rgb + Σ (DyeMask 채널 ÷ 그 마스크 최댓값) × 색, 알파 = Base.a
    색 칸 k 는 DyeMask_(k//3) 의 k%3 채널. 색은 시트 DyeColor, 없으면 .asset 의 baseIconPalettes,
    그것도 없으면(머리 아이콘) 중간 밤색. 게임의 그라데이션·오버레이 효과는 빼서 근사다.
  Icons/CommonIcon/Customize/<이름>.asset   (얼굴 문신·흉터·홍조)
    MonoBehaviour CommonIcon 묶음: keys, commonIcons[크기마다] → 그림 경로 하나 (칠하지 않는다).

한 번 꺼낸 아이콘은 데이터 폴더(dressroom\\icons\\)에 둔다 — service 가 관리한다.
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np

from ..fileio import save_image
from . import assets as A

PRE ="Assets/PatchableAssets/"
SIZE = 128
DEFAULT = (0x8A, 0x70, 0x60)   # 칠할 색이 없는 칸 (머리 아이콘의 머리색 칸 등)


def keep(p: str) -> bool:
    return "/Icons/ColoredIcon/" in p or "/Sprites/CustomizeIcon/" in p or "/Icons/CommonIcon/Customize/" in p


def pack(game_dir: Path) -> A.AssetPack:
    """아이콘 경로만 기억하는 AssetPackages 목차 (1초 남짓)."""
    return A.AssetPack(game_dir, Path("."), keep=keep)


def asset_path(icon: str) -> str:
    p = PRE + icon
    return p if p.endswith(".asset") else p + ".asset"


def _rgb(c) -> tuple[float, float, float] | None:
    if not c:
        return None
    if isinstance(c, str):
        h = c.lstrip("#")
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return float(c["r"]), float(c["g"]), float(c["b"])


def _parts(mono: dict, size: int) -> tuple[str | None, list[str | None]]:
    """ColoredIcon 묶음에서 size 에 맞는 (Base 경로, [DyeMask_0, DyeMask_1] 경로). 크기가 없으면 그보다 큰 것 중 작은 것.
    CommonIcon 묶음이면 (그림 경로, [])."""
    refs = {r["rid"]: r.get("data") or {} for r in (mono.get("references") or {}).get("RefIds", [])}
    keys = list(mono.get("keys") or [])
    icons = list(mono.get("coloredIcons") or mono.get("commonIcons") or [])
    if not keys or len(keys) != len(icons):
        return None, []
    order = sorted(range(len(keys)), key=lambda i: (keys[i] < size, abs(keys[i] - size)))
    ci = refs.get(icons[order[0]]["rid"], {})
    if "path" in ci:   # CommonIcon — 그림 하나
        return ci["path"], []

    def path(k):
        rid = (ci.get(k) or {}).get("rid", -2)
        return (refs.get(rid) or {}).get("path") if rid != -2 else None
    return path("Base"), [path("DyeMask_0"), path("DyeMask_1")]


def paint(base: np.ndarray, masks: list, colors: list) -> np.ndarray:
    """base·masks: RGBA uint8 배열 (같은 크기, mask 는 None 일 수 있다). colors: 칸 0..5 의 (r,g,b) 0~1 또는 None."""
    b = base.astype(np.float32) / 255
    rgb = b[..., :3].copy()
    for mi, m in enumerate(masks):
        if m is None:
            continue
        mf = m.astype(np.float32) / 255
        top = float(mf[..., :3].max())
        if top <= 1e-6:
            continue
        for ch in range(3):
            if not mf[..., ch].any():
                continue
            c = colors[mi * 3 + ch] if mi * 3 + ch < len(colors) else None
            c = c or tuple(v / 255 for v in DEFAULT)
            rgb += (mf[..., ch:ch + 1] / top) * np.asarray(c, np.float32)
    out = np.dstack([np.clip(rgb, 0, 1), b[..., 3:4]])
    return (out * 255 + 0.5).astype(np.uint8)


def _texture(pk: A.AssetPack, rel: str | None, size: int):
    """그림 경로 → RGBA 배열 (size×size). 목차에 없으면 None."""
    if not rel:
        return None
    b = pk.paths.get(PRE + rel)
    if b is None:
        return None
    import UnityPy
    from PIL import Image
    env = UnityPy.Environment()
    env.load_file(io.BytesIO(pk.read(b)))
    for o in env.objects:
        if o.type.name == "Texture2D":
            img = o.read().image.convert("RGBA")
            if img.size != (size, size):
                img = img.resize((size, size), Image.LANCZOS)
            return np.asarray(img)
    return None


def export(pk: A.AssetPack, icon: str, colors: list, out_png: Path, size: int = SIZE) -> bool:
    """아이콘 하나를 칠해 out_png 로. 목차에 없거나 그림이 없으면 False (파일을 만들지 않는다).
    colors: 시트 DyeColor 6칸 ('#RRGGBB' 또는 None)."""
    b = pk.paths.get(asset_path(icon)) if icon else None
    if b is None:
        return False
    import UnityPy
    from PIL import Image
    env = UnityPy.Environment()
    env.load_file(io.BytesIO(pk.read(b)))
    mono = next((o.read_typetree() for o in env.objects if o.type.name == "MonoBehaviour"), None)
    if not mono:
        return False
    base_p, mask_p = _parts(mono, size)
    base = _texture(pk, base_p, size)
    if base is None:
        return False
    masks = [_texture(pk, p, size) for p in mask_p]
    pal = {int(p.get("maskTextureChannelIndex", -1)): _rgb(p.get("color")) for p in mono.get("baseIconPalettes") or []}
    cols = [_rgb(colors[k] if k < len(colors or []) else None) or pal.get(k) for k in range(6)]
    save_image(out_png, Image.fromarray(paint(base, masks, cols), "RGBA"))
    return True
