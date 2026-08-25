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
