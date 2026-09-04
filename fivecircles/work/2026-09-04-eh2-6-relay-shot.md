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
- Relay: `CONTINUE_WITH_NEXT_FORM` → `EH2.6.c1`.
- 상태: COMPLETED. 선택 커밋·푸시 기록만 closeout에서 덧붙인다.
