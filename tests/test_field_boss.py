"""필드 보스 — 열린 시간 계산과, 열린 시간이 아닌 카드를 작업 큐가 비켜 두는 것."""
import datetime as dt
import tempfile
import threading
import time
import types
import unittest
from unittest import mock
from pathlib import Path

from mabi import cutpoint, tasks
from mabi.tasks import field_boss as fb
from mabi.workqueue import Kind, WorkQueue


def at(h, m=0):
    return dt.datetime(2026, 11, 9, h, m)


class WindowTest(unittest.TestCase):
    def test_open_and_left(self):
        self.assertEqual(fb.window(at(12, 0))[0], 30 * 60)
        self.assertEqual(fb.window(at(18, 26))[0], 4 * 60)
        self.assertEqual(fb.window(at(22, 29))[0], 60)

    def test_closed_gives_next(self):
        self.assertEqual(fb.window(at(12, 30)), (0, at(18)))
        self.assertEqual(fb.window(at(9, 0)), (0, at(12)))
        self.assertEqual(fb.window(at(23, 0)), (0, dt.datetime(2026, 11, 10, 12)))

    def test_not_ready(self):
        self.assertEqual(fb.not_ready(at(20, 5)), "")
        self.assertIn("18:00", fb.not_ready(at(13, 0)))
        self.assertIn("곧 닫힘", fb.not_ready(at(20, 27)))  # 4분 안 남음 — 새 캐릭터는 시작하지 않는다
        self.assertIn("22:00", fb.not_ready(at(20, 27)))
        # 시각을 안 주면 지금 시각 — 곧 닫힐 때도 다음 열림을 계산한다 (예전엔 여기서 죽음)
        t = at(12, 27)
        with mock.patch.object(fb.dt, "datetime", mock.Mock(now=lambda: t)):
            self.assertIn("18:00", fb.not_ready())

    def test_only_field_boss_cards_wait(self):
        # 다른 숙제가 섞여 있으면 그 숙제는 한다 (필드 보스 몫만 그 안에서 넘긴다)
        orig = tasks.READY["field_boss"]
        tasks.READY["field_boss"] = lambda: "닫힘"
        try:
            self.assertEqual(tasks.not_ready(["field_boss"]), "닫힘")
            self.assertEqual(tasks.not_ready(["drill", "field_boss"]), "")
            self.assertEqual(tasks.not_ready(["drill"]), "")
        finally:
            tasks.READY["field_boss"] = orig
        self.assertTrue(tasks.timed(["field_boss"]))
        self.assertFalse(tasks.timed(["drill", "field_boss"]))
        self.assertFalse(tasks.timed(None))

    def test_choices_for_screen(self):
        # 화면 칸은 이 목록만 그린다 — 보스마다 고를 수 있는 난이도 수가 다르다
        c = fb.choices("드로흐에넴", "매우 어려움")
        self.assertEqual(c["bosses"][:2], ["페리", "크라브바흐"])
        self.assertEqual(c["difficulties"]["토르모그"], ["일반", "어려움"])
        self.assertEqual(c["difficulties"]["페리"], ["일반", "어려움", "매우 어려움"])
        self.assertIn(c["boss"], c["bosses"])
        from mabi import gamedata as gd
        self.assertLessEqual(len(c["bosses"]), len(gd.point("field_boss_rows")))  # 목록 칸 자리가 모자라면 누를 수 없다
        self.assertIn(c["difficulty"], c["difficulties"][c["boss"]])


class SafeTest(unittest.TestCase):
    """끊어도 되는 곳 — 마을·일반 필드만. 따로 들어가는 곳·로딩·매칭·쓰러짐·모름은 아님."""

    def bot(self, ok=True, **st):
        from mabi.packet_monitor import PacketState
        s = PacketState(**{"loading": False, "channel_type": "Field", "abyss_matching": 0, "dead": False, **st})
        return types.SimpleNamespace(packets=types.SimpleNamespace(ok=ok, state=s))

    def test_safe(self):
        self.assertTrue(cutpoint.safe(self.bot()))
        for t in ("BattleField", "FieldBoss", "InstanceDungeon", "InstanceAbyssDungeon", "InstanceDimension",
                  "InstanceRaidLobby", None):
            self.assertFalse(cutpoint.safe(self.bot(channel_type=t)), t)
        self.assertFalse(cutpoint.safe(self.bot(loading=True)))
        self.assertFalse(cutpoint.safe(self.bot(abyss_matching=2)))
        self.assertFalse(cutpoint.safe(self.bot(dead=True)))
        self.assertFalse(cutpoint.safe(self.bot(ok=False)))

    def test_check_calls_hook_only_when_safe(self):
        calls = []
        cutpoint.set_hook(lambda: calls.append(1) or "")
        try:
            cutpoint.check(self.bot(), "arbeit_go")
            cutpoint.check(self.bot(channel_type="InstanceDungeon"), "dungeon_reward")
            cutpoint.check(self.bot(), "abyss_match")  # 입장을 누른 뒤 단계
            self.assertEqual(calls, [1])
        finally:
            cutpoint.set_hook(None)


