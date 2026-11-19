"""게임 조작키 설정 읽기 — 사용자가 게임에서 바꾼 키를 리모콘 단축키(mabi.keys)가 따라가게 한다. 읽기만 한다.

게임은 바꾼 조작키만 PlayerPrefs 문자열 'CustomKeys' 에 둔다 (LocalLow devCAT\\마비노기 모바일).
  BaseMMPlayerPrefs.txt      'CustomKeys : <값>' — 게임을 끌 때 정리된 값
  ChangedMMPlayerPrefs.txt   '+1 : CustomKeys : <값>' / '-1 : CustomKeys' — 그 뒤 바뀐 것 (마지막 줄이 이긴다)
값은 '<판>' 뒤에 base64 — 풀면 XOR(열쇠 문자열 되풀이)이다 (게임 CustomControlKeyBindStorage, 열쇠·판은 game-rules).
푼 글은 '|' 로 동작마다 나뉘고 ',' 로 칸이 나뉜다:
  동작 번호(CustomControlKey 시트 행 id), 주 키, 보조 키, 게임패드, 누르고 있기
  키 칸은 'None'(안 바꿈) 또는 '개수,키…' (Unity KeyCode 번호 — 보조 키(Shift 등)가 앞, 본 키가 끝, 개수 0 = 키 없앰).
  2026-11-19 실측: 전체 화면 채팅 주 키를 F10 으로 → '104720118,1,291,None,None,0'.
모르는 판이거나 칸이 안 맞는 동작은 건너뛴다 (리모콘 기본값을 그대로 쓴다).
"""
from __future__ import annotations

import base64
import logging
import os
import time
from pathlib import Path

from . import gamedata
from .inputs import combo_name

log = logging.getLogger("mabi")

# Unity KeyCode 번호 → 리모콘 키 이름 (mabi.inputs). 없는 키(마우스·게임패드 등)는 리모콘이 누를 수 없다
UNITY_KEYS = {8: "backspace", 9: "tab", 13: "enter", 27: "esc", 32: "space", 39: "'", 44: ",", 45: "-", 46: ".",
              47: "/", 59: ";", 61: "=", 91: "[", 92: "\\", 93: "]", 96: "`", 127: "delete",
              273: "up", 274: "down", 275: "right", 276: "left", 277: "insert", 278: "home", 279: "end",
              280: "pageup", 281: "pagedown"}
UNITY_KEYS.update({48 + i: str(i) for i in range(10)})                  # Alpha0~9
UNITY_KEYS.update({97 + i: chr(97 + i) for i in range(26)})            # A~Z
UNITY_KEYS.update({256 + i: f"num{i}" for i in range(10)})             # Keypad0~9
UNITY_KEYS.update({282 + i: f"f{i + 1}" for i in range(12)})           # F1~F12
UNITY_MODS = {303: "shift", 304: "shift", 305: "ctrl", 306: "ctrl", 307: "alt", 308: "alt"}

SLOTS = 3  # 주 키 · 보조 키 · 게임패드


def rules() -> dict:
    return gamedata.rules()["keybind"]


def prefs_dir() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home()) / "AppData" / "LocalLow" / rules()["folder"]


def raw_value(folder: Path) -> str:
    """CustomKeys 원래 값 (없으면 빈 글자). 바뀐 기록이 있으면 그 마지막 줄."""
    key = rules()["prefsKey"]
    base, changed = rules()["files"]
    value = ""
    try:
        for line in (folder / base).read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith(key + " : "):
                value = line[len(key) + 3:]
    except OSError:
        pass
    try:
        for line in (folder / changed).read_text(encoding="utf-8", errors="replace").splitlines():
            head, _, rest = line.partition(" : ")
            name, _, v = rest.partition(" : ")
            if name == key or rest == key:
                value = v if head.startswith("+") else ""
    except OSError:
        pass
    return value.strip()


