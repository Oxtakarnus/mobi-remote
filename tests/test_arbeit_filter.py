import unittest
from pathlib import Path
from unittest import mock

from mabi import craft
from mabi.bot import Marks
from mabi.tasks import arbeit

ROOT = Path(__file__).resolve().parent.parent


def quest(title, *objectives):
    return {"QuestTitle": title, "Source": "pinned_sub",
            "Objectives": [{"Description": d, "IsCompleted": done} for d, done in objectives]}


class AcceptedTest(unittest.TestCase):
    def test_pinned_side_quest_is_not_arbeit(self):
        """고정해 둔 사이드 퀘스트도 pinned_sub — 아르바이트 탭에서 본 제목만 아르바이트로 본다."""
        bot = mock.Mock()
        bot.state.query.return_value = [quest("[긴급 의뢰] 사이드"), quest("튼튼한 나무가 필요해")]
        bot.marks = Marks(arb_titles={"튼튼한 나무가 필요해"})
        self.assertEqual([j["title"] for j in arbeit.accepted(bot)], ["튼튼한 나무가 필요해"])
        self.assertEqual(len(arbeit.accepted(bot, raw=True)), 2)

    def test_unfiltered_before_panel_seen(self):
        bot = mock.Mock(spec=["state", "marks"])
        bot.marks = Marks()
        bot.state.query.return_value = [quest("[긴급 의뢰] 사이드")]
        self.assertEqual(len(arbeit.accepted(bot)), 1)


class AlterMissingTest(unittest.TestCase):
    def test_alter_products_only(self):
        craft.configure(ROOT / "state", ROOT / "data", None)
        job = {"title": "x", "objectives": [
            {"Description": f"두유 {arbeit.HAVE} 0/3", "IsCompleted": False},       # 식재료 가공
            {"Description": f"찻잎 {arbeit.HAVE} 2/30", "IsCompleted": False},      # 채집품
            {"Description": f"말린 찻잎 {arbeit.HAVE} 3/3", "IsCompleted": True},   # 다 모음
        ]}
        self.assertEqual(arbeit.alter_missing(job), ["두유"])
        # 가공품이어도 채집으로 구할 수 있으면 건너뛰지 않는다 (2026-10-30 멀리 다녀오실 분 — 깔끔 버섯 포자)
        self.assertEqual(arbeit.alter_missing(job, {"두유"}), [])

    def test_round_with_unknown_gatherable(self):
        # 채집 목록 조회가 안 되면(None) 빈 목록으로 본다 — 예전엔 TypeError 로 아르바이트가 오류로 끝났다 (점검 2026-11-22)
        craft.configure(ROOT / "state", ROOT / "data", None)
        job = {"title": "x", "objectives": [{"Description": f"두유 {arbeit.HAVE} 0/3", "IsCompleted": False}]}
        r = arbeit._Round.__new__(arbeit._Round)
        r.bot, r.skipped, r.save = mock.MagicMock(), {}, mock.MagicMock()
        with (mock.patch.object(arbeit, "gatherable", return_value=None),
              mock.patch.object(arbeit, "quick_alter", return_value=True)):
            self.assertEqual(r.alter_or_skip(job), ["두유"])


class QuickAlterTest(unittest.TestCase):
    """가공이 2분(alter_max_sec) 미만인 가공품만 아르바이트에서 가공한다 (사용자 규칙 2026-10-30)."""

    def test_limit(self):
        craft.configure(ROOT / "state", ROOT / "data", None)
        bot = mock.MagicMock()
        bot.cfg = {"arbeit": {"alter_max_sec": 120}}
        self.assertTrue(arbeit.quick_alter(bot, ["옷감"]))            # 45초
        self.assertTrue(arbeit.quick_alter(bot, ["철괴(철 광석)"]))   # 가공 시설 창 카드 = 레시피 이름 (30초)
        self.assertTrue(arbeit.quick_alter(bot, ["철괴"]))            # 물품 이름
        self.assertFalse(arbeit.quick_alter(bot, ["깔끔 버섯 포자"]))  # 1500초
        self.assertFalse(arbeit.quick_alter(bot, ["옷감", "깔끔 버섯 포자"]))


