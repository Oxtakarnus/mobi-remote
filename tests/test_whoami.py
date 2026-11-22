"""이름을 모를 때 CLI 지문으로 '마지막으로 확인한 그 캐릭터' 인지 (whoami) — 리모콘을 다시 켜고 어비스 입장 창을 띄운 채
시작하면 같은 캐릭터인데도 창을 닫고 메인 화면에서 이름을 읽었다 (2026-11-22 19:10). 비슷한 걸 고르던 옛 방식은 자주
틀려 뺐으니 (2026-10-22) 똑같을 때만, 하나뿐일 때만 맞다고 한다."""
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

from mabi import whoami
from mabi.tasks import repeat

INFO = {"RealmName": "서버", "Level": 100, "EnabledCombatJobDisplayName": "전사", "Title": "칭호",
        "CombatScore": {"Value": 34567}, "LivingScore": {"Value": 1200}, "AttractivenessScore": {"Value": 800},
        "DecorScore": {"Value": 50}}
FP = whoami.fingerprint(INFO)


class MatchTest(unittest.TestCase):
    def test_same_one_slot(self):
        self.assertEqual(whoami.match({"1": {"fp": {**FP, "combat": 30000}}, "2": {"fp": dict(FP)}}, FP), 2)

    def test_combat_changed_is_unknown(self):
        self.assertIsNone(whoami.match({"2": {"fp": {**FP, "combat": 34568}}}, FP))

    def test_account_wide_scores_ignored(self):
        """생활력·매력·데코는 계정 공용일 수 있어 보지 않는다 — 생활력이 자라도 같은 캐릭터."""
        self.assertEqual(whoami.match({"2": {"fp": {**FP, "living": 1300}}}, FP), 2)

    def test_two_same_is_unknown(self):
        self.assertIsNone(whoami.match({"1": {"fp": dict(FP)}, "2": {"fp": dict(FP)}}, FP))

    def test_missing_values(self):
        self.assertIsNone(whoami.match({"1": {"fp": {**FP, "combat": None}}}, {**FP, "combat": None}))
        self.assertIsNone(whoami.match({"1": {"card": {"level": 100}}}, FP))


def learn_bot(tmp, name="가나다", entered_ago=120.0, loading=False):
    b = mock.MagicMock()
    b.packets.ok = True
    b.packets.state = NS(my_name=name, loading=loading, entered_at=time.monotonic() - entered_ago)
    b.session.my_info.return_value = INFO
    b.paths.data = Path(tmp)
    return b


class RememberTest(unittest.TestCase):
    def setUp(self):
        whoami._learned.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ch = {"slot": 3, "name": "가나다"}

    def slots(self):
        return whoami.Characters(Path(self.tmp.name)).load()["slots"]

    def test_learns_when_packet_name_matches(self):
        whoami.remember(learn_bot(self.tmp.name), self.ch)
        self.assertEqual(self.slots()["3"]["fp"], FP)
        self.assertEqual(whoami.recognize(learn_bot(self.tmp.name)), 3)

    def test_not_other_name(self):
        whoami.remember(learn_bot(self.tmp.name, name="라마바"), self.ch)
        self.assertEqual(self.slots(), {})

    def test_not_right_after_entering(self):
        """접속 직후 커넥터가 이전 캐릭터 정보를 잠깐 돌려준다 — 맵에 막 들어왔으면 기억하지 않는다."""
        whoami.remember(learn_bot(self.tmp.name, entered_ago=5.0), self.ch)
        whoami.remember(learn_bot(self.tmp.name, loading=True), self.ch)
        self.assertEqual(self.slots(), {})

    def test_throttled(self):
        b = learn_bot(self.tmp.name)
        whoami.remember(b, self.ch)
        whoami.remember(b, self.ch)
        self.assertEqual(b.session.my_info.call_count, 1)


class EnsureTest(unittest.TestCase):
    def rep(self, recognized, at="entry"):
        r = repeat.Repeat.__new__(repeat.Repeat)
        r.bot = mock.MagicMock()
        r.character, r.unchecked = {"slot": 3, "name": "가나다"}, None
        r._switch = mock.MagicMock()
        r.where = mock.MagicMock(return_value="main")
        with (mock.patch.object(repeat, "current_name", return_value=""),
              mock.patch.object(repeat.whoami, "recognize", return_value=recognized)):
            got = r.ensure_character(at)
        return r, got

    def test_same_fingerprint_keeps_entry_window(self):
        r, at = self.rep(3)
        self.assertEqual(at, "entry")
        r._switch.assert_not_called()
        self.assertEqual(r.unchecked, r.character)  # 이름을 알게 되면 recheck 가 다시 확인

    def test_unknown_switches_as_before(self):
        for recognized in (None, 5):
            r, at = self.rep(recognized)
            r._switch.assert_called_once_with("entry")
            self.assertEqual(at, "main")


if __name__ == "__main__":
    unittest.main()
