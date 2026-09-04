# BidFit Evidence-Harness v1-rc0

## 0. 실험 지위와 선택 계약

이 계약의 구현은 기존 RAG를 곧바로 대체하기 위한 작업이 아니다. page-only baseline은 공정한 비교를
위한 불변 control로 보존한다. 본 Evidence-Harness는 GPT retrieval 연구, EvoHarness 연구와 팀 실험을
조립한 **challenger**이며, 검색 품질과 효율이 더 좋을 것이라는 가설을 검증하는 대상이다.

- 구현·unit/full regression PASS는 기능 안전성 증거이며 성능 우승 증거가 아니다.
- baseline과 challenger는 같은 refined98, frozen gold/qrels, judge/rubric, 질문 순서, scope, budget과
  hash-attested config/artifact로 비교한다.
- component ablation 뒤 조립형 A/B를 수행하고 Recall/MRR/nDCG, 필수 문서·page·object·set completeness,
  build/query latency, RAM/VRAM, index size, token/cost, citation·abstention·error 회귀로 판단한다.
- full golden A/B gate 전에는 default profile을 바꾸거나 “향상/최종”을 주장하지 않는다.
- 최종 통합 대상은 `feat/local-qwen-mini131-eval`이며 generator는 local/API 교체형이다. 현재
  `feat/total-integration`은 challenger 조립 작업대이고 API page-only 경로는 비교 control이다.
- threshold와 non-inferiority 규칙은 run 전에 평가 config에 동결하며, 결과가 혼합되면 baseline을
  유지하거나 품질·효율 Pareto 경계에서 가장 단순한 구성을 선택한다.

## 1. Goal

현재 checkout의 page/table/visual·Mini131 기반선을 control로 보존하면서, 사용자 질문과 대화 이력에서
출발해 무결성 검사를 거친 Evidence 기반 검색·검증·생성·평가 challenger를 production modules로
조립한다. 조립 후 동일 골든셋으로 baseline 대비 검색 품질·효율·안전성을 비교해 채택 여부를 결정한다.

## 2. Background / Current Problem

시작 시점(`feat/vlm-visual-retrieval`, `7ad229f`)에는 다음이 확인됐다.

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

### 8.11 Control / Challenger Selection Contract

retrieval architecture 비교의 authoritative control은 local KURE page-v1 profile이다. API/local generator
비교는 별도 축이며 retrieval arm의 generator·prompt·temperature·hardware/cache 조건을 중간에 바꾸지 않는다.
각 run은 `control|challenger`와 `hypothesis|implemented_unmeasured|evaluated|selected` 상태를 명시한다.

```text
ComparisonSelectionReceipt:
  experiment_id
  control_architecture_id
  challenger_architecture_id
  corpus_hash, golden_hash, qrels_hash, split_hash
  scoring_hash, judge_hash, rubric_hash, non_target_stack_hash
  runtime_profile, quality_metrics, efficiency_metrics, paired_deltas
  hard_gate_results, selection_policy_hash
  decision = selected | retain_control | no_winner
  reasons
```

selection policy와 threshold는 결과를 보기 전에 hash로 봉인한다. integrity/security/reproducibility hard
gate를 모두 통과한 뒤 (a) 핵심 검색 품질이 개선되고 효율 guardrail을 지키거나, (b) 검색 품질이
non-inferior이면서 핵심 효율 지표 하나 이상이 개선될 때만 선택할 수 있다. 임계값이 없거나 서로 Pareto
우위가 아니면 `no_winner`로 기록한다. 누락·오류 case는 분모에서 빼지 않으며 held-out은 튜닝 종료 후 한 번만
실행한다. research 문서, unit/full test, synthetic smoke는 measured superiority로 사용할 수 없다.

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
14. baseline과 challenger가 같은 frozen corpus/gold/qrels/split/scorer/judge 및 non-target stack으로 실제 실행된다.
15. case-level paired delta, 유효 분모, 검색 품질과 효율 지표가 분리 기록된다.
16. `ComparisonSelectionReceipt`가 없으면 challenger는 기본 runtime을 대체하지 않고 baseline을 유지한다.
17. retrieval architecture 결과와 API/local generator 결과를 섞어 우승을 선언하지 않는다.

## 11. Implementation Batches

### Batch 0: Integrity and evaluator safety

**Goal:** runtime/evaluator 타입 분리, fail-closed scope, scorer 회귀를 먼저 고정한다.

**Expected modules:** `runtime_integrity.py`, planner/scope DTO, harness evaluator와 tests.

**Done when:** leakage lineage, empty filter, unsupported predicate, normalization/polarity tests가 통과한다.

### Batch 1: Evidence and retrieval plane

**Goal:** immutable EvidenceStore, child dense/Kiwi BM25, independent RRF, context/legacy profiles를 연결한다.

**Done when:** 동일 child granularity, rescue trace, deterministic ranking, parent-only expansion이 검증된다.

### Batch 2: E1 planner and bounded harness

**Goal:** 기존 평가 Batch 2의 남은 책임을 `EH2.EVAL`로 흡수하고, typed QueryPlan,
compare/follow-up, Belief/Progress/actions와 bounded policy를 구현한다.

**Evaluation ownership:** `evaluation-contract.md`가 질문·split·qrels·hash의 단일 원천이다.
EH는 평가 Schema나 별도 전후 질문셋을 다시 만들지 않는다. `EH2.EVAL`은 완료된 평가 foundation을
참조하고, lane→fusion→rerank→final-context checkpoint가 그 계약을 만족하도록 실행 receipt를 설계한다.
dev 승인과 held-out 작성은 EH 구현과 병행할 수 있지만, actual paired selection과 held-out 실행은
최종 config 동결 뒤 Batch 4에서만 수행한다.

**Done when:** required slots와 actual-citation inheritance가 trace에서 증명되고, qrels가 runtime에
유입되지 않은 채 evaluator가 단계별 receipt를 offline join할 수 있다.

### Batch 3: Specialist lanes and citations

**Goal:** analytics/list/table correction/visual conditional과 structured citation을 구현한다.

**Done when:** complete receipt, deterministic analytics, source-bound citations가 통과한다.

### Batch 4: Reranker, config and layered evaluation

**Goal:** identity/Qwen adapter, R0~R4/E0~E1 config, layered report를 연결한다.

**Done when:** optional unavailable이 정직하게 기록되고 전체 suite·flow report가 통과하며, same-golden
paired run과 `ComparisonSelectionReceipt`가 `selected|retain_control|no_winner` 중 하나를 근거와 함께 남긴다.

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

