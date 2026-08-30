# Local Visual Retrieval and PDF Fidelity Relay Contract

상태: **IMPLEMENTED_REPRESENTATIVE_AND_PDF_GEOMETRY_REPAIR_COMPLETE_RUNTIME_INACTIVE**
결정일: 2026-08-28
선행 계약: `ordered-layout-asset-extraction.md`

## 1. 목적

첫 HWP visual evidence 단위가 만든 인접 제목·일정 fill 근거를 실제 table 검색 입력으로 소비할
수 있는 결정적 변환기를 추가한다. 동시에 refined PDF 4건을 외부 API 없이 전수 점검해
`pdfplumber`가 표·그림·bbox 근거에 어느 정도 적합한지 채택 gate를 만든다.

## 2. HWP 검색 컨텍스트 릴레이

- 기존 `table-md-rowgroup-v1` 청크는 불변으로 둔다.
- verified table visual overlay와 v1 table chunk를 `block_id`로 exact join한 뒤 새
  `table-md-visual-context-v2` 청크를 만든다.
- 같은 page/range의 가장 가까운 prior top-level text를 `[인접 문맥]`으로, 해당 row range에
  속하는 strict schedule fact만 `[시각 일정]`으로 붙인다.
- overlay artifact SHA, 변환 정책, 길이 상한을 config hash에 포함한다. 누락·중복·doc/structure
  불일치와 길이 초과는 fail-closed 한다.
- 기존 display Markdown·source locator·page/bbox 근거는 바꾸지 않는다. 새 chunk ID/content hash를
  발급하며 기존 v1 vector를 v2라고 재사용하지 않는다.
- v2는 기존 exact index/embedding validator가 소비할 수 있어야 하지만, 이 계약에서는 외부
  embedding 호출·table index 생성·Streamlit 기본 config 전환을 하지 않는다.

## 3. PDF local visual evidence PoC

- pinned optional `pdfplumber >=0.11,<0.12`를 lazy import하고 refined PDF 4건을 local-only로 읽는다.
- same-page prior text, line-derived table cell matrix, table/image bbox, table 내부 direct rect fill evidence를
  deterministic private record로 만든다.
- 표 내부 native word bbox를 별도 보존하고, line table matrix가 비운 셀은 exact cell/row-band geometry로만
  복구한다. `M`부터 연속된 `M+n` 헤더가 확인된 표에 한해 행 라벨·fill·milestone을 결합한다.
- direct fill은 최소 변 1.5pt, 면적 8pt² 이상만 남기고 near-white 배경을 제거한다. 실질적인 검정
  Gantt bar는 보존하고 RGB·Gray·CMYK white 판정을 구분한다.
  persisted schema-v1에는 raw color와 복구 matrix만 기록하고, 일정 의미·confidence·provenance는 source SHA
  재검증 뒤 explicit in-memory analysis sink에만 공개한다.
- source는 bounded anonymous snapshot으로 고정하고 크기·SHA·inode/device·mtime/ctime을 전후 검증한다.
  geometry join은 page별 비교 예산을 넘으면 fail-closed 한다.
- page 폭·높이의 85% 이상을 덮는 최대 2x2 후보도 matrix/native text가 비어 있을 때만 obvious frame으로
  억제한다. raw image bytes, OCR, caption, diagram summary는 이 단계에서 만들지 않는다.
- page/object/text/table cell 수, 문자열 길이와 실행 전후 source SHA를 제한·검증한다.
- 원문 filename/text는 stdout·Git·공개 보고서에 남기지 않고 익명 doc index와 aggregate만 기록한다.
- Poppler로 대표 페이지를 렌더링해 table cell matrix와 육안 구조를 대조한다. text extraction만으로
  layout fidelity를 합격시키지 않는다.

## 4. 완료 조건

- HWP page별 `text → table → image` ordered occurrence artifact와 strict schema가 있다.
- 대표 일정표의 v2 검색 text에 exact prior context와 동결된 fill 구간 strict fact가 들어가며,
  해당 row를 포함하지 않는 chunk에는 들어가지 않는다.
- PDF 4건 570쪽의 line table/image candidate aggregate를 재현 가능하게 산출하고, 대표 ruled table의
  추출 cell matrix를 렌더 이미지와 대조한다.
- 표가 선이 없거나 이미지/도형 중심인 PDF는 지원됨으로 과장하지 않고 explicit limitation으로 남긴다.
- 대표 두 일정표의 모든 body row label과 fill/milestone period가 렌더 페이지와 일치해야 한다.
- 전체 회귀, compile, diff check, repository safety와 schema 검증을 통과한다.

## 5. 금지와 다음 gate

- 외부 parser API, HWP/PDF 원문 egress, 모델 다운로드, OCR/VLM, 자동 parser fallback 채택을 금지한다.
- 94 HWP/4 PDF 전건 visual artifact rollout, table v2 embedding/index, runtime RRF/citation 전환은
  corpus reconciliation·비용 승인·사람 fidelity review 뒤 별도 배치로 수행한다.

## 6. 구현 결과 (2026-08-28)

- 대표 69쪽 HWP에서 표 104개(verified 103), 그림 6개(verified 6), ordered occurrence 550개를
  결정적으로 materialize했다. 대표 일정표 제목·fill 구간과 다음 쪽 image asset/bbox가
  exact join됐고 기존 source block/page-v1 hash는 불변이다.
- `table-md-visual-context-v2` 대표 청크 278개를 생성했으며 171개에 prior context, 7개에 row-scoped
  schedule context가 붙었다. display Markdown·source locator는 그대로이고 외부 embedding은 호출하지 않았다.
- PDF 4건 570쪽을 두 번 실행해 byte-identical 1,270 candidate record(선 기반 table 843,
  image geometry 427)를 만들었다. 내용이 있는 반복 full-page 2x2 frame 17건은 오삭제하지 않고 candidate로
  유지했다. 대표 30x11 일정표의 body row 29/29와 대표 15x15 일정표의 body row 14/14를 native word bbox로
  복구했다. 마지막 보고 행의 milestone은 두 표 모두 렌더 페이지와 일치한다.
- filtered fill과 milestone을 결합한 두 일정표 분석은 confidence 0.90이다. 다만 schema-v1 persisted
  record는 계속 candidate이며, verified PDF overlay/chunk 계약 전에는 검색 index와 runtime에 투입하지 않는다.
- native word와 matrix text는 page/document 공통 예산을 소비하고, document별 record/analysis 상한과 page별
  geometry 비교 상한을 둔다. line-table 설정은 immutable canonical hash로 record identity와 provenance에
  묶었으며, analysis sink는 source 재검증 뒤 exact built-in list에만 원자적으로 게시한다.
