"""모자란 물품을 CLI 로 바로 만든다 — 아르바이트 전달 물품 (사용자 규칙 2026-11-25: 가공이 5분 이하인 것만, craft.quick).

작업 큐 목표 카드(gui_app.queue_api.GoalKind)와 같은 판단(craft.goal.next_step)·실행(craft.execute.execute)·헛돌기 열쇠
(step_key)를 숙제(Bot) 안에서 돌린다. 다른 것:
- 시작 전에 모두 가르고(quick.check) 하나라도 안 되면 아무것도 하지 않는다 — 날개를 쓰고 중간에 서지 않게.
- 어림한 시간에 여유를 더한 만큼만 돈다. 넘으면 그만 (걸어 둔 가공은 시설에서 계속돼 다음 실행에 받는다).
- 멈춤(F12)·숙제 시간 상한을 걸음 사이·기다림·명령 중에 본다. 숙제의 CLI 연결(bot.state.cli)은 리모콘 화면의 F12 가
  끊지 못해(화면의 연결만 끊는다) 명령을 따로 돌리며 지켜보다 멈추면 끊는다 (Connector.cancel).
게임 안 가공 시설 창 길의 가름도 같은 조회·같은 기준으로 한다 (check_alter — 시설에 걸린 가공까지 센다).
"""
import threading
import time
from dataclasses import dataclass

from .. import craft, situation
from ..bot import Bot
from ..cache import QueryCache
from ..craft import goal, quick
from ..craft.execute import STEP_AGAIN, STEP_RETRY_LATER, ExecResult, execute, step_command, step_failure, step_key

FAILED = "failed"   # 하다가 막힘 (Made.kind) — 시작 전에 가른 까닭은 quick.LONG·SHORT·CALLS·UNKNOWN
STUCK_LIMIT = 4     # 같은 걸음이 이만큼 거푸 나오면 헛도는 것 (작업 큐 목표 카드와 같은 값)
WAIT_POLL = 20      # 가공을 기다리며 다시 보는 간격 (초)
COLLECT_RETRY = 10  # 수령이 '완료된 게 없다' 로 거절되면 이만큼 기다렸다 다시 판단 (초, 작업 큐와 같은 값)
# 어림한 가공 기다림에 더하는 여유 (초). 시설로 가는 첫 가공 등록·첫 수령이 30초쯤, 채집 한 번(100개)이 2분쯤 걸린다
# (2026-11-24 커넥터 기록 — 가공 등록 29초·그다음 1초, 수령 35초·그다음 6초, 채집 107~127초)
SLACK = 120
CALL_SLACK = 150


@dataclass
class Made:
    ok: bool
    kind: str = ""  # 못 했으면 까닭 — quick.LONG·SHORT·CALLS·UNKNOWN (시작 전) · FAILED (하다가)
    why: str = ""
    wings: int = 0


def _tools(bot: Bot):
    """(레시피·학습 데이터, 숙제의 CLI 연결, 조회 캐시). 캐시 폴더는 리모콘 화면과 같은 곳 — 서로 새 조회를 같이 본다."""
    cd = craft.data()
    return cd, bot.state.cli, QueryCache(bot.state.cli, cd.data_dir / "cache")


def _snapshot(cd, qc) -> dict:
    """goal.snapshot (조회만). 판단에 쓰는 계산이라 뜻밖의 오류는 조회 실패로 — 아르바이트 숙제 전체를 죽이지 않게."""
    try:
        return goal.snapshot(cd, qc)
    except Exception as e:  # noqa: BLE001
        return {"error": "snapshot_failed", "message": f"상태 읽기 오류: {e}"}


def check(bot: Bot, items: dict[str, int]) -> Made:
    """items {물품: 새로 만들 개수} 를 모두 알아서 만들어도 되나 (조회만 — 무료)."""
    cd, _, qc = _tools(bot)
    return _check_all(bot, _snapshot(cd, qc), items)[0]


def check_alter(bot: Bot, names) -> quick.Check:
    """게임 안 가공 시설 창에서 가공하는 길의 가름 (quick.alter_check — CLI 로 만드는 길과 같은 기준, 조회만 — 무료).
    레시피 시간만으로 안 되거나 표에 없는 이름이면 조회하지 않는다 (가공 시설 창 카드 둘레 글자마다 묻는다 — handlers._alter_go).
    조회가 안 되면 시설 줄을 몰라 레시피 시간만 본다 (그 길은 alter_wait 만큼만 기다린다)."""
    cd, _, qc = _tools(bot)
    limit = bot.cfg["arbeit"]["alter_max_sec"]
    c = quick.alter_check({"cd": cd, "kn": None, "works": {}}, names, limit)
    if not c.ok:
        return c
    snap = _snapshot(cd, qc)
    if snap.get("error") or snap.get("stale"):
        bot.log.info(f"가공 시설 줄을 못 봄 ({snap.get('message') or '조회가 안 됨'}) → 레시피 시간만 봄")
        return c
    return quick.alter_check(snap, names, limit)


