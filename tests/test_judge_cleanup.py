"""판정 점검(2026-11-16) 4묶음 — 확인 실패 하나로 일을 통째로 버리거나 다시 켜지 않는다.
접속 뒤 정리 시간 초과 · '게임 종료' 다시 누르기 · 오류 뒤 메인 화면 몇 번 보기 · 아르바이트 누른 일 제목 · 던전 입장 확인."""
import itertools
import logging
import unittest
from types import SimpleNamespace
from unittest import mock

from mabi import outcome
from mabi.bot import Bot
from mabi.exceptions import StepTimeout
from mabi.tasks import arbeit, dungeon, login, press


class Clock:
    """부를 때마다 1초씩 가는 시계 (기다림이 실제로 몇 초씩 돌지 않게)."""

    def __init__(self):
        self.t = itertools.count()

    def __call__(self):
        return float(next(self.t))


class LoginSettleTest(unittest.TestCase):
    def settle(self, in_game):
        b = mock.Mock()
        b.in_game.return_value = in_game
        b.snapshot.return_value.name = "login.png"
        b.log = logging.getLogger("test")
        mon = mock.Mock()
        mon.check.return_value = SimpleNamespace(done=None, what="unknown")
        with mock.patch("mabi.monitor.of", return_value=mon), \
                mock.patch.object(login.time, "monotonic", Clock()):
            return login.settle_first_login(b, {"login": {"first_dialog_xy": [40, 600]}}, timeout=5)

    def test_in_game_goes_on(self):
        """접속은 됐는데 메인 화면이 안정되지 않음 — 그 캐릭터 일을 버리지 않고 이어 간다."""
        with self.assertLogs("test", "WARNING") as cm:
            self.assertEqual(self.settle(True), [])
        self.assertIn("게임 안이라 이어 감", cm.output[0])

    def test_outside_fails(self):
        with self.assertRaises(StepTimeout):
            self.settle(False)


class CharselectTest(unittest.TestCase):
    def test_quit_pressed_again(self):
        """'게임 종료' 를 눌렀는데 창이 안 뜨면 다시 누른다. 확인(Space)은 창이 닫히는 것으로 본다."""
        ui = {"menu_quit": "menu_quit", "dialog_to_charselect": "dialog", "charselect_title": "cs", "title_start": "title"}
        st = {"clicks": 0, "space": False}
        b = mock.MagicMock()
        b.ui = ui
        b.vision.has.return_value = False
        b.click.side_effect = lambda n: st.__setitem__("clicks", st["clicks"] + 1)
        b.key.side_effect = lambda k: k == "space" and st.__setitem__("space", True)
        b.exists.side_effect = lambda n: (n == "dialog" and st["clicks"] >= 2 and not st["space"]) or n == "menu_quit"
        b.wait_any.return_value = SimpleNamespace(name="cs")
        with mock.patch.object(press.time, "monotonic", Clock()):
            Bot.to_charselect(b)
        self.assertEqual(st["clicks"], 2)
        self.assertTrue(st["space"])


class SettleTest(unittest.TestCase):
    def test_main_seen_on_second_look(self):
        """오류 뒤 정리에서 메인 화면을 한 번 못 봤다고 바로 게임을 다시 켜지 않는다."""
        b = mock.MagicMock()
        b.at_main.side_effect = [False, True]
        with mock.patch.object(outcome, "recover"), mock.patch.object(outcome.restart, "now") as now, \
                mock.patch.object(press.time, "monotonic", Clock()):
            outcome.settle(b, "x")
        now.assert_not_called()

    def test_restart_when_never_main(self):
        b = mock.MagicMock()
        b.at_main.return_value = False
        with mock.patch.object(outcome, "recover"), mock.patch.object(outcome.restart, "now") as now, \
                mock.patch.object(press.time, "monotonic", Clock()):
            outcome.settle(b, "x")
        now.assert_called_once()


class PressedTitleTest(unittest.TestCase):
    def test_pressed_one_not_first(self):
        """추적 칸이 아직 앞 일을 보여도 누른 일을 고른다."""
        self.assertEqual(arbeit._pressed_title(["양털 모으기", "빚은 술 배달"], "빛은 술 배달", ["양털 모으기"]),
                         "빚은 술 배달")

    def test_not_excluded_when_title_unknown(self):
        self.assertEqual(arbeit._pressed_title(["양털 모으기", "약초 캐기"], None, ["양털 모으기"]), "약초 캐기")
        self.assertIsNone(arbeit._pressed_title(["양털 모으기"], None, ["양털 모으기"]))  # 아직 안 바뀜


class DungeonEnterTest(unittest.TestCase):
    def play(self, kind):
        b = mock.MagicMock()
        with mock.patch.object(dungeon, "wait_dungeon", side_effect=["", "Cleared"]), \
                mock.patch("mabi.place.place", return_value=SimpleNamespace(kind=kind)), \
                mock.patch.object(dungeon, "cleared_now"), \
                mock.patch.object(dungeon, "_in_ctx"), \
                mock.patch.object(dungeon, "after_clear", return_value="clear", create=True):
            try:
                dungeon._play_dungeon(b, 600, 0, None)
            except StepTimeout as e:
                return e
        return b

    def test_inside_goes_on(self):
        """진행 신호를 못 봤어도 던전 맵 안이면 나가지 않고 이어 한다 (비용을 냈을 수 있다)."""
        from mabi.place import DUNGEON
        out = self.play(DUNGEON)
        self.assertNotIsInstance(out, StepTimeout)
        out.log.warning.assert_any_call("던전 진행 신호는 못 봤지만 던전 맵 안 → 이어 함")

    def test_outside_fails(self):
        from mabi.place import FIELD
        self.assertIsInstance(self.play(FIELD), StepTimeout)


class AbyssLeftoverTest(unittest.TestCase):
    def test_reward_at_start_not_counted(self):
        """보상 화면에서 시작하면 그 판은 이미 센 판 — 보상만 받고 한 판을 더 돈다 (11-19 보상 화면 멈춤 뒤 ▶ 로 두 번 셈)."""
        import time
        from mabi.tasks import abyss
        r = abyss.AbyssRepeat.__new__(abyss.AbyssRepeat)
        r.bot = mock.MagicMock()
        r.a = {"dungeon": "흩어진 물길", "match_timeout": 60, "run_timeout": 600}
        r.runs, r.minutes, r.t0, r.on_event, r.behind = 1, 0, time.monotonic(), lambda e: None, False
        r.stat = {"clears": 0, "deaths": 0, "retries": 0, "revives": 0}
        rounds = []
        r.play_round = lambda play, step: rounds.append(step) or "clear"
        r.recheck = lambda at: False
        r.yield_between = r.repair_between = lambda go_out: False
        r._again = lambda: None
        with mock.patch.object(abyss, "to_reward", return_value="reward"), mock.patch.object(abyss, "exit_reward"),                 mock.patch.object(abyss, "inside", return_value=True),                 mock.patch.object(abyss, "entered_since", return_value=True):
            r.loop("reward")
        self.assertEqual((r.stat["clears"], len(rounds)), (1, 1))


if __name__ == "__main__":
    unittest.main()
