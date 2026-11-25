"""염색 미니게임 맞출 자리 안내 + 자동 맞추기 — 화면 캡처와 마우스 입력만 쓴다 (패킷·메모리는 건드리지 않는다).

  Session     팔레트가 막 열린 첫 화면(위치 0·회전 0·배율 1)으로 팔레트를 복원하고, 프리셋 색을 스포이드들이
              동시에 집는 자리(회전·배율·위치)를 찾는다 (pairs.solve_pairs). 세 색이 다 되는 자리가 없으면
              두 색이 되는 가장 좋은 자리 (사용자 2026-11-25). 프리셋 칸 i ↔ 왼쪽부터 i 번째 스포이드.
  guide()     지금 상태(fit.pose)에서 해 텍셀들이 화면 어디 있나 + 무엇을 할지 한 줄.
              회전·배율이 맞으면 점들이 스포이드 배치와 같은 모양이 되고, 끌어서 겹치면 끝.
  AutoDriver  측정 → 입력 → 측정. 회전(오른쪽 드래그로 원)·휠·왼쪽 드래그. 확정 단추는 누르지 않는다.
              자리에 오면 게임 말풍선 색으로 확인하고, 안 맞으면 둘레를 1px 씩 보고, 그래도 안 되면
              그 텍셀을 빼고 다시 찾는다 (복원 색·섞인 색 계산이 조금씩 틀려도 게임 판정으로 끝낸다).
  HandsOff    자동 조작 중 사람이 키를 누르거나 커서를 움직이면 멈춘다.

조작 실측 (2026-10-31): 화면 시계 방향으로 그리면 rot 이 준다. 작은 회전은 처음 ~1° 가 먹힌다.
휠 한 칸 = 정확히 ×1.01. 회전 반지름은 1080p(팔레트 749px)에서 340px 로 시험했다 → 팔레트 크기에 비례.
2026-11-25 로그의 회전들: 먹힌 각도는 원의 첫 칸이었다 — 두 칸으로 그린 작은 회전은 안 먹히거나 반 또는 전부,
세 칸은 ⅓, 큰 회전은 1° (나머지 칸은 그대로). 시작점으로 옮기자마자 원을 그려 게임이 시작점을 늦게 잡은 것으로
보고 시작점에서 잠깐 멈춘다. 먹히는 각도(rot_dead)는 회전마다 다시 잰다.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from itertools import combinations

import cv2
import numpy as np

from .. import inputs as I
from . import detect as D
from . import fit as FT
from . import pairs as PR

log = logging.getLogger("mabi")

ROT_R = 340 / 749          # 회전 원 반지름 ÷ 팔레트 폭
ROT_HOLD = 0.15            # 회전 시작점에서 원을 그리기 전에 멈추는 시간 (초) — 0.03 이면 첫 칸이 자주 먹혔다
DRAG_MAX = 300 / 749       # 한 번에 끄는 거리 ÷ 팔레트 폭
START_POSE = ((0.0, 0.0), 0.0, 1.0, 0, 1.0)   # 시작 자세 (pos, rot, scale, 근거, 일치)


def wrap(d: float) -> float:
    return (d + 180) % 360 - 180


def pose_txt(m) -> str:
    """잰 상태 한 줄 (디버그 기록) — m: (pos, rot, scale, 근거[, 일치])."""
    hit = f" 일치 {m[4]:.2f}" if len(m) > 4 else ""
    return f"회전 {m[1]:.2f} 배율 {m[2]:.4f} 위치 ({m[0][0]:.4f},{m[0][1]:.4f}){hit}"


def goal_txt(g) -> str:
    """목표 한 줄 (디버그 기록) — g: (rot, scale, pos)."""
    return f"회전 {g[0]:.2f} 배율 {g[1]:.4f} 위치 ({g[2][0]:.4f},{g[2][1]:.4f})"


def nums_txt(xs) -> str:
    return " ".join(f"{float(x):.2f}" for x in xs)


def bgr_hex(p) -> str:
    return D.rgb_to_hex(int(p[2]), int(p[1]), int(p[0]))


class Session:
    """한 번 열린 팔레트. frame: 시작 화면 (BGR(A)), box: detect.Palette, rings/skip: detect.find_leaders 결과.
    refs: 재질 이름 → 원본 그림 (materials.load 그대로 = 행 위부터), mats: 칸마다 재질 (tracker.mats)."""

    def __init__(self, frame, box, rings, skip_shapes, refs=None, mats=None):
        S = box.w
        self.box, self.S = box, S
        rings = sorted(rings, key=lambda r: r.x)
        self.rings = rings
        c = self.crop(frame)
        self.start_crop = c
        skip = D.skip_mask(skip_shapes, np.arange(box.x, box.x + S), np.arange(box.y, box.y + S))
        self.pal = FT.Palette(c, skip, n=len(rings))
        self.mats = None
        if refs and mats:
            # 계산은 행 아래부터(v 증가) — bmp 는 위부터라 뒤집는다
            self.mats = self.pal.add_materials({k: v[::-1] for k, v in refs.items()}, mats)
        self.drops = [((r.x - box.x) / S, 1 - (r.y - box.y) / S) for r in rings]
        self.goal = None          # (rot, scale, pos)
        self.want: list[int] = []      # 프리셋에서 색을 정한 칸 (스포이드가 있는 것만)
        self.use: list[int] = []       # 맞추는 칸 — 세 색이 안 되면 둘
        self.left_out: list[int] = []  # 같이 잡을 자리가 없어 뺀 칸
        self.targets: dict[int, D.Target] = {}   # 칸 → 목표
        self.tb: dict[int, np.ndarray] = {}   # 칸 → 목표 BGR
        self.tol: dict[int, float] = {}
        self.regions: dict[int, PR.Region] = {}   # 칸 → 목표 색을 집는 자리 (solve 가 만든다)
        self.bans: dict[int, np.ndarray] = {}     # 팔레트 번호(mat_key) → 게임 색이 계산과 달라 뺀 텍셀
        self.last = None          # 마지막으로 잰 상태

    @property
    def start_ok(self) -> bool:
        """잡아 둔 화면이 정말 움직이기 전 화면인가 (fit.Palette.start_score)."""
        return self.pal.start_score >= FT.START_OK

    def crop(self, frame):
        b = self.box
        return np.ascontiguousarray(np.asarray(frame)[b.y:b.y + self.S, b.x:b.x + self.S, :3])

    def at_start(self, frame) -> bool:
        """팔레트가 시작 화면 그대로인가 (재지 않아도 시작 자세) — 스포이드 둘레는 색 표시가 바뀌므로 뺀다."""
        c = self.crop(frame).astype(np.int16)
        d = np.abs(c - self.start_crop).max(-1)
        return float((d > 6).mean()) < 0.01

    def drops_of(self, idx=None):
        return [self.drops[i] for i in (self.use if idx is None else idx)]

    # ---- 해 찾기 ----
    def solve(self, targets, m=None, budget: float = 6.0, stop=None) -> bool:
        """targets: 프리셋 칸 순서의 detect.Target (빈 칸 None), m: 지금 자세 (없으면 시작 자세).
        정한 색을 모두 집는 자리를 먼저 찾고, 세 색이 안 되면 두 색씩 다 풀어 점수가 가장 좋은 것.
        지금 자세에서 덜 돌리고 휠을 덜 쓰는 자리부터 (pairs 비용). 찾으면 self.goal·use·left_out."""
        self.goal, self.use, self.left_out = None, [], []
        want = [i for i in range(min(len(targets), len(self.drops))) if targets[i]]
        self.want = want
        if not want:
            return False
        self.targets = {i: targets[i] for i in want}
        self.tb = {i: np.array(targets[i].rgb[::-1], np.int16) for i in want}
        self.tol = {i: float(targets[i].tol_or_default) for i in want}
        self.regions = {i: PR.region_of(self.pal, self.drops[i][0], self.tb[i], self.tol[i], self._ban_of(i))
                        for i in want}
        rot0, s0 = (m[1], m[2]) if m is not None else (0.0, 1.0)
        log.debug("염색 해 찾기 목표 %s · 지금 회전 %.2f 배율 %.4f",
                  ", ".join(f"{i + 1}번 {self.targets[i].hex}±{self.tol[i]:g}" for i in want), rot0, s0)
        t0 = time.monotonic()
        t_end = t0 + budget
        sets = [want] + ([list(c) for c in combinations(want, 2)] if len(want) == 3 else [])
        best = None
        for k, use in enumerate(sets):
            if (stop and stop()) or time.monotonic() > t_end or (k and best and len(best[0]) == len(want)):
                break
            # 세 색 찾기가 시간을 다 쓰지 않게 — 두 색 짝들이 쓸 시간을 남긴다
            dl = t0 + budget * 0.6 if k == 0 and len(sets) > 1 else t_end
            ts = time.monotonic()
            found = PR.solve_pairs(self.pal, self.drops_of(use), [self.tb[i] for i in use],
                                   [self.tol[i] for i in use], rot_ref=rot0, scale_ref=s0, limit=8, deadline=dl,
                                   regions=self.regions_of(use))
            log.debug("염색 해 찾기 칸 %s: %s (%.2fs)", [i + 1 for i in use],
                      f"{len(found)}곳 · 가장 좋은 {goal_txt(found[0][:3])} 점수 {PR.score_of(found[0]):.1f}"
                      if found else "없음", time.monotonic() - ts)
            if found and (best is None or PR.score_of(found[0]) < PR.score_of(best[1])):
                best = (use, found[0])
        if best is None:
            return False
        self.use = best[0]
        self.goal = best[1][:3]
        self.left_out = [i for i in want if i not in self.use]
        g = self.goal
        log.debug("염색 해 찾기 고름 칸 %s · 여유 %gpx · 그 자리에서 스포이드마다 예측 색 %s", [i + 1 for i in self.use],
                  PR.TIERS[best[1][3]], " ".join(bgr_hex(p) for p in FT.predicted(self.pal, self.drops, g[2], g[0], g[1])))
        return True

    def resolve(self, m) -> bool:
        """같은 목표로 지금 자세 m 에서 다시 찾는다 (뺀 텍셀은 빼고). 못 찾으면 지난 목표를 그대로 둔다."""
        keep = (self.goal, self.use, self.left_out, self.regions)
        if self.solve([self.targets.get(i) for i in range(len(self.drops))], m):
            return True
        self.goal, self.use, self.left_out, self.regions = keep
        return False

    def resolve_at(self, m) -> bool:
        """휠을 돌린 뒤 잰 배율에서 해를 다시 찾는다 (휠은 칸 단위라 배율이 조금 다를 수 있다).
        회전은 지금 회전에 가까운 것부터, 목표 회전 둘레 6° 까지."""
        g = self.goal
        found = PR.solve_pairs(self.pal, self.drops_of(), [self.tb[i] for i in self.use],
                               [self.tol[i] for i in self.use], scales=[m[2]], rot_ref=m[1], scale_ref=m[2],
                               rot_win=abs(wrap(g[0] - m[1])) + 6, limit=5, regions=self.regions_of())
        log.debug("염색 배율 %.4f 에서 다시 풀기: %s", m[2], goal_txt(found[0][:3]) if found else "없음 — 목표 그대로")
        if found:
            self.goal = found[0][:3]
            return True
        return False

    # ---- 뺀 텍셀 (게임 색이 계산과 다름) ----
    def _ban_of(self, i):
        return self.bans.get(self.pal.mat_key(self.pal.strip(self.drops[i][0])))

    def ban_goal(self, slots) -> None:
        """그 칸들이 목표 자리에서 집는 텍셀 둘레 한 칸과, 거기 닿은 목표 색 무리(텍셀 가운데 색이 오차 안이고 이어진
        텍셀)를 뺀다 — 게임 말풍선이 계산과 달랐고 둘레를 끌어 봐도 안 된 곳. 복원 색은 무리째 틀리기 쉽다."""
        g = self.goal
        T = FT.TEX
        for i in slots:
            a, b = self.drops[i]
            iy, ix = (int(x) for x in FT._tex(*FT.uv_of(np.array(a), np.array(b), g[2], g[0], g[1])))
            near = np.zeros((T, T), bool)
            near[np.ix_([(iy + d) % T for d in (-1, 0, 1)], [(ix + d) % T for d in (-1, 0, 1)])] = True
            reg = self.regions.get(i)
            if reg is not None and reg.tex.any():
                _, lab = cv2.connectedComponents(reg.tex.astype(np.uint8), connectivity=8)
                ids = np.unique(lab[near])
                near |= np.isin(lab, ids[ids > 0])
            ban = self.bans.setdefault(self.pal.mat_key(self.pal.strip(a)), np.zeros((T, T), bool))
            ban |= near
            log.debug("염색 %d번 목표 텍셀 (%d, %d) 둘레 %d텍셀 뺌", i + 1, ix, iy, int(near.sum()))

    # ---- 지금 상태 ----
    def pose(self, frame):
        c = self.crop(frame)
        m = None
        if self.last is not None:   # 배율이 그대로면 고정해 재는 편이 빠르고 정확하다
            m = FT.pose(c, self.pal, scale=self.last[2])
            if m is not None and m[4] < 0.5:
                m = None
        if m is None:
            m = FT.pose(c, self.pal, last=self.last)
        if m is not None:
            self.last = m
        return m

    def regions_of(self, idx=None):
        return [self.regions[i] for i in (self.use if idx is None else idx)]

    def ok(self, m, margin_px=1.0) -> bool:
        """계산으로 지금 상태에서 스포이드들이 목표 색을 집나 — 둘레 margin_px 까지 섞인 색으로 본다."""
        if not self.use:
            return False
        return PR.regions_ok(self.regions_of(), self.S, self.drops_of(), m, margin_px)

    def tiers(self, m, poses):
        """지금 회전·배율(m) 그대로 위치만 poses 로 옮겼을 때 여유 단계 (작을수록 넉넉, len(TIERS) = 안 맞음)."""
        return PR.tiers_at(self.regions_of(), self.S, self.drops_of(), m[1], m[2], poses)

    def to_frame(self, a, b):
        return self.box.x + a * self.S, self.box.y + (1 - b) * self.S

    # ---- 게임 판정 (말풍선 색) ----
    def labels(self, frame) -> list:
        """게임이 띄운 스포이드 색 (말풍선 글자) — 왼쪽부터, 못 읽은 것은 None."""
        f = D.as_frame(frame, "bgr")
        return [D.read_label(f, self.box, r.x) for r in self.rings]

    def over(self, i, hexes) -> float | None:
        """칸 i 의 말풍선 색이 목표 오차를 넘은 만큼 (0 = 맞음, 못 읽으면 None)."""
        rgb = D.hex_to_rgb(hexes[i]) if i < len(hexes) and hexes[i] else None
        if rgb is None:
            return None
        t = self.targets[i]
        return max(0.0, D.rgb_diff(rgb, t.rgb) - t.tol_or_default)

    def caught_hex(self, hexes) -> bool:
        """말풍선 색(칸 i = 왼쪽부터 i 번째 스포이드)으로 맞추는 칸이 다 잡혔나 — 비교는 detect.picks 와 같은
        rgb_diff ≤ 오차. 계산 팔레트는 화면 색을 되짚은 것이라 틀릴 수 있어 마지막 판정은 게임을 믿는다."""
        return bool(self.use) and all(self.over(i, hexes) == 0 for i in self.use)

    def caught(self, rings) -> bool:
        """tracker 가 읽은 스포이드(고리 x 순서)로 caught_hex."""
        if not rings:
            return False
        return self.caught_hex([r.hex for r in sorted(rings, key=lambda r: r.x)])

    def guide(self, m, caught: bool = False) -> dict:
        """{'points': [(slot, x, y, 스포이드 x, y)], 'text': 할 일, 'done': 맞았나} — 좌표는 프레임 픽셀."""
        g = self.goal
        if g is None:
            return {"points": [], "text": "이 색으로 잡을 수 있는 자리가 없습니다", "done": False}
        out = "" if not self.left_out else "·".join(str(i + 1) for i in self.left_out) + "번 빼고 — "
        if caught:
            return {"points": [], "text": out + "맞았습니다 — 확인하고 적용하세요", "done": True}
        if m is None:
            return {"points": [], "text": "지금 팔레트 상태를 재지 못했습니다", "done": False}
        pts = []
        for slot, (a, b) in zip(self.use, FT.goal_points(self.drops_of(), g, m)):
            x, y = self.to_frame(a, b)
            r = self.rings[slot]
            pts.append((slot, x, y, r.x, r.y))
        d_rot = wrap(g[0] - m[1])
        n = int(round(math.log(g[1] / m[2]) / math.log(FT.WHEEL)))
        if abs(d_rot) > 1.0:
            text = f"오른쪽 버튼으로 {'시계' if d_rot < 0 else '반시계'} 방향 {abs(d_rot):.0f}° 돌리기"
        elif n:
            text = f"휠 {'위로' if n > 0 else '아래로'} {abs(n)}칸"
        else:
            text = "점을 같은 색 스포이드에 겹치게 끌기"
        return {"points": pts, "text": out + text, "done": False}


# ---------------------------------------------------------------- 입력 (절대좌표 SendInput)
def _cands(t, r):
    out = []
    for rr in range(r - 6, r + 7):
        x0, y0 = rr * math.cos(t), rr * math.sin(t)
        for x in (math.floor(x0), math.ceil(x0)):
            for y in (math.floor(y0), math.ceil(y0)):
                out.append((x, y, math.atan2(y, x)))
    return out


def end_points(deg, r):
    """회전 시작·끝 정수 픽셀 ((sx, sy), (ex, ey), 실제 각도). 커서는 정수 픽셀이라 한 반지름·한 방향으로는
    1px ≈ 57/r 도 단위밖에 안 된다 → 시작 방향(20~70°)과 반지름을 조금씩 바꾼 조합에서 고른다
    (2026-10-31 실기: 0.1° 를 넣으면 0.2° 씩 왔다 갔다 했다)."""
    best = None
    for a_deg in range(20, 71, 2):
        a = math.radians(a_deg)
        for sx, sy, sa in _cands(a, r):
            for ex, ey, ea in _cands(a + math.radians(deg), r):
                got = wrap(math.degrees(ea - sa))
                e = abs(got - deg)
                if best is None or e < best[0]:
                    best = (e, (sx, sy), (ex, ey), got)
        if best[0] < 0.005:
            break
    return best[1], best[2], best[3]


class Stopped(Exception):
    pass


class Mouse:
    """to_screen(x, y): 프레임 픽셀 → 화면 픽셀. stop(): True 면 다음 움직임에서 버튼을 떼고 멈춘다.
    busy: 움직이는 중, rest: 움직임을 마친 뒤 커서가 쉬는 자리 (HandsOff 가 사람 손을 가린다)."""

    def __init__(self, to_screen, stop=lambda: False):
        self.to_screen, self.stop = to_screen, stop
        self.busy = False
        self.rest = I.cursor_pos()

    def move(self, x, y):
        I.move_abs(*self.to_screen(x, y))

    def _check(self, up=None):
        if self.stop():
            if up:
                I.mouse_event(up)
            raise Stopped

    def _begin(self):
        self._check()
        self.busy = True

    def _end(self):
        time.sleep(0.05)
        self.rest = I.cursor_pos()
        self.busy = False

    def drag(self, x1, y1, x2, y2, steps=30):
        self._begin()
        try:
            self.move(x1, y1)
            time.sleep(0.08)
            I.mouse_event(I.MOUSEEVENTF_LEFTDOWN)
            time.sleep(0.08)
            for i in range(1, steps + 1):
                self._check(I.MOUSEEVENTF_LEFTUP)
                self.move(x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * i / steps)
                time.sleep(0.012)
            time.sleep(0.15)          # 마지막 자리에서 잠깐 멈춰 관성 없이 놓는다
            I.mouse_event(I.MOUSEEVENTF_LEFTUP)
        finally:
            self._end()

    def rotate(self, cx, cy, deg, r):
        """(cx, cy) 를 축으로 화면에서 deg 도 원을 그린다 (+ = 화면 시계 방향 — 화면 y 가 아래라서)."""
        self._begin()
        try:
            cx, cy = round(cx), round(cy)
            (sx, sy), (ex, ey), _ = end_points(deg, r)
            a0 = math.atan2(sy, sx)
            self.move(cx, cy)
            time.sleep(0.08)
            I.mouse_event(I.MOUSEEVENTF_RIGHTDOWN)
            time.sleep(0.08)
            self.move(cx + sx, cy + sy)            # 축에서 시작점으로 한 번에 (첫 움직임의 각도 = 시작 각도)
            time.sleep(ROT_HOLD)
            n = max(2, int(abs(deg)))
            for i in range(1, n):
                self._check(I.MOUSEEVENTF_RIGHTUP)
                t = a0 + math.radians(deg * i / n)
                self.move(cx + r * math.cos(t), cy + r * math.sin(t))
                time.sleep(0.012)
            self.move(cx + ex, cy + ey)            # 끝점도 정수 픽셀 그대로
            time.sleep(0.15)
            I.mouse_event(I.MOUSEEVENTF_RIGHTUP)
        finally:
            self._end()

    def wheel(self, x, y, notches):
        self._begin()
        try:
            self.move(x, y)
            time.sleep(0.05)
            for _ in range(abs(notches)):
                self._check()
                I.wheel_notch(notches > 0)
                time.sleep(0.03)
        finally:
            self._end()


class HandsOff:
    """자동 조작 중 사람이 손대면 stop 을 켠다 — 훅 없이 상태만 0.05초마다 읽는다.
    키: 켤 때 눌려 있지 않던 키가 눌림 (마우스 버튼은 우리가 누르므로 뺀다, ignore 는 따로 다루는 키).
    마우스: 우리가 움직이지 않는 동안 커서가 쉬던 자리(Mouse.rest)에서 4px 넘게 벗어남."""
    BUTTONS = {0x01, 0x02, 0x04, 0x05, 0x06}

    def __init__(self, mouse: Mouse, stop: threading.Event, ignore=()):
        self.mouse, self.stop = mouse, stop
        self.skip = self.BUTTONS | {int(v) for v in ignore if v}
        self.why = ""
        self._closed = threading.Event()
        self._held = {vk for vk in range(1, 256) if vk not in self.skip and I.key_pressed(vk)}
        threading.Thread(target=self._run, name="dye-hands", daemon=True).start()

    def close(self) -> None:
        self._closed.set()

    def _hit(self, why: str) -> None:
        self.why = why
        self.stop.set()

    def _run(self) -> None:
        while not self._closed.is_set() and not self.stop.is_set():
            for vk in range(1, 256):
                if vk in self.skip:
                    continue
                if I.key_pressed(vk):
                    if vk not in self._held:
                        self._hit("키 입력")
                        return
                else:
                    self._held.discard(vk)
            m = self.mouse
            if not m.busy and m.rest is not None:
                x, y = I.cursor_pos()
                if math.hypot(x - m.rest[0], y - m.rest[1]) > 4 and not m.busy:
                    self._hit("마우스")
                    return
            time.sleep(0.05)


# ---------------------------------------------------------------- 자동 맞추기
class AutoDriver:
    """측정 → 입력 → 측정. 회전 방향·먹히는 각도·휠 배율은 입력 결과로 보정한다.
    snap(): 새 프레임, on_step(m, 문구): 진행 알림, stop: threading.Event, read(frame): 말풍선 색 (기본 Session.labels).

    1) 자리 가기 (reach): 회전(3° 넘게) → 휠 → 끌기. 커서가 정수 픽셀이라 끌기도 정수 px 만 먹힌다 → 지금 회전·배율에서
       갈 수 있는 px 격자 중 계산 여유가 가장 큰 곳으로 (lattice). 미세 회전은 그 격자로 여유가 1px 에 못 미칠 때만.
    2) 확인 (search): 말풍선 색이 다 맞으면 끝. 아니면 말풍선 세 색으로 스포이드가 실제로 집는 자리를 역으로 찾아(locate)
       그 자리 기준 격자로 끌고, 못 찾으면 둘레 px 격자를 계산 여유가 큰 곳부터 — TRIES 번까지 말풍선으로 확인.
    3) 그래도 안 맞으면 안 맞은 칸의 목표 텍셀을 빼고 지금 자세에서 다시 찾아 1) 부터 (RETRIES 번까지).
    2026-11-25 실기: 0.3px 끌기를 왔다 갔다 하다 끝났고(정수 px), 자리에 와도 말풍선이 3~8 어긋났다. 녹화로 보니
    잰 자세가 1~4px 씩 어긋나 있었다 (말풍선으로 역으로 찾은 자리와 비교)."""
    SETTLE = 0.25             # 입력 뒤 화면이 멈출 때까지 재기 전에 쉬는 시간 (초)
    TRIES = 8                 # 말풍선을 보며 둘레 px 격자를 끌어 볼 횟수
    RETRIES = 2               # 목표 텍셀을 빼고 다시 찾는 횟수
    NEAR_PX = 2               # 둘레 격자 반지름 (px)
    LOC_OK = 6.0              # 역으로 찾은 자리를 믿는 스포이드 평균 색 차이 (칸별 최대)
    ROT_FINE = 0.15           # 이보다 작은 회전 차이는 미세 회전을 안 한다 — 스포이드가 0.5px 도 안 움직이고
                              # 회전 결과가 ±0.08° 씩 흔들려 (2026-11-25 0.04° 를 맞추려 1° 를 넣어 왔다 갔다 했다)

    def __init__(self, sess: Session, snap, mouse: Mouse, stop: threading.Event, on_step=None, read=None):
        self.s, self.snap, self.mouse, self.stop = sess, snap, mouse, stop
        self.on_step = on_step or (lambda m, t: None)
        self.read = read or sess.labels
        self.rot_dead = 0.0       # 그린 원에서 먹히는 각도 — 첫 회전(보통 큰 회전)부터 회전마다 다시 잰다
        self.rot_sign = -1.0      # 화면에서 그린 각도(시계 +) → rot 는 반대로
        self.wheel_k = math.log(FT.WHEEL)
        self.cx, self.cy = sess.to_frame(0.5, 0.5)
        self.R = max(60, round(ROT_R * sess.S))
        self.scale = sess.last[2] if sess.last else None
        self.frame = None         # 마지막으로 잰 화면 (말풍선을 여기서 읽는다)
        self.by_label = False     # 끝 판정을 말풍선으로 했나 (못 읽어 계산으로 했으면 False)
        self.probes = 0           # 말풍선을 보며 둘레를 끌어 본 횟수
        self.resolves = 0         # 텍셀을 빼고 다시 찾은 횟수

    def now(self, tries=4):
        """화면이 멈출 때까지 (두 번 연속 같게 잴 때까지) 잰다."""
        last = None
        for _ in range(tries):
            if self.stop.is_set():
                raise Stopped
            time.sleep(self.SETTLE)
            frame = self.snap()
            if frame is None:
                continue
            self.frame = frame
            c = self.s.crop(frame)
            if self.scale is None:
                m = FT.pose(c, self.s.pal, last=self.s.last)
                if m is None:
                    continue
                self.scale = m[2]
                last = m
                continue
            m = FT.measure(c, self.s.pal, scale=self.scale)
            if m is None:
                continue
            if last and abs(m[1] - last[1]) < 0.15 and abs(m[2] / last[2] - 1) < 0.002 \
                    and math.hypot(m[0][0] - last[0][0], m[0][1] - last[0][1]) * self.s.S < 0.6:
                m = FT.refine(c, self.s.pal, m)
                self.s.last = m
                return m
            last = m
        if last is not None:
            self.s.last = last
        log.debug("염색 자동: %d번 재도 멈춘 화면을 못 잼 — %s", tries, pose_txt(last) if last else "못 잼")
        return last

    def look(self, tries=4) -> list:
        """말풍선 색 (왼쪽 스포이드부터) — 두 번 연속 같게 읽힐 때까지. 자세는 재지 않는다."""
        last = None
        for _ in range(tries):
            if self.stop.is_set():
                raise Stopped
            time.sleep(self.SETTLE)
            f = self.snap()
            if f is None:
                continue
            self.frame = f
            hx = list(self.read(f))
            if hx == last:
                return hx
            last = hx
        return last or []

    def shifted(self, m, i, j):
        """정수 px (i, j) 끌기 뒤 자세 — 정수 끌기는 그대로 먹으므로 다시 재지 않는다 (재기는 한 번에 1초 넘게 걸린다)."""
        S = self.s.S
        return ((m[0][0] + i / S, m[0][1] - j / S),) + tuple(m[1:])

    def score(self, hx) -> float | None:
        """맞추는 칸이 말풍선에서 오차를 넘은 만큼의 합 (0 = 다 맞음, 못 읽은 칸이 있으면 None)."""
        ov = [self.s.over(i, hx) for i in self.s.use]
        return None if any(o is None for o in ov) else float(sum(ov))

    def locate(self, m, hx):
        """말풍선 색으로 스포이드가 실제로 집는 자리 — 계산 자세 m 에서 스포이드 자리를 옮겨 보며 섞인 색 예측과
        말풍선 차이(칸별 최대)의 스포이드 평균이 가장 작은 어긋남 (dx, dy px, 화면 오른쪽·아래 +).
        0.25px 격자에서 가장 작은 것 +2 안의 후보 중 잰 자리에 가장 가까운 것을 고른 뒤 0.05px 로 좁힌다.
        읽은 스포이드가 둘 미만이거나 평균 차이가 LOC_OK 를 넘으면 None.
        2026-11-25 녹화 71장면: 잰 자세 그대로는 평균 차이 중앙 25, 찾은 자리는 44% 가 3 이하였다."""
        s = self.s
        ks = [k for k in range(len(s.drops)) if k < len(hx) and hx[k] and D.hex_to_rgb(hx[k])]
        if len(ks) < 2:
            return None
        labs = [np.array(D.hex_to_rgb(hx[k])[::-1], np.int16) for k in ks]

        def err(DX, DY):
            E = np.zeros(DX.shape)
            for k, lab in zip(ks, labs):
                a, b = s.drops[k]
                u, v = FT.uv_of(a + DX / s.S, b - DY / s.S, m[0], m[1], m[2])
                E += np.abs(FT.sample(s.pal.kbgr[int(s.pal.strip(a))], u, v) - lab).max(-1)
            return E / len(ks)

        n = math.ceil(max(3.0, 1.5 * s.S / FT.TEX * m[2]) / 0.25)    # 텍셀 한 칸 반 (화면 px)
        DX, DY = np.meshgrid(np.arange(-n, n + 1) * 0.25, np.arange(-n, n + 1) * 0.25)
        E = err(DX, DY)
        near = E <= E.min() + 2
        q = np.unravel_index(np.argmin(np.where(near, np.hypot(DX, DY), np.inf)), E.shape)
        f = np.arange(-6, 7) * 0.05
        FX, FY = np.meshgrid(DX[q] + f, DY[q] + f)
        FE = err(FX, FY)
        r = np.unravel_index(np.argmin(FE), FE.shape)
        dx, dy, e = float(FX[r]), float(FY[r]), float(FE[r])
        log.debug("염색 자동 말풍선 역추적: 어긋남 (%+.2f, %+.2f)px 평균 차이 %.1f (비슷한 후보 %d곳) → %s",
                  dx, dy, e, int(near.sum()), "믿음" if e <= self.LOC_OK else "안 믿음")
        return (dx, dy) if e <= self.LOC_OK else None

    def drag_px(self, i, j):
        """정수 px (i, j) 만큼 끈다 — 시작·끝을 정수 픽셀로 (커서가 정수라 그 아래는 먹히지 않는다)."""
        if i or j:
            x1, y1 = round(self.cx - i / 2), round(self.cy - j / 2)
            self.mouse.drag(x1, y1, x1 + i, y1 + j)

    def run(self, rounds=14):
        """맞으면 (True, m), 못 맞추면 (False, m). 끝 판정은 말풍선 색 (못 읽으면 계산).
        바퀴마다 잰 상태·목표·한 일을 디버그 기록에 남긴다."""
        s = self.s
        m = self.now()
        if m is None:
            log.debug("염색 자동: 처음 상태를 재지 못함")
            return False, None
        hx = []
        for n in range(self.RETRIES + 1):
            m = self.reach(m, rounds)
            hx = self.look()
            if all(s.over(i, hx) is None for i in s.use):      # 말풍선을 못 읽으면 계산으로
                ok = s.ok(m, 0.5)
                log.debug("염색 자동 끝 (말풍선 못 읽음 — 계산 %s): %s", "맞음" if ok else "못 맞춤", pose_txt(m))
                return ok, m
            self.by_label = True
            ok, m, hx = self.search(m, hx)
            if ok:
                log.debug("염색 자동 끝 (맞음): %s · 말풍선 %s", pose_txt(m), " ".join(h or "?" for h in hx))
                return True, m
            bad = [i for i in s.use if (s.over(i, hx) or 0) > 0]
            if n == self.RETRIES or not bad:
                break
            self.on_step(m, "다른 자리 찾기")
            s.ban_goal(bad)
            if not s.resolve(m):
                log.debug("염색 자동: 칸 %s 목표 텍셀을 빼니 다른 자리가 없음", [i + 1 for i in bad])
                break
            self.resolves += 1
            log.debug("염색 자동 다시 찾기 %d: 칸 %s 목표 텍셀을 빼고 → 칸 %s %s", n + 1, [i + 1 for i in bad],
                      [i + 1 for i in s.use], goal_txt(s.goal))
        log.debug("염색 자동 끝 (못 맞춤): %s · 말풍선 %s", pose_txt(m), " ".join(h or "?" for h in hx))
        return False, m

    def lattice(self, m, skip=None):
        """지금 회전·배율에서 끌 정수 px (i, j) 와 그 자리 여유 단계 (pairs.TIERS 번호, 클수록 좁음).
        멀면 한 번에 DRAG_MAX 까지 목표 쪽으로 — 여유는 None (그 자리에서 다시 본다). skip(i, j): 뺄 자리.
        뺄 자리뿐이면 (None, None)."""
        s = self.s
        tp = FT.best_pos(s.drops_of(), s.goal, m)
        dx, dy = (tp[0] - m[0][0]) * s.S, -(tp[1] - m[0][1]) * s.S   # 프레임 픽셀 (y 아래 +)
        L, lim = math.hypot(dx, dy), DRAG_MAX * s.S
        if L > lim:
            return (round(dx * lim / L), round(dy * lim / L)), None
        ci, cj = round(dx), round(dy)
        offs = [(ci + i, cj + j) for i in range(-2, 3) for j in range(-2, 3)]
        if skip:
            offs = [o for o in offs if not skip(*o)]
            if not offs:
                return None, None
        tier = s.tiers(m, [self.shifted(m, i, j)[0] for i, j in offs])
        q = min(range(len(offs)), key=lambda q: (tier[q], (offs[q][0] - dx) ** 2 + (offs[q][1] - dy) ** 2))
        return offs[q], int(tier[q])

    def reach(self, m, rounds):
        """회전·휠·끌기로 계산상 목표 자리까지 → 마지막으로 잰 상태."""
        s = self.s
        fine, fine_all, small = 0, 0, 0
        for k in range(rounds):
            g = s.goal
            d_rot = wrap(g[0] - m[1])
            d_ls = math.log(g[1] / m[2])
            n = int(round(d_ls / self.wheel_k)) if abs(d_ls) > abs(self.wheel_k) / 2 else 0
            step, tier = (None, None) if abs(d_rot) > 3 or n else self.lattice(m)
            log.debug("염색 자동 %d: 잼 %s · 목표 %s · 남은 텍셀 %s%s", k + 1, pose_txt(m), goal_txt(g),
                      nums_txt(FT.miss_texels(m, g, s.drops_of())),
                      "" if step is None else f" · 끌 자리 {step}px 여유 " +
                      ("?" if tier is None else f"{PR.TIERS[tier]:g}px" if tier < len(PR.TIERS) else "없음"))
            # 1) 회전 — 3° 넘으면 바로. 그 아래는 지금 회전으로 갈 px 격자의 여유가 1px 에 못 미칠 때만
            #    (미세 회전은 연달아 두 번까지, 모두 다섯 번까지)
            if abs(d_rot) > 3 or (tier is not None and tier > 1 and abs(d_rot) >= self.ROT_FINE and fine < 2
                                  and fine_all < 5):
                fine += abs(d_rot) <= 3
                fine_all += abs(d_rot) <= 3
                before = m
                cmd = d_rot + math.copysign(self.rot_dead, d_rot)
                self.on_step(m, f"회전 {d_rot:+.1f}°")
                self.mouse.rotate(self.cx, self.cy, cmd * self.rot_sign, self.R)
                m = self.now() or m
                got = wrap(m[1] - before[1])
                if abs(cmd) > 3 and abs(got) > 1 and got * cmd < 0:
                    self.rot_sign = -self.rot_sign       # 반대로 돌았다
                elif got * cmd >= 0 and abs(cmd) - abs(got) <= 2.5:   # 안 돈 큰 회전(창이 가려짐 등)은 빼고
                    self.rot_dead = max(0.0, abs(cmd) - abs(got))
                log.debug("염색 자동 회전: 명령 %+.2f° → 돈 %+.2f° (방향 %+.0f · 덜 먹힘 %.2f°)",
                          cmd, got, self.rot_sign, self.rot_dead)
                continue
            # 2) 배율 — 휠 반 칸보다 차이가 클 때만
            if n:
                before = m
                n = max(-60, min(60, n))
                self.on_step(m, f"휠 {n:+d}칸")
                self.mouse.wheel(self.cx, self.cy, n)
                self.scale = None                    # 휠 뒤엔 배율도 잰다
                m = self.now() or m
                got = math.log(m[2] / before[2])
                if abs(n) >= 3 and abs(got) > 0.005:
                    self.wheel_k = got / n
                log.debug("염색 자동 휠: %+d칸 → 배율 %.4f → %.4f (칸당 ×%.5f)", n, before[2], m[2],
                          math.exp(self.wheel_k))
                if abs(m[2] / g[1] - 1) > 1e-4:      # 칸 단위라 배율이 조금 다르면 그 배율에서 해를 다시
                    s.resolve_at(m)
                continue
            # 3) 위치 — 정수 px. 1px 끌기가 두 번 이어지면 (잴 때마다 조금씩 달라 왔다 갔다) 말풍선 확인으로 넘긴다
            if step == (0, 0) or small >= 2:
                return m
            small = small + 1 if max(abs(step[0]), abs(step[1])) <= 1 else 0
            before = m
            self.on_step(m, f"끌기 {math.hypot(*step):.0f}px")
            self.drag_px(*step)
            if max(abs(step[0]), abs(step[1])) <= 1:
                # 1px 끌기는 그대로 먹는다 — 다시 재면 0.1~0.3px 씩 달라 1px 을 왔다 갔다 했다 (2026-11-25)
                m = self.shifted(before, *step)
                log.debug("염색 자동 끌기: (%+d, %+d)px — 다시 재지 않음", step[0], step[1])
            else:
                m = self.now() or m
                log.debug("염색 자동 끌기: (%+d, %+d)px → 움직인 (%+.1f, %+.1f)px", step[0], step[1],
                          (m[0][0] - before[0][0]) * s.S, -(m[0][1] - before[0][1]) * s.S)
            fine = 0
        return m

    def search(self, m, hx):
        """말풍선 색이 다 맞을 때까지 둘레 정수 px 격자를 계산 여유가 큰(같으면 가까운) 곳부터 끌어 본다.
        → (맞았나, m, 말풍선). 못 맞추면 가장 덜 어긋난 자리로 돌아가 다시 잰다."""
        s = self.s
        sc = self.score(hx)
        log.debug("염색 자동 말풍선: %s · 목표 %s · 넘침 %s", " ".join(h or "?" for h in hx),
                  " ".join(s.targets[i].hex for i in s.use), "?" if sc is None else f"{sc:g}")
        if sc == 0:
            return True, m, hx
        m0, best = m, (math.inf if sc is None else sc, (0, 0), hx)
        R = self.NEAR_PX
        offs = [(i, j) for i in range(-R, R + 1) for j in range(-R, R + 1) if i or j]
        tier = s.tiers(m0, [self.shifted(m0, i, j)[0] for i, j in offs])
        order = [offs[q] for q in sorted(range(len(offs)), key=lambda q: (tier[q], offs[q][0] ** 2 + offs[q][1] ** 2))]
        cur, tried = (0, 0), {(0, 0)}
        for t in range(self.TRIES):
            # 말풍선으로 실제 자리를 찾으면 그 자리 기준 격자에서, 못 찾으면 계산 여유 순서대로 — 끌어 본 곳은 빼고
            nxt, how = None, "계산 여유 순"
            d = self.locate(self.shifted(m0, *cur), hx)
            if d is not None:
                mc = self.shifted(m0, cur[0] - d[0], cur[1] - d[1])
                step, _ = self.lattice(mc, skip=lambda i, j: (cur[0] + i, cur[1] + j) in tried)
                if step is not None:
                    nxt, how = (cur[0] + step[0], cur[1] + step[1]), f"역추적 ({d[0]:+.1f}, {d[1]:+.1f})px"
            if nxt is None:
                nxt = next((o for o in order if o not in tried), None)
                if nxt is None:
                    break
            self.on_step(m0, f"말풍선 보며 맞추기 {t + 1}/{self.TRIES}")
            self.drag_px(nxt[0] - cur[0], nxt[1] - cur[1])
            self.probes += 1
            cur = nxt
            tried.add(cur)
            hx = self.look()
            sc = self.score(hx)
            log.debug("염색 자동 둘레 %d: (%+d, %+d)px · %s · 말풍선 %s · 넘침 %s", t + 1, cur[0], cur[1], how,
                      " ".join(h or "?" for h in hx), "?" if sc is None else f"{sc:g}")
            if sc == 0:
                return True, self.shifted(m0, *cur), hx
            if sc is not None and sc < best[0]:
                best = (sc, cur, hx)
        self.drag_px(best[1][0] - cur[0], best[1][1] - cur[1])
        m = self.now() or self.shifted(m0, *best[1])
        hx = self.look()
        d = self.locate(m, hx)                   # 다시 찾기는 실제 자리에서
        return False, (m if d is None else self.shifted(m, -d[0], -d[1])), hx
