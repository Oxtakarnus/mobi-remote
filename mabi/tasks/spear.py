"""흩어진 물길 투창병 속성 패턴 — 내게 대상 표시가 붙으면 같은 속성 주술사 옆으로 WASD 로 간다 (상태는 mabi/spear.py).
비틀린 송곳니의 격류도 여기서 피한다 (SpearDodge.rift — 격류가 가는 쪽 면의 균열을 밟아 격류 뒤로).

이 어비스만의 예외다. 어비스 판 진행(abyss.play)이 기다리는 사이 패킷이 깨우면 부른다.
1. 같은 속성 주술사 옆 (주술사에서 가운데 쪽으로 1.5) 으로 이동. 도착은 1칸 안 — 투창 범위 반지름이 약 2.5 라 주술사가 들어간다.
2. 파훼(그 주술사 보호막 깨짐)를 볼 때까지 제자리를 지킨다 — 가만히 있으면 자동 전투·어그로가 끌고 가므로 짧게 움찔거리고,
   밀려나면 다시 들어간다 (사용자). 못 깨면 10초마다 같은 속성을 다시 던지니 계속 지킨다 (상한 HOLD).
   먼저 떠나지 않는다 — 몬스터 길막·후딜 큰 스킬로 늦게 닿을 수 있다 (2026-11-03 사용자).
3. 깨지면 투창병 근처로 돌아간다 (사용자: 돌아가는 건 파훼했을 때). 돌아오면 Space 로 바로 전투로 (사용자 11-19 — 아무 것도 안 하는 상태의 Space 는 지금 '목표' 진행).
W·D 가 맵에서 어느 쪽인지는 카메라를 고정한 채 (사용자) 주술사가 나온 뒤 한 번 짧게 눌러 재고 저장한다 (속성 버프 3~4초 전).
키를 떼도 위치 읽기가 늦어 약 1.5칸 더 가므로 지금 속도 × LAG 만큼 앞에서 뗀다 (11-02 실측 초당 5.5칸, 수도사 이속 버프 때 ~7.9).
게임 키만 누른다 — 패킷은 보내지 않는다.
"""
import ctypes
import json
import math
import random
import time

from .. import keys
from ..bot import Bot
from ..spear import WAVE_DELAY, WAVE_SECS, SpearState, along, exits, wave_line
from ..tictactoe import O_AT, O_WINDOW

TOL = 1.0          # 도착 (목표점에서)
NEAR_SPEAR = 4.0   # 투창병 근처
HOLD = 25.0        # 대상 표시 뒤 이만큼 지나도 못 깨면 포기
SPEED = 5.5        # 보통 이동 속도 (칸/초). 이동 중엔 실제 속도로
LAG = 0.22
GO_LIMIT = 8.0     # 한 번 가는 데 상한 (가장 먼 주술사가 약 24칸)
CALIB_FILE = "spear_calib.json"
SOLO = "솔로"        # 맵 이름 끝 '(… 솔로)' — 혼자하기
CAMERA_WAIT = 2.0  # 맵에 들어오고 적어도 이만큼 뒤, 내 캐릭터가 움직이기 시작하면 카메라를 맞춘다
CAMERA_LATE = 8.0  # 움직임을 못 봐도 들어오고 이만큼 지나면 맞춘다
CAMERA_MOVED = 1.0  # 맵에 들어와 처음 받은 내 자리에서 이만큼 넘게 가면 움직이기 시작한 것
CAMERA_AUTO = 4.0  # 자동 카메라로 이만큼 둔 뒤 수동으로 — 2초로는 덜 돌아간 채 고정됐다 (사용자 11-03)
CAMERA_ICON_MIN = 0.7   # 카메라 아이콘 그림 점수가 이보다 낮으면 모름 (HUD 가 없을 때 등)
CAMERA_ICON_GAP = 0.15  # 수동·자동 두 그림 점수가 이만큼은 벌어져야 한쪽으로 본다 (서로 다른 쪽엔 0.5 안팎)
CAMERA_SWITCH = 0.5     # 자동 → 수동으로 바꾸고 아이콘을 다시 보기까지
QUEST_AT = (8, 52)  # '퀘스트 +' 머리 그림 왼쪽 위 → 추적 칸 첫 퀘스트 제목 끝쪽 (제목은 오른쪽 맞춤이라 길이와 상관없이 글자 위)
CAMP_AUTO = 6.0    # 보스방 갈 때는 더 길게 — 4초로는 덜 돌아간 채 고정될 때가 있었다 (사용자 11-03). 8초는 빠른 캐릭터가
                   # 그 안에 보스방에 들어가 두 번째 Z 가 보스 등장 연출에 묻혀 자동 카메라로 남았다 (11-04 14:34, 사용자)
