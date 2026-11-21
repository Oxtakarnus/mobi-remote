"""저장된 화면 설정만 보는 메인 화면 띠 (display.saved_problems)."""
import unittest
from unittest import mock

from mabi.tasks import display

GOOD = {"GraphicsUserSetting.StandaloneResolutionScale": "1",
        "GraphicsUserSetting.InterfaceStyleType": "1",
        "GraphicsUserSetting.InterfaceStyleScale": "80"}


def run(mode, prefs):
    with mock.patch.object(display, "screen_mode", return_value=mode), \
            mock.patch.object(display, "read_prefs", return_value=prefs):
        return display.saved_problems()


class SavedProblemsTest(unittest.TestCase):
    def test_good_settings_have_no_problem(self):
        self.assertEqual(run((1, 1920, 1080), GOOD), [])
        self.assertEqual(run((1, 2560, 1440), GOOD), [])  # 다른 16:9 는 그대로 쓴다

    def test_each_wrong_setting_is_listed(self):
        bad = run((0, 2560, 1080), {**GOOD, "GraphicsUserSetting.InterfaceStyleScale": "100"})
        self.assertEqual(len(bad), 3)
        self.assertIn("전체화면", bad[0])
        self.assertIn("16:9", bad[1])
        self.assertIn("100%", bad[2])

    def test_scale_ignored_when_not_pc_style(self):
        bad = run((1, 1920, 1080), {**GOOD, "GraphicsUserSetting.InterfaceStyleType": "2",
                                    "GraphicsUserSetting.InterfaceStyleScale": "100"})
        self.assertEqual(len(bad), 1)
        self.assertIn("인터페이스 스타일", bad[0])

    def test_missing_files_say_nothing(self):
        self.assertEqual(run((None, None, None), {}), [])


if __name__ == "__main__":
    unittest.main()
