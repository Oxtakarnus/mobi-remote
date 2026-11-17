"""드레스룸 텍스처 저장소와 꺼내기 오류 기록.

TextureStore: 게임 텍스처를 tex/<이름>.png 로 한 번만 꺼낸다 (옷·이펙트·무대가 같은 폴더·규칙을 쓴다).
이름마다 잠가, 여러 모델이 같은 그림을 동시에 꺼내도 한 번만 풀고 서로의 임시 파일을 건드리지 않는다.

꺼내다 생긴 오류는 problem() 으로 남긴다 — 같은 오류는 경고 로그 한 줄, 그 그림·재질만 빼고 그린다.
환경 탓(모듈·dll 없음, 디스크·권한, 메모리 — RETRY)이면 지금 꺼내는 모델의 '다시 꺼낼 까닭' 에도 넣는다 (collect).
서비스는 그런 모델을 반쪽으로 표시해 두고 다음에 창을 열 때 다시 꺼낸다. 예전엔 오류를 조용히 삼켜,
설치판에 fmod.dll 이 빠졌을 때 모든 옷이 텍스처 없이 흰색으로 캐시에 굳었고 로그도 없었다 (3.23.0 첫 빌드).
여러 모델이 같이 쓰는 값을 메모리에 기억하는 쪽(이펙트 prefab·재질, 모델 정의)은 retries() 를 앞뒤로 견줘
환경 탓 오류가 섞인 결과는 기억하지 않는다 — 다음 모델이 빠진 값을 반쪽 표시 없이 가져가지 않게.
"""
import logging
import re
import threading
from contextlib import contextmanager
from pathlib import Path

from ..fileio import save_image

log = logging.getLogger("mabi")

RETRY = (ImportError, OSError, MemoryError)   # 다시 꺼내면 될 수 있는 오류 (자료가 아니라 환경 탓)

_local = threading.local()
_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}
_warned: set[str] = set()


@contextmanager
def collect():
    """이 스레드에서 도는 꺼내기의 '다시 꺼낼 까닭' 을 모은다 — with collect() as problems: …"""
    prev = getattr(_local, "problems", None)
    _local.problems = problems = []
    try:
        yield problems
    finally:
        _local.problems = prev


def problem(what: str, e: BaseException) -> None:
    """꺼내다 생긴 오류 — 경고 로그(같은 것은 한 번), 환경 탓이면 collect 목록에도."""
    msg = f"{what}: {type(e).__name__}: {e}"
    with _guard:
        fresh = msg not in _warned
        _warned.add(msg)
    if fresh:
        log.warning(f"드레스룸 {msg}")
    if isinstance(e, RETRY):
        _local.retries = retries() + 1
        problems = getattr(_local, "problems", None)
        if problems is not None:
            problems.append(msg)


def retries() -> int:
    """이 스레드에서 지금까지 남긴 환경 탓(RETRY) 오류 수 — 앞뒤로 견줘 그 사이에 났나 본다."""
    return getattr(_local, "retries", 0)


def lock(path) -> threading.Lock:
    """파일마다 하나인 잠금 (프로세스 안)."""
    key = str(Path(path).resolve()).lower()
    with _guard:
        return _locks.setdefault(key, threading.Lock())


def tex_name(t) -> str:
    """Texture2D → 파일 이름 (확장자 빼고)."""
    return re.sub(r"[^\w.-]", "_", t.m_Name)


class TextureStore:
    def __init__(self, tex_dir: Path):
        self.dir = Path(tex_dir)

    def path(self, name: str) -> Path:
        return self.dir / f"{name}.png"

    def save(self, t) -> str:
        """Texture2D → 이름 (이미 있으면 그대로). 못 풀면 오류를 올린다."""
        name = tex_name(t)
        f = self.path(name)
        if not f.exists():
            with lock(f):
                if not f.exists():
                    img = t.image.convert("RGBA")
                    if img.getextrema()[3][0] >= 250:   # 알파가 사실상 다 불투명(압축 잡음 253~255)이면 RGB 로
                        img = img.convert("RGB")
                    save_image(f, img)
        return name

    def ref(self, ptr) -> str | None:
        """텍스처 포인터 → 이름. 빈 포인터·못 꺼낸 그림은 None (오류는 problem 으로)."""
        if ptr is None or not ptr.m_PathID:
            return None
        try:
            return self.save(ptr.deref().read())
        except Exception as e:
            problem("그림을 꺼내지 못했습니다", e)
            return None

    @staticmethod
    def srgb(ptr) -> bool:
        """색 그림(sRGB)인가 — m_ColorSpace 0 이면 값 그림(선형). 못 읽으면 색 그림으로 본다."""
        try:
            return getattr(ptr.deref().read(), "m_ColorSpace", 1) != 0
        except Exception:
            return True
