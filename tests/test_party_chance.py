"""가득 차지 않은 고정 파티 — 파티장은 우연한 만남을 켜고 들어가 빈자리를 채우고, 판이 끝나면 다시 하기 대신
'다른 던전 가기' → 목록에서 같은 어비스 → 입장 (사용자 11-22). 4명이면 예전처럼 준비 UI · 다시 하기."""
import time
import unittest
from types import SimpleNamespace as NS
from unittest import mock

from mabi.packet_monitor import PacketMonitor
from mabi.tasks import abyss

ME, PARTY = 0x174ADF700000, 0x1A1F0A712DA


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

    def test_resume_at_reward(self):
        """보상 화면에서 다시 켜도 지금 인원으로 — 3명이면 다른 던전 가기 (시작 전에 끝난 판은 판 수에 안 넣는다)."""
        r = rep(3, results=("clear",))
        en, other, ex = self.run_loop(r, at="reward")
        other.assert_called_once()
        r._again.assert_not_called()


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
