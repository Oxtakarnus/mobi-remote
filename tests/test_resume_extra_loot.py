"""요일 던전 도중 멈췄다 이어 하면 접속 단계의 시작 정리가 추가 루팅까지 한다.
접속 단계가 진행 기록을 'login' 으로 덮어 끊긴 숙제를 못 알아보고 추가 루팅을 빼던 것 (2026-11-21 점검)."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from mabi.profile import DailyState


def daily_of(progress):
    """진행 기록이 progress 인 DailyState 흉내 — 끊긴 숙제 고르기(interrupted)는 진짜 규칙."""
    d = mock.MagicMock()
    d.progress.return_value = progress
    d.interrupted.side_effect = lambda: DailyState.interrupted(d)
    return d


def unwatched(b):
    """관찰 기록으로는 모름 (감시 꺼짐과 같다) — 끊긴 숙제를 예전처럼 믿는다."""
    b.packets.seen_since.return_value = None
    b.packets.state.char_id = None
    return b


class ProgressBeforeLoginTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = DailyState(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_login_keeps_the_cut_task(self):
        self.st.set_progress(2, "weekday_dungeon")
        self.st.set_progress(2, "login")
        p = self.st.progress()
        self.assertEqual(p["task"], "login")
        self.assertEqual(p["before"]["task"], "weekday_dungeon")
        self.st.set_progress(2, "login")  # 접속이 다시 끊겨 또 접속해도 남는다
        self.assertEqual(self.st.progress()["before"]["task"], "weekday_dungeon")
        self.st.set_progress(2, "arbeit")
        self.assertNotIn("before", self.st.progress())


class LeaveDungeonLootTest(unittest.TestCase):
    def leave(self, progress):
        from mabi.tasks import login
        b = mock.MagicMock()
        b.cfg = {"black_hole": {"space_keyword": "검은 구멍"}, "weekday_dungeon": {"extra_loot": 3}}
        b.character = {"slot": 2}
        b.daily = daily_of(progress)
        unwatched(b)
        here = SimpleNamespace(kind=None, in_field=False)
        with (mock.patch("mabi.place.place", return_value=here),
              mock.patch("mabi.tasks.space.game_space", return_value="던전"),
              mock.patch("mabi.tasks.space.dungeon_state", return_value="Cleared"),
              mock.patch("mabi.tasks.clear.after_clear") as ac):
            login._leave_dungeon(b)
        return ac.call_args.args[1]

    def test_reward_screen_after_pause_loots(self):
        cut = {"slot": 2, "task": "login", "before": {"slot": 2, "task": "weekday_dungeon"}}
        self.assertEqual(self.leave(cut), 3)

    def test_other_task_does_not_loot(self):
        self.assertEqual(self.leave({"slot": 2, "task": "login", "before": {"slot": 2, "task": "tribute"}}), 0)
        self.assertEqual(self.leave({"slot": 2, "task": "login"}), 0)


class LeaveFieldTest(unittest.TestCase):
    """사냥터 안에서 멈췄다 이어 하면 클리어까지 기다린다 — 창이 HUD 를 가려 사냥 퀘스트가 안 보여도 (2026-11-21)."""

    def leave(self, hunt, at_main, task="silver"):
        from mabi.tasks import login
        b = mock.MagicMock()
        b.cfg = {"black_hole": {"space_keyword": "검은 구멍"}, "weekday_dungeon": {"extra_loot": 0},
                 "silver": {"field_timeout": 2400}}
        b.character = {"slot": 2}
        b.daily = daily_of({"slot": 2, "task": "login", "before": {"slot": 2, "task": task}})
        unwatched(b)
        b.at_main.return_value = at_main
        b.exists.return_value = False  # 클리어·보상 화면 아님
        here = SimpleNamespace(kind=None, in_field=True)
        with (mock.patch("mabi.place.place", return_value=here),
              mock.patch("mabi.tasks.space.game_space", return_value="창백한 산"),
              mock.patch("mabi.tasks.space.hunt_quest", return_value=hunt),
              mock.patch("mabi.tasks.space.dungeon_state", return_value="NotInDungeon"),
              mock.patch("mabi.tasks.dungeon.touch_prompt_visible", return_value=False),
              mock.patch("mabi.tasks.dungeon.wait_field") as wf):
            login._leave_dungeon(b)
        return wf.called

    def test_hunt_seen_waits(self):
        self.assertTrue(self.leave("창백한 산 사냥 IV", at_main=True, task="tribute"))

    def test_hud_covered_waits_when_silver_was_cut(self):
        self.assertTrue(self.leave("", at_main=False))

    def test_hud_covered_other_task_does_not_wait(self):
        self.assertFalse(self.leave("", at_main=False, task="arbeit"))

    def test_main_screen_without_hunt_does_not_wait(self):
        # 채집·사냥터 안 던전을 마치고 나와 있는 사냥터 — 판이 아니라 클리어가 오지 않는다
        self.assertFalse(self.leave("", at_main=True))


if __name__ == "__main__":
    unittest.main()
