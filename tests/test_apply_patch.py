"""설치판 패치 적용 (gui._apply_patch) — 지난번에 못 지운 옛 폴더가 있어도 바뀌고, 실패하면 판과 이유를 남긴다."""
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("gui_entry", ROOT / "gui.py")
gui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui)


class ApplyPatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        (self.home / "runtime.txt").write_text("rt1", encoding="utf-8")
        app = self.home / "app"
        app.mkdir()
        (app / "version.json").write_text(json.dumps({"version": "1.0.0", "runtime": "rt1"}), encoding="utf-8")
        (self.home / "update").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def zip(self, version="1.0.1", runtime="rt1"):
        with zipfile.ZipFile(self.home / "update" / "patch.zip", "w") as z:
            z.writestr("version.json", json.dumps({"version": version, "runtime": runtime}))

    def version(self):
        return json.loads((self.home / "app" / "version.json").read_text(encoding="utf-8"))["version"]

    def test_leftover_old_folder_does_not_block(self):
        (self.home / "app.old").mkdir()  # 지난번에 지우다 남은 것
        self.zip()
        gui._apply_patch(self.home)
        self.assertEqual(self.version(), "1.0.1")
        self.assertFalse((self.home / "update" / "patch.zip").exists())
        self.assertEqual(list(self.home.glob("app.old*")), [])

    def test_failure_keeps_app_and_records_version(self):
        self.zip(runtime="other")
        gui._apply_patch(self.home)
        self.assertEqual(self.version(), "1.0.0")
        err = (self.home / "update" / "patch-error.txt").read_text(encoding="utf-8")
        self.assertEqual(err.split("\n")[0], "1.0.0")

    def test_locked_rename_retries(self):
        self.zip()
        real, calls = Path.rename, []

        def flaky(src, dst):
            calls.append(src.name)
            if len(calls) == 1:
                raise PermissionError("잠김")
            return real(src, dst)

        with mock.patch.object(Path, "rename", flaky), mock.patch("time.sleep"):
            gui._apply_patch(self.home)
        self.assertEqual(self.version(), "1.0.1")


if __name__ == "__main__":
    unittest.main()
