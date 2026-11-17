"""작업 표시줄 이름 (gui_app/taskbar.py) — 다시 켜는 명령과 실패해도 창을 막지 않는지."""
import sys
import unittest
from unittest import mock

from gui_app import taskbar


class TaskbarTest(unittest.TestCase):
    def test_relaunch_source(self):
        with (mock.patch.object(sys, "frozen", False, create=True),
              mock.patch.object(taskbar, "LAUNCHER", taskbar.ROOT / "없는 파일.exe")):
            cmd, icon = taskbar.relaunch()
        self.assertIn("gui.py", cmd)
        self.assertNotIn("--dressroom", cmd)
        self.assertTrue(icon.endswith("icon.ico"))

    def test_relaunch_launcher(self):
        # 시작 프로그램이 있으면 고정해 둔 단추도 그것으로 켠다 (관리자 확인 창에 'Python' 대신 앱 이름)
        with (mock.patch.object(sys, "frozen", False, create=True),
              mock.patch.object(taskbar, "LAUNCHER", taskbar.ROOT / "gui.py")):
            cmd, icon = taskbar.relaunch()
        self.assertEqual(cmd, f'"{taskbar.ROOT / "gui.py"}"')
        self.assertEqual(icon, f"{taskbar.ROOT / 'gui.py'},0")

    def test_relaunch_frozen(self):
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(sys, "executable", r"C:\App\MobiRemote.exe"):
            cmd, icon = taskbar.relaunch()
        self.assertEqual(cmd, r'"C:\App\MobiRemote.exe"')
        self.assertEqual(icon, r"C:\App\MobiRemote.exe,0")

    def test_failure_is_quiet(self):
        class Broken:
            def winId(self):  # noqa: N802
                raise RuntimeError("창 없음")
        with self.assertLogs("mabi.gui", "WARNING"):
            self.assertFalse(taskbar.brand(Broken(), "이름"))


if __name__ == "__main__":
    unittest.main()
