# BidFit Evidence-Harness v1-rc0

## 1. Goal

현재 checkout의 page/table/visual·Mini131 기반선을 보존하면서, 사용자 질문과 대화 이력에서 출발해 무결성 검사를 거친 Evidence 기반 검색·검증·생성·평가 경로를 production modules로 조립한다.

## 2. Background / Current Problem

시작 시점(`feature/visual-retrieval`, `7ad229f`)에는 다음이 확인됐다.

### A. 유지할 구현

- refined98 source와 9,331개 `page-v1` chunk, 기존 KURE page index/config identity
- page/table/visual ingestion과 exact index, 기존 answer generation·provider adapters
- deterministic catalog/analytics 기반 기능과 Mini131·supplemental 평가 도구
- private corpus·gold·model artifact의 Git 제외 정책

### B. 인터페이스 또는 별도 기준선은 있으나 목표와 다른 구현

- 기존 retrieval은 page 또는 기존 index 중심이며 child evidence와 provenance parent가 분리되지 않음
- 기존 fusion은 EvidenceStore의 동일 child 단위에 고정된 독립 KURE/Kiwi lane 계약이 아님
- 기존 corpus analytics는 독립 baseline 성격이며 통합 QueryPlan/structured provenance를 반환하지 않음
- visual occurrence/crop/OCR 계약은 있으나 full VLM 의미 이해는 활성화되지 않음

### C. 현재 checkout에 없는 구현

- immutable `EvidenceStore`
- runtime/evaluator DTO hard boundary
- child KURE + Kiwi BM25 independent RRF profile
- typed E1 QueryPlan, Belief/Progress, compare slots, citation-state follow-up
- completeness receipt 기반 exhaustive list
- structured claim→evidence citation source of truth
- identity/Qwen reranker 공통 adapter와 계층별 harness evaluator

별도 ref `feat/evidence-harness-v1`의 prototype은 read-only 감사 자료로만 사용한다. 다른 브랜치를 merge하거나 checkout하지 않는다.

## 3. In Scope

- gold/qrels/expected answer가 runtime scope/plan에 유입되지 않는 integrity gate
- 조건 없음, zero-match, non-empty filter를 구분하는 fail-closed scope
- immutable evidence/provenance graph와 compatibility child builder
- KURE child dense artifact loader/build contract 및 독립 Kiwi BM25 artifact
- 동일 child granularity의 dense+lexical union과 deterministic RRF k=60
- legacy page control과 `hb_child_rrf_v1` profile
- deterministic E1 planner, compare slot coverage, cited-state follow-up, Belief/Progress/action trace
- deterministic analytics 및 document-level exhaustive list receipt
- table correction provenance validation과 conditional visual bridge
- identity reranker 및 optional Qwen3 reranker adapter
- structured claims/citations, 저장 답변 재채점, 계층별 평가
- versioned config·artifact identity·private trace

## 4. Out of Scope

- FreeToken, SFT/RL, KoVRE, full VLM, Qwen3-VL
- Qwen3 embedding 또는 reranker를 winner로 승격
- 기존 corpus/index의 암묵적 재생성·덮어쓰기
- API key가 필요한 실제 generation의 강제 실행
- 성능 재평가 없이 개선됐다고 선언하는 것

## 5. Assumptions

- `resources/data_refined/private/`는 로컬 source of truth이며 Git에 추가하지 않는다.
- KURE page artifact는 legacy control로 재현 가능하지만 child artifact와 동일하지 않다.
- child KURE artifact가 없으면 builder/loader와 synthetic integration까지 검증하고 실제 전체 embedding은 별도 immutable output에만 생성한다.
- Kiwi dependency나 Qwen reranker weight가 없으면 capability-unavailable을 반환하며 simple tokenizer나 identity를 Kiwi/Qwen 결과로 표기하지 않는다.
- 기존 `RagPipeline`과 public request/response v1은 compatibility control로 유지한다.

