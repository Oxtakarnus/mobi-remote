"""아르바이트 전달 물품을 CLI 로 만들기 — 시작 전 가름(craft.quick), 실행(tasks.cli_make), 아르바이트 연결(arbeit._Round·short_of).
사용자 규칙 (2026-11-25): 가공이 5분 이하인 것만 알아서 만들고, 넘는 것은 건너뛴다."""
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from mabi import craft
from mabi.craft import quick
from mabi.craft.execute import ExecResult, step_key
from mabi.exceptions import StopRequested
from mabi.tasks import arbeit, cli_make
from test_craft_plan import plan, snap, table

ROOT = Path(__file__).resolve().parent.parent
METAL = "금속 가공 시설"


def qsnap(owned=None, busy=(), done=()):
    """quick 용 스냅샷 — busy: 금속 가공 시설에 걸린 가공 [(레시피 이름, 남은 초)], done: 완료분 이름."""
    t = table()
    s = snap(owned or {})
    if busy or done:
        s["works"]["facilities"] = [{"facility": METAL, "completed": [{"name": n} for n in done],
                                     "inProgress": [{"name": n, "remainingSec": sec} for n, sec in busy]}]
    s["cd"] = SimpleNamespace(recipes=t, knowledge=SimpleNamespace(product_of=lambda n, k=None: t.product_of(n) or n))
    s["kn"] = {}
    return s


class QuickCheckTest(unittest.TestCase):
    def _check(self, name, n, s, limit=300, calls=10, **ctx):
        return quick.check(s, name, n, limit, calls, plan(name, n, **ctx))

    def test_short_alter_ok(self):
        c = self._check("철괴", 6, qsnap(), owned={"광석": 40})  # 철괴(광석) 60초 × 2
        self.assertTrue(c.ok)
        self.assertEqual((c.sec, c.calls), (120, 2))

    def test_long_recipe(self):
        c = self._check("강철괴", 6, qsnap(), owned={"철괴": 6, "석탄": 8})  # 300초 × 2
        self.assertEqual((c.ok, c.kind), (False, quick.LONG))
        self.assertIn("10분", c.why)

    def test_facility_queue_counts(self):
        """시설은 차례로 가공한다 — 60초짜리라도 금속 가공 시설에 9시간 걸린 가공 뒤에 끝난다 (2026-11-25 백금강괴)."""
        c = self._check("철괴", 3, qsnap(busy=[("백금강괴", 9 * 3600)]), owned={"광석": 20})
        self.assertEqual((c.ok, c.kind), (False, quick.LONG))
        self.assertGreater(c.sec, 9 * 3600)

    def test_incoming_wait_counts(self):
        """곧 들어올 재료(가공 중)에 기대는 계획은 그 시설에 남은 시간을 기다린다 — 새로 걸 게 없어도."""
        s = qsnap(busy=[("철괴(광석)", 50), ("강철괴", 1000)])
        c = self._check("철괴", 3, s, incoming={"철괴": 3})
        self.assertEqual((c.ok, c.kind), (False, quick.LONG))  # 철괴 50초 + 같은 시설 강철괴 1000초
        c = self._check("철괴", 3, qsnap(busy=[("철괴(광석)", 50)]), incoming={"철괴": 3})
        self.assertEqual((c.ok, c.sec), (True, 50))

    def test_other_facility_not_counted(self):
        s = qsnap(busy=[("백금강괴", 9 * 3600)])
        s["works"]["facilities"][0]["facility"] = "목재 가공 시설"
        self.assertTrue(self._check("철괴", 3, s, owned={"광석": 20}).ok)

    def test_cannot_obtain(self):
        c = self._check("장검", 1, qsnap())  # 지배의 도안 (퀘스트 아이템)
        self.assertEqual((c.ok, c.kind), (False, quick.SHORT))

    def test_too_many_calls(self):
        c = self._check("철괴", 6, qsnap(), calls=1, owned={"광석": 40})
        self.assertEqual((c.ok, c.kind), (False, quick.CALLS))

    def test_not_in_table(self):
        self.assertEqual(self._check("없는 물건", 1, qsnap()).kind, quick.UNKNOWN)


