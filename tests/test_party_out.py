"""고정 파티에서 누가 빠지면 — 파티원이면 계속, 파티장이 빠지면(바뀜)·내가 빠지면 반복 카드를 끝낸다
(사용자 11-21 → 11-22) — 패킷 상태와 AbyssRepeat.done."""
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from mabi.packet_monitor import PacketMonitor
from mabi.packet_table import load
from mabi.tasks import party
from mabi.tasks.abyss import AbyssRepeat

ME, FRIEND, PARTY = 0x174ADF700000, 0x178AF7E00001, 0x1A1F0A712DA


def mon(leader):
    m = PacketMonitor(None)
    m.state.char_id = ME
    m.apply("party.info", {"party": PARTY, "leader": leader})
    return m


class PartyOutStateTest(unittest.TestCase):
    def setUp(self):
        self.m = mon(ME)
        self.since = time.monotonic() - 0.5

    def test_table_has_events(self):
        for key in ("party.member_out", "party.left", "party.leader"):
            self.assertIsNotNone(load().by_key(key), key)

    def test_member_out_keeps_going(self):
        self.m.apply("party.member_out", {})
        self.assertEqual(party.broken(self.m.state, self.since, "leader"), "")
        self.assertEqual(party.broken(self.m.state, self.since, "member"), "")

    def test_leader_out_ends_member(self):
        # 파티장(친구)이 나감 — 새 파티장(나)이 빠짐보다 먼저 같은 ms 에 온다 (party-1120b 20:06:11)
        m = mon(FRIEND)
        m.apply("party.leader", {"leader": ME})
        m.apply("party.member_out", {})
        self.assertIn("파티장", party.broken(m.state, self.since, "member"))

    def test_hand_over_ends_leader_until_back(self):
        self.m.apply("party.leader", {"leader": FRIEND})
        self.assertIn("파티장", party.broken(self.m.state, self.since, "leader"))
        self.m.apply("party.leader", {"leader": ME})   # 도로 받으면 파티장 카드는 이어 간다
        self.assertEqual(party.broken(self.m.state, self.since, "leader"), "")

    def test_change_before_start_is_old(self):
        m = mon(FRIEND)
        m.apply("party.leader", {"leader": ME})
        self.assertEqual(party.broken(m.state, time.monotonic() + 0.5, "leader"), "")

    def test_i_left(self):
        self.m.apply("party.left", {})
        self.assertIn("빠짐", party.broken(self.m.state, self.since, "leader"))

    def test_party_gone(self):
        # 어비스에서 혼자 먼저 나옴 — 나감 알림 없이 파티 없음 정보만 온다 (party-1120b 20:05:33)
        self.m.apply("party.info", {"party": 0, "leader": None})
        self.assertIn("빠짐", party.broken(self.m.state, self.since, "member"))

    def test_no_party(self):
        m = PacketMonitor(None)
        m.apply("party.info", {"party": 0, "leader": None})
        self.assertEqual(party.broken(m.state, 0.0, "leader"), "파티가 없음")

    def test_unknown_party_is_not_broken(self):
        m = PacketMonitor(None)
        self.assertEqual(party.broken(m.state, 0.0), "")


class RepeatDoneTest(unittest.TestCase):
    def rep(self, role, state):
        r = AbyssRepeat.__new__(AbyssRepeat)
        r.a = {"party_role": role}
        r.bot = mock.MagicMock()
        r.bot.packets = SimpleNamespace(ok=True, state=state)
        r.runs, r.minutes, r.t0 = 5, 0, time.monotonic()
        r.stat = {"clears": 0}
        r.seen = []
        r.on_event, r.KIND = r.seen.append, "abyss"
        r.party_since = time.monotonic() - 0.5
        return r

    def test_member_leaving_keeps_going(self):
        m = mon(ME)
        r = self.rep("leader", m.state)
        m.apply("party.member_out", {})
        self.assertFalse(r.done())
        self.assertEqual(r.seen, [])

    def test_done_when_leader_leaves(self):
        m = mon(FRIEND)
        r = self.rep("member", m.state)
        self.assertFalse(r.done())
        m.apply("party.leader", {"leader": ME})
        m.apply("party.member_out", {})
        self.assertTrue(r.done())
        self.assertEqual(r.seen[-1]["stage"], "party_out")
        self.assertIn("파티장", r.seen[-1]["why"])
        self.assertTrue(r.done())
        self.assertEqual(len(r.seen), 1)   # 한 번만 알린다

    def test_not_fixed_party_ignores(self):
        m = PacketMonitor(None)
        m.apply("party.info", {"party": 0, "leader": None})
        self.assertFalse(self.rep("", m.state).done())


if __name__ == "__main__":
    unittest.main()
