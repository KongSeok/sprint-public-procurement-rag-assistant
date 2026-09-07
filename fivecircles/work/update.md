# Work Update (2025-12-21)

This file summarizes recent updates so other agents can continue without re‑discovering changes.

## Addendum (2026-08-24) - Batch 0 foundation

### Governance
- MidProjectRAG 요구사항·자료 권위·A/B 제약을 고정하고 가져온 프로젝트 문서를 `legacy/`로 격리했다.

### Security
- 루트 Git 저장소와 ignore/안전 검사기를 만들고 restricted data·secret·PII 공개 경계를 고정했다.

### Tests
- 안전 검사 263파일 PASS; 금지 경로 ignore 검증 PASS; legacy 활성 계약 검색 0건.

## Addendum (2026-08-24) - Batch 0 cross-review and operation initialization

### Review remediation
- 외부 corpus 전송 결정을 승인 대기 상태로 되돌리고 Batch 0~2를 로컬 전용으로 고정했다.
- 활성 레거시 배포·복구 스킬을 격리하고 PDF·파생 JSONL/TXT·강제 secret 추적까지 안전 게이트에 포함했다.
- 안전 검사는 일치한 비밀·PII 내용을 출력하지 않으며, 정확한 corpus·Mission14 주소는 Git 밖 private 레지스터로 옮겼다.

### Verification
- 저장소 안전 검사 284파일 PASS.
- restricted ignore canary 전부 차단, 공개 보고서 PDF와 평가 예제 JSONL allow-list만 허용.
- 추적 대상 문서에서 비공개 Drive 식별자와 개인 절대 경로 0건.

### Operation initialization
- Batch 0 종료 후 authority → requirements/decisions → specs → policies → work/update → todo 순서로 운영 문서를 다시 읽었다.
- 현재 역할을 배치 순차 구현·통합 담당으로 고정하고 다음 작업을 Batch 1 → Batch 2로 설정했다.

## Addendum (2026-08-24) - Batch 1 ingestion implementation

### Delivered
- private data root 안에서 동작하는 `manifest → extract → verify` CLI와 manifest/source-block 계약을 구현했다.
- exact filename join, source hash drift, path/symlink escape, parser 부재, 무텍스트 PDF를 모두 명시적 상태로 기록한다.
- CSV 텍스트 미리보기는 길이·hash만 보존하고 검색 source block에는 넣지 않는다.

### Verification
- 합성 HWP/PDF, join collision, metadata snapshot, hash drift, malformed contract, forged provenance, symlink/path traversal, schema, CLI 테스트 22개를 통과했다.
- private 절대경로·본문·PII가 stdout에 나오지 않는 회귀 테스트를 포함했다.

### Terminal boundary
- 구현은 완료됐지만 실제 private 100건과 `hwp5txt`가 로컬에 없어 전수 추출·fidelity QA는 `BLOCKED_REAL_CORPUS`다.
- 공개 계약 작업인 Batch 2는 이 차단과 독립적으로 진행한다.

## Addendum (2026-08-24) - Batch 2 shared evaluation contract

### Delivered
- 두 실행 스택이 공유하는 요청·응답, eval case, run record Schema와 오프라인 registry를 구현했다.
- 4대 task 누수·hash·지표·CLI와 안전 기권, scope, frozen gate, API↔GCP 비교를 fail-closed로 구현했다.

### Verification
- 평가 31개와 전체 53개 테스트가 malformed shape, 누수, gate 약화, 안전하지 않은 기권, 조작 보고서를 포함해 통과했다.
- 오프라인 `$ref`, compile, 합성 CLI와 저장소 safety 검사를 통과했다.

### Terminal boundary
- 공개 계약·도구·합성 검증은 완료했다.
- 실제 40/20 gold 작성·봉인은 private corpus를 기다리는 `BLOCKED_PRIVATE_GOLD`다.

## Addendum (2026-08-24) - Real corpus materialization and daily brief

### Backend
- 실제 100/100 조인과 HWP 96·PDF 4 전수 추출을 완료하고 PDF Pipe deadlock·HWP fallback을 보강했다.

### Documentation
- 당일/익일/전체 약 35% 위치를 팀 공유 HTML로 정리했다. (ref: `work/2026-08-24-daily-summary.html`)

### Tests
- 전체 58/58, 최종 `require-extracted` 100/100, compile, safety 317파일을 통과했다.

## Addendum (2026-08-25) - rhwp primary HWP extraction

### Decision
- 공식 `rhwp v0.8.4` Release 바이너리의 SHA-256을 검증하고 HWP/HWPX 주 추출기로 확정했다.
- HWP→PDF 일괄 변환 대신 `rhwp` 페이지 텍스트·표 구조를 직접 보존하며, legacy parser와 PDF는 fallback/검증 안전망으로 둔다.

### Backend
- `export-text --json`을 one-based page source block으로, `export-tables --json`을 병합셀·중첩표 구조 block으로 변환하는 bounded adapter를 구현했다.
- `rhwp` text 실패 시 HWP5에 한해 `hwp5txt`→pyhwp binary-model로 복구하고, table 실패 시 page text를 `partial`로 보존한다.
- HWP 96건·PDF 4건을 기존 산출물과 분리해 재추출한 결과 100건 모두 `ok`, 실패 0건이었다.
- 실행 바이너리 절대경로·버전·SHA-256을 extractor identity/input hash에 고정하고, checksum이
  다르면 실행 자체를 막는 production gate를 추가했다.
- page JSON 절단·누락과 table cell count·span 겹침을 fail-closed로 검증한다. page text는
  `primary`, 구조화 table은 `structured_auxiliary`로 분리해 baseline 중복 임베딩을 차단했다.

### Data review
- 팀원 탐색 리뷰와 inventory, NFC 100/100, CSV preview 잘림, 결측 18/18/26/8/1건, HWP 전수 재파싱 결과가 일치했다.
- PDF 4건 중 최대 문서의 parser별 문자 수가 약 10% 달라 후속 fidelity QA로 남겼다.

### Verification
- 전체 70/70 테스트, 별도 pycache compile, real `require-primary-hwp`를 통과했다.
- 실제 manifest 100행과 source block 20,569행은 JSON Schema 오류 0건이었다.
- 저장소 안전 검사 322파일을 통과했다.
- 동일 입력 재추출의 block/meta 200개가 byte-for-byte 동일해 결정성 계약을 통과했다.
- 남은 Batch 1 gate는 HWP 5건의 table↔bbox/한컴 페이지 정합과 PDF 4건 표·bbox QA다.

## Addendum (2026-08-25) - Batch 3 API baseline and optional observability

### Delivered
- 100문서의 primary page block으로 deterministic `page-v1` 청크 9,509개를 만들고 manifest/config/artifact hash를 고정했다.
- `text-embedding-3-small` cache·USD 20 process-safe 비용 원장·exact cosine FAISS/NumPy index·scope 선필터를 구현했다.
- `gpt-5-mini`/`gpt-5-nano` 구조화 응답, top-10 검색/top-5 생성, 인용 교차검증, 기권, 대화 이력 제한을 구현했다.
- 기본 OFF 관측 포트와 metadata-only Langfuse v4 adapter를 추가했다. 로컬 JSONL evaluator가 원장이고 Langfuse는 선택적 보조 UI다.
- 공개 `tiktoken` 어휘 2개는 별도 승인 warmup, 자산 크기 상한, 고정 SHA-256을 거친다. runtime은 검증된 로컬 바이트만 직접 파싱한다.

### Verification
- 전체 126/126 테스트, source/tests compile, 저장소 안전 검사 360파일을 통과했다.
- allowlisted 세 모델의 로컬 token count가 공식 `tiktoken==0.13.0`과 3개 한국어/혼합 표본에서 일치했다.
- 실제 private chunk 결과는 100문서, 9,509개, auxiliary 0이며 artifact identity는 Git 밖에서 검증했다.

### Remaining gates
- 2026-08-25 사용자가 OpenAI corpus egress·provider retention 수용과 Langfuse metadata-only egress를 모두 승인했다.
- 실제 임베딩은 중복 제거 후 9,323개 content, 약 6,939,837 tokens와 USD 0.138796740로 추정돼 예산 차단은 없다.
- 로컬 셸과 표준 private 설정에 `OPENAI_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`가 없어 실제 provider 실행은 자격증명 단계에서 차단됐다.
- dev 40건은 구조·근거 참조가 유효하지만 named human reviewer 승인 전 draft이므로 실행 후에도 공식 기준선으로 발표하지 않는다.
- production FAISS smoke는 macOS arm64가 아닌 과제 GCP L4 VM에서 수행한다.

## Addendum (2026-08-25) - Egress approval preflight

### Operations
- OpenAI·Langfuse 전송 승인을 기록했다. 로컬 자격증명 부재로 provider 실행은 시작 전 차단됐다.
- 임베딩 예상치는 694만 tokens·USD 0.139로 USD 20 hard stop 안이다.

### Tests
- 승인 문서 반영 후 전체 126/126, safety 360파일, `git diff --check`를 통과했다.

## Addendum (2026-08-25) - API/local physical split and Qwen3.8 local baseline

