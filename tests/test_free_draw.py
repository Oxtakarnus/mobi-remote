"""캐시샵 매일 무료 상품 (mabi.freedraw 표·판정, mabi.tasks.free_draw 반복)."""
import types
import unittest
from unittest import mock

from mabi import freedraw as F
from mabi.exceptions import CannotProceed
from mabi.tasks import free_draw

TABLE = {"jobs": {"HighHealer": "힐러", "Knight": "기사"}, "items": {
    "1": {"kind": "costume", "name": "힐러 뱅글", "rarity": "Common", "job": "HighHealer", "part": "장갑", "ref": "x"},
    "2": {"kind": "costume", "name": "힐러 뱅글", "rarity": "Rare", "job": "HighHealer", "part": "장갑", "ref": "x"},
    "3": {"kind": "costume", "name": "기사 투구", "rarity": "Elite", "job": "Knight", "part": "투구", "ref": "x"},
    "4": {"kind": "dye", "name": "지정 염색약", "rarity": "Rare", "color": "#718C41", "ref": F.FIXED_DYE},
    "5": {"kind": "item", "name": "미가공 골드 원석", "rarity": "Rare", "amount": 10, "ref": "RawGoldStone"},
    "6": {"kind": "item", "name": "정령의 흔적", "rarity": "Uncommon", "amount": 392, "ref": "SpiritTrace"},
    "7": {"kind": "money", "name": "하트 토큰", "rarity": None, "amount": 5, "ref": "Coin_SouthRegionToken"},
    "8": {"kind": "item", "name": "에픽 촉매", "rarity": "Epic", "amount": 1, "ref": "AlchemyCatalyst_04"},
}}
IT = TABLE["items"]


class JudgeTest(unittest.TestCase):
    def test_symbol_id(self):
        # 시트 preload 의 행 id — md5 앞 4바이트 부호 있는 정수의 절댓값 (음수도 양수로)
        self.assertEqual(F.symbol_id("FreeDraw_Common_Fashion_HighHealer_Hand"), F.symbol_id("FreeDraw_Common_Fashion_HighHealer_Hand"))
        self.assertGreaterEqual(F.symbol_id("RedElixir"), 0)

    def test_costume_min_rarity(self):
        t = {"type": "costume", "name": "힐러 뱅글", "min": "Uncommon"}
        self.assertFalse(F.wanted(IT["1"], t))
        self.assertTrue(F.wanted(IT["2"], t))
        self.assertFalse(F.wanted(IT["4"], t))

    def test_dye_color(self):
        self.assertTrue(F.wanted(IT["4"], {"type": "dye", "color": "#718c41"}))
        self.assertFalse(F.wanted(IT["4"], {"type": "dye", "color": "#000000"}))

    def test_special_any_target(self):
        self.assertEqual(F.special(IT["5"]), "특수 물품")
        self.assertEqual(F.special(IT["8"]), "특수 물품")
        self.assertEqual(F.special(IT["3"]), "엘리트 이상")
        for k in ("1", "2", "4", "6", "7"):
            self.assertIsNone(F.special(IT[k]), k)

    def test_judge_prefers_target(self):
        t = {"type": "dye", "color": "#718C41"}
        self.assertEqual(F.judge([IT["3"], IT["4"], IT["6"]], t), (1, "목표"))
        self.assertEqual(F.judge([IT["6"], IT["5"], None], t), (1, "특수 물품"))
        self.assertIsNone(F.judge([IT["1"], IT["6"], IT["7"]], t))

    def test_choices(self):
        c = F.choices(TABLE)
        self.assertEqual([x["name"] for x in c["costumes"]], ["기사 투구", "힐러 뱅글"])  # 같은 이름은 한 줄, 직업 이름은 한국어
        self.assertEqual(c["costumes"][1]["job"], "힐러")
        self.assertEqual(c["colors"], ["#718C41"])
        self.assertEqual([r["key"] for r in c["rarities"]], ["Common", "Rare", "Elite"])

    def test_label(self):
        self.assertEqual(F.label(IT["2"]), "힐러 뱅글 (레어)")
        self.assertEqual(F.label(IT["4"]), "지정 염색약 #718C41")
        self.assertEqual(F.label(IT["6"]), "정령의 흔적 ×392")
        self.assertEqual(F.label(None), "모르는 상품")


