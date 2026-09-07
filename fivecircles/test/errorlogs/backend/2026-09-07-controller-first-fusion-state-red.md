# 첫 fusion 의미 상태 연결 — 기대 TDD RED

- 기록 시각: 2026-09-07 15:57:49 KST. run=eh-relay-20260907 / batch=EH2.6.c4.2.b.2.
- 상태: 의도된 선행 RED 후 단일 대상 GREEN 확인(1건/19.696초, Coder 보고 exit0). 필수 확대/최종 검증은 대기이며 b.1 PASS를 새 후보 PASS로 해석하지 않는다.

## 최초 검증

- 명령: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.test_controller_first_fusion_state.
- 실제 수집13 / 442.366초 / failure1. Coder가 보고한 process exit1과 원시 unittest FAILED를 구분 확인했다.
  실패는 successor.state가 before_state와 여전히 같은 객체라는 신규 기대 assertion이다. 기존 dispatch-only 계약의 동작이며 b.2가 바꾸려는 지점이다.
- 새 테스트가 기존 TestCase 클래스를 전역 import해 이전12개가 함께 수집됐다. 신규13개가 아니며 이12개는 통과했다.
  Coder는 module alias로 수집 중복을 제거할 예정이다. 최초 결과의13을 소급 변경하거나 collection 감소를 누락으로 숨기지 않는다.

## 원인·후속

- 직전 fusion은 effect/ledger3/transition3만 연결하고 상태를 보존한다. b.2는 exact effect로 첫 항목의 candidate/provisional_missing 상태를 새로 발급하는 명시적 후속이다.
- Sol Ultra가 승인5파일에서 구현·집중/관련 검증 후 고정 보고를 반환한다. 메인 전체/격리와 fresh Astra deep은 이후이며 아직 실행 성공을 기록하지 않는다.
- 이 테스트는 합성 실행이며 KURE/모델/MPS/GPU를 사용하지 않는다. 별도 CPU 실측 어레스트와 원인·수용 기준을 혼동하지 않는다.

## 근거

- 원시 로그: /private/tmp/eh-relay-20260907.GNy8vE/first-fuse-state-focused-red.log
- SHA256: 58f351eee9b2669a6750dea3a5bee46efbbcd222ce75ac0873b5735c16482754
- 계약: ../../../architecture/specs/controller-first-fusion-transition.md의 b.2 개정.
- 폼: ../../../work/2026-09-07-controller-fusion-state-relay.md.
- 단일 GREEN: /private/tmp/eh-relay-20260907.GNy8vE/first-fuse-state-single-green-1.log; SHA256 0575c6a220a5197585152849eb3a5c456db8cefebb0fcb8980fc22f0bd8768b4. unified-session 출력 전사본이며 최종 후보 검증을 대체하지 않는다.

## 최종 확인 — 2026-09-07 17:21 KST

- 집중25(779.422초)·관련202(230.049초)·격리227(944.217초)·전체1611(1161.717초) PASS, 실패/오류/skip0, exit0. fresh Astra first-fuse-state-review-1 PASS. 원래 실패·탐색 전사본은 보존하며 최종 실행과 혼합하지 않는다.
- 이 오류는 현재 후보의 미해결 필수 실패가 아니다. py_compile 대안을 실행한 것으로 소급 기록하지 않는다.
- [최종 배치 기록](../../../work/2026-09-07-controller-fusion-state-relay.md).
