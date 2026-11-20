"""패킷 표는 설치 폴더 것만 쓰고, 데이터 폴더에 남은 옛 표는 .old 로 치운다 (mabi.packet_table)."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from mabi import packet_table


class TableFileTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data, self.res = Path(tmp.name) / "user", Path(tmp.name) / "app"
        for d in (self.data, self.res):
            (d / "data").mkdir(parents=True)
        (self.res / "data" / packet_table.FILE_NAME).write_bytes(b"new")

    def patch(self, data):
        return [mock.patch.object(packet_table.paths, "load", return_value=SimpleNamespace(data=data)),
                mock.patch.object(packet_table.paths, "resource_dir", return_value=self.res)]

    def run_patched(self, data, fn):
        ps = self.patch(data)
        for p in ps:
            p.start()
        try:
            return fn()
        finally:
            for p in ps:
                p.stop()

    def test_stray_table_in_data_folder_is_renamed(self):
        stray = self.data / "data" / packet_table.FILE_NAME
        stray.write_bytes(b"old")
        old = self.run_patched(self.data, packet_table.retire_stray)
        self.assertFalse(stray.exists())
        self.assertEqual(old.read_bytes(), b"old")
        self.assertEqual(self.run_patched(self.data, packet_table.table_file), self.res / "data" / packet_table.FILE_NAME)

    def test_same_folder_is_left_alone(self):
        self.assertIsNone(self.run_patched(self.res, packet_table.retire_stray))
        self.assertTrue((self.res / "data" / packet_table.FILE_NAME).exists())


if __name__ == "__main__":
    unittest.main()
