"""가득 차지 않은 고정 파티 — 파티장은 우연한 만남을 켜고 들어가 빈자리를 채우고, 판이 끝나면 다시 하기 대신
'다른 던전 가기' → 목록에서 같은 어비스 → 입장 (사용자 11-22). 4명이면 예전처럼 준비 UI · 다시 하기."""
import time
import unittest
from types import SimpleNamespace as NS
from unittest import mock

from mabi.packet_monitor import PacketMonitor
from mabi.place import ABYSS, OPEN_FIELD
from mabi.tasks import abyss, party

ME, FRIEND, PARTY, NEW = 0x174ADF700000, 0x178AF7E00001, 0x1A1F0A712DA, 0x1A1F0A71FFF


def packets(size):
    m = PacketMonitor(None)
    m.state.char_id = ME
    if size is not None:
        m.apply("party.info", {"party": PARTY, "leader": ME, "size": size})
    return m, NS(ok=True, state=m.state)


def rep(size, role="leader", results=()):
    r = abyss.AbyssRepeat.__new__(abyss.AbyssRepeat)
    r.bot = mock.MagicMock()
    r.mon, r.bot.packets = packets(size)
    r.a = {"dungeon": "허상의 정박지", "difficulty": "매우 어려움2", "match_timeout": 60, "run_timeout": 600,
           "mode": "party", "party_role": role}
    r.runs, r.minutes, r.t0, r.on_event, r.behind, r.finish = len(results), 0, time.monotonic(), lambda e: None, False, False
    r.stat = {"clears": 0, "deaths": 0, "retries": 0, "revives": 0, "lefts": 0}
    it = iter(results)
    r.play_round = lambda play, step: next(it)
    r.recheck = lambda at: False
    r.yield_between = r.repair_between = lambda go_out: False
    r._again = mock.MagicMock()
    return r


class ChoiceTest(unittest.TestCase):
    def test_by_size(self):
        self.assertTrue(rep(2).party_chance())
        self.assertTrue(rep(3).party_chance())
        self.assertFalse(rep(4).party_chance())
        self.assertFalse(rep(None).party_chance())               # 인원을 모르면 예전처럼 파티끼리
        self.assertFalse(rep(3, role="member").party_chance())   # 파티원은 파티장을 따른다
        self.assertFalse(rep(3, role="").party_chance())

    def test_monitor_off_is_unknown(self):
        r = rep(3)
        r.bot.packets = NS(ok=False, state=r.mon.state)
        self.assertFalse(r.party_chance())


