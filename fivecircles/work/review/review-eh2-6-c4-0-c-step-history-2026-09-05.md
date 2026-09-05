# EH2.6.c4.0.c one-step claim/history 리뷰

기준: 2026-09-05 · 브랜치 `feat/total-integration`

## 판정

`APPROVE` — repaired GC callback과 source-epoch failure path가 조합된 drift 경로에서도
terminal tombstone을 유지함을 독립 최종 리뷰로 재확인했다. 남은 correctness blocker는 0건이다.

## 리뷰 범위

- exact `(execution identity, decision ordinal, before snapshot, selected action identity)` step key.
- `pristine→claimed→sourced` 실제 경계와 예약된 `effect-bound→transitioned`, terminal `failed` FSM.
- exact claim만 projection을 prepare·source bind할 수 있는지, direct c4.0.b projection이 권한으로
  승격하지 않는지.
- lane provider 직전 source-attempt epoch와 claim cutoff으로 claim 전 시작·완료된 receipt를
  사후 포장할 수 없는지.
- duplicate/concurrent claim, out-of-order, clone/mixed root, forced mutation, dependency drift,
  claim/projection/execution GC와 post-child failure가 failed tombstone을 유지하는지.
- 실패한 provider/receipt mint 경로의 pending source-attempt permit를 exact discard하고 weak registry가
  executable callback 없이 이중 mirror를 검증·정리하는지.

## 결과

- focused: 30/30 PASS.
- controller/source 인접: 249/249 PASS.
- full regression: 1,359/1,359 PASS.
- repository safety: 881 files PASS.
- `git diff --check`: PASS.
- 독립 최종 correctness review: `APPROVE`, blocker 0건.
- 외부 호출: API/OpenAI/model/Langfuse/golden/VLM/provider/clock 0회.
- 이 결과는 temporal authority와 회귀 무결성 검증이며 retrieval 품질 향상 수치가 아니다.

## 계약 적합성

- c4.0.c는 provider/clock을 호출하지 않고 public effect, reducer, ledger advance, state transition을
  발급하지 않는다.
- temporal provenance를 직접 연 경로는 live `LaneSearchReceipt`와 terminal controller decision으로
  제한되며, 그 밖 source kind는 exact dispatch hook이 있는 후속 leaf 전까지 fail-closed다.
- `prepared`는 public status가 아닌 claimed 내부 substate며 bare effect/transition object는 history를
  진행시키지 못한다.

## 남은 경계

- parent c4.0은 PARTIAL이다. `c4.0.d` per-target accumulator와 `c4.0.e` structural-effect bridge가
  남아 있다.
- c4.1 effect mint/ledger advance, d2.x cross-state decision, reducer/transition은 아직 권한이 없다.
- 다음 READY는 validated selected target에서 parent/table/figure exact-one을 고르면서 rerank가
  요구하는 complete parent/bridge batch identity와 canonical order를 보존하는 `EH2.6.c4.0.d`다.
