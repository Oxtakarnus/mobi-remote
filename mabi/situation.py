"""지금 게임이 어떤 상황인가 — 어디서 켜도 그 자리에서 다음 단계로 가기 위한 한곳.

상황 판단은 패킷 → CLI → 화면 순서다 (docs/STATUS.md '상태 판단 순서'). 숙제마다 '메인 화면에서 출발' 을 가정하면
전달 창·작별 대사·던전 창·가공 창 앞에 선 채로 시작했을 때 헤맨다 (2026-10-26). look() 이 지금 상황을 한 단어로 주고,
숙제는 그 상황에 맞는 단계부터 한다 (예: 공물 — 심층 던전 창이 이미 열려 있으면 퀘스트 창을 건너뛴다).

출석: 오전 6시(게임 날짜 바뀜)가 지나면 다음에 필드로 나올 때 출석 대사가 뜬다. 접속 단계(login)는 원래 넘겼지만
어비스 반복처럼 캐릭터를 바꾸지 않고 6시를 넘기면 — 쓰러져 나가거나 수리하러 나가는 순간 — 출석 대사에 막혔다
(2026-10-26 사용자). clear_attendance() 를 막는 화면 넘기기(clear.clear_blockers)가 늘 먼저 부른다.
"""
import time

from .profile import game_date
from .exceptions import StepTimeout

# look() 결과
LOADING = "loading"                # 맵 로딩 중 (패킷)
CHARSELECT = "charselect"          # 캐릭터 선택 화면 (패킷, 모르면 그림)
TITLE = "title"                    # 타이틀 화면 ('게임 시작')
ATTENDANCE = "attendance"          # 출석 대사 ('출석부 건너뛰기')
# 출석 대화 신호 중 메인 HUD 가 이만큼(초) 이어서 보이면 대화는 이미 끝났다. 신호는 대사 창보다 1초쯤 먼저 온다
DELIVER = "deliver"                # 아르바이트 물품 '전달하기' 창
DUNGEON_WINDOW = "dungeon_window"  # 던전 입장 창 (일반·심층·요일 탭 중 하나가 선택됨)
CRAFT = "craft"                    # 제작·가공 창 첫 화면 ('설비로 이동')
DIALOG = "dialog"                  # NPC 대화 (패킷, 모르면 '대화 기록'·넘기기 버튼)
FAREWELL = "farewell"              # 대화는 끝났는데(패킷) 작별 대사 화면이 남음 — '대화 넘기기' 자리를 누르면 닫힌다
MAIN = "main"                      # 필드 메인 화면
UNKNOWN = "unknown"

DUNGEON_TABS = {"dungeon_tab_normal_on": "normal", "dungeon_tab_deep_on": "deep", "dungeon_tab_weekday_on": "weekday"}


def _find(bot, frame, name):
    return bool(name) and bot.vision.has(name) and bot.vision.find(frame, name)


def dungeon_tab(bot, frame=None) -> str | None:
    """던전 창이 열려 있으면 선택된 탭 ('normal' · 'deep' · 'weekday'), 아니면 None."""
    frame = bot.frame() if frame is None else frame
    return next((tab for name, tab in DUNGEON_TABS.items() if _find(bot, frame, name)), None)


def look(bot, frame=None) -> str:
    """지금 상황 한 단어. 판정은 점검자의 상황 인식(mabi.monitor.detect) 한곳에서 한다 — 위 상수에 더해
    아르바이트·제작 창 같은 것도 나온다 (detect 의 상수)."""
    from .monitor import detect
    return detect.look(bot, frame).what


# ---------------------------------------------------------------- 출석

ATTEND_KEY = "daily.attendance_start"


def attendance_seen_today(bot) -> str | None:
    """오늘(게임 날짜, 오전 6시부터) 출석 대화가 있었으면 그 시각 (패킷 하루 기록 — 숙제를 안 돌릴 때 사람이 넘긴 것도,
    리모콘을 다시 켜기 전 것도). 없거나 감시가 안 돌면 None. 출석은 계정에 하루 한 번이다 — 11-17 은 06:47 첫 캐릭터에만
    오고 그 뒤 접속한 캐릭터들엔 없었다 (11-12 도 06:11 한 번)."""
    p = bot.packets
    return p.today(ATTEND_KEY) if p.status == "running" else None


def attendance_due(bot) -> bool:
    """오늘(게임 날짜) 출석을 아직 안 넘겼을 수 있나 — 오늘 출석 대화가 없었고(패킷 하루 기록), 리모콘이 오늘 출석을 넘긴
    적이 없고, 이 실행을 시작한 뒤에 게임 날짜가 바뀌었다 (접속 단계는 출석을 따로 넘기고 attendance_done 을 부른다)."""
    if attendance_seen_today(bot):
        return False
    return getattr(bot, "attendance_date", None) not in (None, game_date())


