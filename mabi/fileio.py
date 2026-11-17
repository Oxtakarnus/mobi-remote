"""파일을 임시 파일에 다 쓴 뒤 한 번에 바꿔 넣는다 — 쓰다가 프로그램이 죽어도 잘린 파일이 완성본으로 남지 않게.

임시 파일 이름에 프로세스·스레드 번호를 넣어, 여러 스레드가 같은 파일을 동시에 써도 서로의 임시 파일을
건드리지 않는다 (마지막에 바꿔 넣은 쪽이 남는다). 실패하면 임시 파일을 지우고 오류를 그대로 올린다.
"""
import json
import os
import threading
from pathlib import Path


def _tmp(path: Path) -> Path:
    return path.with_name(f"{path.name}.{os.getpid()}-{threading.get_ident()}.tmp")


def _replace(path, write) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp(path)
    try:
        write(tmp)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_atomic(path, data: bytes | str) -> None:
    """bytes 는 그대로, str 은 UTF-8 로 (줄바꿈을 바꾸지 않는다)."""
    raw = data.encode("utf-8") if isinstance(data, str) else data
    _replace(path, lambda tmp: tmp.write_bytes(raw))


def write_json(path, obj, **dumps) -> None:
    """json.dumps(obj, ensure_ascii=False, **dumps) 를 write_atomic 으로."""
    write_atomic(path, json.dumps(obj, ensure_ascii=False, **dumps))


def save_image(path, img, fmt: str = "PNG") -> None:
    """PIL 그림을 write_atomic 과 같은 방식으로."""
    _replace(path, lambda tmp: img.save(tmp, format=fmt))
