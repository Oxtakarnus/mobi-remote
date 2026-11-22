"""필드 보스 (주간 숙제): 캐릭터마다 이번 주 1번 잡는다 ('남은 토벌 전리품 1/1회').

흐름 (2026-11-09 12시에 6캐릭터로 확인, 사용자 설명):
  메뉴(ESC) → '필드 보스' → 창 왼쪽 보스 목록에서 보스 · 위쪽 난이도 → '이동하기'(Space) → '이동하시겠습니까' 이동하기(Space)
  → 사냥터 안 보스 지역으로 자동 이동 (빠른 이동) → 도착하면 '○○의 영역에 들어가시겠습니까'(고른 난이도) → 입장하기(Space)
  → 맵 FieldBoss → 그 출현 시간의 캐릭터별 첫 입장엔 컷신 — 로딩이 끝나고 오른쪽 위 '장면 넘기기' 가 뜨면 약 1초 뒤 누른다
    (너무 일찍 누르면 안 먹고, 컷신이 끝난 뒤 그 자리를 누르면 지도가 열린다) → Space 한 번 = 자동 전투
  → 보스가 쓰러지면 결과 창 '처치 완료' → 확인(Space) — 창은 아래 가운데 '확인' 으로 본다 (위쪽 글자는 연속 실행 제한 창이 가린다). 다른 사람들이 금방 잡아 컷신 중에 끝나기도 한다 —
    '전투에 참여하지 않아 획득할 수 있는 보상이 없습니다' 면 영역을 나갔다가 다시 들어간다 (새 보스)
  → 오른쪽 위 나가기 → '영역에서 나가시겠습니까' 나가기(Space). 나가지 않으면 퇴장 시간(4분) 뒤 보관함 쪽으로 뛰어간다.
열리는 때: 매일 12:00 · 18:00 · 20:00 · 22:00 (PC 시계, 한국 시간) 부터 30분. 한 캐릭터에 1~3분 (전환 포함).
잡았나는 CLI get_growth_guide 의 '필드 보스' Weekly IsCompleted — 들어가기 전에도 보고 이미 잡았으면 넘긴다.
보스는 [field_boss] boss · difficulty (주간 숙제 탭). 보스 목록: 페리 · 크라브바흐 · 크라마 · 드로흐에넴 (매우 어려움까지),
토르모그 · 앙그르바한 (어려움까지).
보스전이라 궁극기·팔라딘 변신을 어비스·레이드와 같은 설정으로 쓴다 (boss_skills).
"""
import datetime as dt
import time

from .. import gamedata as gd, monitor
from ..bot import Bot
from ..exceptions import CannotProceed, NotSeen, StepTimeout
from ..game_state import Activity
from ..place import FIELD_BOSS, on_map
from . import press, ui_text
from .boss_skills import BossSkills
from .arrival import wait_arrival
from .clear import confirm_text
from .fight import watch
from .guide import growth_done
from .exits import Exit

MIN_LEFT = 4 * 60          # 남은 시간이 이보다 적으면 새 캐릭터를 시작하지 않는다 (초) — 한 캐릭터 1~3분
GROWTH = "필드 보스"       # CLI 성장 가이드의 Target
SKIP_WAIT = 1.0            # '장면 넘기기' 가 뜬 뒤 누르기까지 (사용자 — 0.5초는 안 먹었다)
SKIP_LOOK = 8              # 들어간 뒤 '장면 넘기기' 를 찾는 시간 (초) — 이 출현 시간에 이미 본 캐릭터는 컷신이 없다
SKIP_MAX = 25              # 패킷이 연출 중이라 하면 버튼을 이만큼까지 기다린다 (초)
# 끊긴 전투를 이어 받을 때: 그 전투를 시작한 지 전투 시간 상한([field_boss] fight_timeout)에 이만큼 더 지났으면 영역에서
# 이미 나가졌다고 본다 (초) — 보스가 쓰러지고 퇴장 시간(4분)이 지나면 저절로 나가진다
CUT_LATE = 5 * 60
# 보스·난이도·출현 시각은 게임 데이터(data/content.json, gamedata.field_bosses·field_boss_hours).
# 보스는 창 왼쪽 목록에 그 순서로 있다 — 누를 때는 순서로 (OCR 이 '드로흐에넴' 을 '…넬' 로 읽는다)


