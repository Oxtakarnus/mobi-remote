"""드레스룸 캐시 쓰기 — 한 번에 바꿔 넣기(fileio), 텍스처 저장소·오류 기록(textures), 반쪽 모델 다시 꺼내기(service)."""
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

from PIL import Image

from mabi import fileio
from mabi.dress import fx as FX
from mabi.dress import service as S
from mabi.dress import textures as TX


class _Tex:
    """가짜 Texture2D — image 를 읽을 때마다 센다 (느리게 풀리는 그림)."""

    def __init__(self, name, alpha=255, delay=0.0):
        self.m_Name = name
        self.alpha = alpha
        self.delay = delay
        self.decoded = 0

    @property
    def image(self):
        self.decoded += 1
        time.sleep(self.delay)
        return Image.new("RGBA", (2, 2), (10, 20, 30, self.alpha))


def _ptr(read=None, raise_=None, pid=1):
    def deref():
        if raise_:
            raise raise_
        return NS(read=lambda: read)
    return NS(m_PathID=pid, deref=deref)


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)


class FileIOTest(_Tmp):
    def test_write(self):
        fileio.write_atomic(self.dir / "a" / "x.bin", b"\x00\x01")
        fileio.write_json(self.dir / "a" / "y.json", {"이름": "값"}, separators=(",", ":"))
        self.assertEqual((self.dir / "a" / "x.bin").read_bytes(), b"\x00\x01")
        self.assertEqual((self.dir / "a" / "y.json").read_text(encoding="utf-8"), '{"이름":"값"}')   # 한글 그대로
        fileio.write_atomic(self.dir / "a" / "x.bin", "다시")   # 덮어쓰기
        self.assertEqual((self.dir / "a" / "x.bin").read_text(encoding="utf-8"), "다시")
        self.assertEqual(sorted(p.name for p in (self.dir / "a").iterdir()), ["x.bin", "y.json"])   # 임시 파일 없음

    def test_failure_leaves_nothing(self):
        class Bad:
            def save(self, f, format):
                Path(f).write_bytes(b"half")
                raise OSError("디스크 가득")
        with self.assertRaises(OSError):
            fileio.save_image(self.dir / "p.png", Bad())
        self.assertEqual(list(self.dir.iterdir()), [])   # 반쪽 파일도 임시 파일도 안 남는다