class AlterCheckTest(unittest.TestCase):
    """게임 안 가공 시설 창 길도 CLI 길과 같은 기준 — 레시피 1회 시간 + 그 시설에 걸린 가공 (사용자 2026-11-25: 두 길 모두)."""

    def test_short_recipe_ok(self):
        c = quick.alter_check(qsnap(), ["철괴"], 300)
        self.assertEqual((c.ok, c.sec), (True, 60))

    def test_queue_counts(self):
        """60초 철괴라도 금속 가공 시설에 9시간 줄이 있으면 포기 — 물품 이름·카드(레시피 이름) 둘 다."""
        s = qsnap(busy=[("백금강괴", 9 * 3600)])
        for name in ("철괴", "철괴(광석)"):
            c = quick.alter_check(s, [name], 300)
            self.assertEqual((c.ok, c.kind), (False, quick.LONG), name)
            self.assertIn("9시간", c.why)

    def test_other_facility_queue_not_counted(self):
        s = qsnap(busy=[("백금강괴", 9 * 3600)])
        s["works"]["facilities"][0]["facility"] = "목재 가공 시설"
        self.assertTrue(quick.alter_check(s, ["철괴"], 300).ok)

    def test_long_recipe_and_unknown(self):
        self.assertEqual(quick.alter_check(qsnap(), ["강철괴"], 299).kind, quick.LONG)
        self.assertEqual(quick.alter_check(qsnap(), ["카드 둘레 글자"], 300).kind, quick.UNKNOWN)

    def test_same_answer_as_cli_path(self):
        """같은 시설 줄이면 두 길의 답이 같다 — 철괴 3개 (1회분 60초)."""
        for busy in ((), [("강철괴", 200)], [("강철괴", 250)], [("백금강괴", 9 * 3600)]):
            s = qsnap(busy=busy)
            cli = quick.check(s, "철괴", 3, 300, 10, plan("철괴", 3, owned={"광석": 20}))
            self.assertEqual(quick.alter_check(s, ["철괴"], 300).ok, cli.ok, busy)


class CheckAlterTest(unittest.TestCase):
    """가공 시설 창 길의 가름 (cli_make.check_alter) — 레시피 시간으로 안 되면 조회하지 않고, 되면 시설 줄을 조회해 다시 본다."""

    def setUp(self):
        craft.configure(ROOT / "state", ROOT / "data", None)
        self.bot = mock.MagicMock()
        self.bot.cfg = {"arbeit": {"alter_max_sec": 300}}

    def _check(self, names, snap):
        with mock.patch.object(cli_make, "_snapshot", return_value=snap) as sn:
            return cli_make.check_alter(self.bot, names), sn

    @staticmethod
    def queue(name, sec):
        fac = craft.data().recipes.alter_rows(name)[0]["facility"]
        return {"cd": craft.data(), "kn": None, "works": {"facilities": [
            {"facility": fac, "completed": [], "inProgress": [{"name": "백금강괴", "remainingSec": sec}]}]}}

    def test_no_query_when_recipe_decides(self):
        for names in (["깔끔 버섯 포자"], ["카드 둘레 글자"]):  # 1500초 · 표에 없음
            c, sn = self._check(names, None)
            self.assertFalse(c.ok)
            sn.assert_not_called()

    def test_queue_from_query(self):
        c, sn = self._check(["옷감"], self.queue("옷감", 9 * 3600))
        sn.assert_called_once()
        self.assertEqual((c.ok, c.kind), (False, quick.LONG))
        self.assertTrue(self._check(["옷감"], self.queue("옷감", 60))[0].ok)  # 45초 + 줄 60초

    def test_query_failed_recipe_only(self):
        c, _ = self._check(["옷감"], {"error": "disconnected"})
        self.assertTrue(c.ok)  # 줄을 모르면 예전처럼 레시피 시간만 (그 길은 alter_wait 만큼만 기다린다)
        self.bot.log.info.assert_called_once()

    def test_quick_alter_logs_only_long(self):
        with mock.patch.object(cli_make, "_snapshot", return_value=self.queue("옷감", 9 * 3600)):
            self.assertFalse(arbeit.quick_alter(self.bot, ["옷감"]))
            self.bot.log.info.assert_called_once()
            self.bot.log.reset_mock()
            self.assertFalse(arbeit.quick_alter(self.bot, ["카드 둘레 글자"]))  # 표에 없는 글자는 조용히
            self.bot.log.info.assert_not_called()

    def test_facility_window_card_skipped_on_long_queue(self):
        """가공 시설 창 카드('철괴(철 광석)', 60초)도 금속 가공 시설 줄이 9시간이면 가공하러 가지 않는다."""
        from mabi.monitor import handlers
        from test_arbeit_filter import _fixture
        ctx = mock.MagicMock(n={}, alter=(), alter_ok=lambda names: arbeit.quick_alter(self.bot, names))
        with mock.patch.object(cli_make, "_snapshot", return_value=self.queue("철괴(철 광석)", 9 * 3600)), \
                mock.patch.object(handlers, "_short_toast", return_value=False), mock.patch.object(handlers, "fast_travel"):
            r = handlers.craft(self.bot, ctx, SimpleNamespace(frame=_fixture("alter_window_metal.png"), hit=None))
        self.assertEqual(r.result, "alter")
        self.assertEqual(ctx.alter, ())
        self.bot.click.assert_not_called()


