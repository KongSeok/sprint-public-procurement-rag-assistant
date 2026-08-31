# Visual image recovery and understanding contract

작성일: 2026-08-30
상태: **CONTRACT_FROZEN / PUBLIC_IMPLEMENTATION_COMPLETE / PRIVATE_GATES_BLOCKED / LOCAL_FIRST**

핵심 결정: **OCR 또는 이미지 설명 레인만 추가해서는 현재 결함이 해결되지 않는다.** 먼저
이미지·도식이 어느 문서의 몇 쪽, 어느 위치에 있었는지를 증명하는 occurrence crop을 만들고,
그 crop에 OCR·layout·caption 결과를 귀속해야 한다.

## 1. Goal

HWP/PDF의 표·이미지·도식을 검색 가능한 근거로 만들되 다음 네 단계를 분리한다.

1. 원본 객체 또는 페이지 렌더 영역을 복구한다.
2. `doc_id + page + bbox + crop_sha256`로 배치 위치를 고정한다.
3. OCR/layout과 선택적 이미지 설명을 별도 증거로 생성한다.
4. 원문 위치를 인용할 수 있는 항목만 검색 lane에 넣는다.

이미지 설명의 목적은 객체의 의미를 보강하는 것이며, 누락된 provenance나 page/bbox를 추정해
채우는 것이 아니다.

## 2. Contract-time baseline (superseded by Section 15)

이 절은 구현 시작 시점의 결함 스냅샷이다. 최종 current state와 실제 v2 실행 수치는
Section 15의 closeout을 따른다.

### 계약 당시 완료된 것

- refined HWP 94/94를 실패 없이 처리했고 8,762쪽, 표 10,787개, ordered occurrence 77,607개를
  결정적으로 생성했다.
- HWP source image reference 452개 중 지원 형식 440개를 보존했고, 전역 canonical object는
  406개다.
- HWP 이미지 증거 상태는 `verified_asset_render` 58,
  `asset_only_unlinked` 382, `render_only_missing_asset` 498,
  `unsupported_source_asset` 12다.
- 실제 HWP render occurrence 556개 중 verified는 body 12/table-nested 46이고, unlinked는
  body 246/table-nested 252다. 현재 top-level ordered image link 12개는 body만 포함한다.
- HWP page/table/text와 검증된 일부 image occurrence는 기존 locator와 순서를 보존한다.
- PDF 4건 570쪽에서 1,270개 geometry record를 두 번 byte-identical하게 만들었다.
  이 중 line-table candidate 843개, image-geometry candidate 427개다.
- PDF native 본문 491,936자와 page-v1 570/570은 추출·검색 가능하다. 미완료 범위는 visual object다.

### 계약 당시 아직 안 된 것

- HWP의 382개 asset-only 항목에는 page/bbox가 없고, 498개 render-only 항목에는 source asset
  연결이 없다.
- 현 HWP link는 문서별 global ordinal을 사용하며, 미지원 형식 1개라도 존재하거나 전체 count,
  render key, aspect ratio 중 하나가 어긋나면 해당 문서 전체를 unlinked로 남긴다.
- 문서별 결과는 14건 verified, 40건 aspect mismatch, 30건 count mismatch, 3건 missing key,
  6건 unsupported 동반, 1건 image 없음이다. 현 validator도 verified/unresolved 혼합 문서를 거부한다.
- 의도적으로 늘여 그린 이미지는 source/render aspect가 달라도 embedded raw SHA가 같았고,
  source 6/render 5 문서도 5개는 exact byte/pixel match였다. count/aspect는 신원 증거가 아니다.
- WMF/GIF 12개는 원본 hash·MIME·size만 있고 검색 가능한 canonical image가 없다.
- PDF `page.images` record는 bbox 중심 후보이며 실제 XObject bytes/xref 및 vector diagram 분류가
  없다.
- PDF의 `lines` table strategy는 조직도·구성도의 사각형도 표로 과검출할 수 있다.
- 저장된 PDF PoC artifact는 현 `pdf_visual.py`보다 약 3시간 35분 먼저 생성됐다. 대표 일정표
  2개의 persisted body row first-column은 각각 29/29, 14/14가 비어 있어 현 복구 코드를 4건에
  다시 실행해야 한다.
- 현재 venv에는 optional `pdfplumber`가 없고 PDF visual corpus용 durable CLI/runner도 없다.
- OCR, reading order, table-cell OCR, diagram semantics, caption 검색 lane은 구현되지 않았다.
- visual semantic index와 기본 Streamlit runtime은 활성화하지 않았다.

### 원인 판정

OCR는 픽셀 안 글자를 읽지만 asset과 page occurrence의 관계를 복구하지 않는다. 이미지 설명도
같은 한계가 있다. 반대로 page/bbox가 있는 render-only occurrence는 원본 asset과 연결되지 않아도
결정적 page crop을 만들 수 있으므로, 이 crop 자체를 페이지 근거로 OCR/VLM 처리할 수 있다.
asset-only 항목은 OCR해도 제목·쪽·순서를 알 수 없어 문서 단위 quarantine을 벗어나지 못한다.

## 3. In Scope

