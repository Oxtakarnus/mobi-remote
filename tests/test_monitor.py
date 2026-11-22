"""점검자(mabi.monitor) — 헛돌기 방지, 모르는 상황, 동작 확인, 메뉴를 다루는 일과 기다리는 중의 정리의 차이."""
import contextlib
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from mabi import monitor
from mabi.bot import Marks
from mabi.monitor import core, detect as d, handlers
from mabi.monitor.detect import Seen
from mabi.packet_monitor import PacketState
from mabi.tasks import dialogue
import tomllib
from pathlib import Path as _P
MONITOR = tomllib.loads((_P(__file__).resolve().parent.parent / "config.default.toml").read_text(encoding="utf-8"))["monitor"]


def fake_bot():
    b = mock.Mock()
    b.cfg = {"arbeit": {"dialog_next_xy": [1800, 45], "report": "report", "accept": "accept", "dialog_log": "dialog_log"},
             "monitor": MONITOR}
    b.shot_dir = None
    b.snapshot.return_value.name = "shot.png"
    b.background = False
    b.packets.ok = False
    b.is_dead.return_value = False  # 쓰러짐은 Bot.is_dead 하나로 (detect.look 도)
    b.marks = Marks()
    b.no_interrupt = contextlib.nullcontext
    return b


def frame(v=0):
    return np.full((100, 100, 3), v, np.uint8)


def talk_bot(menu=True, pages=1, choices=None, step=3):
    """패킷이 대화 덩어리 하나를 막 받은 봇 (진짜 PacketState — 판단은 tasks.dialogue.View 가 한다). 화면·CLI 는 비어 있다."""
    b = fake_bot()
    s = PacketState()
    s.channel = 1  # 감시를 켠 뒤 맵에 들어옴
    s.dialogue_npc, s.dialogue_step, s.dialogue_menu = 7, step, menu
    s.dialogue_pages, s.dialogue_choices = pages, choices
    s.changed_at["dialogue"] = time.monotonic()
    b.packets.ok, b.packets.state = True, s
    b.skip_button.return_value = None
    b.vision.find.return_value = None
    b.activity.return_value = None
    b.dialogue_playing.return_value = True
    return b


class GuardTest(unittest.TestCase):
    def test_same_action_same_screen_is_stuck(self):
        """같은 처리를 했는데 화면이 그대로면 누른 게 안 먹은 것 — 끝없이 누르지 않는다."""
        b = fake_bot()
        mon = monitor.Monitor(b)
        ctx = monitor.Ctx("t", menus=True)
        with mock.patch.object(d, "look", return_value=Seen(d.FAREWELL, frame=frame())):
            with self.assertRaises(monitor.Stuck):
                for _ in range(mon.same_limit + 2):
                    mon.check(ctx)
        self.assertEqual(b.click.call_count, mon.same_limit + 1)

    def test_changing_screen_is_not_stuck(self):
        b = fake_bot()
        mon = monitor.Monitor(b)
        ctx = monitor.Ctx("t", menus=True)
        for i in range(mon.same_limit + 3):
            with mock.patch.object(d, "look", return_value=Seen(d.FAREWELL, frame=frame(i * 20 % 250))):
                mon.check(ctx)

    def test_waiting_is_not_stuck(self):
        b = fake_bot()
        b.may_skip_scene.return_value = False  # 던전 중의 연출은 기다린다
        mon = monitor.Monitor(b)
        with mock.patch.object(d, "look", return_value=Seen(d.SCENE, hit=(1, 1), frame=frame())):
            for _ in range(mon.same_limit + 3):
                self.assertEqual(mon.check(monitor.Ctx("t")).done, "연출 대기")
        b.click.assert_not_called()


