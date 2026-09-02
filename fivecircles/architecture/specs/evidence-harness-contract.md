# Evidence-Harness Contract v1
2026-09-02 · IMPLEMENTATION_CONTRACT · opt-in, baseline not promoted

## 1. 목적 / 경계
작은 팀·단일 실행환경에 맞춰 Modular Monolith 내부 모듈로 구현한다.
Evidence는 존재/출처, retrieval은 후보·순위, harness는 다음 행동/누락 상태,
generator는 근거에 따른 답변, evaluation은 실행 밖 판정을 소유한다.
MSA는 독립 scaling이 실측되기 전 도입하지 않는다.

## 2. 모듈 / public API
| 경로 | 소유 데이터 | 공개 API | 금지 |
| --- | --- | --- | --- |
| src/midprojectrag/evidence/ | immutable evidence와 parent/object 연결 | Evidence, EvidenceStore, build_from_chunks | gold 읽기, provider 호출 |
| src/midprojectrag/retrieval/ | candidates, lane ranks, index adapters | Candidate, Retriever, Reranker, HybridRetriever, select_context | semantic 판정, gold |
| src/midprojectrag/orchestration/ | query plan, slots, state, actions, trace | Harness, QueryPlan, Slot, Verification, HarnessConfig | corpus/parser/gold 수정 |
| 기존 answering/stacks | 답변 호출/비용/전송 정책 | Generator port + 새 adapter | evidence 없는 citation |
| evaluation 및 offline exporter | qrels, diagnostic, 학습 행렬 | 런타임 밖 함수 | runtime plan에 gold 주입 |

의존: orchestration → retrieval → evidence; orchestration → answering 공개 adapter.
역방향 import와 모듈 private 내부 import 금지. 기존 파일은 유지, public __init__에서 export.
새 파일은 해당 데이터 소유 모듈 아래 두고 범용 utils로 이동하지 않는다.

## 3. Evidence 계약
frozen dataclass Evidence:
- evidence_id: str; stable 'ev_' + 24 hex (identity includes provenance, parent, kind, content)
- doc_id: str; page: int | None; kind: 'page' | 'text' | 'table' | 'figure'
- text: str; source_block_ids: tuple[str,...]; parent_id: str | None
- object_id: str | None; bbox: tuple[float,float,float,float] | None; crop_ref: str | None
- content_sha256: canonical content digest (derived, not mutable)
- section_path: tuple[str,...] (default empty)
- provenance extensions: `source_chunk_ids` tuple, `evidence_type` (`ocr`/`layout`/`caption` when known),
  `support_refs` tuple, and inclusive `row_range` tuple when the parser supplied exact values;
  absent values remain empty/`None` and are never inferred.
EvidenceStore(records): rejects duplicate IDs, invalid parent chains/cycles, cross-doc/page links,
non-finite/reversed bbox, object children without object_id, missing source refs.
get(id) raises ValueError for unknown; all() returns tuple; children(id) tuple;
bridge(page_id, kind=None) returns explicit linked table/figure descendants; no inferred bbox.
build_from_chunks(chunks, *, max_chars=1600) -> EvidenceStore:
page parents from validated page chunks, paragraph children with exact source provenance;
existing table/visual chunks connect only via explicit doc/page/source mapping.
Unlocatable auxiliary objects must fail with a reason; never invent page or parent.
Records output canonical dictionaries via to_dict()/from_dict(). Raw/private data never committed.

## 4. Retrieval契約
Candidate(evidence_id: str, score: float, lane: str, rank: int)
Retriever.search(query: str, *, limit: int, allowed_doc_ids: frozenset[str] | None)
  -> tuple[Candidate,...]
Reranker.rerank(query: str, candidates: tuple[Candidate,...]) -> tuple[Candidate,...]
- score finite; rank positive; unknown IDs/out-of-scope fail closed.
- HybridRetriever(store, lanes: Mapping[str,Retriever], rrf_k=60) fuses ranks; duplicate per-lane contributes once;
stable evidence_id tie-break; scope reapplied before ranking even for buggy adapters.
- BM25Retriever uses local tokenized text, never acts as answer judge.
- DenseRetriever accepts aligned vectors and query embedder callback, no implicit model download.
- IdentityReranker is explicitly marked no-op baseline; not called learned reranker.
- select_context(store, candidates, *, max_chars, max_items, per_doc_limit,
  required_ids=()) returns tuple[Evidence,...]. Mandatory verified refs prioritized.
  If mandatory refs cannot fit, raise context_budget_exceeded; never claim full coverage.
