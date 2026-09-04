# EH2.6 릴레이샷 실행 폼

## Cycle 1 — EH2.6.b3.r1 executor provenance repair

### 0. Scope Intake

- 요청 범위: 다음 Evidence-Harness 재귀 leaf를 릴레이 방식으로 실행한다.
- 브랜치: `feat/total-integration`; 새 브랜치를 만들지 않는다.
- 사용자 제약: local-first, VLM 변경 없음, 실제 API/model/Langfuse 호출 없음, user-owned dirty 변경 보존.
- 완료 기준: copied-globals executor clone이 ledger transition·permit·valid receipt를 만들지 못하고 기존 정상 lane은 유지된다.
- 위험/확인 필요: b3 완료 뒤 발견된 실행 출처 우회 가능성이므로 b4보다 먼저 닫는다.

### 1. Start Report / Target Check

- 사용할 스킬: `mermaid-flow-report`.
- 기준 타겟 플로우: immutable source → independent lane execution → fusion → bounded controller.
- 현재 플로우: b3 lane/ledger는 구현됐으나 executor frame provenance가 exact code에만 묶여 copied-globals clone 가설이 남았다.
- 점수표/선정 기준: b3.r1 11점, b4 9점, EH2.EVAL.4 6점.
- 상태: COMPLETED.

### 2. Relay Unit Selection

- 사용할 스킬: `relay-shot`.
- 확인한 TODO source: `architecture/todolist.md`, EH2.6 §16.10, 진행 flow report와 checkpoint.
- 점수 상위 후보: b3.r1 = 4+3+2+2+0=11; b4 = 4+3+1+2-1=9.
- 선택한 다음 단위작업: `EH2.6.b3.r1`.
- 플로우폼 반영: 이 문서와 TODO/checkpoint에 반영.
- 상태: `CONTINUE_WITH_NEXT_FORM`.

### 3. Doc / Contract

- 사용할 스킬: `doc-contract-writer`.
- 문서 생성/수정: EH2.6 §16.10, recursive TODO, checkpoint.
- 계약 확인: ledger mutation frame은 issued executor의 exact code와 exact module-global namespace가 모두 같아야 한다.
- 상태: COMPLETED.

### 4. Implementation

- 사용할 스킬: `one-go`, `batch-sequential-runner`.
- 재귀 TODO: b3.r1 한 건을 sequential로 수행한다.
- 수정 대상: `execution_contracts.py`, `test_retrieval_obligations.py`.
- 상태: COMPLETED.

### 5. Validation + Report

- 사용할 스킬: `test-runner`, `mermaid-flow-report`.
- 자동 테스트: b3 focused → related focused → full unittest → safety.
- 빌드/lint: Python import/`git diff --check`.
- Playwright/browser smoke: closeout HTML flow report 렌더에서 수행.
- 현상태 Mermaid 플로우맵: b3 repair 뒤 flow report를 갱신한다.
- 도달 경로 체크: independent lane execution edge의 provenance를 확인한다.
- provider-policy-flow-validation.md 갱신: MidProjectRAG 대상이 아니므로 SKIPPED_WITH_REASON.
- 타겟 노드 연결 점수: 11.
- 상태: TODO.

### 6. Repair Loop

- 실패 원인: exact caller code만 확인하면 같은 code object의 copied-globals clone을 구분하지 못한다.
- 수리 배치: b3.r1.
- 재테스트: b3 단독 37/37, b3+b4 양방향 64/64 PASS.
- 상태: COMPLETED.

### 7. Push / Publication

- git status 확인: 대규모 user-owned dirty 상태; 선택 범위를 별도 확인한다.
- 커밋 범위: EH2.6 b1~b4의 의존 폐쇄 파일과 계약·테스트·로그만 명시적으로 stage한다.
- 커밋: `5c07c4c` (`feat(harness): add exact fusion and E0 control`).
- 푸시: `origin/feat/total-integration` 동기화 완료.
- 상태: COMPLETED.

### 8. Closeout Report

- 사용할 스킬: `mermaid-flow-report`.
- 시작 타겟 대비 최종 현재 플로우: copied-globals clone은 exact code+module-global namespace를 함께
  요구하는 gate에서 provider 0회로 차단된다.