- HWP RenderTree image occurrence와 도식 영역의 deterministic crop
- HWP BinData/source asset과 render occurrence의 stable resource ID exact link
- exact ID가 없는 HWP를 위한 제한적 visual-match fallback
- PDF raster XObject, inline image, vector drawing cluster, table candidate의 분리
- PDF/HWP region별 한국어 OCR, bbox, confidence, reading order, table structure
- OCR이 충분하지 않은 도식에만 적용하는 local caption/diagram lane
- visual chunk, RRF, citation, abstention 및 human-gold gate
- 대표 5유형 통과 후 HWP 94건 전수 실행

## 4. Out of Scope

- Upstage 등 외부 parser API로 private 원문을 보내는 것
- caption을 원문 text로 합치거나 검증 없이 factual evidence로 승격하는 것
- asset-only 이미지를 임의의 페이지·제목에 연결하는 것
- 이번 계약만으로 기본 runtime 또는 external semantic index를 전환하는 것
- 사용자 승인 없는 모델 다운로드, private corpus egress, 외부 검색 API 호출
- 모든 PDF 도형을 표 또는 그림으로 강제 분류하는 것

## 5. Assumptions

- 원문·crop·OCR·caption artifact는 Git 밖 private root에 둔다.
- 모델 weight와 변환기 binary는 버전·license·SHA-256을 pin한다.
- source asset exact link보다 `page render crop + verified bbox`가 페이지 검색 근거로 먼저 사용될 수
  있다.
- 동일 asset이 여러 페이지/위치에 재사용될 수 있으므로 asset과 occurrence는 1:N 관계다.
- 추정 연결의 recall보다 false link 0이 우선이다.
- PaddleOCR 계열의 한국어 성능은 공식 일반 지표가 아니라 우리 private gold로 다시 검증한다.

## 6. Existing touchpoints

- HWP asset/link: `src/midprojectrag/ingest/hwp_assets.py`
- HWP ordered evidence: `src/midprojectrag/ingest/visual_bundle.py`
- HWP rollout: `src/midprojectrag/ingest/visual_corpus.py`
- PDF candidates: `src/midprojectrag/ingest/pdf_visual.py`
- PDF stale-artifact incident: `fivecircles/test/errorlogs/backend/2026-08-30-pdf-visual-artifact-stale.md`
- visual context: `src/midprojectrag/ingest/visual_context.py`
- current contracts: `contracts/hwp-image-evidence.schema.json`,
  `contracts/pdf-visual-evidence.schema.json`, `contracts/ordered-visual-occurrence.schema.json`
- current result: `hwp-pdf-visual-parsing-flow-validation.md`
- active source: `refined-source-of-truth.md`

기존 source block, page-v1, table identity, display Markdown 및 locator hash는 변경하지 않는다.

## 7. Proposed Design

### 7.1 Evidence recovery comes before understanding

```text
source object / render region
        -> occurrence crop (doc, page, bbox, crop hash)
        -> OCR + layout evidence
        -> optional caption inference
        -> visual retrieval chunk
        -> page/bbox/asset-aware citation
```

상태는 하나의 선형 값이 아니라 다음 독립 축으로 기록한다.

| 축 | 허용 상태 |
| --- | --- |
| placement | `page_bbox_verified`, `doc_only_unlinked`, `ambiguous`, `missing` |
| source object | `exact_resource_link`, `verified_exact_visual_match`, `render_only`, `unsupported`, `missing` |
| understanding | `none`, `ocr_ready`, `layout_ready`, `caption_ready`, `failed` |
| retrieval | `eligible`, `withheld`, `quarantined` |

`retrieval=eligible`은 최소한 source document hash, page, bbox, deterministic crop hash가 있어야 한다.
source asset exact link는 권장되지만 page-render crop의 필수조건은 아니다.

### 7.2 HWP occurrence recovery

1. RenderTree/PageLayerTree의 image node와 table-nested image node에서 page, bbox, container path,
   sequence를 수집한다.
2. 같은 좌표계와 고정 scale/profile로 페이지를 렌더한 뒤 bbox crop을 생성한다.
3. vector/shape 구성도는 image node만 기다리지 않고 shape cluster 또는 page layout detector가 찾은
   region을 별도 `diagram_region` occurrence로 만든다.
4. crop은 `source_sha256 + page + bbox + render_profile_sha256`에 묶고 픽셀 SHA-256을 저장한다.
5. nearby title은 page text에서 bbox 앞의 가장 가까운 heading 후보를 bounded rule로 연결한다.

이 경로는 498개 render-only 및 WMF/GIF가 실제 페이지에 렌더된 경우 바로 OCR 대상으로 사용할 수
있다. crop은 원본 asset을 대체하지 않으며 `evidence_origin=page_render_crop`을 유지한다.

### 7.3 HWP source asset exact link

우선순위 1은 pinned rhwp core의 `sourceImageKey`/BinData identifier를 source record와 render
occurrence 양쪽에 노출하는 작은 helper/CLI 확장이다. core API에는 `getPageSourceImageKeys`,
`getPageFlowImageOps`, `getSourceImageBytes(key)`와 layer-tree `sourceImageKey`가 있지만 현 프로젝트의
`export-render-tree` 경로가 key를 내보내지 않는다.

