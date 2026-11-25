"""두 점 짝으로 맞출 자리 찾기 (2026-11-25) — 예전 격자(배율 37 × 회전 360, 최대 25초)를 갈음한다.

스포이드 두 개가 각각 어느 목표 텍셀에 떨어질지 짝을 정하면 회전·배율·위치가 한 번에 정해진다.
  d = (0.5 + 0.5i) + pos + a·w   (복소수: a = scale·e^{i·rot}, w = 비틀기 전 평면, 주기 1)
  → a = (d_j − d_i) / (w_j − w_i)
세 번째 스포이드는 그 자세에서 떨어지는 자리를 보고, 목표 텍셀이 가까우면 셋을 최소제곱으로 다시 맞춘다.
배율은 휠 칸(×1.01)으로만 바뀌므로 가장 가까운 칸에 붙이고, 둘레 여유(fit.OFFS)까지 실제 계산식으로 확인한다.
저장 화면 시험(오차 10, 세 색): 예전 평균 3.7초·최대 20초 → 평균 0.5초·최대 1.8초.

짝 후보는 색이 오차 안인 텍셀 가운데, 둘레 여유는 섞인 색(fit.Palette.fine)으로 본다 (Region) — 텍셀 하나로 보면
이웃 색이 크게 다른 텍셀이 '맞는 자리' 로 뽑혀 실기에서 섞인 색을 집었다 (2026-11-25). 섞인 색으로 보면 그런 자리는
여유가 좁게 나와, 필요하면 더 확대한 자리(텍셀이 화면에서 큼)를 고른다.
"""
from __future__ import annotations

import math
import time

import cv2
import numpy as np

from . import fit as FT

TIERS = (1.5, 1.0, 0.5, 0.0)   # 스포이드 둘레 여유 (화면 px) — 넓을수록 입력 오차에 강하다 (0 = 그 점만)
TIER_COST = (0.0, 10.0, 25.0, 45.0)  # 여유가 좁을수록 더하는 비용 (회전 4° 와 같은 단위 — MOVE_W)
# 여유 0px 자리는 그 둘레 1px 칸(16점) 중 스포이드가 모두 맞는 비율이 낮을수록 비용을 더한다 — 끌기는 정수 px 라
# 칸이 화면에서 작으면(축소) 닿을 수가 없다. 2026-11-25 실기 화면: 목표 색이 드물어 해가 전부 여유 0px 였고,
# 이 비용이 없으면 0.6배 축소 자리(텍셀 1.8px)를 골랐다
AREA = [(x, y) for x in (-0.375, -0.125, 0.125, 0.375) for y in (-0.375, -0.125, 0.125, 0.375)]
AREA_COST = 80.0
LOG_W = 40.0                   # 움직임 = |회전 차이°| + 40·|ln 배율 비| (휠 10칸 ≈ 4°)
# 비용 = MOVE_W·움직임 — 회전·휠은 많이 해도 몇 초라 맞출 수 있는 정도(여유·닿기)가 훨씬 중요하다. 2026-11-25 실기
# 화면: 1 이면 둘레 1px 칸 모두 맞는 확대 자리(회전 97°)를 두고 19% 만 맞는 축소 자리를 골랐다
MOVE_W = 0.25
MAX_SITES = 1200               # 스포이드마다 짝에 쓸 목표 텍셀 상한 (넘으면 칸마다 가장 안쪽 하나)
NEAR = 2.5                     # 세 번째 스포이드: 이 텍셀 거리 안에 목표 텍셀이 있으면 셋을 다시 맞춘다
CHUNK = 32                     # 한 번에 펼칠 앞 텍셀 수
BAND = 300_000                 # 두 색: 비용이 낮은 짝부터 이만큼씩 확인
KEEP = 4000                    # 세 색: 모아 두는 해 상한 (넘으면 좋은 것만)
MID = 0.5 + 0.5j               # 팔레트 가운데 (정규 좌표, 복소수)
LN_W = math.log(FT.WHEEL)
N_MIN = math.ceil(math.log(FT.SCALE_MIN) / LN_W)
N_MAX = math.floor(math.log(FT.SCALE_MAX) / LN_W)