class StepKeyTest(unittest.TestCase):
    def test_alter_progress_not_repeat(self):
        a = {"kind": "alter", "name": "옷감", "runs": 1, "wanted": 2, "queued": 0}
        self.assertNotEqual(step_key(a, 0), step_key({**a, "queued": 1}, 0))
        self.assertEqual(step_key(a, 0), step_key(dict(a), 0))


class MakerTest(unittest.TestCase):
    """한 물품을 목표까지 — 엔진 걸음(next_step)과 명령 결과(execute)를 차례로 흉내 낸다."""

    def _run(self, steps, results=(), check=quick.Check(True, sec=90, calls=2), max_calls=10):
        bot = mock.MagicMock()
        bot.cfg = {"arbeit": {"alter_max_sec": 300, "make_max_calls": max_calls}}
        steps, res = iter(steps), iter(results)
        with mock.patch.object(cli_make.goal, "snapshot", return_value={"owned": {}}), \
                mock.patch.object(cli_make.goal, "have", return_value=0), \
                mock.patch.object(cli_make.goal, "next_step", side_effect=lambda *a: next(steps)), \
                mock.patch.object(cli_make, "execute", side_effect=lambda *a, **k: next(res)) as ex, \
                mock.patch.object(cli_make.situation, "to_main") as tm:
            m = cli_make._Maker(bot, None, mock.MagicMock(), None, "옷감", 6, check).run()
        return m, ex, tm, bot

    ALTER = {"kind": "alter", "name": "옷감", "runs": 1, "wanted": 2, "queued": 0, "why": "옷감 1건 가공 등록"}

    def test_alter_wait_collect_done(self):
        steps = [self.ALTER, {**self.ALTER, "queued": 1}, {"kind": "wait", "seconds": 40, "why": "기다림"},
                 {"kind": "collect", "name": "옷감", "facility": "옷감 가공 시설"}, {"kind": "done"}]
        ok = ExecResult(True, 0, wings_spent=5)
        m, ex, tm, bot = self._run(steps, [ok, ok, ExecResult(True, 0)])
        self.assertTrue(m.ok)
        self.assertEqual(m.wings, 10)
        self.assertEqual([c.args[3] for c in ex.call_args_list],
                         ["execute_altering", "execute_altering", "complete_altering_work"])
        self.assertEqual(tm.call_count, 3)  # 명령마다 먼저 메인 화면
        self.assertIn(mock.call(20), bot.sleep.call_args_list)  # 기다림은 20초씩 끊어 다시 본다

    def test_same_step_repeating_stops(self):
        m, ex, _, _ = self._run([self.ALTER] * 6, [ExecResult(True, 0)] * 6)
        self.assertEqual(m.kind, cli_make.FAILED)
        self.assertIn("진전이 없음", m.why)
        self.assertEqual(ex.call_count, 4)

    def test_paid_call_cap(self):
        steps = [self.ALTER, {**self.ALTER, "queued": 1}]
        m, ex, _, _ = self._run(steps, [ExecResult(True, 0, wings_spent=5)], max_calls=1)
        self.assertIn("1번을 넘음", m.why)
        self.assertEqual((ex.call_count, m.wings), (1, 5))

    def test_collect_is_free(self):
        steps = [{"kind": "collect", "name": "옷감"}, {"kind": "collect", "name": "철괴"}, {"kind": "done"}]
        m, _, _, _ = self._run(steps, [ExecResult(True, 0)] * 2, max_calls=0)
        self.assertTrue(m.ok)

    def test_deadline(self):
        with mock.patch.object(cli_make, "SLACK", -1):
            m, ex, _, _ = self._run([self.ALTER], check=quick.Check(True, sec=0, calls=0))
        self.assertIn("시간이 지남", m.why)
        ex.assert_not_called()

    def test_blocked_retries_once_after_screen(self):
        steps = [self.ALTER, {"kind": "done"}]
        m, ex, tm, _ = self._run(steps, [ExecResult(False, 1, "blocked", wings_spent=5), ExecResult(True, 0, wings_spent=0)])
        self.assertTrue(m.ok)
        self.assertEqual((ex.call_count, tm.call_count, m.wings), (2, 2, 5))  # 막혀도 나간 날개는 센다

    def test_collect_not_ready_waits(self):
        steps = [{"kind": "collect", "name": "옷감"}, {"kind": "done"}]
        m, _, _, bot = self._run(steps, [ExecResult(False, 1, "not_completed_yet")])
        self.assertTrue(m.ok)
        bot.sleep.assert_any_call(cli_make.COLLECT_RETRY)

    def test_refused_stops(self):
        m, _, _, _ = self._run([self.ALTER], [ExecResult(False, 1, "not_enough_ingredient", ko={"text": "재료 부족"})])
        self.assertEqual(m.kind, cli_make.FAILED)
        self.assertIn("재료 부족", m.why)

    def test_equipment_counted_by_crafts(self):
        # 장비는 get_items 에 안 나와 보유량이 늘 0 — 만든 개수로 세서 목표(6)에 닿으면 그만 만든다 (2026-11-28 장갑 7개)
        bot = mock.MagicMock()
        bot.cfg = {"arbeit": {"alter_max_sec": 300, "make_max_calls": 10}}
        craft = {"kind": "craft", "name": "옷감", "product": "옷감", "runs": 6, "batch": 3, "per": 1, "why": "옷감 3회 제작"}
        seen = []

        def step(snap, name, target):
            seen.append(snap["owned"].get(name, 0))
            return {"kind": "done"} if snap["owned"].get(name, 0) >= target else craft

        made = [ExecResult(True, 0, data={"result": "completed", "rewards": [{"DisplayName": "옷감", "Count": 3}]}),
                ExecResult(True, 0, data={"result": "completed"})]   # 본문에 개수가 없으면 회수 × 1회당 개수
        with mock.patch.object(cli_make.goal, "snapshot", side_effect=lambda *a, **k: {"owned": {}}),                 mock.patch.object(cli_make.goal, "have", return_value=0),                 mock.patch.object(cli_make.goal, "next_step", side_effect=step),                 mock.patch.object(cli_make, "execute", side_effect=made) as ex,                 mock.patch.object(cli_make.situation, "to_main"):
            m = cli_make._Maker(bot, None, mock.MagicMock(), None, "옷감", 6, quick.Check(True, sec=90, calls=2)).run()
        self.assertTrue(m.ok)
        self.assertEqual(seen, [0, 3, 6])
        self.assertEqual(ex.call_count, 2)

    def test_produced(self):
        self.assertEqual(cli_make.produced({"rewards": [{"DisplayName": "장갑", "Count": 2}],
                                            "criticalRewards": [{"DisplayName": "장갑", "Count": 1}]}, "장갑", 9), 3)
        self.assertEqual(cli_make.produced({"rewards": [{"DisplayName": "다른 것", "Count": 2}]}, "장갑", 4), 4)
        self.assertEqual(cli_make.produced(None, "장갑", 4), 4)

    def test_unplanned_block_stops(self):
        m, ex, _, _ = self._run([{"kind": "blocked", "reason": "stuck", "message": "기다려도 안 풀림"}])
        self.assertIn("기다려도 안 풀림", m.why)
        ex.assert_not_called()