```text
(doc_id, source_image_key)
    -> one canonical source object
    -> one or more page occurrences
```

`source_image_key`/BinData ID는 document-local provenance이며 global asset ID가 아니다. 영속 asset
identity는 source bytes SHA-256을 사용한다. helper는 page/bbox, body 또는 table/row/column/nested-cell
anchor, 가능한 paragraph/control index, match evidence를 함께 내보낸다. flow image API가 table-nested
occurrence를 모두 포함하지 않으면 full layer tree/all-image API를 사용한다.

v2 validator는 문서 단위 all-or-nothing을 제거하고 occurrence별 verified/unresolved 혼합을 허용한다.
table-nested 이미지는 top-level stream에 중복 삽입하지 않고 canonical table block의 exact cell path에
붙인다.

exact ID를 얻을 수 없는 문서만 다음 fallback을 쓴다.

1. SVG embedded raw bytes SHA가 source bytes SHA와 같은지 비교한다.
2. 재인코딩된 경우 width/height와 normalized RGBA SHA가 모두 같은지 비교한다.
3. SVG transform/clip을 반영한 page+bbox가 render occurrence와 exact reconciliation되는지 확인한다.
4. 위 exact evidence를 모두 만족하는 후보가 유일할 때만 `verified_exact_visual_match`로 승격한다.
5. 반복 asset은 canonical object cluster 단위로 1:N placement를 허용한다.
6. 동일 pixel의 여러 source ref나 동률 후보는 `ambiguous`로 남긴다.

pHash, SSIM, OCR, CLIP, 파일명, ordinal, aspect ratio, proximity는 review candidate 생성에만 쓰고
verified link 근거로 사용하지 않는다. 매칭되지 않은 occurrence는 page crop 기반 `render_region`
증거가 될 수 있지만 source asset link라고 주장하지 않는다.

### 7.4 PDF object recovery and classification

현 `pypdf + pdfplumber` lane을 기본으로 유지하되 raster/vector/table을 다음처럼 분리한다.

- raster/inline image: pypdf의 page/Form XObject image API로 actual bytes, resource path, indirect
  reference, inline 상태를 얻고 pdfplumber placement bbox와 reconciliation한다.
- repeated placement: 동일 xref/digest라도 page+bbox별 occurrence를 따로 기록한다.
- masked image: image와 soft mask를 합성한 canonical crop 및 원본 xref provenance를 함께 보존한다.
- vector diagram: `Page.get_drawings()`/drawing cluster의 bbox를 page-render crop으로 만든다.
- table: line geometry만으로 verified가 되지 않는다. cell grid, 행/열 text alignment, header 또는
  사람이 검증한 rule을 만족해야 승격한다.
- fallback: xref가 0인 inline image나 vector-only diagram은 page crop을 canonical evidence로 쓴다.
- containment: table bbox 안의 image placement는 상호배타 top-level 분류 대신
  `parent_occurrence_id`를 가진 `table_child_image`로 보존한다.

generic rectangle와 조직도 box를 table로 세지 않도록 `raster_image`, `vector_diagram`,
`table`, `decorative`, `ambiguous` 분류를 별도 필드로 둔다.

read-only inventory에서 427 bbox occurrence와 PDF image resource entry 416개, decoded digest 92개의
재사용 구조가 달랐으므로 resource count를 placement count로 해석하지 않는다.

PyMuPDF의 `get_image_info(xrefs=True)`와 `get_drawings()`는 별도 기술 spike 후보지만 AGPL/상용
이중 라이선스다. 저장소 라이선스와 배포 의무를 결정하기 전 production dependency로 채택하지
않는다.

### 7.5 OCR and layout lane

첫 local 후보는 **PP-StructureV3 + `lang=korean` + `ocr_version=PP-OCRv5`**다. 세밀한 bbox,
confidence, reading order와 table structure가 필요한 현재 목적에 일반 caption VLM보다 우선한다.

OCR output은 다음을 반드시 포함한다.

- occurrence/crop SHA-256
- polygon 또는 bbox, text, confidence, reading order
- table cell bbox와 HTML/structured cell identity가 있으면 그 값
- model name/version/weight SHA-256, config SHA-256, runtime/device
- 실패·저신뢰 상태와 sanitized warning

text layer가 충분한 PDF page 전체에 OCR를 중복 적용하지 않는다. scan page, image/diagram region,
저품질 text region만 선택해 비용과 중복을 줄인다.

### 7.6 Caption and diagram lane

caption은 OCR/layout 뒤에 선택적으로 실행한다.

- 대상: 조직도, 시스템 구성도, 흐름도, 차트처럼 OCR 문자열만으로 관계를 알기 어려운 region
- 1차 비교: PaddleOCR-VL full pipeline
- 보조 후보: Qwen3-VL 4B/8B Instruct local model
- 비대상: 로고, 장식, OCR만으로 충분한 표, 중복 occurrence

caption에는 `descriptive_evidence` 유형을 부여하고 원문 text와 합치지 않는다. 숫자, 기관명,
방향·관계 주장은 OCR bbox, 기존 HWP/PDF text, table cell 중 하나가 support reference로 연결될
때만 답변 근거가 된다. 지원되지 않은 문장은 검색 recall용 저가중치 설명으로만 남긴다.