- 남은 GAP/PARTIAL: b4 이후 focused gate와 E1 reducer/controller.
- 다음 점수표 갱신: b4 구현 11점, b5 gate 10점.
- 상태: COMPLETED.

### 9. Relay Shot

- 사용할 스킬: `relay-shot`.
- 확인한 TODO source: `architecture/todolist.md`, 계약 §16.10, checkpoint.
- 다음 후보: b4.
- 선택한 다음 작업: b4.
- 새 원샷딜 시작 여부: 아래 Cycle 2로 연속 실행.
- 멈춘 이유, 있으면: 없음.

### 10. Final Ledger

- Doc: COMPLETED.
- Implementation: COMPLETED.
- Validation: COMPLETED.
- Repair: COMPLETED.
- Push: COMPLETED (`5c07c4c`).
- Report: COMPLETED.
- Relay: CONTINUE_WITH_NEXT_FORM.
- 남은 리스크: 없음. 다음 leaf의 별도 acceptance는 b5에서 판정한다.

## Cycle 2 — EH2.6.b4 same-round fusion / state-free E0

### 0. Scope Intake

- 선택 leaf: `EH2.6.b4`.
- 구현 범위: dense·lexical의 same-round fusion receipt, obligation 순서형 E0 one-shot aggregate,
  public validator와 provider-free 합성 회귀.
- 제외: VLM 변경, 실제 모델/API/Langfuse 호출, E1 reducer/controller, golden 품질 측정.
- 상태: COMPLETED.

### 1. Contract / Implementation

- `FusionReceipt.stage_ordinal=4`: 평가 checkpoint의 optional visual lane 자리(3)를 보존한다.
- fusion은 같은 live obligation의 정상 dense·lexical pair와 exact query/scope/store/config/runtime만 받는다.
- E0는 진입 전에 canonical obligation 전체를 검증·원자 claim하고 obligation별
  dense→lexical→fusion을 끝낸 뒤 다음 obligation으로 이동한다.
- 공개 payload에는 safe evidence/anchor/partition와 child SHA만 남기고 raw query/provider trace,
  state/decision, evaluator/gold/qrels는 두지 않는다.
- 상태: COMPLETED.

### 2. Independent Review / Repair Loop

- 1차 P1: provider callback이 global child executor를 바꾸면 다음 단계가 교체 구현을 신뢰할 수 있었다.
  E0 진입 시 executor/validator identity를 local로 고정하고 모든 provider 반환 뒤 dependency gate,
  exact DTO type, public validator를 재실행하도록 수리했다.
- 2차 P1: 다중 obligation에서 다음 dense lane이 이전 fusion 전에 열릴 수 있었다. lane claim 앞에
  previous-fusion-complete gate를 추가했다.
- 3차 P1: closure cell 자체가 교체되면 code/default/global pin만으로 부족했다. runtime dependency pin에
  closure와 closure-value exact identity를 추가했다.
- 4차 P1: receipt GC 뒤 단일 progress map을 지우면 replay 이력이 사라질 수 있었다. ledger-lifetime
  history를 별도로 두고 progress/history가 같은 immutable tuple object를 가리킬 때만 진행하도록 수리했다.
- final independent review: APPROVE, P0/P1/P2 없음.
- 상태: COMPLETED.

### 3. Validation

- b4 focused: 27/27 PASS.
- b3+b4: 64/64 PASS.
- retrieval 관련 회귀: 214/214 PASS.
- 전체 unittest: 1,175/1,175 PASS, skip/failure 0.
- repository safety: 828 files PASS. 대상 diff-check PASS.
- 실제 API/model/Langfuse 호출: 0.
- 상태: COMPLETED.

### 4. Flow / Closeout

- current flow는 owner obligation → dense → lexical → same-round RRF → state-free E0까지 갱신했다.
- 목표 대비 남은 gap은 b5 focused gate, EH2.6.c~e effect/reducer/E1, EH3 specialist,
  EH4 generation/evaluator, 동일 golden A/B다.
- 다음 READY: `EH2.6.b5`.
- 상태: COMPLETED.

### 5. Push / Relay

- user-owned dirty 파일을 broad-add하지 않고 EH2.6 의존 폐쇄만 선별 stage한다.
- commit/push: `5c07c4c`를 `origin/feat/total-integration`에 푸시했다.
- relay: `CONTINUE_WITH_NEXT_FORM`, 다음 leaf `EH2.6.b5`.
- 상태: COMPLETED.

