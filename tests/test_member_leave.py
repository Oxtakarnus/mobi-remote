"""어비스 함께하기 '파티원 퇴장 시 나감' (사용자 11-22) — 같은 판 사람(패킷 상태 others)·판 지켜보기·반복·카드.
우연한 만남은 파티가 아니라 파티 신호가 없다. 이 어비스 맵에 나타난 다른 캐릭터가 결과 전에 사라지면 나간 것으로 본다
(11-03 흩어진 물길 26판: 판 도중 사라진 캐릭터는 다시 나타나지 않았고, 클리어 판의 사라짐은 모두 결과 뒤)."""
import threading
import time
import unittest
from types import SimpleNamespace as NS
from unittest import mock

from mabi.packet_monitor import PacketMonitor
from mabi.place import ABYSS
from mabi.spear import MAP_NAME

A, B, ME, MOB = 0x3944CC4, 0x3944CAA, 0x3944CB0, 0x5000001


def enter(m, kind=ABYSS, name="어비스"):
    m.apply("channel.entering", {"channel": 1, "channel_type": kind, "channel_name": name})


def met(m):
    """어비스 맵에 들어가 나와 다른 두 사람이 나타남."""
    enter(m)
    m.apply("char.appearing", {"actor": ME, "mine": True})
    m.apply("char.appearing", {"actor": A, "mine": False})
    m.apply("char.appearing", {"actor": B, "mine": False})
    return m


class OthersStateTest(unittest.TestCase):
    def setUp(self):
        self.m = met(PacketMonitor(None))

    def test_others_are_not_me(self):
        self.assertEqual(set(self.m.state.others), {A, B})

    def test_gone_before_result_is_left(self):
        t = time.monotonic()
        self.m.apply("spear.gone", {"actor": A})
        self.assertGreaterEqual(self.m.state.other_out_at, t)
        self.assertEqual(set(self.m.state.others), {B})

    def test_unknown_object_gone_ignored(self):
        self.m.apply("spear.gone", {"actor": MOB})
        self.assertEqual(self.m.state.other_out_at, 0.0)

    def test_gone_after_result_ignored(self):
        # 클리어 뒤 보상 받고 나가는 것은 판 도중 나감이 아니다
        self.m.apply("abyss.result", {"abyss": 7})
        self.m.apply("spear.gone", {"actor": A})
        self.assertEqual(self.m.state.other_out_at, 0.0)

    def test_new_map_and_forget_clear(self):
        enter(self.m)
        self.assertEqual(self.m.state.others, {})
        met(self.m)
        self.m.forget("시험")
        self.assertEqual(self.m.state.others, {})

    def test_not_tracked_outside_abyss(self):
        m = PacketMonitor(None)
        enter(m, "InstanceDungeon", "던전")
        m.apply("char.appearing", {"actor": A, "mine": False})
        self.assertEqual(m.state.others, {})


class RouteTest(unittest.TestCase):
    """감시는 사라짐을 같은 판 사람이 있을 때만 풀고, 그 사람 것만 상태로 넘긴다 (몬스터 사라짐은 수없이 온다)."""

    def monitor(self, name="어비스"):
        m = PacketMonitor(None)
        m.table = NS(event=lambda p: NS(key="spear.gone", fields=["actor"]),
                     decode=lambda p, b: (None, {"actor": int.from_bytes(b[:8], "little")}))
        enter(m, name=name)
        return m

    def gone(self, m, actor):
        m._handle(1, 0, actor.to_bytes(8, "little"))

    def test_only_others_reach_state(self):
        for name in ("어비스", MAP_NAME):  # 투창 패턴 맵(흩어진 물길)에서도 투창 쪽과 함께
            m = self.monitor(name)
            m.apply("char.appearing", {"actor": A, "mine": False})
            n = len(m.recent)
            self.gone(m, MOB)
            self.assertEqual((m.state.other_out_at, len(m.recent)), (0.0, n), name)
            self.gone(m, A)
            self.assertGreater(m.state.other_out_at, 0.0, name)

    def test_not_decoded_without_others(self):
        m = self.monitor()
        m.table.decode = mock.Mock(side_effect=AssertionError("풀면 안 됨"))
        self.gone(m, A)


