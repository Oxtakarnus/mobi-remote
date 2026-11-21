"""멈췄다 이어 할 때 끊긴 판을 지금 게임과 맞춰 본다 (점검 2026-11-22).
- 끊긴 숙제는 같은 캐릭터이고 멈춘 뒤 로그아웃·마을로 나간 것이 관찰되지 않았을 때만 (login.cut_task)
- 창이 HUD 를 가려 사냥 퀘스트를 모르면 창을 닫고 다시 본다, 던전 맵인데 상태를 모르면 진행 중으로
- 끊긴 주말 어비스·레이드·필드 보스 전투 안이면 나가지 않고 그 판을 마친다
- 공물: 퀘스트가 없고 이미 깬 근거가 있으면 오지 않을 퀘스트를 기다리지 않는다"""
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from test_resume_extra_loot import daily_of, unwatched

from mabi.packet_monitor.monitor import PacketMonitor
from mabi.place import ABYSS, DUNGEON, FIELD, FIELD_BOSS


def watched(b, char=7, rows=()):
    """감시가 멈추기 전부터 끊김 없이 돌았다 — 관찰 기록 rows [(key, vals, char)] 를 받은 뒤."""
    m = PacketMonitor(None)
    m.status, m.last_rx, m.watch_from = "running", time.monotonic(), time.time() - 100
    m.state.char_id = char
    for key, vals, who in rows:
        m.days.record(key, vals, who)
    b.packets = m
    return b


def bot(progress, char_in_game=None):
    b = mock.MagicMock()
    b.cfg = {"black_hole": {"space_keyword": "검은 구멍"}, "weekday_dungeon": {"extra_loot": 3},
             "silver": {"field_timeout": 2400}, "tribute": {"clear_timeout": 900}}
    b.character = {"slot": 2}
    b.daily = daily_of(progress)
    return b


STOPPED = {"slot": 2, "task": "login", "before": {"slot": 2, "task": "weekday_dungeon", "char": 7, "stopped": 0.0}}


class CutTaskTest(unittest.TestCase):
    def cut(self, rows=(), char=7, stopped_ago=50):
        from mabi.tasks import login
        prog = {**STOPPED, "before": {**STOPPED["before"], "stopped": time.time() - stopped_ago}}
        b = watched(bot(prog), char, rows)
        return login.cut_task(b)

    def test_same_run_kept(self):
        self.assertEqual(self.cut()["task"], "weekday_dungeon")
        # 던전 맵(인스턴스) 진입은 끊긴 판으로 들어간 것 (입장 로딩 중에 멈춤) — 판이 끝난 게 아니다
        self.assertIsNotNone(self.cut([("channel.entering", {"channel_type": DUNGEON}, 7)]))

    def test_other_character_in_game(self):
        self.assertIsNone(self.cut(char=8))

    def test_left_after_stop(self):
        self.assertIsNone(self.cut([("channel.entering", {"channel_type": "Field", "channel_name": "이멘 마하"}, 7)]))
        self.assertIsNone(self.cut([("session.logout_ok", {}, 7)]))
        self.assertIsNone(self.cut([("char.personal_data", {"char_id": 8}, 8)]))

    def test_login_stop_used_when_task_has_no_stop(self):
        # 숙제 도중 리모콘이 꺼져 멈춤 기록이 없고, 이어 하려던 접속 도중 멈췄으면 그 멈춤부터 본다 (이어 하기 순서와 같은 때)
        from mabi.tasks import login
        prog = {"slot": 2, "task": "login", "stopped": time.time() - 50,
                "before": {"slot": 2, "task": "weekday_dungeon", "char": 7}}
        b = watched(bot(prog), 7, [("channel.entering", {"channel_type": "Field", "channel_name": "이멘 마하"}, 7)])
        self.assertIsNone(login.cut_task(b))

    def test_unknown_keeps_old_rule(self):
        from mabi.tasks import login
        b = unwatched(bot(STOPPED))
        self.assertEqual(login.cut_task(b)["task"], "weekday_dungeon")

    def test_next_character_login_is_not_a_cut(self):
        from mabi.tasks import login
        b = unwatched(bot({"slot": 3, "task": "login", "before": {"slot": 2, "task": "arbeit"}}))
        b.character = {"slot": 3}
        self.assertIsNone(login.cut_task(b))


