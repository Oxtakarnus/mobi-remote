"""염색 미니게임 맞출 자리 안내 + 자동 맞추기 — 화면 캡처와 마우스 입력만 쓴다 (패킷·메모리는 건드리지 않는다).

  Session     팔레트가 막 열린 첫 화면(위치 0·회전 0·배율 1)으로 팔레트를 복원하고, 프리셋 색을 스포이드들이
              동시에 집는 자리(회전·배율·위치)를 찾는다 (pairs.solve_pairs). 세 색이 다 되는 자리가 없으면
              두 색이 되는 가장 좋은 자리 (사용자 2026-11-25). 프리셋 칸 i ↔ 왼쪽부터 i 번째 스포이드.
  guide()     지금 상태(fit.pose)에서 해 텍셀들이 화면 어디 있나 + 무엇을 할지 한 줄.
              회전·배율이 맞으면 점들이 스포이드 배치와 같은 모양이 되고, 끌어서 겹치면 끝.
  AutoDriver  측정 → 입력 → 측정. 회전(오른쪽 드래그로 원)·휠·왼쪽 드래그. 확정 단추는 누르지 않는다.
  HandsOff    자동 조작 중 사람이 키를 누르거나 커서를 움직이면 멈춘다.

조작 실측 (2026-10-31): 화면 시계 방향으로 그리면 rot 이 준다. 작은 회전은 처음 ~1° 가 먹힌다.
휠 한 칸 = 정확히 ×1.01. 회전 반지름은 1080p(팔레트 749px)에서 340px 로 시험했다 → 팔레트 크기에 비례.
"""
from __future__ import annotations

import math
import threading
import time
from itertools import combinations

import numpy as np

from .. import inputs as I
from . import detect as D
from . import fit as FT
from . import pairs as PR

ROT_R = 340 / 749          # 회전 원 반지름 ÷ 팔레트 폭
DRAG_MAX = 300 / 749       # 한 번에 끄는 거리 ÷ 팔레트 폭
START_POSE = ((0.0, 0.0), 0.0, 1.0, 0, 1.0)   # 시작 자세 (pos, rot, scale, 근거, 일치)


