# BidFit Evidence-Harness v1-rc0 원샷딜 실행 기록

기준일: 2026-09-03

## 최신 실행 조정 — 작은 단위 순차 처리

- 사용자 요청(2026-09-03): 큰 범위/토큰 소모를 줄이기 위해 TODO를 재귀적으로 분할한다.
- 목표와 Phase 0~4는 유지한다. 구현 루프는 **leaf 1개 → focused test → 체크포인트 → 다음 leaf**다.
- canonical 작업 tree: `../architecture/todolist.md`의 EH-RC0. 현재 지점/짧은 재개 맥락:
  `bidfit-evidence-harness-v1-rc0-checkpoint.md`.
- 전체 첨부·리서치 재독/전체 감사 재실행은 생략하고 현재 leaf에 필요한 계약 절과 파일만 읽는다.
- 전체 원샷 원장은 이 문서에 유지하되 매 leaf마다 납품 문서/flow를 통째로 재생성하지 않는다.
  Phase gate와 최종 납품에서 통합·회귀·보고·push/relay를 닫는다.
- 현재 전체 상태: **IN_PROGRESS / Phase 0 push 완료, Phase 1 구현 중**. 작은 leaf 완료를 전체 완료로 보고하지 않는다.

## 원샷딜 플로우폼

### 0. Scope Intake

- 요청 범위: `assembly-on-research-and-exp.md`와 사용자 원샷 요구사항을 현재 checkout의 production modules에 통합
- 전달 브랜치: 기존 `feature/visual-retrieval`을 `feat/total-integration`으로 이름 변경해 Phase 2 통합 작업대로만 사용한다.
  후속 전체 범위의 선택 커밋·검증을 마친 뒤 `feat/local-qwen-mini131-eval`에 병합한다.
  새 브랜치는 만들지 않는다.
- 사용자 제약: checkout/통째 merge/force push/dirty 변경 삭제/기존 artifact 덮어쓰기 금지
- 완료 기준: P0 무결성, child dense+Kiwi BM25+RRF, E1 QueryPlan/Harness, Analytics/List/Table/Citation, reranker control, 분리 평가와 문서·테스트·푸시
- 위험/확인 필요: 시작 시 tracked 수정 39개와 다수 untracked 사용자 변경이 존재하므로 신규 파일 및 의도한 최소 겹침만 선택 커밋
- 로컬 기준: 생성기는 교체 가능한 provider adapter로 유지하되 기본 실행은 local profile이다. API profile은
  명시적으로 선택했을 때만 교체하며 자동 API 호출을 하지 않는다.
- 상태: COMPLETED

### 1. Start Report / Target Check

- 사용할 스킬: `mermaid-flow-report`
- 기준 타겟 플로우: `fivecircles/architecture/specs/bidfit-evidence-harness-v1-rc0-target-flow.mmd`
- 현재 플로우: `fivecircles/architecture/specs/bidfit-evidence-harness-v1-rc0-current-flow.mmd`
- 점수표/선정 기준: upstream + connection + safety + validation - risk
- 상태: COMPLETED

### 2. Relay Unit Selection

- 사용할 스킬: `relay-shot`
- 확인한 TODO source: 사용자 원샷 요구사항, `assembly-on-research-and-exp.md`, 현재 코드/테스트 감사
- 점수 상위 후보: P0 runtime integrity 11, evidence/retrieval foundation 8, E1 state loop 7, specialist lanes 6, reranker/evaluation 5
- 선택한 다음 단위작업: P0 gold leakage·empty-filter·scorer 회귀를 먼저 고정한 뒤 명시된 Phase 1~4를 순서대로 연결
- 플로우폼 반영: 계약 §10의 완료 조건 13개를 구현·검증 배치의 acceptance gate로 사용
- 상태: COMPLETED

### 3. Doc / Contract

- 사용할 스킬: `doc-contract-writer`
- 문서 생성/수정: `fivecircles/architecture/specs/bidfit-evidence-harness-v1-rc0.md`
- 계약 확인: runtime/evaluator 분리, immutable evidence, 동일 child granularity, fail-closed scope, structured citation
- 상태: COMPLETED (구현 전 계약 초안; leaf별 변경 시 필요한 절만 갱신)

### 4. Implementation

- 사용할 스킬: `one-go`
- 재귀 TODO: `architecture/todolist.md` EH-RC0의 leaf를 순서대로 실행. 최신 leaf는 active-context/checkpoint를 따른다.
- 수정 대상: 신규 `evidence`, `retrieval`, `orchestration`, `analytics`, harness config/평가 모듈과 관련 테스트
- 상태: TODO