### Structure
- provider 구현을 `src/midprojectrag/stacks/api`와 `src/midprojectrag/stacks/local`로 분리했다.
- 테스트도 `tests/stacks/api`와 `tests/stacks/local`로 분리하고 AST 경계 검사로 상호 import와
  core의 provider 역참조를 차단했다.
- private 산출물은 `indexes`, `caches`, `outputs` 아래에서 각각 `api`와 `local`로 분리한다.

### Local baseline
- 기존 100문서·9,509청크를 `local-hash-char-v1` 2,048차원 NumPy exact index로 생성했다.
- 두 번째 인덱싱에서 cache 9,509/9,509 hit와 vector/row hash 불변을 확인했다.
- `qwen3.8:27b-mlx`의 설치 digest를 대조하고 loopback-only, proxy/redirect 차단,
  `OLLAMA_NO_CLOUD=1` 조건에서 합성 및 private 단일 질의를 통과했다.
- private 질의 2회는 8.3~12.9초에 `answered`, 검색 10건, 검증된 인용 1건으로 종료됐다.
- 최종 재실행은 cache hit, input/output 1,687/62 tokens였고 corpus/chunk/index/model/seed/context
  설정과 query config SHA-256을 text-free reproducibility metadata로 함께 저장했다.
- local query 산출물에 corpus/chunk/index/config hash와 text-free generation/retrieval 설정을 기록한다.

### Verification and boundary
- 전체 152/152 테스트, 별도 pycache compile, 저장소 안전 검사 389파일을 통과했다.
- CLI가 `private/{indexes,caches,outputs}/{api,local}` 경계를 강제하며 교차 stack 경로는
  provider/Ollama 초기화 전에 실패한다. shared core는 provider-neutral budget protocol에만 의존한다.
- 로컬 경로는 `mac_local_experimental`이며 공식 API/GCP L4 평가·제출 점수에 포함하지 않는다.
- API 코드는 준비됐지만 실제 embedding/dev 실행은 `OPENAI_API_KEY`와 사람 검토 dev set을 기다린다.

## Addendum (2026-08-26) - canonical root consolidation and Langfuse live audit

### Delivered
- 현재 저장소를 유일한 정식 루트로 유지하고, 잘못 만든 작업 사본에서는 Langfuse·dotenv 보완만 선별 이식했다.
- content-free input/output과 `chain → span/embedding/retriever/generation/guardrail` 계층을 수동 Langfuse 4.14.5 adapter에 반영했다.
- 프로젝트 `.env`를 `override=False`로 지연 로딩하고, 표준 키가 비어 있을 때만 `OPENAI_API_KEY_PRIVATE`를 프로세스 내부 alias로 연결한다. 실제 `.env` 권한은 600으로 제한했다.

### Live verification
- 합성 데이터와 fake embedding/generation provider로 실제 `RagPipeline`을 Langfuse Cloud에 전송했다. OpenAI API와 실제 corpus는 호출·열람하지 않았다.
- 7 observations, 6 child-parent links, logical root, 종료 7/7, 안전 I/O 7/7, embedding/generation usage·cost, Boolean `task_success` score를 재조회했다.
- 질문·문서·답변 canary는 I/O와 application metadata에 없었고 observer failure/drop은 모두 0이었다.
- SDK 송신 직전 model 속성은 embedding/generation 모두 존재했지만 Observations API v2의 `providedModelName`은 null이었다. allowlisted model metadata는 정상이며 외부 projection gap으로 기록했다.

### Verification
- 프로젝트 Python 3.12 환경에서 전체 156/156 테스트, source/tests compile, 저장소 안전 검사 393파일과 `git diff --check`를 통과했다.
- 잘못 만든 작업 사본을 삭제한 뒤에도 전체 156/156과 safety를 재통과했고, 정식 저장소와 상위 폴더는 유지됨을 확인했다.

### Post-audit runtime state
- 실제 검색·생성 가동 전까지 로컬 `.env`의 Langfuse backend와 tracing을 다시 비활성화했다. 자격증명은 유지하며 첫 실제 RAG smoke에서만 명시적으로 활성화한다.
- API 임베딩·생성 기본값을 각각 `text-embedding-3-small`과 `gpt-5-mini`로 환경설정에 고정하고, 생성 대안은 `gpt-5-nano`만 허용한다. 비허용 환경값은 CLI 인자 처리와 provider 호출 전에 fail-closed한다.

## Addendum (2026-08-26) - metadata missing-value and mapping correction

### Data quality
- 원본 100행 CSV를 불변으로 보존하고 source/row hash·old value·typed evidence를 잠그는 private correction overlay를 구현했다.
- 105개 필드 결정을 전수 감사해 apply 74, clear 3, retain-null 28로 확정했고 실제 셀 77개를 변경했다.
- 공고번호·차수 17쌍, 번호 체계 18건, 날짜 시작 5·마감 8, 개찰 3·제안서 평가 1,
  금액 6, 발주기관 2건을 보완·교정했다.
- 근거가 불충분한 일정·금액과 후속 차수는 추정 적용하지 않고 검토 큐에 남겼다. 입찰 히스토리 수집은 후순위다.

### Implementation and verification
- `correct-metadata` CLI는 source/row drift, duplicate target, old-value mismatch, 근거·신뢰도 부족,
  amount/date 형식과 start/end/open/evaluation 역전을 fail-closed한다.
- 수정본은 100행·15열이며 HWP 96/PDF 4 exact manifest join 100/100, 오류 0을 유지했다.
- manifest는 선택적 번호 체계·개찰·제안서 평가 metadata를 보존한다.
- 전체 207/207 tests, compile, repository safety 410 files와 `git diff --check`를 통과했다.

## Addendum (2026-08-26) - Personal OpenAI API 2×2 provisional baseline

### Delivered
- 개인 계정에서 `text-embedding-3-small`/`large`와 `gpt-5-nano`/`mini`의 2×2를 동일한 draft dev 40건으로 실행했다.
- 9,509행의 small 1,536차원·large 3,072차원 NumPy exact cosine index를 분리 생성하고 corpus/chunk/index/config hash를 고정했다.
- Structured Outputs root envelope, 동적 citation 상한, citation 중복 정규화, 엄격한 abstention을 적용했다.
- transient provider 오류에는 SDK retry 2회를 적용하고 generation output 한도를 2,000 tokens로 높였다.

### Verification
- `dev40-provisional-v5`: 4조합 × 40건 = 160/160 완료, error 0, response contract error 0%.
- v5 비용 증분 USD 0.111497070, 종료 원장 USD 1.172692850/5.00, reserve 0, breach 없음.
- small nDCG@10 0.994648, large 0.974123. large는 source-block Recall@10 0.907222로 small 0.798889보다 높았다.
- nano는 mini보다 약 4.7배 저렴했고, mini는 자동 인용 커버리지가 높았다.
- 최종 전체 198/198 테스트, 저장소 안전 검사 404파일, `git diff --check`를 통과했다.
- 집계 보고서: `fivecircles/work/2026-08-26-api-2x2-provisional-baseline.md`.

### Status and next gates
- 결과는 `provisional_unreviewed_dev`; 40건 모두 draft이고 human judgment는 0건이다.
- 과정 후보는 small이며 large는 개인 계정 실험이다. 품질 우선 잠정안은 small+mini, 비용·속도 대조군은 small+nano다.
- 30/40건이 explicit scope라 검색 점수는 주로 선택 문서 내부 근거 검색 성능이다.
- Langfuse metadata-only tracing은 활성화했으나 post-run API 감사는 Observations v2 schema drift에서 fail-closed 중단됐다.
- 다음 gate는 2인 dev 검토, 전체 corpus 문서 탐색 평가, GCP FAISS smoke다.

## Addendum (2026-08-26) - metadata missingness handoff
### Documentation
- 잔여 결측 31셀·21문서를 필드·사유·결정별로 기록했다.
- Handoff: work/data-quality-corrections/audit-summary.md

### Tests
- 레지스터 31/31 연결, 전체 207 tests, safety 412 files, git diff --check 통과.

## Addendum (2026-08-26) - retrieval cut analysis and Streamlit baseline start

### Retrieval analysis
- 문서 기준 small nDCG@5는 0.994648, large는 0.968215였다.
- 청크 기준 nDCG@5/Recall@5는 small 0.713787/0.740556,
  large 0.739137/0.814444로, 문서 순위와 top-5 근거 청크 회수의 우세 모델이 달랐다.
- 현재 9,509청크는 모두 source block 하나와 1:1이므로 현 snapshot에서는 chunk Recall과
  source-block Recall이 같다. 이 수치는 draft 30개 answerable case의 offline 진단이며 공식 점수가 아니다.

### Corrected catalog boundary
- 원본 retrieval manifest와 교정 catalog는 `doc_id`, 원본 SHA, 정규화 파일명이 100/100 같다.
  이는 문서 정체성이 같다는 뜻이며 metadata가 같다는 뜻이 아니다.
- 교정 원장은 실제 CSV 셀 77개를 변경했다. 공고번호·차수 17쌍, 시작일 5, 마감일 8,
  개찰 3, 제안서 평가 1, 금액 6, 발주기관 2건이 보완·교정됐다.
- 따라서 현재 small vector는 재사용하되 검색용 manifest hash와 표시용 catalog hash를 분리한다.