class LeaveAtLoginTest(unittest.TestCase):
    def leave(self, kind=None, in_field=False, hunts=("",), at_main=(False,), state="NotInDungeon", task="silver",
              shown=False):
        from mabi.tasks import login
        b = unwatched(bot({"slot": 2, "task": task}))
        b.at_main.side_effect = list(at_main) + [at_main[-1]] * 10
        b.exists.return_value = shown  # 던전 클리어 화면(터치·보상 나가기)이 보이나
        here = SimpleNamespace(kind=kind, in_field=in_field)
        with (mock.patch("mabi.place.place", return_value=here),
              mock.patch("mabi.tasks.space.game_space", return_value=""),
              mock.patch("mabi.tasks.space.hunt_quest", side_effect=list(hunts)),
              mock.patch("mabi.tasks.space.dungeon_state", return_value=state),
              mock.patch("mabi.tasks.dungeon.touch_prompt_visible", return_value=False),
              mock.patch("mabi.tasks.dungeon.wait_field") as wf,
              mock.patch("mabi.tasks.dungeon.play_dungeon") as pd,
              mock.patch("mabi.tasks.clear.after_clear") as ac,
              mock.patch("mabi.tasks.exits.leave_instance") as li):
            login._leave_dungeon(b)
        return SimpleNamespace(field=wf.called, dungeon=pd.called, left=li.called, closed=b.to_main.called,
                               reward=ac.called)

    def test_covered_hud_closes_and_looks_again(self):
        # 지도 창이 HUD 를 가림 → 닫고 다시 보니 사냥 퀘스트가 있다 → 끊긴 숙제가 무엇이든 기다린다
        r = self.leave(in_field=True, hunts=("", "창백한 산 사냥 IV"), at_main=(False, True), task="arbeit")
        self.assertTrue(r.closed and r.field)

    def test_covered_hud_still_unknown_waits_only_for_silver(self):
        self.assertTrue(self.leave(in_field=True, hunts=("", ""), at_main=(False,)).field)
        self.assertFalse(self.leave(in_field=True, hunts=("", ""), at_main=(False,), task="arbeit").field)

    def test_unknown_map_and_unknown_quest_does_not_wait(self):
        # 맵도 퀘스트도 모름 (캐릭터 선택 화면 등) — 은동전이 끊겼어도 40분을 기다리지 않는다
        self.assertFalse(self.leave(in_field=None, hunts=(None,), task="silver").field)

    def test_dungeon_map_with_unknown_state_waits(self):
        r = self.leave(kind=DUNGEON, state=None, task="tribute")
        self.assertTrue(r.dungeon)
        self.assertFalse(self.leave(kind=None, state=None, task="tribute").dungeon)

    def test_reward_screen_with_unknown_state_takes_reward(self):
        # 상태를 몰라도 클리어 화면이 보이면 보상부터 — 진행 중으로 보고 끝난 판을 기다리지 않는다
        r = self.leave(kind=DUNGEON, state=None, task="tribute", shown=True)
        self.assertTrue(r.reward)
        self.assertFalse(r.dungeon)

    def test_abyss_left_unless_weekend_cut(self):
        self.assertTrue(self.leave(kind=ABYSS, task="arbeit").left)
        with mock.patch("mabi.tasks.weekend.finish_inside") as fin:
            r = self.leave(kind=ABYSS, task="weekend_abyss")
        self.assertTrue(fin.called)
        self.assertFalse(r.left)

    def test_finish_blocked_leaves_and_goes_on(self):
        # 끊긴 판을 마치다 막히면 예전처럼 나와서 접속을 잇는다 — 예외로 이 캐릭터의 숙제를 통째로 건너뛰지 않게
        from mabi.exceptions import CannotProceed
        with (mock.patch("mabi.tasks.weekend.finish_inside", side_effect=CannotProceed("시간 초과")),
              mock.patch("mabi.tasks.field_boss.inside", return_value=False)):
            r = self.leave(kind=ABYSS, task="weekend_abyss")
        self.assertTrue(r.left)

    def test_stop_while_finishing_goes_up(self):
        from mabi.exceptions import StopRequested
        with mock.patch("mabi.tasks.weekend.finish_inside", side_effect=StopRequested("멈춤")):
            with self.assertRaises(StopRequested):
                self.leave(kind=ABYSS, task="weekend_abyss")

    def test_field_boss_fight_cut_finishes_fight(self):
        from mabi.tasks import login
        b = unwatched(bot({"slot": 2, "task": "field_boss"}))
        b.daily.last_step.return_value = {"step": "fb_fight"}
        with (mock.patch("mabi.place.place", return_value=SimpleNamespace(kind=FIELD_BOSS, in_field=False)),
              mock.patch("mabi.tasks.field_boss.inside", return_value=True),
              mock.patch("mabi.tasks.field_boss.finish_inside") as fin):
            self.assertTrue(login._leave_dungeon(b))
        self.assertTrue(fin.called)


