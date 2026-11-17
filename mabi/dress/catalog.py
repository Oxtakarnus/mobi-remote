"""드레스룸 목록 — 게임 자산 경로에서 체형·부위별 모델을 모으고, 게임 시트의 아이템 이름을 붙인다 (names).

  의상   Character/Player/Human/<Female|Male|Infant>/<부위>/ForAssetBundle/<모델>.prefab  (+ FBX/Human/<성별>/<부위>/<모델>.fbx)
         모자는 <성별>/Helmet/<모델>.prefab 처럼 ForAssetBundle 없이 바로 밑에 있는 것도 많다 (그리는 법은 같다)
         다른 부위의 바로 밑 prefab 은 게임 시트(이름 표)가 쓰는 모델만 받는다 — 머리 일부는 거기만 있고, 나머지는 개발용(_test·Guide)
         fbx 가 없는 모델(무늬만 바꾼 옷·머리 일부)은 게임이 실행 중에 쓰는 자료가 있을 때(runtime) prefab 을 그린다
  장식   Character/Player/Human/Facial/Customize/<성별>/Acc/[ForAssetBundle/]<모델>.prefab (+ …/<성별>/FBX/<모델>.fbx)
         얼굴·눈·귀 장식은 같은 폴더라 부위는 이름 표의 게임 부위로, 없으면 모델 정의의 AppearanceSlot(Accessory0·1·2)으로 가른다
         백팩도 이 폴더다 — 게임 의상 칸은 로브(이름 표 '로브'), 모델 정의 부위는 AccessoryBody0 (로브처럼 옷을 숨기지 않는다)
  공용   자기 prefab 이 없고 모델 정의(AssetPathToLoad)가 다른 모델의 prefab 을 가리키는 모델 — 그 모델의 자산으로 그린다
         (여성·남성 풍선껌이 아이 prefab, 철자만 다른 prefab 등)
  무기   Item/<종류>/<모델>.prefab (+ Item/<종류>/FBX/<모델>.fbx) — 체형 공용(folder ""), 의상 행 하나가 도구 여럿이라
         대표 도구를 목록 id 로 두고 나머지는 extra 로 같이 싣는다 (tools.groups)
  몸     Character/Player/Human/FBX/<Female|Male|Infant|InfantMale>_Body_00.fbx
  머리   Character/Player/Human/Facial/Customize/<성별>/FBX/<성별>_Head_Default_00.fbx
  눈     Character/Player/Human/Facial/Customize/<성별>/FBX/<성별>_Eye_Default_00.fbx
  동작   Animation/Player/Human/<성별>/Customize/<HF|HM|HC>@Customize_Stand_<Default|Thin|Fat|Muscle>.fbx

영어 이름(name)은 모델 이름에서 성별·부위 말을 떼고 낱말을 띄운다 (Female_BalloonLineCarpentry_Helmet_01 → Balloon Line Carpentry 01).
게임 아이템이 이 모델을 쓰면 한글 이름(kor)·게임 부위(slot)·세트·아이콘 경로를 같이 싣는다. 시트에 없는 모델
(NPC·미출시 옷)은 영어 이름만 있다. 목록 순서는 부위 → 한글 이름 있는 것(가나다) → 없는 것(영어 이름).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from . import cover as CV
from . import tools as T
from .names import SLOT_KOR

H = "Assets/PatchableAssets/Character/Player/Human/"
ANIM = "Assets/PatchableAssets/Animation/Player/Human/"
PARTS = ("Top", "Bottom", "OnePiece", "Robe", "Gloves", "Shoes", "Helmet", "Hair", "FaceDeco", "EyeDeco", "EarDeco",
         "Weapon")
PART_KOR = {"Top": "상의", "Bottom": "하의", "OnePiece": "한 벌", "Robe": "로브", "Gloves": "장갑", "Shoes": "신발",
            "Helmet": "모자", "Hair": "머리", "FaceDeco": "얼굴 장식", "EyeDeco": "눈 장식", "EarDeco": "귀 장식",
            "Weapon": "패션 무기"}
CLOTH = PARTS[:8]                                # 몸 의상 폴더(Human/<체형>/<부위>/)에서 찾는 부위
DECO = ("FaceDeco", "EyeDeco", "EarDeco")
_ACC_KOR = {SLOT_KOR[k]: k for k in (*DECO, "Robe")}                         # 장식 폴더: 이름 표 게임 부위 → 부위
_ACC_SLOT = {"Accessory0": "FaceDeco", "Accessory1": "EyeDeco", "Accessory2": "EarDeco",   # 모델 정의 AppearanceSlot
             "AccessoryBody0": "Robe"}                                                       # 백팩
# 체형: (이름, 의상 폴더, 몸 모델, 동작 접두어)
BODIES = {
    "Female": ("여성", "Female", "Female_Body_00", "HF"),
    "Male": ("남성", "Male", "Male_Body_00", "HM"),
    "Girl": ("소녀", "Infant", "Infant_Body_00", "HC"),
    "Boy": ("소년", "Infant", "InfantMale_Body_00", "HC"),
}
ADULTS = ("Female", "Male")   # 성인 체형 (체형 id 와 의상 폴더 이름이 같다) — 성인 기준 모습만 쓰는 다른 프로그램용
# 셰이프(뷰어 이름) → 동작 파일 이름
STAND = {"": "Default", "Thin": "Thin", "Fat": "Fat", "Muscular": "Muscle"}
_PREFAB = re.compile(r"/Character/Player/Human/(Female|Male|Infant)/(\w+)/(ForAssetBundle/)?(\w+)\.prefab$")
_LOOSE = ("Helmet",)   # ForAssetBundle 없이 부위 폴더 바로 밑 prefab 도 받는 부위
_FBX = re.compile(r"/Character/Player/Human/FBX/Human/\w+/\w+/(\w+)\.fbx$")
_ACC = re.compile(r"/Character/Player/Human/Facial/Customize/(Female|Male|Infant)/Acc/(?:ForAssetBundle/)?(\w+)\.prefab$")
_ACC_FBX = re.compile(r"/Character/Player/Human/Facial/Customize/\w+/FBX/(\w+)\.fbx$")
_TOOL = re.compile(r"/PatchableAssets/Item/\w+/(\w+)\.prefab$")
_TOOL_FBX = re.compile(r"/PatchableAssets/Item/\w+/FBX/(\w+)\.fbx$")


@dataclass(frozen=True)
class Item:
    id: str        # 모델 이름 (Female_Maid_Bottom_00)
    folder: str    # Female · Male · Infant ("" = 체형 공용 — 패션 무기)
    part: str      # PARTS 중 하나
    name: str      # 영어 이름 (모델 이름에서)
    fbx: str       # 자산 경로
    kor: str = ""                  # 게임 아이템 이름 (없으면 "")
    alt: tuple[str, ...] = ()      # 같은 모델을 쓰는 다른 아이템 이름
    slot: str = ""                 # 게임 부위 (모자·상의·…, 한 벌 옷도 상의)
    set_name: str = ""             # 세트 이름
    icon: str = ""                 # 시트 아이콘 경로 (Icons/…_ColoredIcon.asset, 없으면 "")
    extra: tuple[tuple[str, str], ...] = ()   # 같이 그리는 모델 (모델, 자산 경로) — 패션 무기의 방패·화살통 등
    prefab: str = ""               # prefab 자산 경로 (fbx 로 그리는 모델도 — 이펙트 소켓 노드는 prefab 에만 있다)
    colors: tuple = ()             # 게임 시트의 아이템 기본 염색 6칸 (#RRGGBB 또는 None, 시트에 없으면 ())
    job: str = ""                  # 패션 무기의 직업 (동작 표 직업 갈래 이름 — 무기 든 경계 자세를 고른다, 없으면 "")

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("extra")
        d.pop("prefab")
        d["alt"] = list(self.alt)
        d["colors"] = list(self.colors)
        d["set"] = d.pop("set_name")
        d["named"] = bool(self.kor)
        return d


def _words(s: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", s)


def pretty(model: str, folder: str, part: str) -> str:
    bits = model.split("_")
    if bits and bits[0] in (folder, "Infant", "InfantMale"):
        bits = bits[1:]
    bits = [b for b in bits if b.lower() != part.lower()]
    num = bits.pop() if bits and bits[-1].isdigit() else ""
    name = " ".join(_words(b) for b in bits) or model
    return f"{name} {num}" if num and num != "00" else name


def _item(model: str, folder: str, part: str, src: str, names: dict, extra=(), prefab: str = "") -> Item:
    n = names.get(model) or {}
    return Item(model, folder, part, pretty(model, folder, part), src, kor=n.get("name", ""), alt=tuple(n.get("alt") or ()),
                slot=n.get("slot", ""), set_name=n.get("set", ""), icon=n.get("icon", ""), extra=tuple(extra), prefab=prefab,
                colors=tuple(n.get("colors") or ()), job=n.get("job", ""))


def build(paths, names: dict | None = None, runtime=None, som=None) -> list[Item]:
    """자산 경로들 → 의상 목록. names: 모델 id → 이름 표 한 줄 (dress.names).
    fbx 가 있는 모델은 fbx 를, 없으면 runtime(모델) 이 참일 때 prefab 을 Item.fbx 로 싣는다 (modular.Library.has).
    som(모델) → 모델 정의 dict 또는 None (modular.Library.som) — 장식 부위·무기 대표를 가른다. 없으면 이름 표만으로."""
    fbx, acc_fbx, tool_fbx, tool = {}, {}, {}, {}
    for p in paths:
        for rx, d in ((_FBX, fbx), (_ACC_FBX, acc_fbx), (_TOOL_FBX, tool_fbx), (_TOOL, tool)):
            m = rx.search(p)
            if m:
                d.setdefault(m.group(1), p)
                break
    names = names or {}
    som = som or (lambda model: None)

    def src_of(model, prefab, fbx_of):
        return fbx_of.get(model) or (prefab if runtime is not None and runtime(model) else None)

    out, seen = [], set()
    for p in paths:
        m = _PREFAB.search(p)
        if not m:
            continue
        folder, part, bundled, model = m.groups()
        if part not in CLOTH or model in seen or (not bundled and part not in _LOOSE and model not in names):
            continue
        src = src_of(model, p, fbx)
        if src is None:
            continue
        if "Test" in model:   # 개발용 (TestDigger…)
            continue
        seen.add(model)
        out.append(_item(model, folder, part, src, names, prefab=p))

    for p in paths:   # 얼굴·눈·귀 장식, 백팩
        m = _ACC.search(p)
        if not m:
            continue
        folder, model = m.groups()
        if model in seen or "Test" in model:
            continue
        part = _ACC_KOR.get((names.get(model) or {}).get("slot")) or _ACC_SLOT.get(CV.slot(som(model)))
        src = src_of(model, p, acc_fbx) if part else None
        if src is None:
            continue
        seen.add(model)
        out.append(_item(model, folder, part, src, names, prefab=p))

    folders = {v[1] for v in BODIES.values()}
    by_model = {i.id: i for i in out}
    for model in names:   # 다른 모델의 자산을 같이 쓰는 모델
        if model in seen or "Test" in model:
            continue
        ap = str((som(model) or {}).get("AssetPathToLoad") or "")
        target = by_model.get(ap.rsplit("/", 1)[-1].rsplit(".", 1)[0]) if ap.endswith(".prefab") else None
        if target is None:
            continue
        folder = model.split("_", 1)[0]
        seen.add(model)
        out.append(_item(model, folder if folder in folders else target.folder, target.part, target.fbx, names,
                         prefab=target.prefab))

    for g in T.groups(names, lambda model: CV.slot(som(model))):   # 패션 무기 (의상 행마다 한 개)
        if g.main in seen:
            continue
        src = src_of(g.main, tool.get(g.main), tool_fbx) if g.main in tool else None
        if src is None:
            continue
        extra = [(m, s) for m in g.others if m in tool for s in (src_of(m, tool[m], tool_fbx),) if s]
        seen.add(g.main)
        out.append(_item(g.main, "", "Weapon", src, names, extra, prefab=tool.get(g.main, "")))
    out.sort(key=sort_key)
    return out


def sort_key(i: Item):
    """부위 → 한글 이름 있는 것 먼저(가나다) → 없는 것(영어 이름)."""
    return PARTS.index(i.part), not i.kor, (i.kor or i.name).lower(), i.id


def body_of(folder: str) -> str:
    """의상 폴더 → 그 폴더를 쓰는 첫 체형 id (Female·Male 은 같은 이름, Infant → Girl)."""
    return next(b for b, v in BODIES.items() if v[1] == folder)


def body_paths(body: str) -> dict[str, str]:
    """체형 → {body, head, eye} fbx 자산 경로."""
    _, folder, b, _ = BODIES[body]
    face = H + f"Facial/Customize/{folder}/FBX/{folder}"
    return {"body": H + f"FBX/{b}.fbx", "head": face + "_Head_Default_00.fbx", "eye": face + "_Eye_Default_00.fbx"}


def stand_path(body: str, shape: str) -> str:
    """체형·셰이프 → 꾸미기 화면 대기 동작 fbx."""
    _, folder, _, pre = BODIES[body]
    return ANIM + f"{folder}/Customize/{pre}@Customize_Stand_{STAND.get(shape, 'Default')}.fbx"
