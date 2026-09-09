# Visual Retrieval Feature Contract

Status: `LOCAL_OCR_SMOKE_VERIFIED / R2_R5_GATES_OPEN / DEFAULT_RUNTIME_UNCHANGED`

Branch: `feature/visual-retrieval`

Related contract: `visual-image-recovery-and-understanding.md`

Readiness re-review (2026-09-03): the earlier plan-only approval is superseded. The OCR command
protocol and visual-index components exist, but the real PaddleOCR wrapper, usable model profile,
application flags, and visual UI integration are not complete. The default remains the refined98
page-only Streamlit bundle, with catalog display and separately supported optional table composition.
Section 14 controls the immediate OCR-text-only sequence. Sections 7.1 and the optional portions of
Section 9 are extension plans, not prerequisites for the local OCR slice. Plan review, implementation
verification and runtime activation are separate decisions. No runtime or model configuration was
changed by this review.

Final document re-review (2026-09-03): the primary and two independent reviewers approve the local
OCR runtime/wrapper development and bounded one-crop CPU smoke plan only. R1-R6 implementation,
API egress and runtime activation remain open. Evidence:
`fivecircles/work/review/review-visual-ocr-plan-followup-2026-09-03.md`.

Implementation follow-up (2026-09-03 one-shot): R1/R6 are now verified for the bounded local
OCR-only slice. The historical reviews above describe the pre-implementation state. Final smoke:
one crop, 27 text regions, 6.671 seconds, peak child RSS 4.65 GiB, cache reuse without inference,
zero private egress. Full current-tree tests 802/802 pass. This is not human-gold quality validation.
R2–R5, caption semantics, API approval and application activation remain open. Publication is blocked
by the pre-existing shared-team private-data safety finding; see `visual-ocr-local-flow.md`.

## 1. Goal

Add an independently gated visual-retrieval lane within the existing application for HWP/PDF figures and diagrams without
changing the current page/text or table baseline. The lane must return a page, bbox, occurrence,
crop hash, and the evidence used to retrieve the visual item.

The first implementation uses OCR/layout and nearby document context as text embeddings. A direct
image embedding is an optional second lane and must never replace the text-evidence lane for factual
questions.

## 2. Current Problem

- Visual occurrence inventory and deterministic crops exist, but visual semantic chunks are not in
  the active runtime.
- Existing `text-embedding-3-small` and `KURE-v1` are text embedding models; raw image bytes cannot
  be sent to them as embeddings.
- The current Streamlit bundle is page-only and the current visual baseline has no OCR/caption/image
  vectors.
- Table visual context remains a separate table lane and must not be duplicated by this feature.

## 3. In Scope

- OCR/layout evidence for eligible raster images and vector diagrams.
- Optional local diagram caption evidence with explicit support references.
- Independent visual text chunks and model-specific indexes for API and local runs.
- Retrieval fusion with the existing page/table index through a bounded visual quota.
- Page/bbox/crop citation and Streamlit preview behind a feature flag.
- Visual gold evaluation and a fail-closed activation gate.

## 4. Out of Scope

- Replacing the page/text or table baseline.
- Sending private crops or source documents to an external parser or VLM without approval.
- Treating an unlinked, ambiguous, quarantined, or withheld occurrence as searchable evidence.
- Concatenating vectors from different models or dimensions into one index.
- Enabling visual retrieval in the default runtime before gold, model, and artifact gates pass.

## 5. Assumptions

- Private source and derived artifacts remain outside Git under `resources/data_refined/private/`.
- Original source files remain immutable; refined artifacts and indexes are additive.
- `page_bbox_verified + crop_sha256` is the minimum retrieval eligibility contract.
- API and local embeddings are separate bundles even when they share the same chunk schema.
- The current table acceptance applies only to the table lane; it does not close the figure lane.

## 6. Existing System Touchpoints and Placement Contract

This feature is a cross-module lane in the existing modular monolith. Do not create a new top-level
`visual/` application folder.

