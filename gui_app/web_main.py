"""웹 화면판 진입점: 하나만 띄우기 · 트레이 · 창 닫기(트레이로 숨기기 또는 정리 후 종료)."""
import logging
import sys

from PySide6.QtCore import QPoint, QRect, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from mabi import paths as mpaths
from mabi.runner import setup_logging

from . import control, taskbar
from .api import APP_NAME, Api
from .web_shell import WEB, WebWindow

log = logging.getLogger("mabi")
SINGLE = "MobiRemote-single"
# 이미 떠 있는 리모콘에 보내는 명령 (gui.py --resume / --halt). 키보드를 못 만질 때 원격으로 이어 하기·멈추기
COMMANDS = {"--resume": b"resume", "--halt": b"halt", "--enhance": b"enhance", "--restart-game": b"restart"}


def _command(argv: list[str]) -> bytes:
    """이미 떠 있는 리모콘에 보낼 명령. 사람이 컴퓨터를 못 만질 때 밖에서 부린다:
      --halt 일시정지 · --resume 이어 하기 · --daily 슬롯,슬롯 [숙제,숙제] [--force] 일일 숙제 카드를 넣고 시작 (--force: 오늘 완료 기록이 있어도 다시)
      --abyss 슬롯 던전 [판수] [난이도] [solo|party] 어비스 카드를 큐 뒤에 넣는다 (판수 0 = 멈출 때까지). 여러 번 부르면 차례로 쌓인다
      --raid 슬롯 레이드 [판수] [난이도] [solo|party] 레이드 카드를 큐 뒤에 넣는다 (어비스와 같음)
      --enhance 각인 강화 반복을 지금 시작 (열어 둔 각인 강화 창에서 — 다른 작업이 돌면 시작하지 않는다)
      --restart-game '게임 다시 켜기' 카드를 지금 (mabi/restart — 제한 창이 없어도 끄고 다시 켜서 같은 캐릭터로 접속,
                     꺼져 있으면 켜서 접속. 다른 PC 에서 시험할 때도. 돌던 카드는 밀렸다가 이어서)
      마지막 칸은 혼자하기(solo) / 함께하기(party). 비우면 설정 탭에 고른 대로"""
    for flag in ("--abyss", "--raid"):
        if flag in argv:
            i = argv.index(flag)
            rest = [a for a in argv[i + 1:i + 6] if not a.startswith("--")]
            return (flag[2:] + ":" + ":".join(rest)).encode()
    if "--daily" in argv:
        i = argv.index("--daily")
        rest = [a for a in argv[i + 1:i + 3] if not a.startswith("--")]
        rest += [""] * (2 - len(rest)) + (["force"] if "--force" in argv else [])
        return ("daily:" + ":".join(rest)).encode()
    return next((m for a, m in COMMANDS.items() if a in argv), b"show")


def _on_message(win: "MainWindow", conn) -> None:
    """예전 통로의 글자 한 줄 → 제어 통로와 같은 명령 (gui_app.control). 모르는 글자면 창을 앞으로."""
    msg = bytes(conn.readAll()).strip()
    cmd = control.legacy(msg)
    if cmd is None:
        win.show_window()
        return
    name, args = cmd
    if name == "show":
        win.show_window()
        return
    r = win.commands.run(name, args)
    if not r.get("ok"):
        log.warning(f"명령 → {name}: 하지 않음 ({r.get('message')})")


