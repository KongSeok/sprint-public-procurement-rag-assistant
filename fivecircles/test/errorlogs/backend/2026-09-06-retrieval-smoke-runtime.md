# Offline KURE smoke 런타임 검증

- 시각: 2026-09-06 06:28 KST.
- 첫 실제 실행: bundle/page/dense/lexical 로드 후 query 기록 전 중단. 001 폴더는 plan/draft만 있고 완료 receipt가 없다.
- 원인 재현: dense import 시 HF cache 상수가 먼저 고정되어 이후 환경 설정과 불일치. 토크나이저 probe가 local cache missing으로 실패했다.
- 수정: HF_HOME/HF_HUB_CACHE/offline을 프로세스 시작 전에 설정하고 runtime 상수 불일치 fail-fast 회귀를 추가했다.
- 경계: 001은 자동 삭제·덮어쓰지 않는다. 모델 호출 수를 실패 로그가 없다는 이유로 0으로 추정하지 않는다. API/생성 경로는 사용하지 않았다.
- 환경: sysctl RAM 읽기는 sandbox에서 거절되어 승인된 읽기 재실행으로 64GiB 확인; 디스크823GiB 여유.
- 합성: smoke5/recorder12/draft8/inputs15 총40 PASS(0.383s). 독립 리뷰는 수정 전 smoke4 포함24 PASS/APPROVE.
- 실제 재실행은 새 002 폴더에서 진행. stdout에 질의 원문 대신 arm/round/ordinal만 기록하도록 보강했다.
- 결과:002 실제12회 PASS/API·생성0, 파일 불변·반복 후보 일치. 관련93 PASS/독립 최종 APPROVE.
- 후속 effective TRANSFORMERS_CACHE gate는 합성/별도 preflight로 확인했고, 진행 중이던002 코드에 소급 적용했다고 세지 않는다.
- 반복 후보 jq 확인의 배열 접근 오류1은 식을 바로잡아 page/child/hybrid 모두 일치로 재검증했다.
