"""출석 NPC 의 버튼 없는 말풍선 대사 (situation.attendance_bubble) — 2026-11-23 06:12 주간 초기화 뒤 필드로 나오자 대화 창
없이 말풍선만 떠 메인 화면 복귀가 ESC 만 누르다 게임을 다시 켰다. 신호 + 흰 말풍선이면 출석으로 보고 넘긴다."""
import time
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

from mabi import situation as sit

FIX = Path(__file__).parent / "fixtures"


def bubble_frame():
    """위쪽 가운데에 흰 둥근 상자 + 글자 한 줄 (실제 화면 1920x1080 의 말풍선 자리 — 760~1160, 100~225)."""
    f = np.full((1080, 1920, 3), 60, np.uint8)
    f[100:225, 760:1160] = 255
    f[140:160, 820:1100] = 40   # 글자 줄
    return f


def bot(attending=True, since=10.0, main=False, loading=False, menu=False):
    b = mock.MagicMock()
    b.packets.ok = True
    b.packets.state.attending.return_value = attending
    b.packets.state.attendance_at = time.monotonic() - since
    b.at_main.return_value = main
    b.map_loading.return_value = loading
    b.ui = {"menu_quit": "menu_quit"}
    b.vision.has.return_value = True
    b.vision.find.return_value = (1, 1) if menu else None
    return b


class BubbleTest(unittest.TestCase):
    def test_bubble_with_signal(self):
        self.assertTrue(sit.attendance_bubble(bot(), bubble_frame()))

    def test_no_signal(self):
        self.assertFalse(sit.attendance_bubble(bot(attending=False), bubble_frame()))

    def test_too_soon(self):
        """신호가 막 왔으면 아직 — 대사 창이 그려지기 전에 누르면 필드의 무언가가 눌린다."""
        self.assertFalse(sit.attendance_bubble(bot(since=1.0), bubble_frame()))

    def test_main_loading_menu(self):
        for kw in ({"main": True}, {"loading": True}, {"menu": True}):
            self.assertFalse(sit.attendance_bubble(bot(**kw), bubble_frame()), kw)

    def test_window_is_not_bubble(self):
        """신호만 남은 90초 동안 연 입장 창은 출석이 아니다 — 흰 말풍선이 없다."""
        for name in ("abyss_entry_together.png", "raid_entry_scas.png"):
            frame = cv2.imread(str(FIX / name))
            self.assertFalse(sit.bubble_shown(frame), name)
            self.assertFalse(sit.attendance_bubble(bot(), frame), name)

    def test_clear_clicks_left(self):
        """말풍선이면 대화 창 대사처럼 왼쪽 빈 자리를 누른다 (2초에 한 번)."""
        b = bot()
        b.cfg = {"login": {"first_dialog_xy": [40, 600], "attendance_skip": "skip"}}
        b.marks.attendance_clicked = 0.0
        b.vision.find.return_value = None
        with mock.patch("mabi.tasks.dialogue.now") as now:
            now.return_value.drawn = False
            did = sit.clear_attendance(b, bubble_frame())
        b.click.assert_called_once_with((40, 600))
        self.assertEqual(did, "출석 대사 넘김")


if __name__ == "__main__":
    unittest.main()