SCENE_FIND = 10.0  # 보스 등장 연출의 넘기기 버튼을 찾는 상한 — 버튼이 늦게 뜰 때가 있다 (11-19 14:00 5초로는 못 찾음)
SCENE_TAKES = 2.0  # 누른 뒤 연출이 끝나길(패킷) 기다리는 초 — 안 끝나고 버튼이 남아 있으면 다시 누른다
SCENE_CLICKS = 3
SCENE_DELAY = 0.5  # 처음 누를 땐 버튼을 보고(또는 버튼 자리를 누르기로 하고) 이만큼 더 기다린다 — 버튼이 막 뜬 때 누른 것이
                   # 클릭 효과는 났는데 안 먹었다 (11-19 16:26 '버튼 1.1초' 헛방, 같은 1.1초에 4번은 먹음 — 사용자 0.5초 늦추기)
# HUD 가 사라진 뒤 버튼이 뜨기까지 틈이 있다 (11-19 15:23 화면: 연출이 어둡게 시작해 0.3초 넘게 버튼 없음) — 그 틈에 버튼 자리를
# 누르면 안 먹고 SCENE_TAKES 를 버린다 (15:07·15:18 첫 누름이 안 먹고 4초대 두 번째에 넘어감 — 이 틈으로 봄). 그래서 이만큼 HUD 가 없는데도
# 버튼 그림이 안 맞을 때만 그 자리를 누른다
SCENE_SPOT_AFTER = 1.5
# '장면 넘기기' 자리 (기준 1920x1080, 11-19 13:30 버튼을 찾아 누른 자리). 평소 화면에선 미니맵 위라 HUD 가 사라진 뒤에만 누른다
SCENE_SKIP_XY = (1805, 44)
# 격류 피하기 (사용자 11-19: 격류가 가운데를 넘었거나 캐릭터 가까이 왔을 때 가까운 균열로 — 일찍 타면 건너편이 아직 격류)
NEAR_HIT = 6.0    # 격류 앞머리가 이만큼 가까이 오면 균열로 출발 (가운데 전이라도)
NEAR_STEP = 2.5   # 균열 앞에서 기다리는데 격류가 이만큼 붙으면 가운데 전이라도 밟는다 (밀리며 맞느니)
RIFT_STAGE = 5.0  # 가운데 전에 균열에 닿으면 이만큼 안쪽에서 기다린다 (밟히는 범위를 아직 못 재서 넉넉히)
RIFT_TOL = 0.5
RIFT_OFF = 5.0    # 넘어온 균열에서 송곳니 쪽으로 비켜 서는 칸 — 그 위에서 싸우다 밀리면 재사용 대기(5초)가 끝나자마자 다시
                  # 옮겨진다 (11-19 16:14:05 넘어간 쪽에 송곳니가 있어 균열 위에서 싸움 — 사용자)
RIFT_WAIT = 1.5   # 균열 자리에 닿고 넘어가길 기다리는 초 — 안 넘어가면 같은 면 다른 균열로


def camera_mode(bot: Bot, frame=None) -> str | None:
    """오른쪽 위 카메라 아이콘으로 본 지금 카메라 — "manual"(카메라에 손가락) · "auto"(카메라만) · None(모름)."""
    frame = bot.frame() if frame is None else frame
    score = {}
    for mode in ("manual", "auto"):
        name = bot.ui.get(f"camera_{mode}", f"camera_{mode}")
        m = bot.vision.best(frame, name) if bot.vision.has(name) else None
        score[mode] = float(m.score) if m else 0.0
    top = max(score, key=score.get)
    if score[top] < CAMERA_ICON_MIN or score[top] - min(score.values()) < CAMERA_ICON_GAP:
        return None
    return top


def _per_map(name: str):
    """이 맵에서 한 번 한 일 (맵 진입 시각) — 판 진행을 다시 부를 때마다 SpearDodge 가 새로 생겨도 이어지게
    맵 상태(SpearState)에 둔다. 클리어 뒤 보상 화면에서 판 진행을 다시 불러 보스방 카메라를 또 돌렸다 (11-03 19:26)."""
    return property(lambda self: getattr(self.bot.packets.spear, name, 0.0),
                    lambda self, v: setattr(self.bot.packets.spear, name, v))


