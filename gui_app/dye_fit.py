"""염색 맞출 자리 찾기·자동 맞추기 — 단축키(옵션 창 '염색 맞추기 키', 기본 F10)나 염색 탭 단추로.

  한 번 누름   지금 팔레트 상태를 재고 프리셋 색을 스포이드들이 집는 자리를 찾아 게임 위에 점과 할 일 한 줄.
  한 번 더     마우스로 자동으로 맞춘다 (회전·휠·끌기). 도는 중에 다시 누르거나 키·마우스를 만지면 멈춘다.
               확정 단추는 누르지 않는다. 찾는 중에 한 번 더 누르면 찾는 대로 자동.

시작 화면: 도우미가 켜진 채 팔레트가 새로 뜨면, 열리는 연출이 끝나 멈춘 첫 화면 한 장을 메모리에만 들고 있는다
(늘 위치 0·회전 0·배율 1 — 팔레트 전체를 되짚는 바탕). 파일로 쓰지 않고 팔레트가 닫히면 버린다.
켜기 전에 이미 열려 있던 팔레트는 시작 상태를 몰라 찾지 않는다.
계산은 누를 때만 한다 — 2026-10-31 판은 팔레트가 뜰 때부터 상시 계산해 무거워 뺐다.
세 색이 다 되는 자리가 없으면 두 색이 되는 가장 좋은 자리 (사용자 2026-11-25, autofit.Session.solve).
"""
from __future__ import annotations

import contextlib
import logging
import threading
import time

import mss
import numpy as np

from mabi.dye import autofit as AF
from mabi.dye import detect as D
from mabi.dye import fit as FT

log = logging.getLogger("mabi")

IDLE, BUSY, SHOWN, AUTO = "idle", "busy", "shown", "auto"
START_STILL = 3      # 팔레트가 뜬 뒤 이만큼 이어 멈춘 화면이면 시작 화면으로 잡는다 (열리는 연출·카운트다운 피하기)
START_AFTER = 0.8    # 뜬 뒤 최소 이만큼 (초)
GONE_TICKS = 8       # 패킷을 못 볼 때 팔레트가 이만큼 이어 안 보이면 닫힌 것으로 (알림 창 등에 잠깐 가린 것은 넘긴다)


class _Jobs:
    """계산 스레드 하나. 이름마다 가장 마지막에 넣은 일만 남기고 PRIORITY 순으로 한다.
    계산은 틈틈이 쉰다(fit.Duty) — 같은 프로세스의 캡처·흑백 강조가 GIL 을 못 얻어 밀리지 않게."""
    PRIORITY = ("find", "pose")

    def __init__(self):
        self.cv = threading.Condition()
        self.todo: dict = {}
        threading.Thread(target=self._run, name="dye-fit", daemon=True).start()

    def put(self, name, fn) -> None:
        with self.cv:
            self.todo[name] = fn
            self.cv.notify()

    def clear(self) -> None:
        with self.cv:
            self.todo.clear()

    def _run(self) -> None:
        FT.pausing(FT.Duty())
        while True:
            with self.cv:
                while not self.todo:
                    self.cv.wait()
                name = next(n for n in self.PRIORITY if n in self.todo)
                fn = self.todo.pop(name)
            try:
                fn()
            except Exception:
                log.exception("염색 맞출 자리 계산 실패 (%s)", name)