### Streamlit implementation status
- `text-embedding-3-small + gpt-5-nano`, dense top-10/context top-5/citation 3의 첫 UI를 구현했다.
- UI는 public `midprojectrag.application` facade만 호출하고, versioned bundle이 manifest/chunk/index/catalog
  hash를 검증한 뒤에만 provider를 만든다.
- 문서 범위 선택, 대화, 답변/기권/오류, 사업명·발주기관·페이지 인용, latency/cost/cache 표시를 연결했다.
- Langfuse는 baseline bundle에서 OFF이고 외부 corpus 전송은 매 session 동의 후 요청별로 재검사한다.
- application/config/service와 Streamlit AppTest 12개, 전체 회귀 219/219, source/tests/apps compile,
  repository safety 428파일, `git diff --check`를 통과했다.
- 실제 9,509청크·small 1,536차원 index·교정 catalog 100건 bundle을 OpenAI 호출 없이 검증·로드했고,
  loopback `/_stcore/health`는 `ok`였다.
- Codex in-app browser의 localhost admin policy 검증이 불가해 실제 탭 시각 검증만
  `ENV_BLOCKED_BROWSER_POLICY`로 남겼다. 우회하지 않았으며 실제 API 질의·비용·외부 전송은 없었다.
- 현재 상태는 `AUTOMATED_AND_HEALTH_VERIFIED_BROWSER_VISUAL_PENDING`이다.

## Addendum (2026-08-26) - human-readable metadata audit merge
### Documentation
- 사업명 기준 원래 결측 35문서·71셀의 보완·미보완과 Q0~Q5 예상 답변을 audit-summary에 통합했다.
- 별도 레지스터를 제거하고 README·TODO·handoff 참조를 audit-summary로 일원화했다.

### Tests
- 제목 35/35, 집계 71=43+28, 전체 219 tests, safety 428 files, git diff --check 통과.

## Addendum (2026-08-26) - Streamlit final review and metadata boundary correction

### Correction
- 원본 retrieval manifest와 교정 catalog의 100/100 일치는 `doc_id`·원본 SHA·정규화
  파일명의 문서 정체성이다. metadata는 같지 않으며 실제 CSV 77셀이 변경됐다.
- Streamlit bundle은 교정 catalog hash를 검증하지만 현재 사업명·발주기관 선택/인용
  라벨에만 사용한다. 공고번호·차수·금액·입찰일 보정값은 아직 검색·생성
  context에 연결되지 않았다.
- locator 없는 catalog 값을 기존 page chunk에 넣어 허위 페이지 인용을 만들지 않는다.
  provenance/locator를 보존하는 구조화 metadata retrieval·citation 계약을 후속 gate로 둔다.

### Review fixes
- Langfuse `config_sha256`는 launcher bundle hash가 아니라 실제 retrieval/generation run-config hash를
  전송하도록 수정했다.
- OpenAI egress 동의 문구에 질문·최근 대화 기록·상위 근거 청크 전송 범위를 명시했다.
- catalog/섹션 문자열은 Markdown으로 해석하지 않고 plain text로 렌더하게 했다.
- 최종 수정 후 application/UI 집중 테스트 9/9, 전체 220/220, compile, repository safety
  429 files, `git diff --check`를 통과했다. 실제 OpenAI 질의는 실행하지 않았다.

## Addendum (2026-08-26) - structured metadata lane and Streamlit local E2E

### Delivered
- corrected catalog와 105개 correction ledger를 결합해 12필드 typed fact, exact/range/date AND filter,
  정확한 전체 결과 수와 `doc_id` routing을 구현했다. metadata 변경만으로 재임베딩하지 않았다.
- config 1.1은 correction artifact hash를 필수로 검증하며, local browse는 API 키 없이 시작하고
  OpenAI pipeline은 승인된 첫 body ask에서만 지연 생성한다.
- application 공개 DTO에서 locator 속성 자체를 제거했고, metadata-enabled runtime은 사용자가
  고른 1–20개 문서만 질문 scope로 허용한다. legacy 1.0 all scope는 유지한다.
- Streamlit은 metadata 필터→전체 건수→수동 선택→감사 상태 카드→별도 본문 page citation 흐름을
  제공하며 필터/범위 변경 시 선택·대화를 초기화한다.

### Verification
- 실제 번들 100 cards, 1,200 facts, 105 audited targets, all-match 100, 공개 locator attribute 0.
- 전체 249/249 tests, compileall, repository safety 448 files, `git diff --check` 통과.
- 실제 Streamlit `/_stcore/health=ok`; in-app browser에서 기본/metadata/무결과/100건 비절단/
  카드 분리/동의 전후 입력 상태를 시각 검증했다.
- 독립 계약 리뷰와 application 구현 재리뷰 모두 최종 `APPROVE`; 차단 P0/P1 없음.

### Remaining gate
- private retrieved chunks를 개인 OpenAI로 보내는 단일 small+nano smoke는 managed egress gate가
  destination-specific 재승인을 요구해 process 시작 전에 중단됐다. provider call·추가 비용은 0이며
  우회하지 않았다.

## Addendum (2026-08-27) - personal OpenAI live contract smoke

### Result
- destination-specific 승인 후 explicit 1문서 범위에서 정확히 1회 실행했다.
- `text-embedding-3-small` query embedding, dense top-10, context top-5, `gpt-5-nano` 생성과
  응답 계약 검증이 완료됐다. cache miss였고 Langfuse는 OFF였다.
- 첫 사례는 `insufficient_evidence`로 정상 기권했으며 citation은 0개였다. 즉 live runtime/contract
  E2E는 확인됐지만 실제 인용 답변 품질은 아직 증명되지 않았다.
- 비공개 본문·문서명·locator는 기록하지 않았다. aggregate는 76 embedding tokens,
  2,997 input tokens, 865 output tokens, 13.332초, USD 0.000497370이다.

### Next gate
- 사람이 answerable로 검토한 gold case에서 실제 페이지 인용 답변을 확인하고, 이후 dev 40 전체를
  검토한다. 단일 기권 사례만 보고 top-k·prompt·청킹을 변경하지 않는다.
## Addendum (2026-08-27) - Streamlit local server activation
### Frontend
- small+nano UI를 localhost:8501에 실행했다. (refs: apps/streamlit_app.py)

### Tests
- /_stcore/health=ok를 확인했다. Langfuse는 OFF다.
## Addendum (2026-08-27) - Streamlit startup hardening
### Frontend
- headless 실행으로 바꾸고 자동 생성 skill 링크 2개를 제거했다. (refs: README.md)

### Tests
- 재시작 후 health=ok, skill link 0건을 확인했다. (refs: test/errorlogs/frontend/2026-08-27-streamlit-skills-symlink-side-effect.md)
## Addendum (2026-08-27) - Technology stack snapshot
### Backend
- 활성·선택·실험·목표·비채택 스택을 기준서에 일원화했다. (refs: architecture/specs/technology-stack.md)

### Tests
- 코드·config·artifact 교차검증, 독립 재리뷰 APPROVE, safety 455 files와 diff check를 통과했다.
## Addendum (2026-08-27) - Metadata query and document scope review
### Backend
- metadata top-N 비교와 전체 corpus 검색 복원을 REVIEW_PENDING TODO로 추가했다. (refs: architecture/todolist.md)

### Tests
- 현 코드의 all-scope 경로와 metadata runtime의 explicit 20개 차단을 교차확인했다.
## Addendum (2026-08-27) - Team progress share document
### Documentation
- 실험환경·1차/후순위 스택·Streamlit·후보질문100·구현범위·후속 TODO를 팀 공유문서로 정리했다.

### Tests
- 독립 3관점 재검토 APPROVE, 근거파일 11/11, diff check, safety 457 files를 통과했다.
## Addendum (2026-08-27) - Team progress report HTML
### Frontend
- 기존 단계 선택형 요약을 모든 스펙이 한 화면에 노출되는 스크롤형 보고서 HTML로 교체했다.

### Documentation
- 프로젝트 현황, 데이터·메타데이터, 파이프라인, 런타임 계약, 기술 스택, 평가 결과, 구현 범위, 제약, 후속 TODO를 표·도형·그래프로 통합했다.

### Tests
- 독립 문서·데이터·런타임 리뷰 P0/P1 0건. Chrome 1024/736/360px에서 horizontal overflow 0, page errors 0, 11 sections, 14 tables 확인. CSP와 sandbox 유지, repository safety PASS 458 files.
## Addendum (2026-08-27) - 사업금액 sentinel 2건 확정 및 catalog 스냅샷 동기화
### 변경
- 예약발매시스템 개량 ISMP 용역의 사업금액을 KORAIL 공식 설계서·공고문 근거로 470,251,968원(VAT 포함) 확정했다.
- 운행정보기록 자동분석시스템 개량의 사업금액을 KORAIL 공식 재공고문 근거로 487,150,000원(VAT 포함) 확정했다.

### 산출물
- correction 107건(apply 76, clear 3, retain-null 28), 실제 변경 79셀, corrected catalog 100문서·양수 금액 97·null 3·0/1원 sentinel 0으로 재생성했다.

### 연결
- 새 manifest snapshot과 correction/catalog SHA-256을 활성 small+nano Streamlit config에 반영했다. metadata-only 변경이라 body chunk·embedding·index는 재생성하지 않았다.