### 16.5 QueryPlan과 rule registry — EH2.1

- 공개 API는 `midprojectrag.orchestration`의 `QueryPlan`, `RetrievalBudget`, `RequiredSlot`,
  `PlanEntity`, `PlanConstraint`, `RoutingRule`, `RuleRegistry`, `default_rule_registry`다.
- query type은 `fact`, `compare`, `follow_up`, `exhaustive_list`, `analytics`, `table_visual`,
  `unknown_or_out_of_scope`의 닫힌 집합이다. 알 수 없는 문자열을 `fact`로 대체하지 않는다.
- `QueryPlan`은 schema version, normalized query, entity와 그 출처, resolved/inherited doc ID,
  fail-closed scope state/origin, 일반 constraint, typed `MetadataPredicate`, `doc_id.field` required slot, 여섯 budget 값,
  global fallback 허용 여부, unresolved constraint, planner version, registry config SHA를 보존한다.
- 모든 DTO는 frozen+slots이며 중첩 sequence를 tuple로 복사한다. `to_dict/from_dict`는 정확히 닫힌
  JSON schema와 유한 숫자를 검증하고, unknown/missing field와 중복 ID/slot을 거부한다.
- `RetrievalBudget`의 `None`은 동적 예산을 뜻하며 JSON에서는 `null`이다. 기본값은 §8.4를 따르고
  analytics는 catalog 전용이므로 검색 예산 0·동적 citation, unknown은 전부 0이다. exhaustive list에는
  dense/lexical 80씩만 고정하고 rerank/final/max-per-doc/citation을 동적으로 둔다.
- `RuleRegistry`는 query-type별 budget을 정확히 한 개씩 소유하고 rule ID를 중복 허용하지 않는다.
  canonical JSON의 SHA-256을 `config_sha256`으로 계산하며 로드시 재검증한다.
- provenance source는 기관/사업 alias, filename tag, domain synonym, history citation, metadata predicate,
  일반 query expression을 구분한다. 실행 가능한 `RoutingRule` source는 history citation과 일반 query
  expression뿐이며 alias는 content-hashed catalog, predicate는 runtime request에서 온다. registry에는
  evaluator case ID, expected doc, qrels, 정답 문자열을 넣지 않는다. 실제 실행은 EH2.2 책임이다.
- plan 생성은 registry factory를 거쳐 budget/planner version/config SHA를 결합한다. registry 검증은
  임의 plan이 다른 budget이나 SHA를 주장하면 거부한다. EH2.1은 router 실행·follow-up 상속·slot 상태
  전이·controller를 구현했다고 주장하지 않는다.

### 16.6 Deterministic planner — EH2.2

- `DeterministicPlanner`의 유일한 runtime 입력은 닫힌 `RuntimeRequest`다. `EvaluationCase`나 임의 mapping을
  받지 않으며, gold/qrels/expected/source-document 필드는 planner API에 존재하지 않는다.
- `PlanningCatalog`는 production metadata에서 `from_metadata(CatalogDocument...)`로 파생하거나, 테스트에서만
  `synthetic(...)`으로 만드는 봉인된 불변 snapshot이다. raw constructor는 거부한다. source는 agency/business
  alias, filename tag, domain synonym만 허용하고 catalog/source canonical JSON SHA 및 production/synthetic
  실행 구분을 trace에 남긴다. 직렬화된 catalog 로드는 별도의 기대 source SHA를 필수 trust anchor로 받고,
  source documents에서 entity를 다시 파생한다. 이는 평가 expected-document registry가 아니다.
- query normalization은 NFC+공백 정리만 하며 원문의 의미 토큰을 삭제하지 않는다. 실행 planner는 현재
  승인된 default registry SHA만 받고, query-type rule은 priority/rule ID 순으로 평가해 match ID/source를
  trace한다. citation history rule은 실제
  prior citation이 있으면서 등록된 follow-up signal이 일치할 때만 활성화한다. 무조건적인 history 결합은 하지 않는다.
- 문서 scope는 `all`, `user_explicit`, `entity_resolution`, `user_explicit+entity_resolution`을 구분한다.
  explicit empty와 explicit∩entity empty는 `empty`로 보존하고 global 검색으로 바꾸지 않는다.
  entity의 catalog match는 scope 적용 전 후보이므로 최종 resolved scope 밖 doc ID도 provenance로 보존할 수 있다.
  겹치는 alias는 가장 긴 실제 occurrence를 우선하고, 같은 alias의 서로 다른 binding은 union하지 않고
  `ambiguous_entity_alias`와 empty scope로 닫는다.
- request metadata filter는 모두 `MetadataPredicate`로 재구성한다. unsupported/unresolved 상태는 plan의
  `unresolved_constraints`와 trace 양쪽에 남기며 조용히 버리지 않는다. predicate 실행은 EH3.1 책임이다.
- 결과는 `PlanningResult(plan, trace)`다. trace에는 request fingerprint, registry/catalog SHA, matched rule,
  scope state/origin/doc IDs, predicate status를 기록하고 질문/정답 본문은 복제하지 않는다.
- EH2.2는 follow-up cited ID 상속/승인된 fallback 실행(EH2.3), compare slot 생성(EH2.4), state/action
  projection·decision(EH2.5), state transition·retrieval controller(EH2.6)를 구현했다고 주장하지 않는다.

### 16.7 Actual-citation follow-up — EH2.3

- follow-up scope 후보는 `RuntimeRequest.prior_citation_state`의 cited doc/evidence뿐이다. 가장 최근의
  실제 assistant history turn에 기록된 두 citation 배열과 정확히 일치하고, 현재 immutable
  `EvidenceStore`에서 doc/evidence 및 evidence→doc binding이 확인돼야 한다. list/comparison doc ID,
  resolved-entity 문자열, evaluator expected/qrels는 scope를 넓히지 않는다.
- 사용자가 명시한 document scope는 citation 상속보다 우선한다. entity scope와 citation scope가 함께
  있으면 교집합만 `combined`로 사용하고, 공집합은 empty로 닫는다. 순수 follow-up일 때만
  `followup_citations` scope와 `inherited_doc_ids`를 만든다.
- fallback은 versioned policy와 현재 `EvidenceStore`에 결합된 `PrimaryEvidenceProgress`가 검증된
  answer-support evidence/required-slot 충족도를 판정한 뒤에만 고려한다. raw boolean, primary candidate 수,
  distinct-doc 수는 충분성 증거로 사용하지 않는다. plan이 허용하고 검증된 primary 근거가 부족한 경우에만
  unfiltered 검색을 정확히 한 번 실행한다. user-explicit/empty/combined scope는 global fallback을 허용하지
  않는다. EH2.3은 이 봉인된 경계를 만들고, 의미 검증기와 slot verifier 연결은 EH2.5~EH2.6에서 완성한다.
