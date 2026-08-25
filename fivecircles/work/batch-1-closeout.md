# Batch 1 Closeout — Private Corpus Ingestion

상태: IN_PROGRESS_FIDELITY_QA
날짜: 2026-08-25

## 구현 완료

- `Copy of ` 1회 제거 + Unicode NFC 기반 CSV↔원문 exact join
- 원문 SHA-256, snapshot ID, parser/version, 상태·경고를 보존하는 private manifest
- `pypdf` PDF 페이지 adapter와 `hwp5txt` HWP 문단 adapter
- 대용량 PDF Pipe 결과를 수신 후 worker를 종료하는 deadlock 방지
- HWP XML 변환 실패 시 격리 pyhwp binary-model 텍스트 fallback
- 체크섬 검증 `rhwp v0.8.4` 페이지 텍스트·병합셀/중첩표 구조 adapter와 legacy fallback chain
- 페이지 절단·누락, 표 cell count·span 겹침을 거부하는 fail-closed JSON 계약
- 실행 바이너리 절대경로·버전·SHA-256을 input hash에 고정하는 production gate
- page text `primary`와 table `structured_auxiliary` retrieval lane, 문자 수 분리 계측 및
  primary-only PII 계수
- stable source block, content hash, source locator, PII 유형별 개수
- `manifest`, `extract`, `verify` CLI와 원자적 JSON/JSONL 쓰기
- data root 밖 path traversal·symlink, 원문 hash drift, 잘못된 doc ID의 fail-closed 처리
- stdout에서 절대경로·본문·PII를 제외한 집계 전용 결과

## 검증

- 표준 라이브러리 `unittest`: 전체 70개 통과 — `rhwp` 페이지 완전성, bounded output,
  checksum mismatch 미실행, 병합·중첩표, table partial, legacy fallback, 대용량 PDF 결과와 오류 분류 회귀 포함
- `compileall`: 별도 `/tmp` pycache를 사용해 통과
- 실제 manifest 100행·source block 20,569행 JSON Schema 오류 0건
- HWP subprocess와 PDF 격리 process에 문서별 timeout 적용
- 저장소 안전 검사 322파일과 restricted artifact ignore 정책 통과

## 외부 실사

- 지정 corpus 인벤토리: metadata CSV 100행, 원문 100건(HWP 96, PDF 4), 정규화 후 파일명 100/100 대응
- private snapshot: 실제 CSV↔원문 100/100 조인, HWP 96건 `partial`, PDF 4건 `ok`, 실패 0건
- 최종 `require-extracted` 검증: 문서·블록·입력 hash·provenance 오류 0건
- 고정 `rhwp` identity snapshot: HWP 96건·PDF 4건 모두 `ok`, partial/실패 0건,
  `require-primary-hwp` strict gate 오류 0건
- HWP 전수 실사: 페이지 8,940쪽, 페이지 본문 7,076,421자, 논리 표 11,183개, 병합셀 66,929개
- 실제 source block 20,569개는 primary 9,509개와 structured auxiliary 11,060개다.
  문자는 각각 7,550,077자와 6,555,392자로 분리 계측한다.
- 동일 corpus 재실행의 block/meta 파일 200개가 byte-for-byte 동일해 source block 결정성을 확인했다.
- 팀원 데이터 리뷰 교차확인: NFC 조인·결측 건수·CSV 잘림·HWP 전수 재파싱 결과 일치
- 로컬 LibreOffice HWP 필터는 구형 HWP97용이므로 HWP5 직접 추출기에서 제외

## 남은 항목

- HWP 5건에서 논리 표↔render-tree bbox 조인율과 한컴 페이지 정합을 QA한다.
- PDF 4건의 표·bbox와 최대 문서의 약 10% parser별 문자 수 차이를 QA한다.
- baseline은 `retrieval_role=primary`만 임베딩한다. 구조화된 `table` block은 별도 auxiliary
  lane에서만 실험해 같은 ranking pool의 중복을 방지한다.

실제 source blocks가 준비되어 Batch 2 private gold 작성을 시작할 수 있다.
