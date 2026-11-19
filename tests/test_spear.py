"""흩어진 물길 투창병 속성 패턴 — 패킷 상태(spear.SpearState)와 이동 키 고르기."""
import math
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from mabi.packet_monitor import PacketMonitor
from mabi.spear import (FANG_KIND, RIFT_PASS, RIFTS, SHAMAN_ATTR, SPEAR_ATTR, SPEAR_MARK, TARGET_MARK, WAVE_KIND,
                        exits, wave_line)
from mabi.tasks.spear import SpearDodge
from mabi.tictactoe import FORECAST, choose

ME, OTHER, SPEAR = 100, 200, 300
LAYOUT = {"독": (-10, 142), "번개": (-10, 151), "얼음": (-10, 160), "불": (10, 142), "어둠": (10, 151), "빛": (10, 160)}
SH = {n: 1000 + i for i, n in enumerate(LAYOUT)}
BUFF = {v: k for k, v in SHAMAN_ATTR.items()}
SPEAR_BUFF = {v: k for k, v in SPEAR_ATTR.items()}


class SpearStateTest(unittest.TestCase):
    def setUp(self):
        self.m = PacketMonitor(None)
        self.m.status = "running"
        self.m.state.me = ME
        self.enter("흩어진 물길 (어비스 시즌2 3구역 매우 어려움2 솔로)")

    def enter(self, name, kind="InstanceAbyssDungeon"):
        self.m.apply("channel.entering", {"channel": 1, "channel_type": kind, "channel_name": name})

    def feed(self, key, **v):
        self.m._spear(key, v)

    def summon(self):
        for n, (x, y) in LAYOUT.items():
            self.feed("spear.monster", actor=SH[n], x=float(x), y=float(y))
        self.feed("spear.monster", actor=SPEAR, x=0.0, y=0.0)  # 투창병은 이 칸이 위치가 아니다
        self.feed("spear.buff", actor=SPEAR, buff=SPEAR_MARK, caster=SPEAR)
        for n in LAYOUT:
            self.feed("spear.buff", actor=SH[n], buff=BUFF[n], caster=SH[n])

    def throw(self, attr=None, target=ME):
        if attr:
            self.feed("spear.buff", actor=SPEAR, buff=SPEAR_BUFF[attr], caster=SPEAR)
        self.feed("spear.buff", actor=target, buff=TARGET_MARK, caster=SPEAR)

    def test_only_in_scattered_waterway(self):
        self.assertTrue(self.m.spear.active)
        self.enter("다른 어비스")
        self.assertFalse(self.m.spear.active)
        self.enter("흩어진 물길", kind="Field")  # 같은 이름이라도 어비스 맵이 아니면
        self.assertFalse(self.m.spear.active)

    def test_target_me_goes_to_same_attr_shaman(self):
        self.summon()
        self.throw("불")
        st = self.m.spear
        self.assertTrue(st.due())
        job = st.take()
        self.assertEqual((job["attr"], job["x"], job["y"]), ("불", 10, 142))
        self.assertFalse(st.due())  # 한 번 맡으면 끝

    def test_other_character_target_ignored(self):
        """함께하기 — 다른 캐릭터에 걸리면 움직이지 않는다."""
        self.summon()
        self.throw("독", target=OTHER)
        self.assertFalse(self.m.spear.due())

    def test_repeat_same_attr_until_broken(self):
        """못 깨면 속성 버프 없이 대상 표시만 다시 온다 → 남은 속성으로."""
        self.summon()
        self.throw("어둠")
        self.m.spear.take()
        self.throw()
        self.assertEqual(self.m.spear.take()["attr"], "어둠")
        t = time.monotonic() - 1
        self.feed("spear.break", actor=SH["어둠"])
        self.assertTrue(self.m.spear.broken_since(SH["어둠"], t))
        self.assertIsNone(self.m.spear.pending)

    def test_unknown_layout_does_not_move(self):
        self.throw("빛")  # 소환을 못 봄 (판 도중에 켬)
        self.assertTrue(self.m.spear.due())
        self.assertIsNone(self.m.spear.take())

    def test_finished_when_shamans_die(self):
        """투창병이 쓰러지면 주술사도 모두 쓰러진다 → 이 맵의 패턴 끝 (사용자: 주술사가 죽었다 == 투창병이 죽었다)."""
        self.summon()
        for n in LAYOUT:
            self.assertFalse(self.m.spear.finished)
            self.m.apply("actor.dead", {"actor": SH[n], "dead": True})
        self.assertTrue(self.m.spear.finished)
        self.throw("불")
        self.assertFalse(self.m.spear.due())

    def test_party_satiety_keeps_me(self):
        """함께하기 — 다른 캐릭터 포만감 패킷이 내 번호를 덮어써 내게 걸린 대상 표시를 놓쳤다 (11-03 16:05)."""
        self.summon()
        self.m.apply("char.satiety", {"actor": OTHER, "satiety": 80})
        self.assertEqual(self.m.state.me, ME)
        self.throw("어둠")
        self.assertTrue(self.m.spear.due())

    def test_new_map_resets(self):
        self.summon()
        self.enter("흩어진 물길 (어비스 시즌2 3구역 매우 어려움2 솔로)")
        self.assertEqual(self.m.spear.attr, {})

    def test_positions_and_spear_home(self):
        self.summon()
        self.feed("spear.move_update", actor=ME, x=1.5, y=160.0)
        self.assertEqual(self.m.spear.where(ME, 1.0), (1.5, 160.0))
        self.assertEqual(self.m.spear.spear_home(), (0.0, 163.0))  # 투창병 자리를 못 봤으면 제자리
        self.feed("spear.move_update", actor=SPEAR, x=3.1, y=0.0)  # 위치가 아닌 값 — 믿지 않는다
        self.assertEqual(self.m.spear.spear_home(), (0.0, 163.0))


