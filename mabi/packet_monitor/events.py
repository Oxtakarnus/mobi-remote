"""표가 풀어 준 이벤트(맵 진입·던전·사냥터·드릴·어비스·레이드·대화·변신 …)를 PacketState 에 반영한다.
PacketMonitor 가 상속한다 (self.state · self.spear · self._cond · recent · history 를 쓴다)."""
import logging
import time
from collections import deque

from ..game_state import FIELD_OUT, NOT_IN_DUNGEON
from ..place import ABYSS, FIELD, FIELD_BOSS, OPEN_MAPS, is_instance
from ..spear import MAP_NAME
from .days import KEYS as DAY_KEYS
from .state import CLI_FACTS, Seen, _snapshot

log = logging.getLogger("mabi")

NO_TARGET = 0xFFFFFFFFFFFFFFFF
# 맵의 오브젝트(몬스터·캐릭터)가 사라짐. 이름은 흩어진 물길 투창 패턴에서 처음 써서 붙었다 — 어비스 같은 판 사람의 나감에도 쓴다
OBJECT_GONE = "spear.gone"
# 빠른 이동(T)이 되는 FastTravelAvailableState — Restricted* 는 갈 곳이 제한될 뿐 T 는 된다
# (2026-11-16 필드 보스 이동: 내내 RestrictedByBattleZone 이었고 화면에선 T 가 됐다). Disabled* · None 은 안 된다
FAST_TRAVEL_USABLE = ("Enabled", "RestrictedByBattlefieldEntrance", "RestrictedByBattlefieldExit", "RestrictedByBattleZone")


KEY_KEEP = 64  # 이벤트 종류마다 기억하는 최근 개수 (PacketMonitor.by_key)
ATE_GAP = 1.0  # 아이템 사용 답 뒤 이 안(초)에 온 포만감이면 내가 먹은 것 — 실측 같은 때(ms) 온다