### 7.7 Retrieval and citation

별도 chunk type을 추가한다.

- `image-ocr-v1`: OCR text와 bbox evidence
- `image-layout-v1`: reading order, table/chart structure
- `image-caption-v1`: 저가중치 descriptive inference

RRF에서 caption lane에는 per-document·per-query cap을 두며 exact metadata/page/table lane을 이기지
못하게 한다. visual hit의 citation은 `doc_id`, page, bbox, occurrence ID, crop SHA, evidence type을
반환한다. UI는 가능하면 원본 page crop을 함께 보여준다.

asset-only + no-page 항목, ambiguous object, unsupported claim은 retrieval에서 withheld한다.

## 8. Contracts

### 8.1 Proposed records

```text
VisualOccurrenceV2
  occurrence_id, doc_id, source_sha256
  page, bbox, coordinate_space, sequence_in_page, container_path
  region_kind, evidence_origin, crop_sha256, crop_media_type
  parent_occurrence_id?
  source_image_key?, source_anchor?, render_occurrence_key?, container_anchor?
  source_object_id?, source_object_status, link_method?, match_evidence[]
  placement_status, understanding_status, retrieval_status, warnings[]

OcrEvidenceV1
  evidence_id, occurrence_id, crop_sha256
  text_items[{polygon, text, confidence, reading_order}]
  table_cells?, model, weights_sha256, config_sha256, runtime

CaptionEvidenceV1
  evidence_id, occurrence_id, crop_sha256
  description, claims[{text, support_refs[], status}]
  model, weights_sha256, prompt_sha256, decode_config_sha256
```

기존 v1 schema는 변경하지 않고 v2/additive schema를 만든다. v1 artifact는 migration source로만
읽고 재해석한 상태를 원본 record에 덮어쓰지 않는다.

aggregate metadata는 parser dependency version뿐 아니라 adapter/code identity와 config SHA를
포함한다. strict reuse는 mtime이 아니라 이 identity hash와 artifact reconciliation으로 판정한다.

### 8.2 Function boundaries

```text
recover_hwp_occurrences(source, render_bundle, config) -> VisualOccurrenceV2[]
link_hwp_source_objects(occurrences, assets, config) -> VisualOccurrenceV2[]
recover_pdf_occurrences(pdf, config) -> VisualOccurrenceV2[]
run_local_ocr(occurrence, model_config) -> OcrEvidenceV1
run_local_caption(occurrence, ocr_refs, model_config) -> CaptionEvidenceV1
build_visual_chunks(occurrences, ocr, captions, config) -> Chunk[]
```

모든 함수는 path containment, symlink, byte/pixel/object/page/time limit를 fail-closed로 검사한다.

### 8.3 Promotion rules

- `page_bbox_verified + crop_sha256`가 없으면 OCR/caption이 있어도 retrieval로 승격하지 않는다.
- page-render crop은 exact source object link 없이도 page evidence가 될 수 있다.
- `doc_only_unlinked` asset은 검색에서 제외한다.
- visual match는 raw SHA 또는 normalized RGBA SHA와 bbox exact evidence 및 후보 유일성을 만족해야 한다.
- pHash/SSIM/OCR/CLIP/ordinal/aspect/proximity만으로 verified source link를 만들지 않는다.
- caption claim은 support ref가 없으면 answer evidence가 아니다.
- 기존 verified 58개와 source object 406개의 provenance를 퇴행시키지 않는다.

### 8.4 Risks and controls

| 위험 | 통제 |
| --- | --- |
| 잘못된 asset↔page 연결 | document-local key 또는 exact byte/pixel+bbox, ambiguous 보존 |
| PDF dependency license | pypdf/pdfplumber 기본, PyMuPDF는 라이선스 결정 전 spike-only |
| PDF diagram→table 과검출 | raster/vector/table 분리 및 human gold |
| OCR 오류 | confidence·polygon 보존, critical-token gold |
| VLM 환각 | support refs, 별도 저가중치 lane, factual promotion 금지 |
| private data egress | local-only default, destination-specific approval gate |
| 비결정적 생성 | model/prompt/decode pin, deterministic 설정, hash audit |
| 모델/이미지 DoS | pixel/token/time/object limit와 sanitized failure |

## 9. Acceptance Criteria

### 대표 gate

- HWP 대표 5유형과 PDF 4건에 사람이 object type, page, bbox, nearby title, OCR text, 관계를 표기한다.
- 기존 appshot의 일정표와 시스템 구성도 page를 critical case로 포함한다.
- auto-verified occurrence locator precision은 100%, annotated region recall은 90% 이상이다.
- critical case의 target region recall과 citation page/bbox 정확도는 100%다.
- 한국어 critical-token recall은 95% 이상이며 표 cell exact accuracy를 별도로 보고한다.
- caption의 unsupported 숫자·기관명·관계 claim은 0건이다.
- 같은 input/config를 두 번 실행해 non-generative artifact는 byte-identical해야 한다.
- caption은 deterministic decode에서 normalized output hash가 같거나 명시적 nondeterminism 상태를
  기록해야 한다.