class FieldBossResumeTest(unittest.TestCase):
    def run_fb(self, resume, got):
        from mabi.tasks import field_boss
        b = mock.MagicMock()
        b.resume = resume
        inside = iter([True, False, False])
        with (mock.patch.object(field_boss, "done", return_value=False),
              mock.patch.object(field_boss, "inside", side_effect=lambda bot: next(inside, False)),
              mock.patch.object(field_boss, "fight", return_value=got) as fight,
              mock.patch.object(field_boss, "leave"),
              mock.patch.object(field_boss, "not_ready", return_value="열린 시간이 아님")):
            try:
                out = field_boss.run(b, {"field_boss": {"boss": "페리", "difficulty": "일반"}})
            except Exception as e:  # noqa: BLE001 — 다시 들어가려다 시간 밖이라 멈춘 것
                out = f"멈춤: {e}"
        return out, fight.called

    def test_fight_cut_continues(self):
        out, fought = self.run_fb({"step": "fb_fight"}, True)
        self.assertTrue(fought)
        self.assertIn("끊긴 전투", out)

    def test_inside_without_fight_step_leaves(self):
        out, fought = self.run_fb({"step": "fb_travel"}, True)
        self.assertFalse(fought)


class TributeClearedTest(unittest.TestCase):
    """공물: 퀘스트가 목록에 없을 때 이미 깼나 — 끊긴 단계 뒤의 심층 던전 클리어 관찰로만 바로 판단한다.
    게임을 다시 켜면 접속 뒤 몇 분은 남은 퀘스트도 목록에 없어, 끊긴 단계만으로 깼다고 보면 안 한 숙제를 넘긴다."""
    DEEP = "페카 2-1 심층 던전"  # 실제 맵 이름 모양 — 심층은 난이도가 안 붙는다

    def rows(self, char=7, name=None):
        return [("channel.entering", {"channel_type": DUNGEON, "channel_name": name or self.DEEP}, char),
                ("dungeon.state", {"state_name": "Cleared"}, char)]

    def tbot(self, resume=None, rows=()):
        b = watched(mock.MagicMock(), 7, rows)
        b.resume = resume
        return b

    def test_cut_cleared_needs_clear_after_cut(self):
        from mabi.tasks import tribute
        before = time.time() - 1
        self.assertIn(self.DEEP, tribute.cut_cleared(self.tbot({"step": "in_dungeon", "ts": before}, self.rows())))
        # 끊긴 단계 뒤에 깬 기록이 없으면 — 게임을 다시 켠 뒤라 퀘스트가 아직 안 뜬 것일 수 있다
        self.assertEqual(tribute.cut_cleared(self.tbot({"step": "travel", "ts": time.time() + 5}, self.rows())), "")
        self.assertEqual(tribute.cut_cleared(self.tbot({"step": "in_dungeon", "ts": before})), "")
        self.assertEqual(tribute.cut_cleared(self.tbot({"step": "in_dungeon"}, self.rows())), "")  # 옛 기록(ts 없음)
        self.assertEqual(tribute.cut_cleared(self.tbot({"step": "tr_wait", "ts": before}, self.rows())), "")

    def test_deep_cleared_only_deep_and_this_character(self):
        from mabi import observed
        self.assertIn(self.DEEP, observed.deep_cleared_today(self.tbot(rows=self.rows())))
        self.assertEqual(observed.deep_cleared_today(self.tbot(rows=self.rows(name="룬다 1-3 던전 어려움"))), "")
        self.assertEqual(observed.deep_cleared_today(self.tbot(rows=self.rows(char=8))), "")

    def run_tr(self, resume, rows=(), visible=(False,), wait=0):
        from mabi.tasks import tribute
        b = self.tbot(resume, rows)
        b.read_counter.return_value = 4
        b.session.login_at = 0.0
        c = {"cost": 2, "quest_wait": wait, "quest_login_wait": 600, "max_runs": 0, "very_hard": "x"}
        seen = iter(visible)
        with (mock.patch.object(tribute.situation, "dungeon_tab", return_value=None),
              mock.patch.object(tribute, "quest_visible", side_effect=lambda bot: next(seen, visible[-1]))):
            try:
                return tribute.run(b, {"tribute": c}), b
            except Exception as e:  # noqa: BLE001
                return e, b

    def test_run_skips_wait_when_cut_run_cleared(self):
        out, b = self.run_tr({"step": "in_dungeon", "ts": time.time() - 1}, self.rows(), wait=600)
        self.assertIn("끊긴 판을", out)
        b.step.assert_not_called()

    def test_run_waits_after_relogin_without_clear(self):
        # 이동 중에 끊기고 게임을 다시 켬 — 퀘스트가 접속 뒤에 다시 뜨면 그대로 한다 (예전 판단은 여기서 넘겼다)
        out, b = self.run_tr({"step": "travel", "ts": time.time() - 1}, visible=(False, False, True), wait=600)
        self.assertIsInstance(out, str)
        self.assertNotIn("깸", out)
        self.assertEqual(b.step.call_args_list[0].args[0], "tr_wait")

    def test_run_end_of_wait(self):
        from mabi.exceptions import CannotProceed
        out, _ = self.run_tr(None, self.rows())
        self.assertIn("이미 깬 것으로 봄", out)  # 기다린 끝 — 오늘 심층을 깼으면 실패로 남기지 않는다
        out, _ = self.run_tr(None)
        self.assertIsInstance(out, CannotProceed)