class MainWindow(WebWindow):
    def __init__(self, api: Api, commands: control.Commands):
        super().__init__(api, api.initial())
        self.api = api
        self.commands = commands
        self._quitting = False
        self.control: control.ControlServer | None = None
        self.tray = QSystemTrayIcon(QIcon(str(WEB / "tray.png")), self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        menu.addAction(QAction("창 열기", menu, triggered=self.show_window))
        menu.addAction(QAction("종료", menu, triggered=self.quit_app))
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: r in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick)
                                    and self.show_window())
        self.tray.show()
        # 창 자리 기억 — 옮기거나 크기를 바꾸면 잠깐 뒤 저장한다 (리모콘을 강제로 꺼도 남게 닫을 때만 저장하지 않는다)
        self._placed = False
        self._geo_timer = QTimer(self, singleShot=True, interval=800, timeout=self._save_place)

    PLACE_KEY = "window"  # 설정 파일의 창 자리 {x, y, w, h, max}
    _placed = False       # 부모 __init__ 중에도 changeEvent 가 불린다 — 그때는 아직 저장하지 않는다

    def place(self) -> bool:
        """지난번 창 자리로 옮긴다. 기억이 없거나 그 자리가 지금 화면들 밖이면(모니터를 뺐음 등) 주 화면 가운데.
        예전엔 자리를 정하지 않아 Windows 가 켤 때마다 조금씩 아래·오른쪽으로 밀어(새 창 계단식 배치) 오른쪽 아래에 박혔다.
        최대화였으면 True (부르는 쪽이 최대화로 띄운다)."""
        g = self.api.settings.get(self.PLACE_KEY)
        ok = False
        if isinstance(g, dict):
            try:
                rect = QRect(int(g["x"]), int(g["y"]), int(g["w"]), int(g["h"]))
                head = QPoint(rect.center().x(), rect.top() + 20)  # 제목 줄이 어느 화면 안에 있어야 끌어 옮길 수 있다
                ok = QGuiApplication.screenAt(head) is not None
            except (KeyError, TypeError, ValueError):
                ok = False
        if ok:
            self.resize(max(rect.width(), self.minimumWidth()), max(rect.height(), self.minimumHeight()))
            self.move(rect.topLeft())
        else:
            area = QGuiApplication.primaryScreen().availableGeometry()
            frame = self.frameGeometry()
            frame.moveCenter(area.center())
            # 창이 화면보다 크면 가운데에 두면 제목 줄이 위로 넘어간다 — 왼쪽 위는 화면 안에
            self.move(max(frame.left(), area.left()), max(frame.top(), area.top()))
        self._placed = True
        return bool(ok and g.get("max"))

    def _remember(self) -> None:
        if self._placed and self.isVisible() and not self.isMinimized() and hasattr(self, "_geo_timer"):
            self._geo_timer.start()

    def _save_place(self) -> None:
        if self.isMinimized():
            return
        g = dict(self.api.settings.get(self.PLACE_KEY) or {})
        g["max"] = self.isMaximized()
        if not g["max"]:  # 최대화 동안엔 창 모드 자리를 덮지 않는다 — 풀면 그 자리로
            g.update(x=self.x(), y=self.y(), w=self.width(), h=self.height())
        if g != self.api.settings.get(self.PLACE_KEY):
            self.api._save_settings({self.PLACE_KEY: g})

    def moveEvent(self, e):  # noqa: N802
        super().moveEvent(e)
        self._remember()

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        self._remember()

    def changeEvent(self, e):  # noqa: N802
        super().changeEvent(e)
        self._remember()

    def show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_app(self) -> None:
        self._quitting = True
        self.close()

    def closeEvent(self, e):  # noqa: N802
        if self.api.settings.get("closeToTray") and not self._quitting:
            e.ignore()
            self.hide()
            return
        if self.control:
            self.control.close()
        self.api.close()
        t = self.api._daily_thread
        if t and t.is_alive():
            t.join(8)
        self.tray.hide()
        super().closeEvent(e)
        QApplication.quit()


def main() -> int:
    paths = mpaths.load()
    setup_logging(paths, console=False)
    # 작업 표시줄은 프로세스(pythonw.exe)의 아이콘으로 묶어 보여 준다 — 우리 앱 ID 를 따로 주어야 창 아이콘이 쓰인다
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(taskbar.APP_ID)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(QIcon(str(WEB / "icon.png")))
    app.setQuitOnLastWindowClosed(False)  # 트레이로 숨겨도 꺼지지 않게 (종료는 closeEvent 에서)
    # 하나만 띄운다. 이미 떠 있으면 그 창을 앞으로 부르고 끝낸다
    sock = QLocalSocket()
    sock.connectToServer(SINGLE)
    if sock.waitForConnected(300):
        sock.write(_command(sys.argv))
        sock.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(SINGLE)
    server = QLocalServer()
    server.listen(SINGLE)
    ring = control.LogRing()
    logging.getLogger("mabi").addHandler(ring)
    api = Api(paths)
    commands = control.Commands(api, log_ring=ring)
    win = MainWindow(api, commands)
    # 다른 프로그램이 묻고 부리는 통로 (gui_app/control.py) — 화면으로 가는 알림 중 일부도 그쪽에 흘린다
    win.control = control.ControlServer(commands)
    api.emit_hooks.append(win.control.events.on_emit)

    def on_connect():
        conn = server.nextPendingConnection()
        conn.readyRead.connect(lambda: _on_message(win, conn))

    server.newConnection.connect(on_connect)
    if win.place():
        win.showMaximized()
    else:
        win.show()
    log.info(f"{APP_NAME} 시작")
    # 게임 조작키 설정에서 바꾼 키를 리모콘 단축키가 따라간다 (mabi.keys — 옵션에서 따로 정한 키가 이긴다)
    from mabi import keys as game_keys
    game_keys.follow_game()
    # 패킷 감시는 숙제를 안 돌려도 리모콘이 켜져 있는 내내 돈다 — 그 사이 사람이 한 일(출석 등)을 하루 기록에 남겨 숙제를
    # 시작할 때 쓴다 (사용자 2026-11-17). 화면이 상태를 물을 때 켜지던 것을 화면과 상관없이 여기서 켠다 (설정에서 끄면 안 켬)
    api.packet_status()
    return app.exec()
