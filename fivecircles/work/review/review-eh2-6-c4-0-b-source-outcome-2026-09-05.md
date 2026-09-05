# EH2.6.c4.0.b typed source/outcome resolver 리뷰

날짜: 2026-09-05

브랜치: `feat/total-integration`

대상: `src/midprojectrag/orchestration/execution_contracts.py`,
`tests/test_controller_source_outcome_resolver.py`

## 판정

`APPROVE`. 구현·회귀·안전·브라우저 gate와 독립 최종 재리뷰를 모두 통과했다.
이 leaf는 live effect나 상태 전이를 발급하지 않는 private normalization boundary다.

## 계약 대조

- caller 입력은 exact execution, decision, source receipt, store, config, runtime 여섯 개뿐이다.
- source kind, receipt kind/SHA, native/effect outcome, evidence/context/absence projection과 call flag는
  기존 receipt authority와 live validator에서만 유도한다.
- selected action kind·obligation·target과 c4.0.a exact source root가 일치해야 한다.
- lane/fusion/parent/bridge/rerank/semantic/absence/controller-decision 타입만 closed matrix로 허용한다.
- semantic supported/contradicted는 `applied`로 정규화하고 native disposition을 보존한다.
  unsupported는 이 leaf에서 absence SHA가 없으며, 후속 structural bridge가 exact
  `bounded_no_verified_support` receipt를 결합하기 전에는 effect authority가 아니다.
- provider, clock, effect mint, claim/history, reducer, ledger/state transition은 호출하지 않는다.

## TDD와 수리 기록

1. 첫 RED는 `_resolve_controller_source_outcome` 부재의 `AttributeError`로 확인했다.
2. 첫 GREEN 뒤 강제 attribute 변경과 structural projection clone이 reader 없이 남는 문제를 확인했다.
   identity-mirrored authority, forced-mutation 대조, same-object cache와 GC tombstone을 추가했다.
3. validator/runtime global replacement으로 live receipt drift를 우회할 수 있는 경로를 확인했다.
   resolver dependency를 code/default/global/closure identity에 봉인했다.
4. module-visible issuer 직접 호출 가능성을 확인했다. issuer를 exact resolver implementation code에
   봉인하고 다른 caller 호출을 거부했으며 authority reader/builder 별칭은 초기화 후 삭제했다.
5. reader도 captured exact dependency를 재검증하고 resolver를 다시 실행하도록 폐쇄했다.
6. 수정 중 기존 `_SemanticVerifierParentContext`와 `_RerankerEvidence` class pin의 `_create`가 빠진
   부작용을 diff 감사에서 찾아 즉시 복구했다.

## 검증 결과

- focused resolver: 14/14 PASS
- controller authority/decision 인접: 29/29 PASS
- source validator 인접 묶음: 168/168 PASS
- 전체 회귀: 1,329/1,329 PASS, skip 1
- repository safety: 877 files PASS
- `git diff --check`: PASS
- HTML desktop/mobile: images 2, tables 8, page errors 0, mobile overflow 0 PASS
- 실제 API/OpenAI/model/Langfuse/golden/VLM/provider/clock 호출: 0
- 독립 최종 리뷰: APPROVE, correctness finding 0. focused 14와 별도 인접 49를 재실행하고,
  fusion·parent·table/figure bridge·rerank applied/unavailable·semantic supported·absence의 현재 비선택
  branch를 live exact receipt로 read-only probe해 정규화와 추가 provider call 0을 확인했다.

## 남은 경계

- d2.i가 아직 revision-zero dense 선택만 정식 발급하므로, 나머지 source 종류의 positive decision-bound
  통합은 c4.0.c~e와 d2.x가 실제 permit을 연 뒤 다시 실행한다. 현재는 각 source의 기존 live validator와
  closed mapping을 유지하며 임의 decision/action 발급기를 테스트용으로 열지 않았다.
- 이 projection은 effect 권한이 아니다. c4.0.c claim/history, c4.0.d per-target accumulator,
  c4.0.e structural bridge가 남아 있다.
