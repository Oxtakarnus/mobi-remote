"""보스전 궁극기·팔라딘 변신 (mabi.tasks.boss_skills) — 패킷 상태와 캐릭터별 설정으로 누를지 가르기."""
import logging
import time
import unittest
from unittest import mock

from mabi.packet_monitor import PacketMonitor
from mabi.place import DRILL
from mabi.tasks.abyss import AbyssRepeat
from mabi.tasks.boss_skills import KINDS, BossSkills
from mabi.tasks.raid import RaidRepeat

ABYSS = "InstanceAbyssDungeon"


class FakeBot:
    def __init__(self):
        self.packets = PacketMonitor(None)
        self.packets.status = "running"
        self.packets.last_rx = time.monotonic()
        self.cfg = {"game": {"ultimate_key": "6", "paladin_key": "f5"},
                    "boss_skills": {"ultimate_slots": [1], "paladin_slots": [2]}}
        self.log = logging.getLogger("test")
        self.keys = []
        self.packets.state.me = 14000001

    def key(self, k):
        self.keys.append(k)

    def enter(self, kind):
        self.packets.apply("channel.leaving", {})
        self.packets.apply("channel.entering", {"channel": 1, "channel_type": kind, "channel_name": ""})

    def boss(self):  # 모닥불 → 보스방 → 보스 등장 연출 (2026-10-30 실측)
        self.packets.apply("abyss.campfire", {})
        self.packets.apply("cutscene.play", {})
        self.packets.apply("cutscene.end", {})

    def transfigure(self):  # 변신 패킷 (시작·끝에 한 번씩, [0:4] 내 캐릭터 번호)
        self.packets.apply("transfigure.current", {"actor": self.packets.state.me})

    def gauge(self, v):  # abyss1 처럼 두 게이지가 같은 값으로 오르고 궁극기는 300 에서 멈춘다
        self.packets.apply("ultimate.resource", {"ult_max": 300.0, "ult": min(v, 300.0), "pal_max": 500.0, "pal": v})


def abyss_fight(s):
    return AbyssRepeat.boss_fight(None, s)


