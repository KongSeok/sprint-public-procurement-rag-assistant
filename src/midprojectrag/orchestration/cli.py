"""Explicit opt-in CLI; local live mode never contacts an external LLM service."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from midprojectrag.answering.evidence_adapter import EvidenceAnswerAdapter
from midprojectrag.evaluation import validate_request
from midprojectrag.evidence import EvidenceStore, build_from_chunks
from midprojectrag.retrieval import BM25Retriever, HybridRetriever
from .artifacts import digest, read_json, trace_record, write_private_json
from .controller import Harness
from .llm import LLMPlanner, LLMPolicy, LLMVerifier, LocalJSONBackend
from .pipeline import EvidenceHarnessPipeline
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
    run = subs.add_parser("run", help="Run pinned local LLM planner/verifier/generator, lexical lane only")
    run.add_argument("--evidence", type=Path, required=True)
    run.add_argument("--request", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--policy", choices=("bounded", "llm"), default="llm")
    run.add_argument("--timeout-seconds", type=float, default=180)
    run.add_argument("--requires-pixels", action="store_true")
    run.add_argument("--synthetic", action="store_true", help="Mark synthetic smoke; never a quality receipt")
    args = parser.parse_args(argv)
    root = Path.cwd() / "private" / "evidence-harness"
    backend = None
    store = None
    config = None
    try:
        # Validate output before any provider call (write itself remains exclusive).
        if not args.output.resolve().is_relative_to(root.resolve()) or args.output.exists():
            raise ValueError("private_new_output_required")
        if args.command == "build":
            chunks = read_json(args.chunks)
            if not isinstance(chunks, list):
                raise ValueError("chunk_array_required")
            store = build_from_chunks(chunks)
            write_private_json(args.output, store.to_dict(), private_root=root)
            print(json.dumps({"status": "built", "evidence_count": len(store.all()), "sha256": digest(store.to_dict())}))
            return 0
        request = read_json(args.request, max_bytes=512000)
        if validate_request(request):
            raise ValueError("invalid_request")
        store = EvidenceStore.from_dict(read_json(args.evidence))
        config = HarnessConfig(timeout_seconds=args.timeout_seconds)
        deadline = time.monotonic() + config.timeout_seconds
        backend = LocalJSONBackend(deadline=deadline, max_calls=2 * config.max_actions + 1)
        policy = LLMPolicy(backend) if args.policy == "llm" else BoundedPolicy()
        plan = LLMPlanner(backend).plan(request)
        # Parent pages remain locators; avoid scoring duplicate page and child text.
        child_ids = tuple(e.evidence_id for e in store.all() if e.kind != "page")
        retriever = HybridRetriever(store, {"lexical": BM25Retriever(store, evidence_ids=child_ids)})
        harness = Harness(store=store, retriever=retriever, verifier=LLMVerifier(backend), policy=policy, config=config)
        from midprojectrag.stacks.local.generation import OllamaGenerator
        generator = OllamaGenerator(max_output_tokens=1800, context_tokens=32768, timeout_seconds=1)
        # Generated provider timeout is set per call without changing a shared instance.
        class DeadlineGenerator:
            model = generator.model
            requires_budget = False
            max_output_tokens = generator.max_output_tokens
            system_instructions = generator.system_instructions
            def estimate_cost(self, inputs, outputs):
                return generator.estimate_cost(inputs, outputs)
            def generate(self, prompt):
                remaining = deadline - time.monotonic()
                if remaining < 2:
                    raise TimeoutError("deadline_exceeded")
                provider = OllamaGenerator(max_output_tokens=self.max_output_tokens, context_tokens=32768,
                                           timeout_seconds=min(30, remaining / 2))
                record = {"purpose": "answer", "model": self.model, "status": "attempted", "prompt": prompt}
                backend.calls.append(record)
                try:
                    result, inputs, outputs = provider.generate(prompt)
                    record.update(status="completed", response=result, input_tokens=inputs, output_tokens=outputs)
                    return result, inputs, outputs
                except Exception:
                    record["status"] = "error"
                    raise
        adapter = EvidenceAnswerAdapter(generator=DeadlineGenerator(), counter=ByteUpperCounter(), max_prompt_tokens=32768)
        result = EvidenceHarnessPipeline(harness=harness, answer_adapter=adapter).query(
            request, plan=plan, deadline=deadline, requires_pixels=args.requires_pixels)
        trace = trace_record(request=request, store=store, config=config, policy_id=policy.policy_id,
                             result=result, provider_calls=backend.calls, synthetic=args.synthetic)
        write_private_json(args.output, trace, private_root=root)
        print(json.dumps({"status": result.answer.response["status"], "harness_status": result.harness.status,
                          "reason": result.harness.reason, "actions": result.harness.state.actions_spent,
                          "trace_sha256": trace["trace_sha256"], "official": False}))
        return 0 if result.harness.status != "ERROR" and result.answer.response.get("status") != "error" else 2
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