- 결과는 primary와 optional fallback `SearchResult`를 별도로 보존한다. trace에는 request/plan/store/policy
  hash, scope, candidate 수, 충분성, 승인·실행 여부와 bounded reason code만 기록하며 질문·정답 본문을
  복제하지 않는다. 검색 결과의 bundle, child granularity, evidence/doc/scope binding을 다시 검증한다.

### 16.8 Compare doc×field slots — EH2.4

- compare는 base `PlanningResult`를 바로 실행하지 않는다. `RuntimeRequest`와 동일
  `DeterministicPlanner`로 계획을 재생성해 fingerprint·scope·catalog provenance를 다시 대조한 뒤,
  별도의 versioned compare-field registry SHA와 전체 canonical planning result/trace SHA,
  planner execution kind, catalog source kind/source SHA, base/effective plan SHA를 `BoundCompare`에
  봉인한다. 검색·coverage entrypoint는 factory가 발급한 변경되지 않은 동일 객체 identity까지
  요구하므로 같은 모양의 저수준 재구성이나 발급 뒤 중첩 planning 교체는 실행 권한이 아니다.
  evaluator expected/qrels/required document는 인자나 field registry에 들어올 수 없다.
- 비교 대상은 사용자가 명시한 문서 scope 2건 이상 또는 질의에서 각각 단일 문서로
  해소된 business entity 2개 이상일 때만 승인한다. unfiltered·empty·1건·다중 문서 agency
  alias는 임의로 첫 N건을 고르지 않고 bounded unresolved reason으로 닫는다. 명시 scope 밖의
  business target을 질의가 추가로 지목한 경우에도 일부 대상만 남기지 않고 unresolved로 닫는다.
- 비교 축은 NFC/boundary-aware한 일반 domain signal registry로만 선택한다. 명시된 축이
  없으면 예산·기간·유지보수를 임의로 삽입하지 않고 `compare_fields_unresolved`로 남긴다.
  해소된 사업명/alias 구간은 축 선택 전에 제거해 사업명 안의 `유지보수` 같은 단어를 축으로
  오인하지 않는다. v2 선택기는 `만` 조사를 인식하고 `비교하지 말고`·`제외`·`빼고` 뒤의 축을
  positive axis로 선택하지 않는다. 인식된 축과 미지원 축/미해소 target이 함께 있으면 조용히
  일부만 남기지 않고 `compare_fields_unsupported`/`compare_targets_unresolved`로 닫는다.
  metadata predicate는 EH3.1의 실제 filtered-scope receipt가 없으면 지원 문법도
  실행 완료로 간주하지 않고 fail-closed한다.
  유효한 대상·축이면 `resolved_doc_ids × selected_fields`의 전체 Cartesian product를 doc-major
  순서로 `required_slots`에 생성하며 부분 matrix를 허용하지 않는다.
- compare slot은 unsearched/candidate/verified/missing/contradicted 상태와 candidate/verified evidence,
  bounded missing reason, contradiction state를 따로 보존한다. candidate는 사용자 비교·부정 문장을
  재사용하지 않은 registry-owned positive field 한국어 검색어,
  단일 document scope, 전체 slot matrix에 균등 분할한 query-level plan budget, slot ordinal,
  action/profile과 store/binding/plan hash를 묶은 `CompareSearchReceipt`에서만 오고, provider raw trace는
  닫힌 projection과 source trace hash로 교체한다. production 검색은 query 전달 전에 loader가 발급한
  KURE/Kiwi child attestation과 `from_loaded_artifacts` factory가 발급한 hybrid runtime binding,
  store/row/artifact identity를 모두 재검증한 RRF retriever만 허용한다. raw constructor와 class 이름,
  hash 모양만으로는 승인하지 않는다. 실제 query inference는 노출된 mutable adapter가 아니라 pinned
  dependency identity를 확인한 private runtime을 사용한다. artifact hash는 일관성을 증명하며 외부
  작성자를 인증하지 않으므로 private artifact directory는 배포 신뢰 경계로 유지한다. 동일 slot의
  재시도·누적 소비 ledger는 EH2.6 책임이며 EH2.4 receipt만으로 전체 실행 횟수를 주장하지 않는다.
  EH2.4의 `CompareVerificationReceipt`는 field rule 신호가 있는
  candidate를 `field_relevance_only`로만 기록하며 verified evidence를 만들지 않는다. 실제 claim/value와
  support를 봉인하는 typed semantic receipt가 추가되기 전에는 해당 슬롯도 candidate 상태이고 정상 stop은
  불가능하다. 빈 top-k·후보 수·예산 소진만으로 missing을 확정하지 않는다.
- EH2.4의 missing은 `no_candidate_yet`/`candidates_unverified`를 보존하는 비종료 관찰이다.
  bounded action을 모두 수행했음을 봉인한 absence receipt는 EH2.6에서만 만들며,
  그전에는 missing reason이 있어도 coverage·정상 stop에 산입하지 않는다.
- coverage는 slot과 document 두 축으로 계산한다. 모든 required slot이 verified이고 모든 required
  document의 필드가 완결됐을 때만 정상 stop을 허용한다. verified와 confirmed missing이 섞인 경우는
  `partial_abstained`, 전부 confirmed missing이면 `abstained`이며 둘 다 정상 stop이 아니다.
  confirmed contradiction은 accounted로는 보이되 정상 stop을 막고 abstain/conflict 경로를
  요구한다. EH2.4는 임의 evidence 두 건만으로 contradiction을 확정하지 않으며 typed value receipt가
  추가될 때까지 그 승격을 차단한다. required slot 0건을 vacuous completion으로 판정하지 않는다.
  `CompareCoverage`는 factory가 발급한 동일 객체 identity와 전체 tree hash를 함께 요구하고, 각 slot과
  document를 재검증한 뒤 count·ratio·covered/accounted document·answerability·stop flag를 원자료에서
  다시 계산한다. 상단 집계값이나 중첩 slot을 바꾸고 공개 hash만 다시 계산한 객체는 권한이 아니다.
- persisted receipt는 provider를 다시 호출하기 전에 slot/request/binding/plan/store/query/budget/scope/
  action/profile/result projection 및 내부·외부 hash를 pure-validation한다. 재생 결과 비교는 Python의
  느슨한 scalar equality가 아니라 canonical JSON으로 수행해 `4`/`4.0`, `false`/`0`도 구분한다.