def choices(boss: str, difficulty: str) -> dict:
    """화면(필드 보스 칸)이 고를 수 있는 것 — 보스 목록, 보스마다 고를 수 있는 난이도,
    기본값(화면에서 아직 고른 적이 없을 때 — 부르는 쪽이 config.default.toml [field_boss] 에서 준다)."""
    bosses = gd.field_bosses()
    return {"bosses": list(bosses), "difficulties": bosses,
            "boss": boss, "difficulty": difficulty}


# ---- 열리는 시간

def window(now: dt.datetime | None = None) -> tuple[int, dt.datetime]:
    """(지금 열려 있으면 남은 초, 아니면 0, 다음에 열리는 때 — 열려 있으면 지금 회차의 시작)."""
    now = now or dt.datetime.now()
    hours, open_min = gd.field_boss_hours()
    for h in hours:
        start = now.replace(hour=h, minute=0, second=0, microsecond=0)
        end = start + dt.timedelta(minutes=open_min)
        if start <= now < end:
            return int((end - now).total_seconds()), start
        if now < start:
            return 0, start
    tomorrow = (now + dt.timedelta(days=1)).replace(hour=hours[0], minute=0, second=0, microsecond=0)
    return 0, tomorrow


def not_ready(now: dt.datetime | None = None) -> str:
    """새 캐릭터를 시작하면 안 되는 까닭 (열린 시간이 아님 · 곧 닫힘), 시작해도 되면 빈 문자열."""
    now = now or dt.datetime.now()   # '곧 닫힘' 의 다음 열림 계산에 쓴다 — 빈 채로 두면 그 줄에서 죽었다 (2026-11-16)
    left, at = window(now)
    if left >= MIN_LEFT:
        return ""
    if left:
        return f"필드 보스가 곧 닫힘 (남은 {left // 60}분) — 다음 열림 {window(now + dt.timedelta(seconds=left + 1))[1]:%H:%M}"
    return f"필드 보스가 열린 시간이 아님 — 다음 열림 {at:%H:%M}"


# ---- 상태

def done(bot: Bot) -> bool | None:
    """이번 주 잡았나 (CLI 성장 가이드). 모르면 None."""
    return growth_done(bot, GROWTH, "Weekly")


def inside(bot: Bot) -> bool | None:
    """보스 영역 안인가 — 패킷 맵으로 (place.on_map). 패킷이 맵을 모르면(리모콘을 영역 안에서 다시 켬·감시 꺼짐) CLI 가
    사냥터 밖이라 할 때만 밖(False) — 영역은 사냥터를 거쳐 들어가 그 안에서도 CLI 는 사냥터 안이라 답한다 (place.CLI_FLAGS).
    로딩 중이거나 사냥터 안이면 모름(None). '모름' 을 '밖' 으로 읽지 않는다."""
    known = on_map(bot, FIELD_BOSS)
    if known is not None or bot.map_loading():
        return known
    act = bot.activity()
    return False if act is not None and not Activity.of(act).in_field else None


def _texts(bot: Bot, key: str) -> str:
    from ..ocr import find_texts, nospace
    return "".join(nospace(t) for t, _, _ in find_texts(bot.frame(), gd.region(key)))


# ---- 단계