### 전수 gate

- 대표 gate 통과 뒤에만 HWP 94건을 실행한다.
- 기존 HWP 94/94, 8,762 page, 10,787 table 및 verified link 58개가 퇴행하지 않는다.
- v2는 source/occurrence/ocr/caption/retrieval 수와 모든 withheld 이유를 reconciliation한다.
- 검색 가능한 visual chunk는 모두 page+bbox/crop citation을 가진다.
- visual 질문 gold의 top-10 evidence hit rate는 90% 이상이며 text-only gold의 기존 결과를 훼손하지
  않는다.
- full suite, schema audit, compile, repository safety, private-path containment를 통과한다.
- 외부 API 호출과 private egress는 0이다.

초기 gold가 만들어지면 CER, cell accuracy, runtime/VRAM의 관측값을 보고 위 threshold를 더 엄격하게
동결할 수는 있지만 완화는 별도 review가 필요하다.

## 10. Implementation Batches

1. **Gold and inventory**: HWP 5유형 + PDF 4건 annotation, 현재 950/1,270 record 상태 동결
2. **HWP exact key**: rhwp helper, occurrence별 혼합 상태, exact table/cell anchor
3. **Exact fallback and crop**: raw/RGBA+bbox match, render/image/shape crop, nearby title, WMF/GIF crop
4. **PDF recovery**: XObject bytes/xref, inline image, masks, vector cluster, table classifier 분리
5. **OCR/layout**: PP-StructureV3 + Korean PP-OCRv5, schema/cache/quality gate
6. **Caption/retrieval**: 필요한 diagram만 VLM, claim support, chunks/RRF/citation/UI preview
7. **Rollout**: 대표 gate 재검증 후 HWP 94건, 검색 gold, runtime 전환 여부 결정

Batch 2에서 document-local key와 위치 계약을 먼저 고정하고 Batch 3에서 render-region crop을 만든다.
render-only 이미지는 Batch 3부터 페이지 검색 근거를 가질 수 있다. caption은 그 뒤에 붙인다.

## 11. Test Plan

- synthetic: 반복 asset, missing key, count mismatch, unsupported media, nested table image
- HWP private opt-in: body image, table image, vector diagram, WMF/GIF, repeated/mismatch 5유형
- PDF private opt-in: raster XObject, inline image, mask, vector diagram, ruled/borderless/schedule table
- PDF regeneration: durable CLI, stale artifact refusal, current-code v2 materialization, aggregate reconciliation
- matching: exact resource ID, raw SHA, normalized RGBA+bbox, ambiguous tie, 1:N repeated placement
- HWP identity: reused key 1→81 placements, stretched image, source/render 6→5, WMF+PNG mixed document
- HWP table: exact nested row/column/path, top-level non-duplication, missing paragraph/control index
- OCR: Korean/English/numeric, rotation, low resolution, bbox, confidence, reading order, table cells
- caption: OCR-supported claim, unsupported claim, empty OCR, duplicate image, deterministic decode
- retrieval: OCR-only query, diagram relation query, nearby title query, page/bbox citation, caption cap
- regression: existing source block/page/table/verified image hashes and v1 loader behavior
- safety: model checksum, offline mode, path/symlink escape, oversized image/PDF, timeout, sanitized logs

## 12. Open Questions

- `getPageFlowImageOps`가 table-nested, header/footer/master-page reuse를 모두 포함하는가?
- source key가 없는 합성/vector occurrence를 full layer tree에서 안정적으로 구분할 수 있는가?
- image node가 없는 HWP shape diagram을 RenderTree cluster와 PP-Structure layout 중 어느 쪽이 더
  정확히 찾는가?
- 대표 gold에서 PP-StructureV3와 PaddleOCR-VL의 한국어 표/도식 성능과 L4 runtime은 얼마인가?
- caption 후보는 PaddleOCR-VL만으로 충분한가, Qwen3-VL 보조가 유의미한가?
- UI에서 bbox crop을 직접 보여줄 때 비공개 원문 접근 통제를 어떻게 유지할 것인가?

## 13. Handoff Notes

다음 구현자는 모델부터 붙이지 않는다. 대표 HWP 5유형과 PDF 4건의 occurrence gold를 만든 뒤
rhwp source-key helper·table-cell anchor와 PDF durable runner를 먼저 구현한다. 그 다음 고정 profile
page crop과 PP-StructureV3/PP-OCRv5를 연결해 OCR가 정확한 `doc_id/page/bbox`로 인용되는지
확인한다. 복잡한 도식만 VLM 후보를 비교한다.

외부 API는 필요하지 않다. 로컬 Mac은 작은 표본·계약 검증에, GCP L4는 pinned model 전수 성능
검증에 사용한다. model weight 다운로드와 GCP 실행은 각각 기존 승인·비용 gate를 따른다.

## 14. Implementation Freeze (2026-08-30)

### 14.1 Additive public contracts

기존 v1 schema는 수정하지 않고 다음 파일을 추가한다.

- `contracts/visual-occurrence-v2.schema.json`
- `contracts/ocr-evidence-v1.schema.json`
- `contracts/caption-evidence-v1.schema.json`
- `contracts/visual-chunk-v1.schema.json`
- `contracts/visual-corpus-v2-metadata.schema.json`

