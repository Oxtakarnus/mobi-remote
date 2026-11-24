"""단계 공용 도우미 — 막히면 다시 하기, 조건까지 기다리기, 스크롤 목록 한 화면씩."""
import time
from typing import Callable

from ..bot import Bot
from ..exceptions import StepTimeout


# 퀘스트 창 → 진행하기 → 이동 단계가 막히면 처음부터 다시 해 보는 횟수. 입구에 사람이 몰려 창이 안 뜨거나
# 창이 지난 스크롤 자리로 열리는 등 한 번 더 하면 되는 일이 많다 (2026-10-26)
STEP_RETRIES = 2
# 목록 맨 위로 올리기를 몇 번까지 거듭할지 (list_views — 한 번 더 올려도 화면이 그대로면 맨 위)
TOP_TRIES = 3


def with_retries(bot: Bot, what: str, fn: Callable, retries: int = STEP_RETRIES):
    """fn() 을 하고, 막히면(StepTimeout·RuntimeError) 메인 화면으로 돌아가 retries 번까지 다시 한다."""
    for attempt in range(retries + 1):
        try:
            return fn()
        except (StepTimeout, RuntimeError) as e:
            if attempt == retries:
                raise
            bot.log.warning(f"{what} 막힘 → 다시 시도 ({attempt + 1}/{retries}): {e}")
            bot.to_main()


def list_views(bot: Bot, area, at, step: int, steps: int):
    """스크롤 목록을 맨 위부터 조금씩 내려가며 한 화면씩 넘겨준다 (yield 때마다 지금 화면을 본다). 더 내려가지 않으면 (맨 아래) 끝.
    한 번에 많이 내리면 가운데 줄을 건너뛴다 (2026-10-25, 미션 선물 7개를 못 보고 넘어감).
    맨 위는 한 번 더 올려도 화면이 그대로일 때다 (TOP_TRIES 번까지). 퀘스트 창은 열린 뒤 게임이 막 갱신된 카드 쪽으로 목록을
    늦게 옮겨 첫 올리기가 묻힌다 — 공물 던전이 은동전 숙제(주간 목표 '던전 클리어' 갱신) 바로 뒤마다 맨 아래부터 찾다
    고난도 카드를 못 봤다 (11-05·11-13·11-17·11-25 모두 은동전 직후, 남은 그림은 맨 아래·주간 목표 카드가 펼쳐진 채).
    area: 목록 영역 [x, y, 너비, 높이] (스크롤해도 안 바뀌면 맨 위·맨 아래), at: 휠을 굴릴 자리, step: 한 번에 내리는 휠 칸 수."""
    def scroll(notches):
        bot.scroll(*at, notches)
        bot.sleep(0.8, 1.0)

    def view():
        return bot.frame()[y:y + h, x:x + w].astype("int16")

    x, y, w, h = area
    scroll(15)
    top = view()
    for _ in range(TOP_TRIES):
        scroll(15)
        now = view()
        if abs(now - top).mean() < 2:
            break
        top = now
    before = None
    for _ in range(steps):
        yield
        now = view()
        if before is not None and abs(now - before).mean() < 2:
            return
        before = now
        scroll(-step)


def wait_until(bot: Bot, pred: Callable[[], bool], timeout: float, interval: float = 3.0, what: str = "") -> None:
    end = time.monotonic() + timeout
    while not pred():
        if time.monotonic() > end:
            raise StepTimeout(f"{timeout:.0f}s 안에 {what or '조건'} 충족 안 됨")
        bot.sleep(interval)