class FinishCutRoundTest(unittest.TestCase):
    """끊긴 주말 판만 마친다 (Repeat.finish) — 이미 끝난 판(보상 화면)이면 보상만, 쓰러지면 거기서 그만."""

    def abyss_rep(self, result="clear"):
        from mabi.tasks import abyss
        r = abyss.AbyssRepeat.__new__(abyss.AbyssRepeat)
        r.bot = mock.MagicMock()
        r.a = {"dungeon": "흩어진 물길", "match_timeout": 60, "run_timeout": 600}
        r.runs, r.minutes, r.t0, r.on_event, r.behind, r.finish = 1, 0, time.monotonic(), lambda e: None, False, True
        r.stat = {"clears": 0, "deaths": 0, "retries": 0, "revives": 0}
        r.rounds = []
        r.play_round = lambda play, step: r.rounds.append(step) or result
        r.recheck = lambda at: False
        r.yield_between = r.repair_between = lambda go_out: False
        r._again = mock.MagicMock()
        return r

    def loop(self, r, at):
        from mabi.tasks import abyss
        with (mock.patch.object(abyss, "to_reward", return_value="reward"),
              mock.patch.object(abyss, "exit_reward") as ex,
              mock.patch.object(abyss, "leave", return_value=True),
              mock.patch.object(abyss, "enter") as en,
              mock.patch.object(abyss, "inside", return_value=True),
              mock.patch.object(abyss, "entered_since", return_value=True)):
            r.loop(at)
        return ex.called, en.called

    def test_reward_screen_takes_reward_only(self):
        r = self.abyss_rep()
        exited, entered = self.loop(r, "reward")
        self.assertEqual((r.stat["clears"], len(r.rounds)), (1, 0))  # 한 판 더 돌지 않는다
        self.assertTrue(exited)
        self.assertFalse(r._again.called or entered)

    def test_play_then_out(self):
        r = self.abyss_rep()
        exited, _ = self.loop(r, "play")
        self.assertEqual((r.stat["clears"], len(r.rounds)), (1, 1))
        self.assertTrue(exited)

    def test_dead_stops_without_reentry(self):
        r = self.abyss_rep("dead")
        _, entered = self.loop(r, "play")
        self.assertEqual((r.stat["deaths"], len(r.rounds)), (1, 1))
        self.assertFalse(entered)  # 다시 들어가는 건 숙제 차례에

    def test_weekend_passes_finish_and_ship_is_left(self):
        from mabi.place import RAID, RAID_LOBBY
        from mabi.tasks import weekend
        self.assertNotIn(RAID_LOBBY, weekend.INSIDE["weekend_raid"])
        self.assertIn(RAID, weekend.INSIDE["weekend_raid"])
        made = []

        class Fake:
            finish = False

            def __init__(self, bot, cfg, runs=0):
                made.append(self)

            def run(self):
                return {}
        cfg = {"abyss": {"dungeon": "흩어진 물길"}, "weekend": {"abyss": {}}}
        with (mock.patch.object(weekend.abyss, "AbyssRepeat", Fake),
              mock.patch.object(weekend, "_kept", return_value=mock.MagicMock()),
              mock.patch("mabi.tasks.exits.leave_instance") as li):
            weekend.finish_inside(mock.MagicMock(), cfg, "weekend_abyss")
        self.assertTrue(made[0].finish)
        self.assertTrue(li.called)

    def test_finish_runs_the_abyss_map_here(self):
        # 계획의 첫 던전이 아니라 지금 선 맵의 던전으로 마친다 (흩어진 물길은 게임을 앞에 두고 — setup)
        from mabi.tasks import weekend
        got = []

        class Fake:
            finish = False

            def __init__(self, bot, cfg, runs=0):
                got.append(cfg["abyss"]["dungeon"])

            def run(self):
                return {}
        here = SimpleNamespace(kind=ABYSS, name="흩어진 물길 (어비스 시즌2 3구역 매우 어려움2)")
        cfg = {"abyss": {"dungeon": "허상의 정박지"}, "weekend": {"abyss": {}}}
        with (mock.patch.object(weekend.abyss, "AbyssRepeat", Fake),
              mock.patch.object(weekend, "_kept", return_value=mock.MagicMock()),
              mock.patch("mabi.place.place", return_value=here),
              mock.patch("mabi.tasks.exits.leave_instance")):
            weekend.finish_inside(mock.MagicMock(), cfg, "weekend_abyss")
        self.assertEqual(got, ["흩어진 물길"])

    def test_kept_restores_weight_watch(self):
        # 접속 단계 안에서 판을 마친 뒤 무게 감시가 켜진 채 남지 않는다 (접속 중엔 앞 캐릭터 무게를 보지 않는다)
        from mabi.tasks import weekend
        b = SimpleNamespace(background=True, scene_skip=False, watch_weight=False)
        with weekend._kept(b):
            b.background, b.scene_skip, b.watch_weight = False, True, True  # 반복이 바꾼 것 (Repeat.run)
        self.assertEqual((b.background, b.scene_skip, b.watch_weight), (True, False, False))

    def test_matching_start_counts_only_a_later_map(self):
        # 매칭 중에 시작 — 지금 선 맵(지난 판) 뒤에 들어간 맵만 이번 판 (예전엔 0 부터 봐 지난 판 맵을 새 판으로 셌다)
        from mabi.tasks import abyss
        r = self.abyss_rep()
        r.bot.packets.state.entered_at = 123.0
        since = []
        with (mock.patch.object(abyss, "to_reward", return_value="reward"),
              mock.patch.object(abyss, "exit_reward"),
              mock.patch.object(abyss, "inside", return_value=True),
              mock.patch.object(abyss, "entered_since", side_effect=lambda bot, at: since.append(at) or True)):
            r.loop("matching")
        self.assertEqual(since[:1], [123.0])


if __name__ == "__main__":
    unittest.main()