### 5. Validation + Report

- 사용할 스킬: `test-runner`
- 필수 리포트 스킬: `mermaid-flow-report`
- 자동 테스트: 영역별 targeted test 후 전체 `unittest discover`
- 빌드/lint: `compileall`, repository safety check
- Playwright/browser smoke: 정적 target/current HTML 리포트 렌더 검증
- Mermaid/PNG/HTML 리포트: 본 문서와 같은 prefix의 flow artifacts
- 타겟 대비 현상태: 시작 시 핵심 harness 패키지 부재
- 상태: TODO
- 결과: 미실행

### 6. Repair Loop

- 실패 원인: 미정
- 수리 배치: 최대 2회 focused repair
- 재테스트: 실패 영역 targeted 후 full suite
- 상태: TODO

### 7. Push / Publication

- git status 확인: dirty 사용자 변경과 작업 변경 분리
- 커밋 범위: 이번 원샷의 파일만 pathspec으로 stage
- 커밋: 미정
- 푸시: 현재 브랜치의 안전한 원격 존재 여부 확인 후 수행
- 상태: TODO

### 8. Closeout Report

- 사용할 스킬: `mermaid-flow-report`
- 시작 타겟 대비 최종 현재 플로우: 검증 후 갱신
- 남은 GAP/PARTIAL: 검증 후 명시
- 다음 점수표 갱신: 검증 후 명시
- 상태: TODO

### 9. Relay Shot

- 사용할 스킬: `relay-shot`
- 확인한 TODO source: 갱신된 flow gap과 프로젝트 TODO
- 다음 후보: 검증 후 산정
- 선택한 다음 작업: 검증 후 산정
- 새 원샷딜 시작 여부: 검증 후 결정
- 멈춘 이유: 해당 없음
- 상태: TODO

### 10. Final Ledger

- Doc: COMPLETED (구현 전 계약; 최종 구현 보고서는 EH-D.1)
- Implementation: TODO
- Validation: TODO
- Repair: TODO
- Push: TODO
- Report: TODO
- Relay: TODO
- 남은 리스크: TODO

## 시작 감사 스냅샷

- 현재 브랜치: `feat/total-integration` (이름 변경 전 `feature/visual-retrieval`)
- 시작 HEAD: `7ad229f`
- working tree: tracked 수정 39개와 다수 untracked 파일 존재; 전부 사용자 소유로 간주하고 보존
- Python: `>=3.11`, setuptools, 기존 테스트는 `unittest discover`가 검증된 진입점
- 현재 본체: `indexing/`, `answering/`, page/table/visual ingest, local/API stack 및 Mini131 평가
- 현재 결손: checkout에는 `evidence/`, `retrieval/`, `orchestration/`, `offline_harness/` production 패키지가 없음
- 읽기 전용 참고 ref: `feat/evidence-harness-v1`; 통째 merge하지 않고 현재 계약에 맞는 최소 코드만 재조립
- private source: `resources/data_refined/private/`; Git 밖에 유지하며 기존 artifact를 덮어쓰지 않음

## Relay 1 — Phase 0 (2026-09-03)

| Form | 현재 결정 |
| --- | --- |
| 0 Scope | EH0.1.a→b→c, 이어 EH0.2~7; 브랜치/dirty/기존 artifacts 보존 |
| 1 Target check | 기존 flow ledger P0 GAP, score 11; 새로운 전체 감사 생략 |
| 2 Selection | 명시적 READY EH0.1.a. 각 leaf 검증 후 다음 leaf만 착수 |
| 3 Contract | 기존 §8.1~8.2와 공개 DTO API; 원문 15완료 기준은 요약 13개와 별도 |
| 4 Implementation | COMPLETED: EH0.1~7, one-go/recursive sequential TODO |
| 5 Validation | focused unittest → Phase 0 full/smoke; flow는 Phase gate에서 갱신 |
| 6 Repair | 테스트로 재현 후 해당 leaf 내 수정, assertion 약화/skip 금지 |
| 7 Publication | COMPLETED: c2c621c, origin/feature/visual-retrieval push; 기존 dirty39 보존, staged snapshot focused47 PASS |
| 8 Closeout | COMPLETED: current flow/PNG/HTML, focused47/full852, replay129; 이후 GAP은 남김 |
| 9 Relay | CONTINUE_WITH_NEXT_FORM; 단순 1~2 leaf 완료는 중단 사유 아님 |
| 10 Ledger | Doc/Implementation/Test/Push/Report 완료. Relay2 EH1.1 착수 |

