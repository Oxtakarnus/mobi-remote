"""찍는 동안 가리기 (screen.add_grab_veil): 캡처 제외가 안 걸린 우리 창은 찍기 전에 가리고, 찍은 뒤(실패해도) 되돌린다."""
import unittest
from types import SimpleNamespace

import numpy as np

from mabi import screen as scr


class FakeVeil:
    def __init__(self, shown=True):
        self.shown, self.calls = shown, []

    def before(self):
        self.calls.append("before")
        return self.shown

    def after(self):
        self.calls.append("after")


class FakeSct:
    def __init__(self, fail=False):
        self.fail = fail

    def grab(self, box):
        if self.fail:
            raise OSError("찍기 실패")
        return np.zeros((box["height"], box["width"], 4), np.uint8)


def make_screen(fail=False):
    s = scr.Screen.__new__(scr.Screen)
    s.window = SimpleNamespace(client_rect=lambda: SimpleNamespace(left=0, top=0, width=1920, height=1080))
    s._local = SimpleNamespace(sct=FakeSct(fail))
    return s


class GrabVeilTest(unittest.TestCase):
    def tearDown(self):
        scr._grab_veils.clear()

    def test_veil_wraps_grab(self):
        v = FakeVeil()
        scr.add_grab_veil(v)
        scr.add_grab_veil(v)  # 두 번 등록해도 한 번
        make_screen().grab()
        self.assertEqual(v.calls, ["before", "after"])

    def test_not_shown_is_not_restored(self):
        v = FakeVeil(shown=False)
        scr.add_grab_veil(v)
        make_screen().grab()
        self.assertEqual(v.calls, ["before"])

    def test_restored_when_grab_fails(self):
        v = FakeVeil()
        scr.add_grab_veil(v)
        with self.assertRaises(OSError):
            make_screen(fail=True).grab()
        self.assertEqual(v.calls, ["before", "after"])

    def test_removed_veil_is_skipped(self):
        v = FakeVeil()
        scr.add_grab_veil(v)
        scr.remove_grab_veil(v)
        make_screen().grab()
        self.assertEqual(v.calls, [])


if __name__ == "__main__":
    unittest.main()