### 16.9 Belief / Progress / typed action — EH2.5

- EH2.5는 실행 loop가 아니다. EH2.3의 follow-up binding/progress/outcome과 EH2.4의 compare
  binding/coverage를 공통 상태로 투영하고, 현재 상태에서 허용되는 typed action과 결정 chain만
  만든다. retrieval/provider 호출, retry·round·deadline·no-progress, 실제 before→after 효과 및
  confirmed absence receipt는 EH2.6 책임이다. `HarnessState` reducer/transition과 action-effect
  receipt도 EH2.6 전용이며 EH2.5 API에는 존재하지 않는다.
- `Belief`는 `source_kind`, request/binding/effective-plan/config/store identity, query type,
  plan에서 온 entity/constraint, scope, obligation별 candidate/verified evidence map과 원본 authority
  receipt SHA를 보존한다. 원문 질문이나 action이 바꿀 수 있는 query/scope/doc ID는 복제하지 않는다.
  `Progress`는 required/verified/provisional-missing/confirmed-missing/contradicted/open obligation,
  coverage ratio, answerability와 stop/abstain gate를 보존한다. compare의 EH2.4 missing은 전부
  provisional+open이며 field relevance만으로 verified가 되지 않는다.
- follow-up은 예약 obligation `$answer_support`를 항상 첫 항목으로 사용하고 실제 required slot을
  plan 순서로 뒤에 둔다. primary 뒤 fallback candidate를 순서 보존 dedupe하고,
  `PrimaryEvidenceProgress`의 verified answer/slot만 verified로 투영한다. `sufficient=true`이고
  outcome trace와 전체 hash chain이 맞을 때만 정상 stop을 허용한다. fallback 미승인·빈 결과는
  confirmed absence나 강제 abstain 근거가 아니다.
- `HarnessState`와 그 하위 DTO는 frozen/slotted/factory-only이며 factory가 발급한 동일 object identity와
  전체 canonical payload hash를 실행 경계에서 다시 확인한다. compare는 기존 identity authority를
  재사용한다. follow-up은 raw `object.__new__`나 발급 후 drift를 막도록 bound/attempt/progress/outcome의
  발급 identity와 request/plan/store/policy/result hash chain을 먼저 봉인한다.
- typed action은 `retrieve_dense`, `retrieve_lexical`, `fuse`, `expand_parent`, `rerank`,
  `bridge_table`, `bridge_figure`, `verify_slot`, `stop`, `abstain`으로 닫는다. retrieve/fuse/rerank/verify는
  obligation만, expand/bridge는 obligation+현재 candidate evidence만, terminal action은 target 없이
  생성한다. action에는 임의 query나 scope를 받지 않는다. `fuse`는 lane별 실행 ledger가 생기는
  EH2.6 전에는 타입만 제공하고 허용 action으로 발급하지 않는다.
- 비종료 allowed action은 source와 obligation 상태로 정확히 제한한다.

  | source | obligation 상태 | EH2.5 allowed action |
  | --- | --- | --- |
  | compare | `unsearched` | `retrieve_dense`, `retrieve_lexical` |
  | compare | `candidate` | eligibility를 만족하는 `expand_parent`, `bridge_table`, `bridge_figure`; 이후 `rerank`, `verify_slot` |
  | compare | `provisional_missing` | `retrieve_dense`, `retrieve_lexical` |
  | follow-up | `$answer_support` 또는 실제 slot의 `candidate` | eligibility를 만족하는 `expand_parent`, `bridge_table`, `bridge_figure`; 이후 `rerank`, `verify_slot` |
  | follow-up | `provisional_missing` | 없음. EH2.3의 primary와 허용된 fallback은 이미 종결되었고 재시도는 EH2.6 전용이다. |
  | 공통 | `verified`, `confirmed_missing` | 없음 |
  | 공통 | `contradicted` | 전역 gate가 `abstain`만 허용 |

  `expand_parent`는 해당 obligation의 candidate가 현재 store에 존재하고 그 candidate의 `parent_id`를
  `store.parent(...)`로 해석할 수 있을 때만 발급한다. `bridge_table`과 `bridge_figure`는 각각
  `store.bridge(candidate_id, kinds=("table_row_group",))`와
  `store.bridge(candidate_id, kinds=("figure_object",))`가 실제 연결 객체를 반환할 때만 발급한다.
  caller는 evidence kind, parent, support lineage를 제공하거나 덮어쓸 수 없다. bridge/parent target은
  state의 candidate ID와 sealed store에서만 파생한다.
- deterministic E1 allowed order는 plan/coverage가 봉인한 canonical obligation 순서를 먼저 적용하고,
  각 obligation 안에서 `retrieve_dense`, `retrieve_lexical`, `expand_parent`, `bridge_table`,
  `bridge_figure`, `rerank`, `verify_slot` 순서를 사용한다. expand/bridge candidate는 `evidence_id`
  오름차순으로 둔다. open 상태에는 이 순서의 비종료 action 뒤에 target 없는 `abstain`을 정확히
  한 번 붙이고, decision은 allowed tuple의 첫 action을 선택한다. `fuse`는 이 순서에 포함되지 않는다.
- gate는 다음 공식으로만 파생한다. compare의 `normal_stop_allowed`와 `abstain_required`는 sealed
  `CompareCoverage`의 동명 값과 정확히 같아야 한다. follow-up의 `normal_stop_allowed`는
  `progress.sufficient`이고 primary/fallback/progress/outcome 전체 authority chain이 유효할 때만 true다.
  EH2.5는 confirmed absence를 만들지 않으므로 그 밖의 follow-up 부족 상태는 provisional/open으로
  남고 `abstain_required=false`다. `normal_stop_allowed=true`이면 allowed tuple은 정확히
  `(stop,)`, `abstain_required=true`이면 정확히 `(abstain,)`이다. 두 값은 동시에 true일 수 없다.
- deterministic E1 decision은 위 exact gate/order를 사용하고 state SHA,
  전체 allowed-action SHA, selected action, policy ID/SHA, execution identity, ordinal과 이전 decision SHA를
  `ActionDecisionTrace`에 묶는다. previous chain은 같은
  execution identity·정확한 ordinal+1·nonterminal 이전 decision만 허용한다.
- persisted state/decision replay는 동일한 bound/source receipts/store/registry/policy로 재구성한 canonical
  JSON과 정확히 같아야 한다. evaluator/gold/qrels/expected answer는 모든 factory 인자와 직렬화에서 금지한다.

### 16.10 E0/E1 bounded controller — EH2.6

