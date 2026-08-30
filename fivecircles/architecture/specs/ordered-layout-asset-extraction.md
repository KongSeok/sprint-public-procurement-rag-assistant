# Ordered Layout and Asset Extraction Contract

상태: **IMPLEMENTED_REPRESENTATIVE_VERIFIED_CORPUS_ROLLOUT_PENDING**
결정일: 2026-08-28
범위: refined 98문서 중 HWP 94건의 로컬 visual evidence overlay v1

## 1. 목적과 사용자 문제

현재 HWP 본문은 페이지 텍스트가 먼저 나오고 구조화 표가 문서 뒤에 별도 추가되므로,
`제목 → 표 → 그림`이라는 원래 읽기 순서가 검색 근거에서 사라진다. 표의 병합 셀과 텍스트는
보존되지만 일정표의 색칠 칸 같은 시각 증거는 버려지고, 그림 원본은 추출 산출물에 없다.

이 계약은 기존 canonical page/table block을 변경하지 않고, 그 위에 페이지 순서·bbox·셀 시각
증거·그림 자산을 결합한 private overlay를 추가한다. 기존 9,331개 page chunk/vector와 stable
source block ID는 그대로 유지한다.

## 2. 결정과 경계

- HWP 텍스트·표 구조의 권위는 checksum-verified `rhwp v0.8.4`의 `export-text`와
  `export-tables`에 계속 둔다.
- 페이지 순서와 bbox는 같은 binary의 `dump-pages`와 `export-render-tree`로만 확정한다.
- 그림 bytes는 `export-doclang --assets-dir`에서 얻되, DocLang은 본문·표 의미의 권위로 쓰지 않는다.
- 기존 `table-layout-v1`과 99.50% top-level table join을 보존한다. 독립 증거가 없는 page/bbox,
  nested table, asset 연결은 null/unresolved로 남기며 추정하지 않는다.
- raw image asset은 근거일 뿐 이미지 내용을 이해한 결과가 아니다. OCR·caption·diagram summary는
  별도 local-only derived lane과 모델/config hash가 생긴 뒤에만 검색 본문으로 사용한다.
- 외부 API, cloud parser, HWP 전건 PDF 변환, 기존 source block 순서/ID 변경은 이 범위에서 금지한다.

## 3. 입력과 산출물

입력은 exact source SHA가 기록된 HWP, canonical source block JSONL, pinned rhwp binary와 그 SHA다.

private 출력은 다음과 같다.

- `visual-layout-v1.jsonl`: 페이지별 monotonic `sequence_in_page`를 가진 text/table/image occurrence
- `visual-assets-v1/<sha256>.<ext>`: content-addressed 그림 bytes
- `visual-layout-v1.metadata.json`: source/block/rhwp/config/artifact hash와 aggregate count

각 occurrence는 다음을 기록한다.

- `schema_version`, `doc_id`, stable `occurrence_id`
- one-based `page`, zero-based `sequence_in_page`, `node_type`
- `bbox`와 `coordinate_space=rhwp_css_px_96dpi`
- same-page에서 바로 앞선 top-level text context와 그 locator/method
- table이면 기존 `block_id`, `structure_sha256`, render key, rows/cols
- table cell이면 row/col/bbox와 direct `Rect` fill evidence
- image이면 `asset_id`, private-root relative path, MIME/magic, bytes, SHA-256, width/height
- `status`, sanitized `warnings`, extraction/link method

`occurrence_id`와 `asset_id`는 source identity와 구조/bytes hash에서 결정적으로 만든다. 실제 파일명,
원문 text, asset path와 render tree는 Git 또는 stdout에 출력하지 않는다.

## 4. 순서·문맥·일정표 규칙

- Body의 top-level visual traversal만 페이지 읽기 순서로 사용한다. Table 내부 TextLine은 별도
  top-level text로 중복시키지 않는다.
