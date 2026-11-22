"""고정 파티 어비스·레이드 (사용자 11-20, 녹화 party-1120b).

파티장: 입장 창 함께하기 탭 → 우연한 만남 끔 → 입장하기(Space) → 인원이 모자라면 '어비스에 도전하시겠습니까?' 창에서
도전하기(Space) → 오른쪽 파티 창(준비 UI)이 뜨고 파티장은 이미 준비 끝 → 파티원이 모두 준비하면 저절로 입장.
클리어 뒤 '다시 하기'(Space)도 같은 준비 UI 로 이어지고, 인원이 모자라면 같은 확인 창이 또 뜬다.
파티원: 파티장이 입장을 시작하면 같은 준비 UI 가 뜨고 아래 버튼이 '준비 완료'(Space) — 누르면 '준비 취소' 로 바뀐다.
클리어 화면 아래는 '나가기' 와 '파티장 선택 대기' — 파티장이 다시 하기를 누르면 또 준비 UI 가 뜬다.
파티가 FULL 명이 안 되면 (사용자 11-22): 파티장은 우연한 만남을 켜고 입장해 빈자리를 채운다 (준비 UI 없음). 판이 끝나면
다시 하기 대신 '다른 던전 가기' → 어비스 목록에서 같은 어비스 → 우연한 만남 확인 → 입장하기 (abyss.AbyssRepeat.party_chance).
누가 빠지면 (사용자 11-22): 파티원이면 남은 인원으로 계속, 파티장이 바뀌거나 내가 파티에서 빠지면 카드를 끝낸다 (Watch).
패킷: 입장 진행이 시작되면 파티원 목록과 상태가 온다 (PacketState.party_marks), 끝은 party_end 3 입장 · 4 취소.
"""
import time

from .. import gamedata as gd
from ..bot import Bot
from ..exceptions import CannotProceed
from ..place import OPEN_MAPS
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


# 파티가 마지막으로 바뀐 뒤(party_at) 이만큼 지나도 우리 파티가 아니어야 깨진 것으로 본다 — 매칭이 잡힌 뒤 맵 로딩이
# 시작되기 전에 파티가 풀려도 (파티원은 매칭 신호를 못 받을 수도 있다) 로딩까지 넉넉히
GRACE = 20.0
# 우연한 만남 판 뒤 어비스 밖(마을·필드)으로 나와 우리 파티가 돌아오길 기다리는 상한 (초). 파티장이 쓰러져 먼저 나오면
# 파티원은 아직 판 안일 수 있어 넉넉히
RESTORE_WAIT = 300.0
GATHER_WAIT = 60.0  # 우리 파티가 돌아온 뒤 판 전 인원이 다 모이길 기다리는 상한 (초) — 넘으면 빠진 것으로 보고 지금 인원으로


