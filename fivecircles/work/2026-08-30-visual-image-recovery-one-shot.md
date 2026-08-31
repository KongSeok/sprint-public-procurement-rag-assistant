# Visual image recovery one-shot delivery ledger

실행일: 2026-08-30
브랜치: `feat/hwp-visual-corpus-rollout`
실행 모드: `hybrid` — 공통 schema/identity를 순차 잠근 뒤 HWP/PDF/OCR 레인을 병렬화하고 통합한다.

> 2026-08-31 correction: 아래 2026-08-30 단계별 test count는 당시 공개 구현의 역사 기록이다.
> current helper와 representative artifact의 권위 있는 상태는 바로 아래 correction ledger가
> 대체하며, 과거 493/493 수치를 current-tree green 증거로 재사용하지 않는다.

## 2026-08-31 blank-crop correction ledger

- Root cause: `renderPageSvg()`의 data-URI `<image>`가 base SVG rasterization에서 누락됐고,
  hash/dimension-only 검증이 순백 crop을 eligible로 통과시켰다.
- Repair: embedded raster overlay, nested viewBox/viewport/rect clip, 관측된 linear RGB effect와
  opacity를 구현했다. 순백 crop과 미지원 TIFF를 각각 fail closed/quarantine한다.
- Parser hardening: `<style>` element, `class`, ancestor `display`/`visibility`/inline `style`,
  `<defs>` 내부 image는 조용히 무시하지 않고 명시적 오류로 종료한다.
- Pinned identity: helper SHA-256
  `0b7ab8edd3b3cb6018704b40e1c7b662041a79c857dc99eba66432280cfc0a9b`, artifact set
  `visualv2_1a25cd3f5f6c34dfe2e8ff9c`.
- Private execution: 대표 5문서, occurrence 27개, eligible 15개, TIFF quarantined 1개,
  doc-only withheld 11개. crop 15/15와 page render 14/14가 nonblank다.
- Determinism/safety: expected artifact-set strict reuse `PASS`, 외부 API 호출 0회,
  `private_egress=false`. 과거 순백 14-crop bundle은 incident archive로 보존한다.
- Contract audit: representative 530페이지에서 `<style>`/`class`/`display`/`visibility`/
  `<defs>`-image 패턴은 0건이며, 관측되지 않은 형식도 adversarial fixture로 fail closed를 검증한다.
- Automated verification: helper focused 11/11, repository-wide discovery 505/505, focused schema
  2/2, compileall, Node syntax, diff-check, repository safety 562 files 모두 `PASS`.
- Current terminal state: crop repair `COMPLETED`, representative strict-reuse gate `PASSED`,
  full discovery `PASSED`, HWP 94 rollout `BLOCKED_BY_REVIEWED_GOLD`,
  실제 OCR/caption `BLOCKED_BY_PINNED_MODEL_WEIGHT`.

## 원샷딜 플로우폼

### 0. Scope Intake

- 요청 범위: HWP/PDF 이미지 누락을 occurrence 복구, deterministic crop, local OCR/layout,
  선택 caption, retrieval/citation까지 해결한다.
- 브랜치: `feat/hwp-visual-corpus-rollout`; `main` 직접 작업 금지.
- 사용자 제약: 외부 parser/search API와 private corpus egress 금지; 대표 유형 5개 뒤 94개 전수;
  문서·계약·TODO·구현·테스트·푸시·로그까지 완료.
- 완료 기준: 계약의 7개 배치가 terminal state에 도달하고 자동 검증, safety, 흐름 리포트,
  의도한 파일만 포함한 커밋과 원격 push가 끝난다.
- 위험/확인 필요: private human gold와 model weight는 Git 밖에서만 존재할 수 있다. 실제 model
  실행이나 94개 private materialization이 환경상 불가능하면 코드·합성 gate는 완료하고 해당
  private 실행만 정확한 blocker로 기록한다.
- 상태: `COMPLETED`

### 1. Start Report / Target Check

- 사용할 스킬: `mermaid-flow-report`
- 기준 타겟 플로우: `fivecircles/architecture/specs/hwp-pdf-visual-parsing-flow-validation.md`
- 현재 플로우: HWP v1은 문서 단위 all-or-nothing link, PDF PoC는 stale geometry candidate,
  OCR/caption/retrieval citation v2는 미구현.
