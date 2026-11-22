"""이름을 모를 때 지금 캐릭터가 마지막으로 확인한 그 캐릭터인가 — CLI get_my_info 의 '지문'으로.

패킷 이름(my_name)은 맵에 들어갈 때만 와서 리모콘을 막 켜면 모르고, 화면 이름(OCR)은 메인 화면에서만 읽힌다. 그래서
업데이트로 리모콘만 다시 켜고 어비스 입장 창을 띄운 채 시작하면, 같은 캐릭터인데도 창을 닫고 메인 화면에서 이름을 읽은
뒤 다시 열었다 (2026-11-22 19:10).

get_my_info 에는 이름이 없어 슬롯마다 지문(서버·레벨·직업·타이틀·전투력 …)을 기억해 둔다. 예전엔 '가장 비슷한 슬롯' 을
골랐는데 자주 틀려서 뺐다 (2026-10-22 — 생활력·매력·데코는 계정 공용일 수 있고 접속 직후 커넥터가 이전 캐릭터 정보를 잠깐
돌려준다). 지금은 좁게만 쓴다:
- 기억: 패킷 이름이 그 캐릭터라고 할 때만, 맵에 들어간 지 LEARN_SETTLE 초 뒤부터 (반복 콘텐츠는 판을 깰 때마다 새로 쓴다)
- 알아보기: SAME_KEYS 가 모두 똑같은 슬롯이 딱 하나일 때만 — 전투력은 장비로 캐릭터마다 다르고 자주 바뀌므로, 마지막으로
  확인한 뒤 아무것도 안 바뀐 같은 캐릭터만 맞는다. 조금이라도 다르면 모름 (예전처럼 메인 화면에서 확인)
- 그래도 이름을 알게 되면 다시 확인한다 (tasks.repeat.Repeat.recheck)
"""
import json
import threading
import time
from datetime import datetime
from pathlib import Path

SAME_KEYS = ("realm", "level", "job", "title", "combat")  # 모두 같아야 같은 캐릭터 (생활력·매력·데코는 계정 공용일 수 있어 뺌)
LEARN_EVERY = 60.0    # 같은 슬롯 지문을 다시 쓰는 간격(초)
LEARN_SETTLE = 30.0   # 맵에 들어간 뒤 이만큼은 기억하지 않는다 — 접속 직후 커넥터가 이전 캐릭터 정보를 잠깐 돌려준다
_learned: dict[int, float] = {}  # 슬롯 → 마지막으로 기억한 때 (monotonic)


def fingerprint(info: dict | None) -> dict | None:
    """get_my_info 원본 → 지문. 값이 없으면 None."""
    if not isinstance(info, dict) or info.get("Level") is None:
        return None

    def v(k):
        return (info.get(k) or {}).get("Value")
    return {"realm": info.get("RealmName") or "", "level": info.get("Level"),
            "job": info.get("EnabledCombatJobDisplayName") or "", "title": info.get("Title") or "",
            "combat": v("CombatScore"), "living": v("LivingScore"), "attract": v("AttractivenessScore"),
            "decor": v("DecorScore")}


def same(a: dict | None, b: dict | None) -> bool:
    """두 지문이 SAME_KEYS 모두 같은가 (레벨·전투력을 모르면 아니다)."""
    if not a or not b or a.get("level") is None or a.get("combat") is None:
        return False
    return all(a.get(k) == b.get(k) for k in SAME_KEYS)


def match(slots: dict, fp: dict | None) -> int | None:
    """기억한 지문({슬롯: {"fp": …}}) 가운데 fp 와 같은 슬롯 — 딱 하나일 때만, 아니면 None."""
    hits = [int(k) for k, e in slots.items() if same((e or {}).get("fp"), fp)]
    return hits[0] if len(hits) == 1 else None


def remember(bot, ch: dict | None) -> None:
    """패킷이 알려 준 지금 캐릭터 이름이 ch 면 지금 지문을 ch 슬롯에 기억한다 (LEARN_EVERY 초에 한 번,
    맵에 들어간 지 LEARN_SETTLE 초 뒤부터). 화면 이름(OCR)으로는 기억하지 않는다 — 잘못 읽은 이름으로 남지 않게."""
    from .tasks.login import name_matches  # login 은 봇 전체를 불러와 여기서
    slot = (ch or {}).get("slot")
    p = bot.packets
    now = time.monotonic()
    if slot is None or not p.ok or now - _learned.get(slot, -1e9) < LEARN_EVERY:
        return
    s = p.state
    if not s.my_name or s.loading or now - s.entered_at < LEARN_SETTLE or not name_matches(s.my_name, ch.get("name", "")):
        return
    fp = fingerprint(bot.session.my_info(max_age=0))
    if not fp:
        return
    _learned[slot] = now
    Characters(bot.paths.data).learn(slot, fp)


def recognize(bot) -> int | None:
    """지금 지문과 똑같은 지문을 기억한 슬롯 (하나뿐일 때), 모르면 None. CLI 를 새로 묻는다."""
    fp = fingerprint(bot.session.my_info(max_age=0))
    return match(Characters(bot.paths.data).load()["slots"], fp) if fp else None


class Characters:
    """data/characters.json: {"slots": {"1": {"fp": {...}, "seen": "..."}}}"""

    def __init__(self, data_dir: Path):
        self.file = Path(data_dir) / "characters.json"
        self._lock = threading.Lock()

    def load(self) -> dict:
        try:
            d = json.loads(self.file.read_text(encoding="utf-8"))
            if isinstance(d, dict) and isinstance(d.get("slots"), dict):
                return d
        except (OSError, ValueError):
            pass
        return {"slots": {}}

    def _save(self, d: dict) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.file)

    def learn(self, slot: int, fp: dict) -> None:
        with self._lock:
            d = self.load()
            d["slots"].setdefault(str(slot), {}).update(fp=fp, seen=datetime.now().isoformat(timespec="seconds"))
            self._save(d)

    def set_card(self, slot: int, level, job) -> None:
        """캐릭터 선택 화면에서 읽은 레벨·직업 (카드 표시용. 알아보기에는 쓰지 않는다)."""
        with self._lock:
            d = self.load()
            e = d["slots"].setdefault(str(slot), {})
            e["card"] = {"level": level, "job": job}
            self._save(d)
