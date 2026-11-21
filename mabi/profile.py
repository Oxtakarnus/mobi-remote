"""사용자별 설정(숙제할 캐릭터 슬롯)과 하루 단위 진행 기록.

profile.json  : {"slots": [1, 2, 5], "names": {"5": "캐릭터 이름"}}
                처음 실행할 때 입력받아 저장한다 (python run.py --setup 으로 다시 입력).
state/<게임 날짜>.json : {"5": {"weekday_dungeon": "done", "silver": "fail: ..."}}
                게임 하루는 오전 6시에 초기화되므로 6시 이전은 전날로 친다.
"""
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

RESET_HOUR = 6
WEEK_START = 0  # 주간 초기화 요일 (월요일, RESET_HOUR 시) — 임무 게시판 재입고가 목요일 21시에 '3일 이후' (2026-11-19)
KEEP_DAYS = 7  # 하루 기록 파일(state/날짜.json)을 며칠치 남길지


def load_profile(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_profile(path: Path, profile: dict) -> None:
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")


def ask_profile(path: Path, old: dict | None = None) -> dict:
    """콘솔에서 숙제할 슬롯 번호와 (선택) 표시 이름을 입력받는다."""
    print("캐릭터 선택 화면에서 왼쪽 위부터 1, 2, 3, 4 / 다음 줄 5, 6 ... 순서입니다.")
    print("(선택 화면 정렬은 '캐릭터 생성 순'으로 두세요. 정렬이 바뀌면 번호가 달라집니다.)")
    default = ",".join(map(str, old["slots"])) if old else ""
    while True:
        raw = input(f"숙제할 슬롯 번호를 쉼표로 입력 (예: 1,2,3,4,5,6){f' [{default}]' if default else ''}: ").strip()
        raw = raw or default
        try:
            slots = sorted({int(x) for x in raw.replace(" ", "").split(",") if x})
        except ValueError:
            print("숫자와 쉼표만 입력하세요.")
            continue
        if slots and all(s >= 1 for s in slots):
            break
        print("슬롯 번호를 하나 이상 입력하세요.")
    names = dict((old or {}).get("names", {}))
    for s in slots:
        cur = names.get(str(s), "")
        name = input(f"  슬롯 {s} 표시 이름 (생략 가능){f' [{cur}]' if cur else ''}: ").strip() or cur
        if name:
            names[str(s)] = name
    profile = {"slots": slots, "names": {k: v for k, v in names.items() if int(k) in slots}}
    save_profile(path, profile)
    print(f"저장: profile.json  슬롯 {slots}")
    return profile


def characters(profile: dict) -> list[dict]:
    return [{"slot": s, "name": profile.get("names", {}).get(str(s), f"슬롯 {s}")} for s in profile["slots"]]


def chars(paths) -> list[dict]:
    """profile.json 의 캐릭터 목록 [{slot, name}]. 파일이 없으면 빈 목록 (없으면 멈춰야 하는 숙제 실행기는 직접 읽는다)."""
    return characters(load_profile(paths.profile) or {"slots": []})


def game_date(now: datetime | None = None) -> str:
    now = now or datetime.now()
    return (now - timedelta(hours=RESET_HOUR)).strftime("%Y-%m-%d")


def game_week(now: datetime | None = None) -> str:
    """이번 게임 주가 시작된 날 (월요일 게임 날짜, 'YYYY-MM-DD') — 주간 기록의 열쇠."""
    day = datetime.strptime(game_date(now), "%Y-%m-%d")
    return (day - timedelta(days=(day.weekday() - WEEK_START) % 7)).strftime("%Y-%m-%d")


def game_day_start(now: datetime | None = None) -> datetime:
    """오늘 게임 날짜가 시작된 때 (오전 6시, 6시 전이면 전날 6시)."""
    now = now or datetime.now()
    return (now - timedelta(hours=RESET_HOUR)).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=RESET_HOUR)


WEEKLY_TASKS = ("field_boss", "vanguard", "board")  # 주 1번 숙제 — 결과를 state/week-<주 시작일>.json 에도 남긴다
KEEP_WEEKS = 4  # 주간 기록 파일을 몇 주치 남길지


