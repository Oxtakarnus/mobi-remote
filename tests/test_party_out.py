"""고정 파티에서 누가 빠지면 — 파티원이면 계속, 파티장이 빠지면(바뀜)·내가 빠지면 반복 카드를 끝낸다 (사용자 11-21 → 11-22).
판단은 이벤트 한 번이 아니라 지금 상태로 (party.Watch) — 우연한 만남 판에 게임이 파티를 풀었다 다시 만드는 사이는 깨짐이
아니다 (사용자 11-23 테스터 제보)."""
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from mabi.packet_monitor import PacketMonitor
from mabi.packet_table import load
from mabi.place import ABYSS, OPEN_FIELD
from mabi.tasks import party
from mabi.tasks.abyss import AbyssRepeat

ME, FRIEND, OTHER, PARTY, NEW = 0x174ADF700000, 0x178AF7E00001, 0x1999999A0002, 0x1A1F0A712DA, 0x1A1F0A71FFF


def mon(leader, size=2):
    m = PacketMonitor(None)
    m.state.char_id = ME
    m.state.channel_type = OPEN_FIELD
    m.apply("party.info", {"party": PARTY, "leader": leader, "size": size})
    return m


def later(s, sec=party.GRACE + 1):
    """파티가 바뀐 지 sec 초 뒤의 지금."""
    return s.party_at + sec


class WatchTest(unittest.TestCase):
    def watch(self, role, m):
        w = party.Watch(role, m.state)
        self.assertEqual(w.why(m.state), "")   # 처음 본 파티장·파티 번호를 기억
        return w

    def test_table_has_events(self):
        for key in ("party.member_out", "party.left", "party.leader", "party.info", "abyss.matching_update"):
            self.assertIsNotNone(load().by_key(key), key)

    def test_member_out_keeps_going(self):
        for role, leader in (("leader", ME), ("member", FRIEND)):
            m = mon(leader, size=3)
            w = self.watch(role, m)
            m.apply("party.member_out", {})
            self.assertEqual(w.why(m.state, later(m.state)), "", role)

    def test_leader_out_ends_member_after_grace(self):
        # 파티장(친구)이 나감 — 새 파티장(나)이 빠짐보다 먼저 같은 ms 에 온다 (party-1120b 20:06:11)
        m = mon(FRIEND)
        w = self.watch("member", m)
        m.apply("party.leader", {"leader": ME})
        m.apply("party.member_out", {})
        self.assertEqual(w.why(m.state, later(m.state, 1)), "")   # 바뀐 직후엔 아직 (풀었다 다시 만드는 사이일 수 있다)
        self.assertIn("파티장", w.why(m.state, later(m.state)))

    def test_hand_over_ends_leader_until_back(self):
        m = mon(ME)
        w = self.watch("leader", m)
        m.apply("party.leader", {"leader": FRIEND})
        self.assertIn("파티장", w.why(m.state, later(m.state)))
        m.apply("party.leader", {"leader": ME})   # 도로 받으면 파티장 카드는 이어 간다
        self.assertEqual(w.why(m.state, later(m.state)), "")

    def test_leader_back_within_grace(self):
        """잠깐 파티가 없어졌다 같은 파티장으로 다시 생기면 깨짐이 아니다."""
        m = mon(FRIEND)
        w = self.watch("member", m)
        m.apply("party.info", {"party": 0, "leader": None})
        self.assertEqual(w.why(m.state, later(m.state, 2)), "")
        m.apply("party.info", {"party": NEW, "leader": FRIEND, "size": 2})
        self.assertEqual(w.why(m.state, later(m.state)), "")

    def test_i_left(self):
        m = mon(ME)
        w = self.watch("leader", m)
        m.apply("party.left", {})
        m.apply("party.info", {"party": 0, "leader": None})
        self.assertIn("파티가 없음", w.why(m.state, later(m.state)))

    def test_no_party_at_start(self):
        m = PacketMonitor(None)
        m.state.char_id = ME
        m.apply("party.info", {"party": 0, "leader": None})
        self.assertIn("파티가 없음", party.Watch("leader", m.state).why(m.state, later(m.state)))

    def test_unknown_party_is_not_broken(self):
        m = PacketMonitor(None)
        self.assertEqual(party.Watch("member", m.state).why(m.state), "")


