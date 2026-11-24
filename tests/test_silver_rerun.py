"""은동전: 도는 동안 저절로 찬 은동전으로 한 판 더 할 만큼 남으면 한 번 더 돈다."""
import unittest
from unittest import mock

from mabi import monitor
from mabi.exceptions import CannotProceed, StepTimeout
from mabi.monitor import handlers
from mabi.tasks import silver, ui_text

CFG = {"silver": {"unit": 20}}


class RerunTest(unittest.TestCase):
    def test_runs_again_when_enough_left(self):
        with mock.patch.object(silver, "_run_round", side_effect=[("첫 판", 20), ("둘째 판", 0)]) as r:
            note = silver.run(mock.Mock(), CFG)
        self.assertEqual(r.call_count, 2)
        self.assertIn("더: 둘째 판", note)

    def test_stops_when_below_unit(self):
        with mock.patch.object(silver, "_run_round", return_value=("첫 판", 19)) as r:
            self.assertEqual(silver.run(mock.Mock(), CFG), "첫 판")
        self.assertEqual(r.call_count, 1)

    def test_only_one_extra_round(self):
        with mock.patch.object(silver, "_run_round", return_value=("판", 40)) as r:
            silver.run(mock.Mock(), CFG)
        self.assertEqual(r.call_count, 2)

    def test_extra_round_blocked_keeps_first(self):
        # 첫 판은 했다 — 더 도는 판만 막히면 실패로 뒤집지 않고 한 만큼 남긴다
        with mock.patch.object(silver, "_run_round", side_effect=[("첫 판", 20), CannotProceed("막힘")]):
            note = silver.run(mock.Mock(), CFG)
        self.assertIn("첫 판", note)
        self.assertIn("더: 진행 불가 (막힘)", note)


class Daily:
    def __init__(self):
        self.data = {}

    def get(self, slot, key):
        return self.data.get(key)

    def set(self, slot, key, value):
        self.data[key] = value


ROUND_CFG = {"silver": {"unit": 20, "min_units_for_field": 1, "field_runs": 1, "dungeon": "피오드 던전",
                        "dungeon_cost": 20, "by_slot": {}}}


def make_bot(coins=73):
    bot = mock.MagicMock()
    bot.on_clear = None
    bot.character = {"slot": 4}
    bot.daily = Daily()
    bot.read_counter.return_value = coins
    bot.state.currency.return_value = None
    return bot


class BlockedTest(unittest.TestCase):
    """한 판도 못 들어가면(지도에서 장소를 못 고름 등) '남음' 이 아니라 실패 — 한 번 더 돌지도 않는다 (2026-11-14)."""

    def test_nothing_entered_is_failure(self):
        blocked = mock.Mock(side_effect=CannotProceed("지역 맵에서 '창백한 산' 을 고르지 못함"))
        dungeon = mock.Mock(side_effect=CannotProceed("지역 맵에서 '피오드 던전' 을 고르지 못함"))
        with mock.patch.object(silver, "field_once", blocked), mock.patch.object(silver, "dungeon_once", dungeon):
            with self.assertRaises(CannotProceed) as cm:
                silver.run(make_bot(), ROUND_CFG)
        msg = str(cm.exception)
        self.assertIn("은동전 73개 그대로", msg)
        self.assertIn("창백한 산", msg)
        self.assertIn("피오드 던전", msg)
        self.assertEqual((blocked.call_count, dungeon.call_count), (1, 1))  # 같은 실패를 한 바퀴 더 돌지 않는다

    def test_partly_blocked_is_not_failure(self):
        # 사냥터는 막혔지만 던전은 했다 → 실패가 아니다 (남은 건 완료 확인이 본다)
        bot = make_bot(coins=40)
        field = mock.Mock(side_effect=CannotProceed("못 고름"))
        dungeon = mock.Mock(return_value="clear")
        bot.read_counter.side_effect = [40, 0]
        with mock.patch.object(silver, "field_once", field), mock.patch.object(silver, "dungeon_once", dungeon):
            note = silver.run(bot, ROUND_CFG)
        self.assertIn("사냥터 진행 불가", note)
        self.assertIn("던전 클리어 1/1", note)


