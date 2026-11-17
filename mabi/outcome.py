"""작업 하나(숙제·반복)가 예외로 끝났을 때 결과를 가르는 공통 규칙 — 일일 숙제(runner)와 어비스·레이드 반복
(daily_api._repeat_launch)이 같이 쓴다. 예전엔 runner 에만 있어 반복은 게임 꺼짐·연속 실행 제한·가방 무게도 모두
'실패' 로만 보고 큐가 다음 카드로 넘어갔다.

결과 상태: OK · STOP(멈춤 — 이어 하기로 계속) · HEAVY(가방 무게) · SKIP(템플릿 없음) · FAIL · ERROR.
FAIL·ERROR 가운데 오류(unexpected — 인식 불가·시간 초과·알 수 없는 예외)는 따로 본다: 실패 뒤 자리를 정리하고(settle)
작업 큐는 그 카드를 맨 아래로 내려 한 번 더 한다 (mabi/workqueue).
"""
import logging

from . import restart
from .bot import Bot
from .exceptions import AuthBlocked, CannotProceed, MissingTemplate, Overweight, SelectStuck, StepTimeout, StopRequested

log = logging.getLogger("mabi")

# 코드가 상황을 알고 낸 실패·멈춤 — 오류가 아니다 (unexpected). CannotProceed: 미해금·장소 없음·재료 없음 등
EXPECTED = (StopRequested, AuthBlocked, Overweight, MissingTemplate, CannotProceed)
SETTLE_WAIT = 60  # 오류 뒤 연출·맵 로딩이 끝나길 기다리는 초 (settle)


def box(bot: Bot, tag: str) -> None:
    """실패한 작업의 직전 30초(화면·누른 것·패킷)를 남긴다 — 남기다 터져도 실패 처리는 이어 간다."""
    try:
        name = bot.dump_box(tag)
    except Exception as e:  # noqa: BLE001
        log.debug(f"블랙박스를 남기지 못함: {e}")
        return
    if name:
        log.info(f"블랙박스: {name}")


def classify(bot: Bot, tag: str, label: str, e: BaseException) -> tuple[str, str, bool]:
    """예외 → (상태, 요약, 화면 정리가 필요한가). 실패면 스냅샷·블랙박스를 남긴다."""
    if isinstance(e, StopRequested):
        log.warning(bot.stopper.reason())
        return "STOP", "", False
    if isinstance(e, AuthBlocked):  # 접속을 더 두드리면 꼬일 수 있다 → 전체를 멈추고 사람에게 넘긴다
        log.error(str(e))
        return "STOP", str(e), False
    if isinstance(e, Overweight):  # 가방 정리가 필요 → 그 캐릭터의 남은 일은 건너뛴다
        log.warning(f"{label}: {e} → 이 캐릭터는 건너뜀")
        return "HEAVY", str(e), False
    if isinstance(e, MissingTemplate):
        return "SKIP", str(e), False
    if isinstance(e, CannotProceed):  # 미해금 등: 실패로 기록하고 다음으로
        return "FAIL", str(e), True
    if isinstance(e, StepTimeout):
        summary = f"{e} → {bot.snapshot(tag).name}"
        box(bot, tag)
        return "FAIL", summary, True
    log.error(label, exc_info=e)  # 한 작업의 알 수 없는 오류가 전체를 멈추지 않도록
    summary = f"{type(e).__name__}: {e} → {bot.snapshot(tag).name}"
    box(bot, tag)
    return "ERROR", summary, True


def recover(bot: Bot) -> None:
    """실패한 작업 뒤 정리: 콘텐츠(던전·어비스·레이드) 안이면 나오고 메인 화면으로 — 다음 작업이 낯선 화면에서 시작하지 않게.
    정리 실패로 다음 작업까지 막지 않는다 (다음 작업이 시작 점검을 한다)."""
    from .tasks.exits import leave_instance
    for what, fn in (("콘텐츠에서 나가기", lambda: leave_instance(bot)), ("메인 화면으로 돌아가기", bot.to_main)):
        try:
            fn()
        except (StepTimeout, MissingTemplate, RuntimeError):  # RuntimeError: 게임 창이 없음 (꺼짐)
            pass
        except Exception:  # noqa: BLE001
            log.exception(f"실패 뒤 {what} 실패")


def unexpected(e: BaseException | None) -> bool:
    """오류(예상 못 한 실패)인가 — 기다리던 화면·신호가 안 옴(인식 불가·시간 초과)이나 알 수 없는 예외.
    코드가 상황을 알고 낸 실패(EXPECTED)는 아니다. 오류 뒤엔 게임이 어떤 화면에 남았는지 모른다."""
    return e is not None and not isinstance(e, EXPECTED)


