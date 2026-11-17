"""내 캐릭터 외형 — 개인 데이터·내 등장 메시지에서 드레스룸에 넘길 요약만 뽑는다 (읽기만).

개인 데이터(char.personal_data, 접속·맵 이동마다 약 500KB)엔 친구·길드 같은 다른 정보도 들어 있어 본문은 들고 있지 않는다.
요약엔 캐릭터 이름·고유 번호를 넣지 않는다. 직렬화는 리틀엔디안 고정 크기, 목록은 [u32 개수] + 항목.

  외형 58바이트   [i16 성별 1 여·2 남][f32 키 -1..1][u32 몸 모델]
                  [u32 ×12 시트 id: 머리 그룹·눈 그룹·수염·얼굴형·입 그룹·얼굴 문신·몸 문신·체형·피부색·머리색·머리 장식색·눈동자색]
                  메시지 끝 쪽에 있다 — 뒤에서부터, 몸 모델이 아는 값 넷 중 하나인 자리를 찾는다 (수염·문신은 0 = 없음)
  입은 의상       [u32 n][n × (u32 의상 종류, 의상)] — 앞쪽 64KB 안에서 찾는다
                  의상 = [u64 고유 번호][u32 시트 id] … +29 색 있음 ×6 · +35 RGBA ×6 (크기 96 — 10-25 엔 95, 패치마다 맞춰 본다)
  보이기          의상 보관함 [u32 프리셋 수][u32 지금 프리셋][u32 n][n × (u64 고유 번호, 의상)][u32 보관 수]…
                  …[u32 k][k × (u64 고유 번호, u32 프리셋, u8 보이기)] — 입은 의상의 고유 번호로 찾는다
  나이            외형엔 없다. 내 등장 메시지의 앞머리 [u32 나이][i16 성별][f32 키][u32 몸 모델] 에서 읽는다

게임 11-05 패치 기준, 캡처(11-08) 12건으로 맞춰 봤다. 모양이 안 맞으면 그 부분만 비운다 (감시는 그대로).
"""
from __future__ import annotations

import logging
import struct
import threading
import time

log = logging.getLogger("mabi")

COSTUME_TYPE = {180: "EarDeco", 190: "EyeDeco", 200: "FaceDeco", 201: "Weapon", 202: "Hat", 203: "Bottom",
                204: "Top", 205: "Gloves", 206: "Shoes", 207: "Robe"}
GENDER = {1: "Female", 2: "Male"}
# 몸 모델 값 → 드레스룸 체형 (값은 모델 이름의 해시로 보이지만 못 풂 — 성별·나이와 같이 본 실측 짝)
BODY_MODEL = {0x0CD5CF74: "Female", 0xC7472698: "Male", 0x72666BA4: "Girl", 0xECD612F0: "Boy"}
FIELDS = ("hair", "eyes", "beard", "head", "mouth", "ftat", "btat", "shape", "skin", "hair_color", "hairacc_color",
          "eye_color")
_OPTIONAL = {"beard", "ftat", "btat", "hairacc_color"}   # 0 일 수 있는 칸
COSTUME_SIZES = (96, 95, *(x for x in range(88, 128) if x not in (95, 96)))   # 앞에서부터 맞춰 본다
SCAN = 64 * 1024                             # 입은 의상을 찾는 앞쪽 범위


def _hex(v: int) -> str:
    """RGBA 4바이트(u32 로 읽은 값) → '#RRGGBB'."""
    b = struct.pack("<I", v)
    return "#%02X%02X%02X" % (b[0], b[1], b[2])


# ---------------------------------------------------------------- 개인 데이터
def appearance(b: bytes) -> dict | None:
    """외형 58바이트 → {gender, body, height, model, sheet{…}}. 몸 모델 값마다 뒤에서부터 찾아 가장 뒤의 맞는 자리. 없으면 None."""
    def ok(o):
        g, h = struct.unpack_from("<hf", b, o)
        if g not in GENDER or not -1.0001 <= h <= 1.0001:
            return False
        vals = struct.unpack_from("<12I", b, o + 10)
        return all(v for k, v in zip(FIELDS, vals) if k not in _OPTIONAL)

    best = -1
    for model in BODY_MODEL:
        key = struct.pack("<I", model)
        i = b.rfind(key, 0, len(b) - 48)
        while i - 6 > max(best, 8):
            if ok(i - 6):
                best = i - 6
                break
            i = b.rfind(key, 0, i)
    if best < 0:
        return None
    g, h, model = struct.unpack_from("<hfI", b, best)
    return {"gender": GENDER[g], "body": BODY_MODEL[model], "height": max(-1.0, min(1.0, h)), "model": model,
            "sheet": dict(zip(FIELDS, struct.unpack_from("<12I", b, best + 10)))}


def _costume_ok(b: bytes, o: int, cs: int) -> bool:
    return o + cs <= len(b) and all(x <= 1 for x in b[o + 29:o + 35]) and struct.unpack_from("<I", b, o + 8)[0] != 0


def _costume(b: bytes, o: int) -> dict:
    uid, sheet = struct.unpack_from("<QI", b, o)
    cols = struct.unpack_from("<6I", b, o + 35)
    return {"uid": uid, "sheet": sheet, "colors": [_hex(c) if h else None for h, c in zip(b[o + 29:o + 35], cols)]}


