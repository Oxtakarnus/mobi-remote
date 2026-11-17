"""게임 시트(아이템·콘텐츠 표)를 읽기만 한다 — ResourcesPackage Starter 의 client.sheet*.bin.

  client.sheetmeta.bin  VU 시트 수 | 시트마다 (S 이름, VU 행 id 꼴, VU 행 수, VU preload 크기, VU 행 블록 크기)
                        | 시트마다 VU 행 크기 × 행 수 | 시트마다 preload 블록 (이 순서로 이어 붙임)
  client.sheetdata.bin  행 데이터 — 시트 행 블록을 목차 순서대로 이어 붙임
  client.sheettext.bin  문자열 표 — 값 칸에는 이 파일 안 오프셋이 들어 있다 (gamefiles._lzs 로 푼다)

데이터에는 필드 이름이 없다. 행을 어떤 순서로 읽는지는 쓰는 쪽이 안다 (게임 SheetLoader.Preload/LoadRow 순서,
mabi-recipes README 3.6절). 패치로 필드가 늘면 행 끝이 안 맞으므로, 쓰는 쪽은 Reader.done 으로 확인한다.

파일 셋은 합쳐 30MB 남짓이다. Sheets 는 목차만 먼저 읽고 행·문자열 파일은 처음 쓸 때 읽는다.
쓰는 쪽은 필요한 값만 뽑아 두고 Sheets 를 버린다 (오래 들고 있지 않는다).
"""
from __future__ import annotations

import json
import logging
import struct
from pathlib import Path

from . import gamefiles as gf
from .fileio import write_json

log =logging.getLogger("mabi")

_DIR = "Sheetdata_Client/"
META = _DIR + "client.sheetmeta.bin"
DATA = _DIR + "client.sheetdata.bin"
TEXT = _DIR + "client.sheettext.bin"


class SheetError(Exception):
    """시트 파일이 없거나 생각한 모양이 아니다 (게임 패치로 형식이 바뀌었을 때)."""


class Reader:
    """행·preload 바이트를 앞에서부터 읽는다. text 는 문자열 값을 풀 때 쓰는 sheettext 원문."""

    __slots__ = ("b", "o", "text")

    def __init__(self, b: bytes, o: int = 0, text: bytes | None = None):
        self.b, self.o, self.text = b, o, text

    @property
    def done(self) -> bool:
        return self.o == len(self.b)

    def u8(self) -> int:
        v = self.b[self.o]
        self.o += 1
        return v

    def vu(self) -> int:
        """부호 없는 varint (LEB128)."""
        r = sh = 0
        while True:
            c = self.b[self.o]
            self.o += 1
            r |= (c & 0x7F) << sh
            sh += 7
            if not c & 0x80:
                return r

    def vi(self) -> int:
        """부호 있는 varint — 첫 바이트 bit7 계속·bit6 부호·하위 6비트, 다음 바이트부터 7비트씩. 부호면 ~값."""
        c = self.b[self.o]
        self.o += 1
        neg, r, i = c & 0x40, c & 0x3F, 1
        while c & 0x80:
            c = self.b[self.o]
            self.o += 1
            r |= (c & 0x7F) << (7 * i - 1)
            i += 1
        return ~r if neg else r

    def fi(self) -> int:
        """4바이트 고정 정수 (다른 시트 행 id 같은 것)."""
        if self.o + 4 > len(self.b):
            raise IndexError("행 끝을 넘었다")
        v = struct.unpack_from("<I", self.b, self.o)[0]
        self.o += 4
        return v

    def s(self) -> str:
        """문자열 (값 = sheettext 오프셋)."""
        off = self.vu()
        if self.text is None:
            raise SheetError("문자열 표 없이 문자열을 읽으려 했다")
        return gf._lzs(self.text, off)

    def color(self) -> tuple[int, int, int] | None:
        """색 — 태그 바이트 + 0~3바이트. 00 = 없음.
        9N 회색 N×0x11 · A0 x 회색 x · A4 x y (x,x,y) · A8 x y (x,y,x) · AC x y (x,y,y) · B0 r g b."""
        t = self.u8()
        if t == 0:
            return None
        if 0x90 <= t <= 0x9F:
            v = (t & 0x0F) * 0x11
            return v, v, v
        if t == 0xA0:
            v = self.u8()
            return v, v, v
        if t in (0xA4, 0xA8, 0xAC):
            x, y = self.u8(), self.u8()
            return {0xA4: (x, x, y), 0xA8: (x, y, x), 0xAC: (x, y, y)}[t]
        if t == 0xB0:
            return self.u8(), self.u8(), self.u8()
        raise SheetError(f"모르는 색 꼴 {t:#04x}")

    def many(self, read) -> list:
        """VU 개수 + 값 여럿. read 는 Reader 메서드 (예: r.many(r.s))."""
        return [read() for _ in range(self.vu())]


def hex_color(c) -> str | None:
    return None if c is None else "#%02X%02X%02X" % tuple(c)