- EH2.6은 EH2.3/EH2.4 receipt를 변경하지 않는 audit root로 사용하고, 모든 실행 변화는
  factory-issued `ActionEffectReceipt`와 `HarnessTransitionReceipt` chain으로만 만든다. EH2.5의
  `ActionDecisionTrace`는 한 상태의 deterministic preview/reference이며 다단계 controller chain으로
  재해석하지 않는다. 특히 EH2.3 `PrimaryEvidenceProgress`는 caller가 candidate ID, 허용된 verifier ID,
  임의 config hash를 공급하는 compatibility receipt이므로 E1 terminal semantic authority가 아니다.
  EH2.5 follow-up state가 verified/stop으로 보이더라도 E1 시작 상태로 직접 사용할 수 없다. 실제
  `ControllerDecisionReceipt`는 `HarnessState + ExecutionLedger`에서 allowed
  action을 다시 계산하고 직전 `transition_sha256`에 연결한다.
- EH2.6 runtime authority는 무결성 경계이지 Python sandbox가 아니다. 공개 입력 위조, 동일 payload clone,
  발급 후 object drift, mutable public dependency alias와 단일 private registry/pin drift는 호출 전에
  fail-closed한다. 반면 동일 프로세스에서 여러 private module registry 또는 closure cell을 함께 고쳐
  구현과 검증 root를 동시에 교체할 수 있는 arbitrary-code 실행은 구현 자체 패치와 같으므로 비범위다.
  그 위협은 배포 process isolation과 repository artifact 검증이 담당하며, runtime DTO 회귀의 P1로
  무한 확장하지 않는다.
- E1은 `fact`, `compare`, `follow_up`을 지원한다. `BoundFact`는 동일 request를 동일 planner로 replay해
  fact plan/catalog/config/store identity를 봉인하고 `$answer_support` 하나가 unsearched인 초기 state를
  만든다. restricted scope의 모든 doc ID가 sealed catalog universe와 exact live `EvidenceStore` 양쪽에
  존재하고 store canonical payload가 bundle SHA와 일치해야 한다. live store 검증은 parent/evidence ID
  index와 derived child tuple의 exact type·key·object identity까지 canonical reconstruction과 대조한다. unknown/stale
  doc, empty/unresolved scope는
  검색 전에 fail-closed한다. compare/follow-up은 기존 bound source를 재사용한다.
  analytics/list/table-visual 실행과 generation은 EH2.6 범위가 아니다.
- fact binding은 constructor-issued `RuntimeRequest`의 exact frozen-tree identity/type을 직렬화 전에 확인한다.
  planner/catalog/registry/planning/trace/store도 untrusted method·hash·비교 호출 전에 exact type/identity를
  선검증하며, clone 또는 `object.__setattr__` 기반 drift는 검색과 planner replay 전에 거부한다.
- `HarnessExecutionConfig`는 `e0_once|e1_bounded`, policy ID, `max_nonterminal_actions`, obligation별
  max rounds, max no-progress, `max_context_targets_per_obligation`, 정수 `timeout_ms`와 `rrf_k=60`을
  hash로 봉인한다. terminal stop/abstain
  receipt는 action budget을 소비하지 않고 항상 마지막에 한 번 발급할 수 있다. v1은 distinct-query rewrite 계약이
  없으므로 obligation별 retrieval round는 정확히 1회다. bool-as-int, NaN/Inf, unknown field와 발급 후
  drift를 거부한다. production clock은 내부 `monotonic_ns`, synthetic clock 주입은 test runtime factory만 허용한다.
  EH2.6.b2 구현은 config/runtime을 constructor가 아닌 owner factory만 발급하며, production에서는
  loader-attested KURE/Kiwi/hybrid와 내부 clock만 허용한다. verifier/reranker는 승인 구현이 생기기 전까지
  unavailable로 고정하고 synthetic adapter는 test factory에만 둔다. bind/validate/to_dict와 evidence/dense/
  lexical/fusion preflight는 callable code/default/global, class descriptor, registry/entry identity를 traversal보다
  먼저 검증하여 query·retriever·tokenizer·model·verifier·reranker·clock 호출 0회를 보장한다.
- compare/fact retrieval은 exact production hybrid binding을 재검증하되 실행을 dense, lexical, pure RRF
  세 단계로 분리한다. `LaneSearchReceipt`는 lane, execution/obligation/round, source에서 재구성한 query
  hash, scope, candidate limit, store/runtime binding, safe projected result와 실제 호출 여부를 봉인한다.
  같은 round의 두 lane receipt가 query/scope/store/runtime identity까지 같을 때만 `FusionReceipt`를
  만들고 `fuse_rrf`를 실행한다. 기존 `HybridChildRetriever.search()` 한 번을 `retrieve_dense`로 기록하지
  않는다. `HarnessRuntimeBinding`은 exact hybrid/dense/lexical object identity와 class, method override 부재,
  loader attestation/config hash를 보존한다. query를 만들거나 외부 코드로 보내기 전에 전부 재검증하고,
  approved lane class method를 직접 호출한다. follow-up은 EH2.3 primary/허용 fallback에서 검색이 이미
  종결됐으므로 추가 retriever 호출은 0회다.
- EH2.6.b3 구현은 `BoundFact`/`BoundCompare` owner가 재구성한 private query·scope에서만
  `RetrievalObligation`을 발급한다. 공개 obligation/receipt에는 raw query와 qrels를 넣지 않고 query hash,
  source receipt, exact store/config/runtime identity만 남긴다. 동일 source를 재발급하면 동일 obligation과
  ledger를 돌려주며, 요청 graph가 사라지면 issuance/obligation/ledger/receipt authority도 weak cleanup된다.
  ledger는 전체 obligation 순서에 대해 각 dense→lexical을 한 번씩만 소비하고 hash/revision chain을
  전진시킨다. lane close가 발급한 일회성 permit과 closure-sealed executor gate는 issued public executor의
  exact code와 exact module-global namespace에서 온 frame만 허용한다. 따라서 copied-globals function clone을
  포함해 실제 public executor를 거치지 않은 direct claim/close·receipt mint와 permit 재사용을 거부한다.
  provider error와 호출 전/후
  contract error는 typed boundary로 분리하며 `call_performed`를 실제 경계와 결합한다. dense provider
  failure 뒤에는 untouched lexical을 정확히 한 번만 진단 실행할 수 있고 그 뒤 종료한다.
  copied-globals function clone도 ledger mutation을 할 수 없도록 executor의 exact code와 exact
  module-global namespace를 함께 검사한다.