class Region:
    """스포이드 하나가 목표 색을 집는 자리.
    tex  (TEX×TEX)       텍셀 가운데 색이 오차 안이고 본 텍셀 — 짝 후보·세 번째 스포이드 가까운 칸
    fine (TEX·F×TEX·F)   잔 격자에서 섞인 색까지 오차 안 — 맞았나 판정 (hit)"""

    def __init__(self, tex, fine):
        self.tex, self.fine = tex, fine

    def hit(self, u, v):
        n = self.fine.shape[0]
        return self.fine[np.floor((np.asarray(v) % 1) * n).astype(int) % n,
                         np.floor((np.asarray(u) % 1) * n).astype(int) % n]

    def any(self) -> bool:
        return bool(self.tex.any() and self.fine.any())


def region_of(pal, a, t, tol, ban=None) -> Region:
    """화면 가로 a 의 스포이드가 목표 t (BGR) 를 오차 tol 안으로 집는 자리. ban: 뺄 텍셀 (TEX×TEX, 그 칸 재질).
    그림 가장자리 2텍셀은 뺀다 — 원본 Cloth 마지막 열(253)은 전부 검정인데 화면 팔레트엔 안 그려진다."""
    k = int(pal.strip(a))
    tex = (FT.diff(pal.kbgr[k], t) <= tol) & pal.kknown[k]
    col, known = pal.fine(k)
    fine = (np.abs(col - np.asarray(t, np.int16)).max(-1) <= tol) & known
    if ban is not None and ban.any():
        tex &= ~ban
        fine &= ~np.repeat(np.repeat(ban, FT.FINE, 0), FT.FINE, 1)
    e = 2 * FT.FINE
    tex[:2], tex[-2:], tex[:, :2], tex[:, -2:] = False, False, False, False
    fine[:e], fine[-e:], fine[:, :e], fine[:, -e:] = False, False, False, False
    return Region(tex, fine)


def regions_of(pal, drops, targets, tols, bans=None):
    """스포이드마다 Region. targets 는 BGR, bans: 스포이드마다 뺄 텍셀 (없으면 None)."""
    return [region_of(pal, a, t, tol, None if bans is None else bans[n])
            for n, ((a, _), t, tol) in enumerate(zip(drops, targets, tols))]


def regions_ok(regions, S, drops, m, margin_px=1.0) -> bool:
    """자세 m 에서 스포이드마다 둘레 margin_px 까지 섞인 색이 모두 목표 오차 안인가."""
    for reg, (a, b) in zip(regions, drops):
        for ex, ey in FT.OFFS:
            u, v = FT.uv_of(np.array(a + ex * margin_px / S), np.array(b + ey * margin_px / S), m[0], m[1], m[2])
            if not reg.hit(u, v):
                return False
    return True


def tiers_at(regions, S, drops, rot, scale, poses):
    """같은 회전·배율에서 위치(poses: [(px, py)])마다 여유 단계 (0 = TIERS[0] … len(TIERS) = 그 점도 안 맞음)."""
    A = np.full(len(poses), scale * np.exp(1j * math.radians(rot)), complex)
    B = np.array([complex(px, py) for px, py in poses])
    return _tiers(regions, S, [(float(a), float(b)) for a, b in drops], A, B)


def score_of(found) -> float:
    """solve_pairs 한 해의 점수 (낮을수록 좋다) — 비용 + 여유 비용."""
    return found[4] + TIER_COST[found[3]]


def _wrap(deg):
    return (deg + 180.0) % 360.0 - 180.0