class HowtoRowTest(unittest.TestCase):
    """'구하는 방법' 에서 가공 시설 줄보다 채집 줄을 고른다 (가공 시설이 맨 위여도)."""

    def pick(self, texts):
        from types import SimpleNamespace
        from mabi.monitor import handlers
        bot = mock.MagicMock()
        bot.cfg = {"arbeit": {"howto_area": [1200, 240, 720, 700]}}
        ctx = mock.MagicMock(n={}, alter=())
        with (mock.patch.object(handlers.ocr, "find_texts", return_value=texts),
              mock.patch.object(handlers, "fast_travel")):
            handlers.howto(bot, ctx, SimpleNamespace(frame=None))
        return bot.click.call_args[0][0]

    def test_gather_row_over_facility(self):
        rows = [("구하는 방법", 1290, 160), ("약품", 1340, 275), ("가공 시설", 1420, 275),
                ("깔끔 버섯", 1360, 369), ("977m", 1790, 369), ("얼음 협곡 임무 전리품", 1420, 463)]
        self.assertEqual(self.pick(rows), (1360, 369))

    def test_alter_job_takes_facility(self):
        from types import SimpleNamespace
        from mabi.monitor import handlers
        bot = mock.MagicMock()
        bot.cfg = {"arbeit": {"howto_area": [1200, 240, 720, 700]}}
        ctx = mock.MagicMock(n={}, alter=("옷감",))
        rows = [("양털 깎기", 1360, 275), ("옷감", 1340, 369), ("가공 시설", 1420, 369)]
        with mock.patch.object(handlers.ocr, "find_texts", return_value=rows):
            handlers.howto(bot, ctx, SimpleNamespace(frame=None))
        self.assertEqual(bot.click.call_args[0][0][1], 369)

    def test_facility_only(self):
        self.assertEqual(self.pick([("약품 가공 시설", 1390, 369)]), (1390, 369))


class HowtoShopTest(unittest.TestCase):
    """상점 줄(카트 아이콘)은 고르지 않는다 — 실제 화면으로 (2026-11-06 '갑작스런 주문' 밀가루)."""

    def run_on(self, png, alter=()):
        import cv2
        from types import SimpleNamespace
        from mabi.monitor import handlers
        from mabi.vision import Vision
        bot = mock.MagicMock()
        bot.cfg = {"arbeit": {"howto_area": [1200, 240, 720, 700]}}
        bot.vision = Vision(ROOT / "templates")
        ctx = mock.MagicMock(n={}, alter=alter)
        frame = cv2.imread(str(ROOT / "tests" / "fixtures" / png))
        with mock.patch.object(handlers, "fast_travel"), mock.patch.object(handlers, "_shot", return_value="x.png"):
            out = handlers.howto(bot, ctx, SimpleNamespace(frame=frame))
        return out, bot.click.call_args[0][0] if bot.click.called else None

    def test_shop_rows_skipped_goes_to_facility(self):
        # 식재료 가공 시설 · 카페 · 레스토랑(물물교환) · 방앗간(물물교환) → 상점은 빼고 가공 시설로 (가공 창이 건너뜀을 정한다)
        out, at = self.run_on("howto_alter_or_shop.png")
        self.assertEqual(out, "구하는 방법 → 시설")
        self.assertLess(abs(at[1] - 275), 30)

    def test_gather_rows_kept(self):
        out, at = self.run_on("howto_gather.png")
        self.assertEqual(out, "채집하러 감 (구하는 방법 맨 위)")
        self.assertLess(abs(at[1] - 275), 30)


if __name__ == "__main__":
    unittest.main()


class AlterGoUnknownTest(unittest.TestCase):
    """추적 칸에 없던 일을 이어 하다 가공 창이 열리면 카드 이름으로 짧은 가공인지 정한다."""

    def _run(self, ok):
        from types import SimpleNamespace
        from mabi.monitor import handlers
        bot = mock.MagicMock()
        ctx = mock.MagicMock(n={}, alter=(), alter_ok=lambda names: ok and names == ["옷감"])
        cards = [("옷감", 700, 400), ("가공 시간 45초", 900, 300)]
        with mock.patch.object(handlers.ocr, "find_texts", return_value=cards), \
                mock.patch.object(handlers, "_short_toast", return_value=True), \
                mock.patch.object(handlers, "_shot", return_value="x"), mock.patch.object(handlers, "_esc"):
            r = handlers._alter_go(bot, ctx, SimpleNamespace(frame=None))
        return r, ctx, bot

    def test_short(self):
        r, ctx, bot = self._run(True)
        self.assertEqual(ctx.alter, ("옷감",))
        self.assertEqual(bot.click.call_args[0][0], (700, 340))
        self.assertEqual(r.result, "alter_short")

    def test_long(self):
        r, ctx, bot = self._run(False)
        self.assertEqual(r.result, "alter")
        bot.click.assert_not_called()


