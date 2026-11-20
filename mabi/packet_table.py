"""게임 패킷 상태 표 (리소스 data\\packet-states.bin).

게임 서버가 보내는 메시지 번호 → 상태 이벤트(던전 상태, 맵 진입, 사망 등)와 본문 읽는 법,
상태값 이름(enum), 채널(맵) 이름·종류를 담는다. 화면 인식을 보조하는 신호로만 쓴다 — 패킷은 받기만 한다.

파일은 압축 + 암호화(SHA-256 스트림, HMAC-SHA256 위변조 검사)돼 있다. 키(packet.key)는 저장소에 넣지 않는다 —
개발 PC 의 프로젝트 폴더에만 두고, tools\\build.py 가 배포판 app\\ 에 넣는다. 배포판 안에는 키가 있으므로
공개 저장소에서 바로 보이지 않게 하는 정도이지 보안 장치는 아니다. 표에는 우리가 붙인 이벤트 이름·메시지 번호·읽는 자리만 두고
게임 내부 메시지 이름은 넣지 않는다. 원본 명세와 묶는 도구는 저장소 밖(mabi-packets)에 있다.

게임 패치로 메시지 번호가 바뀌면 표를 다시 묶어 데이터 폴더(paths.data)\\data 에 넣으면 그쪽이 우선한다 (gamedata 와 같은 규칙).
"""
import hashlib
import hmac
import json
import os
import re
import struct
import zlib
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from . import paths, sjon

FILE_NAME = "packet-states.bin"
KEY_NAME = "packet.key"   # 16진수 한 줄. 없으면 표를 못 연다 (패킷 신호 없이 화면 인식만으로 돈다)
MAGIC = b"MRPT"
VERSION = 2
_NONCE = 16
_TAG = 32


def key_file() -> Path:
    return paths.resource_dir() / KEY_NAME


@cache
def _keys() -> tuple[bytes, bytes]:
    f = key_file()
    if not f.exists():
        raise FileNotFoundError(f"키 파일 없음: {f}")
    secret = bytes.fromhex(f.read_text(encoding="ascii").strip())
    return (hashlib.sha256(b"enc" + secret).digest(),
            hashlib.sha256(b"mac" + secret).digest())


