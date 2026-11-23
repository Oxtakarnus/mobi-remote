"""다시(force) 카드가 밀렸다 이어 할 때 그 카드에서 끝낸 캐릭터·숙제는 건너뛴다 (2026-11-23 주간 카드가 필드 보스에
밀렸다 이어 하며 1번 캐릭터부터 다시 했다) — 카드 기록(queue_api.card_did·card_done) · 실행기(RunOptions.done)."""
import unittest
from unittest import mock

from gui_app.queue_api import DailyKind, card_did, card_done
from mabi.profile import game_date
from mabi.runner import RunOptions, Runner

CHARS = [{"slot": 1, "name": "가"}, {"slot": 2, "name": "나"}]
ONLY = ["weekend_abyss", "weekend_raid"]


def run_loop(opts):
    """캐릭터 둘 · 주간 숙제 둘로 실행기를 돌린다 → (한 일 [(캐릭터, 숙제)], 접속한 캐릭터, 결과)."""
    r = Runner.__new__(Runner)
    r._emit = lambda *a, **k: None
    r._loot, r._iface = mock.MagicMock(), mock.MagicMock()
    r._iface.attempt.return_value = False
    bot = mock.MagicMock()
    bot.overweight.return_value = None
    did, logins = [], []

    def task(tid):
        return lambda b, c: did.append((b.character["name"], tid)) or "끝"

    registry = {t: (t, task(t)) for t in ONLY}
    cfg = {"run": {"order": ONLY, "task_timeout_min": 30}, "arbeit": {"slots": []}}
    state = mock.MagicMock()
    state.last_step.return_value = None
    results = []
    with mock.patch("mabi.runner.login.run", side_effect=lambda b, c, ch: logins.append(ch["name"]) or "접속"):
        r._loop(cfg, opts, registry, {}, CHARS, state, bot, mock.MagicMock(), results)
    return did, logins, results


class RunnerDoneTest(unittest.TestCase):
    def test_force_skips_what_the_card_did(self):
        did, logins, results = run_loop(RunOptions(only=ONLY, force=True,
                                                   done={1: set(ONLY), 2: {"weekend_abyss"}}))
        self.assertEqual(logins, ["나"])  # 다 끝낸 캐릭터는 접속하지도 않는다
        self.assertEqual(did, [("나", "weekend_raid")])
        self.assertIn(("[가]", "DONE", "이 카드에서 끝냄"), results)

    def test_force_without_record_does_all(self):
        did, logins, _ = run_loop(RunOptions(only=ONLY, force=True))
        self.assertEqual(logins, ["가", "나"])
        self.assertEqual(len(did), 4)


class CardDidTest(unittest.TestCase):
    def ev(self, slot, task, status="OK"):
        return {"type": "task_end", "slot": slot, "task": task, "status": status}

    def test_records_finished_tasks_only(self):
        it = {}
        for e in (self.ev(1, "weekend_abyss"), self.ev(1, "login"), self.ev(1, "weekend_raid", "FAIL"),
                  self.ev(2, "arbeit", "MANUAL"), self.ev(2, "black_hole", "DONE"), self.ev(2, "silver", "STOP"),
                  {"type": "task_start", "slot": 2, "task": "silver"}):
            if (d := card_did(it, e)) is not None:
                it["did"] = d
        self.assertEqual(it["did"], {"date": game_date(), "slots": {"1": ["weekend_abyss"], "2": ["arbeit", "black_hole"]}})
        self.assertIsNone(card_did(it, self.ev(1, "weekend_abyss")))  # 이미 적힘
        self.assertEqual(card_done(it), {1: {"weekend_abyss"}, 2: {"arbeit", "black_hole"}})

    def test_other_day_starts_over(self):
        it = {"did": {"date": "2000-01-01", "slots": {"1": ["weekend_abyss"]}}}
        self.assertIsNone(card_done(it))
        self.assertEqual(card_did(it, self.ev(2, "weekend_raid"))["slots"], {"2": ["weekend_raid"]})


class SavedTest(unittest.TestCase):
    def test_did_survives_restart(self):  # queue.json 에 남는다 — 다시 켠 뒤 실패 카드를 ▶ 해도 끝낸 것은 건너뛴다
        import json
        from mabi.craft import queue as cq
        it = {"id": 5, "kind": "daily", "force": True, "did": {"date": game_date(), "slots": {"1": ["vanguard"]}}}
        self.assertEqual(json.loads(cq.encode({"items": [it]}))["items"][0]["did"], it["did"])


class DailyKindDoneTest(unittest.TestCase):
    def run_card(self, it):
        api = mock.MagicMock()
        api._q_display.return_value = True
        api._busy_reason.return_value = None
        api._q_fit.return_value = None
        seen = {}

        def launch(opts, on_event):
            seen["opts"] = opts
            on_event({"type": "task_end", "slot": 2, "task": "weekend_abyss", "status": "OK"})
            api._daily_result = ("done", [("[나] 주간 어비스", "OK", "")])
            return mock.Mock()
        api._daily_launch.side_effect = launch
        k = DailyKind.__new__(DailyKind)
        k.api = api
        q = mock.MagicMock(session={}, stop=None)
        q.patch.side_effect = lambda _id, fields, quiet=False: it.update(fields)
        k.run(q, it)
        return seen["opts"]

    def test_force_card_passes_and_records(self):
        it = {"id": 1, "chars": [1, 2], "only": ONLY, "force": True,
              "did": {"date": game_date(), "slots": {"1": list(ONLY)}}}
        opts = self.run_card(it)
        self.assertEqual(opts.done, {1: set(ONLY)})
        self.assertEqual(it["did"]["slots"], {"1": list(ONLY), "2": ["weekend_abyss"]})

    def test_plain_card_keeps_no_record(self):  # 다시가 아닌 카드는 오늘 완료 기록이 그 일을 한다
        it = {"id": 1, "chars": [1, 2]}
        self.run_card(it)
        self.assertNotIn("did", it)


if __name__ == "__main__":
    unittest.main()
