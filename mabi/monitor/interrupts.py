"""끼어들기 — 어느 태스크든 언제든 화면에 떠서 하던 일을 막는 것 (NPC 가 말을 걺·출석).

기본은 '없다' 로 보고 하던 일을 한다. 화면에 떠서 막을 때만 멈추고 → 무엇인지 보고 → 넘긴 뒤 → 하던 일로 돌아간다
(사용자 2026-11-17). 패킷 신호는 '화면을 한번 볼 때' 를 알려 줄 뿐, 신호만으로 멈추거나 기다리지 않는다. 끝 패킷을
놓친 신호가 남아 화면엔 아무것도 없는데 20초 넘게 헛기다렸다 — 각인 강화 창 위에서 세 번(2026-11-15 00:06~00:12),
사용자가 직접 넘긴 출석 신호로 필드에서(11-17 06:49). 넘긴 뒤 막혔던 동작은 다시 한다 — Bot.interrupt_n 이 늘면
Monitor.act · press.until 이 그 시도를 세지 않고 다시 한다.

NPC 가 갑자기 말을 거는 것(주간 목표 첫 달성 뒤 에반 등)·출석처럼 '이 일 뒤에 뜰 수도 안 뜰 수도' 있는 것을 태스크마다
'여기서 볼까' 하며 끼워 넣던 것을 한곳으로 (사용자 2026-10-27). Bot 기본 동작(check_stop — sleep·frame·wait_packet 이
늘 거친다)이 신호가 있을 때 화면을 한 번 보고, 떠 있으면 하던 일을 잠깐 멈추고 점검자로 넘긴다. 별도 스레드가 직접 누르지
않는다 — 태스크의 입력과 섞이면 엉뚱한 곳이 눌린다.

여기에 드는 것은 태스크가 열지 않은 것뿐이다. NPC 대화를 스스로 다루는 일(접속·아르바이트·요일 던전 게시판·수리)은
Bot.npc_talk() 로 '내 몫' 이라고 알리고, 그동안 대화는 끼어들기로 보지 않는다. 그 밖에 메뉴(선택지)가 뜨는 대화는
고르지 않고 ESC('대화 종료')로 마친다 — 로나가 먼저 말을 걸면 대사 뒤 [판의 조언 · 상점 · 대화 종료] 메뉴가 뜨고,
ESC 뒤 작별 대사를 넘겨야 끝난다 (2026-11-02 실기). 대사 내용으로 판단하지 않는다.
패킷이 없으면 아무것도 하지 않는다 — 기다리는 쪽(bot.wait 의 막는 화면 넘기기)과 act 앞 정리가 화면으로 본다.
"""
import time

from .. import situation as sit

# 신호가 있는 동안 화면을 보는 간격 (초). 막 온 신호는 자주, STALE 초 넘게 화면에 안 뜨는 신호는 드물게 —
# 끝 패킷을 놓친 신호일 수 있지만, 늦게 그려지는 대화(에반이 걸어와 말을 거는 등)도 놓치지 않게 아주 끄지는 않는다
LOOK_EVERY = 1.0
LOOK_LATER = 5.0
STALE = 8
# 끼어들기 하나를 붙잡고 있는 상한 (초). 넘기지 못하면 손을 떼고 한동안 같은 신호를 보지 않는다
HOLD = 25
COOLDOWN = 30
# 화면에서 사라진 뒤 이만큼 그대로면 끝 (대사 사이·출석부가 뜨기 전 잠깐 비는 때). 신호도 끝났으면 바로
GONE = 2.0


def pending(bot) -> str | None:
    """끼어들기 신호 (패킷). 'attendance' · 'dialog' · None. 화면에 떠 있는지는 shown 이 본다."""
    p = bot.packets
    if not p.ok:
        return None
    s = p.state
    if s.attending():
        return "attendance"
    if s.in_dialogue and not bot.npc_owned():
        return "dialog"
    return None


def shown(bot, what: str, frame) -> bool:
    """what 이 화면에 떠 있나 — 대화 창(tasks.dialogue.View.drawn), 출석은 '출석부 건너뛰기' 와 말풍선 대사도."""
    from ..tasks import dialogue
    if what == "attendance" and (sit.skip_attendance_button(bot, frame) or sit.attendance_bubble(bot, frame)):
        return True
    return dialogue.now(bot, frame).drawn


class Watch:
    """끼어들기 신호를 지켜본다 — 지금 신호, 처음 본 때, 화면을 마지막으로 본 때. Bot.check_interrupt 가 0.1초마다
    부르므로 화면은 여기서 정한 때만 본다."""

    def __init__(self):
        self.what: str | None = None
        self.since = 0.0
        self.looked = 0.0

    def due(self, bot) -> str | None:
        """화면을 볼 때가 된 신호, 아니면 None. 패킷만 본다 — 가볍다."""
        what, now = pending(bot), time.monotonic()
        if what != self.what:
            self.what, self.since, self.looked = what, now, 0.0
        if not what or now - self.looked < (LOOK_EVERY if now - self.since < STALE else LOOK_LATER):
            return None
        self.looked = now
        return what


def handle(bot, what: str) -> bool:
    """what 이 화면에 떠 있으면 하던 일을 멈추고 넘긴다. 무언가 했으면 True, 화면에 없으면 바로 False (기다리지 않는다).
    점검자가 화면을 보고 처리한다 (출석 — 대사 넘기다 건너뛰기, 대화 — 대사 넘기기, 이어 뜨는 퀘스트 클리어 '확인' 도).
    화면에서 사라지면 끝 — 신호가 남아 있어도. HOLD 초 안에 못 넘기면 COOLDOWN 동안 같은 신호를 보지 않는다."""
    frame = bot.frame()
    if not shown(bot, what, frame):
        return False
    from . import Ctx, of
    from ..tasks import dialogue
    mon = of(bot)
    ctx = Ctx(bot.task_id or "interrupt", f"끼어들기 ({what})", revive=False)
    label = {"attendance": "출석", "dialog": "NPC 대화"}.get(what, what)
    bot.log.info(f"끼어들기: {label} 이 화면을 막음 → 하던 일 잠깐 멈춤")
    t0 = time.monotonic()
    gone = None
    done = False
    while True:
        now = time.monotonic()
        if now - t0 > HOLD:
            bot.log.warning(f"끼어들기: {label} 을 넘기지 못함 → {COOLDOWN}초 동안 두고 하던 일로 ({bot.snapshot('interrupt').name})")
            bot.interrupt_cooldown(what, COOLDOWN)
            return done
        if not shown(bot, what, frame):
            gone = gone or now
            if pending(bot) != what or now - gone > GONE:
                break
            bot.sleep(0.4, 0.5)
        else:
            gone = None
            # 메뉴가 뜨는 덩어리면 마치기(메뉴는 ESC, 그 앞 대사는 넘김), 아니면 대사 넘김 (handlers.dialog)
            ctx.leave = what == "dialog" and bool(dialogue.now(bot, frame).menu)
            if mon.check(ctx, frame, guard=False).done:
                done = True
            bot.sleep(0.6, 0.9)
        frame = bot.frame()
    # 대화 뒤 이어 뜨는 '퀘스트 클리어!!' 확인 — 패킷 신호가 없어 화면으로 몇 번 더 본다
    for _ in range(3):
        bot.sleep(0.8, 1.0)
        if not mon.check(ctx, guard=False).done:
            break
    bot.log.info(f"끼어들기: {label} 넘김 ({time.monotonic() - t0:.0f}s) → 하던 일로")
    return True