### 6. Final Ledger

- Doc: COMPLETED.
- Implementation: COMPLETED.
- Validation: COMPLETED.
- Repair: COMPLETED.
- Push: COMPLETED (`5c07c4c`).
- Report: COMPLETED.
- Relay: `CONTINUE_WITH_NEXT_FORM`.
- 다음 READY: `EH2.6.b5`.

## Cycle 3 — EH2.6.b5 focused retrieval gate

### 0. Scope / Decision

- 목적: b3/b4 production surface를 넓히지 않고 네 핵심 실행 의미를 하나의 focused gate로 고정한다.
- 포함: 독립 lane의 lexical-only rescue, fact all-empty, 호출 전 zero-dispatch, provider-error 진단 경계.
- 제외: effect/reducer/E1, 실제 provider/model/API/Langfuse, golden 품질 측정, VLM 변경.
- 판정: 기존 경계가 구현돼 있어 production 코드 추가는 불필요하고 전용 회귀만 추가한다.

### 1. Test Gate

- `b5_r1`: dense normal-empty + lexical applied → stage-4 lexical-only fusion, 양 lane 정확히 1회.
- `b5_r2`: fact 양 lane empty → E0 `empty/execution_complete`, semantic ready/state 필드 없음.
- `b5_r3`: pre-call contract rejection → provider log 0, lexical/fusion child 없음.
- `b5_r4`: dense provider error → lexical 진단 1회, fusion 없음.
- 네 테스트 모두 public validator를 재호출하고 private provider detail 비노출을 확인한다.
- focused: 4/4 PASS. b3+b4+b5 module: 68/68 PASS.

### 2. Review / Result

- 계약·테스트 독립 감사: APPROVE. 누락 P0/P1 없음.
- 선택적 P2였던 validator·비누출 자급 assertion도 전용 gate에 추가했다.
- parent `EH2.6.b` source/runtime/retrieval receipt 기반을 COMPLETED로 닫는다.
- 다음 READY: `EH2.6.c1` follow-up candidate projection.

### 3. Validation / Publication

- 관련 회귀 218/218, 전체 unittest 1,179/1,179, repository safety 829 files PASS.
- commit/push: b5 문서·테스트만 선별 stage하고 사용자 소유 변경은 제외한다.
- 구현·gate commit: `f794915 test(harness): close b5 retrieval gate`.
- push: `origin/feat/total-integration`에 `f794915`까지 동기화했다.
- Relay: `CONTINUE_WITH_NEXT_FORM` → `EH2.6.c1`.
- 상태: COMPLETED.

## Cycle 4 — EH2.6.c1 E1 follow-up safe projection

### 0. One-shot flow form

| 단계 | 상태 | 판정 |
| --- | --- | --- |
| Scope | COMPLETED | `feat/total-integration`, 사용자 dirty/VLM/resources 보존, provider 호출 0 |
| Report | COMPLETED | EH2.5 호환 state와 E1 안전 초기 state의 의미 차이 확인 |
| Relay select | COMPLETED | `EH2.6.c1`, `CONTINUE_WITH_NEXT_FORM` |
| Doc / Contract | COMPLETED | 별도 E1 projection, metadata predicate fail-closed, finite integrity threat boundary |
| Implementation | COMPLETED | test-first public API와 outcome/pin mirror 추가 |
| Validation / Report | COMPLETED | focused7→related60→full1186→safety837, Mermaid PNG/static PASS |
| Repair / Review | COMPLETED | 독립 P1 반복 수리 후 reviewer 3명 최종 APPROVE |
| Push | COMPLETED | c1 대상만 `a9ac527`로 선별 commit/push |
| Closeout | COMPLETED | TODO/checkpoint/update/review/flow ledger 갱신 |
| Relay | COMPLETED | `EH2.6.c2`를 재채점하고 아래 Cycle 5 form으로 진입 |

### 1. Relay score

점수식: `upstream + connection + safety + validation - risk`.

| 후보 | upstream | connection | safety | validation | risk | 합계 | 분류 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| EH2.6.c1 | 4 | 3 | 2 | 2 | 0 | 11 | MATCHED / 선택 |
| EH2.6.c2 | 3 | 3 | 2 | 2 | 1 | 9 | PARTIAL / c1 선행 |
| EH2.EVAL.4 | 2 | 2 | 1 | 1 | 1 | 5 | GAP / 사람·private qrels 필요 |