class AlterFullTest(unittest.TestCase):
    """가공하기를 눌러도 가공 목록에 그 가공품이 늘지 않으면 (칸이 꽉 참) 그 일은 포기한다."""

    def _run(self, counts):
        from types import SimpleNamespace
        from mabi.monitor import handlers
        bot = mock.MagicMock()
        seq = iter(counts)
        bot.state.query.side_effect = lambda *_: {"works": [{"DisplayName": "옷감", "IsCompleted": True}] * next(seq)}
        ctx = mock.MagicMock(n={}, alter=("옷감",))
        with mock.patch.object(handlers, "_short_toast", return_value=False), \
                mock.patch.object(handlers, "_shot", return_value="x"), mock.patch.object(handlers, "_esc"), \
                mock.patch.object(handlers.time, "monotonic", side_effect=[0, 1, 5, 9, 13, 100, 200]):
            return handlers.alter(bot, ctx, SimpleNamespace(frame=None))

    def test_full_gives_up(self):
        r = self._run([0, 0, 0, 0, 0])
        self.assertEqual(r.result, "alter_full")

    def test_started_waits(self):
        r = self._run([0, 1, 1, 1, 1])
        self.assertEqual(r, "가공 → 받기")  # 시작됐고 (목록이 늘었고) 다 끝나 받음


def _fixture(name):
    import cv2
    import numpy as np
    return cv2.imdecode(np.fromfile(str(ROOT / "tests" / "fixtures" / name), np.uint8), cv2.IMREAD_COLOR)


class AlterWindowTest(unittest.TestCase):
    """제작 창 첫 화면이 가공 시설 창인가 — 제목을 '?' 로만 읽어도 왼쪽 위 시설 이름으로 안다 (2026-11-23 09:51)."""

    def test_title_unread_but_facility_name(self):
        from mabi.monitor import handlers
        frame = _fixture("alter_window_metal.png")
        titles = [t for t, _, _ in handlers.ocr.find_texts(frame, handlers.CRAFT_TITLE_AREA)]
        self.assertFalse(any(t.endswith(handlers.ALTER_TITLE) for t in titles))  # 그날처럼 제목은 못 읽는다
        self.assertTrue(handlers._alter_window(frame))

    def test_craft_window(self):
        from mabi.monitor import handlers
        self.assertFalse(handlers._alter_window(_fixture("craft_window_weapon.png")))

    def test_craft_handler_goes_to_alter_by_card(self):
        """제작 창 처리기가 가공 시설 창으로 알아보고, 카드 이름(레시피 이름)으로 짧은 가공을 정해 가공하러 간다."""
        from types import SimpleNamespace
        from mabi.monitor import handlers
        craft.configure(ROOT / "state", ROOT / "data", None)
        bot = mock.MagicMock()
        bot.cfg = {"arbeit": {"alter_max_sec": 120}}
        ctx = mock.MagicMock(n={}, alter=(), alter_ok=lambda names: arbeit.quick_alter(bot, names))
        with mock.patch.object(handlers, "_short_toast", return_value=False), mock.patch.object(handlers, "fast_travel"):
            r = handlers.craft(bot, ctx, SimpleNamespace(frame=_fixture("alter_window_metal.png"), hit=None))
        self.assertEqual(r, "가공하러 감")
        self.assertEqual(ctx.alter, ("철괴(철 광석)",))
        x, y = bot.click.call_args[0][0]
        self.assertLess(abs(x - 690), 30)
        self.assertLess(abs(y - 289), 30)  # 카드 이름 위 (카드 가운데)


class AlterNameTest(unittest.TestCase):
    """가공품 이름 맞추기 — 물품 이름('철괴')으로 레시피 이름('철괴(철 광석)') 카드·가공 목록을 찾는다."""

    def test_like(self):
        from mabi.monitor import handlers
        craft.configure(ROOT / "state", ROOT / "data", None)
        like = handlers._alter_like(["철괴"])
        self.assertTrue(like("철괴(철 광석)"))
        self.assertTrue(like("철괴"))
        self.assertFalse(like("강철괴"))
        self.assertFalse(like(None))
        self.assertTrue(handlers._alter_like(["철괴(철 광석)"])("철괴(철광석)"))  # 띄어쓰기만 다름

    def test_alter_go_finds_recipe_card_by_product(self):
        from types import SimpleNamespace
        from mabi.monitor import handlers
        craft.configure(ROOT / "state", ROOT / "data", None)
        bot = mock.MagicMock()
        ctx = mock.MagicMock(n={}, alter=("철괴",))
        with mock.patch.object(handlers.ocr, "find_texts", return_value=[("3", 715, 279), ("철괴(철 광석)", 690, 349)]), \
                mock.patch.object(handlers, "_short_toast", return_value=False), mock.patch.object(handlers, "fast_travel"):
            r = handlers._alter_go(bot, ctx, SimpleNamespace(frame=None))
        self.assertEqual(r, "가공하러 감")
        bot.click.assert_called_once_with((690, 289))


