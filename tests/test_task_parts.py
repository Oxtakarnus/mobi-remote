"""여러 콘텐츠가 같이 쓰는 작은 부품 — 메뉴 열기·도착 기다리기·우연한 만남·버튼 기다리기."""
import unittest
from unittest import mock

from mabi.exceptions import NotSeen, StepTimeout
from mabi.tasks import arrival, entry, fight, press, ui_text


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def fake_bot(clock, **kw):
    bot = mock.Mock()
    bot.map_loading.return_value = False
    bot.sleep.side_effect = lambda *a: setattr(clock, "now", clock.now + (a[0] if a else 1))
    for k, v in kw.items():
        getattr(bot, k).return_value = v
    return bot


class WaitArrivalTest(unittest.TestCase):
    def run_wait(self, bot, clock, visible, **kw):
        with mock.patch.object(arrival.time, "monotonic", clock):
            return arrival.wait_arrival(bot, visible, 30, "shot", "못 감", **kw)

    def test_visible(self):
        c = Clock()
        bot = fake_bot(c)
        seen = iter([False, False, True])
        self.assertTrue(self.run_wait(bot, c, lambda: next(seen)))

    def test_stopped_without_window(self):
        c = Clock()
        bot = fake_bot(c, at_main=True, auto_traveling=False)
        self.assertFalse(self.run_wait(bot, c, lambda: False, still=3))
        self.assertEqual(bot.sleep.call_count, 2)  # 세 번째 멈춤에서 바로

    def test_timeout_raises(self):
        c = Clock()
        bot = fake_bot(c, at_main=False, fast_travel=False)
        with self.assertRaises(NotSeen):
            self.run_wait(bot, c, lambda: False, retry_fast=True)
        self.assertGreater(bot.fast_travel.call_count, 1)  # 될 때까지 다시 해 본다

    def test_fast_travel_once(self):
        c = Clock()
        bot = fake_bot(c, fast_travel=True)
        with self.assertRaises(NotSeen):
            self.run_wait(bot, c, lambda: False, retry_fast=True)
        bot.fast_travel.assert_called_once()


class OpenMenuTest(unittest.TestCase):
    def test_retries_until_item_shows(self):
        bot = mock.Mock()
        found = iter([None, (1700, 300), (1700, 300)])
        with mock.patch.object(ui_text, "find", lambda *a, **k: next(found)):
            ui_text.open_menu(bot, "abyss_menu", "메뉴의 어비스", "abyss")
        self.assertEqual([c.args for c in bot.key.call_args_list], [("esc",), ("esc",)])
        bot.clear_blockers.assert_called_once()
        bot.click.assert_called_once_with((1700, 300))

    def test_menu_open_clicks_at_once(self):
        bot = mock.Mock()
        with mock.patch.object(ui_text, "find", return_value=(1700, 300)):
            ui_text.open_menu(bot, "raid_menu", "메뉴의 레이드", "raid", menu_open=True)
        bot.key.assert_not_called()
        bot.click.assert_called_once_with((1700, 300))


class EntryPartsTest(unittest.TestCase):
    def test_chance_turned_on(self):  # 꺼져 있으면 한 번 누르고 다시 보지 않는다 (입장 결과로 안다)
        bot = mock.Mock()
        entry.chance_on(bot, entry.Entry("enter", (False, (900, 800))))
        bot.click.assert_called_once_with((900, 800))
        bot = mock.Mock()
        entry.chance_on(bot, entry.Entry("enter", (True, (900, 800))))
        bot.click.assert_not_called()

    def test_chance_missing_goes_on(self):
        """스위치가 없어도(능력치가 그 난이도 기준에 못 미침) 실패하지 않고 그대로 입장한다."""
        bot = mock.Mock()
        with mock.patch.object(entry, "read", return_value=entry.Entry("enter", None)):
            entry.chance_on(bot)
        bot.click.assert_not_called()

    def test_wait_button(self):
        bot = mock.Mock()
        got = iter(["", "", "move"])
        self.assertEqual(entry.wait_button(bot, lambda b: next(got)), "move")
        self.assertEqual(entry.wait_button(bot, lambda b: "", tries=2), "")