## 6. Existing System Touchpoints

| Surface | 역할 | 변경 규칙 |
| --- | --- | --- |
| `indexing/` | page/table/visual chunk 및 exact index | 기존 ID/hash 불변, adapter만 추가 |
| `answering/` | generator/provider budget | verified evidence pack adapter를 추가하고 기존 pipeline 유지 |
| `application/` | metadata/catalog route | planner metadata predicate의 입력으로만 사용 |
| `mini131_report.py`, `evaluation.py` | 기존 평가 | 저장 결과를 재사용하며 새 harness scorer를 분리 |
| `resources/data_refined/private/` | private corpus/index/gold | read-only 기본, 새 artifact는 새 namespace에만 작성 |

시작 artifact identity:

- refined CSV: `cef0a276...7cd7e5b`
- page chunks: 98 docs / 9,331 chunks / `bb82b593...a35b9a2`
- corpus manifest: `6c91d30a...c1fe1cb`
- KURE page vectors: 1,024 dim / `a9aa5e85...9542556`
- local baseline config: `2af236e3...46d8f4`

## 7. Proposed Design

```text
RuntimeRequest + CitationHistory
  -> IntegrityGate
  -> DeterministicPlanner
  -> QueryPlan + ResolvedScope
  -> EvidenceStore
  -> DenseChildLane || KiwiBM25ChildLane
  -> CandidateUnion -> RRF
  -> Reranker -> CoverageSelector
  -> Belief/Progress bounded actions
  -> Analytics | ExhaustiveList | Table/Visual bridge
  -> VerifiedEvidencePack
  -> local/API generator profile
  -> StructuredClaims/Citations
  -> LayeredOfflineEvaluation + PrivateTrace
```

검색 후보는 child evidence뿐이다. parent는 locator와 bounded context expansion에만 사용한다. 서로 다른 granularity는 같은 RRF key로 섞지 않는다.

## 8. Contracts

### 8.1 Runtime / Evaluation Boundary

`RuntimeRequest`는 다음 필드만 허용한다.

```text
request_id, question, history, document_scope, metadata_filters,
options, prior_citation_state
```

`EvaluationCase`는 runtime request와 별도 타입이며 다음 evaluator-only 필드를 보유할 수 있다.

```text
required_doc_ids, required_evidence_ids, qrels, reference_answer, expected
```

projection 함수는 명시적 runtime allowlist만 복사한다. evaluator-only key뿐 아니라 그 값의 lineage도 runtime serialization에서 부재해야 한다. scope 출처는 `user_explicit`, `followup_citations`, `metadata_filter`, `all` 중 하나다.

### 8.2 Scope / Filter Contract

```text
ResolvedScope.state = unfiltered | empty | restricted
ResolvedScope.doc_ids = frozenset[str]
ResolvedScope.origin = user_explicit | followup_citations | metadata_filter | all
```

- `unfiltered`: retriever에는 `None`
- `empty`: retriever에는 `frozenset()`; 모든 lane이 호출 없이 empty 반환
- `restricted`: non-empty `frozenset`
- 미지원 predicate는 `unsupported_filter`, `unresolved_constraint`, `requires_semantic_verification` 중 하나로 남기고 무시하지 않음

### 8.3 Evidence / Provenance Contract

`EvidenceStore`와 `Evidence`는 frozen/content-addressed다.

```text
EvidenceKind = page | text | table_row_group | figure_object | analytics_result
ProvenanceParent.kind = pdf_page | page_v1 | hwp_section_flow | rendered_hwp_page
```

필수 identity에는 `evidence_id`, `doc_id`, content hash, source block IDs, parent ID, locator가 포함된다. child는 parent를 필요로 하고 parent는 검색 후보가 아니다. 기존 page-v1은 재번호화하지 않는다.

Compatibility splitter는 기존 1,600자 newline 방식을 유지한다. heading/paragraph-aware splitter는 별도 `chunker_id`와 artifact hash를 사용한다.

