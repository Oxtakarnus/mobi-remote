"""임무 게시판 제작 스크롤 (주간 숙제): 네 마을 임무 게시판에서 '제작 스크롤: …' 을 이번 주 살 수 있는 만큼 산다.

흐름 (2026-11-19 직접 해 봄, 사용자 설명):
  게시판까지: 지금 마을(CLI)이 그 마을이면 퀵 내비게이터('.') '일반' 탭 → '임무 게시판' — 마을 안에서 지도(M)를 열면
  캐릭터 둘레만 보여 게시판 아이콘이 화면 밖일 수 있다 (사용자). 다른 곳이면 지도 → 월드맵 → 마을 → 그 지역 맵의
  게시판 아이콘(그림 map_board) → '여기로 가기'(Space). 둘 다 자동 이동 → 빠른 이동(T) → 도착하면 게시판 대화가 저절로 열린다.
  → 메뉴 '임무 목록'(Space) → 대사 한 마디를 넘기면 상점 창 (왼쪽 위 '<마을> 게시판', 오른쪽에 카드가 한 줄에 4장)
  → '제작 스크롤' 카드를 누르면 오른쪽 아래 구입 창 (이름 · '구입 n/3' · 수량 · '구입하기'(Space))
  → Shift+E (+10 — 남은 수만큼으로 맞춰진다) → Space → 구입 성공 패킷(shop.buy_ok) · 구입 창이 닫히고 카드가 '일시 품절'
  → 목록을 내려 다음 카드들 → 다 사면 ESC(상점 닫기) → 작별 인사 → 메인 화면.
살 수 있나: 상점을 열 때 목록 패킷은 오지 않는다 → 카드의 '구입 n/3'·'일시 품절' 글자. 다 산 카드를 눌러도 구입 창은 뜨지만
  버튼이 '구입 조건 필요 아이템 보기' 로 바뀐다 → Space 전에 버튼이 '구입하기' 인지 꼭 본다. 구입 창의 ESC 는 구입 창만 닫는다.
  상점이 열린 채 오른쪽 위 '대화 넘기기' 자리를 누르면 골드 표시가 눌려 '보유한 재화' 창이 뜬다 → 상점이 보이면 대사를 넘기지 않는다.
끝냈나: CLI·패킷에 없다 → 이번 주(월요일 오전 6시부터) 캐릭터마다 다 산 마을을 기록한다 (state/board-week.json).
"""
import re
import time
from dataclasses import dataclass

from .. import gamedata as gd, profile
from ..bot import Bot
from ..exceptions import CannotProceed, NotSeen
from ..ocr import find_texts, nospace
from ..store import JsonStore
from . import dialogue, worldmap
from .arrival import go_talk, quick_nav

BUY, SOLD, UNKNOWN = "buy", "sold", ""
_COUNT = re.compile(r"(\d+)/(\d+)")


@dataclass(frozen=True)
class Card:
    """상점 카드 하나. title 은 제목 줄을 위에서부터 띄어쓰기 없이 이은 것, (x, y) 는 누를 자리(카드 그림),
    state 는 BUY(살 수 있음) · SOLD(이번 주 다 삼) · UNKNOWN(상태 글자를 못 읽음 — 눌러서 구입 창으로 본다)."""
    title: str
    x: int
    y: int
    state: str

    @property
    def key(self) -> str:
        """같은 카드를 알아보는 열쇠 — OCR 이 ':'·'!' 를 섞어 읽어도 같게 한글·영숫자만."""
        return re.sub(r"[^0-9A-Za-z가-힣]", "", self.title)

    @property
    def craft(self) -> bool:
        return gd.text("board_craft") in self.title


def status_of(text: str) -> str | None:
    """카드 상태 글자 → BUY · SOLD · UNKNOWN('구입' 인데 n/m 을 못 읽음). 상태 글자가 아니면 None."""
    t = nospace(text)
    if gd.text("board_soldout") in t:
        return SOLD
    if not t.startswith(gd.text("board_count")):
        return None
    m = _COUNT.search(t)
    if not m:
        return UNKNOWN
    return BUY if int(m[1]) < int(m[2]) else SOLD