class TicTacToeTest(unittest.TestCase):
    """보스 틱택토 — 11-03 abyss_runs/boss2 순서 재생과 고르기 (사용자: 첫 X 상하좌우 → 귀퉁이 · 반대 귀퉁이 · 가운데)."""
    BOSS, C = 900, 400

    def setUp(self):
        SpearStateTest.setUp(self)

    enter, feed = SpearStateTest.enter, SpearStateTest.feed

    def walk(self, actor, x, y):
        self.feed("spear.path", actor=actor, points=2, x=x, y=y)

    def turn(self, drawer, x_at):
        self.walk(self.BOSS, *x_at)  # 보스가 칸 가운데로 걸어가 X
        self.feed("spear.timeline", actor=drawer, name=FORECAST)

    def draw(self, drawer, x, y):
        self.m.spear.ttt.turn_at -= 5  # 차례 시작 뒤 몇 초 지나 보스가 담당 자리로 출발
        self.walk(self.BOSS, x, y)

    def test_boss2_replay(self):
        ttt = self.m.spear.ttt
        self.walk(ME, -3.4, 363.3)  # 플레이어 경로 이동은 칸 가운데가 아니라 X 로 안 본다
        self.turn(ME, (0.0, 375.5))
        self.assertTrue(ttt.due())
        job = ttt.take()
        self.assertIn(job["cell"], [(0, 0), (2, 0)])  # X 가 아래 가운데 → 먼 쪽(위) 귀퉁이
        self.draw(ME, -9.6, 375.4)  # 실제로는 사람이 아래 왼쪽에 둠
        self.turn(ME, (9.0, 366.5))
        self.assertEqual(ttt.take()["cell"], (2, 0))  # 반대 귀퉁이 → 가운데가 남아 반드시 이김
        self.draw(ME, 9.4, 358.0)
        self.turn(self.C, (-9.0, 357.5))
        self.assertFalse(ttt.due())  # 다른 캐릭터가 담당
        self.draw(self.C, 0.3, 366.5)
        self.assertTrue(ttt.done)
        self.assertEqual(ttt.text(), "X.O/.OX/OX.")

    def test_tie_goes_to_nearest(self):
        """점수가 같은 칸이면 내 자리에서 가까운 칸 (사용자 11-04)."""
        from mabi.tictactoe import choose
        b = {(1, 2): "X"}  # 아래 가운데 X → 위 두 귀퉁이가 같은 점수
        self.assertEqual(choose(b, (8.0, 360.0)), (2, 0))
        self.assertEqual(choose(b, (-8.0, 360.0)), (0, 0))
        self.assertEqual(choose({(0, 0): "O", (2, 2): "O"}, (9.0, 357.5)), (1, 1))  # 이기는 칸은 거리와 상관없이
        # 위 가운데 X 에 내가 그 옆 → 열린 줄이 하나 적어도 가까운 X 옆 귀퉁이 (11-04 15:44 은 반대편으로 뛰었다)
        self.assertEqual(choose({(1, 0): "X"}, (5.0, 358.0)), (2, 0))
        self.assertEqual(choose({(1, 0): "X"}, (-5.0, 358.0)), (0, 0))
        # 다음 수에 반드시 이기는 칸이 둘이면 가까운 쪽 (사용자 11-04 질문)
        b = {(0, 0): "X", (1, 0): "X", (0, 1): "O", (0, 2): "O", (1, 2): "X"}
        self.assertEqual(choose(b, (9.0, 357.5)), (2, 0))
        self.assertEqual(choose(b, (9.0, 375.5)), (2, 1))
        # O 둘(10점)이 걸리면 멀어도 그 칸
        self.assertEqual(choose({(1, 0): "X", (0, 0): "O"}, (9.0, 357.5)), (2, 2))

    def test_boss3_replay(self):
        """11-03 01:32 — 차례 간격 5~6초, 첫 X 왼쪽 가운데."""
        ttt = self.m.spear.ttt
        self.turn(self.C, (-9.0, 366.5))
        self.assertEqual(ttt.board, {(0, 1): "X"})
        self.draw(self.C, -9.5, 375.1)
        self.turn(ME, (9.0, 366.5))
        self.assertEqual(ttt.take()["cell"], (2, 0))
        self.draw(ME, 8.3, 357.5)
        self.turn(ME, (9.0, 375.5))
        self.assertEqual(ttt.take()["cell"], (1, 1))
        self.draw(ME, 0.0, 366.8)
        self.assertTrue(ttt.done)

    def test_o_only_in_window(self):
        """O 는 차례 시작 3.5~8초 사이의 보스 경로만 (11-03 party2: 늘 4.9~5.1초). 2초 때 움직임을 O 로 읽어 판이 틀어졌다."""
        ttt = self.m.spear.ttt
        self.turn(self.C, (0.0, 375.5))
        ttt.turn_at -= 2
        self.walk(self.BOSS, 9.0, 357.5)  # 너무 이르다
        self.assertNotIn((2, 0), ttt.board)
        self.draw(self.C, -9.2, 357.8)
        self.assertEqual(ttt.board.get((0, 0)), "O")

    def test_signals_after_done_ignored(self):
        """한 줄을 만든 뒤에도 보스가 같은 연출·대상 표시를 한 번 더 쓴다 — 차례·투창으로 보지 않는다 (11-03 17:19:38)."""
        ttt = self.m.spear.ttt
        ttt.done = True
        self.feed("spear.timeline", actor=ME, name=FORECAST)
        self.assertFalse(ttt.due())
        SpearStateTest.summon(self)
        for n in SH:
            self.m.apply("actor.dead", {"actor": SH[n], "dead": True})
        self.feed("spear.buff", actor=ME, buff=TARGET_MARK, caster=SPEAR)
        self.assertEqual(self.m.spear.target_at, 0.0)

    def test_choose_plan(self):
        for x1 in [(1, 0), (0, 1), (2, 1), (1, 2)]:  # 첫 X 상하좌우 어디든
            b = {x1: "X"}
            o1 = choose(b)
            self.assertIn(o1, [(0, 0), (2, 0), (0, 2), (2, 2)])  # X 옆 귀퉁이여도 (가까운 쪽, 사용자 11-04)
            b[o1] = "O"
            b[(1, 0) if (1, 0) not in b else (1, 2)] = "X"
            o2 = choose(b)
            self.assertEqual(o2, (2 - o1[0], 2 - o1[1]))
            b[o2] = "O"
            self.assertEqual(choose(b), (1, 1))


    def test_choose_messy_party(self):
        """함께하기 — 다른 사람이 가운데·상하좌우에 먼저 둬도 그 판에서 가장 나은 칸 (사용자 11-03)."""
        def pick(t):
            return choose({(c, r): ch for r, row in enumerate(t.split("/")) for c, ch in enumerate(row) if ch != "."})
        self.assertIn(pick(".X./.O./..."), [(0, 2), (2, 2)])  # 가운데 O 를 낀 대각선
        self.assertEqual(pick(".X./O../..."), (2, 1))          # 가운데만 남는 가로줄 → 다음에 반드시
        self.assertEqual(pick(".X./.O./X.O"), (0, 0))          # 바로 이김
        self.assertEqual(pick("X.O/.X./O.."), (2, 2))          # 두 줄 동시


