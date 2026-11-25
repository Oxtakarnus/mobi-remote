"""바로 쓸 물품을 짧게 만들 수 있나 — 아르바이트 전달 물품을 CLI 로 만들기 전에 가른다 (실행은 mabi.tasks.cli_make).

사용자 규칙 (2026-11-25): 가공이 5분([arbeit] alter_max_sec) 이하인 것만 알아서 만들고, 넘는 것은 지금처럼 건너뛴다.
시설은 한 번에 하나씩 차례로 가공한다 — 새로 건 가공은 그 시설에 걸려 있는 가공이 다 끝나야 끝난다. 그래서 계획의
가공 시간(차례로 더한 것)에, 계획이 쓰는 시설(새로 걸 곳·곧 들어올 재료를 만드는 곳)에 남은 시간을 더해 본다 (wait_sec).
제작은 바로 끝나 시간에 넣지 않는다. 채집도 넣지 않는다 (한 번에 2분쯤) — 날개 드는 호출 수 상한(max_calls)으로 막는다.
"""
from dataclasses import dataclass

from . import goal

# 못 하는 까닭 (Check.kind)
LONG = "long"        # 가공을 기다릴 시간이 상한을 넘음 (가공 시간을 모르는 것 포함)
SHORT = "short"      # 직접 구해야 하는 재료(상점·드롭 등)·시설 레벨·생활 스킬이 모자람
CALLS = "calls"      # 날개 드는 호출(채집·가공·제작)이 상한을 넘음
UNKNOWN = "unknown"  # 레시피 표에 없음


@dataclass
class Check:
    ok: bool
    kind: str = ""     # 못 하면 까닭 (위 넷)
    why: str = ""
    sec: float = 0     # 가공을 기다릴 시간 어림 (초)
    calls: int = 0     # 날개 드는 호출 수 (수령은 무료라 안 센다)
    wings: int = 0


def wait_sec(snap: dict, p: dict) -> float:
    """계획대로 하면 가공을 기다릴 시간 (초, 넉넉하게). 계획의 가공 시간(serial)에, 새로 가공을 걸 시설과 계획에 쓰일 것을
    가공 중인 시설에 걸려 있는 가공(진행 중·대기)의 남은 시간을 모두 더한다."""
    kn, k = snap["cd"].knowledge, snap["kn"]
    wanted = {p["target"], *(s["product"] for s in p["steps"])}
    use = {s["facility"] for s in p["steps"] if s["via"] == "alter" and s["runs"] > 0}
    left = 0.0
    for f in snap["works"].get("facilities") or []:
        busy = f.get("inProgress") or []
        if f["facility"] in use or any(kn.product_of(w["name"], k) in wanted for w in busy):
            left += sum(w.get("remainingSec") or 0 for w in busy)
    return left + (p["time"]["serial"] or 0)


def _mmss(sec: float) -> str:
    """사람이 읽는 시간 — '8시간 56분' · '5분' · '1분 30초' · '45초'."""
    sec = int(sec)
    if sec >= 3600:
        return f"{sec // 3600}시간" + (f" {sec % 3600 // 60}분" if sec % 3600 >= 60 else "")
    if sec >= 60:
        return f"{sec // 60}분" + (f" {sec % 60}초" if sec % 60 else "")
    return f"{sec}초"


def check(snap: dict, name: str, target: int, limit_sec: float, max_calls: int, p: dict | None = None) -> Check:
    """name 을 target 개까지 (가방+보관함) 알아서 만들어도 되나. snap: goal.snapshot. 조회만 하고 아무것도 하지 않는다."""
    p = p if p is not None else goal.full_plan(snap, name, target)
    if not p.get("ok"):
        return Check(False, UNKNOWN, "레시피 표에 없음")
    if p["missing"] or p["blocked"]:
        return Check(False, SHORT, goal.plan_step(snap, p).get("message") or "만들 수 없음")
    unknown = [s["recipe"] for s in p["steps"] if s["via"] == "alter" and s["runs"] > 0 and s.get("sec") is None]
    if unknown:
        return Check(False, LONG, f"가공 시간을 모름 ({', '.join(unknown)})")
    c = Check(True, sec=wait_sec(snap, p), calls=p["calls"]["total"], wings=p["wings"])
    if c.sec > limit_sec:
        c.ok, c.kind, c.why = False, LONG, f"가공 {_mmss(c.sec)} 걸림 (시설에 걸린 가공 포함, 상한 {_mmss(limit_sec)})"
    elif c.calls > max_calls:
        c.ok, c.kind, c.why = False, CALLS, f"날개 드는 호출 {c.calls}번 (상한 {max_calls}번)"
    return c
