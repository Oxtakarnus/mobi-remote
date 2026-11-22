"""NPC 대화 판정 한 모듈 (tasks.dialogue.View) — 받은 대화 패킷(11-05 아르바이트 캡처의 본문)으로 대본을 읽고,
패킷·CLI·화면을 한 규칙으로 합치는지. 2026-11-22: 패킷 칸 하나를 잘못 읽은 것이 '패킷만' 보던 곳에서 한꺼번에 터졌다."""
import time
import unittest
from pathlib import Path
from unittest import mock

from mabi import packet_table, sjon
from mabi.bot import Marks
from mabi.packet_monitor import PacketMonitor
from mabi.tasks import dialogue

FIX = Path(__file__).resolve().parent / "fixtures" / "dialogue"
# 표(spec/states.json)의 대화 칸과 같은 읽는 법
NODE = {"breaks": ("sjon_count", "dialogueContents/Next"), "why": ("sjon_kids", "dialogueConditions"),
        "action": ("sjon", "dialogueAction")}


def body(name: str) -> bytes:
    return (FIX / f"{name}.bin").read_bytes()


def node_vals(name: str, step: int) -> dict:
    b = body(name)
    out = {k: packet_table._read(b, 0, typ, key=key) for k, (typ, key) in NODE.items()}
    return {"active": True, "step": step, **out}


def prompt_vals(name: str) -> dict:
    import struct
    b = body(name)
    step, kind, n = struct.unpack_from("<III", b, 0)
    return {"step": step, "type": kind, "choices": n, "labels": packet_table._read(b, 8, "str32list", at=4, size=17)}


class ReadTest(unittest.TestCase):
    """대화 패킷 읽기 — 대사 묶음(SJON) 나무의 쪽 경계·조건, 선택지 알림의 버튼 글자."""

    def test_node_script(self):
        self.assertEqual(node_vals("accept_node", 1), {"active": True, "step": 1, "breaks": 0, "why": ("ArbeitReceiving",),
                                                       "action": "AcceptQuest"})
        self.assertEqual(node_vals("end_node", 2)["breaks"], 2)  # 3쪽 작별 대사
        v = node_vals("report_node", 4)
        self.assertEqual((v["breaks"], v["why"], v["action"]), (1, ("QuestObjectiveWaitingForAchieve",), "AchieveQuestObjective"))

    def test_choice_labels(self):
        self.assertEqual(prompt_vals("accept_prompt")["labels"], ("수락", "나중에 한다"))
        self.assertEqual(prompt_vals("menu_prompt")["labels"], ("결과 보고", "상점", "아무말", "대화 종료"))
        self.assertEqual(prompt_vals("report_prompt"), {"step": 4, "type": 3, "choices": 0, "labels": ()})

    def test_labels_must_fill_body(self):
        """칸이 밀리면 엉뚱한 글자 대신 모름 (본문 끝과 꼭 맞아야 한다)."""
        b = body("menu_prompt")
        self.assertIsNone(packet_table._read(b + b"\0", 8, "str32list", at=4, size=17))
        self.assertIsNone(packet_table._read(b[:-1], 8, "str32list", at=4, size=17))
        self.assertIsNone(packet_table._read(b, 8, "str32list", at=5, size=16))

    def test_no_script_or_broken_script(self):
        self.assertEqual(packet_table._read(bytes(14), 0, "sjon_count", key="dialogueContents/Next"), 0)  # 대화 끝 (대본 없음)
        self.assertEqual(packet_table._read(bytes(14), 0, "sjon_kids", key="dialogueConditions"), ())
        b = body("report_node")
        s = b.find(b"SJON")
        self.assertIsNone(packet_table._read(b[:s + 40], 0, "sjon_count", key="dialogueContents/Next"))  # 잘림 → 모름

    def test_sjon_inside_packet(self):
        """패킷의 대사 묶음은 뒤에 다른 바이트가 붙어 있어 길이를 머리로 센다."""
        b = body("accept_node")
        s = b.find(b"SJON")
        n = sjon.sized(b, s)
        self.assertIsNotNone(n)
        self.assertLessEqual(s + n, len(b))
        self.assertEqual(sjon.load_at(b + b"tail", s)["Name"], "Dialogue")
        self.assertIsNone(sjon.sized(b[:s + 20], s))
        with self.assertRaises(sjon.SjonError):
            sjon.load_at(b"nope")

    def test_table_has_dialogue_fields(self):
        """묶은 표(packet-states.bin)가 같은 칸을 읽는다 — 키가 없는 곳에서는 건너뛴다."""
        try:
            table = packet_table.load()
        except (FileNotFoundError, ValueError) as e:
            self.skipTest(str(e))
        up, pr = table.by_key("dialogue.update"), table.by_key("dialogue.prompt")
        self.assertEqual(table.decode(up.proto, body("report_node"))[1]["breaks"], 1)
        self.assertEqual(table.decode(pr.proto, body("menu_prompt"))[1]["labels"], ("결과 보고", "상점", "아무말", "대화 종료"))