def settle(bot: Bot, why: str) -> None:
    """오류 뒤 자리 정리 — 다음 일이 이 오류의 뒷자리(연출·로딩·열린 창·콘텐츠 안)에서 시작해 연달아 실패하지 않게.
    연출·맵 로딩이 끝나길 SETTLE_WAIT 초까지 기다리고 (연출 중 로그아웃하자 캐릭터 선택이 먹통이 됐다 — 2026-11-16 12:07),
    콘텐츠에서 나와 메인 화면으로 간다(recover). 그래도 메인 화면이 아니면 게임을 다시 켠다 (restart.now force —
    작업 큐가 돌 때만, 30분에 한 번). 게임이 꺼졌으면 손대지 않는다 (escalate 가 멈춤으로)."""
    try:
        if not bot.window.find():
            return
        bot.wait_packet(lambda s: not s.loading and not s.cutscene, SETTLE_WAIT)
        recover(bot)
        if bot.at_main():
            return
    except StopRequested:  # 멈춤 요청 — 정리도 그만 (다시 켜지 않는다)
        return
    except (StepTimeout, MissingTemplate, RuntimeError) as e:  # RuntimeError: 게임 창이 없음 (꺼짐)
        log.debug(f"오류 뒤 정리 실패: {e}")
    if restart.now(bot, f"{why} 오류 뒤 메인 화면으로 돌아오지 못함", force=True):
        log.warning(f"{why}: 오류 뒤 메인 화면으로 돌아오지 못함 → 게임을 다시 켬")


def after_failure(bot: Bot, e: BaseException, messy: bool, why: str, in_game: bool = True) -> None:
    """실패 뒤 정리 한곳 — 오류면 settle, 아니면 화면 정리가 필요할 때(messy) recover.
    in_game False: 접속 단계의 실패 (게임 밖 화면이라 건드리지 않는다 — 선택 먹통은 escalate 가 다시 켠다)."""
    if not in_game:
        return
    if unexpected(e):
        settle(bot, why)
    elif messy:
        recover(bot)


def escalate(bot: Bot, status: str, summary: str, err: BaseException | None = None) -> tuple[str, str]:
    """실패가 작업 탓이 아니라 게임 탓이면 멈춤으로 바꾼다 — 남은 일마다 같은 실패를 쌓지 않게.
    게임이 꺼짐(튕김·사람이 끔).
    게임 서버와 연결이 끊긴 창(점검 등)이 떠 있으면 남은 일도 다 막힌다 → 게임을 끄고 멈춤 (mabi/restart.server_down —
    보통은 점검자가 먼저 보고 끈다. 여기는 그 전에 실패한 일).
    화면에 연속 실행 제한 창('재시작해주세요')이 떠 있으면 그 창이 가려 실패했을 수 있다 → 작업 큐가 게임을 다시 켜고
    (mabi/restart — 큐가 돌 때·설정이 켜져 있을 때) 이 일은 실패가 아니라 멈춤으로 두어 다시 켠 뒤 그 자리부터 이어 한다.
    다시 켜지 않을 때와 CLI 의 제한 오류는 멈추지 않고 요약에 메모만 붙인다 (2026-11-10 사용자 결정 — 창이 떠 있어도
    일은 계속 됐다).
    err(실패한 예외)가 SelectStuck 이면 캐릭터 선택 화면이 클릭을 받지 않는 것 — 남은 캐릭터도 다 같은 자리에서 막힌다
    (2026-11-16 12:07 다섯 명 연달아) → 창이 없어도 게임을 다시 켜고(force, 30분에 한 번) 멈춤으로 둬 그 자리부터 이어 한다."""
    if status not in ("FAIL", "ERROR"):
        return status, summary
    if not bot.window.find():
        log.error("게임이 꺼짐 → 일시정지 (게임을 켠 뒤 다시 시작하면 이어 함)")
        return "STOP", "게임이 꺼짐 — 게임을 켠 뒤 다시 시작하면 이어 합니다"
    if bot.server_down_popup():
        return "STOP", restart.server_down(bot)
    if bot.run_limit_popup():
        if restart.now(bot, "연속 실행 제한 창이 떠 있는 채 실패"):
            log.warning("실패 — 화면에 연속 실행 제한 창 → 게임을 다시 켠 뒤 이 자리부터 이어 함")
            return "STOP", f"{summary} · 연속 실행 제한 창 → 게임을 다시 켠 뒤 이어 함"
        log.warning("실패 — 화면에 연속 실행 제한 창이 떠 있음 (멈추지 않고 실패만 남김)")
        return status, f"{summary} · 화면에 연속 실행 제한 창이 떠 있음"
    if isinstance(err, SelectStuck) and restart.now(bot, "캐릭터 선택 화면이 눌러도 반응하지 않음", force=True):
        log.warning("실패 — 캐릭터 선택 화면이 클릭을 받지 않음 → 게임을 다시 켠 뒤 이 자리부터 이어 함")
        return "STOP", f"{summary} · 캐릭터 선택이 먹통 → 게임을 다시 켠 뒤 이어 함"
    if bot.cli.run_limited:
        log.warning("실패 — CLI 연속 사용 제한이 걸려 있음 (멈추지 않고 실패만 남김, 게임 안 확인 창을 누르면 풀림)")
        return status, f"{summary} · CLI 연속 사용 제한 걸림"
    return status, summary
