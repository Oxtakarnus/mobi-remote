"""클리어 뒤 연출 (mabi.tasks.clear._clear_show) — 보상 메뉴가 늦게 떠도 빈 곳을 계속 누르지 않는다."""
import logging
import unittest
from types import SimpleNamespace
from unittest import mock

from mabi.monitor import detect as d
from mabi.tasks import clear


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class FakeBot:
    def __init__(self, clock):
        self.clock = clock
        self.task_id = "weekday_dungeon"
        self.cfg = {"dungeon": {"window_close": None}}  # 잘못 열린 창 닫기는 이 시험에서 보지 않는다
        self.packets = SimpleNamespace(ok=True, state=None)
        self.log = logging.getLogger("test")

    def sleep(self, a, b=None):
        self.clock.t += a

    def dialogue_playing(self):
        return False

    def cutscene_playing(self):
        return False


class FakeMon:
    def __init__(self, clock, menu_at, scene_at=None):
        self.clock, self.menu_at, self.scene_at = clock, menu_at, scene_at

    def dialog_opening(self):
        return False

    def check(self, ctx, guard=False):
        fin = self.clock.t >= self.menu_at
        scene = self.scene_at is not None and self.scene_at <= self.clock.t < self.scene_at + 5
        what = d.REWARD if fin else d.SCENE if scene else d.UNKNOWN
        return SimpleNamespace(finish=fin, what=what, done="연출 대기" if scene else None, frame=None)


class ClearShowTest(unittest.TestCase):
    def run_show(self, prompt_visible=False, scene_at=None):
        clock = Clock()
        bot = FakeBot(clock)
        touches = []
        self.how = []  # 'space' (글자를 봄) · 'blank' (보지 않고)

        def press(how):
            return lambda *a: (touches.append(clock.t), self.how.append(how))
        with mock.patch.object(clear, "clear_kind", return_value="dungeon"), \
                mock.patch.dict(clear.CLEAR_KINDS, {"dungeon": (lambda st: True, lambda st: True)}), \
                mock.patch.object(clear.time, "monotonic", clock), \
                mock.patch.object(clear, "touch_prompt_visible", return_value=prompt_visible), \
                mock.patch.object(clear, "handlers_touch", press("space")), \
                mock.patch.object(clear, "tap_blank", press("blank")):
            clear._clear_show(bot, FakeMon(clock, menu_at=40, scene_at=scene_at), d, end=1000)
        return touches

    def test_blind_touches_slow_down(self):
        """요일 던전은 보상 메뉴까지 40초 — 처음 3번 뒤로는 10초에 한 번만 (2026-11-04 빈 곳 연타)."""
        self.assertLessEqual(len(self.run_show()), 6)

    def test_no_blind_touch_after_scene(self):
        """던전은 보상 상자 연출을 본 뒤로는 보지 않고 누르지 않는다 (사용자 11-04)."""
        touches = self.run_show(scene_at=15)
        self.assertTrue(touches and all(t < 15 for t in touches), touches)

    def test_touch_when_prompt_seen(self):
        self.assertGreater(len(self.run_show(prompt_visible=True)), 6)
        self.assertIn("space", self.how)  # 글자를 봤으면 Space

    def test_blind_touch_is_not_space(self):
        """글자를 못 봤을 땐 Space 를 누르지 않는다 — 메인 화면이면 자동 전투가 켜진다."""
        self.run_show()
        self.assertEqual(set(self.how), {"blank"})


class TouchKeyTest(unittest.TestCase):
    def test_touch_presses_space_in_front(self):
        """'화면을 터치해 주세요' 가 보이면 앞에서도 Space (사용자 11-19 — 클릭 대신)."""
        from mabi.monitor import handlers
        bot = mock.Mock()
        bot.behind.return_value = False
        self.assertEqual(handlers.touch(bot, None, None), "화면 터치")
        bot.key.assert_called_once_with("space")
        bot.click.assert_not_called()

    def test_blank_tap(self):
        bot = mock.Mock()
        bot.cfg = {"dungeon": {"touch_xy": [40, 600]}}
        bot.behind.return_value = False
        clear.tap_blank(bot)
        bot.click.assert_called_once_with((40, 600))
        bot.key.assert_not_called()
        bot.behind.return_value = True
        clear.tap_blank(bot)
        bot.key.assert_called_once_with("space")


if __name__ == "__main__":
    unittest.main()
