"""Bounded offline connectivity check, never a formal Mini131 quality run."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from time import perf_counter

from .evidence.artifacts import file_sha, load_bundle, private_path, write_new_json
from .gcp_local_baseline import (_configure_hf_cache, _load_chunks, mac_index_config_sha256,
                                 MAC_LOCAL_EQUIVALENT, verify_dependency_lock)
from .indexing.embeddings import embedding_cache_namespace
from .indexing.exact_index import ExactDenseIndex
from .local_mini131_baseline import verify_suite
from .retrieval.dense import load_dense
from .retrieval.fusion import HybridChildRetriever, require_production_hybrid
from .retrieval.kiwi_bm25 import KiwiBM25Lane, KiwiTokenizer
from .retrieval.legacy_page import LegacyPageLane
from .retrieval_experiment import ARM_IDS, make_draft
from .runtime_integrity import RuntimeRequest
from .stage_checkpoints import canonical_sha
from .stage_evaluation import load_source_snapshot
from .stage_inputs import build_inputs
from .stage_recorder import record_request
from .stacks.local.hf_embeddings import KureEmbeddingProvider


def select_cases(cases):
    """Choose by original request scope only, never by answer/gold/score."""
    selected = []
    for mode in ("explicit", "all"):
        case = next((c for c in cases if c.lane == "core40" and c.request_template is not None
                     and c.request_template["document_scope"]["mode"] == mode), None)
        if case is None:
            raise ValueError("smoke_requires_original_explicit_and_all_requests")
        selected.append((case.case_id, RuntimeRequest.from_dict(case.request_template)))
    return selected


def require_offline_cache(cache_path):
    # dense imports Transformers to pin dispatch identities at module import.
    # Changing HF_HOME later does not change Hugging Face's cached constants.
    from huggingface_hub import constants
    from transformers.utils.hub import TRANSFORMERS_CACHE
    if (Path(constants.HF_HUB_CACHE).resolve() != (cache_path / "hub").resolve()
            or Path(TRANSFORMERS_CACHE).resolve() != (cache_path / "hub").resolve()
            or constants.HF_HUB_OFFLINE is not True
            or os.environ.get("TRANSFORMERS_OFFLINE") != "1"):
        raise ValueError("smoke_offline_cache_startup_mismatch")


def verify_inputs(inputs_dir, suite, snapshot):
    inventory = json.loads((inputs_dir / "inventory.json").read_text(encoding="utf-8"))
    projected = build_inputs(suite.cases, suite.ledger_rows, snapshot,
                             {k: v["sha256"] for k, v in suite.config["sources"].items()}, suite.parser_receipt)
    projected["input_config_sha256"] = suite.config_sha256
    projected.pop("inputs_sha256")
    projected["inputs_sha256"] = canonical_sha(projected)
    qrels = [json.loads(line) for line in (inputs_dir / "qrels.jsonl").read_text(encoding="utf-8").splitlines() if line]
    if qrels != projected["qrels"]:
        raise ValueError("smoke_input_qrels_mismatch")
    expected = {k: v for k, v in projected.items() if k != "qrels"}
    expected.update(qrels_file_sha256=file_sha(inputs_dir / "qrels.jsonl"), publication_status="complete")
    expected["inventory_sha256"] = canonical_sha(expected)
    if inventory != expected:
        raise ValueError("smoke_input_inventory_mismatch")
    return inventory


def _write_jsonl(path, rows):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")


def run_arms(selected, backends, store, config, output_dir, *, run_id, recorder=record_request):
    """Two rounds; actual observations stay private and arms remain separate."""
    reference, summaries, seen_backend = {}, [], set()
    for arm in ARM_IDS:
        backend_key = "page" if arm == "page_kure" else "child"
        for round_index in (1, 2):
            records, observations = [], []
            for case_id, request in selected:
                print(json.dumps({"phase": "query_started", "arm": arm, "round": round_index,
                                  "case_ordinal": len(records) + 1}), flush=True)
                start = perf_counter()
                out = recorder(request=request, backend=backends[backend_key], store=store, config=config,
                               run_id=f"{run_id}.r{round_index}", case_id=case_id, arm_id=arm)
                wall_ms = (perf_counter() - start) * 1000
                record, observation = out["record"], out["observations"]
                actual_binding = {k: v for k, v in record["binding"].items() if k != "execution_key_sha256"}
                if reference.setdefault(case_id, actual_binding) != actual_binding:
                    raise ValueError("smoke_common_query_scope_config_mismatch")
                stages = {c["stage"]: c for c in record["checkpoints"]}
                required = ("lane_dense", "lane_lexical", "fusion", "final_context") if arm == "child_bm25_rrf" else ("lane_dense", "final_context")
                counts = [e["encoder_calls"] for e in observation["stage_observations"]]
                summary = {"case_id": case_id, "arm_id": arm, "round": round_index,
                           "backend_temperature": "first_query_may_include_lazy_model_load" if backend_key not in seen_backend else "reused_backend",
                           "query_wall_ms": wall_ms, "required_stages_ok": all(stages[s]["outcome"] == "ok" for s in required),
                           "encoder_calls": sum(counts) if all(type(c) is int for c in counts) else None,
                           "observation_sha256": observation["receipt_sha256"]}
                seen_backend.add(backend_key)
                records.append(record)
                observations.append(observation)
                summaries.append(summary)
            _write_jsonl(output_dir / f"{arm}.round{round_index}.records.jsonl", records)
            _write_jsonl(output_dir / f"{arm}.round{round_index}.observations.jsonl", observations)
            print(json.dumps({"phase": "arm_round_recorded", "arm": arm, "round": round_index,
                              "count": len(records), "ok": all(s["required_stages_ok"] for s in summaries[-len(records):])}), flush=True)
    return summaries


def run(args):
    target = private_path(args.output_dir, args.data_root)
    if target.exists() or not target.parent.is_dir():
        raise ValueError("smoke_new_output_directory_required")
    root = private_path(args.artifact_root, args.data_root)
    inputs_dir = private_path(args.inputs_dir, args.data_root)
    suite = verify_suite(repo_root=args.repo_root, config_path=args.config)
    verified = suite.stack
    lock = verify_dependency_lock(verified)
    if not verified.hf_cache_path.is_dir():
        raise ValueError("smoke_offline_cache_missing")
    require_offline_cache(verified.hf_cache_path)
    _configure_hf_cache(verified.hf_cache_path, offline=True)
    timings = {}
    def timed(name, function):
        start = perf_counter()
        result = function()
        timings[name] = (perf_counter() - start) * 1000
        print(json.dumps({"phase": name, "status": "loaded", "elapsed_ms": timings[name]}), flush=True)
        return result
    store, bundle_receipt = timed("bundle_load", lambda: load_bundle(root / "compat", data_root=args.data_root))
    snapshot = timed("source_snapshot", lambda: load_source_snapshot(data_root=args.data_root,
                     manifest=verified.manifest_path, blocks_dir=args.data_root / "private/blocks",
                     store=store, input_hashes=bundle_receipt["input_hashes"]))
    inventory = verify_inputs(inputs_dir, suite, snapshot)
    selected = select_cases(suite.cases)
    config = make_draft({"input_inventory": inventory["inventory_sha256"], "source_snapshot": snapshot.snapshot_sha256,
                         "evidence_store": store.bundle_sha256, "page_index": file_sha(verified.index_path / "metadata.json"),
                         "child_dense": file_sha(root / "dense/receipt.json"), "child_lexical": file_sha(root / "lexical/receipt.json")})
    protected = [verified.manifest_path, verified.chunks_path, inputs_dir / "inventory.json", inputs_dir / "qrels.jsonl"]
    for folder in (root / "compat", root / "dense", root / "lexical", verified.index_path):
        protected.extend(p for p in folder.rglob("*") if p.is_file() and not p.name.endswith(".lock"))
    before = {str(p): file_sha(p) for p in protected}
    target.mkdir(mode=0o700)
    write_new_json(target / "experiment-draft.json", config)
    plan = {"schema_version": "retrieval-smoke-plan-v1", "mini131_case_count": 131, "sample_case_count": 2,
            "case_ids": [c for c, _ in selected], "arms": list(ARM_IDS), "rounds": 2,
            "query_call_budget": 12, "api_calls": 0, "generation_calls": 0, "formal_comparison_authorized": False,
            "source_file_sha256s": inventory["source_file_sha256s"], "config_sha256": config["config_sha256"]}
    write_new_json(target / "plan.json", plan)
    page_provider = KureEmbeddingProvider(batch_size=1, device="cpu")
    chunks = timed("page_chunks_load", lambda: _load_chunks(verified))
    index = timed("page_index_load", lambda: ExactDenseIndex.load(verified.index_path, chunks,
                  expected_embedding_model=embedding_cache_namespace(page_provider, role="document"),
                  expected_dimensions=1024, expected_api_profile=MAC_LOCAL_EQUIVALENT,
                  expected_index_config_sha256=mac_index_config_sha256(verified)))
    page = timed("page_mapping", lambda: LegacyPageLane(index, store, page_provider, artifact_sha256=config["artifact_hashes"]["page_index"]))
    dense = timed("child_dense_load", lambda: load_dense(store, KureEmbeddingProvider(batch_size=1, device="cpu"),
                                                        output_dir=root / "dense", data_root=args.data_root))
    lexical = timed("child_lexical_load", lambda: KiwiBM25Lane.load(store, KiwiTokenizer(), root / "lexical", data_root=args.data_root))
    child = timed("child_binding", lambda: HybridChildRetriever.from_loaded_artifacts(store, dense, lexical))
    require_production_hybrid(child, store)
    summaries = run_arms(selected, {"page": page, "child": child}, store, config, target, run_id=target.name)
    if before != {str(p): file_sha(p) for p in protected}:
        raise ValueError("smoke_protected_artifact_changed")
    verify_suite(repo_root=args.repo_root, config_path=args.config)
    verify_inputs(inputs_dir, suite, snapshot)
    after_snapshot = load_source_snapshot(data_root=args.data_root, manifest=verified.manifest_path,
                                         blocks_dir=args.data_root / "private/blocks", store=store,
                                         input_hashes=bundle_receipt["input_hashes"])
    if after_snapshot.snapshot_sha256 != snapshot.snapshot_sha256:
        raise ValueError("smoke_source_snapshot_changed")
    passed = all(row["required_stages_ok"] and row["encoder_calls"] == 1 for row in summaries)
    receipt = {"schema_version": "retrieval-smoke-v1", "status": "passed" if passed else "failed",
               "measurement_kind": "connectivity_not_quality", "mini131_case_count": 131, "sample_case_count": 2,
               "record_count": len(summaries), "query_embedding_calls": sum(row["encoder_calls"] for row in summaries)
               if all(type(row["encoder_calls"]) is int for row in summaries) else None,
               "api_calls": 0, "generation_calls": 0, "formal_comparison_authorized": False,
               "artifact_unchanged": True, "artifact_load_ms": timings, "dependency_lock": lock,
               "config_sha256": config["config_sha256"], "inventory_sha256": inventory["inventory_sha256"],
               "runs": summaries, "output_file_sha256s": {p.name: file_sha(p) for p in sorted(target.iterdir()) if p.is_file()}}
    receipt["receipt_sha256"] = canonical_sha(receipt)
    write_new_json(target / "run-receipt.json", receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("repo-root", "config", "data-root", "artifact-root", "inputs-dir", "output-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        receipt = run(args)
        print(json.dumps({k: receipt[k] for k in ("status", "record_count", "query_embedding_calls", "api_calls",
                                                  "generation_calls", "formal_comparison_authorized", "receipt_sha256")}))
        return 0 if receipt["status"] == "passed" else 2
    except (ValueError, TypeError, RuntimeError, OSError, KeyError, AttributeError) as exc:
        reason = "smoke_offline_cache_startup_mismatch" if str(exc) == "smoke_offline_cache_startup_mismatch" else "offline_retrieval_smoke_failed"
        print(json.dumps({"status": "rejected", "reason": reason,
                          "error_type": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
