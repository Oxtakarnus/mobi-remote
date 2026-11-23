"""게임이 위에 띄우는 창(ui.json covers — 연속 실행 제한 창)이 가리는 자리를 판단에 쓰지 않는가.

새 글자 영역·그림 ROI·설정 영역을 그 자리에 두면 CoversTest 가 걸린다 — 그 자리 밖의 신호를 찾거나, 판단에 안 쓰는 것이면
ui.json covered_ok 에 까닭을 적는다. 나머지는 그 자리 대신 쓰는 신호(입장 창·전멸·결과 창)가 맞게 읽히는지와
창 감지(run_limit_shown — 게임 다시 켜기의 신호)를 본다.
"""
import json
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from mabi import gamedata as gd
from mabi.tasks import entry
from mabi.exceptions import CannotProceed

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
RELATIVE = ("charselect.", "daily_mission.card_title_offset")  # 카드·버튼 기준 상대 좌표 — 화면 자리가 아니다


def _config_rects() -> dict:
    def walk(d, pre=""):
        for k, v in d.items():
            if isinstance(v, dict):
                yield from walk(v, f"{pre}{k}.")
            elif isinstance(v, list) and len(v) == 4 and all(isinstance(i, int) for i in v):
                yield f"{pre}{k}", v
    cfg = tomllib.loads((ROOT / "config.default.toml").read_text(encoding="utf-8"))
    return {f"config/{k}": v for k, v in walk(cfg) if not k.startswith(RELATIVE)}


def _rects() -> dict:
    """화면 자리 이름 → [x, y, 너비, 높이]: ui.json regions(덮는 창 자신 빼고) · 그림 ROI · 설정 영역."""
    ui = json.loads((ROOT / "data" / "ui.json").read_text(encoding="utf-8"))
    out = {k: v for k, v in ui["regions"].items() if k not in gd.covers()}
    index = json.loads((ROOT / "templates" / "index.json").read_text(encoding="utf-8"))
    out.update({f"templates/{k}": v["roi"] for k, v in index.items() if isinstance(v, dict) and v.get("roi")})
    out.update(_config_rects())
    return out


def _frame(name):
    import cv2
    import numpy as np
    p = FIXTURES / name
    if not p.exists():
        raise unittest.SkipTest(f"시험 그림 없음: {name}")
    return cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_COLOR)


class CoversTest(unittest.TestCase):
    def test_run_limit_popup_is_a_cover(self):
        self.assertIn("run_limit_popup", gd.covers())  # 2026-11-10 친구 스샷으로 잰 자리 (x 701~1218, y 39~236)

    def test_no_unlisted_overlap(self):
        ok = gd.covered_ok()
        bad = {k: (r, gd.covering(r)) for k, r in _rects().items() if gd.covering(r) and k not in ok}
        self.assertEqual(bad, {}, "덮는 창 자리와 겹친다 — 그 자리 밖의 신호로 판단하거나, 판단에 안 쓰면 "
                                  "data/ui.json covered_ok 에 까닭을 적는다")

    def test_allowlist_is_current(self):
        rects = _rects()
        for k in gd.covered_ok():
            with self.subTest(k):
                self.assertIn(k, rects, "없는 영역 — covered_ok 에서 지운다")
                self.assertTrue(gd.covering(rects[k]), "이제 안 겹친다 — covered_ok 에서 지운다")

    def test_covering(self):
        self.assertEqual(gd.covering((960, 100, 10, 10)), ["run_limit_popup"])
        self.assertEqual(gd.covering((960, 300, 10, 10)), [])


class EntryScreenTest(unittest.TestCase):
    """어비스·레이드 입장 창 — 위쪽 탭 대신 오른쪽 아래로 본다 (tasks/entry.py)."""

    def test_entry_under_run_limit_popup(self):
        # 2026-11-10 친구 PC: 전멸 뒤 뜬 입장 창 위에 연속 실행 제한 창 — 탭 글자가 가려 74분 멈췄다
        from mabi import ocr
        from mabi.bot import run_limit_shown
        f = _frame("abyss_entry_run_limit.png")
        self.assertTrue(run_limit_shown(f))
        top = "".join(t for t, *_ in ocr.find_texts(f, gd.region("abyss_entry_top")))
        self.assertNotIn(gd.text("abyss_together"), top.replace(" ", ""))  # 탭은 못 읽는다
        self.assertEqual(entry.parse(f), entry.Entry("enter", (True, (1850, 610))))  # 그래도 입장 창 · 함께하기 · 켜짐
        self.assertEqual([t for t, *_ in ocr.find_texts(f, gd.region("abyss_entry_title"))], ["허상의 정박지"])

    def test_abyss_and_raid_entry(self):
        from mabi.bot import run_limit_shown
        f = _frame("abyss_entry_together.png")
        self.assertEqual(entry.parse(f).button, "enter")
        self.assertTrue(entry.parse(f).together)
        self.assertFalse(run_limit_shown(f))
        r = entry.parse(_frame("raid_entry_scas.png"))
        self.assertEqual((r.button, r.together), ("sail", True))

    def test_together_without_chance(self):
        # 2026-11-16: 능력치가 지옥1 기준에 못 미쳐 함께하기인데도 우연한 만남이 없는 입장 창 (위 탭·오른쪽 아래만 남긴 그림).
        # 예전엔 이것을 혼자하기로 읽어 '탭이 바뀌지 않음' 으로 실패했다 — 이제 입장 창이면 탭은 누르기만 한다
        e = entry.parse(_frame("abyss_entry_hell_together.png"))
        self.assertEqual((e.button, e.chance), ("move", None))

    def test_not_entry(self):
        import numpy as np
        self.assertIsNone(entry.parse(np.zeros((1080, 1920, 3), np.uint8)))


