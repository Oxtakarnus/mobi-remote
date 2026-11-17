"""받은 TCP 조각 → 메시지. 이더넷/IP/TCP 머리를 벗기고(parse_tcp), 서버 연결 하나의 수신 스트림을 순서대로 이어
[메시지 번호 u32][길이 u32][압축 u8][본문] 로 자른다(Stream). 연결 처음엔 인사 블록 'MMCG'[길이 u32][내용] 하나."""
import socket
import struct
import time

try:
    import brotli
except ImportError:  # 없으면 압축된 메시지를 풀 때마다 실패한다 (decompress) — 예전처럼 그 메시지만 못 읽는다
    brotli = None

HDR = 9
HELLO = b"MMCG"             # 연결 첫머리 인사 블록 (메시지가 아니다)
MAX_FRAME = 8 << 20         # 맵 진입 때 오는 것 중 큰 건 0.8MB 쯤
MAX_PENDING = 512           # 순서가 뒤바뀐 조각을 이만큼까지 들고 기다린다
# 빠진 조각을 이만큼 기다린다 (초). 네트워크에서 잃은 것은 서버가 금방 다시 보내고(재전송) 그것도 받는다.
# 캡처에서 잃은 것(받는 칸 넘침)은 끝내 안 온다 — 예전엔 뒤 조각이 512개 쌓일 때까지 기다리며 이벤트가 멈췄다
HOLE_WAIT = 1.5
SYNC_FRAMES = 3             # 중간부터 받기 시작했을 때 이만큼 연달아 말이 되면 맞춘 것으로 본다


def decompress(body: bytes) -> bytes:
    """압축된 메시지 본문을 푼다 (brotli). 없으면 ImportError, 못 풀면 brotli.error."""
    if brotli is None:
        raise ImportError("No module named 'brotli'")
    return brotli.decompress(body)


# ── 이더넷/IP/TCP ───────────────────────────────────────────────────

def parse_tcp(frame: bytes, link: int = 1):
    """(서버 IP, 서버 포트, 내 포트, seq, flags, payload) 또는 None. link 1 = 이더넷."""
    if link != 1 or len(frame) < 14:
        return None
    off, etype = 14, struct.unpack_from("!H", frame, 12)[0]
    if etype == 0x8100:  # VLAN
        etype = struct.unpack_from("!H", frame, 16)[0]
        off = 18
    if etype != 0x0800 or len(frame) < off + 20:
        return None
    ihl = (frame[off] & 0x0F) * 4
    total = struct.unpack_from("!H", frame, off + 2)[0]
    if frame[off + 9] != 6:
        return None
    src = socket.inet_ntoa(frame[off + 12:off + 16])
    t = off + ihl
    if len(frame) < t + 20:
        return None
    sport, dport, seq = struct.unpack_from("!HHI", frame, t)
    doff = (frame[t + 12] >> 4) * 4
    flags = frame[t + 13]
    end = min(len(frame), off + total) if total else len(frame)
    return src, sport, dport, seq, flags, frame[t + doff:end]


# ── 스트림 → 메시지 ─────────────────────────────────────────────────

def _rel(a: int, b: int) -> int:
    """TCP 번호 a 가 b 보다 얼마나 뒤인가 (앞이면 음수, 32비트 돌아감 고려)."""
    d = (a - b) & 0xFFFFFFFF
    return d - (1 << 32) if d >= 0x80000000 else d