def parse_cards(items, region) -> list[Card]:
    """카드 칸 글자들 [(글자, x, y)] → 카드들. 상태 글자('구입 n/3'·'일시 품절') 하나가 카드 하나이고, 제목은 그 위
    board_title_from~to 상자 안의 줄들 (가운데 정렬 — 한 줄이든 두 줄이든). 상태 줄이 칸 안에 들어와야 할 자리인데
    못 읽은 제작 스크롤 제목은 상태 UNKNOWN 카드로 (상태 줄이 칸 밖이면 목록을 내린 뒤에 본다)."""
    (fx, fy), (tx, ty), (cx, cy) = gd.point("board_title_from"), gd.point("board_title_to"), gd.point("board_card_click")
    bottom = region[1] + region[3]
    cards, used = [], set()
    for t, sx, sy in items:
        state = status_of(t)
        if state is None:
            continue
        lines = sorted((y, x, s) for s, x, y in items if sx + fx < x < sx + tx and sy + fy < y < sy + ty)
        used.update((s, x, y) for y, x, s in lines)
        cards.append(Card("".join(nospace(s) for _, _, s in lines), sx + cx, sy + cy, state))
    word = gd.text("board_craft")
    for t, x, y in items:
        if (t, x, y) in used or word not in nospace(t) or y - fy > bottom:
            continue
        sy = y - (fy + ty) // 2  # 상태 줄이 있을 자리 (제목 상자의 가운데에서 거꾸로)
        cards.append(Card(nospace(t), x + cx, sy + cy, UNKNOWN))
    return cards


def visit_order(towns: list[str], here: str | None) -> list[str]:
    """들를 순서 — 지금 있는 마을이 들어 있으면 거기부터 (지도를 열지 않고 퀵 내비게이터로 바로 간다), 나머지는 설정 순서."""
    first = [t for t in towns if worldmap.same_town(t, here)]
    return first + [t for t in towns if t not in first]


class Week:
    """이번 주(월요일 오전 6시부터) 캐릭터마다 다 산 마을 — state/board-week.json {"week": 날짜, "done": {슬롯: [마을]}}.
    주가 바뀌면 지난 기록은 버린다."""

    def __init__(self, path, now=None):
        self.store, self.week = JsonStore(path, {}), profile.game_week(now)

    @classmethod
    def of(cls, bot: Bot) -> "Week":
        return cls(bot.paths.state / "board-week.json")

    def _data(self) -> dict:
        d = self.store.load()
        return d if d.get("week") == self.week else {"week": self.week, "done": {}}

    def done(self, slot) -> list[str]:
        return list(self._data()["done"].get(str(slot), [])) if slot is not None else []

    def add(self, slot, town: str) -> None:
        if slot is None:
            return
        d = self._data()
        towns = d["done"].setdefault(str(slot), [])
        if town not in towns:
            towns.append(town)
        self.store.save(d)


def _slot(bot: Bot):
    return bot.character["slot"] if bot.character else None


def _texts(frame, key: str) -> list[str]:
    return [nospace(t) for t, _, _ in find_texts(frame, gd.region(key))]


def shop_title(bot: Bot, frame=None) -> str | None:
    """상점 창이 열려 있으면 왼쪽 위 제목 ('이멘마하게시판' — 구입 창이 열려 있으면 앞이 잘린다), 아니면 None."""
    title = "".join(_texts(bot.frame() if frame is None else frame, "board_shop_title"))
    return title if gd.text("board_shop") in title else None


# 넓은 칸에서는 글자 찾기가 마을 이름 덩어리를 놓칠 때가 있다 — 그러면 칸을 좁혀 다시 읽는다 (폭, 화면 px).
# 2026-11-26 테스터 PC 콜헨: 420px 칸에서 '게시판' 만 읽혀 다른 마을 상점으로 보고 멈춤. 300·240px 에선 '콜헨게시판'.
# 가장 긴 '이멘마하 게시판' 도 300px 안에 든다
TITLE_NARROW = (300, 240)


def is_town_shop(bot: Bot, town: str, title: str) -> bool:
    """열린 게시판 상점(제목 title)이 town 것인가. 제목에 마을 이름이 없으면 좁은 칸으로 다시 읽어 본다."""
    if worldmap.similar(title, town) >= 0.6:
        return True
    frame = bot.frame()
    x, y, w, h = gd.region("board_shop_title")
    for nw in TITLE_NARROW:
        again = "".join(nospace(t) for t, _, _ in find_texts(frame, (x, y, min(w, nw), h)))
        if worldmap.similar(again, town) >= 0.6:
            bot.log.debug(f"게시판 상점 제목 '{title}' → 좁혀 다시 읽음 '{again}'")
            return True
    return False


def _panel_button(bot: Bot) -> str | None:
    """구입 창(오른쪽 아래)의 버튼 글자 — '구입하기' · 다 산 물품은 '구입 조건 필요 아이템 보기'. 구입 창이 없으면 None.
    창이 열렸나는 이 버튼으로만 본다: 이름 칸은 목록을 내린 위치에 따라 카드 제목이 그 높이에 걸려, 창이 닫혔는데 열린
    것으로 읽었다 (2026-11-19 이멘마하 — 구입은 됐는데 '구입 창이 안 닫힘' 으로 멈춤). 닫히면 그 자리엔 구입·판매 탭뿐이다."""
    for t in _texts(bot.frame(), "board_panel_button"):
        if any(w in t for w in gd.words("board_panel")):
            return t
    return None