class BossSkillsTest(unittest.TestCase):
    def test_abyss_boss_is_after_campfire_scene(self):
        bot = FakeBot()
        bot.enter(ABYSS)
        sk = BossSkills(bot, True, True, abyss_fight, only=KINDS)  # 보스에서만
        bot.gauge(500)
        self.assertFalse(sk.tick({"IsInCombat": True}))  # 모닥불 전
        bot.packets.apply("abyss.campfire", {})
        self.assertFalse(sk.tick({"IsInCombat": True}))  # 모닥불 뒤 보스방 앞 잡몹 — 아직 (16:49:27 에 일찍 변신했다)
        bot.packets.apply("cutscene.play", {})
        self.assertFalse(sk.tick({"IsInCombat": True}))  # 보스 등장 연출 중
        bot.packets.apply("cutscene.end", {})
        self.assertFalse(sk.tick({"IsInCombat": False}))
        self.assertTrue(sk.tick({"IsInCombat": True}))
        self.assertEqual(bot.keys, ["f5"])  # 팔라딘 먼저

    def test_weekly_entry_scene_is_not_boss(self):
        bot = FakeBot()
        bot.enter(ABYSS)
        bot.packets.apply("cutscene.play", {})  # 주마다 첫 입장 연출 (모닥불 전)
        bot.packets.apply("cutscene.end", {})
        self.assertFalse(abyss_fight(bot.packets.state))

    def test_started_mid_run(self):
        bot = FakeBot()  # 판 도중에 리모콘을 켬 — 맵 진입·모닥불을 못 봤다
        bot.packets.apply("cutscene.play", {})
        bot.packets.apply("cutscene.end", {})
        self.assertTrue(abyss_fight(bot.packets.state))

    def test_no_ultimate_while_transformed(self):
        bot = FakeBot()
        bot.enter(ABYSS)
        bot.boss()
        sk = BossSkills(bot, True, True, abyss_fight)
        bot.gauge(500)
        self.assertTrue(sk.tick({"IsInCombat": True}))
        self.assertFalse(sk.tick({"IsInCombat": True}))  # 시작 패킷 전 — 변신 중으로 본다
        bot.transfigure()  # 변신 시작
        bot.gauge(300)
        self.assertFalse(sk.tick({"IsInCombat": True}))
        self.assertEqual(bot.keys, ["f5"])  # 변신 중엔 6 이 변신 해제
        bot.transfigure()  # 20초 뒤 끝
        self.assertTrue(sk.tick({"IsInCombat": True}))
        self.assertEqual(bot.keys, ["f5", "6"])  # 끝나면 궁극기 (예전엔 패킷 앞 번호를 변신 번호로 읽어 판 내내 막혔다)
        self.assertFalse(sk.tick({"IsInCombat": True}))  # 방금 눌렀다 — RETRY 동안 안 누른다

    def test_no_ultimate_when_start_packet_missing(self):
        bot = FakeBot()  # 2026-10-30 17:33: 변신은 됐는데 시작 패킷이 안 와 7초 뒤 6 으로 변신이 풀림
        bot.enter(ABYSS)
        bot.boss()
        sk = BossSkills(bot, True, True, abyss_fight)
        bot.gauge(500)
        self.assertTrue(sk.tick({"IsInCombat": True}))
        sk.pressed["팔라딘 변신"] -= 10
        self.assertFalse(sk.tick({"IsInCombat": True}))
        sk.pressed["팔라딘 변신"] -= 14  # 변신 시간이 지남
        bot.packets.apply("ultimate.resource", {"ult_max": 300.0, "ult": 300.0, "pal_max": 500.0, "pal": 0.0})
        self.assertTrue(sk.tick({"IsInCombat": True}))
        self.assertEqual(bot.keys, ["f5", "6"])  # 팔라딘 게이지가 비었다 = 변신했다 → F5 다시 안 누르고 궁극기
        sk.pressed["궁극기"] -= 9
        bot.packets.apply("ultimate.resource", {"ult_max": 300.0, "ult": 0.0, "pal_max": 500.0, "pal": 0.0})
        self.assertFalse(sk.tick({"IsInCombat": True}))  # 궁극기만 0 — 따로 쌓인다

    def test_end_packet_missed(self):
        bot = FakeBot()
        bot.enter(ABYSS)
        bot.boss()
        sk = BossSkills(bot, True, False, abyss_fight)
        bot.gauge(300)
        bot.transfigure()  # 사람이 직접 변신
        self.assertFalse(sk.tick({"IsInCombat": True}))
        bot.packets.state.transform_start -= 24  # 끝 패킷을 놓쳤다 — 변신 시간으로 끊는다
        self.assertTrue(sk.tick({"IsInCombat": True}))
        self.assertEqual(bot.keys, ["6"])

    def test_transform_counts_when_me_unknown(self):
        bot = FakeBot()
        bot.packets.state.me = None  # 판 도중에 리모콘을 켬 — 내 등장 메시지를 못 봤다
        bot.packets.apply("transfigure.current", {"actor": 123})
        self.assertTrue(bot.packets.state.transform_start)

    def test_party_member_transform_ignored(self):
        bot = FakeBot()
        bot.enter(ABYSS)
        bot.packets.apply("transfigure.current", {"actor": 123})
        self.assertEqual(bot.packets.state.transform_start, 0.0)

    def test_paladin_once_per_dungeon_and_gauge_reset(self):
        bot = FakeBot()
        bot.enter(ABYSS)
        bot.boss()
        sk = BossSkills(bot, False, True, abyss_fight)
        bot.gauge(500)
        self.assertTrue(sk.tick({"IsInCombat": True}))
        bot.transfigure()
        bot.transfigure()
        sk.pressed["팔라딘 변신"] -= 30
        bot.gauge(500)  # 같은 던전에서 다시 차도 변신은 한 번뿐
        self.assertFalse(sk.tick({"IsInCombat": True}))
        self.assertEqual(bot.keys, ["f5"])
        bot.enter(ABYSS)  # 다시 하기 — 게이지가 처음으로
        self.assertEqual((bot.packets.state.ult, bot.packets.state.pal), (0.0, 0.0))
        bot.boss()
        bot.gauge(500)
        self.assertTrue(sk.tick({"IsInCombat": True}))  # 새 던전에선 다시 한 번
        self.assertEqual(bot.keys, ["f5", "f5"])

    def test_paladin_key_missed_retries_then_gives_up(self):
        bot = FakeBot()
        bot.enter(ABYSS)
        bot.boss()
        sk = BossSkills(bot, False, True, abyss_fight)
        bot.gauge(500)
        self.assertTrue(sk.tick({"IsInCombat": True}))  # F5 — 변신 패킷도 게이지 변화도 없음
        sk.pressed["팔라딘 변신"] -= 10
        self.assertFalse(sk.tick({"IsInCombat": True}))  # 변신이 됐는데 신호만 늦을 수 있다 — 변신 시간 안엔 다시 안 누른다
        for _ in range(2):
            sk.pressed["팔라딘 변신"] -= 24
            self.assertTrue(sk.tick({"IsInCombat": True}))
        sk.pressed["팔라딘 변신"] -= 24
        self.assertFalse(sk.tick({"IsInCombat": True}))  # 세 번 안 됨 → 이 맵에선 포기
        self.assertEqual(bot.keys, ["f5", "f5", "f5"])
        bot.enter(ABYSS)  # 다음 판엔 다시
        bot.boss()
        bot.gauge(500)
        self.assertTrue(sk.tick({"IsInCombat": True}))
        self.assertEqual(bot.keys[-1], "f5")

    def test_gauge_not_full(self):
        bot = FakeBot()
        bot.enter(ABYSS)
        bot.boss()
        sk = BossSkills(bot, True, True, abyss_fight)
        bot.gauge(350)
        self.assertTrue(sk.tick({"IsInCombat": True}))
        self.assertEqual(bot.keys, ["6"])  # 궁극기는 300 에서 참

    def test_no_paladin_here_or_cutscene_or_new_map(self):
        bot = FakeBot()
        bot.enter(ABYSS)
        bot.boss()
        bot.gauge(500)
        bot.packets.apply("ultimate.can_paladin", {"on": False})
        sk = BossSkills(bot, False, True, abyss_fight, only=("paladin",))
        self.assertFalse(sk.tick({"IsInCombat": True}))
        bot.packets.apply("ultimate.can_paladin", {"on": True})
        bot.packets.apply("cutscene.play", {})
        self.assertFalse(sk.tick({"IsInCombat": True}))
        bot.packets.apply("cutscene.end", {})
        bot.enter(ABYSS)  # 다음 판 — 보스 연출 표시는 지워진다
        bot.gauge(500)
        self.assertFalse(sk.tick({"IsInCombat": True}))
        self.assertEqual(bot.keys, [])

    def test_raid_boss_signal(self):
        bot = FakeBot()
        bot.enter("InstanceRaid")
        bot.packets.apply("abyss.campfire", {})  # 레이드는 맵 진입 때도 모닥불이 온다 — 그걸로 보지 않는다
        bot.gauge(300)
        sk = BossSkills(bot, True, False, lambda s: RaidRepeat.boss_fight(None, s), only=("ultimate",))
        self.assertFalse(sk.tick({"IsInCombat": True}))
        bot.packets.apply("raid.boss_begin", {})
        self.assertTrue(sk.tick({"IsInCombat": True}))
        self.assertEqual(bot.keys, ["6"])

    def test_anywhere_by_default(self):
        """'보스에서만' 을 안 켰으면 보스전이 아니어도 전투 중 게이지가 차면 쓴다 (사용자 11-19)."""
        bot = FakeBot()
        bot.enter(ABYSS)
        sk = BossSkills(bot, True, True, abyss_fight)
        bot.gauge(500)
        self.assertFalse(abyss_fight(bot.packets.state))  # 모닥불 전 잡몹
        self.assertFalse(sk.tick({"IsInCombat": False}))  # 전투 중이 아니면 안 씀
        self.assertTrue(sk.tick({"IsInCombat": True}))
        self.assertEqual(bot.keys, ["f5"])

    def test_boss_only_per_skill(self):
        bot = FakeBot()
        bot.enter(ABYSS)
        sk = BossSkills(bot, True, True, abyss_fight, only=("paladin",))  # 팔라딘만 보스에서만
        bot.gauge(500)
        self.assertTrue(sk.tick({"IsInCombat": True}))
        self.assertEqual(bot.keys, ["6"])  # 잡몹 때 궁극기만
        sk.pressed["궁극기"] -= 9
        bot.packets.apply("ultimate.resource", {"ult_max": 300.0, "ult": 0.0, "pal_max": 500.0, "pal": 500.0})
        self.assertFalse(sk.tick({"IsInCombat": True}))  # 팔라딘은 보스까지 아낀다
        bot.boss()
        self.assertTrue(sk.tick({"IsInCombat": True}))
        self.assertEqual(bot.keys, ["6", "f5"])

    def test_inside_guard(self):
        """드릴·필드 보스는 그 맵 안에서만 — '보스에서만' 을 꺼도."""
        bot = FakeBot()
        bot.enter(DRILL)
        here = lambda s: s.channel_type == DRILL  # noqa: E731
        sk = BossSkills(bot, True, False, here, inside=here)
        bot.gauge(300)
        self.assertTrue(sk.tick({"IsInCombat": True}))
        bot.enter("Field")
        sk.pressed.clear()
        bot.gauge(300)
        self.assertFalse(sk.tick({"IsInCombat": True}))
        self.assertEqual(bot.keys, ["6"])

    def test_boss_only_from_settings(self):
        bot = FakeBot()
        bot.cfg["boss_skills"]["paladin_boss_only"] = True
        two = BossSkills.for_character(bot, bot.cfg, 2, abyss_fight)
        one = BossSkills.for_character(bot, bot.cfg, 1, abyss_fight)
        self.assertEqual(two.describe(), "팔라딘 변신 (보스에서만)")
        self.assertEqual(one.describe(), "궁극기")

    def test_boss_only_per_character(self):
        """'보스에서만' 은 기본값을 따르되 캐릭터 탭에서 캐릭터별로 켜고 끈다."""
        from mabi.tasks import boss_skills
        bot = FakeBot()
        b = bot.cfg["boss_skills"]
        b["paladin_boss_only"] = True
        b["paladin_boss_any_slots"] = [2]   # 2번은 기본값(보스에서만)과 달리 아무 때나
        b["ultimate_boss_only_slots"] = [1]  # 1번은 궁극기를 보스에서만
        self.assertEqual(BossSkills.for_character(bot, bot.cfg, 2, abyss_fight).describe(), "팔라딘 변신")
        self.assertEqual(BossSkills.for_character(bot, bot.cfg, 1, abyss_fight).describe(), "궁극기 (보스에서만)")
        self.assertEqual(boss_skills.boss_only(b, 3), {"paladin"})
        self.assertEqual(boss_skills.boss_only(b), {"paladin"})

    def test_per_character(self):
        bot = FakeBot()
        one = BossSkills.for_character(bot, bot.cfg, 1, abyss_fight)
        two = BossSkills.for_character(bot, bot.cfg, 2, abyss_fight)
        nobody = BossSkills.for_character(bot, bot.cfg, None, abyss_fight)
        self.assertEqual(one.describe(), "궁극기")
        self.assertEqual(two.describe(), "팔라딘 변신")
        self.assertFalse(nobody.enabled)

    def test_repeat_round_passes_tick(self):
        rep = mock.Mock()
        rep.stat = {"clears": 0, "deaths": 0, "retries": 0, "revives": 0}
        rep.a = {"run_timeout": 60}
        from mabi.tasks.repeat import Repeat
        play = mock.Mock(return_value="clear")
        self.assertEqual(Repeat.play_round(rep, play, "abyss_play"), "clear")
        self.assertIs(play.call_args.kwargs["tick"], rep.skills.tick)