class AlterCollectTest(unittest.TestCase):
    """가공 칸이 꽉 차 가공이 안 걸리면 그 시설 완료분을 CLI 로 받고 한 번 더 한다 (사용자 2026-11-23). 한 일에 한 번만."""

    METAL = "금속 가공 시설"

    def _run(self, works, ok=True, tried=False):
        from types import SimpleNamespace
        from mabi.monitor import handlers
        craft.configure(ROOT / "state", ROOT / "data", None)
        bot = mock.MagicMock()
        bot.state.query.return_value = {"works": works}
        bot.state.cli.run.return_value = SimpleNamespace(ok=ok, error=None if ok else "blocked", reason=None, message="")
        ctx = mock.MagicMock(n={"alter_collect": 1} if tried else {}, alter=("철괴(철 광석)",))
        with mock.patch.object(handlers, "_short_toast", return_value=False), \
                mock.patch.object(handlers, "_shot", return_value="x"), mock.patch.object(handlers, "_esc"), \
                mock.patch.object(handlers.time, "monotonic", side_effect=[0, 1, 5, 9, 13]):
            r = handlers.alter(bot, ctx, SimpleNamespace(frame=None))
        return r, bot

    def full(self, done=True):
        return [{"DisplayName": "철괴(철 광석)", "FacilityName": self.METAL, "IsCompleted": done}] * 7

    def test_collects_and_retries(self):
        from mabi.monitor import handlers
        r, bot = self._run(self.full())
        self.assertEqual(r, "가공 칸 비움 → 다시 가공")
        bot.to_main.assert_called_once()
        bot.state.cli.run.assert_called_once_with("complete_altering_work", {"displayName": "철괴(철 광석)"},
                                                  timeout=handlers.COLLECT_TIMEOUT)

    def test_only_once_per_job(self):
        r, bot = self._run(self.full(), tried=True)
        self.assertEqual(r.result, "alter_full")
        bot.state.cli.run.assert_not_called()

    def test_in_progress_full_skips(self):
        r, bot = self._run(self.full(done=False))
        self.assertEqual(r.result, "alter_full")
        bot.state.cli.run.assert_not_called()

    def test_collect_failed_skips(self):
        r, bot = self._run(self.full(), ok=False)
        self.assertEqual(r.result, "alter_full")

    def test_facility_from_recipes(self):
        """가공 목록에 같은 가공품이 없으면 시설은 레시피 표로 — 그 시설의 다른 가공품 완료분을 받는다."""
        works = [{"DisplayName": "강철괴", "FacilityName": self.METAL, "IsCompleted": True}] * 7
        r, bot = self._run(works)
        self.assertEqual(r, "가공 칸 비움 → 다시 가공")
        bot.state.cli.run.assert_called_once_with("complete_altering_work", {"displayName": "강철괴"}, timeout=mock.ANY)


class PressProgressTest(unittest.TestCase):
    """맨 위 '진행하기' 가 아니라 이 일의 카드 — 건너뛴 일이 수락한 채 위에 남아 있다 (2026-11-07)."""

    def press(self, items, title):
        from mabi.tasks import arbeit
        bot = mock.MagicMock()
        bot.cfg = {"arbeit": {"list_pages": 1}}
        act = lambda ctx, name, do, *a, **k: do()  # noqa: E731
        with mock.patch.object(arbeit, "_buttons", return_value=items), \
                mock.patch.object(arbeit, "open_arbeit_tab"), mock.patch.object(arbeit, "_fast_travel"), \
                mock.patch.object(arbeit.monitor, "of", return_value=mock.Mock(act=act)):
            ok = arbeit._press_progress(bot, title)
        return ok, bot

    def test_picks_own_card_not_top(self):
        items = [("국경 수비대 물자 보급", 1400, 300), ("진행하기", 1700, 420),
                 ("좋아하는 버섯", 1400, 560), ("진행하기", 1700, 680), ("지원하기", 1700, 940)]
        ok, bot = self.press(items, "좋아하는 버섯")
        self.assertTrue(ok)
        bot.click.assert_called_once_with((1700, 680))

    def test_single_card_top_even_if_title_unread(self):
        items = [("??", 1400, 300), ("진행하기", 1700, 420), ("지원하기", 1700, 680)]
        ok, bot = self.press(items, "좋아하는 버섯")
        self.assertTrue(ok)
        bot.click.assert_called_once_with((1700, 420))

    def test_two_cards_title_not_found_does_not_press(self):
        items = [("국경 수비대 물자 보급", 1400, 300), ("진행하기", 1700, 420),
                 ("??", 1400, 560), ("진행하기", 1700, 680), ("지원하기", 1700, 940)]
        ok, bot = self.press(items, "좋아하는 버섯")
        self.assertFalse(ok)
        bot.click.assert_not_called()