class KeysTest(unittest.TestCase):
    def test_keys_toward(self):
        """11-02 실측 보정 (W = +Y, D = +X)."""
        sd = SpearDodge(None)
        sd.calib = ((0.0, 1.0), (1.0, 0.0))
        self.assertEqual(sd.keys_toward(0, -5), ["s"])
        self.assertEqual(sorted(sd.keys_toward(7, -10)), ["d", "s"])
        self.assertEqual(sd.keys_toward(-3, 0.2), ["a"])

    def test_fight_key_after_return(self):
        """투창병 쪽으로 돌아온 뒤 1 을 3번 — 바로 전투로 (사용자 11-03)."""
        from unittest import mock
        bot = mock.MagicMock()
        sd = SpearDodge(bot)
        sd.go = sd.hold = mock.MagicMock()
        st = mock.MagicMock()
        st.broken_since.return_value = True
        with (mock.patch.object(SpearDodge, "st", st), mock.patch.object(SpearDodge, "ok", return_value=True),
              mock.patch("mabi.tasks.spear.time.sleep")):
            sd.dodge({"x": 10, "y": 142, "at": time.monotonic(), "shaman": 1, "attr": "불"})
        self.assertEqual([c.args for c in bot.key.call_args_list], [("1",)] * 3)

    def test_camera_when_fang_dies(self):
        """비틀린 송곳니가 쓰러지면 (보스방으로 걸어감) 카메라를 한 번 더 맞춘다 — 혼자하기도 (사용자 11-03).
        모닥불만으로는 안 맞춘다 (아직 싸우는 중일 수 있다). 사라짐은 멀어져도 와서 쓰러짐만 본다."""
        from unittest import mock
        m = PacketMonitor(None)
        m.state.me = ME
        m.apply("channel.entering", {"channel": 1, "channel_type": "InstanceAbyssDungeon",
                                     "channel_name": "흩어진 물길 (어비스 시즌2 3구역 매우 어려움2 솔로)"})
        bot = mock.MagicMock(packets=m)
        sd = SpearDodge(bot)
        m._spear("spear.monster", {"actor": 77, "x": 0.0, "y": 0.0, "kind": FANG_KIND})
        m._spear("spear.monster", {"actor": 78, "x": 0.0, "y": 0.0, "kind": 6})
        m.apply("abyss.campfire", {})
        self.assertFalse(sd.camera_due())
        m._spear("spear.gone", {"actor": 77})
        m.apply("actor.dead", {"actor": 78, "dead": True})
        self.assertFalse(sd.camera_due())
        m.apply("actor.dead", {"actor": 77, "dead": True})
        self.assertTrue(sd.camera_due())
        bot.cfg = {"game": {"camera_key": "c"}}  # 옵션에서 바꾼 카메라 키
        with mock.patch("mabi.tasks.spear.time.sleep") as sleep:
            sd.set_camera()
        self.assertEqual([c.args for c in bot.key.call_args_list], [("c",), ("c",)])
        self.assertAlmostEqual(sum(c.args[0] for c in sleep.call_args_list), 6.0)  # 보스방 갈 땐 6초 (사용자 11-04)
        m.apply("cutscene.play", {})
        m.apply("cutscene.end", {})
        self.assertFalse(sd.camera_due())  # 한 맵에 한 번

    def test_camera_second_press_after_scene(self):
        """맞추는 중에 보스 등장 연출이 시작되면 두 번째 Z 는 연출이 끝난 뒤 (11-04 14:34 자동 카메라로 남음)."""
        from unittest import mock
        m = PacketMonitor(None)
        m.state.me = ME
        m.apply("channel.entering", {"channel": 1, "channel_type": "InstanceAbyssDungeon",
                                     "channel_name": "흩어진 물길 (어비스 시즌2 3구역 매우 어려움2 솔로)"})
        m.apply("abyss.campfire", {})
        m.apply("cutscene.play", {})
        m.apply("cutscene.end", {})
        bot = mock.MagicMock(packets=m)
        sd = SpearDodge(bot)
        n = []

        def sleep(sec):
            n.append(sec)
            if len(n) == 20:  # 2초 뒤 보스방에 들어가 연출 시작
                m.apply("cutscene.play", {})
        with mock.patch("mabi.tasks.spear.time.sleep", sleep):
            sd.set_camera()
        self.assertEqual(bot.key.call_count, 1)
        self.assertFalse(sd.camera_due())  # 연출 중엔 안 누른다
        m.apply("cutscene.end", {})
        self.assertTrue(sd.camera_due())
        sd.set_camera()
        self.assertEqual(bot.key.call_count, 2)
        self.assertFalse(sd.camera_due())

    def test_party_entry_camera_after_moving(self):
        """함께하기 들어올 때 카메라는 내 캐릭터가 움직이기 시작한 뒤 — 맵 진입 패킷 2초 뒤로는 아직 로딩 화면일 때가 있었다
        (사용자 11-19). 움직임을 못 봐도 CAMERA_LATE 뒤엔 맞춘다."""
        from unittest import mock
        from mabi.tasks import spear as sp
        m = PacketMonitor(None)
        m.state.me = ME
        m.apply("channel.entering", {"channel": 1, "channel_type": "InstanceAbyssDungeon",
                                     "channel_name": "흩어진 물길 (어비스 시즌2 3구역 매우 어려움2)"})
        bot = mock.MagicMock(packets=m)
        sd = SpearDodge(bot)
        m.state.entered_at -= 3  # 들어오고 3초
        self.assertFalse(sd.camera_due())  # 아직 안 움직임
        m._spear("spear.move_location", {"actor": ME, "x": 0.0, "y": 100.0})  # 처음 받은 자리
        self.assertFalse(sd.camera_due())
        m._spear("spear.move_update", {"actor": ME, "x": 0.5, "y": 100.2})   # 제자리 흔들림
        self.assertFalse(sd.camera_due())
        m._spear("spear.move_update", {"actor": ME, "x": 0.0, "y": 103.0})   # 걷기 시작
        self.assertTrue(sd.camera_due())
        with mock.patch("mabi.tasks.spear.time.sleep"):
            sd.set_camera()
        self.assertFalse(sd.camera_due())
        m.apply("channel.leaving", {})
        m.apply("channel.entering", {"channel": 1, "channel_type": "InstanceAbyssDungeon",
                                     "channel_name": "흩어진 물길 (어비스 시즌2 3구역 매우 어려움2)"})
        m.state.entered_at -= 3
        self.assertFalse(sd.camera_due())  # 새 맵 — 움직임을 다시 본다
        m.state.entered_at -= sp.CAMERA_LATE
        self.assertTrue(sd.camera_due())   # 못 봐도 늦게는 맞춘다

    def test_camera_once_per_map_across_calls(self):
        """판 진행을 다시 불러 SpearDodge 가 새로 생겨도 같은 맵에서 카메라를 또 돌리지 않는다 (11-03 19:26)."""
        from unittest import mock
        m = PacketMonitor(None)
        m.state.me = ME
        m.apply("channel.entering", {"channel": 1, "channel_type": "InstanceAbyssDungeon",
                                     "channel_name": "흩어진 물길 (어비스 시즌2 3구역 매우 어려움2 솔로)"})
        m.apply("abyss.campfire", {})
        m.apply("cutscene.play", {})
        m.apply("cutscene.end", {})
        bot = mock.MagicMock(packets=m)
        sd = SpearDodge(bot)
        self.assertTrue(sd.camera_due())
        with mock.patch("mabi.tasks.spear.time.sleep"):
            sd.set_camera()
        self.assertFalse(SpearDodge(bot).camera_due())

    def scene_bot(self):
        from unittest import mock
        m = PacketMonitor(None)
        m.state.me = ME
        m.apply("channel.entering", {"channel": 1, "channel_type": "InstanceAbyssDungeon",
                                     "channel_name": "흩어진 물길 (어비스 시즌2 3구역 매우 어려움2)"})
        m.apply("abyss.campfire", {})
        m.apply("cutscene.play", {})
        bot = mock.MagicMock(packets=m)
        return m, bot

    def test_scene_clicked_again_when_it_goes_on(self):
        """눌러도 연출이 이어지고 버튼이 남아 있으면 다시 누른다 (사용자 11-19 — 넘어갈 때도 있고 아닐 때도)."""
        from unittest import mock
        m, bot = self.scene_bot()
        bot.skip_button.return_value = ("scene", "hit")
        bot.wait_packet.side_effect = [False, True]  # 첫 번째는 안 먹음
        sd = SpearDodge(bot)
        with mock.patch("mabi.tasks.spear.time.sleep"):
            sd.skip_scene()
        self.assertEqual(bot.click.call_count, 2)
        self.assertIn("2번 누름", bot.log.info.call_args.args[0])
        self.assertIn(" → ", bot.log.info.call_args.args[0])  # 누른 것마다 어떻게·몇 초

    def test_scene_spot_when_hud_gone(self):
        """버튼 그림이 안 맞아도 HUD 가 사라진 지 SCENE_SPOT_AFTER 초가 지났으면 버튼 자리를 누른다.
        HUD 가 보이는 동안(미니맵)이나 막 사라진 때(연출이 어둡게 시작해 버튼이 아직 없음 — 11-19 15:23)는 안 누른다."""
        from unittest import mock
        from mabi.tasks import spear
        m, bot = self.scene_bot()
        bot.skip_button.return_value = None
        bot.wait_packet.return_value = True
        t = [0.0]
        hud = iter([True, True] + [False] * 40)
        seen = {}

        def clock():
            t[0] += 0.25
            return t[0]

        def at_main(frame):
            v = next(hud)
            if not v:
                seen.setdefault("gone", t[0])
            return v

        bot.at_main.side_effect = at_main
        bot.click.side_effect = lambda xy: seen.setdefault("click", t[0])
        with mock.patch("mabi.tasks.spear.time.sleep"), mock.patch("mabi.tasks.spear.time.monotonic", side_effect=clock):
            SpearDodge(bot).skip_scene()
        bot.click.assert_called_once_with(spear.SCENE_SKIP_XY)
        self.assertGreaterEqual(seen["click"] - seen["gone"], spear.SCENE_SPOT_AFTER)

    def test_scene_without_button_tries_next_scene(self):
        """넘기기 버튼이 없는 연출이 먼저 오면 그 연출만 넘어가고 다음 연출에서 또 찾는다."""
        from unittest import mock
        m, bot = self.scene_bot()
        bot.skip_button.return_value = None
        sd = SpearDodge(bot)
        clock = iter(range(0, 1000, 3))
        with mock.patch("mabi.tasks.spear.time.sleep"), \
                mock.patch("mabi.tasks.spear.time.monotonic", side_effect=lambda: next(clock)):
            sd.skip_scene()
        bot.click.assert_not_called()
        self.assertFalse(sd.scene_due())  # 같은 연출은 다시 안 본다
        m.apply("cutscene.end", {})
        m.apply("cutscene.play", {})
        m.state.changed_at["cutscene"] += 1  # 다음 연출 (시계가 거칠어 같은 값이 나올 수 있다)
        self.assertTrue(sd.scene_due())   # 다음 연출은 본다

    def test_camera_after_boss_scene_without_fang(self):
        """송곳니를 못 봤으면 (판 도중에 켬 등) 보스 등장 연출을 넘긴 뒤 맞춘다."""
        from unittest import mock
        m = PacketMonitor(None)
        m.state.me = ME
        m.apply("channel.entering", {"channel": 1, "channel_type": "InstanceAbyssDungeon",
                                     "channel_name": "흩어진 물길 (어비스 시즌2 3구역 매우 어려움2 솔로)"})
        bot = mock.MagicMock(packets=m)
        bot.skip_button.return_value = ("scene", "hit")
        sd = SpearDodge(bot)
        self.assertFalse(sd.camera_due())  # 혼자하기는 들어올 때 맞추지 않는다
        m.apply("abyss.campfire", {})
        self.assertFalse(sd.camera_due() or sd.scene_due())  # 모닥불만 — 아직 싸우는 중
        m.apply("cutscene.play", {})
        self.assertFalse(sd.camera_due())  # 연출 중엔 맞추지 않고
        self.assertTrue(sd.scene_due())    # 넘긴다
        sd.skip_scene()
        bot.click.assert_called_once_with("hit")
        self.assertFalse(sd.scene_due())   # 한 맵에 한 번
        m.apply("cutscene.end", {})
        m.apply("cutscene.play", {})
        self.assertFalse(sd.scene_due())   # 넘긴 뒤 다음 연출은 그대로 둔다
        m.apply("cutscene.end", {})
        self.assertTrue(sd.camera_due())
        with mock.patch("mabi.tasks.spear.time.sleep"):
            sd.set_camera()
        self.assertEqual([c.args for c in bot.key.call_args_list], [("end",), ("end",)])
        self.assertFalse(sd.camera_due())  # 한 맵에 한 번

    def test_wanted_only_when_active(self):
        m = PacketMonitor(None)
        sd = SpearDodge(SimpleNamespace(packets=m))
        sd.calib = ((0, 1), (1, 0))
        self.assertFalse(sd.wanted())  # 다른 맵
        m.state.me = ME
        m.apply("channel.entering", {"channel": 1, "channel_type": "InstanceAbyssDungeon", "channel_name": "흩어진 물길"})
        m._spear("spear.buff", {"actor": ME, "buff": TARGET_MARK, "caster": SPEAR})
        self.assertTrue(sd.wanted())