class DefaultTest(unittest.TestCase):
    """기본값(어비스·레이드 탭)을 따르고 캐릭터 탭에서 따로 켜거나 끈 캐릭터만 다르게 (boss_skills.on_for)."""

    def test_default_and_overrides(self):
        from mabi.tasks.boss_skills import on_for
        b = {"ultimate": True, "paladin": False, "ultimate_off_slots": [2], "paladin_slots": [3]}
        self.assertTrue(on_for(b, "ultimate", 1))
        self.assertFalse(on_for(b, "ultimate", 2))
        self.assertTrue(on_for(b, "ultimate", None))   # 캐릭터를 모르면 기본값
        self.assertFalse(on_for(b, "paladin", 1))
        self.assertTrue(on_for(b, "paladin", 3))
        self.assertFalse(on_for({"ultimate_slots": [1]}, "ultimate", 2))  # 예전 설정(기본값 없음) = 켠 캐릭터만
        self.assertTrue(on_for({"ultimate_slots": [1]}, "ultimate", 1))

    def test_settings_api_boss_only(self):
        """어비스·레이드 탭 저장·읽기 — '보스에서만' 은 켠 기술 목록으로 주고받는다."""
        from gui_app import daily_api
        api = daily_api.DailyApi.__new__(daily_api.DailyApi)
        doc = {"boss_skills": {"ultimate": True, "paladin": True, "paladin_boss_only": True}}
        api._doc = lambda: doc
        api.paths = mock.Mock()
        with mock.patch.object(daily_api.prof, "chars", return_value=[]):
            self.assertEqual(api.daily_bossSettings()["boss_only"], ["paladin"])
        with mock.patch.object(daily_api.userconfig, "save"):
            self.assertEqual(api.daily_saveBoss({"ultimate": True, "paladin": True, "boss_only": ["ultimate"]}), {"ok": True})
        self.assertEqual((doc["boss_skills"]["ultimate_boss_only"], doc["boss_skills"]["paladin_boss_only"]), (True, False))


if __name__ == "__main__":
    unittest.main()
