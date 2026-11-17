"""지금 어디인가 (mabi.place) — 패킷이 맵을 알면 패킷, 모르면 CLI 로 짐작."""
import time
import unittest
from types import SimpleNamespace

from mabi import gamedata as gd
from mabi.session import GameSession
from mabi.packet_monitor import PacketMonitor
from mabi.place import ABYSS, DUNGEON, FIELD, FIELD_BOSS, RAID_LOBBY, on_map, place


class FakeBot:
    map_loading = GameSession.map_loading

    def __init__(self, act=None, name=""):
        self.packets = PacketMonitor(None)
        self.packets.status, self.packets.last_rx = "running", time.monotonic()
        self._act, self._name = act, name

    def activity(self, max_age=1.0):
        return self._act

    def environment(self, max_age=3.0):
        return {"ChannelDisplayName": self._name} if self._name else None


class PlaceTest(unittest.TestCase):
    def test_packet_knows_map(self):
        bot = FakeBot()
        bot.packets.apply("channel.entering", {"channel": 1, "channel_type": ABYSS, "channel_name": "허상의 정박지"})
        pl = place(bot)
        self.assertEqual((pl.src, pl.kind, pl.loading), ("packet", ABYSS, False))
        bot.packets.apply("channel.leaving", {})
        self.assertEqual((place(bot).loading, place(bot).kind), (True, None))

    def test_on_map_knows_or_says_unknown(self):
        """on_map — 맞음·다른 맵·모름. 모름(맵을 지움·로딩 중·감시 막 켬)을 다른 맵으로 읽지 않는다 (2026-11-16)."""
        bot = FakeBot()
        self.assertIsNone(on_map(bot, FIELD_BOSS))   # 감시를 켠 뒤 아직 맵을 옮긴 적 없음
        bot.packets.apply("channel.entering", {"channel": 2, "channel_type": FIELD_BOSS, "channel_name": ""})
        self.assertIs(on_map(bot, FIELD_BOSS), True)
        self.assertIs(on_map(bot, FIELD), False)
        bot.packets.forget("시험")                    # 흐름 끊김 → 맵 모름
        self.assertIsNone(on_map(bot, FIELD_BOSS))
        bot.packets.apply("channel.entering", {"channel": 3, "channel_type": FIELD, "channel_name": ""})
        self.assertIs(on_map(bot, FIELD_BOSS), False)
        bot.packets.apply("channel.leaving", {})
        self.assertIsNone(on_map(bot, FIELD_BOSS))   # 로딩 중

    def test_cli_guesses(self):
        act = {"Dungeon": {"State": "NotInDungeon"}, "Battlefield": {"IsInBattleField": False}}
        self.assertEqual(place(FakeBot(act, "허상의 정박지")).kind, ABYSS)
        self.assertEqual(place(FakeBot(act, gd.text("raid_ship"))).kind, RAID_LOBBY)
        self.assertIsNone(place(FakeBot(act, "던바튼")).kind)  # 마을은 짐작하지 않는다
        field = {"Dungeon": {"State": "NotInDungeon"}, "Battlefield": {"IsInBattleField": True}}
        self.assertEqual((place(FakeBot(field, "센마이 평원")).kind, place(FakeBot(field)).in_field), (FIELD, True))
        dun = {"Dungeon": {"State": "InProgress"}, "Battlefield": {"IsInBattleField": False}}
        self.assertEqual(place(FakeBot(dun, "마스 심층 던전 1층 2구역")).kind, DUNGEON)

    def test_nothing_known(self):
        pl = place(FakeBot())
        self.assertEqual((pl.loading, pl.kind, pl.src), (None, None, ""))


if __name__ == "__main__":
    unittest.main()