- EH2.6.b4 구현은 평가 checkpoint의 고정 순서에서 visual lane 자리를 보존해 `FusionReceipt.stage_ordinal=4`로
  둔다. exact same obligation/round/query/scope/store/config/runtime의 정상 dense·lexical receipt만 RRF 입력이
  되며, 둘 중 error receipt가 있거나 역할·identity가 섞이면 fusion 호출 전에 거부한다. fusion 결과는 lane
  candidate union, exact RRF score/order, store text evidence, scope, dense-only/lexical-only/both partition을 다시
  검증한다. 공개 receipt에는 safe evidence ID·stable anchor·partition/hash만 남기고 `fuse_rrf`가 중첩한 raw
  lane trace·query·qrels는 보존하지 않는다.
- fusion 소비는 b3 lane ledger를 소급 변경하지 않고 exact ledger/obligation/lane-receipt pair에 결합된 별도
  closure-private lock/permit로 한 번만 허용한다. 현재 obligation의 두 lane 뒤, 이전 obligation fusion이 모두
  완료되고 다음 obligation lane이 아직 시작되지 않은 시점만 claim할 수 있다. claim·close는 issued fusion
  executor의 exact code와 exact module-global namespace를 모두 요구하며 receipt 수명과 무관하게 ledger가
  살아 있는 동안 replay를 거부하고 request graph 소멸 시 weak cleanup한다. 이 보장은 receipt 수명에 기대지
  않는다. ledger 수명의 완료 이력은 현재 진행 상태와 동일 immutable tuple identity를 공유하는 별도
  closure-private history에 함께 기록하며, 어느 한쪽만 교체·삭제되면 public fusion 전에 authority drift로
  닫힌다. executor와 validator의 closure cell 값도 발급 시 identity로 고정해 cell 교체를 dependency drift로
  거부한다.
- E0 public entry는 `mode=e0_once`와 complete canonical obligation tuple을 전 obligation에 대해 첫 provider 호출
  전에 검증하고 전체 실행을 원자적으로 claim한다. 각 obligation은 dense→lexical→fusion 뒤에만 다음
  obligation으로 이동한다. E0 실행 중 child lane/fusion은 exact E0 executor caller만 허용해 concurrent 외부
  소비를 차단한다. E0는 child executor·validator를 진입 시 local identity로 고정하고, 각 provider 반환 뒤
  dependency gate와 exact child receipt type/public validator를 다시 통과한 결과만 집계한다. provider가 실행
  중 global child executor를 교체하거나 다음 obligation lane을 이전 fusion보다 먼저 시작하려 하면 receipt를
  발급하지 않고 fail-closed한다. dense provider error는 untouched lexical 진단을 한 번 보존하되 fusion하지 않고 error로
  닫으며, contract/fusion error 뒤 untouched obligation은 `error/execution_terminated_before_obligation`으로
  명시한다. `unavailable`은 스키마·집계에는 남지만 현재 필수 dense/lexical/RRF runtime에서는 합성하지 않는다.
  aggregate에는 child receipt SHA만 선형으로 참조하며 state/decision/action/transition, semantic READY,
  evaluator/gold/qrels 입력을 두지 않는다.
- EH2.6.b5 focused gate는 b3/b4 production 경계를 넓히지 않고 네 실행 의미를 함께 고정한다. dense가 정상
  empty이고 lexical이 후보를 찾으면 lexical-only partition으로 fusion되어 retrieval rescue가 된다. 두 lane이
  모두 empty인 fact E0는 bounded retrieval 완료로 닫히지만 semantic READY/answerable/verified 상태를 만들지
  않는다. 호출 전 contract rejection은 provider side-effect, lexical, fusion을 모두 0으로 유지한다. dense
  provider error 뒤의 lexical 한 번은 진단 receipt일 뿐 fusion rescue로 승격하지 않는다.
- `LaneSearchReceipt`, `FusionReceipt`, 이후 rerank/context receipt는 `evaluation-contract.md` §9.1의
  stage checkpoint를 구성할 수 있는 safe evidence ID·stable anchor·owner receipt/config identity를
  보존한다. 평가 case나 qrels를 인자로 받지 않으며, evaluator는 실행 종료 뒤 private qrels를 별도로
  join한다. text lane anchor는 evidence locator hash와 별도로 `doc_id + source_block_id` 기반의
  chunk-invariant `source_block_anchor_sha256`를 보존한다. evaluator-only resolver만 private source-block
  snapshot의 exact owner와 `source_locator` SHA를 대조해 canonical qrel locator hash로 해석하고
  `AnchorResolutionReceipt`로 봉인한다. pre/post 평가를 위해 raw lane 결과를 fusion 결과나 final
  context로 덮어쓰지 않는다.
- action order는 obligation 순서 안에서 `retrieve_dense`, `retrieve_lexical`, `fuse`, eligible parent/table/
  figure context, `rerank`, `verify_slot` 순이다. candidate target은 evidence ID 오름차순이다. ledger에서
  성공·empty·unavailable로 이미 종결된 action은 다시 선택하지 않는다. unavailable capability는 같은
  target에 정확히 한 번 기록한 뒤 다음 action으로 진행하며, semantic verifier 부재는 absence가 아니라
  capability-gap abstain이다. EH2.6은 EH2.5 public action constructor를 넓히지 않고 동일한 닫힌
  kind/target shape의 별도 factory-issued `ControllerAction`을 state+ledger에서만 발급한다.
- context action target은 fused/source 결과에서 고정한 `retrieval_seed_candidate_ids` 중
  `max_context_targets_per_obligation` 이내로 제한한다. quota는 execution config의 양의 정수이며 plan의
  per-obligation final/rerank budget보다 클 수 없다. bridge로 추가된 evidence는 verifier input에는 들어가지만
  다시 expand/bridge target이 될 수 없어 graph 순환과 action 폭증을 막는다.
- fact/compare에서 dense·lexical·fusion이 모두 종결됐는데 후보가 없는 provisional obligation과,
  follow-up 승인 경로가 종결됐으나 후보가 없는 provisional obligation에는 controller 전용
  `verify_slot` exhaustion check를 허용한다. 이 검사는 verifier/provider를 호출하지 않고 exact ledger에서
  absence 발급 조건만 판정한다. EH2.4에서 이미 one-shot hybrid search가 들어간 coverage는 독립 lane
  receipt로 소급 포장하지 않는다. E1 compare start는 모든 slot이 `unsearched`인 coverage만 허용하고,
  pre-searched candidate/missing seed는 fail-closed한다.
