"""게임 설치 폴더의 리소스를 **읽기만** 하는 곳 (염색 재질 그림, 드레스룸 자산).

게임 파일은 저장소·배포본에 넣지 않는다. 쓰는 쪽이 처음에 여기서 꺼내 사용자 데이터 폴더에 복사본을 두고,
게임이 패치돼 목차(index)가 바뀌면 다시 꺼낸다 (stamp 로 비교).

리소스 묶음 (ResourcesPackage):
  Starter\\index   경로 목차 — 경로마다 (BlobKey, 묶음 안 번호). BlobKey 의 0x8000 은 Starter\\, 아니면 ResourcesPackage\\,
                   나머지 비트가 묶음 번호. 묶음 안 번호는 1부터, 0 은 오프셋 표 바로 뒤의 항목.
  NNNN.blob        오프셋 표 + 항목들. 항목 = Romu-trio 난수 XOR(시드: 항목 오프셋·크기) → 4바이트 원래 크기 + raw deflate.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

M64 = (1 << 64) - 1
_MUL = 0xD3833E804F4C574B


def game_dir() -> Path | None:
    """게임 설치 폴더 (ResourcesPackage 가 있는 곳). CLI 를 찾는 경로를 그대로 쓴다. 못 찾으면 None."""
    from .connector import candidates
    for exe, _ in candidates():
        d = Path(exe).parent
        if (d / "ResourcesPackage" / "Starter" / "index").is_file():
            return d
    return None


def _rol(v, r):
    return ((v << r) | (v >> (64 - r))) & M64


def _unxor(data: bytes, h1: int, h2: int) -> bytes:
    """항목 난독화 풀기 (GameAssembly 의 묶음 읽기와 같은 Romu-trio 흐름)."""
    h1 &= M64
    h2 &= M64
    t = ((((~h2) & M64) ^ h1) + 0x171974E5E5BDDA11) & M64
    x = (t * _MUL) & M64
    rdx = (h2 + 0x849EE64C9720BB37) & M64
    rcx = (h1 + 0x708B6BA5FB11F033) & M64
    z = _rol((t - rdx) & M64, 44)
    y = _rol((rdx - rcx) & M64, 12)
    out = bytearray(data)
    n = len(out)
    i = 0
    while i < n:
        xp = x
        x = (z * _MUL) & M64
        y2 = _rol((y - xp) & M64, 12)
        z = _rol((z - y) & M64, 44)
        y = y2
        k = struct.pack("<Q", xp)
        for j in range(min(8, n - i)):
            out[i + j] ^= k[j]
        i += 8
    return bytes(out)


def _lzs(data: bytes, pos: int) -> str:
    out = bytearray()
    b = data[pos]
    while b:
        pos += 1
        if b < 0x80:
            ln, src, nxt = b, pos, pos + b
        else:
            v = ((b & 0x7F) << 8) | data[pos]
            ln, src, nxt = (v & 0x1F) + 1, pos - (v >> 5) - 2, pos + 1
        out += data[src:src + ln]
        b = data[nxt]
        pos = nxt
    return out.decode("utf-8", "replace")


def parse_index(d: bytes, want) -> dict[str, tuple[int, int]]:
    """목차 원문 → {경로: (BlobKey, 묶음 안 번호)} (want(경로) 가 참인 것만). AssetPackages 목차도 같은 형식."""
    p = 4
    n = struct.unpack_from("<i", d, p)[0]
    p += 4
    items = [struct.unpack_from("<HH", d, p + 4 * i) for i in range(n)]
    p += 4 * n
    nd = struct.unpack_from("<I", d, p)[0]
    p += 4
    for _ in range(nd):
        p += 4
        c = struct.unpack_from("<I", d, p)[0]
        p += 4 + 4 * c
    hn = struct.unpack_from("<i", d, p)[0]
    p += 4 + 4 * hn
    pn = struct.unpack_from("<i", d, p)[0]
    p += 4
    paths = struct.unpack_from("<%dQ" % pn, d, p)
    p += 8 * pn
    bn = struct.unpack_from("<i", d, p)[0]
    p += 4 + 4 * bn
    blocks = []
    for _ in range(3):
        ln = struct.unpack_from("<i", d, p)[0]
        blocks.append(d[p + 4:p + 4 + ln])
        p += 4 + ln
    dt, nm, pf = blocks
    cache: dict[int, str] = {}

    def dirpath(i):
        if i in cache:
            return cache[i]
        j = i + 1
        while dt[j] > 4:
            j += 1
        name, t = dt[i:j].decode("utf-8", "replace"), dt[j]
        r = name if t == 0 else dirpath(i - int.from_bytes(dt[j + 1:j + 1 + t], "little")) + "/" + name
        cache[i] = r
        return r

    out = {}
    for k, v in enumerate(paths):
        di, ni, po = v & 0xFFFFFF, (v >> 24) & 0xFFFFFFF, v >> 52
        path = dirpath(di) + "/" + _lzs(nm, ni) + _lzs(pf, po)
        if want(path):
            out[path] = items[k]
    return out


def _entry(blob: Path, i: int) -> bytes:
    """묶음의 i 번째 항목(0부터) 원문. i = -1 은 목차 번호 0 인 항목 — 오프셋 표 바로 뒤(파일 위치 n)부터 표 첫 값까지."""
    with open(blob, "rb") as fh:
        head = fh.read(8)
        n = struct.unpack_from("<I", head, 4)[0]
        offs = struct.unpack("<%dI" % (n // 4), fh.read(n))
        s, e = (n, offs[0]) if i < 0 else (offs[i], offs[i + 1])
        fh.seek(s)
        raw = fh.read(e - s)
    p = _unxor(raw, s, e - s)
    return zlib.decompress(p[4:], -15)


class Resources:
    """ResourcesPackage 목차. want(경로) 가 참인 경로만 기억한다 (목차 전체는 수십만 줄)."""

    def __init__(self, root: Path, want=lambda p: True, main: bool = False):
        """main: 본 목차(ResourcesPackage\\index)도 읽는다 — 타임라인 같은 자료는 Starter 목차에 없다.
        두 목차에 같은 경로가 있으면 Starter 것을 쓴다."""
        self.root = Path(root) / "ResourcesPackage"
        self.index = self.root / "Starter" / "index"
        self.paths = parse_index(self.index.read_bytes(), want)
        self.main = self.root / "index" if main else None
        if self.main is not None:
            for p, v in parse_index(self.main.read_bytes(), want).items():
                self.paths.setdefault(p, v)

    def stamp(self) -> list[int]:
        """목차 크기·시각 — 캐시가 이 값과 같으면 게임이 그대로다."""
        return stamp_of(self.index) + (stamp_of(self.main) if self.main is not None else [])

    def find(self, tail: str) -> str | None:
        """경로 끝이 tail 인 첫 경로."""
        for p in self.paths:
            if p.endswith(tail):
                return p
        return None

    def read(self, path: str) -> bytes:
        bk, ix = self.paths[path]
        base = self.root / "Starter" if bk & 0x8000 else self.root
        return _entry(base / f"{bk & 0x7FFF:04d}.blob", ix - 1)


def stamp_of(index: Path) -> list[int]:
    st = Path(index).stat()
    return [st.st_size, int(st.st_mtime)]


def index_of(root: Path) -> Path:
    return Path(root) / "ResourcesPackage" / "Starter" / "index"


def res_stamp(root: Path) -> list[int]:
    """ResourcesPackage 목차 둘(Starter·본)의 크기·시각 — Resources(main=True) 로 읽은 값의 캐시 기준. 없는 목차는 뺀다."""
    rp = Path(root) / "ResourcesPackage"
    return [v for f in (rp / "Starter" / "index", rp / "index") if f.is_file() for v in stamp_of(f)]