def bot_of(m: PacketMonitor, act=None, skip=None, log=None, hud=None):
    b = mock.Mock()
    b.packets.ok, b.packets.state = True, m.state
    b.marks = Marks()
    b.cfg = {"arbeit": {"dialog_log": "dialog_log", "dialog_next_xy": [1800, 45]}}
    b.activity.return_value = act
    b.dialogue_playing.side_effect = lambda a=None: m.state.in_dialogue
    b.skip_button.return_value = skip
    b.vision.find.side_effect = lambda f, n: log if n == "dialog_log" else None
    b.at_main.return_value = hud is not None
    b.frame.return_value = None
    return b


def talk(m: PacketMonitor, *nodes) -> None:
    """캡처 순서대로 — 덩어리마다 선택지 알림이 대사 진행 바로 앞에 온다, 대화 대상은 첫 덩어리 뒤."""
    for i, (node, prompt, step) in enumerate(nodes):
        m.apply("dialogue.prompt", prompt_vals(prompt))
        m.apply("dialogue.update", node_vals(node, step))
        if i == 0:
            m.apply("dialogue.target", {"target": 0xA2A9})


def monitor() -> PacketMonitor:
    m = PacketMonitor(None)
    m.state.channel = 1  # 감시를 켠 뒤 맵에 들어옴
    return m


CLI_MENU = {"IsDialoguePlaying": True, "IsDialogueNextAvailable": False, "IsWaitingForSelection": True}
CLI_NEXT = {"IsDialoguePlaying": True, "IsDialogueNextAvailable": True, "IsWaitingForSelection": False}


class ViewTest(unittest.TestCase):
    def test_accept_menu_is_up(self):
        """알바 받기: 1쪽 + 선택지 [수락·나중에 한다] → 넘길 대사 없음, 메뉴 떠 있음, 우리 메뉴 (패킷만으로)."""
        m = monitor()
        talk(m, ("accept_node", "accept_prompt", 1))
        v = dialogue.now(bot_of(m))
        self.assertTrue(v.open)
        self.assertEqual((v.lines_left, v.lines_src, v.menu_up), (False, "packet", True))
        self.assertTrue(v.has("결과보고", "수락"))
        self.assertEqual(v.after, "AcceptQuest")

    def test_report_line_is_tapped(self):
        """결과 보고 뒤 한마디 (종류 3 · 선택지 0 · 2쪽) — 메뉴가 아니다. 눌러서 넘긴다 (2026-11-22 07:53 13분 멈춤)."""
        m = monitor()
        talk(m, ("accept_node", "accept_prompt", 1), ("report_node", "report_prompt", 4))
        v = dialogue.now(bot_of(m, act=CLI_MENU))  # CLI 가 엉뚱해도 패킷 대본이 정한다
        self.assertIs(v.menu, False)
        self.assertEqual((v.lines_left, v.menu_up), (True, False))
        self.assertEqual(v.why, ("QuestObjectiveWaitingForAchieve",))

    def test_many_page_menu_needs_one_tap(self):
        """여러 쪽 메뉴 덩어리: 아직 안 눌렀으면 넘길 대사가 있다. 한 번 누르면 덩어리째 메뉴 쪽으로 건너뛰므로 그 뒤는
        화면·CLI 로 본다 (넘기기 버튼이 보이면 남음)."""
        m = monitor()
        talk(m, ("accept_node", "menu_prompt", 3))
        m.state.dialogue_pages = 3
        b = bot_of(m, act=CLI_MENU)
        self.assertTrue(dialogue.now(b).lines_left)
        dialogue.tap(b, (1800, 45))
        v = dialogue.now(b)
        self.assertEqual((v.taps, v.lines_left, v.lines_src, v.menu_up), (1, False, "cli", True))
        b.skip_button.return_value = ("dialog", (1800, 45))
        self.assertEqual(dialogue.now(b).lines_src, "screen")

    def test_taps_count_per_node(self):
        m = monitor()
        talk(m, ("accept_node", "menu_prompt", 3))
        b = bot_of(m)
        dialogue.tap(b, (1, 1))
        dialogue.tap(b, (1, 1))
        self.assertEqual(dialogue.now(b).taps, 2)
        time.sleep(0.002)
        m.apply("dialogue.prompt", prompt_vals("report_prompt"))
        m.apply("dialogue.update", node_vals("report_node", 4))
        self.assertEqual(dialogue.now(b).taps, 0)  # 새 덩어리

    def test_unknown_packet_uses_cli_then_screen(self):
        """패킷이 대본을 모르면 (감시가 꺼짐) 넘길 쪽·메뉴는 CLI, 대화 중은 CLI → 화면."""
        m = monitor()
        b = bot_of(m, act=CLI_MENU)
        b.packets.ok = False
        b.dialogue_playing.side_effect = lambda a=None: False
        v = dialogue.now(b)
        self.assertEqual((v.menu, v.lines_src, v.menu_up), (None, "cli", True))
        self.assertFalse(v.open)  # 신호 없음 + 창 없음
        b.vision.find.side_effect = lambda f, n: (1, 1) if n == "dialog_log" else None
        v = dialogue.now(b)
        self.assertEqual((v.open, v.src), (True, "screen"))

    def test_missing_prompt_is_unknown_menu(self):
        """선택지 알림을 못 받은 덩어리는 메뉴를 모름 — 지난 덩어리의 메뉴가 남지 않고 CLI 로."""
        m = monitor()
        talk(m, ("accept_node", "accept_prompt", 1))
        m.apply("dialogue.update", node_vals("end_node", 2))
        v = dialogue.now(bot_of(m, act=CLI_NEXT))
        self.assertIsNone(v.menu)
        self.assertEqual((v.lines_left, v.lines_src, v.menu_up), (True, "cli", False))

    def test_has_ignores_spaces(self):
        m = monitor()
        talk(m, ("accept_node", "menu_prompt", 3))
        v = dialogue.now(bot_of(m))
        self.assertTrue(v.has("결과보고"))
        self.assertFalse(v.has("수리"))
        b = bot_of(m)
        b.packets.ok = False
        self.assertIsNone(dialogue.now(b).has("수락"))