def open_window(bot: Bot, boss: str, difficulty: str) -> None:
    """메뉴(ESC) → 필드 보스 창 → 보스 · 난이도를 고른다."""
    ui_text.open_menu(bot, "fb_menu", "메뉴의 필드 보스", "field_boss")
    if not ui_text.wait(bot, gd.text("fb_title"), gd.region("fb_title"), timeout=8):
        raise NotSeen(f"필드 보스 창이 열리지 않음 → {bot.snapshot('field_boss').name}")
    bot.sleep(0.8, 1.2)
    bosses = list(gd.field_bosses())
    if boss not in bosses:
        raise CannotProceed(f"모르는 필드 보스 '{boss}' (고를 수 있는 것: {', '.join(bosses)})")
    rows = gd.point("field_boss_rows")  # 목록 카드 가운데
    if bosses.index(boss) >= len(rows):
        raise CannotProceed(f"필드 보스 목록 칸 자리(ui.json field_boss_rows)가 {len(rows)}개뿐 — '{boss}' 는 {bosses.index(boss) + 1}번째")
    bot.click_xy(*rows[bosses.index(boss)])
    bot.sleep(1.0, 1.4)
    if difficulty:
        ui_text.click(bot, difficulty, gd.region("fb_difficulty"), what=f"난이도 '{difficulty}'", shot="field_boss")
        bot.sleep(0.6, 0.9)


def travel(bot: Bot, boss: str) -> None:
    """창의 이동하기 → 확인 → 빠른 이동 → 보스 지역 입장 창이 뜰 때까지. 이동이 시작됐나는 결과(자동 이동·맵 로딩·
    이미 가까워 입장 창)로 본다 — '이동하시겠습니까' 글자를 못 읽어 두 번째 Space 를 안 누르면 이동 상한(5분)을 헛기다렸다.
    안 시작됐으면 다시 누른다 (확인 창이 떠 있었으면 그 창의 이동하기가 된다 — press.until)."""
    bot.step("fb_move", f"'{boss}' 지역으로 이동")

    def press_move():
        bot.key("space")  # 이동하기
        if ui_text.wait(bot, gd.text("fb_move_confirm"), gd.region("fb_dialog"), timeout=5, exact=False):
            bot.key("space")  # '이동하시겠습니까' 이동하기

    press.until(bot, press_move, lambda: press.poll(bot, lambda: bool(
        bot.auto_traveling() or bot.map_loading() or ui_text.find(bot, gd.text("fb_enter"), gd.region("fb_dialog"), exact=False))),
        "필드 보스 이동하기", shot="fb_move")
    bot.fast_travel(wait=6)
    wait_arrival(bot, lambda: bool(ui_text.find(bot, gd.text("fb_enter"), gd.region("fb_dialog"), exact=False)),
                 bot.cfg["field_boss"]["travel_timeout"], "fb_travel",
                 f"'{boss}' 지역에 닿지 못함 (입장 창이 안 뜸)", retry_fast=True, interval=(1.0, 1.4))


