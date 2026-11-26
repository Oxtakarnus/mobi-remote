"""지금 어디인가 — 맵·로딩·던전·사냥터·쓰러짐 같은 '자리' 사실을 한곳에서 정한다.

예전엔 어비스(abyss.inside)·레이드(raid._map)·접속(login._in_field)·던전(content.dungeon_state)이 이 사실들을
저마다 다른 순서·다른 CLI 키로 따로 구했다 (구조 점검 2026-10-30). 이제 모두 place() 를 본다.
각 콘텐츠만의 화면 판단(입장 창·배·목록·보상 화면)은 그 태스크에 둔다.

출처 규칙: 패킷 상태(바뀌는 즉시 알고, CLI 를 물을 때마다 CLI 답으로 맞춰짐 — Bot.activity) → 패킷이 맵을 모르면 CLI.
패킷이 맵을 알아도 CLI 를 같이 물어 맞춘 뒤 본다 (1초 안의 답은 같이 씀) — 패킷만 믿다 흐름이 끊겨 틀린 맵에 머물렀다
(2026-11-03 사용자: 여러 신호를 동시에 보고 우선순위로).
장소 이름은 CLI 의 ChannelDisplayName 하나로 (패킷 맵 이름과는 글자가 다르다: '마스 심층 던전 1층 2구역' /
'마스 3_2 던전 (심층 1층 2구역) 매우 어려움').
"""
from dataclasses import dataclass

from . import gamedata as gd
from .game_state import FIELD_OUT, Activity

# 맵 종류 (패킷 channel_type 이름). 맵 종류 글자는 여기서만 적고 다른 모듈은 이 이름을 쓴다
ABYSS = "InstanceAbyssDungeon"
RAID = "InstanceRaid"
RAID_LOBBY = "InstanceRaidLobby"       # 출항선 (레이드마다 같은 맵)
DUNGEON = "InstanceDungeon"
DRILL = "InstanceBreakthroughDungeon"  # 나이트메어 드릴
DIMENSION = "InstanceDimension"       # 검은 구멍 (사냥터·필드 안에서 들어간다)
INSTANCE = "Instance"                  # 콘텐츠 맵(던전·어비스·레이드·드릴 …) 맵 종류의 머리 — is_instance
FIELD = "BattleField"                  # 사냥터
OPEN_FIELD = "Field"                   # 마을·일반 필드
FIELD_BOSS = "FieldBoss"
SCENARIO_FIELD = "ScenarioField"
# 여관 안쪽 보관함 구역·마이 홈·스텔라 돔 — 사냥터·던전은 아니지만 메인 화면처럼 보이고 오른쪽 위 나가기가 있는 따로 된 구역.
# 여기서 숙제를 시작하면 이동이 안 돼 헤맨다 → 먼저 나온다 (exits.SideAreaExit). 새 구역은 SIDE_AREAS 에 한 줄
HOUSING_INN = "HousingInn"
HOUSING = "Housing"
STELLA_DOME = "StellaDome"   # 2026-11-26 스텔라 돔 안에서 숙제를 시작해 요일·공물 던전 이동이 안 됐다
SIDE_AREAS = (HOUSING_INN, HOUSING, STELLA_DOME)
OPEN_MAPS = (OPEN_FIELD, FIELD, FIELD_BOSS, HOUSING_INN, SCENARIO_FIELD)  # 던전이 아닌 맵 종류
# 맵 종류마다 CLI get_activity 가 답하는 (던전 안, 사냥터 안) — None 은 따지지 않음. 표에 없는 종류는 (None, False).
# 패킷 맵이 CLI 와 어긋나나(packet_monitor.cli_sync.map_contradicts)를 이 표 하나로 본다 — 새 맵 종류는 여기 한 줄.
# 어비스·레이드·드릴은 CLI 가 던전으로 치지 않아 던전 안팎을 보지 않는다. 필드 보스 영역은 사냥터를 거쳐 들어가
# CLI 가 사냥터 안으로 답한다 (2026-11-16 — 어긋남으로 봐 맵을 지우자 전투가 '영역 밖으로 나옴' 으로 끝났다).
# 검은 구멍·심층 던전도 사냥터 안에서 들어가면 CLI 가 사냥터 안으로 답해 사냥터 안팎을 보지 않는다 — 예전엔 들어갈 때마다
# 맵을 지웠다 (11월 로그 검은 구멍 97번·심층 던전 50번, 점검 2026-11-22)
CLI_FLAGS = {
    OPEN_FIELD: (False, False), FIELD: (False, True), FIELD_BOSS: (False, None),
    HOUSING_INN: (False, False), SCENARIO_FIELD: (False, False), DUNGEON: (True, None), DIMENSION: (False, None),
}
INN_SUFFIX = "여관"   # CLI 장소 이름 '반호르 여관' — 여관 보관함 구역에선 CLI Housing.IsInHousing 이 false (2026-10-31 실측)


