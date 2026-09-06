# 다음 decision — RED와 fixture 교정

- 기록: 2026-09-06 14:34 KST, Cycle19.
- 첫 실패: 새 fixture에 max_rounds=2를 임의 기본값으로 넣어 기존 `retrieval_rounds_not_pinned_to_one` 계약에서 실패했다.
- 교정: production 검증을 바꾸지 않고 fixture를 기존 pin1로 복구했다. 같은 round의 lexical 자격만 검증한다.
- 구현 중간 tree 재실행은 reason 인자 전파가 아직 끝나지 않은 시점과 겹쳤으므로 납품 검증으로 사용하지 않았다.
- 순수 RED: 고정된 Cycle18 source 임시 트리에 새 테스트/fixture만 복사해 신규9 tests/errors25,
  `controller_decision_cross_state_not_ready`를 확인했다(6.047초). 구현 이후 focused/full 결과는 Cycle19 원장에 추가한다.
- 예방: 공통 fixture 옵션을 늘릴 때 실제 config signature와 pinned scalar 계약을 먼저 확인한다.
  병렬 구현 중 RED는 고정된 이전 source로 검사하고, 통합 테스트는 작성자가 변경을 멈춘 뒤 실행한다.
- 교정 후: 신규11 포함 인접79 PASS, 전체1522 PASS(186.315초, errors/failures/skips0, exit0), 독립 APPROVE.
- 원장: `../../../work/2026-09-06-controller-next-decision-relay.md`.
