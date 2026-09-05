# EH2.6.c4.0.d per-target context accumulator 리뷰

기준: 2026-09-05 · 브랜치 `feat/total-integration`

## 판정

`APPROVE` — 최종 독립 correctness review에서 P0/P1 문제를 찾지 못했다. bounded context candidate
계약과 구현이 일치하며 남은 correctness blocker는 0건이다.

## 리뷰 범위

- exact live semantic obligation과 `_context_seed_evidence_ids`가 함께 정한 bounded target.
- `expand_parent|bridge_table|bridge_figure` closed action set과 target별 receipt exact-one 선택.
- rerank prerequisite에 사용한 complete parent/bridge tuple의 same-object identity와 canonical order.
- caller receipt/batch/hash/outcome 주입, missing/duplicate/wrong-role/cross-root/clone/reorder 변조 차단.
- repeated/concurrent single live value, live semantic root의 GC remint tombstone, dead-root passive cleanup.
- captured helper와 runtime dependency drift가 selection authority로 승격하지 않는지.
- private value가 effect, claim, reducer, transition 또는 provider/model/clock 호출 권한이 아닌지.

## 결과

- focused: 13/13 PASS.
- context/controller/source 인접: 175/175 PASS.
- full regression: 1,372/1,372 PASS.
- repository safety: 883 files PASS.
- `git diff --check`: PASS.
- 독립 최종 correctness review: `APPROVE`, blocker 0건.
- 외부 호출: API/OpenAI/model/Langfuse/golden/VLM/provider/clock 0회.
- 이 결과는 accumulator 권한·회귀 무결성 검증이며 retrieval 품질 향상 수치가 아니다.

## 리뷰 과정의 수리

1. captured `matching_receipts` helper code를 교체하면 wrong-role receipt를 선택할 수 있던 경로를
   helper code/defaults/closure pin으로 fail-closed했다.
2. executable weakref callback을 제거했다. result가 사라져도 exact semantic root가 살아 있으면 remint를
   막고, root까지 사라지면 다음 accumulator/read가 authority·cache/shadow·tombstone·root-key mirror를
   함께 수거하도록 바꿨다.
3. missing/duplicate/wrong-role 강제 변조를 이름 있는 focused regression으로 추가했다.

## 남은 경계

- c4.0.d 결과는 non-authorizing accumulator다. public effect mint나 state transition을 만들지 않는다.
- parent c4.0은 `c4.0.e` structural-effect bridge가 남아 PARTIAL이다.
- c4.1 effect mint/ledger advance, d2.x cross-state decision, reducer/transition은 아직 권한이 없다.
- 다음 READY는 c4.0.c의 exact step source와 c4.0.d의 exact target context를 결합하되 public mint와
  provider/clock 호출을 계속 0으로 유지하는 `EH2.6.c4.0.e`다.
