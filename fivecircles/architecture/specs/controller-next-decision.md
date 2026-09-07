# EH2.6.d2.x.a — 첫 전이 이후 다음 행동 선택

상태: 구현·검증 완료 · 2026-09-06. 기준: §16.10, Cycle18 `925f4ab`.

## 목적 / 범위

기존 `decide_controller_action(execution, store, config, runtime)`을 exact revision1 최초 dense successor까지 넓힌다.
revision0 fact/compare의 기존 행동·public signature를 보존한다. revision2, follow-up, fusion/context/reducer,
실제 두 번째 실행과 terminal result 발급은 이 단계가 아니다. provider/model/clock 호출0.

## 선택 규칙

항상 기존 execution live validator와 exact initial transition reader를 먼저 통과한다.
raw consumed lane/hash나 caller outcome을 권위로 삼지 않는다. 첫 obligation의 이미 소비한 dense는 재선택하지 않는다.

| 우선순위 / 조건 | allowed / selected | reason_code |
| --- | --- | --- |
| nonterminal_action_count >= max_nonterminal_actions | untargeted abstain 하나 | action_budget_exhausted |
| exact dense effect=contract_error | untargeted abstain 하나 | contract_error |
| exact dense effect=provider_error | 같은 obligation lexical, abstain | dense_provider_error_diagnostic |
| exact dense effect=applied/empty | 같은 obligation lexical, abstain | first_eligible_nonterminal |

이 최소 slice는 후속 obligation·fuse/context를 미리 eligible로 노출하지 않는다. provider_error 뒤 lexical은
진단 전용이며 fusion/다른 obligation 승격은 금지다. contract-error abstain은 기권 결정이며 아직 terminal
`HarnessRunResult`가 발급됐다는 의미가 아니다. deadline은 시간 authority가 없어 이번 단계에서 판정하지 않는다.
같은 round의 untouched lexical은 `max_retrieval_rounds_per_obligation=1`에도 허용한다.

## DTO / authority / 정책

- ordinal2, current state/ledger/snapshot, exact previous transition SHA를 봉인한다. before/after 의미 state는 같다.
- specs뿐 아니라 reason도 factory 내부에서 유도하고 live authority에 결합·재검증한다. caller reason 입력은 없다.
- terminal reason은 abstain-only, diagnostic reason은 lexical-selected인 closed shape만 허용한다.
- 같은 snapshot 반복/동시 발급은 same-object이고 GC remint/clone/mixed/tuple·source·effect 변조는 거절한다.
- 기존 policy hash payload의 revision-zero-only 선언을 새 slice에 맞게 명시적으로 갱신한다.
  초기 행동·signature는 같지만 새 process의 action/decision SHA는 달라진다. 동일 실행 내 action identity는 stable이다.
  baseline/index/golden/config는 바꾸지 않으며 역사 receipt를 새 policy로 덮어쓰지 않는다.

## 검증 및 인계

- fact/compare applied/empty/provider/contract-error·budget1·round1, consumed dense 재선택 금지, chain/ordinal.
- repeated/barrier concurrent same-object, previous decision 유지, source/effect/ledger drift 및 추가 호출0.
- c4.1의 '두 번째 decision 미지원' 테스트는 새 기능 경계에 맞춰 'advance 자체는 두 번째 dispatch 없음'으로 갱신한다.
- focused→initial/transition/history 인접→policy/shared validator 전체 회귀를 수행하고 독립 리뷰한다.
- d2.x 부모는 PARTIAL 유지; 다음은 감사로 선택하는 후속 matrix 또는 c4.2 dispatch leaf다.

검증: 신규11 포함 인접79 PASS, 전체1522 PASS(186.315초, errors/failures/skips0), 독립 APPROVE.
후속 순서: c4.2.a lexical dispatch/revision2 → d2.x.b outcome/fusion 자격 → 후속 reducer.
lexical은 새 obligations를 발급하지 않고 exact dense receipt가 보존한 obligation을 재사용해야 한다.

## EH2.6.d2.x.b.1 — revision2 이후 ordinal3 decision (2026-09-07)

상태: 승인된 릴레이 범위 안의 구현 계약. 위 d2.x.a 설명은 revision0/1의 역사적 범위이며,
이 절은 c4.2.a가 발급한 revision2에만 추가 적용한다. public 함수 signature와 revision0/1 동작은 보존한다.

### 입력과 exact-history 경계

- 기존 `decide_controller_action(execution, store, config, runtime)`이 exact revision2 fact/compare
  첫 obligation의 ordinal3 decision을 발급한다. caller outcome/source receipt/evidence/obligation 입력은 없다.
- 먼저 live execution validator와 revision2 lexical reader를 통과하고, execution authority가 보존한
  immediate predecessor의 revision1 dense reader를 통과한다. 두 reader의 exact effect/source chain이 권위다.
