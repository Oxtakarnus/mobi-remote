"""콘텐츠(일반 던전·어비스·레이드·출항선)·보관함 구역 안에서 나가기의 공통 틀.

순서는 같다: 여기서 나가기(단축키 Shift+Esc, 안 뜨면 오른쪽 위 아이콘) → 확인 창 → 확인(Space, 안 먹으면 버튼 클릭)
→ 로딩 → 밖 메인 화면. 단축키는 게임 '여기서 나가기' 조작키다 (옵션 [game] leave_key, 게임 설정에서 바꾸면 따라감 — 사용자 11-19).
종류마다 다른 것(안인가 · 확인 창 알아보기 · 확인 방법 · 나가기 전에 판이 끝났나)만 하위 클래스가 덮어쓴다
(DungeonExit 은 여기, abyss.AbyssExit · raid.RaidExit · raid.ShipExit · drill.DrillExit · field_boss.FieldBossExit).
예전엔 네 벌이 따로 있어 'Space 가 안 먹으면 클릭'(레이드)·'나가기 전에 판이 끝났나'(어비스)가 한쪽에만 있었다.

leave_instance(bot) 는 지금 자리(place)를 보고 맞는 나가기를 부른다 — 실패 뒤 정리(runner.recover)·접속(login)이 쓴다.
맞는 나가기로 못 나오면 안전장치 두 가지(_escape): 여기서 나가기 키 뒤 확인 창이면 Space, 그래도 안이면 ESC 메뉴로
캐릭터 선택 화면에 나가 다시 접속. 게임을 끄고 켜지는 않는다 (사용자 2026-11-23).
"""
import time

from .. import gamedata as gd, keys, ocr
from ..bot import Bot
from ..exceptions import StepTimeout


