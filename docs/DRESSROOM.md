# 드레스룸 작업 참고

드레스룸(`mabi/dress/`, `gui_app/dressroom.py`, `web/dressroom/`)을 고칠 때 지킬 규칙, 무엇을 기준 자료로 삼는지, 바꾼 뒤
어떻게 확인하는지를 모은다. 기능 설명과 지나온 일은 `docs/STATUS.md` '드레스룸'.

## 자료 흐름

```
게임 폴더 (읽기만)
  AssetPackages 번들 ── assets.AssetPack ── CAB 표(cab.json, 거른 목차) + 표 밖 CAB(cab_extra.json)
  ResourcesPackage ──── gamefiles · gamesheet ── 시트(이름·기본 염색·얼굴·동작·이펙트) · 실행용 메시 · 몸 다양성
        │
  catalog / names ── 목록 항목 (모델·부위·이름·아이콘·기본 염색 colors·prefab 경로)
  export.Exporter ── 모델 하나 → models\<id>.json + .bin, 텍스처 tex\*.png   (service.DressRoom 이 캐시·판 번호 관리)
        │
  web/dressroom ──── 조립: dresser.js (입히기·색·동작·무기·흔들림) · viewer.js (그리기) · cover.js (가림) · fit.js (겹침·몸 자르기)
                     화면: main.js (상태·기억) · list.js (목록 칸) · cards.js (옷 카드) · looks.js (기억 값 검사) · view.js (옵션) · ui.js
```

## 무엇을 기준으로 삼나

게임이 실제로 그리는 자료(prefab·시트·모델 정의)를 기준으로 삼는다. 작업 파일(fbx)과 재질의 고유 값은 그 자료가 없을 때만 쓴다.
두 자료가 다를 때 작업 파일 쪽을 고르면, 몇 벌이 아니라 수백 벌이 함께 틀린다 (아래 '깨졌던 것').

| 항목 | 기준 | 없을 때 | 코드 |
|---|---|---|---|
| 메시 모양 | 옷 fbx | 실행용 메시 (`StageObjectModels/ModelParts`) | `export`, `modular` |
| 메시 칸 → 재질 배정 | 게임 prefab 렌더러의 `m_Materials` | 그 칸만 fbx 배정 | `Exporter._prefab_mats` |
| 칸 기본색 | 게임 시트 아이템 기본 염색 DyeColor0~5 (목록 `colors`) | 그 칸만 재질 `_DyeColor` | `Dresser.defaultColors` |
| 염색 칸 배선 | 모델 정의 DyeInfo (칸 → 메시·재질 칸·채널) | 배선 없는 채널은 재질 기본색 | `dyeslots` |
| 피부 재질 | 이름 Body·Head, 그림 Body_·Face_, 문신 자리 값 `_TattooMapScalePosition` (눈 재질 Eye_* 제외) | — | `export` 의 skin 판정 |
| 그림·재질 찾기 | CAB 표 | 전체 목차를 한 번 훑어 `cab_extra.json` 에 기록 | `AssetPack.cab` |
| 가림·옷끼리 겹침 | 모델 정의 ModelPartInfo·AppearanceSlot·JunctionPointInfo | — | `cover.py` → `cover.js`, `fit.js` |
| 이름·아이콘·부위 | 시트 Costume·CharacterHair·Equipment | 영어 모델 이름 | `names` |
| 의상 이펙트 | 시트 StageObjectModelTimeline + ResourcesPackage 본 목차 타임라인 | — | `fx` |
| 동작 클립 | 묶음 안에서 파일 이름과 같은 이름의 클립 | — | `anim.pick_clip` |
| 회전 키 보간 | 직접 계산 (`anim.lerpQuat`) — three.js slerp 쓰지 않음 | — | `web/dressroom/anim.js` |

## 지킬 규칙

- **같은 판정은 한 함수에서만 한다.** 기본색은 `Dresser.defaultColors`, 가림은 `cover.js`, 몸 자르기와 옷 겹침은
  `fit.js seamPlanes`·`beyond`, 피부 재질은 export 의 skin 판정, 그림 찾기는 `AssetPack.cab` 에서만 한다.
  화면 쪽에서 같은 판정을 따로 만들면 고칠 때 한쪽만 바뀐다. 실제로 피부 조각 재질을 뷰어에서 바꾸다 되돌린 일이 있다.
