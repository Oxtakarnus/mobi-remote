"""어비스·레이드 입장 창 (둘이 같은 모양) — 입장 창인가 · 버튼 · '우연한 만남' 을 한 곳에서 본다.

입장 창인가는 오른쪽 아래 버튼(입장하기 · 출항하기 · 이동하기) 또는 그 위 '주요 전리품' 으로 본다. 화면 위 가운데
'혼자하기 / 함께하기' 탭은 연속 실행 제한 창이 가리는 자리라 (data/ui.json covers) 판단에 쓰지 않는다
(2026-11-10 친구 PC: 전멸 뒤 입장 창이 떴는데 탭이 가려져 입장 창으로 못 보고 74분 멈춤).
탭·우연한 만남은 누르기만 하고 맞았는지 따로 보지 않는다 — 입장하기 뒤 매칭·로딩 신호가 오나로 안다 (abyss.enter).
예전엔 누른 뒤 탭을 '우연한 만남 스위치가 있나' 로 확인했는데, 스위치는 능력치(마도 저항 등)가 그 난이도 기준에
못 미치면 함께하기에도 안 떠서 탭이 바뀌지 않은 것으로 읽고 실패했다 (2026-11-16 사용자: 입장 창인지만 알면 아는
자리를 누르고 결과로 확인).
"""
import time
from dataclasses import dataclass

from .. import gamedata as gd
from ..bot import Bot
from ..ocr import find_texts, nospace
from ..vision import green_ratio
from . import ui_text
from ..exceptions import CannotProceed

BUTTONS = (("abyss_enter", "enter"), ("raid_sail", "sail"), ("abyss_move", "move"))  # ui.json 문구 → 버튼


def _switch_xy(label) -> tuple[int, int]:
    """'우연한 만남' 글자 가운데 → 스위치 가운데 (ui.json chance_switch_dx)."""
    dx, dy = gd.point("chance_switch_dx")
    return label[0] + dx, label[1] + dy


@dataclass
class Entry:
    button: str  # enter(입장하기) · sail(출항하기) · move(이동하기) · ''(버튼 없음 — 매칭 중 등)
    # '우연한 만남' 스위치 (켜짐, 자리). 없으면 None — 혼자하기 탭이거나, 함께하기여도 능력치가 그 난이도 기준에 못 미침
    chance: tuple[bool, tuple[int, int]] | None

    @property
    def together(self) -> bool:
        return self.chance is not None


def parse(frame) -> Entry | None:
    """이 화면이 입장 창이면 Entry, 아니면 None — 오른쪽 아래를 한 번 읽어(OCR) 버튼·전리품·우연한 만남을 같이 본다.
    매칭 중 화면(필드 + 오른쪽 '우연한 만남' 창)은 버튼도 '주요 전리품' 도 없어 입장 창이 아니다."""
    hits = [(nospace(t), x, y) for t, x, y in find_texts(frame, gd.region("abyss_entry_right"))]
    texts = {t for t, _, _ in hits}
    button = next((b for key, b in BUTTONS if nospace(gd.text(key)) in texts), "")
    if not button and nospace(gd.text("entry_loot")) not in texts:
        return None
    label = next(((x, y) for t, x, y in hits if t == nospace(gd.text("abyss_chance"))), None)
    return Entry(button, (_switch_on(frame, label), _switch_xy(label)) if label else None)


def _switch_on(frame, label: tuple[int, int]) -> bool:
    """스위치가 켜져 있나 (켜지면 초록)."""
    x, y = _switch_xy(label)
    return green_ratio(frame[y - 6:y + 6, x - 20:x + 20], g_min=150, b_max=150) > 0.2  # 스위치 자리에서 잰 기준


def read(bot: Bot) -> Entry | None:
    return parse(bot.frame())


def visible(bot: Bot) -> bool:
    return read(bot) is not None


def wait(bot: Bot, timeout: float) -> Entry | None:
    """입장 창이 뜰 때까지 (최대 timeout 초)."""
    end = time.monotonic() + timeout
    while True:
        e = read(bot)
        if e or time.monotonic() > end:
            return e
        bot.sleep(0.8, 1.2)


def button(bot: Bot) -> str:
    e = read(bot)
    return e.button if e else ""