class Exit:
    NAME = ""        # 로그·오류에 쓰는 이름
    SNAP = "leave"   # 실패 스냅샷 이름
    HOTKEY = "leave"  # 나가기 단축키 이름 (mabi.keys — 여기서 나가기. 클릭과 달리 뒤에서 도는 게임을 앞으로 가져오지 않는다)
    TIMEOUT = 120    # 나가기를 누르는 데 쓰는 시간 상한 (횟수가 아니라 시간 — 사람이 PC 를 쓰는 동안 클릭이 몇 번 건너뛰어져도)
    # 안인지 모를 때(where 가 None) 안으로 보고 나가기를 누를까. 모름 처리는 이 한 줄로 정한다 (2026-11-16 점검: 종류마다
    # 모름을 안·밖으로 제각각 읽었다). 나가기 아이콘이 다른 곳(사냥터 등)의 아이콘과 헷갈리는 종류는 누르지 않는다(False)
    UNKNOWN_INSIDE = False

    # ---- 종류마다 덮어쓴다
    def where(self, bot: Bot) -> bool | None:
        """안이면 True, 밖이면 False, 모르면 None."""
        raise NotImplementedError

    # ---- where 로 정해진다 (모름은 UNKNOWN_INSIDE)
    def inside(self, bot: Bot) -> bool:
        """아직 안이라 나가기를 눌러야 하나."""
        w = self.where(bot)
        return self.UNKNOWN_INSIDE if w is None else w

    def gone(self, bot: Bot) -> bool:
        """다 나왔나 (메인 화면과 같이 본다) — 안이라고 알 때만 아니다."""
        return self.where(bot) is not True

    def dialog(self, bot: Bot, timeout: float):
        """확인 창이 떴으면 그 표시(누를 자리면 좌표), 아니면 None. timeout 동안 기다린다."""
        raise NotImplementedError

    def confirm(self, bot: Bot, hit) -> None:
        """확인 창에서 나가기. 기본: Space, 로딩이 안 시작되고 창이 남았으면 그 자리를 누른다
        (레이드에서 29판을 잘 돌다 이 창에서만 Space 를 안 받고 창이 그대로 남았다 — 마우스로는 넘어감, 2026-10-28)."""
        bot.key("space")
        if not bot.wait_packet(lambda s: s.loading, 6, since=bot.input_mark) and (again := self.dialog(bot, 0)):
            bot.log.info(f"Space 를 눌러도 {self.NAME}에서 안 나가짐 → 확인 버튼 클릭")
            if isinstance(again, tuple):
                bot.click(again)
            else:
                bot.key("space")

    def surely_inside(self, bot: Bot) -> bool:
        """단축키를 눌러도 되나 — 안이라고 알 때만."""
        return self.where(bot) is True

    def finished_before(self, bot: Bot) -> bool:
        """나가기 전에 판이 끝났나 (끝났으면 나가지 않고 부르는 쪽이 결과로 잇는다)."""
        return False

    def uncover(self, bot: Bot) -> None:
        """나가기 버튼이 안 보일 때 — 가린 창(부활 창 등)을 닫아 본다."""
        bot.key("esc")

    def open_dialog(self, bot: Bot):
        """확인 창이 아직 없을 때 나가기를 눌러 띄운다 → dialog 표시, 못 띄웠으면 None (안인지부터 다시 본다).
        기본: 여기서 나가기 단축키 먼저, 창이 안 뜨면 오른쪽 위 나가기 아이콘. 키는 안이 확실하거나 아이콘이 보일 때만 —
        둘 다 아니면(가린 창 등) uncover 뒤 다시 본다."""
        icon = bot.exists(bot.ui["abyss_exit"])
        if not icon and not self.surely_inside(bot):
            self.uncover(bot)
            bot.sleep(1.0, 1.5)
            return None
        if hit := self.press_hotkey(bot, 4):
            return hit
        if not icon:
            self.uncover(bot)  # 단축키로도 안 뜸 — 가린 창(부활 창 등)을 닫아 본다
            bot.sleep(1.0, 1.5)
            return None
        # 아이콘이 보였다가 누르기 전에 사라질 수 있다 — 판이 끝나 게임이 밖으로 내보냄 (2026-11-23 13:18 레이드: 아이콘을
        # 10초 기다려 누르는 click 이 StepTimeout 으로 실패) → 누르지 못했으면 안인지부터 다시 본다
        if not bot.click_if(bot.ui["abyss_exit"]):
            bot.log.debug(f"{self.NAME} 나가기: 아이콘이 사라짐 → 안인지부터 다시")
            return None
        bot.log.debug(f"{self.NAME} 나가기: 아이콘 클릭")
        return self.dialog(bot, 5)

    def press_hotkey(self, bot: Bot, timeout: float):
        """여기서 나가기 단축키를 누르고 확인 창을 기다린다 → dialog 표시, 단축키가 없거나 창이 안 뜨면 None."""
        key = keys.of(bot, self.HOTKEY) if self.HOTKEY else ""
        if not key:
            return None
        bot.log.debug(f"{self.NAME} 나가기: {key.upper()} 키")
        bot.key(key)
        return self.dialog(bot, timeout)

    # ---- 공통
    def run(self, bot: Bot) -> bool:
        """나간다. 다 나와 메인 화면이 보이면 True, 나가기 전에 판이 끝났으면 False."""
        for attempt in range(self.RETRIES + 1):
            got = self._press(bot)
            if got is not None:
                return got
            if attempt == self.RETRIES:
                break
            # 확인까지 눌렀는데 그대로 안이다 — 나가는 사이 부활(어비스 우연한 만남: 캠프파이어에 앉은 파장이 전체 부활)이
            # 확인 창을 닫았다. 한 번 나가기로 정했으면 무슨 일이 생겨도 나간다 (2026-11-06 사용자) → 처음부터 다시 누른다
            bot.log.warning(f"{self.NAME} 나가기를 눌렀는데 아직 안 (나가는 사이 부활 등) → 다시 나가기 "
                            f"({attempt + 1}/{self.RETRIES}) → {bot.snapshot(self.SNAP + '_again').name}")
        raise StepTimeout(f"{self.NAME}에서 나가기를 {self.RETRIES + 1}번 눌러도 안에 남음 → {bot.snapshot(self.SNAP).name}")

    RETRIES = 3     # 확인까지 눌렀는데 안에 남았을 때 처음부터 다시 누르는 횟수
    STAY = 20       # 확인 뒤 이만큼 로딩이 안 시작되고 안에 그대로면 안 나가진 것으로 본다 (초)

    def _press(self, bot: Bot) -> bool | None:
        """나가기 → 확인 → 밖. True 나옴 / False 나가기 전에 판이 끝남 / None 확인까지 눌렀는데 안에 남음."""
        deadline = time.monotonic() + self.TIMEOUT
        while True:
            if self.finished_before(bot):
                bot.log.info(f"나가기 전에 판이 끝남 ({self.NAME}) → 나가지 않고 결과로")
                return False
            if not self.inside(bot):
                break
            if time.monotonic() > deadline:
                raise StepTimeout(f"{self.NAME}에서 나가지 못함 → {bot.snapshot(self.SNAP).name}")
            hit = self.dialog(bot, 0)  # 확인 창이 이미 떠 있으면(지난 시도의 Space 가 안 먹음) 그 창부터
            if not hit:
                hit = self.open_dialog(bot)
                if not hit:
                    continue
                bot.sleep(0.5, 0.9)
            bot.log.debug(f"{self.NAME} 나가기: 확인 창 → 나가기")
            self.confirm(bot, hit)
            break
        # 밖으로 나와 메인 화면이 보일 때까지 — 패킷이 있으면 맵을 떠나기 시작하는 순간(길어야 15초)을 기다렸다가,
        # 로딩 동안은 화면을 보지 않는다
        pressed = time.monotonic()
        if bot.wait_packet(lambda s: s.loading, 15, since=bot.input_mark) is False and self.inside(bot) \
                and not bot.map_loading():
            return None  # 패킷: 맵을 떠나기 시작하지 않았고 그대로 안
        end = time.monotonic() + bot.cfg["timing"]["loading"]
        left = False  # 로딩이든 밖이든 한 번이라도 안을 벗어났나
        while time.monotonic() < end:
            if bot.map_loading():
                left = True
                bot.wait_loaded(end - time.monotonic())
                continue
            if self.gone(bot):
                left = True
                if bot.at_main():
                    return True
                if not bot.is_loading():
                    bot.clear_blockers(ocr=True)  # 나오면서 뜬 퀘스트 완료 창 등
            elif not left and not bot.is_loading() and time.monotonic() - pressed > self.STAY:
                return None  # 패킷 없이 화면으로만: 확인 뒤 한참 그대로 안
            bot.sleep(2)
        raise StepTimeout(f"{self.NAME}에서 나온 뒤 메인 화면이 나오지 않음")