class FakePackets:
    """누를 때마다 script 의 다음 세 칸을 shop.free_draw 로 쌓는다. 'fail' = 거절, None = 응답 없음."""

    def __init__(self, script):
        self.script, self.seq, self.recent, self.ok = list(script), 0, [], True

    def mark(self):
        return self.seq

    def press(self):
        r = self.script.pop(0) if self.script else None
        if r == "fail":
            self.add("shop.free_draw_renew_fail", {})
        elif r is not None:
            self.add("shop.free_draw", dict(zip(("slot1", "slot2", "slot3"), r)))

    def add(self, key, vals):
        self.seq += 1
        self.recent.append(types.SimpleNamespace(seq=self.seq, key=key, vals=vals))

    def wait(self, keys, timeout, after=None):
        keys = {keys} if isinstance(keys, str) else set(keys)
        return next((s for s in self.recent if s.seq > after and s.key in keys), None)


class FakeBot:
    def __init__(self, script):
        self.packets, self.pressed = FakePackets(script), 0
        self.log = types.SimpleNamespace(info=lambda m: None)

    def click_xy(self, x, y):
        self.pressed += 1
        self.packets.press()

    def check_stop(self):
        pass

    def snapshot(self, tag):
        return types.SimpleNamespace(name=tag)


class RepeatTest(unittest.TestCase):
    def run_it(self, script, target, limit=10, button=(1570, 562)):
        bot, seen = FakeBot(script), []
        with mock.patch.object(free_draw, "renew_button", return_value=button):
            try:
                return free_draw.repeat(bot, TABLE, target, limit, lambda n, names: seen.append(names)), bot, seen
            except CannotProceed as e:
                return str(e), bot, seen

    def test_until_target(self):
        got, bot, seen = self.run_it([(1, 6, 7), (6, 2, 7)], {"type": "costume", "name": "힐러 뱅글", "min": "Rare"})
        self.assertEqual(got, {"tries": 2, "slot": 1, "why": "목표", "item": "힐러 뱅글 (레어)"})
        self.assertEqual(seen[0], ["힐러 뱅글 (일반)", "정령의 흔적 ×392", "하트 토큰 ×5"])
        self.assertEqual(bot.pressed, 2)

    def test_special_stops_any_target(self):
        got, bot, _ = self.run_it([(1, 6, 7), (6, 7, 5)], {"type": "dye", "color": "#000000"})
        self.assertEqual((got["slot"], got["why"]), (2, "특수 물품"))

    def test_limit(self):
        got, bot, _ = self.run_it([(1, 6, 7)] * 5, {"type": "none"}, limit=3)
        self.assertEqual(got, {"tries": 3, "slot": None})
        self.assertEqual(bot.pressed, 3)

    def test_rejected_stops(self):
        got, bot, _ = self.run_it([(1, 6, 7), "fail"], {"type": "none"})
        self.assertIn("갱신 거절", got)
        self.assertEqual(bot.pressed, 2)

    def test_no_answer_stops(self):
        # 확인 창이 떴거나 창이 닫혔으면 더 누르지 않는다
        got, bot, _ = self.run_it([None, (1, 6, 7)], {"type": "none"})
        self.assertIn("바뀌지 않음", got)
        self.assertEqual(bot.pressed, 1)

    def test_no_window(self):
        got, bot, _ = self.run_it([], {"type": "none"}, button=None)
        self.assertIn("열려 있지 않음", got)
        self.assertEqual(bot.pressed, 0)

    def test_no_packets(self):
        bot = FakeBot([])
        bot.packets.ok = False
        with mock.patch.object(free_draw, "renew_button", return_value=(1, 1)):
            with self.assertRaises(CannotProceed):
                free_draw.repeat(bot, TABLE, {"type": "none"}, 5)
        self.assertEqual(bot.pressed, 0)


if __name__ == "__main__":
    unittest.main()