class RiftTest(unittest.TestCase):
    """비틀린 송곳니 격류 → 격류가 가는 쪽 면의 균열로 (2026-11-19 caps/fang1119 · 사용자 설명).
    북 (0, 237.5) 방향 π 에서 나온 격류는 남쪽으로 40칸을 20초에 — 남쪽 균열 (±10, 200) 을 밟아 북쪽으로 넘어간다."""
    NORTH = {"x": 0.0, "y": 237.5, "dir": math.pi}

    def setUp(self):
        self.t = [1000.0]
        p = mock.patch.object(time, "monotonic", lambda: self.t[0])
        p.start()
        self.addCleanup(p.stop)
        self.m = PacketMonitor(None)
        self.m.status = "running"
        self.m.state.me = ME
        self.m.apply("channel.entering", {"channel": 1, "channel_type": "InstanceAbyssDungeon",
                                          "channel_name": "흩어진 물길 (어비스 시즌2 3구역 매우 어려움2 솔로)"})
        self.m._spear("spear.monster", {"actor": 77, "x": 0.0, "y": 0.0, "kind": FANG_KIND})
        for i, (x, y) in enumerate(RIFTS):
            self.m._spear("spear.move_ensure", {"actor": 900 + i, "x": x, "y": y})

    @property
    def st(self):
        return self.m.spear

    def wave(self, w=None):
        self.m._spear("spear.object", {"actor": 555, "kind": WAVE_KIND, **(w or self.NORTH)})

    def test_state(self):
        self.m._spear("spear.object", {"actor": 554, "kind": 1234, **self.NORTH})  # 다른 기술 물체
        self.assertFalse(self.st.wave_due())
        self.assertEqual(self.st.feed("spear.object", {"actor": 555, "kind": WAVE_KIND, **self.NORTH}, ME),
                         "격류 나옴 (0, 238)")
        self.assertTrue(self.st.wave_due())
        self.assertEqual(len(self.st.rifts()), 8)
        self.st.take_wave()
        self.assertFalse(self.st.wave_due())  # 한 번만 맡는다
        self.t[0] += 1
        self.wave()
        self.assertTrue(self.st.wave_due())
        self.m.apply("actor.dead", {"actor": 77, "dead": True})
        self.assertFalse(self.st.wave_due())  # 송곳니가 쓰러지면 안 맡는다

    def test_warp_signals(self):
        """균열을 지나면 재사용 대기 버프와 자리 튐이 둘 다 온다 — 한 번만 알린다."""
        self.wave()
        self.m._spear("spear.move_update", {"actor": ME, "x": -10.0, "y": 200.5})
        self.t[0] += 0.3
        self.assertEqual(self.st.feed("spear.buff", {"actor": ME, "buff": RIFT_PASS, "caster": 904}, ME),
                         "균열로 넘어감 (버프)")
        self.assertIsNone(self.st.feed("spear.move_update", {"actor": ME, "x": -10.0, "y": 235.0}, ME))
        self.assertIsNone(self.st.feed("spear.buff", {"actor": OTHER, "buff": RIFT_PASS, "caster": 904}, ME))
        self.t[0] += 5
        self.assertEqual(self.st.feed("spear.move_update", {"actor": ME, "x": -10.0, "y": 201.0}, ME),
                         "균열로 넘어감 ((-10, 235) → (-10, 201))")  # 버프를 못 받아도 자리 튐으로

    def test_exit_edge(self):
        """격류가 가는 쪽 면의 균열만 — 경로 패킷이 없으면 나온 자리·방향으로 어림한다."""
        cases = [(self.NORTH, {(-10.0, 200.0), (10.0, 200.0)}),
                 ({"x": -19.9, "y": 217.5, "dir": math.pi / 2}, {(18.0, 208.0), (18.0, 228.0)}),
                 ({"x": 0.0, "y": 197.5, "dir": 0.0}, {(-10.0, 235.0), (10.0, 235.0)}),
                 ({"x": 19.9, "y": 217.5, "dir": 3 * math.pi / 2}, {(-18.0, 208.0), (-18.0, 228.0)})]
        for w, want in cases:
            start, u, length, front = wave_line({**w, "at": 0.0, "path": None}, 12.0)
            self.assertEqual(set(exits(start, u, length)), want)
            self.assertAlmostEqual(front, 20.0)  # 2초 뒤 출발 · 10초에 반
        path = {**self.NORTH, "at": 0.0, "path": (0.0, 237.5, 0.0, 197.5, 20.0, 3.0)}
        self.assertAlmostEqual(wave_line(path, 13.0)[3], 20.0)  # 경로를 받은 때부터

    def dodge(self, me, on_sleep=None, stuck=False):
        """격류가 나온 때 run 을 부른다. 2초 뒤 경로 패킷. 가짜 이동: 5.5칸/초로 가고, 균열 1칸 안에 서면 넘어간다.
        stuck: 균열 말고는 못 움직임 (밀리거나 묶임). 돌려줌: ([(목표, 출발 초)], 넘어간 초 또는 None, bot)."""
        pos, moves = [me], []
        bot = mock.MagicMock(packets=self.m)
        sd = SpearDodge(bot)
        sd.calib = ((0.0, 1.0), (1.0, 0.0))
        sd.my_pos = sd.pos_loose = lambda *a, **k: pos[0]
        sd._with_focus = lambda fn: fn()
        start = self.t[0]

        def sleep(sec):
            self.t[0] += sec
            w = self.st.wave
            if w and w["path"] is None and self.t[0] - start >= 2.0:
                self.m._spear("spear.object_path", {"actor": 555, "x1": 0.0, "y1": 237.5, "x2": 0.0, "y2": 197.5,
                                                    "secs": 20.0})
            if on_sleep:
                on_sleep(self.t[0] - start)

        def go(target, tol, until, done, pattern=True):
            moves.append((target, round(self.t[0] - start, 1)))
            rift = any(math.dist(target, r) < 1.0 for r in RIFTS)
            if stuck and not rift:
                return False
            sleep(math.dist(pos[0], target) / 5.5)
            pos[0] = target
            if rift:
                self.m._spear("spear.buff", {"actor": ME, "buff": RIFT_PASS, "caster": 904})
            return True

        def hold(target, until, done, pattern=True):
            while not done() and self.t[0] < until:
                sleep(0.1)

        sd.go, sd.hold = go, hold
        with (mock.patch.object(SpearDodge, "ok", return_value=True), mock.patch.object(time, "sleep", sleep),
              mock.patch.object(SpearDodge, "camera_due", return_value=False),
              mock.patch.object(SpearDodge, "scene_due", return_value=False)):
            self.wave()
            self.assertTrue(sd.wanted())
            sd.run()
        warped = round(self.st.warped_at - start, 1) if self.st.warped_at else None
        return moves, warped, bot

    def logged(self, bot, text):
        return any(text in str(c.args[0]) for c in bot.log.info.call_args_list + bot.log.warning.call_args_list)

    def test_center_waits_for_half(self):
        """가운데에 있으면 격류가 6칸 안으로 올 때 출발해 남쪽 균열 앞에서 기다렸다가 가운데를 넘은 뒤 밟는다."""
        moves, warped, bot = self.dodge((0.0, 217.5))
        self.assertEqual(moves[0][0], (-10.0, 205.0))       # 균열 5칸 앞
        self.assertAlmostEqual(moves[0][1], 9.0, delta=0.2)  # 앞머리 14칸 = 나와 6칸
        self.assertEqual(moves[1][0], (-10.0, 200.0))
        self.assertGreaterEqual(moves[1][1], 12.0)           # 경로 받고 10초 = 가운데
        self.assertLess(warped, 14.0)
        self.assertTrue(self.logged(bot, "격류: 균열로 넘어감"))

    def test_near_start_edge_leaves_early(self):
        """격류가 나온 면 가까이 있으면 바로 출발하지만, 밟는 건 가운데를 넘은 뒤 (일찍 타면 건너편이 아직 격류)."""
        moves, warped, _ = self.dodge((8.0, 233.0))
        self.assertEqual(moves[0], ((10.0, 205.0), 0.0))
        self.assertGreaterEqual(moves[1][1], 12.0)
        self.assertIsNotNone(warped)

    def test_inside_wave_still_waits(self):
        """격류에 붙어 있어도 가운데 전이면 바로 타지 않고 앞질러 균열 앞에서 기다린다."""
        moves, warped, _ = self.dodge((0.0, 236.5))
        self.assertEqual(moves[0], ((-10.0, 205.0), 0.0))
        self.assertGreaterEqual(moves[1][1], 12.0)

    def test_caught_steps_early(self):
        """균열 앞까지 못 가고 격류가 2.5칸 안으로 붙으면 가운데 전이라도 밟는다 (밀리며 맞느니)."""
        moves, warped, _ = self.dodge((-10.0, 216.0), stuck=True)
        self.assertEqual([m[0] for m in moves], [(-10.0, 205.0), (-10.0, 200.0)])
        self.assertLess(moves[1][1], 12.0)
        self.assertIsNotNone(warped)

    def test_fang_down_stops(self):
        """기다리는 동안 송곳니가 쓰러지면 그만둔다 (사용자 11-19)."""
        def kill(dt):
            if dt >= 5:
                self.m.apply("actor.dead", {"actor": 77, "dead": True})
        moves, warped, bot = self.dodge((0.0, 217.5), kill)
        self.assertEqual(moves, [])
        self.assertIsNone(warped)
        self.assertTrue(self.logged(bot, "송곳니가 쓰러짐"))

    def test_no_rifts_seen(self):
        self.t[0] += 10  # 균열 자리가 오래돼 안 보임
        moves, _, bot = self.dodge((0.0, 217.5))
        self.assertEqual(moves, [])
        self.assertTrue(self.logged(bot, "균열이 안 보임"))


if __name__ == "__main__":
    unittest.main()