| Responsibility | Canonical location | Owns | Must not own |
| --- | --- | --- | --- |
| Occurrence/crop recovery | `src/midprojectrag/ingest/visual_bundle.py`, `visual_corpus.py`, `visual_context.py` | source/page/bbox/crop provenance | embeddings or answer generation |
| OCR/caption normalization | `src/midprojectrag/ingest/visual_understanding.py` | OCR/layout/caption evidence schemas and fail-closed validation | vector search or UI state |
| Batch execution/cache | `src/midprojectrag/ingest/visual_understanding_runner.py` | pinned local inference and private artifacts | provider-specific RAG composition |
| Visual chunk/index | `src/midprojectrag/indexing/visual_fusion.py` | `visual-chunk-v1`, exact visual index, fusion policy | parser recovery or model downloads |
| Query orchestration | `src/midprojectrag/answering/pipeline.py` | visual context selection, citation and abstention | crop generation |
| Runtime composition | `src/midprojectrag/application/composition.py`, `config.py` | optional artifact loading and feature flag | OCR inference |
| Presentation | `apps/streamlit_app.py` | page/bbox/crop preview and status | retrieval scoring or evidence mutation |
| Schemas | `contracts/ocr-evidence-v1.schema.json`, `caption-evidence-v1.schema.json`, `visual-chunk-v1.schema.json` | serialized contracts | runtime policy |
| Private artifacts | `resources/data_refined/private/visual-v2-*` and model-specific index directories | immutable snapshots and hashes | source edits |

Other modules may import visual code only through the public exports of `ingest` and `indexing`.
They must not import private helper functions from `visual_understanding.py` or `visual_fusion.py`.

## 7. Proposed Data Flow

```text
eligible occurrence
  -> OCR/layout evidence
  -> optional caption evidence
  -> visual-chunk-v1 records
  -> API/local text index
  -> page/table/visual RRF
  -> bounded context
  -> page+bbox+crop citation
```

The optional direct image vector is a separate index keyed by the same `occurrence_id`; it is not
combined numerically with a text vector. Fusion happens at ranked-result level.

### 7.1 Deferred multi-lane execution candidate

The following cascade is a target proposal, not implemented behavior. It is deferred until the
OCR-text baseline in Section 14 is measured. OCR extraction and corpus embedding run offline;
query-time visual-text search reads an already-built index. These costs must not be conflated.

```text
Stage A: existing approved baseline; table/catalog query routing only when separately supported
Stage B (visual intent or weak A evidence): OCR/layout visual-text retrieval
Stage C (visual-text miss or explicit visual search): text-image dual-encoder retrieval
Stage D (top visual candidates only): optional VLM explanation/diagram relation extraction
```

- Stage A preserves the active bundle; it must not silently activate table or catalog query routing.
- Stage B is the first visual expansion because OCR/layout evidence is cheap to cite and audit.
- Stage C is optional and uses a **text-image dual encoder**. An image-only encoder is not a valid
  implementation for natural-language queries because its vector space cannot be queried by text.
- Stage D is bounded to at most two crops per query by default. Support-reference existence alone
  does not prove a VLM claim. Until separate claim-to-evidence validation exists, captions remain
  auxiliary and are excluded from factual answer context.
- A visual lane may also be explicitly requested by a UI toggle. Absent visual intent, a weak-evidence
  trigger, or the toggle, the request stays on the page/table baseline.
- The initial experiment uses explicit opt-in and parallel baseline/OCR-text lookup. Automatic
  "weak evidence" or "miss" routing requires a calibrated definition and router-recall evaluation;
  it is not a prerequisite for the cheap OCR-text lane.
- Image retrieval and VLM interpretation are independent extensions. A crop found by text search
  can be interpreted without an image index; retrieval misses and interpretation failures need
  different experiments.

## 8. Contracts

### 8.1 Occurrence contract

Required fields of the eligible source occurrence joined to each visual chunk:

```text
doc_id, occurrence_id, page, bbox, coordinate_space,
crop_sha256, crop_relpath, crop_media_type,
placement_status=page_bbox_verified,
retrieval_status=eligible
```

`quarantined`, `withheld`, `ambiguous`, `doc_only_unlinked`, and missing-crop records are excluded
from retrieval.

The chunk-to-occurrence join must verify `occurrence_id + crop_sha256` together with doc/page/bbox
and the pinned source artifact set. Coordinate space, crop path/media type and placement/retrieval
states belong to the occurrence sidecar. They are not new fields in `visual-chunk-v1`, whose schema
rejects additional properties. Resolve preview paths through the verified occurrence, not provider text.

### 8.2 Visual chunk contract

Use the existing `visual-chunk-v1` schema and `build_visual_chunks()` implementation.

