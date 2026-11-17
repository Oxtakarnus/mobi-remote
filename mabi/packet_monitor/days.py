"""패킷 하루 기록 — 받은 상태 이벤트를 게임 날짜(오전 6시에 바뀜)별 파일에 남기고, '오늘 이 신호가 있었나' 에 답한다.

리모콘을 켜 두면 숙제를 돌리지 않아도 패킷 감시는 늘 돈다. 그 사이 사람이 한 일(출석 등)을 숙제를 시작할 때 알려면 그날 받은
것을 기억해야 하고, 리모콘을 다시 켜도 남아야 한다 (사용자 2026-11-17). logs\\packets\\<게임 날짜>.jsonl 한 줄에 이벤트 하나 —
{t 시각, key 이벤트, char 내 캐릭터 고유 번호, vals 값}. 오늘과 어제 것만 두고 그 전 것은 지운다.
남기는 것은 우리 판단에 쓰는 이벤트(KEYS)뿐이다 (사용자 2026-11-17 '작업에 필요한 것만 체크·저장').
"""
import json
import threading
from datetime import datetime, timedelta
from pathlib import Path

from ..profile import game_date

# 하루 기록에 남기는 이벤트 — '오늘 이 신호가 있었나' 를 쓰는 판단이 생기면 여기에 넣는다 (Events._remember 가 거른다)
KEYS = frozenset({
    "daily.attendance_start",  # 출석 — situation.attendance_seen_today (계정에 하루 한 번)
})
KEEP = 2       # 남기는 게임 날짜 수 (오늘·어제)
TEXT_MAX = 80  # vals 에 남기는 글자 길이 상한 (긴 글·바이트는 남기지 않는다)


def _oldest_kept(day: str) -> str:
    return (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=KEEP - 1)).strftime("%Y-%m-%d")


class DayLog:
    """오늘 받은 이벤트의 첫 시각을 기억하고 파일에 남긴다. 폴더를 열기 전(open)에는 기억만 한다 (시험·감시를 켜기 전)."""

    def __init__(self):
        self.dir: Path | None = None
        self.day: str | None = None
        self.first: dict[str, str] = {}  # 오늘 key → 처음 받은 시각 'HH:MM:SS'
        self._lock = threading.Lock()

    def open(self, root: Path | None, now: datetime | None = None) -> None:
        """root 폴더에 쓰기 시작 — 오늘 파일을 읽어 기억을 채우고(리모콘을 다시 켜도 오늘 것을 안다) 지난 파일을 지운다."""
        with self._lock:
            self.dir = root
            self._roll(game_date(now))

    def _roll(self, day: str) -> None:
        """게임 날짜가 바뀜 (또는 처음 엶): 기억을 그날 것으로 바꾸고 KEEP 일보다 오래된 파일을 지운다. 잠금 안에서 부른다."""
        self.day, self.first = day, {}
        if self.dir is None:
            return
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            oldest = _oldest_kept(day)
            for f in self.dir.glob("*.jsonl"):
                if f.stem < oldest:
                    f.unlink(missing_ok=True)
            p = self.dir / f"{day}.jsonl"
            if p.exists():
                with p.open(encoding="utf-8") as fp:
                    for line in fp:
                        try:
                            row = json.loads(line)
                        except ValueError:
                            continue
                        if row.get("key") and row.get("t"):
                            self.first.setdefault(row["key"], row["t"])
        except OSError:
            pass

    def record(self, key: str, vals: dict, char: int | None = None, now: datetime | None = None) -> None:
        now = now or datetime.now()
        day, t = game_date(now), now.strftime("%H:%M:%S")
        with self._lock:
            if day != self.day:
                self._roll(day)
            self.first.setdefault(key, t)
            if self.dir is None:
                return
            row = {"t": t, "key": key}
            if char is not None:
                row["char"] = char
            v = {k: x for k, x in vals.items()
                 if isinstance(x, (bool, int, float)) or isinstance(x, str) and len(x) <= TEXT_MAX}
            if v:
                row["vals"] = v
            try:
                with (self.dir / f"{day}.jsonl").open("a", encoding="utf-8") as fp:
                    fp.write(json.dumps(row, ensure_ascii=False) + "\n")
            except OSError:
                pass

    def today(self, key: str, now: datetime | None = None) -> str | None:
        """오늘(게임 날짜) key 를 처음 받은 시각 'HH:MM:SS', 없으면 None."""
        with self._lock:
            day = game_date(now)
            if day != self.day:
                self._roll(day)
            return self.first.get(key)