def on_map(bot, kind: str) -> bool | None:
    """패킷이 아는 지금 맵이 kind 인가 — 맞음 True · 다른 맵 False · 모름 None (감시 꺼짐·로딩 중·맵을 모름 — CLI 맞춤이나
    흐름 끊김으로 맵을 지운 때도). 콘텐츠 안팎을 자주 보는 자리용으로 가볍다 (CLI 를 묻지 않는다 — 로딩이 오래 가는
    때만 map_loading 이 묻는다). 장소 이름이나 CLI 짐작까지 필요하면 place().
    '모름' 을 '다른 맵' 으로 읽으면 안 된다 — 필드 보스 전투가 그렇게 '영역 밖으로 나옴' 으로 끝났다 (2026-11-16)."""
    if bot.map_loading() is not False:
        return None
    t = bot.packets.state.channel_type
    return t == kind if t else None


def is_instance(kind: str | None) -> bool:
    """콘텐츠 맵(Instance…)인가. 모르면(None·'') False."""
    return (kind or "").startswith(INSTANCE)


@dataclass
class Place:
    loading: bool | None      # 맵 로딩 중 (모르면 None)
    kind: str | None          # 맵 종류 (패킷 channel_type 이름을 쓴다). 모르면 None
    src: str                  # kind 를 무엇으로 알았나: packet / cli / ''
    name: str = ""            # 장소 이름 (패킷이면 맵 이름, CLI 면 ChannelDisplayName)
    dungeon: str | None = None  # 던전 상태 NotInDungeon / Entering / InProgress / Cleared
    in_field: bool | None = None  # 사냥터 안 (클리어 뒤 채널 옮김 대기 포함)


def place(bot) -> Place:
    """지금 자리. 패킷이 맵을 알면 그것으로, 모르면 CLI(get_activity 의 던전·사냥터 + 장소 이름)로 짐작한다."""
    p = bot.packets
    loading = bot.map_loading()
    if loading is False:
        bot.activity()  # CLI 답으로 패킷의 맵·던전·사냥터를 맞춘다 (merge_cli — 어긋나면 맵을 모름으로 돌린다)
        loading = bot.map_loading()
    s = p.state
    if loading is not None:  # 패킷이 맵을 안다
        # 사냥터 상태를 모르면(CLI 맞춤·작업 시작 점검이 모름으로 돌림 — CLI 는 진행 중과 클리어 뒤를 못 가른다) 맵 종류로.
        # 예전엔 모름으로 둬 이어 하기가 사냥터 맵 안인 줄 몰랐다 (점검 2026-11-22)
        field = (s.field_state != FIELD_OUT if s.field_state is not None
                 else s.channel_type == FIELD if s.channel_type and not loading else None)
        return Place(loading, None if loading else (s.channel_type or None), "packet",
                     s.channel_name, s.dungeon_state, field)
    act = bot.activity()
    if act is None:  # 로딩 중이거나 게임 밖이거나 CLI 가 없다
        return Place(None, None, "", "", s.dungeon_state if p.ok else None, None)
    a = Activity.of(act)
    dungeon, in_field = a.dungeon, a.in_field
    env = bot.environment() or {}
    name = env.get("ChannelDisplayName", "") or ""
    kind = None
    if (env.get("Housing") or {}).get("IsInHousing"):
        kind = HOUSING  # 마이 홈
    elif name.endswith(INN_SUFFIX):
        kind = HOUSING_INN
    elif in_field:
        kind = FIELD
    elif name and any(n in name for n in ("어비스", *gd.abyss_names())):
        kind = ABYSS
    elif name and name == gd.text("raid_ship"):
        kind = RAID_LOBBY
    elif a.in_dungeon:
        kind = DUNGEON
    return Place(False, kind, "cli" if kind else "", name, dungeon, in_field)