class LoopTest(unittest.TestCase):
    def run_loop(self, r, at="main"):
        with (mock.patch.object(abyss, "to_reward", return_value="reward"),
              mock.patch.object(abyss, "exit_reward") as ex,
              mock.patch.object(abyss, "enter") as en,
              mock.patch.object(abyss, "other_dungeon", return_value="list") as other,
              mock.patch.object(abyss, "inside", return_value=True),
              mock.patch.object(abyss, "entered_since", return_value=True)):
            r.loop(at)
        return en, other, ex

    def test_short_party_uses_chance_meeting(self):
        r = rep(3, results=["clear", "clear"])
        en, other, ex = self.run_loop(r)
        self.assertEqual([c.kwargs["party"] for c in en.call_args_list], [False, False])  # 우연한 만남 (준비 UI 없음)
        self.assertEqual([c.kwargs["party_chance"] for c in en.call_args_list], [True, True])
        self.assertEqual(en.call_args_list[1].kwargs["at"], "list")   # 다른 던전 가기 → 목록에서
        other.assert_called_once()
        r._again.assert_not_called()
        ex.assert_called_once()                                      # 마지막 판은 나가기

    def test_full_party_keeps_ready_flow(self):
        r = rep(4, results=["clear", "clear"])
        en, other, ex = self.run_loop(r)
        self.assertEqual([c.kwargs["party"] for c in en.call_args_list], [True])
        r._again.assert_called_once()
        other.assert_not_called()

    def test_unknown_then_known(self):
        """리모콘을 켠 뒤 파티 정보가 아직 없으면 첫 판은 파티끼리 — 어비스에 들어가 3명인 걸 알면 다음 판부터 우연한 만남."""
        r = rep(None, results=())
        r.runs = 2
        r.play_round = lambda play, step: (r.mon.apply("party.info", {"party": PARTY, "leader": ME, "size": 3}), "clear")[1]
        en, other, ex = self.run_loop(r)
        self.assertEqual([c.kwargs["party"] for c in en.call_args_list], [True, False])
        other.assert_called_once()
        r._again.assert_not_called()

    def test_member_joins_back_to_ready_flow(self):
        """3명으로 우연한 만남을 돌다 넷째가 들어오면 다음 입장은 파티끼리."""
        r = rep(3, results=())
        r.runs = 2
        r.play_round = lambda play, step: (r.mon.apply("party.member_add", {}), "clear")[1]
        en, other, ex = self.run_loop(r)
        self.assertEqual([c.kwargs["party"] for c in en.call_args_list], [False, True])
        other.assert_called_once()   # 이번 판은 우연한 만남이었다 — 다시 하기가 아니라 목록에서

    def test_member_leaves_keeps_going(self):
        """4명으로 돌다 파티원이 빠져도 카드를 끝내지 않고, 그 판이 끝난 뒤부터 우연한 만남으로 (사용자 11-22)."""
        r = rep(4, results=())
        r.runs = 2
        r.play_round = lambda play, step: (r.mon.apply("party.member_out", {}), "clear")[1]
        en, other, ex = self.run_loop(r)
        self.assertEqual([c.kwargs["party"] for c in en.call_args_list], [True, False])
        other.assert_called_once()
        r._again.assert_not_called()
        self.assertEqual(r.stat["clears"], 2)

    def test_leader_hand_over_ends_card(self):
        """파티장을 넘기면 (패킷 파티장 바뀜) 그 판을 마치고 보상 화면에서 나가 카드를 끝낸다 — 판 도중에 넘겨 보상
        화면에선 이미 GRACE 가 지났다."""
        r = rep(3, results=())
        r.runs = 3

        def play(play, step):
            r.mon.apply("party.leader", {"leader": FRIEND})
            r.mon.state.party_at -= party.GRACE + 1
            return "clear"
        r.play_round = play
        en, other, ex = self.run_loop(r)
        self.assertEqual(len(en.call_args_list), 1)
        other.assert_not_called()
        ex.assert_called_once()

    def test_resume_at_reward(self):
        """보상 화면에서 다시 켜도 지금 인원으로 — 3명이면 다른 던전 가기 (시작 전에 끝난 판은 판 수에 안 넣는다)."""
        r = rep(3, results=("clear",))
        en, other, ex = self.run_loop(r, at="reward")
        other.assert_called_once()
        r._again.assert_not_called()


