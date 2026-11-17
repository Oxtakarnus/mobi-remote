"""게임 "SJON" 바이너리 읽기만 — 리소스의 *.sjon.bin (몸 다양성 자료 등)과 패킷 대사 묶음이 같은 꼴이다.

  "SJON" · u32 판(1) · u32 문자열 수 n · u32 본문 낱말 수 · u32 끝 위치 n 개 · 문자열 덩어리(UTF-8, 4바이트로 맞춤)
  · u32 본문 낱말들

본문 낱말의 아래 3비트가 꼬리표다.
  0 숫자      비트 3..5 = 10진 지수 e, 부호 있는 값 >> 6 = 정수 m → m · 10^-e
  1 긴 숫자   가리킨 곳 두 낱말 = 64비트 부호 정수 q → 지수 q & 31, 정수 q >> 5
  2 null · 3 bool (v >> 3) · 4 문자열 (v >> 3 = 문자열 번호)
  5 배열 · 6 객체 · 7 사전 — v >> 3 은 이 낱말 바로 다음부터 센 거리.
      배열 [개수, 원소…] · 객체 [형 번호, 필드…] · 사전 [개수, 키 문자열 번호…, 값…]
본문 0 번 낱말 = 배열 [스키마, 루트]. 스키마 = [형 수, 형 이름 번호…, 필드 정의(사전 꼴)…],
필드 정의 = [필드 수, 필드 이름 번호…, 필드 형(문자열)…]. 객체는 형의 필드 순서대로 값이 놓인다.
"""
from __future__ import annotations

import struct


class SjonError(ValueError):
    """SJON 이 아니거나 생각한 모양이 아니다."""


def strings(b: bytes, s: int = 0) -> list[str] | None:
    """s 에서 시작하는 SJON 의 문자열 표. 잘렸거나 모양이 이상하면 None (패킷처럼 믿을 수 없는 바이트에도 쓴다)."""
    if b[s:s + 4] != b"SJON" or s + 16 > len(b):
        return None
    n = struct.unpack_from("<I", b, s + 8)[0]
    blob = s + 16 + n * 4
    if n > 100000 or blob > len(b):
        return None
    ends = struct.unpack_from(f"<{n}I", b, s + 16)
    out, start = [], 0
    for e in ends:
        if e < start or blob + e > len(b):
            return None
        out.append(b[blob + start: blob + e].decode("utf-8", "replace"))
        start = e
    return out


def load(b: bytes):
    """파일 하나 → 루트 값 (객체는 dict, 배열은 list)."""
    return _Doc(b).root


class _Doc:
    def __init__(self, b: bytes):
        if b[:4] != b"SJON" or len(b) < 16:
            raise SjonError("SJON 파일이 아닙니다")
        ver, n, nw = struct.unpack_from("<3I", b, 4)
        if ver != 1:
            raise SjonError(f"모르는 SJON 판 {ver}")
        strs = strings(b)
        if strs is None:
            raise SjonError("SJON 문자열 표가 잘렸습니다")
        self.strs = strs
        end = struct.unpack_from("<I", b, 16 + 4 * (n - 1))[0] if n else 0
        body = 16 + 4 * n + ((end + 3) & ~3)
        if len(b) - body != 4 * nw:
            raise SjonError("SJON 본문 길이가 맞지 않습니다")
        self.w = struct.unpack_from(f"<{nw}I", b, body)
        try:
            top = self._items(self._to(0))
            self.schema = self._schema(self._to(top[0]))
            self.root = self.value(top[1])
        except (IndexError, KeyError) as e:
            raise SjonError(f"SJON 본문을 풀지 못했습니다 ({e})") from None

    def _to(self, i: int) -> int:
        return i + 1 + (self.w[i] >> 3)

    def _items(self, j: int) -> list[int]:
        return [j + 1 + k for k in range(self.w[j])]

    def _schema(self, j: int) -> list[tuple[str, list[str]]]:
        n = self.w[j]
        out = []
        for k in range(n):
            d = self._to(j + 1 + n + k)
            nf = self.w[d]
            out.append((self.strs[self.w[j + 1 + k]], [self.strs[self.w[d + 1 + f]] for f in range(nf)]))
        return out

    @staticmethod
    def _num(m: int, e: int):
        return m if e == 0 else round(m * 10.0 ** -e, e)

    def value(self, i: int):
        v = self.w[i]
        t = v & 7
        if t == 0:
            return self._num((v - (1 << 32) if v & 0x80000000 else v) >> 6, (v >> 3) & 7)
        if t == 1:
            j = self._to(i)
            q = self.w[j] | (self.w[j + 1] << 32)
            if q >> 63:
                q -= 1 << 64
            return self._num(q >> 5, q & 31)
        if t == 2:
            return None
        if t == 3:
            return bool(v >> 3)
        if t == 4:
            return self.strs[v >> 3]
        if t == 5:
            return [self.value(x) for x in self._items(self._to(i))]
        if t == 6:
            j = self._to(i)
            _name, fields = self.schema[self.w[j]]
            return {f: self.value(j + 1 + k) for k, f in enumerate(fields)}
        j = self._to(i)   # 7 사전
        n = self.w[j]
        return {self.strs[self.w[j + 1 + k]]: self.value(j + 1 + n + k) for k in range(n)}
