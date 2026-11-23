"""화면 글자(OCR)로 찾고 누르기 — 여러 작업이 같이 쓴다 (어비스 입장 화면, 대장간 수리 등).

글자는 띄어쓰기를 빼고 비교한다. region 은 [x, y, 너비, 높이] (1920x1080 기준) — 보통 gamedata.region(키).
"""
import difflib
import re
import time

from .. import gamedata as gd
from ..bot import Bot
from ..ocr import find_texts, nospace as norm
from ..exceptions import NotSeen


def is_word(t: str, word: str) -> bool:
    """버튼 글자 word 인가. OCR 이 한 글자쯤 틀리거나 덧붙여도 ('지원하기》') 같다고 본다.
    '지원하기' 와 '진행하기' 는 반만 같아 섞이지 않는다."""
    n, w = norm(t), norm(word)
    return n == w or (len(n) <= len(w) + 2 and difflib.SequenceMatcher(None, n, w).ratio() >= 0.75)


def match(items, want: str, exact: bool = True):
    """이미 읽은 글자들(find_texts 결과 [(글자, x, y)])에서 want 를 찾는다 → (글자, x, y), 없으면 None.
    exact=False 면 want 가 들어 있기만 해도. 한 번 읽은 화면에서 여러 번 찾을 때 (화면 설정 display 등)."""
    w = norm(want)
    for t, x, y in items:
        n = norm(t)
        if n == w if exact else w in n:
            return t, x, y
    return None


def find(bot: Bot, want: str, region=None, exact: bool = True):
    """want 글자의 가운데 (x, y), 없으면 None. exact=False 면 want 가 들어 있기만 해도."""
    hit = match(find_texts(bot.frame(), region), want, exact)
    return hit[1:] if hit else None


def wait(bot: Bot, want: str, region=None, timeout: float = 5, exact: bool = True):
    """want 글자가 보일 때까지 (최대 timeout 초). 자리, 못 찾으면 None."""
    end = time.monotonic() + timeout
    while True:
        hit = find(bot, want, region, exact)
        if hit or time.monotonic() > end:
            return hit
        bot.sleep(0.8, 1.2)


def click(bot: Bot, want: str, region=None, exact: bool = True, what: str = "", tries: int = 4,
          shot: str = "text", key: str | None = None, chosen=None) -> bool:
    """want 글자를 찾아 누른다. tries 번 봐도 없으면 NotSeen (오류 — 큐가 한 번 더, 스크린샷 shot).
    key: 버튼에 단축키가 붙어 있으면 글자로 있는 것만 확인하고 클릭 대신 그 키 (사용자 2026-10-28).
    chosen(frame, items, hit): 선택지(난이도 등)가 이미 골라져 있나 — 참이면 누르지 않는다. 글자를 찾은 그 화면으로 누르기
    전에 한 번 볼 뿐, 누른 뒤 맞았나는 다시 보지 않는다 (결과로 안다). 눌렀으면 True, 골라져 있어 그대로 두면 False."""
    for _ in range(tries):
        if chosen is None:
            hit = find(bot, want, region, exact)
        else:
            frame = bot.frame()
            items = find_texts(frame, region)
            got = match(items, want, exact)
            if got and chosen(frame, items, got):
                bot.log.debug(f"'{what or want}' 가 이미 골라져 있음 → 누르지 않음")
                return False
            hit = got[1:] if got else None
        if hit:
            if key:
                bot.key(key)
            else:
                bot.click(hit)
            bot.sleep(1.2, 1.6)
            return True
        bot.sleep(1.0, 1.4)
    raise NotSeen(f"'{what or want}' 를 화면에서 찾지 못함 → {bot.snapshot(shot).name}")


def open_menu(bot: Bot, text_key: str, what: str, shot: str, menu_open: bool = False) -> None:
    """메인 화면 → 메뉴(ESC) → 오른쪽 메뉴 칸의 text_key 항목(어비스·레이드·나이트메어 드릴·필드 보스)을 누른다.
    ESC 뒤 항목이 안 보이면 ESC 를 먹은 창(메인 HUD 가 보이는 채로 뜬 퀘스트 완료 창 등)을 넘기고 3번까지 다시.
    menu_open 이면 이미 열린 메뉴에서 바로 누른다. 끝내 못 누르면 NotSeen (스크린샷 shot)."""
    want, region = gd.text(text_key), gd.region("menu_right")
    for _ in range(0 if menu_open else 3):
        bot.to_main()
        bot.key("esc")
        bot.sleep(1.5, 1.8)
        if find(bot, want, region):
            break
        bot.clear_blockers(ocr=True)
    click(bot, want, region, what=what, shot=shot)


def read_button(frame, region) -> tuple[int | None, str, str]:
    """숫자와 한글이 섞인 버튼('20 입장하기', '10 임무 시작', '2층 3구역 진입') → (가격, Windows 글자, 한글 글자).
    숫자는 Windows OCR, 한글은 RapidOCR 로 읽는다 (ocr.py 머리말). 가격은 버튼 글자의 마지막 숫자."""
    from ..ocr import read_ko, read_text
    win, ko = read_text(frame, region), read_ko(frame, region)
    nums = re.findall(r"\d+", win)
    return (int(nums[-1]) if nums else None), win, ko


def has_word(word: str, *texts: str) -> bool:
    """한글 단어가 읽은 글자들 중 하나에 있는지 (띄어쓰기 무시)."""
    from ..ocr import nospace
    w = nospace(word)
    return any(w in nospace(t) for t in texts)