### 2. Failure log / recurrence guard

- 직전 Cycle 3은 로그올과 push까지 끝났지만 `CONTINUE_WITH_NEXT_FORM` 뒤 새 form을 열지 않고 종료했다.
- 원샷딜 종료 조건을 leaf 완료로 잘못 해석한 프로세스 실패이며 B5 구현 실패는 아니다.
- 열린 사용자 요청과 안전한 READY TODO가 함께 있으면 push 뒤 final을 금지하고 새 form부터 즉시 시작한다.
- 근거: `../test/errorlogs/backend/2026-09-05-one-shot-relay-reentry.md`.

### 3. TDD red

- 신규 `tests.test_e1_followup_projection`을 먼저 추가했다.
- 예상대로 public `build_e1_followup_harness_state` import 부재로 1 module ERROR가 발생했다.
- production 구현 전 계약 부재를 재현한 red이며 다음 단계에서 최소 API로 green 전환한다.

### 4. Implementation / contract

- 전용 `build_e1_followup_harness_state`만 추가하고 EH2.5 compatibility builder/replay는 바꾸지 않았다.
- primary→fallback first-seen dedupe, answer 전체 후보, slot별 sealed-store 동일 doc 후보를 투영한다.
- 기존 verified는 candidate로 강등하고 coverage 0, all-open, stop/abstain false로 시작한다.
- metadata predicate는 EH3.1 filtered-scope receipt 전까지 fail-closed한다.
- runtime integrity는 공개 위조·clone·발급 후 drift·public alias·단일 private pin/registry drift를 막는다.

### 5. Validation / repair / review

- focused 7/7, 관련 60/60, 전체 unittest 1,186/1,186, repository safety 837 files PASS.
- API/OpenAI/model/Langfuse 및 추가 retrieval 호출 0회.
- current Mermaid PNG 재생성·직접 검사와 HTML 자산/상태 정적 참조 PASS.
- HTML browser visual QA는 local file URL 정책으로 environment-blocked이며 우회하지 않았다.
- mutable validator root, 잘못 고친 EH2.5 callsite, single-map forge, validator closure,
  public aliases+single private pin 조합을 순차 수리했다.
- 최종 독립 리뷰: contract/adversarial/authority 모두 APPROVE, P0/P1/P2 없음.

### 6. Push / closeout / relay

- 사용자 소유 dirty 변경을 broad-add하지 않고 c1 code/test/contract/report/log hunk만 선별 stage한다.
- commit/push: `a9ac527` (`feat(harness): add safe followup E1 projection`) 원격 동기화 완료.
- closeout flow: c1 MATCHED, c2 MATCHED/NEXT, EH2.EVAL.4 GAP/WAIT.
- Relay: push 후 `EH2.6.c2` 새 form을 열고 즉시 시작한다.

### 7. Final ledger

- Doc: COMPLETED.
- Implementation: COMPLETED.
- Validation: COMPLETED / PASS_WITH_RISKS (HTML browser visual만 environment-blocked).
- Repair: COMPLETED, 독립 최종 APPROVE 3건.
- Push: COMPLETED (`a9ac527`, `origin/feat/total-integration`).
- Report: COMPLETED, current flow에 c1 노드 추가.
- Flow diagram verification: PARTIAL — c1 MATCHED, c2~E1 controller는 GAP.
- Relay: `CONTINUE_WITH_NEXT_FORM`.
- 남은 리스크: 브라우저 file URL 정책 외 c1 구현 blocker 없음.

## Cycle 5 — EH2.6.c2 semantic verification receipt

### 0. Scope Intake

- 요청 범위: c1 push 뒤 최고 점수 READY TODO인 c2를 계약→구현→검증→푸시→다음 relay로 수행한다.
- 브랜치: `feat/total-integration`; 새 브랜치 생성/병합 없음.
- 사용자 제약: user-owned dirty·VLM·resources 보존, 실제 API/model/Langfuse/golden 실행 0.
- 완료 기준: exact source/runtime verifier만 supplied evidence의 typed semantic receipt를 발급하고 호출 전 거부는 0 dispatch.
- 위험/확인 필요: verifier target/output schema, private authority bridge, unavailable와 actual-call 의미를 먼저 고정한다.
- 상태: COMPLETED.

