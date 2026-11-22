"""고정 파티 어비스·레이드 (사용자 11-20, 녹화 party-1120b).

파티장: 입장 창 함께하기 탭 → 우연한 만남 끔 → 입장하기(Space) → 인원이 모자라면 '어비스에 도전하시겠습니까?' 창에서
도전하기(Space) → 오른쪽 파티 창(준비 UI)이 뜨고 파티장은 이미 준비 끝 → 파티원이 모두 준비하면 저절로 입장.
클리어 뒤 '다시 하기'(Space)도 같은 준비 UI 로 이어지고, 인원이 모자라면 같은 확인 창이 또 뜬다.
파티원: 파티장이 입장을 시작하면 같은 준비 UI 가 뜨고 아래 버튼이 '준비 완료'(Space) — 누르면 '준비 취소' 로 바뀐다.
클리어 화면 아래는 '나가기' 와 '파티장 선택 대기' — 파티장이 다시 하기를 누르면 또 준비 UI 가 뜬다.
파티가 FULL 명이 안 되면 (사용자 11-22): 파티장은 우연한 만남을 켜고 입장해 빈자리를 채운다 (준비 UI 없음). 판이 끝나면
다시 하기 대신 '다른 던전 가기' → 어비스 목록에서 같은 어비스 → 우연한 만남 확인 → 입장하기 (abyss.AbyssRepeat.party_chance).
패킷: 입장 진행이 시작되면 파티원 목록과 상태가 온다 (PacketState.party_marks), 끝은 party_end 3 입장 · 4 취소.
"""
import time

from .. import gamedata as gd
from ..bot import Bot
from ..exceptions import CannotProceed
from . import ui_text

ROLES = ("leader", "member")
CONFIRM_LOOK = 2.5  # 입장하기 뒤 '도전하시겠습니까?' 창을 찾는 초 (가득 찬 파티면 안 뜬다)
FULL = 4  # 어비스 파티가 가득 찬 인원 (입장 창 '권장 인원 4명') — 모자라면 파티장이 우연한 만남으로 채운다


def size(packets) -> int | None:
    """패킷: 내 파티 인원 (나 포함). 감시가 없거나 리모콘을 켠 뒤 파티 정보가 아직 안 왔으면 None, 파티가 없으면 0.
    파티 정보는 파티를 맺거나 맵(서버)을 옮길 때마다 온다 — 어비스에 들어가면 온다 (party-1120b)."""
    if not packets.ok:
        return None
    s = packets.state
    if s.party_id is None:
        return None
    return s.party_size if s.party_id else 0


def confirm(bot: Bot) -> bool:
    """'어비스에 도전하시겠습니까? 권장 인원보다 적은 인원으로…' 창이 뜨면 도전하기(Space). 눌렀으면 True.
    패킷으로 입장 진행·우연한 만남 매칭이 이미 시작됐으면 창이 없는 것이라 보지 않는다."""
    end = time.monotonic() + CONFIRM_LOOK
    while time.monotonic() < end:
        s = bot.packets.state
        if bot.packets.ok and (s.party_marks or s.loading or s.matching):
            return False
        if ui_text.find(bot, gd.text("party_challenge"), gd.region("abyss_popup"), exact=False):
            bot.key("space")
            bot.log.info("권장 인원보다 적은 파티 → 도전하기")
            bot.sleep(0.8, 1.2)
            return True
        bot.sleep(0.4, 0.6)
    return False


def broken(s, since: float) -> bool:
    """패킷: since 뒤에 파티에서 누가 빠졌나 (파티원이 나감·내가 나감), 또는 지금 파티가 없나.
    파티 정보가 아직 안 왔으면(party_id None) 모른다 → False."""
    return s.party_out_at > since or s.party_id == 0


def started(s) -> bool:
    """패킷: 파티 입장 진행이 시작됐나 (준비 UI) 또는 이미 맵을 옮기는 중."""
    return bool(s.party_marks) or s.loading


def cancelled(s, since: float) -> bool:
    """패킷: since 뒤에 시작한 입장 진행이 취소로 끝났나 (파티원이 준비를 취소·거절 등). 입장 진행 전의 취소(파티장이
    입구 창을 열고 닫을 때 잠깐 오는 것)는 세지 않는다."""
    return s.party_end == 4 and s.party_end_at > s.party_enter_at > since


def ready_button(bot: Bot) -> bool:
    """화면: 파티 준비 UI 아래 버튼이 '준비 완료' 인가 (파티원이 아직 준비 안 함). 준비 뒤엔 '준비 취소'."""
    return ui_text.find(bot, gd.text("party_ready"), gd.region("party_ready_button"), exact=False) is not None


def entering(s) -> bool:
    """패킷: 내가 준비를 마쳤거나 이미 입장 중."""
    return s.party_mark() == s.PARTY_READY or s.loading


def wait_ready(bot: Bot, timeout: float, abort=None) -> bool:
    """파티원: 파티장이 입장을 시작해 준비 UI 가 뜨길 기다렸다가 '준비 완료'(Space). 내 준비가 끝나면(패킷 0x0b 또는
    버튼이 '준비 취소' 로 바뀜) 돌아간다 — 그 뒤 입장은 부르는 쪽이 기다린다. 신호: 패킷에서 내 상태 1(준비 창 뜸)
    또는 화면의 '준비 완료' 버튼 (패킷이 없는 PC 도 된다). timeout 안에 파티장이 시작하지 않으면 CannotProceed.
    abort() 가 참이 되면(파티가 깨짐) 준비하지 않고 False. 준비했으면 True."""
    end = time.monotonic() + timeout
    pressed = 0
    told = False
    while True:
        p = bot.packets
        s = p.state if p.ok else None
        if abort and abort():
            return False
        if s is not None and entering(s):
            return True
        mark = s.party_mark() if s is not None else None
        button = ready_button(bot)
        if pressed and not button and (s is None or mark != 1):
            return True  # 눌렀고 버튼이 바뀜 (패킷이 없거나 이미 넘어감)
        if mark == 1 or button:
            if pressed >= 5:
                raise CannotProceed(f"준비 완료를 {pressed}번 눌러도 준비가 안 됨 → {bot.snapshot('party_ready').name}")
            bot.key("space")
            pressed += 1
            bot.log.info("파티 준비 UI → 준비 완료 (Space)")
            if bot.wait_packet(entering, 3, since=bot.input_mark):
                return True
            continue
        if not told:
            bot.log.info("파티장이 입장을 시작하길 기다림 (준비 UI 가 뜨면 준비 완료)")
            told = True
        if time.monotonic() > end:
            raise CannotProceed(f"파티장이 {timeout / 60:.0f}분 안에 입장을 시작하지 않음")
        if p.ok:
            p.changed(2)
        bot.sleep(0.8, 1.2)