### 검증
- manifest join/verify 통과, 전체 unittest 249/249, compileall, git diff --check, repository safety 458 files 통과했다.

### 문서
- audit summary, evidence register, 결측치 스냅샷, structured metadata/technology stack, 팀 공유 Markdown·HTML을 최신 집계로 동기화했다.
## Addendum (2026-08-28) - 사업금액 8건 처리 방법 명시
### Backend
- 사업금액 8건을 사용자 순서로 재정렬하고 원본→최종값·처리법·근거를 명시했다. (refs: audit-summary.md)

### Tests
- 정정 원장 8건 재대조, git diff check와 repository safety 458 files 통과.
## Addendum (2026-08-28) - refined 98-document source migration
### Backend
- 98-row refined CSV now directly materializes 69 metadata cells and 98 canonical bodies (refs: refined-source-of-truth.md)

### Documentation
- Active source contract is 98 documents; historical 100-document runtime remains isolated (refs: requirements/decisions.md)

### Tests
- 252/252 tests, 98/98 manifest verify, safety 462 files passed (refs: refined-csv-field-limit errorlog)

## Addendum (2026-08-28) - refined page/table dual-lane local completion

### Backend
- refined 98문서를 pinned parser로 다시 추출해 실패 0, page chunks 9,331개와 structured table
  Markdown chunks 35,128개를 생성했다.
- HWP top-level body table 10,782개 중 10,728개를 render-tree page/bbox에 exact join했고,
  33,338개 table chunk에 검증된 page를 연결했다. nested 1,524개와 미검증 표에는 page를
  추정하지 않았다.
- page/table exact index, query 1회 embedding, RRF fusion, table context cap, locator citation과
  runtime config v1.2 fail-closed 조립을 구현했다.
- 기존 OpenAI small page vector 9,509개에서 byte-identical refined subset 9,331개를 로컬 이관했다.
  제외 178, 누락·변형 0, vector byte delta 0, network/API 비용 0이다.

### Tests
- 로컬 표 질문 3건 중 행 비교·배점 합계 2건 적중, 병합 header 1건은 table rank 8로 fusion
  top-10에서 누락됐다. local hash 결과만으로 검색 파라미터를 변경하지 않았다.
- 전체 unittest 300/300, 실제 layout/chunk/page_count 교차검증, repository safety 474 files와
  diff check를 통과했다.

### Remaining gate
- 사용자의 destination-specific 승인 후 35,128개 table Markdown을 OpenAI
  `text-embedding-3-small`로 임베딩하고 표 gold를 실행한다.
- 두 API index와 layout을 고정한 v1.2 bundle을 검증한 뒤에만 Streamlit 기본 config를 전환한다.

## Addendum (2026-08-28) - HWP visual evidence and PDF local candidate PoC

### Backend
- 대표 69쪽 HWP에 ordered text/table/image, strict schedule fill, content-addressed image evidence를
  별도 private bundle로 구현했다. 표 104(verified 103), 그림 6/6, ordered occurrence 550이다.
- table visual context v2 대표 청크 278개를 만들고 prior title 171개, row-scoped schedule context
  7개를 연결했다. 기존 display Markdown, locator, source block/page-v1 hash는 불변이다.
- refined PDF 4건 570쪽을 local pdfplumber로 두 번 전수 실행해 byte-identical candidate record
  1,270개(table-line 843, image-geometry 427)를 strict schema로 검증했다.

### Quality boundary
- 일반 ruled PDF 표는 셀 text가 잘 보이지만 일정표 row label 누락과 box diagram 과검출이 있어
  PDF candidate를 verified retrieval로 채택하지 않았다. OCR/diagram understanding도 구현하지 않았다.
- HWP 94건 rollout, 사람 fidelity gold, v2 embedding/index/runtime activation은 다음 gate로 남겼다.

### Tests
- compileall, 전체 unittest 355/355, git diff check, repository safety 503 files를 통과했다.
- 외부 parser/embedding API 호출 0, 기존 canonical artifact hash 변경 0이다.

## Addendum (2026-08-28) - 5-risk → 94-HWP visual corpus local rollout

### Backend
- 위험 유형 5건을 5/5 strict·결정성 gate로 통과시킨 뒤 refined HWP 94/94를 재개형 visual
  bundle로 생성하고 즉시 재실행 94/94 reuse를 확인했다.
- 8,762쪽·표 10,787개·image record 950개·ordered occurrence 77,607개를 reconciliation했다.
  supported source reference 440개는 global canonical object 406개로 보존했고 WMF/GIF 12개는
  provenance-only unsupported로 기록했다.
- 기존 35,128개 table chunk를 visual-context v2로 변환하고 provider-free 2,048차원 local index를
  생성했다. 재실행 cache hit 35,128/35,128이며 외부 API 호출·비용은 0이다.

### Repair and review
- DocLang URI를 exact path 또는 pinned-OTSL ancestry로만 해석하고 prefix/ordinal guessing을 제거했다.
- source media를 magic-led로 검증하고 raw/canonical dual provenance, PNG trailer normalization,
  unsupported-source unlink를 구현했다.
- 독립 리뷰의 strict reuse P1을 수리해 canonical object magic/MIME/dimensions와 status-specific
  render/link proof를 매번 재검증한다. 별도 전수 감사와 retrieval E2E review 모두 PASS다.

### Tests
- 전체 unittest 388/388, compileall, diff check, repository safety 516 files 통과.
- 독립 Schema 124,568 instances 오류 0, local vector 35,128행 전수 재계산 불일치 0.
- Chromium 1,440/1,024/390px report QA에서 overflow 0, image load 정상, page error 0.

### Remaining gate
- 사람 5문서 fidelity gold와 목적지별 private corpus egress·비용 승인 뒤에만 semantic API index와
  기본 Streamlit runtime을 전환한다. OCR/diagram semantics와 PDF verified-table 승격도 별도다.

## Addendum (2026-08-30) - visual image recovery and understanding contract

### Documentation
- HWP/PDF 완료·미완료 수치와 이미지 누락 원인을 구현 계약으로 고정했다.
- occurrence crop→OCR/layout→선택 caption→검색·인용 순서를 TODO에 추가했다.

### Current boundary
- HWP는 94/94 성공했지만 image link는 verified 58, asset-only 382, render-only 498, unsupported 12다.
- HWP all-or-nothing link가 aspect/count/key/unsupported 한 건에도 문서 전체를 unlinked로 만든다.
- PDF 843 table·427 image record는 semantic object가 아닌 geometry candidate다.
- PDF artifact는 현 코드보다 오래됐고 일정표 2건의 body row label 29/29·14/14가 비어 있다.
- PDF 전수 재생성 runner와 현재 venv의 optional pdfplumber가 없어 remediation TODO로 남겼다.

### Decision
- OCR/caption은 provenance를 복구하지 않으며 page+bbox crop에 귀속될 때만 검색 근거가 된다.
- HWP는 rhwp document-local source key를 먼저 노출하고 raw/RGBA+bbox exact match만 fallback으로 쓴다.
- 5유형 human gold 뒤 PP-StructureV3/Korean PP-OCRv5를 먼저 검증하고, 복잡한 도식만 VLM을 쓴다.

### Tests
- private artifact 집계와 HWP/PDF 현 코드 경계를 재감사했다. 이번 변경은 문서·TODO만이며 runtime은 불변이다.
- HWP/PDF 집중 회귀 58/58, git diff check, repository safety 518 files를 통과했다.

## Addendum (2026-08-30) - visual recovery public implementation closeout

### Backend
- HWP/PDF occurrence·crop, offline OCR/caption adapter, bounded visual 검색·인용을 additive v2로 구현했다.
- HWP 대표 5건과 PDF 4건을 재실행했고, reviewed gold 없는 HWP 94 모드는 실행 전에 차단했다.

### Tests
- 전체 unittest 493/493, compileall, JSON Schema 23개, diff-check와 safety 556 files를 통과했다.
- flow HTML은 정적 QA 완료, 인앱 `file://` 검증은 정책 차단으로 별도 기록했다.

### Publication
- 공개 구현 커밋 `df72d69`를 `origin/feat/hwp-visual-corpus-rollout` 신규 브랜치에 푸시했다.
- private corpus·crop·모델 출력, `resources/**`, scoring과 무관한 앱/UI 작업은 커밋에서 제외했다.

## Addendum (2026-08-31) - HWP visual blank-crop correction closeout

### Backend
- `@rhwp/core` page SVG의 embedded raster를 로컬 canvas에 명시적으로 합성하고 nested viewBox,
  viewport/rect clip, 관측된 RGB linear filter와 opacity를 보존했다.
- SVG CSS style/class, display/visibility, definition-only image, 미지원 transform/mask/filter는
  잘못 그리지 않고 fail closed하며 TIFF 1건은 provenance-only quarantine으로 유지한다.
- 대표 5문서를 동결 helper `0b7ab8edd3b3cb6018704b40e1c7b662041a79c857dc99eba66432280cfc0a9b`로
  재생성해 artifact set `visualv2_1a25cd3f5f6c34dfe2e8ff9c`를 canonical로 승격했다.

### Verification
- 27 occurrence 중 eligible 15/quarantined 1/withheld 11이며 crop 15/15와 page render 14/14가
  nonblank다. strict reuse, object hash/ref, orphan/missing/symlink 0을 독립 재감사했다.