- 인접 문맥은 같은 페이지에서 먼저 나온 가장 가까운 non-empty top-level TextLine만 연결하며,
  이를 문서의 의미상 부모 제목이라고 과장하지 않는다.
- 표는 section/paragraph/control과 rows/cols가 canonical structure와 맞을 때만 block에 연결한다.
- direct `Rect`는 색상 이름이 아니라 `fill_evidence`로만 기록한다. renderer가 color를 제공하지
  않으므로 파란색이라고 단정하지 않는다.
- 일정 문장은 canonical header가 정확히 `M`, `M+n` 패턴이고 fill cell이 그 header span에
  일의적으로 포함될 때만 만든다. header shading, 전체 행 group shading, 모호한 병합은 일정으로
  변환하지 않는다.
- 검색용 context는 `인접 문맥 + 검증된 일정 문장`만 materialize한다. canonical cell text/span은
  기존 table lane에서 계속 제공한다.

## 5. 그림 자산 연결과 보안

- XML bytes에 DOCTYPE/ENTITY가 있으면 거부한다.
- asset URI는 상대 경로만 허용하고 resolve 뒤 지정 assets root 내부의 regular non-symlink file인지
  검증한다. path escape, duplicate URI, magic/MIME mismatch를 거부한다.
- per-file/total byte, asset count, XML byte, subprocess timeout/stdout 상한을 적용한다.
- DocLang picture와 RenderTree Image는 global occurrence order, 전체 count, intrinsic/display aspect
  ratio가 모두 맞을 때만 verified로 연결한다. 하나라도 다르면 asset/page/bbox를 추정하지 않는다.
- public test는 synthetic bytes만 사용한다. private QA는 문서 text·filename·image를 로그에 남기지
  않고 ID/count/hash 여부만 기록한다.

## 6. 실패와 하위호환 계약

- visual overlay 실패는 기존 canonical extraction을 망가뜨리지 않는다.
- malformed render node, 구조 불일치, asset 누락/중복/폭증, timeout은 sanitized error code와
  unresolved record로 남긴다.
- overlay가 없는 기존 page/table chunk 결과는 byte-identical해야 한다.
- overlay를 검색에 사용하는 새 artifact는 별도 config hash와 overlay SHA를 요구한다. 활성 runtime
  config는 98문서 manifest/page count/block/asset reference가 모두 reconcile되기 전 전환하지 않는다.

## 7. 구현 배치와 완료 조건

### V1-A — 계약과 흐름 증거

- 본 계약, D-018, TODO, target/current Mermaid·PNG·HTML을 만든다.

### V1-B — HWP overlay와 asset materializer

- ordered RenderTree traversal, canonical table join, cell fill evidence, strict schedule facts를 구현한다.
- bounded DocLang asset extraction, content-address 저장, verified image occurrence link를 구현한다.
- source block v1과 기존 `table-layout-v1`은 수정하지 않는다.

### V1-C — 검증과 인계

- 합성 unit/security/determinism 테스트를 통과한다.
- opt-in private gate에서 알려진 69페이지 HWP의 p.7 `text → 26x21 table`과 p.8
  `text → one image`, PNG magic/dimension/hash, bbox, 일정 fill evidence를 aggregate assertion으로
  확인한다.
- 기존 page/table block hash와 page-v1 hash가 변하지 않았음을 확인한다.
- 전체 회귀, compile, diff check, repository safety를 통과하고 work log/TODO를 갱신한다.

## 8. 명시적 후속 릴레이

PDF 4건은 기존 pypdf page lane을 유지한다. 별도 bounded local parser PoC에서 table/image/bbox와
determinism을 전건 QA한 뒤에만 PDF visual lane을 채택한다. Docling 같은 heavy/model-backed 후보는
버전·모델·offline cache를 pin하고 implicit download가 없음을 증명하기 전 의존성에 넣지 않는다.
그림 OCR/diagram understanding과 visual index/RRF/citation 활성화도 이 HWP evidence unit이 닫힌 뒤
각각 독립 계약·gold gate로 릴레이한다.
