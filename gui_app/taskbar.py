"""작업 표시줄에 보일 앱 이름·아이콘을 창마다 붙인다 (윈도 창 속성).

소스로 켜면 프로세스가 pythonw.exe 라 작업 표시줄 오른쪽 클릭 메뉴(점프 목록)에 'Python' 이 뜬다.
앱 ID 만 따로 주면 묶음만 갈라지고 이름은 여전히 exe 설명에서 가져오므로,
창 속성에 앱 ID·다시 켜는 명령·표시 이름·아이콘을 함께 넣는다 (넷 중 명령과 이름이 같이 있어야 이름이 쓰인다).
"""
from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from pathlib import Path

log = logging.getLogger("mabi.gui")

APP_ID = "MobiRemote.App"   # 리모콘·드레스룸이 한 묶음
ROOT = Path(__file__).resolve().parent.parent


class _GUID(ctypes.Structure):
    _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]

    @classmethod
    def of(cls, s: str) -> "_GUID":
        h = s.strip("{}").replace("-", "")
        return cls(int(h[:8], 16), int(h[8:12], 16), int(h[12:16], 16), (ctypes.c_ubyte * 8)(*bytes.fromhex(h[16:])))


class _PKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", wintypes.DWORD)]


class _PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("p", ctypes.c_void_p), ("pad", ctypes.c_void_p)]


_VT_LPWSTR = 31
_IID_IPropertyStore = "{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}"
_FMT = "{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"   # PKEY_AppUserModel_*
_ID, _COMMAND, _ICON, _NAME = 5, 2, 3, 4


LAUNCHER = ROOT / ".venv" / "Scripts" / "모비 커넥터 리모콘.exe"   # 소스 실행용 시작 프로그램 (tools/make_launcher.py)


def relaunch() -> tuple[str, str]:
    """(다시 켜는 명령, 아이콘 자원) — 배포판은 exe, 소스는 시작 프로그램이 있으면 그것, 없으면 pythonw + gui.py."""
    exe = Path(sys.executable)
    if getattr(sys, "frozen", False):
        return f'"{exe}"', f"{exe},0"
    if LAUNCHER.is_file():
        return f'"{LAUNCHER}"', f"{LAUNCHER},0"
    w = exe.with_name("pythonw.exe")
    return f'"{w if w.exists() else exe}" "{ROOT / "gui.py"}"', str(ROOT / "tools" / "icon.ico")


def brand(window, name: str) -> bool:
    """창(QWidget)의 작업 표시줄 이름·아이콘을 정한다. 창을 띄우기 전에 부른다. 실패해도 창은 그대로 쓴다."""
    if sys.platform != "win32":
        return False
    command, icon = relaunch()
    try:
        hwnd = int(window.winId())
        store = ctypes.c_void_p()
        hr = ctypes.windll.shell32.SHGetPropertyStoreForWindow(
            wintypes.HWND(hwnd), ctypes.byref(_GUID.of(_IID_IPropertyStore)), ctypes.byref(store))
        if hr != 0 or not store:
            raise OSError(f"SHGetPropertyStoreForWindow {hr & 0xFFFFFFFF:#x}")
        vtbl = ctypes.cast(ctypes.cast(store, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_PKEY), ctypes.POINTER(_PROPVARIANT))
        set_value = proto(vtbl[6])
        commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtbl[7])
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])
        try:
            keep = []
            for pid, text in ((_ID, APP_ID), (_COMMAND, command), (_ICON, icon), (_NAME, name)):
                buf = ctypes.create_unicode_buffer(text)
                keep.append(buf)
                pv = _PROPVARIANT(vt=_VT_LPWSTR, p=ctypes.cast(buf, ctypes.c_void_p).value)
                hr = set_value(store, ctypes.byref(_PKEY(_GUID.of(_FMT), pid)), ctypes.byref(pv))
                if hr != 0:
                    raise OSError(f"SetValue({pid}) {hr & 0xFFFFFFFF:#x}")
            commit(store)
        finally:
            release(store)
        return True
    except Exception as e:   # 이름이 'Python' 으로 남을 뿐이다
        log.warning(f"작업 표시줄 이름을 못 정함: {e}")
        return False
