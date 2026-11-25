"""두 점 짝으로 맞출 자리 찾기 (2026-11-25) — 예전 격자(배율 37 × 회전 360, 최대 25초)를 갈음한다.

스포이드 두 개가 각각 어느 목표 텍셀에 떨어질지 짝을 정하면 회전·배율·위치가 한 번에 정해진다.
  d = (0.5 + 0.5i) + pos + a·w   (복소수: a = scale·e^{i·rot}, w = 비틀기 전 평면, 주기 1)
  → a = (d_j − d_i) / (w_j − w_i)
세 번째 스포이드는 그 자세에서 떨어지는 자리를 보고, 목표 텍셀이 가까우면 셋을 최소제곱으로 다시 맞춘다.
배율은 휠 칸(×1.01)으로만 바뀌므로 가장 가까운 칸에 붙이고, 둘레 여유(fit.OFFS)까지 실제 계산식으로 확인한다.
저장 화면 시험(오차 10, 세 색): 예전 평균 3.7초·최대 20초 → 평균 0.5초·최대 1.8초.
"""
from __future__ import annotations

import math
import time

import cv2
import numpy as np

from . import fit as FT

TIERS = (1.5, 1.0, 0.5)        # 스포이드 둘레 여유 (화면 px) — 넓을수록 입력 오차에 강하다
TIER_COST = (0.0, 10.0, 25.0)  # 여유가 좁을수록 더하는 비용 (회전 1° 와 같은 단위)
LOG_W = 40.0                   # 비용 = |회전 차이°| + 40·|ln 배율 비| (휠 10칸 ≈ 4°)
MAX_SITES = 1200               # 스포이드마다 짝에 쓸 목표 텍셀 상한 (넘으면 칸마다 가장 안쪽 하나)
NEAR = 2.5                     # 세 번째 스포이드: 이 텍셀 거리 안에 목표 텍셀이 있으면 셋을 다시 맞춘다
CHUNK = 32                     # 한 번에 펼칠 앞 텍셀 수
BAND = 300_000                 # 두 색: 비용이 낮은 짝부터 이만큼씩 확인
KEEP = 4000                    # 세 색: 모아 두는 해 상한 (넘으면 좋은 것만)
MID = 0.5 + 0.5j               # 팔레트 가운데 (정규 좌표, 복소수)
LN_W = math.log(FT.WHEEL)
N_MIN = math.ceil(math.log(FT.SCALE_MIN) / LN_W)
N_MAX = math.floor(math.log(FT.SCALE_MAX) / LN_W)


def masks_of(pal, drops, targets, tols):
    """스포이드마다 그 칸 재질 팔레트에서 목표 오차 안이고 아는 텍셀. targets 는 BGR.
    그림 가장자리 2텍셀은 뺀다 — 원본 Cloth 마지막 열(253)은 전부 검정인데 화면 팔레트엔 안 그려진다."""
    out = []
    for (a, _), t, tol in zip(drops, targets, tols):
        k = int(pal.strip(a))
        m = (FT.diff(pal.kbgr[k], t) <= tol) & pal.kknown[k]
        m[:2], m[-2:], m[:, :2], m[:, -2:] = False, False, False, False
        out.append(m)
    return out


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


def _hit(mask, d, A, B):
    """자세(A = scale·e^{i rot}, B = pos)에서 화면 점 d 가 집는 텍셀이 mask 안인가."""
    w = (d - MID - B) / A
    u, v = FT.F(w.real, w.imag)
    iy, ix = FT._tex(u, v)
    return mask[iy, ix]


def _tiers(masks, S, drops, A, B):
    """자세마다 통과한 가장 넓은 여유 단계 번호 (0 = 1.5px … 2 = 0.5px, 3 = 0.5px 도 못 넘음)."""
    tier = np.full(len(A), len(TIERS), np.int8)
    idx = np.arange(len(A))
    for t in range(len(TIERS) - 1, -1, -1):
        mp = TIERS[t]
        for mask, (da, db) in zip(masks, drops):
            for ex, ey in FT.OFFS:
                if not len(idx):
                    return tier
                idx = idx[_hit(mask, complex(da + ex * mp / S, db + ey * mp / S), A[idx], B[idx])]
        tier[idx] = t
    return tier


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
                limit=40, deadline=None):
    """목표 색(BGR)들을 스포이드들이 동시에 집는 자세 [(rot, scale, (px, py), 여유 단계, 비용)] — 좋은 것부터.
    비용 = |rot − rot_ref| + 40·|ln(scale / scale_ref)| (지금 자세에서 덜 움직이는 쪽), 점수 = score_of.
    scales: 허용 배율 (None = 휠 칸 1.01^n 전부), max_snap: 그 배율에 붙일 때 허용하는 ln 차이,
    rot_win: rot_ref 둘레 이 각도(°) 안만. 스포이드가 하나면 회전·배율은 그대로 두고 끌기만."""
    S = pal.S
    drops = [(float(a), float(b)) for a, b in drops]
    if not drops or len(drops) > 3:
        return []
    masks = masks_of(pal, drops, targets, tols)
    if not all(m.any() for m in masks):
        return []
    if max_snap is None:
        max_snap = LN_W / 2 + 1e-9 if scales is None else 0.004
    dz = [complex(a, b) for a, b in drops]
    pick = _Pick()

    if len(drops) == 1:          # 회전·배율 그대로 끌기만
        P = _sites(masks[0])
        s0 = float(scales[0]) if scales is not None else float(scale_ref)
        A = np.full(len(P), s0 * np.exp(1j * math.radians(rot_ref)), complex)
        B = dz[0] - MID - A * P
        pick.add(A, B, _tiers(masks, S, drops, A, B), np.zeros(len(P)))
        return pick.result(limit)

    # 짝 = 가장 먼 두 스포이드 (회전·배율이 가장 정확하다), 남은 하나는 세 번째
    i, j = max(((i, j) for i in range(len(drops)) for j in range(i + 1, len(drops))),
               key=lambda ij: abs(dz[ij[1]] - dz[ij[0]]))
    rest = [k for k in range(len(drops)) if k not in (i, j)]
    P, Q = _sites(masks[i]), _sites(masks[j])
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
        cost = drot + LOG_W * np.abs(np.log(s2) - ln_ref)
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
                pick.add(a, b, _tiers(masks, S, drops, a, b), cost[sel])
                FT._yield()
            if pick.n or cut == math.inf or (deadline and time.monotonic() > deadline):
                break
            lo = cut             # 이번 구간에 해가 없으면 다음 비용 구간
        return pick.result(limit)

    # 세 색: 짝 자세에서 세 번째가 떨어지는 자리를 보고, 맞거나 가까우면 셋을 다시 맞춘다
    k = rest[0]
    ny, nx, nd = _nearest(masks[k])
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
        hit = masks[k][iy, ix]
        if hit.any():            # 짝 자세 그대로
            pick.add(a[hit], b[hit], _tiers(masks, S, drops, a[hit], b[hit]), cost[hit])
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
        c3 = drot[ok] + LOG_W * np.abs(np.log(s3[ok]) - ln_ref)
        pick.add(a3, b3, _tiers(masks, S, drops, a3, b3), c3)
    return pick.result(limit)
