# Batch 1 Closeout — Private Corpus Ingestion

상태: BLOCKED_REAL_CORPUS
날짜: 2026-08-24

## 구현 완료

- `Copy of ` 1회 제거 + Unicode NFC 기반 CSV↔원문 exact join
- 원문 SHA-256, snapshot ID, parser/version, 상태·경고를 보존하는 private manifest
- `pypdf` PDF 페이지 adapter와 `hwp5txt` HWP 문단 adapter
- stable source block, content hash, source locator, PII 유형별 개수
- `manifest`, `extract`, `verify` CLI와 원자적 JSON/JSONL 쓰기
- data root 밖 path traversal·symlink, 원문 hash drift, 잘못된 doc ID의 fail-closed 처리
- stdout에서 절대경로·본문·PII를 제외한 집계 전용 결과

## 검증

- 표준 라이브러리 `unittest`: 22개 통과 — 합성 HWP, 무텍스트 PDF, join collision, metadata snapshot, source hash drift, malformed manifest, forged provenance, symlink/path traversal, 계약/CLI 검증
- `compileall`: 별도 `/tmp` pycache를 사용해 통과
- JSON Schema 문법 검사 통과
- HWP subprocess와 PDF 격리 process에 문서별 timeout 적용
- 저장소 안전 검사와 restricted artifact ignore 정책은 Batch 통합 단계에서 재실행

## 외부 실사

- 지정 corpus 인벤토리: metadata CSV 100행, 원문 100건(HWP 96, PDF 4), 정규화 후 파일명 100/100 대응
- 원격 HWP 표본 1건: OLE CFB 기반 HWP5 v5.1 계열; 전체 96건을 대표한다고 간주하지 않음
- 로컬 LibreOffice HWP 필터는 구형 HWP97용이므로 HWP5 직접 추출기에서 제외

## 차단 항목

- private 원문 100건이 로컬 Git 밖 데이터 디렉터리에 아직 materialize되지 않음
- 격리 Python 3.11 환경에 `pyhwp`/`hwp5txt`가 아직 설치·고정되지 않음
- 따라서 실제 100/100 manifest, HWP 페이지·표 fidelity, 4 PDF 전체 추출과 수동 QA는 미실행

이 차단은 Batch 2의 공개 평가 계약·합성 검증과 독립적이므로 다음 배치로 진행한다.