- lane을 실제 시도한 모든 outcome(`applied`, `empty`, `unavailable`, `provider_error`, `contract_error`,
  `deadline_discarded`)은 해당 obligation/round/lane을 정확히 한 번 소비하며 v1은 자동 retry하지 않는다.
  deadline과 contract-integrity error는 즉시 종료한다. 일반 dense provider error는 untouched lexical lane을
  정확히 한 번 실행할 수 있지만, 두 정상 lane receipt가 없으므로 fusion은 허용하지 않고 lexical 결과를
  진단 receipt로만 보존한 뒤 sanitized error로 종료한다. terminal 뒤나 이미 소비한 lane에는 재호출하지 않는다.
- `SemanticVerificationReceipt`는 verifier에게 실제 공급된 evidence ID와 `supported`, `unsupported`,
  `contradicted`, `unavailable` disposition을 봉인한다. verified/contradicted ID는 supplied candidate/bridge evidence의
  subset이어야 한다. compare는 field, value type, canonical value와 value별 support가 추가로 필요하며,
  서로 다른 canonical value가 각각 typed support를 가질 때만 contradiction을 만든다. EH2.4의
  `field_relevance_only`, raw boolean 또는 caller ID map은 terminal semantic 권한이 아니다.
- c2의 semantic target은 caller가 query·field·evidence ID를 조립하는 값 객체가 아니다. fact/compare는 exact
  `RetrievalObligation`과 same-round dense/lexical/`FusionReceipt`에서, follow-up은 exact `BoundFollowup`과 finalized
  outcome을 c1 projection으로 다시 검증한 뒤 실제 obligation key에서 factory가 유도한다. public factory는
  source receipt, store, config, runtime을 모두 exact identity로 받되 query·candidate/bridge/context ID·disposition·
  value·gold/qrels/evaluator 입력을 받지 않는다. c2 최초 구현에서 bridge/context 역할은 예약하되 비어 있고,
  c3의 owner-issued context/rerank effect만 이 공급 집합을 넓힐 수 있다. 후보가 비면 verifier를 호출하지 않고
  c3 bounded exhaustion 경로로 넘긴다.
- factory-only `SemanticVerificationObligation`의 공개 payload는 source kind, obligation key, optional source-derived field,
  source binding/receipt와 optional c1 state SHA, query SHA, store/config/runtime SHA, ordered candidate/bridge/context/
  supplied ID와 stable anchor, obligation SHA만 담는다. raw query, evidence text/object, verifier object는 private
  authority에만 둔다. supplied order는 candidate→bridge→context first-seen이며 승격 가능한 ID는 candidate+bridge뿐이다.
  compare field는 key 문자열을 재해석하지 않고 exact bound projection ordinal에서 유도한다.
- verifier adapter는 factory-only private request 한 개만 받는 exact declared class method `verify(self, request)`다.
  request는 source kind, obligation key, optional target doc/field, raw query와 contiguous index가 붙은 ordered
  `(role, Evidence)`를 보유하지만 serialize나 public 반환을 제공하지 않는다. raw result는 정확히
  `schema_version`, `disposition`, `support_indexes`, `values` 키를 가진 dict이고 value도 정확히 `value_type`,
  `canonical_value`, `support_indexes`만 가진다. disposition은 `supported|unsupported|contradicted`만 허용한다.
  adapter request는 ID 없는 content projection만 받고 결과에도 ID를 되돌려줄 수 없으며 executor만 index를
  owner-issued ID로 바꾼다. bare bool/ID map,
  extra key, scalar·비유한 수·중복·범위 밖 index와 provider 본문은 거부한다. unavailable은 adapter 출력이 아니라
  exact runtime capability에서만 zero-call로 유도한다.
- typed value는 `text|krw_amount|kst_datetime|duration|boolean|number`로 닫고 canonical string만 저장한다. text는
  NFC+trim+whitespace collapse, 금액은 정규 10진 정수 문자열, datetime은 ISO-8601 `+09:00`, duration은 ISO-8601,
  boolean은 `true|false`, number는 finite canonical decimal이다. 기본 field type은 budget=`krw_amount`,
  duration=`duration`, deadline=`kst_datetime`, joint_contract/subcontract=`boolean`, 나머지=`text`로 하나만 허용한다.
  `$answer_support`처럼 field 없는 supported/contradicted는 values가 비고 support index만 가진다. field 있는 supported는
  정확히 한 typed value와 nonempty support를 요구하고 verified ID는 그 support union과 같아야 한다. field 있는
  contradicted는 같은 field-approved type의 서로 다른 canonical value 둘 이상이 pairwise-disjoint nonempty support를
  가지며 contradicted ID가 그 union과 정확히 같을 때만 성립한다. unsupported는 ID/value가 모두 비어야 한다.
- exact verifier protocol과 모든 source/store/config/runtime dependency를 claim·호출 전에 검증하며 ABI/identity
  거부와 production unavailable은 provider 0회다. 이 preflight 거부는 실행 attempt로 소비하지 않는다. available
  verifier는 exact class method를 한 번만 직접 호출하고, 반환 직후 runtime, source, store, prerequisite receipt를
  parsing/mint보다 먼저 재검증한다. provider 예외, 호출 뒤 contract/malformed 결과와 post-call drift는
  sanitized fixed error로 끝나고 local claim을 소비해 같은 live semantic obligation을 다시 호출할 수 없다. issuance와
  실행 완료 history는 receipt GC와 독립적이고 동시 호출 winner는 하나뿐이다. c2 receipt는 상태를 직접 바꾸지 않으며
  전체 action budget·deadline·terminal order는 d 단계, effect/absence 투영은 c3 책임이다.
- `ActionEffectReceipt`는 execution/step/decision/action/before-state, sanitized outcome, typed source receipt,
  evidence projection, parent/bridge context, optional absence SHA를 봉인한다. outcome은 `applied`, `empty`,
  `unsupported`, `unavailable`, `deadline_discarded`, `provider_error`, `contract_error`, `terminal`로 닫는다. provider 예외
  본문·경로·키는 저장하지 않는다. parent expansion은 verifier context일 뿐 candidate/citation evidence로
  승격하지 않고, bridge는 sealed store가 반환한 실제 linked evidence만 후보에 추가한다. reranker는 기존
  candidate의 subset/permutation만 반환할 수 있다.
- `AbsenceConfirmationReceipt`는 모든 허용 retrieval/verification 경로가 bounded하게 종결된 한 obligation에
  한해 `bounded_no_candidate|bounded_no_verified_support|followup_approved_paths_exhausted`를 기록한다.
  이는 해당 query/scope/budget에서 support를 확보하지 못했다는 뜻이며 corpus에 사실이 없다는 주장이 아니다.
  timeout, provider error, unavailable capability, unresolved scope만으로는 발급할 수 없다.