class SetTabTest(unittest.TestCase):
    """탭은 글자를 찾아 누르기만 한다 — 맞았는지는 입장 결과(매칭·로딩 신호)로 안다 (abyss.enter)."""

    def bot(self, popup=True):
        b = mock.Mock()
        b.run_limit_popup.return_value = popup
        b.snapshot.return_value = Path("x.png")
        return b

    def test_hidden_tab_under_popup(self):  # 제한 창이 탭을 가림 — 게임을 다시 켜야 풀린다
        bot = self.bot()
        with mock.patch.object(entry.ui_text, "find", return_value=None), self.assertRaisesRegex(CannotProceed, "가림"):
            entry.set_tab(bot, solo=False, shot="t")
        bot.click.assert_not_called()

    def test_hidden_tab_goes_on(self):  # 글자가 안 보이기만 하면 누르지 않고 간다
        bot = self.bot(popup=False)
        with mock.patch.object(entry.ui_text, "find", return_value=None):
            entry.set_tab(bot, solo=False, shot="t")
        bot.click.assert_not_called()

    def test_visible_tab_is_clicked_only(self):  # 누르기만 하고 바뀌었나는 다시 읽지 않는다
        bot = self.bot(popup=False)
        with mock.patch.object(entry.ui_text, "find", return_value=(830, 57)), \
                mock.patch.object(entry, "read", side_effect=AssertionError("탭을 다시 읽지 않는다")):
            entry.set_tab(bot, solo=True, shot="t")
        bot.click.assert_called_once_with((830, 57))

    def test_together_seen_skips_tab(self):
        """탭 앞에서 읽은 창에 '우연한 만남' 이 보이면 이미 함께하기 — 탭 글자를 읽지도 누르지도 않는다 (사용자 2026-11-23)."""
        bot = self.bot(popup=False)
        now = entry.Entry("enter", (True, (1850, 610)))
        with mock.patch.object(entry.ui_text, "find", side_effect=AssertionError("탭 글자를 읽지 않는다")):
            self.assertFalse(entry.set_tab(bot, solo=False, shot="t", now=now))
        bot.click.assert_not_called()

    def test_unsure_tab_is_clicked(self):
        """혼자하기를 원하거나, 우연한 만남이 안 보이면 (혼자하기거나 능력치 미달 — 모른다) 지금처럼 누른다."""
        for solo, now in ((True, entry.Entry("enter", (True, (1850, 610)))), (False, entry.Entry("move", None)), (False, None)):
            bot = self.bot(popup=False)
            with mock.patch.object(entry.ui_text, "find", return_value=(830, 57)):
                self.assertTrue(entry.set_tab(bot, solo=solo, shot="t", now=now))
            bot.click.assert_called_once_with((830, 57))


class DifficultyChosenTest(unittest.TestCase):
    """입장 창 난이도가 이미 골라져 있으면 누르지 않는다 — 고른 것은 빨간 테두리·글자 (entry.difficulty_chosen, 11-23)."""

    def read(self, name, region):
        from mabi import ocr
        f = _frame(name)
        return f, ocr.find_texts(f, gd.region(region))

    def chosen(self, name, region):
        f, items = self.read(name, region)
        return [t for t, x, y in items if entry.difficulty_chosen(f, items, (t, x, y))]

    def test_chosen_is_the_red_one(self):
        self.assertEqual(self.chosen("abyss_difficulty_hard2.png", "abyss_difficulty"), ["매우 어려움2"])
        self.assertEqual(self.chosen("abyss_difficulty_hell1.png", "abyss_difficulty"), ["지옥1"])  # 알약이 넓어 덜 빨갛다
        self.assertEqual(self.chosen("raid_entry_scas.png", "raid_difficulty"), ["매우 어려움"])

    def test_two_reds_is_unsure(self):  # 둘 이상 빨가면 (뒤 그림 등) 모르는 것 → 누른다
        f, items = self.read("abyss_difficulty_hard2.png", "abyss_difficulty")
        hit = next(i for i in items if i[0] == "매우 어려움2")
        x, y = next((x, y) for t, x, y in items if t == "어려움")
        both = f.copy()
        both[y - 12:y + 12, x - 40:x + 40] = (0, 40, 250)  # 빨강 (BGR)
        self.assertFalse(entry.difficulty_chosen(both, items, hit))

    def test_click_skips_chosen(self):
        """ui_text.click(chosen=...) — 골라져 있으면 누르지 않고 False, 아니면 그 글자를 눌러 True."""
        from mabi.tasks import ui_text
        bot = mock.Mock()
        bot.frame.return_value = _frame("abyss_difficulty_hard2.png")
        region = gd.region("abyss_difficulty")
        self.assertFalse(ui_text.click(bot, "매우 어려움2", region, chosen=entry.difficulty_chosen))
        bot.click.assert_not_called()
        self.assertTrue(ui_text.click(bot, "매우 어려움", region, chosen=entry.difficulty_chosen))
        self.assertEqual(bot.click.call_count, 1)