### 1. Start Report / Target Check

- 사용할 스킬: `mermaid-flow-report`.
- 기준 타겟 플로우: §16.10 E1 `candidate → semantic verify → effect/reducer`.
- 현재 플로우: c1 safe candidate projection까지 MATCHED, semantic receipt부터 GAP.
- 점수표/선정 기준: upstream + connection + safety + validation - risk.
- 상태: COMPLETED.

### 2. Relay Unit Selection

- 사용할 스킬: `relay-shot`.
- 확인한 TODO source: `architecture/todolist.md`, §16.10, module-contract, checkpoint, refreshed flow report.
- 점수 상위 후보: c2=4+3+2+2+0=11, c3=3+3+2+2-1=9, EVAL.4=2+2+1+1-1=5.
- 선택한 다음 단위작업: `EH2.6.c2`.
- 플로우폼 반영: 이 Cycle 5 form.
- 상태: `CONTINUE_WITH_NEXT_FORM` / COMPLETED.

### 3. Doc / Contract

- 사용할 스킬: `doc-contract-writer`.
- 문서 생성/수정: §16.10, module-contract, recursive TODO/checkpoint.
- 계약 확인: source-derived target, closed verifier request/result, typed canonical values, supplied/context 역할,
  production unavailable zero-call, executor-only receipt, c3 state mutation 비범위.
- 계약 결과: fact/compare/follow-up 별 closed factory, private one-argument verifier request, six typed canonical
  value, exact support/contradiction coherence, local at-most-once·post-call revalidation을 §16.10과 module contract에 고정했다.
- 상태: COMPLETED.

### 4. Implementation

- 사용할 스킬: `one-go`, 필요시 `batch-sequential-runner`.
- 재귀 TODO: c2.1 target/schema → c2.2 execution/receipt → c2.3 focused authority gate.
- 수정 대상: `orchestration/action_effects.py`, `execution_contracts.py`, additive public DTO/factory/validator export,
  focused tests. d의 deadline permit 전 production executor는 unavailable zero-call만 가능하다.
- 구현 결과: source-derived factory-only obligation, exact one-call/zero-call verifier execution, closed typed
  normalizer, state-free receipt와 source-lifetime local at-most-once history를 구현했다.
- 상태: COMPLETED.

### 5. Validation + Report

- 사용할 스킬: `test-runner`, `mermaid-flow-report`.
- 자동 테스트: c2 focused 26/26, execution/retrieval/fusion/c1 관련 118/118, full 1,212/1,212,
  safety 846파일 PASS.
- 빌드/lint: write-free imports, target diff-check.
- Playwright/browser smoke: flow HTML; URL 정책 차단 시 기존 비우회 규칙으로 environment-blocked 기록.
- 현상태 Mermaid 플로우맵: semantic receipt current node 추가, PNG 재렌더, HTML images2/tables8/errors0/
  mobile overflow0 PASS.
- 도달 경로 체크: exact source/runtime → one verifier call/zero-call unavailable → typed receipt.
- provider-policy-flow-validation.md 갱신: MidProjectRAG 비대상이므로 SKIPPED_WITH_REASON.
- 타겟 노드 연결 점수: 11.
- 상태: COMPLETED.

### 6. Repair Loop

- 실패 원인: system Python dependency 누락, report Playwright runtime 탐색 실패, transitive global pin·receipt
  close ordering·source history 수명·private request constructor/pickle 경계와 acceptance coverage 누락.
- 수리 배치: repo `.venv` 고정, bundled Playwright+installed Chrome, reachable pin/receipt-before-completion,
  source weak cleanup, token factory+serialization guard, post-call/request/GC/mismatch/empty/disposition tests.
- 재테스트: focused 정·역순 26/26, related118, full1212, safety와 독립 최종 APPROVE 2건.
- 상태: COMPLETED.

### 7. Push / Publication

- git status 확인: 대규모 user-owned dirty에서 c2 의존 폐쇄 22파일/hunk만 선별했다.
- 커밋 범위: c2 code/test/contract/report/log hunk. resources·gold·VLM·기타 사용자 변경 제외.
- 커밋/푸시: `05fc4cc` (`feat(harness): add semantic verification receipts`)를
  `origin/feat/total-integration`에 push했다.
