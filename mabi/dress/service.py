"""드레스룸 자료 관리 — 게임 폴더에서 목록을 만들고, 고른 모델만 그때 꺼내 데이터 폴더(dressroom\\)에 둔다.

  dressroom\\cab.json          CAB 이름 → 번들 표 (assets)
  dressroom\\names.json        모델 → 게임 아이템 이름·아이콘 경로·기본 색 (names, 시트 목차 stamp 로 따로 관리)
  dressroom\\face.json         얼굴 꾸미기 선택지·부품 값 (face, names 와 같은 방식)
  dressroom\\fx.json           의상 → 이펙트 타임라인 표 (fx, names 와 같은 방식) · dressroom\\fx\\cab.json 이펙트용 CAB 표
  dressroom\\motions.json      동작 탭 목록 — 공통·꾸미기·감정 표현과 표정 짝 (motions, 시트 + 동작 목차 stamp)
  dressroom\\stamp.json       꺼낸 자료가 어느 게임 목차·형식에서 나왔나 — 목차·FORMAT 이 다르면 models\\·tex\\·icons\\ 를
                               비우고, CLIP_FORMAT·MESH_FORMAT 만 다르면 그 모델만 지운다 (_check_stamp)
                               (AssetPackages 목차 둘 + ResourcesPackage 목차 둘 — 이펙트 타임라인이 본 목차에 있다)
  dressroom\\models\\<id>.json·bin · tex\\<이름>.png   (export, textures)
  dressroom\\models\\<id>.partial  환경 탓으로 그림·이펙트를 빼고 꺼낸 모델 — 다음에 창을 열 때 지우고 다시 꺼낸다
  dressroom\\icons\\<id>.png   칠한 아이템 아이콘 (icons — 목록에 보이는 것만 그때 꺼낸다)

뷰어는 이 폴더를 mmdress://app/cache/ 로 읽는다 (gui_app/dressroom.py).
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import threading
from pathlib import Path

from .. import gamefiles as gf
from ..fileio import write_atomic, write_json
from . import anim as N
from . import assets as A
from . import body as B
from . import catalog as C
from . import cover as CV
from . import dyeslots as DS
from . import face as FC
from . import fx as FX
from . import gamelook as GL
from . import icons as I
from . import modular as MD
from . import motions as MO
from . import names as NM
from . import stage as ST
from . import textures as TX
from . import tools as T
from . import xaf as XF
from .export import Exporter, ExportError

log = logging.getLogger("mabi")
_NO_UNITYPY = "드레스룸 구성 요소(UnityPy)가 없습니다 — 설치 파일로 다시 설치해 주세요"


FORMAT = 17   # 꺼낸 모델 형식 — 바뀌면 캐시를 비운다 (2: 뼈대·스킨·동작, 3: 염색 판정을 칸 색으로, 4: 명암 값·키워드, 5: 몸 자르는 고리,
             # 6: 번호 0 번들(빠졌던 재질·텍스처)·실행용 메시, 7: 장식·패션 무기(attach·piece),
             # 8: 염색 키워드 없는 재질은 그림 그대로, 9: 후드 메시 hood·가림 규칙 rules,
             # 10: 재질마다 받는 염색 칸 slots — 의상 색 6칸, 11: 옷 자르는 판 sep·겹침 순서 fit,
             # 12: 발광 emit·가장자리 빛 fresnel, 13: 모든 모델에 게임 부위 fit.slot — 백팩,
             # 14: 스타킹 stocking, 15: 보석 gem, 16: 의상 이펙트 fx·소켓 노드, 17: 재질 배정은 게임 prefab 을 따른다)
MESH_FORMAT = 1   # 모델 json 에만 더한 것 — 바뀌면 동작 클립 밖의 모델만 비운다, 텍스처·아이콘은 둔다 (1: 옷·머리 흔들림 cloth)
CLIP_FORMAT = 4   # 꺼낸 동작 클립 형식 — 바뀌면 동작 클립(clip_*·anim_*)만 비운다 (2: 묶음 안 여러 클립 중 그 파일 것 — anim.pick_clip,
                  #  3: 오일러 커브를 X → Y → Z 순서로, 4: 표정 짝에 표정 키 face — xaf)
TOOL_BODY = "Female"   # 무기 기본 자세 (모델 json 은 체형 공용 — 다른 체형 자세는 attach 표에서 뷰어가 고른다)


class DressError(Exception):
    pass


def _missing(e: ImportError) -> DressError:
    """구성 요소가 빠진 설치 — 패치만 받은 옛 설치판 (UnityPy 는 설치 파일에 들어 있다)."""
    if (e.name or "").startswith("UnityPy"):
        return DressError(_NO_UNITYPY)
    return DressError(f"게임 파일을 읽을 구성 요소가 없습니다 ({e.name or e})")


def _guard(what: str, mid: str, fn):
    """fn() 을 부르고 실패를 화면에 보일 DressError 로 — 처음 보는 형식은 그 모델·아이콘 하나만 못 꺼낸 것으로 본다
    (드레스룸 창과 이 캐시를 쓰는 다른 프로그램은 이 판정 하나를 본다)."""
    try:
        return fn()
    except DressError:
        raise
    except ImportError as e:
        raise _missing(e) from e
    except Exception as e:
        log.warning(f"드레스룸 {what} {mid}: {type(e).__name__}: {e}")
        raise DressError(f"이 {what}은 읽지 못했습니다 ({type(e).__name__})") from e


class DressRoom:
    def __init__(self, cache_dir: Path, game_dir=None):
        """game_dir: 게임 폴더를 돌려주는 함수 (기본 gamefiles.game_dir)."""
        self.dir = Path(cache_dir)
        self._game_dir = game_dir
        self._lock = threading.Lock()
        self._pack: A.AssetPack | None = None
        self._items: dict[str, C.Item] = {}
        self._names: dict[str, dict] = {}
        self._face: dict | None = None
        self._face_icons: set[str] = set()
        self._by_sheet: dict[int, dict] | None = None   # 의상 시트 id → 체형별 모델 (게임 캐릭터 불러오기, 처음 부를 때)
        self._icon_pack: A.AssetPack | None = None
        self._lib: MD.Library | None = None   # 게임 실행용 메시 (fbx 없는 모델)
        self._lib_err: Exception | None = None   # 실행용 메시 목차를 못 읽은 까닭 (make 가 모델을 반쪽으로 표시)
        self._fx: FX.Effects | None = None    # 의상 이펙트 (처음 꺼낼 때)
        self._motions: dict | None = None     # 동작 탭 목록 (motions)
        self._xaf: XF.Library | None = None   # 표정 키 목차 (처음 표정 짝을 꺼낼 때)
        self._source: dict | None = None      # 꺼낸 캐시의 게임 파일·형식 (stamp.json 과 같은 값 — source)
        self._model_locks: dict[str, threading.Lock] = {}

    # ── 준비 ──
    def _gd(self):
        if self._game_dir is not None:
            return self._game_dir()
        from ..gamefiles import game_dir
        return game_dir()

    def pack(self) -> A.AssetPack:
        with self._lock:
            if self._pack is None:
                gd = self._gd()
                if gd is None or not (Path(gd) / "AssetPackages" / "index").is_file():
                    raise DressError("마비노기 모바일 설치 폴더를 찾지 못했습니다")
                pack = A.AssetPack(gd, self.dir)
                self._check_stamp(pack.stamp() + gf.res_stamp(gd))
                self._drop_partial()
                pack.cabs()
                self._names = self._load_names(gd)
                self._face = self._load_face(gd)
                self._lib = self._load_lib(gd)
                self._motions = self._load_motions(gd, pack)
                lib = self._lib
                self._items = {i.id: i for i in C.build(pack.paths, self._names, lib.has if lib else None,
                                                        lib.som if lib else None)}
                self._pack = pack
            return self._pack

    def _load_names(self, gd) -> dict[str, dict]:
        """이름 표 (names.json — 시트가 바뀌었으면 다시 만든다). 이름은 덤이라 못 읽어도 목록은 영어 이름으로 뜬다."""
        try:
            names, fresh = NM.load(self.dir, gd)
        except Exception as e:
            log.warning(f"드레스룸 이름 표를 만들지 못했습니다: {type(e).__name__}: {e}")
            return {}
        if fresh:   # ResourcesPackage 가 바뀌었다 — 시트 기본 색·몸 자료(bdc)도 바뀌었을 수 있다
            shutil.rmtree(self.dir / "icons", ignore_errors=True)
            for pat in ("bdc_*.json", "light_*.json"):   # light: 볼륨 자료로 만든 조명 프리셋 (stage)
                for f in (self.dir / "models").glob(pat):
                    f.unlink(missing_ok=True)
        return names

    def _load_lib(self, gd) -> MD.Library | None:
        """실행용 메시 목차. 못 읽으면 None — fbx 있는 모델만 목록에 뜬다. 까닭은 _lib_err 에 둔다 (환경 탓이면
        그동안 꺼내는 모델을 반쪽으로 표시해 다음에 다시 꺼낸다 — make)."""
        self._lib_err = None
        try:
            return MD.Library(Path(gd))
        except Exception as e:
            log.warning(f"드레스룸 실행용 메시 목차를 읽지 못했습니다: {type(e).__name__}: {e}")
            self._lib_err = e
            return None

    def _load_motions(self, gd, pack: A.AssetPack) -> dict | None:
        """동작 탭 목록. 덤이라 못 만들면 None — 동작 탭 없이 뜬다 (대기 동작은 anim:<체형>:<셰이프> 로 따로)."""
        try:
            if self._fx is None:   # 감정 표현 타임라인을 이으려고 (pack 의 잠금 안이라 바로 만든다)
                self._fx = FX.Effects(Path(gd), self.dir)
            return MO.load(self.dir, gd, pack.paths, pack.stamp(), tl=self._fx)
        except Exception as e:
            log.warning(f"드레스룸 동작 표를 만들지 못했습니다: {type(e).__name__}: {e}")
            return None

    def _load_face(self, gd) -> dict | None:
        """얼굴 선택지 표 (face.json). 덤이라 못 읽으면 None — 얼굴 고르기 없이 뜬다."""
        try:
            t, _fresh = FC.load(self.dir, gd)
        except Exception as e:
            log.warning(f"드레스룸 얼굴 표를 만들지 못했습니다: {type(e).__name__}: {e}")
            return None
        self._face_icons = {p for k in FC.KINDS for e in (t or {}).get(k, ()) for p in e["icon"].values() if p}
        return t

    def release(self) -> None:
        """창을 닫을 때 — 목차·목록을 메모리에서 내린다 (다시 열면 1초 안에 다시 읽는다)."""
        with self._lock:
            self._pack = None
            self._items = {}
            self._names = {}
            self._face = None
            self._face_icons = set()
            self._by_sheet = None
            self._icon_pack = None
            self._lib = None
            self._lib_err = None
            self._fx = None
            self._motions = None
            self._xaf = None

    def _check_stamp(self, stamp) -> None:
        """게임이 패치됐으면 꺼내 둔 모델·텍스처·아이콘을 비운다 (cab.json 은 assets, names.json 은 names 가 따로 비교한다).
        동작 클립 형식만 바뀌었으면 동작 클립만, 모델 json 형식(MESH_FORMAT)만 바뀌었으면 동작 클립 밖의 모델만 지운다.
        source 에는 MESH_FORMAT 을 안 넣는다 (동작 클립과 상관없다)."""
        f = self.dir / "stamp.json"
        cur = {"format": FORMAT, "clips": CLIP_FORMAT, "meshes": MESH_FORMAT, "stamp": stamp}
        self._source = {k: v for k, v in cur.items() if k != "meshes"}
        try:
            old = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            old = None
        if old == cur:
            return
        if isinstance(old, dict) and old.get("format") == FORMAT and old.get("stamp") == stamp:
            clip = ("clip_", "anim_")
            for x in (self.dir / "models").glob("*"):
                stale = old.get("clips") != CLIP_FORMAT if x.name.startswith(clip) else old.get("meshes") != MESH_FORMAT
                if stale and x.is_file():
                    x.unlink(missing_ok=True)
        else:
            for d in ("models", "tex", "icons"):
                shutil.rmtree(self.dir / d, ignore_errors=True)
        write_json(f, cur)

    def catalog(self) -> dict:
        self.pack()
        bodies = [{"id": k, "name": v[0], "folder": v[1]} for k, v in C.BODIES.items()]
        parts = [{"id": p, "name": C.PART_KOR[p]} for p in C.PARTS]
        face = {k: v for k, v in self._face.items() if k not in ("hairs", "shapes")} if self._face else None
        motions = MO.public(self._motions) if self._motions else None
        return {"bodies": bodies, "parts": parts, "items": [i.to_dict() for i in self._items.values()], "face": face,
                "motions": motions}

    def motions(self) -> dict | None:
        """동작 표 (motions.load — 못 만들었으면 None)."""
        self.pack()
        return self._motions

    def source(self) -> dict | None:
        """꺼낸 캐시가 어느 게임 파일·형식에서 나왔나 — 이 캐시에서 클립을 복사해 가는 쪽이 다시 담을지 본다."""
        self.pack()
        return self._source

    def game_look(self, snap: dict) -> tuple[dict, list[str]]:
        """리모콘이 패킷으로 본 내 캐릭터 외형(요약) → (화면 코디, 드레스룸에 없어 못 입힌 것들)."""
        self.pack()
        with self._lock:
            if self._by_sheet is None:
                self._by_sheet = NM.by_sheet(self._names)
        try:
            return GL.convert(snap, self._face, self._names, self._items, self._by_sheet)
        except GL.LookError as e:
            raise DressError(str(e)) from e

    # ── 모델 ──
    def model(self, mid: str) -> str:
        """모델 id → 캐시 안 json 경로 (dressroom 기준 상대 경로).

        의상 id (패션 무기는 도구 여럿을 몸 소켓에 붙인 한 모델 — _tool) · 'body:<체형>' · 'head:<체형>' · 'eye:<체형>' · 'anim:<체형>:<셰이프>' (꾸미기 화면 대기 동작)
        · 'clip:<줄기>' (동작 탭 동작 — 줄기가 _Facial 로 끝나면 표정: 머리 아래 뼈만, motions)
        · 'bdc:<체형>' (나이·키별 뼈 크기 — ResourcesPackage, body)
        · 'face:<부품 모델>' (얼굴형·눈·수염 메시) · 'decal:<부품 모델>' (입·문신 그림 — {"tex": 이름})
        · 'stage:rebirth' (환생 무대) · 'light:presets' (조명 프리셋) — stage
        · 'tl:<타임라인>' (감정 표현 이펙트·소품 — {"fx": fx.timeline 값 | null, "props": [{key, bone, begin, end, abegin,
          model: 'tlp:<타임라인>:<번호>', clip: 'tlc:<타임라인>:<번호>' | null}]}, 동작 표 timeline 에 있는 것만)
          'tlp:' 소품 모델 (무기처럼 몸 뼈 밑 — json attach[0].node 가 소품 루트 경로) · 'tlc:' 소품 동작 (소품 루트 기준 경로)
        처음 보는 오류도 DressError 로 바꾼다 (_guard).
        """
        return _guard("모델", mid, lambda: self._model(mid))

    def _model(self, mid: str) -> str:
        pack = self.pack()
        rel = f"models/{mid.replace(':', '_')}.json"
        if mid in ST.MODELS:   # 무대용 CAB 표는 dressroom\\stage\\ 에 따로 둔다
            return self._build(rel, lambda out: ST.export(mid, Path(self._gd()), self.dir, out), (ST.StageError,))
        if mid.startswith(("tl:", "tlp:", "tlc:")):
            return self._timeline_model(mid, rel)
        kind, fbx = self._fbx(mid)

        item = self._items.get(mid)

        def make(out: Path) -> None:
            if kind == "anim":
                N.export(pack, fbx, out)
            elif kind == "facial":
                N.export(pack, fbx, out, keep=N.face_only, face=self._face_keys(fbx))
            elif kind == "bdc":
                B.export(self._gd(), fbx, out)
            elif kind == "decal":
                Exporter(pack, self.dir / "tex").decal(fbx, out)
            elif item is not None and item.part == "Weapon":
                self._tool(pack, item, out)
            else:
                # 메시 칸이 빈 prefab(의상·얼굴 부품)은 같은 모델 이름의 실행용 메시로 채운다
                name = mid[5:] if mid.startswith("face:") else mid if item is not None else None
                lib = self._lib if name else None
                if name and lib is None and self._lib_err is not None:   # 재질 칸·가림 규칙·빈 메시 칸 없이 꺼낸다
                    TX.problem("실행용 메시 목차를 읽지 못했습니다", self._lib_err)
                som = lib.som(name) if lib and item is not None else None
                extra = {"rules": CV.rules(som), "fit": CV.fit(som)}   # 의상이 가리는 부위·후드, 겹침 순서
                more = None
                if item is not None:
                    extra["fx"], more = self._effects(pack, item)
                Exporter(pack, self.dir / "tex").run(
                    fbx, out, parts=(lambda: lib.parts(name)) if lib else None,
                    extra={k: v for k, v in extra.items() if v} or None, wiring=DS.wiring(som), more=more,
                    prefab=item.prefab if item is not None else None)

        return self._build(rel, make, (ExportError, B.BodyError, MD.PartError))

    def _effects_lib(self) -> FX.Effects:
        with self._lock:
            if self._fx is None:
                self._fx = FX.Effects(Path(self._gd()), self.dir)
            return self._fx

    def _timeline_model(self, mid: str, rel: str) -> str:
        """'tl:'·'tlp:'·'tlc:' (model 의 설명). 동작 표 timeline 에 있는 타임라인·있는 소품 번호만."""
        kind, _, rest = mid.partition(":")
        name, i = (rest, None) if kind == "tl" else (rest.rpartition(":")[0], rest.rpartition(":")[2])
        if name not in set(((self._motions or {}).get("timeline") or {}).values()):
            raise DressError(f"모르는 모델: {mid}")
        effects = self._effects_lib()
        if kind == "tl":
            return self._build(rel, lambda out: write_json(out, self._timeline_json(effects, name)))
        props = self._props(effects, name)
        if not i.isdigit() or int(i) >= len(props):
            raise DressError(f"모르는 모델: {mid}")
        p = props[int(i)]
        if kind == "tlc":
            if not p["anim"]:
                raise DressError(f"모르는 모델: {mid}")
            return self._build(rel, lambda out: N.export(effects.pack(), p["anim"], out), (ExportError,))

        def make(out: Path) -> None:
            body = json.loads((self.dir / self.model(f"body:{TOOL_BODY}")).read_text(encoding="utf-8"))["skeleton"]
            at, chain = T.socket_chain(body, p["bone"]) or ("", [])
            Exporter(effects.pack(), self.dir / "tex").run_mounted(
                [{"path": p["path"], "at": at, "t": p["off"], "r": p["rot"], "s": [1, 1, 1], "hidden": False,
                  "parts": None, "info": {"key": p["key"]}}], out, chain)
        return self._build(rel, make, (ExportError,))

    @staticmethod
    def _props(effects: FX.Effects, name: str) -> list[dict]:
        """감정 표현 소품 중 게임 목차에 prefab 이 있는 것 (번호가 'tlp:'·'tlc:' 번호). 소품 동작이 목차에 없으면 anim None —
        편집기 전용 경로(_EditorOnly)나 빠진 파일을 가리키는 타임라인이 있다 (그 소품은 붙은 자리에 가만히)."""
        known = effects.pack().paths
        return [dict(p, anim=p["anim"] if p["anim"] in known else None) for p in effects.props(name) if p["path"] in known]

    @classmethod
    def _timeline_json(cls, effects: FX.Effects, name: str) -> dict:
        """'tl:' 내용. 이펙트·소품은 덤이라 못 꺼내면 빈 값 (환경 탓이면 반쪽 표시 — 다음에 다시)."""
        try:
            fx = effects.timeline(name)
        except Exception as e:   # noqa: BLE001
            TX.problem(f"감정 표현 이펙트를 꺼내지 못했습니다 ({name})", e)
            fx = None
        try:
            props = cls._props(effects, name)
        except Exception as e:   # noqa: BLE001
            TX.problem(f"감정 표현 소품을 읽지 못했습니다 ({name})", e)
            props = []
        return {"fx": fx, "props": [{"key": p["key"], "bone": p["bone"], "begin": p["begin"], "end": p["end"],
                                     "abegin": p["abegin"], "model": f"tlp:{name}:{k}",
                                     "clip": f"tlc:{name}:{k}" if p["anim"] else None} for k, p in enumerate(props)]}

    def _face_keys(self, fbx: str) -> dict | None:
        """표정 짝의 표정 키 (입·눈 그림 칸, 눈 메시 보이기, 눈꺼풀 모프 — xaf). 못 읽으면 경고만 하고 뼈만 튼다."""
        try:
            with self._lock:
                if self._xaf is None:
                    self._xaf = XF.Library(Path(self._gd()))
                lib = self._xaf
            return lib.keys(fbx)
        except Exception as e:   # noqa: BLE001 — 표정 키는 덤이라 무엇이 틀려도 뼈 클립은 낸다
            TX.problem("표정 키를 읽지 못했습니다", e)
            return None

    def _build(self, rel: str, make, errors: tuple = ()) -> str:
        """make(경로) 로 캐시 파일 rel 을 만든다 — 모델마다 잠금 하나, 이미 있으면 그대로.
        errors 는 그 글 그대로 화면에 보일 DressError 로 바꾼다 (나머지는 model 의 _guard). 환경 탓(TX.RETRY)으로
        그림·이펙트를 빼고 꺼냈으면 <id>.partial 을 남겨 다음에 창을 열 때 다시 꺼낸다 (_drop_partial)."""
        out = self.dir / rel
        with self._model_locks.setdefault(rel, threading.Lock()):
            if out.exists():
                return rel
            with TX.collect() as problems:
                try:
                    make(out)
                except errors as e:
                    raise DressError(str(e)) from e
            mark = out.with_suffix(".partial")
            if problems:
                write_atomic(mark, "\n".join(problems))
                log.warning(f"드레스룸: {rel} 은 일부를 빼고 꺼냈습니다 — 다음에 창을 열 때 다시 꺼냅니다")
            else:
                mark.unlink(missing_ok=True)
        return rel

    def _drop_partial(self) -> None:
        """지난번에 일부를 빼고 꺼낸 모델(<id>.partial)을 지워 이번에 다시 꺼내게 한다 (환경이 고쳐졌을 수 있다)."""
        for mark in (self.dir / "models").glob("*.partial"):
            for f in (mark.with_suffix(".json"), mark.with_suffix(".bin"), mark):
                f.unlink(missing_ok=True)

    def _effects(self, pack: A.AssetPack, item: C.Item) -> tuple[dict | None, list | None]:
        """의상 → (json 의 fx 값, 뼈대에 더할 이펙트 소켓 노드). 이펙트는 덤이라 못 꺼내면 (None, None) — 옷은 그린다
        (환경 탓이면 TX.problem 이 그 옷을 반쪽으로 표시해 다음에 다시 꺼낸다)."""
        with self._lock:
            if self._fx is None:
                self._fx = FX.Effects(Path(self._gd()), self.dir)
            effects = self._fx
        try:
            if not effects.has(item.id):
                return None, None
            fx = effects.export(item.id)
            return fx, (FX.sockets(pack, item.prefab, FX.bones(fx)) if fx else None)
        except Exception as e:
            TX.problem(f"이펙트를 꺼내지 못했습니다 ({item.id})", e)
            return None, None

    def _tool(self, pack: A.AssetPack, item: C.Item, out: Path) -> None:
        """패션 무기 → 도구마다 모델 정의의 붙는 곳·자세로 몸 소켓 밑에 둔 한 모델 (기본은 TOOL_BODY 어른 자세).
        json 의 attach[k] (메시 piece k): {model, node(prefab 루트 노드 경로), state(그린 상태),
        states: {상태: {to(소켓 경로, '' = 뼈대 루트, None = 몸에 없음), visible, tf: [{infant, gender, t, r, s}]}}}
        — 뷰어가 체형에 맞는 tf(tools.pick_tf 규칙)로 node 를 다시 놓을 수 있다."""
        lib = self._lib
        body = json.loads((self.dir / self.model(f"body:{TOOL_BODY}")).read_text(encoding="utf-8"))["skeleton"]
        pieces = [(item.id, item.fbx)] + list(item.extra)
        infos = [T.info(lib.som(m) if lib else None) for m, _ in pieces]
        state = T.state_of(infos[0])
        mounts, chain, seen = [], [], set()
        for (model, path), inf in zip(pieces, infos):
            st = inf["states"].get(state) or {"to": "", "visible": True, "tf": []}
            at, links = T.socket_chain(body, st["to"]) or ("", [])
            for c in links:
                if c["path"] not in seen:
                    seen.add(c["path"])
                    chain.append(c)
            tf = T.pick_tf(st["tf"]) or {"t": [0, 0, 0], "r": [0, 0, 0, 1], "s": [1, 1, 1]}
            states = {}
            for k, v in inf["states"].items():
                sk = T.socket_chain(body, v["to"])
                states[k] = {**v, "to": sk[0] if sk else None}
            mounts.append({"path": path, "at": at, "t": tf["t"], "r": tf["r"], "s": tf["s"], "hidden": not st["visible"],
                           "parts": (lambda m=model: lib.parts(m)) if lib else None,
                           "info": {"model": model, "state": state, "states": states}})
        Exporter(pack, self.dir / "tex").run_mounted(mounts, out, chain)

    # ── 아이콘 ──
    def icon(self, mid: str) -> str | None:
        """의상 id 또는 'fi:<얼굴 선택지 아이콘 경로>' → 칠한 아이콘 png (dressroom 기준 상대 경로). 이미 있으면 그대로.
        게임 아이템이 아니거나 시트에 아이콘이 없거나 게임 목차에 그 아이콘이 없으면 None.
        처음 보는 오류도 DressError 로 바꾼다 (_guard)."""
        return _guard("아이콘", mid, lambda: self._icon(mid))

    def _icon(self, mid: str) -> str | None:
        self.pack()
        if mid.startswith("fi:"):
            if mid[3:] not in self._face_icons:
                raise DressError(f"모르는 아이콘: {mid}")
            n = {"icon": mid[3:], "colors": []}
        elif mid not in self._items:
            raise DressError(f"모르는 모델: {mid}")
        else:
            n = self._names.get(mid) or {}
        if not n.get("icon"):
            return None
        rel = "icons/" + re.sub(r"[^\w.-]", "_", mid) + ".png"
        lock = self._model_locks.setdefault("icon:" + mid, threading.Lock())
        with lock:
            if (self.dir / rel).exists():
                return rel
            ok = I.export(self._icons(), n["icon"], n.get("colors") or [], self.dir / rel)
        return rel if ok else None

    def _icons(self) -> A.AssetPack:
        """아이콘 경로만 기억하는 목차 (처음 부를 때 1초 남짓)."""
        with self._lock:
            if self._icon_pack is None:
                gd = self._gd()
                if gd is None:
                    raise DressError("마비노기 모바일 설치 폴더를 찾지 못했습니다")
                self._icon_pack = I.pack(Path(gd))
            return self._icon_pack

    def _fbx(self, mid: str) -> tuple[str, str]:
        """모델 id → (종류, 자산 경로)."""
        if mid.startswith(("face:", "decal:")):
            kind, _, model = mid.partition(":")
            p = ((self._face or {}).get("parts") or {}).get(model)
            if not p or (kind == "decal") != ("st" in p):
                raise DressError(f"모르는 모델: {mid}")
            return ("item" if kind == "face" else kind), p["a"]
        if mid.startswith("clip:"):
            p = ((self._motions or {}).get("clips") or {}).get(mid[5:])
            if not p:
                raise DressError(f"모르는 모델: {mid}")
            return ("facial" if mid.endswith("_Facial") else "anim"), p
        if ":" in mid:
            kind, _, rest = mid.partition(":")
            body, _, shape = rest.partition(":")
            if body not in C.BODIES:
                raise DressError(f"모르는 모델: {mid}")
            if kind == "anim" and shape in C.STAND:
                return kind, C.stand_path(body, shape)
            if kind in ("body", "head", "eye") and not shape:
                return kind, C.body_paths(body)[kind]
            if kind == "bdc" and not shape:
                return kind, body
            raise DressError(f"모르는 모델: {mid}")
        item = self._items.get(mid)
        if item is None:
            raise DressError(f"모르는 모델: {mid}")
        return "item", item.fbx

    def path(self, rel: str) -> Path | None:
        """mmdress://app/cache/<rel> 가 가리키는 파일 (dressroom 밖은 None)."""
        f = (self.dir / rel).resolve()
        try:
            f.relative_to(self.dir.resolve())
        except ValueError:
            return None
        return f if f.is_file() else None