class SpearDodge:
    calib_tried = _per_map("calib_tried")   # 보정을 해 봤나
    camera_set = _per_map("camera_set")     # 카메라를 맞췄나
    camp_camera = _per_map("camp_camera")   # 보스방 갈 때 카메라를 다시 맞췄나
    quest_spear = _per_map("quest_spear")   # 투창 패턴이 끝나 추적 칸을 눌렀나
    quest_fang = _per_map("quest_fang")     # 송곳니가 쓰러져 추적 칸을 눌렀나
    camera_half = _per_map("camera_half")   # 첫 카메라 키만 누르고 연출이 시작돼 두 번째가 남았나
    scene_tried = _per_map("scene_tried")   # 보스 등장 연출을 넘겨 봤나 (넘기기를 눌렀다)
    scene_seen = _per_map("scene_seen")     # 넘기기 버튼을 찾아본 연출 (그 연출이 시작된 때)

    def __init__(self, bot: Bot):
        self.bot = bot
        self._calib = False     # 처음 쓸 때 파일에서 (흩어진 물길이 아니면 읽지도 않는다)
        self._cli_pos, self._cli_at = None, -1e9  # pos_loose 가 CLI 로 본 내 자리

    @property
    def file(self):
        return self.bot.paths.state / CALIB_FILE

    @property
    def calib(self):
        if self._calib is False:
            try:
                c = json.loads(self.file.read_text(encoding="utf-8"))
                self._calib = (tuple(c["w"]), tuple(c["d"]))
            except (OSError, ValueError, KeyError, TypeError):
                self._calib = None
        return self._calib

    @calib.setter
    def calib(self, v):
        self._calib = v

    @property
    def st(self) -> SpearState:
        return self.bot.packets.spear

    def wanted(self) -> bool:
        """지금 맡을 일이 있나 — 내가 투창 대상이거나 틱택토 O 담당, 비틀린 송곳니 격류가 나옴,
        또는 주술사가 나왔는데 W·D 방향을 아직 모름."""
        st = getattr(self.bot.packets, "spear", None)
        if not isinstance(st, SpearState) or not st.active:
            return False
        if self.camera_due() or self.scene_due() or self.quest_due():
            return True
        if st.ttt.due() or st.wave_due():
            return True
        if st.finished:
            return False
        return st.due() or (self.calib is None and len(st.attr) == 6
                            and self.calib_tried != self.bot.packets.state.entered_at)

    def camera_due(self) -> bool:
        """함께하기는 카메라가 캐릭터 반대쪽을 보고 시작한다 (혼자하기는 캐릭터가 보는 쪽 — 2026-11-03 사용자).
        W·D 방향이 혼자하기와 달라지므로 맵에 들어와 로딩이 끝나면 한 번 맞춘다.
        보스방에 들어가면 한 번 더 — 첫 방에서 쓰러졌다 일어나면 시점이 뒤틀릴 수 있다 (사용자, 두 모드 다).
        모닥불만 봐서는 아직 보스방 앞 몬스터와 싸우는 중일 수 있어 (11-03 사용자) 비틀린 송곳니가 쓰러질 때 맞춘다
        — 그 순간 모닥불이 나오고 보스방으로 17~20초 걸어간다 (party2 10판). 그걸 못 봤으면 보스 등장 연출이 끝난 뒤에."""
        s = self.bot.packets.state
        if not s.entered_at or s.loading or s.dead:
            return False
        if self.camera_half == s.entered_at:
            return not s.cutscene
        if self.camp_camera != s.entered_at and (self.st.fang_down or s.boss_scene):
            return not s.cutscene
        if self.camera_set == s.entered_at:  # 혼자하기도 들어올 때 수동 카메라인지는 본다 (set_camera)
            return False
        # 맵 진입 패킷은 로딩 화면이 걷히기 전에 와서, 2초 뒤에 눌러도 첫 키를 게임이 못 받을 때가 있었다 → 첫 키만 먹고
        # 자동 카메라로 남음 (사용자 11-19). 내 캐릭터가 움직이기 시작한 뒤 (= 조작을 받는다) 누른다
        since = time.monotonic() - s.entered_at
        return since > CAMERA_WAIT and (self.moved_since_entry() or since > CAMERA_LATE)

    def moved_since_entry(self) -> bool:
        """맵에 들어와 내 캐릭터가 움직이기 시작했나 — 패킷 내 이동으로, 들어와 처음 받은 자리에서 CAMERA_MOVED 넘게."""
        s = self.bot.packets.state
        p = self.st.pos.get(s.me) if s.me is not None else None
        if not p or p[2] < s.entered_at:
            return False
        start = getattr(self.st, "camera_from", None)
        if not start or start[0] != s.entered_at:
            self.st.camera_from = (s.entered_at, p[0], p[1])
            return False
        return abs(p[0] - start[1]) + abs(p[1] - start[2]) > CAMERA_MOVED

    def set_camera(self) -> None:
        """카메라 토글(자동 카메라) → 몇 초 뒤 캐릭터 뒤로 돌아오면 한 번 더(수동 카메라)로 고정 (사용자).
        키는 옵션의 수동 / 자동 카메라 토글 키 (게임 기본 End, 보조 Z)."""
        s = self.bot.packets.state
        key = keys.of(self.bot, "camera")
        if self.camera_half == s.entered_at:
            self.camera_half = 0.0
            self.bot.log.info(f"카메라: 연출이 끝나 남은 {key.upper()} 를 눌러 고정")
            self.bot.key(key)
            return
        camp = bool(self.st.fang_down or s.boss_scene)
        self.camera_set = s.entered_at  # 모닥불 뒤에 처음 맞춰도 맵 진입 때 것은 다시 하지 않는다
        if camp:
            self.camp_camera = s.entered_at
        self.manual_camera(key)
        if not camp and SOLO in (s.channel_name or ""):
            return  # 혼자하기는 카메라가 캐릭터가 보는 쪽으로 시작한다 — 수동인지만 본다
        what, wait = ("보스방", CAMP_AUTO) if camp else ("함께하기", CAMERA_AUTO)
        self.bot.log.info(f"{what}: 카메라를 캐릭터 뒤로 맞춤 ({key.upper()} → {wait:.0f}초 → {key.upper()})")
        self.bot.key(key)
        for _ in range(round(wait / 0.1)):
            if s.cutscene or s.loading:
                # 연출·로딩 중에 누른 키는 게임이 받지 않는다 — 두 번째 카메라 키는 연출이 끝난 뒤 (camera_due)
                self.camera_half = s.entered_at
                self.bot.log.info(f"카메라: 맞추는 중 연출이 시작됨 → 두 번째 {key.upper()} 는 연출 뒤에")
                return
            time.sleep(0.1)
        self.bot.key(key)

    def manual_camera(self, key: str) -> None:
        """카메라 맞춤(키 → 자동 → 몇 초 → 키 → 수동)은 수동 카메라에서 시작해야 맞는다. 자동 카메라로 둔 캐릭터는
        거꾸로 수동 → 자동이 되어 시점이 반대로 돌았다 (11-19 16:45). 그래서 맞추기 전에 오른쪽 위 아이콘을 보고
        자동이면 키를 한 번 눌러 수동으로 해 둔다 (사용자 11-19). 아이콘을 모르면 그대로 둔다."""
        if camera_mode(self.bot) != "auto":
            return
        self.bot.log.info(f"카메라: 자동 카메라라 {key.upper()} 를 눌러 수동으로 바꿈")
        self.bot.key(key)
        time.sleep(CAMERA_SWITCH)
        if camera_mode(self.bot) == "auto":
            self.bot.log.warning("카메라: 눌렀는데도 자동 카메라로 보임")

    def scene_due(self) -> bool:
        """보스 등장 연출 중이고 이 맵에서 아직 안 넘겼다. 물결은 어차피 게임을 앞에 두고 돌아 넘겨도 된다 (사용자 11-03)
        — 다른 어비스는 연출을 기다린다 (Bot.scene_skip)."""
        s = self.bot.packets.state
        return bool(s.entered_at and s.cutscene and s.boss_scene and self.scene_tried != s.entered_at
                    and self.scene_seen != s.changed_at.get("cutscene"))

    def skip_scene(self) -> None:
        """'장면 넘기기' 를 누르고 연출이 끝나는지(패킷 cutscene.end·abort) 본다. 연출 패킷이 와도 화면에 연출이 뜨기까지
        2초 넘게 걸리고 (11-19 13:30 블랙박스 — 1초 뒤엔 아직 평소 화면), 반투명 버튼 그림은 안 맞을 때가 있다 (14:00·14:11).
        그래서 버튼이 보이면 그 버튼을, 안 보여도 HUD 가 사라진 지 SCENE_SPOT_AFTER 초가 지났으면 연출 화면이 뜬 것으로 보고
        버튼 자리를 누른다 (사용자 11-19 — 버튼을 찾기보다 그 자리를). 그 자리는 평소 화면에선 미니맵이라 HUD 가 보이는 동안은 누르지 않는다.
        누른 뒤 안 끝나면 다시 (SCENE_CLICKS 번까지).
        버튼을 못 찾은 연출은 그 연출만 넘어가고, 같은 맵에서 다음 연출이 오면 또 찾는다 — 보스 연출 앞에 넘기기 없는
        연출이 끼면 그것만 보고 끝내 정작 보스 연출을 못 넘길 수 있다."""
        bot = self.bot
        self.scene_seen = bot.packets.state.changed_at.get("cutscene", 0.0)
        start = time.monotonic()
        clicks = 0
        gone_at = None  # HUD 가 사라진 때 (연출 화면이 뜬 때)
        tries: list[str] = []  # 누른 것마다 '어떻게 몇 초' — 첫 번째가 안 먹은 까닭을 로그로 가리려고
        while bot.packets.state.cutscene and time.monotonic() < start + SCENE_FIND and clicks < SCENE_CLICKS:
            frame = bot.frame()
            hit = bot.skip_button(frame)
            if bot.at_main(frame):
                gone_at = None
            elif gone_at is None:
                gone_at = time.monotonic()
            if hit and hit[0] == "scene":
                where, how = hit[1], "버튼"
            elif gone_at is not None and time.monotonic() - gone_at >= SCENE_SPOT_AFTER:
                where, how = SCENE_SKIP_XY, "버튼 자리"
            else:
                time.sleep(0.3)
                continue
            if not clicks:
                time.sleep(SCENE_DELAY)
                if not bot.packets.state.cutscene:
                    break
            clicks += 1
            found = time.monotonic() - start
            tries.append(f"{how} {found:.1f}초")
            self.scene_tried = bot.packets.state.entered_at
            bot.click(where)
            if bot.wait_packet(lambda st: not st.cutscene, SCENE_TAKES):
                again = f" · {clicks}번 누름: {' → '.join(tries)}" if clicks > 1 else ""
                bot.log.info(f"물결: 보스 등장 연출 넘김 ({how} {found:.1f}초 · 끝남 {time.monotonic() - start:.1f}초{again})")
                return
        if not bot.packets.state.cutscene:
            if clicks:
                bot.log.info(f"물결: 보스 등장 연출 넘김 ({clicks}번 누름 · 끝난 것은 화면으로)")
            return
        if clicks:
            bot.log.warning(f"물결: 넘기기를 {clicks}번 눌러도 보스 등장 연출이 이어짐 ({' → '.join(tries)}) → 끝나길 기다림 "
                            f"({bot.snapshot('spear_scene').name})")
        else:
            bot.log.info(f"물결: 보스 등장 연출의 넘기기 버튼을 못 찾음 — 끝나길 기다림 ({bot.snapshot('spear_scene').name})")

    def run(self) -> None:
        st = self.st
        if self.scene_due():
            self._with_focus(self.skip_scene)
            return
        if self.quest_due():  # 카메라 맞춤보다 먼저 — 보스방으로 걷기 시작해야 자동 카메라가 캐릭터 뒤로 돈다
            self.resume("투창 패턴 끝" if self.quest_spear != self.bot.packets.state.entered_at else "송곳니 쓰러짐")
            return
        if self.camera_due():
            self.set_camera()  # Z 만 누른다 — 뒤에서도 창에 직접 보내지므로 게임을 앞으로 가져오지 않는다 (사용자 11-03)
            return
        if st.wave_due():
            w = st.take_wave()
            if w and self.calib is None:
                self._with_focus(self.calibrate)
            if w and self.calib is not None:
                self.rift(w)  # 움직일 때만 게임 창을 앞으로
            self.resume("격류")
            return
        if st.ttt.due():
            job = st.ttt.take(self.my_pos())  # 크게 차이 나지 않으면 가까운 칸
            if job and self.calib is None:
                self._with_focus(self.calibrate)
            if job and self.calib is not None:
                self._with_focus(lambda: self.tictactoe(job))
            return
        if self.calib is None and not st.due():
            self.calib_tried = self.bot.packets.state.entered_at
            self._with_focus(self.calibrate)
            return
        job = st.take()
        if job is None:
            self.bot.log.info("투창 대상이지만 속성이나 그 주술사를 모름 (맵에 들어온 뒤 소환을 못 봄) — 움직이지 않음")
        else:
            if self.calib is None:  # 주술사 소환 때 못 쟀다 — 지금이라도 (늦게 출발한다)
                self._with_focus(self.calibrate)
            if self.calib is not None:
                self._with_focus(lambda: self.dodge(job))
        self.resume("투창")

    # ── 순서 ──
    def dodge(self, job: dict) -> None:
        x, y = job["x"], job["y"]
        target = (x - math.copysign(1.5, x), y)
        t0, so = job["at"], job["shaman"]
        done = lambda: self.st.broken_since(so, t0)
        until = t0 + HOLD
        self.bot.log.info(f"투창 패턴: {job['attr']} 주술사 ({x:.0f}, {y:.0f}) 옆 {target[0]:.1f}, {target[1]:.1f} 로 이동")
        self.go(target, TOL, min(until, time.monotonic() + GO_LIMIT), done)
        # 파훼를 볼 때까지 붙어 있는다 — 길막·후딜 큰 스킬로 늦게 닿을 수 있어 먼저 떠나지 않는다 (사용자)
        self.hold(target, until, done)
        if not done():
            self.bot.log.info(f"투창 패턴: {HOLD:.0f}초 동안 파훼 못 봄 — 투창병 쪽으로")
        if self.ok():
            self.go(self.st.spear_home(), NEAR_SPEAR, time.monotonic() + GO_LIMIT, lambda: False)

    def tictactoe(self, job: dict) -> None:
        """틱택토 O 담당 — 차례 시작 5초 안에 고른 칸 가운데로 가서, 보스가 O 를 새기러 올 때까지 그 칸에서 버틴다
        (밀려나면 다시 들어간다). 보스는 5초 때 담당이 서 있는 자리로 가므로 늦으면 엉뚱한 칸에 O 가 생긴다 (사용자)."""
        ttt = self.st.ttt
        target, t0 = (job["x"], job["y"]), job["at"]
        done = lambda: ttt.resolved
        near = job.get("near")
        at = f"({near[0]:.0f}, {near[1]:.1f})" if near else "모름"
        self.bot.log.info(f"틱택토: O 담당 → 칸 {job['cell']} ({target[0]:.0f}, {target[1]:.1f}) 로 이동 · 판 {ttt.text()}"
                          f" · 내 자리 {at} · 차례 시작 {time.monotonic() - t0:.1f}초 뒤 출발")
        if self.go(target, TOL, t0 + O_AT, done, pattern=False):
            self.bot.log.info(f"틱택토: 칸 도착 (차례 시작 {time.monotonic() - t0:.1f}초)")
        elif not done():
            self.bot.log.warning(f"틱택토: {O_AT:.0f}초 안에 칸에 못 감 — 그래도 버팀")
        self.hold(target, t0 + O_WINDOW[1], done, pattern=False)
        if not done():
            self.bot.log.info("틱택토: 보스가 O 를 새기러 오는 것을 못 봄")

    def rift(self, w: dict) -> None:
        """격류 피하기 (사용자 11-19: 격류가 나오면 시작해 균열을 탔거나 송곳니가 쓰러지면 끝).
        앞머리가 가운데를 넘거나 내 가까이(NEAR_HIT) 올 때까지는 자동 전투 그대로 두고 (게임 창도 앞으로 안 가져온다),
        그때 격류가 가는 쪽 면의 균열 가운데 가까운 것으로 간다. 가운데 전이면 균열 앞(RIFT_STAGE)에서 기다렸다가
        가운데를 넘거나 거기까지 격류가 붙으면(NEAR_STEP) 밟는다 — 일찍 타면 건너편이 아직 격류다.
        그 밖에 쓰러짐·맵 떠남·로딩, 격류가 끝까지 감에도 그만둔다."""
        st, bot = self.st, self.bot
        if not st.rifts():
            bot.log.info("격류: 균열이 안 보임 (패킷) — 움직이지 않음")
            return
        end = w["at"] + WAVE_DELAY + WAVE_SECS + 1.0
        over = lambda: self._rift_over(w, end)
        while not over():
            bot.check_stop()
            if self._rift_time(w, NEAR_HIT):
                break
            time.sleep(0.1)
        if not over():
            self._with_focus(lambda: self._rift_move(w, end, over))
        self._rift_end(w)

    def _rift_over(self, w: dict, end: float) -> bool:
        st = self.st
        return st.warped_at > w["at"] or bool(st.fang_down) or not self.ok(pattern=False) or time.monotonic() > end

    def _rift_time(self, w: dict, near: float | None) -> bool:
        """격류 앞머리가 가운데를 넘었거나 내 near 칸 안으로 왔다 (이미 나를 덮쳐 밀고 있어도). near None 이면 가운데만."""
        start, u, length, front = wave_line(w, time.monotonic())
        if front >= length / 2:
            return True
        p = self.pos_loose() if near is not None else None
        return p is not None and along(p, start, u) - front <= near

    def _rift_move(self, w: dict, end: float, over) -> None:
        st, bot = self.st, self.bot
        start, u, length, front = wave_line(w, time.monotonic())
        me = self.my_pos()
        if not me:
            bot.log.info("격류: 내 자리를 모름 — 움직이지 않음")
            return
        outs = exits(start, u, length, st.rifts()) or exits(start, u, length)  # 패킷으로 본 균열, 없으면 정해 둔 자리
        outs.sort(key=lambda r: math.dist(r, me))
        bot.log.info(f"격류: ({start[0]:.0f}, {start[1]:.0f}) 에서 옴 · {front / length * 100:.0f}% · "
                     f"나와 {along(me, start, u) - front:.1f}칸 → 균열 ({outs[0][0]:.0f}, {outs[0][1]:.0f}) 로 "
                     f"(나온 지 {time.monotonic() - w['at']:.1f}초)")
        if not self._rift_time(w, None):  # 가운데 전 — 격류에 붙어 있어도 일단 앞질러 균열 앞에서 기다린다
            stage = (outs[0][0] - u[0] * RIFT_STAGE, outs[0][1] - u[1] * RIFT_STAGE)
            self.go(stage, TOL, end, lambda: over() or self._rift_time(w, None), pattern=False)
            self.hold(stage, end, lambda: over() or self._rift_time(w, NEAR_STEP), pattern=False)
        for r in outs:
            if over():
                break
            self.go(r, RIFT_TOL, min(end, time.monotonic() + GO_LIMIT), over, pattern=False)
            bot.input.hold(())
            stop = time.monotonic() + RIFT_WAIT
            while time.monotonic() < stop and not over():
                time.sleep(0.05)
            if not over():
                bot.log.info(f"격류: 균열 ({r[0]:.0f}, {r[1]:.0f}) 에 닿았는데 안 넘어감 — 같은 면 다른 균열로")
        if st.warped_at > w["at"] and self.ok(pattern=False):
            self._step_off(u)

    def quest_due(self) -> bool:
        """투창 패턴이 끝났거나(주술사 모두 쓰러짐) 송곳니가 쓰러졌는데 이 맵에서 아직 추적 칸을 안 눌렀다."""
        s = self.bot.packets.state
        if not s.entered_at or s.loading or s.dead or s.cutscene or not self.st.active:
            return False
        return ((self.st.finished and self.quest_spear != s.entered_at)
                or (self.st.fang_down and self.quest_fang != s.entered_at))

    def resume(self, why: str) -> None:
        """오른쪽 퀘스트 추적 칸의 첫 퀘스트('흩어진 물길 클리어')를 눌러 목표 진행으로 돌아간다 (사용자 11-19).
        투창·격류 처리가 끝나면 — 해냈든 그만뒀든 —, 그리고 투창 패턴이 끝나거나 송곳니가 쓰러지면 누른다.
        Space(메인 버튼)는 이때 아무 일도 안 했고 (11-19 17:00), 게임 조작키에도 추적 퀘스트를 진행하는 키는 없다
        (ControlKey 목록 — 추적 칸 위아래 고르기뿐). 쓰러졌거나 맵을 떠났으면 안 누른다. 사용자가 멈춰 예외로 빠져나갈 때도 안 누른다."""
        st, s, bot = self.st, self.bot.packets.state, self.bot
        if st.finished:
            self.quest_spear = s.entered_at
        if st.fang_down:
            self.quest_fang = s.entered_at
        if not self.ok(pattern=False):
            return
        m = bot.vision.find(bot.frame(), bot.ui.get("quest_tracker", "quest_tracker"))
        if m is None:
            bot.log.info(f"물길: {why} 뒤 — 퀘스트 추적 칸이 안 보여 못 누름")
            return
        bot.log.info(f"물길: {why} 뒤 — 퀘스트 추적 칸을 눌러 목표 진행")
        bot.click_xy(m.x + QUEST_AT[0], m.y + QUEST_AT[1])

    def _step_off(self, u) -> None:
        """넘어온 균열에서 비켜 선다. 송곳니 쪽으로 RIFT_OFF 칸 (사용자 11-19) — 자동 전투가 균열 위가 아니라 그 앞에서 이어진다.
        송곳니가 가장자리 쪽이거나 자리를 모르면 격류가 간 쪽(안쪽)으로. 격류 앞머리는 가운데 너머라 이 근처는 비어 있다."""
        time.sleep(0.3)  # 옮겨진 자리가 오길 (순간이동 패킷·CLI)
        p = self.my_pos(fresh=True)
        if not p:
            return
        d, boss = u, self.st.where(self.st.fang, 30.0)  # 송곳니는 서 있으면 자리를 안 보낸다 (녹화: 최대 9초 틈)
        if boss and math.dist(boss, p) > 1.0:
            n = math.dist(boss, p)
            b = ((boss[0] - p[0]) / n, (boss[1] - p[1]) / n)
            if b[0] * u[0] + b[1] * u[1] > 0.3:  # 안쪽으로 가는 쪽일 때만
                d = b
        self.go((p[0] + d[0] * RIFT_OFF, p[1] + d[1] * RIFT_OFF), TOL, time.monotonic() + 3.0, lambda: False,
                pattern=False)

    def _rift_end(self, w: dict) -> None:
        st = self.st
        _, _, length, front = wave_line(w, time.monotonic())
        at = f"격류 {front / length * 100:.0f}% · 나온 지 {time.monotonic() - w['at']:.1f}초"
        if st.warped_at > w["at"]:
            self.bot.log.info(f"격류: 균열로 넘어감 ({at})")
        elif st.fang_down:
            self.bot.log.info(f"격류: 송곳니가 쓰러짐 — 그만둠 ({at})")
        elif not self.ok(pattern=False):
            self.bot.log.info(f"격류: 쓰러졌거나 맵을 떠남 — 그만둠 ({at})")
        else:
            self.bot.log.warning(f"격류: 균열로 못 넘어감 ({at})")

    def ok(self, pattern: bool = True) -> bool:
        """계속해도 되나 — 맵을 떠났거나 쓰러졌거나 (투창이면) 패턴이 끝났으면 그만둔다."""
        p = self.bot.packets
        return self.st.active and not (pattern and self.st.finished) and not p.state.loading and not p.state.dead

    def _with_focus(self, fn) -> None:
        """게임 창을 앞으로 (키를 누른 채 있어야 해서 뒤에서는 못 한다). 뒤에서 돌던 중이면 끝나고 원래 창을 돌려준다."""
        bot = self.bot
        prev = ctypes.windll.user32.GetForegroundWindow()
        behind = bot.background and not bot.window.is_foreground()
        bot.ensure_focus()
        if not bot.window.is_foreground() and not bot.input.dry_run:
            bot.log.warning("투창 패턴: 게임 창을 앞으로 가져오지 못해 움직이지 못함")
            return
        try:
            fn()
        finally:
            bot.input.hold(())
            if behind:
                bot.window.give_back(prev)

    # ── 자리 ──
    def my_pos(self, fresh: bool = False) -> tuple[float, float] | None:
        """내 자리 — 패킷(내 이동 메시지)이 0.25초 안이면 그것, 아니면 CLI."""
        if not fresh:
            p = self.st.where(self.bot.packets.state.me, 0.25)
            if p:
                return p
        env = self.bot.environment(max_age=0.0) or {}
        w = env.get("WorldPosition") or {}
        return (w["X"], w["Y"]) if "X" in w else None

    def pos_loose(self) -> tuple[float, float] | None:
        """기다리는 동안 내 자리 — 서 있으면 이동 패킷이 안 오므로 3초 안 패킷 자리, 없으면 CLI 를 0.5초에 한 번만."""
        p = self.st.where(self.bot.packets.state.me, 3.0)
        if p:
            return p
        now = time.monotonic()
        if now - self._cli_at > 0.5:
            self._cli_pos, self._cli_at = self.my_pos(fresh=True), now
        return self._cli_pos

    # ── 움직이기 ──
    def keys_toward(self, dx: float, dy: float) -> list[str]:
        """월드 방향 (dx, dy) 로 가는 키 — W·D 성분으로 나눠 큰 쪽, 둘 다 크면 대각선."""
        (wx, wy), (ex, ey) = self.calib
        det = wx * ey - wy * ex
        a, b = (dx * ey - dy * ex) / det, (wx * dy - wy * dx) / det
        m = max(abs(a), abs(b)) or 1
        ks = []
        if abs(a) > 0.4 * m:
            ks.append("w" if a > 0 else "s")
        if abs(b) > 0.4 * m:
            ks.append("d" if b > 0 else "a")
        return ks

    def go(self, target, tol: float, until: float, done, pattern: bool = True) -> bool:
        """target 까지 키를 누른 채 다시 보며 간다. 속도 × LAG 앞에서 떼고, 멈춘 자리가 모자라거나 지나쳤으면 짧게 다시."""
        inp, fine, hist = self.bot.input, False, []
        while time.monotonic() < until and not done() and self.ok(pattern):
            self.bot.check_stop()
            p = self.my_pos()
            if not p:
                time.sleep(0.05)
                continue
            dx, dy = target[0] - p[0], target[1] - p[1]
            dist, now = math.hypot(dx, dy), time.monotonic()
            hist = [h for h in hist if now - h[0] < 0.6] + [(now, p)]
            speed = SPEED
            if inp.held and len(hist) >= 3 and now - hist[0][0] > 0.3:
                speed = math.dist(p, hist[0][1]) / (now - hist[0][0]) or SPEED
            lead = 0.0 if fine else min(2.5, max(0.6, speed * LAG))
            if dist <= tol + lead:
                inp.hold(())
                time.sleep(0.45)
                p = self.my_pos(fresh=True) or p
                dist = math.dist(target, p)
                if dist <= tol + (0.3 if fine else 0):
                    return True
                fine, hist = True, []
                continue
            inp.hold(self.keys_toward(dx, dy))
            time.sleep(0.05)
        inp.hold(())
        return False

    def hold(self, target, until: float, done, pattern: bool = True) -> None:
        """파훼까지 제자리 — 벗어나면 다시 들어가고, 아니면 0.3초마다 짧게 움찔 (반대 키로 되돌림)."""
        inp, back = self.bot.input, {"w": "s", "s": "w", "a": "d", "d": "a"}
        pair = None
        while time.monotonic() < until and not done() and self.ok(pattern):
            self.bot.check_stop()
            p = self.my_pos()
            if p and math.dist(target, p) > TOL + 0.4:
                self.go(target, TOL, until, done, pattern)
                continue
            if pair:  # 앞에서 움찔한 반대쪽으로 되돌린다
                k, pair = pair, None
            else:
                k = random.choice("wsad")
                pair = back[k]
            inp.hold((k,))
            time.sleep(0.06)
            inp.hold(())
            time.sleep(0.25)

    # ── 보정 ──
    def measure(self, key: str) -> tuple[float, float] | None:
        a = self.my_pos(fresh=True)
        self.bot.input.hold((key,))
        time.sleep(0.3)
        self.bot.input.hold(())
        time.sleep(0.3)
        b = self.my_pos(fresh=True)
        if not a or not b:
            return None
        d = math.dist(a, b)
        return ((b[0] - a[0]) / d, (b[1] - a[1]) / d) if d > 0.4 else None

    def calibrate(self) -> None:
        """W·D 를 0.3초씩 눌러 맵 방향을 잰다. 둘이 거의 직각일 때만 믿고 저장한다 (맞아서 밀려나는 중에 재면 틀린 값이 나온다)."""
        w = self.measure("w")
        d = self.measure("d")
        if not w or not d or abs(w[0] * d[0] + w[1] * d[1]) > 0.35:
            self.bot.log.info(f"투창 패턴: W·D 방향 재기 실패 (W {w} · D {d}) — 다음 기회에")
            return
        self.calib = (w, d)
        try:
            self.file.write_text(json.dumps({"w": w, "d": d}), encoding="utf-8")
        except OSError:
            pass
        self.bot.log.info(f"투창 패턴: W→({w[0]:.2f}, {w[1]:.2f}) · D→({d[0]:.2f}, {d[1]:.2f}) 저장")