### 8.4 Retrieval Contract

```text
dense.search(query, dense_k, scope) -> child candidates
lexical.search(query, lexical_k, scope) -> child candidates
union -> RRF score = sum(1 / (60 + lane_rank))
```

모든 lane은 같은 `evidence_unit_id`와 `granularity=child`를 선언해야 한다. trace에는 dense-only, lexical-only, both, duplicate, distinct-doc 수와 query tokenization identity를 기록한다.

기본 budget:

| type | dense | lexical | rerank | final | max/doc |
| --- | ---: | ---: | ---: | ---: | ---: |
| fact | 30 | 30 | 40 | 6 | 6 |
| follow_up | 20 | 20 | 30 | 6 | 6 |
| compare | 50 | 50 | 60 | 10 | 2 |
| exhaustive_list | 80 | 80 | dynamic | dynamic | dynamic |
| table_visual | 30 | 30 | 30 | 8 | 4 |

### 8.5 QueryPlan / State Contract

`QueryPlan`은 query type, normalized query, entities, resolved/inherited docs, constraints, metadata predicates, required slots, budget, fallback flag, unresolved constraints, planner version과 config hash를 가진다.

query types: `fact`, `compare`, `follow_up`, `exhaustive_list`, `analytics`, `table_visual`, `unknown_or_out_of_scope`.

compare slot은 `doc_id.field` 키와 candidate/verified/missing/contradiction 상태를 보유한다. follow-up은 실제 `cited_doc_ids`, `cited_evidence_ids`, resolved entities만 상속한다. global fallback은 명시적으로 허용된 경우에만 실행하고 trace한다.

Belief는 intent/entities/constraints/scope/candidate map, Progress는 required/verified/missing/contradicted slots, answerability, coverage ratio다.

typed actions: `retrieve_dense`, `retrieve_lexical`, `fuse`, `expand_parent`, `rerank`, `bridge_table`, `bridge_figure`, `verify_slot`, `stop`, `abstain`.

### 8.6 Specialist Contracts

Analytics는 `count`, `count_by_category`, `sum`, `mean`, `median`, `quantile`, `iqr`, `top_n_share`, `outlier`, `min`, `max`, `ratio`를 deterministic하게 계산한다. 결과에는 corpus hash, input/filtered rows, field, null policy, formula, exact result, source metadata, timestamp, version을 포함한다.

Exhaustive list receipt:

```text
matched_doc_ids, rejected_doc_ids, unknown_doc_ids, visited_doc_ids,
universe_doc_count, completeness, incompleteness_reason,
per_document_evidence, citation_budget
```

미방문/unknown이 있으면 `complete=false`; zero-match도 전 universe를 판정했으면 complete empty set이 가능하다. 일반 top-k나 문서당 2회 LLM scan은 complete 근거가 아니다.

Table correction은 source hash와 locator binding이 검증된 provenance object만 사용할 수 있다. `CORRECTED_TABLES`식 질문별 answer injection은 거부한다. Visual은 caption/nearby text→object bridge까지만 조건부이며 reader가 없으면 `visual_unavailable`이다.

### 8.7 Reranker Contract

- `IdentityReranker`: 공식 control, 입력 순서/ID 보존
- `Qwen3RerankerAdapter`: caller-injected scorer/모델 artifact 필요, candidate 밖 evidence 생성 금지
- model/weight가 없으면 `reranker_unavailable`; identity fallback은 trace에 명시
- 동일 candidate artifact를 재사용해 retrieval 변화와 reranker 변화를 분리

### 8.8 Structured Citation Contract

```json
{
  "claim_id": "claim_1",
  "text": "...",
  "status": "supported",
  "evidence_ids": ["ev_..."]
}
```

```json
{
  "evidence_id": "ev_...",
  "doc_id": "doc_...",
  "parent_id": "ev_...",
  "source_block_ids": ["block_..."],
  "locator": {"page": 1, "section_path": []}
}
```

