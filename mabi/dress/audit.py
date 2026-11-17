"""드레스룸 전체 의상 점검 — 목록의 모든 모델을 지금 코드로 꺼내 보고 깨질 만한 것을 줄마다 적는다 (tools/dress_audit.py).

쓰는 법 (저장소 폴더에서. 게임이 깔려 있어야 하고, 꺼낸 자료가 2GB 쯤이라 저장소·사용자 dressroom 폴더 밖 작업 폴더에):
  .venv/Scripts/python.exe tools/dress_audit.py <작업 폴더> [--jobs 4] [--fresh]   모두 꺼내 보고 요약
  .venv/Scripts/python.exe tools/dress_audit.py <작업 폴더> --report [보기 수]     지난 결과 요약만
  .venv/Scripts/python.exe tools/dress_audit.py <작업 폴더> --show <모델 id> ...    메시 → 재질 배정과 재질 값
작업 폴더에 cache\\ (꺼낸 모델 — 드레스룸 데이터 폴더와 같은 모양)와 audit_<k>.jsonl (일꾼마다 결과)이 생긴다.
끊긴 뒤 다시 돌리면 본 모델은 건너뛴다. 코드를 고친 뒤 처음부터 보려면 --fresh — 결과 파일(audit_*.jsonl)만 지운다.
꺼낸 모델은 service.FORMAT 을 올렸으면 서비스가 비우고, 안 올렸으면 그대로 쓰므로 그때는 cache\\models 를 손으로 지운다.
일꾼은 보통 아래 우선순위로 돈다 (게임이 켜져 있어도). 4 일꾼으로 5,400벌에 5분쯤 (디스크가 데워진 뒤).

줄의 issues:
  partial:<문제 첫 줄>              그림·재질 일부를 못 읽고 꺼냄 (빠진 CAB 등)
  skin-mesh-not-skin:<메시>:<재질>  옷의 피부 조각(Mesh_Skin_*)에 피부 아닌 재질 — 목·가슴이 하얗게 나온다
  color-no-tex:<메시>:<재질>        그림 없이 단색인 재질 — 대부분 의도된 것(눈 빛·화살·유리·가이드 옷)
error 칸은 꺼내다 실패한 것 (tb 에 끝 부분). 기준선은 docs/DRESSROOM.md '점검 기준선'.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path

KINDS = ("error", "partial", "skin-mesh-not-skin", "color-no-tex")


def check(meta: dict, partial: str | None = None) -> list[str]:
    """꺼낸 모델 json 하나의 문제 목록. partial: <id>.partial 내용 (없으면 None)."""
    issues = []
    mats = meta.get("materials") or []
    for me in meta.get("meshes") or []:
        for g in me.get("groups") or []:
            ma = mats[g["mat"]]
            if me.get("skin") and not ma.get("skin"):
                issues.append(f"skin-mesh-not-skin:{me['name']}:{ma['name']}")
            # 'body' 는 그림 없는 몸 자리 재질, *Lit* 는 기본 머티리얼(풍선껌 등) — 단색이 맞다
            if not ma.get("skin") and ma.get("kind") == "color" and not ma.get("gem") \
                    and ma["name"] != "body" and "Lit" not in ma["name"]:
                issues.append(f"color-no-tex:{me['name']}:{ma['name']}")
    if partial is not None:
        issues.append("partial:" + (partial.strip().splitlines() or [""])[0][:160])
    return issues


def rows(work: Path) -> list[dict]:
    out = []
    for f in sorted(work.glob("audit_*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass   # 끊길 때 반쯤 쓴 줄
    return out


def summary(rs: list[dict]) -> dict:
    """종류별 건수 {종류: n} (error 포함, 0 인 종류도)."""
    n = dict.fromkeys(KINDS, 0)
    for r in rs:
        if "error" in r:
            n["error"] += 1
        for i in r.get("issues", []):
            n[i.split(":", 1)[0]] += 1
    return n


def report(work: Path, show: int = 6) -> None:
    rs = rows(work)
    n = summary(rs)
    print(f"모델 {len(rs)}벌 — " + " · ".join(f"{k} {v}" for k, v in n.items()))
    for r in [r for r in rs if "error" in r][:show * 3]:
        print(f"  error {r['id']}: {r['error'][:160]}")
    for kind in KINDS[1:]:
        by = collections.defaultdict(list)   # 같은 재질·같은 빠진 CAB 끼리 묶어 본다
        for r in rs:
            for i in r.get("issues", []):
                if i.startswith(kind + ":"):
                    rest = i.split(":", 1)[1]
                    key = rest.rsplit(":", 1)[-1] if kind != "partial" else re.sub(r"^.*?(cab-[0-9a-f]+).*$", r"\1", rest)
                    by[key].append(r["id"])
        if not by:
            continue
        print(f"== {kind} — 묶음 {len(by)}")
        for key, ids in sorted(by.items(), key=lambda kv: -len(kv[1]))[:show * 3]:
            print(f"  {len(ids):4d}  {key[:70]}  예: {', '.join(sorted(set(ids))[:3])}")


def _room(work: Path):
    from . import service as SV
    return SV.DressRoom(work / "cache")


def worker(work: Path, k: int, n: int) -> None:
    """일꾼 k/n: 목록을 n 으로 나눈 k 번째 몫을 꺼내 보고 audit_<k>.jsonl 에 줄마다 적는다."""
    if sys.platform == "win32":
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.SetPriorityClass(k32.GetCurrentProcess(), 0x4000)   # 보통 아래 — 게임이 켜져 있을 수 있다
    room = _room(work)
    room.pack()
    out = work / f"audit_{k}.jsonl"
    done = {r["id"] for r in rows(work) if "id" in r}
    with out.open("a", encoding="utf-8") as fh:
        for mid in sorted(room._items)[k::n]:
            if mid in done:
                continue
            t0 = time.time()
            it = room._items[mid]
            row = {"id": mid, "part": it.part, "kor": it.kor}
            try:
                rel = room.model(mid)
                path = room.dir / rel
                mark = path.with_suffix(".partial")
                meta = json.loads(path.read_text(encoding="utf-8"))
                row["issues"] = check(meta, mark.read_text(encoding="utf-8") if mark.exists() else None)
            except Exception as e:   # noqa: BLE001 — 한 벌이 깨져도 나머지를 본다
                src = e.__cause__ or e   # 서비스가 DressError 로 감싼 처음 오류
                row.update(error=f"{type(src).__name__}: {src}"[:300],
                           tb="".join(traceback.format_exception(src))[-400:])
            row["sec"] = round(time.time() - t0, 2)
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()


def show(work: Path, ids: list[str]) -> None:
    """모델마다 메시 → 재질 칸, 재질 이름·종류·피부·염색 칸·반투명."""
    room = _room(work)
    for mid in ids:
        meta = json.loads((room.dir / room.model(mid)).read_text(encoding="utf-8"))
        print(mid)
        for me in meta.get("meshes") or []:
            if me.get("groups"):
                print(f"  메시 {me['name']}{' (피부 조각)' if me.get('skin') else ''} → {[g['mat'] for g in me['groups']]}")
        for i, ma in enumerate(meta.get("materials") or []):
            print(f"  재질 {i} {ma['name']} {ma.get('kind')} 피부={bool(ma.get('skin'))} 칸={ma.get('slots')} "
                  f"반투명={(ma.get('float') or {}).get('_RenderMode')}")


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="드레스룸 전체 의상 점검")
    ap.add_argument("work", type=Path, help="작업 폴더 (저장소·사용자 dressroom 폴더 밖)")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--fresh", action="store_true", help="지난 결과를 지우고 처음부터")
    ap.add_argument("--report", type=int, nargs="?", const=6, help="지난 결과 요약만 (묶음마다 보일 수)")
    ap.add_argument("--show", nargs="+", metavar="ID", help="이 모델들의 재질 배정만 본다")
    ap.add_argument("--worker", type=int, nargs=2, metavar=("K", "N"), help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    work = a.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    if a.worker:
        worker(work, *a.worker)
        return 0
    if a.show:
        show(work, a.show)
        return 0
    if a.report is not None:
        report(work, a.report)
        return 0
    if a.fresh:
        for f in work.glob("audit_*.jsonl"):
            f.unlink()
    _room(work).pack()   # 목록·CAB 표를 한 번만 만든다 (일꾼이 같이 만들지 않게)
    t0 = time.time()
    tool = Path(__file__).resolve().parents[2] / "tools" / "dress_audit.py"   # 저장소 경로를 스스로 잡는다 (python -I 여도)
    procs = [subprocess.Popen([sys.executable, str(tool), str(work), "--worker", str(k), str(a.jobs)])
             for k in range(a.jobs)]
    code = max(p.wait() for p in procs)
    print(f"{time.time() - t0:.0f}초")
    report(work)
    return code


if __name__ == "__main__":
    sys.exit(main())