class UnknownTest(unittest.TestCase):
    def test_unknown_goes_main_once_then_stuck(self):
        b = fake_bot()
        mon = monitor.Monitor(b)
        mon.unknown_limit = 10
        ctx = monitor.Ctx("t")
        clock = [0.0]
        with mock.patch.object(d, "look", return_value=Seen(d.UNKNOWN, frame=frame())), \
                mock.patch.object(core.time, "monotonic", side_effect=lambda: clock[0]):
            mon.check(ctx)
            clock[0] = 11
            mon.check(ctx)  # 한 번은 메인 화면으로
            b.to_main.assert_called_once()
            clock[0] = 15
            mon.check(ctx)
            clock[0] = 22
            with self.assertRaises(monitor.Stuck):
                mon.check(ctx)

    def test_unknown_again_after_main_is_stuck(self):
        """메인으로 돌린 뒤 태스크가 같은 동작을 해 또 모르는 상황 — 같은 일에서 두 번째면 멈춘다 (2026-10-26 11:22)."""
        b = fake_bot()
        mon = monitor.Monitor(b)
        mon.unknown_limit = 10
        ctx = monitor.Ctx("t")
        clock = [0.0]
        with mock.patch.object(core.time, "monotonic", side_effect=lambda: clock[0]):
            with mock.patch.object(d, "look", return_value=Seen(d.UNKNOWN, frame=frame())):
                mon.check(ctx)
                clock[0] = 11
                mon.check(ctx)
            with mock.patch.object(d, "look", return_value=Seen(d.MAIN, frame=frame(), idle=True)):
                mon.check(ctx)  # 메인 화면 — 태스크가 진행하기를 다시 누른다
            with mock.patch.object(d, "look", return_value=Seen(d.UNKNOWN, frame=frame())):
                clock[0] = 20
                mon.check(ctx)
                clock[0] = 31
                with self.assertRaises(monitor.Stuck):
                    mon.check(ctx)
        b.to_main.assert_called_once()

    def test_unknown_retries_main_after_long_time(self):
        """몇 시간 도는 일에서 한참 전에 메인으로 돌린 것 때문에 새 모르는 화면에서 바로 멈추지 않는다 (판정 점검 11-16)."""
        b = fake_bot()
        mon = monitor.Monitor(b)
        mon.unknown_limit = 10
        ctx = monitor.Ctx("t")
        clock = [0.0]
        with mock.patch.object(core.time, "monotonic", side_effect=lambda: clock[0]):
            with mock.patch.object(d, "look", return_value=Seen(d.UNKNOWN, frame=frame())):
                mon.check(ctx)
                clock[0] = 11
                mon.check(ctx)  # 메인으로
            with mock.patch.object(d, "look", return_value=Seen(d.MAIN, frame=frame(), idle=True)):
                mon.check(ctx)
            with mock.patch.object(d, "look", return_value=Seen(d.UNKNOWN, frame=frame())):
                clock[0] = 20 + core.UNKNOWN_RETRY
                mon.check(ctx)
                clock[0] = 31 + core.UNKNOWN_RETRY
                mon.check(ctx)  # 멈추지 않고 한 번 더 메인으로
        self.assertEqual(b.to_main.call_count, 2)

    def test_run_limit_does_not_stop(self):
        """CLI 연속 실행 제한이 걸려 있어도 점검자는 평소대로 화면을 본다 (멈추지 않는다 — 2026-11-10 사용자)."""
        b = fake_bot()
        b.cli.run_limited = True
        b.map_loading.return_value = "loading"
        self.assertEqual(d.look(b).what, d.LOADING)

    def test_exit_question_untouched(self):
        b = fake_bot()
        with mock.patch.object(d, "look", return_value=Seen(d.EXIT_ASK, frame=frame())):
            self.assertIsNone(monitor.Monitor(b).clear())
        b.key.assert_not_called()
        b.click.assert_not_called()


class ActTest(unittest.TestCase):
    def mon(self):
        m = monitor.Monitor(fake_bot())
        m.settle = mock.Mock(return_value=None)
        return m

    def test_ok(self):
        self.assertTrue(self.mon().act(monitor.Ctx("t"), "x", lambda: True, lambda: True, within=1))

    def test_cannot(self):
        do = mock.Mock(return_value=False)
        self.assertIs(self.mon().act(monitor.Ctx("t"), "x", do, lambda: True, within=1), False)
        do.assert_called_once()  # 할 수 없는 건 다시 하지 않는다

    def test_no_change_retries_then_none(self):
        do = mock.Mock(return_value=True)
        clock = iter(range(0, 1000, 5))
        with mock.patch.object(core.time, "monotonic", side_effect=lambda: next(clock)):
            self.assertIsNone(self.mon().act(monitor.Ctx("t"), "x", do, lambda: False, within=6, tries=2))
        self.assertEqual(do.call_count, 2)

    def test_within_counts_after_do(self):
        """do() 가 오래 걸려도(창 열기·글자 읽기·빠른 이동) 기다리는 시간은 그 뒤부터 (2026-11-17 07:09 '진행하기')."""
        now = [1000.0]

        def do():
            now[0] += 30
            return True
        seen = []

        def expect():
            seen.append(now[0])
            return len(seen) >= 3
        m = self.mon()
        m.bot.sleep.side_effect = lambda *a: now.__setitem__(0, now[0] + 1)
        with mock.patch.object(core.time, "monotonic", side_effect=lambda: now[0]):
            self.assertTrue(m.act(monitor.Ctx("t"), "x", do, expect, within=12, tries=1))
        self.assertEqual(seen[0], 1030.0)


    def test_dialog_opening_bounded(self):
        """창 없는 대화 신호는 태스크가 건 대화일 때만 계속 기다리고, 아니면 OPENING 초까지 (사용자 2026-11-17)."""
        m = self.mon()
        b = m.bot
        b.dialogue_playing.return_value = True
        b.npc_owned.return_value = False
        t = [50.0]
        with mock.patch.object(core.time, "monotonic", side_effect=lambda: t[0]):
            self.assertTrue(m.dialog_opening())
            t[0] += core.OPENING + 1
            self.assertFalse(m.dialog_opening())
            b.npc_owned.return_value = True
            self.assertTrue(m.dialog_opening())   # 태스크가 건 대화
            b.npc_owned.return_value = False
            b.dialogue_playing.return_value = False
            self.assertFalse(m.dialog_opening())  # 신호가 끝나면 다시 처음부터
            b.dialogue_playing.return_value = True
            self.assertTrue(m.dialog_opening())

    def test_redo_after_interrupt_not_counted(self):
        """기다리는 사이 끼어들기를 넘겼으면 남은 시간을 기다리지 않고 다시 하고, 그 시도는 세지 않는다 (사용자 2026-11-17)."""
        m = self.mon()
        m.bot.interrupt_n = 0
        done = []

        def do():
            done.append(1)
            if len(done) == 1:
                m.bot.interrupt_n += 1  # 누른 사이 NPC 가 말을 걸어 넘김
            return True
        self.assertTrue(m.act(monitor.Ctx("t"), "x", do, lambda: len(done) >= 2, within=30, tries=1))
        self.assertEqual(len(done), 2)

    def test_redo_has_limit(self):
        m = self.mon()
        m.bot.interrupt_n = 0
        do = mock.Mock(side_effect=lambda: setattr(m.bot, "interrupt_n", m.bot.interrupt_n + 1))
        self.assertIsNone(m.act(monitor.Ctx("t"), "x", do, lambda: False, within=30, tries=1))
        self.assertEqual(do.call_count, 1 + core.REDO)