class Stream:
    """서버 연결 하나의 수신 스트림. feed() 가 다 모인 메시지 (번호, 압축, 본문) 를 돌려준다."""

    def __init__(self, known: frozenset[int], on_desync=None):
        self.known = known
        self.on_desync = on_desync
        self.next_seq: int | None = None
        self.pending: dict[int, bytes] = {}
        self.buf = bytearray()
        self.synced = False
        self.hole_at: float | None = None  # 지금 빈자리가 생긴 때 (빈자리가 없으면 None)

    def feed(self, seq: int, flags: int, payload: bytes, now: float | None = None) -> list[tuple[int, int, bytes]]:
        if flags & 0x02:  # SYN: 연결 처음부터 받음 → 메시지 경계가 맞다
            self.next_seq, self.pending, self.buf, self.synced = (seq + 1) & 0xFFFFFFFF, {}, bytearray(), True
            self.hole_at = None
            return []
        if not payload:
            return []
        if self.next_seq is None:  # 연결 중간부터 받기 시작함
            self.next_seq = seq
        now = time.monotonic() if now is None else now
        d = _rel(seq, self.next_seq)
        if d > 0:  # 앞 조각이 아직 안 옴 — 들고 기다린다
            if len(payload) > len(self.pending.get(seq, b"")):
                self.pending[seq] = payload
            if self.hole_at is None:
                self.hole_at = now
            if len(self.pending) > MAX_PENDING or now - self.hole_at > HOLE_WAIT:
                return self._skip_hole("gap", now)
            return []
        if -d >= len(payload):  # 이미 받은 자리 (재전송)
            return []
        self._append(payload[-d:])  # 겹친 재전송이면 새 부분만
        self._drain(now)
        return self._frames()

    def _append(self, data: bytes):
        self.buf += data
        self.next_seq = (self.next_seq + len(data)) & 0xFFFFFFFF

    def _drain(self, now: float) -> None:
        """들고 있던 조각 중 이어지는 것을 붙인다 (겹치면 새 부분만, 이미 받은 것은 버림). 빈자리가 남으면 그때부터 다시 잰다."""
        base = self.next_seq
        for seq in sorted(self.pending, key=lambda s: _rel(s, base)):
            d = _rel(seq, self.next_seq)
            if d > 0:
                break  # 아직 빈자리
            data = self.pending.pop(seq)
            if -d < len(data):
                self._append(data[-d:])
        self.hole_at = now if self.pending else None

    def _skip_hole(self, why: str, now: float) -> list[tuple[int, int, bytes]]:
        """빈자리가 끝내 안 메워짐 — 그 자리의 메시지는 잃었다. 들고 있던 뒤 조각은 버리지 않고 빈자리 다음부터 다시
        맞춘다 (예전엔 다 버려 그 안의 맵 진입 같은 이벤트도 잃었다). 메시지 경계를 모르니 _sync 로 머리를 다시 찾는다."""
        if self.on_desync:
            self.on_desync(why)
        self.buf.clear()
        self.synced = False
        self.next_seq = min(self.pending, key=lambda s: _rel(s, self.next_seq))
        self._drain(now)
        return self._frames()

    def _lost(self, why: str):
        if self.on_desync:
            self.on_desync(why)
        self.pending.clear()
        self.buf.clear()
        self.next_seq = None
        self.synced = False
        self.hole_at = None

    def _plausible(self, off: int) -> int | None:
        """off 에서 시작하는 메시지 헤더가 말이 되면 다음 메시지 위치."""
        if off + HDR > len(self.buf):
            return None
        proto, n, flag = struct.unpack_from("<IIB", self.buf, off)
        if flag > 1 or n > MAX_FRAME or proto not in self.known:
            return None
        return off + HDR + n

    def _sync(self) -> bool:
        b = len(self.buf)
        for start in range(min(b, 65536)):
            off, count = start, 0
            while count < SYNC_FRAMES:
                nxt = self._plausible(off)
                if nxt is None:
                    break
                count += 1
                off = nxt
                if off >= b:
                    break
            if count >= SYNC_FRAMES or (count and off == b):
                del self.buf[:start]
                self.synced = True
                return True
        if b > 1 << 20:  # 1MB 를 모아도 못 맞춤
            self._lost("sync")
        return False

    def _frames(self) -> list[tuple[int, int, bytes]]:
        if not self.synced and not self._sync():
            return []
        out, off = [], 0
        while off + HDR <= len(self.buf):
            if self.buf[off:off + 4] == HELLO:
                n = struct.unpack_from("<I", self.buf, off + 4)[0]
                if off + 8 + n > len(self.buf):
                    break
                off += 8 + n
                continue
            proto, n, flag = struct.unpack_from("<IIB", self.buf, off)
            if flag > 1 or n > MAX_FRAME:
                del self.buf[:off]
                self.synced = False
                if self.on_desync:
                    self.on_desync("header")
                return out + self._frames()
            if off + HDR + n > len(self.buf):
                break
            out.append((proto, flag, bytes(self.buf[off + HDR:off + HDR + n])))
            off += HDR + n
        del self.buf[:off]
        return out