def enter(bot: Bot) -> None:
    """입장하기(Space) → 보스 영역 맵 → 컷신이면 '장면 넘기기' → Space 한 번(자동 전투). 입장하기가 먹었나는 맵 로딩
    신호로 본다 (press.until — 안 오면 다시 누른다)."""
    bot.step("fb_enter", "보스 영역 입장")
    press.until(bot, lambda: bot.key("space"), press.signal(
        bot, lambda s: s.loading or s.channel_type == FIELD_BOSS,
        still=lambda: bool(ui_text.find(bot, gd.text("fb_enter"), gd.region("fb_dialog"), exact=False))),
        "보스 영역 입장하기", shot="fb_enter")
    if bot.packets.ok:
        if not bot.wait_packet(lambda s: s.channel_type == FIELD_BOSS and not s.loading, 40, since=bot.input_mark):
            raise NotSeen(f"보스 영역에 들어가지 못함 → {bot.snapshot('fb_enter').name}")
    else:
        bot.sleep(8, 9)
    # 로딩이 끝나고 컷신이면 '장면 넘기기' 가 곧 뜬다. 안 뜨면(이 출현 시간에 이미 본 캐릭터) 그냥 지나간다.
    # 패킷이 연출 중이라 하면 버튼이 늦게 떠도 기다린다 — 12:07(2026-11-16)엔 들어간 지 16초 뒤에 떠 8초 창을 놓쳤고,
    # 자동 전투 Space 를 연출 중에 눌렀다
    start = time.monotonic()
    end = start + SKIP_LOOK
    while time.monotonic() < end:
        hit = ui_text.find(bot, gd.text("fb_skip"), gd.region("fb_skip"), exact=False)
        if hit:
            bot.sleep(SKIP_WAIT)
            bot.click(hit)
            bot.sleep(0.8, 1.0)
            if not ui_text.find(bot, gd.text("fb_skip"), gd.region("fb_skip"), exact=False):
                bot.log.info("필드 보스 컷신 넘김")
                break
            end = max(end, time.monotonic() + 3)  # 안 먹었다 — 다시
        else:
            if bot.cutscene_playing() and time.monotonic() < start + SKIP_MAX:
                end = max(end, time.monotonic() + 1)
            bot.sleep(0.2)
    # 자동 전투는 연출이 끝난 뒤에 누른다 (패킷이 모르면 예전처럼 바로)
    if bot.cutscene_playing():
        bot.wait_packet(lambda s: not s.cutscene, max(1.0, start + SKIP_MAX - time.monotonic()))
    bot.sleep(0.6, 0.9)
    bot.key("space")  # 자동 전투


def fight(bot: Bot, until: float | None = None) -> bool:
    """결과 창까지 기다려 확인(Space). 보상을 받았으면 True, '참여하지 않아 보상 없음' 이면 False.
    until: 이 시각(time.time)까지만 기다린다 — 맵을 모르는 채 끊긴 전투를 이어 받을 때 (finish_inside).
    결과 창 없이 보스 영역 밖으로 나왔어도 False — 컷신 중에 다른 사람이 잡아 결과 창을 놓쳤거나(자동 전투 Space 가 그
    창을 닫음) 퇴장 시간이 지난 것. 실패로 끝내면 다시 들어가 보지 못했다 (2026-11-16 12:07). run 이 성장 가이드로 잡았나를
    보고 다시 들어간다."""
    bot.step("fb_fight", "보스와 전투 중")
    here = lambda s: s.channel_type == FIELD_BOSS  # noqa: E731 — 보스 영역 안 전체가 보스전
    skills = BossSkills.for_current(bot, bot.character, here, inside=here)
    ctx = monitor.Ctx("field_boss", "필드 보스 전투", revive=True)
    end = time.monotonic() + bot.cfg["field_boss"]["fight_timeout"]
    if until:
        end = min(end, time.monotonic() + until - time.time())
    asked = time.monotonic()
    while time.monotonic() < end:
        result = confirm_text(bot.frame())  # 결과 창 '처치 완료' (아래 가운데 '확인') — 한 바퀴에 한 번 읽는다
        # 결과 창을 놓쳤어도(점검자가 먼저 닫음 등) 잡았으면 끝 — 성장 가이드로 가끔 본다
        if time.monotonic() - asked > 15:
            asked = time.monotonic()
            if done(bot):
                bot.log.info("필드 보스 처치 완료 (성장 가이드)")
                if result:
                    bot.key("space")  # 결과 창이 떠 있으면 닫고 나간다
                    bot.sleep(1.2, 1.6)
                return True
        if result:
            bot.sleep(1.0, 1.5)  # 보상이 그려지는 동안
            got = gd.text("fb_noreward") not in _texts(bot, "fb_noreward")
            if got and done(bot) is False:  # '확인' 은 있는데 아직 안 잡음 — 퀘스트 완료 같은 다른 창 → 넘기고 계속
                bot.log.info("필드 보스 전투 중 '확인' 창 → 넘김")
                bot.key("space")
                bot.sleep(1.0, 1.3)
                continue
            bot.log.info("필드 보스 처치 완료 — " + ("보상 받음" if got else "전투에 참여하지 않아 보상 없음"))
            bot.key("space")  # 확인
            bot.sleep(1.2, 1.6)
            return got
        if inside(bot) is False:   # 다른 맵이라고 알거나 CLI 가 사냥터 밖이라 할 때만 — 모름(None)은 나간 것이 아니다
            bot.log.warning(f"결과 창 없이 보스 영역 밖으로 나옴 → 보상을 못 받은 것으로 봄 ({bot.snapshot('fb_fight').name})")
            return False
        act = bot.activity() or {}
        skills.tick(act)
        seen = watch(bot, ctx, act)
        if not seen.done:
            bot.sleep(1.0, 1.3)
    raise CannotProceed(f"필드 보스 결과가 {bot.cfg['field_boss']['fight_timeout'] // 60}분 안에 안 나옴 "
                        f"→ {bot.snapshot('fb_fight').name}")


