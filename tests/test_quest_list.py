"""스크롤 목록 훑기(steps.list_views)와 공물 던전의 고난도 카드 찾기(tribute.open_quest) — 가짜 목록으로 돌린다."""
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from mabi.tasks import steps, tribute

AREA = (1230, 150, 690, 850)
C = {"list_scroll_at": [1540, 600], "quest_card": "card", "quest_go": "go"}


class FakeList:
    """목록 자리(pos 0 = 맨 위 … bottom). late: 첫 올리기 뒤 게임이 목록을 맨 아래로 옮긴다 (막 갱신된 주간 목표 카드 쪽).
    고난도 카드(제목 y=300, 버튼 y=480)는 맨 위에서만 보이고, 내려가면 제목이 화면 위로 사라져 버튼만 남는다."""

    def __init__(self, bottom=2, late=False):
        self.pos, self.bottom, self.late, self.scrolls, self.clicked = bottom, bottom, late, 0, None
        self.log = mock.MagicMock()

    def scroll(self, x, y, n):
        self.scrolls += 1
        self.pos = 0 if n > 0 else min(self.pos + 1, self.bottom)
        if self.late and self.scrolls == 1:
            self.pos = self.bottom

    def sleep(self, *a):
        pass

    def frame(self):
        return np.full((1080, 1920, 3), self.pos * 60, np.uint8)

    def find(self, name, region=None, threshold=None, fresh=True):
        return SimpleNamespace(x=1300, y=300, w=300, h=30) if name == "card" and self.pos == 0 else None

    def find_all(self, name, region=None, threshold=None):
        if name != "go":
            return []
        y = 480 if self.pos == 0 else 300  # 맨 위가 아니면 고난도 카드 버튼이 위로 올라가 제목 없이 보인다
        return [SimpleNamespace(x=1690, y=y, w=150, h=60)]

    def click(self, at):
        self.clicked = at

    def snapshot(self, tag):
        return SimpleNamespace(name=f"{tag}.png")


class ListViewsTest(unittest.TestCase):
    def test_starts_at_top_even_if_game_moves_list_late(self):
        """첫 올리기가 묻혀도(게임이 늦게 목록을 옮김) 한 번 더 올려 맨 위부터 넘겨준다."""
        bot = FakeList(late=True)
        seen = [bot.pos for _ in steps.list_views(bot, AREA, (1540, 600), 3, 8)]
        self.assertEqual(seen, [0, 1, 2, 2])  # 맨 아래는 한 번 더 내려 봐도 그대로일 때 끝

    def test_already_top_one_extra_scroll(self):
        bot = FakeList()
        it = steps.list_views(bot, AREA, (1540, 600), 3, 8)
        next(it)
        self.assertEqual((bot.pos, bot.scrolls), (0, 2))  # 올리기 두 번 (두 번째는 맨 위 확인)


class OpenQuestTest(unittest.TestCase):
    def _open(self, bot):
        with mock.patch.object(tribute, "open_tab", return_value=True), \
                mock.patch.object(tribute.ui_text, "find_texts", return_value=[]):
            tribute.open_quest(bot, C)

    def test_presses_card_button_when_list_moved_late(self):
        # 2026-11-25 06:47: 은동전 직후 — 예전엔 맨 아래부터 찾아 제목 없는 버튼만 보고 '진행하기를 찾지 못함'
        bot = FakeList(late=True)
        self._open(bot)
        self.assertEqual(bot.clicked.y, 480)

    def test_title_by_text_when_picture_misses(self):
        bot = FakeList()
        bot.find = lambda *a, **k: None
        with mock.patch.object(tribute, "open_tab", return_value=True), \
                mock.patch.object(tribute.ui_text, "find_texts", return_value=[(tribute.QUEST_TITLE, 1500, 315)]):
            tribute.open_quest(bot, C)
        self.assertEqual(bot.clicked.y, 480)

    def test_not_found_raises(self):
        bot = FakeList()
        bot.find = lambda *a, **k: None
        with self.assertRaises(RuntimeError):
            self._open(bot)
        self.assertIsNone(bot.clicked)


if __name__ == "__main__":
    unittest.main()
