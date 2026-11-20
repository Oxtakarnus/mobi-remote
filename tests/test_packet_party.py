"""고정 파티 패킷 — 파티장 읽기, 입장 진행 상태(파티원 목록·준비), 역할 판단 (녹화 party-1120b 모양)."""
import logging
import struct
import time
import unittest
from unittest import mock

from mabi.packet_monitor import PacketMonitor
from mabi.packet_monitor.monitor import party_leader
from mabi.packet_table import _read
from mabi.tasks import party

ME, FRIEND, PARTY = 0x174ADF700000, 0x178AF7E00001, 0x1A1F0A712DA


def info_body(name: str, leader: int | None) -> bytes:
    """파티 정보 앞부분: [0:8] 파티 번호 · [27:31] 이름 길이 · 이름 · 12바이트 뒤 파티장."""
    raw = name.encode("utf-16le")
    head = struct.pack("<Q", PARTY if name else 0) + bytes(19) + struct.pack("<I", len(raw)) + raw + bytes(12)
    return head + struct.pack("<Q", 0xFFFFFFFFFFFFFFFF if leader is None else leader) + bytes(30)


def play_body(marks: dict) -> bytes:
    """단계 2 입장 진행: [14] 단계 · [35:39] 인원 + (번호 u64 · 상태 u32)."""
    body = bytearray(35)
    body[14] = 2
    body += struct.pack("<I", len(marks))
    for k, v in marks.items():
        body += struct.pack("<QI", k, v)
    return bytes(body + bytes(5))


class PartyTest(unittest.TestCase):
    def setUp(self):
        self.m = PacketMonitor(None)
        self.m.state.char_id = ME

    def test_leader_after_name(self):
        self.assertEqual(party_leader(info_body("파티 이름 열 글자짜리", ME)), ME)
        self.assertIsNone(party_leader(info_body("", None)))

    def test_list_fields(self):
        b = play_body({ME: 1, FRIEND: 0x0B})
        self.assertEqual(_read(b, 35, "u64list", 12, 0), [ME, FRIEND])
        self.assertEqual(_read(b, 35, "u32list", 12, 8), [1, 0x0B])

    def test_role(self):
        s = self.m.state
        self.assertIsNone(s.party_role())
        self.m.apply("party.info", {"party": PARTY, "leader": FRIEND})
        self.assertEqual(s.party_role(), "member")
        self.m.apply("party.leader", {"leader": ME})
        self.assertEqual(s.party_role(), "leader")
        self.m.apply("party.info", {"party": 0, "leader": None})
        self.assertEqual(s.party_role(), "")

    def test_member_ready_flow(self):
        s = self.m.state
        self.m.apply("party.info", {"party": PARTY, "leader": FRIEND})
        self.m.apply("party.play", {"stage": 0, "ids": [], "marks": []})
        self.assertIsNone(s.party_mark())
        self.m.apply("party.play", {"stage": 2, "ids": [ME, FRIEND], "marks": [1, 0x0B]})
        self.assertEqual(s.party_mark(), 1)
        self.m.apply("party.play", {"stage": 0, "ids": [], "marks": []})  # 같은 때 오는 단계 0 은 무시
        self.assertEqual(s.party_mark(), 1)
        self.m.apply("party.ready_ok", {})
        self.assertEqual(s.party_mark(), s.PARTY_READY)
        self.m.apply("party.enter_end", {"code": 3})
        self.assertIsNone(s.party_mark())
        self.assertEqual(s.party_end, 3)


class FakeBot:
    """준비 UI: 처음 두 번 보면 아직 없음 → 세 번째부터 내 상태 1, Space 를 누르면 준비 끝."""
    def __init__(self, mon):
        self.packets, self.keys, self.looks, self.input_mark = mon, [], 0, 0
        self.log = logging.getLogger("test")

    def sleep(self, *a):
        self.looks += 1
        if self.looks == 2:
            self.packets.apply("party.play", {"stage": 2, "ids": [ME, FRIEND], "marks": [1, 0x0B]})

    def key(self, k):
        self.keys.append(k)
        self.packets.apply("party.ready_ok", {})

    def wait_packet(self, pred, timeout, since=0):
        return pred(self.packets.state)


class WaitReadyTest(unittest.TestCase):
    def test_presses_space_once_when_ready_ui_opens(self):
        m = PacketMonitor(None)
        m.status, m.last_rx = "running", time.monotonic()
        m.state.char_id = ME
        m.apply("party.info", {"party": PARTY, "leader": FRIEND})
        bot = FakeBot(m)
        with mock.patch.object(party, "ready_button", return_value=False):
            party.wait_ready(bot, 60)
        self.assertEqual(bot.keys, ["space"])
        self.assertEqual(m.state.party_mark(), m.state.PARTY_READY)


if __name__ == "__main__":
    unittest.main()