DUNGEON_ONLY = {"silver": {"unit": 20, "min_units_for_field": 1, "field_runs": 0, "dungeon": "피오드 던전",
                           "dungeon_cost": 20, "by_slot": {}}}


class OneMoreTest(unittest.TestCase):
    """계획한 마지막 던전 판 뒤 도는 사이 은동전이 차서 한 판 더 할 만큼 남았으면 나가서 지도로 다시 찾아가지 않고
    '다시 하기' 로 한 판 더 (사용자 11-24: 같은 던전을 또 돌 땐 재입장)."""

    def run_round(self, coins, left_at_reward):
        bot = make_bot(coins=coins)
        left = iter(left_at_reward)
        bot.state.currency.side_effect = lambda name: next(left) if asked else coins
        calls = []
        asked = False

        def once(bot, c, again=False, more=False):
            nonlocal asked
            calls.append((again, callable(more)))
            if callable(more):
                asked = True
                more = more()
                asked = False
            return "again" if more else "clear"
        with mock.patch.object(silver, "dungeon_once", once):
            note, _ = silver._run_round(bot, DUNGEON_ONLY)
        return note, calls

    def test_retry_when_coins_left(self):
        note, calls = self.run_round(40, [20, 5])
        # 계획 2판: 첫 판 뒤 다시 하기 → 마지막 판 보상 화면에서 20개 남음 → 다시 하기 → 셋째 판 뒤 5개라 나감
        self.assertEqual(calls, [(False, False), (True, True), (True, True)])
        self.assertIn("던전 클리어 3/3", note)

    def test_exit_when_coins_short(self):
        note, calls = self.run_round(20, [3])
        self.assertEqual(calls, [(False, True)])
        self.assertIn("던전 클리어 1/1", note)


class RewardAgainTest(unittest.TestCase):
    """보상 화면 반복 버튼 — 그림은 버튼 자리(roi)에서만 찾으므로 못 찾으면 버튼 줄 글자로 한 번 더 (사용자 11-24 제보:
    같은 던전을 다시 하기 대신 나가서 지도로 다시 찾아감). 함수면 보상 화면에서 정한다."""

    def reward(self, again, found_text=None):
        bot = mock.MagicMock()
        bot.wait.side_effect = StepTimeout("그림 없음")
        ctx = monitor.Ctx("silver", "클리어 뒤", reward=True, again=again)
        with mock.patch.object(ui_text, "find", return_value=found_text) as find:
            r = handlers.reward(bot, ctx, None)
        return r, bot, find

    def test_text_fallback(self):
        r, bot, find = self.reward("dungeon_retry", found_text=(1062, 1010))
        self.assertEqual(r.result, "again")
        bot.click.assert_called_once_with((1062, 1010))
        self.assertEqual(find.call_args.args[1], "다시하기")

    def test_no_button_exits(self):
        r, bot, _ = self.reward("dungeon_retry")
        self.assertEqual(r, "보상 화면 나가기")
        bot.key.assert_called_once_with("esc")

    def test_callable_none_exits_without_looking(self):
        r, bot, find = self.reward(lambda: None)
        self.assertEqual(r, "보상 화면 나가기")
        bot.wait.assert_not_called()
        find.assert_not_called()

    def test_callable_button(self):
        bot = mock.MagicMock()
        ctx = monitor.Ctx("silver", "클리어 뒤", reward=True, again=lambda: "dungeon_retry")
        r = handlers.reward(bot, ctx, None)
        self.assertEqual(r.result, "again")
        bot.wait.assert_called_once()
        self.assertEqual(bot.wait.call_args.args[0], "dungeon_retry")


if __name__ == "__main__":
    unittest.main()
