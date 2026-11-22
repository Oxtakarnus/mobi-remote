"""오래된 스크린샷 자동 정리 · 같은 화면은 한 장만."""
import os
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import numpy as np

from mabi import session as sm
from mabi.session import GameSession, prune_shots


class PruneShotsTest(unittest.TestCase):
    def test_only_old_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            old, new = d / "20261001_120000_login.png", d / "20261025_120000_login.png"
            mine, other = d / "내 사진.png", d / "20261001_120000_note.txt"  # 사용자가 둔 파일은 건드리지 않는다
            for f in (old, new, mine, other):
                f.write_bytes(b"x")
            past = time.time() - 8 * 86400
            for f in (old, mine, other):
                os.utime(f, (past, past))
            self.assertEqual(prune_shots(d), 1)
            self.assertEqual(sorted(f.name for f in d.iterdir()), sorted([new.name, mine.name, other.name]))

    def test_missing_dir(self):
        self.assertEqual(prune_shots(Path(tempfile.gettempdir()) / "없는-폴더-shots"), 0)


A = np.full((1080, 1920, 3), 90, np.uint8)
A2 = A.copy()
A2[500:530, 900:980] = 200  # 조금 움직임 (막힌 대화 앞 NPC·촛불)
B = np.zeros((1080, 1920, 3), np.uint8)  # 다른 화면


class SameShotTest(unittest.TestCase):
    """같은 이름표로 되풀이해 찍는 같은 화면은 한 장만 — 막힌 대화 앞에서 13분 동안 100장이 쌓였다 (2026-11-22)."""

    def shots(self, calls):
        """calls: [(이름표, 화면, 초)] → (돌려받은 사진 이름들, 남은 파일 수)"""
        with tempfile.TemporaryDirectory() as tmp:
            s = GameSession.__new__(GameSession)
            s.shot_dir, s.last_shots = Path(tmp), {}
            s.screen = mock.Mock()
            s.screen.grab.side_effect = [img for _, img, _ in calls]
            times = [datetime(2026, 11, 22, 7, 53, i) for i in range(len(calls))]
            with (mock.patch.object(sm, "datetime") as dt,
                  mock.patch.object(sm.time, "monotonic", side_effect=[t for _, _, t in calls])):
                dt.now.side_effect = times
                names = [s.snapshot(tag).name for tag, _, _ in calls]
            return names, len(list(Path(tmp).iterdir()))

    def test_same_screen_once(self):
        names, n = self.shots([("arbeit_menu", A, 0), ("arbeit_menu", A2, 7), ("arbeit_menu", A, 14)])
        self.assertEqual(n, 1)
        self.assertEqual(set(names), {"20261122_075300_arbeit_menu.png"})

    def test_new_screen_or_tag_or_later(self):
        _, n = self.shots([("arbeit_menu", A, 0), ("arbeit_menu", B, 7)])  # 화면이 바뀜
        self.assertEqual(n, 2)
        _, n = self.shots([("arbeit_menu", A, 0), ("npc_menu_other", A, 7)])  # 이름표마다
        self.assertEqual(n, 2)
        _, n = self.shots([("arbeit_menu", A, 0), ("arbeit_menu", A, sm.SHOT_SAME_GAP + 1)])  # 한참 뒤
        self.assertEqual(n, 2)


if __name__ == "__main__":
    unittest.main()