def _slot_lists(b: bytes, cs: int):
    """[u32 n][n × (u32 의상 종류, 의상)] 로 읽히는 자리마다 (항목들) — 앞에서부터."""
    for p in range(8, min(len(b), SCAN) - 8 - cs):
        n = struct.unpack_from("<I", b, p)[0]
        if not 1 <= n <= 12:
            continue
        o, items = p + 4, []
        for _ in range(n):
            t = struct.unpack_from("<I", b, o)[0] if o + 4 <= len(b) else 0
            if t not in COSTUME_TYPE or not _costume_ok(b, o + 4, cs):
                break
            items.append((COSTUME_TYPE[t], _costume(b, o + 4)))
            o += 4 + cs
        else:
            yield items


def costumes(b: bytes) -> tuple[list[tuple[str, dict]], int] | None:
    """입은 의상 [(종류, 의상)] 과 의상 크기. 항목 셋 이상으로 맞는 첫 목록 (앞쪽에 장비 목록이 먼저 온다 —
    장비 슬롯 번호는 101~111 이라 의상 종류로 안 읽힌다). 입은 것이 둘 이하면 찾지 못할 수 있다."""
    for cs in COSTUME_SIZES:
        for items in _slot_lists(b, cs):
            if len(items) >= 3:
                return items, cs
    return None


def showing(b: bytes, uid: int, cs: int) -> dict[int, bool] | None:
    """의상 고유 번호 → 지금 프리셋에서 보이나. 의상 보관함을 찾지 못하거나 보관 칸이 차 있으면(항목 크기 미확인) None."""
    step = 8 + cs
    k = b.find(struct.pack("<QQ", uid, uid))   # 보관함 사전: 열쇠 = 안의 고유 번호
    if k < 12:
        return None
    while k - step >= 12 and b[k - step:k - step + 8] == b[k - step + 8:k - step + 16] and _costume_ok(b, k - step + 8, cs):
        k -= step
    n = struct.unpack_from("<I", b, k - 4)[0]
    current = struct.unpack_from("<I", b, k - 8)[0]
    o = k + n * step
    if o + 8 > len(b) or struct.unpack_from("<I", b, o)[0]:
        return None
    cnt = struct.unpack_from("<I", b, o + 4)[0]
    o += 8
    if cnt > 256 or o + cnt * 13 > len(b):
        return None
    out = {}
    for _ in range(cnt):
        cid, preset, show = struct.unpack_from("<QIB", b, o)
        if preset == current:
            out[cid] = bool(show)
        o += 13
    return out


def personal(b: bytes) -> dict | None:
    """개인 데이터 본문 → 요약 (외형을 못 찾으면 None). 의상은 못 찾으면 빈 목록."""
    ap = appearance(b)
    if ap is None:
        return None
    worn = costumes(b)
    items, cs = worn if worn else ([], 0)
    show = showing(b, items[0][1]["uid"], cs) if items else None
    ap["costumes"] = [{"type": t, "sheet": c["sheet"], "colors": c["colors"],
                       "show": show.get(c["uid"]) if show is not None else None} for t, c in items]
    return ap


# ---------------------------------------------------------------- 등장 메시지
def age(b: bytes, model: int, gender: str) -> int | None:
    """내 등장 메시지에서 나이 — [u32 나이][i16 성별][f32 키][u32 몸 모델] 인 첫 자리."""
    g = {v: k for k, v in GENDER.items()}[gender]
    key = struct.pack("<I", model)
    i = b.find(key, 10)
    while i >= 0:
        a, gg, h = struct.unpack_from("<Ihf", b, i - 10)
        if gg == g and 1 <= a <= 200 and -1.0001 <= h <= 1.0001:
            return a
        i = b.find(key, i + 1)
    return None


class MyLook:
    """마지막으로 본 내 캐릭터 외형. 캡처 스레드가 넣고(personal·appearing) 제어 통로가 읽는다(snapshot)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._look: dict | None = None
        self._char: int | None = None
        self._age: int | None = None
        self._warned = False

    def personal(self, body: bytes) -> None:
        why = "맞는 자리가 없음"
        try:
            look = personal(body)
            char = struct.unpack_from("<Q", body, 0)[0]
        except (struct.error, ValueError, IndexError) as e:
            look, char, why = None, None, f"{type(e).__name__}: {e}"
        if look is None:
            if not self._warned:   # 한 번만 — 맵을 옮길 때마다 온다
                self._warned = True
                log.info("패킷: 개인 데이터에서 내 캐릭터 외형을 못 읽음 (%s) — 게임 패치로 모양이 바뀐 듯", why)
            return
        look["at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            if char != self._char:
                self._age = None   # 다른 캐릭터 — 나이는 그 캐릭터가 맵에 나타나야 안다
            self._char, self._look = char, look

    def appearing(self, body: bytes) -> None:
        with self._lock:
            look = self._look
        if look is None:
            return
        try:
            a = age(body, look["model"], look["gender"])
        except (struct.error, ValueError) as e:
            log.debug("패킷: 내 등장 메시지에서 나이를 못 읽음 (%s)", e)
            return
        if a is not None:
            with self._lock:
                if self._look is look:
                    self._age = a

    def snapshot(self) -> dict | None:
        """{gender, body, height, age, sheet, costumes, at} — 아직 못 받았으면 None."""
        with self._lock:
            if self._look is None:
                return None
            d = {k: v for k, v in self._look.items() if k != "model"}
            d["sheet"] = dict(d["sheet"])
            d["costumes"] = [dict(c, colors=list(c["colors"])) for c in d["costumes"]]
            d["age"] = self._age
            return d