ID는 정규화된 canonical JSON의 SHA-256 앞 24 hex를 사용한다. bbox 숫자는 finite number만 받고
`x,y,w,h` 순서와 6자리 소수 정규화를 ID 입력에 사용한다. `source_object_id`는 content SHA에만
묶어 전역 중복을 허용하고, `occurrence_id`는 source document hash, page, bbox, region kind,
container anchor와 sequence에 묶는다. crop hash나 OCR/caption 값은 occurrence ID에 넣지 않는다.

`VisualOccurrenceV2`의 enum은 다음으로 동결한다.

| Field | Values |
| --- | --- |
| `placement_status` | `page_bbox_verified`, `doc_only_unlinked`, `ambiguous`, `missing` |
| `source_object_status` | `exact_resource_link`, `verified_exact_visual_match`, `render_only`, `unsupported`, `missing`, `ambiguous` |
| `understanding_status` | `none`, `ocr_ready`, `layout_ready`, `caption_ready`, `failed` |
| `retrieval_status` | `eligible`, `withheld`, `quarantined` |
| `region_kind` | `raster_image`, `inline_image`, `vector_diagram`, `table`, `table_child_image`, `decorative`, `ambiguous` |
| `evidence_origin` | `source_object`, `page_render_crop`, `resource_and_page_crop` |
| `link_method` | `document_resource_key`, `raw_sha256_bbox_exact`, `rgba_sha256_bbox_exact`, `render_region_only`, `none` |

`retrieval_status=eligible`은 `page_bbox_verified`, finite positive bbox, `crop_sha256`와 private
`crop_relpath`, Git 밖 root containment를 모두 요구한다. exact object link가 없어도
`render_region_only` page crop은 eligible일 수 있다. asset-only/doc-only, ambiguous, unsupported
source claim은 withheld 또는 quarantined만 허용한다.

### 14.2 Helper and runner boundaries

- HWP helper는 JSONL로 page, bbox, sequence, `source_image_key`, container anchor와 raw source
  SHA를 내보낸다. official rhwp API가 없는 구버전에서는 helper 입력을 생략하고 exact SVG/raw 또는
  normalized RGBA+bbox fallback만 사용한다.
- helper 실행 파일과 model command는 절대경로, executable, non-symlink, SHA-256 allowlist를
  통과해야 한다. stdout/stderr/time/record/byte limit를 둔다.
- page crop 함수는 caller가 만든 PNG page render를 받아 bbox를 coordinate-space scale로 변환한 뒤
  PNG를 deterministic option으로 저장한다. 페이지 bitmap hash, render profile hash와 crop hash를
  metadata에 모두 기록한다.
- PDF runner는 pypdf resource identity/bytes와 pdfplumber placement를 분리해 수집하고 unique
  reconciliation만 exact link로 승격한다. 동일 resource의 반복 placement는 1:N occurrence다.
- aggregate strict reuse는 source manifest, adapter code, config, dependency version, output hashes를
  함께 비교한다. mtime은 경고에만 사용한다.

### 14.3 Local understanding and retrieval boundary

OCR/VLM adapter는 Python 라이브러리를 직접 import하는 경로와 checksum-pinned local command
경로를 모두 허용하되 network는 사용하지 않는다. 공개 CI는 deterministic fixture adapter로 schema,
cache, support-ref guard와 error handling을 검증한다. 실제 PP-StructureV3/PP-OCRv5/PaddleOCR-VL
weight가 없으면 production adapter 실행은 `model_artifact_unavailable`로 fail closed한다.

visual chunk는 기존 page/table chunk schema에 섞지 않고 별도 schema를 쓴다. caption chunk는
`retrieval_weight <= 0.35`, query당 2개와 문서당 1개 cap을 기본으로 하며 support ref 없는 claim을
answer text에 넣지 않는다. 모든 citation은 occurrence ID, page, bbox, crop SHA와 evidence ID를
반환한다.

### 14.4 Public vs private completion

공개 저장소 완료는 contract/schema, bounded adapters/runners, deterministic fixtures, CLI smoke,
offline/safety/regression gate로 판정한다. private human gold, HWP 5→94 실제 재생성, PDF 4건 실제
재생성, model quality/VRAM 측정은 원문·weight가 있는 opt-in 실행이며 Git에 artifact를 남기지 않는다.
코드가 준비돼도 private input/model이 없으면 해당 execution gate만 `BLOCKED`로 기록하고 public
implementation을 허위로 실패 처리하거나 simulated private pass로 주장하지 않는다.

## 15. Implementation closeout

> 2026-08-31 정정: 아래 대표 HWP crop 완료 주장은 후속 픽셀 감사에서 무효화됐다.
> 원본 산출물은 incident 증거로 격리하고, §16의 nonblank gate를 통과한 재생성 결과만
> 검색 가능 evidence로 인정한다.

공개 계약과 실행 경로는 구현 완료했다. HWP/PDF occurrence 복구, deterministic crop, 폐쇄형
OCR·caption evidence, checksum-pinned OS-network-sandbox adapter, bounded visual fusion, page/bbox
citation과 visual gold 평가를 기존 text/table identity를 바꾸지 않는 additive v2로 제공한다.

