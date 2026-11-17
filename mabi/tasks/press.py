"""누르고 결과로 확인 — 화면이 무엇인지 확실히 안 뒤에는 아는 자리·단축키를 누르고, 됐는지는 결과 신호(패킷 매칭·맵 로딩·
이동 시작, 다음 창)로 본다. 누른 뒤 중간 상태(탭이 바뀌었나, 버튼 글자가 있나)를 다시 읽어 실패하지 않는다
(2026-11-16 사용자: "시도도 못 하고 잘못 인식해서 실패 처리되는 게 더 속상하다" — 그림·글자 인식은 애니메이션만 조금
들어가도 확 떨어진다). 신호가 안 오면 화면을 다시 맞춰 몇 번 더 누르고, 그래도 안 되면 화면에서 까닭을 읽어 붙여
NotSeen (오류 — 작업 큐가 자리를 정리하고 맨 아래에서 한 번 더).

어비스·레이드·드릴·뱅가드·필드 보스 입장이 같이 쓴다.
"""
import time
from typing import Callable

from .. import gamedata as gd
from ..bot import Bot
from ..exceptions import NotSeen
from ..ocr import find_texts

TRIES = 3  # 눌러도 시작되지 않을 때 화면을 다시 맞춰 누르는 횟수
TOOK = 8   # 누른 뒤 시작 신호를 기다리는 초
REDO = 2   # 기다리는 사이 끼어들기(monitor.interrupts)를 넘겨 다시 누르는 횟수 상한 (TRIES 에 세지 않는다)


def until(bot: Bot, press: Callable[[], None], started: Callable[[], bool | None], what: str, *,
          tries: int = TRIES, again: Callable[[], None] | None = None, why: Callable[[], str] | None = None,
          shot: str = "press") -> None:
    """press() 뒤 started() 가 True(시작됨)거나 None(모름 — 뒤의 기다림이 상한까지 본다)이면 끝. False 면 again()
    (화면을 다시 맞춤 — 없으면 그대로) 뒤 다시 누른다. tries 번 모두 False 면 까닭(reason)을 붙여 NotSeen.
    기다리는 사이 끼어들기를 넘겼으면(Bot.interrupt_n) 그 시도는 세지 않고 다시 맞춰 누른다 — 끼어든 창이 누른 것을 먹었다."""
    n = redo = 0
    while n < tries:
        if (n or redo) and again:
            again()
        k = bot.interrupt_n
        press()
        if started() is not False:
            return
        if bot.interrupt_n != k and redo < REDO:
            redo += 1
            bot.log.info(f"{what}: 시작 신호를 기다리는 사이 끼어들기를 넘김 → 다시 누름")
            continue
        n += 1
        bot.log.info(f"{what}: 눌렀는데 시작 신호가 없음 ({n}/{tries})" + (" → 다시" if n < tries else ""))
    raise NotSeen(f"{what}: {tries}번 눌러도 시작되지 않음 ({reason(bot, why)}) → {bot.snapshot(shot).name}")


def signal(bot: Bot, pred, timeout: float = TOOK, still: Callable[[], bool] | None = None) -> Callable[[], bool | None]:
    """started 로 쓸 패킷 신호 — 방금 누른 뒤(input_mark) pred 를 한 번이라도 만족했나 (bot.wait_packet: 모르면 None).
    still: 누른 창이 아직 떠 있나. 신호가 없어도 창이 닫혔으면 모름(None) — 무언가 시작됐을 수 있다 (매칭 신호가 늦게 오는
    중에 다시 누르면 매칭 창의 취소가 된다). 창이 그대로일 때만 다시 누른다."""
    def started():
        got = bot.wait_packet(pred, timeout, since=bot.input_mark)
        if got is False and still is not None and not still():
            bot.log.info("시작 신호는 없지만 창이 닫힘 → 다시 누르지 않고 뒤의 기다림으로")
            return None
        return got
    return started


def poll(bot: Bot, check: Callable[[], bool], timeout: float = TOOK, interval: float = 1.0) -> bool:
    """started 로 쓸 화면·CLI 신호 — check() 가 timeout 초 안에 참이 되나."""
    end = time.monotonic() + timeout
    while True:
        if check():
            return True
        if time.monotonic() > end:
            return False
        bot.sleep(interval, interval + 0.3)


def reason(bot: Bot, why: Callable[[], str] | None = None) -> str:
    """시작되지 않은 까닭을 화면에서 읽는다 — 연속 실행 제한 창(실패 처리 escalate 가 게임을 다시 켠다), 가운데 아래
    알림 글자('입장 불가 …' 등), 그 화면만의 사정(why)."""
    if bot.run_limit_popup():
        return "연속 실행 제한 창"
    parts = []
    popup = "".join(t for t, *_ in find_texts(bot.frame(), gd.region("abyss_popup")))
    if popup:
        parts.append(f"알림 '{popup}'")
    if why and (w := why()):
        parts.append(w)
    return " · ".join(parts) or "까닭을 화면에서 못 읽음"