class DungeonExit(Exit):
    """일반 던전(공물·은동전·요일): 어비스와 같은 오른쪽 맨 위 나가기 → '던전에서 퇴장하시겠습니까?' → 나가기(Space)."""
    NAME, SNAP = "던전", "dungeon_leave"

    def where(self, bot):
        from ..place import DUNGEON, place
        kind = place(bot).kind
        return None if kind is None else kind == DUNGEON

    def dialog(self, bot, timeout):
        if timeout <= 0:
            return bot.exists(bot.ui["abyss_exit_dialog"]) or None
        try:
            return bot.wait(bot.ui["abyss_exit_dialog"], timeout=timeout)
        except StepTimeout:
            return None


class HousingExit(Exit):
    """여관 안쪽 보관함 구역·마이 홈: 오른쪽 위 나가기 (던전과 같은 아이콘) → 아래 '반호르 여관에서 나가시겠습니까?'
    (마을 이름이 들어가 글자 대신 초록 'Space 나가기' 버튼으로 본다) → Space, 안 먹으면 그 버튼.
    여기서 접속을 끊은 캐릭터는 숙제 이동이 안 돼 헤맨다 — 숙제 시작(login)·실패 뒤 정리(recover)가 먼저 꺼낸다."""
    NAME, SNAP = "보관함 구역", "housing_leave"
    LOADING = "loading"   # 확인 창 없이 바로 맵을 떠나기 시작함

    def where(self, bot):
        from ..place import HOUSINGS, place
        kind = place(bot).kind
        return None if kind is None else kind in HOUSINGS

    def dialog(self, bot, timeout):
        end = time.monotonic() + max(0.0, timeout)
        while True:
            if bot.map_loading():
                return self.LOADING
            if hit := bot.exists(bot.ui["housing_exit_ok"]):
                return hit
            if time.monotonic() >= end:
                return None
            bot.sleep(0.4, 0.6)

    def confirm(self, bot, hit):
        if hit == self.LOADING:
            return
        super().confirm(bot, hit)


def leave_instance(bot: Bot) -> bool:
    """지금 콘텐츠(일반 던전·어비스·레이드·출항선)·보관함 구역 안이면 맞는 나가기로 밖 메인 화면까지.
    나갔으면 True, 밖이면 False. 맞는 나가기로 못 나오면 안전장치(_escape)를 해 보고, 그래도 안이면 StepTimeout.
    사냥터·검은 구멍은 나가지 않는다 (끝날 때까지 기다리는 것이 숙제 규칙 — login._leave_dungeon)."""
    from ..place import ABYSS, DUNGEON, HOUSINGS, RAID, RAID_LOBBY, place
    kind = place(bot).kind
    if kind in HOUSINGS:
        name, leave = HousingExit.NAME, lambda: HousingExit().run(bot)
    elif kind == DUNGEON:
        name, leave = DungeonExit.NAME, lambda: DungeonExit().run(bot)
    elif kind == ABYSS:
        from . import abyss
        name, leave = abyss.AbyssExit.NAME, lambda: abyss.get_out(bot)
    elif kind in (RAID, RAID_LOBBY):
        from . import raid
        name, leave = (raid.RaidExit if kind == RAID else raid.ShipExit).NAME, lambda: raid.get_out(bot)
    else:
        return False
    try:
        leave()
    except StepTimeout as e:
        _escape(bot, kind, name, e)
    bot.log.info(f"콘텐츠 안({kind}) → 나옴")
    return True