- 점수표/선정 기준: target의 upstream unmatched node부터
  `upstream + connection + safety + validation + risk`로 평가.
- 상태: `COMPLETED`

### 2. Relay Unit Selection

- 사용할 스킬: `relay-shot`
- 확인한 TODO source: `fivecircles/architecture/todolist.md`, visual recovery contract,
  PDF stale-artifact incident, target/current flow report.
- 점수 상위 후보: occurrence identity/schema 11; HWP exact key/mixed state 10;
  PDF durable recovery 9; deterministic crop 9; OCR/layout 7; caption/retrieval 5.
- 선택한 다음 단위작업: occurrence identity/schema와 promotion rule을 먼저 잠그고 계약의 7개
  배치를 dependency 순서대로 완결한다.
- 플로우폼 반영: 이 문서의 Batch Sequential Runner ledger로 추적한다.
- 상태: `COMPLETED`

### 3. Doc / Contract

- 사용할 스킬: `doc-contract-writer`
- 문서 생성/수정: `visual-image-recovery-and-understanding.md`, flow validation report,
  decision/TODO/incident 상태.
- 계약 확인: additive v2 schema, false-link-zero, page+bbox+crop promotion, local-only,
  caption claim support, legacy hash 불변.
- 상태: `COMPLETED`

### 4. Implementation

- 사용할 스킬: `one-go`
- batch가 명시된 경우: `batch-sequential-runner`
- 재귀 TODO: 아래 7개 배치.
- 수정 대상: contracts, ingest HWP/PDF/visual modules, CLI, OCR/caption/retrieval modules,
  tests와 private-safe runners.
- 상태: `COMPLETED_PUBLIC`
- 결과: additive v2 계약, HWP/PDF occurrence·crop runner, checksum-pinned offline
  OCR/layout/caption adapter, visual fusion·citation·abstention과 평가 parity를 구현했다. 실제 HWP 대표
  5건과 PDF 4건은 private root에서 재실행했으며 원문·crop·모델 산출물은 Git 밖에 유지했다.

### 5. Validation + Report

- 사용할 스킬: `test-runner`
- 필수 리포트 스킬: `mermaid-flow-report`
- 자동 테스트: touched suites → full unittest → schema/compile/safety/diff.
- 빌드/lint: Python compileall과 repository-native checks.
- Playwright/browser smoke: static flow HTML의 이미지·legend·gap/priority 표·viewport 확인.
- Mermaid/PNG/HTML 리포트: target/current `.mmd`, PNG, HTML, screenshot.
- 타겟 대비 현상태: node/edge별 `MATCHED`, `PARTIAL`, `GAP` 기록.
- 상태: `COMPLETED`
- 결과: 전체 unittest 493/493, compileall, Draft 2020-12 schema 23개, diff-check와 safety
  556 files를 통과했다. 리포트 HTML은 이미지 존재·tag balance·responsive/overflow를 정적 검증했다.
  인앱 브라우저의 `file://` 정책 차단은 우회하지 않고 `ENVIRONMENT_BLOCKED / STATIC_QA_COMPLETE`로
  기록했다.

### 6. Repair Loop

- 실패 원인: PDF atomic publish root 권한, Mermaid browser launch sandbox, rhwp WASM file URL,
  PDF identity/drawing limit, visual fusion rank expectation, 모델 command의 네트워크 격리 계약과
  caption/evaluation 통합 경계에서 결함을 발견했다.
- 수리 배치: atomic publish와 strict identity를 fail-closed로 만들고, drawing 상한·bounded visual
  quota·caption support-ref·exact visual citation·OS sandbox enforcement를 추가했다.
- 재테스트: focused 92/92 뒤 전체 493/493와 schema/compile/safety를 재실행했다.
- 상태: `COMPLETED`

### 7. Push / Publication

- git status 확인: 대량 기존 dirty tree를 보존하고 의도한 code/docs/tests만 explicit stage.
- 커밋 범위: visual recovery와 이를 실행 가능하게 하는 기존 uncommitted visual stack;
  private artifacts/resources와 scoring은 제외.
