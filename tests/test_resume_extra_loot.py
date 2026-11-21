"""요일 던전 도중 멈췄다 이어 하면 접속 단계의 시작 정리가 추가 루팅까지 한다.
접속 단계가 진행 기록을 'login' 으로 덮어 끊긴 숙제를 못 알아보고 추가 루팅을 빼던 것 (2026-11-21 점검)."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from mabi.profile import DailyState


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
        b.daily.progress.return_value = progress
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


if __name__ == "__main__":
    unittest.main()