class WatchedTest(unittest.TestCase):
    def test_stop_cancels_command(self):
        """F12: 숙제의 CLI 연결은 화면 F12 가 못 끊는다 → 지켜보다 끊는다 (Connector.cancel)."""
        gate, cli, bot = threading.Event(), mock.MagicMock(), mock.MagicMock()
        cli.cancel.side_effect = gate.set  # 끊으면 명령이 끝난다
        calls = [0]

        def sleep(*_):
            calls[0] += 1
            if calls[0] == 3:
                raise StopRequested()
        bot.sleep.side_effect = sleep
        with self.assertRaises(StopRequested):
            cli_make._watched(bot, cli, lambda: gate.wait(5) and ExecResult(False, -1, "cancelled"))
        cli.cancel.assert_called_once()
        bot.no_interrupt.assert_called_once()  # 도는 동안 끼어들기 없음

    def test_command_error_is_step_failure(self):
        def boom():
            raise ValueError("깨짐")
        r = cli_make._watched(mock.MagicMock(), mock.MagicMock(), boom)
        self.assertEqual((r.ok, r.error), (False, "exception"))


class MakeTest(unittest.TestCase):
    def setUp(self):
        craft.configure(ROOT / "state", ROOT / "data", None)
        self.bot = mock.MagicMock()
        self.bot.cfg = {"arbeit": {"alter_max_sec": 300, "make_max_calls": 10}}

    def test_any_item_fails_nothing_made(self):
        checks = iter([quick.Check(True), quick.Check(False, quick.LONG, "가공 1시간 걸림")])
        with mock.patch.object(cli_make.goal, "snapshot", return_value={"owned": {}}), \
                mock.patch.object(cli_make.quick, "check", side_effect=lambda *a: next(checks)), \
                mock.patch.object(cli_make, "_Maker") as maker:
            m = cli_make.make(self.bot, {"옷감": 3, "말린 찻잎": 3})
        self.assertEqual((m.ok, m.kind), (False, quick.LONG))
        self.assertIn("말린 찻잎", m.why)
        maker.assert_not_called()

    def test_target_adds_to_owned(self):
        """목표 보유량 = 지금 보유(가방+보관함) + 모자란 개수 — 보관함에 있어도 새로 만든다."""
        with mock.patch.object(cli_make.goal, "snapshot", return_value={"owned": {"옷감": 2}}), \
                mock.patch.object(cli_make.quick, "check", return_value=quick.Check(True)) as qc, \
                mock.patch.object(cli_make, "_Maker") as maker:
            maker.return_value.run.return_value = cli_make.Made(True, wings=10)
            m = cli_make.make(self.bot, {"옷감": 3})
        self.assertEqual(qc.call_args.args[2], 5)
        self.assertEqual((m.ok, m.wings), (True, 10))

    def test_stale_snapshot_does_nothing(self):
        with mock.patch.object(cli_make.goal, "snapshot", return_value={"owned": {}, "stale": True}), \
                mock.patch.object(cli_make, "_Maker") as maker:
            self.assertEqual(cli_make.make(self.bot, {"옷감": 3}).kind, cli_make.FAILED)
        maker.assert_not_called()