class AuditTest(unittest.TestCase):
    """출처끼리 어긋나면 덩어리마다 한 번 관찰 기록(judge.dialogue)에 — 창이 그려지고 자리를 잡은 뒤에만."""

    def setUp(self):
        self.m = monitor()
        talk(self.m, ("accept_node", "accept_prompt", 1))
        self.m.state.changed_at["dialogue"] -= dialogue.SETTLE + 1  # 덩어리가 온 지 오래

    def test_disagreement_is_observed_once(self):
        b = bot_of(self.m, act=CLI_NEXT, log=(1, 1))  # 패킷: 메뉴 떠 있음 · CLI: 넘길 대사 있음
        dialogue.now(b).audit()
        dialogue.now(b).audit()
        b.packets.observe.assert_called_once()
        key, vals = b.packets.observe.call_args[0]
        self.assertEqual(key, "judge.dialogue")
        self.assertIn("메뉴(CLI)", vals["odd"])
        self.assertEqual((vals["menu"], vals["cli_sel"], vals["choices"]), (True, False, "수락/나중에 한다"))

    def test_agreement_is_not_observed(self):
        b = bot_of(self.m, act=CLI_MENU, log=(1, 1))
        dialogue.now(b).audit()
        b.packets.observe.assert_not_called()

    def test_waits_for_window_and_settle(self):
        b = bot_of(self.m, act=CLI_NEXT)  # 창이 아직 안 그려짐
        dialogue.now(b).audit()
        b.packets.observe.assert_not_called()
        self.m.state.changed_at["dialogue"] = time.monotonic()  # 막 온 덩어리
        b = bot_of(self.m, act=CLI_NEXT, log=(1, 1))
        dialogue.now(b).audit()
        b.packets.observe.assert_not_called()


class NextLineTest(unittest.TestCase):
    def test_menu_node_does_not_wait_for_packet(self):
        """메뉴 덩어리는 눌러도 메뉴 쪽으로 건너뛸 뿐 패킷이 안 온다 — 3초씩 헛기다리지 않는다."""
        m = monitor()
        talk(m, ("accept_node", "menu_prompt", 3))
        b = bot_of(m, skip=("dialog", (1800, 45)))
        with mock.patch.object(dialogue, "wait_next") as wn:
            self.assertTrue(dialogue.next_line(b))
        wn.assert_not_called()
        b.click.assert_called_once_with((1800, 45))

    def test_line_waits_for_next_node(self):
        m = monitor()
        talk(m, ("accept_node", "accept_prompt", 1), ("end_node", "report_prompt", 4))
        b = bot_of(m, skip=("dialog", (1800, 45)))
        with mock.patch.object(dialogue, "wait_next", return_value=True) as wn:
            self.assertTrue(dialogue.next_line(b))
        wn.assert_called_once_with(b, 4, 3)


if __name__ == "__main__":
    unittest.main()