- 같은 stable execution root, 첫 obligation, round1, exact predecessor/transition chain, store/config/runtime,
  query/scope를 유지한 dense·lexical pair만 판정한다. ledger revision2/count2/소비 tuple은 일치 검사이며 권위 원천이 아니다.
- 기존 private authority/readback을 재사용한다. compare 전체 obligation tuple 재발급이나 sibling 보존 확대는 하지 않는다.

### 결정 우선순위와 닫힌 결과

| 순서 / 조건 | allowed_actions (첫 항목 selected) | reason_code |
| --- | --- | --- |
| 검증된 count >= max_nonterminal_actions | untargeted abstain 하나 | action_budget_exhausted |
| 두 exact lane effect 중 contract_error 있음 | untargeted abstain 하나 | contract_error |
| 두 exact lane effect 중 provider_error 있음 | untargeted abstain 하나 | provider_error |
| 두 effect가 각각 applied 또는 empty | 첫 obligation fuse, untargeted abstain | first_eligible_nonterminal |

- 위 검증을 모두 마친 뒤 우선순위를 적용한다. 변조·미지원 outcome은 정상 abstain으로 덮지 않고 거부한다.
- 정상/empty의 네 조합은 모두 fuse 자격이 있다. all-empty도 fusion 이전의 의미 상태 승격이나 missing 확정을 하지 않는다.
- dense provider_error + 성공 lexical도 provider_error 기권이다. lexical contract_error가 겹치면 contract_error가
  우선하되 dense 오류 source/effect는 그대로 보존한다. max_actions=2이면 budget 우선, 3이면 fuse 선택 가능하다.
- `provider_error`는 새 고정 sanitized reason이며 revision2/ordinal3의 abstain-only에만 허용한다.
  contract_error/action_budget_exhausted는 기존 revision1과 새 revision2에만 허용한다.
  dense_provider_error_diagnostic은 기존 revision1 lexical-selected에만 허용한다.
- revision2의 정상 결과는 정확히 (fuse, abstain)이며 다른 obligation·소비 lane·context·verify·stop을 노출하지 않는다.
  기권 decision은 아직 terminal 실행이나 HarnessRunResult가 아니다.

### 결속·부작용·정책

- ordinal3, current state/ledger/snapshot, exact transition2 SHA를 봉인한다. stable action identity와
  selected-first, repeat/concurrent same-object, live snapshot GC remint 금지 및 clone/mixed 거부를 유지한다.
- 결정 발급과 검증은 lane/fusion/provider/model/clock 호출0, claim/ledger/state/transition 변경0이다.
  이미 발급한 revision0/1 decision과 양쪽 source chain은 계속 유효하고 오류 결과를 지우지 않는다.
- 기존 decision policy hash payload에 revision0/1/2 범위와 위 matrix를 명시한다. 새 process의 action/decision SHA는
  바뀔 수 있으나 config/baseline/evaluation hash와 역사 receipt는 고치지 않는다. 새 authority framework는 만들지 않는다.
- fusion 실행/claim 완료/effect/revision3/semantic reducer/terminal issuance/public start-step-run,
  follow-up/후속 compare obligation/deadline은 비범위다. 전체 d2.x.b와 Controller/E2E는 PARTIAL 유지한다.

### 검증과 후속

- fact/compare 두 source outcome matrix, budget2/3, round1, both-empty, dense diagnostic 오류 보존과 추가 호출0.
- ordinal3/transition2·이전 decision 유효, 반복/동시 same-object·GC remint 거부, clone/mixed 및
  source/effect/ledger/transition/reason/tuple drift 거부. 기존 lexical의 'ordinal3 미지원' 단언만 새 기권 결과에 맞춘다.
- focused/인접 controller·전체 synthetic 회귀와 같은 후보 fresh 검수 후 통합한다.
  실제 provider/API/Langfuse/VLM/gold 실행과 품질 개선 주장은 없다.
- 다음 후보는 첫 obligation의 선택된 fuse 실행 수직 단위이며 별도 설계가 필요하다.
  다른 compare obligation 실행 전에 full sibling-obligation lifetime 계약을 별도로 해결한다.

## EH2.6.d2.x.b.2 — First post-fusion ordinal4 decision (2026-09-07)

### Goal, supersession and inputs

Extend the existing decide_controller_action(execution, store, config, runtime) only to the exact
revision3 fact/compare first-obligation successor issued under c4.2.b.2. Earlier revision0/1/2
behavior and public signatures remain unchanged. The prior next-decision sections and first-fusion
contract's ordinal4 exclusion describe historical slices; this amendment selects ordinal4 decision
only, not the execution of the selected action. Historical receipts and PASS records are unchanged.

Require live execution/state validation and the exact first-fusion transition reader, then recover
its retained revision2 lexical and revision1 dense predecessors and original source owner. Require
the same stable root, first obligation, round1, store/config/runtime, query/scope and exact three-source
chain. Reuse existing authority/readback helpers; caller hashes, ledger counts, structural DTOs and
EH2.5 preview actions are not mint authority. Do not remint any retrieval or semantic obligation.

