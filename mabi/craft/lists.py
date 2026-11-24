"""레시피 수확(harvest_recipes — 화면 목록을 볼 때마다)과 가공 작업 현황(altering_works — 목표 판단용).

레시피는 게임 데이터에서 뽑은 표(recipes.json)가 전부 갖고 있다. 수확은 표에 없는 레시피(패치로 새로 생긴 것)만
게임이 흘린 부족분으로 배워 둔다. 학습 실패는 조회를 막지 않는다.
kw 는 QueryCache.get 인자 (refresh, offline, max_age).
"""
from ..query import _fail


def harvest_recipes(cd, rows: list, kind: str, ok_key: str, per_key: str) -> None:
    """표에 없는 레시피만 게임이 알려 준 부족분으로 배운다 (부족분뿐이라 partial — 1회 만들어 보면 완성된다)."""
    kn = cd.knowledge
    for r in rows:
        if r.get(ok_key) or not r.get("MissingIngredients") or cd.recipes.has(r.get("DisplayName")):
            continue
        try:
            kn.learn_recipe_from_missing(r["DisplayName"], kind, r["MissingIngredients"], r.get(per_key))
        except Exception:
            pass  # 학습 실패가 조회를 막으면 안 된다


def collect_name(fac: dict) -> str | None:
    """그 시설 완료분을 받을 때 complete_altering_work 에 넘길 이름. 커넥터는 이름으로 시설을 고르는데, 그 이름의 가공이
    아직 남아 있으면(진행 중·대기) 완료분이 있어도 not_completed_yet 으로 거절한다 (2026-11-25 06:33 은합금괴 — 하나는 완료,
    하나는 진행 중이라 전체 수령이 그 시설만 실패). → 완료됐고 같은 이름이 남아 있지 않은 것. 없으면 None (남은 같은 이름이
    끝나야 받을 수 있다). fac: altering_works 의 시설 한 줄 {completed: [{name}], inProgress: [{name}]}."""
    left = {w.get("name") for w in fac.get("inProgress") or []}
    return next((w["name"] for w in fac.get("completed") or [] if w.get("name") and w["name"] not in left), None)


def altering_works(cd, qc, **kw) -> dict:
    """가공 작업 현황. 완료분은 시설별로 묶어야 complete_altering_work 를 시설당 1회만 부른다.
    아이템↔시설 매핑과 시설별 칸 수는 여기서만 알 수 있어 볼 때마다 쌓는다.
    {completed_count, in_progress_count, total, facilities: [{facility, completed:[], inProgress:[], collect}], room, works}"""
    kn = cd.knowledge
    res = qc.get("get_altering_works", **kw)
    if not res.get("data"):
        return _fail(res)
    works = res["data"].get("works") or [] if isinstance(res["data"], dict) else []
    try:
        kn.learn_from_altering_works(res["data"])
    except Exception:
        pass  # 학습 실패는 조회를 막지 않는다

    by: dict[str, dict] = {}
    for w in works:
        key = w.get("FacilityName") or "(시설 미상)"
        e = by.setdefault(key, {"facility": key, "completed": [], "inProgress": []})
        row = {"name": w.get("DisplayName"), "state": w.get("State"), "remainingSec": w.get("RemainingSeconds")}
        (e["completed"] if w.get("IsCompleted") else e["inProgress"]).append(row)
    for e in by.values():
        e["collect"] = collect_name(e)  # 받기에 넘길 이름 (없으면 지금은 못 받음 — 화면 수령 버튼도 이것)

    return {"completed_count": res["data"].get("completedCount") or sum(1 for w in works if w.get("IsCompleted")),
            "in_progress_count": sum(1 for w in works if not w.get("IsCompleted")), "total": len(works),
            "cached": res.get("cached", False), "stale": bool(res.get("stale")),
            "facilities": sorted(by.values(), key=lambda f: -len(f["completed"])),
            "room": kn.room_report(res["data"]),
            "works": [{"name": w.get("DisplayName"), "facility": w.get("FacilityName"), "state": w.get("State"),
                       "done": bool(w.get("IsCompleted")), "remainingSec": w.get("RemainingSeconds")} for w in works]}
