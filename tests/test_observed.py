"""관찰 기록 (packet_monitor.days · PacketMonitor.seen_since): 멈춘 뒤 그 캐릭터에게 일어난 일을 이어 할 때 본다.
끊긴 사냥터 판은 관찰 기록에 클리어가 있으면 한 것, 빠짐없이 봤는데 없으면 안 한 것, 모르면 은동전 셈으로 (2026-11-22)."""
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from mabi.packet_monitor.days import DayLog, describe, val
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
        self.assertTrue(self.m.seen_since(ts, "field.context", 7, lambda r: val(r, "state_name") == WAIT["state_name"]))
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

    def test_interrupted(self):
        """끊긴 숙제 — 접속 도중이면 그 접속이 이어 하려던 같은 캐릭터의 숙제, 다음 캐릭터로 넘어가던 접속이면 없음."""
        from mabi.profile import DailyState
        with tempfile.TemporaryDirectory() as d:
            st = DailyState(Path(d))
            st.set_progress(2, "silver")
            self.assertEqual(st.interrupted()["task"], "silver")
            st.set_progress(2, "login")
            self.assertEqual(st.interrupted()["task"], "silver")
            st.set_progress(3, "login")  # 앞 캐릭터가 끝내고 다음 캐릭터로
            self.assertIsNone(st.interrupted())

    def test_login_takes_before_only_from_same_slot(self):
        """다른 자리의 접속 기록에 딸린 옛 숙제를 끌고 오지 않는다 (점검 2026-11-22)."""
        from mabi.profile import DailyState
        with tempfile.TemporaryDirectory() as d:
            st = DailyState(Path(d))
            st.set_progress(1, "silver")
            st.set_progress(2, "login")  # 다른 자리 접속이 끊김 — 그 before 는 1번의 은동전
            st.set_progress(1, "login")  # 1번부터 다시 — 2번으로 넘어갔으니 1번 은동전 판은 끝났다
            self.assertIsNone(st.interrupted())
            st.set_progress(1, "silver")
            st.set_progress(1, "login")
            st.set_progress(1, "login")  # 같은 자리 접속이 또 끊김 — 이어 하려던 숙제는 그대로
            self.assertEqual(st.interrupted()["task"], "silver")


class ObservedTest(unittest.TestCase):
    """관찰 기록 질문은 mabi.observed 한곳에서 (사용자 2026-11-22)."""

    def test_stopped_at_falls_back_to_login_stop(self):
        from mabi import observed
        from mabi.profile import DailyState
        self.assertIsNone(observed.stopped_at(None))
        with tempfile.TemporaryDirectory() as d:
            st = DailyState(Path(d))
            st.set_progress(2, "silver")  # 숙제 도중 리모콘이 꺼짐 — 멈춤 기록 없음
            self.assertIsNone(observed.stopped_at(st))
            st.set_progress(2, "login")
            st.mark_stopped()  # 이어 하려던 접속 도중 멈춤
            self.assertEqual(st.interrupted()["task"], "silver")
            self.assertEqual(observed.stopped_at(st), st.progress()["stopped"])

    def test_since_line_keeps_last(self):
        from mabi import observed
        m = PacketMonitor(None)
        for i in range(14):
            m.days.record("channel.entering", {"channel_name": f"맵{i}"}, 7)
        b = mock.MagicMock()
        b.packets = m
        line = observed.since_line(b, time.time() - 10)
        self.assertIn("맵13", line)
        self.assertNotIn("맵0", line)
        self.assertIn("(앞 2건 생략)", line)
        self.assertEqual(observed.since_line(b, None), "")


