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
- 현재 전체 상태: **INCOMPLETE / implementation not started**. 작은 leaf 완료를 전체 완료로 보고하지 않는다.

## 원샷딜 플로우폼

### 0. Scope Intake

- 요청 범위: `assembly-on-research-and-exp.md`와 사용자 원샷 요구사항을 현재 checkout의 production modules에 통합
- 브랜치: `feature/visual-retrieval` 고정
- 사용자 제약: checkout/통째 merge/force push/dirty 변경 삭제/기존 artifact 덮어쓰기 금지
- 완료 기준: P0 무결성, child dense+Kiwi BM25+RRF, E1 QueryPlan/Harness, Analytics/List/Table/Citation, reranker control, 분리 평가와 문서·테스트·푸시
- 위험/확인 필요: 시작 시 tracked 수정 39개와 다수 untracked 사용자 변경이 존재하므로 신규 파일 및 의도한 최소 겹침만 선택 커밋
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
- 재귀 TODO: `architecture/todolist.md` EH-RC0의 leaf를 순서대로 실행. 현재 READY는 EH0.1.a.
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

- 현재 브랜치: `feature/visual-retrieval`
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
| 4 Implementation | IN_PROGRESS: one-go, recursive sequential TODO |
| 5 Validation | focused unittest → Phase 0 full/smoke; flow는 Phase gate에서 갱신 |
| 6 Repair | 테스트로 재현 후 해당 leaf 내 수정, assertion 약화/skip 금지 |
| 7 Publication | Phase 0 검증 후 이번 source/tests/docs만 선택 stage/commit/push, 아직 미실행 |
| 8 Closeout | Phase gate에서 current flow와 실제 결과 갱신; 이후 GAP은 남김 |
| 9 Relay | CONTINUE_WITH_NEXT_FORM; 단순 1~2 leaf 완료는 중단 사유 아님 |
| 10 Ledger | Doc 완료, Implementation 진행, Test/Push/Report 대기. 다음 코드는 EH0.1 |