class Sheet:
    """시트 하나 — 행 수, preload, 행 바이트."""

    def __init__(self, owner: "Sheets", name: str, id_type: int, count: int, rows: list[int], end: int,
                 pre: tuple[int, int]):
        self._owner = owner
        self.name, self.id_type, self.count = name, id_type, count
        self._rows, self._end, self._pre = rows, end, pre

    def row(self, i: int) -> bytes:
        s = self._rows[i]
        e = self._rows[i + 1] if i + 1 < self.count else self._end
        return self._owner.data[s:e]

    def reader(self, i: int) -> Reader:
        return Reader(self.row(i), 0, self._owner.text)

    def preload(self) -> Reader:
        a, n = self._pre
        return Reader(self._owner.meta[a:a + n], 0, self._owner.text)


class Sheets:
    """시트 묶음. open(game_dir) 로 게임 폴더에서 읽거나, 바이트를 바로 넘겨 만든다 (시험)."""

    def __init__(self, meta: bytes, data=None, text=None):
        """data·text 는 bytes 또는 그 바이트를 돌려주는 함수 (처음 쓸 때 부른다)."""
        self.meta = meta
        self._data, self._text = data, text
        self._sheets: dict[str, Sheet] = {}
        self._parse()

    @classmethod
    def open(cls, game_dir) -> "Sheets":
        """게임 폴더의 ResourcesPackage 에서 경로로 찾아 읽는다 (blob·항목 번호는 패치마다 바뀐다)."""
        try:
            res = gf.Resources(Path(game_dir), lambda p: p.startswith(_DIR + "client.sheet"))
        except OSError as e:
            raise SheetError(f"게임 리소스 목차를 읽지 못했습니다: {e}") from e
        for p in (META, DATA, TEXT):
            if p not in res.paths:
                raise SheetError(f"게임 리소스에 {p} 가 없습니다")
        return cls(res.read(META), lambda: res.read(DATA), lambda: res.read(TEXT))

    @property
    def data(self) -> bytes:
        if callable(self._data):
            self._data = self._data()
        return self._data

    @property
    def text(self) -> bytes:
        if callable(self._text):
            self._text = self._text()
        return self._text

    def _parse(self) -> None:
        r = Reader(self.meta)
        # 목차의 이름은 sheettext 문자열이라 이름 오프셋만 먼저 모은다
        heads, off = [], 0
        for _ in range(r.vu()):
            name_off, id_type, count, pre_size, block = r.vu(), r.vu(), r.vu(), r.vu(), r.vu()
            heads.append((name_off, id_type, count, pre_size, off, block))
            off += block
        rows = []
        for _name, _type, count, _pre, start, _block in heads:
            o, lst = start, []
            for _ in range(count):
                lst.append(o)
                o += r.vu()
            rows.append(lst)
        pres = []
        for h in heads:
            pres.append((r.o, h[3]))
            r.o += h[3]
        if r.o != len(self.meta):
            raise SheetError("시트 목차 길이가 맞지 않습니다")
        self._heads = list(zip(heads, rows, pres))

    def _index(self) -> dict[str, Sheet]:
        if not self._sheets and self._heads:
            for (name_off, id_type, count, _ps, start, block), rows, pre in self._heads:
                name = gf._lzs(self.text, name_off)
                self._sheets[name] = Sheet(self, name, id_type, count, rows, start + block, pre)
        return self._sheets

    def names(self) -> list[str]:
        return list(self._index())

    def __contains__(self, name: str) -> bool:
        return name in self._index()

    def sheet(self, name: str) -> Sheet:
        try:
            return self._index()[name]
        except KeyError:
            raise SheetError(f"시트 {name} 가 없습니다") from None


def stamp(game_dir) -> list[int]:
    """시트가 든 ResourcesPackage 목차의 크기·시각 — 이 값이 그대로면 시트도 그대로다."""
    return gf.stamp_of(gf.index_of(Path(game_dir)))


def cached(f: Path, fmt: int, game_dir, build, opener=None, what: str = "시트 표", key: str = "value", stamper=None):
    """시트로 만든 값을 파일 f 에 두고 다시 쓴다 — 목차 stamp 와 형식 fmt 가 그대로면 파일 것을.
    (값, 이번에 새로 만들었나). build(Sheets) 가 값을 만든다. 목차·시트를 못 읽으면 경고만 남기고 (None, False).
    opener: 게임 폴더 → Sheets (기본 Sheets.open — 시험에서 바꾼다).
    stamper: 게임 폴더 → stamp (기본 stamp — build 가 본 목차 자료도 읽으면 gamefiles.res_stamp)."""
    f = Path(f)
    try:
        cur = (stamper or stamp)(game_dir)
    except OSError as e:
        log.warning(f"{what}: 게임 리소스 목차를 못 읽었습니다 ({e})")
        return None, False
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        if d.get("format") == fmt and d.get("stamp") == cur and key in d:
            return d[key], False
    except (OSError, ValueError, AttributeError):
        pass
    try:
        sh = (opener or Sheets.open)(game_dir)
        value = build(sh)
        del sh   # 시트 원문(30MB 남짓)은 들고 있지 않는다
    except (SheetError, OSError, IndexError) as e:
        log.warning(f"{what}: 게임 시트를 읽지 못했습니다 ({e})")
        return None, False
    write_json(f, {"format": fmt, "stamp": cur, key: value})
    return value, True
