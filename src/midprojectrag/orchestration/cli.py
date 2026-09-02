"""Explicit opt-in CLI; local live mode never contacts an external LLM service."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from midprojectrag.answering.evidence_adapter import EvidenceAnswerAdapter
from midprojectrag.evaluation import validate_request
from midprojectrag.evidence import EvidenceStore, build_from_chunks
from .artifacts import digest, read_json, trace_record, write_private_json
from .controller import Harness
from .enumeration import BoundedListEnumerator, EnumerationConfig
from .golden_v3 import build_runtime_requests, load_inventory
from .llm import LLMPlanner, LLMPolicy, LLMVerifier, LocalJSONBackend, SYSTEM
from .local_runtime import DeadlineGenerator, compose_retriever, legacy_paths
from .pipeline import EvidenceHarnessPipeline, ListPipelineResult
from .types import BoundedPolicy, HarnessConfig


class ByteUpperCounter:
    """Conservative UTF-8 byte upper bound, not a measured model tokenizer."""
    def count(self, text: str) -> int:
        return len(text.encode("utf-8"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Evidence-Harness opt-in, nonofficial local runtime")
    subs = parser.add_subparsers(dest="command", required=True)
    build = subs.add_parser("build", help="Convert validated page/explicit auxiliary chunk JSON array")
    build.add_argument("--chunks", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    prepare = subs.add_parser("prepare-legacy", help="Read pinned legacy page chunks into a private evidence store")
    prepare.add_argument("--source-root", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    run = subs.add_parser("run", help="Run local controller; opt in to pinned KURE page + lexical child retrieval")
    run.add_argument("--evidence", type=Path, required=True)
    run.add_argument("--request", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--policy", choices=("bounded", "llm"), default="llm")
    run.add_argument("--timeout-seconds", type=float, default=180)
    run.add_argument("--per-call-seconds", type=float, default=60,
                     help="Bound each local HTTP call within the shared request deadline")
    run.add_argument("--source-root", type=Path, help="Existing corpus/cache root; absent means lexical-only")
    run.add_argument("--requires-pixels", action="store_true")
    run.add_argument("--synthetic", action="store_true", help="Mark synthetic smoke; never a quality receipt")
    v3_preflight = subs.add_parser("golden-v3-preflight", help="Validate the third lane-specific golden inventory")
    v3_preflight.add_argument("--root", type=Path, required=True, help="Path to the unpacked golden-set-v3-share package")
    v3_prepare = subs.add_parser("golden-v3-prepare", help="Prepare private runtime requests from the third golden inventory")
    v3_prepare.add_argument("--root", type=Path, required=True, help="Path to the unpacked golden-set-v3-share package")
    v3_prepare.add_argument("--output", type=Path, required=True)
    v3_prepare.add_argument("--include-visual", action="store_true", help="Include visual questions; default is nonvisual lanes only")
    args = parser.parse_args(argv)
    root = Path.cwd() / "private" / "evidence-harness"
    if args.command in {"golden-v3-preflight", "golden-v3-prepare"}:
        try:
            inventory = load_inventory(args.root)
            if args.command == "golden-v3-preflight":
                summary = {
                    "status": "validated",
                    "official": False,
                    "set_id": inventory.set_id,
                    "inventory_status": inventory.status,
                    "index_sha256": inventory.index_sha256,
                    "counts": dict(inventory.counts),
                    "lane_counts": inventory.lane_counts,
                    "nonvisual_request_count": inventory.nonvisual_request_count,
                }
                print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
                return 0
            if not args.output.resolve().is_relative_to(root.resolve()) or args.output.exists():
                raise ValueError("private_new_output_required")
            requests = build_runtime_requests(inventory, include_visual=args.include_visual)
            write_private_json(args.output, list(requests), private_root=root)
            print(json.dumps({
                "status": "prepared",
                "official": False,
                "set_id": inventory.set_id,
                "request_count": len(requests),
                "include_visual": bool(args.include_visual),
                "output_sha256": digest(list(requests)),
            }, ensure_ascii=False, sort_keys=True))
            return 0
        except Exception:
            print(json.dumps({"status": "error", "reason": "golden_v3_preflight_or_prepare_failed", "official": False}))
            return 2
    backend = None
    store = None
    config = None
    try:
        # Validate output before any provider call (write itself remains exclusive).
        if not args.output.resolve().is_relative_to(root.resolve()) or args.output.exists():
            raise ValueError("private_new_output_required")
        if args.command in {"build", "prepare-legacy"}:
            if args.command == "prepare-legacy":
                from midprojectrag.retrieval.legacy_page import read_pinned_page_chunks
                chunks = read_pinned_page_chunks(legacy_paths(args.source_root)[0])
            else:
                chunks = read_json(args.chunks)
                if not isinstance(chunks, list):
                    raise ValueError("chunk_array_required")
            store = build_from_chunks(chunks)
            write_private_json(args.output, store.to_dict(), private_root=root, max_bytes=256 * 1024 * 1024)
            print(json.dumps({"status": "built", "evidence_count": len(store.all()), "sha256": digest(store.to_dict())}))
            return 0
        request = read_json(args.request, max_bytes=512000)
        if validate_request(request):
            raise ValueError("invalid_request")
        store = EvidenceStore.from_dict(read_json(args.evidence, max_bytes=256 * 1024 * 1024))
        config = HarnessConfig(timeout_seconds=args.timeout_seconds)
        enumeration_config = EnumerationConfig(citation_limit=20, timeout_seconds=args.timeout_seconds)
        deadline = time.monotonic() + config.timeout_seconds
        backend = LocalJSONBackend(deadline=deadline, per_call_seconds=args.per_call_seconds,
                                   max_calls=2 * config.max_actions + enumeration_config.max_calls + 2)
        policy = LLMPolicy(backend) if args.policy == "llm" else BoundedPolicy()
        retriever, retrieval_profile = compose_retriever(store, source_root=args.source_root,
                                                       deadline=deadline, calls=backend.calls)
        plan = LLMPlanner(backend).plan(request)
        harness = Harness(store=store, retriever=retriever, verifier=LLMVerifier(backend), policy=policy,
                          config=config, pack_verified_only=True)
        generator = DeadlineGenerator(backend)
        adapter = EvidenceAnswerAdapter(generator=generator, counter=ByteUpperCounter(), max_prompt_tokens=32768)
        enumerator = BoundedListEnumerator(store, backend, config=enumeration_config)
        result = EvidenceHarnessPipeline(harness=harness, answer_adapter=adapter, enumerator=enumerator).query(
            request, plan=plan, deadline=deadline, requires_pixels=args.requires_pixels)
        runtime = {"retrieval": retrieval_profile, "enumeration": enumeration_config,
                   "controller_model": generator.model, "model_digest": generator.model_digest,
                   "context_tokens": 32768, "output_tokens": 1800, "call_limit": backend.max_calls,
                   "controller_prompt_sha256": digest(SYSTEM),
                   "per_call_seconds": backend.per_call_seconds,
                   "context_policy": "verified_only",
                   "visual_reader_enabled": False, "learned_policy_promoted": False}
        trace = trace_record(request=request, store=store, config=config, policy_id=policy.policy_id,
                             result=result, provider_calls=backend.calls, synthetic=args.synthetic, runtime=runtime)
        write_private_json(args.output, trace, private_root=root)
        if isinstance(result, ListPipelineResult):
            status, reason, count = result.status, result.reason, result.enumeration.calls
        else:
            status, reason, count = result.harness.status, result.harness.reason, result.harness.state.actions_spent
        print(json.dumps({"status": result.answer.response["status"], "harness_status": status,
                          "reason": reason, "steps": count, "query_type": plan.query_type,
                          "trace_sha256": trace["trace_sha256"], "official": False}))
        return 0 if status != "ERROR" and result.answer.response.get("status") != "error" else 2
    except Exception:
        persisted = False
        if backend is not None and backend.calls:
            interrupted = {"schema_version": "evidence-harness-trace-v1", "official": False,
                           "synthetic": bool(getattr(args, "synthetic", False)), "status": "interrupted", "result": None,
                           "reason": "preflight_or_runtime_failure", "provider_calls": backend.calls,
                           "config_sha256": digest(config), "evidence_sha256": digest(store.to_dict())}
            interrupted["trace_sha256"] = digest(interrupted)
            try:
                write_private_json(args.output, interrupted, private_root=root)
                persisted = True
            except Exception:
                pass
        # Do not print raw provider errors or private paths, questions, or source text.
        print(json.dumps({"status": "error", "reason": "preflight_or_runtime_failure", "official": False,
                          "interrupted_trace_saved": persisted}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
