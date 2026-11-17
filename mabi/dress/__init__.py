"""드레스룸 — 게임 설치 폴더의 의상 3D 자산을 읽어(읽기만) 데이터 폴더에 복사본으로 두고 뷰어(web/dressroom)에 넘긴다.

assets   AssetPackages 목차·번들 꺼내기·CAB 참조 따라 열기
catalog  자산 경로 → 체형·부위별 모델 목록
export   모델 → 메시 묶음(json+bin)·텍스처 png
service  위 셋을 묶어 캐시를 관리 (게임 목차가 바뀌면 비운다)
"""
