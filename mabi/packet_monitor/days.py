"""패킷 하루 기록 — 받은 상태 이벤트를 게임 날짜(오전 6시에 바뀜)별 파일에 남기고, '오늘 이 신호가 있었나' 에 답한다.

리모콘을 켜 두면 숙제를 돌리지 않아도 패킷 감시는 늘 돈다. 그 사이 사람이 한 일(출석 등)을 숙제를 시작할 때 알려면 그날 받은
것을 기억해야 하고, 리모콘을 다시 켜도 남아야 한다 (사용자 2026-11-17). logs\\packets\\<게임 날짜>.jsonl 한 줄에 이벤트 하나 —
{t 시각, ts 시각(초), key 이벤트, char 내 캐릭터 고유 번호, name 내 캐릭터 이름, vals 값}. 오늘과 어제 것만 두고 그 전 것은 지운다.
남기는 것은 우리 판단에 쓰는 이벤트(KEYS)뿐이다 (사용자 2026-11-17 '작업에 필요한 것만 체크·저장').

관찰 기록이기도 하다 — 일시정지 중에도 감시는 돌므로, 이어 할 때 '멈춘 그 단계가 그사이 끝났나' 를 since 로 본다
(사용자 2026-11-22: 캐릭터 바뀜·접속·어느 캐릭터였나까지 남겨 재시작 때 지금 상황을 확실히 알게).
숙제·이어 하기·출석이 묻는 곳은 mabi.observed 하나다 — 기록의 생김새(이벤트·상태 이름)는 거기서만 안다.
"""
import json
import threading
from datetime import datetime, timedelta
from pathlib import Path

from ..profile import RESET_HOUR, game_date

# 출석 끝 신호 후보 (실측 전, 2026-11-23) — 서버가 보내는 출석부 갱신 넷. 출석 대화 시작 뒤 언제 오는지 하루 기록과 로그에
# 남겨, 대화가 끝날 때 오는 것이 있으면 끝 신호로 쓴다 (지금은 끝을 몰라 화면의 말풍선 모양·90초로 짐작한다). 게임이 보내는
# '출석 끝' 메시지는 보내는 쪽 패킷이라 감시가 읽지 않는다
ATTENDANCE_END = ("daily.attendance_update", "daily.attendance_add", "daily.attendance_remove",
                  "daily.attendance_rewardable")
# 하루 기록에 남기는 이벤트 — '오늘 이 신호가 있었나' 를 쓰는 판단이 생기면 여기에 넣는다 (Events._remember 가 거른다).
# 이 밖에 리모콘 쪽 판단(judge.*)은 PacketMonitor.observe 가 남긴다 — 대화 판정 출처끼리 어긋남 judge.dialogue (tasks.dialogue)
KEYS = frozenset({
    "daily.attendance_start",  # 출석 — observed.attendance_today (계정에 하루 한 번)
    *ATTENDANCE_END,           # 출석 끝 신호 후보 (실측 전)
    # 관찰 기록 — 이어 할 때 멈춘 단계가 그사이 끝났는지 (observed 가 묻는다)
    "session.logout_ok",       # 로그아웃 → 캐릭터 선택 화면
    "char.personal_data",      # 접속한 캐릭터 (char 가 새 캐릭터 번호)
    "channel.entering",        # 맵 진입 (channel_name · channel_type)
    "dungeon.state",           # 던전 상태 (state_name: Entering / InProgress / Cleared / NotInDungeon)
    "field.context",           # 사냥터 상태 (state_name: InProgress / WaitingForChannelTransfer = 클리어 / NotInBattlefield)
    "drill.result",            # 나이트메어 드릴 구역 클리어
})
KEEP = 2       # 남기는 게임 날짜 수 (오늘·어제)
TEXT_MAX = 80  # vals 에 남기는 글자 길이 상한 (긴 글·바이트는 남기지 않는다)
ROWS_MAX = 5000  # 기억하는 줄 수 상한 (since 가 본다)


_SAY = {"session.logout_ok": "로그아웃", "char.personal_data": "접속", "daily.attendance_start": "출석",
        "daily.attendance_update": "출석부 갱신", "daily.attendance_add": "출석부 추가",
        "daily.attendance_remove": "출석부 빠짐", "daily.attendance_rewardable": "출석 보상 갱신",
        "channel.entering": "맵", "dungeon.state": "던전", "field.context": "사냥터", "drill.result": "드릴 클리어"}


def describe(row: dict) -> str:
    """관찰 기록 한 줄을 로그 글로 — 'HH:MM:SS 이름 맵 이멘 마하'. 이름을 모르면 캐릭터 번호."""
    v = row.get("vals") or {}
    what = v.get("channel_name") or v.get("state_name") or (f"{v['zone']}구역" if v.get("zone") else "")
    who = row.get("name") or (f"#{row['char']}" if row.get("char") is not None else "")
    return " ".join(x for x in (row.get("t", ""), who, _SAY.get(row["key"], row["key"]), str(what)) if x)