- 커밋: 공개 구현 `df72d69` (`feat(ingest): recover and index local visual evidence`).
- 푸시: `origin/feat/hwp-visual-corpus-rollout` 신규 브랜치 publication 성공.
- 상태: `COMPLETED`

### 8. Closeout Report

- 사용할 스킬: `mermaid-flow-report`
- 시작 타겟 대비 최종 현재 플로우: V1–V4·V6 공개 구현 `MATCHED`, V5는 코드 완료/실제
  weight 실행 차단, V7은 대표 5건 완료/94건 human-gold gate 차단으로 갱신했다.
- 남은 GAP/PARTIAL: private human gold, pinned model weight와 그 품질 측정, 이후 HWP 94건 전수다.
- 다음 점수표 갱신: 자동 실행 가능한 공개 단위는 남지 않았고 외부 입력 gate만 남았다.
- 상태: `COMPLETED`

### 9. Relay Shot

- 사용할 스킬: `relay-shot`
- 확인한 TODO source: closeout score table과 visual recovery TODO.
- 다음 후보: private HWP 5건 + PDF 4건 사람 fidelity gold와 checksum-pinned local model weight.
- 선택한 다음 작업: 외부 입력이 준비되면 gold 동결 → 실제 OCR 품질 gate → HWP 94건 전수.
- 새 원샷딜 시작 여부: `STOP_WITH_REASON`.
- 멈춘 이유: 다음 단위는 private 원문에 대한 사람 판정 또는 사용자 승인 하의 model weight가
  필요해 현재 실행에서 안전하게 자동 생성할 수 없다.
- 상태: `COMPLETED`

### 10. Final Ledger

- Doc: `COMPLETED`
- Implementation: `COMPLETED_PUBLIC`
- Validation: `COMPLETED`
- Repair: `COMPLETED`
- Push: `COMPLETED`
- Report: `COMPLETED`
- Relay: `STOP_WITH_REASON`
- 남은 리스크: private human gold/model weights, 그 gate 뒤 HWP 94건 전수와 실제 품질 판정.

## Batch Sequential Runner Ledger

- Run mode: `hybrid`
- Current wave: complete
- Completed: Batch 1–6과 Batch 7의 공개 orchestration/대표 실행
- In progress: none
- Blocked: Batch 7 private 94건은 reviewed gold와 model-quality gate 대기
- Failed after retry: none
- Skipped with reason: none
- Remaining actionable: 현재 입력으로 자동 실행 가능한 항목 없음
- Files changed: contracts, ingest/answering/indexing/evaluation, CLI, tests, flow report와 운영 로그
- Checks run: focused 92/92, full 493/493, compileall, 23 schemas, safety, diff-check, static HTML QA
- Integration checks: public path complete; private model inference 0, HWP 94 corpus mode gold 없이 fail-closed

| Batch | Scope | Dependency | Terminal state |
| --- | --- | --- | --- |
| 1 | public synthetic gold/inventory contract and fixtures | none | COMPLETED |
| 2 | HWP exact key, mixed occurrence state, exact nested-cell anchor | 1 | COMPLETED |
| 3 | exact fallback and deterministic page-region crop | 1–2 | COMPLETED |
| 4 | PDF resource/placement recovery and durable corpus runner | 1 | COMPLETED |
| 5 | local OCR/layout adapter, cache and quality gates | 1, 3–4 | COMPLETED_PUBLIC / MODEL_RUN_BLOCKED |
| 6 | supported caption claims, visual chunks, RRF/citation | 5 | COMPLETED_PUBLIC |
| 7 | representative gate, rollout orchestration and regression audit | 2–6 | REPRESENTATIVE_COMPLETE / 94_BLOCKED_BY_GOLD |

## Recurrence-prevention plan

- Never accept a visual link from ordinal, aspect ratio, proximity, OCR, pHash, or caption alone.
- Never run OCR/caption without an immutable `doc_id + page + bbox + crop_sha256` occurrence.
- Never treat PDF geometry candidates or stale artifacts as verified semantic objects.
- Keep source text/table/page identities immutable and add v2 records rather than rewriting v1.
- Keep private source/crop/OCR/caption artifacts out of Git and sanitize logs to counts/status only.
