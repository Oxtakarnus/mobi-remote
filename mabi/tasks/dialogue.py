"""NPC 대화 — 판단은 View 하나(now), 행동은 next_line(넘기기)·leave(마치기). 아르바이트·요일 던전 게시판·대장간 수리·
접속 정리·끼어들기·점검자가 모두 이것만 묻는다. 예전엔 '대화 중인가' 를 묻는 방식이 네 가지, '메뉴가 떴나' 가 세 가지라
패킷 칸 하나를 잘못 읽은 것이 패킷만 보던 곳에서 한꺼번에 터졌다 (2026-11-22 대화 판정 한 모듈로).

대화 화면은 왼쪽 위 '대화 기록', 넘길 대사가 있으면 오른쪽 위 '대화 넘기기'. 그 자리(arbeit.dialog_next_xy)를 한 번 누르면
대화 덩어리 하나가 통째로 넘어간다 — 3쪽짜리도 한 번 (2026-11-05 로그와 캡처 시각). 메뉴가 있는 덩어리는 메뉴가 뜬 마지막
쪽으로 건너뛰고, 없는 덩어리는 마지막 쪽 뒤 할 일까지 한다. 메뉴 버튼이 떠 있는 동안은 ESC 가 '대화 종료' 이고, 그 뒤
NPC 의 작별 인사는 ESC 로 안 넘어가서 눌러야 끝난다 (2026-10-25 대장간).

출처마다 아는 것 (2026-11-22 아르바이트·게시판·로나 캡처를 다시 풀어 봄 — mabi-packets STATES.md '대화 덩어리 구조'):
  패킷  대본 — 덩어리(step)마다 쪽 수 · 마지막 쪽 뒤 할 일(after) · 선택지 수와 글자 · 조건(why). 쪽 넘김은 패킷이 없다
  CLI   대화 중(IsDialoguePlaying) · 누르면 넘어감(IsDialogueNextAvailable) · 선택 기다림(IsWaitingForSelection)
  화면  창이 그려졌나('대화 기록'·넘기기 버튼 — 반투명이라 밝은 배경에서 안 맞기도 한다) · 버튼 자리
판단 규칙 (여기 한 곳):
  대화 중      패킷 → CLI (Bot.dialogue_playing). 패킷이 모르고 CLI 도 아니라 하면 화면 (open)
  넘길 쪽      메뉴 없는 덩어리는 늘 눌러 넘긴다. 메뉴 덩어리는 1쪽이면 없음, 여러 쪽인데 이 덩어리에서 아직 안 눌렀으면 있음.
               그 밖(누른 뒤·패킷 모름)은 넘기기 버튼(보이면 있음) → CLI
  메뉴 떠 있음  메뉴 덩어리 + 넘길 쪽 없음. 패킷이 모르면 CLI 선택 기다림
  우리 메뉴    선택지 글자(패킷)에 찾는 낱말이 있나. 글자를 모르면 None — 부르는 쪽이 화면 글자로
출처끼리 어긋나면 (창이 그려지고 SETTLE 초 지난 뒤, 덩어리마다 한 번) 실행 로그와 관찰 기록(judge.dialogue)에 출처별 값을
남긴다 (audit). 판단은 바꾸지 않는다. 대사 내용으로는 판단하지 않는다.

대사 넘기기·선택지 고르기·대화 마치기는 점검자(mabi.monitor — Ctx 의 choose · leave)가 한다. 루틴만의 창은 leave() 에
넘기는 처리기(handlers)로 끼워 넣는다 — 처리기가 먼저 자기 화면인지 보고 처리했으면 True. 예: 대장간의 수리 창 ESC.
"""
import time
from functools import cached_property

from ..game_state import Activity

# 덩어리가 온 뒤 이만큼(초) 지나야 출처끼리 견준다 — 창이 그려지고 메뉴 버튼이 1~2초 늦게 뜨는 동안은 어긋나는 게 보통이다
SETTLE = 2.0


def now(bot, frame=None, act: dict | None = None) -> "View":
    """지금 대화를 한 번 본다. frame·act 는 이미 받아 둔 화면·CLI 답 (없으면 물을 때 받는다)."""
    return View(bot, frame, act)