class Events:
    """이벤트 → 상태. 상태를 고치는 일은 모두 잠금(self._cond) 안에서."""

    def apply(self, key: str, vals: dict) -> None:
        """상태를 고치는 일은 모두 잠금 안에서 — 패킷 받는 스레드(apply)와 작업 스레드(merge_cli·reconcile·forget)가
        같은 상태를 고친다. 자세한 것은 _apply."""
        with self._cond:
            was = self.state.char_id
            self._apply(key, vals)
            self._remember(key, vals, was)

    def _remember(self, key: str, vals: dict, was_char: int | None = None) -> None:
        """우리 판단에 쓰는 이벤트(days.KEYS)만 하루 기록에 남긴다. 잠금 안에서 부른다 (_apply 뒤라 char_id 가 새 값).
        접속한 캐릭터(char.personal_data)는 맵을 옮길 때마다 오므로 캐릭터가 바뀌었거나 로그아웃 뒤 처음 온 때만 남긴다 —
        같은 캐릭터로 다시 접속한 것(게임을 다시 켬 등)도 '접속' 으로 남는다 (점검 2026-11-22)."""
        if key == "session.logout_ok":
            self._relogin = True
        if key not in DAY_KEYS:
            return
        if key == "char.personal_data":
            if self.state.char_id == was_char and not self._relogin:
                return
            self._relogin = False
        self.days.record(key, vals, self.state.char_id, name=self.state.my_name)

    def _who(self, char: int | None) -> str:
        """로그용 캐릭터 번호 — '나' 또는 번호 끝 네 자리 (파티장이 같은 사람인지 줄끼리 맞춰 볼 수 있게)."""
        if char is None:
            return "?"
        return "나" if char == self.state.char_id else f"…{char & 0xFFFF:04x}"

    def _end_dialogue(self) -> None:
        """대화가 끝남 (끝 패킷·맵 옮김·로그아웃) — 대화 칸을 처음 값으로, 아직 덩어리를 못 만난 선택지 알림도 버린다."""
        self.state.end_dialogue()
        self._prompt = None

    def _dialogue_node(self, s, vals: dict) -> None:
        """대화 덩어리 하나가 옴 — 덩어리 칸을 한꺼번에 바꾼다. 쪽 수는 대사 묶음의 쪽 경계(Next) + 1.
        이 덩어리의 선택지 알림을 못 받았으면 메뉴는 모름(None) — 지난 덩어리 메뉴가 남지 않게."""
        step = vals.get("step") or s.dialogue_step
        breaks = vals.get("breaks")
        s.dialogue_action, s.dialogue_step = vals.get("action") or "", step
        s.dialogue_pages = breaks + 1 if isinstance(breaks, int) else None
        s.dialogue_why = tuple(vals.get("why") or ())
        s.changed_at["dialogue"] = time.monotonic()
        prompt, self._prompt = self._prompt, None
        if prompt is not None and prompt.get("step") == step:
            self._apply_prompt(s, prompt)
        else:
            s.dialogue_menu, s.dialogue_type, s.dialogue_choices = None, None, None

    @staticmethod
    def _apply_prompt(s, vals: dict) -> None:
        # 메뉴 버튼은 선택지가 있을 때만 뜬다. 대사 종류(type)만 보면 문게이트 정찰 결과 보고 뒤 대사(종류 3 '퀘스트 목표
        # 달성', 선택지 0 — 눌러서 넘기는 대사)도 메뉴로 읽어, 버튼만 기다리며 ESC 를 13분 눌렀다 (2026-11-22 07:53~08:06)
        s.dialogue_menu = bool(vals.get("choices"))
        s.dialogue_type = vals.get("type")
        labels = vals.get("labels")
        s.dialogue_choices = tuple(labels) if labels is not None and len(labels) == vals.get("choices") else None

    def _apply(self, key: str, vals: dict) -> None:
        """이벤트 하나를 상태에 반영하고 기다리는 쪽을 깨운다. 잠금(self._cond) 안에서 부른다 (apply)."""
        s = self.state
        old = {f: getattr(s, f) for f in CLI_FACTS}
        if key == "channel.leaving":
            s.loading, s.loading_at = True, time.monotonic()
            s.dye_open_at, s.dye_known = None, True
            s.attendance_at = 0.0
        elif key == "channel.entering":
            s.loading = False
            s.channel, s.channel_type, s.channel_name = vals.get("channel"), vals.get("channel_type", ""), \
                vals.get("channel_name", "")
            s.entered_at = time.monotonic()
            s.in_game = True  # 감시를 켠 뒤 처음 맵을 옮긴 경우에도 알게
            s.cutscene = False
            s.fast_travel_ok = None  # 새 맵 — 빠른 이동 가능 여부는 다음 자동 이동 때 다시 온다
            # 우연한 만남 매칭(ChanceMeetingGlobalMatching)은 레이드도 같이 쓴다 — 어비스 맵에서만 지우면 레이드 매칭으로
            # 출항선에 들어간 뒤에도 '잡힘' 이 남아, 다음 어비스 반복이 '매칭 중' 으로 보고 오지 않을 입장을 기다렸다
            # (2026-11-07 17:32). 콘텐츠 맵(Instance*)에 들어갔거나 잡힌(3) 뒤 맵을 옮겼으면 매칭은 끝났다.
            # 찾는 중(1·2)에 필드를 옮겨 다니는 것은 매칭이 이어진다
            if is_instance(s.channel_type) or s.abyss_matching == 3:
                s.abyss_matching = 0
            s.abyss_result = 0  # 새 맵 — 지난 판 결과는 끝났다 (나갈 때 0 이 오는지 실측이 없어 여기서도 지운다)
            s.raid_result, s.raid_boss, s.campfire, s.boss_scene = 0, False, False, False
            s.drill_result = 0
            s.transform_start, s.transformed_here = 0.0, False
            # 맵을 나가면(클리어 뒤 다시 하기·나가기) 궁극기·팔라딘 게이지가 처음으로 (사용자). 새 값이 오기 전에 지난 판 값을 믿지 않게
            if s.ult is not None:
                s.ult = s.pal = 0.0
            s.dead, s.dead_src = None, ""  # 쓰러진 채 맵을 옮기면 부활 신호가 안 올 수 있다 → 다시 쓰러질 때까지 CLI 로
            # 마을·사냥터면 던전 밖이다. 던전을 나가는 패킷(NotInDungeon)을 놓치면 지난밤 'Cleared' 가 남아,
            # 아침에 접속 단계가 메인 화면을 던전 클리어 화면으로 알고 6명 모두 3분씩 헛돌았다 (2026-10-30 06:44)
            if s.channel_type in OPEN_MAPS:
                s.dungeon_state = NOT_IN_DUNGEON
            # 마을·집·이야기 필드면 사냥터 밖이다 — 다른 캐릭터로 들어오면 앞 캐릭터의 사냥터 상태가 남아 CLI 가 몇 초 뒤에야
            # 바로잡았다 (2026-11-16·11-20). 검은 구멍·심층 던전·보스 영역은 사냥터 안에서 들어가 그 상태가 이어진다
            if s.channel_type and s.channel_type not in (FIELD, FIELD_BOSS) and not is_instance(s.channel_type):
                s.field_state = FIELD_OUT
            # 대화는 맵을 옮기면 끝난다 — 끝 패킷 없이 끊긴 대화가 '대화 중' 으로 남아 끼어들기·정리가 헛돌지 않게
            self._end_dialogue()
            s.party_marks = {}  # 입장 진행은 맵을 옮기면 끝났다 (끝 알림을 놓쳤어도)
            s.others = {}  # 같은 판 사람은 맵마다 새로
            self.spear.reset(s.channel_type == ABYSS and MAP_NAME in (s.channel_name or ""))
            log.info("패킷: 맵 진입 %s (%s)", s.channel_name or s.channel, s.channel_type or "?")
        elif key == "session.logout_ok":  # 캐릭터 선택 화면으로 (me1 03:29:30 — 맵 떠남·세션 정리와 같은 때)
            s.in_game, s.loading = False, False
            s.me = s.my_name = None
            s.dungeon_state = s.field_state = None  # 다음 캐릭터의 던전·사냥터는 맵 진입·CLI 로 다시 안다
            s.drill_best = None  # 다음에 접속하는 캐릭터의 기록은 맵 진입 때 새로 온다
            s.dimensions_cleared = None  # 검은 구멍 깬 목록도 캐릭터마다 다르다 — 앞 캐릭터 것으로 '완료' 라 보지 않게
            s.attendance_at = 0.0
            self._end_dialogue()
            log.info("패킷: 로그아웃 → 캐릭터 선택 화면")
        elif key == "session.entered":  # 게임 서버 입장 (접속·서버 옮김). 맵 진입은 몇 초 뒤
            if s.in_game is False:
                s.loading, s.loading_at = True, time.monotonic()
            s.in_game = True
        elif key == "daily.attendance_start":
            s.attendance_at = time.monotonic()
            log.info("패킷: 출석 대화 시작")
        elif key == "dungeon.state":
            s.dungeon_state = vals.get("state_name")
            log.info("패킷: 던전 상태 %s", s.dungeon_state)
        elif key == "abyss.result":
            s.abyss_result = vals.get("abyss") or 0
            if s.abyss_result:
                s.others = {}  # 판이 끝남 — 그 뒤에 나가는 것(보상 받고 나가기)은 판 도중 나감이 아니다
        elif key == "raid.state":
            s.raid_state = vals.get("state_name")
            log.info("패킷: 레이드 상태 %s", s.raid_state)
        elif key == "raid.result":
            s.raid_result = vals.get("raid") or 0
            log.info("패킷: 레이드 결과 옴")
        elif key == "drill.best":
            # 직업마다 기록이 따로 있다 — 표는 첫 기록만 읽는다 (기록이 여럿이면 어느 직업 것인지 몰라 드릴 숙제가 창으로도 본다)
            s.drill_best = (vals.get("zone") or 0) if vals.get("count") else 0
            s.drill_records = vals.get("count") or 0
        elif key == "drill.enter":
            s.drill_result = 0
        elif key == "drill.result":
            s.drill_result = vals.get("zone") or 0
            log.info("패킷: 나이트메어 드릴 %s구역 클리어", s.drill_result)
        elif key == "raid.boss_begin":
            s.raid_boss = True
            log.info("패킷: 레이드 보스전 시작")
        elif key == "abyss.campfire":
            s.campfire = True
        elif key == "ultimate.resource":
            s.ult, s.ult_max, s.pal, s.pal_max = vals.get("ult"), vals.get("ult_max"), vals.get("pal"), vals.get("pal_max")
        elif key == "ultimate.can_paladin":
            s.can_paladin = bool(vals.get("on"))
        elif key == "transfigure.current":
            # 파티원 변신은 뺀다. 내 번호를 모르면(판 도중에 리모콘을 켬) 내 것으로 본다 — 변신 중에 6(변신 해제)을
            # 누르지 않는 쪽이 안전하다
            if s.me is None or vals.get("actor") == s.me & 0xFFFFFFFF:
                now = s.transform_seen = time.monotonic()
                if s.transform_start and now - s.transform_start < 30:  # 변신 중에 또 옴 = 끝
                    s.transform_start = 0.0
                    log.info("패킷: 변신 끝")
                else:
                    s.transform_start, s.transformed_here = now, True
                    log.info("패킷: 변신 시작")
        elif key == "abyss.matching_update":
            s.abyss_matching = vals.get("state") or 0
            s.changed_at["abyss_matching"] = time.monotonic()
        elif key == "abyss.matching_cancel_ok":
            s.abyss_matching = 0
        elif key == "party.info":
            # 파티를 만들거나 들어갈 때·서버를 옮길 때마다 온다. 우연한 만남(전 서버 매칭)이면 게임이 파티를 풀었다 다시
            # 만드는 것으로 보여 (사용자 11-23 테스터 제보) 번호·파티장이 바뀔 때마다 남긴다 — 다음에 깨지면 순서를 알게
            had, had_leader = s.party_id, s.party_leader
            s.party_id = vals.get("party") or 0
            s.party_leader = vals.get("leader") if s.party_id else None
            size = vals.get("size") if s.party_id else 0
            if s.party_id and (s.party_id != had or s.party_leader != had_leader):
                log.info("패킷: 파티 정보 — 번호 끝 %04x · 파티장 %s · %s명", s.party_id & 0xFFFF, self._who(s.party_leader),
                         size if size is not None else "?")
            elif s.party_id and size is not None and size != s.party_size:
                log.info("패킷: 파티 %d명", size)
            if (s.party_id, s.party_leader, size) != (had, had_leader, s.party_size):
                s.party_at = time.monotonic()
            s.party_size = size
            if not s.party_id:
                s.party_marks = {}
                if had:
                    # 나가기, 어비스에서 혼자 먼저 나옴(나감 알림 없이 이것만 — party-1120b 20:05:33), 우연한 만남으로 풀림
                    log.info("패킷: 파티가 없어짐")
        elif key == "party.member_add":
            if s.party_size is not None:
                s.party_size += 1
            s.party_at = time.monotonic()
            log.info("패킷: 파티원이 들어옴 (%s명)", s.party_size if s.party_size is not None else "?")
        elif key == "party.member_out":
            # 파티원이 빠져도 고정 파티는 남은 인원으로 계속 돈다 (사용자 11-22). 파티장이 나가면 party.leader 가 먼저 온다
            if s.party_size:
                s.party_size -= 1
            s.party_at = time.monotonic()
            log.info("패킷: 파티원이 파티에서 나감 (%s명)", s.party_size if s.party_size is not None else "?")
        elif key == "party.left":
            s.party_size = 0
            s.party_at = time.monotonic()
            log.info("패킷: 내가 파티에서 나감")
        elif key in ("party.restore", "party.restore_data"):
            # 우연한 만남(전 서버 매칭) 뒤 원래 파티를 되살리는 것으로 보이는 이름 — 아직 받아 본 적 없다. 고정 파티로 우연한
            # 만남을 돌 때 오는지 보려고 남긴다 (사용자 2026-11-22 고정 파티 우연한 만남)
            log.info("패킷: 우연한 만남 파티 복구 신호 %s %s", key, vals or "")
        elif key == "party.leader":
            # 넘김, 또는 파티장이 나감 (빠짐보다 먼저 같은 ms 에 온다 — party-1120b 20:06:11). 고정 파티 판단은 tasks.party.Watch
            if vals.get("leader") != s.party_leader:
                s.party_at = time.monotonic()
            s.party_leader = vals.get("leader")
            log.info("패킷: 파티장 바뀜 (%s)", self._who(s.party_leader))
        elif key == "party.play":
            # 단계 2 만 본다 — 같은 때 단계 0 짜리가 하나 더 와서 단계 0 으로는 끝을 알 수 없다 (끝은 party.enter_end)
            ids, marks = vals.get("ids") or [], vals.get("marks") or []
            if vals.get("stage") == 2 and ids and len(ids) == len(marks):
                if not s.party_marks:
                    s.party_enter_at = time.monotonic()
                    log.info("패킷: 파티 입장 준비 시작 (%d명)", len(ids))
                s.party_marks = dict(zip(ids, marks))
        elif key == "party.ready_ok":
            if s.char_id in s.party_marks:
                s.party_marks = {**s.party_marks, s.char_id: s.PARTY_READY}
            log.info("패킷: 파티 입장 준비 누름")
        elif key == "party.enter_end":
            s.party_end, s.party_end_at = vals.get("code") or 0, time.monotonic()
            s.party_marks = {}
            log.info("패킷: 파티 입장 진행 끝 (%s)", {3: "입장", 4: "취소"}.get(s.party_end, s.party_end))
        elif key == "field.context":
            s.field_state = vals.get("state_name")
            log.info("패킷: 사냥터 상태 %s", s.field_state)
        elif key == "dungeon.current":
            s.dungeon = vals.get("channel") or None
        elif key == "dungeon.boss_battle":
            s.boss_battle = bool(vals.get("on"))
        elif key == "dialogue.target":
            t = vals.get("target")
            s.dialogue_npc = None if t in (None, NO_TARGET) else t
        elif key in ("dialogue.cleared", "dialogue.force_end") or key == "dialogue.update" and vals.get("active") is False:
            self._end_dialogue()
        elif key == "dialogue.update":
            self._dialogue_node(s, vals)
        elif key == "dialogue.prompt":
            # 선택지 알림은 늘 그 덩어리의 대사 진행 바로 앞에 온다 (11-05·11-15·11-20 캡처 모두) — 덩어리가 오면 같이 반영한다.
            # 덩어리가 먼저 와 있으면(순서가 바뀐 때) 바로
            if s.dialogue_menu is None and vals.get("step") == s.dialogue_step:
                self._apply_prompt(s, vals)
            else:
                self._prompt = vals
        elif key == "char.personal_data":
            if vals.get("char_id") != s.char_id:  # 다른 캐릭터로 접속 — 맵에 들어가야 새 번호·이름을 안다
                s.me = s.my_name = None
                s.durability = None
                s.recommend = None  # 앞 캐릭터의 추천 항목 (요일 던전 '안 함' 판단)이 남지 않게
                s.dimensions_cleared = None  # 앞 캐릭터의 검은 구멍 깬 목록 (점검 2026-11-22)
                s.dungeon_state = s.field_state = None  # 앞 캐릭터의 던전·사냥터 상태
            s.char_id = vals.get("char_id")
        elif key == "char.appearing":
            if vals.get("mine"):
                if vals.get("actor") != s.me:
                    # 내 번호는 맵에 들어올 때만 바뀐다. 이미 이 맵에서 정했으면 다른 오브젝트의 등장에도 내 고유 번호가
                    # 들어 있는 것 — 무시한다 (11-03 21:36 이멘 마하: 들어온 11초 뒤 다른 캐릭터를 '나' 로 바꿨다.
                    # CLI 칭호·직업은 처음 캐릭터). 바꾸면 '나' 판단(투창·틱택토·변신·쓰러짐)이 틀어진다
                    if s.me is not None and s.entered_at and s.me_map == s.entered_at:
                        log.warning("패킷: 이 맵에서 정한 내 번호 %s 를 두고 다른 등장(%s, %s)에도 내 고유 번호가 있음 → 무시",
                                    s.me, vals.get("actor"), vals.get("name") or "?")
                        return
                    s.combat = "NonCombat"  # 맵에 막 들어옴 — 싸우는 중이면 곧 전투 상태가 온다
                s.me, s.me_map = vals.get("actor"), s.entered_at
                s.my_name = vals.get("name") or s.my_name
                log.info("패킷: 내 캐릭터 %s (번호 %s)", s.my_name or "?", s.me)
            elif s.channel_type == ABYSS and not s.abyss_result and vals.get("actor") not in (None, s.me):
                s.others[vals["actor"]] = time.monotonic()  # 같이 하는 사람 — 결과 전에 사라지면 나간 것
        elif key == OBJECT_GONE:
            # 감시(PacketMonitor._handle)는 같은 판 사람의 사라짐만 넘긴다 — 몬스터 사라짐은 투창 패턴만 쓴다
            if s.others.pop(vals.get("actor"), None) is not None:
                s.other_out_at = time.monotonic()
                log.info("패킷: 같은 판의 다른 캐릭터가 결과 전에 사라짐 → 나감으로 봄 (남은 %d명)", len(s.others))
        elif key == "actor.dead":
            if self.spear.active:
                self._spear(key, vals)  # 흩어진 물길 주술사가 모두 쓰러지면 투창 패턴 끝
            if s.me is not None and vals.get("actor") == s.me:  # 파티 판에서는 부활 창 신호가 안 온다 (death1 03:10:24)
                s.dead, s.dead_src = bool(vals.get("dead")), "actor"
                if s.dead:
                    s.dead_at = time.monotonic()
                log.info("패킷: 내 캐릭터 %s", "쓰러짐" if s.dead else "일어남")
        elif key == "revive.availability":
            was = s.dead
            if vals.get("available"):
                s.dead, s.dead_src, s.dead_at = True, "revive", time.monotonic()
            elif not (was and s.dead_src == "actor"):
                s.dead = False
            # 파티 판은 부활 창이 없어 쓰러짐 알림 바로 뒤 0 이 온다 — 그것으로 풀면 쓰러짐이 5~8초 늦게 CLI 로 다시 잡혔다
            # (11월 로그 16번 중 15번, 점검 2026-11-22). 쓰러짐 알림으로 쓰러진 것은 일어남 알림·부활 응답·CLI 로 푼다
            if s.dead != was and (s.dead or was):  # 맵에 들어갈 때마다 0 이 오므로 쓰러져 있다가 풀릴 때만 '부활'로 남긴다
                log.info("패킷: %s", "쓰러짐" if s.dead else "부활")
        elif key == "dimension.cleared":
            s.dimensions_cleared = vals.get("times")
        elif key in ("dye.open", "dye.start"):
            s.dye_open_at, s.dye_known = time.monotonic(), True
        elif key in ("dye.finish", "dye.cancel", "dye.abort", "dye.cancel_free"):
            s.dye_open_at, s.dye_known = None, True
        elif key == "recommend.add":
            s.recommend = vals.get("type")
        elif key == "revive.count":
            s.revives_used, s.revives_max = vals.get("used"), vals.get("max")
        elif key in ("revive.checkpoint_ok", "revive.item_ok"):
            s.dead, s.dead_src = False, "revive"
        elif key == "cutscene.play":
            s.cutscene = True
            s.changed_at["cutscene"] = time.monotonic()
            if s.campfire or not s.entered_at:
                s.boss_scene = True
        elif key in ("cutscene.end", "cutscene.abort"):
            s.cutscene = False
        elif key == "travel.begin":
            s.traveling, s.travel_points, s.travel_index = True, vals.get("points") or 0, 0
        elif key == "travel.target":
            s.travel_index = vals.get("index") or 0
        elif key == "travel.end":
            s.traveling, s.fast_travel_ok = False, False
        elif key == "fast_travel.state":
            s.fast_travel_ok = vals.get("available_name") in FAST_TRAVEL_USABLE
        elif key == "actor.combat_state":
            if s.me is not None and vals.get("actor") == s.me:
                s.combat = vals.get("state_name")
        elif key == "char.ai":
            s.ai = vals.get("ai", "")
        elif key == "char.satiety":
            # 함께하기에선 다른 캐릭터의 포만감도 온다 — 예전엔 이걸로 내 번호를 덮어써, 투창 대상·틱택토 O 담당이
            # 나인데도 '다른 캐릭터'로 봤다 (2026-11-03 16:05·16:10). 내 번호를 모를 때도 내가 먹은 답(item.use_ok)이
            # 바로 앞에 왔을 때만 내 것으로 본다 — 남의 것이 먹은 답 없이 온다 (캡처 board1·arbeit1·party-1120, 점검 2026-11-22)
            a = vals.get("actor")
            used = self.by_key.get("item.use_ok")
            ate = bool(used) and time.monotonic() - used[-1].at < ATE_GAP
            if a is None or a == s.me or (s.me is None and ate):
                s.satiety = vals.get("satiety")
                s.me = s.me if a is None else a
        elif key == "equip.durability":
            r = vals.get("ratio")
            if r is not None:
                s.durability = r if s.durability is None else min(s.durability, r)
        elif key == "equip.repair_ok":
            s.durability = None
            log.info("패킷: 장비 수리됨")
        elif key == "char.weight":
            s.weight = vals.get("weight")
        elif key == "char.max_weight":
            s.max_weight = vals.get("max_weight")
        now = time.monotonic()
        for f, v in old.items():
            if getattr(s, f) != v:
                s.changed_at[f] = now
        self._seq += 1
        seen = Seen(self._seq, time.monotonic(), key, vals)
        self.recent.append(seen)
        q = self.by_key.get(key)
        if q is None:
            q = self.by_key[key] = deque(maxlen=KEY_KEEP)
        q.append(seen)
        if not self.history or self.history[-1][1] != s:
            self.history.append((self._seq, _snapshot(s)))
        self._cond.notify_all()