class DialogTest(unittest.TestCase):
    def test_job_presses_accept_when_menu_comes_late(self):
        """메뉴가 늦게 떠도 '수락' 이 보이면 Space — 넘기기를 눌러 수락을 놓치지 않는다 (2026-10-26 10:34)."""
        b = talk_bot()
        b.exists.side_effect = lambda n: n == "accept"
        ctx = monitor.Ctx("arbeit", "x", menus=True)
        with mock.patch.object(handlers.sit, "clear_attendance", return_value=None):
            self.assertEqual(handlers.dialog(b, ctx, Seen(d.DIALOG, frame=frame())), "수락")
        b.key.assert_called_once_with("space")

    def menu_by_text(self, texts, task="arbeit", ctx=None, b=None):
        """메뉴 덩어리(패킷, 1쪽 — 넘길 대사 없음) + 그림으로는 버튼을 못 찾음 → 버튼 줄 글자 texts."""
        b = b or talk_bot()
        b.exists.return_value = False
        ctx = ctx or monitor.Ctx(task, "x", menus=True)
        clock = iter(range(0, 1000, 5))
        with (mock.patch.object(handlers.sit, "clear_attendance", return_value=None),
              mock.patch.object(handlers.time, "monotonic", side_effect=lambda: next(clock)),
              mock.patch.object(handlers.ocr, "find_texts", return_value=[(t, 0, 0) for t in texts]) as ft,
              mock.patch("mabi.tasks.dialogue.next_line") as nl):
            did = handlers.dialog(b, ctx, Seen(d.DIALOG, frame=frame()))
        b.read, b.line = ft.called, nl.called
        return b, did

    def test_menu_without_template_uses_button_text(self):
        """메뉴(패킷) + 넘길 대사 없음 + 그림이 안 맞음 → 버튼 글자 '수락' 이 보이면 Space (2026-10-28 09:07)."""
        b, did = self.menu_by_text(["Space", "수락", "나중에 한다"])
        self.assertEqual(did, "수락")
        b.key.assert_called_once_with("space")

    def test_menu_with_other_buttons_waits(self):
        b, did = self.menu_by_text(["Space", "상점", "대화 종료"])
        self.assertEqual(did, "메뉴 버튼 기다림")
        b.key.assert_not_called()

    def test_other_menu_after_clear_ends_talk(self):
        """클리어 뒤 정리에서 뜬 NPC 메뉴(로나: 판의 조언·상점·대화 종료)는 기다리지 않고 대화 종료 (2026-11-06)."""
        b, did = self.menu_by_text(["Space", "판의 조언", "상점", "대화 종료"], task="weekday_dungeon")
        self.assertEqual(did, "대화 종료")
        b.key.assert_called_once_with("esc")

    def test_arbeit_menu_gives_up_after_waits(self):
        ctx = monitor.Ctx("arbeit", "x", menus=True)
        dids = [self.menu_by_text(["Space", "상점", "대화 종료"], ctx=ctx)[1] for _ in range(4)]
        self.assertEqual(dids, ["메뉴 버튼 기다림"] * 3 + ["대화 종료"])

    def test_other_menu_by_choice_labels_ends_at_once(self):
        """선택지 글자(패킷)에 '수락'·'결과 보고' 가 없으면 아르바이트여도 기다리지 않고 대화 종료 — 글자도 안 읽는다."""
        b, did = self.menu_by_text(["상점"], b=talk_bot(choices=("$npc,Pan$의 조언", "상점", "대화 종료")))
        self.assertEqual(did, "대화 종료")
        b.key.assert_called_once_with("esc")
        self.assertFalse(b.read)

    def test_our_menu_by_choice_labels_reads_button(self):
        b, did = self.menu_by_text(["Space", "결과 보고", "상점"], b=talk_bot(choices=("결과 보고", "상점", "아무말", "대화 종료")))
        self.assertEqual(did, "결과 보고")
        b.key.assert_called_once_with("space")

    def test_many_page_menu_is_skipped_to_buttons(self):
        """여러 쪽 메뉴 덩어리(로나 7쪽)는 아직 안 눌렀으면 넘긴다 — 버튼이 없을 때라 글자도 안 읽는다."""
        b, did = self.menu_by_text(["수락"], b=talk_bot(pages=7, choices=("$npc,Pan$의 조언", "상점", "대화 종료")))
        self.assertEqual(did, "대사 넘김")
        self.assertTrue(b.line)
        self.assertFalse(b.read)
        b.key.assert_not_called()

    def test_line_without_menu_is_tapped(self):
        """메뉴가 없는 덩어리(결과 보고 뒤 한마디 — 종류 3, 선택지 0)는 기다리지 않고 넘긴다 (2026-11-22 07:53 13분 멈춤)."""
        b, did = self.menu_by_text([], b=talk_bot(menu=False, pages=2, choices=()))
        self.assertEqual(did, "대사 넘김")
        b.key.assert_not_called()

    def test_arbeit_menu_wait_counts_only_in_a_row(self):
        """지난번 메뉴에서 기다린 횟수가 남아 다음 메뉴를 일찍 닫지 않는다 (판정 점검 11-16)."""
        ctx = monitor.Ctx("arbeit", "x", menus=True)
        ctx.n.update(menu_wait=2, menu_wait_at=-100)
        self.assertEqual(self.menu_by_text(["Space", "상점", "대화 종료"], ctx=ctx)[1], "메뉴 버튼 기다림")

    def test_blocker_does_not_touch_menus(self):
        """기다리는 중의 정리는 NPC 메뉴(수락·결과 보고)를 누르지 않는다."""
        b = fake_bot()
        with mock.patch.object(d, "look", return_value=Seen(d.ACCEPT, hit=(1, 1), frame=frame())):
            self.assertIsNone(monitor.Monitor(b).clear())
        b.key.assert_not_called()

    def test_dungeon_window_finishes_job(self):
        b = fake_bot()
        ctx = monitor.Ctx("arbeit", "x", job=True, finish_on={d.DUNGEON_WINDOW: "dungeon"})
        with mock.patch.object(d, "look", return_value=Seen(d.DUNGEON_WINDOW, frame=frame(), info={"tab": "weekday"})):
            seen = monitor.Monitor(b).check(ctx)
        self.assertEqual(seen.finish.result, "dungeon")


