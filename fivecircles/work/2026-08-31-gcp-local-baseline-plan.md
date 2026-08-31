# GCP Local Baseline Relay Plan

## One-Shot Delivery Flow Form

### 0. Scope Intake

- 요청 범위: GCP 고정 스펙을 로컬에서 구현하고 가능한 골든셋 채점까지 수행.
- 브랜치: `feat/hwp-visual-corpus-rollout`.
- 사용자 제약: KURE + Qwen3-8B-AWQ/vLLM, L4 24 GB, RAM 16 GB, storage hard max 100 GB.
- 완료 기준: 계약·provider·runner·테스트·local equivalent 결과·로그·선별 push.
- 위험/확인 필요: Mac에는 CUDA/L4가 없어 공식 GCP 실행과 GPU 지표는 생성할 수 없음.

### 1. Start Report / Target Check

- 사용할 스킬: mermaid-flow-report.
- 기준 타겟 플로우: `gcp-local-baseline-target-flow.mmd`.
- 현재 플로우: `gcp-local-baseline-current-flow.mmd`.
- 점수표/선정 기준: upstream + connection + safety + validation - risk.
- 상태: COMPLETED_WITH_GAPS.

### 2. Relay Unit Selection

- 사용할 스킬: relay-shot.
- 확인한 TODO source: Batch 5, technology/rag-stack/evaluation contracts, current code/tests.
- 점수 상위 후보: provider/run-record/disk 11; KURE index 9; local golden runner 8.
- 선택한 다음 단위작업: provider + run-record + 100 GB contracts.
- 플로우폼 반영: Batch 5.2부터 의존 순서대로 실행.
- 상태: CONTINUE_WITH_NEXT_FORM.

### 3. Doc / Contract

- 사용할 스킬: doc-contract-writer.
- 문서 생성/수정: GCP local HF contract, flow report, D-023, Batch 5 recursive TODO.
- 계약 확인: Mac equivalent와 official GCP 결과 분리, private artifact, exact model revisions.
- 상태: COMPLETED.

### 4. Implementation

- 사용할 스킬: one-go, batch-sequential-runner.
- 재귀 TODO: 5.2 provider/contracts → 5.3 retrieval → 5.4 local equivalent evaluation.
- 수정 대상: local stack adapters, evaluation schema/validator, dedicated local baseline runner.
- 상태: COMPLETED.

### 5. Validation + Report

- 사용할 스킬: test-runner, mermaid-flow-report.
- 자동 테스트: provider, evaluation contract, pipeline integration, runner, full regression.
- 빌드/lint: compileall, diff check, repository safety.
- Playwright/browser smoke: static flow HTML image/table/render check and screenshot.
- 현상태 Mermaid 플로우맵: opening GAP/PARTIAL; closeout에서 갱신.
- 도달 경로 체크: exact provider → shared pipeline → private run → provisional score.
- 타겟 노드 연결 점수: 11.
- 상태: COMPLETED_WITH_ONE_MODEL_CONTRACT_ERROR.

### 6. Repair Loop

- 실패 원인: `dev-unknown-001`에서 로컬 Qwen이 `status=abstained`와 함께 비어 있지 않은
  `answer`를 반환해 strict response contract가 `generation_abstention_invalid`로 거부했다.
- 수리 판단: baseline 측정값을 사후 정규화하거나 한 사례만 다른 프롬프트로 재생성하면 동일
  실험 정체성이 깨지므로 보정하지 않고 모델 계약 실패로 기록했다.
- 재테스트: 40/40 후보 무결성 검증과 resume 검증(`executed=0`, `resumed=40`) 완료.
- 상태: COMPLETED_WITH_RECORDED_BASELINE_DEFECT.

### 7. Push / Publication

- git status 확인: 기존 dirty worktree와 본 작업을 분리.
- 커밋 범위: public contract/code/tests/content-free receipts only.
- 커밋/푸시: `81c6c26` (`feat(rag): add pinned KURE Qwen local baseline`)를
  `origin/feat/hwp-visual-corpus-rollout`에 선별 push했다.
- 상태: COMPLETED.

### 8. Closeout Report

- 사용할 스킬: mermaid-flow-report.
- 시작 타겟 대비 최종 현재 플로우: 구현 증거로 갱신.
- 남은 GAP/PARTIAL: live L4/vLLM 및 human/Sol gate를 정확히 표시.
- 상태: COMPLETED_WITH_EXTERNAL_GAPS.

### 9. Relay Shot

- 사용할 스킬: relay-shot.
- 다음 후보: 로컬 결과 뒤 가장 높은 안전 gap.
- 새 원샷딜 시작 여부: actionable이면 즉시 계속, L4/외부 승인만 남으면 STOP_WITH_REASON.
- 재평가 결과: **STOP_WITH_REASON** — 다음 기술 단위는 유료 외부 VM을
  시작하는 Batch 5.5이고, 의미 판정은 명시적 휴먼 승인과 고정 judge가 필요하다.

### 10. Final Ledger

- Doc: COMPLETED
- Implementation: COMPLETED
- Validation: COMPLETED_WITH_PROVISIONAL_SCORE
- Repair: RECORDED_NO_POST_HOC_COERCION
- Push: COMPLETED (`81c6c26`, origin synchronized)
- Report: CLOSEOUT_UPDATED
- Relay: STOP_WITH_REASON
- 남은 리스크: CUDA/L4 부재, provisional gold, fixed Sol judge availability

## Measured Mac-equivalent Result

- 실행: 40/40 (`executed=38`, `resumed=2`), 재개 재검증은 `executed=0`, `resumed=40`.
- 검색: document recall@1 `0.833333`, recall@3/5/10 `1.0`, MRR@10 `1.0`,
  nDCG@10 `0.991972`.
- 세부 근거: source-block recall@1 `0.578889`, @3 `0.69`, @5 `0.753333`,
  @10 `0.865556`.
- 계약: citation validity `1.0`, response contract validity `1.0` (최종 오류 응답도 오류
  스키마 자체는 유효함).
- 행동: abstention match `0.775`; 로컬 생성 계약 오류 1건, runtime error rate `0.025`.
- 지연: total p50 `34,996.577458 ms`, total p95 `65,119.728166 ms`.
- 평가 경계: `mac_local_equivalent`, `official=false`, draft gold, semantic judgment `not_run`.
- 저장공간: working set `9,169,366,585 bytes`, 100 GB guard 통과, warning 없음.

## Batch Sequential Runner Ledger

- Run mode: sequential (contracts and providers are upstream dependencies).
- Current wave: Batch 5 local closeout complete.
- Completed: 5.1, 5.2, 5.3, 5.4.
- In progress: none.
- Blocked: Batch 5.5 live GCP until VM use is explicitly entered.
- Remaining actionable: none without live GCP authorization or human/Sol semantic review.
- Integration checks: staged-only 81/81, compile, diff/safety, flow HTML render, scoped Git
  publication complete. Repository-wide 721-test run retains two unrelated mini131 fixture failures.