class OpenEntryTest(unittest.TestCase):
    """열린 입장 창부터 맞출 때: 탭 앞에서 읽은 창을 set_tab 에 넘기고, 난이도는 골라져 있나 보고 누른다 (11-23)."""

    def run_open(self, mod, now, solo, **kw):
        bot = mock.MagicMock()
        read = mock.Mock(return_value=now) if now else mock.Mock(side_effect=AssertionError("창을 읽지 않는다"))
        with mock.patch.object(mod.ui_text, "find", return_value=(960, 100)), \
                mock.patch.object(mod.entry, "read", read), \
                mock.patch.object(mod.entry, "set_tab") as tab, \
                mock.patch.object(mod.ui_text, "click") as click, \
                mock.patch.object(mod.entry, "chance_on") as on:
            mod.open_entry(bot, "어딘가", "매우 어려움2", at="entry", solo=solo, **kw)
        self.assertIs(click.call_args.kwargs["chosen"], entry.difficulty_chosen)
        return bot, tab, on

    def test_abyss_together(self):
        from mabi.tasks import abyss
        now = entry.Entry("enter", (True, (1850, 610)))
        bot, tab, on = self.run_open(abyss, now, solo=False)
        tab.assert_called_once_with(bot, False, "abyss", now)
        on.assert_called_once_with(bot, now)  # 버튼·스위치는 탭·난이도 뒤에 새로 읽은 창으로

    def test_raid(self):
        from mabi.tasks import raid
        now = entry.Entry("sail", (True, (1850, 610)))
        bot, tab, on = self.run_open(raid, now, solo=False)
        tab.assert_called_once_with(bot, False, "raid", now)
        on.assert_called_once_with(bot)
        bot, tab, on = self.run_open(raid, None, solo=True)  # 혼자하기는 탭 앞에서 창을 읽지 않는다 (알 길이 없다)
        tab.assert_called_once_with(bot, True, "raid", None)
        on.assert_not_called()


class WipeTest(unittest.TestCase):
    """전멸은 첫 줄('전멸하였습니다' — 가려지는 자리) 대신 그 아래 '재도전' 줄로 본다."""

    def texts(self, name):
        from mabi import ocr
        return "".join(t for t, *_ in ocr.find_texts(_frame(name), gd.region("abyss_wiped"))).replace(" ", "")

    def test_wiped(self):
        self.assertIn(gd.text("abyss_wiped"), self.texts("abyss_wiped.png"))

    def test_down_is_not_wiped(self):  # 혼자 쓰러짐 — '행동불능 · 부활 제한 구역입니다'
        self.assertNotIn(gd.text("abyss_wiped"), self.texts("abyss_dead_revives3.png"))


class ResultConfirmTest(unittest.TestCase):
    """레이드·필드 보스 결과 창은 위쪽 '처치 완료'(창 자리 y 약 216) 대신 아래 가운데 '확인' 으로 본다 (clear.confirm_text).
    2026-11-11 화이트 서큐버스 결과 창 — 버튼 띠만 남긴 그림."""

    def test_raid_result(self):
        from mabi.tasks.clear import confirm_text
        x, y = confirm_text(_frame("raid_result_confirm.png"))
        self.assertTrue(abs(x - 959) < 15 and abs(y - 1009) < 15)


class RunLimitShownTest(unittest.TestCase):
    """제한 창 감지는 '종료' 버튼 색을 먼저 본다 — 끊는 자리마다 부르므로 창이 없으면 글자를 읽지 않는다."""

    def test_popup(self):
        from mabi.bot import run_limit_shown
        self.assertTrue(run_limit_shown(_frame("abyss_entry_run_limit.png")))

    def test_no_popup_skips_ocr(self):
        from mabi.bot import run_limit_shown
        with mock.patch("mabi.ocr.find_texts") as ocr:
            for name in ("abyss_entry_together.png", "raid_entry_scas.png", "raid_result_confirm.png"):
                self.assertFalse(run_limit_shown(_frame(name)), name)
        ocr.assert_not_called()


if __name__ == "__main__":
    unittest.main()
