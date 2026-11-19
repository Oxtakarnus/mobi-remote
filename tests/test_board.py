"""임무 게시판 제작 스크롤 (mabi/tasks/board.py) — 카드 읽기 · 들를 순서 · 주간 기록 · 지금 마을(CLI 먼저).

카드 글자는 2026-11-19 네 마을 게시판 캡처를 OCR 한 결과 그대로 (find_texts → [(글자, x, y)]).
"""
import logging
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from mabi import gamedata as gd
from mabi.packet_monitor import PacketState
from mabi.tasks import board, worldmap
from mabi.tasks.board import BUY, SOLD, UNKNOWN

REGION = gd.region("board_cards")

# 콜헨 — 목록을 끝까지 내린 화면. 사슬 갑옷 신발은 이번 주 다 삼
KOLHEN_BOTTOM = [
    ('©900', 1256, 288), ('©90', 1421, 287), ('©900', 1584, 288), ('©900', 1748, 288),
    ('채집 스크롤:', 1297, 367), ('제작 스크롤:', 1625, 367), ('제작 스크롤:두꺼운', 1790, 367), ('상급 통나무+', 1297, 390),
    ('채집 스크롤:조개', 1461, 378), ('사슬 갑옷 신발', 1626, 389), ('가죽 갑옷 신발', 1790, 389), ('21', 1666, 414),
    ('인 18', 1829, 414), ('구입 0/3', 1297, 530), ('구입 0/3', 1461, 530), ('일시품절', 1625, 530), ('구입 0/3', 1790, 530),
    ('900', 1266, 585), ('900', 1430, 584), ('900', 1594, 584), ('900', 1759, 585),
    ('제작 스크롤:두꺼운', 1297, 668), ('전투복 신발', 1297, 691), ('한 15', 1336, 715), ('구입 0/3', 1296, 830),
    ('900', 1266, 887),
]

# 던바튼 — 처음 연 화면. 셋째 줄 제목(y 909)은 상태 줄이 칸 밖이라 목록을 내린 뒤에 본다
DUNBARTON_TOP = [
    ('토벌 스크롤:', 1297, 307), ('여신의 뜰', 1297, 329), ('요리 스크롤:', 1461, 306), ('사과 주스', 1461, 328),
    ('채집 스크롤:', 1625, 307), ('쑥쑥 버섯', 1625, 328), ('채집 스크롤:우유', 1790, 318),
    ('구입 0/3', 1297, 470), ('구입 0/3', 1461, 470), ('구입 0/3', 1625, 470), ('구입 0/3', 1789, 470),
    ('480', 1266, 524), ('480', 1430, 524), ('480', 1594, 524), ('480', 1759, 524),
    ('채광 스크롤:', 1297, 608), ('제작스크롤:', 1791, 608), ('철 광석', 1297, 630), ('채집 스크롤:옥수수', 1462, 619),
    ('채집 스크롤:양파', 1626, 620), ('크레센트 엣지소드', 1790, 630), ('후 18', 1829, 655),
    ('구입 0/3', 1296, 770), ('구입 0/3', 1461, 770), ('구입 0/3', 1625, 770), ('구입0/3', 1789, 770),
    ('480', 1266, 826), ('480', 1430, 826), ('480', 1594, 826), ('480', 1759, 826),
    ('제작 스크롤:그랜드', 1297, 909), ('제작 스크롤:', 1461, 908),
]

# 반호르 — 제목이 가로로 나뉘어 읽힌 칸('채집' + '스크롤:콩')
BANHORR_TOP = [
    ('채집', 1259, 318), ('스크롤:콩', 1313, 318), ('채집 스크롤:파스닙', 1462, 318), ('요리 스크롤:', 1625, 306),
    ('통감자구이', 1626, 329), ('토벌 스크롤:', 1790, 307), ('구름 황야', 1790, 329),
    ('구입 0/3', 1297, 469), ('구입 0/3', 1461, 469), ('구입0/3', 1625, 470), ('구입 0/3', 1789, 469),
    ('1,000', 1273, 525), ('1,000', 1437, 525), ('1,000', 1602, 525), ('1,000', 1766, 525),
    ('제작 스크롤:', 1298, 607), ('제작 스크롤:라이트', 1462, 607), ('제작 스크롤:마블', 1625, 607),
    ('론 엣지소드S', 1297, 630), ('크로스보우S', 1461, 631), ('힐링 완드S', 1626, 631),
    ('4 18', 1336, 655), ('수 18', 1500, 655), ('후 18', 1664, 655),
    ('구입 0/3', 1296, 770), ('구입 0/3', 1461, 771), ('구입0/3', 1625, 771),
    ('1,000', 1273, 827), ('1,000', 1437, 826), ('1,000', 1602, 827),
]


def crafts(items):
    return [(c.key, c.state) for c in board.parse_cards(items, REGION) if c.craft]


