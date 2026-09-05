"""Observe one retrieval arm without gold input, retries, or generation.

These offline observations are NOT controller live-authority receipts. The
caller must verify artifact files and keep one arm per scorer input file.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from time import perf_counter

from .answering.pipeline import _retrieval_query
from .evidence import EvidenceStore, validate_evidence_store_snapshot
from .indexing.exact_index import ExactDenseIndex
from .retrieval.context import select_context
from .retrieval.contracts import SearchResult
from .retrieval.fusion import HybridChildRetriever, fuse_rrf, require_production_hybrid
from .retrieval.legacy_page import LegacyPageLane
from .retrieval_experiment import ARM_IDS, validate_draft
from .runtime_integrity import RuntimeRequest, ResolvedScope, validate_runtime_request_snapshot
from .stage_checkpoints import SCHEMA, STAGES, canonical_sha, make_checkpoint
from .stacks.local.hf_embeddings import HuggingFaceTokenCounter, KureEmbeddingProvider


def _id(value):
    if type(value) is not str or not value or len(value) > 160 or any(
        not (c.isascii() and (c.isalnum() or c in "_.:-")) for c in value
    ):
        raise ValueError("invalid_recorder_identifier")


def _backend_guard(backend, store, config, arm_id):
    artifacts = config["artifact_hashes"]
    validate_evidence_store_snapshot(store, artifacts["evidence_store"])
    if arm_id != "page_kure":
        binding = require_production_hybrid(backend, store)
        if (binding.dense_artifact_sha256 != artifacts["child_dense"]
                or binding.lexical_artifact_sha256 != artifacts["child_lexical"]):
            raise ValueError("recorder_child_artifact_mismatch")
        return {"backend_guarantee": "loader_attested_child", "binding_sha256": binding.binding_sha256}
    if (type(backend) is not LegacyPageLane or backend.store is not store
            or type(backend.index) is not ExactDenseIndex or type(backend.provider) is not KureEmbeddingProvider
            or backend.provider.execution_kind != "real_local_model"
            or backend.artifact_sha256 != artifacts["page_index"]):
        raise ValueError("recorder_verified_page_backend_required")
    # The legacy adapter has no sealed loader binding. Recheck its mapping but
    # never describe this as a child production attestation.
    rebuilt = LegacyPageLane(backend.index, store, backend.provider, artifact_sha256=backend.artifact_sha256)
    if backend._mapping != rebuilt._mapping:
        raise ValueError("recorder_page_mapping_drift")
    return {"backend_guarantee": "legacy_page_mapping_only", "binding_sha256": None}


def record_request(*, request: RuntimeRequest, backend, store: EvidenceStore,
                   config: dict, run_id: str, case_id: str, arm_id: str) -> dict:
    """Production entry: exact request and loaded backend; no caller real flag."""
    validate_draft(config)
    for identifier in (run_id, case_id):
        _id(identifier)
    if arm_id not in ARM_IDS:
        raise ValueError("recorder_unknown_arm")
    validate_runtime_request_snapshot(request)
    if request.metadata_filters or request.options or request.prior_citation_state is not None:
        raise ValueError("recorder_request_feature_not_supported")
    frozen_config = deepcopy(config)
    proof = _backend_guard(backend, store, frozen_config, arm_id)

    def guard():
        validate_runtime_request_snapshot(request)
        if validate_draft(config) != frozen_config["config_sha256"]:
            raise ValueError("recorder_config_drift")
        if _backend_guard(backend, store, frozen_config, arm_id) != proof:
            raise ValueError("recorder_backend_binding_drift")

    start = perf_counter()
    query = _retrieval_query(request.to_dict(), HuggingFaceTokenCounter(),
                             max_tokens=frozen_config["query_policy"]["max_input_tokens"])
    query_ms = (perf_counter() - start) * 1000
    scope = ResolvedScope.from_request(request)
    guard()

    def search(lane, limit):
        if arm_id == "page_kure":
            return LegacyPageLane.search(backend, query, limit, allowed_doc_ids=scope.allowed_doc_ids)
        return HybridChildRetriever.search_lane(backend, query, lane=lane, limit=limit, scope=scope)

    return _record(query=query, scope=scope, store=store, config=frozen_config, run_id=run_id,
                   case_id=case_id, arm_id=arm_id, search=search, guard=guard,
                   query_build_ms=query_ms, proof=proof)


def _record(*, query, scope, store, config, run_id, case_id, arm_id, search,
            guard=lambda: None, query_build_ms=None, proof=None):
    """Internal test seam; absent a production proof it is always synthetic."""
    config = deepcopy(config)
    config_sha = validate_draft(config)
    for identifier in (run_id, case_id):
        _id(identifier)
    if arm_id not in ARM_IDS or type(query) is not str or not query.strip():
        raise ValueError("invalid_recorder_input")
    if type(scope) is not ResolvedScope or scope.origin not in {"all", "user_explicit"}:
        raise ValueError("recorder_original_scope_required")
    validate_evidence_store_snapshot(store, config["artifact_hashes"]["evidence_store"])
    arm = next(row for row in config["arms"] if row["arm_id"] == arm_id)
    binding = {"query_sha256": sha256(query.encode("utf-8")).hexdigest(), "scope_sha256": canonical_sha(scope.to_dict()),
               "evidence_store_sha256": store.bundle_sha256, "run_config_sha256": config_sha,
               "execution_key_sha256": canonical_sha({"run_id": run_id, "case_id": case_id, "arm_id": arm_id})}
    proof = proof or {"backend_guarantee": "synthetic", "binding_sha256": None}
    producer = "synthetic" if proof["backend_guarantee"] == "synthetic" else "observed_local_retrieval"
    checkpoints, events, results = {}, {}, {}

    def emit(stage, *, value=None, elapsed=None, attempted=False, error=None, upstream=(), input_ids=()):
        ids = ([] if value is None else list(value.evidence_ids) if stage == "final_context"
               else [c.evidence_id for c in value.candidates])
        outcome = "ok" if value is not None else "error" if attempted else "unavailable"
        trace = {} if value is None else value.trace
        encoder_calls = (0 if not attempted else None) if stage == "lane_dense" else 0
        if stage == "lane_dense" and value is not None:
            count = trace.get("encoder_calls")
            if type(count) is int and count >= 0:
                encoder_calls = count
            elif trace.get("lane_calls") == 0 and trace.get("empty_scope") is True:
                encoder_calls = 0
        event = {"schema_version": "retrieval-stage-observation-v1", "producer_kind": producer,
                 "run_id": run_id, "case_id": case_id, "arm_id": arm_id, "stage": stage,
                 "binding": binding, "backend_proof": proof, "artifact_hashes": config["artifact_hashes"],
                 "outcome": outcome, "call_performed": attempted, "error_code": error,
                 "elapsed_ms": elapsed, "encoder_calls": encoder_calls,
                 "query_embedding_elapsed_ms": None, "candidate_count": len(ids),
                 "ordered_ids_sha256": canonical_sha(ids), "input_ids_sha256": canonical_sha(list(input_ids)),
                 "upstream_receipt_sha256s": [events[s]["receipt_sha256"] for s in upstream]}
        event["receipt_sha256"] = canonical_sha(event)
        stage_config_sha = canonical_sha({"arm": arm, "stage": stage, "context": config["context"],
                                          "return_k": config["return_k"]})
        checkpoints[stage] = make_checkpoint(stage, ids, store=store, binding=binding,
                                             stage_config_sha256=stage_config_sha,
                                             source_receipt_sha256=event["receipt_sha256"],
                                             call_performed=attempted, outcome=outcome)
        events[stage], results[stage] = event, value

    def call(stage, function, *, upstream=(), input_ids=()):
        guard()  # A drift is fatal, not a normal empty/error search.
        start = perf_counter()
        value, error = None, None
        try:
            try:
                value = function()
            finally:
                elapsed = (perf_counter() - start) * 1000
            if stage != "final_context":
                if type(value) is not SearchResult:
                    raise ValueError("recorder_search_result_required")
                for rank, candidate in enumerate(value.candidates, 1):
                    evidence = store.get(candidate.evidence_id)
                    if (candidate.rank != rank or evidence.doc_id != candidate.doc_id
                            or candidate.granularity != arm["granularity"]
                            or evidence.kind != ("page" if arm["granularity"] == "page" else "text")
                            or (scope.allowed_doc_ids is not None and evidence.doc_id not in scope.allowed_doc_ids)):
                        raise ValueError("recorder_candidate_mismatch")
                limit = arm["dense_k"] if stage == "lane_dense" else arm["lexical_k"]
                if stage != "fusion" and len(value.candidates) > limit:
                    raise ValueError("recorder_candidate_budget_exceeded")
        except Exception:
            value, error = None, "stage_execution_failed"
        guard()
        emit(stage, value=value, attempted=True, elapsed=elapsed, error=error,
             upstream=upstream, input_ids=input_ids)

    call("lane_dense", lambda: search("dense", arm["dense_k"]))
    if arm_id == "child_bm25_rrf":
        call("lane_lexical", lambda: search("lexical", arm["lexical_k"]))
        upstream = ("lane_dense", "lane_lexical")
        if all(results[s] is not None for s in upstream):
            call("fusion", lambda: fuse_rrf(results["lane_dense"], results["lane_lexical"], store,
                                            rrf_k=arm["rrf_k"]), upstream=upstream)
        else:
            emit("fusion", upstream=upstream, error="upstream_unavailable")
    else:
        emit("lane_lexical", error="arm_stage_not_configured")
        emit("fusion", error="arm_stage_not_configured")
    for stage in ("lane_visual", "rerank"):
        emit(stage, error="arm_stage_not_configured")
    pre = arm["pre_context_stage"]
    if results[pre] is None:
        emit("final_context", upstream=(pre,), error="upstream_unavailable")
    else:
        candidates = results[pre].candidates[:config["return_k"]]
        settings = {k: v for k, v in config["context"].items() if k != "selector"}
        call("final_context", lambda: select_context(candidates, store, **settings),
             upstream=(pre,), input_ids=[c.evidence_id for c in candidates])
    guard()
    ordered = sorted(STAGES, key=STAGES.get)
    record = {"schema_version": SCHEMA, "case_id": case_id, "run_id": run_id, "binding": binding,
              "checkpoints": [checkpoints[stage] for stage in ordered]}
    observation = {"schema_version": "retrieval-observation-v1", "producer_kind": producer,
                   "formal_comparison_authorized": False, "arm_id": arm_id, "binding": binding,
                   "query_build_ms": query_build_ms, "load_elapsed_ms": None,
                   "stage_observations": [events[stage] for stage in ordered],
                   "record_sha256": canonical_sha(record)}
    observation["receipt_sha256"] = canonical_sha(observation)
    return {"record": record, "observations": observation}