class DeadTest(unittest.TestCase):
    def dead(self, revive, ok):
        b = fake_bot()
        with (mock.patch.object(d, "look", return_value=Seen(d.DEAD, src="packet")),
              mock.patch("mabi.tasks.abyss.revive_here", return_value=ok),
              mock.patch("mabi.tasks.fight.ensure_auto")):
            return monitor.Monitor(b).check(monitor.Ctx("t", revive=revive), guard=False)

    def test_revives_here(self):
        self.assertEqual(self.dead(True, True).done, "여기서 부활")

    def test_cannot_revive_finishes(self):
        self.assertEqual(self.dead(True, False).finish.result, "dead")

    def test_without_revive_left_to_task(self):
        seen = self.dead(False, True)
        self.assertIsNone(seen.done)
        self.assertIsNone(seen.finish)


class FinishOnTest(unittest.TestCase):
    def test_waited_screen_finishes_without_pressing(self):
        """태스크가 기다리던 화면(어비스 보상 화면)이면 누르지 않고 끝 — 다시 하기·나가기는 태스크가 정한다."""
        b = fake_bot()
        ctx = monitor.Ctx("abyss", finish_on={d.REWARD: "reward"})
        with mock.patch.object(d, "look", return_value=Seen(d.REWARD, hit=(1, 1), frame=frame())):
            self.assertEqual(monitor.Monitor(b).check(ctx).finish.result, "reward")
        b.key.assert_not_called()
        b.click.assert_not_called()


