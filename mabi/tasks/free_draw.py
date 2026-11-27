"""캐시샵 매일 무료 상품 갱신 반복 (기타 숙제): 열어 둔 '매일 무료 상품' 창에서 '상품 갱신' 을 눌러, 노리는 상품이 뜨면 멈춘다
(사용자, 2026-11-27). 어디로 찾아가지 않는다 — 캐시샵 추천 픽 탭은 사람이 열어 둔다.

노리는 것: 의상(이름 + 최소 희귀도) 또는 지정 염색약(색 코드). 목표와 상관없이 특수 물품(연금술 촉매·미가공 골드/데카 원석)이나
엘리트 이상이 떠도 멈춘다 (mabi.freedraw.judge).
결과는 패킷 shop.free_draw (세 칸 시트 행 id) — 누를 때마다 온다 (caps/freedraw1). 거절(갱신권 부족 등)이 오면 멈춘다.
버튼은 글자('상품 갱신')로 찾아 누른다. 누른 뒤 응답이 없으면 (확인 창·창 닫힘 등) 더 누르지 않고 멈춘다.
"""
from .. import freedraw as F
from .. import gamedata as gd
from ..bot import Bot
from ..exceptions import CannotProceed
from ..ocr import find_texts, nospace

PRESS_WAIT = 3.0   # 누른 뒤 새 세 칸을 기다리는 시간
BUTTON = "상품갱신"


def renew_button(bot: Bot) -> tuple[int, int] | None:
    """'상품 갱신' 버튼 가운데 (매일 무료 상품 창이 떠 있을 때), 없으면 None."""
    for t, x, y in find_texts(bot.frame(), gd.region("free_draw_renew")):
        if BUTTON in nospace(t):
            return x, y
    return None


def repeat(bot: Bot, table: dict, target: dict, limit: int, on_try=None) -> dict:
    """멈출 상품이 뜰 때까지 '상품 갱신'. {'tries', 'slot'(0~2), 'why', 'item'(이름)}.
    limit 번 눌러도 안 뜨면 {'tries', 'slot': None}. on_try(tries, [세 칸 이름]) — 한 번 누를 때마다."""
    items = table["items"]
    xy = renew_button(bot)
    if xy is None:
        raise CannotProceed(f"매일 무료 상품 창이 열려 있지 않음 — 캐시샵 추천 픽을 열어 두고 시작하세요 "
                            f"({bot.snapshot('freedraw_none').name})")
    if not bot.packets.ok:
        raise CannotProceed("패킷 감시가 꺼져 있어 뜬 상품을 알 수 없음 — 누르지 않음")
    bot.log.info(f"무료 상품 갱신 반복 — 목표 {describe(target)}, 최대 {limit}번")
    for tries in range(1, limit + 1):
        bot.check_stop()
        mark = bot.packets.mark()
        bot.click_xy(*xy)
        got = bot.packets.wait(("shop.free_draw", "shop.free_draw_renew_fail"), PRESS_WAIT, after=mark)
        if got is None:
            if not bot.packets.ok:
                raise CannotProceed(f"패킷이 끊겨 결과를 알 수 없음 → 멈춤 ({tries - 1}번 갱신)")
            raise CannotProceed(f"눌러도 상품이 바뀌지 않음 — 확인 창·창 닫힘 등 ({tries - 1}번 갱신, "
                                f"{bot.snapshot('freedraw_quiet').name})")
        if got.key == "shop.free_draw_renew_fail":
            raise CannotProceed(f"갱신 거절 — 갱신권 부족 등 ({tries - 1}번 갱신)")
        slots = [items.get(str(got.vals.get(k))) for k in ("slot1", "slot2", "slot3")]
        names = [F.label(s) for s in slots]
        bot.log.info(f"무료 상품 {tries}번째: " + " · ".join(names))
        if on_try:
            on_try(tries, names)
        hit = F.judge(slots, target)
        if hit:
            n, why = hit
            bot.log.info(f"무료 상품 멈춤 — {why}: {names[n]} ({n + 1}번째 칸, {tries}번째 갱신)")
            return {"tries": tries, "slot": n, "why": why, "item": names[n]}
    bot.log.info(f"무료 상품 {limit}번 갱신했지만 목표가 뜨지 않음")
    return {"tries": limit, "slot": None}


def describe(target: dict) -> str:
    if target.get("type") == "costume":
        return f"{target.get('name')} {F.RARITY_KO.get(target.get('min'), '일반')} 이상"
    if target.get("type") == "dye":
        return f"지정 염색약 {target.get('color')}"
    return "특수 물품·엘리트 이상만"
