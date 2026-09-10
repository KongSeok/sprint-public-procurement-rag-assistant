# 학습 수집 어댑터의 metadata_filters 타입 오류

- 기록 시각: 2026-09-10 13:56 KST
- 대상: 보강 전용 side-v2 수집 스크립트. 제품 런타임 코드는 수정하지 않았다.

## 증상·원인

첫 요청이 `IntegrityError:invalid_metadata_filters`로 중단됐다. 어댑터가 목록 필드인 metadata_filters에 빈 객체를 전달했다.

## 수정·확인

빈 목록으로 수정한 side-v3에서 실검색2건이 완료됐다. side-v2 원시 실패는 archive에 보존했다. 별도 회귀 전체를 실행한 결과는 아니다.

## 예방

대형 모델·인덱스 초기화 전에 RuntimeRequest 생성만으로 요청 스키마를 확인한다. 기본값을 새로 추정하기보다 기존 요청 생성기를 사용한다.