class View:
    """NPC 대화를 한 순간 본 것 — 값은 처음 물을 때 한 번만 구한다 (화면 템플릿·CLI 는 무겁다). 다시 보려면 now() 를 새로."""

    def __init__(self, bot, frame=None, act: dict | None = None):
        self.bot, self._frame, self._act = bot, frame, act

    # ---- 출처

    @cached_property
    def packet(self):
        """대화 칸을 믿을 수 있는 패킷 상태, 아니면 None (감시가 꺼졌거나 켠 뒤 맵에 들어온 적이 없음)."""
        p = self.bot.packets
        return p.state if p.ok and p.state.dialogue_known else None

    @cached_property
    def frame(self):
        return self.bot.frame() if self._frame is None else self._frame

    @cached_property
    def act(self) -> dict | None:
        """CLI get_activity 답. 없으면 None (로딩·끊김)."""
        return self._act if self._act is not None else self.bot.activity()

    @cached_property
    def cli(self) -> Activity:
        return Activity.of(self.act)

    @cached_property
    def skip(self):
        """오른쪽 위 넘기기 버튼 (Bot.skip_button — 대화·장면 어느 쪽이든 (종류, 자리)). 없으면 None."""
        return self.bot.skip_button(self.frame)

    @property
    def skip_xy(self):
        """대화 넘기기 버튼 자리. 장면 넘기기(보스 출현 연출 등)는 아니다 — 그림만 보던 때 그것을 대화로 알고 눌렀다 (2026-10-25)."""
        return self.skip[1] if self.skip and self.skip[0] == "dialog" else None

    # ---- 대화 중·창

    @cached_property
    def talking(self) -> bool:
        """대화 중 (신호) — 패킷 대화 대상, 모르면 CLI. 바쁨 판정과 같은 Bot.dialogue_playing 하나."""
        return self.bot.dialogue_playing(self._act)

    @cached_property
    def drawn(self) -> bool:
        """대화 창이 화면에 그려져 있나 (그림만) — '대화 기록' 또는 대화 넘기기 버튼. 둘 다 반투명이라 하나만 맞아도 된다
        (2026-10-23 부자 NPC: 흰 건물 앞에서 '대화 기록' 0.78). 신호는 대화라는데 이게 아니면 창이 아직 안 그려졌거나(열리는 중)
        끝 신호를 놓친 것 — 각인 강화 창을 열어 둔 채 '대화 중' 신호가 남아 끼어들기가 창 위를 눌렀다 (2026-11-15 00:06~00:12)."""
        return bool(self.bot.vision.find(self.frame, self.bot.cfg["arbeit"]["dialog_log"])) or self.skip_xy is not None

    @cached_property
    def open(self) -> bool:
        """NPC 와 대화 중인가 — 신호(talking)가 대화면 대화, 패킷이 대화가 아니라 하면 아님. 패킷이 모르고 CLI 도 아니라 하면
        화면을 본다 (CLI 는 창이 그려지기 전·후에 어긋날 수 있다)."""
        if self.talking or self.packet is not None:
            return self.talking
        return self.drawn

    @property
    def src(self) -> str:
        """open 을 정한 출처 (로그용)."""
        if self.packet is not None:
            return "packet"
        return "cli" if self.talking else "screen"

    @cached_property
    def ready(self) -> bool:
        """대사를 넘길 수 있게 창이 떴나 — 대화 넘기기 버튼이 보이거나 HUD 가 가려짐 (한 쪽짜리 대사는 버튼이 없다).
        패킷은 창이 그려지기 전에 대화 중이라고 한다 — 그때 넘기기 자리를 누르면 안 먹고 그 자리의 미니맵이 눌릴 수 있다
        (사냥터를 나온 뒤 에반이 찾아왔을 때 넘기기 칸이 생기기 전에 눌러 진행이 안 됨 — 제보 2026-10-27)."""
        return self.skip_xy is not None or not self.bot.at_main(self.frame)

    # ---- 대본 (패킷, 모르면 None)

    @property
    def step(self) -> int | None:
        s = self.packet
        return s.dialogue_step if s is not None else None

    @property
    def after(self) -> str | None:
        """지금 덩어리 뒤 할 일 (SelectKeyword · AcceptQuest · EndDialogue …). 대화가 아니면 '', 모르면 None."""
        s = self.packet
        return s.dialogue_action if s is not None else None

    @property
    def menu(self) -> bool | None:
        """지금 덩어리 마지막 쪽에 메뉴(선택지 버튼)가 뜨나. 모르면 None."""
        s = self.packet
        return s.dialogue_menu if s is not None else None

    @property
    def choices(self) -> tuple[str, ...] | None:
        """선택지 글자 차례대로. 모르면 None."""
        s = self.packet
        return s.dialogue_choices if s is not None else None

    @property
    def pages(self) -> int | None:
        s = self.packet
        return s.dialogue_pages if s is not None else None

    @property
    def why(self) -> tuple[str, ...]:
        s = self.packet
        return s.dialogue_why if s is not None else ()

    @property
    def node(self) -> float | None:
        """지금 덩어리를 가르는 표 (온 때, monotonic). 대화가 아니거나 모르면 None."""
        s = self.packet
        return s.changed_at.get("dialogue") if s is not None and s.in_dialogue else None

    @property
    def taps(self) -> int:
        """이 덩어리에서 넘기기를 누른 수 (tap 이 센다)."""
        node, n = self.bot.marks.talk_taps
        return n if node is not None and node == self.node else 0

    # ---- 판단

    @cached_property
    def _lines(self) -> tuple[bool, str]:
        menu, pages = self.menu, self.pages
        if menu is False:
            return True, "packet"  # 버튼 없는 덩어리 — 눌러 넘긴다 (마지막 쪽 뒤 할 일까지)
        if menu and pages is not None and (pages == 1 or self.taps == 0):
            return pages > 1, "packet"  # 1쪽이면 메뉴가 바로 뜨고, 여러 쪽이면 한 번 눌러 메뉴 쪽으로 건너뛴다
        if self.skip_xy is not None:
            return True, "screen"
        # 버튼은 반투명이라 밝은 배경에서 그림이 안 맞는다 (2026-10-30 던컨 집 지붕 앞 0.48 → 메뉴 버튼만 기다리며 7분 넘게 멈춤)
        a = self.cli
        return a.dialogue_next and not a.selecting, "cli"

    @property
    def lines_left(self) -> bool:
        """메뉴 앞에 눌러 넘길 대사가 남았나 — 남았으면 넘기고, 없으면 메뉴 버튼을 본다 (규칙은 모듈 설명 '넘길 쪽')."""
        return self._lines[0]

    @property
    def lines_src(self) -> str:
        """lines_left 를 정한 출처 — 'packet' 이면 확실하다."""
        return self._lines[1]

    @cached_property
    def menu_up(self) -> bool:
        """메뉴 버튼이 떠 있나 (떠 있으면 고르거나 ESC, 아니면 넘긴다) — 메뉴 덩어리 + 넘길 쪽 없음. 패킷이 모르면 CLI 선택 기다림."""
        if self.menu is not None:
            return self.menu and not self.lines_left
        return self.cli.selecting

    def has(self, *words: str) -> bool | None:
        """선택지 글자(패킷)에 words 중 하나가 든 것이 있나 (띄어쓰기는 보지 않는다). 글자를 모르면 None."""
        c = self.choices
        if c is None:
            return None
        want = ["".join(w.split()) for w in words if w]
        return any(w in "".join(x.split()) for x in c for w in want)

    # ---- 기록

    def sources(self) -> dict:
        """판정에 쓰는 출처별 값 (기록용 — 화면·CLI 까지 다 본다)."""
        s, a = self.packet, self.cli
        return {"step": self.step, "pages": self.pages, "taps": self.taps, "menu": self.menu, "after": self.after or "",
                "type": s.dialogue_type if s is not None else None, "choices": "/".join(self.choices or ()),
                "why": "/".join(self.why), "lines": self.lines_left, "lines_src": self.lines_src, "menu_up": self.menu_up,
                "cli": self.act is not None, "cli_talk": a.dialogue, "cli_next": a.dialogue_next, "cli_sel": a.selecting,
                "skip": self.skip_xy is not None, "drawn": self.drawn}

    def odd(self) -> list[str]:
        """패킷 판정이 CLI·화면과 어긋나는 것 (창이 그려지고 자리를 잡은 뒤에 견줄 것)."""
        out = []
        cli = self.act is not None
        a = self.cli
        if self.lines_src == "packet":
            if not self.lines_left and self.skip_xy is not None:
                out.append("넘길 쪽(화면)")
            if cli and self.lines_left != (a.dialogue_next and not a.selecting):
                out.append("넘길 쪽(CLI)")
        if self.menu is not None and cli and self.menu_up != a.selecting:
            out.append("메뉴(CLI)")
        if cli and not a.dialogue:
            out.append("대화 중(CLI)")
        return out

    def audit(self) -> None:
        """덩어리를 처음 볼 때 출처별 값을 실행 로그(DEBUG)에, 창이 그려지고 SETTLE 초 지난 뒤 한 번 출처끼리 견줘 어긋나면
        실행 로그(INFO)와 관찰 기록(judge.dialogue)에 남긴다. 패킷이 덩어리를 모르면 견줄 것이 없다.
        예전엔 패킷이 '메뉴' 라고 잘못 읽은 것을 CLI 의 '넘길 대사 있음' 이 한 달 가까이 몰래 덮어 아무도 몰랐다 (2026-11-22)."""
        node, bot = self.node, self.bot
        if node is None:
            return
        seen, compared = bot.marks.talk_audit
        if seen == node and compared:
            return
        settled = time.monotonic() - node >= SETTLE and self.drawn
        if seen == node and not settled:
            return
        bot.marks.talk_audit = (node, settled)
        vals = self.sources()
        text = " ".join(f"{k}={v}" for k, v in vals.items())
        odd = self.odd() if settled else []
        if odd:
            bot.log.info(f"대화 판정 어긋남 ({', '.join(odd)}): {text}")
            bot.packets.observe("judge.dialogue", {**vals, "odd": ",".join(odd)})
        else:
            bot.log.debug(f"대화 판정{' (자리 잡음)' if settled else ''}: {text}")