- fact 또는 follow-up plan에 metadata predicate가 있으면 EH3.1 filtered-scope receipt 전에는 not-ready로
  닫는다. syntactically supported predicate도 무시한 채 unfiltered/citation-only retrieval로 실행하지 않는다.
  missing/partial/full abstention은
  controller `HarnessRunResult`에서 파생하며, contradiction 전용인 `Progress.abstain_required`를 재사용하지 않는다.
- E1 follow-up 전용 초기 projection은 EH2.3 primary/fallback의 모든 후보를 audit lineage와 함께
  `$answer_support` candidate로 낮춘다. 각 실제 required slot에는 그 slot의 `doc_id`와 같은 후보만
  순서 보존 dedupe해 candidate로 넣고, 없을 때만 provisional missing으로 둔다. 기존 progress가 주장한
  verified ID도 candidate 이상으로 승격하지 않으며 새 runtime-bound `SemanticVerificationReceipt`만 verified를
  만든다. `$answer_support`와 각 slot은 별도 obligation이고 한 transition은 하나만 바꾼다.
- reducer는 exact before state와 effect로 exact after state를 하나만 결정한다. lane 실행, parent context,
  terminal stop/abstain은 exact same state object를 after로 사용한다. 상태가 실제 바뀌는 effect만 새 state를
  발급하고 그 source receipt가 effect SHA를 가리키며, 한 nonterminal transition은 하나의 obligation만
  바꾼다. verified/confirmed-missing/contradicted terminal obligation은 다시 열지 않는다.
  `HarnessExecution` aggregate는 exact state, ledger, last transition identity를 함께 봉인한다.
  `HarnessTransitionReceipt`는 before/after state SHA, decision/effect, 이전 transition과 semantic progress
  fingerprint를 hash-chain한다. fingerprint는 provenance/source SHA, ordinal, 시간, counter를 제외하고
  obligation별 stage·candidate/verified ID와 verifier-context ID를 포함한다. dense/lexical prerequisite 완료는
  operational progress로 기록하되 no-progress streak를 늘리지 않는다. fuse/verify checkpoint에서 semantic
  state와 verifier context가 모두 그대로일 때만 streak를 1 올린다.
- 종료 우선순위는 complete stop, contradiction abstain, deadline, action budget, no-progress, round cap에서
  발급 가능한 bounded absence, capability unavailable, sanitized contract/provider error 순이다. provider
  호출 직전·직후 deadline을 검사하고, post-call deadline 판정은 raw 결과 parsing/projection보다 먼저 한다.
  늦게 돌아온 raw payload는 완전히 폐기하고 `deadline_discarded`만 남겨 state에 승격하지
  않는다. adapter별 강제 취소 timeout은 후속 composition 책임이다. terminal 뒤에는 decision/provider
  호출이 0회여야 한다.
- 최종 상태는 모든 obligation verified일 때만 `ready`다. verified+confirmed missing은
  `partial_abstained`, 전부 confirmed missing 또는 contradiction은 `abstained`다. open obligation을 남긴
  timeout/budget/no-progress/capability 종료는 verified가 일부 있어도 종료 reason을 보존하며 정상 stop으로
  바꾸지 않는다.
- E0는 state/policy transition 없이 fact/compare의 bound query별 dense+lexical+RRF를 정확히 한 번 수행하는
  control receipt다. follow-up은 EH2.3 outcome을 재사용하며 재검색하지 않는다. E0 결과는
  obligation별 `retrieved|empty|unavailable|error`를 순서대로 보존한다. aggregate precedence는 error,
  unavailable, all-empty, otherwise retrieved이며 nonempty/empty/unavailable/error obligation key와
  `execution_complete`를 함께 기록해 혼합 compare 결과를 숨기지 않는다. `execution_complete`는 모든
  obligation이 retrieved/empty로 bounded 종결됐을 때만 true다. E0는 semantic READY 또는 품질 향상을
  주장하지 않는다. E1은 같은 source authority 위에 ledger-aware decision/effect/reducer loop를 추가한다.
  E2 policy/학습/query rewrite는 비범위다.
- persisted execution replay는 provider/retriever/verifier/reranker/clock을 다시 호출하지 않는다. exact source,
  store, config, factory-issued effects로 state를 순서대로 reduce하고 strict canonical JSON을 대조한다.
  이 authoritative replay는 같은 process의 exact live effect identity를 요구한다. persisted raw JSON-only
  replay는 구조/hash audit 결과일 뿐 provider 실행 권한을 다시 발급하지 않으며 executable로 승격하지 않는다.
  ledger/decision/transition/run payload는 ordered receipt SHA와 bounded summary만 보존하고 이전 payload 전체를
  재중첩하지 않는다. top-level receipt bundle이 각 receipt payload를 정확히 한 번 포함해 action 수에 대해
  선형 크기를 유지한다.
  runtime API와 serialization에는 evaluator/gold/qrels/expected/reference answer를 받을 필드가 없어야 한다.
- `HarnessRuntimeBinding`은 semantic verifier와 optional reranker도 factory에서 exact identity/class,
  capability, implementation/config hash, method override 부재에 결합한다. production은 승인된 class method를,
  synthetic은 명시적 test factory만 호출하며 receipt는 executor만 발급한다. caller가 disposition이나
  evidence ID를 public execution 인자로 넘겨 semantic/rerank receipt를 mint할 수 없다. 승인된 production
  verifier가 없으면 production E1은 정직하게 capability-gap으로 종료한다. optional bridge/reranker unavailable은
  한 번 skip할 수 있지만 required semantic verifier unavailable은 종료한다.
- 구현 파일 경계는 다음으로 고정한다. controller는 다른 모듈의 underscore API나 factory token을 import하지
  않는다. `fact_binding.py`가 `bind_fact`를, 기존 `compare_slots.py`가 public sealed compare
  `RetrievalObligation` projection을, `harness_state.py`가 fact initial state와 E1 follow-up safe projection을
  소유한다.
  `retrieval/fusion.py`는 exact runtime-bound independent lane execution/fusion public boundary를 제공한다.
  `execution_contracts.py`는 config/runtime/obligation/ledger/action/receipt aggregate와 exact semantic verifier 호출을,
  `action_effects.py`는 typed semantic schema·순수 정규화 및 verifier/reranker/context effect를,
  `state_reducer.py`는 state-changing factory와
  reducer를, `controller.py`는 start/decide/step/run/replay orchestration만 소유한다.