def _panel_name(bot: Bot) -> str:
    """열린 구입 창의 물품 이름 (로그용)."""
    return "".join(_texts(bot.frame(), "board_panel_name"))


def _close_panel(bot: Bot, c: dict) -> None:
    """구입 창이 열려 있으면 ESC — 구입 창만 닫힌다."""
    if _panel_button(bot) is not None:
        bot.key("esc")
        _wait(lambda: _panel_button(bot) is None, c["buy_timeout"], bot)


def _wait(cond, timeout: float, bot: Bot) -> bool:
    end = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > end:
            return False
        bot.sleep(0.4, 0.6)
    return True


def go(bot: Bot, town: str, c: dict) -> None:
    """town 의 임무 게시판까지 가서 대화가 열릴 때까지. 지금 그 마을이면 퀵 내비게이터, 아니면 지도의 게시판 아이콘."""
    if worldmap.same_town(worldmap.current_town(bot), town):
        how = "퀵 내비게이터"

        def start():
            bot.click(quick_nav(bot, "board_nav_tab", "board_nav", "board_nav"))
    else:
        how = "지도"

        def start():
            worldmap.pick_icon(bot, town, c["icon"], gd.text("board_nav"), "board_map")
            bot.key("space")  # 여기로 가기
    bot.log.info(f"{town} 임무 게시판으로 ({how})")
    go_talk(bot, start, f"{town} 임무 게시판", "board_go", c["travel_timeout"])


def open_shop(bot: Bot, town: str, c: dict) -> None:
    """게시판 대화에서 '임무 목록' 을 골라 상점 창까지. 고르기·대사 넘기기는 점검자 (Ctx choose). 상점이 보이면 더 넘기지 않는다
    — 넘기기 자리가 상점의 골드 표시다. 다른 마을 게시판이면 NotSeen (퀵 내비게이터는 가까운 게시판으로 간다)."""
    from .. import monitor
    mon = monitor.of(bot)
    ctx = monitor.Ctx("board", f"{town} 임무 게시판", choose=gd.text("board_menu"))
    end = time.monotonic() + c["shop_timeout"]
    while time.monotonic() < end:
        title = shop_title(bot)
        if title is not None:
            if not is_town_shop(bot, town, title):
                raise NotSeen(f"{town} 이 아닌 게시판 상점 ('{title}') → {bot.snapshot('board_town').name}")
            bot.log.info(f"{town} 게시판 상점 열림")
            return
        if mon.check(ctx, guard=False).done:
            _wait(lambda: shop_title(bot) is not None, 3, bot)  # 대사를 넘긴 뒤 상점이 뜨기 전에 또 누르지 않게
        else:
            bot.sleep(0.8, 1.2)
    raise NotSeen(f"{town} 게시판에서 상점 창이 열리지 않음 → {bot.snapshot('board_shop').name}")


def buy(bot: Bot, card: Card, c: dict) -> str | None:
    """카드 하나를 남은 만큼 산다 → 산 물품 이름, 이번 주 다 샀으면 None. 골드 부족 등 실패 패킷이면 CannotProceed."""
    bot.click((card.x, card.y))
    if not _wait(lambda: _panel_button(bot) is not None, c["buy_timeout"], bot):
        raise NotSeen(f"카드 '{card.title}' 를 눌렀는데 구입 창이 안 뜸 → {bot.snapshot('board_panel').name}")
    name = _panel_name(bot) or card.title
    if gd.text("board_buy") not in (_panel_button(bot) or ""):
        bot.log.info(f"{name}: 이번 주 다 삼 (구입 창 버튼이 '구입하기' 가 아님)")
        _close_panel(bot, c)
        return None
    mark = bot.packets.mark()
    bot.key("shift+e")  # +10 — 남은 수만큼으로 맞춰진다
    bot.sleep(0.4, 0.6)
    bot.key("space")    # 구입하기
    end = time.monotonic() + c["buy_timeout"]
    while time.monotonic() < end:
        bot.sleep(0.5, 0.7)
        if bot.packets.find("shop.buy_fail", mark):
            raise CannotProceed(f"{name} 구입 실패 (패킷 — 골드 부족 등) → {bot.snapshot('board_buy_fail').name}")
        if _panel_button(bot) is None:
            ok = "구입 성공 (패킷)" if bot.packets.find("shop.buy_ok", mark) else "구입 창 닫힘"
            bot.log.info(f"{name}: {ok}")
            return name
    raise NotSeen(f"{name} 구입하기 뒤 구입 창이 닫히지 않음 → {bot.snapshot('board_buy').name}")


def _same_view(a: list[int], b: list[int]) -> bool:
    """목록이 그대로인가 — 상태 글자 y 들이 그대로 (글자 위치 흔들림 12px 까지)."""
    return len(a) == len(b) and all(abs(x - y) <= 12 for x, y in zip(a, b))