The first slice produces OCR/layout chunks only; caption schema compatibility does not authorize
caption generation or factual use. R3 is satisfied for this slice by excluding every caption from
factual provider context and citations, regardless of a legacy `supported` label. Claim-verifier
implementation is a later VLM-extension gate, not a prerequisite for basic OCR development.

- `evidence_type`: `ocr`, `layout`, or `caption`
- `retrieval_role`: `visual_auxiliary`
- `citation`: must repeat page, bbox, occurrence ID, crop SHA, and evidence IDs
- `retrieval_weight`: OCR/layout may be primary; caption is capped at `0.35`
- `answer_support`: required for factual caption claims

The current `supported` field checks reference membership, not semantic entailment. Do not treat
that implementation as a factual-verification gate. OCR node labels alone do not establish arrow
direction, system connectivity, organizational hierarchy, or map geometry.

Do not add image vectors to the chunk JSON. Store them in a model-specific index artifact with the
same `occurrence_id` and `crop_sha256`.

### 8.3 Index contract

Each embedding model has its own index namespace:

```text
private/indexes/visual/api/text-embedding-3-small/<artifact-set>/
private/indexes/visual/local/KURE-v1/<artifact-set>/
private/indexes/visual/local/image/<encoder>/<artifact-set>/   # optional
```

Every index metadata record must include corpus hash, chunk hash, model identity, dimensions,
normalization, code/config hash, and source artifact-set ID. A dimension or identity mismatch fails
closed. Cross-model vector concatenation is forbidden.

The image namespace is valid only for an approved text-image dual encoder and must additionally
record `query_modality=text|image|both`, encoder checksum, and preprocessing identity. A pure
image encoder may be used only for an explicitly image-to-image query lane, not for the default
natural-language search path.

The image lane must encode query text with its own paired text encoder. The current
`VisualAugmentedIndex` shares one query vector with the base index and is suitable only for a
matching text-embedding space. Equal dimensions alone never authorize cross-model reuse.

### 8.4 Retrieval contract

- Query the page/table index and visual index independently.
- Fuse ranked results with the existing RRF policy.
- Treat the visual quota as a maximum, not a reserved minimum. Admit only relevant candidates;
  irrelevant visual hits must not displace base evidence merely to fill the quota.
- Group by `occurrence_id` before applying quotas; retain supporting evidence IDs and the strongest
  citation rather than spending multiple slots on the same crop's OCR/layout/caption chunks.
- Return visual citations with page, bbox, crop SHA, occurrence ID, and evidence type.
- Before visual hits enter answer context, freeze a model/chunk-specific admission policy using dev
  positives and nonvisual hard negatives, including positive-score irrelevant candidates. Rejecting
  negative cosine values alone is not a relevance policy. Record the score rule, threshold, quota and
  their model/chunk/config hashes; absent a valid policy, retain baseline-only answer context.

### 8.5 Runtime contract

Proposed `visual_retrieval_enabled` defaults to `false`; it is not yet an application config field.

The planned implementation must expose independent flags so a heavy lane cannot be enabled accidentally:
`visual_text_enabled`, `visual_image_enabled`, and `visual_vlm_enabled`. The first implementation
accepts only OCR-text opt-in; image/VLM true values must be rejected until their later implementations
are approved. All defaults remain false. OCR-text mode enforces a distinct-occurrence candidate cap
and bounded context; the deferred VLM extension additionally caps crops at two. Corpus OCR, image/text vectors and indexes are built offline;
query encoding and lookup occur online. Query-time model downloads are forbidden.

It can become `true` only when:

1. representative HWP 5-type and PDF 4-document gold is frozen;
2. OCR model weights/config are checksum-pinned;
3. visual chunks and indexes pass identity/reconciliation checks;
4. visual retrieval evaluation passes without text/table regression;
5. any required private egress and cost approval is present for the exact payload and provider;
   D-020 remains controlling until an explicit scoped decision authorizes visual-derived text egress.

If any artifact is missing or stale, the application stays page/table-only and records a sanitized
capability gap; it must not silently fall back to unverified image evidence.

## 9. Implementation Batches

These are implementation milestones, not automatic activation steps. Section 14 defines the current
phase ordering: a bounded technical smoke can precede gold freeze, but quality claims/scaling and
real opt-in answer use cannot. Interface code may be tested with fixtures before evaluation; real
visual answers/preview remain gated. API work is a candidate after D-020 egress resolution, not an
authorized consequence of this plan review.