class AbyssEnterTest(unittest.TestCase):
    """어비스 입장은 누르고 결과(매칭·로딩 신호)로 확인 — 안 오면 창을 다시 맞춰 몇 번, 그래도면 까닭을 붙여 오류."""

    def run_enter(self, took):
        from mabi.tasks import abyss
        bot = mock.Mock()
        bot.wait_packet.side_effect = list(took)
        bot.run_limit_popup.return_value = False
        bot.snapshot.return_value.name = "s.png"
        with mock.patch.object(abyss, "enter_screen") as scr, mock.patch.object(abyss.ui_text, "click") as click, \
                mock.patch.object(abyss, "where", return_value="entry"), mock.patch.object(press, "find_texts", return_value=[]), \
                mock.patch.object(abyss.entry, "visible", return_value=True), \
                mock.patch.object(abyss.entry, "describe", return_value="버튼 enter · 우연한 만남 꺼짐"):
            abyss.enter(bot, "허상의 정박지", "매우 어려움2")
        click.assert_not_called()  # 입장하기 글자를 다시 읽지 않고 Space 를 누른다
        return scr, [c for c in bot.key.call_args_list if c.args == ("space",)]

    def test_took_first(self):
        scr, space = self.run_enter([True])
        self.assertEqual((scr.call_count, len(space)), (1, 1))

    def test_retry_then_took(self):
        scr, space = self.run_enter([False, True])
        self.assertEqual(len(space), 2)
        self.assertEqual(scr.call_args_list[1].kwargs["at"], "entry")  # 열린 창 그 자리부터 다시 맞춘다

    def test_unknown_packets_go_on(self):  # 패킷이 모르면 신호를 기다리지 않는다 (뒤의 매칭 기다림이 본다)
        self.assertEqual(len(self.run_enter([None])[1]), 1)

    def test_gives_up_with_reason(self):  # 인식 실패는 오류 (NotSeen — 큐가 한 번 더)
        with self.assertRaisesRegex(NotSeen, "우연한 만남 꺼짐"):
            self.run_enter([False] * 3)


class PressTest(unittest.TestCase):
    """누르고 결과로 확인 (press.until)."""

    def bot(self):
        bot = mock.Mock()
        bot.run_limit_popup.return_value = False
        bot.snapshot.return_value.name = "s.png"
        return bot

    def test_again_only_between_tries(self):
        pressed, again = mock.Mock(), mock.Mock()
        press.until(self.bot(), pressed, mock.Mock(side_effect=[False, False, True]), "x", again=again)
        self.assertEqual((pressed.call_count, again.call_count), (3, 2))

    def test_interrupt_redo_not_counted(self):
        """시작 신호를 기다리는 사이 끼어들기를 넘겼으면 그 시도는 세지 않고 다시 맞춰 누른다 (사용자 2026-11-17)."""
        bot = self.bot()
        bot.interrupt_n = 0
        pressed, again = mock.Mock(), mock.Mock()

        def started():
            if pressed.call_count == 1:
                bot.interrupt_n += 1  # 누른 사이 NPC 가 말을 걸어 넘김
                return False
            return True
        press.until(bot, pressed, started, "x", tries=1, again=again)
        self.assertEqual((pressed.call_count, again.call_count), (2, 1))

    def test_unknown_is_done(self):  # 모름(None)은 다시 누르지 않는다
        pressed = mock.Mock()
        press.until(self.bot(), pressed, lambda: None, "x")
        pressed.assert_called_once()

    def test_reason_reads_popup(self):
        bot = self.bot()
        with mock.patch.object(press, "find_texts", return_value=[("입장 불가", 0, 0)]), \
                self.assertRaisesRegex(NotSeen, "알림 '입장 불가' · 창 닫힘"):
            press.until(bot, mock.Mock(), lambda: False, "x", tries=2, why=lambda: "창 닫힘")

    def test_run_limit_popup_first(self):
        bot = self.bot()
        bot.run_limit_popup.return_value = True
        with self.assertRaisesRegex(NotSeen, "연속 실행 제한 창"):
            press.until(bot, mock.Mock(), lambda: False, "x", tries=1)

    def test_window_gone_is_unknown(self):  # 신호가 늦어도 창이 닫혔으면 다시 누르지 않는다 (매칭 취소 방지)
        bot = self.bot()
        bot.wait_packet.return_value = False
        self.assertIsNone(press.signal(bot, None, still=lambda: False)())
        self.assertIs(press.signal(bot, None, still=lambda: True)(), False)

    def test_not_seen_is_step_timeout(self):  # 큐는 StepTimeout 을 오류로 본다 (정리 → 맨 아래에서 한 번 더)
        self.assertTrue(issubclass(NotSeen, StepTimeout))