- **꺼낸 결과가 바뀌면 판 번호를 올린다.** 올리지 않으면 사용자 캐시에 옛 모델이 남아, 고친 내용이 보이지 않는다.
  올릴 때는 상수 옆 주석에 `N: 무엇` 을 덧붙인다.

  | 상수 | 올리는 때 | 비우는 것 |
  |---|---|---|
  | `service.FORMAT` | 모델 json·bin 형식이나 꺼내는 규칙(재질·메시·그림)이 바뀜 | models\ · tex\ · icons\ |
  | `service.CLIP_FORMAT` | 동작 클립 꺼내는 규칙 | 동작 클립만 |
  | `service.MESH_FORMAT` | 모델 json 에 더하기만 한 것 (흔들림 `cloth` 등) | 동작 클립 밖의 모델만 (텍스처·아이콘은 둔다) |
  | `assets._CAB_VER` | 목차 거르기(`_keep`·`_CHAR_TEX`)·번들 위치 규칙 | CAB 표 |
  | `names.FORMAT`·`face.FORMAT`·`motions.FORMAT`·`fx.FORMAT` | 그 표의 형식·고르는 규칙 | 그 표 |

- **고친 코드로 꺼내 보는 시험은 데이터 폴더의 복사본에서 한다.** 판 번호가 다른 코드가 실제 `dressroom\` 을 열면
  그 자리에서 캐시를 비운다 (11-17 시험 스크립트가 리모콘의 모델을 지웠다 — 도장 stamp.json 을 되돌려 클립은 지켰다).
- **게임 자산과 추출물은 저장소와 배포판에 넣지 않는다.** 시험은 가짜 값으로 쓰고, 전체 점검 작업 폴더도 저장소 밖에 둔다.
- **환경 탓 실패는 오류로 막지 않는다.** 그림 몇 장을 못 읽었으면 빼고 그리고 `<id>.partial` 로 남긴다. 다음에 창을 열 때
  다시 꺼낸다 (`service._build`). 다만 점검에서 partial 은 0 이어야 한다.
- **한 벌만 이상하면 그 옷의 게임 값을 먼저 본다.** 다른 옷에 퍼지는 특례를 만들기 전에 `--show` 로 재질 배정과 값을 확인하고,
  게임 자료에 근거가 있으면 규칙으로 넣는다.

## 깨졌던 것

| 증상 | 원인 | 지금 규칙 |
|---|---|---|
| 옷의 목·가슴 피부가 하얗게 나옴 (233벌 — 하이스쿨 크러쉬 유니폼 등) | 재질 배정을 fbx 에서 가져옴 — 피부 조각에 빈·천 재질 | prefab 배정 (FORMAT 17) |
| 폼폼 소다 웨어 셔츠 밑이 비어 보임 | fbx 배정이 비키니 칸에 반투명 셔츠 재질 → 셔츠가 먼저 그려져 깊이로 비키니를 가림 | prefab 배정 |
| 기본색이 게임과 다름 (염색 가능 3,204벌 중 1,664벌) | 재질의 작업용 색을 기본색으로 씀 | 시트 기본 염색 우선 |
| 검사학교 교복 상의가 흼 | 염색 지도가 `TestDummies` 폴더라 CAB 표 밖 | 캐릭터 이름 그림은 폴더와 상관없이 표에 (CAB 표 10) |
| 사물 머리·풍등·해적 모자·캣츠데이 무기 그림이 빠지거나 못 꺼냄 | 배경 소품·이펙트·마네킹 재질을 빌려 씀 | 표 밖 CAB 찾기 |
| 환생 무대 무늬가 빠짐 | 모리안 제단 그림을 빌려 씀 | `stage._KEEP` |
| 베일문 가디언 아머(아이)·남성 중갑신발을 못 꺼냄 | 법선이 4칸(x,y,z,w) | `export._cols` 앞 칸만 |
| 동작 중 몸 떨림 | three.js slerp 가 길이 1 이 아닌 키의 작은 각을 건너뜀 | `anim.lerpQuat` |
| 동작 82개가 엉뚱함 | 묶음의 첫 클립을 씀 | `anim.pick_clip` |
| 격투가 클록 어깨가 주황 | 칸 i = 채널 i 로 칠함 | DyeInfo 배선 |
| 재질·그림 몇 개 빠짐 | 묶음 파일 목차 번호 0 항목을 버림 | `gamefiles._entry`, `assets._starts` |
| 가끔 다른 번들 내용이 섞임 | UnityPy 가 이름 없는 번들을 메모리 주소로 이름 지어 덮어씀 | 열 때 이름을 준다 |
| 안경알이 사라짐 | 반투명을 0.5 로 잘라 그림 | `_RenderMode` 1 은 섞어 그림 |
| 짧은 옷 조합에서 몸이 사라짐 · 드레스 허벅지 구멍 | 몸 자르는 고리 방향·덮음 판정 | 구역별 판정, 세 꼭짓점을 같은 옷이 덮어야 숨김 |
| 3D 를 띄운 채 목록을 넘기면 창이 꺼짐 | PySide6 6.12.0 WebEngine | 6.11.3 고정 (requirements.txt) |
| 예복 치마가 2m 가까이 튀어 오름 (흔들림) | 굽힘을 날개 점만 돌려 맞춤 — 이웃 줄끼리 서로 키워 감 | 네 점을 각의 기울기로 옮김 (`cloth.js bend`) |
| 드레스룸 창이 둘 떠 설정을 서로 덮어쓸 수 있음 | 띄운 창에 신호가 안 닿으면 20초 뒤엔 새 창을 띄움 | 띄운 창이 살아 있으면 안 띄움, 창은 신호 통로를 다시 연다 |

## 바꾼 뒤 확인

1. 단위 시험: `python -m unittest discover -s tests` (드레스룸은 `test_dress*.py`), `node tests/dress_*.test.mjs`,
   `node tests/web_load.test.js`.
2. 꺼내는 규칙을 바꿨으면 전체 의상을 점검한다. 작업 폴더는 저장소 밖에 두고, 2GB 쯤 쓴다.
   ```
   .venv/Scripts/python.exe tools/dress_audit.py <작업 폴더> --fresh     # 4 일꾼, 5,400벌 5분쯤 (게임이 켜져 있어도 낮은 우선순위)
   .venv/Scripts/python.exe tools/dress_audit.py <작업 폴더> --report     # 종류별 건수, 같은 재질·같은 CAB 끼리 묶음
   .venv/Scripts/python.exe tools/dress_audit.py <작업 폴더> --show <모델 id>   # 메시 → 재질 배정, 재질 종류·피부·염색 칸·반투명
   ```
   아래 기준선보다 늘어난 종류가 있으면 묶음을 보고 `--show` 로 원인을 찾는다. FORMAT 을 올리지 않고 다시 볼 때는
   `<작업 폴더>\cache\models` 도 지운다.
3. 드레스룸에서 직접 입혀 보는 표본 (몇 벌만, 여성 체형 기준):
   - 하이스쿨 크러쉬 유니폼: 남색 재킷·녹색 넥타이, 목 피부색
   - 검사학교 교복: 남색 몸판·흰 깃
   - 폼폼 소다 웨어: 흰 셔츠 밑 비키니, 하늘색 반바지
   - 몽블랑 원피스: 짙은 회색 원피스·붉은 허리띠 (게임 아이콘과 같은 색)
   - 팬시 기프트 헤드·브리밍 언 헤드(어항)·풍등 모자: 그림과 반투명
   - 베일문 가디언 아머(아이 여성)·캐릭터 1레벨 표준 중갑신발(남성): 꺼내지는지
   - 패션 무기 하나: 대기에선 넣은 자세, 경계 자세에선 손에 든 자세
4. FORMAT 이나 CAB 표 판을 올렸으면, 첫 열기 때 다시 꺼내느라 느리다는 것을 릴리스 노트에 적는다.

## 점검 기준선

2026-11-17, FORMAT 17 · CAB 표 10, 그날 게임 목차 기준이다. 게임 패치로 옷이 늘면 모델 수도 는다.

| 종류 | 건수 | 내용 |
|---|---|---|
| 모델 | 5,406 | 목록 전부 |
| error | 0 | |
| partial | 0 | |
| skin-mesh-not-skin | 4 | 게임 prefab 이 그렇게 둔 것: 시간을 건넌 뉴비웨어(여성·아이 여성)의 속옷 재질, 이름 없는 리본 니트 상의의 속옷 재질, 아이 파이터 글러브의 장갑 재질 |
| color-no-tex | 92 (재질 17종) | 그림이 원래 없는 재질: 의식용 단검 눈 빛 48, 화살 8, 뉴비 마스크 눈 반짝임 4, 기사 깃발 4, 램프 헤드 빛 3, 어항 유리·물 6 (반투명), 컷신용 볼륨 체크 의상 가이드 15, 미스티 코트 스타킹 2 (짙은 타이츠), 캣츠데이 류트 1, 캣츠데이 너클 마네킹 1 |