def make(bot: Bot, items: dict[str, int]) -> Made:
    """items {물품: 새로 만들 개수} 를 모두 만든다. 먼저 모두 가르고 하나라도 안 되면 아무것도 하지 않는다."""
    cd, cli, qc = _tools(bot)
    m, goals = _check_all(bot, _snapshot(cd, qc), items)
    if not m.ok:
        return m
    spent = 0
    for name, (target, c) in goals.items():
        r = _Maker(bot, cd, cli, qc, name, target, c).run()
        spent += r.wings
        if not r.ok:
            return Made(False, r.kind, r.why, spent)
    return Made(True, wings=spent)


def _check_all(bot: Bot, snap: dict, items: dict[str, int]) -> tuple[Made, dict]:
    """모두 가른다 → (결과, {물품: (목표 보유량, quick.Check)}). 목표는 지금 보유량(가방+보관함)에 새로 만들 개수를 더한 것."""
    if snap.get("error") or snap.get("stale"):  # 옛 조회로는 날개 쓰는 판단을 하지 않는다
        return Made(False, FAILED, snap.get("message") or "조회가 안 됨 (옛 기록뿐)"), {}
    a = bot.cfg["arbeit"]
    goals = {}
    for name, n in items.items():
        target = goal.have(snap, name) + n
        try:
            c = quick.check(snap, name, target, a["alter_max_sec"], a["make_max_calls"])
        except Exception as e:  # noqa: BLE001 — 계획 계산 오류는 그 일만 막힘으로
            return Made(False, FAILED, f"{name}: 계획 오류 {e}"), {}
        if not c.ok:
            return Made(False, c.kind, f"{name}: {c.why}"), {}
        goals[name] = (target, c)
    return Made(True), goals