class FieldBossExit(Exit):
    """보스 영역에서 나간다: 여기서 나가기(Shift+Esc, 안 뜨면 오른쪽 위 나가기 — 던전과 다른 자리 fb_exit_button)
    → '영역에서 나가시겠습니까' 나가기(Space).
    영역 밖이면 아무것도 누르지 않는다 (밖에서 그 자리를 누르면 다른 창이 열린다). 감시가 꺼졌거나 맵을 모르면 안으로 보고 누른다."""
    NAME, SNAP = "보스 영역", "fb_leave"
    TIMEOUT = 15  # 나가기 창을 띄우는 데 쓰는 시간 — 예전처럼 몇 번(누르기 + 3초)만 해 보고 그만둔다

    UNKNOWN_INSIDE = True  # 감시가 꺼졌거나 맵을 모르면 안으로 보고 누른다

    def where(self, bot):
        return inside(bot)  # 모르면 UNKNOWN_INSIDE — 예전엔 감시가 켜져 있으면 맵을 몰라도 밖으로 봤다

    def dialog(self, bot, timeout):
        return ui_text.wait(bot, gd.text("fb_exit"), gd.region("fb_dialog"), timeout=max(0.0, timeout), exact=False)

    def open_dialog(self, bot):  # 여기서 나가기 단축키 먼저, 안 뜨면 오른쪽 위 나가기 자리를 누른다
        if hit := self.press_hotkey(bot, 3):
            return hit
        x, y, w, h = gd.region("fb_exit_button")
        bot.click((x + w // 2, y + h // 2))
        return self.dialog(bot, 3)

    def confirm(self, bot, hit):  # 찾은 글자는 창의 문구라 누를 자리가 아니다 — Space 만
        bot.key("space")
        bot.log.info("보스 영역 나가기")


def leave(bot: Bot) -> None:
    """보스 영역 안이면 나간다 (FieldBossExit). 못 나가도 멈추지 않고 남긴다 — 영역은 퇴장 시간(4분)이 지나면 저절로 나가진다."""
    try:
        FieldBossExit().run(bot)
    except StepTimeout as e:
        bot.log.warning(f"보스 영역 나가기: {e}")


def fight_cut(bot: Bot, last: dict | None) -> bool:
    """보스와 싸우던 중에 끊겼고(마지막 단계 기록 last 가 전투) 영역 밖이라고 알지 않는가 — 숙제(run)와 접속의 시작
    정리(finish_cut)가 이 한 기준으로 본다. 리모콘을 영역 안에서 다시 켜 맵을 모르면(None) 끊긴 전투로 보고 결과를
    기다린다 — 영역 안에선 리모콘이 할 일이 없으니 결과(처치·전멸)에만 대응하고 나가면 거기서 다시 본다 (사용자
    2026-11-22. 예전엔 모르면 끊긴 것으로 보지 않아 영역 안에서 메뉴부터 열었다). 다만 맵을 모르고 그 전투를 시작한 지
    전투 시간 상한 + CUT_LATE 가 지났으면 이미 나가졌다."""
    last = last or {}
    if last.get("step") != "fb_fight":
        return False
    where = inside(bot)
    if where is None and (until := _cut_until(bot, last)) is not None and time.time() > until:
        return False
    return where is not False


def _cut_until(bot: Bot, last: dict) -> float | None:
    """끊긴 전투에서 영역에 남아 있을 수 있는 마지막 시각 (time.time) — 그 전투를 시작한 때부터 센다. 모르면 None."""
    ts = last.get("ts")
    return ts + bot.cfg["field_boss"]["fight_timeout"] + CUT_LATE if ts else None


def finish_cut(bot: Bot, cut: dict, kind: str | None) -> bool:
    """접속의 시작 정리(tasks.FINISH_CUT): 보스와 싸우던 중에 끊겼으면 그 전투부터 마치고 나온다. 아니면 False."""
    last = bot.daily.last_step(cut["slot"], "field_boss")
    if not fight_cut(bot, last):
        return False
    bot.step("fb_inside_at_login", "보스와 싸우던 중에 끊김 → 그 전투부터 마침")
    finish_inside(bot, last)
    return True


def finish_inside(bot: Bot, last: dict | None = None) -> bool:
    """보스와 싸우던 중에 끊긴 채 보스 영역 안에서 다시 시작함: 나가지 않고 그 전투부터 마치고 나온다 — 예전엔 나가서
    새 보스로 다시 들어가 쌓은 기여를 버렸다 (점검 2026-11-22). 보상을 받았으면 True (못 받았으면 run 이 다시 들어간다).
    맵을 모르면(리모콘을 영역 안에서 다시 켬) 끊긴 전투(last)를 시작한 때부터 센 시간까지만 기다린다 (_cut_until)."""
    got = fight(bot, until=_cut_until(bot, last or {}) if inside(bot) is None else None)
    leave(bot)
    return got


def run(bot: Bot, cfg: dict) -> str:
    fb = cfg["field_boss"]
    boss, difficulty = fb["boss"], fb["difficulty"]
    if done(bot):
        return "이번 주 이미 잡음"
    if fight_cut(bot, bot.resume):
        bot.log.info("보스와 싸우던 중에 끊김 → 그 전투부터" + ("" if inside(bot) else " (맵을 모름 — 결과를 기다림)"))
        try:
            if finish_inside(bot, bot.resume):
                return f"{boss} {difficulty} 처치 (끊긴 전투를 이어서)"
        except CannotProceed as e:  # 결과가 안 나옴 — 맵을 모르는 채 영역 밖이었을 수 있다. 지금 자리에서 다시 본다
            bot.log.warning(f"끊긴 전투: {e} → 지금 자리에서 다시")
    if inside(bot):
        bot.log.info("이미 보스 영역 안 → 나가서 다시")
        leave(bot)
    for attempt in range(3):
        if attempt and done(bot):  # 결과 창을 놓쳤지만 잡았다 (성장 가이드)
            return f"{boss} {difficulty} 처치 (결과 창 없이 — 성장 가이드로 확인)"
        if (why := not_ready()):
            raise CannotProceed(why)
        open_window(bot, boss, difficulty)
        travel(bot, boss)
        enter(bot)
        got = fight(bot)
        leave(bot)
        if got:
            return f"{boss} {difficulty} 처치"
        bot.log.info("보상을 못 받음 → 다시 들어가 새 보스를")
    raise CannotProceed(f"{boss}: 세 번 들어갔지만 다른 사람이 먼저 잡아 보상을 못 받음")


def verify(bot: Bot, cfg: dict) -> bool:
    return bool(done(bot))