class ChanceWindowTest(unittest.TestCase):
    """우연한 만남 판: 매칭 → (게임이 파티를 풀거나 바꿈) → 어비스 → 밖으로 나와 다시 생긴 파티."""

    def start(self, role, leader):
        m = mon(leader, size=3)
        w = party.Watch(role, m.state)
        w.why(m.state)
        m.apply("abyss.matching_update", {"state": 2})
        return m, w

    def into_abyss(self, m, party_id=0, leader=None):
        m.apply("party.info", {"party": party_id, "leader": leader, "size": 4 if party_id else 0})
        m.state.abyss_matching, m.state.channel_type = 0, ABYSS

    def test_dissolved_then_restored(self):
        for role, leader in (("leader", ME), ("member", FRIEND)):
            m, w = self.start(role, leader)
            self.assertEqual(w.why(m.state), "")                       # 매칭 중
            self.into_abyss(m, OTHER, OTHER)                            # 판 안: 모르는 사람이 파티장인 파티
            self.assertEqual(w.why(m.state, later(m.state, 300)), "", role)
            self.assertTrue(w.replaced(m.state))                        # 보상 화면에서: 파티가 바뀜 → 나간다
            m.state.channel_type = OPEN_FIELD                           # 나옴 — 아직 파티 없음
            m.apply("party.info", {"party": 0, "leader": None})
            now = time.monotonic()
            self.assertEqual(w.why(m.state, now), "")
            self.assertEqual(w.why(m.state, now + party.RESTORE_WAIT - 1), "")
            m.apply("party.info", {"party": NEW, "leader": leader, "size": 2})   # 다시 생김 (새 번호)
            self.assertEqual(w.why(m.state, now + party.RESTORE_WAIT + 5), "", role)
            self.assertFalse(w.gathered(m.state))                       # 판 전 3명 — 아직 2명
            m.apply("party.member_add", {})
            self.assertTrue(w.gathered(m.state))
            self.assertFalse(w.replaced(m.state))                       # 새 번호가 이제 우리 파티

    def test_not_restored_ends(self):
        m, w = self.start("member", FRIEND)
        self.into_abyss(m)
        m.state.channel_type = OPEN_FIELD
        now = time.monotonic()
        self.assertEqual(w.why(m.state, now), "")
        why = w.why(m.state, now + party.RESTORE_WAIT + 1)
        self.assertIn("돌아오지 않음", why)
        self.assertIn("파티가 없음", why)

    def test_restored_with_other_leader_ends_member(self):
        m, w = self.start("member", FRIEND)
        self.into_abyss(m)
        m.state.channel_type = OPEN_FIELD
        m.apply("party.info", {"party": NEW, "leader": OTHER, "size": 3})
        now = time.monotonic()
        self.assertEqual(w.why(m.state, now), "")
        self.assertIn("파티장이 바뀜", w.why(m.state, now + party.RESTORE_WAIT + 1))

    def test_party_kept_same(self):
        """게임이 파티를 그대로 두면 (같은 번호) 어비스 안에서 바로 돌아온 것 — 예전 흐름(다른 던전 가기)."""
        m, w = self.start("leader", ME)
        self.into_abyss(m, PARTY, ME)
        self.assertEqual(w.why(m.state), "")
        self.assertFalse(w.away)
        self.assertFalse(w.replaced(m.state))

    def test_dissolved_inside_without_matching(self):
        """파티원이 매칭 신호를 못 받아도 판 안에서 파티 번호가 바뀌면 우연한 만남 판으로 보고 밖으로 나올 때까지 미룬다."""
        m = mon(FRIEND, size=3)
        w = party.Watch("member", m.state)
        w.why(m.state)
        m.state.channel_type = ABYSS
        m.apply("party.info", {"party": 0, "leader": None})
        self.assertEqual(w.why(m.state, later(m.state)), "")
        self.assertTrue(w.away)
        self.assertTrue(w.replaced(m.state))
        m.state.channel_type = OPEN_FIELD
        now = time.monotonic()
        self.assertEqual(w.why(m.state, now), "")
        self.assertIn("돌아오지 않음", w.why(m.state, now + party.RESTORE_WAIT + 1))

    def test_leader_changed_inside_same_party_ends(self):
        """판 안이라도 같은 파티에서 파티장만 바뀌면 (파티장이 나감) 예전처럼 GRACE 뒤 끝낸다 — 판은 마저 하고 보상 화면에서."""
        m = mon(FRIEND, size=3)
        w = party.Watch("member", m.state)
        w.why(m.state)
        m.state.channel_type = ABYSS
        m.apply("party.leader", {"leader": ME})
        self.assertIn("파티장", w.why(m.state, later(m.state)))
        self.assertFalse(w.away)

    def test_replaced_when_number_unknown(self):
        """판 전 파티 번호를 몰라도 (판 도중에 켬) 파티가 없거나 우리 파티장이 아니면 바뀐 것."""
        m = PacketMonitor(None)
        m.state.char_id, m.state.channel_type = ME, ABYSS
        m.apply("party.info", {"party": 0, "leader": None})
        w = party.Watch("leader", m.state)
        self.assertTrue(w.replaced(m.state))
        m.apply("party.info", {"party": NEW, "leader": OTHER, "size": 4})
        self.assertTrue(w.replaced(m.state))
        m.apply("party.info", {"party": NEW, "leader": ME, "size": 4})
        self.assertFalse(w.replaced(m.state))

    def test_member_anchor_not_taken_inside(self):
        """파티원이 판 도중에 켰으면 판 안 파티장(모르는 사람일 수 있다)을 기억하지 않는다 — 밖에서 기억한다."""
        m = PacketMonitor(None)
        m.state.char_id, m.state.channel_type = ME, ABYSS
        m.apply("party.info", {"party": NEW, "leader": OTHER, "size": 4})
        w = party.Watch("member", m.state)
        self.assertEqual(w.why(m.state, later(m.state, 999)), "")
        self.assertIsNone(w.leader)
        m.state.channel_type = OPEN_FIELD
        m.apply("party.info", {"party": PARTY, "leader": FRIEND, "size": 3})
        self.assertEqual(w.why(m.state), "")
        self.assertEqual(w.leader, FRIEND)


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
        return r

    def test_member_leaving_keeps_going(self):
        m = mon(ME, size=3)
        r = self.rep("leader", m.state)
        self.assertFalse(r.done())
        m.apply("party.member_out", {})
        with mock.patch.object(party, "GRACE", 0.0):
            self.assertFalse(r.done())
        self.assertEqual(r.seen, [])

    def test_done_when_leader_leaves(self):
        m = mon(FRIEND)
        r = self.rep("member", m.state)
        self.assertFalse(r.done())
        m.apply("party.leader", {"leader": ME})
        m.apply("party.member_out", {})
        self.assertFalse(r.done())                 # 바뀐 직후엔 아직
        with mock.patch.object(party, "GRACE", 0.0):
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