def _cards(bot: Bot, region, timeout: float) -> list:
    """보이는 카드. 하나도 안 보이면 보일 때까지 기다린다 — 빈 화면은 '모름' 이다 (그리는 중이거나 창이 가림).
    카드가 그려지기 전에 읽으면 목록을 내려 첫 화면 카드를 건너뛰고, 빈 화면 둘을 '목록이 그대로 = 끝' 으로 보면
    그 마을을 이번 주 완료로 적는다 (점검 2026-11-22). 끝내 안 보이면 NotSeen."""
    end = time.monotonic() + timeout
    while not (cards := parse_cards(find_texts(bot.frame(), region), region)):
        if time.monotonic() > end:
            raise NotSeen(f"게시판 상점에 카드가 안 보임 → {bot.snapshot('board_cards').name}")
        bot.sleep(0.4, 0.6)
    return cards


def buy_all(bot: Bot, c: dict) -> list[str]:
    """보이는 제작 스크롤을 다 사고 목록을 내리기를 더 안 내려갈 때까지 → 산 물품 이름들.
    산 카드는 '일시 품절' 로 바뀌어 다시 읽으면 빠진다. 다 산 줄 몰랐던 카드(구입 창 버튼이 다름)는 넘긴다(skip)."""
    region = gd.region("board_cards")
    _close_panel(bot, c)  # 구입 창을 연 채 끊겼다 이어 하면 카드 칸이 가려져 있다
    bought, skip, prev = [], set(), None
    for _ in range(c["max_pages"]):
        for _ in range(12):  # 한 화면 카드 8장 + 다시 읽기 여유
            cards = _cards(bot, region, c["buy_timeout"])
            todo = [k for k in cards if k.craft and k.state != SOLD and k.key not in skip]
            if not todo:
                break
            card = todo[0]
            name = buy(bot, card, c)
            if name:
                bought.append(name)
            else:
                skip.add(card.key)
        else:
            raise NotSeen(f"게시판 카드를 너무 여러 번 눌러 봄 → {bot.snapshot('board_cards').name}")
        ys = sorted(k.y for k in cards)
        if prev is not None and _same_view(prev, ys):
            break  # 더 안 내려감 = 끝
        prev = ys
        bot.scroll(*gd.point("board_scroll"), -c["scroll_notches"])
        bot.sleep(0.8, 1.1)
    return bought


def _close_shop(bot: Bot) -> bool:
    """대화 처리기: 상점(이나 구입 창)이 떠 있으면 ESC — 구입 창이 열려 있으면 그것만 닫혀 한 번 더 온다."""
    if shop_title(bot) is None:
        return False
    bot.key("esc")
    bot.sleep(1.0, 1.4)
    return True


def leave(bot: Bot) -> None:
    """상점 닫기 → 작별 인사 넘기기 → 메인 화면."""
    dialogue.leave(bot, handlers=(lambda: _close_shop(bot),))


def _shop_of(bot: Bot, town: str) -> bool:
    """town 게시판 상점이 이미 열려 있나 (구입 중에 끊겼다 이어 하기). 다른 마을 게시판 상점이면 닫는다."""
    title = shop_title(bot)
    if title is None:
        return False
    if is_town_shop(bot, town, title):
        return True
    leave(bot)
    return False


def run(bot: Bot, cfg: dict) -> str:
    """NPC 대화를 스스로 다루는 일 — 그동안 대화는 끼어들기로 넘기지 않는다 (Bot.npc_talk, monitor.interrupts)."""
    with bot.npc_talk():
        return _task(bot, cfg)


def _task(bot: Bot, cfg: dict) -> str:
    c = cfg["board"]
    week, slot = Week.of(bot), _slot(bot)
    done = week.done(slot)
    left = [t for t in visit_order(c["towns"], worldmap.current_town(bot)) if t not in done]
    if not left:
        return "이번 주 이미 함"
    bot.background = False  # 클릭이 많다 — 게임을 앞에 둔다
    got = []
    for town in left:
        if _shop_of(bot, town):
            bot.log.info(f"{town} 게시판 상점이 이미 열려 있음 → 거기서 이어 함")
        else:
            bot.step("board_go", f"{town} 임무 게시판으로 이동")
            go(bot, town, c)
            open_shop(bot, town, c)
        bot.step("board_buy", f"{town} 게시판 제작 스크롤 사기")
        names = buy_all(bot, c)
        leave(bot)
        week.add(slot, town)
        got.append(f"{town} {len(names)}종")
        bot.log.info(f"{town} 게시판 끝 — 새로 산 것 {len(names)}종{': ' + ', '.join(names) if names else ''}")
    return " · ".join(got)


def verify(bot: Bot, cfg: dict) -> bool:
    return set(cfg["board"]["towns"]) <= set(Week.of(bot).done(_slot(bot)))