- 상태: COMPLETED.

### 8. Closeout Report

- 사용할 스킬: `mermaid-flow-report`.
- 시작 타겟 대비 최종 현재 플로우: c1 candidate → exact semantic receipt까지 MATCHED.
- 남은 GAP/PARTIAL: c3 effect/absence, c4 reducer, c5 semantic transition gate, d controller, EH2.G E2E.
- 다음 점수표: c3=4+3+2+2-1=10, c4=3+3+2+2-1=9, EVAL.4=2+2+1+1-1=5.
- 상태: COMPLETED.

### 9. Relay Shot

- 사용할 스킬: `relay-shot`.
- 확인한 TODO source/다음 후보: TODO §EH2.6.c와 계약 §16.10, 다음 최고 READY `EH2.6.c3`.
- 새 원샷딜 시작 여부: 아래 Cycle 6 form을 생성하고 즉시 시작한다.
- 멈춘 이유, 있으면: 없음.
- 상태: `CONTINUE_WITH_NEXT_FORM` / COMPLETED.

### 10. Final Ledger

- Doc / Implementation / Validation / Repair / Push / Report / Relay: COMPLETED.
- Flow diagram verification: PARTIAL — semantic receipt까지 MATCHED, c3 effect/absence부터 GAP.
- 남은 리스크: c2 receipt는 state-free이며 c3 effect/absence와 c4 reducer가 아직 없다. 실제 품질 우승은
  동일 golden E2E 전까지 주장하지 않는다.

## Cycle 6 — EH2.6.c3.1 parent/bridge source receipts

### 0. Scope Intake

- 요청 범위: c2 push 뒤 최고 점수 READY TODO인 c3를 재귀 분할하고 첫 leaf c3.1을
  계약→TDD→구현→검증→푸시→다음 relay로 수행한다.
- 브랜치: `feat/total-integration`; 새 브랜치 생성/병합 없음.
- 사용자 제약: user-owned dirty·VLM·resources 보존, 실제 API/model/Langfuse/golden 실행 0.
- 완료 기준: immutable candidate seed prefix에서 parent=context-only와 table/figure actual bridge
  `applied|empty`를 caller ID 없이 봉인하고 root-lifetime at-most-once를 검증한다.
- 위험/확인 필요: source owner matrix, evidence 승격 규칙, absence의 충분조건과 replay/lifetime을 코드 전 고정한다.
- 상태: COMPLETED.

### 1. Start Report / Target Check

- 사용할 스킬: `mermaid-flow-report`.
- 기준 타겟 플로우: §16.10 `typed source receipt → rerank/derived semantic → absence/effect → reducer`.
- 현재 플로우: c2 exact semantic receipt까지 MATCHED, parent/bridge source부터 GAP.
- 점수표/선정 기준: c3.1=10, c3.2=10, c3.3=8, c4=7(BLOCKED_BY_d2), EVAL.4=5.
- 상태: COMPLETED.

### 2. Relay Unit Selection

- 사용할 스킬: `relay-shot`.
- 확인한 TODO source: refreshed flow report, TODO §EH2.6.c, 계약 §16.10, checkpoint/module contract.
- 점수 상위 후보: c3 10, c4 9, EVAL.4 5.
- 선택한 다음 단위작업: `EH2.6.c3.1`.
- 플로우폼 반영: 이 Cycle 6 form과 c3.1~c3.3 재귀 TODO.
- 상태: `CONTINUE_WITH_NEXT_FORM` / COMPLETED.

### 3. Doc / Contract

- 사용할 스킬: `doc-contract-writer`.
- 문서 생성/수정: §16.10, module-contract, recursive TODO/checkpoint.
- 계약 확인: source-owned factory, closed outcome/projection, parent nonpromotion, bridge actual linkage,
  rerank subset/permutation, semantic verify projection, bounded absence 충분조건·금지사유.
- 계약 결과: parent의 evidence ID 부재, rerank source receipt 부재, d2 controller decision 선행 의존을 확인했다.
  c3는 parent/bridge/rerank/absence source receipt와 effect DTO/validator를 닫고, public effect mint는 d2 permit
  전까지 금지한다. EH2.5 preview는 실행 권한으로 재사용하지 않는다.
- 상태: COMPLETED.

### 4. Implementation