class Timed(Kind):
    """open 이 False 면 준비 안 됨. 돌면 이름을 적는다."""

    def __init__(self):
        self.open, self.ran = False, []

    def ready(self, it):
        return "" if self.open or it.get("label") != "필보" else "열린 시간이 아님"

    def run(self, q, it):
        self.ran.append(it["label"])
        return True


class QueueSkipTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.k = Timed()
        self.q = WorkQueue(Path(d.name) / "q.json", Path(d.name) / "h.jsonl", lambda ch, v: None, {"daily": self.k})
        self.addCleanup(self.settle)  # 임시 폴더보다 먼저 (나중에 넣은 정리가 먼저 돈다)

    def settle(self):
        """큐 스레드가 끝나길 기다린다 — 아직 큐 파일을 쓰는 중에 임시 폴더를 지우면 '디렉터리가 비어 있지 않음' 으로 실패한다."""
        self.q.pause()
        if self.q._thread:
            self.q._thread.join(5)

    def wait_for(self, cond, timeout=5):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            time.sleep(0.02)
        return False

    def test_closed_card_steps_aside_then_runs(self):
        self.q.add({"kind": "daily", "label": "필보"})
        self.q.add({"kind": "daily", "label": "어비스"})
        self.q.tick()
        self.assertTrue(self.wait_for(lambda: self.k.ran == ["어비스"]))  # 위 카드가 닫혀 있어 아래부터
        self.assertEqual(self.q.items[0]["note"], "열린 시간이 아님")
        self.assertTrue(self.q.running)  # 열리길 기다린다
        self.k.open = True
        self.assertTrue(self.wait_for(lambda: self.k.ran == ["어비스", "필보"], timeout=35))
        self.assertTrue(self.wait_for(lambda: not self.q.running))

    def test_timed_card_cuts_in_at_safe_point(self):
        # 긴 카드가 도는 중 시간 정해진 카드가 열리면, 긴 카드가 끊어도 되는 자리(cut_for_timed 를 부름)에서 밀려나고
        # 그 카드를 먼저 한 뒤 긴 카드를 이어 한다
        k, q = self.k, self.q
        k.timed = lambda it: it.get("label") == "필보"
        stop = threading.Event()
        steps = []

        def run(q_, it):
            if it["label"] != "긴 일":
                k.ran.append(it["label"])
                return True
            for n in range(200):
                if stop.is_set():
                    stop.clear()
                    q_.set_stop("stopped")
                    return False
                steps.append(n)
                if n == 3:
                    k.open = True
                q_.cut_for_timed()  # 단계마다 (cutpoint.check)
                time.sleep(0.01)
            k.ran.append("긴 일")
            return True
        k.run = run
        k.stop = lambda reason: stop.set()
        q.add({"kind": "daily", "label": "긴 일"})
        q.add({"kind": "daily", "label": "필보"})
        q.tick()
        self.assertTrue(self.wait_for(lambda: k.ran == ["필보", "긴 일"]))
        self.assertTrue(self.wait_for(lambda: not q.running))

    def test_not_cut_by_itself_or_closed(self):
        k, q = self.k, self.q
        k.timed = lambda it: it.get("label") == "필보"
        cut = []

        def run(q_, it):
            cut.append(q_.cut_for_timed())
            k.ran.append(it["label"])
            return True
        k.run = run
        q.add({"kind": "daily", "label": "긴 일"})
        q.add({"kind": "daily", "label": "필보"})
        q.tick()  # 필보는 닫혀 있음 → 긴 일이 끊기지 않는다
        self.assertTrue(self.wait_for(lambda: k.ran == ["긴 일"]))
        k.open = True  # 열리면 필보가 돌고, 필보는 저 자신을 끊지 않는다
        self.assertTrue(self.wait_for(lambda: k.ran == ["긴 일", "필보"], timeout=35))
        self.assertEqual(cut, ["", ""])

    def test_timed_due_only_asks(self):
        # 판 사이에 묻기만 한다 (어비스 '다시 하기' 대신 나갈지) — 카드를 옮기거나 큐를 세우지 않는다
        k, q = self.k, self.q
        k.timed = lambda it: it.get("label") == "필보"
        asked = []

        def run(q_, it):
            if it["label"] == "긴 일":
                asked.append(q_.timed_due())
                k.open = True
                asked.append(q_.timed_due())
                asked.append([x["label"] for x in q_.items])
                asked.append(q_.stop)
            k.ran.append(it["label"])
            return True
        k.run = run
        q.add({"kind": "daily", "label": "긴 일"})
        q.add({"kind": "daily", "label": "필보"})
        q.tick()
        self.assertTrue(self.wait_for(lambda: k.ran == ["긴 일", "필보"]))
        self.assertEqual(asked, ["", "'필보' 열림", ["긴 일", "필보"], None])

    def test_pause_while_waiting(self):
        self.q.add({"kind": "daily", "label": "필보"})
        self.q.tick()
        self.assertTrue(self.wait_for(lambda: self.q.items[0]["note"] == "열린 시간이 아님"))
        self.q.pause()
        self.assertTrue(self.wait_for(lambda: not self.q.running, timeout=3))
        self.assertEqual(self.k.ran, [])