class ChanceRestoreTest(unittest.TestCase):
    """우연한 만남 판에 게임이 파티를 풀었다가 어비스 밖에서 다시 만들면 (사용자 11-23 테스터 제보) 카드를 끝내지 않고,
    보상 화면에서 나가 파티가 다시 모이면 메뉴에서 다시 들어간다. 파티가 그대로면 예전처럼 다른 던전 가기."""

    def dissolve(self, m, keep=False):
        """매칭 → (keep 이 아니면 게임이 파티를 풂) → 어비스 맵."""
        m.apply("abyss.matching_update", {"state": 2})
        if not keep:
            m.apply("party.info", {"party": 0, "leader": None})
        m.state.abyss_matching, m.state.channel_type = 0, ABYSS

    def restore(self, m, leader, size=3):
        """보상 화면에서 나가 마을 — 파티가 새 번호로 다시 생김."""
        m.state.channel_type = OPEN_FIELD
        m.apply("party.info", {"party": NEW, "leader": leader, "size": size})

    def run_loop(self, r, enter=None, wait_ready=None, leader=ME, size=3):
        m = r.mon
        m.state.channel_type = OPEN_FIELD
        with (mock.patch.object(abyss, "to_reward", return_value="reward"),
              mock.patch.object(abyss, "exit_reward", side_effect=lambda bot: self.restore(m, leader, size)) as ex,
              mock.patch.object(abyss, "leave", return_value=True),
              mock.patch.object(abyss, "enter", side_effect=enter) as en,
              mock.patch.object(abyss, "other_dungeon", return_value="list") as other,
              mock.patch.object(abyss.party_mod, "wait_ready", side_effect=wait_ready) as wr,
              mock.patch.object(abyss, "inside", return_value=True),
              mock.patch.object(abyss, "entered_since", return_value=True)):
            r.loop("main")
        return en, other, ex, wr

    def test_leader_waits_and_enters_from_menu(self):
        r = rep(3, results=("clear", "clear"))
        en, other, ex, _ = self.run_loop(r, enter=lambda *a, **kw: self.dissolve(r.mon))
        self.assertEqual(r.stat["clears"], 2)
        other.assert_not_called()                     # 다른 던전 가기 대신 나가서
        self.assertEqual(ex.call_count, 2)            # 판 뒤 나가기 + 마지막 판 뒤 나가기
        self.assertEqual([c.kwargs["at"] for c in en.call_args_list], ["main", ""])   # 두 번째는 메뉴에서
        self.assertEqual([c.kwargs["party_chance"] for c in en.call_args_list], [True, True])

    def test_leader_party_kept_uses_other_dungeon(self):
        r = rep(3, results=("clear", "clear"))
        en, other, ex, _ = self.run_loop(r, enter=lambda *a, **kw: self.dissolve(r.mon, keep=True))
        other.assert_called_once()
        ex.assert_called_once()                       # 마지막 판 뒤에만
        self.assertEqual(r.stat["clears"], 2)

    def test_member_leaves_after_leader_then_waits(self):
        r = rep(3, role="member", results=("clear", "clear"))
        r.mon.apply("party.info", {"party": PARTY, "leader": FRIEND, "size": 3})

        def leader_starts(bot, timeout, abort=None):   # 파티장이 우연한 만남으로 입장 — 파티원은 매칭에 끌려 들어간다
            self.assertFalse(abort())
            self.dissolve(r.mon)
            return True
        en, other, ex, wr = self.run_loop(r, wait_ready=leader_starts, leader=FRIEND)
        self.assertEqual(r.stat["clears"], 2)
        en.assert_not_called()
        self.assertEqual(wr.call_count, 2)            # 나가서 돌아온 파티로 파티장의 다음 입장을 기다림
        self.assertEqual(ex.call_count, 2)
        r.bot.sleep.assert_any_call(*abyss.MEMBER_DELAY)   # 파티장이 먼저 나가게

    def test_member_without_matching_signal(self):
        """파티원이 파티장의 매칭 신호를 못 받아도 판 안에서 파티가 바뀐 걸로 알고 같은 길로 간다."""
        r = rep(3, role="member", results=("clear", "clear"))
        r.mon.apply("party.info", {"party": PARTY, "leader": FRIEND, "size": 3})

        def leader_starts(bot, timeout, abort=None):
            r.mon.apply("party.info", {"party": 0, "leader": None})
            r.mon.state.channel_type = ABYSS
            return True
        en, other, ex, wr = self.run_loop(r, wait_ready=leader_starts, leader=FRIEND)
        self.assertEqual(r.stat["clears"], 2)
        self.assertEqual(wr.call_count, 2)
        self.assertEqual(ex.call_count, 2)
        r.bot.sleep.assert_any_call(*abyss.MEMBER_DELAY)

    def test_leader_dead_waits_for_party(self):
        """우연한 만남 판에서 쓰러져 먼저 나오면 파티가 돌아올 때까지 다음 입장을 미룬다 (파티원을 두고 가지 않게)."""
        r = rep(3, results=("dead", "clear"))
        r.runs = 1
        seen = []

        def go(*a, **kw):
            seen.append(r.mon.state.party_id)
            self.dissolve(r.mon)
        r.bot.sleep.side_effect = lambda *a: self.restore(r.mon, ME)   # 기다리는 사이 파티원이 나와 파티가 돌아옴
        en, other, ex, _ = self.run_loop(r, enter=go)
        self.assertEqual(seen, [PARTY, NEW])     # 돌아온 파티로 다시 입장
        self.assertEqual(r.stat["clears"], 1)

    def test_leader_enters_with_fewer_after_gather_wait(self):
        """파티는 돌아왔는데 판 전보다 적으면 GATHER_WAIT 뒤 지금 인원으로 들어간다 (파티원이 빠짐 — 계속)."""
        r = rep(3, results=("clear", "clear"))
        with mock.patch.object(party, "GATHER_WAIT", 0.0):
            en, other, ex, _ = self.run_loop(r, enter=lambda *a, **kw: self.dissolve(r.mon), size=2)
        self.assertEqual(r.stat["clears"], 2)
        self.assertEqual(en.call_count, 2)

    def test_member_party_kept_waits_at_reward(self):
        r = rep(3, role="member", results=("clear", "clear"))
        r.mon.apply("party.info", {"party": PARTY, "leader": FRIEND, "size": 3})

        def leader_starts(bot, timeout, abort=None):
            self.dissolve(r.mon, keep=True)
            return True
        en, other, ex, wr = self.run_loop(r, wait_ready=leader_starts, leader=FRIEND)
        self.assertEqual(wr.call_count, 2)
        ex.assert_called_once()                       # 보상 화면에서 파티장의 다음 입장을 기다림 — 나가지 않음