class ChooseTest(unittest.TestCase):
    def test_space_option_is_not_pressed_when_choosing(self):
        """고를 선택지가 따로 있으면 Space(기본 선택지)를 누르지 않는다 — 게시판 선택지가 메뉴 버튼처럼 보여도."""
        self.assertIs(handlers.pick(monitor.Ctx("t", menus=True, choose="골드"), d.REPORT), handlers.dialog)
        self.assertIs(handlers.pick(monitor.Ctx("t", menus=True), d.REPORT), handlers.menu_space)

    def test_choose_reads_given_region(self):
        """대장간 '수리' 처럼 게시판이 아닌 선택지 줄도 읽는다 (choose_region)."""
        b = fake_bot()
        ctx = monitor.Ctx("repair", choose="수리", choose_region="npc_buttons")
        with (mock.patch.object(handlers.ocr, "find_texts", return_value=[("수리", 600, 800)]) as ft,
              mock.patch.object(handlers.gd, "region", side_effect=lambda n: n)):
            self.assertEqual(handlers._choose(b, ctx, SimpleNamespace(menu_up=True, has=lambda *w: None)), "선택지 '수리'")
        self.assertEqual(ft.call_args[0][1], "npc_buttons")
        b.click.assert_called_once_with((600, 800))
        self.assertTrue(ctx.take("chosen"))

    def test_choice_missing_from_labels_is_not_read(self):
        """선택지 글자(패킷)에 원하는 낱말이 없으면 글자를 읽지 않고 기다린다 — 아무거나 누르지 않는다."""
        b = talk_bot(choices=("임무 목록", "대화 종료"))
        ctx = monitor.Ctx("repair", choose="수리", choose_region="npc_buttons")
        with mock.patch.object(handlers.ocr, "find_texts") as ft:
            self.assertEqual(handlers._choose(b, ctx, dialogue.now(b, frame())), "선택지 기다림")
        ft.assert_not_called()
        b.click.assert_not_called()


class DeadAfterResultTest(unittest.TestCase):
    def test_dead_with_abyss_result_is_not_dead(self):
        """쓰러진 채로 판이 끝나면(어비스 결과) 쓰러짐이 아니라 화면(클리어·보상)을 본다."""
        b = mock.Mock()
        b.cli.run_limited = False
        b.map_loading.return_value = False
        b.packets.at_charselect.return_value = False
        b.packets.ok = True
        b.packets.state.dead = True
        b.packets.state.abyss_result = 0
        self.assertEqual(d.look(b).what, d.DEAD)
        b.packets.state.abyss_result = 7
        from mabi.monitor import offline
        b.cfg = offline.config()
        b.ui = b.cfg["ui"]
        b.vision.has.return_value = False
        b.skip_button.return_value = None
        b.at_main.return_value = False
        with mock.patch("mabi.tasks.dialogue.View.open", new=property(lambda self: False)):
            self.assertNotEqual(d.look(b).what, d.DEAD)


class LeaveTest(unittest.TestCase):
    def leave(self, shown):
        b = talk_bot(menu=shown)
        ctx = monitor.Ctx("repair", leave=True)
        with (mock.patch.object(handlers.sit, "clear_attendance", return_value=None),
              mock.patch("mabi.tasks.dialogue.wait_next", return_value=True),
              mock.patch("mabi.tasks.dialogue.next_line") as nl):
            return b, nl, handlers.dialog(b, ctx, Seen(d.DIALOG, frame=frame()))

    def test_menu_is_closed_with_esc(self):
        """대화를 마칠 때 메뉴는 고르지 않고 ESC('대화 종료')."""
        b, nl, did = self.leave(True)
        self.assertEqual(did, "대화 종료")
        b.key.assert_called_once_with("esc")
        nl.assert_not_called()

    def test_farewell_line_is_skipped(self):
        """작별 인사는 ESC 로 안 넘어간다 → 넘기기."""
        b, nl, did = self.leave(False)
        self.assertEqual(did, "대사 넘김")
        nl.assert_called_once()
        b.key.assert_not_called()

    def test_space_option_is_not_pressed_when_leaving(self):
        self.assertIs(handlers.pick(monitor.Ctx("t", menus=True, leave=True), d.ACCEPT), handlers.dialog)


class LoginPopupTest(unittest.TestCase):
    def test_popups_handled_in_any_task(self):
        """접속 직후 창(공지·새 이벤트·스텔라 픽)은 어느 일에서든 처리한다 — 오전 6시 뒤·캐릭터마다 뜰 수도 안 뜰 수도 있다."""
        for what in (d.NOTICE, d.EVENT_POPUP, d.STELLA):
            self.assertIsNotNone(handlers.pick(monitor.Ctx("abyss"), what))

    def test_notice_closed_with_esc(self):
        b = fake_bot()
        with mock.patch.object(d, "look", return_value=Seen(d.NOTICE, hit=(1, 1), frame=frame())):
            self.assertEqual(monitor.Monitor(b).check(monitor.Ctx("t"), guard=False).done, "공지 팝업 닫음")
        b.key.assert_called_with("esc")