### Batch 1: Branch, contract, and gold gate

**Goal:** Freeze placement, schema, and representative visual qrels.

**Expected files:** this contract, `contracts/*visual*`, visual gold fixtures under private root,
`fivecircles/architecture/todolist.md`.

**Done when:** branch exists, schema validators pass, and gold rows identify expected object/page/bbox.

### Batch 2: OCR-first visual artifacts

**Goal:** Run pinned OCR/layout on eligible crops and materialize visual chunks.

**Expected files:** existing `ingest/visual_understanding*.py`, private OCR/chunk artifacts, runner
tests.

**Done when:** a pinned real OCR wrapper/profile executes on the reviewed sample, each chunk reconciles
to one eligible occurrence and carries evidence/citation hashes, and applicable OCR quality gates pass.
The initial one-crop technical smoke demonstrates execution only, not completion of this batch.

### Batch 3: First approved visual-text index; optional local parity

**Goal (revised 2026-09-03):** Integrate into the local design only; build a separate local KURE
OCR-text index first after quality gates. Keep parsing/retrieval local and make only answer generation
replaceable with an approved model API. Do not merge the API branch wholesale.
See `local-visual-integration.md`. API OCR embedding is deferred, not a prerequisite.

**Expected files:** `indexing/visual_fusion.py`, index metadata/config fixtures, API/local build scripts.

**Done when:** the first approved index count, chunk hash, model, dimension, and artifact-set identity
all reconcile. Without scoped API approval this milestone remains pending; do not silently transmit
text or substitute a different embedding stack.

### Batch 4: Opt-in runtime integration

**Goal:** Load the visual lane only when explicitly enabled and preserve the current default bundle.

**Expected files:** `application/config.py`, `application/composition.py`, `answering/pipeline.py`,
`apps/streamlit_app.py`.

**Done when:** disabled mode preserves the baseline index, deterministic ranking, context and provider
input; enabled mode returns bbox/crop citations. Live generated text and trace IDs are not required to
be byte-identical. Actual opt-in use also requires the applicable Batch 5 evaluation and corpus gates;
passing fixture-only integration tests does not activate this mode.

### Batch 5: Evaluation and optional image-vector lane

**Goal:** Measure visual retrieval and add direct image vectors only if OCR/layout evidence is
insufficient for the approved visual qrels.

**Expected files:** visual qrels/evaluator, optional image encoder adapter and index metadata.

**Done when:** page-only vs page+OCR-text comparison records lane-level and fused object/page
Recall@5/@10, nDCG@10, citation accuracy, false positives, latency and cost, and the applicable quality
gates pass. If an image-vector experiment is separately selected, an additional OCR-only vs OCR+image
ablation must justify it; skipping that optional experiment does not fail the OCR-text milestone.

## 10. Acceptance Criteria

- Existing page/table tests and baseline artifacts remain unchanged.
- No unverified or withheld occurrence enters an index.
- Every visual hit has page, bbox, occurrence ID, crop SHA, and evidence type.
- API and local indexes cannot be mixed.
- Missing model weights, stale artifacts, or schema mismatch fail closed.
- OCR-text retrieval uses its matching approved text embedder. Only the optional image-vector lane
  requires a pinned text-image dual encoder and its paired text-query encoder; image-only vectors
  cannot silently enter a natural-language query path.
- The default request does not pay the VLM cost; VLM execution is explicit or triggered by a bounded
  visual cascade and is limited to supported crops.
- Visual gold evaluation has a saved qrels/result record; no claim is made from the current zero-chunk
  baseline.
- Streamlit shows the visual result only when the opt-in flag and runtime gates pass.

## 11. Test Plan

- Unit: occurrence eligibility, chunk identity, citation binding, index dimension/hash checks.
- Integration: crop → OCR → chunk → embedding → visual search → RRF.
- Regression: page/table retrieval, answer schema, citation serialization, current default config.
- Manual: Streamlit page/bbox/crop display and withheld/quarantined status.
- Safety: private path containment, symlink rejection, model checksum, timeout, and no-egress mode.

## 12. Capability Gaps