class WeeklyState:
    """이번 게임 주(월요일 오전 6시부터) 캐릭터별 주간 숙제 결과 — 숙제 탭의 주간 숙제 카드가 완료 표시에 쓴다.
    그 주에 한 번 'done' 이 되면 뒤의 다른 결과로 덮지 않는다 (이미 한 것을 다시 확인하다 끊긴 경우)."""

    def __init__(self, state_dir: Path, now: datetime | None = None):
        self.dir = state_dir
        self.week = game_week(now)
        self.path = self.dir / f"week-{self.week}.json"
        self.data: dict = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else self._from_days()

    def _from_days(self) -> dict:
        """주간 파일이 아직 없으면 이번 주 하루 기록(state/날짜.json)에서 모은다 — 이 기록이 생기기 전에 한 것도 보이게."""
        out: dict = {}
        for f in sorted(self.dir.glob("????-??-??.json")) if self.dir.exists() else []:
            if f.stem < self.week:
                continue
            try:
                day = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for slot, rec in day.items():
                if not slot.isdigit() or not isinstance(rec, dict):
                    continue
                for task in WEEKLY_TASKS:
                    if task in rec and out.get(slot, {}).get(task) != "done":
                        out.setdefault(slot, {})[task] = rec[task]
        return out

    def get(self, slot: int, task: str) -> str | None:
        return self.data.get(str(slot), {}).get(task)

    def set(self, slot: int, task: str, status: str) -> None:
        if self.get(slot, task) == "done" and status != "done":
            return
        self.data.setdefault(str(slot), {})[task] = status
        self.dir.mkdir(exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        self.prune()

    def prune(self, keep_weeks: int = KEEP_WEEKS) -> None:
        """keep_weeks 주보다 오래된 주간 기록 파일은 지운다."""
        cutoff = (datetime.strptime(self.week, "%Y-%m-%d") - timedelta(weeks=keep_weeks)).strftime("%Y-%m-%d")
        for f in self.dir.glob("week-????-??-??.json"):
            if f.stem[5:] < cutoff:
                f.unlink(missing_ok=True)


class DailyState:
    """오늘(게임 날짜) 캐릭터별 숙제 결과. 'done' 이면 다음 실행 때 건너뛴다."""

    def __init__(self, state_dir: Path):
        self.dir = state_dir
        self.date = game_date()
        self.path = self.dir / f"{self.date}.json"
        self.data: dict = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.prune()

    def prune(self, keep_days: int = KEEP_DAYS) -> None:
        """keep_days 일보다 오래된 기록 파일은 지운다 (파일 이름이 게임 날짜라 문자열 비교로 충분)."""
        if not self.dir.exists():
            return
        cutoff = (datetime.strptime(self.date, "%Y-%m-%d") - timedelta(days=keep_days)).strftime("%Y-%m-%d")
        for f in self.dir.glob("????-??-??.json"):
            if f.stem < cutoff:
                f.unlink(missing_ok=True)

    def get(self, slot: int, task: str) -> str | None:
        return self.data.get(str(slot), {}).get(task)

    def is_done(self, slot: int, task: str) -> bool:
        """끝남 — 'MANUAL'(할 수 있는 건 다 하고 남은 건 사람이 처리)도 다시 하지 않는다."""
        s = self.get(slot, task)
        return s == "done" or (isinstance(s, str) and s.startswith("MANUAL"))

    def set(self, slot: int, task: str, status: str) -> None:
        self.data.setdefault(str(slot), {})[task] = status
        self._save()
        if task in WEEKLY_TASKS:
            WeeklyState(self.dir).set(slot, task, status)

    def _save(self) -> None:
        self.dir.mkdir(exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 진행 위치: 중단·충돌 뒤 다시 시작하면 이 캐릭터부터 이어 한다
    PROGRESS = "_progress"

    def progress(self) -> dict | None:
        """{"slot", "task", "at"} — 마지막으로 하던 숙제. 실행이 끝까지 돌면 지워진다."""
        return self.data.get(self.PROGRESS)

    def set_progress(self, slot: int, task: str, char: int | None = None) -> None:
        """접속(login)으로 덮을 때는 그 전에 하던 숙제를 'before' 로 남긴다 — 접속의 시작 정리(login._leave_dungeon)가
        끊긴 숙제를 보고 마무리한다 (요일 던전 추가 루팅·은동전 사냥터).
        ts(시각·초)와 char(패킷 캐릭터 고유 번호)도 남긴다 — 이어 할 때 관찰 기록에서 그 뒤 그 캐릭터에게 무슨 일이 있었나 본다."""
        old = self.data.get(self.PROGRESS)
        now = datetime.now()
        rec = {"slot": slot, "task": task, "at": now.strftime("%H:%M:%S"), "ts": round(now.timestamp(), 3)}
        if char is not None:
            rec["char"] = char
        if task == "login" and old:
            before = old.get("before") if old.get("task") == "login" else old
            if before:
                rec["before"] = {k: before[k] for k in ("slot", "task", "at", "ts", "char", "stopped", "step", "stage")
                                  if k in before}
        self.data[self.PROGRESS] = rec
        self._save()

    # ---- 숙제 안의 단계: 'slot' 의 'task' 를 어디까지 했나. 다시 시작하면 그 숙제가 이걸 보고 이어 한다
    STEPS = "_steps"

    def set_step(self, slot: int, task: str, step: str, text: str = "", **data) -> None:
        """step: 단계 키 (각 숙제가 정한 고정 이름, 예 'bh_inside' — 이어 하기는 이걸로 판단), text: 사람이 읽는 설명.
        ts: 그 단계에 들어선 시각(초) — 이어 할 때 그 뒤의 관찰 기록을 본다 (tribute.cut_cleared)."""
        rec = {"step": step, "text": text or step, "at": datetime.now().strftime("%H:%M:%S"), "ts": round(time.time(), 3),
               **data}
        self.data.setdefault(str(slot), {}).setdefault(self.STEPS, {})[task] = rec
        p = self.data.get(self.PROGRESS)
        if p and p.get("slot") == slot and p.get("task") == task:
            p.update(step=step, stage=rec["text"], stage_at=rec["at"])
        self._save()

    def last_step(self, slot: int, task: str) -> dict | None:
        return self.data.get(str(slot), {}).get(self.STEPS, {}).get(task)

    # ---- 캐릭터 상태 표시: 오늘 알게 된 사실 (예 'no_food' — 먹을 음식이 없음)
    FLAGS = "_flags"

    def flag(self, slot: int, key: str) -> bool:
        return key in self.data.get(str(slot), {}).get(self.FLAGS, {})

    def set_flag(self, slot: int, key: str) -> None:
        self.data.setdefault(str(slot), {}).setdefault(self.FLAGS, {})[key] = datetime.now().strftime("%H:%M:%S")
        self._save()

    # ---- 캐릭터별 오늘 횟수 (예 'food' — 음식을 먹은 횟수)
    COUNTS = "_counts"

    def count(self, slot: int, key: str) -> int:
        return self.data.get(str(slot), {}).get(self.COUNTS, {}).get(key, 0)

    def bump(self, slot: int, key: str) -> int:
        counts = self.data.setdefault(str(slot), {}).setdefault(self.COUNTS, {})
        counts[key] = counts.get(key, 0) + 1
        self._save()
        return counts[key]

    def interrupted(self) -> dict | None:
        """끊긴 숙제의 진행 기록 — 이어 하기(runner._arrange)와 접속의 시작 정리(login._leave_dungeon)가 같이 쓴다.
        접속(login) 도중 끊겼으면 그 접속이 이어 하려던 같은 캐릭터의 숙제(before). 다음 캐릭터로 넘어가던 접속이면
        아무것도 안 한 것이라 None (before 는 앞 캐릭터가 끝낸 숙제다)."""
        p = self.progress()
        if not p or p.get("task") != "login":
            return p
        b = p.get("before")
        return b if b and b.get("slot") == p.get("slot") else None

    def mark_stopped(self) -> None:
        """하던 숙제가 멈춤(STOP)으로 끝난 때 — 이어 할 때 그 뒤의 관찰 기록을 본다."""
        p = self.data.get(self.PROGRESS)
        if p is not None:
            p["stopped"] = round(datetime.now().timestamp(), 3)
            self._save()

    def clear_progress(self) -> None:
        if self.data.pop(self.PROGRESS, None) is not None:
            self._save()

    def failed(self, slot: int, task: str) -> bool:
        """오늘 해 봤는데 끝나지 않은 숙제 (FAIL/ERROR/CHECK 등).
        사람이 멈춘 것(STOP)은 실패가 아니다 — 실패로 치면 그 캐릭터가 '실패만 남음'으로 맨 뒤로 밀려
        다시 시작할 때 멈춘 숙제 대신 다음 캐릭터부터 할 수 있었다."""
        s = self.get(slot, task)
        return s is not None and not self.is_done(slot, task) and not (isinstance(s, str) and s.startswith("STOP"))