The current first entry must exactly match the authenticated fusion effect: applied means candidate
with the identical ordered nonempty candidate IDs; empty means provisional_missing with no candidates.
Verified IDs remain empty. Preserve untouched sibling identities, effect provenance, open progress,
coverage0.0, in_progress and false terminal gates. Require ledger3/count3, exact three consumed action
hashes, the original two consumed lanes, round1 and zero no-progress/unavailable history. Reject
unsupported, cloned, mixed, inconsistent or drifted histories before applying budget or normal reasons.
No dense-error/diagnostic lexical graph can become a valid revision3 input.

### Closed decision matrix

| Validated condition, in order | allowed_actions, selected first | reason_code |
| --- | --- | --- |
| count3 >= max_nonterminal_actions | untargeted abstain only | action_budget_exhausted |
| applied fusion and exact candidate entry | expand_parent(first obligation, first bounded seed), untargeted abstain | first_eligible_nonterminal |
| empty fusion and exact provisional_missing entry | verify_slot(first obligation, no evidence target), untargeted abstain | first_eligible_nonterminal |

For applied fusion, derive context quota from the exact retained owner plan and execution config:
min(max_context_targets_per_obligation, owner final_evidence_budget, owner rerank_k, candidate_count).
Use the existing owner budget semantics and require their positive bounded values. The bounded seed
prefix is sorted(candidate IDs)[:quota], matching _context_seed_evidence_ids; select only its first
ID. Sorting determines a context target, never changes the fusion/state candidate order. Derive this
read-only from authenticated source ownership without issuing a SemanticVerificationObligation or
context receipt. Reuse available pure owner-budget logic; do not introduce a parallel framework.
Parent context is a store-backed prerequisite, not semantic support and not a model capability claim.

For empty fusion, verify_slot is solely the existing zero-provider bounded exhaustion-check intent
from technical section16.10. It does not issue an absence receipt, invoke a verifier, establish global
absence, or change provisional_missing. max_retrieval_rounds_per_obligation remains pinned to 1;
a value of 2 is rejected before dispatch, and this v1 slice does not retry. Missing semantic-verifier
capability must not turn an
empty result into confirmed absence, nor trigger provider work during decision issuance.

No other target/action is exposed: no later parent seed, table/figure bridge, rerank, nonempty semantic
verify, later compare obligation, repeated lane/fuse, stop, follow-up, deadline or general terminal
matrix. These require subsequent exact dispatch/state contracts. Do not use actions.py EH2.5 preview
to add unconditional rerank/verify actions.

### Sealing and zero-side-effect behavior

Seal ordinal4, current derived state/ledger/snapshot and exact transition3 SHA through the existing
ControllerDecisionReceipt/action authority. Extend the existing closed payload reason-shape validator
and live reason/action rederivation for revision3. action_budget_exhausted gains revision3 only;
contract_error/provider_error/dense diagnostic retain their earlier revision restrictions.
Revise the existing policy hash payload explicitly for revision0/1/2/3 and this matrix. New-process
action/decision hashes may change; configuration/baseline/evaluation hashes and historical evidence
do not. Preserve action identity within the process and every earlier decision's validity.

Repeat/barrier-concurrent calls yield the same live decision object. GC does not permit remint while
the snapshot remains live. Keep existing identity mirrors, dependency pins and drift rejection.
Decision issuance/readback performs no provider, model, clock, retrieval, fusion, context, rerank,
verifier or absence execution; no source/semantic/context receipt mint, claim consumption, state,
ledger, no-progress, transition or capability-unavailable mutation. Existing source/predecessor
readback remains non-dispatching. The ordinal4 permit is not an implemented fourth executor.

### Acceptance and handoff

Test real synthetic dense -> lexical -> fusion/state -> ordinal4 for fact and compare, all four
applied/empty pairs and lexical rescue. Check budgets3/4, authentic round1 and rejection of round cap2
before any dispatch, unavailable verifier
without fabricated capability results, exact first seed under owner/config bounds, retained fusion
candidate order and untouched siblings. Verify repeated/concurrent identity, GC tombstone, earlier
decisions/source lifetime, and clone/mixed/state/effect/source/owner-budget/ledger/transition/reason/
target/dependency drift rejection, including zero additional work and no partial decision on failure.
Replace only obsolete ordinal4-unsupported assertions; keep unsupported later revisions rejected.

Coder runs focused and affected adjacent synthetic tests; main gathers one final frozen-candidate
isolated and full regression at the integration boundary. Require fresh deep review of decision,
state/source ownership and downstream permit/readback boundaries. Reuse prior report sections only
where fingerprint identity holds and explicitly show this contract delta. Keep Controller/E2E and
parent c4.2.b/d2.x.b PARTIAL. No production performance claim, profiling, external execution,
DIAG131/data/gold/config/dependency change or publication-scanner exception is authorized.