| Gap | Impact | Resolution |
| --- | --- | --- |
| Three OCR/layout weights are pinned, but wrapper/runtime and enabled submodules are incomplete | No real visual chunks | Pin executable/dependencies and map local model directories; disable unprovisioned submodules before a smoke run |
| Caption VLM unavailable | Diagram semantics remain descriptive-only | Add approved local VLM only after OCR gate |
| Current app is page-only; visual flags are not implemented | Visual lane not user-visible | Add opt-in config and UI preview after evaluation |
| Direct image encoder not selected | No visual-similarity search | Treat as optional Batch 5 experiment |

## 13. Handoff Notes

The branch is intentionally isolated from the current baseline branch. The first implementation slice
is Batch 1/2: keep the default runtime off, reuse the existing visual contracts, and materialize only
eligible OCR-based visual chunks. Do not activate a new provider, download model weights, or rewrite
the original/refined source without an explicit gate and artifact hash.

## 14. Readiness re-review and reduced next slice (2026-09-03)

This section is the immediate rollout plan and takes precedence over the deferred extension sequence
above. The full multi-lane implementation remains unverified. Review of this local OCR development
plan does not close R1-R6, authorize private egress, or activate the application.

### 14.1 Minimal execution plan

1. Establish a pinned local CPU OCR runtime and real JSON wrapper. The existing manifest pins only
   PP-DocLayout-L, PP-OCRv5_server_det and the Korean PP-OCRv5 recognizer. It is not a complete
   PP-StructureV3 installation. Disable unprovisioned orientation, table, formula, region and other
   optional modules explicitly; do not rely on library defaults. Avoid duplicating the table lane.
2. Run a bounded representative crop smoke without API calls; preserve OCR polygons, confidence,
   page/bbox/crop identity and failures. Verify every consumed weight, not just the manifest hash.
   Use one allowlisted crop within existing pixel/byte limits, batch size 1, one worker and a 120-second
   subprocess timeout. Record cold-start time and peak RSS. This technical smoke may precede human
   gold freeze and makes no retrieval-quality or resource-fit claim.
3. Freeze reviewed dev/held-out visual qrels before adding OCR text and verified nearby context to a
   separate local KURE index. Reuse the matching local query embedding; preserve the page index.
   Only answer generation may later switch to an approved model API. D-020 still requires scoped
   text-egress authorization for OCR-derived prompts; credentials alone never authorize that payload.
4. With an explicit opt-in, compare baseline-only against baseline plus OCR-text lookup. Fix relevance
   admission and occurrence grouping first. Add page/crop preview and bounded factual OCR context
   only after the locator, qrels and nonvisual regression gates pass.
5. Classify remaining failures. Test one paired text-image encoder only for demonstrated visual
   retrieval misses; test a VLM only for demonstrated interpretation gaps. Neither is mandatory for
   the first slice, and one does not inherently require the other. Both remain disabled for now.

### 14.2 Required repair and validation gates

Local implementation slice (2026-09-03): use the PaddleOCR OCR-only subpipeline with explicit
`PP-OCRv5_server_det` and `korean_PP-OCRv5_mobile_rec` local directories. Document layout weights
remain verified but inactive. No document-layout, table, orientation, unwarping, formula or region
model is constructed. `table_cells=[]`; polygons refer to crop pixels, source page/bbox remain in
the occurrence. This is not a full PP-StructureV3 result. The new minimal profile is separate from
the historical provisioned profile, and its runtime label states OCR-only. Reject unsupported flags.
Verify exact nine weight files and bytes/SHA-256 before inference, reject symlinks and missing files,
preserve the existing valid manifest bytes, and atomically publish only a new manifest.
Use an isolated `.venv-ocr` with version-pinned dependencies; the smoke pins executable, wrapper
and module identities and records installed-package versions. JSON stdout is machine-only; model
logs and recognized text never enter public logs. Public evidence contains only counts and timings.

| Gate | Required evidence before closing |
| --- | --- |
| R1: real OCR runtime | Pinned dependencies/wrapper/local model paths; no implicit downloads; one real image-to-OCR result plus all enabled-weight checks |
| R2: retrieval safety | Negative-score visual hits do not evict correct base hits; same occurrence uses one object slot; scope and disabled-baseline tests pass |
| R3: caption grounding | Valid reference IDs cannot by themselves promote unrelated facts or unsupported edges; unverified captions stay outside factual context |
| R4: runtime and model boundaries | Opt-in config/composition/UI tests; paired image query encoder if later enabled; same-dimension wrong-model rejection |
| R5: evaluation and resources | Object/page-aware qrels, implicit-visual and nonvisual negatives, latency p50/p95, peak RSS/VRAM, input-resolution/batch/concurrency limits, baseline regression |
| R6: repeatable provisioning | Manifest excludes itself; exact expected files and checksums; atomic publication and a download-free repeat-run test |