def check_attendance(bot) -> None:
    """작업을 시작할 때 (Bot.check_in): 오늘 출석이 이미 있었으면 넘긴 것으로 하고, 남은 출석 신호(90초)는 화면에 출석이
    없으면 지운다 — 사람이 넘긴 것이다 (사용자 2026-11-17 '오늘 6시 이후 출석 패킷이 있었으니 패스'). 신호가 남아 있으면
    그동안 태스크가 건 NPC 대화를 출석으로 알아 가운데를 누를 수 있다."""
    at = attendance_seen_today(bot)
    if not at:
        return
    attendance_done(bot)
    s = bot.packets.state
    if not s.attending():
        return
    from .tasks.dialogue import dialog_shown
    frame = bot.frame()
    if skip_attendance_button(bot, frame) or dialog_shown(bot, frame):
        return  # 아직 화면에 있다 — 끼어들기가 넘긴다
    s.attendance_at = 0.0
    bot.log.info(f"오늘 출석은 {at} 에 이미 지나감 (패킷 하루 기록) → 남은 출석 신호 지움")


def attendance_done(bot) -> None:
    bot.attendance_date = game_date()


def skip_attendance_button(bot, frame):
    """'출석부 건너뛰기' 버튼 자리 (없으면 None)."""
    return _find(bot, frame, bot.cfg["login"].get("attendance_skip")) or None


def clear_attendance(bot, frame=None) -> str | None:
    """출석 대사를 하나 넘긴다. 넘긴 것의 이름, 없으면 None. 화면에 떠 있을 때만 한다 — 신호만 있으면 아무것도 안 한다.
    - '출석부 건너뛰기' 가 보이면 그것만 누른다 ('대화 넘기기' 는 다른 대사로 이어진다 — 사용자 2026-10-22)
    - 그 전에 NPC 가 버튼 없는 대사를 한두 마디 한다 (몇 마디인지는 무작위 — 사용자 2026-10-27). 패킷이 출석 대화
      시작을 알렸고 대화 창이 떠 있으면 건너뛰기가 뜰 때까지 가운데를 2초에 한 번 눌러 대사를 넘긴다
    - 패킷이 없으면: 날짜가 바뀐 뒤(attendance_due)에 NPC 대화 중이고 대화 창에 넘기기 버튼이 없을 때만 가운데를 누른다
      (4초에 한 번 — 대사가 뜬 뒤 잠깐 입력을 안 받는다)"""
    from .monitor.handlers import Did  # 점검자가 이 모듈을 불러오므로 여기서
    from .tasks.dialogue import dialog_shown
    frame = bot.frame() if frame is None else frame
    c = bot.cfg["login"]
    p = bot.packets
    if (m := skip_attendance_button(bot, frame)):
        bot.click(m)
        attendance_done(bot)
        if p.ok:
            p.state.attendance_at = 0.0  # 끝 패킷을 아직 몰라 넘긴 쪽이 지운다 (안 눌렸으면 건너뛰기가 남아 다시 누른다)
        return "출석부 건너뛰기"
    if p.ok and p.state.attending():
        # 대화 창이 떠 있을 때만 — 패킷은 대사 창이 그려지기 전에 오고(그때 가운데를 누르면 필드의 무언가가 눌린다) 끝 패킷이
        # 없어 90초 남는다. 신호만 보고 기다리던 때는 사용자가 직접 넘긴 출석에 막 시작한 숙제가 25초를 헛기다렸다
        # (2026-11-17 06:49). 창이 그려지면 그때 막힌 것으로 보고 넘긴다 (monitor.interrupts)
        if not dialog_shown(bot, frame):
            return None
        if time.monotonic() - bot.marks.attendance_clicked < 2:
            return Did.ATTEND_WAIT
        bot.marks.attendance_clicked = time.monotonic()
        bot.click(tuple(c["first_dialog_xy"]))
        return Did.ATTEND_LINE
    if not attendance_due(bot):
        return None
    if not (p.ok and p.state.in_dialogue) or bot.skip_button(frame) or not dialog_shown(bot, frame):
        return None
    if time.monotonic() - bot.marks.attendance_clicked < 4:
        return None
    bot.marks.attendance_clicked = time.monotonic()
    bot.log.info("날짜가 바뀐 뒤 버튼 없는 대사 (출석 첫 대사) → 화면 한 번 클릭")
    bot.click(tuple(c["first_dialog_xy"]))
    return "출석 첫 대사"


# ---------------------------------------------------------------- 메인 화면으로

def to_main(bot, timeout: float = 60) -> str:
    """지금 상황에서 메인 화면까지 (어디서 켜도). 마지막 상황을 돌려준다 (MAIN 이면 성공).
    점검자(mabi.monitor)가 남은 대사·확인·전달 창·작별 화면·출석을 정리하고, 그래도 메인이 아니면 ESC (Bot.to_main).
    NPC 대화 도중이면 메뉴(수락·결과 보고)까지 처리한다 — ESC 가 하던 아르바이트를 날리지 않게."""
    from . import monitor
    mon = monitor.of(bot)
    end = time.monotonic() + timeout
    at = look(bot)
    while at != MAIN and time.monotonic() < end:
        if at in (CHARSELECT, TITLE):
            return at  # 게임 밖이거나 사람 몫 — 접속 단계가 따로 한다
        if at == LOADING:
            bot.wait_loaded(max(1, end - time.monotonic()))
        elif not mon.settle(monitor.Ctx("to_main", menus=True)) and look(bot) not in (MAIN, LOADING):
            try:
                bot.to_main(tries=2)
            except StepTimeout:
                pass
        bot.sleep(1.2, 1.6)
        at = look(bot)
    return at
