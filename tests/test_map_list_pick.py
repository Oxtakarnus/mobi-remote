"""지역 맵 목록 칸 고르기: 템플릿이 안 맞아도 (이름 아래 진행도 '일반 100%' 가 붙어 이름이 올라간 칸) 글자로 확인해 누른다."""
import unittest
from unittest import mock

from mabi.tasks import worldmap

PLACE = {"town": "이멘마하", "tab": "남부", "index": 1, "label": "place_04"}


def make_bot(template_hit):
    b = mock.MagicMock()
    b.cfg = {"map": {"tabs": {"남부": [220, 1022]}, "list_y": [884, 951, 1018], "list_y_tabbed": [816, 883, 950],
                     "list_x": 150, "list_threshold": 0.97, "info_name_region": [0, 0, 10, 10]}}
    b.find.return_value = object() if template_hit else None
    return b


class PickFromListTest(unittest.TestCase):
    def pick(self, template_hit, texts):
        b = make_bot(template_hit)
        with (mock.patch("mabi.ocr.find_texts", return_value=[(t, 130, 870) for t in texts]),
              mock.patch.object(worldmap, "_read_best", return_value=(1.0, "룬다 던전"))):
            ok = worldmap._pick_from_list(b, PLACE, "룬다 던전")
        clicked = (150, 883) in [c.args[0] for c in b.click.call_args_list]
        return ok, clicked

    def test_template_match_clicks(self):
        self.assertEqual(self.pick(True, []), (True, True))

    def test_progress_line_falls_back_to_text(self):
        self.assertEqual(self.pick(False, ["룬다 던전", "일반 100%"]), (True, True))

    def test_other_place_is_not_clicked(self):
        self.assertEqual(self.pick(False, ["피오드 던전", "일반 100%"]), (False, False))


if __name__ == "__main__":
    unittest.main()