def _sites(mask):
    """짝에 쓸 목표 텍셀의 w (복소수, 0~1). 많으면 cell×cell 칸마다 이웃이 가장 많은(안쪽) 하나 — 작은 무리도 남는다."""
    ys, xs = np.nonzero(mask)
    if len(ys) > MAX_SITES:
        m8 = mask.astype(np.int8)
        core = sum(np.roll(np.roll(m8, dy, 0), dx, 1) for dy in (-1, 0, 1) for dx in (-1, 0, 1))[ys, xs]
        first = np.arange(len(ys))
        for cell in range(2, 33):
            key = (ys // cell) * 1024 + xs // cell
            order = np.lexsort((-core, key))
            ks = key[order]
            first = order[np.r_[True, ks[1:] != ks[:-1]]]
            if len(first) <= MAX_SITES:
                break
        ys, xs = ys[first], xs[first]
    wx, wy = FT.Finv((xs + 0.5) / FT.TEX, (ys + 0.5) / FT.TEX)
    return (wx % 1.0) + 1j * (wy % 1.0)


def _nearest(mask):
    """텍셀마다 가장 가까운 mask 텍셀 (감싸기) → (ny, nx, 텍셀 거리)."""
    T = FT.TEX
    big = np.tile(mask, (3, 3))
    src = np.where(big, 0, 255).astype(np.uint8)
    dist, lab = cv2.distanceTransformWithLabels(src, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    zy, zx = np.nonzero(big)
    lut = np.zeros((int(lab.max()) + 1, 2), np.int32)
    lut[lab[zy, zx]] = np.stack([zy, zx], 1)
    c = lab[T:2 * T, T:2 * T]
    return lut[c, 0] % T, lut[c, 1] % T, dist[T:2 * T, T:2 * T]


def _lifts(rmax):
    """뒤 텍셀을 가장 가까운 주기 자리로 옮긴 뒤 더해 볼 정수 들어올림."""
    r = rmax + math.sqrt(0.5)
    n = int(math.ceil(r))
    return np.array([complex(x, y) for x in range(-n, n + 1) for y in range(-n, n + 1) if x * x + y * y <= r * r])


def _snap(s, scales, max_snap):
    """배율을 휠 칸(또는 주어진 배율)에 붙인다 → (붙인 배율, 붙일 수 있나)."""
    ln = np.log(s)
    if scales is None:
        ln2 = np.clip(np.rint(ln / LN_W), N_MIN, N_MAX) * LN_W
    else:
        ls = np.log(np.asarray(scales, float))
        ln2 = ls[np.abs(ln[:, None] - ls[None, :]).argmin(1)]
    return np.exp(ln2), np.abs(ln - ln2) <= max_snap


def _hit(reg, d, A, B):
    """자세(A = scale·e^{i rot}, B = pos)에서 화면 점 d 가 집는 섞인 색이 목표 오차 안인가."""
    w = (d - MID - B) / A
    u, v = FT.F(w.real, w.imag)
    return reg.hit(u, v)


def _tiers(regions, S, drops, A, B):
    """자세마다 통과한 가장 넓은 여유 단계 번호 (0 = 1.5px … 3 = 그 점만, 4 = 그 점도 안 맞음)."""
    tier = np.full(len(A), len(TIERS), np.int8)
    idx = np.arange(len(A))
    for t in range(len(TIERS) - 1, -1, -1):
        mp = TIERS[t]
        for reg, (da, db) in zip(regions, drops):
            for ex, ey in (FT.OFFS if mp else FT.OFFS[:1]):
                if not len(idx):
                    return tier
                idx = idx[_hit(reg, complex(da + ex * mp / S, db + ey * mp / S), A[idx], B[idx])]
        tier[idx] = t
    return tier


def _area(regions, S, drops, A, B):
    """자세마다 둘레 1px 칸(AREA 16점)에서 스포이드가 모두 맞는 비율 — 정수 px 끌기로 닿을 수 있는 정도."""
    hits = np.zeros(len(A))
    for ex, ey in AREA:
        ok = np.ones(len(A), bool)
        for reg, (da, db) in zip(regions, drops):
            ok &= _hit(reg, complex(da + ex / S, db + ey / S), A, B)
        hits += ok
    return hits / len(AREA)


def _judge(regions, S, drops, A, B):
    """자세마다 (여유 단계, 더할 비용) — 여유 0px 자리는 둘레 1px 칸에서 맞는 비율이 낮을수록 비싸다."""
    tier = _tiers(regions, S, drops, A, B)
    extra = np.zeros(len(A))
    z = np.nonzero(tier == len(TIERS) - 1)[0]
    if len(z):
        extra[z] = AREA_COST * (1 - _area(regions, S, drops, A[z], B[z]))
    return tier, extra


class _Pick:
    """찾은 해 모음 — 점수(비용 + 여유 비용) 낮은 것부터."""

    def __init__(self):
        self.A, self.B, self.tier, self.cost = [], [], [], []
        self.n = 0

    def add(self, A, B, tier, cost):
        ok = tier < len(TIERS)
        if ok.any():
            self.A.append(A[ok]), self.B.append(B[ok]), self.tier.append(tier[ok]), self.cost.append(cost[ok])
            self.n += int(ok.sum())
            if self.n > 2 * KEEP:
                self._squash(KEEP)

    def _squash(self, keep):
        A, B, t, c = (np.concatenate(x) for x in (self.A, self.B, self.tier, self.cost))
        order = np.argsort(c + np.asarray(TIER_COST)[t], kind="stable")[:keep]
        self.A, self.B, self.tier, self.cost = [A[order]], [B[order]], [t[order]], [c[order]]
        self.n = len(order)

    def worst(self, k):
        """k 번째로 좋은 점수 (그보다 비용이 큰 짝은 볼 필요 없다)."""
        if self.n < k:
            return math.inf
        self._squash(max(k, self.n))
        sc = self.cost[0] + np.asarray(TIER_COST)[self.tier[0]]
        return float(sc[k - 1])

    def result(self, limit):
        if not self.n:
            return []
        self._squash(limit)
        A, B, t, c = self.A[0], self.B[0], self.tier[0], self.cost[0]
        return [(float(np.degrees(np.angle(a))), float(abs(a)), (float(b.real), float(b.imag)), int(tt), float(cc))
                for a, b, tt, cc in zip(A, B, t, c)]


def solve_pairs(pal, drops, targets, tols, scales=None, max_snap=None, rot_ref=0.0, scale_ref=1.0, rot_win=None,
                limit=40, deadline=None, regions=None):
    """목표 색(BGR)들을 스포이드들이 동시에 집는 자세 [(rot, scale, (px, py), 여유 단계, 비용)] — 좋은 것부터.
    비용 = MOVE_W·(|rot − rot_ref| + 40·|ln(scale / scale_ref)|) (지금 자세에서 덜 움직이는 쪽) + 여유 0px 자리의
    닿기 비용 (AREA_COST), 점수 = score_of.
    scales: 허용 배율 (None = 휠 칸 1.01^n 전부), max_snap: 그 배율에 붙일 때 허용하는 ln 차이,
    rot_win: rot_ref 둘레 이 각도(°) 안만. 스포이드가 하나면 회전·배율은 그대로 두고 끌기만.
    regions: 미리 만든 Region (없으면 targets·tols 로 만든다)."""
    S = pal.S
    drops = [(float(a), float(b)) for a, b in drops]
    if not drops or len(drops) > 3:
        return []
    regs = regions if regions is not None else regions_of(pal, drops, targets, tols)
    if not all(r.any() for r in regs):
        return []
    if max_snap is None:
        max_snap = LN_W / 2 + 1e-9 if scales is None else 0.004
    dz = [complex(a, b) for a, b in drops]
    pick = _Pick()

    if len(drops) == 1:          # 회전·배율 그대로 끌기만
        P = _sites(regs[0].tex)
        s0 = float(scales[0]) if scales is not None else float(scale_ref)
        A = np.full(len(P), s0 * np.exp(1j * math.radians(rot_ref)), complex)
        B = dz[0] - MID - A * P
        t, x = _judge(regs, S, drops, A, B)
        pick.add(A, B, t, x)
        return pick.result(limit)

    # 짝 = 가장 먼 두 스포이드 (회전·배율이 가장 정확하다), 남은 하나는 세 번째
    i, j = max(((i, j) for i in range(len(drops)) for j in range(i + 1, len(drops))),
               key=lambda ij: abs(dz[ij[1]] - dz[ij[0]]))
    rest = [k for k in range(len(drops)) if k not in (i, j)]
    P, Q = _sites(regs[i].tex), _sites(regs[j].tex)
    dd = dz[j] - dz[i]
    ad, ang = abs(dd), np.angle(dd)
    rmin = ad / (FT.SCALE_MAX * math.exp(max_snap))
    rmax = ad / (FT.SCALE_MIN * math.exp(-max_snap))
    lifts = _lifts(rmax)
    ln_ref = math.log(scale_ref)

    def chunk(c0):
        """앞 텍셀 묶음 하나의 짝 → (앞 w, Δw, 붙인 배율, 회전, 비용)."""
        p = P[c0:c0 + CHUNK]
        base = Q[None, :] - p[:, None]
        base = ((base.real + 0.5) % 1.0 - 0.5) + 1j * ((base.imag + 0.5) % 1.0 - 0.5)
        dw = base[:, :, None] + lifts[None, None, :]
        r = np.abs(dw)
        ii, jj, ll = np.nonzero((r >= rmin) & (r <= rmax))
        dw = dw[ii, jj, ll]
        rot = _wrap(np.degrees(ang - np.angle(dw)))
        s2, ok = _snap(ad / np.abs(dw), scales, max_snap)
        drot = np.abs(_wrap(rot - rot_ref))
        if rot_win is not None:
            ok &= drot <= rot_win
        cost = MOVE_W * (drot + LOG_W * np.abs(np.log(s2) - ln_ref))
        return p[ii][ok], dw[ok], s2[ok], rot[ok], cost[ok]

    def pose2(p, dw, s2, rot):
        a = s2 * np.exp(1j * np.radians(rot))
        return a, (dz[i] + dz[j]) / 2 - MID - a * (p + dw / 2)

    if not rest:                 # 두 색: 비용이 낮은 짝부터 확인하고, 더 볼 필요가 없으면 멈춘다
        lo = -1.0
        while True:
            keep, cut = [], math.inf
            for c0 in range(0, len(P), CHUNK):
                if deadline and time.monotonic() > deadline:
                    break
                p, dw, s2, rot, cost = chunk(c0)
                ok = (cost > lo) & (cost < cut)
                keep.append((p[ok], dw[ok], s2[ok], rot[ok], cost[ok]))
                if sum(len(k[0]) for k in keep) > 2 * BAND:
                    cat = [np.concatenate(x) for x in zip(*keep)]
                    part = np.argpartition(cat[4], BAND)[:BAND]
                    keep = [tuple(x[part] for x in cat)]
                    cut = float(keep[0][4].max())
                FT._yield()
            if not keep:
                break
            p, dw, s2, rot, cost = (np.concatenate(x) for x in zip(*keep))
            order = np.argsort(cost, kind="stable")
            for s0 in range(0, len(order), 20000):
                if deadline and time.monotonic() > deadline:
                    break
                sel = order[s0:s0 + 20000]
                if cost[sel[0]] >= pick.worst(limit):
                    break
                a, b = pose2(p[sel], dw[sel], s2[sel], rot[sel])
                t, x = _judge(regs, S, drops, a, b)
                pick.add(a, b, t, cost[sel] + x)
                FT._yield()
            if pick.n or cut == math.inf or (deadline and time.monotonic() > deadline):
                break
            lo = cut             # 이번 구간에 해가 없으면 다음 비용 구간
        return pick.result(limit)

    # 세 색: 짝 자세에서 세 번째가 떨어지는 자리를 보고, 맞거나 가까우면 셋을 다시 맞춘다
    k = rest[0]
    ny, nx, nd = _nearest(regs[k].tex)
    wx, wy = FT.Finv((nx + 0.5) / FT.TEX, (ny + 0.5) / FT.TEX)
    wr_tab = wx + 1j * wy
    Dd = np.array([dz[i], dz[j], dz[k]])
    Dm = Dd.mean()
    Dc = Dd - Dm
    for c0 in range(0, len(P), CHUNK):
        if deadline and time.monotonic() > deadline:
            break
        FT._yield()
        p, dw, s2, rot, cost = chunk(c0)
        if not len(p):
            continue
        cut = pick.worst(limit)
        if math.isfinite(cut):
            ok = cost < cut
            p, dw, s2, rot, cost = p[ok], dw[ok], s2[ok], rot[ok], cost[ok]
        a, b = pose2(p, dw, s2, rot)
        w3 = (dz[k] - MID - b) / a
        u, v = FT.F(w3.real, w3.imag)
        iy, ix = FT._tex(u, v)
        hit = regs[k].hit(u, v)
        if hit.any():            # 짝 자세 그대로
            t, x = _judge(regs, S, drops, a[hit], b[hit])
            pick.add(a[hit], b[hit], t, cost[hit] + x)
        near = nd[iy, ix] <= NEAR
        if not near.any():
            continue
        # 셋을 최소제곱으로: 앞 w, 뒤 w, 세 번째 목표 텍셀 w (세 번째가 떨어진 자리와 같은 주기로)
        wr = wr_tab[iy[near], ix[near]]
        dl = w3[near] - wr
        wr = wr + np.rint(dl.real) + 1j * np.rint(dl.imag)
        W = np.stack([p[near], p[near] + dw[near], wr], 1)
        Wm = W.mean(1)
        Wc = W - Wm[:, None]
        a3 = (np.conj(Wc) * Dc[None, :]).sum(1) / (np.abs(Wc) ** 2).sum(1)
        s3, ok = _snap(np.abs(a3), scales, max_snap)
        a3 = s3 * a3 / np.abs(a3)
        rot3 = np.degrees(np.angle(a3))
        drot = np.abs(_wrap(rot3 - rot_ref))
        if rot_win is not None:
            ok &= drot <= rot_win
        if not ok.any():
            continue
        a3, b3 = a3[ok], (Dm - MID - a3 * Wm)[ok]
        c3 = MOVE_W * (drot[ok] + LOG_W * np.abs(np.log(s3[ok]) - ln_ref))
        t, x = _judge(regs, S, drops, a3, b3)
        pick.add(a3, b3, t, c3 + x)
    return pick.result(limit)
