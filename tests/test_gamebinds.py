"""게임 조작키 설정 읽기 (mabi.gamebinds) — CustomKeys 풀기, 리모콘 단축키로 옮기기."""
import base64
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mabi import gamebinds as G, keys

SAMPLE = "<103>fH13YmFkfnx0enppa3R8bxs8OiphAjklIHV9"   # 2026-11-19 실측: 전체 화면 채팅 주 키 F11 → F10


def encode(text: str, ver: int = 103) -> str:
    k = G.rules()["xor"].encode()
    raw = bytes(b ^ k[i % len(k)] for i, b in enumerate(text.encode()))
    return f"<{ver}>" + base64.b64encode(raw).decode()


def act(name: str) -> int:
    return G.rules()["actions"][name]["id"]


class DecodeTest(unittest.TestCase):
    def test_sample(self):
        self.assertEqual(G.decode(SAMPLE), (103, "104720118,1,291,None,None,0"))
        self.assertEqual(G.parse("104720118,1,291,None,None,0"), {104720118: [[291], None, None]})
        self.assertEqual(G.bindings("104720118,1,291,None,None,0"), {})  # 리모콘이 쓰지 않는 동작

    def test_bad_values(self):
        for v in ("", "abc", "<103>@@@", "<x>AAAA"):
            self.assertIsNone(G.decode(v), v)
        self.assertEqual(G.parse("1,2|x,None|5,1"), {})  # 칸이 안 맞으면 건너뜀

    def test_key_names(self):
        self.assertEqual(G.key_name([291]), "f10")
        self.assertEqual(G.key_name([304, 27]), "shift+esc")
        self.assertEqual(G.key_name([306, 304, 97]), "ctrl+shift+a")
        self.assertEqual(G.key_name([279]), "end")
        self.assertIsNone(G.key_name([]))
        self.assertIsNone(G.key_name([323]))      # 마우스 버튼 — 리모콘이 누를 수 없다
        self.assertIsNone(G.key_name([97, 98]))   # 보조 키가 아닌 앞 키

    def test_bindings(self):
        text = "|".join([
            f"{act('camera')},1,99,None,None,0",          # 카메라 주 키 C
            f"{act('leave')},2,304,113,None,None,0",      # 여기서 나가기 Shift+Q
            f"{act('quest')},0,None,None,0",              # 퀘스트 창 주 키를 없앰 (보조 키도 없음)
            f"{act('skill1')},0,None,None,0",             # 스킬 1 주 키를 없앰 → 게임 보조 키 L
            f"{act('food')},None,1,103,None,0",           # 음식 보조 키만 바꿈 → 주 키 B 그대로
        ])
        self.assertEqual(G.bindings(text), {"camera": "c", "leave": "shift+q", "skill1": "l", "food": "b"})

    def test_all_defaults_are_sendable(self):
        """game-rules 의 게임 기본 키는 리모콘이 누를 수 있고, 주 키는 리모콘 기본값과 같아야 한다."""
        from mabi import inputs
        acts = G.rules()["actions"]
        self.assertEqual(set(acts), set(keys.GAME_KEYS))
        for name, a in acts.items():
            for k in a["keys"]:
                inputs.combo(k)
            self.assertEqual(a["keys"][0], keys.GAME_KEYS[name][0], name)


class FilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, base: str | None, changed: list[str] | None = None):
        if base is not None:
            (self.dir / "BaseMMPlayerPrefs.txt").write_text(f"STRING\nOther : 1\nCustomKeys : {base}\n", encoding="utf-8")
        if changed is not None:
            (self.dir / "ChangedMMPlayerPrefs.txt").write_text("\n".join(changed) + "\n", encoding="utf-8")

    def test_changed_wins_last_line(self):
        cam = encode(f"{act('camera')},1,99,None,None,0")
        self.write(SAMPLE, ["+4 : Flag : True", f"+1 : CustomKeys : {SAMPLE}", f"+1 : CustomKeys : {cam}"])
        self.assertEqual(G.raw_value(self.dir), cam)
        self.write(SAMPLE, [f"+1 : CustomKeys : {cam}", "-1 : CustomKeys"])
        self.assertEqual(G.raw_value(self.dir), "")
        self.write("", None)
        (self.dir / "ChangedMMPlayerPrefs.txt").unlink()
        self.assertEqual(G.raw_value(self.dir), "")

    def test_game_binds_rereads_when_changed(self):
        self.write(encode(f"{act('camera')},1,99,None,None,0"), [])
        gb = G.GameBinds(self.dir)
        gb.CHECK = 0
        self.assertEqual(gb.current(), {"camera": "c"})
        g = encode(f"{act('map')},1,103,None,None,0")  # 지도 주 키 G
        self.write(None, [f"+1 : CustomKeys : {g}"])
        self.assertEqual(gb.current(), {"map": "g"})

    def test_unknown_version_ignored(self):
        self.write(encode(f"{act('camera')},1,99,None,None,0", ver=200), [])
        gb = G.GameBinds(self.dir)
        with self.assertLogs("mabi", "WARNING"):
            self.assertEqual(gb.current(), {})

    def test_missing_folder(self):
        self.assertEqual(G.GameBinds(self.dir / "없음").current(), {})
        self.assertEqual(G.GameBinds(None).current(), {})

    def test_follow_game_feeds_keys(self):
        self.write(encode(f"{act('leave')},2,304,113,None,None,0"), [])
        try:
            keys.follow_game(self.dir)
            self.assertEqual(keys.of({"game": {}}, "leave"), "shift+q")
        finally:
            keys._game = None
        self.assertEqual(keys.of({"game": {}}, "leave"), "shift+esc")


class SettingsTest(unittest.TestCase):
    def test_saving_game_key_keeps_following(self):
        """옵션 창 저장 때 게임에서 읽은 키 그대로면 기본값으로 둔다 — 게임 설정을 계속 따라가게."""
        from gui_app import daily_api
        with mock.patch.object(keys, "game_key", side_effect={"camera": "c"}.get):
            api = daily_api.DailyApi.__new__(daily_api.DailyApi)
            doc = {"silver": {}, "game": {"stop_key": "f12", "dye_key": "f11", "camera_key": "end"}}
            api._doc = lambda: doc
            api.paths = mock.Mock()
            with mock.patch.object(daily_api.userconfig, "save"):
                r = api.daily_saveSettings({"game_keys": {"camera": "c", "food": "v"}})
        self.assertNotIn("error", r or {})
        self.assertEqual(doc["game"]["camera_key"], "end")
        self.assertEqual(doc["game"]["food_key"], "v")


if __name__ == "__main__":
    unittest.main()