실제 private 실행은 내용·파일명 없이 다음 집계만 남긴다.

- HWP 대표 5문서 초기 실행: occurrence 27개, exact source object 27개였으나, 16개 placement에서
  공유된 14개 crop PNG가 전부 순백 픽셀이었다. 당시 metadata/hash/dimension 재사용 검증은
  이 semantic blank를 검출하지 못했으므로 검색 가능 16개 주장은 철회한다. page를 증명할 수 없는
  11개 withheld 상태와 source object provenance 자체는 영향을 받지 않는다.
- PDF 4문서 570쪽: resource 416개, occurrence 1,110개, eligible 1,103개,
  ambiguous/withheld 7개. 재실행 artifact identity가 동일했다.
- 실제 OCR/caption inference: 0개. checksum-pinned private model weight가 없으므로 공개 runner가
  fail closed하며, fixture 경로만 자동 검증했다.
- HWP 94건 v2 rollout: 미실행. reviewed HWP 5건 + PDF 4건 gold 없이 corpus mode가 helper 실행
  전에 `hwp_visual_runner_gold_gate_required`로 중단되는 것을 확인했다.

따라서 남은 작업은 코드 TODO가 아니라 외부 입력 gate다. 사람이 occurrence/title/OCR/관계 gold를
동결하고 허용된 model weight를 pin한 뒤 실제 품질 기준을 통과해야만 HWP 94건과 기본 runtime
활성화를 별도 실행한다.

## 16. HWP blank-crop correctness correction (2026-08-31)

### 16.1 Goal and current problem

`@rhwp/core.renderPageSvg()`가 만든 SVG에는 HWP 그림이 `data:image/...;base64` `<image>`로
포함되지만, 현재 `@napi-rs/canvas.loadImage(Buffer(svg))` 경로는 SVG의 text/vector만 그리고
내장 raster image를 누락한다. 그 결과 page render는 생성되지만 image bbox crop은 순백이 되며,
기존 검증은 PNG 구조·크기·hash만 검사해 잘못된 evidence를 `eligible`로 승격했다.

### 16.2 Scope and assumptions

- 대상은 pinned rhwp helper가 생성하는 self-contained SVG data URI image다.
- PNG/JPEG/BMP/WebP만 로컬 canvas overlay 대상으로 허용한다.
- TIFF/GIF/SVG/WMF처럼 현재 renderer가 디코딩하지 못하는 source는 원본 provenance를 보존하되
  crop/검색 승격 없이 `unsupported` + `withheld` 또는 `quarantined`로 남긴다.
- 외부 parser, OCR, VLM, 검색 API는 호출하지 않는다.
- 임의의 SVG `transform`, mask, CSS cascade와 복합 paint-order 일반화는 이번 수리 범위 밖이다.
  helper가 실제로 내보내는 axis-aligned root/nested viewport, 단일 rect clip,
  `none`/`meet`/`slice` preserve-aspect-ratio, RGB linear component-transfer와 scalar opacity만
  허용한다. `<style>` element, `class`, ancestor `display`/`visibility`/inline `style`, 그리고
  `<defs>`처럼 paint tree 밖의 container에 들어간 `<image>`는 조용히 무시하지 않고 fail closed한다.
  SVG 표준에 따라 생략된 `x/y`는 0으로 정규화하고, 계약 밖 effect나 geometry는 추정하지 않는다.

### 16.3 Function and evidence contracts

1. helper는 `<image>` data URI를 bounded base64로 해석하고 media magic과 선언 MIME을 대조한다.
2. base SVG를 먼저 rasterize한 뒤, 지원 raster를 page coordinate→pixel scale로 같은 bbox에
   deterministic overlay한다. 중첩 `<svg>`는 `x/y/width/height`, `viewBox`, 기본
   `xMidYMid meet` 또는 명시적 `none/meet/slice`를 axis-aligned transform으로 합성하고 viewport와
   상위 viewport clip의 교집합만 bitmap source crop으로 그린다.
3. `<clipPath><rect>` ancestor는 overlay crop에 교차하고, 관측된 RGB linear component-transfer와
   scalar opacity는 bounded pixel buffer에 순서대로 적용한다. 다른 filter/mask는 실패시킨다.
4. `<style>` element와 `class` attribute를 SVG 전체에서 거부한다. `<image>` ancestor의
   `display`, `visibility`, inline `style`, mask/overflow 또는 `<svg>/<g>` 이외 container 구조도
   `rhwp_visual_helper_page_svg_effect_unsupported` 또는
   `rhwp_visual_helper_page_svg_image_structure_unsupported`로 fail closed한다.
5. renderer identity는 `rhwp_core_renderPageSvg+napi_canvas+data_uri_overlay`로 바꿔 이전 artifact의
   strict reuse를 자동 거부한다.
6. `crop_page_region()`은 알파를 흰 배경에 합성한 뒤 모든 픽셀이 순백이면
   `visual_crop_blank`로 fail closed한다. blank crop은 hash와 PNG 구조가 유효해도 evidence가 아니다.
7. `source_object_status=unsupported` occurrence는 crop을 만들지 않으며 retrieval eligible로
   승격하지 않는다.