class NpcVisitTest(unittest.TestCase):
    """기다리는 중 NPC 가 말을 걸어 옴 (주간 목표 첫 달성 뒤 에반 — 다시 하기 뒤 다음 판 안에서도): 넘기기 버튼이 안 잡혀도
    패킷이 대화 중·메뉴 없음이고 대화 창('대화 기록')이 보이면 대사를 넘긴다. 메뉴가 있거나, HUD 가 보이거나, 다른 창 위에
    신호만 남았으면 누르지 않는다 (2026-11-15 각인 강화 창)."""
    def _bot(self, menu=False, hud=None, log=(100, 40)):
        b = fake_bot()
        b.ui = {"main_hud": "hud"}
        b.skip_button.return_value = None
        b.behind.return_value = False
        b.packets.ok = True
        b.packets.state.fresh, b.packets.state.in_dialogue, b.packets.state.dialogue_menu = True, True, menu
        b.vision.find.side_effect = lambda f, n: {"hud": hud, "dialog_log": log}.get(n)
        b.at_main.side_effect = lambda f=None: b.vision.find(f, "hud") is not None  # 메인 화면 판정은 bot.at_main 하나로
        return b

    def test_lines_advanced_by_packet(self):
        b = self._bot()
        with mock.patch("mabi.tasks.dialogue.next_line") as nl:
            self.assertEqual(handlers._dialog_blocker(b, Seen(d.DIALOG, frame=frame()), dialogue.now(b, frame())), "대사 넘김")
        nl.assert_called_once()

    def test_menu_or_hud_left_alone(self):
        for b in (self._bot(menu=True), self._bot(hud=(1, 1), log=None), self._bot(log=None)):
            with mock.patch("mabi.tasks.dialogue.next_line") as nl:
                self.assertIsNone(handlers._dialog_blocker(b, Seen(d.DIALOG, frame=frame()), dialogue.now(b, frame())))
            nl.assert_not_called()


class LineReadyTest(unittest.TestCase):
    """대사 넘기기는 대화 창이 그려진 뒤에만 — 패킷은 창이 뜨기 전에 대화 중이라고 한다 (넘기기 칸이 생기기 전에 눌러
    진행이 안 됨, 제보 2026-10-27). '대화 넘기기' 가 보이거나 HUD 가 가려졌을 때 누른다."""
    def _bot(self, skip=None, hud=None):
        b = fake_bot()
        b.ui = {"main_hud": "hud"}
        b.frame.return_value = frame()
        b.skip_button.return_value = skip
        b.vision.find.return_value = hud
        b.at_main.side_effect = lambda f=None: b.vision.find(f, "hud") is not None  # 메인 화면 판정은 bot.at_main 하나로
        return b

    def test_waits_for_dialog_window(self):
        from mabi.tasks import dialogue
        b = self._bot(hud=(1, 1))  # HUD 가 남음 = 창이 아직
        self.assertFalse(dialogue.next_line(b, ready_within=0))
        b.click.assert_not_called()

    def test_clicks_when_window_up(self):
        from mabi.tasks import dialogue
        for b in (self._bot(skip=("dialog", (1800, 45)), hud=(1, 1)), self._bot()):  # 넘기기 버튼 / HUD 가려짐 (한마디 대사)
            self.assertTrue(dialogue.next_line(b, wait=False))
            b.click.assert_called_once_with((1800, 45))


