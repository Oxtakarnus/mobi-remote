"""게임 단축키 (mabi.keys) — 옵션에서 바꾼 키, 기본값, 검사."""
import unittest
from types import SimpleNamespace
from unittest import mock

from mabi import keys


class KeysTest(unittest.TestCase):
    def test_default_and_override(self):
        self.assertEqual(keys.of(SimpleNamespace(cfg={"game": {}}), "camera"), "end")  # 게임 기본 주 키 (보조 Z)
        self.assertEqual(keys.of({"game": {"camera_key": "C"}}, "camera"), "c")
        self.assertEqual(keys.of(mock.MagicMock(), "leave"), "shift+esc")  # 가짜 봇 (cfg 가 dict 가 아님)
        self.assertEqual(keys.of({"game": {"fast_travel_key": ""}}, "fast_travel"), "")  # 비우면 안 씀

    def test_follows_game_unless_remote_set(self):
        """게임에서 바꾼 키를 따라가되, 리모콘 옵션에서 기본값과 다르게 정한 키가 이긴다 (사용자 11-19)."""
        game = {"camera": "f10", "food": "f12"}
        with mock.patch.object(keys, "game_key", side_effect=game.get):
            self.assertEqual(keys.of({"game": {}}, "camera"), "f10")
            self.assertEqual(keys.of({"game": {"camera_key": "end"}}, "camera"), "f10")  # 기본값 그대로면 게임 쪽
            self.assertEqual(keys.of({"game": {"camera_key": "c"}}, "camera"), "c")
            self.assertEqual(keys.of({"game": {}}, "quest"), "j")  # 게임에서 안 바꿈
            # 리모콘 일시정지 키와 같은 게임 키는 쓰지 않는다 (누르면 리모콘이 스스로 멈춘다)
            self.assertEqual(keys.of({"game": {"stop_key": "f12"}}, "food"), "b")

    def test_follow_game_off_by_default(self):
        self.assertIsNone(keys._game)  # 시험·도구에서는 게임 설정을 읽지 않는다 (앱만 follow_game)

    def test_check(self):
        self.assertIsNone(keys.check("camera", "f5"))
        self.assertIsNone(keys.check("leave", "shift+esc"))
        self.assertIsNotNone(keys.check("leave", "esc+shift"))  # 보조 키가 앞
        self.assertIsNotNone(keys.check("leave", "shift"))
        for k in ("end", "home", "pagedown", ",", "num3", "`"):  # 게임에서 쓰는 다른 키도 (사용자 11-03)
            self.assertIsNone(keys.check("camera", k), k)
        self.assertIsNone(keys.check("fast_travel", ""))
        self.assertIsNotNone(keys.check("camera", ""))
        self.assertIsNotNone(keys.check("camera", "ㅋ"))
        self.assertIsNotNone(keys.check("nope", "z"))

    def test_defaults_match_config_file(self):
        """config.default.toml 의 [game] 키와 GAME_KEYS 기본값이 같아야 옵션 창 '기본값으로' 가 맞다."""
        import tomllib
        from pathlib import Path
        g = tomllib.loads((Path(__file__).parent.parent / "config.default.toml").read_text(encoding="utf-8"))["game"]
        for name, (default, _) in keys.GAME_KEYS.items():
            self.assertEqual(g.get(f"{name}_key"), default, name)

    def test_combo(self):
        from mabi import inputs
        self.assertEqual(inputs.combo("shift+esc"), [0x10, 0x1B])
        self.assertEqual(inputs.combo("Z"), [ord("Z")])
        self.assertEqual(inputs.combo("shift"), [0x10])  # 보조 키 하나만 — Bot.ensure_focus (11-19 이걸 막아 어비스가 멈췄다)
        self.assertEqual(inputs.combo_name({"shift", "ctrl"}, "5"), "ctrl+shift+5")
        for bad in ("", "+", "esc+shift", "shift+", "hyper+a", "ctrl+shift"):
            with self.assertRaises(ValueError):
                inputs.combo(bad)

    def test_combo_presses_modifier_around_key(self):
        from mabi import inputs
        sent = []
        with (mock.patch.object(inputs, "_send", side_effect=lambda i: sent.append((i.ki.wScan, i.ki.dwFlags & 2))),
              mock.patch.object(inputs.time, "sleep")):
            inputs.Input().key("shift+esc")
        shift, esc = (inputs.user32.MapVirtualKeyW(v, 0) for v in (0x10, 0x1B))
        self.assertEqual(sent, [(shift, 0), (esc, 0), (esc, 2), (shift, 2)])

    def test_navigation_keys_are_extended(self):
        """End·Home 등은 확장 키 표시를 붙여 보낸다 — 없으면 게임이 숫자 패드 키로 받는다."""
        from mabi import inputs
        self.assertTrue(inputs._key(inputs.vk_of("end"), up=False).ki.dwFlags & inputs.KEYEVENTF_EXTENDEDKEY)
        self.assertFalse(inputs._key(inputs.vk_of("z"), up=False).ki.dwFlags & inputs.KEYEVENTF_EXTENDEDKEY)


if __name__ == "__main__":
    unittest.main()
