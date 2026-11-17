"""드레스룸 창 — 리모콘이 따로 띄우는 프로세스 (gui.py --dressroom).

리모콘 화면은 GPU 를 끄고 그린다 (gui.py — 게임과 GPU 를 나눠 쓰다 화면 엔진이 죽은 일이 있어서). 3D(WebGL)는 GPU 없이
그릴 수 없으므로 드레스룸만 GPU 를 켠 별도 프로세스로 띄운다. 이 프로세스가 죽어도 리모콘은 그대로다.

  리모콘 → 드레스룸   Launcher.open: 떠 있으면 'show' 를 보내 앞으로, 없으면 새로 띄운다 (DRESS_PIPE)
  드레스룸 → 리모콘   control.call: 기억 값·재질 딱지·프리셋 넣기·게임 캐릭터 외형
                      (제어 통로 명령 dress_prefs · dye_reach · dye_add · dress_look)
                      제어 통로 연결 하나를 열어 두고, 그것이 끊기면(리모콘이 꺼지면) 같이 닫는다

화면은 web/dressroom/ (three.js) 을 mmdress://app/ 으로 띄우고, 게임에서 꺼낸 자료(mabi.dress, 데이터 폴더 dressroom\\)는
mmdress://app/cache/ 로 읽는다. 같은 주소 아래라 ES 모듈·fetch 가 그대로 된다 (file:// 은 모듈을 막는다).
"""
from __future__ import annotations

import json
import logging
import mimetypes
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt, QTimer, QUrl
from PySide6.QtGui import QIcon
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (QWebEngineProfile, QWebEngineScript, QWebEngineUrlRequestJob, QWebEngineUrlScheme,
                                     QWebEngineUrlSchemeHandler)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QMainWindow

from mabi.dress.service import DressError, DressRoom
from mabi.fileio import write_json

from . import taskbar
from .api import APP_NAME, _GuiCall
from .web_shell import WEB, Backend, Page, _qrc_text

log = logging.getLogger("mabi")
SCHEME = b"mmdress"
APP_DIR = WEB / "dressroom"
TITLE = "드레스룸"
DRESS_PIPE = "MobiRemote-dressroom"
ROOT = Path(__file__).resolve().parent.parent
# GPU 는 3D 에만 쓴다 — 목록·글자는 CPU 로 그리고, 3D 는 게임과 같은 D3D11 경로로 (ANGLE 기본값이지만 못 박아 둔다).
# 리모콘에서 물려받은 --disable-gpu 는 이것으로 덮는다
GPU_FLAGS = "--use-angle=d3d11 --disable-gpu-rasterization"


def register_scheme() -> None:
    """QApplication 을 만들기 전에 부른다."""
    s = QWebEngineUrlScheme(SCHEME)
    s.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    s.setDefaultPort(QWebEngineUrlScheme.SpecialPort.PortUnspecified.value)   # PySide6 는 int 만 받는다
    s.setFlags(QWebEngineUrlScheme.Flag.SecureScheme | QWebEngineUrlScheme.Flag.LocalScheme
               | QWebEngineUrlScheme.Flag.LocalAccessAllowed | QWebEngineUrlScheme.Flag.CorsEnabled
               | QWebEngineUrlScheme.Flag.FetchApiAllowed)   # 뷰어가 모델(json·bin)을 fetch 로 읽는다
    QWebEngineUrlScheme.registerScheme(s)


def resolve(room: DressRoom, url_path: str) -> Path | None:
    """mmdress://app/<경로> → 파일. cache/… 는 데이터 폴더, 나머지는 web/dressroom. 그 밖으로는 못 나간다."""
    rel = url_path.lstrip("/")
    if rel.startswith("cache/"):
        return room.path(rel[len("cache/"):])
    f = (APP_DIR / (rel or "index.html")).resolve()
    try:
        f.relative_to(APP_DIR.resolve())
    except ValueError:
        return None
    return f if f.is_file() else None


class _Handler(QWebEngineUrlSchemeHandler):
    def __init__(self, room: DressRoom, parent=None):
        super().__init__(parent)
        self.room = room

    def requestStarted(self, job: QWebEngineUrlRequestJob) -> None:  # noqa: N802
        url = job.requestUrl()
        f = resolve(self.room, url.path()) if url.host() == "app" else None
        if f is None:
            job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
            return
        mime = {".js": "text/javascript", ".json": "application/json", ".bin": "application/octet-stream",
                ".css": "text/css", ".html": "text/html", ".png": "image/png"}.get(f.suffix.lower()) \
            or mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        buf = QBuffer(job)
        buf.setData(QByteArray(f.read_bytes()))
        buf.open(QIODevice.OpenModeFlag.ReadOnly)
        job.reply(mime.encode(), buf)