모든 citation은 같은 EvidenceStore에서 resolve되어야 한다. 기존 string citation은 compatibility projection일 뿐 source of truth가 아니다.

### 8.9 Evaluation Contract

레이어를 하나의 평균으로 합치지 않는다.

- integrity: leakage, hash mismatch, invalid scope, missing citation
- parser/provenance: source/parent/object binding
- retrieval: Recall@k, MRR, nDCG, lane rescue, doc coverage
- context: pre/post retention, mandatory retention, slot coverage
- deterministic generation: abstention, citation coverage, amount/date/token normalization, polarity
- semantic generation: correctness/faithfulness/completeness adapter; provider 없으면 unavailable
- list: precision/recall/F1/exact/completeness
- analytics: exact result/formula/source
- visual: source/object bridge support

저장 답변 scorer는 provider를 호출하지 않는다.

### 8.10 Config / Artifact Contract

`architecture_id=bidfit-evidence-harness-v1-rc0` config는 R0~R4/E0~E1 profile과 query-type budget을 한곳에 고정한다. trace/report에는 config hash, evidence bundle hash, dense/lexical artifact hash, model revision, dimensions, chunker ID를 포함한다.

## 9. Permission / Risk Rules

- private corpus, qrels, expected answer, prompt/trace 본문은 Git에 저장하지 않음
- 기존 artifact는 read-only; 새 builder는 대상 경로가 이미 있으면 fail-closed
- API key 부재는 unavailable이며 자동 fallback/과금 호출 금지
- model download는 명시적 실행 경로에서만 가능
- 성능 향상은 동일 gold/config/generator로 재평가한 뒤에만 주장

## 10. Acceptance Criteria

1. 시작 full suite 805 tests가 보존되고 최종 full suite가 통과한다.
2. evaluator-only 값이 runtime scope/plan serialization에 없다.
3. empty filter는 global search로 변하지 않는다.
4. legacy control과 child RRF profile이 모두 실행된다.
5. dense와 Kiwi BM25가 동일 child 단위에서 독립 실행되고 lexical-only rescue가 union에 남는다.
6. compare slot과 distinct-document coverage가 동작한다.
7. follow-up은 실제 citation state만 상속하며 fallback을 trace한다.
8. list는 미방문 문서가 있으면 complete를 주장하지 않는다.
9. analytics 결과가 deterministic provenance를 포함한다.
10. table correction은 source binding 없이는 사용되지 않는다.
11. structured citation이 EvidenceStore 객체로 resolve된다.
12. config/artifact identity가 trace에 남는다.
13. scorer regression 6종과 저장 답변 재채점이 provider 없이 통과한다.

## 11. Implementation Batches

### Batch 0: Integrity and evaluator safety

**Goal:** runtime/evaluator 타입 분리, fail-closed scope, scorer 회귀를 먼저 고정한다.

**Expected modules:** `runtime_integrity.py`, planner/scope DTO, harness evaluator와 tests.

**Done when:** leakage lineage, empty filter, unsupported predicate, normalization/polarity tests가 통과한다.

### Batch 1: Evidence and retrieval plane

**Goal:** immutable EvidenceStore, child dense/Kiwi BM25, independent RRF, context/legacy profiles를 연결한다.

**Done when:** 동일 child granularity, rescue trace, deterministic ranking, parent-only expansion이 검증된다.

### Batch 2: E1 planner and bounded harness

**Goal:** typed QueryPlan, compare/follow-up, Belief/Progress/actions와 bounded policy를 구현한다.

**Done when:** required slots와 actual-citation inheritance가 trace에서 증명된다.

### Batch 3: Specialist lanes and citations

**Goal:** analytics/list/table correction/visual conditional과 structured citation을 구현한다.

**Done when:** complete receipt, deterministic analytics, source-bound citations가 통과한다.