For the initial local OCR work, R1/R6 cover runtime/provisioning and one technical smoke. Before
real OCR-text answer use, close R2, R3-caption-exclusion, R4-text-opt-in and applicable R5 gates.
R3 semantic caption verification, R4 image query encoding and GPU/VLM resource checks stay deferred;
their absence does not block local OCR development and does not imply those capabilities passed.

The existing human-gold thresholds in `visual-image-recovery-and-understanding.md` Section 9 remain
in force: they are not replaced by fixture passes or four provisional figure cases. The current
legacy visual evaluator reads page ranges/source block IDs; an occurrence-aware projection is needed
before using it to score new visual chunks. Automatic routing, if later added, also needs router recall.

### 14.3 Scope-aware evaluation and leakage boundaries

- Locator precision, region discovery, Korean OCR-token quality, citation binding and existing
  baseline regressions apply to the OCR-text slice with the existing thresholds unchanged.
- Table-cell reconstruction, diagram arrows/hierarchy, map relations, image similarity and caption
  semantics are not provided by this slice. Report their applicable tests as `not_supported/deferred`
  (table-cell accuracy: `N/A`), not as passing because the modules were disabled. Keep the separate
  table baseline regression. Report OCR-capable subset quality alongside all-visual coverage and
  unsupported-case counts; do not drop difficult cases from the overall coverage denominator.
- This partial-capability experiment does not satisfy the original full-visual/full-corpus activation
  contract by itself. Its deferred cases cannot be used to relax the older human/corpus quality gates.
- Follow `evaluation-contract.md` split/group rules. Freeze reviewed dev and held-out qrels before
  tuning; fit admission thresholds/quotas on dev positives and negatives only, then freeze config
  before held-out scoring. Record held-out reruns and do not retune on their outcomes.
- Qrels, expected answers and review notes are evaluator-only: never put them in OCR chunks, index
  content, runtime routing, retrieval prompts or generation context. Verified source context is not
  gold context. D-022 governs semantic relevance/answer/citation review; code measures transcription,
  structural/rank and resource metrics. A run judgment cannot approve or rewrite gold.

### 14.4 Resource and external-boundary phase gates

The one-crop smoke observes resource use; observation alone is not an acceptance result. Before
increasing sample/batch size or running corpus/API/UI trials, pin finite numeric input pixel/byte,
worker/batch/concurrency, timeout, process-tree RSS and host-headroom bounds in the execution profile.
Do not start a larger run with unspecified limits. Exceeding a bound stops the worker/batch, records
a sanitized failure and preserves validated cache for explicit resume; it must not auto-retry at a
larger limit. Online latency SLO remains a measurement/comparison until separately frozen, consistent
with `evaluation-contract.md`. GPU and co-resident generation require their own measurements.

D-023 storage limits remain 100 GB hard max, warning at 80 GB used and stop below 10 GB free.

D-020 currently forbids private egress for this visual work. The OCR wrapper, parser and local
technical/quality checks remain zero-egress. API embedding of OCR-derived text, sending OCR context
to generation and exporting material for semantic review each require a recorded applicable
destination/payload/profile/budget authorization that explicitly resolves D-020; this contract does
not change that decision. Until then, API/index/answer stages wait while local implementation can
proceed. Text-egress approval must never imply crop/page-image upload, an external parser or a VLM.

No resource-fit claim follows from the approximately 230 MB model files. CPU/GPU resident memory,
activation buffers, image resolution and concurrent generation must be measured. The current Linux
network sandbox does not explicitly pass NVIDIA devices through its replacement `/dev`; GPU readiness
requires a separate device-access and CUDA smoke, while the first local smoke stays CPU-only.

Official module reference (reviewed 2026-09-03; not a dependency pin):
[PaddleX PP-StructureV3 configuration](https://raw.githubusercontent.com/PaddlePaddle/PaddleX/develop/paddlex/configs/pipelines/PP-StructureV3.yaml).