- 사용할 스킬: `one-go`, 재귀 leaf는 `batch-sequential-runner`.
- 재귀 TODO: c3.0 계약교정 → c3.1 context receipt → c3.2 rerank/derived semantic → c3.3 absence →
  c3.4 closed effect DTO → c3.5 authority/회귀 gate.
- 수정 대상: `execution_contracts.py`, orchestration public exports, focused tests.
- 구현 결과: factory-only `ParentContextReceipt`/`BridgeContextReceipt`, bounded seed, parent nonpromotion,
  actual table/figure linkage와 `empty` attempt, exact dependency pin, local at-most-once를 구현했다.
- 상태: COMPLETED (`c3.1`).

### 5. Validation + Report

- 사용할 스킬: `test-runner`, `mermaid-flow-report`, `logall`.
- 자동 테스트: c3 focused → c2/retrieval/fusion/follow-up 관련 → full unittest → safety.
- 빌드/lint: write-free import와 diff check.
- Playwright/browser smoke: 갱신한 flow HTML desktop/mobile.
- 현상태 Mermaid 플로우맵: c3 완료 뒤 effect/absence node를 current flow에 추가한다.
- 도달 경로 체크: exact typed source → state-free effect 또는 fully-bounded zero-provider absence.
- 타겟 노드 연결 점수: 10.
- 상태: COMPLETED.
- 결과: TDD RED→GREEN; focused 8/8, semantic/retrieval/action/state 관련 114/114,
  full 1,220/1,220, safety 850 PASS. Playwright images2/tables8/errors0/mobile overflow0 PASS.
  외부 API/model/Langfuse/VLM/golden 호출 0.

### 6. Repair Loop

- 실패 원인: 중간 semantic obligation GC 뒤 root source가 살아 있어도 발급 history가 정리되어
  동등 authority를 재발급할 수 있는 독립 감사 P1.
- 수리 배치: 실행 key/history/cache를 exact root source issuance lifetime에 결합하고 semantic GC 회귀를 추가했다.
- 재테스트: focused 8/8, related 114/114, full 1,220/1,220 PASS.
- 상태: COMPLETED.

### 7. Push / Publication

- git status 확인: user-owned dirty와 c3 변경을 분리한다.
- 커밋 범위: c3.1 code/test/contract/report/log hunk만. resources·gold·VLM·기타 사용자 변경 제외.
- 커밋/푸시: `7b7af7d` (`feat(harness): add bounded context source receipts`)를
  `origin/feat/total-integration`에 push했다.
- 상태: COMPLETED.

### 8. Closeout Report

- 사용할 스킬: `mermaid-flow-report`.
- 시작 타겟 대비 최종 현재 플로우: parent/bridge source receipt까지 MATCHED.
- 남은 GAP/PARTIAL 및 다음 점수표: c3.2 rerank/derived semantic 10 SELECTED, c3.3 absence 8,
  c4 effect/reducer 7 BLOCKED_BY_d2, EVAL.4 5.
- 상태: COMPLETED.

### 9. Relay Shot

- 사용할 스킬: `relay-shot`.
- 확인한 TODO source/다음 후보: TODO §EH2.6.c3과 계약 §16.10. 다음 최고 READY는 c3.2다.
- 새 원샷딜 시작 여부: 아래 Cycle 7 새 form을 쓰고 c3.2 계약 교정부터 즉시 시작한다.
- 멈춘 이유, 있으면: 없음.
- 상태: `CONTINUE_WITH_NEXT_FORM` / COMPLETED.

### 10. Final Ledger

- Doc: COMPLETED.
- Implementation / Validation / Repair / Report: COMPLETED.
- Push / Relay: COMPLETED.
- Flow diagram verification: PARTIAL — parent/bridge source receipt까지 MATCHED, c3.2 rerank부터 GAP.
- 남은 리스크: derived semantic의 auxiliary parent context와 c2 at-most-once issuance key를 분리해야 한다.

## Cycle 7 — EH2.6.c3.2 ID-less rerank / derived semantic

### 0. Scope Intake

- 요청 범위: c3.1 push 뒤 최고 점수 READY TODO c3.2를 새 원샷딜로 계약→TDD→구현→검증→푸시하고
  다음 TODO로 relay한다.
