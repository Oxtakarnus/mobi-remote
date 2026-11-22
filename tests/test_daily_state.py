"""하루 진행 기록 — 사람이 멈춘 숙제(STOP)는 실패가 아니다 (mabi.profile.DailyState)."""
import tempfile
import unittest
from pathlib import Path

from mabi.profile import DailyState, manual_note


class FailedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = DailyState(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_stop_is_not_failed(self):
        # 실패로 치면 그 캐릭터가 '실패만 남음'으로 맨 뒤로 밀려 다음 캐릭터부터 했다
        self.st.set(1, "silver", "STOP: ")
        self.assertFalse(self.st.failed(1, "silver"))
        self.assertFalse(self.st.is_done(1, "silver"))

    def test_fail_and_check_are_failed(self):
        self.st.set(1, "tribute", "FAIL: 퀘스트 없음")
        self.st.set(1, "daily_mission", "CHECK: 남음")
        self.assertTrue(self.st.failed(1, "tribute"))
        self.assertTrue(self.st.failed(1, "daily_mission"))

    def test_done_and_untried(self):
        self.st.set(1, "weekday_dungeon", "done")
        self.assertFalse(self.st.failed(1, "weekday_dungeon"))
        self.assertFalse(self.st.failed(1, "arbeit"))

    def test_manual_is_done_with_note(self):
        self.st.set(1, "arbeit", "MANUAL: 아르바이트 6개 완료, 건너뜀: 가공 일(가공 필요) — 조건이 안 돼 넘긴 일은 직접 처리")
        self.assertTrue(self.st.is_done(1, "arbeit"))
        self.assertEqual(manual_note(self.st.get(1, "arbeit")),
                         "아르바이트 6개 완료, 건너뜀: 가공 일(가공 필요) — 조건이 안 돼 넘긴 일은 직접 처리")
        self.assertIsNone(manual_note("done"))
        self.assertIsNone(manual_note(None))


class CardTodayTest(unittest.TestCase):
    """캐릭터 탭 카드 — 넘긴 숙제도 끝난 것으로 세되 따로 (사용자 11-22: '오늘 클리어 · 넘김 1' + 풍선)."""

    def test_manual_listed(self):
        from gui_app.chars_api import today_of
        with tempfile.TemporaryDirectory() as d:
            st = DailyState(Path(d))
            st.set(1, "silver", "done")
            st.set(1, "arbeit", "MANUAL: 건너뜀: 가공 일(가공 필요)")
            t = today_of(st, 1, ["silver", "arbeit", "black_hole"])
        self.assertEqual((t["done"], t["total"]), (2, 3))
        self.assertEqual(t["manual"], [{"task": "아르바이트", "note": "건너뜀: 가공 일(가공 필요)"}])

    def test_nothing_skipped(self):
        from gui_app.chars_api import today_of
        with tempfile.TemporaryDirectory() as d:
            st = DailyState(Path(d))
            st.set(2, "silver", "done")
            self.assertEqual(today_of(st, 2, ["silver"]), {"done": 1, "total": 1, "manual": []})


if __name__ == "__main__":
    unittest.main()
