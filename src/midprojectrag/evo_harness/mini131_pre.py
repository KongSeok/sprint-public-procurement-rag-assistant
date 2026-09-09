"""Prospective Mini131 PRE adapter for the frozen untrained EvoHarness candidate."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
import math
import os
from pathlib import Path
from statistics import fmean, median
import subprocess
import time
from typing import Any, Mapping

from midprojectrag.local_mini131_baseline import verify_suite
from .experience import Experience
from .runner import EpisodeRunner
from .runtime import load_hotline_tools
from .policy import AnswerComposer, LLMPolicy
from .state import Budgets
from .worker_backend import PersistentMLXBackend

SCHEMA_VERSION = "evo-mini131-pre-v1"
SUPPORTED_TEXT_LANES = frozenset({"core40", "supplemental_answer_legacy", "supplemental_answer_rerun"})
UNSUPPORTED = {
    "supplemental_set_rerun": "exhaustive_set_tool_missing",
    "visual": "full_visual_index_missing",
    "corpus_analytics": "analytics_tool_missing",
}
CORE_RUNTIME_PATHS = (
    "src/midprojectrag/evo_harness/policy.py",
    "src/midprojectrag/evo_harness/runner.py",
    "src/midprojectrag/evo_harness/runtime.py",
    "src/midprojectrag/evo_harness/state.py",
    "src/midprojectrag/evo_harness/tools.py",
    "src/midprojectrag/evo_harness/visual.py",
    "configs/rag/evo-hotline-qwen35-v1.json",
)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value: Any) -> str:
    return sha256(_canonical(value).encode()).hexdigest()


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lo = int(math.floor(pos)); hi = int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _secure_append(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
        stream.write(_canonical(dict(value)) + "\n")
        stream.flush(); os.fsync(stream.fileno())


def _secure_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + ".tmp")
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(dict(value), stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
    os.replace(temp, path)


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                value = json.loads(line)
                if type(value) is not dict:
                    raise ValueError("pre_record_invalid")
                rows.append(value)
    ids = [row.get("case_id") for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("pre_duplicate_case_record")
    return rows


RUNTIME_REPAIR_CODES = frozenset({"policy_context_budget_exceeded", "policy_attempt_budget_exhausted"})


def runtime_failure_case_ids(records: list[dict[str, Any]]) -> tuple[str, ...]:
    """Select PRE runtime exhaustion only; answer/gold quality is irrelevant."""
    selected = []
    for row in records:
        result = row.get("result")
        if (row.get("classification") == "executed_text" and type(result) is dict
                and result.get("status") == "budget_exhausted" and result.get("code") in RUNTIME_REPAIR_CODES):
            case_id = row.get("case_id")
            if type(case_id) is not str or not case_id:
                raise ValueError("pre_runtime_failure_case_id_invalid")
            selected.append(case_id)
    if len(selected) != len(set(selected)):
        raise ValueError("pre_runtime_failure_duplicate_case")
    return tuple(selected)


def _required_docs(case) -> list[str]:
    if case.lane == "core40":
        value = case.source.get("gold", {}).get("required_doc_ids", [])
    elif case.lane.startswith("supplemental_answer"):
        value = case.source.get("required_doc_ids", [])
    else:
        value = []
    if type(value) is not list or any(type(item) is not str for item in value):
        raise ValueError("pre_required_docs_invalid")
    return sorted(set(value))


def _decision(case) -> str | None:
    value = case.source.get("gold", {}).get("decision")
    return value if value in {"answer", "abstain"} else None


def _base_request(template: Mapping[str, Any]) -> dict[str, Any]:
    result = {"question": template["question"], "history": deepcopy(template.get("history", [])),
              "document_scope": deepcopy(template["document_scope"]),
              "options": {"max_citations": 3}}
    return result


def _is_followup(case) -> bool:
    return case.lane == "core40" and case.source.get("task_type") == "follow_up"


def _end_to_end_followup(runner: EpisodeRunner, case) -> tuple[dict, dict | None]:
    template = case.request_template
    if not isinstance(template, Mapping):
        raise ValueError("pre_followup_request_missing")
    history = list(template.get("history", []))
    users = [turn for turn in history if turn.get("role") == "user"]
    assistants = [turn for turn in history if turn.get("role") == "assistant"]
    if not users or not assistants or type(users[-1].get("content")) is not str:
        raise ValueError("pre_followup_history_invalid")
    prior_request = {"question": users[-1]["content"], "history": [],
                     "document_scope": deepcopy(template["document_scope"]),
                     "options": {"max_citations": 3}}
    prior = runner.run(prior_request, record_trajectory=False)
    if prior.get("status") != "answered" or type(prior.get("response")) is not dict:
        return {"status": "error", "code": "prior_turn_failed", "usage": {}, "actions": [],
                "wall_seconds": 0.0, "response": None}, prior
    response = prior["response"]
    cited_docs = response.get("cited_doc_ids", [])
    prior_state = response.get("prior_citation_state", {})
    cited_ids = prior_state.get("cited_evidence_ids", [])
    if not cited_docs or not cited_ids:
        return {"status": "error", "code": "prior_turn_citations_missing", "usage": {}, "actions": [],
                "wall_seconds": 0.0, "response": None}, prior
    assistant_turn = {"turn_id": assistants[-1].get("turn_id", "candidate-prior"), "role": "assistant",
                      "content": response.get("answer", ""), "cited_doc_ids": cited_docs,
                      "cited_evidence_ids": cited_ids}
    follow = {"question": template["question"],
              "history": [deepcopy(users[-1]), assistant_turn],
              "document_scope": deepcopy(template["document_scope"]),
              "options": {"max_citations": 3}}
    return runner.run(follow, follow_up=True, record_trajectory=False), prior


def _execution_record(case, result: dict, *, elapsed: float, prior: dict | None = None) -> dict:
    required = _required_docs(case)
    response = result.get("response") if type(result.get("response")) is dict else {}
    cited = sorted(set(response.get("cited_doc_ids", []) if type(response.get("cited_doc_ids")) is list else []))
    retrieved = set()
    for event in result.get("actions", []):
        observation = event.get("observation")
        if type(observation) is dict:
            for row in observation.get("candidates", []):
                if type(row) is dict and type(row.get("doc_id")) is str:
                    retrieved.add(row["doc_id"])
    expected = _decision(case)
    decision_match = ((expected == "answer" and result.get("status") == "answered") or
                      (expected == "abstain" and result.get("status") == "abstained")) if expected else None
    return {"schema_version": SCHEMA_VERSION, "case_id": case.case_id, "lane": case.lane,
            "task_type": case.source.get("task_type"), "source_sha256": case.source_sha256,
            "classification": "executed_text", "execution_mode": "end_to_end_followup" if _is_followup(case) else "direct",
            "expected_decision": expected, "required_doc_ids": required,
            "observed": {"status": result.get("status"), "code": result.get("code"),
                         "decision_match": decision_match, "cited_doc_ids": cited,
                         "retrieved_doc_ids": sorted(retrieved),
                         "required_doc_citation_recall": (len(set(required) & set(cited)) / len(required)) if required else None,
                         "all_required_docs_cited": set(required) <= set(cited) if required else None,
                         "required_doc_retrieval_recall": (len(set(required) & retrieved) / len(required)) if required else None,
                         "all_required_docs_retrieved": set(required) <= retrieved if required else None,
                         "case_wall_seconds": elapsed},
            "result": result, "prior_result": prior}


def _unsupported_record(case) -> dict:
    return {"schema_version": SCHEMA_VERSION, "case_id": case.case_id, "lane": case.lane,
            "task_type": case.source.get("task_type"), "source_sha256": case.source_sha256,
            "classification": "unsupported_specialist", "reason": UNSUPPORTED[case.lane]}


def _usage(records: list[dict]) -> dict[str, int]:
    total: Counter = Counter()
    for record in records:
        for key in ("prior_result", "result"):
            value = record.get(key)
            if type(value) is dict and type(value.get("usage")) is dict:
                for name, count in value["usage"].items():
                    if type(count) is int and not isinstance(count, bool):
                        total[name] += count
    return dict(sorted(total.items()))


def aggregate(records: list[dict], *, candidate_commit: str, source_suite_sha256: str, runner_commit: str | None = None,
              tool_load_seconds: float, model_load_seconds: float, worker_manifest_sha256: str | None,
              parser_status: str = "not_run_separate_etl") -> dict[str, Any]:
    executed = [row for row in records if row.get("classification") == "executed_text"]
    unsupported = [row for row in records if row.get("classification") == "unsupported_specialist"]
    latencies = [float(row["observed"]["case_wall_seconds"]) for row in executed]
    decision = [row["observed"]["decision_match"] for row in executed if row["observed"].get("decision_match") is not None]
    citation = [row["observed"]["required_doc_citation_recall"] for row in executed if row["observed"].get("required_doc_citation_recall") is not None]
    retrieval = [row["observed"]["required_doc_retrieval_recall"] for row in executed if row["observed"].get("required_doc_retrieval_recall") is not None]
    all_cited = [row["observed"]["all_required_docs_cited"] for row in executed if row["observed"].get("all_required_docs_cited") is not None]
    all_retrieved = [row["observed"]["all_required_docs_retrieved"] for row in executed if row["observed"].get("all_required_docs_retrieved") is not None]
    lanes = Counter(row.get("lane") for row in records)
    statuses = Counter(row.get("observed", {}).get("status") for row in executed)
    return {"schema_version": SCHEMA_VERSION, "candidate_commit": candidate_commit, "runner_commit": runner_commit or candidate_commit,
            "source_suite_sha256": source_suite_sha256, "records_sha256": _hash(records),
            "semantic_answer_quality": "unjudged", "training_stage": "prompt_time_untrained",
            "inventory": {"rag_total": 129, "parser_total": 2, "overall_total": 131,
                          "records": len(records), "executed_text": len(executed),
                          "unsupported_specialist": len(unsupported), "parser_status": parser_status,
                          "lane_counts": dict(sorted(lanes.items()))},
            "status_counts": dict(sorted((str(k), v) for k, v in statuses.items())),
            "objective": {"decision_match_rate": (sum(decision) / len(decision)) if decision else None,
                          "required_doc_citation_recall_mean": fmean(citation) if citation else None,
                          "all_required_docs_cited_rate": (sum(all_cited) / len(all_cited)) if all_cited else None,
                          "required_doc_retrieval_recall_mean": fmean(retrieval) if retrieval else None,
                          "all_required_docs_retrieved_rate": (sum(all_retrieved) / len(all_retrieved)) if all_retrieved else None},
            "usage": _usage(records),
            "latency_seconds": {"count": len(latencies), "mean": fmean(latencies) if latencies else None,
                                "p50": _percentile(latencies, .50), "p95": _percentile(latencies, .95)},
            "setup_seconds": {"retrieval_tools": tool_load_seconds, "qwen_model": model_load_seconds},
            "worker_manifest_sha256": worker_manifest_sha256,
            "limitations": ["Mini131 is a previously exposed historical benchmark, not a sealed holdout.",
                            "Semantic answer quality is unjudged until the frozen GPT-5.6 Sol judge is applied.",
                            "Set13, visual10 and analytics10 remain explicit unsupported specialist lanes.",
                            "Follow-up10 uses end-to-end prior-turn replay because fixed history lacks current-runtime evidence IDs."]}


def _verify_candidate(repo_root: Path, candidate_commit: str) -> str:
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_root, text=True).strip()
    ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", candidate_commit, actual], cwd=repo_root)
    if ancestor.returncode != 0:
        raise ValueError("pre_candidate_not_ancestor")
    result = subprocess.run(["git", "diff", "--quiet", candidate_commit, "--", *CORE_RUNTIME_PATHS], cwd=repo_root)
    if result.returncode != 0:
        raise ValueError("pre_candidate_core_dirty")
    return actual


def run(*, repo_root: Path, source_repo_root: Path, source_config: Path, runtime_data_root: Path,
        artifact_dir: Path, mlx_python: Path, model_dir: Path, model_manifest: Path,
        expected_revision: str, output_dir: Path, candidate_commit: str,
        limit: int | None = None) -> dict[str, Any]:
    repo_root = repo_root.resolve(); source_repo_root = source_repo_root.resolve()
    runtime_data_root = runtime_data_root.resolve(); output_dir = output_dir.resolve()
    runner_commit = _verify_candidate(repo_root, candidate_commit)
    if "private" not in output_dir.parts or output_dir.is_symlink():
        raise ValueError("pre_private_output_required")
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    suite = verify_suite(repo_root=source_repo_root, config_path=source_config.resolve())
    if len(suite.cases) != 129:
        raise ValueError("pre_suite_count_mismatch")
    records_path = output_dir / "records.jsonl"
    records = _read_records(records_path)
    completed = {row["case_id"] for row in records}

    tool_started = time.monotonic()
    tools = load_hotline_tools(runtime_data_root, artifact_dir.resolve(), device="mps")
    tool_load = time.monotonic() - tool_started
    with PersistentMLXBackend(python=mlx_python, model_dir=model_dir, model_manifest=model_manifest,
                              expected_revision=expected_revision, startup_timeout=30.0,
                              stderr_path=output_dir / "mlx-worker.stderr") as backend:
        runner = EpisodeRunner(tools, LLMPolicy(backend), AnswerComposer(backend),
                               budgets=Budgets(), experience=Experience())
        attempted_new = 0
        for case in suite.cases:
            if case.case_id in completed:
                continue
            if limit is not None and attempted_new >= limit:
                break
            if case.lane in UNSUPPORTED:
                record = _unsupported_record(case)
            elif case.lane in SUPPORTED_TEXT_LANES:
                started = time.monotonic()
                if _is_followup(case):
                    result, prior = _end_to_end_followup(runner, case)
                else:
                    result = runner.run(_base_request(case.request_template), record_trajectory=False)
                    prior = None
                record = _execution_record(case, result, elapsed=time.monotonic() - started, prior=prior)
            else:
                raise ValueError("pre_unknown_lane")
            _secure_append(records_path, record)
            records.append(record); completed.add(case.case_id); attempted_new += 1
            progress = {"schema_version": SCHEMA_VERSION, "candidate_commit": candidate_commit,
                        "completed_records": len(records), "rag_total": 129,
                        "last_case_id": case.case_id, "last_lane": case.lane,
                        "semantic_answer_quality": "unjudged"}
            _secure_json(output_dir / "progress.json", progress)
        summary = aggregate(records, candidate_commit=candidate_commit, runner_commit=runner_commit,
                            source_suite_sha256=suite.eval_set_sha256, tool_load_seconds=tool_load,
                            model_load_seconds=backend.load_seconds,
                            worker_manifest_sha256=backend.manifest_sha256)
    _secure_json(output_dir / "aggregate.json", summary)
    return summary