def _confirm_dialog(bot: Bot):
    """화면 가운데 확인 창의 '취소' 버튼 글자 자리, 없으면 None. 넓게 읽으면 ESC 표시와 한 덩이('ESc 취소')로 읽힌다.
    '매칭 취소' 같은 다른 버튼 글자는 아니다."""
    want = gd.text("dialog_cancel")
    for t, x, y in ocr.find_texts(bot.frame(), gd.region("confirm_dialog")):
        if ocr.nospace(t).lower() in (want, "esc" + want):
            return x, y
    return None


class AnyDialogExit(Exit):
    """맞는 나가기로 못 나왔을 때 첫 안전장치 (_escape): 여기서 나가기 키를 누르고, 가운데 확인 창('취소' 버튼)이 뜨면
    무슨 창인지 알아보지 않고 Space(창의 기본 버튼)를 누른다 — 처음 보는 나가기 창이어도 나간다 (2026-11-23 레이드 함께하기
    전멸 '포기하기' 창을 몰라 20분 동안 다음 캐릭터 접속이 줄줄이 실패). 창이 안 뜨면 누르지 않는다 (보상 화면의 Space 는
    '다시 하기' 일 수 있다). 아이콘은 누르지 않는다. 나갔는지는 틀(_press)대로 로딩·자리로 본다."""
    SNAP = "leave_any"
    RETRIES = 1
    TIMEOUT = 20
    UNKNOWN_INSIDE = True  # 맵을 모르면 안으로 보고 누른다 — 나왔는지는 _escape 가 자리로 다시 본다

    def __init__(self, kind: str, name: str):
        self.kind, self.NAME = kind, name

    def where(self, bot):
        from ..place import on_map
        return on_map(bot, self.kind)

    def dialog(self, bot, timeout):
        """나가기 키 뒤 뜬 확인 창 ('취소' 자리). 키를 누르기 전(timeout 0)엔 보지 않는다 — 떠 있던 창은 open_dialog 가 닫는다."""
        if timeout <= 0:
            return None
        end = time.monotonic() + timeout
        while not (hit := _confirm_dialog(bot)) and time.monotonic() < end:
            bot.sleep(0.8, 1.2)
        return hit

    def open_dialog(self, bot):
        if _confirm_dialog(bot):
            bot.key("esc")  # 무슨 창인지 모르는 채 떠 있던 확인 창은 닫고 나가기 키부터
            bot.sleep(1.0, 1.5)
        return self.press_hotkey(bot, 3)


def _escape(bot: Bot, kind: str, name: str, err: StepTimeout) -> None:
    """맞는 나가기로 콘텐츠에서 못 나왔을 때 (처음 보는 창·쓰러진 채 등) — 사용자 2026-11-23 결정, 게임을 끄고 켜지는 않는다.
    ① 여기서 나가기 키 → 가운데 확인 창이면 Space (AnyDialogExit)
    ② ESC 메뉴 → 게임 종료 → 캐릭터 선택 화면 (메인 화면을 거치지 않는다) → bot.character 로 다시 접속 (login.enter_again —
       실패 뒤 정리면 그 캐릭터, 접속 중이면 고를 캐릭터. 못 나온 캐릭터 때문에 다음 캐릭터 접속이 줄줄이 실패하지 않게)
    다시 들어가서도 안이면 StepTimeout."""
    from ..place import place
    from . import login
    bot.log.warning(f"{err} → 여기서 나가기 키 뒤 확인 창이면 Space")
    try:
        AnyDialogExit(kind, name).run(bot)
        if place(bot).kind != kind:
            bot.log.info(f"{name}: 나가기 키 뒤 Space 로 나옴")
            return
    except StepTimeout as e:
        bot.log.warning(str(e))
    bot.log.warning(f"{name}에서 못 나옴 → ESC 메뉴로 캐릭터 선택 화면에 나가 다시 접속")
    try:
        bot.menu_to_charselect()
        bot.log.info(login.enter_again(bot))
    except StepTimeout as e:
        raise StepTimeout(f"{err} · 나가기 키 뒤 Space·다시 접속도 안 됨 ({e})") from e
    if place(bot).kind == kind:
        raise StepTimeout(f"{err} · 다시 접속해도 {name} 안 → {bot.snapshot(AnyDialogExit.SNAP).name}")
    bot.log.info(f"{name}: 다시 접속해서 나옴")