def wrap(d: float) -> float:
    return (d + 180) % 360 - 180


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
        rot0, s0 = (m[1], m[2]) if m is not None else (0.0, 1.0)
        t0 = time.monotonic()
        t_end = t0 + budget
        sets = [want] + ([list(c) for c in combinations(want, 2)] if len(want) == 3 else [])
        best = None
        for k, use in enumerate(sets):
            if (stop and stop()) or time.monotonic() > t_end or (k and best and len(best[0]) == len(want)):
                break
            # 세 색 찾기가 시간을 다 쓰지 않게 — 두 색 짝들이 쓸 시간을 남긴다
            dl = t0 + budget * 0.6 if k == 0 and len(sets) > 1 else t_end
            found = PR.solve_pairs(self.pal, self.drops_of(use), [self.tb[i] for i in use],
                                   [self.tol[i] for i in use], rot_ref=rot0, scale_ref=s0, limit=8, deadline=dl)
            if found and (best is None or PR.score_of(found[0]) < PR.score_of(best[1])):
                best = (use, found[0])
        if best is None:
            return False
        self.use = best[0]
        self.goal = best[1][:3]
        self.left_out = [i for i in want if i not in self.use]
        return True

    def resolve_at(self, m) -> bool:
        """휠을 돌린 뒤 잰 배율에서 해를 다시 찾는다 (휠은 칸 단위라 배율이 조금 다를 수 있다).
        회전은 지금 회전에 가까운 것부터, 목표 회전 둘레 6° 까지."""
        g = self.goal
        found = PR.solve_pairs(self.pal, self.drops_of(), [self.tb[i] for i in self.use],
                               [self.tol[i] for i in self.use], scales=[m[2]], rot_ref=m[1], scale_ref=m[2],
                               rot_win=abs(wrap(g[0] - m[1])) + 6, limit=5)
        if found:
            self.goal = found[0][:3]
            return True
        return False

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

    def ok(self, m, margin_px=1.0) -> bool:
        """지금 상태에서 스포이드들이 목표 색을 집나 — 둘레 margin_px 까지 (자동 맞추기는 1px 여유를 남긴다)."""
        if not self.use:
            return False
        return FT.colors_ok(self.pal, m, self.drops_of(), [self.tb[i] for i in self.use],
                            [self.tol[i] for i in self.use], margin_px=margin_px)

    def to_frame(self, a, b):
        return self.box.x + a * self.S, self.box.y + (1 - b) * self.S

    def caught(self, rings) -> bool:
        """게임이 띄운 색(tracker 가 읽은 스포이드 색 — 말풍선 글자)으로 맞추는 칸이 다 잡혔나. 칸 i 는 왼쪽부터
        i 번째 스포이드만 본다 — 비교는 detect.picks 와 같은 rgb_diff ≤ 오차.
        계산 팔레트는 화면 색을 되짚은 것이라 원본과 ±2 틀릴 수 있어 마지막 판정은 화면을 믿는다."""
        if not self.use or not rings:
            return False
        rs = sorted(rings, key=lambda r: r.x)
        for i in self.use:
            if i >= len(rs) or not rs[i].hex:
                return False
            t = self.targets[i]
            if D.rgb_diff(D.hex_to_rgb(rs[i].hex), t.rgb) > t.tol_or_default:
                return False
        return True

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
            time.sleep(0.03)
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
    snap(): 새 프레임, on_step(m, 문구): 진행 알림, stop: threading.Event."""
    SETTLE = 0.25             # 입력 뒤 화면이 멈출 때까지 재기 전에 쉬는 시간 (초)

    def __init__(self, sess: Session, snap, mouse: Mouse, stop: threading.Event, on_step=None):
        self.s, self.snap, self.mouse, self.stop = sess, snap, mouse, stop
        self.on_step = on_step or (lambda m, t: None)
        self.rot_dead = 1.0       # 작은 회전에서 먹히는 각도 (매번 다시 잰다)
        self.rot_sign = -1.0      # 화면에서 그린 각도(시계 +) → rot 는 반대로
        self.wheel_k = math.log(FT.WHEEL)
        self.cx, self.cy = sess.to_frame(0.5, 0.5)
        self.R = max(60, round(ROT_R * sess.S))
        self.scale = sess.last[2] if sess.last else None

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
        return last

    def run(self, rounds=14):
        """맞으면 (True, m), 못 맞추면 (False, m)."""
        s = self.s
        m = self.now()
        if m is None:
            return False, None
        fine, fine_all = 0, 0
        for _ in range(rounds):
            g = s.goal
            if s.ok(m) or max(FT.miss_texels(m, g, s.drops_of())) <= 0.3:
                return True, m
            d_rot = wrap(g[0] - m[1])
            # 1) 회전 — 미세 회전은 연달아 두 번까지, 모두 다섯 번까지 (측정이 흔들려 끝없이 돌지 않게)
            if abs(d_rot) > 0.03 and (abs(d_rot) > 3 or (fine < 2 and fine_all < 5 and (fine == 0 or abs(d_rot) > 0.08))):
                fine += abs(d_rot) <= 3
                fine_all += abs(d_rot) <= 3
                before = m
                cmd = d_rot + math.copysign(self.rot_dead, d_rot) if abs(d_rot) <= 3 else d_rot
                self.on_step(m, f"회전 {d_rot:+.1f}°")
                self.mouse.rotate(self.cx, self.cy, cmd * self.rot_sign, self.R)
                m = self.now() or m
                got = wrap(m[1] - before[1])
                if abs(cmd) <= 4:
                    lost = abs(cmd) - abs(got) if got * cmd >= 0 else abs(cmd)
                    self.rot_dead = max(0.0, min(2.5, lost))
                if abs(d_rot) > 3 and abs(got) > 1:
                    self.rot_sign *= d_rot / got if abs(d_rot / got) < 3 else 1
                    self.rot_sign = max(-1.3, min(1.3, self.rot_sign)) if abs(self.rot_sign) > 0.7 else \
                        math.copysign(1, self.rot_sign)
                continue
            # 2) 배율 — 휠 반 칸보다 차이가 클 때만
            d_ls = math.log(g[1] / m[2])
            n = int(round(d_ls / self.wheel_k)) if abs(d_ls) > abs(self.wheel_k) / 2 else 0
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
                if abs(m[2] / g[1] - 1) > 1e-4:      # 칸 단위라 배율이 조금 다르면 그 배율에서 해를 다시
                    s.resolve_at(m)
                continue
            # 3) 위치 — 같은 무늬가 되는 자리 중 가장 가까운 곳
            tp = FT.best_pos(s.drops_of(), g, m)
            dx, dy = (tp[0] - m[0][0]) * s.S, -(tp[1] - m[0][1]) * s.S   # 프레임 픽셀 (y 아래 +)
            L = math.hypot(dx, dy)
            if L > 0.3:
                f = min(1.0, DRAG_MAX * s.S / L)
                x1, y1 = self.cx - dx * f / 2, self.cy - dy * f / 2
                self.on_step(m, f"끌기 {L:.0f}px")
                self.mouse.drag(x1, y1, x1 + dx * f, y1 + dy * f)
                m = self.now() or m
                fine = 0
                continue
            break
        return s.ok(m), m