class PlayTest(unittest.TestCase):
    def play(self, member_leave, out_at, cleared=False):
        from mabi.tasks import abyss
        bot = mock.MagicMock()
        bot.packets.state = NS(entered_at=100.0, other_out_at=out_at)
        bot.packets.find.return_value = {"abyss": 7} if cleared else None
        with mock.patch.object(abyss, "SpearDodge") as sd:
            sd.return_value.wanted.return_value = False
            return abyss.AbyssPlay(bot, 600, True, None, None, member_leave=member_leave)

    def test_left_only_when_on(self):
        self.assertEqual(self.play(True, 105.0).packet_end(), "left")
        self.assertIsNone(self.play(False, 105.0).packet_end())

    def test_wake(self):
        p = self.play(True, 105.0)
        self.assertTrue(p.wake(p.bot.packets.state))

    def test_earlier_map_ignored(self):
        self.assertIsNone(self.play(True, 99.0).packet_end())

    def test_clear_wins(self):
        self.assertEqual(self.play(True, 105.0, cleared=True).packet_end(), "clear")


class RepeatTest(unittest.TestCase):
    def rep(self, results, **a):
        from mabi.tasks import abyss
        r = abyss.AbyssRepeat.__new__(abyss.AbyssRepeat)
        r.bot = mock.MagicMock()
        r.a = {"dungeon": "흩어진 물길", "match_timeout": 60, "run_timeout": 600, "mode": "party", "member_leave": True, **a}
        r.runs, r.minutes, r.t0, r.on_event, r.behind, r.finish = 1, 0, time.monotonic(), lambda e: None, False, False
        r.stat = {"clears": 0, "deaths": 0, "retries": 0, "revives": 0, "lefts": 0}
        it = iter(results)
        r.plays = []
        r.play_round = lambda play, step: r.plays.append(play) or next(it)
        r.recheck = lambda at: False
        r.yield_between = r.repair_between = lambda go_out: False
        r._again = mock.MagicMock()
        return r

    def test_left_leaves_then_enters_again(self):
        from mabi.tasks import abyss
        r = self.rep(["left", "clear"])
        with (mock.patch.object(abyss, "to_reward", return_value="reward"),
              mock.patch.object(abyss, "exit_reward"),
              mock.patch.object(abyss, "leave", return_value=True) as lv,
              mock.patch.object(abyss, "enter") as en,
              mock.patch.object(abyss, "inside", return_value=True),
              mock.patch.object(abyss, "entered_since", return_value=True)):
            r.loop("play")
        self.assertEqual((lv.call_count, en.call_count), (1, 1))  # 나간 뒤 입장부터
        self.assertEqual((r.stat["lefts"], r.stat["clears"]), (1, 1))
        self.assertTrue(r.plays[0].keywords["member_leave"])

    def test_only_chance_meeting(self):
        self.assertTrue(self.rep([]).member_leave)
        self.assertFalse(self.rep([], mode="solo").member_leave)
        self.assertFalse(self.rep([], party_role="leader").member_leave)
        self.assertFalse(self.rep([], member_leave=False).member_leave)

    def test_finish_counts_left(self):
        r = self.rep([])
        r.finish = True
        self.assertFalse(r.done())
        r.stat["lefts"] = 1
        self.assertTrue(r.done())


class CardTest(unittest.TestCase):
    X = {"id": 1, "runs": 1, "slot": 2, "dungeon": "흩어진 물길", "difficulty": "매우 어려움2", "mode": "party"}

    def test_detail(self):
        from gui_app.queue_api import AbyssKind
        self.assertIn("파티원 퇴장 시 나감", AbyssKind.detail({**self.X, "memberLeave": True}))
        self.assertNotIn("파티원 퇴장", AbyssKind.detail(self.X))

    def test_run_passes_option(self):
        from gui_app.queue_api import AbyssKind
        got = []
        for card in ({**self.X, "memberLeave": True}, self.X):
            api = mock.MagicMock()
            api._q_fit.return_value = False
            api._busy_reason.return_value = None
            api._rep.return_value.result = {"type": "done"}

            def launch(kind, v, on_event):
                got.append(v["member_leave"])
                t = threading.Thread(target=lambda: None)
                t.start()
                return t
            api._repeat_launch.side_effect = launch
            AbyssKind(api).run(mock.MagicMock(session={}), card)
        self.assertEqual(got, [True, False])


if __name__ == "__main__":
    unittest.main()