- 관련 회귀 31/31, 전체 unittest 505/505, JSON Schema 2/2, compileall, Node syntax,
  diff check와 repository safety 562 files를 통과했다.
- 외부 API 호출과 private egress는 0이다. HWP 94건 실행은 reviewed human gold와 pinned model
  weight gate가 남아 있어 `STOP_WITH_REASON`으로 유지한다.

### Publication
- correction implementation/docs commit `343e489`를
  `origin/feat/hwp-visual-corpus-rollout`에 push했다.
- private 원문·crop·모델 출력과 `resources/**`, 다른 refined98/UI 작업은 commit에서 제외했다.

## Addendum (2026-08-31) - private EDA golden seed 10

### Evaluation data
- 기존 검증 풀 136행에서 고정 ID 10개를 원문 행 그대로 선택해 private EDA seed를 만들었다.
- 난이도는 easy 3 / medium 4 / hard 3이며 10/10 active·answerable·근거 문서 연결·정답 보유,
  ID/정규화 질문 중복 0을 검증했다.
- source SHA-256은 `2dab148e5c361f1d28facb1794a54da748b4b7da42252dbf1ad4668becbef79f`,
  subset SHA-256은 `28ebbcdd2525fec82bb7cbdc5fecab304999787d90d636b87c0c93c5fef0406d`다.

### Privacy and review boundary
- 산출물은 `resources/data_refined/private/evaluation/eda-golden-10-v1.jsonl`과
  `.metadata.json`에만 두고 질문·정답·문서명은 Git과 운영 로그에 기록하지 않았다.
- 외부 API 호출 0회, `private_egress=false`다. source row verification을 상속한 EDA seed이며,
  strict evaluator schema 변환과 named human review 전에는 공식 평가 gold로 승격하지 않는다.

## Addendum (2026-08-31) - supplemental 69 provisional baseline activation

### Backend
- 44/13/12를 56 answer+13 set draft로 만들고 11개 정정·사람 review·answer/set scorer를 고정했다.
- small+mini top-10/context-5, atomic resume, content-free receipt와 명시적 OpenAI egress gate를 구현했다.

### Tests
- evaluation 83/83, 전체 546/546가 통과했다. (refs: 2026-08-26-actual-index-lock-sandbox.md)
- private build는 byte 동일하고 provisional 69/69 PASS, official gate는 미승인 69건을 차단한다.

## Addendum (2026-08-31) - LLM semantic review contract
### Governance
- 답변 의미 품질 판정을 코드 lexical flag에서 고정된 ChatGPT `gpt-5.6-sol` 직접 검수로 전환했다.
### Tests
- 리뷰 HTML 재생성 후 alignment-h16 false flag 제거, supplemental review 3 tests와 diff check PASS.

## Addendum (2026-08-31) - GPT-5.6 direct supplemental baseline score

### Evaluation
- 답변형 56문항을 고정된 ChatGPT `gpt-5.6-sol`이 질문·기준답변·실제답변·검색근거·인용을
  직접 읽어 판정했다. lexical/regex failure flag는 의미점수에서 제외했다.
- 1차 56/56, 독립 2차 5건, 3차 판정 5건을 완료했다. 최종 평균은 46.70/100,
  accepted 19, rejected 35, needs human 2로 품질 gate는 실패했다.
- 의미 구성점수는 정확성 43.52%, 충실성 45.37%, 완전성 43.52%, 주장별 인용 커버리지
  70.37%, 인용 타당성 42.59%다.

### Diagnostics and privacy
- 별도 검색 진단은 document Recall@5 84.57%, MRR@10 0.8247, set-13 Macro F1 23.28%,
  exact set match 0%다. 기존 scorer의 `passed=true`는 구조·실행 통과이지 의미 품질 통과가 아니다.
- 문항별 판정·사유·질문·답변은 ignored private JSONL/HTML에만 저장했다. 공개 영수증은 집계와
  SHA-256만 포함한다.

## Addendum (2026-08-31) - Mini131 frozen harness preflight

### Backend
- Mini 39+90, Sol 판정 이력, blind 입력, parser 2건과 동일 private HTML 계약을 고정했다.
- 세 live preflight는 PASS이며 provider·corpus 재임베딩은 0회다.

### Tests
- parser 2/2, 평가 범위 90/90, 최초 전체 679/679와 syntax·diff check가 통과했다.
- 이후 동시 변경된 visual schema fixture 1건만 전체 재실행에서 실패해 별도 로그로 분리했다.
- 실제 90문항 실행·최종 점수·push는 명시적 OpenAI private-egress 승인 대기다.

## Addendum (2026-08-31) - Mini131 integrated baseline completion

### Live candidate and fixed judge
- 사용자가 OpenAI 목적지·private payload·최대 140회·USD 4 상한을 승인한 뒤 Core40,
  Gap30, Visual/EDA20을 `gpt-5-mini`로 완료했다. 기존 exact 39개는 별도 계보로 보존했다.
- 후보 답변은 수정하지 않고 고정 `gpt-5.6-sol`/`gpt56-semantic-v2`가 RAG 129개를 판정했다.
  primary 129, crossed secondary 13, fresh adjudicator 13의 입력·출력을 모두 private 기록에 남겼다.

### Result and integrity
- 평균 54.845/100, accepted 58, rejected 71, unresolved 0이며 parser C21/C22는 2/2 PASS다.
- 후보 상태 answered 93·abstained 31·error 5, 총 비용 USD 0.21345322다. corpus vector
  재임베딩은 0회이며 query embedding만 실행했다.
- source transcript 129/129와 131개 HTML 카드를 확인했다. private JSONL/HTML은 0600,
  공개 receipt는 0644이고 질문·답변·본문·case ID·provider payload를 포함하지 않는다.

### Verification
- Mini131 preflight `ready=true`, input 28/28, RAG 129/129.
- evaluation 210/210, 전체 unittest 728/728, staged clean-checkout 614/614(비공개 artifact
  통합 테스트 8개 expected skip), 최종 hash·권한·line count 검증 PASS.

## Addendum (2026-09-03) - EH-RC0 Phase 0 relay
### Backend
- runtime/evaluation 경계·empty scope·typed predicate·결정론 scorer·provider-free replay 구현. 기존 앱 경로는 유지했다.
- 실제 저장 답변129/source hash129 검증, 최종 코드 SHA의 private replay-03. 생성/API0; 새 검색 성능 향상은 미측정.
### Tests
- focused47/full852 PASS, skip0. 리뷰18재현·compile·safety·flow Playwright PASS; 오류 수리 기록 연결.
- refs: bidfit-evidence-harness-v1-rc0-implementation-report.md, bidfit-evidence-harness-v1-rc0-active-context.md.

## Addendum (2026-09-03) - EH-RC0 Phase 1 relay
### Backend
- immutable EvidenceStore, 1,600자 compatibility/heading challenger, 실제 KURE child dense, Kiwi BM25, RRF와 bounded context를 구현했다.
- 98문서에서 parent 9,331, child 9,496를 새 private namespace에 생성했다. 구조 challenger 62,382는 미임베딩 비교 artifact로만 보관했다.
- 기존 page 9,331 index는 legacy control로 그대로 load/search했다. 원본 SHA 유지, 생성/API 호출0, 기존 artifact overwrite0.
### Tests
- Phase1 focused35/full887 PASS, skip0. 실제 child/legacy search smoke와 hash/load 검증, safety780, flow Playwright PASS.
- real smoke의 dense-only21/lexical-only21/both9는 lane 동작 증거이며 골든셋 성능 향상 주장 근거가 아니다.
### Next
- EH2.1 QueryPlan/budget/version registry부터 E1 state loop를 retrieval 위에 연결한다.
- refs: bidfit-evidence-harness-v1-rc0-implementation-report.md, ../architecture/specs/bidfit-evidence-harness-v1-rc0-flow-validation.md.
## Addendum (2026-09-04) - EH2.5 sealed state and typed action
### Backend
- Compare/follow-up state projection, typed actions, deterministic decision chain을 구현했다. (refs: ../architecture/specs/bidfit-evidence-harness-v1-rc0.md)

### Tests
- focused55/full1020·독립 재검토 PASS. API·Langfuse 호출 0. (refs: ../test/errorlogs/backend/2026-09-04-eh25-bound-compare-nested-authority.md)

## Addendum (2026-09-04) - EH2.6.b1 sealed fact authority
### Backend
- BoundFact·fact 초기 state와 exact request/planner/catalog/store authority를 구현했다. (refs: ../architecture/specs/bidfit-evidence-harness-v1-rc0.md)
### Tests
- focused47/full1034/safety807·독립 리뷰 PASS. API·Langfuse 0회. (refs: ../test/errorlogs/backend/2026-09-04-eh26-b1-live-authority.md)

## Addendum (2026-09-04) - EH2.6.b2 execution config/runtime authority

### Backend
- Closed/hash-bound `HarnessExecutionConfig`와 exact production/synthetic `HarnessRuntimeBinding`을 구현했다.
- EvidenceStore, KURE dense, Kiwi lexical, RRF hybrid와 root bind/validate/serialize의 callable·class descriptor·registry/entry를 traversal 전에 봉인했다.
- production은 loader-attested KURE/Kiwi/hybrid와 내부 monotonic clock만 허용하며 verifier/reranker는 승인 전 unavailable이다. 실제 lane receipt 실행은 EH2.6.b3이다.