_BAD_NAME = set('\\/:*?"<>|')   # 파일 이름에 못 쓰는 글자


def safe_name(name, default: str) -> str:
    """파일 이름으로 쓸 수 있게 — 못 쓰는 글자를 빼고 앞뒤 빈칸·점을 깎는다 (비면 default)."""
    return "".join(c for c in str(name or default) if c not in _BAD_NAME).strip(" .") or default


LOOK_FORMAT = "dressroom-look"   # 코디 파일 표시 (형식 검사는 여기서만 — 화면은 값 모양만 본다)
LOOK_FILE_MAX = 256 * 1024       # 가져올 코디 파일 크기 상한 (바이트)


class DressApi:
    """드레스룸 화면이 부르는 것. 무거운 일(목록·모델 꺼내기)은 Backend 의 작업 스레드에서 돈다.
    call(cmd, args) 는 리모콘 제어 통로에 묻는 함수 (control.call) — 실패하면 예외.
    파일 창은 화면 스레드에서만 열린다 — 창이 gui(_GuiCall)·win 을 넣어 준다."""

    def __init__(self, room: DressRoom, call):
        self.room, self._call = room, call
        self.gui: _GuiCall | None = None
        self.win = None
        self._dir = ""   # 코디 파일 창이 마지막으로 연 폴더

    def _pick(self, fn):
        if self.gui is None:
            return None
        return self.gui.call(fn)

    def _look_dir(self) -> str:
        if self._dir and Path(self._dir).is_dir():
            return self._dir
        docs = Path.home() / "Documents"
        return str(docs if docs.is_dir() else Path.home())

    def look_export(self, name, look):
        """코디 하나를 사람이 고른 json 파일로."""
        from PySide6.QtWidgets import QFileDialog
        if not isinstance(look, dict):
            return {"error": "코디 값이 이상합니다"}
        safe = safe_name(name, "코디")
        f = self._pick(lambda: QFileDialog.getSaveFileName(self.win, "코디 내보내기", str(Path(self._look_dir()) / f"{safe}.json"),
                                                           "드레스룸 코디 (*.json)")[0])
        if not f:
            return {"canceled": True}
        self._dir = str(Path(f).parent)
        try:
            write_json(Path(f), {"format": LOOK_FORMAT, **look}, indent=1)
        except OSError as e:
            return {"error": f"파일을 쓰지 못했습니다 ({e})"}
        return {"ok": True, "file": Path(f).name}

    def look_import(self):
        """사람이 고른 코디 json → {"look": …, "file": 이름}. 모양 확인은 화면이 한다."""
        from PySide6.QtWidgets import QFileDialog
        f = self._pick(lambda: QFileDialog.getOpenFileName(self.win, "코디 가져오기", self._look_dir(),
                                                           "드레스룸 코디 (*.json)")[0])
        if not f:
            return {"canceled": True}
        self._dir = str(Path(f).parent)
        try:
            if Path(f).stat().st_size > LOOK_FILE_MAX:
                return {"error": "코디 파일이 너무 큽니다"}
            d = json.loads(Path(f).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as e:
            return {"error": f"코디 파일을 읽지 못했습니다 ({type(e).__name__})"}
        if not isinstance(d, dict) or d.get("format") != LOOK_FORMAT:
            return {"error": "드레스룸 코디 파일이 아닙니다"}
        return {"look": d, "file": Path(f).stem}

    def catalog(self):
        try:
            return self.room.catalog()
        except DressError as e:
            return {"error": str(e)}

    def model(self, mid):
        """모델 → {"url"} 또는 {"error"} — 처음 보는 형식도 서비스가 DressError 로 바꾼다 (이 옷만 못 보고 창은 그대로)."""
        try:
            return {"url": "cache/" + self.room.model(str(mid))}
        except DressError as e:
            return {"error": str(e)}

    def icon(self, mid):
        """의상 아이콘 → {"url": "cache/icons/<id>.png"}. 게임 아이템 아이콘이 없으면 {"url": None}."""
        try:
            rel = self.room.icon(str(mid))
            return {"url": "cache/" + rel if rel else None}
        except DressError as e:
            return {"error": str(e)}

    def _ask(self, cmd: str, args: dict):
        try:
            return self._call(cmd, args)
        except Exception as e:   # 리모콘이 꺼졌거나 답이 이상하다
            log.warning(f"드레스룸 → 리모콘 {cmd}: {e}")
            return {"error": f"리모콘에 묻지 못했습니다 ({e})"}

    def reach(self, colors, tols=None):
        return self._ask("dye_reach", {"colors": colors, "tols": tols})

    def prefs(self):
        v = self._ask("dress_prefs", {})
        return v if isinstance(v, dict) and "error" not in v else {}

    def save_prefs(self, v):
        if isinstance(v, dict):
            self._ask("dress_prefs", {"set": v})
        return {"ok": True}

    def to_preset(self, name, colors):
        """색 셋을 염색 탭 프리셋으로 (리모콘 Api.dress_preset)."""
        return self._ask("dye_add", {"name": name, "colors": colors})

    def game_look(self):
        """리모콘 패킷 감시가 마지막으로 본 내 캐릭터 → {"look": 코디, "miss": [못 입힌 것], "at": 받은 시각}."""
        try:
            snap = self._call("dress_look", {})
        except Exception as e:   # 리모콘이 꺼졌거나 아직 못 받음 (답의 글을 그대로 보인다)
            return {"error": str(e)}
        try:
            look, miss = self.room.game_look(snap)
        except DressError as e:
            return {"error": str(e)}
        return {"look": look, "miss": miss, "at": snap.get("at") if isinstance(snap, dict) else None}

    def fullscreen(self, on=None):
        """창 전체 화면 켜기·끄기 (on 이 없으면 바꾼다) → {"on": 지금 상태}. 창 일은 화면 스레드에서."""
        win = self.win
        if win is None or self.gui is None:
            return {"error": "창이 없습니다"}

        def flip():
            want = (not win.isFullScreen()) if on is None else bool(on)
            if want != win.isFullScreen():
                win.showFullScreen() if want else win.showNormal()
            return win.isFullScreen()
        return {"on": bool(self.gui.call(flip))}


class DressWindow(QMainWindow):
    def __init__(self, room: DressRoom, call, theme: str = "dark"):
        super().__init__()
        self.setWindowTitle(TITLE)
        self.setWindowIcon(QIcon(str(WEB / "icon.png")))
        taskbar.brand(self, APP_NAME)   # 리모콘과 한 묶음 — 메뉴 이름·다시 켜기도 리모콘으로
        self.resize(1360, 860)
        self.setMinimumSize(980, 620)
        api = DressApi(room, call)
        api.gui, api.win = _GuiCall(), self   # 코디 파일 창 (화면 스레드에서 만든다)
        self.backend = Backend(api)
        self.profile = QWebEngineProfile(self)   # 기록을 남기지 않는 프로필
        self.handler = _Handler(room, self.profile)
        self.profile.installUrlSchemeHandler(SCHEME, self.handler)
        view = QWebEngineView(self)
        view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        page = Page(self.profile, view)
        view.setPage(page)
        sc = QWebEngineScript()
        sc.setName("mm-dress-channel")
        # 테마(리모콘과 같게) → qwebchannel.js 순으로 페이지보다 먼저 심는다
        init = {"theme": "light" if theme == "light" else "dark"}
        sc.setSourceCode("window.__MM_INIT__ = " + json.dumps(init) + ";\n" + _qrc_text(":/qtwebchannel/qwebchannel.js"))
        sc.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        sc.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        page.scripts().insert(sc)
        ch = QWebChannel(page)
        ch.registerObject("backend", self.backend)
        page.setWebChannel(ch)
        view.load(QUrl("mmdress://app/index.html"))
        self.view = view
        self.setCentralWidget(view)

    def front(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, e):  # noqa: N802
        # 화면(페이지)을 프로필보다 먼저 지운다 — 창은 이 뒤에 지워지며 프로필을 데려간다
        self.view.deleteLater()
        super().closeEvent(e)


# ---------------------------------------------------------------- 리모콘 쪽
def _poke(msg: str) -> bool:
    """떠 있는 드레스룸에 한 줄 보낸다 ('show' 앞으로 · 'quit' 닫기). 없으면 False."""
    try:
        with open(r"\\.\pipe" + "\\" + DRESS_PIPE, "wb", buffering=0) as f:
            f.write(msg.encode() + b"\n")
        return True
    except OSError:
        return False


def child_argv(theme: str) -> list[str]:
    extra = ["--dressroom", f"--theme={theme}"]
    if getattr(sys, "frozen", False):
        return [sys.executable, *extra]
    return [sys.executable, str(ROOT / "gui.py"), *extra]


class Launcher:
    """드레스룸 프로세스를 띄우거나 앞으로 부른다 (리모콘 Api 가 하나 들고 있다)."""
    START_GRACE = 20   # 띄운 뒤 이 초 안에 다시 누르면 뜨는 중으로 본다

    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.started = 0.0
        self._lock = threading.Lock()

    def open(self, theme: str) -> dict:
        with self._lock:
            if sys.platform == "win32":   # 리모콘이 앞에 있을 때 누른 것 — 드레스룸 창이 앞으로 나올 수 있게
                import ctypes
                ctypes.windll.user32.AllowSetForegroundWindow(-1)
            if _poke("show"):
                return {"ok": True}
            if self.proc and self.proc.poll() is None:
                # 띄운 창이 아직 있다 — 뜨는 중이거나 신호 통로가 안 열린 것. 두 번째 창은 띄우지 않는다: 두 창이 각자
                # 설정을 저장해 서로 덮어쓴다 (11-16 23:54 창이 떠 있는데 00:15 에 하나 더 떠 00:32 까지 같이 돌았다)
                if time.time() - self.started >= self.START_GRACE:
                    log.warning(f"드레스룸: 떠 있는 창(pid {self.proc.pid})에 신호가 닿지 않아 새 창을 띄우지 않습니다")
                return {"ok": True}
            env = {k: v for k, v in os.environ.items() if k != "QTWEBENGINE_CHROMIUM_FLAGS"}
            try:
                self.proc = subprocess.Popen(child_argv(theme), env=env, close_fds=True,
                                             cwd=str(Path(sys.executable).parent if getattr(sys, "frozen", False) else ROOT))
            except OSError as e:
                return {"error": f"드레스룸을 띄우지 못했습니다 ({e})"}
            self.started = time.time()
            log.info(f"드레스룸 띄움 (pid {self.proc.pid})")
            threading.Thread(target=self._watch, args=(self.proc,), name="dressroom-watch", daemon=True).start()
            return {"ok": True}

    @staticmethod
    def _watch(proc: subprocess.Popen) -> None:
        """드레스룸이 끝나면 종료 코드를 남긴다 — 네이티브 충돌(0xC0000005 등)은 드레스룸 쪽 로그에 시각이 안 남는다."""
        code = proc.wait()
        if code:
            log.warning(f"드레스룸 비정상 종료 (pid {proc.pid}, 코드 0x{code & 0xFFFFFFFF:08X})")

    def close(self) -> None:
        _poke("quit")


# ---------------------------------------------------------------- 드레스룸 프로세스
_crash_file = None


def _theme(argv: list[str]) -> str:
    return next((a.partition("=")[2] for a in argv if a.startswith("--theme=")), "dark")


def main() -> int:
    """gui.py --dressroom. 리모콘이 띄우고, 리모콘이 꺼지면 같이 닫는다."""
    global _crash_file
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = GPU_FLAGS
    import faulthandler

    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import QApplication

    from mabi import paths as mpaths
    from mabi.runner import setup_logging

    from . import control
    paths = mpaths.load()
    setup_logging(paths, console=False, name="dressroom")
    _crash_file = open(paths.logs / "crash-dressroom.log", "a", encoding="utf-8")
    _crash_file.write(f"--- 드레스룸 시작 {time.strftime('%Y-%m-%d %H:%M:%S')} (pid {os.getpid()})\n")   # 충돌 기록이 언제 것인지
    _crash_file.flush()
    faulthandler.enable(_crash_file, all_threads=True)
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(taskbar.APP_ID)   # 작업 표시줄에서 리모콘과 한 묶음
    register_scheme()
    app = QApplication(sys.argv)
    app.setApplicationName(TITLE)
    app.setWindowIcon(QIcon(str(WEB / "icon.png")))
    if _poke("show"):   # 이미 떠 있다
        return 0
    link = QLocalSocket()
    link.connectToServer(control.PIPE)
    if not link.waitForConnected(3000):
        log.warning("드레스룸: 리모콘 제어 통로에 붙지 못해 닫습니다")
        return 1
    QLocalServer.removeServer(DRESS_PIPE)
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    if not server.listen(DRESS_PIPE):
        # 앞 창이 닫히는 중이라 이름이 남아 있을 수 있다 — 열릴 때까지 다시 연다 (못 열면 리모콘 버튼이 이 창을 못 부른다)
        log.warning(f"드레스룸 신호 통로를 열지 못함: {server.errorString()} — 2초마다 다시")
        retry = QTimer(app)

        def relisten() -> None:
            if server.listen(DRESS_PIPE):
                retry.stop()
                log.info("드레스룸 신호 통로 열림")
        retry.timeout.connect(relisten)
        retry.start(2000)
    win = DressWindow(DressRoom(paths.data / "dressroom"), control.call, _theme(sys.argv))

    def read(conn) -> None:
        for line in bytes(conn.readAll()).split(b"\n"):
            if line.strip() == b"show":
                win.front()
            elif line.strip() == b"quit":
                win.close()

    def accept() -> None:
        while server.hasPendingConnections():
            conn = server.nextPendingConnection()
            conn.readyRead.connect(lambda c=conn: read(c))
            conn.disconnected.connect(lambda c=conn: (read(c), c.deleteLater()))
            read(conn)   # 붙자마자 써 두고 끊는 쪽 — 이미 와 있는 글

    server.newConnection.connect(accept)
    link.disconnected.connect(win.close)   # 리모콘이 꺼졌다
    win.front()
    log.info(f"드레스룸 시작 (pid {os.getpid()})")
    return app.exec()
