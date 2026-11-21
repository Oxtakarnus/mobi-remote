"""패킷 하루 기록 (packet_monitor.days) — 게임 날짜별 파일, 오늘·어제만 두기, 다시 켜도 오늘 것을 앎, 내 것만 남김.
그리고 그것으로 출석을 넘긴 것으로 보기 (situation.check_attendance)."""
import json
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from mabi.packet_monitor import PacketMonitor
from mabi.packet_monitor.days import DayLog


def at(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


class DayLogTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_game_day_files_and_first_time(self):
        d = DayLog()
        d.open(self.dir, at("2026-11-17 07:00:00"))
        d.record("daily.attendance_start", {}, 15, at("2026-11-17 06:47:54"))
        d.record("daily.attendance_start", {}, 16, at("2026-11-17 07:10:00"))
        d.record("channel.entering", {"channel": 7, "blob": b"x", "long": "y" * 200}, 15, at("2026-11-18 05:59:00"))
        self.assertEqual(d.today("daily.attendance_start", at("2026-11-17 09:00:00")), "06:47:54")
        rows = [json.loads(x) for x in (self.dir / "2026-11-17.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["t"] for r in rows], ["06:47:54", "07:10:00", "05:59:00"])  # 다음 날 06시 전은 같은 게임 날짜
        self.assertEqual(rows[2]["vals"], {"channel": 7})  # 바이트·긴 글은 남기지 않는다
        self.assertEqual(rows[0]["char"], 15)
        # 오전 6시가 지나면 새 날 — 어제 출석은 오늘 출석이 아니다
        self.assertIsNone(d.today("daily.attendance_start", at("2026-11-18 06:00:01")))

    def test_reopen_knows_today(self):
        d = DayLog()
        d.open(self.dir, at("2026-11-17 07:00:00"))
        d.record("daily.attendance_start", {}, 1, at("2026-11-17 06:47:54"))
        again = DayLog()  # 리모콘을 다시 켬
        again.open(self.dir, at("2026-11-17 08:00:00"))
        self.assertEqual(again.today("daily.attendance_start", at("2026-11-17 08:00:00")), "06:47:54")

    def test_keeps_today_and_yesterday(self):
        for day in ("2026-11-14", "2026-11-15", "2026-11-16", "2026-11-17"):
            (self.dir / f"{day}.jsonl").write_text("", encoding="utf-8")
        (self.dir / "note.txt").write_text("", encoding="utf-8")
        DayLog().open(self.dir, at("2026-11-17 07:00:00"))
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["2026-11-16.jsonl", "2026-11-17.jsonl", "note.txt"])
        d = DayLog()
        d.open(self.dir, at("2026-11-17 07:00:00"))
        d.record("x", {}, None, at("2026-11-18 06:00:05"))  # 날이 바뀌면 그때도 지운다
        self.assertEqual(sorted(p.name for p in self.dir.glob("*.jsonl")), ["2026-11-17.jsonl", "2026-11-18.jsonl"])

    def test_memory_only_before_open(self):
        d = DayLog()
        d.record("x", {}, None)
        self.assertIsNotNone(d.today("x"))
        self.assertEqual(list(self.dir.iterdir()), [])


class RememberTest(unittest.TestCase):
    """감시는 우리 판단에 쓰는 이벤트(days.KEYS)만 남긴다 (사용자 2026-11-17)."""
    def test_only_needed_keys(self):
        m = PacketMonitor(None)
        m.state.me, m.state.char_id = 77, 15
        rec = []
        m.days.record = lambda key, vals, char=None, name=None: rec.append((key, char))
        m.apply("actor.combat_state", {"actor": 77, "state_name": "InCombat"})  # 순간 상태는 안 남긴다
        m.apply("travel.begin", {"points": 3})
        m.apply("channel.entering", {"channel": 3})  # 관찰 기록 (2026-11-22)
        m.apply("daily.attendance_start", {})
        self.assertEqual(rec, [("channel.entering", 15), ("daily.attendance_start", 15)])

    def test_today_needs_running(self):
        m = PacketMonitor(None)
        m.days.record("daily.attendance_start", {})
        self.assertIsNone(m.today("daily.attendance_start"))  # 감시가 안 돌면 모름
        m.status = "running"
        self.assertIsNotNone(m.today("daily.attendance_start"))


class AttendancePassTest(unittest.TestCase):
    """오늘 출석 대화가 있었으면 지나간 것 — 작업을 시작할 때 남은 신호는 화면에 출석이 없으면 지운다 (사용자 2026-11-17)."""
    def bot(self, seen_at="06:47:54", window=False):
        from mabi.bot import Marks
        from mabi.packet_monitor import PacketState
        b = mock.Mock()
        b.cfg = {"login": {"attendance_skip": "attendance_skip"}, "arbeit": {"dialog_log": "dialog_log"}}
        b.marks = Marks()
        b.attendance_date = "2000-01-01"
        b.packets.status = "running"
        b.packets.today.side_effect = lambda key: seen_at if key == "daily.attendance_start" else None
        b.packets.state = PacketState(attendance_at=time.monotonic())
        b.vision.has.return_value = True
        b.vision.find.side_effect = lambda f, n: (1, 1) if window and n == "dialog_log" else None
        b.skip_button.return_value = None
        return b

    def test_passed_signal_cleared(self):
        from mabi import situation
        b = self.bot()
        self.assertFalse(situation.attendance_due(b))
        situation.check_attendance(b)
        self.assertFalse(b.packets.state.attending())
        self.assertEqual(b.attendance_date, situation.game_date())

    def test_still_on_screen_kept(self):
        from mabi import situation
        b = self.bot(window=True)
        situation.check_attendance(b)
        self.assertTrue(b.packets.state.attending())  # 끼어들기가 넘긴다

    def test_not_seen_today_left_alone(self):
        from mabi import situation
        b = self.bot(seen_at=None)
        situation.check_attendance(b)
        self.assertTrue(b.packets.state.attending())
        self.assertEqual(b.attendance_date, "2000-01-01")
        self.assertTrue(situation.attendance_due(b))


if __name__ == "__main__":
    unittest.main()