def val(row: dict, name: str):
    """관찰 기록 한 줄의 값 하나 (없으면 None)."""
    return (row.get("vals") or {}).get(name)


def day_start(now: datetime | None = None) -> float:
    """지금 게임 날짜(오전 6시에 바뀜)가 시작된 시각(초) — '오늘 이 캐릭터가 …했나' 를 since 로 물을 때."""
    return datetime.strptime(game_date(now), "%Y-%m-%d").replace(hour=RESET_HOUR).timestamp()


def _oldest_kept(day: str) -> str:
    return (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=KEEP - 1)).strftime("%Y-%m-%d")


class DayLog:
    """오늘 받은 이벤트의 첫 시각을 기억하고 파일에 남긴다. 폴더를 열기 전(open)에는 기억만 한다 (시험·감시를 켜기 전)."""

    def __init__(self):
        self.dir: Path | None = None
        self.day: str | None = None
        self.first: dict[str, str] = {}  # 오늘 key → 처음 받은 시각 'HH:MM:SS'
        self.rows: list[dict] = []  # 남긴 줄 (오늘·어제, ts 가 있는 것) — since 가 본다
        self.names: dict[int, str] = {}  # 캐릭터 번호 → 이름 (접속 직후엔 이름이 아직 안 와 지난 줄에서 채운다)
        self._lock = threading.Lock()

    def open(self, root: Path | None, now: datetime | None = None) -> None:
        """root 폴더에 쓰기 시작 — 오늘 파일을 읽어 기억을 채우고(리모콘을 다시 켜도 오늘 것을 안다) 지난 파일을 지운다."""
        with self._lock:
            self.dir = root
            self._roll(game_date(now))

    def _roll(self, day: str) -> None:
        """게임 날짜가 바뀜 (또는 처음 엶): 기억을 그날 것으로 바꾸고 KEEP 일보다 오래된 파일을 지운다. 잠금 안에서 부른다."""
        self.day, self.first = day, {}
        oldest = _oldest_kept(day)
        if self.dir is None:
            self.rows = [r for r in self.rows if r.get("day", day) >= oldest]
            return
        self.rows = []
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            for f in sorted(self.dir.glob("*.jsonl")):
                if f.stem < oldest:
                    f.unlink(missing_ok=True)
                    continue
                with f.open(encoding="utf-8") as fp:
                    for line in fp:
                        try:
                            row = json.loads(line)
                        except ValueError:
                            continue
                        if not row.get("key"):
                            continue
                        if f.stem == day and row.get("t"):
                            self.first.setdefault(row["key"], row["t"])
                        if row.get("ts"):
                            self.rows.append(row)
                        if row.get("name") and row.get("char") is not None:
                            self.names[row["char"]] = row["name"]
            self.rows = self.rows[-ROWS_MAX:]
        except OSError:
            pass

    def record(self, key: str, vals: dict, char: int | None = None, now: datetime | None = None,
               name: str | None = None) -> None:
        now = now or datetime.now()
        day, t = game_date(now), now.strftime("%H:%M:%S")
        with self._lock:
            if day != self.day:
                self._roll(day)
            self.first.setdefault(key, t)
            row = {"t": t, "ts": round(now.timestamp(), 3), "key": key}
            if char is not None:
                row["char"] = char
                if name:
                    self.names[char] = name
                else:
                    name = self.names.get(char)
            if name:
                row["name"] = name
            v = {k: x for k, x in vals.items()
                 if isinstance(x, (bool, int, float)) or isinstance(x, str) and len(x) <= TEXT_MAX}
            if v:
                row["vals"] = v
            self.rows.append(row if self.dir is not None else {**row, "day": day})
            del self.rows[:-ROWS_MAX]
            if self.dir is None:
                return
            try:
                with (self.dir / f"{day}.jsonl").open("a", encoding="utf-8") as fp:
                    fp.write(json.dumps(row, ensure_ascii=False) + "\n")
            except OSError:
                pass

    def since(self, ts: float, keys=None, char: int | None = None) -> list[dict]:
        """ts(초) 이후에 남긴 줄 (오래된 것부터). keys 를 주면 그 이벤트만, char 를 주면 그 캐릭터 것만."""
        keys = {keys} if isinstance(keys, str) else set(keys) if keys else None
        with self._lock:
            return [r for r in self.rows if r["ts"] >= ts and (keys is None or r["key"] in keys)
                    and (char is None or r.get("char") == char)]

    def today(self, key: str, now: datetime | None = None) -> str | None:
        """오늘(게임 날짜) key 를 처음 받은 시각 'HH:MM:SS', 없으면 None."""
        with self._lock:
            day = game_date(now)
            if day != self.day:
                self._roll(day)
            return self.first.get(key)