class _Maker:
    """물품 하나를 목표 보유량까지 — 매 걸음 상태를 새로 읽고 엔진이 정한 한 걸음 (goal.next_step)."""

    def __init__(self, bot: Bot, cd, cli, qc, name: str, target: int, c: quick.Check):
        self.bot, self.cd, self.cli, self.qc, self.name, self.target = bot, cd, cli, qc, name, target
        self.end = time.monotonic() + c.sec + SLACK + c.calls * CALL_SLACK
        self.max_calls = bot.cfg["arbeit"]["make_max_calls"]
        self.spent = self.paid = self.repeat = 0
        self.last, self.waiting = "", ""
        self.start: int | None = None   # 처음 읽은 보유량
        self.made = 0                   # 이 물품을 직접 만든 개수 (제작 결과로 센다)

    def fail(self, why: str) -> Made:
        return Made(False, FAILED, f"{self.name}: {why}", self.spent)

    def run(self) -> Made:
        bot, name = self.bot, self.name
        bot.log.info(f"CLI 로 만들기: {name} → 보유 {self.target}개까지")
        while True:
            snap = _snapshot(self.cd, self.qc)
            if snap.get("error") or snap.get("stale"):
                return self.fail(snap.get("message") or "조회가 안 됨")
            have = self.count(snap)
            try:
                st = goal.next_step(snap, name, self.target)
            except Exception as e:  # noqa: BLE001 — 판단 계산 오류는 이 물품만 막힘으로
                return self.fail(f"판단 오류 {e}")
            kind = st.get("kind")
            if kind == "done":
                bot.log.info(f"CLI 로 만들기: {name} {have}개 — 됨 (날개 {self.spent})")
                return Made(True, wings=self.spent)
            if kind not in ("wait", "collect", "alter", "craft", "gather"):  # blocked·learn — 가를 때 없던 일
                return self.fail(st.get("message") or kind)
            key = step_key(st, have)
            self.repeat = self.repeat + 1 if key == self.last and kind != "wait" else 0
            self.last = key
            if self.repeat >= STUCK_LIMIT:
                return self.fail(f"진전이 없음 — {st.get('name') or kind} {self.repeat + 1}번 거푸")
            left = self.end - time.monotonic()
            if left <= 0:
                return self.fail("어림한 시간이 지남 (걸어 둔 가공은 다음에 받는다)")
            if kind == "wait":
                if st.get("why") != self.waiting:
                    self.waiting = st.get("why") or ""
                    bot.log.info(f"CLI 로 만들기: {self.waiting} (남은 {int(st.get('seconds') or 0)}초)")
                bot.sleep(max(1.0, min(float(st.get("seconds") or WAIT_POLL), left, WAIT_POLL)))
                continue
            self.waiting = ""
            if kind != "collect":
                self.paid += 1
                if self.paid > self.max_calls:
                    return self.fail(f"날개 드는 호출이 {self.max_calls}번을 넘음")
            bot.log.info(f"CLI 로 만들기: {st.get('why') or kind}")
            r = self.execute(st)
            self.spent += r.wings_spent
            if r.ok:
                if kind == "craft" and st.get("product") == name:
                    self.made += produced(r.data, name, (st.get("batch") or 1) * (st.get("per") or 1))
                continue
            what = step_failure(kind, {"error": r.error, "data": r.data})
            if what == STEP_RETRY_LATER:
                bot.sleep(COLLECT_RETRY)
                continue
            if what != STEP_AGAIN:  # 제작 상한을 넘김(AGAIN)은 엔진이 배운 상한으로 다음 걸음에서 맞춘다
                ko = r.ko or {}
                return self.fail(f"{st.get('name') or kind} — {ko.get('text') or r.message or r.error or '알 수 없음'}")

    def count(self, snap: dict) -> int:
        """보유량. 장비·의상은 get_items 에 안 나온다 (CLI 설명 'not equipment/costume/pet', 2026-11-28 아르바이트
        '두꺼운 전투복 장갑 3개' 를 7개 만들고도 0개로 보여 재료 채집까지 갔다) → 직접 만든 개수를 처음 보유량에 더해
        스냅샷 보유량을 그만큼 올려 둔다. 조회에 잡히는 물품은 조회가 더 크거나 같아 그대로다."""
        raw = goal.have(snap, self.name)
        if self.start is None:
            self.start = raw
        if self.start + self.made > raw:
            snap.setdefault("owned", {})[self.name] = self.start + self.made
            return self.start + self.made
        return raw

    def execute(self, st: dict) -> ExecResult:
        """걸음 하나 (게임 명령). 게임 안 창(보상·확인 창, 연속 사용 제한)에 막히면 화면을 정리하고 한 번만 더 —
        가공은 막혀도 날개가 나간다 (작업 큐 _q_exec 와 같은 규칙, 실측)."""
        bot = self.bot
        cmd, body, _ = step_command(st)
        situation.to_main(bot, timeout=30)  # 게임 창이 열린 채 부르면 막힌다 (2026-11-02)
        r = _watched(bot, self.cli, lambda: execute(self.cd, self.cli, self.qc, cmd, body))
        if r.ok or r.error != "blocked":
            return r
        bot.log.info(f"CLI 로 만들기: 게임 창에 막힘 ({r.message or r.error}) → 화면 정리 뒤 한 번 더")
        situation.to_main(bot, timeout=30)
        again = _watched(bot, self.cli, lambda: execute(self.cd, self.cli, self.qc, cmd, body))
        again.wings_spent += r.wings_spent
        return again


def produced(data, name: str, fallback: int) -> int:
    """제작 결과 본문(rewards·criticalRewards)에서 name 이 몇 개 나왔나. 못 읽으면 fallback (회수 × 1회당 개수)."""
    if not isinstance(data, dict):
        return fallback
    n, seen = 0, False
    for key in ("rewards", "criticalRewards"):
        for x in data.get(key) or []:
            if isinstance(x, dict) and x.get("DisplayName", x.get("name")) == name:
                seen = True
                n += int(x.get("Count", x.get("count", 1)) or 0)
    return n if seen else fallback


def _watched(bot: Bot, cli, fn) -> ExecResult:
    """게임 명령 fn() 을 따로 돌리며 멈춤(F12)·숙제 시간 상한을 본다. 멈추면 명령을 끊고(Connector.cancel) 그 멈춤을 그대로
    올린다. 도는 동안 끼어들기(출석·NPC 말 걸기)는 하지 않는다 — 게임 명령이 캐릭터를 움직이는 중에 화면을 누르지 않게.
    명령 쪽 뜻밖의 오류는 그 걸음의 실패로 돌려준다."""
    box: dict = {}

    def run():
        try:
            box["r"] = fn()
        except Exception as e:  # noqa: BLE001
            box["r"] = ExecResult(False, -1, "exception", str(e))

    t = threading.Thread(target=run, daemon=True, name="cli-make")
    t.start()
    try:
        with bot.no_interrupt():
            while t.is_alive():
                bot.sleep(0.3)
    except BaseException:
        cli.cancel()
        t.join(10)
        raise
    return box["r"]