def _stream(key: bytes, nonce: bytes, n: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < n:
        out += hashlib.sha256(key + nonce + struct.pack("<Q", counter)).digest()
        counter += 1
    return bytes(out[:n])


def _xor(data: bytes, ks: bytes) -> bytes:
    return (int.from_bytes(data, "little") ^ int.from_bytes(ks, "little")).to_bytes(len(data), "little")


def seal(payload: dict) -> bytes:
    """표(dict) → 파일 내용. 묶는 도구(mabi-packets\\tools\\pack_states.py)가 쓴다."""
    enc, mac = _keys()
    nonce = os.urandom(_NONCE)
    plain = zlib.compress(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9)
    head = MAGIC + bytes([VERSION]) + nonce
    body = _xor(plain, _stream(enc, nonce, len(plain)))
    return head + body + hmac.new(mac, head + body, hashlib.sha256).digest()


def unseal(blob: bytes) -> dict:
    if blob[:4] != MAGIC or len(blob) < 5 + _NONCE + _TAG:
        raise ValueError("패킷 상태 표 형식이 아님")
    if blob[4] != VERSION:
        raise ValueError(f"패킷 상태 표 판 번호가 다름: {blob[4]}")
    enc, mac = _keys()
    head, body, tag = blob[:5 + _NONCE], blob[5 + _NONCE:-_TAG], blob[-_TAG:]
    if not hmac.compare_digest(tag, hmac.new(mac, head + body, hashlib.sha256).digest()):
        raise ValueError("패킷 상태 표가 손상됐거나 바뀜")
    plain = _xor(body, _stream(enc, head[5:], len(body)))
    return json.loads(zlib.decompress(plain).decode("utf-8"))


@dataclass(frozen=True)
class Field:
    name: str
    off: int
    type: str
    enum: str = ""
    lookup: str = ""
    size: int = 0  # u64list·u32list: 항목 하나의 바이트 수
    at: int = 0    # u64list·u32list: 항목 안에서 읽을 값 위치
    key: str = ""  # sjon: 이 이름 다음 문자열을 값으로 읽는다
    # 표식 — 패치로 앞 내용이 늘거나 줄어 칸이 밀려도 따라가게, 이 바이트 모양(16진, ?? 는 아무 바이트)을 찾아
    # 그 시작 + rel 에서 읽는다. 표식이 없으면 off 그대로 (11-05 패치로 물길 주술사 위치가 64바이트 밀림)
    find: str = ""
    rel: int = 0
    # off 가 음수면 본문 끝에서부터 센다 — 앞쪽에 길이가 바뀌는 칸이 있고 뒤쪽은 고정일 때
    # (장비 갱신: 박힌 보석 수만큼 앞이 늘어 각인 단계가 밀린다, 11-09 목걸이 298 · 완드 322바이트)

    def at_body(self, body: bytes) -> int:
        if self.find:
            m = _marker(self.find).search(body)
            if m:
                return m.start() + self.rel
        return self.off if self.off >= 0 else len(body) + self.off


@dataclass(frozen=True)
class Event:
    key: str
    proto: int
    status: str  # confirmed(실측) / candidate(아직 실측 안 함)
    desc: str
    fields: tuple[Field, ...] = field(default_factory=tuple)

    @property
    def confirmed(self) -> bool:
        return self.status == "confirmed"


class Table:
    def __init__(self, data: dict):
        self.diag = None  # packet_diag.PacketDiag — 붙어 있으면 표와 안 맞는 패킷을 기록한다
        self.meta: dict = data["meta"]
        self.known: frozenset[int] = frozenset(data["known"])  # 게임에 있는 메시지 번호 전부 (처음 보는 번호 가려내기용)
        self.enums: dict[str, dict[int, str]] = {
            n: {int(k): v for k, v in vals.items()} for n, vals in data["enums"].items()}
        self.channels: dict[int, dict] = {int(k): v for k, v in data["channels"].items()}
        # 리모콘이 판단하는 상태 → 쓰는 이벤트·PacketState 필드·대체 수단·아직 못 하는 것 (spec/states.json 의 states)
        self.states: list[dict] = data.get("states", [])
        self._events: dict[int, Event] = {}
        self._by_key: dict[str, Event] = {}
        for e in data["events"]:
            ev = Event(e["key"], e["proto"], e["status"], e["desc"],
                       tuple(Field(**f) for f in e.get("fields", ())))
            self._events[ev.proto] = ev
            self._by_key[ev.key] = ev

    def event(self, proto: int) -> Event | None:
        return self._events.get(proto)

    def by_key(self, key: str) -> Event | None:
        return self._by_key.get(key)

    def events(self) -> list[Event]:
        return list(self._events.values())

    def channel(self, cid: int) -> dict | None:
        """{'type': 'InstanceDungeon' 등, 'name': 이름(던전·사냥터·필드만)} 또는 None (표에 없는 새 맵)."""
        return self.channels.get(cid)

    def enum(self, name: str) -> dict[int, str]:
        return self.enums.get(name, {})

    def decode(self, proto: int, body: bytes) -> tuple[Event, dict] | None:
        """상태 이벤트면 (이벤트, 읽은 값). 본문이 짧아 못 읽은 필드는 빠진다."""
        ev = self._events.get(proto)
        if ev is None:
            if proto not in self.known:
                self._problem("unknown_proto", f"0x{proto:06x}", body)
            return None
        vals = {}
        for f in ev.fields:
            off = f.at_body(body)
            v = _read(body, off, f.type, f.size, f.at, f.key) if off >= 0 else None
            if v is None:
                self._problem("short_body", ev.key, body, field=f.name, off=off, type=f.type)
                continue
            vals[f.name] = v
            if f.enum:
                name = self.enum(f.enum).get(v)
                if name is None:
                    self._problem("unknown_enum", f"{ev.key}.{f.name}={v}", body, enum=f.enum)
                vals[f.name + "_name"] = name or "?"
            if f.lookup == "channels":
                ch = self.channel(v)
                if ch is None and v:
                    self._problem("unknown_channel", str(v), None, event=ev.key)
                vals[f.name + "_name"] = ch.get("name", "") if ch else ""
                vals[f.name + "_type"] = ch["type"] if ch else ""
        return ev, vals

    def _problem(self, kind: str, key: str, body: bytes | None, **info) -> None:
        if self.diag is not None:
            self.diag.record(kind, key, body, **info)


@cache
def _marker(hexpat: str) -> re.Pattern:
    """'0000403f??01' → 바이트 정규식 (?? = 아무 바이트)."""
    parts = [hexpat[i:i + 2] for i in range(0, len(hexpat), 2)]
    return re.compile(b"".join(b"." if h == "??" else re.escape(bytes.fromhex(h)) for h in parts), re.S)


_FMT = {"u8": "<B", "u32": "<I", "i32": "<i", "u64": "<Q", "f32": "<f"}


def sjon_strings(body: bytes, off: int = 0) -> list[str] | None:
    """대사 내용 묶음(SJON, 꼴은 mabi/sjon.py)의 문자열 표.
    문자열은 이름·값이 차례로 이어진다 ('npcName', NPC 이름, …, 'dialogueAction', 'SelectKeyword' …). off 부터 'SJON' 을 찾는다."""
    s = body.find(b"SJON", off)
    return None if s < 0 else sjon.strings(body, s)


def _read(body: bytes, off: int, typ: str, size: int = 0, at: int = 0, key: str = ""):
    if typ == "sjon":  # SJON 문자열 중 key 바로 다음 것. key 가 없으면 '' (그 대사엔 그 항목이 없음)
        strs = sjon_strings(body, off)
        if strs is None:
            return ""  # 대사 내용이 없는 메시지 (대화 끝 등)
        return next((strs[i + 1] for i in range(len(strs) - 1) if strs[i] == key), "")
    if typ in ("u64list", "u32list"):  # u32 개수 + size 바이트씩 — 각 항목 at 위치의 u64 (u32list 는 u32)
        fmt, w = ("<Q", 8) if typ == "u64list" else ("<I", 4)
        if off + 4 > len(body):
            return None
        n = struct.unpack_from("<I", body, off)[0]
        if size < at + w or off + 4 + n * size > len(body):
            return None
        return [struct.unpack_from(fmt, body, off + 4 + i * size + at)[0] for i in range(n)]
    if typ == "bool":
        return bool(body[off]) if off < len(body) else None
    if typ == "str32":
        if off + 4 > len(body):
            return None
        n = struct.unpack_from("<I", body, off)[0]
        raw = body[off + 4: off + 4 + n]
        return raw.decode("utf-16le", "replace") if len(raw) == n else None
    fmt = _FMT[typ]
    if off + struct.calcsize(fmt) > len(body):
        return None
    return struct.unpack_from(fmt, body, off)[0]


def table_file() -> Path:
    """표는 설치 폴더(코드 옆 data 폴더)의 것 하나만 쓴다 — 판(설치 파일·패치 묶음)과 함께 바뀌므로 판을 올리면 표도 새것이다.
    예전엔 데이터 폴더(LOCALAPPDATA 의 MobiRemote/data)를 먼저 봐서, 거기 옛 표가 남아 있으면 새 판을 깔아도
    그 표를 읽었다 (11-20 다른 PC: 3.29.1 인데 11-12 표로 stale_table)."""
    return paths.resource_dir() / "data" / FILE_NAME


def retire_stray() -> Path | None:
    """데이터 폴더에 남은 표를 .old 로 이름을 바꿔 치운다 (지우지는 않는다). 바꾼 파일 경로, 없으면 None.
    개발 중처럼 데이터 폴더가 곧 설치 폴더면 그 표가 쓰는 표라 건드리지 않는다."""
    try:
        stray = paths.load().data / "data" / FILE_NAME
        if not stray.exists() or stray.resolve() == table_file().resolve():
            return None
        old = stray.with_name(FILE_NAME + ".old")
        old.unlink(missing_ok=True)
        stray.rename(old)
        return old
    except OSError:
        return None


@cache
def load() -> Table:
    f = table_file()
    if not f.exists():
        raise FileNotFoundError(f"데이터 파일 없음: {f}")
    return Table(unseal(f.read_bytes()))
