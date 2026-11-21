"""관찰 기록(패킷 하루 기록 — logs\\packets\\<게임 날짜>.jsonl)에 묻는 곳. 숙제·이어 하기·출석이 '오늘·멈춘 뒤 그
캐릭터에게 무슨 일이 있었나' 는 여기서만 묻는다 — 이벤트 이름·상태 값·맵 종류 같은 기록의 생김새는 이 모듈만 안다
(사용자 2026-11-22: 관찰 기록 확인은 한 모듈에서).

남기는 쪽은 packet_monitor (Events._remember → days.DayLog, 줄마다 시각·캐릭터 번호·이름). '없음' 을 믿어도 되나(감시를
켠 때·흐름이 끊긴 때)는 PacketMonitor.seen_since 가 가린다. 그래서 '그 뒤에 있었나' 의 답은 셋이다 — 찾은 줄(받은 것은
사실) · False(빠짐없이 봤는데 없음) · None(모름 — 부르는 쪽이 예전 규칙으로).
찾은 줄을 로그 글로 바꾸는 것은 describe (부르는 쪽도 observed.describe 로).
"""
from . import gamedata as gd
from .packet_monitor.days import day_start, describe, val
from .place import OPEN_MAPS

ATTEND = "daily.attendance_start"
# 끊긴 판을 떠났다고 볼 이벤트 — 로그아웃 · 다른 캐릭터로 접속 · 던전이 아닌 맵(마을 등) 진입 (left_since)
_LEFT = ("session.logout_ok", "char.personal_data", "channel.entering")
_FIELD_CLEARED = "WaitingForChannelTransfer"  # 사냥터 상태 — 클리어하면 채널 옮김 대기로 바뀐다


# ---- 오늘 (게임 날짜, 오전 6시부터)

def attendance_today(bot) -> str | None:
    """오늘 출석 대화가 있었으면 그 시각 — 숙제를 안 돌릴 때 사람이 넘긴 것도, 리모콘을 다시 켜기 전 것도. 없거나 감시가
    안 돌면 None. 출석은 계정에 하루 한 번이다 — 11-17 은 06:47 첫 캐릭터에만 오고 그 뒤 접속한 캐릭터들엔 없었다
    (11-12 도 06:11 한 번)."""
    p = bot.packets
    return p.today(ATTEND) if p.status == "running" else None


def deep_cleared_today(bot) -> str:
    """오늘 지금 캐릭터가 심층 던전을 깬 때 '시각 맵 이름' (없거나 모르면 "") — deep_cleared_since."""
    return deep_cleared_since(bot, day_start())


# ---- 멈춘 뒤

def stopped_at(daily) -> float | None:
    """멈춘 때(초) — 끊긴 숙제(DailyState.interrupted)의 멈춤 시각, 없으면 지금 진행 기록의 멈춤 시각 (숙제 도중 리모콘이
    꺼져 멈춤 기록이 없고, 그 숙제를 이어 하려던 접속 도중 멈춤). 모르면 None.
    이어 하기 순서(runner)와 끊긴 판 판단(login.cut_task)이 같은 때부터 본다."""
    if not daily:
        return None
    return (daily.interrupted() or {}).get("stopped") or (daily.progress() or {}).get("stopped")


def left_since(bot, ts: float | None, char: int | None) -> dict | bool | None:
    """ts 뒤 끊긴 판을 떠난 일 — 로그아웃 · char 가 아닌 캐릭터로 접속 · 던전이 아닌 맵(마을 등) 진입. 던전·어비스 같은
    콘텐츠 맵 진입은 끊긴 판으로 들어간 것이라 떠난 게 아니다 (입장 로딩 중에 멈춤). char 를 모르면 접속은 보지 않는다."""
    def left(r: dict) -> bool:
        if r["key"] == "channel.entering":
            return val(r, "channel_type") in OPEN_MAPS
        if r["key"] == "char.personal_data":
            return char is not None and r.get("char") != char
        return True  # 로그아웃
    return bot.packets.seen_since(ts, _LEFT, check=left)


def field_cleared_since(bot, ts: float | None, char: int | None) -> dict | bool | None:
    """ts 뒤 그 캐릭터가 사냥터를 깼나 (클리어 뒤 채널 옮김 대기). 캐릭터를 모르면 None — 다른 캐릭터의 클리어를 셀 수 있다."""
    if char is None:
        return None
    return bot.packets.seen_since(ts, "field.context", char, lambda r: val(r, "state_name") == _FIELD_CLEARED)


def deep_cleared_since(bot, after: float | None) -> str:
    """after(초) 뒤 지금 캐릭터가 심층 던전을 깬 때 '시각 맵 이름' (없거나 모르면 ""). 심층 던전 맵 이름엔 '심층' 이 들고
    난이도는 없다 (예 '페카 2-1 심층 던전'). 들어간 맵 이름은 after 앞의 줄에서도 찾는다 — 던전 단계 기록보다 맵 진입이
    먼저 온다."""
    char = bot.packets.state.char_id if bot.packets.ok else None
    if char is None or not after:
        return ""
    deep, where = gd.text("dungeon_deep"), ""
    for r in bot.packets.days.since(day_start(), ("channel.entering", "dungeon.state"), char):
        if r["key"] == "channel.entering":
            where = val(r, "channel_name") or ""
        elif val(r, "state_name") == "Cleared" and deep in where and r.get("ts", 0) >= after:
            return f"{r['t']} {where}"
    return ""


def since_line(bot, ts: float | None, limit: int = 12) -> str:
    """ts 뒤 관찰한 일을 로그 한 줄로 — 누구 것이든 최근 limit 건. 없으면 ""."""
    seen = bot.packets.days.since(ts) if ts else []
    if not seen:
        return ""
    more = f" (앞 {len(seen) - limit}건 생략)" if len(seen) > limit else ""
    return " · ".join(describe(r) for r in seen[-limit:]) + more