class AlterNeedTest(unittest.TestCase):
    """가공 목록 화면(카드 없음)에 조건을 모르고 왔으면 지금 조건(CLI)으로 짧은 가공인지 정한다
    (2026-11-23 07:00 '옷감이 필요해' — 옷감은 45초 가공인데 조건을 몰라 건너뜀)."""

    def _run(self, need, ok=True):
        from types import SimpleNamespace
        from mabi import monitor
        from mabi.monitor import handlers
        bot = mock.MagicMock()
        ctx = monitor.Ctx("arbeit", "옷감이 필요해", job=True, alter_ok=lambda names: ok, alter_need=lambda: need)
        with mock.patch.object(handlers, "_short_toast", return_value=True), \
                mock.patch.object(handlers, "_shot", return_value="x"), mock.patch.object(handlers, "_esc"), \
                mock.patch.object(handlers, "_alter_count", return_value=0):
            r = handlers.alter(bot, ctx, SimpleNamespace(frame=None))
        return r, ctx, bot

    def test_short_goes_on(self):
        r, ctx, bot = self._run(["옷감"])
        self.assertEqual(ctx.alter, ("옷감",))
        bot.key.assert_called_with("space")  # 가공하기
        self.assertEqual(r.result, "alter_short")  # (이 시험에선 재료 부족 알림이 뜬다)

    def test_long_or_unknown_skips(self):
        r, ctx, bot = self._run(["옷감"], ok=False)
        self.assertEqual((r.result, ctx.alter), ("alter", ()))
        self.assertIn("옷감", r.why)
        bot.key.assert_not_called()
        r, ctx, bot = self._run([])
        self.assertEqual(r.result, "alter")
        bot.key.assert_not_called()

    def test_job_ctx_reads_current_conditions(self):
        craft.configure(ROOT / "state", ROOT / "data", None)
        bot = mock.MagicMock()
        job = {"title": "옷감이 필요해", "objectives": [{"Description": f"옷감 {arbeit.HAVE} 0/5", "IsCompleted": False}]}
        ctx = arbeit._job_ctx(bot, "옷감이 필요해")
        with mock.patch.object(arbeit, "accepted", return_value=[job]), \
                mock.patch.object(arbeit, "gatherable", return_value=set()):
            self.assertEqual(ctx.alter_need(), ["옷감"])
        with mock.patch.object(arbeit, "accepted", return_value=[]):
            self.assertEqual(ctx.alter_need(), [])


class WaitAcceptTest(unittest.TestCase):
    """지원하기 뒤 수락 대기 — 가는 길에 다른 퀘스트 '확인' 을 넘기면 45초가 아니라 짧게만 기다린다
    (2026-11-23 07:24·08:00·09:04 — 매번 45초 서 있다가 다시 지원해 수락)."""

    def _run(self, confirm_at):
        from types import SimpleNamespace
        from mabi import monitor
        clock, n = [0.0], [0]
        bot = mock.MagicMock()
        bot.cfg = {"arbeit": {"travel_timeout": 300}}
        bot.sleep.side_effect = lambda *a: clock.__setitem__(0, clock[0] + 1)
        ctx = monitor.Ctx("arbeit", "지원하기", menus=True)

        def check(c):
            n[0] += 1
            if n[0] == confirm_at:
                c.event("confirmed")  # 처리기가 '확인' 을 눌렀다
            return SimpleNamespace(done=None, finish=None, what=arbeit.d.MAIN, idle=True)
        mon = mock.MagicMock()
        mon.check.side_effect = check
        with mock.patch("time.monotonic", side_effect=lambda: clock[0]):
            self.assertFalse(arbeit._wait_accept(bot, mon, ctx))
        return clock[0]

    def test_plain_stop_waits_full_grace(self):
        self.assertGreater(self._run(confirm_at=0), 45)

    def test_after_other_confirm_short(self):
        t = self._run(confirm_at=3)
        self.assertLess(t, 3 + arbeit.AFTER_CONFIRM_GRACE + 3)