### Tests
- focused104/full1109/safety811·py_compile·diff-check PASS. 독립 리뷰 P1 10건 수리 후 최종 재리뷰 PASS.
- bind/validate 동안 API·Langfuse·retriever·tokenizer·model/provider·verifier·reranker·clock 호출 0회.
- refs: ../test/errorlogs/backend/2026-09-04-eh26-b2-runtime-authority.md, bidfit-evidence-harness-v1-rc0-checkpoint.md.

### Next
- EH2.6.b3: owner-issued `RetrievalObligation`과 독립 dense/lexical `LaneSearchReceipt`, exact-once 소비를 구현한다.

## Addendum (2026-09-05) - EH2.6.b3 repair and b4 fusion/E0 relay

### Backend

- b3 copied-globals executor provenance를 exact code+module-global namespace로 닫았다.
- same-round stage-4 `FusionReceipt`와 state-free `E0ControlReceipt`를 구현했다.
- provider 반환 뒤 child dependency/type/receipt를 재검증하고, obligation별 dense→lexical→fusion 순서를
  강제하며 closure-cell pin과 dual immutable history로 replay를 차단한다.

### Tests

- b4 focused27, b3+b4 64, 관련214, 전체1175, safety828 PASS.
- 정·역순 교대 10회 총640 PASS와 독립 APPROVE(P0/P1/P2 없음).
- 실제 API/model/Langfuse 호출 0. retrieval 품질 개선은 아직 측정하지 않았다.

### Next

- EH2.6.b5 focused gate 뒤 effect/reducer와 bounded E1 controller를 순차 구현한다.
- refs: `review/review-eh2-6-b4-fusion-e0-2026-09-05.md`,
  `../architecture/specs/evidence-harness-progress-flow-validation.md`.

## Addendum (2026-09-05) - EH2.6.b5 focused retrieval gate

### Backend

- b3/b4 production surface를 바꾸지 않고 lexical-only rescue, fact all-empty state-free 완료,
  pre-call zero-dispatch, provider-error lexical diagnostic/no-fusion 네 경계를 전용 테스트로 고정했다.
- parent `EH2.6.b` source/runtime/retrieval receipt 기반을 완료로 닫고 다음 READY를 `EH2.6.c1`로 옮겼다.

### Tests

- b5 focused4, b3+b4+b5 68, 관련218, 전체1179 PASS; 독립 리뷰 2건 APPROVE(P0/P1/P2 없음).
- 실제 API/model/Langfuse 호출과 VLM/golden 품질 실행은 0이다.

### Next

- EH2.6.c1 candidate projection부터 effect/reducer와 bounded E1 controller를 순차 구현한다.
- refs: `review/review-eh2-6-b5-focused-gate-2026-09-05.md`,
  `../architecture/specs/evidence-harness-progress-flow-validation.md`.

## Addendum (2026-09-05) - one-shot relay re-entry

### Process

- B5 push 뒤 멈춘 relay 오류를 기록하고 Cycle 4 `EH2.6.c1` form을 즉시 열었다.

## Addendum (2026-09-05) - EH2.6.c1 E1 follow-up projection

- EH2.3 verified 주장을 candidate로 낮추고 primary→fallback dedupe와 slot별 동일 doc 후보 투영을 구현했다.
- 초기 state는 coverage 0·all-open·stop false이며 metadata predicate는 EH3.1 receipt 전까지 fail-closed한다.
- public extra/gold, foreign outcome/store clone, dependency·단일 private pin/registry drift를 호출 전에 차단한다.
- focused7·관련60·전체1186·safety837 PASS, 독립 리뷰 3건 APPROVE. `a9ac527` push, 외부 호출 0이다.
- 다음 READY는 exact runtime verifier receipt를 구현하는 `EH2.6.c2`다.
- 계속 요청+안전한 READY TODO이면 다음 form 시작 전 final을 금지한다.

### Next

- EH2.6.c2 semantic verifier receipt를 계약-first로 구현·검증·푸시하고 다음 TODO로 재진입한다.

## Addendum (2026-09-05) - EH2.6.c2 semantic verification receipt

### Backend

- fact/compare/follow-up exact owner에서만 target·query·supplied evidence를 유도하는 factory-only semantic
  obligation을 구현했다.
- exact `verify(self, request)`를 local at-most-once로 호출하고, ID-less request와 닫힌 typed result를
  supplied evidence의 support/value/contradiction receipt로 봉인했다.
- verifier 부재는 zero-call unavailable, provider/contract/post-call drift는 fixed error+consumed attempt로
  처리하며 c2 receipt는 state-free로 유지했다.

### Tests

- normalizer+semantic focused 26/26, 검색/fusion/follow-up 관련 118/118, 전체 1,212/1,212,
  repository safety 846파일 PASS.
- 독립 감사에서 발견한 `SCHEMA_VERSION`/validator/unicode 전역 재바인딩과 receipt 완료 전환 원자성을
  수리하고 전용 zero-call 회귀를 추가했다.
- Mermaid current PNG와 HTML을 갱신했고 Playwright desktop/mobile에서 images2, tables8, page errors0,
  mobile overflow0 PASS. API·OpenAI·실제 model·Langfuse 호출은 0이며 synthetic verifier만 실행했다.

### Next

- `EH2.6.c3`: expansion/bridge/rerank/verify `ActionEffectReceipt`와 bounded zero-provider absence receipt를
  계약-first로 구현한다.

## Addendum (2026-09-05) - EH2.6.c3.1 parent/bridge source receipts

### Backend

- immutable candidate seed의 config-bounded prefix에서 caller ID 없이 `ParentContextReceipt`와
  table/figure `BridgeContextReceipt`를 발급한다.
- parent는 context-only `ProvenanceParent`로 보존해 evidence/support/citation으로 승격하지 않고, bridge는
  실제 `EvidenceStore.bridge`의 linked evidence 또는 `empty` 시도를 봉인한다.
- at-most-once claim/history/cache를 exact owner root source 수명에 묶어 중간 semantic obligation GC와
  동등 obligation 재발급을 통한 authority remint를 차단했다.

### Tests

- TDD RED 뒤 focused 8/8, semantic/retrieval/action/state 관련 114/114, 전체 1,220/1,220,
  repository safety 850파일 PASS.
- 독립 감사의 root-lifetime P1을 최소 수리하고 semantic GC 회귀를 추가했다.
- API·OpenAI·model-provider·Langfuse·VLM·golden 호출은 0이며 synthetic/offline fixture만 실행했다.

### Next

- `EH2.6.c3.2`: ID-less exact-once rerank receipt와 parent/bridge/rerank를 반영한 derived semantic
  obligation을 새 원샷딜 폼에서 계약-first로 구현한다.
- refs: `../test/errorlogs/backend/2026-09-05-c3-context-source-lifetime.md`,
  `../architecture/specs/evidence-harness-progress-flow-validation.md`.

## Addendum (2026-09-05) - EH2.6.c3.2 rerank and derived semantic

### Backend

- ID-less rerank, owner budget, global role order, unindexed parent, one-shot derived route를 구현했다.

### Tests

- focused9/related128/full1229/safety854·Playwright PASS; provider 예외 post-call P1을 수리했다.
## Addendum (2026-09-05) - EH2.6.c3.3 bounded absence receipt
### Backend
- Three-reason zero-provider absence와 follow-up root-lifetime exact-once를 구현했다.

### Tests
- focused67·related192·full1267·safety858·Playwright PASS; API/model/Langfuse 0.

### Next
- EH2.6.c3.4 closed ActionEffectReceipt DTO/validator를 새 원샷딜 폼으로 시작한다.
## Addendum (2026-09-05) - EH2.6.c3.3 publication and relay
### Git
- 7dd5ad4를 origin/feat/total-integration에 선택 push했다; resources/private/gold/VLM 및 무관 dirty는 제외했다.

### Relay
- CONTINUE_WITH_NEXT_FORM으로 EH2.6.c3.4 closed ActionEffectReceipt DTO/validator form을 열고 contract/TDD 착수했다.

### Boundary
- public effect mint는 exact d2 ControllerDecisionReceipt permit 전까지 fail-closed하며 API/model/Langfuse 호출은 0이다.

## Addendum (2026-09-05) - EH2.6.c3.4 closed action effect value

### Backend

- 19-field `ActionEffectReceipt`와 pure validator를 추가하고 public mint/issuer/authority는 닫았다.
- source kind·context·absence·serialization drift의 독립 리뷰 P1/P2를 수리했다.

### Tests

- focused11·related114·full1278·safety861·Playwright PASS; 독립 APPROVE, 외부 호출 0.

### Next

- EH2.6.c3.5 live-authority/replay/nonpromotion adversarial gate로 즉시 릴레이한다.
## Addendum (2026-09-05) - EH2.6.c3.4 publication and relay
### Git
- 3c2d7d0 pushed to origin/feat/total-integration; only C3.4 code/test/contract/report/log paths and hunks were selected.

### Relay
- CONTINUE_WITH_NEXT_FORM selects EH2.6.c3.5 and starts its contract/adversarial RED immediately.