class Watch:
    """고정 파티 카드 하나가 지켜보는 파티 — 이어 갈 수 없게 됐나를 이벤트 한 번이 아니라 지금 상태로 판단한다.

    우리 파티(ours): 파티장 카드면 내가 파티장인 파티, 파티원 카드면 처음 본 파티장(사람 고유 번호 — 파티 번호가 아님)이
    파티장인 파티. 파티 번호를 기준으로 삼지 않는 까닭: 우연한 만남(전 서버 매칭)에 들어가면 게임이 파티를 풀었다가 어비스
    밖에서 다시 만드는 것으로 보인다 (게임 메타데이터에 우연한 만남 뒤 파티를 되살리는 메시지가 있고, 결과에 '만들기 실패'·
    '들어가기 실패'가 따로 있다). 이벤트 한 번(파티 없어짐·파티장 바뀜)으로 끝내던 예전엔 그때마다 카드가 끝났다 (사용자 11-23 테스터 제보).
    - 맵 로딩·매칭 중엔 판단하지 않는다.
    - 매칭이 보이면 우연한 만남 판 — 파티끼리 입장은 준비 UI 뿐이고 매칭 패킷이 없다 (party-1120b). 매칭을 못 봤어도 판
      안에서 파티 번호가 바뀌면(풀림·새 파티) 같은 것으로 본다. 그때부터 '나가 있음': 어비스 안에선 같은 번호의 우리 파티,
      어비스 밖에선 번호가 바뀌었어도 우리 파티가 보이면 돌아온 것. 어비스 밖으로 나온 뒤 RESTORE_WAIT 초 안에 안 돌아오면
      깨짐.
    - 그 밖엔 파티가 바뀐 지 GRACE 초가 지나도 우리 파티가 아니면 깨짐 — 파티원 카드는 파티장이 바뀌거나, 파티장 카드는
      내가 파티장이 아니게 되거나, 파티가 없으면 (사용자 11-22 '파티원이 빠지면 계속, 파티장이 빠지면 끝').
    파티 모양과 판단이 바뀔 때마다 로그를 남긴다 — 테스터 로그만으로 게임이 파티를 어떤 순서로 바꿨는지 알 수 있게."""

    def __init__(self, role: str, s=None, log=None):
        self.role, self.log = role, log
        self.leader: int | None = None  # 기억한 파티장 고유 번호 (파티장 카드는 나)
        self.fixed: int | None = None   # 우리 파티 번호 — 마지막으로 나가 있지 않을 때 본 것 (판 뒤 그대로인가: replaced)
        self.size: int | None = None    # 그때 인원
        self.round_size: int | None = None  # 우연한 만남 판에 나가기 전 인원 — 판 뒤 다 모였나 (gathered)
        self.matched = s.changed_at.get("abyss_matching", 0.0) if s is not None else 0.0  # 마지막으로 본 매칭 신호
        self.away = 0.0   # 우연한 만남 판으로 나간 때 (0 = 아님)
        self.back = 0.0   # 그 뒤 어비스 밖으로 나온 때
        self.told = ""    # 마지막으로 남긴 '우리 파티가 아님' 모양 (같은 말을 되풀이하지 않게)
        self.shape = None
        if s is not None and (s.matching or (s.channel_type and s.channel_type not in OPEN_MAPS)):
            # 매칭 중·콘텐츠 안에서 시작함 (리모콘을 판 도중에 켬) — 우연한 만남 판인지 몰라 어비스 밖으로 나올 때까지 미룬다
            self.away = time.monotonic()

    def _say(self, msg: str) -> None:
        if self.log:
            self.log.info(f"고정 파티: {msg}")

    def describe(self, s) -> str:
        if s.party_id is None:
            return "파티 정보 모름"
        if not s.party_id:
            return "파티 없음"
        lead = s.party_leader
        who = ("?" if lead is None else "나" if lead == s.char_id else "기억한 파티장" if lead == self.leader
               else f"다른 사람(…{lead & 0xFFFF:04x})")
        return f"번호 끝 {s.party_id & 0xFFFF:04x} · 파티장 {who} · {s.party_size if s.party_size is not None else '?'}명"

    def ours(self, s) -> bool | None:
        """지금 파티가 이 카드의 고정 파티인가. 모르면 None (파티 정보·내 번호·기억한 파티장이 아직 없음)."""
        if s.party_id is None:
            return None
        if not s.party_id:
            return False
        if self.role == "leader":
            return None if s.char_id is None else s.party_leader == s.char_id
        return None if self.leader is None else s.party_leader == self.leader

    def note(self, s, now: float) -> None:
        """패킷 상태로 기억을 고친다 — 매칭(우연한 만남)을 봤나, 파티장·파티 번호·인원, 모양이 바뀌었으면 로그."""
        m = s.changed_at.get("abyss_matching", 0.0)
        if s.matching or m > self.matched:
            self.matched = max(m, self.matched, now if s.matching else 0.0)
            self._leave(s, now, "매칭 (우연한 만남 판)")
        # 파티장은 나가 있지 않을 때나 어비스 밖에서만 기억한다 (우연한 만남 판 안의 파티는 모르는 사람이 파티장일 수 있다)
        settled = not (s.loading or s.matching) and (not self.away or s.channel_type in OPEN_MAPS)
        if settled and s.party_id and s.party_leader is not None:
            if self.leader is None and (self.role == "leader" or s.party_leader != s.char_id):
                self.leader = s.char_id if self.role == "leader" else s.party_leader
            if not self.away and self.ours(s):
                self.fixed, self.size = s.party_id, s.party_size
        shape = (s.party_id, s.party_leader, s.party_size)
        if shape != self.shape:
            self.shape = shape
            self._say(f"지금 파티 {self.describe(s)}")

    def _leave(self, s, now: float, what: str) -> None:
        """우리 파티를 떠났을 수 있다 (우연한 만남 판) — 파티가 돌아올 때까지 판단을 미룬다."""
        if self.away:
            return
        self.away, self.back, self.round_size = now, 0.0, self.size
        self._say(f"{what} — 게임이 파티를 풀었다 다시 만들 수 있어 파티가 돌아올 때까지 판단을 미룸 (지금 {self.describe(s)})")

    def chance_since(self, t: float) -> bool:
        """t 뒤에 매칭(우연한 만남)을 봤나 — 파티원은 파티장이 우연한 만남으로 들어갔는지 이걸로 안다."""
        return self.matched > t

    def replaced(self, s) -> bool:
        """지금 파티가 판 전 우리 파티가 아닌가 — 파티가 없거나, 번호가 바뀌었거나, 파티장이 우리 파티장이 아님 (우연한
        만남 판 뒤 게임이 파티를 바꿨나). 파티 정보를 모르면 False (예전 흐름대로)."""
        if s.party_id is None:
            return False
        if not s.party_id or (self.fixed is not None and s.party_id != self.fixed):
            return True
        return self.ours(s) is False

    def gathered(self, s) -> bool:
        """우리 파티가 돌아와 우연한 만남 판 전 인원만큼 모였나 (파티장이 그 판 뒤 다음 입장 전에 본다)."""
        n = s.party_size or 0
        return not self.away and self.ours(s) is True and (self.round_size is None or n >= self.round_size)

    def why(self, s, now: float | None = None) -> str:
        """고정 파티를 더 이어 갈 수 없나 — 까닭, 괜찮거나 아직 판단할 때가 아니면 ""."""
        now = time.monotonic() if now is None else now
        self.note(s, now)
        if s.loading or s.matching:
            return ""
        o = self.ours(s)
        home = s.channel_type in OPEN_MAPS
        inside = bool(s.channel_type) and not home
        if self.away:
            # 돌아옴: 어비스 안에선 같은 번호의 우리 파티 (번호를 몰랐으면 우리 파티면), 밖에선 번호가 바뀌었어도 우리 파티
            if o and (s.party_id == self.fixed or home or self.fixed is None):
                what = ("우리 파티 확인" if self.fixed is None else "파티 그대로" if s.party_id == self.fixed
                        else "파티가 돌아옴 (새 번호)")
                self._say(f"{what} — {self.describe(s)}, 떠난 뒤 {now - self.away:.0f}초")
                self.fixed, self.away, self.back, self.told = s.party_id, 0.0, 0.0, ""
                return ""
            if not home:
                return ""  # 아직 어비스 안 (판·보상 화면) — 다시 만든 파티는 밖으로 나와야 보일 수 있다
            if not self.back:
                self.back = now
                self._say(f"어비스 밖 — 파티가 돌아오길 기다림 (상한 {RESTORE_WAIT:.0f}초, 지금 {self.describe(s)})")
            if now - self.back < RESTORE_WAIT:
                return ""
            return f"{self._broken(s)} — 우연한 만남 판 뒤 {RESTORE_WAIT:.0f}초 안에 파티가 돌아오지 않음"
        if o is None or o:
            self.told = ""
            return ""
        if inside and self.fixed is not None and s.party_id != self.fixed:
            # 판 안에서 파티 번호가 바뀜 — 파티원은 파티장이 건 매칭 신호를 못 받을 수도 있어 같은 것으로 본다
            self._leave(s, now, "판 안에서 파티가 바뀜 (우연한 만남 판일 수 있음)")
            return ""
        if now - s.party_at < GRACE:
            if self.told != self.describe(s):
                self.told = self.describe(s)
                self._say(f"우리 파티가 아님 ({self.told}) — 파티가 바뀐 지 {GRACE:.0f}초 지나도 그대로면 끝냄")
            return ""
        return self._broken(s)

    def _broken(self, s) -> str:
        if s.party_id is None:
            return "파티 정보가 오지 않음"
        if not s.party_id:
            return "파티가 없음 (내가 빠짐·파티가 풀림)"
        if self.role == "leader":
            return "내가 파티장이 아님 (파티장이 바뀜)"
        return "파티장이 바뀜 (파티장이 나감·넘김)"


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