### Relay 1 closeout

- Doc/Implementation/Test/Repair/Push/Report: COMPLETED (Phase 0 범위). focused47/full852/실물replay129/hash129/browser PASS.
- Flow: GAP/PARTIAL, 기존 앱 연결과 Evidence/E1은 후속. Decision: CONTINUE_WITH_NEXT_FORM.

## Relay 2 — Phase 1, 첫 leaf EH1.1

| Form | 결정 |
| --- | --- |
| 0 Scope | Evidence/ProvenanceParent frozen 타입, branch/dirty/source 보존 |
| 1 Target | 기존 target/current의 EvidenceStore GAP, score8 |
| 2 Selection | EH1.1→EH1.2→splitter 순; 한 번에 구현 leaf 하나 |
| 3 Contract | §8.3 + §16.1 공개 타입/불변성/locator 규칙 |
| 4 Implementation | IN_PROGRESS: EH1.1만 구현, 다른 leaf는 준비/검토만 |
| 5 Validation | evidence focused → Phase1 integration/full/flow/browser |
| 6 Repair | 해당 leaf 실패만 고치고 동일 회귀 재실행 |
| 7 Publication | Phase1 gate 후 선택 commit/push, pending |
| 8 Closeout | child artifact/legacy path/실제 실행과 미실측을 분리 |
| 9 Relay | CONTINUE_WITH_NEXT_FORM; EH1.1 시작 |
| 10 Ledger | Doc 완료, 구현 진행, gate/납품 대기 |

### Relay 2 closeout

- Doc/Implementation/Test/Repair/Report: COMPLETED (Phase 1 범위). EH1.1~10/G, focused35/full887,
  actual 98문서 child+legacy smoke, safety/browser, 독립 review closure PASS.
- actual artifacts는 private 새 namespace이며 source unchanged/generation0. 동일 gold A/B 전이므로 성능 향상은 주장하지 않는다.
- Publication: `ff9fa2e` (`feat(harness): add evidence-level hybrid retrieval`) origin push 완료.
  Decision: `CONTINUE_WITH_NEXT_FORM`.

## Relay 3 — Phase 2, 첫 leaf EH2.1

| Form | 결정 |
| --- | --- |
| 0 Scope | 결정론 QueryPlan/budget/version registry; branch/dirty/private source 보존 |
| 1 Target | current flow의 QueryPlan/E1 GAP, connection score 7 |
| 2 Selection | EH2.1 → planner → follow-up/compare → state/controller 순, 한 구현 leaf씩 |
| 3 Contract | §8.5 및 EH2.1 public schema를 publication 뒤 고정 |
| 4 Implementation | Phase1 push 뒤 EH2.1 TDD 시작 |
| 5 Validation | planner focused → Phase2 integration/full/flow/browser |
| 6 Repair | gold-specific 규칙/미지원 constraint silent drop/불변성 문제를 fail-closed 수리 |
| 7 Publication | Phase2 gate 후 별도 선택 commit/push |
| 8 Closeout | actual app wiring과 synthetic test를 분리 보고 |
| 9 Relay | `CONTINUE_WITH_NEXT_FORM`; EH2.3 선택 |
| 10 Ledger | 총통합 브랜치 `feat/total-integration`. EH2.1~2, focused51/full922 및 독립 adversarial review PASS |

### Relay 3 checkpoint — EH2.3~EH2.5

- EH2.3 actual-citation follow-up, EH2.4 compare slot coverage, EH2.5 sealed state/action decision을 순차 구현했다.
- EH2.5는 실행 loop가 아니다. reducer/transition/action-effect/round·deadline·no-progress는 EH2.6에 남겼다.
- 최종 검증: EH2.5 관련 focused 55/55, 전체 1,020/1,020, 독립 P1 수리 후 재검토 PASS.
- 실제 API·generator·Langfuse trace는 0회다. 성능 향상이나 실제 end-to-end 완료를 주장하지 않는다.
- publication: EH2.5.d까지 `85b6000`으로 origin push. EH2.5.e 수리·로그는 다음 선택 체크포인트에서 푸시한다.
- 다음 READY: EH2.6을 계약/audit→effect receipt→reducer→bounded controller→gate로 재귀 분할한다.