- request scope preserved in every action and parent expansion.

## 5. Runtime DTO / state
Slot(key: str, query: str, doc_id: str | None = None, kind: str | None = None)
QueryPlan(query: str, slots: tuple[Slot,...], query_type='fact', history=(),
          allowed_doc_ids: frozenset[str] | None = None)
query_type: fact/compare/list/visual/followup. Slots come ONLY from current query/history;
doc_ids are user-scoped or query-planned, not golden required docs.
List completeness must have an explicit enumeration-complete signal; top-k saturation alone is not proof.

Verification(evidence_ids: tuple[str,...], contradiction: bool=False)
Verifier.verify(slot: Slot, evidence: tuple[Evidence,...]) -> Verification.
Semantic relevance/claim support comes from LLM or explicit injected test doubles; regex/lexical cannot grant support.
Returned IDs must occur in supplied evidence, satisfy slot doc/kind scope, and exist in store.

HarnessConfig: positive max_actions, max_rounds, max_candidates, max_context_chars,
max_context_items, max_per_doc, timeout_seconds. Defaults bounded; optional modules declare availability.
State: immutable snapshot per decision: slot→verified IDs, missing slots, contradictions,
candidate IDs, rounds/actions spent, selected context, terminal reason.
Typed actions: search, bridge, verify, stop, abstain. Unknown/malformed/premature stop rejected.
A policy may choose next allowed action; controller validates action and enforces budgets.
Experience is disabled by default; cannot store benchmark question answers.

Transitions:
NEW → SEARCH → VERIFY → (missing? targeted SEARCH/BRIDGE → VERIFY) → PACK → READY
Any phase → ABSTAINED (unsupported/incomplete/exhaustion/contradiction)
Any phase → ERROR (provider/contract/invalid actions)
READY means verified planned slots all retained; not official correctness/accepted judgment.
Until a verified visual reader provider is injected, a pixel-dependent `visual` plan is a
`capability_gap` even if OCR/caption text exists; descriptive captions cannot substitute for pixels.
No returned evidence, contradiction, exhausted budget, unknown action cannot become READY.
Budget checked before dispatch including verify/generate; adapters impose per-call timeout.
No automatic uncontrolled retry. Infinite/repeated no-progress loops end explicitly.

## 6. Generation / compatibility
Opt-in wrapper builds escaped evidence prompt including explicit history and source IDs.
Reuses budgeted Generator port; dynamic citation cap <= existing request contract maximum.
Only packed evidence can be cited; if required planned support cannot fit citation/context budget,
return incomplete/abstained rather than silently relaxing bounds.
Text-only generator receives verified structured text/OCR/caption; crop path alone is NOT visible evidence.
Pixel-dependent question without a visual reader returns capability_gap.
Ollama actual Mac model name must never be relabeled Qwen3-8B.
A no-op/dummy provider is clearly synthetic and cannot generate official receipts.

## 7. Trace / metrics / privacy
Versioned sidecar: plan, config hash, evidence artifact hash, policy ID, selected actions,
observations, candidate ranks per lane, verifier decision, pre/post context IDs, prompt/response usage.
private JSON with mode 0600; stdout only safe count/status/hash. Raw trace path must be under private output.
Offline diagnostic = intersection of frozen qrels with evidence IDs at each stage.
qrels with missing labels return not_available; runtime never imports qrels/evaluation cases.
No online answer judge in code. Fixed GPT-5.6 semantic judge evaluates persisted candidate transcript separately.

## 8. Acceptance / capability gate
Test: missing compare slot triggers targeted doc expansion/bridge; verified evidence retained;
list incomplete cannot report complete; unsafe citation/unknown ID rejected; all actions bounded;
history present; no golden fields; stable source hashes; baseline unaffected.
New checkpoints/rerankers/KoVRE/visual reader/SFT/RL are capability gaps until paths+hash+hardware verified.
Model-selection experiments assumed complete in plan; unsupported engines cannot silently fall back.
Promotion requires approved gold, sealed holdout, same judge/config, measured resources and rollback.