def job(*objectives):
    return {"title": "x", "objectives": [{"Description": d, "IsCompleted": False} for d in objectives]}


class ArbeitItemsTest(unittest.TestCase):
    def setUp(self):
        craft.configure(ROOT / "state", ROOT / "data", None)

    def test_short_counts(self):
        j = job(f"옷감 {arbeit.HAVE} 2/6", f"찻잎 {arbeit.HAVE} 0/30", "옷감 가공 0/2")
        self.assertEqual(arbeit.short_counts(j), {"옷감": 4, "찻잎": 30})  # 가공 동작 조건은 '보유' 가 아니다

    def test_made_missing(self):
        j = job(f"옷감 {arbeit.HAVE} 0/6", f"찻잎 {arbeit.HAVE} 0/30", f"달걀프라이 {arbeit.HAVE} 0/3",
                f"모르는 물건 {arbeit.HAVE} 0/1")
        # 가공품·제작품은 만든다, 채집품은 게임 안 채집(무료), 표에 없는 것은 모른다
        self.assertEqual(arbeit.made_missing(j, {"찻잎"}), {"옷감": 6, "달걀프라이": 3})

    def test_short_of_with_counts_makes(self):
        from mabi import monitor
        bot = mock.MagicMock()
        bot.cfg = {"arbeit": {"alter_max_sec": 300}}
        ctx = monitor.Ctx("arbeit", "일", job=True)
        with mock.patch.object(arbeit, "gatherable", return_value={"찻잎"}):
            r = arbeit.short_of(bot, ctx, ["달걀프라이", "찻잎"], {"달걀프라이": 3, "찻잎": 10})
        self.assertEqual(r.result, "make")
        self.assertEqual(bot.marks.arb_make, {"달걀프라이": 3})  # 채집품은 만들지 않는다
        with mock.patch.object(arbeit, "gatherable", return_value={"찻잎"}):  # 개수를 모르면 예전 규칙
            self.assertIn("채집으로 못 구하는", arbeit.short_of(bot, ctx, ["달걀프라이"], {}))