class CardTest(unittest.TestCase):
    def test_status(self):
        self.assertEqual(board.status_of("구입 0/3"), BUY)
        self.assertEqual(board.status_of("구입0/3"), BUY)
        self.assertEqual(board.status_of("구입 3/3"), SOLD)
        self.assertEqual(board.status_of("일시 품절"), SOLD)
        self.assertEqual(board.status_of("구입 0/:"), UNKNOWN)
        self.assertIsNone(board.status_of("1,000"))
        self.assertIsNone(board.status_of("제작 스크롤:"))

    def test_kolhen_bottom(self):
        self.assertEqual(crafts(KOLHEN_BOTTOM), [("제작스크롤사슬갑옷신발", SOLD), ("제작스크롤두꺼운가죽갑옷신발", BUY),
                                                 ("제작스크롤두꺼운전투복신발", BUY)])
        # 누를 자리는 카드 그림 (상태 글자 위)
        card = next(c for c in board.parse_cards(KOLHEN_BOTTOM, REGION) if c.key == "제작스크롤두꺼운전투복신발")
        self.assertEqual((card.x, card.y), (1296, 760))

    def test_badge_and_price_not_in_title(self):
        titles = [c.title for c in board.parse_cards(KOLHEN_BOTTOM, REGION)]
        self.assertTrue(all("18" not in t and "900" not in t and "15" not in t for t in titles), titles)

    def test_row_below_edge_waits_for_scroll(self):
        self.assertEqual(crafts(DUNBARTON_TOP), [("제작스크롤크레센트엣지소드", BUY)])

    def test_split_title(self):
        keys = [c.key for c in board.parse_cards(BANHORR_TOP, REGION)]
        self.assertIn("채집스크롤콩", keys)
        self.assertEqual([s for _, s in crafts(BANHORR_TOP)], [BUY, BUY, BUY])

    def test_unread_status_still_tried(self):
        items = [i for i in KOLHEN_BOTTOM if (i[1], i[2]) != (1790, 530)]  # 두꺼운 가죽 갑옷 신발의 상태를 못 읽음
        card = next(c for c in board.parse_cards(items, REGION) if c.craft and c.x == 1790)
        self.assertEqual(card.state, UNKNOWN)
        self.assertTrue(380 < card.y < 520)  # 카드 그림 근처

    def test_same_view(self):
        self.assertTrue(board._same_view([460, 760], [462, 761]))
        self.assertFalse(board._same_view([460, 760], [400, 700]))
        self.assertFalse(board._same_view([460], [460, 760]))


class OrderTest(unittest.TestCase):
    TOWNS = ["이멘마하", "반호르", "던바튼", "콜헨"]

    def test_current_town_first(self):
        self.assertEqual(board.visit_order(self.TOWNS, "콜헨"), ["콜헨", "이멘마하", "반호르", "던바튼"])
        self.assertEqual(board.visit_order(self.TOWNS, "이멘 마하"), self.TOWNS)

    def test_unknown_or_other_place_keeps_order(self):
        self.assertEqual(board.visit_order(self.TOWNS, None), self.TOWNS)
        self.assertEqual(board.visit_order(self.TOWNS, "티르코네일"), self.TOWNS)


class WeekTest(unittest.TestCase):
    def test_add_and_reset_on_new_week(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "board-week.json"
            thu = board.Week(path, datetime(2026, 11, 19, 21))
            thu.add(3, "이멘마하")
            thu.add(3, "이멘마하")
            self.assertEqual(thu.done(3), ["이멘마하"])
            self.assertEqual(thu.done(4), [])
            self.assertEqual(board.Week(path, datetime(2026, 11, 23, 5, 59)).done(3), ["이멘마하"])  # 일요일 밤 = 같은 주
            self.assertEqual(board.Week(path, datetime(2026, 11, 23, 6)).done(3), [])  # 월요일 오전 6시부터 새 주

    def test_no_character_no_record(self):
        with tempfile.TemporaryDirectory() as d:
            w = board.Week(Path(d) / "board-week.json")
            w.add(None, "콜헨")
            self.assertEqual(w.done(None), [])


def town_bot(cli=None, act=None, **packet):
    """cli: get_current_environment 답 (None 이면 CLI 가 답하지 않음)."""
    return SimpleNamespace(
        state=SimpleNamespace(available=lambda: cli is not None), environment=lambda: cli, activity=lambda: act or {},
        packets=SimpleNamespace(ok=True, state=PacketState(**packet)), log=logging.getLogger("test"))


class CurrentTownTest(unittest.TestCase):
    def test_cli_first(self):
        bot = town_bot({"ChannelDisplayName": "이멘마하"}, channel=1, channel_type="Field", channel_name="콜헨")
        self.assertEqual(worldmap.current_town(bot), "이멘마하")
        self.assertTrue(worldmap.same_town(worldmap.current_town(bot), "이멘마하"))

    def test_cli_field_is_not_town(self):
        bot = town_bot({"ChannelDisplayName": "창백한 산"}, {"Battlefield": {"IsInBattleField": True}})
        self.assertIsNone(worldmap.current_town(bot))

    def test_packet_when_cli_silent(self):
        bot = town_bot(None, channel=1, channel_type="Field", channel_name="이멘 마하")
        self.assertTrue(worldmap.same_town(worldmap.current_town(bot), "이멘마하"))
        self.assertIsNone(worldmap.current_town(town_bot(None)))


if __name__ == "__main__":
    unittest.main()