class EnterTest(unittest.TestCase):
    """입장하기 — 우연한 만남 파티는 매칭 신호로, 스위치가 없어 '도전하시겠습니까?' 가 뜨면 도전하기 (예전 파티 방식)."""

    def push(self, **kw):
        bot = mock.MagicMock()
        with (mock.patch.object(abyss, "enter_screen"), mock.patch.object(abyss.party_mod, "confirm") as cf,
              mock.patch.object(abyss.press, "signal") as sig, mock.patch.object(abyss.press, "until") as until):
            abyss.enter(bot, "허상의 정박지", **kw)
            until.call_args.args[1]()   # push
        return cf, sig.call_args.args[1]

    def test_chance_party_accepts_both(self):
        cf, ok = self.push(party_chance=True)
        cf.assert_called_once()
        self.assertTrue(ok(NS(matching=True, loading=False, party_marks={})))
        self.assertTrue(ok(NS(matching=False, loading=False, party_marks={ME: 0x0B})))
        self.assertFalse(ok(NS(matching=False, loading=False, party_marks={})))

    def test_chance_meeting_alone_no_confirm(self):
        cf, ok = self.push()
        cf.assert_not_called()
        self.assertFalse(ok(NS(matching=False, loading=False, party_marks={ME: 1})))

    def test_confirm_skips_when_matching(self):
        bot = mock.MagicMock()
        bot.packets.ok = True
        bot.packets.state = NS(party_marks={}, loading=False, matching=True)
        with mock.patch.object(abyss.party_mod.ui_text, "find") as find:
            self.assertFalse(abyss.party_mod.confirm(bot))
        find.assert_not_called()


class OtherDungeonTest(unittest.TestCase):
    def test_click_then_list(self):
        bot = mock.MagicMock()
        bot.map_loading.return_value = False

        def find(b, want, region=None, exact=True):
            if want == "다른던전가기":
                return (1165, 1010)
            return (1300, 140) if bot.click.called else None

        with mock.patch.object(abyss.ui_text, "find", side_effect=find), \
                mock.patch.object(abyss.entry, "visible", return_value=False):
            self.assertEqual(abyss.other_dungeon(bot, "허상의 정박지"), "list")
        bot.click.assert_called_once_with((1165, 1010))
        self.assertFalse(bot.background)

    def test_no_button_goes_out(self):
        bot = mock.MagicMock()
        with mock.patch.object(abyss.ui_text, "find", return_value=None), \
                mock.patch.object(abyss.d, "reward_button", return_value=True), \
                mock.patch.object(abyss, "exit_reward") as ex:
            self.assertEqual(abyss.other_dungeon(bot, "허상의 정박지"), "")
        ex.assert_called_once()
        bot.click.assert_not_called()


if __name__ == "__main__":
    unittest.main()
