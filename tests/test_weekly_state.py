"""주간 숙제 기록 (WeeklyState): 월요일 오전 6시에 새 주, 완료는 그 주 동안 유지, 하루 기록에서 모으기."""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from mabi import profile as prof


class WeeklyStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_week_starts_monday_6am(self):
        # 2026-11-23 은 월요일
        self.assertEqual(prof.game_week(datetime(2026, 11, 23, 5, 59)), "2026-11-16")
        self.assertEqual(prof.game_week(datetime(2026, 11, 23, 6, 0)), "2026-11-23")
        self.assertEqual(prof.game_week(datetime(2026, 11, 29, 23, 0)), "2026-11-23")

    def test_done_not_overwritten_in_same_week(self):
        now = datetime(2026, 11, 24, 12, 0)
        w = prof.WeeklyState(self.dir, now)
        w.set(1, "field_boss", "done")
        w.set(1, "field_boss", "FAIL: 끊김")
        self.assertEqual(prof.WeeklyState(self.dir, now).get(1, "field_boss"), "done")
        w.set(2, "board", "FAIL: 끊김")
        w.set(2, "board", "done")
        self.assertEqual(prof.WeeklyState(self.dir, now).get(2, "board"), "done")

    def test_new_week_is_empty(self):
        prof.WeeklyState(self.dir, datetime(2026, 11, 22, 12, 0)).set(1, "vanguard", "done")
        self.assertIsNone(prof.WeeklyState(self.dir, datetime(2026, 11, 23, 6, 0)).get(1, "vanguard"))

    def test_collects_from_daily_files(self):
        (self.dir / "2026-11-15.json").write_text(json.dumps({"1": {"board": "done"}}), encoding="utf-8")  # 지난주
        (self.dir / "2026-11-16.json").write_text(json.dumps({"1": {"vanguard": "done", "silver": "done"}}), encoding="utf-8")
        (self.dir / "2026-11-18.json").write_text(json.dumps({"1": {"vanguard": "FAIL: x"}, "_progress": {}}), encoding="utf-8")
        w = prof.WeeklyState(self.dir, datetime(2026, 11, 20, 12, 0))
        self.assertEqual(w.data, {"1": {"vanguard": "done"}})

    def test_daily_set_mirrors_weekly_tasks(self):
        d = prof.DailyState(self.dir)
        d.set(3, "field_boss", "done")
        d.set(3, "silver", "done")
        w = prof.WeeklyState(self.dir)
        self.assertEqual(w.get(3, "field_boss"), "done")
        self.assertIsNone(w.get(3, "silver"))


if __name__ == "__main__":
    unittest.main()
