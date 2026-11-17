"""퀘스트 창(J) — 탭 줄에 걸치지 않은 버튼 고르기, 탭 열기."""
from .. import gamedata as gd, keys
from ..bot import Bot
from ..exceptions import NotSeen, StepTimeout


# 퀘스트 창(J) 아래 탭 줄(지도·퀘스트·아르바이트·이벤트) 윗선 (1920 기준). 카드 버튼이 이 줄에 반쯤 걸쳐 보일 때
# 그 자리를 누르면 버튼 대신 탭('이벤트')이 눌린다 — 공물 던전(2026-10-24 16:48)·알바(17:42, 18:10)에서 따로 터졌다.
# 퀘스트 창의 버튼은 모두 questwin_buttons / questwin_text_ok 로 걸러서 누른다 (안 보이면 목록을 내려서 다시)
QUESTWIN_TAB_BAR_Y = 950


def questwin_buttons(bot: Bot, name: str, region=None) -> list:
    """퀘스트 창에서 템플릿 name 버튼 중 탭 줄에 걸치지 않고 다 보이는 것 (위에서부터)."""
    return sorted((b for b in bot.find_all(name, region=region) if b.y + b.h <= QUESTWIN_TAB_BAR_Y), key=lambda b: b.y)


def questwin_text_ok(y: int) -> bool:
    """OCR 로 찾은 버튼 글자(가운데 y)가 탭 줄에 걸치지 않았나 (버튼 높이 약 60)."""
    return y <= QUESTWIN_TAB_BAR_Y - 30


# 탭 → (그림 템플릿 — config [ui] 키, 탭 글자 — data/ui.json 키). 없는 것은 None
TABS = {
    "arbeit": ("questwin_tab_arbeit", "arbeit_tab"),
    "main": ("questwin_tab_main", None),
    "event": (None, "questwin_event_tab"),
}


def open_tab(bot: Bot, tab: str, timeout: float = 6):
    """퀘스트 창(J)을 열고 tab 탭('arbeit'·'main'·'event')을 누른다 → 누른 자리. 탭을 못 찾으면 None (창은 연 채 —
    이벤트 탭은 이벤트 퀘스트를 다 깨면 없어지므로 부른 쪽이 따진다). 퀘스트 창 탭 열기는 이것 하나로 (2026-11-16 점검:
    아르바이트·공물·주말 퀘스트가 셋이 다르게 열었다).
    그림이 있으면 그림 먼저 — 지난번에 누른 탭 위에 커서가 남아 있으면 탭 그림이 커져 안 맞아 커서를 치운다. 그림이
    가려졌거나(퀘스트 목록이 길면 맨 아래 카드의 '진행하기' 가 탭 아이콘 위에 겹친다 — 2026-10-22 '함께하는 대모험' 카드)
    그림이 없는 탭은 아래 탭 줄의 글자로 (아이콘 쪽은 겹친 버튼이라 글자를 누른다)."""
    from . import ui_text
    template, text = TABS[tab]
    bot.to_main()
    bot.hover_off()
    bot.key(keys.of(bot, "quest"))
    hit = None
    if template:
        try:
            hit = bot.wait(bot.ui[template], timeout=timeout)
        except StepTimeout:
            pass
    if hit is None and text:
        hit = ui_text.wait(bot, gd.text(text), gd.region("questwin_tabs"), timeout=2 if template else timeout, exact=False)
        if hit and template:
            bot.log.debug(f"퀘스트 창 '{gd.text(text)}' 탭 그림이 가려짐 → 탭 글자 {hit} 를 누름")
    if hit is None:
        return None
    bot.click(hit)
    bot.sleep(1, 1.5)
    return hit


def open_arbeit_tab(bot: Bot) -> None:
    """퀘스트 창(J)을 열고 아르바이트 탭으로 (open_tab). 못 찾으면 NotSeen."""
    if not open_tab(bot, "arbeit", timeout=5):
        raise NotSeen(f"퀘스트 창의 아르바이트 탭을 찾지 못함 → {bot.snapshot('questwin').name}")
