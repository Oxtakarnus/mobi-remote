"""보상 화면 '다시 하기' 를 게임이 받지 않으면 (월요일 06:00 주간 초기화 뒤 전리품 정산 전 — 2026-11-23 06:02) 매칭 상한
10분을 기다리지 않고 나가서 입장 화면부터 (정산 판정이 거기 있다) — AbyssRepeat._again · loop."""
import time
import unittest
from types import SimpleNamespace as NS
from unittest import mock

from mabi.tasks import abyss


def rep(results=("clear",)):
    r = abyss.AbyssRepeat.__new__(abyss.AbyssRepeat)
    r.bot = mock.MagicMock()
    r.bot.packets = NS(ok=True, state=NS(entered_at=0.0))
    r.a = {"dungeon": "흩어진 물길", "difficulty": "매우 어려움2", "match_timeout": 600, "run_timeout": 600}
    r.runs, r.minutes, r.t0, r.on_event, r.behind, r.finish = len(results), 0, time.monotonic(), lambda e: None, False, False
    r.stat = {"clears": 0, "deaths": 0, "retries": 0, "revives": 0, "lefts": 0}
    it = iter(results)
    r.play_round = lambda play, step: next(it)
    r.recheck = lambda at: False
    r.yield_between = r.repair_between = lambda go_out: False
    return r


class AgainTest(unittest.TestCase):
    def again(self, took, button=True):
        r = rep()
        r.bot.wait_packet.return_value = took
        r.bot.exists.return_value = button
        r.bot.behind.return_value = False
        return r, r._again()

    def test_refused_after_all_presses(self):
        r, ok = self.again(False)
        self.assertFalse(ok)
        r.bot.key.assert_called_once_with("space")                          # 처음 Space
        self.assertEqual(r.bot.click.call_count, abyss.AGAIN_PRESSES - 1)   # 안 받으면 다시 누름
        self.assertEqual(r.bot.wait_packet.call_count, abyss.AGAIN_PRESSES)  # 누를 때마다 신호를 기다림

    def test_took(self):
        r, ok = self.again(NS(vals={}))
        self.assertTrue(ok)
        r.bot.click.assert_not_called()

    def test_packet_unknown_trusts_match_limit(self):
        r, ok = self.again(None)   # 패킷이 모르면 다시 누르지 않는다 — 매칭 중에 또 누르면 취소된다
        self.assertTrue(ok)
        r.bot.click.assert_not_called()

    def test_button_gone(self):
        r, ok = self.again(False, button=False)
        self.assertTrue(ok)


class LoopTest(unittest.TestCase):
    def test_refused_goes_to_entry(self):
        r = rep(results=("clear", "clear"))
        r._again = mock.MagicMock(return_value=False)
        with (mock.patch.object(abyss, "to_reward", return_value="reward"),
              mock.patch.object(abyss, "exit_reward") as ex,
              mock.patch.object(abyss, "enter") as en,
              mock.patch.object(abyss, "inside", return_value=True),
              mock.patch.object(abyss, "entered_since", return_value=True)):
            r.loop("main")
        self.assertEqual(en.call_count, 2)        # 다시 하기 대신 입장 화면부터 한 번 더
        self.assertEqual(ex.call_count, 2)        # 안 받은 뒤 나가기 + 마지막 판 뒤 나가기
        self.assertEqual(r.stat["clears"], 2)


if __name__ == "__main__":
    unittest.main()