### Boundary
- ActionEffectReceipt remains structural-only; public mint/reducer/authority and live API/model/Langfuse calls remain absent.
## Addendum (2026-09-05) - EH2.6.c3.5 publication and relay
### Scope
- Structural ActionEffectReceipt non-authority and seven live source-validator authority regressions.

### Change
- Added constant redacted repr, exact all-effect public/module inventory, clone/replay/serialization/subclass nonpromotion gates, and coherent alternate-live-graph validation for lane/fusion/parent/bridge/rerank/semantic/absence.

### Verification
- Focused 18/18, related 147/147, full 1288/1288, repository safety 867 files, Mermaid render and Playwright images2/tables8/page-errors0/mobile-overflow0; independent review APPROVE with P0/P1 none.

### Publication
- Commit aa0ff9d pushed to origin/feat/total-integration; unrelated dirty and resources excluded.

### External calls
- OpenAI/model/Langfuse/golden/VLM calls 0; synthetic offline fixtures only.

### Relay
- CONTINUE_WITH_NEXT_FORM to EH2.6.d1 ExecutionLedger and HarnessExecution aggregate.
## Addendum (2026-09-05) - EH2.6.d1 publication and relay
### Backend
- Initial-only ExecutionLedger/HarnessExecution authority sealed and pushed as 6ada15b.

### Tests
- Focused 10, related 234, full 1298, safety 868, browser QA and independent review passed.

### Maintenance
- Next READY leaf is EH2.6.d2 allowed-action and decision-permit contract; external calls remain zero.
## Addendum (2026-09-05) - EH2.6.d2.i publication and relay
### Backend
- Revision-0 fact/compare ControllerAction and selected-first ControllerDecisionReceipt authority sealed; parent d2 remains PARTIAL.

### Tests
- Focused 18/18, related 278/278, full 1306/1306, safety 873 files, browser QA and independent adversarial review APPROVE.

### Git
- Commit dac3338 pushed to origin/feat/total-integration; unrelated dirty and resources were excluded.

### Relay
- CONTINUE_WITH_NEXT_FORM selects EH2.6.c4.0 source-owner authority; API/model/Langfuse/golden/VLM calls remain zero.
## Addendum (2026-09-05) - EH2.6.c4.0.a source-owner publication and relay
### Backend
- State 생성 시 exact Bound/coverage/outcome/registry/policy를 closure-private source-owner authority로 봉인하고 HarnessExecution이 exact initial-state identity로만 상속하도록 구현했다.

### Integrity
- Equal-hash payload clone, 사후 owner 부착, legacy follow-up 승격, owner 재사용과 validator/accessor drift를 fail-closed했다.

### Tests
- Focused+인접 43/43, 전체 1315/1315, safety 874 files, Playwright images2/tables8/page_errors0/mobile_overflow0, 독립 적대 리뷰 APPROVE(P0/P1 0).

### Git
- Commit c0455f8 pushed to origin/feat/total-integration; unrelated dirty and resources were excluded.

### Relay
- CONTINUE_WITH_NEXT_FORM selects EH2.6.c4.0.b typed source/outcome resolver; parent c4.0 and d2 remain PARTIAL, external API/model/Langfuse/golden/VLM/provider/clock calls remain zero.
## Addendum (2026-09-05) - EH2.6.c4.0.b typed source/outcome resolver 완료
### Scope
- exact controller decision·source-owner·live receipt graph에서 closed source/outcome projection을 유도했다. effect mint·claim/history·reducer·ledger/state transition은 열지 않았다.

### Implementation
- lane/fusion/parent/bridge/rerank/semantic/absence/controller-decision receipt를 기존 authority·validator로 역참조하고 action kind·obligation·target·root identity를 대조했다. direct issuer, forced mutation, structural/equal-payload clone, dependency drift와 GC remint를 차단했다.

### Validation
- focused 14/14, controller 인접 29/29, source-validator 인접 168/168, 전체 1329/1329, safety 877파일, HTML desktop/mobile PASS. 독립 최종 리뷰 APPROVE, correctness finding 0.

### External calls
- API/OpenAI/model/Langfuse/golden/VLM/provider/clock 호출 0.

### Git
- ab5a223 feat(harness): resolve typed controller sources 를 origin/feat/total-integration에 push했다.

### Next
- TODO를 재조회해 EH2.6.c4.0.c one-step claim/history를 다음 READY leaf로 선택하고 새 원샷 form 및 첫 RED를 즉시 실행한다.
## Addendum (2026-09-05) - EH2.6.c4.0.c one-step history 완료 및 c4.0.d 릴레이
### Scope
- feat/total-integration에서 exact controller one-step claim/history를 closure-private authority로 구현하고 c4.0.c를 완료했다.

### Implementation
- claim-authorized prepare→source, shared lane attempt epoch/claim cutoff, callback-free weak registry와 exact discard, live execution 수명의 failed tombstone을 추가했다.

### Repair
- 독립 리뷰에서 helper drift tombstone 우회, root drift 중 claim/projection GC, source registry drift 후 재시도를 재현해 mutable-root validation과 독립된 mirrored emergency failure path로 닫았다.

### Validation
- focused 30/30, adjacent 249/249, full 1359/1359, repository safety 881 files, git diff --check PASS, independent review APPROVE.

### Publication
- 선택 커밋 3fb2363 (feat(harness): seal controller step history)을 origin/feat/total-integration에 push했다. user-owned dirty와 resources는 제외했다.

### External calls
- OpenAI/API/model/Langfuse/golden/VLM/provider/clock 실제 호출은 0회다.

### Next
- refreshed TODO의 EH2.6.c4.0.d를 READY로 선택한다. exact semantic authority와 validated target에서 parent/table/figure exact-one을 고르고 rerank용 full batch tuple identity/order를 보존하는 private non-authorizing accumulator의 첫 RED를 즉시 실행한다.
## Addendum (2026-09-05) - EH2.6.c4.0.d target context accumulator 완료 및 c4.0.e 릴레이
### Scope
- exact semantic obligation의 bounded context target에서 parent/table/figure receipt exact-one과 complete rerank batch identity/order를 보존하는 private non-authorizing accumulator를 구현했다.

### Repair
- captured selection helper drift를 pinning으로 차단하고 executable weakref callback을 제거했다. live semantic root remint tombstone과 dead-root passive cleanup을 분리했으며 missing/duplicate/wrong-role 변조 회귀를 추가했다.

### Validation
- focused 13/13, context/controller/source adjacent 175/175, full 1372/1372, repository safety 883 files, git diff --check와 Chrome/Playwright QA PASS, independent review APPROVE(P0/P1 0).

### Publication
- f154a75 feat(harness): seal target context accumulation 및 fdb8520 docs(harness): close target context relay를 origin/feat/total-integration에 push했다. user-owned dirty와 resources는 제외했다.

### External calls
- API/OpenAI/model/Langfuse/golden/VLM/provider/clock 실제 호출은 0회다.

### Next
- refreshed TODO의 EH2.6.c4.0.e structural-effect bridge를 READY leaf로 선택해 새 Cycle 17 form과 첫 RED를 시작한다.

## Addendum (2026-09-05) - EH4.7a 단계별 근거 평가 선행
### Backend
- Mini131 원본 유지. source resolver·전후 Recall·관련 retention·lane rescue·private CLI 구현. 계약: stage-evaluation-v1.md.
- 전체131 수량 guard·부분 결과 표시·전용 suite 분리. 원문/질문/API/기본 runtime·VLM 변경 없음.
### Tests
- 집중·관련112 PASS, 실제98문서/20,118블록 출처 검증 PASS, 독립 재리뷰 APPROVE. 모델/API 호출0.
- PNG2종 검토 완료. HTML 브라우저 QA는 URL 정책으로 BLOCKED. refs: 2026-09-05-stage-evaluation.md.
### Next
- 기존131 위치 qrel 재사용→실제 단계 recorder→동일 문항 실측. EH4.7 전체 완료나 성능 향상으로 표기하지 않음.

## Addendum (2026-09-05) - 검색 비교 우선 TODO 재구성
### Architecture
- 기존 ID157 상태를 보존하고 입력→recorder→지표/동결→3종 비교로 실행 큐·checkpoint/resume을 정합화했다.
- Controller c4.0.e는 기술 READY/우선순위 대기. VLM·기본 profile·131문항/답변 무변경.
### Tests
- 112 관련 회귀·diff·ID 보존 PASS, 독립 재리뷰 APPROVE. schema 선행·pre-context·고정 paired 분모 보완.
- PNG2 생성/직접 검토 완료. HTML browser는 정책 차단 유지. refs: 2026-09-05-search-first-relay.md.
### Next
- 다음 EVAL.4.a 입력·위치 감사→.4.b adapter를 새 Cycle B 폼으로 선택했다. 선택 push 후 착수한다.

## Addendum (2026-09-06) - 검색 선행 납품 회귀 재검증
### Tests
- 전체1393: 최초1390 PASS/환경실패2/skip1. 권한을 맞춘 해당2건 재실행 PASS; 코드 변경 없음.
- refs: test/errorlogs/backend/2026-09-06-search-first-test-permissions.md. HTML browser BLOCKED는 별도 유지.

