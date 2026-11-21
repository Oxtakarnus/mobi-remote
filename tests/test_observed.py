"""관찰 기록 (packet_monitor.days · PacketMonitor.seen_since): 멈춘 뒤 그 캐릭터에게 일어난 일을 이어 할 때 본다.
끊긴 사냥터 판은 관찰 기록에 클리어가 있으면 한 것, 빠짐없이 봤는데 없으면 안 한 것, 모르면 은동전 셈으로 (2026-11-22)."""
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from mabi.packet_monitor.days import DayLog, describe
from mabi.packet_monitor.monitor import PacketMonitor

T0 = datetime(2026, 11, 22, 12, 0, 0)
WAIT = {"state_name": "WaitingForChannelTransfer"}


class DayLogSinceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = DayLog()
        self.log.open(Path(self.tmp.name), T0)

    def tearDown(self):
        self.tmp.cleanup()

    def test_since_filters_time_key_char(self):
        self.log.record("field.context", {"state_name": "InProgress"}, 7, T0, name="가")
        self.log.record("field.context", WAIT, 7, T0 + timedelta(minutes=5), name="가")
        self.log.record("field.context", WAIT, 8, T0 + timedelta(minutes=6), name="나")
        after = (T0 + timedelta(minutes=1)).timestamp()
        self.assertEqual([r["char"] for r in self.log.since(after, "field.context")], [7, 8])
        self.assertEqual(len(self.log.since(after, "field.context", 7)), 1)
        self.assertEqual(self.log.since(after, "dungeon.state"), [])

    def test_rows_survive_reopen(self):
        self.log.record("channel.entering", {"channel_name": "이멘 마하"}, 7, T0, name="가")
        again = DayLog()
        again.open(Path(self.tmp.name), T0)
        rows = again.since(T0.timestamp() - 1)
        self.assertEqual(rows[0]["name"], "가")
        self.assertEqual(describe(rows[0]), "12:00:00 가 맵 이멘 마하")


class SeenSinceTest(unittest.TestCase):
    def setUp(self):
        self.m = PacketMonitor(None)
        self.m.status = "running"
        self.m.watch_from = time.time() - 100

    def test_found_none_unknown(self):
        ts = time.time() - 50
        self.assertIs(self.m.seen_since(ts, "field.context", 7), False)  # 빠짐없이 봤는데 없음
        self.m.days.record("field.context", WAIT, 7)
        self.assertTrue(self.m.seen_since(ts, "field.context", 7, lambda v: v.get("state_name") == WAIT["state_name"]))
        self.assertIs(self.m.seen_since(ts, "field.context", 8), False)

    def test_unknown_when_not_watching_whole_time(self):
        ts = time.time() - 200  # 감시를 켜기 전
        self.assertIsNone(self.m.seen_since(ts, "field.context", 7))
        self.m.gap_at = time.time() - 10  # 흐름이 끊긴 적 있음
        self.assertIsNone(self.m.seen_since(time.time() - 50, "field.context", 7))
        self.assertIsNone(self.m.seen_since(None, "field.context", 7))


class CutFieldTest(unittest.TestCase):
    def done(self, seen, coins_now):
        from mabi.tasks import silver
        bot = mock.MagicMock()
        bot.packets.seen_since.return_value = seen
        pend = {"kind": "field", "n": 3, "coins": 68, "ts": 1.0, "char": 7}
        return silver._cut_field_done(bot, pend, coins_now, 20)

    def test_clear_seen_counts_even_if_coins_confusing(self):
        self.assertTrue(self.done({"t": "23:38:38"}, coins_now=68))

    def test_watched_no_clear_does_not_count(self):
        self.assertFalse(self.done(False, coins_now=48))

    def test_unknown_falls_back_to_coins(self):
        self.assertTrue(self.done(None, coins_now=48))
        self.assertFalse(self.done(None, coins_now=68))


class ProgressStopTest(unittest.TestCase):
    def test_stopped_kept_through_login(self):
        from mabi.profile import DailyState
        with tempfile.TemporaryDirectory() as d:
            st = DailyState(Path(d))
            st.set_progress(2, "silver", char=7)
            st.mark_stopped()
            st.set_progress(2, "login")
            b = st.progress()["before"]
            self.assertEqual((b["task"], b["char"]), ("silver", 7))
            self.assertIn("stopped", b)


if __name__ == "__main__":
    unittest.main()
