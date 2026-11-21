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
    def leave(self, kind=None, in_field=False, hunts=("",), at_main=(False,), state="NotInDungeon", task="silver"):
        from mabi.tasks import login
        b = unwatched(bot({"slot": 2, "task": task}))
        b.at_main.side_effect = list(at_main) + [at_main[-1]] * 10
        b.exists.return_value = False
        here = SimpleNamespace(kind=kind, in_field=in_field)
        with (mock.patch("mabi.place.place", return_value=here),
              mock.patch("mabi.tasks.space.game_space", return_value=""),
              mock.patch("mabi.tasks.space.hunt_quest", side_effect=list(hunts)),
              mock.patch("mabi.tasks.space.dungeon_state", return_value=state),
              mock.patch("mabi.tasks.dungeon.touch_prompt_visible", return_value=False),
              mock.patch("mabi.tasks.dungeon.wait_field") as wf,
              mock.patch("mabi.tasks.dungeon.play_dungeon") as pd,
              mock.patch("mabi.tasks.exits.leave_instance") as li):
            login._leave_dungeon(b)
        return SimpleNamespace(field=wf.called, dungeon=pd.called, left=li.called, closed=b.to_main.called)

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

    def test_abyss_left_unless_weekend_cut(self):
        self.assertTrue(self.leave(kind=ABYSS, task="arbeit").left)
        with mock.patch("mabi.tasks.weekend.finish_inside") as fin:
            r = self.leave(kind=ABYSS, task="weekend_abyss")
        self.assertTrue(fin.called)
        self.assertFalse(r.left)

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
    def cleared(self, resume=None, rows=()):
        from mabi.tasks import tribute
        b = watched(mock.MagicMock(), 7, rows)
        b.resume = resume
        return tribute.cleared_today(b)

    def test_cut_after_opening_quest(self):
        self.assertIn("in_dungeon", self.cleared({"step": "in_dungeon"}))
        self.assertEqual(self.cleared({"step": "tr_wait"}), "")

    def test_observed_deep_dungeon_clear(self):
        deep = [("channel.entering", {"channel_type": DUNGEON, "channel_name": "페카 2-1 심층 던전 매우 어려움"}, 7),
                ("dungeon.state", {"state_name": "Cleared"}, 7)]
        self.assertIn("심층", self.cleared(rows=deep))
        other = [("channel.entering", {"channel_type": DUNGEON, "channel_name": "라비 던전"}, 7),
                 ("dungeon.state", {"state_name": "Cleared"}, 7)]
        self.assertEqual(self.cleared(rows=other), "")
        self.assertEqual(self.cleared(rows=[(k, v, 8) for k, v, _ in deep]), "")  # 다른 캐릭터

    def test_run_does_not_wait_for_cleared_quest(self):
        from mabi.tasks import tribute
        b = mock.MagicMock()
        b.read_counter.return_value = 4
        b.resume = {"step": "dungeon_reward"}
        b.session.login_at = 0.0
        c = {"cost": 2, "quest_wait": 180, "quest_login_wait": 600, "max_runs": 1, "very_hard": "x"}
        with (mock.patch.object(tribute.situation, "dungeon_tab", return_value=None),
              mock.patch.object(tribute, "quest_visible", return_value=False)):
            out = tribute.run(b, {"tribute": c})
        self.assertIn("이미 깸", out)
        b.step.assert_not_called()


if __name__ == "__main__":
    unittest.main()