class TextureStoreTest(_Tmp):
    def test_save_once(self):
        st = TX.TextureStore(self.dir / "tex")
        t = _Tex("Top 00/DyeMap")
        self.assertEqual(st.save(t), "Top_00_DyeMap")
        self.assertEqual(st.save(t), "Top_00_DyeMap")
        self.assertEqual(t.decoded, 1)                                   # 있으면 다시 안 푼다
        self.assertEqual(Image.open(st.path("Top_00_DyeMap")).mode, "RGB")   # 다 불투명이면 RGB
        self.assertEqual(Image.open(st.path(st.save(_Tex("Glass", alpha=100)))).mode, "RGBA")

    def test_same_texture_from_threads(self):
        """여러 모델이 같은 그림을 동시에 꺼내도 한 번만 풀고 부딪히지 않는다 (예전엔 고정 이름 .tmp 를 같이 썼다)."""
        st = TX.TextureStore(self.dir / "tex")
        t = _Tex("Shared", delay=0.05)
        errors = []

        def run():
            try:
                st.save(t)
            except Exception as e:   # noqa: BLE001
                errors.append(e)
        threads = [threading.Thread(target=run) for _ in range(8)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertEqual(errors, [])
        self.assertEqual(t.decoded, 1)
        self.assertEqual([p.name for p in (self.dir / "tex").iterdir()], ["Shared.png"])

    def test_ref_records_problems(self):
        st = TX.TextureStore(self.dir / "tex")
        self.assertIsNone(st.ref(None))
        self.assertIsNone(st.ref(NS(m_PathID=0)))
        with TX.collect() as problems:
            self.assertEqual(st.ref(_ptr(_Tex("Ok"))), "Ok")
            with self.assertLogs("mabi", "WARNING"):
                self.assertIsNone(st.ref(_ptr(raise_=OSError("fmod.dll 없음"))))       # 환경 탓 — 다시 꺼낼 까닭
                self.assertIsNone(st.ref(_ptr(raise_=NotImplementedError("모르는 형식"))))   # 자료 탓 — 기록만
        self.assertEqual(len(problems), 1)
        self.assertIn("fmod.dll", problems[0])
        with self.assertNoLogs("mabi", "WARNING"):   # 같은 오류는 로그 한 번
            st.ref(_ptr(raise_=OSError("fmod.dll 없음")))

    def test_collect_is_per_thread(self):
        seen = []

        def other():
            TX.problem("다른 스레드", ImportError("x"))
        with TX.collect() as problems:
            th = threading.Thread(target=other)
            th.start()
            th.join()
            seen.extend(problems)
        self.assertEqual(seen, [])


class BuildTest(_Tmp):
    def setUp(self):
        super().setUp()
        self.room = S.DressRoom(self.dir, game_dir=lambda: None)
        self.calls = 0

    def _make(self, err=None):
        def make(out):
            self.calls += 1
            fileio.write_atomic(out.with_suffix(".bin"), b"b")
            if err:
                TX.problem("그림을 꺼내지 못했습니다", err)
            fileio.write_json(out, {})
        return make

    def test_partial_mark_and_retry(self):
        with self.assertLogs("mabi", "WARNING"):
            self.assertEqual(self.room._build("models/a.json", self._make(OSError("dll"))), "models/a.json")
        mark = self.dir / "models" / "a.partial"
        self.assertIn("dll", mark.read_text(encoding="utf-8"))
        self.room._build("models/a.json", self._make())
        self.assertEqual(self.calls, 1)                      # 이번 창에서는 있는 것을 그대로 쓴다
        self.room._build("models/b.json", self._make(ValueError("형식")))
        self.assertFalse((self.dir / "models" / "b.partial").exists())   # 자료 탓은 다시 꺼내도 같다
        self.room._drop_partial()                            # 다음에 창을 열 때
        self.assertEqual(sorted(p.name for p in (self.dir / "models").iterdir()), ["b.bin", "b.json"])
        self.room._build("models/a.json", self._make())
        self.assertEqual(self.calls, 3)
        self.assertFalse(mark.exists())

    def test_errors(self):
        def boom(e):
            def make(out):
                raise e
            return make
        with self.assertRaisesRegex(S.DressError, "그릴 메시"):
            self.room._build("models/x.json", boom(S.ExportError("그릴 메시가 없습니다")), (S.ExportError,))
        # 구성 요소가 빠진 것은 model 의 한 판정(_guard)이 바꾼다
        err = ImportError("no", name="UnityPy.export")
        with self.assertRaisesRegex(S.DressError, "UnityPy"):
            S._guard("모델", "x", lambda: self.room._build("models/x.json", boom(err)))
        with self.assertRaisesRegex(S.DressError, "fmod_toolkit"):
            S._guard("모델", "x", lambda: self.room._build("models/x.json", boom(ImportError("no", name="fmod_toolkit"))))
        self.assertFalse((self.dir / "models" / "x.json").exists())


class EffectsLockTest(_Tmp):
    def test_table_once(self):
        """여러 스레드가 처음에 같이 불러도 표는 한 번만 만든다."""
        calls = []

        def cached(*a, **k):
            calls.append(1)
            time.sleep(0.05)
            return {"M": [["tl", False]]}, True
        fx = FX.Effects(self.dir, self.dir)
        with mock.patch.object(FX.G, "cached", cached):
            threads = [threading.Thread(target=fx.has, args=("M",)) for _ in range(6)]
            for th in threads:
                th.start()
            for th in threads:
                th.join()
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