### Batch 4: Reranker, config and layered evaluation

**Goal:** identity/Qwen adapter, R0~R4/E0~E1 config, layered report를 연결한다.

**Done when:** optional unavailable이 정직하게 기록되고 전체 suite·flow report가 통과한다.

## 12. Test Plan

- Unit: 사용자 요구사항의 integrity/retrieval/follow-up/list/analytics/citation/table case 전부
- Integration: synthetic EvidenceStore에서 child dense+Kiwi BM25+RRF→planner→harness→structured result
- Legacy: 기존 full `unittest discover`와 artifact hash 불변
- Real artifact smoke: refined98 metadata와 기존 page control은 read-only 검증; 새 full child embedding은 별도 artifact 유무에 따라 실행/미실행을 구분
- Static: `compileall`, repository safety
- Workflow: target/current Mermaid PNG/HTML과 Playwright 렌더

## 13. Capability Gaps / Open Questions

| Gap | 현재 영향 | 처리 |
| --- | --- | --- |
| full refined98 KURE child artifact 부재 | 실제 새 profile 성능 재평가 불가 | builder/identity/명령 제공, 별도 경로에 생성 후 평가 |
| Qwen3 reranker weight/runtime 미확인 | challenger 실측 불가 | adapter/mock/unavailable만 구현 |
| API key 사용 여부 | API generation 재실행 불확실 | 저장 답변 재채점, API는 unavailable 가능 |
| full VLM/KoVRE | 그림 의미 질의 미지원 | 이번 범위 밖, conditional bridge 후 기권 |

## 14. Migration / Rollback

- 기본 legacy profile을 제거하지 않는다.
- 새 config를 opt-in으로 선택하면 harness 경로가 실행된다.
- rollback은 config를 `legacy_page_control`로 되돌리는 것이며 기존 corpus/index를 수정하지 않는다.
- 새 child/lexical artifacts는 namespace 단위로 추가/폐기할 수 있고 기존 page-v1 hash에는 영향이 없다.

## 15. Handoff Notes

구현은 Batch 0→4 순서를 지키고 매 batch targeted tests를 실행한다. 현재 dirty 변경과 겹치는 파일은 가능한 한 건드리지 않고 신규 package/config/test로 구성한다. 필요한 기존 entry point 수정은 최소 patch로 제한하고 커밋 시 이번 원샷 path만 명시적으로 stage한다.

## 16. 작은 단위 실행 / 모듈 경계

사용자 최신 요청에 따라 canonical 실행 순서는 `../todolist.md`의 EH-RC0 leaf tree가 정한다.
체크포인트는 `../../work/bidfit-evidence-harness-v1-rc0-checkpoint.md`다. 계약 자체를 매 leaf마다 복제하지 않는다.

구조 결정: 기존 Python package 안에 작은 modular monolith를 추가한다. 새 서버·DB·microservice는 만들지 않는다.
모듈 public API는 `__init__.py` 또는 아래 명시된 단일 모듈이다. 다른 모듈의 private 파일을 직접 import하지 않는다.

| 공개 모듈 | 소유 데이터/책임 | 허용 의존성 | 금지 책임 |
| --- | --- | --- | --- |
| `runtime_integrity.py` | RuntimeRequest, EvaluationCase 경계, scope/filter DTO | 표준 라이브러리 | 검색, 모델 호출, gold로 scope 생성 |
| `evidence` | evidence/provenance/immutable artifact | runtime primitive, 기존 ingest의 검증된 공개 도구 | gold/LLM/검색 순위 |
| `retrieval` | child 후보, tokenizer/index, fusion/context | evidence public API, 기존 pinned embedder/index adapter | 답변 정답/평가 라벨 접근 |
| `orchestration` | QueryPlan/Belief/Progress/action policy | runtime, evidence, retrieval, specialist 공개 API | private model 구현/평가 정답 |
| `analytics` | catalog 판정/통계/list receipt | runtime, evidence | query별 정답 주입/임의 추정 결측 |
| `offline_harness` | scorer/eval case/재채점 receipt | 위 공개 API (일방향) | runtime scope/plan 변경 |
| `harness_cli.py` | config/load/명령 조립 | 공개 API와 provider adapters | core ranking/통계 규칙 |