## Addendum (2026-09-06) - EH2.EVAL.4 입력 adapter 완료
### Backend
- 기존 pinned8 입력·131ID와 원문 위치를 재검증하고 private qrels/inventory adapter를 구현했다. 질문/답변/검수 불변.
- 실제131 생성: ready30/missing67/not-applicable34. 보조69 검수 재사용, 후보186 자동 gold 승격 금지.
### Tests
- focused15·관련65 PASS, 독립 APPROVE, 실제CLI 신규 private 저장 PASS. 모델/API0·공식 비교 미승인.
- refs: test/errorlogs/backend/2026-09-06-stage-inputs-validation.md, work/2026-09-05-search-first-relay.md.
### Next
- EXP-SELECT.2.a 최소 recorder schema→EH4.7b.1 실제 단계 기록으로 릴레이. 위치 의미 승인 .4.c는 별도 잔여.

## Addendum (2026-09-06) - 검색 단계 recorder 완료
### Backend
- local3종 draft와 raw lane/fusion/context 관측기를 구현했다. content-free hash chain, 실패/미실행/빈 결과 구분.
- raw50/full union 뒤 반환10/context5를 적용한다. 기본 앱·VLM·gold·index 무변경, 이번 모델/API0.
### Tests
- recorder12·관련88 PASS/독립 APPROVE. child kind/query SHA/timer 수정 및 테스트 모듈명 재탐색 후 통과.
- refs: test/errorlogs/backend/2026-09-06-stage-recorder-validation.md. HTML browser BLOCKED는 별도 유지.
### Next
- 로그·선택 push 후 Cycle D EH4.7b.2 실제 로컬 KURE smoke 착수. 정식 성능 비교 승인과 구분한다.

## Addendum (2026-09-06) - 로컬 검색12회 smoke 완료
### Backend
- 기존 인덱스로 원래2질문×3종×2회 검색/기록 PASS. query embedding12, API·생성0, 파일 불변·반복 후보 동일.
- 기존131 평가셋은 유지했다. 신규002 private만 저장, 초기 cache 실패001도 보존. receipt는 search-first relay 참조.
### Tests
- HF startup cache 실패 재현·수정 후 실제 PASS. 관련93 PASS/독립 APPROVE, 파일15개0600·폴더0700·Git ignored.
- refs: test/errorlogs/backend/2026-09-06-retrieval-smoke-runtime.md. smoke wall은 관측 비용 포함이며 품질·serving latency 아님.
### Next
- Cycle D 선택 push 후 EH4.7c.1.a/b/c 순위 지표·원래 문서 qrels·CLI 통합으로 릴레이한다.

## Addendum (2026-09-06) - 순위 채점·원래 문서 qrels 연결
### Backend
- source/doc RR·nDCG, 원래131 inventory와 CLI/집계를 연결했다. refs: `architecture/specs/stage-evaluation-v1.md`.
- source-ready30/doc-ready97 분리; formal 승인 없음. 다음 EXP-SELECT.2.a.2.i 사전 감사 폼을 열었다.
### Tests
- 관련118·독립34 PASS. 기존12기록 재채점6파일 PASS/모델0·입력 불변. refs: `2026-09-05-search-first-relay.md`.
- PNG 확인, HTML browser 기존 BLOCKED 유지. refs: `test/errorlogs/backend/2026-09-06-stage-ranking-validation.md`.

## Addendum (2026-09-06) - 다음 TODO 전체131 사전 감사 완료
### Backend
- original request/source를 결합한 private readiness CLI 구현. 기술 후보 source30/doc84, 공식분모 null·모델0.
- .2.a.2.i 완료 후 .ii 비교범위/기준·승인 연결 결정 대기. refs: `2026-09-05-search-first-relay.md`.
### Tests
- focused9/관련127·독립 APPROVE, 실제 최신002 감사 PASS/0600·Git ignored. 이전001 보존.
- source/request 합성 gap 수정. refs: `test/errorlogs/backend/2026-09-06-readiness-source-binding.md`. browser 기존 BLOCKED.

## Addendum (2026-09-06) - EH2.6.c4.0.e structural-effect bridge 완료
### Architecture
- exact sourced claim과 bounded target context를 closure-private structural bridge로 결합했다.
- bridge는 immutable/non-serializable/redacted이며 c4.1 전에는 effect mint·history advance·transition·public
  surface로 승격되지 않는다. same-object idempotence와 root-lifetime remint tombstone을 고정했다.
### Backend
- `_require_controller_step_source`, `_prepare/_require_controller_structural_effect_bridge`와 private
  `_ControllerStructuralEffectBridge`를 추가했다. caller payload/hash/outcome 주입, clone/mixed/out-of-order/
  mutation/dependency drift를 fail-closed한다.
### Tests
- focused7/7, c4.0.c/d/e 인접50/50 PASS. `git diff --check`·repository safety 941파일 PASS.
- 전체1,438건의 23 errors/2 failures는 private index lock, 미설치 선택 의존성, sandbox loopback 정책의
  환경 실패이며 신규 bridge 실패는 없다. 외부 API/model/Langfuse/golden/VLM/provider/clock 호출 0회.
- refs: `fivecircles/test/errorlogs/backend/2026-09-06-eh2-6-c40e-full-regression-environment.md`,
  `fivecircles/architecture/specs/controller-structural-effect-bridge.md`.
### Next
- `EH2.6.c4.1` initial effect/transition을 다음 relay 단위로 선택했다. d2.x cross-state decision,
  c4.2 reducer, EH3/EH4와 동일 golden 성능 비교는 이후 단계로 남긴다.

## Addendum (2026-09-06) - Python 실행환경 오류 해결
### Backend
- 프로젝트 `.venv` extras 설치 동기화 완료. 기존 패키지 모두 충족, pip check 정상·ML lock32 불일치0.
- bare Miniconda 사용 오류를 정정하고 README·testpolicy에 `.venv/bin/python`과 `-t .`을 고정했다.
### Tests
- 기존 실패 영역153/153, 전체1498/1498 PASS(211.055초). 오류·실패·skip0; 앱 코드·테스트 변경 없음.
- refs: `fivecircles/test/errorlogs/backend/2026-09-06-eh2-6-c40e-full-regression-environment.md`.

## Addendum (2026-09-06) - Python 환경 오류 Arrest 기록
### Operations
- Python 오선택·패키지 누락 오진·동일 실패 재실행을 `fivecircles/agent/mistakes-arrest.md`에 기록했다.
- interpreter 확인·lock 대조·실패 영역 재검증 규칙을 고정하고 기존 오류 로그와 연결했다.

## Addendum (2026-09-06) - EH2.6.c4.1 최초 dense 실행 전이
### Backend
- 원본 receipt→live effect→ledger1→transition→successor 연결. 동일 state와 predecessor 권위 유지, 중복 발급 차단.
### Tests
- 신규13·인접합91·전체1511 PASS(174.977초, 오류/실패/skip0), 독립 APPROVE. API·모델0.
- current/target PNG·Chrome desktop/mobile 보고서 PASS. refs: `2026-09-06-controller-initial-transition-relay.md`.
### Next
- d2.x ledger-aware decision을 다음 릴레이로 선택. c4.2·controller/E2E·동일 골든셋 품질 비교는 미완성.

## Addendum (2026-09-06) - EH2.6.d2.x.a 다음 행동 선택
### Backend
- exact dense 전이 후 ordinal2 lexical/진단/기권 선택. budget 우선·closed reason 봉인·초기 행동 유지, 정책 hash revision 명시.
### Tests
- 신규11·인접79·전체1522 PASS(186.315초, 오류/실패/skip0), 독립 APPROVE·Chrome desktop/mobile PASS. 모델0.
### Next
- c4.2.a 실제 lexical/전이2 → d2.x.b 후속 자격 순으로 분할. refs: `2026-09-06-controller-next-decision-relay.md`.

## Addendum (2026-09-07) - 협업 릴레이 스킬 동기화
### Operations
- 프로젝트 협업 스킬·관련 훅 동기화, 독립/내장 fivecircles 루트와 spec/specs 경로 보존.
- 제품·기존 변경 제외, 현재 브랜치의 지정 파일만 커밋/푸시. refs: `2026-09-07-collaboration-skill-sync.md`.
### Tests
- 후보 스킬23·JSON6·참조19 통과, 한글명3 예외 유지. 독립 Astra의 세 프로젝트 경로/변경 보존 검수 PASS.

## Addendum (2026-09-07) - EH2.6.c4.2.a lexical 전이
### Backend
- 같은 항목 lexical1회 실행과 effect/ledger2/transition2 연결. 이전 근거·dense 오류 보존.
- 범위·검수: work/review/review-controller-lexical-transition-2026-09-07.md.
### Tests
- 집중36·관련98·격리134·전체1534 PASS, 오류/실패/skip0. fresh Astra PASS.
- 재개 wiring·pin 순서 수리: test/errorlogs/backend/2026-09-07-controller-lexical-resume-import.md.
### Relay
- run=eh-relay-20260907 / batch=EH2.6.c4.2.a. 통합 전 로그올; 실제 SHA는 사후 영수증에 기록.
- 다음=d2.x.b 후속 자격. 앱 모델/API/골든셋 실행0; 전체 Controller/E2E는 미완성.