class FitAssist:
    """DyeService 가 캡처 바퀴마다 observe 를 부르고, 단축키·단추가 press 를 부른다.

    repaint(): 게임 위 표시를 다시 그리게, emit(dict): 화면(웹)에 단계 알림, focus(): 게임 창을 앞으로,
    rect(): 게임 창 클라이언트 영역 (x, y, w, h) 실제 픽셀 | None, refs(): 재질 원본 그림 | None,
    key(): 단축키 ('f10'). 시험은 자동 맞추기 입력·손 감시·캡처를 가짜로 넣는다 —
    mouse(to_screen, stop) · hands(mouse, stop, ignore) · snap() (없으면 mss 로 게임 창).
    """

    def __init__(self, repaint, emit, focus, rect, refs, key, mouse=None, hands=None, snap=None):
        self.repaint, self.emit, self.focus, self.rect, self.refs, self.key = repaint, emit, focus, rect, refs, key
        self.make_mouse = mouse or AF.Mouse
        self.make_hands = hands or AF.HandsOff
        self.snap = snap
        self.jobs = _Jobs()
        self.lock = threading.RLock()
        self.st = None               # 마지막 DyeState
        self.tr = None               # DyeTracker
        self.frame = None            # 마지막 캡처
        self.gone = 0
        self.stop_ev: threading.Event | None = None
        self.reset(fresh=False)

    # ---- 상태 ----
    def reset(self, fresh: bool) -> None:
        """도우미를 켜고 끌 때·팔레트가 닫힐 때. fresh: 다음에 뜨는 팔레트를 처음부터 보게 되나."""
        self._halt()
        self.jobs.clear()
        with self.lock:
            self.gen = getattr(self, "gen", 0) + 1   # 돌던 계산이 끝나도 옛 결과는 버린다
            self.box = None          # 지금 팔레트 자리 (x, y, w, h)
            self.fresh = fresh
            self.opened = 0.0
            self.still = 0
            self.start = None        # (화면, box, rings, skip, mats) — 메모리에만
            self.moved = False       # 시작 화면을 잡은 뒤 팔레트가 움직였나
            self.sess: AF.Session | None = None
            self.phase = IDLE
            self.want_auto = False
            self.remeasure = False
            self.text, self.done, self.points = "", False, []
        self._emit_phase()

    def closed(self) -> None:
        """염색 미니게임이 끝났다 (패킷) — 바로 버린다."""
        if self.box is not None or self.start is not None:
            self.reset(fresh=True)
        else:
            self.fresh = True

    def retarget(self) -> None:
        """프리셋 색이 바뀌었다 — 찾아 둔 자리는 버린다 (팔레트 복원은 그대로 둔다)."""
        with self.lock:
            if self.phase == AUTO:
                return               # 도는 동안엔 그 목표로 끝까지 (멈추면 다시 찾는다)
            self.gen += 1
            self.phase, self.want_auto, self.remeasure = IDLE, False, False
            self.text, self.done, self.points = "", False, []
        self._emit_phase()
        self.repaint()

    def overlay(self) -> dict | None:
        """게임 위에 그릴 안내 (draw.overlay_items guide)."""
        if not self.text and not self.points:
            return None
        return {"points": list(self.points), "text": self.text, "done": self.done}

    def _say(self, text: str, done: bool = False, points=None) -> None:
        self.text, self.done, self.points = text, done, list(points or [])
        self.repaint()

    def _emit_phase(self) -> None:
        s = self.sess
        self.emit({"fit": self.phase, "goal": bool(s is not None and s.goal is not None and not self.done)})

    def _halt(self) -> None:
        if self.stop_ev is not None:
            self.stop_ev.set()

    # ---- 캡처 바퀴마다 (dye 스레드, 가볍게) ----
    def observe(self, img, st, tr, gate=None) -> None:
        """gate: 패킷으로 본 미니게임 열림 (True | None — 닫힘은 closed 로 따로 받는다).
        패킷이 열렸다고 하면 화면에서 잠깐 안 보여도(알림 창 등) 같은 팔레트로 둔다."""
        self.frame, self.st, self.tr = img, st, tr
        if st is None or st.status != "active" or tr.box is None:
            self.gone += 1
            if gate is None:
                if self.box is not None and self.gone >= GONE_TICKS:
                    self.reset(fresh=True)
                elif self.box is None:
                    self.fresh = True
            return
        self.gone = 0
        b = tr.box
        key = (b.x, b.y, b.w, b.h)
        if key != self.box:              # 새로 떴다 (자리만 바뀐 것 — 자리 고치기 — 은 처음이 아니다)
            fresh = self.fresh and self.box is None
            self.reset(fresh=fresh)
            self.box, self.opened = key, time.monotonic()
        if self.start is None:
            if not self.fresh or not tr.lead or not tr.lead.rings:
                return
            self.still = self.still + 1 if (tr.lead_ok and not tr.moving) else 0
            if self.still >= START_STILL and time.monotonic() - self.opened >= START_AFTER:
                self.start = (np.array(np.asarray(img)[..., :3]), b, list(tr.lead.rings),
                              list(tr.lead.skip) + [D.frame_skip(b)], list(tr.mats) if tr.mats else None)
                log.info("염색 시작 화면 잡음 (재질 %s)", tr.mats)
            return
        if tr.moving:
            self.moved = True
            if self.phase in (SHOWN, BUSY):  # 찾는 중에 움직여도 다 찾은 뒤 다시 잰다
                self.remeasure = True
                if self.phase == SHOWN and self.points:
                    self._say(self.text)     # 움직이는 동안 지난 점은 틀리다
            return
        if self.phase != SHOWN or self.sess is None or self.sess.goal is None:
            return
        # 게임 판정(말풍선 색)은 tracker 가 다시 읽은 바퀴에서만 — 멈춘 동안은 같은 상태를 돌려준다
        if st.redraw and self.sess.caught(st.rings):
            self.remeasure = False
            if not self.done:
                self._say(self.sess.guide(None, True)["text"], True)
                self._emit_phase()
        elif self.remeasure:
            self.remeasure = False
            frame, gen = img, self.gen
            self.jobs.put("pose", lambda: self._pose(frame, gen))

    # ---- 단축키·단추 ----
    def press(self) -> dict:
        """단계에 따라 찾기 / 자동 / 멈춤."""
        with self.lock:
            ph = self.phase
            if ph == AUTO:
                self._halt()
                return {"ok": True, "stopped": True}
            if ph == BUSY:
                self.want_auto = True
                return {"ok": True}
            if self.box is None:
                return {"error": "염색 팔레트가 떠 있지 않습니다"}
            if self.start is None:
                msg = ("팔레트를 열기 전에 염색 도우미를 켜 두어야 합니다" if not self.fresh
                       else "팔레트를 아직 읽는 중입니다 — 잠깐 뒤에 다시 눌러 주세요")
                self._say(msg)
                return {"error": msg}
            if ph == SHOWN and self.sess is not None and self.sess.goal is not None and not self.done:
                self._start_auto()
                return {"ok": True, "auto": True}
            self.phase, self.want_auto, self.remeasure = BUSY, False, False
            gen = self.gen
        self._say("맞출 자리 찾는 중…")
        self._emit_phase()
        self.jobs.put("find", lambda: self._find(gen))
        return {"ok": True}

    def _targets(self):
        return self.tr.slot_targets() if self.tr else []

    def _find(self, gen) -> None:
        t0 = time.monotonic()
        try:
            sess = self.sess or self._build(gen)
            if sess is None or gen != self.gen:
                return
            frame = self.frame
            if frame is None or sess.at_start(frame):
                m = AF.START_POSE           # 아직 안 움직였다 — 재지 않아도 시작 자세
            else:
                m = sess.pose(frame)
            if gen != self.gen:
                return
            if m is None:
                self._fail("지금 팔레트 상태를 재지 못했습니다")
                return
            if not any(self._targets()):
                self._fail("찾을 색을 정해 주세요")
                return
            ok = sess.solve(self._targets(), m, stop=lambda: gen != self.gen)
            if gen != self.gen:
                return
            log.info("염색 자리 찾기 %.1fs: %s", time.monotonic() - t0,
                     f"칸 {[i + 1 for i in sess.use]} 회전 {sess.goal[0]:.1f}° 배율 {sess.goal[1]:.3f}" if ok else "없음")
            sess.last = m
            self._show(sess.guide(m, ok and self.st is not None and sess.caught(self.st.rings)))
            if ok and self.want_auto and not self.done:
                with self.lock:
                    if gen == self.gen and self.phase == SHOWN:
                        self._start_auto()
        except Exception:
            log.exception("염색 자리 찾기 실패")
            self._fail("자리를 찾다 오류가 났습니다")
        finally:
            with self.lock:
                if gen == self.gen and self.phase == BUSY:
                    self.phase = IDLE
            self._emit_phase()

    def _build(self, gen):
        frame, box, rings, skip, mats = self.start
        t0 = time.monotonic()
        self._say("팔레트 읽는 중…")
        sess = AF.Session(frame, box, rings, skip, self.refs(), mats)
        log.info("염색 팔레트 복원 %.1fs, 재질 %s, 시작 화면 일치 %.2f",
                 time.monotonic() - t0, sess.mats, sess.pal.start_score)
        if gen != self.gen:
            return None
        if not sess.start_ok:
            self.start = None        # 움직인 뒤 화면을 잡았다 — 이 팔레트로는 못 한다
            self._fail("시작 화면을 놓쳤습니다 — 팔레트를 다시 열어 주세요")
            return None
        self.sess = sess
        return sess

    def _fail(self, text: str) -> None:
        with self.lock:
            self.phase = IDLE
        self._say(text)

    def _show(self, gd: dict) -> None:
        """찾은 자리·할 일을 띄운다. 자동으로 할 수 있으면 단축키를 알려 준다."""
        with self.lock:
            self.phase = SHOWN
            text = gd["text"]
            if self.sess is not None and self.sess.goal is not None and not gd["done"]:
                text += f"  ·  {self.key().upper()} 한 번 더 = 자동"
            self._say(text, gd["done"], gd["points"])
        self._emit_phase()

    def _pose(self, frame, gen) -> None:
        sess = self.sess
        if sess is None or sess.goal is None or gen != self.gen or self.phase != SHOWN:
            return
        m = sess.pose(frame)
        if gen == self.gen and self.phase == SHOWN:
            self._show(sess.guide(m, self.st is not None and sess.caught(self.st.rings)))

    # ---- 자동 맞추기 ----
    def _start_auto(self) -> None:
        self.phase = AUTO
        self.stop_ev = stop = threading.Event()
        threading.Thread(target=self._auto, args=(self.sess, stop, self.gen), name="dye-auto", daemon=True).start()
        self._say("자동 맞추는 중…")
        self._emit_phase()

    def _snapper(self, sct):
        def snap():
            r = self.rect()
            if r is None:
                return None
            return np.asarray(sct.grab({"left": r[0], "top": r[1], "width": r[2], "height": r[3]}))
        return snap

    def _auto(self, sess, stop, gen) -> None:
        from mabi.inputs import vk_of
        FT.pausing(FT.Duty())
        text, done, m, hands = "", False, None, None
        try:
            self.focus()
            time.sleep(0.3)

            def to_screen(x, y):
                r = self.rect() or (0, 0, 0, 0)
                return r[0] + x, r[1] + y

            mouse = self.make_mouse(to_screen, stop.is_set)
            try:
                ignore = vk_of(self.key())
            except ValueError:
                ignore = 0
            hands = self.make_hands(mouse, stop, ignore=(ignore,))
            try:
                with contextlib.ExitStack() as es:
                    snap = self.snap or self._snapper(es.enter_context(mss.mss()))
                    drv = AF.AutoDriver(sess, snap, mouse, stop,
                                        lambda _m, what: self._say(f"자동 맞추는 중 — {what}"))
                    ok, m = drv.run()
            finally:
                hands.close()
            log.info("염색 자동 맞추기 %s (%s)", "맞춤" if ok else "못 맞춤", "말풍선" if drv.by_label else "계산")
            # 마지막 판정은 게임이 띄운 색으로 — 자동이 말풍선으로 확인했으면 그대로, 아니면 tracker 가 멈춘
            # 화면을 다시 읽을 때까지 잠깐
            caught = ok and drv.by_label
            for _ in range(0 if caught else 6):
                time.sleep(0.25)
                if self.st is not None and sess.caught(self.st.rings):
                    caught = True
                    break
            if self.st is not None:
                rs = sorted(self.st.rings, key=lambda r: r.x)
                log.info("염색 자동 끝 스포이드 색 %s · 목표 %s", " ".join(r.hex or "?" for r in rs), " ".join(
                    "-" if i not in sess.targets else sess.targets[i].hex if i in sess.use else "뺌"
                    for i in range(len(rs))))
            gd = sess.guide(m, caught)
            done = gd["done"]
            if done:
                text = gd["text"]
            elif ok:
                text = "자리는 맞췄는데 게임 색이 조금 다릅니다 — 말풍선 색을 확인하세요"
            else:
                text = "다 맞추지 못했습니다 — " + gd["text"]
        except AF.Stopped:
            why = getattr(hands, "why", "") if hands is not None else ""
            text = "자동 맞추기를 멈췄습니다" + (f" ({why})" if why else "")
            log.info("염색 자동 맞추기 멈춤 %s", why)
        except Exception:
            log.exception("염색 자동 맞추기 실패")
            text = "자동 맞추기 중 오류가 났습니다"
        finally:
            with self.lock:
                if self.stop_ev is stop:
                    self.stop_ev = None
                if gen == self.gen and self.phase == AUTO:
                    self.phase = SHOWN
                    if m is not None:
                        sess.last = m
                    self._say(text, done, [] if done or m is None else sess.guide(m)["points"])
            self._emit_phase()