class FightTest(unittest.TestCase):
    """콘텐츠 안 전투 대기의 뼈대 (fight.Fight)."""

    def make(self, ends, seen_done=False, **kw):
        from mabi.monitor import detect as d
        c = Clock()
        bot = fake_bot(c, wait_packet=False, is_dead=False)
        bot.activity.return_value = {}
        ends = iter(ends)

        class F(fight.Fight):
            def packet_end(self):
                return next(ends)
        seen = d.Seen(d.MAIN, src="test")
        seen.done = "x" if seen_done else None
        with mock.patch.object(fight.time, "monotonic", c):
            f = F(bot, 60, **kw)
        return f, bot, c, seen

    def run_fight(self, f, c, seen):
        with mock.patch.object(fight.time, "monotonic", c), mock.patch.object(fight, "watch", return_value=seen):
            return f.run()

    def test_zero_is_a_result(self):  # 드릴의 '못 깸' 은 0
        f, bot, c, seen = self.make([None, 0])
        self.assertEqual(self.run_fight(f, c, seen), 0)

    def test_next_skips_round(self):
        tick = mock.Mock()
        f, bot, c, seen = self.make([fight.Fight.NEXT, "clear"], tick=tick)
        self.assertEqual(self.run_fight(f, c, seen), "clear")
        bot.activity.assert_not_called()
        tick.assert_not_called()

    def test_eat_and_tick_only_when_fighting(self):
        tick = mock.Mock()
        f, bot, c, seen = self.make([None, "clear"], tick=tick)
        self.run_fight(f, c, seen)
        bot.eat_if_hungry.assert_called_once()
        tick.assert_called_once_with({})
        tick.reset_mock()
        f, bot, c, seen = self.make([None, "clear"], seen_done=True, tick=tick)
        self.run_fight(f, c, seen)
        bot.eat_if_hungry.assert_not_called()
        tick.assert_not_called()

    def test_timeout(self):
        f, bot, c, seen = self.make(iter(lambda: None, 1))
        bot.wait_packet.side_effect = lambda *a, **k: setattr(c, "now", c.now + 3) or False
        self.assertEqual(self.run_fight(f, c, seen), "timeout")

    def test_dead_without_revive(self):
        f, bot, c, seen = self.make([None], revive=False)
        bot.is_dead.return_value = True
        self.assertEqual(self.run_fight(f, c, seen), "dead")


class BehindTest(unittest.TestCase):
    """게임을 뒤로 보내기 (Bot.to_back · behind_while)."""

    def fake(self):
        from mabi.bot import Bot
        b = mock.Mock(background=False, user_window=7)
        b.to_back = lambda window=None: Bot.to_back(b, window)
        return b, Bot

    def test_behind_while_resets_on_error(self):
        b, Bot = self.fake()
        with self.assertRaises(ValueError), Bot.behind_while(b, True):
            self.assertTrue(b.background)
            raise ValueError
        self.assertFalse(b.background)
        b.window.give_back.assert_called_once_with(7)

    def test_off_keeps_front(self):
        b, Bot = self.fake()
        with Bot.behind_while(b, False):
            self.assertFalse(b.background)
        b.window.give_back.assert_not_called()



class OneRuleTest(unittest.TestCase):
    """같은 판정은 한 함수로 (2026-11-16 점검)."""

    def test_stopped_needs_time_not_count(self):
        st = arrival.Stopped(grace=60)
        self.assertFalse(any(st.see(True) for _ in range(10)))  # 몇 번 연달아 봐도 시간이 안 지났으면 아직
        st = arrival.Stopped(grace=-1)
        self.assertTrue(st.see(True))
        self.assertFalse(st.see(False))  # 움직이면 처음부터

    def test_reward_button_either(self):
        from mabi.monitor import detect
        bot = mock.Mock()
        bot.ui = {"reward_exit": "ex", "dungeon_retry": "re"}
        self.assertEqual(detect.reward_button(bot, find=lambda n: "hit" if n == "re" else None), "hit")
        self.assertIsNone(detect.reward_button(bot, find=lambda n: None))

    def test_quest_tab_falls_back_to_text(self):
        from mabi.tasks import questwin
        bot = mock.Mock()
        bot.ui = {"questwin_tab_arbeit": "tab"}
        bot.wait.side_effect = StepTimeout("가려짐")
        with mock.patch.object(ui_text, "wait", return_value=(1700, 1030)) as by_text:
            self.assertEqual(questwin.open_tab(bot, "arbeit"), (1700, 1030))
        by_text.assert_called_once()
        bot.click.assert_called_once_with((1700, 1030))
        with mock.patch.object(ui_text, "wait", return_value=None):
            self.assertIsNone(questwin.open_tab(bot, "event"))  # 이벤트 탭이 없으면 None (부른 쪽이 따진다)

    def test_in_game_since(self):
        from mabi.session import GameSession
        s = mock.Mock()
        s.packets.status = "running"
        s.packets.state.loading = False
        s.packets.find.return_value = None
        s.state.query.return_value = None
        self.assertFalse(GameSession.in_game(s, since=5))   # 누른 뒤 맵에 들어온 적 없음 · CLI 도 모름
        s.packets.find.return_value = {"event": "channel.entering"}
        self.assertTrue(GameSession.in_game(s, since=5))


if __name__ == "__main__":
    unittest.main()
