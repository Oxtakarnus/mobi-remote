"""인터페이스 PC·80% 맞추기 (display.InterfaceFit) — 일일 숙제·반복 공통. 맞췄을 때만 on_fit."""
import unittest
from unittest import mock

from mabi.tasks import display


class InterfaceFitTest(unittest.TestCase):
    def bot(self, in_game=True):
        b = mock.MagicMock()
        b.in_game.return_value = in_game
        return b

    def test_once_and_on_fit(self):
        fits = []
        f = display.InterfaceFit(mock.MagicMock(), on_fit=lambda: fits.append(1))
        with mock.patch.object(display, "busy", return_value=""), mock.patch.object(display, "prepare_interface", return_value="ok") as p:
            self.assertTrue(f.attempt(self.bot()))
            self.assertFalse(f.attempt(self.bot()))
        p.assert_called_once()
        self.assertEqual(fits, [1])

    def test_waits_outside_game_or_busy(self):
        f = display.InterfaceFit(mock.MagicMock())
        self.assertFalse(f.attempt(self.bot(in_game=False)))
        with mock.patch.object(display, "busy", return_value="어비스 안"):
            self.assertFalse(f.attempt(self.bot()))
        # 방금 접속했으면 게임 안인지는 묻지 않지만, 콘텐츠 안(드릴에 남긴 캐릭터 등)인지는 본다 (점검 2026-11-22)
        with mock.patch.object(display, "busy", return_value="콘텐츠 맵 안 (InstanceBreakthroughDungeon)"):
            self.assertFalse(f.attempt(self.bot(in_game=False), after_login=True))
        with mock.patch.object(display, "busy", return_value=""),                 mock.patch.object(display, "prepare_interface", return_value="ok"):
            self.assertTrue(f.attempt(self.bot(in_game=False), after_login=True))

    def test_busy_in_content_maps(self):
        """드릴·보스 영역·검은 구멍처럼 따로 들어가는 맵도 콘텐츠 안 — ESC 가 나가기가 될 수 있다."""
        from mabi.packet_monitor import PacketState
        b = mock.MagicMock()
        b.packets.ok = True
        for kind in ("InstanceBreakthroughDungeon", "FieldBoss", "InstanceDimension"):
            b.packets.state = PacketState(channel=1, channel_type=kind)
            self.assertIn("콘텐츠 맵 안", display.busy(b), kind)
        b.packets.state = PacketState(channel=1, channel_type="Field")
        b.activity.return_value = {}
        b.cfg = {"black_hole": {"space_keyword": "검은 구멍"}}
        with mock.patch("mabi.tasks.space.game_space", return_value="마을"):
            self.assertEqual(display.busy(b), "")

    def test_failure_no_on_fit(self):
        fits = []
        f = display.InterfaceFit(mock.MagicMock(), on_fit=lambda: fits.append(1))
        with mock.patch.object(display, "busy", return_value=""), \
                mock.patch.object(display, "prepare_interface", side_effect=display.DisplayFixFailed("x")):
            self.assertTrue(f.attempt(self.bot()))
        self.assertEqual(fits, [])

    def test_disabled(self):
        self.assertFalse(display.InterfaceFit(mock.MagicMock(), enabled=False).attempt(self.bot(), after_login=True))


if __name__ == "__main__":
    unittest.main()
