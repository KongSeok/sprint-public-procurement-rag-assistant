# Controller initial transition — test-first 기록

- 기록 시각: 2026-09-06 14:21 KST. RED는 같은 Cycle18의 구현 전 실행이다.
- 범위: `tests.test_controller_initial_transition`, 실제 corpus/API/model 호출 없음.
- 예상 RED: 신규 transition API 구현 전 11 tests, errors17(subtests 포함), 모두 미구현 API AttributeError였다.
- 교정: 계약대로 live effect/history, ledger1/transition, predecessor를 보존하는 successor 발급을 구현했다.
- 리뷰 보강: 전후 연결 hash, barrier 동시성, tuple/source 변조, 발급 중간 예외→failed 소비를 추가했다.
- 결과: 신규13 PASS, 인접합91 PASS, 전체1511 PASS(174.977초, errors/failures/skipped0, exit0).
- 예방: provider_error receipt의 정상 전이와 발급 도중 예외를 별도 테스트한다. 전후 state/ledger/decision/effect 연결을 직접 검사한다.
- 원장: `../../../work/2026-09-06-controller-initial-transition-relay.md`.
