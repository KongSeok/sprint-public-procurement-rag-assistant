# EH2.6.d2.i Controller Decision Permit 리뷰

기준: 2026-09-05 · 브랜치 `feat/total-integration`

## 판정

`APPROVE` — EH2.6.d2.i의 제한된 revision-0 범위에서 P0/P1 문제는 없다. 다만 parent
`EH2.6.d2` 전체는 완료가 아니며, `EH2.6.c4.0`과 `c4.1` 이후 `d2.x`가 끝날 때까지 열린 상태로 둔다.

## 먼저 발견한 구조 공백과 조치

최초 계약 감사에서 다음 P1 공백을 확인했다.

- 기존 ledger에는 lane 소비 여부만 있고 성공·오류·불가 같은 outcome이 없어 cross-state `fuse` 허용을
  안전하게 판정할 수 없다.
- 현재 aggregate만으로 parent/bridge source owner, follow-up outcome, owner별 budget을 복구할 수 없다.
- 기존 parent/bridge issuer는 batch 단위라 controller의 per-target action과 직접 연결되지 않는다.
- structural `ActionEffectReceipt`를 live transition authority로 승격하는 정식 bridge가 없다.
- unavailable capability는 첫 시도 전에 숨기면 안 된다. 한 번 선택해 zero-call unavailable effect를 남긴 뒤
  같은 stable action을 다시 선택하지 않도록 ledger가 소비해야 한다.

따라서 전체 d2를 억지로 닫지 않고 다음 순서로 분할했다.

1. `d2.i`: exact revision-0 initial decision permit.
2. `c4.0`: source/outcome/per-target transition authority.
3. `c4.1`: initial selected action의 effect mint와 ledger advance.
4. `d2.x`: transition-aware cross-state decision matrix.
5. `c4.2`: full reducer 연결.

## 구현 범위

- immutable non-dataclass `ControllerAction`, `ControllerDecisionReceipt`.
- exact live revision-0 `fact|compare`, 모든 obligation이 `unsearched`, empty last transition에서만 발급.
- obligation-major `retrieve_dense → retrieve_lexical` canonical action order와 마지막 `abstain`.
- 첫 action만 selected action으로 묶고 ordinal 1, stable execution identity, current snapshot/state/ledger hash를
  decision hash에 봉인.
- 동일 snapshot idempotence, 32-thread single winner, root GC 뒤 재발급을 막는 tombstone.
- clone, nested action 교체, mixed dependency, subclass, drift와 EH2.5 preview/structural effect의 authority 승격 차단.
- public issuer/replay/from-dict/previous-decision 인자는 노출하지 않으며 provider·clock·effect/reducer 호출은 0.

## 비범위

- effect mint, source receipt 발급, ledger consume/advance, state transition/reducer.
- revision 1 이상, follow-up/candidate state, capability/filter outcome 기반 다음 action.
- controller start/step/run, terminal result, 실제 retrieval/generation/golden/Langfuse 실행.

## 검증

- d2.i focused: 8/8 PASS.
- d1+d2.i 결합: 18/18 PASS.
- execution/controller 관련 회귀: 278/278 PASS.
- 전체 회귀: 1,306/1,306 PASS.
- repository safety: 873 files PASS.
- 독립 적대적 리뷰: private token 위조와 decision GC 뒤 action 보관 공격까지 재검증, P0/P1 0건.
- 외부 호출: API/OpenAI/model/Langfuse/golden/VLM/provider/clock 0회.

## 다음 gate

다음 READY leaf는 `EH2.6.c4.0`이다. source receipt의 owner·target·outcome을 execution transition history와
정확히 결합하는 권한을 먼저 만든 뒤에만 initial effect와 cross-state decision을 연다.
