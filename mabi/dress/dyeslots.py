"""염색 칸 배선 — 모델 정의(StageObjectModel)의 DyeInfo → 재질 채널마다 받는 의상 색 칸.

  DyeInfo.Slots[] = {Slot: "Slot<k>", Wirings: [{MeshIndex, MaterialIndex, ChannelIndex}]}
      k 는 의상 색 칸(0~5), MeshIndex 는 SkinnedMeshList 순서, MaterialIndex 는 그 메시의 재질 칸,
      ChannelIndex 는 재질의 염색 채널 0~2 (_DyeColor1~3)
  칸 0~2 가 채널 0~2 로 가는 옷이 대부분이지만, 두 번째 재질이 칸 3~5 를 받거나(상의의 6색)
  칸이 섞이거나(0·4·5) 한 채널만 받는 재질도 많다. 배선이 없는 채널은 염색되지 않는다 (재질 기본색).
  Skin·Hair 같은 이름 칸은 여기서 다루지 않는다 (피부·머리색은 따로 칠한다).
"""
from __future__ import annotations

import re

_SLOT = re.compile(r"Slot(\d)$")
CHANNELS = 3


def wiring(som: dict | None) -> dict[tuple[str, int], list[int | None]] | None:
    """모델 정의 → {(메시 이름, 재질 칸): [채널 0~2 가 받는 칸 | None]}. 번호 칸이 하나도 없으면 None."""
    if not isinstance(som, dict):
        return None
    meshes = [m.get("MeshName") if isinstance(m, dict) else None for m in som.get("SkinnedMeshList") or []]
    slots = (som.get("DyeInfo") or {}).get("Slots") if isinstance(som.get("DyeInfo"), dict) else None
    out: dict[tuple[str, int], list[int | None]] = {}
    seen = False
    for s in slots or []:
        m = _SLOT.match(str(s.get("Slot", ""))) if isinstance(s, dict) else None
        if not m:
            continue
        seen = True
        k = int(m.group(1))
        for w in s.get("Wirings") or []:
            try:
                mi, ma, ch = int(w["MeshIndex"]), int(w["MaterialIndex"]), int(w["ChannelIndex"])
            except (KeyError, TypeError, ValueError):
                continue
            if not 0 <= mi < len(meshes) or not meshes[mi] or not 0 <= ch < CHANNELS:
                continue
            out.setdefault((meshes[mi], ma), [None] * CHANNELS)[ch] = k
    return out if seen else None