runtime public API: `RuntimeRequest.from_dict`, `project_runtime`, `EvaluationCase.from_dict`.
Evaluator→runtime 변환은 `project_runtime` 한 곳으로 제한한다. options/history/filter 중첩에도 닫힌 스키마를 적용한다.
공통 데이터는 소유 모듈의 frozen DTO/조회 API로만 전달한다. boundary tests는 runtime→evaluator 의존과
parent/child 혼합, 골든 값 의존을 검출한다. 정확한 새 파일/메서드는 해당 leaf 착수 때 이 표의 책임 안에서 정한다.
독립 확장 후보는 retrieval/tokenizer adapter와 generator adapter지만 서비스 분리는 현재 팀/규모에서 불필요하다.

### 16.1 Evidence public types — EH1.1

- `Locator(page=None, flow_id=None, section_path=(), object_id=None, bbox=None, row_range=None, char_range=None)`:
  page는 1-based, bbox는 `(x0,y0,x1,y1)`이며 좌표계의 정합성은 builder/source artifact가 증명한다.
  HWP flow에 물리 page를 추정해 채우지 않는다.
- `char_range=(start,end)`는 parent 원문 기준 0-based half-open 범위다. 동일 문구의 반복 occurrence를
  ID suffix나 가짜 source ID 없이 구별한다. Store가 text/page의 원문 slice 동일성을 검증한다.
  `row_range`는 0-based inclusive이며 char_range와 다른 좌표계다.
- `ProvenanceParent(doc_id, kind, text, source_block_ids, locator)`: `parent_id=pr_<hash>`, content SHA.
  kind는 pdf_page/page_v1/hwp_section_flow/rendered_hwp_page.
  analytics/catalog용 예외는 필요할 때 EH3에서 명시적으로 확장하며 현재 page로 위장하지 않는다.
- `Evidence(doc_id, kind, text, parent_id, source_block_ids, locator, source_chunk_ids=(), crop_ref=None, support_refs=())`:
  `evidence_id=ev_<hash>`, content SHA. kind는 page/text/table_row_group/figure_object/analytics_result.
- `page` evidence는 legacy control을 표현할 때만 사용한다. child 검색의 기본 후보는 text이며 parent는 항상 provenance 전용이다.
- ID는 원문 text+모든 provenance 필드의 canonical identity에서 결정된다. 알 수 없는/위조 ID를 from_dict로 허용하지 않는다.
- DTO는 frozen+slots, nested collection은 tuple; source block/chunk identity는 그대로 보존.
- 공개 API는 `midprojectrag.evidence`의 타입과 `to_dict/from_dict`; 외부 JSON이나 객체를 실행하지 않는다.
- 다음 EH1.2 store가 parent 존재/doc/locator/source binding을 검증한다. EH1.1 타입만으로 graph 검증 완료를 주장하지 않는다.
- figure_object는 유효한 crop_ref가 있으면 비어 있는 텍스트를 허용한다. 읽지 않은 그림에 임의 caption을 생성하지 않는다.

### 16.2 EvidenceStore — EH1.2

- 생성 시 부모/근거 iterable을 복사해 read-only mapping과 tuple 인덱스로 고정한다. 외부 mutation으로 snapshot/hash가 바뀌지 않는다.
- `get(evidence_id)`, `parent(parent_id)`, `children(parent_id, kinds=None)`, `for_document(doc_id, kinds=None)`,
  `bridge(evidence_id, kinds)`는 저장소 안의 canonical 객체만 반환한다. 알 수 없는 ID는 명시적 오류다.