class InterruptTest(unittest.TestCase):
    """무작위 이벤트 끼어들기 (monitor.interrupts): 기본은 없음 — 신호가 있으면 화면을 보고, 떠 있을 때만 멈추고 넘긴 뒤
    돌아간다 (사용자 2026-11-17)."""
    def _bot(self, dialog=True, menu=False, owned=False, attending=False):
        b = fake_bot()
        b.packets.ok = True
        s = b.packets.state
        s.in_dialogue, s.dialogue_menu = dialog, menu
        s.attending.return_value = attending
        b.npc_owned.return_value = owned
        b.task_id = "silver"
        b.frame.return_value = frame()
        return b

    def test_pending(self):
        from mabi.monitor import interrupts
        self.assertEqual(interrupts.pending(self._bot()), "dialog")
        self.assertEqual(interrupts.pending(self._bot(menu=True)), "dialog")  # 메뉴가 뜨는 대화도 (로나) — ESC 로 마침
        self.assertIsNone(interrupts.pending(self._bot(owned=True)))   # NPC 대화를 다루는 일 (아르바이트 등)
        self.assertEqual(interrupts.pending(self._bot(dialog=False, attending=True)), "attendance")
        b = self._bot()
        b.packets.ok = False
        self.assertIsNone(interrupts.pending(b))

    def test_shown_needs_window(self):
        """대화 창('대화 기록'·대화 넘기기)이나 '출석부 건너뛰기' 가 보여야 떠 있는 것."""
        from mabi.monitor import interrupts
        b = self._bot()
        b.cfg["login"] = {"attendance_skip": "attendance_skip"}
        b.vision.has.return_value = True
        b.skip_button.return_value = None
        for found, what, want in ((None, "dialog", False), ("dialog_log", "dialog", True),
                                  ("attendance_skip", "attendance", True), ("attendance_skip", "dialog", False)):
            b.vision.find.side_effect = lambda f, n, found=found: (1, 1) if n == found else None
            self.assertIs(interrupts.shown(b, what, frame()), want, (found, what))
        b.vision.find.side_effect = lambda f, n: None
        b.skip_button.return_value = ("dialog", (1800, 45))
        self.assertTrue(interrupts.shown(b, "dialog", frame()))

    def test_not_shown_does_not_wait(self):
        """신호만 있고 화면엔 없으면 멈추지도 누르지도 않는다 (11-15 각인 강화 창 위 3번, 11-17 06:49 필드 25초)."""
        from mabi.monitor import interrupts
        b = self._bot()
        mon = mock.Mock()
        with mock.patch("mabi.monitor.of", return_value=mon), mock.patch.object(interrupts, "shown", return_value=False):
            self.assertFalse(interrupts.handle(b, "dialog"))
        mon.check.assert_not_called()
        b.sleep.assert_not_called()
        b.click.assert_not_called()

    def test_handle_while_shown(self):
        from mabi.monitor import interrupts
        b = self._bot()
        mon = mock.Mock()
        calls = []

        def check(ctx, fr=None, guard=False):
            calls.append(ctx.what)
            if len(calls) == 2:
                b.packets.state.in_dialogue = False  # 대사를 넘겨 대화가 끝남
            return Seen(d.DIALOG, frame=frame(), done="대사 넘김" if len(calls) <= 2 else None)
        mon.check.side_effect = check
        with mock.patch("mabi.monitor.of", return_value=mon), \
                mock.patch.object(interrupts, "shown", side_effect=lambda *a: b.packets.state.in_dialogue):
            self.assertTrue(interrupts.handle(b, "dialog"))
        self.assertEqual(calls[0], "끼어들기 (dialog)")
        self.assertEqual(len(calls), 3)  # 넘김 2번 + 이어 뜨는 확인 한 번 봄
        b.interrupt_cooldown.assert_not_called()

    def test_gone_from_screen_ends_even_with_signal(self):
        """신호가 남아도 화면에서 사라져 GONE 초 그대로면 끝 — 신호만 보고 붙잡지 않는다."""
        from mabi.monitor import interrupts
        b = self._bot()
        mon = mock.Mock()
        mon.check.return_value = Seen(d.DIALOG, frame=frame(), done="대사 넘김")
        looks = iter([True, True, False])
        with mock.patch("mabi.monitor.of", return_value=mon), mock.patch.object(interrupts, "GONE", -1), \
                mock.patch.object(interrupts, "shown", side_effect=lambda *a: next(looks, False)):
            self.assertTrue(interrupts.handle(b, "dialog"))
        self.assertTrue(b.packets.state.in_dialogue)
        b.interrupt_cooldown.assert_not_called()

    def test_menu_dialog_leaves(self):
        # 메뉴가 떠 있으면 고르지 않고 대화를 마친다 (Ctx.leave → ESC '대화 종료'), 메뉴가 사라지면 다시 대사 넘김
        from mabi.monitor import interrupts
        b = self._bot(menu=True)
        mon = mock.Mock()
        leaves = []

        def check(ctx, fr=None, guard=False):
            leaves.append(ctx.leave)
            s = b.packets.state
            if len(leaves) == 1:
                s.dialogue_menu = False  # ESC → 작별 대사
            else:
                s.in_dialogue = False
            return Seen(d.DIALOG, frame=frame(), done="대화 종료" if len(leaves) == 1 else "대사 넘김")
        mon.check.side_effect = check
        with mock.patch("mabi.monitor.of", return_value=mon), \
                mock.patch.object(interrupts, "shown", side_effect=lambda *a: b.packets.state.in_dialogue):
            self.assertTrue(interrupts.handle(b, "dialog"))
        self.assertEqual(leaves[:2], [True, False])

    def test_gives_up_and_cools_down(self):
        from mabi.monitor import interrupts
        b = self._bot()
        mon = mock.Mock()
        mon.check.return_value = Seen(d.DIALOG, frame=frame())  # 넘기지 못함
        with mock.patch("mabi.monitor.of", return_value=mon), mock.patch.object(interrupts, "HOLD", -1), \
                mock.patch.object(interrupts, "shown", return_value=True):
            interrupts.handle(b, "dialog")
        b.interrupt_cooldown.assert_called_once_with("dialog", interrupts.COOLDOWN)

    def test_watch_looks_less_when_stale(self):
        """신호가 있으면 화면을 1초마다 보고, STALE 초 넘게 안 뜨는 신호는 5초마다. 신호가 바뀌면 바로 다시."""
        from mabi.monitor import interrupts
        b = self._bot()
        w = interrupts.Watch()
        t = [100.0]

        def at(v):
            t[0] = v
            return w.due(b)
        with mock.patch.object(interrupts.time, "monotonic", side_effect=lambda: t[0]):
            self.assertEqual(at(100), "dialog")
            self.assertIsNone(at(100.5))
            self.assertEqual(at(101.1), "dialog")
            self.assertEqual(at(100 + interrupts.STALE + 1), "dialog")
            self.assertIsNone(at(100 + interrupts.STALE + 3))
            self.assertEqual(at(100 + interrupts.STALE + 6.5), "dialog")
            b.packets.state.in_dialogue = False
            self.assertIsNone(at(120))
            b.packets.state.in_dialogue = True
            self.assertEqual(at(120.1), "dialog")

    def test_bot_counts_only_handled(self):
        """화면에 없어 넘기지 않았으면 interrupt_n 이 늘지 않는다 (act·press.until 이 다시 하지 않게)."""
        from mabi.bot import Bot
        from mabi.monitor import interrupts
        b = self._bot()
        b._interrupting, b.interrupts, b._watch, b._interrupt_off = False, True, None, {}
        b.interrupt_n, b.interrupt_spent = 0, 0.0
        b.behind.return_value = False
        with mock.patch.object(interrupts, "handle", side_effect=[False, True]):
            Bot.check_interrupt(b)
            self.assertEqual(b.interrupt_n, 0)
            b._watch.looked = 0
            Bot.check_interrupt(b)
        self.assertEqual(b.interrupt_n, 1)
        self.assertFalse(b._interrupting)


