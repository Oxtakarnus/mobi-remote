"""게임 단축키 — 게임 설정에서 바꿀 수 있는 키는 리모콘 옵션([game] <이름>_key)에서도 바꾼다 (사용자 11-03).
이동(WASD)과 버튼에 붙은 확인 키(Space·Esc·R 여기서 부활·A 모두 받기 …)는 게임 화면 표시 그대로라 고정이다.

게임 조작키 설정에서 바꾼 키는 따라간다 (mabi.gamebinds, 사용자 11-19). 정하는 순서:
  리모콘 옵션에서 기본값과 다르게 정한 키 > 게임에서 바꾼 키 > 기본 키(게임 기본 주 키와 같다).
게임 키 읽기는 앱이 켤 때 follow_game() 으로 켠다 — 시험·도구에서는 꺼져 있어 기본 키만 쓴다."""
from .inputs import MODIFIERS, combo

# 이름: (기본 키, 옵션 창 설명). 순서대로 옵션 창에 나온다. 조합 키는 'shift+esc' 처럼 적는다
GAME_KEYS = {
    "leave": ("shift+esc", "여기서 나가기 — 던전·어비스·레이드·출항선·보스 영역·여관에서 나갈 때"),
    "camera": ("end", "수동 / 자동 카메라 토글 — 흩어진 물길에서 카메라를 캐릭터 뒤로 맞출 때"),
    "food": ("b", "음식 먹기"),
    "quest": ("j", "퀘스트 창"),
    "mission": ("n", "미션 창"),
    "map": ("m", "지도"),
    "guide": ("/", "콘텐츠 가이드"),
    "quick_nav": (".", "퀵 내비게이터"),
    "fast_travel": ("t", "빠른 이동 — 비우면 쓰지 않음"),
    "ultimate": ("6", "궁극기 — 어비스·레이드·드릴·필드 보스 전투"),
    "paladin": ("f5", "팔라딘 변신 — 어비스·레이드·드릴·필드 보스 전투"),
}
OPTIONAL = {"fast_travel"}  # 비워도 되는 키

_game = None  # mabi.gamebinds.GameBinds — follow_game() 으로 켠다


def follow_game(folder=None) -> None:
    """게임 조작키 설정을 따라가게 한다 (앱 시작 때). folder 를 안 주면 게임 설정 폴더."""
    global _game
    from . import gamebinds
    _game = gamebinds.GameBinds(folder or gamebinds.prefs_dir())


def game_key(name: str) -> str | None:
    """게임에서 바꾼 키 (안 바꿨거나 따라가기가 꺼져 있으면 None)."""
    return _game.current().get(name) if _game is not None else None


def remote_key(bot_or_cfg, name: str) -> str:
    """리모콘 설정의 키 — 설정에 없으면 기본 키 (테스트용 가짜 봇처럼 cfg 가 없어도)."""
    cfg = bot_or_cfg if isinstance(bot_or_cfg, dict) else getattr(bot_or_cfg, "cfg", None)
    game = cfg.get("game") if isinstance(cfg, dict) else None
    v = game.get(f"{name}_key") if isinstance(game, dict) else None
    return str(GAME_KEYS[name][0] if v is None else v).lower()


def of(bot_or_cfg, name: str) -> str:
    """지금 쓸 키. 리모콘 옵션에서 기본값과 다르게 정했으면 그 키, 아니면 게임에서 바꾼 키, 아니면 기본 키.
    게임 키가 리모콘의 일시정지·염색 도우미 키와 같으면 쓰지 않는다 — 누르는 순간 리모콘이 스스로 멈춘다."""
    v = remote_key(bot_or_cfg, name)
    if v != GAME_KEYS[name][0]:
        return v
    g = game_key(name)
    return g if g and g not in _own_keys(bot_or_cfg) else v


def _own_keys(bot_or_cfg) -> set[str]:
    cfg = bot_or_cfg if isinstance(bot_or_cfg, dict) else getattr(bot_or_cfg, "cfg", None)
    game = cfg.get("game") if isinstance(cfg, dict) else None
    if not isinstance(game, dict):
        return set()
    return {str(game[k]).lower() for k in ("stop_key", "dye_key") if game.get(k)}


def check(name: str, key: str) -> str | None:
    """옵션 창에서 고른 키가 쓸 수 있는지. 문제가 있으면 그 이유."""
    if name not in GAME_KEYS:
        return f"모르는 단축키 항목: {name}"
    if not key:
        return None if name in OPTIONAL else f"{GAME_KEYS[name][1].split(' —')[0]} 키를 비울 수 없습니다"
    try:
        combo(key)
    except ValueError:
        return f"쓸 수 없는 키: {key}"
    if key.lower() in MODIFIERS:
        return f"보조 키만으로는 쓸 수 없습니다: {key}"
    return None