def decode(value: str) -> tuple[int, str] | None:
    """'<판>base64' → (판, 푼 글). 모양이 다르면 None."""
    if not value.startswith("<") or ">" not in value:
        return None
    ver, _, body = value[1:].partition(">")
    try:
        raw = base64.b64decode(body, validate=True)
        ver = int(ver)
    except ValueError:
        return None
    k = rules()["xor"].encode()
    try:
        return ver, bytes(b ^ k[i % len(k)] for i, b in enumerate(raw)).decode("utf-8")
    except UnicodeDecodeError:
        return None


def parse(text: str) -> dict[int, list[list[int] | None]]:
    """푼 글 → {동작 번호: [주 키, 보조 키, 게임패드]} (칸마다 None = 안 바꿈, [] = 키 없앰, [번호…])."""
    out = {}
    for item in filter(None, text.split("|")):
        t = item.split(",")
        try:
            aid, i, slots = int(t[0]), 1, []
            for _ in range(SLOTS):
                if t[i] == "None":
                    slots.append(None)
                    i += 1
                else:
                    n = int(t[i])
                    slots.append([int(x) for x in t[i + 1:i + 1 + n]])
                    if len(slots[-1]) != n:
                        raise ValueError
                    i += 1 + n
            if len(t) - i > 1:  # 남는 칸은 '누르고 있기' 하나뿐이어야 한다
                raise ValueError
        except (ValueError, IndexError):
            log.debug(f"게임 조작키: 모르는 모양 건너뜀 {item!r}")
            continue
        out[aid] = slots
    return out


def key_name(codes: list[int]) -> str | None:
    """Unity KeyCode 번호들 → 리모콘 키 이름 ('shift+esc'). 리모콘이 누를 수 없는 키면 None."""
    if not codes:
        return None
    *mods, main = codes
    if main not in UNITY_KEYS or any(m not in UNITY_MODS for m in mods):
        return None
    return combo_name([UNITY_MODS[m] for m in mods], UNITY_KEYS[main])


def bindings(text: str) -> dict[str, str]:
    """푼 글 → 리모콘 단축키 이름별로 게임에서 쓰는 키 (바꾼 동작만). 주 키를 먼저, 없으면 보조 키 (안 바꾼 칸은 게임 기본값)."""
    got = parse(text)
    out = {}
    for name, a in rules()["actions"].items():
        slots = got.get(a["id"])
        if slots is None:
            continue
        default = list(a["keys"]) + [None] * (2 - len(a["keys"]))
        for i in range(2):
            k = default[i] if slots[i] is None else key_name(slots[i])
            if k:
                out[name] = k
                break
    return out


class GameBinds:
    """게임 조작키를 읽어 둔다. 파일이 바뀌었을 때만 다시 읽는다 (보는 간격 CHECK 초)."""
    CHECK = 5.0

    def __init__(self, folder: Path | None = None):
        self.folder = folder
        self._stamp, self._seen, self._binds = None, 0.0, {}

    def _files_stamp(self):
        st = []
        for f in rules()["files"]:
            try:
                s = (self.folder / f).stat()
                st.append((s.st_mtime_ns, s.st_size))
            except OSError:
                st.append(None)
        return tuple(st)

    def current(self) -> dict[str, str]:
        if self.folder is None:
            return {}
        now = time.monotonic()
        if now - self._seen < self.CHECK:
            return self._binds
        self._seen = now
        stamp = self._files_stamp()
        if stamp == self._stamp:
            return self._binds
        self._stamp = stamp
        dec = decode(raw_value(self.folder))
        binds = {}
        if dec is not None:
            ver, text = dec
            if ver in rules()["versions"]:
                binds = bindings(text)
            else:
                log.warning(f"게임 조작키 저장 판 {ver} 을 모름 → 리모콘 기본 키를 씀")
        if binds != self._binds:
            if binds:
                log.info("게임 조작키를 따름: " + ", ".join(f"{n}={k.upper()}" for n, k in sorted(binds.items())))
            elif self._binds:
                log.info("게임 조작키가 기본값으로 돌아감 → 리모콘 기본 키")
        self._binds = binds
        return binds