- 부모 존재/같은 doc/child source block의 parent 포함을 검증한다. page/flow는 부모와 동일하며
  section은 parent prefix, parent에 object/bbox/row 범위가 있으면 child의 같은 locator/포함 관계를 검증한다.
- text/page의 char_range가 있으면 범위와 정확한 parent text slice를 검증한다. 부모의 source block은
  immutable provenance이며 table/figure 텍스트는 원문 구조 변환을 허용하되 별도 EH3 source binding이 필요하다.
- support_refs는 동일 저장소의 evidence ID만 참조한다. 자기 참조/cycle/다른 문서의 근거 연결은 거부한다.
- 동일 ID 중복 입력은 조용히 유실시키지 않고 거부한다. 반복 문구 occurrence는 char_range로 구별한다.
- snapshot `to_dict/from_dict`는 canonical content hash를 검증하며 입력 순서가 달라도 bundle hash는 같다.
  hash는 무결성 식별자이지 외부 자료가 진실임을 인증하는 서명은 아니다.

### 16.3 Child builder — EH1.3~4

- `SplitConfig(chunker_id="compat-newline-1600-v1", max_chars=1600)`와 `split_spans(text,config)`는
  Python Unicode character 기준의 원문 `(start,end)` 범위를 반환한다. compat는 기존 newline split
  정책(후반부의 마지막 빈줄→줄바꿈→hard cut, 주변 공백 제거)을 재현한다.
- 현재 checkout에는 별도 1,600자 child artifact가 없고 page-v1만 있다. 따라서 기존 page-v1/ID는 그대로
  유지하고 이 정책을 새 child compatibility profile로 명시한다. 기존 child를 재사용했다는 주장은 하지 않는다.
- `build_store(chunks, config, source_blocks=None, parent_kinds=None)`는 검증된 page-v1을 입력받아
  provenance parent+text child+명시적 legacy page evidence를 만든다. source chunk IDs는 원래 값이다.
- source block이 없으면 part_count=1인 page-v1만 허용한다. multipart 원문을 추측해 이어붙이지 않는다.
  source block을 제공하면 doc/content hash/page/source ID와 각 chunk의 정확한 원문 부분 문자열을 검사한다.
- `heading-paragraph-v1`은 별도 실험 splitter다. section heading/빈줄 경계에서 나누며 oversize는
  compat hard bound로 나눈다. 두 정책 모두 원문 slice 보존/최대 길이/반복 occurrence 검증이 필요하다.
- 새 bundle은 data_root/private 아래 새 디렉터리에만 저장하며 기존 경로는 거부한다. bundle/config/input
  SHA와 parent/evidence/doc count를 receipt에 남긴다. loader는 이 계약과 SHA를 재검증한다.

### 16.4 Retrieval public boundary — EH1.5~9

- `Candidate(evidence_id,doc_id,score,lane,rank,granularity="child")`와 `SearchResult(candidates,trace)`는 immutable다.
- `DenseChildLane(store,vectors,embedding_identity,query_embedder)`는 정확한 child row 순서와 1,024차원,
  pinned KURE revision/prompt/pooling을 검증한다. page evidence는 후보가 아니며 부모는 벡터화하지 않는다.
- `search(query,limit,*,allowed_doc_ids=None)`에서 empty는 encoder 호출 전 종료한다. scope를 먼저
  적용하고 cosine 계산·동점 evidence ID 정렬을 한다. 합성 tests의 fake encoder는 실측 성공으로 집계하지 않는다.
- `build_dense`는 순서 고정한 child text를 실제 provider에 배치 전달해 새 vectors를 생성한다. provider identity와
  store/bundle/row/vector SHA를 저장하고 load 시 모두 확인한다. 기존 page vector 재활용 금지.
- legacy adapter만 granularity=page를 선언하며 동일 source_chunk_ids를 실제 기존 index hit와 연결한다.
  새 child fusion은 page/child 혼합을 명시적으로 거부한다.