- 브랜치: `feat/total-integration`; 새 브랜치 생성/병합 없음.
- 사용자 제약: user-owned dirty·VLM·resources 보존, 실제 API/model/Langfuse/golden 실행 0.
- 완료 기준: exact owner-derived candidate+bridge만 ID-less reranker에 최대 한 번 공급하고, output index를
  receipt로 복원한 뒤 parent를 unindexed private context로만 쓰는 derived semantic obligation을 봉인한다.
- 위험/확인 필요: rerank output order와 role partition, `rerank_k` budget, base/derived verifier 실행권 분리,
  root-lifetime at-most-once를 코드 전 고정한다.
- 상태: COMPLETED.

### 1. Start Report / Target Check

- 사용할 스킬: `mermaid-flow-report`.
- 기준 타겟 플로우: §16.10 `candidate+bridge → ID-less rerank → derived semantic verify`.
- 현재 플로우: c3.1 parent/bridge source receipt까지 MATCHED, rerank/derived semantic부터 GAP.
- 점수표/선정 기준: c3.2=4+3+2+2-1=10, c3.3=3+3+2+1-1=8,
  c4=3+2+2+1-1=7(BLOCKED_BY_d2), EVAL.4=5.
- 상태: COMPLETED.

### 2. Relay Unit Selection

- 사용할 스킬: `relay-shot`.
- 확인한 TODO source: refreshed flow report, TODO §EH2.6.c3, 계약 §16.10, checkpoint/active context.
- 선택한 다음 단위작업: `EH2.6.c3.2`.
- 플로우폼 반영: 이 Cycle 7 form.
- 상태: `CONTINUE_WITH_NEXT_FORM` / COMPLETED.

### 3. Doc / Contract

- 사용할 스킬: `doc-contract-writer`.
- 교정 대상: rerank result order와 candidate/bridge role partition을 분리하고 `rerank_k`를 exact output
  상한으로 고정한다. parent는 verifier request의 private unindexed context이며 support index 대상이 아니다.
- 실행권: base semantic 실행과 rerank 파생 실행은 exact owner history에서 원자적으로 경쟁시켜 double verifier를
  금지하고, derived obligation은 별도 verifier key를 가진다.
- 계약 결과: owner plan budget/effective quota, complete same-live context batch, cross-role/bridge-only global order,
  strict ID-less ABI, root-lifetime route CAS, deterministic auxiliary parent와 derived recursion 차단까지 봉인했다.
  독립 REDTEAM 재검토 P0/P1 없음(APPROVE).
- 상태: COMPLETED.

### 4. Implementation

- 사용할 스킬: `one-go`, 재귀 leaf는 `batch-sequential-runner`.
- 재귀 TODO: c3.2.a contract/RED → c3.2.b rerank receipt → c3.2.c derived semantic → c3.2.d adversarial gate.
- 수정 대상: `execution_contracts.py`, orchestration exports, focused tests.
- 상태: IN_PROGRESS (`c3.2.b`, RED acceptance 작성 중).

### 5. Validation + Report

- 사용할 스킬: `test-runner`, `mermaid-flow-report`, `logall`.
- 자동 테스트: c3.2 focused → c2/c3.1/retrieval/follow-up 관련 → full unittest → safety.
- Playwright/browser smoke: 갱신한 flow HTML desktop/mobile.
- 상태: PENDING.
- 결과: PENDING.

### 6. Repair Loop

- 실패 원인/수리/재테스트: PENDING.
- 상태: PENDING.

### 7. Push / Publication

- git status 확인과 selective stage: PENDING.
- 커밋/푸시: PENDING.
- 상태: PENDING.

### 8. Closeout Report

- 시작 타겟 대비 최종 현재 플로우·남은 GAP·점수표: PENDING.
- 상태: PENDING.

### 9. Relay Shot

- 확인할 TODO source/다음 후보: c3.2 종료·push 뒤 TODO §EH2.6.c3을 재채점한다.
- 새 원샷딜 시작 여부: 안전한 READY가 있으면 새 form을 쓰고 즉시 시작한다.
- 상태: PENDING.

### 10. Final Ledger

- Scope / Target / Relay select: COMPLETED.
- Doc / Contract: COMPLETED.
- Implementation / Validation / Repair / Push / Report / Relay: PENDING.
- 남은 리스크: production reranker는 승인 전 unavailable이고, 이 Cycle은 synthetic/offline 계약 검증만 수행한다.