class AttendanceTest(unittest.TestCase):
    """출석: 패킷이 출석 대화 시작을 알리고 대화 창이 떠 있으면 '출석부 건너뛰기' 가 뜰 때까지 대사(한두 마디, 무작위)를
    넘기고, 뜨면 그것만 누른다. 신호만 있고 창이 없으면 아무것도 안 한다."""
    def _bot(self, skip, window=True):
        import time
        from mabi.packet_monitor import PacketState
        b = fake_bot()
        b.cfg["login"] = {"attendance_skip": "attendance_skip", "first_dialog_xy": [960, 540]}
        b.ui = {"main_hud": "hud"}
        b.packets.ok = True
        b.packets.state = PacketState(attendance_at=time.monotonic())
        b.vision.has.return_value = True
        b.skip_button.return_value = None
        b.window_up = window

        def find(f, n):
            if n == "attendance_skip":
                return skip
            if n == "dialog_log":
                return (100, 40) if b.window_up else None
            if n == "hud":
                return None if b.window_up else (1, 1)
            return None
        b.vision.find.side_effect = find
        b.at_main.side_effect = lambda f=None: b.vision.find(f, "hud") is not None  # 메인 화면 판정은 bot.at_main 하나로
        return b

    def test_lines_then_skip(self):
        from mabi import situation
        b = self._bot(skip=None)
        self.assertEqual(situation.clear_attendance(b, frame()), "출석 대사 넘김")
        b.click.assert_called_with((960, 540))
        self.assertEqual(situation.clear_attendance(b, frame()), "출석 대사 기다림")  # 2초 안엔 다시 누르지 않는다
        b.vision.find.side_effect = lambda f, n: (1800, 45)
        self.assertEqual(situation.clear_attendance(b, frame()), "출석부 건너뛰기")
        b.click.assert_called_with((1800, 45))
        self.assertFalse(b.packets.state.attending())

    def test_signal_without_window_does_nothing(self):
        """신호가 남았어도 대화 창이 없으면 기다리지도 누르지도 않는다 — 사용자가 직접 넘긴 출석에 막 시작한 숙제가
        25초를 헛기다렸다 (2026-11-17 06:49). 창이 그려지면 그때 넘긴다."""
        from mabi import situation
        b = self._bot(skip=None, window=False)
        self.assertIsNone(situation.clear_attendance(b, frame()))
        b.click.assert_not_called()
        b.window_up = True
        self.assertEqual(situation.clear_attendance(b, frame()), "출석 대사 넘김")

    def _look(self, b):
        b.cli.run_limited = False
        b.map_loading.return_value = False
        b.packets.at_charselect.return_value = False
        b.frame.return_value = frame()
        return d.look(b).what

    def test_detect_attending_when_shown(self):
        self.assertEqual(self._look(self._bot(skip=None)), d.ATTENDANCE)  # 버튼 없는 대사 (대화 창)
        self.assertEqual(self._look(self._bot(skip=(1800, 45), window=False)), d.ATTENDANCE)

    def test_detect_signal_only_is_not_attendance(self):
        b = self._bot(skip=None, window=False)
        b.activity.return_value = None
        self.assertEqual(self._look(b), d.MAIN)


class NetworkTest(unittest.TestCase):
    """'네트워크가 불안정' — 다시 시도하기를 세며 (bot.marks), 너무 잦으면 F12 와 같은 일시정지 (StopWatcher.pause)."""
    def test_retry_then_pause(self):
        from mabi.exceptions import StopRequested
        from mabi.bot import Bot
        from mabi.inputs import StopWatcher
        b = fake_bot()
        seen = Seen(d.NETWORK, (5, 5), frame=frame())
        for n in range(handlers.NETWORK_TRIES):
            self.assertEqual(handlers.network(b, None, seen), "네트워크 다시 시도")
        self.assertEqual(len(b.marks.network_tries), handlers.NETWORK_TRIES)
        sw = StopWatcher.__new__(StopWatcher)  # 키 감시 스레드 없이
        sw.by_key, sw.stopped = False, threading.Event()
        b.stopper, b.pause_as_key = sw, Bot.pause_as_key.__get__(b)  # 진짜 Bot 의 것 (기본 대기 pause 와 헷갈리지 않게)
        with self.assertRaises(StopRequested):
            handlers.network(b, None, seen)
        self.assertTrue(sw.by_key and sw.stopped.is_set())


if __name__ == "__main__":
    unittest.main()