class CharacterRecordTest(unittest.TestCase):
    """관찰 기록에 캐릭터가 바뀐 것·이름을 남긴다 (사용자 2026-11-22)."""

    def test_char_change_only_and_names(self):
        m = PacketMonitor(None)
        m.apply("char.personal_data", {"char_id": 7})
        m.apply("char.appearing", {"mine": True, "actor": 1, "name": "가"})
        m.apply("channel.entering", {"channel_type": "Field", "channel_name": "이멘 마하"})
        m.apply("char.personal_data", {"char_id": 7})  # 맵을 옮길 때마다 온다 — 같은 캐릭터면 남기지 않는다
        m.apply("session.logout_ok", {})
        m.apply("char.personal_data", {"char_id": 8})  # 다른 캐릭터 — 이름은 맵에 들어가야 온다
        rows = [(r["key"], r.get("char"), r.get("name")) for r in m.days.since(0)]
        self.assertEqual(rows, [("char.personal_data", 7, None), ("channel.entering", 7, "가"),
                                ("session.logout_ok", 7, "가"), ("char.personal_data", 8, None)])
        m.apply("char.personal_data", {"char_id": 7})  # 돌아옴 — 전에 본 이름을 채운다
        self.assertEqual(m.days.since(0)[-1].get("name"), "가")

    def test_same_character_relogin_recorded(self):
        # 같은 캐릭터로 다시 접속(게임을 다시 켬 등)도 '접속' 으로 — 맵을 옮길 때마다 오는 것은 그대로 거른다
        m = PacketMonitor(None)
        m.apply("char.personal_data", {"char_id": 7})
        m.apply("session.logout_ok", {})
        m.apply("char.personal_data", {"char_id": 7})
        m.apply("char.personal_data", {"char_id": 7})
        self.assertEqual([r["key"] for r in m.days.since(0)],
                         ["char.personal_data", "session.logout_ok", "char.personal_data"])

    def test_black_hole_list_cleared_with_character(self):
        m = PacketMonitor(None)
        m.apply("char.personal_data", {"char_id": 7})
        m.apply("dimension.cleared", {"times": [1, 2]})
        m.apply("char.personal_data", {"char_id": 8})
        self.assertIsNone(m.state.dimensions_cleared)
        m.apply("dimension.cleared", {"times": [1]})
        m.apply("session.logout_ok", {})
        self.assertIsNone(m.state.dimensions_cleared)


class GatherableTest(unittest.TestCase):
    def test_failure_not_remembered_and_per_character(self):
        from mabi.bot import Marks
        from mabi.tasks import arbeit
        b = mock.MagicMock()
        b.marks = Marks()
        b.character = {"slot": 1}
        b.state.query.return_value = None
        self.assertIsNone(arbeit.gatherable(b))
        self.assertEqual(arbeit.ungatherable(b, {"objectives": [{"Description": "새록 버섯 포자 보유 3/10"}]}), [])
        b.state.query.return_value = {"items": [{"DisplayName": "새록 버섯 포자", "ToolOk": True}]}
        self.assertEqual(arbeit.gatherable(b), {"새록 버섯 포자"})
        b.state.query.return_value = {"items": [{"DisplayName": "새록 버섯 포자", "ToolOk": False}]}
        self.assertEqual(arbeit.gatherable(b), {"새록 버섯 포자"})  # 같은 캐릭터 — 기억
        b.character = {"slot": 2}
        self.assertEqual(arbeit.gatherable(b), set())  # 다른 캐릭터 — 다시 물음


class BoardCardsTest(unittest.TestCase):
    def test_empty_view_is_unknown(self):
        """카드가 안 보이는 화면은 '끝' 이 아니라 모름 — 보일 때까지 기다리고, 끝내 안 보이면 NotSeen."""
        from mabi.exceptions import NotSeen
        from mabi.tasks import board
        b = mock.MagicMock()
        reads = iter([[], [], ["카드"]])
        with (mock.patch.object(board, "find_texts"),
              mock.patch.object(board, "parse_cards", side_effect=lambda *a: next(reads, []))):
            self.assertEqual(board._cards(b, (0, 0, 1, 1), 5), ["카드"])
            with self.assertRaises(NotSeen):
                board._cards(b, (0, 0, 1, 1), 0)


if __name__ == "__main__":
    unittest.main()