### 16.4 Acceptance criteria

- synthetic helper 회귀에서 base SVG, direct embedded raster, x/y 생략 raster, nonzero viewBox의
  nested raster, rect-clipped raster와 linear-filter/opacity raster가 예상 draw path로 그려진다.
  nested/clip raster의 source fraction과 destination 좌표를 수치로 검증한다.
- `<style>`, `class`, ancestor `display`/`visibility`/inline `style`, `<defs>` 내부 image fixture는
  각각 허용 경로로 떨어지지 않고 명시적 helper 오류로 종료한다.
- 순백 crop은 `visual_crop_blank`로 거부되고, nonblank crop은 기존 deterministic hash 계약을 유지한다.
- 대표 HWP 5건을 새 renderer identity로 재생성했을 때 생성된 모든 eligible crop이 nonblank다.
- 대표 문서의 PNG/JPEG placement는 실제 그림 픽셀을 포함하고, 디코딩 불가 TIFF는 명시적으로
  격리된다.
- 기존 흰 crop bundle은 삭제하지 않고 invalid incident artifact로 보존하며, canonical 대표 경로는
  검증을 통과한 새 bundle로만 교체한다.
- private 원문·crop·파일명은 Git에 커밋하지 않고 집계와 비식별 상태만 기록한다.

### 16.5 Implementation batches and test plan

1. SVG data-image parser/overlay와 renderer identity를 구현한다.
2. blank crop gate와 unsupported-source promotion guard를 구현한다.
3. unit tests, 대표 5건 재생성, 픽셀 전수 감사, sample visual review를 실행한다.
4. flow report·incident·learn/update/TODO를 정정하고 scoped commit/push한다.

검증은 Node syntax, 관련 Python/Node helper unit tests, 대표 bundle schema/reuse, Pillow nonwhite
전수검사, 실제 crop 시각 확인, Mermaid PNG/HTML render, repository safety 순서로 수행한다.

### 16.6 Closeout evidence

- current helper SHA-256은
  `0b7ab8edd3b3cb6018704b40e1c7b662041a79c857dc99eba66432280cfc0a9b`, canonical
  representative artifact set은 `visualv2_1a25cd3f5f6c34dfe2e8ff9c`다.
- 새 renderer profile로 대표 HWP 5/5를 재생성했다. occurrence 27개 중 15개가 nonblank
  page/bbox crop으로 eligible, TIFF 1개가 quarantined, page를 증명하지 못한 11개가 withheld다.
- unique crop PNG 15/15와 page render 14/14가 모두 nonblank다. 큰 문서형 raster 2개와
  nested-viewBox 소형 로고 1개도 직접 열어 합성 위치와 내용이 보이는지 확인했다.
- canonical output에 대해 occurrence reference/hash reconciliation, expected artifact-set identity와
  strict reuse를 다시 통과했다. 외부 API 호출은 0회이고 metadata의 `private_egress`는 `false`다.
- `<style>`/`class`/`display`/`visibility`/`<defs>`-image fail-closed 회귀를 포함한 helper focused
  test는 11/11 통과했다. 대표 5문서 530페이지 SVG 전수 스캔에서 이 패턴은 0건이었다.
- repository-wide discovery 505/505, focused schema 2/2, compileall, Node syntax,
  `git diff --check`, repository safety 562 files를 모두 통과해 current-tree green을 확정했다.
- 대표본의 linear-filter/opacity crop을 Chrome 원본 SVG render와 같은 bbox에서 비교한 결과 channel
  mean absolute error는 `0.754/255`, RMSE는 `1.471/255`였다.
- 과거 순백 14-crop bundle은 incident archive로 보존했고 canonical representative 경로에는
  수정 bundle만 둔다. private artifact는 Git 범위 밖이다.

이 closeout은 crop 복구의 기술 gate만 통과시킨다. 실제 OCR/도식 관계 품질과 HWP 94건 전수는
사람이 검토한 5-HWP + 4-PDF gold와 pinned model-quality gate가 준비될 때까지 계속 차단한다.

## Official References

- rhwp Export API: https://github.com/edwardkim/rhwp/wiki/Export-API-%EC%82%AC%EC%9A%A9-%EA%B0%80%EC%9D%B4%EB%93%9C
- PyMuPDF page images/vector/OCR: https://pymupdf.readthedocs.io/en/latest/page.html
- PyMuPDF image/xref extraction: https://pymupdf.readthedocs.io/en/latest/recipes-images.html
- PyMuPDF license: https://github.com/pymupdf/PyMuPDF/blob/main/docs/about.rst
- pypdf image extraction: https://pypdf.readthedocs.io/en/stable/user/extract-images.html
- pypdf PageObject images: https://pypdf.readthedocs.io/en/latest/modules/PageObject.html
- pdfplumber tables/debugging: https://github.com/jsvine/pdfplumber/blob/stable/README.md
- PP-StructureV3: https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/PP-StructureV3.html
- PaddleOCR Korean OCR: https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/OCR.html
- PaddleOCR-VL: https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/PaddleOCR-VL.html
- Qwen3-VL: https://github.com/QwenLM/Qwen3-VL
