"""콘텐츠에서 못 나올 때 안전장치 (exits.leave_instance → _escape, 사용자 2026-11-23)."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cv2
import numpy as np

from mabi import place as place_mod
from mabi.exceptions import StepTimeout
from mabi.place import OPEN_FIELD, RAID
from mabi.tasks import exits, login, raid

FIX = Path(__file__).parent / "fixtures"


def image(name):
    return cv2.imdecode(np.fromfile(str(FIX / name), np.uint8), cv2.IMREAD_COLOR)


BLANK = np.zeros((1080, 1920, 3), np.uint8)


class EscapeTest(unittest.TestCase):
    """맞는 나가기로 못 나오면 ① 나가기 키 뒤 확인 창이면 Space ② ESC 메뉴로 캐릭터 선택 화면 → 같은 캐릭터로 다시 접속.
    게임을 끄고 켜지는 않는다."""

    def _run(self, kinds, any_ok=False, menu_err=None):
        bot = mock.MagicMock()
        calls, seq = [], iter(kinds)

        def get_out(b):
            calls.append("나가기")
            raise StepTimeout("레이드에서 나가지 못함")

        def any_run(self, b):
            calls.append("키+Space")
            if any_ok:
                return True
            raise StepTimeout("레이드에서 나가기를 2번 눌러도 안에 남음")

        def menu(**kw):
            calls.append("메뉴")
            if menu_err:
                raise menu_err
        bot.menu_to_charselect.side_effect = menu

        def enter_again(b):
            calls.append("다시 접속")
            return "접속 완료"
        with mock.patch.object(place_mod, "place", side_effect=lambda b: SimpleNamespace(kind=next(seq, kinds[-1]))), \
                mock.patch.object(raid, "get_out", side_effect=get_out), \
                mock.patch.object(exits.AnyDialogExit, "run", any_run), \
                mock.patch.object(login, "enter_again", side_effect=enter_again):
            try:
                return exits.leave_instance(bot), calls
            except StepTimeout as e:
                return e, calls

    def test_key_space_gets_out(self):
        r, calls = self._run([RAID, OPEN_FIELD], any_ok=True)
        self.assertIs(r, True)
        self.assertEqual(calls, ["나가기", "키+Space"])

    def test_relog_when_key_space_fails(self):
        r, calls = self._run([RAID, OPEN_FIELD])
        self.assertIs(r, True)
        self.assertEqual(calls, ["나가기", "키+Space", "메뉴", "다시 접속"])

    def test_still_inside_after_relog_fails(self):
        r, calls = self._run([RAID, RAID])
        self.assertIsInstance(r, StepTimeout)
        self.assertIn("레이드에서 나가지 못함", str(r))
        self.assertIn("다시 접속해도", str(r))

    def test_menu_not_opening_fails(self):
        r, calls = self._run([RAID], menu_err=StepTimeout("메뉴 안 열림"))
        self.assertIsInstance(r, StepTimeout)
        self.assertEqual(calls, ["나가기", "키+Space", "메뉴"])

    def test_outside_does_nothing(self):
        r, calls = self._run([OPEN_FIELD])
        self.assertIs(r, False)
        self.assertEqual(calls, [])


class AnyDialogExitTest(unittest.TestCase):
    def _bot(self):
        b = mock.MagicMock()
        b.cfg = {"timing": {"loading": 30}}
        b.frame.return_value = BLANK
        b.wait_packet.return_value = True  # Space 뒤 로딩 시작
        b.map_loading.return_value = False
        b.at_main.return_value = True
        keys = []
        b.key.side_effect = lambda k, *a, **kw: keys.append(k)
        return b, keys

    def test_confirm_dialog_reads_esc_cancel(self):
        b = mock.MagicMock()
        b.frame.return_value = image("raid_leave_giveup.png")
        self.assertIsNotNone(exits._confirm_dialog(b))
        b.frame.return_value = BLANK
        self.assertIsNone(exits._confirm_dialog(b))

    def test_space_on_unknown_confirm_dialog(self):
        """나가기 키 뒤 가운데 확인 창이 뜨면 무슨 창인지 몰라도 Space — 그날 몰랐던 '포기하기' 창."""
        shown = image("raid_leave_giveup.png")
        b, keys = self._bot()
        b.frame.side_effect = lambda: shown if "shift+esc" in keys else BLANK
        seq = iter([True, False])
        with mock.patch.object(exits.AnyDialogExit, "where", lambda self, bot: next(seq, False)):
            self.assertTrue(exits.AnyDialogExit(RAID, "레이드").run(b))
        self.assertEqual(keys, ["shift+esc", "space"])
        b.click.assert_not_called()
        b.click_if.assert_not_called()

    def test_no_dialog_no_space(self):
        """창이 안 뜨면 Space 를 누르지 않는다 (보상 화면의 Space 는 '다시 하기' 일 수 있다) → 시간이 다 되면 StepTimeout."""
        b, keys = self._bot()
        clock = [0.0]
        b.sleep.side_effect = lambda *a: clock.__setitem__(0, clock[0] + 1)
        with mock.patch.object(exits.AnyDialogExit, "where", lambda self, bot: True), \
                mock.patch("time.monotonic", side_effect=lambda: clock[0]):
            with self.assertRaises(StepTimeout):
                exits.AnyDialogExit(RAID, "레이드").run(b)
        self.assertIn("shift+esc", keys)
        self.assertNotIn("space", keys)


class EnterAgainTest(unittest.TestCase):
    def test_from_charselect_without_start_tidy(self):
        """다시 접속은 선택 화면부터 — 시작 정리(콘텐츠 나가기)를 다시 부르지 않는다 (그 나가기 안에서 부른다)."""
        b = mock.MagicMock()
        b.cfg = {"login": {}}
        b.ui = {"main_hud": "m", "title_start": "t", "charselect_title": "cs"}
        b.character = {"slot": 2, "name": "x"}
        order = []
        with mock.patch.object(login._Login, "tidy_start", side_effect=AssertionError("시작 정리")), \
                mock.patch.object(login._Login, "reach_charselect",
                                  lambda self: order.append("선택 화면") or SimpleNamespace(name="cs")), \
                mock.patch.object(login._Login, "enter_game", lambda self: order.append("게임 시작") or "mark"), \
                mock.patch.object(login._Login, "check_character", lambda self, mark: order.append(("확인", mark))), \
                mock.patch.object(login._Login, "settle", lambda self: order.append("정리") or "접속 완료"), \
                mock.patch.object(login, "_auth_names", return_value=[]):
            self.assertEqual(login.enter_again(b), "접속 완료")
        self.assertEqual(order, ["선택 화면", "게임 시작", ("확인", "mark"), "정리"])


if __name__ == "__main__":
    unittest.main()