# ---------------------------------------------------------------- 행동

def tap(bot, xy, v: View | None = None) -> None:
    """대화 넘기기 한 번 누름 — 이 덩어리에서 누른 수를 센다 (View.taps → 넘길 쪽 판정)."""
    node = (v or now(bot)).node
    was, n = bot.marks.talk_taps
    bot.marks.talk_taps = (node, n + 1 if node is not None and was == node else 1)
    bot.click(xy)


def wait_next(bot, since: int | None, timeout: float = 4) -> bool | None:
    """대화가 since 다음 덩어리로 넘어가거나 끝날 때까지 (패킷). True 넘어감 / False 그대로 / None 모름."""
    if since is None:
        return None
    return bot.wait_packet(lambda s: s.dialogue_step != since or not s.in_dialogue, timeout)


def next_line(bot, wait: bool = True, ready_within: float = 5) -> bool:
    """대사 덩어리 하나 넘기기 — 대화 창이 뜨길 (ready_within 초까지) 기다렸다가 '대화 넘기기' 자리를 누른다.
    창이 안 뜨면 누르지 않고 False (부르는 쪽이 다음 차례에 다시 본다). 메뉴 덩어리는 눌러도 메뉴 쪽으로 건너뛸 뿐 패킷이
    오지 않으니 다음 덩어리를 기다리지 않는다 (예전엔 3초씩 헛기다렸다 — 2026-11-05 16:18 두 쪽 메뉴)."""
    end = time.monotonic() + ready_within
    while not (v := now(bot)).ready:
        if time.monotonic() > end:
            bot.log.debug("대화 창이 아직 안 떠 대사를 넘기지 않음")
            return False
        bot.sleep(0.3, 0.4)
    before, menu = v.step, v.menu
    tap(bot, tuple(bot.cfg["arbeit"]["dialog_next_xy"]), v)
    if not wait:
        return True
    if menu:
        bot.sleep(0.6, 0.8)  # 메뉴 쪽으로 건너뜀 — 버튼이 그려지는 동안만
    elif wait_next(bot, before, 3) is None:
        bot.sleep(1.0, 1.4)
    return True


def leave(bot, handlers=(), timeout: float = 25) -> None:
    """NPC 대화에서 메인 화면으로. 차례마다 handlers(루틴이 연 창 닫기 등)를 먼저 묻고, 나머지는 점검자가 한다
    (Ctx leave — 메뉴면 ESC '대화 종료', 작별 인사 등 대사면 넘기기). 처리할 것이 없으면 to_main 에 맡긴다."""
    from .. import monitor
    mon = monitor.of(bot)
    ctx = monitor.Ctx(bot.task_id or "npc", "대화 마침", leave=True)
    end = time.monotonic() + timeout
    while not bot.at_main() and time.monotonic() < end:
        if any(h() for h in handlers):
            continue
        if not mon.check(ctx, guard=False).done:
            break
    bot.to_main()
