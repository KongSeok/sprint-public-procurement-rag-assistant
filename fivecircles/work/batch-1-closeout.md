# Batch 1 Closeout — Private Corpus Ingestion

상태: IN_PROGRESS_FIDELITY_QA
날짜: 2026-08-24

## 구현 완료

- `Copy of ` 1회 제거 + Unicode NFC 기반 CSV↔원문 exact join
- 원문 SHA-256, snapshot ID, parser/version, 상태·경고를 보존하는 private manifest
- `pypdf` PDF 페이지 adapter와 `hwp5txt` HWP 문단 adapter
- 대용량 PDF Pipe 결과를 수신 후 worker를 종료하는 deadlock 방지
- HWP XML 변환 실패 시 격리 pyhwp binary-model 텍스트 fallback
- stable source block, content hash, source locator, PII 유형별 개수
- `manifest`, `extract`, `verify` CLI와 원자적 JSON/JSONL 쓰기
- data root 밖 path traversal·symlink, 원문 hash drift, 잘못된 doc ID의 fail-closed 처리
- stdout에서 절대경로·본문·PII를 제외한 집계 전용 결과

## 검증

- 표준 라이브러리 `unittest`: ingest 27개 통과 — 대용량 PDF 결과와 HWP fallback·오류 분류 회귀 포함
- `compileall`: 별도 `/tmp` pycache를 사용해 통과
- JSON Schema 문법 검사 통과
- HWP subprocess와 PDF 격리 process에 문서별 timeout 적용
- 저장소 안전 검사와 restricted artifact ignore 정책은 Batch 통합 단계에서 재실행

## 외부 실사

- 지정 corpus 인벤토리: metadata CSV 100행, 원문 100건(HWP 96, PDF 4), 정규화 후 파일명 100/100 대응
- private snapshot: 실제 CSV↔원문 100/100 조인, HWP 96건 `partial`, PDF 4건 `ok`, 실패 0건
- 최종 `require-extracted` 검증: 문서·블록·입력 hash·provenance 오류 0건
- 로컬 LibreOffice HWP 필터는 구형 HWP97용이므로 HWP5 직접 추출기에서 제외

## 남은 항목

- HWP 페이지·표와 PDF 표·bbox fidelity를 대표 표본으로 QA한다.
- baseline에는 현재 stable paragraph/page block을 사용하고, QA가 입증할 때만 고비용 fallback을 추가한다.

실제 source blocks가 준비되어 Batch 2 private gold 작성을 시작할 수 있다.