class RoundMakeTest(unittest.TestCase):
    def setUp(self):
        craft.configure(ROOT / "state", ROOT / "data", None)
        r = self.r = arbeit._Round.__new__(arbeit._Round)
        r.bot, r.done, r.skipped, r.stuck, r.save = mock.MagicMock(), [], {}, [], mock.MagicMock()
        r.bot.marks.arb_make = None

    def _go(self, made, objectives=(f"옷감 {arbeit.HAVE} 0/6",)):
        with mock.patch.object(arbeit, "gatherable", return_value=set()), \
                mock.patch.object(arbeit.cli_make, "make", return_value=made) as mk:
            return self.r.make_or_skip(job(*objectives)), mk

    def test_made_then_goes(self):
        ok, mk = self._go(cli_make.Made(True, wings=15))
        self.assertTrue(ok)
        mk.assert_called_once_with(self.r.bot, {"옷감": 6})
        self.assertEqual((self.r.skipped, self.r.stuck), ({}, []))

    def test_long_skips(self):
        ok, _ = self._go(cli_make.Made(False, quick.LONG, "옷감: 가공 6분 걸림"))
        self.assertFalse(ok)
        self.assertEqual(self.r.skipped, {"x": "가공이 오래 걸림"})

    def test_failed_midway_is_stuck(self):
        ok, _ = self._go(cli_make.Made(False, cli_make.FAILED, "조회가 안 됨"))
        self.assertFalse(ok)
        self.assertEqual(self.r.stuck, ["x"])  # 다음 실행 때 다시 (걸어 둔 가공은 받기만)

    def test_gather_only_goes_without_make(self):
        with mock.patch.object(arbeit, "gatherable", return_value={"찻잎"}), \
                mock.patch.object(arbeit.cli_make, "make") as mk:
            self.assertTrue(self.r.make_or_skip(job(f"찻잎 {arbeit.HAVE} 0/30")))
        mk.assert_not_called()

    def test_popup_make_then_once_more(self):
        """'필요한 아이템이 없습니다' 에서 정한 물품을 만들고 한 번 더 진행 — 또 모자라면 그만."""
        r = self.r

        def work(bot, title):
            bot.marks.arb_make = {"달걀프라이": 3}
            return "make"
        results = iter(["done"])
        with mock.patch.object(arbeit, "_work", side_effect=lambda *a: work(*a) if not r.bot.marks.made else next(results)), \
                mock.patch.object(arbeit.cli_make, "make", side_effect=lambda *a: setattr(r.bot.marks, "made", True)
                                  or cli_make.Made(True)) as mk, \
                mock.patch.object(arbeit, "_press_progress", return_value=True) as press:
            r.bot.marks.made = False
            self.assertEqual(r.work("x"), "done")
        mk.assert_called_once_with(r.bot, {"달걀프라이": 3})
        press.assert_called_once()
        with mock.patch.object(arbeit, "_work", side_effect=work), \
                mock.patch.object(arbeit.cli_make, "make", return_value=cli_make.Made(True)), \
                mock.patch.object(arbeit, "_press_progress", return_value=True):
            self.assertEqual(r.work("x"), "short")
        self.assertIsNone(r.bot.marks.arb_make)

    def test_restore_rechecks_make_skips(self):
        r = self.r
        r.book = {"skipped": {"x": "가공이 오래 걸림", "y": "전달 물품 부족"}}
        tracked = [job(f"옷감 {arbeit.HAVE} 0/6"), {**job(f"달걀프라이 {arbeit.HAVE} 0/3"), "title": "y"}]
        with mock.patch.object(arbeit, "accepted", return_value=tracked), \
                mock.patch.object(arbeit, "gatherable", return_value=set()), \
                mock.patch.object(arbeit.cli_make, "check", return_value=cli_make.Made(True)) as chk:
            r.restore_skipped()
        self.assertEqual(r.skipped, {"y": "전달 물품 부족"})  # 물품 부족은 사람 몫 — 다시 보지 않는다
        chk.assert_called_once_with(r.bot, {"옷감": 6})


if __name__ == "__main__":
    unittest.main()
