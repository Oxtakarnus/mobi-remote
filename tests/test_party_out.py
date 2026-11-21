"""고정 파티에서 누가 빠지면 반복 카드를 끝낸다 (사용자 11-21) — 패킷 상태와 AbyssRepeat.done."""
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from mabi.packet_monitor import PacketMonitor
from mabi.packet_table import load
from mabi.tasks import party
from mabi.tasks.abyss import AbyssRepeat

ME, FRIEND, PARTY = 0x174ADF700000, 0x178AF7E00001, 0x1A1F0A712DA


class PartyOutStateTest(unittest.TestCase):
    def setUp(self):
        self.m = PacketMonitor(None)
        self.m.state.char_id = ME
        self.m.apply("party.info", {"party": PARTY, "leader": ME})
        self.since = time.monotonic()

    def test_table_has_events(self):
        for key in ("party.member_out", "party.left"):
            self.assertIsNotNone(load().by_key(key), key)

    def test_member_out(self):
        self.assertFalse(party.broken(self.m.state, self.since))
        self.m.apply("party.member_out", {})
        self.assertTrue(party.broken(self.m.state, self.since))

    def test_i_left(self):
        self.m.apply("party.left", {})
        self.assertTrue(party.broken(self.m.state, self.since))

    def test_party_gone(self):
        self.m.apply("party.info", {"party": 0, "leader": None})
        self.assertTrue(party.broken(self.m.state, self.since))

    def test_unknown_party_is_not_broken(self):
        m = PacketMonitor(None)
        self.assertFalse(party.broken(m.state, 0.0))


class RepeatDoneTest(unittest.TestCase):
    def rep(self, role, state):
        r = AbyssRepeat.__new__(AbyssRepeat)
        r.a = {"party_role": role}
        r.bot = mock.MagicMock()
        r.bot.packets = SimpleNamespace(ok=True, state=state)
        r.runs, r.minutes, r.t0 = 5, 0, time.monotonic()
        r.stat = {"clears": 0}
        r.on_event, r.KIND = lambda e: None, "abyss"
        r.party_since = time.monotonic()
        return r

    def test_done_when_member_leaves(self):
        m = PacketMonitor(None)
        m.apply("party.info", {"party": PARTY, "leader": ME})
        r = self.rep("leader", m.state)
        self.assertFalse(r.done())
        m.apply("party.member_out", {})
        self.assertTrue(r.done())

    def test_not_fixed_party_ignores(self):
        m = PacketMonitor(None)
        m.apply("party.info", {"party": 0, "leader": None})
        self.assertFalse(self.rep("", m.state).done())


if __name__ == "__main__":
    unittest.main()
