"""염색 맞출 자리 (mabi/dye/fit·pairs·autofit, gui_app/dye_fit) — 합성 팔레트로 복원·시작 화면 판정·해 찾기·
자동 맞추기·단축키 흐름. 게임·화면 캡처·실제 입력은 쓰지 않는다."""
import math
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from mabi.dye import autofit as AF
from mabi.dye import detect as D
from mabi.dye import fit as FT
from mabi.dye import pairs as PR

DROPS = ((0.3, 0.4), (0.62, 0.7), (0.75, 0.3))


def texture(seed=0, block=6):
    """칸마다 다른 색인 254×254 그림 (행 아래부터) — 실제 팔레트처럼 같은 색 칸이 몇 텍셀씩."""
    rng = np.random.default_rng(seed)
    n = -(-FT.TEX // block)
    cells = rng.integers(0, 256, (n, n, 3), dtype=np.uint8)
    return np.kron(cells, np.ones((block, block, 1), np.uint8))[:FT.TEX, :FT.TEX]


def render(tex, S, pos, rot, scale):
    """게임 계산식대로 팔레트 안쪽 S×S 를 그린다."""
    a, b = FT.grid_ab(S)
    u, v = FT.uv_of(a, b, pos, rot, scale)
    iy, ix = FT._tex(u, v)
    return tex[iy, ix]


def texel(tex, a, b, pos, rot, scale):
    """그 자세에서 화면 정규 좌표 (a, b) 가 집는 색 (BGR) — 게임의 스포이드 판정."""
    iy, ix = FT._tex(*FT.uv_of(np.array(a), np.array(b), pos, rot, scale))
    return tex[iy, ix]


def hex_of(c):
    return "#%02X%02X%02X" % (int(c[2]), int(c[1]), int(c[0]))


def bgr_targets(pal, drops, pos, rot, scale):
    """그 자세에서 스포이드마다 든 텍셀 색 (BGR) — 목표 색은 텍셀 색으로 잡는다."""
    return [np.asarray(pal.color_at(*FT.uv_of(np.array(a), np.array(b), pos, rot, scale), np.array(a)), np.int16)
            for a, b in drops]


def colors_ok(pal, m, drops, targets, tols, margin_px):
    """계산으로 자세 m 에서 스포이드마다 둘레 margin_px 까지 섞인 색이 목표 오차 안인가."""
    return PR.regions_ok(PR.regions_of(pal, drops, targets, tols), pal.S, drops, m, margin_px)


class FakeGame:
    """자동 맞추기 상대 — 입력을 받아 상태를 바꾸고 그 상태의 화면을 그린다.
    실기처럼 회전은 처음 1° 가 먹히고, 화면 시계 방향이 rot 를 줄이며, 휠 한 칸은 ×1.01.
    끌기는 커서가 정수 픽셀이라 정수 px 만 먹는다. 스포이드 색(말풍선)은 섞인 색 (FT.sample, 폭 blend —
    계산 쪽 FT.BLEND 와 일부러 다르게), shift: 스포이드가 실제로 집는 자리가 고리 가운데에서 어긋난 만큼 (px)."""

    def __init__(self, tex, S, blend=0.7, shift=(0.0, 0.0), drops=DROPS, eat=1.0):
        """eat: 회전마다 먹히는 각도 (0 = 시작점에서 멈춰 그려 안 먹히는 경우)."""
        self.tex, self.S, self.blend, self.shift, self.drops, self.eat = tex, S, blend, shift, drops, eat
        self.pos, self.rot, self.scale = (0.0, 0.0), 0.0, 1.0

    def frame(self):
        return render(self.tex, self.S, self.pos, self.rot, self.scale)

    def rotate(self, cx, cy, deg, r):
        d = math.copysign(max(0.0, abs(deg) - self.eat), deg)
        q = math.radians(-d)
        x, y = self.pos           # 가운데를 축으로 무늬가 돈다
        self.pos = (x * math.cos(q) - y * math.sin(q), x * math.sin(q) + y * math.cos(q))
        self.rot -= d

    def wheel(self, x, y, n):
        k = min(FT.SCALE_MAX, max(FT.SCALE_MIN, self.scale * 1.01 ** n)) / self.scale
        self.scale *= k
        self.pos = (self.pos[0] * k, self.pos[1] * k)

    def drag(self, x1, y1, x2, y2):
        dx, dy = round(x2) - round(x1), round(y2) - round(y1)
        self.pos = (self.pos[0] + dx / self.S, self.pos[1] - dy / self.S)

    def color(self, a, b):
        """스포이드 (a, b) 가 지금 집는 색 (BGR)."""
        u, v = FT.uv_of(np.array(a + self.shift[0] / self.S), np.array(b - self.shift[1] / self.S),
                        self.pos, self.rot, self.scale)
        return FT.sample(self.tex, u, v, self.blend)

    def labels(self, frame=None):
        """말풍선 색 — 왼쪽 스포이드부터."""
        return [hex_of(self.color(a, b)) for a, b in sorted(self.drops)]


def rings_of(S, drops=DROPS):
    return [SimpleNamespace(x=round(a * S), y=round((1 - b) * S)) for a, b in drops]


# ---------------------------------------------------------------- 복원·측정·시작 화면
class FitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tex = texture()
        cls.S = 320
        cls.pal = FT.Palette(render(cls.tex, cls.S, (0, 0), 0, 1))

    def test_restore(self):
        # 시작 화면 한 장으로 팔레트 대부분이 원래 색 그대로 나온다
        k = self.pal.known
        self.assertGreater(k.mean(), 0.9)
        self.assertTrue((self.pal.bgr[k] == self.tex[k]).mean() > 0.97)

    def test_measure_moved(self):
        pos, rot, scale = (0.07, -0.04), 23.0, 1.0
        c = render(self.tex, self.S, pos, rot, scale)
        m = FT.measure(c, self.pal, scale=1.0)
        self.assertIsNotNone(m)
        m = FT.refine(c, self.pal, m)
        self.assertLess(abs(AF.wrap(m[1] - rot)), 0.2)
        # 위치는 무늬가 되풀이되는 만큼 달라도 같다 → 같은 화면을 그리는지로 본다
        self.assertGreater((render(self.tex, self.S, m[0], m[1], m[2]) == c).all(-1).mean(), 0.9)

    def test_start_score(self):
        # 실제 크기(1080p 팔레트 749px) — 시작 화면은 통과, 크게 돌린 화면을 시작으로 잡으면 떨어진다.
        # 조금 끌거나 휠 몇 칸은 못 거른다 (그만큼 어긋남도 작고, 마지막 판정은 게임 말풍선 색)
        tex, S = texture(1, block=2), 749
        self.assertGreaterEqual(FT.Palette(render(tex, S, (0, 0), 0, 1)).start_score, FT.START_OK)
        for pose in (((0.05, -0.02), 31.0, 1.0), ((0.0, 0.0), -60.0, 1.0)):
            self.assertLess(FT.Palette(render(tex, S, *pose)).start_score, FT.START_OK, pose)


class SampleTest(unittest.TestCase):
    """스포이드가 집는 섞인 색 (FT.sample) 과 해 찾기가 쓰는 잔 격자 (Palette.fine)."""

    def test_sample_center_and_edge(self):
        img = np.zeros((FT.TEX, FT.TEX, 3), np.uint8)
        img[10, 20] = (200, 100, 50)
        uv = lambda x, y: ((x + 0.5) / FT.TEX, (y + 0.5) / FT.TEX)   # noqa: E731  텍셀 (x, y) 가운데
        self.assertEqual(FT.sample(img, *uv(20, 10)).tolist(), [200, 100, 50])
        # 가운데에서 (1 − w)/2 안쪽은 그대로, 경계(반 텍셀)에서는 이웃과 반반
        u, v = uv(20, 10)
        self.assertEqual(FT.sample(img, u + 0.09 / FT.TEX, v, 0.8).tolist(), [200, 100, 50])
        self.assertEqual(FT.sample(img, u + 0.5 / FT.TEX, v, 0.8).tolist(), [100, 50, 25])
        self.assertEqual(FT.sample(img, u + 0.51 / FT.TEX, v, 0.0).tolist(), [0, 0, 0])   # 폭 0 = 가장 가까운 텍셀

    def test_fine_grid_matches_sample(self):
        tex = texture(2, block=3)
        pal = FT.Palette(render(tex, 320, (0, 0), 0, 1))
        col, known = pal.fine(0)
        n = FT.TEX * FT.FINE
        rng = np.random.default_rng(0)
        ys, xs = rng.integers(0, n, 200), rng.integers(0, n, 200)
        got = FT.sample(pal.bgr, (xs + 0.5) / n, (ys + 0.5) / n)
        self.assertTrue((np.abs(got - col[ys, xs]) <= 1).all())


# ---------------------------------------------------------------- 두 점 짝 해 찾기
class PairsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tex = texture()
        cls.S = 320
        cls.pal = FT.Palette(render(cls.tex, cls.S, (0, 0), 0, 1))

    def check(self, found, drops, tl, tols):
        self.assertTrue(found)
        for rot, scale, pos, tier, cost in found:
            self.assertTrue(colors_ok(self.pal, (pos, rot, scale), drops, tl, tols, margin_px=PR.TIERS[tier]))
            n = math.log(scale) / PR.LN_W            # 배율은 휠 칸
            self.assertAlmostEqual(n, round(n), 6)
            self.assertTrue(FT.SCALE_MIN <= scale <= FT.SCALE_MAX)
        sc = [PR.score_of(f) for f in found]
        self.assertEqual(sc, sorted(sc))                # 좋은 것부터

    def test_two_drops_rotated_and_zoomed(self):
        drops = [(0.2, 0.35), (0.8, 0.6)]
        tl = bgr_targets(self.pal, drops, (0.13, -0.07), 52.0, FT.WHEEL ** 23)
        self.check(PR.solve_pairs(self.pal, drops, tl, [3, 3]), drops, tl, [3, 3])

    def test_three_drops(self):
        drops = list(DROPS)
        tl = bgr_targets(self.pal, drops, (-0.2, 0.31), -71.0, FT.WHEEL ** -17)
        self.check(PR.solve_pairs(self.pal, drops, tl, [3, 3, 3]), drops, tl, [3, 3, 3])

    def test_prefers_near_reference(self):
        # 지금 자세(rot_ref·scale_ref)에서 덜 돌리고 휠을 덜 쓰는 자리부터
        drops = list(DROPS)
        tl = bgr_targets(self.pal, drops, (0.1, 0.05), 40.0, 1.0)
        found = PR.solve_pairs(self.pal, drops, tl, [3, 3, 3], rot_ref=38.0, scale_ref=1.0)
        self.assertTrue(found)
        self.assertLess(abs(AF.wrap(found[0][0] - 38.0)), 10.0)

    def test_fixed_scale_near_rotation(self):
        # 휠 뒤 다시 찾기: 배율은 잰 값 그대로, 회전은 지금 회전 둘레만
        drops = list(DROPS)
        s0 = FT.WHEEL ** 9 * 1.0013                     # 휠 칸에서 조금 어긋난 잰 배율
        tl = bgr_targets(self.pal, drops, (0.05, 0.1), 12.0, s0)
        found = PR.solve_pairs(self.pal, drops, tl, [3, 3, 3], scales=[s0], rot_ref=10.0, scale_ref=s0, rot_win=8.0)
        self.assertTrue(found)
        for rot, scale, pos, tier, cost in found:
            self.assertAlmostEqual(scale, s0, 9)
            self.assertLessEqual(abs(AF.wrap(rot - 10.0)), 8.0 + 1e-9)
            self.assertTrue(colors_ok(self.pal, (pos, rot, scale), drops, tl, [3, 3, 3], margin_px=PR.TIERS[tier]))

    def test_single_drop_drags_only(self):
        drops = [(0.4, 0.55)]
        tl = bgr_targets(self.pal, drops, (0.21, 0.08), 0.0, 1.0)
        found = PR.solve_pairs(self.pal, drops, tl, [3])
        self.assertTrue(found)
        rot, scale, pos, tier, cost = found[0]
        self.assertEqual((rot, scale), (0.0, 1.0))
        self.assertTrue(colors_ok(self.pal, (pos, rot, scale), drops, tl, [3], margin_px=PR.TIERS[tier]))

    def test_isolated_texel_has_no_margin(self):
        # 같은 색이 외딴 텍셀 하나와 6×6 덩어리에 있으면 덩어리를 고른다 — 외딴 텍셀은 스포이드가 이웃과 섞인 색을 집는다
        tex = texture(4)
        c = np.array([17, 203, 99], np.uint8)
        tex[100, 100] = c
        tex[40:46, 160:166] = c
        pal = FT.Palette(render(tex, self.S, (0, 0), 0, 1))
        drops = [(0.4, 0.55)]
        found = PR.solve_pairs(pal, drops, [c.astype(np.int16)], [3], limit=200)
        self.assertTrue(found)
        where = []
        for rot, scale, pos, tier, cost in found:
            iy, ix = FT._tex(*FT.uv_of(np.array(drops[0][0]), np.array(drops[0][1]), pos, rot, scale))
            where.append(((int(iy), int(ix)), tier))
        (iy, ix), tier = where[0]
        self.assertTrue(40 <= iy < 46 and 160 <= ix < 166, where[0])
        self.assertLessEqual(tier, 1)
        self.assertTrue(all(t == len(PR.TIERS) - 1 for p, t in where if p == (100, 100)))

    def test_missing_color(self):
        drops = [(0.2, 0.35), (0.8, 0.6)]
        tl = bgr_targets(self.pal, drops, (0, 0), 0.0, 1.0)
        tl[1] = np.array([-50, 0, 0], np.int16)          # 없는 색
        self.assertEqual(PR.solve_pairs(self.pal, drops, tl, [3, 3]), [])

    def test_nearest_table_wraps(self):
        m = np.zeros((FT.TEX, FT.TEX), bool)
        m[0, 0] = True
        ny, nx, nd = PR._nearest(m)
        self.assertEqual((int(ny[FT.TEX - 1, FT.TEX - 1]), int(nx[FT.TEX - 1, FT.TEX - 1])), (0, 0))   # 감싸서 바로 옆
        self.assertLess(float(nd[FT.TEX - 1, FT.TEX - 1]), 1.5)


# ---------------------------------------------------------------- Session: 세 색 → 두 색, 안내, 게임 판정
class SessionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tex = texture(3)
        cls.S = 320
        cls.frame = render(cls.tex, cls.S, (0, 0), 0, 1)

    def session(self):
        return AF.Session(self.frame, D.Palette(0, 0, self.S, self.S), rings_of(self.S), [])

    def targets(self, pose, tol=3):
        return [D.target(hex_of(texel(self.tex, a, b, *pose)), tol) for a, b in DROPS]

    def test_three_colors(self):
        s = self.session()
        self.assertTrue(s.start_ok)
        self.assertTrue(s.solve(self.targets(((0.1, 0.05), 37.0, 1.0)), AF.START_POSE))
        self.assertEqual((s.use, s.left_out), ([0, 1, 2], []))
        g = s.goal
        self.assertTrue(s.ok((g[2], g[0], g[1]), margin_px=0))

    def test_falls_back_to_two(self):
        # 세 색이 같이 안 되면 두 색이 되는 가장 좋은 자리 — 안 되는 칸은 빼고 안내 앞에 붙인다
        s = self.session()
        tg = self.targets(((0.1, 0.05), 37.0, 1.0))
        tg[2] = D.target("#010203", 0)
        self.assertTrue(s.solve(tg, AF.START_POSE))
        self.assertEqual((s.use, s.left_out), ([0, 1], [2]))
        self.assertTrue(s.guide(AF.START_POSE)["text"].startswith("3번 빼고 — "))

    def test_empty_slot_is_not_left_out(self):
        s = self.session()
        tg = self.targets(((0.1, 0.05), 37.0, 1.0))
        tg[1] = None
        self.assertTrue(s.solve(tg, AF.START_POSE))
        self.assertEqual((s.want, s.use, s.left_out), ([0, 2], [0, 2], []))

    def test_no_place(self):
        s = self.session()
        self.assertFalse(s.solve([D.target("#010203", 0), None, None], AF.START_POSE))
        self.assertEqual(s.guide(AF.START_POSE), {"points": [], "text": "이 색으로 잡을 수 있는 자리가 없습니다",
                                                  "done": False})

    def test_caught_by_slot_position(self):
        # 게임 판정은 칸 i ↔ 왼쪽부터 i 번째 스포이드 — 색이 맞아도 자리가 바뀌면 아니다
        s = self.session()
        self.assertTrue(s.solve([D.target("#112233", 3), D.target("#445566", 3), None], AF.START_POSE) or True)
        s.use, s.targets = [0, 1], {0: D.target("#112233", 3), 1: D.target("#445566", 3)}
        ring = lambda x, h: SimpleNamespace(x=x, hex=h)   # noqa: E731
        self.assertTrue(s.caught([ring(30, "#112234"), ring(200, "#445566"), ring(260, "#000000")]))
        self.assertTrue(s.caught([ring(200, "#445566"), ring(30, "#112233")]))   # 순서는 x 로 다시 센다
        self.assertFalse(s.caught([ring(30, "#445566"), ring(200, "#112233")]))
        self.assertFalse(s.caught([ring(30, "#112233")]))

    def test_at_start(self):
        s = self.session()
        self.assertTrue(s.at_start(self.frame))
        self.assertFalse(s.at_start(render(self.tex, self.S, (0.02, 0), 0, 1)))


class GuideTest(unittest.TestCase):
    def bare(self, goal):
        s = AF.Session.__new__(AF.Session)
        s.box, s.S = D.Palette(0, 0, 100, 100), 100
        s.goal, s.use, s.left_out = goal, [0], []
        s.drops, s.rings = [(0.5, 0.5)], [SimpleNamespace(x=50, y=50)]
        return s

    def test_steps(self):
        m = ((0.0, 0.0), 0.0, 1.0, 0, 1.0)
        self.assertEqual(self.bare((10.0, 1.0, (0, 0))).guide(m)["text"], "오른쪽 버튼으로 반시계 방향 10° 돌리기")
        self.assertEqual(self.bare((-25.0, 1.0, (0, 0))).guide(m)["text"], "오른쪽 버튼으로 시계 방향 25° 돌리기")
        self.assertEqual(self.bare((0.0, FT.WHEEL ** 3, (0, 0))).guide(m)["text"], "휠 위로 3칸")
        self.assertEqual(self.bare((0.0, FT.WHEEL ** -2, (0, 0))).guide(m)["text"], "휠 아래로 2칸")
        g = self.bare((0.0, 1.0, (0.1, 0))).guide(m)
        self.assertEqual(g["text"], "점을 같은 색 스포이드에 겹치게 끌기")
        self.assertEqual(len(g["points"]), 1)
        self.assertFalse(g["done"])

    def test_caught_wins(self):
        g = self.bare((10.0, 1.0, (0, 0))).guide(None, caught=True)
        self.assertEqual(g, {"points": [], "text": "맞았습니다 — 확인하고 적용하세요", "done": True})

    def test_end_points_exact(self):
        # 회전 끝점은 정수 픽셀이어도 0.01° 안쪽으로 맞는다
        for deg in (0.1, -0.37, 5.0, -81.2):
            (sx, sy), (ex, ey), got = AF.end_points(deg, 340)
            self.assertLess(abs(got - deg), 0.01)
            self.assertAlmostEqual(AF.wrap(math.degrees(math.atan2(ey, ex) - math.atan2(sy, sx))), got, 6)


# ---------------------------------------------------------------- 자동 맞추기
class AutoDriverTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(AF.AutoDriver, "SETTLE", 0.0)
        p.start()
        self.addCleanup(p.stop)

    def run_case(self, seed, pose, tex=None, spoil=None, **kw):
        """seed 그림에서 pose 자리 세 색을 목표로 자동 맞추기. spoil(game, sess): 해를 찾은 뒤 게임만 바꾼다."""
        tex, S = (texture(seed) if tex is None else tex), 320
        tg = [D.target(hex_of(texel(tex, a, b, *pose)), 3) for a, b in DROPS]
        game = FakeGame(tex.copy(), S, **kw)
        sess = AF.Session(game.frame(), D.Palette(0, 0, S, S), rings_of(S), [])
        self.assertTrue(sess.solve(tg, AF.START_POSE))
        if spoil:
            spoil(game, sess)
        sess.last = AF.START_POSE
        drv = AF.AutoDriver(sess, game.frame, game, threading.Event(), read=game.labels)
        ok, m = drv.run()
        self.assertTrue(ok, f"자세 {m and (round(m[1], 2), round(m[2], 4))} 목표 {sess.goal[:2]} 말풍선 {game.labels()}")
        self.assertTrue(drv.by_label)
        self.assertTrue(sess.caught_hex(game.labels()))           # 게임이 띄운 색으로 맞았다
        return drv, sess

    def test_reaches_goal(self):
        self.run_case(3, ((0.1, 0.05), 37.0, 1.0))

    def test_reaches_zoomed_goal(self):
        self.run_case(5, ((-0.12, 0.2), -24.0, FT.WHEEL ** 14))

    def test_reaches_goal_when_rotation_not_eaten(self):
        # 먹히는 각도는 큰 회전에서 재 둔다 — 안 먹히면 미세 회전에 덧붙이지 않는다
        drv, _ = self.run_case(3, ((0.1, 0.05), 37.0, 1.0), eat=0.0)
        self.assertLess(drv.rot_dead, 0.1)

    def test_feels_around_when_dropper_is_off(self):
        # 스포이드가 실제로 집는 자리가 고리 가운데에서 1.4px 어긋나 계산 자리에선 안 맞는다 → 말풍선을 보며 둘레를 끈다
        drv, _ = self.run_case(3, ((0.1, 0.05), 37.0, 1.0), shift=(1.4, -1.1))
        self.assertGreater(drv.probes, 0)

    def test_locate_finds_dropper_offset(self):
        # 말풍선 세 색으로 스포이드가 실제로 집는 자리 (고리 가운데에서 어긋난 만큼)를 역으로 찾는다
        tex, S = texture(8, block=1), 749
        drops = [(round(a * S) / S, 1 - round((1 - b) * S) / S) for a, b in DROPS]   # 고리 자리 = 정수 px
        game = FakeGame(tex, S, shift=(1.5, -0.75), drops=drops)
        sess = AF.Session(game.frame(), D.Palette(0, 0, S, S), rings_of(S, drops), [])
        drv = AF.AutoDriver(sess, game.frame, game, threading.Event(), read=game.labels)
        d = drv.locate(AF.START_POSE, game.labels())
        self.assertIsNotNone(d)
        self.assertLess(math.hypot(d[0] - 1.5, d[1] + 0.75), 0.3, d)
        self.assertIsNone(drv.locate(AF.START_POSE, [None, game.labels()[1], None]))   # 하나로는 못 찾는다

    def test_bans_wrong_color_and_finds_another(self):
        # 계산이 고른 자리의 1번 색이 게임에선 다르다 (복원 색이 틀린 셈). 같은 세 색을 다른 자리에도 심어 두면
        # 둘레를 끌어 봐도 안 될 때 그 무리를 빼고 다시 찾아 그 자리로 간다
        pose, other = ((0.1, 0.05), 37.0, 1.0), ((-0.3, -0.2), -12.0, 1.0)
        tex = texture(3)
        for a, b in DROPS:
            iy, ix = (int(x) for x in FT._tex(*FT.uv_of(np.array(a), np.array(b), *other)))
            tex[iy - 2:iy + 3, ix - 2:ix + 3] = texel(tex, a, b, *pose)

        def spoil(game, sess):
            g = sess.goal
            a, b = sess.drops[0]
            iy, ix = (int(x) for x in FT._tex(*FT.uv_of(np.array(a), np.array(b), g[2], g[0], g[1])))
            sl = (slice(iy - 6, iy + 7), slice(ix - 6, ix + 7))
            c = tex[iy, ix]
            game.tex[sl] = np.where((game.tex[sl] == c).all(-1)[..., None], ((c.astype(int) + 90) % 256).astype(np.uint8),
                                    game.tex[sl])

        drv, sess = self.run_case(3, pose, tex=tex, spoil=spoil)
        self.assertGreaterEqual(drv.resolves, 1)
        self.assertEqual(sess.use, [0, 1, 2])

    def test_stops(self):
        tex, S = texture(3), 320
        game = FakeGame(tex, S)
        sess = AF.Session(game.frame(), D.Palette(0, 0, S, S), rings_of(S), [])
        self.assertTrue(sess.solve([D.target(hex_of(texel(tex, a, b, (0.1, 0.05), 37.0, 1.0)), 3)
                                    for a, b in DROPS], AF.START_POSE))
        stop = threading.Event()
        stop.set()
        with self.assertRaises(AF.Stopped):
            AF.AutoDriver(sess, game.frame, game, stop).run()


# ---------------------------------------------------------------- 단축키 흐름 (gui_app/dye_fit.FitAssist)
class _Ring:
    """스포이드 — hex 는 게임이 지금 띄우는 색 (지금 자세에서 스포이드 자리 섞인 색)."""

    def __init__(self, game, a, b):
        self.game, self.a, self.b = game, a, b
        self.x, self.y = round(a * game.S), round((1 - b) * game.S)

    @property
    def hex(self):
        return hex_of(self.game.color(self.a, self.b))


class _NoHands:
    why = ""

    def close(self):
        pass


class FitAssistTest(unittest.TestCase):
    S = 320
    GOAL = ((0.1, 0.05), 37.0, 1.0)

    def setUp(self):
        from gui_app import dye_fit
        self.dye_fit = dye_fit
        for p in (mock.patch.object(dye_fit, "START_AFTER", 0.0), mock.patch.object(AF.AutoDriver, "SETTLE", 0.0)):
            p.start()
            self.addCleanup(p.stop)
        self.tex = texture(3)
        self.game = FakeGame(self.tex, self.S)
        self.events = []
        rings = [_Ring(self.game, a, b) for a, b in DROPS]
        targets = [D.target(hex_of(texel(self.tex, a, b, *self.GOAL)), 3) for a, b in DROPS]
        self.tr = SimpleNamespace(box=D.Palette(0, 0, self.S, self.S), lead=SimpleNamespace(rings=rings, skip=[]),
                                  lead_ok=True, moving=False, mats=None, bands=None, mats_of=lambda img: None,
                                  slot_targets=lambda: list(targets))
        self.st = SimpleNamespace(status="active", redraw=True, rings=rings)
        self.fa = dye_fit.FitAssist(repaint=lambda: None, emit=self.events.append, focus=lambda: None,
                                    rect=lambda: (0, 0, self.S, self.S), refs=lambda: None, key=lambda: "f10",
                                    mouse=lambda to_screen, stop: self.game, hands=lambda *a, **k: _NoHands(),
                                    snap=self.game.frame)

    def open_palette(self, ticks=4):
        for _ in range(ticks):
            self.fa.observe(self.game.frame(), self.st, self.tr, True)

    def wait(self, cond, limit=60.0):
        t = time.monotonic() + limit
        while time.monotonic() < t:
            if cond():
                return True
            time.sleep(0.02)
        self.fail(f"기다림 초과 — 단계 {self.fa.phase}, 문구 {self.fa.text!r}")

    def test_find_then_auto(self):
        self.fa.closed()                       # 도우미를 켜 둔 채 미니게임이 열린다
        self.open_palette()
        self.assertIsNotNone(self.fa.start)
        self.assertEqual(self.fa.press(), {"ok": True})
        self.wait(lambda: self.fa.phase == "shown")
        self.assertEqual(len(self.fa.points), 3)
        self.assertIn("F10 한 번 더 = 자동", self.fa.text)
        self.assertIn({"fit": "shown", "goal": True}, self.events)
        self.assertEqual(self.fa.press(), {"ok": True, "auto": True})
        self.wait(lambda: self.fa.phase == "shown" and self.fa.done)
        self.assertEqual(self.fa.text, "맞았습니다 — 확인하고 적용하세요")
        self.assertEqual(self.fa.overlay(), {"points": [], "text": self.fa.text, "done": True})

    def test_press_again_stops_auto(self):
        self.fa.closed()
        self.open_palette()
        self.fa.press()
        self.wait(lambda: self.fa.phase == "shown")
        self.fa.press()
        self.assertEqual(self.fa.press(), {"ok": True, "stopped": True})
        self.wait(lambda: self.fa.phase == "shown" and self.fa.text.startswith("자동 맞추기를 멈췄습니다"))

    def test_needs_fresh_palette(self):
        # 도우미를 켜기 전에 이미 열려 있던 팔레트는 시작 상태를 몰라 찾지 않는다
        self.open_palette()
        self.assertIsNone(self.fa.start)
        self.assertEqual(self.fa.press(), {"error": "팔레트를 열기 전에 염색 도우미를 켜 두어야 합니다"})

    def test_packet_open_keeps_start(self):
        # 패킷이 열렸다고 하면 화면에서 잠깐 가려져도 시작 화면을 버리지 않는다. 닫히면 버린다
        self.fa.closed()
        self.open_palette()
        hidden = SimpleNamespace(status="waiting", redraw=True, rings=[])
        gone = SimpleNamespace(box=None)
        for _ in range(20):
            self.fa.observe(self.game.frame(), hidden, gone, True)
        self.assertIsNotNone(self.fa.start)
        self.fa.closed()
        self.assertIsNone(self.fa.start)

    def test_unknown_mixed_materials_refused(self):
        # 재질이 갈린 옷인데 칸 재질을 모르면 한 재질로 되짚어 헤매지 않고 다시 열어 달라고 한다 (2026-11-25)
        self.tr.bands = [(0, 100), (100, 200), (200, self.S)]
        self.fa.refs = lambda: {"Cloth": np.zeros((8, 8, 3), np.uint8)}
        self.fa.closed()
        self.open_palette()
        self.fa.press()
        self.wait(lambda: self.fa.phase == "idle" and "재질" in self.fa.text)
        self.assertEqual(self.fa.text, "옷 재질을 읽지 못했습니다 — 팔레트를 다시 열어 주세요")
        self.assertIsNone(self.fa.sess)

    def test_retarget_clears_guide(self):
        self.fa.closed()
        self.open_palette()
        self.fa.press()
        self.wait(lambda: self.fa.phase == "shown")
        self.fa.retarget()
        self.assertEqual((self.fa.phase, self.fa.text, self.fa.points), ("idle", "", []))
        self.assertIsNone(self.fa.overlay())


# ---------------------------------------------------------------- 주변: 칸 목표·그리기·단축키
class SlotTargetsTest(unittest.TestCase):
    def test_empty_slot_keeps_place(self):
        from mabi.dye.tracker import DyeTracker
        t = DyeTracker()
        t.set_targets(["#112233", "", "#445566"], [None, None, 9])
        st = t.slot_targets()
        self.assertEqual([x and x.hex for x in st], ["#112233", None, "#445566"])
        self.assertEqual(st[2].tol_or_default, 9)


class GuideDrawTest(unittest.TestCase):
    def test_guide_points_and_banner(self):
        from mabi.dye import draw
        from mabi.dye.tracker import DyeState
        st = DyeState("active", "x", "ok")
        gd = {"points": [(1, 100.0, 50.0, 80, 40)], "text": "돌리세요", "done": False}
        items = draw.overlay_items(st, guide=gd, slots=["#112233", "#445566", "#778899"])
        circles = [it for it in items if it.kind == "circle" and it.stroke and it.stroke.color == draw.rgba("#445566")]
        self.assertTrue(any((c.cx, c.cy) == (100, 50) for c in circles))
        self.assertTrue(any(it.kind == "text" and it.text == "돌리세요" for it in items))
        self.assertFalse(any(it.kind == "text" and it.text == "돌리세요" for it in draw.overlay_items(st)))


class FitKeyTest(unittest.TestCase):
    def test_key_only_while_helper_runs(self):
        from gui_app.api import Api

        class Dyes:
            running = False
            pressed = 0

            def fit_press(self):
                self.pressed += 1
                return {"ok": True}
        a = Api.__new__(Api)
        a.dyes = Dyes()
        a._dye_fit_key()
        self.assertEqual(a.dyes.pressed, 0)
        a.dyes.running = True
        a._dye_fit_key()
        self.assertEqual(a.dyes.pressed, 1)

    def test_own_keys(self):
        from mabi import keys
        cfg = {"game": {"stop_key": "f12", "dye_key": "f11", "dye_fit_key": "f10"}}
        self.assertEqual(keys._own_keys(cfg), {"f12", "f11", "f10"})

    def test_save_checks(self):
        from gui_app import daily_api

        def save(v):
            api = daily_api.DailyApi.__new__(daily_api.DailyApi)
            doc = {"silver": {}, "game": {"stop_key": "f12", "dye_key": "f11", "dye_fit_key": "f10"}}
            api._doc = lambda: doc
            api.paths = mock.Mock()
            with mock.patch.object(daily_api.userconfig, "save"):
                return api.daily_saveSettings(v), doc
        r, doc = save({"dye_fit_key": "f9"})
        self.assertNotIn("error", r or {})
        self.assertEqual(doc["game"]["dye_fit_key"], "f9")
        self.assertIn("error", save({"dye_fit_key": "f11"})[0])      # 염색 도우미 키와 같다
        self.assertIn("error", save({"dye_fit_key": "x"})[0])        # F 키만
        self.assertIn("error", save({"game_keys": {"camera": "f10"}})[0])   # 게임 단축키로 못 쓴다


if __name__ == "__main__":
    unittest.main()