def describe(bot: Bot, solo: bool) -> str:
    """입장이 시작되지 않았을 때 실패 메모에 붙일 입장 창 모양 — 버튼 · (함께하기면) 우연한 만남, 창이 없으면 닫힘."""
    e = read(bot)
    if e is None:
        return "입장 창이 닫힘"
    parts = [f"버튼 {e.button or '못 읽음'}"]
    if not solo:
        parts.append("우연한 만남 " + ("안 보임" if e.chance is None else "켜짐" if e.chance[0] else "꺼짐"))
    return " · ".join(parts)


def wait_button(bot: Bot, read=None, tries: int = 5) -> str:
    """오른쪽 아래 버튼이 그려질 때까지 몇 번 본다 → 버튼 이름, 끝내 없으면 ''. read: 버튼 읽기 (기본은 이 입장 창의
    button — 나이트메어 드릴 창처럼 버튼 자리만 다른 창은 그 읽기를 넘긴다)."""
    read = read or button
    for _ in range(tries):
        if (got := read(bot)):
            return got
        bot.sleep(1.0, 1.4)
    return ""


def chance_on(bot: Bot, now: Entry | None = None) -> None:
    """함께하기 '우연한 만남' 스위치가 꺼져 있으면 켠다 (어비스·레이드 입장 창이 같은 자리·모양). 누르기만 하고 다시 보지
    않는다 (입장 결과로 안다). 스위치가 없으면 그대로 간다 — 능력치(마도 저항 등)가 그 난이도 기준에 못 미치면 안 뜬다.
    now: 방금 읽은 입장 창 (버튼까지 그려진 것 — 스위치도 같이 그려져 있다). 없으면 버튼이 그려지길 잠깐 기다려 읽는다."""
    e = now or _settled(bot)
    on = e.chance if e else None
    if on is None:
        bot.log.info("'우연한 만남' 이 안 보임 (능력치가 난이도 기준에 못 미치면 안 뜬다) → 그대로 입장")
        return
    if not on[0]:
        bot.click(on[1])
        bot.sleep(1.0, 1.3)
        bot.log.info("우연한 만남 켬")


def chance_off(bot: Bot, now: Entry | None = None) -> None:
    """'우연한 만남' 이 켜져 있으면 끈다 — 고정 파티 파티장은 끄고 들어가야 우리 파티끼리 입장한다 (사용자 11-20).
    파티가 가득 차면 스위치가 안 보일 수 있다 — 그때는 그대로 간다."""
    e = now or _settled(bot)
    on = e.chance if e else None
    if on and on[0]:
        bot.click(on[1])
        bot.sleep(1.0, 1.3)
        bot.log.info("우연한 만남 끔 (고정 파티)")


def _settled(bot: Bot, timeout: float = 3) -> Entry | None:
    """버튼까지 그려진 입장 창 — 스위치는 버튼과 같은 칸이라 버튼이 보이면 같이 그려져 있다. 끝내 버튼이 없으면 마지막 것."""
    end = time.monotonic() + timeout
    while True:
        e = read(bot)
        if (e and e.button) or time.monotonic() > end:
            return e
        bot.sleep(0.5, 0.8)


def set_tab(bot: Bot, solo: bool, shot: str) -> None:
    """탭 글자를 찾아 혼자하기(solo) 또는 함께하기를 누른다 — 누르기만 하고 바뀌었나는 보지 않는다 (입장 결과로 안다).
    글자가 안 보이면: 연속 실행 제한 창이 가렸으면 CannotProceed (게임을 다시 켜야 풀린다), 아니면 누르지 않고 간다."""
    name = "혼자하기" if solo else "함께하기"
    for _ in range(4):
        hit = ui_text.find(bot, gd.text("raid_solo" if solo else "abyss_together"), gd.region("abyss_entry_top"), exact=False)
        if hit:
            bot.click(hit)
            bot.sleep(1.2, 1.6)
            return
        if bot.run_limit_popup():
            raise CannotProceed(f"'{name}' 탭을 누르지 못함 — 연속 실행 제한 창이 탭을 가림 (게임을 다시 켜야 함) "
                                f"→ {bot.snapshot(shot).name}")
        bot.sleep(1.0, 1.4)  # 막 뜬 창이면 다시 본다
    bot.log.info(f"입장 창 '{name}' 탭 글자가 안 보임 → 누르지 않고 진행 (입장 결과로 확인)")
