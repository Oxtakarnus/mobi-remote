"""데이터 폴더 자리 (mabi.paths.default_data_dir) — 설치판·무설치판, 옛 이름 폴더 옮기기."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mabi import paths as P


class DataDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.local, self.app = root / "Local", root / "App"
        self.local.mkdir()
        self.app.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def data_dir(self):
        with (mock.patch.object(sys, "frozen", True, create=True),
              mock.patch.object(sys, "executable", str(self.app / "MobiRemote.exe")),
              mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.local)})):
            return P.default_data_dir()

    def test_source_run_is_project(self):
        with mock.patch.object(sys, "frozen", False, create=True):
            self.assertEqual(P.default_data_dir(), P.PROJECT)

    def test_new_install(self):
        self.assertEqual(self.data_dir(), self.local / "MobiRemote")
        self.assertFalse((self.local / "MobiRemote").exists())   # 만드는 건 Paths.ensure

    def test_old_folder_moves(self):
        old = self.local / "MabiDaily"
        (old / "logs").mkdir(parents=True)
        (old / "settings.json").write_text("{}", encoding="utf-8")
        got = self.data_dir()
        self.assertEqual(got, self.local / "MobiRemote")
        self.assertTrue((got / "settings.json").is_file() and (got / "logs").is_dir())
        self.assertFalse(old.exists())

    def test_new_wins_over_old(self):
        (self.local / "MabiDaily").mkdir()
        (self.local / "MobiRemote").mkdir()
        self.assertEqual(self.data_dir(), self.local / "MobiRemote")
        self.assertTrue((self.local / "MabiDaily").is_dir())   # 옛 폴더는 건드리지 않는다

    def test_old_kept_when_move_fails(self):
        (self.local / "MabiDaily").mkdir()
        with mock.patch.object(Path, "rename", side_effect=PermissionError("열려 있음")):
            self.assertEqual(self.data_dir(), self.local / "MabiDaily")

    def test_portable(self):
        (self.app / "portable.txt").write_text("", encoding="utf-8")
        (self.app / "MabiDaily_data").mkdir()
        self.assertEqual(self.data_dir(), self.app / "MobiRemote_data")
        self.assertFalse((self.app / "MabiDaily_data").exists())


if __name__ == "__main__":
    unittest.main()
