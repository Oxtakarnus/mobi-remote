"""서버 연결 끊김 단서 (점검 등). 무수신·연결 닫힘은 로그로만 남기고, 세션 강제 종료 알림은 판단에 쓴다 — 받으면 봇이
게임을 끄고 작업 큐를 일시정지한다 (kicked → Bot.check_server, 사용자 2026-11-19).
PacketMonitor 가 상속한다 (self._silent · _opened · _closed · _kick · last_rx · state 를 쓴다)."""
import logging
import time

from .stream import decompress

log = logging.getLogger("mabi")

SILENT_LOG = 30      # 게임 안인데 서버 패킷이 이만큼(초) 안 오면 로그 — 하트비트가 약 2초마다 와서 평소 최대 무수신 2.3초 (11월 캡처)
# 서버가 세션을 끊는다는 알림. 본문 첫 4바이트가 사유 — 83 은 점검 (끊김 창의 'ERROR 83', 2026-11-19 06:00:15 받은 뒤 같은 초에
# 서버가 연결을 닫음). 17 은 11-17 19:01 에 한 번 (리모콘은 쉬고 있었고 23분 뒤 다시 접속 — 무엇인지는 모름)
KICKS = ("system.session_kicked", "system.kicked_by_block")
KICK_CONFIRM = 5     # 알림 뒤 서버가 연결을 닫았거나 이만큼(초) 아무것도 안 보내면 끊긴 것으로 본다


def _hms(t: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(t))


class LinkWatch:
    def _server_notice(self, key: str, flag: int, body: bytes) -> None:
        """세션 강제 종료·접속 차단 같은 서버 알림 (표의 system.*). 평소엔 안 오는 것들이라(11월 캡처 17분·서버 이동
        12번에 0번) 오면 본문 앞부분까지 남긴다."""
        if flag:
            try:
                body = decompress(body)
            except Exception:  # noqa: BLE001 — 못 풀면 압축된 채로 남긴다
                pass
        if key in KICKS:
            code = int.from_bytes(body[:4], "little") if len(body) >= 4 else -1
            self._kick = (time.time(), code)
        # 점검 공지(notice_add)는 160바이트쯤 — 나중에 글을 풀 수 있게 통째로 남긴다
        log.warning("패킷: 서버 알림 %s — 본문 %d바이트 %s", key, len(body), body[:192].hex(" "))

    def kicked(self) -> int | None:
        """서버가 이 세션을 끊었으면 그 사유 번호(83 = 점검), 아니면 None. 세션 강제 종료 알림(KICKS)이 오고, 그 뒤 서버가
        연결을 닫았거나(FIN·RST) KICK_CONFIRM 초 넘게 아무것도 안 보내야 끊긴 것으로 본다 — 알림만 오고 연결이 살아 있으면
        게임을 끄지 않는다. 그 뒤 새 연결이 열렸거나(다시 접속) 이미 처리했으면(kick_handled) 아니다."""
        k = self._kick
        if k is None or self._opened > k[0] or k[0] <= self._kick_done:
            return None
        closed = self._closed is not None and self._closed[0] >= k[0] - 1
        if closed or time.monotonic() - self.last_rx >= KICK_CONFIRM:
            return k[1]
        return None

    def kick_handled(self) -> None:
        """이 알림으로 게임을 껐다 — 다시 시작해도 같은 알림으로 또 끄지 않는다."""
        if self._kick:
            self._kick_done = self._kick[0]

    def _link(self, src: str, flags: int) -> None:
        """서버 패킷을 받을 때마다: 연결이 열리고(SYN) 닫힌(FIN·RST) 때를 적어 두고, 무수신 로그 뒤 다시 받았으면 한 줄."""
        if self._silent:
            self._silent = False
            log.info("패킷: 서버 패킷 다시 옴 (%.0f초 만)", time.monotonic() - self.last_rx)
        if flags & 0x02:
            self._opened = time.time()
        if flags & 0x05:
            self._closed = (time.time(), "RST" if flags & 0x04 else "FIN", src)

    def _watch_silence(self) -> None:
        """게임 안인데 서버 패킷이 SILENT_LOG 초 넘게 안 오면 한 번 남긴다 — 마지막 연결을 서버가 닫았는지, 열린 채인지와 함께.
        판단에는 아직 안 쓴다. 게임이 켜져 있는지는 여기서 모른다 — 사람이 게임을 꺼도 한 줄 남는다."""
        if self._silent or not self.last_rx or not self.state.in_game:
            return
        gap = time.monotonic() - self.last_rx
        if gap < SILENT_LOG:
            return
        self._silent = True
        if self._closed and self._closed[0] >= self._opened:
            at, how, src = self._closed
            last = f"서버가 {_hms(at)} 에 연결을 닫음 ({how} · {src}), 그 뒤 새 연결 없음"
        else:
            last = "연결은 열린 채" + (f" (마지막 새 연결 {_hms(self._opened)})" if self._opened else "")
        log.info("패킷: 게임 안인데 서버 패킷이 %.0f초째 안 옴%s — %s", gap, " · 맵 로딩 중" if self.state.loading else "", last)