class YieldBetweenTest(unittest.TestCase):
    """어비스·레이드 반복의 판 사이 (tasks.repeat.Repeat.yield_between)."""

    def run_yield(self, due, done=False):
        from mabi.tasks.repeat import Repeat
        me = types.SimpleNamespace(done=lambda: done, bot=types.SimpleNamespace(log=types.SimpleNamespace(info=lambda m: None)))
        out = []
        cutpoint.set_hook(lambda: "", lambda: due)
        try:
            got = Repeat.yield_between(me, lambda: out.append("나감"))
        finally:
            cutpoint.set_hook(None)
        return got, out

    def test_leaves_when_timed_card_open(self):
        self.assertEqual(self.run_yield("'필보' 열림"), (True, ["나감"]))

    def test_retries_when_nothing_due(self):
        self.assertEqual(self.run_yield(""), (False, []))

    def test_last_round_not_asked(self):
        self.assertEqual(self.run_yield("'필보' 열림", done=True), (False, []))


class FightOutsideTest(unittest.TestCase):
    """결과 창 없이 보스 영역 밖으로 나오면 실패가 아니라 '보상 못 받음' — run 이 다시 들어간다 (2026-11-16 12:07)."""

    def test_left_area_is_no_reward(self):
        bot = mock.Mock()
        bot.cfg = {"field_boss": {"fight_timeout": 60}}
        bot.snapshot.return_value.name = "s.png"
        with mock.patch.object(fb, "BossSkills"), mock.patch.object(fb, "confirm_text", return_value=None), \
                mock.patch.object(fb, "on_map", return_value=False):
            self.assertIs(fb.fight(bot), False)

    def test_run_checks_guide_before_retry(self):  # 다시 들어가기 전에 성장 가이드가 잡았다고 하면 끝
        with mock.patch.object(fb, "done", side_effect=[False, True]), mock.patch.object(fb, "inside", return_value=False), \
                mock.patch.object(fb, "not_ready", return_value=""), mock.patch.object(fb, "open_window"), \
                mock.patch.object(fb, "travel"), mock.patch.object(fb, "enter"), \
                mock.patch.object(fb, "fight", return_value=False), mock.patch.object(fb, "leave"):
            out = fb.run(mock.Mock(), {"field_boss": {"boss": "보스", "difficulty": "어려움"}})
        self.assertIn("성장 가이드", out)


if __name__ == "__main__":
    unittest.main()


class EnterTest(unittest.TestCase):
    """보스 영역 입장 — 컷신 '장면 넘기기' 를 기다리는 시간 (가짜 시계)."""

    def run_enter(self, cutscene, button_at):
        clock, clicked = [0.0], []
        bot = mock.MagicMock()
        bot.packets.ok = True
        bot.wait_packet.return_value = True
        bot.sleep.side_effect = lambda a, b=None: clock.__setitem__(0, clock[0] + a)
        bot.click.side_effect = lambda hit: clicked.append(clock[0])
        bot.cutscene_playing.side_effect = lambda: cutscene and not clicked
        find = lambda *a, **k: "hit" if button_at is not None and clock[0] >= button_at and not clicked else None  # noqa: E731
        with (mock.patch.object(fb.time, "monotonic", lambda: clock[0]), mock.patch.object(fb.ui_text, "find", find),
              mock.patch.object(fb.gd, "text", lambda k: k), mock.patch.object(fb.gd, "region", lambda k: (0, 0, 1, 1))):
            fb.enter(bot)
        bot.key.assert_called_with("space")  # 자동 전투
        return clicked, clock[0]

    def test_late_button_while_cutscene(self):
        clicked, _ = self.run_enter(cutscene=True, button_at=16)  # 2026-11-16 12:07 — 들어간 지 16초 뒤에 뜸
        self.assertEqual(len(clicked), 1)

    def test_no_cutscene_moves_on(self):
        clicked, t = self.run_enter(cutscene=False, button_at=None)  # 이 출현 시간에 이미 본 캐릭터
        self.assertEqual(clicked, [])
        self.assertLess(t, fb.SKIP_LOOK + 2)
