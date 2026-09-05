# EH2.6.d1 Execution Aggregate 독립 리뷰

- 날짜: 2026-09-05
- 범위: `ExecutionLedger`, `HarnessExecution`, package factory/validator, 계약과 focused gate
- 판정: **APPROVE — 남은 P0/P1 없음**
- 외부 실행: API·model·Langfuse·golden·VLM·provider·clock 0회

## 확인한 경계

- controller ledger는 b3의 `_RetrievalExecutionLedger`와 책임·수명이 분리돼 있다.
- exact initial state/store/config/runtime에서만 revision 0, zero-consumption aggregate가 발급된다.
- 동일 root의 반복 발급은 같은 객체를 반환하고 32-thread 동시 발급도 single winner다.
- stable `execution_identity_sha256`와 state/ledger를 포함한 `execution_snapshot_sha256`가 분리돼 있다.
- clone, nested identity drift, coherent mixed dependency, serialization/from-dict/asdict, GC 뒤 재발급이
  live authority로 승격되지 않는다.
- d2 decision permit, c4 effect mint/reducer, d3 start/step/run public surface는 계속 부재한다.

## 첫 리뷰의 P1과 수리

1. dataclass `asdict`가 nested state를 재귀 노출할 수 있었다.
   - `HarnessExecution`을 dataclass가 아닌 immutable slots value로 바꿔 `asdict` 경로를 차단했다.
2. d1 helper의 module-global drift pin이 빠져 있었다.
   - d1 global/function/class namespace와 code/default/kwdefault identity를 함께 봉인했다.
3. 이미 검색된 compare seed가 initial aggregate로 들어올 수 있었다.
   - `e1_compare_seed_not_unsearched`로 initial-only 조건을 fail-closed 처리했다.
4. `execution_sha256` 한 이름이 stable effect binding과 mutable snapshot 의미를 섞었다.
   - stable `execution_identity_sha256`와 changing `execution_snapshot_sha256`로 분리했다.

## 재검토 정정

리뷰 중 `_require_hash`가 `_HEX64` global에 의존한다는 추가 지적은 다른 모듈과의 혼동이었다.
실제 구현은 pinned function code 내부에서 길이 64와 literal hex alphabet을 검사한다. 존재하지 않는
global을 새로 추가하지 않고 해당 수정은 되돌렸다. 재검토자는 이 사실을 확인하고 최종 승인했다.

## 검증 영수증

- focused: 10/10 PASS
- 관련 회귀: 234/234 PASS
- 전체 회귀: 1,298/1,298 PASS
- repository safety: 868 files PASS
- 독립 재리뷰: APPROVE, P0/P1 0

이 판정은 d1 구현 무결성 승인이다. retrieval 품질 향상이나 controller E2E 완료 판정은 아니다.
