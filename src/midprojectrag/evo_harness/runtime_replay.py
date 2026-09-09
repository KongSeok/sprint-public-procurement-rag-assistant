"""Replay only frozen PRE runtime-exhaustion cases on a repaired candidate."""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import time
from typing import Any

from midprojectrag.local_mini131_baseline import verify_suite
from .experience import Experience
from .mini131_pre import (_base_request, _end_to_end_followup, _is_followup,
    _read_records, _verify_candidate, runtime_failure_case_ids)
from .policy import AnswerComposer, LLMPolicy
from .runner import EpisodeRunner
from .runtime import load_hotline_tools
from .state import Budgets
from .worker_backend import PersistentMLXBackend

SCHEMA = "evo-runtime-failure-replay-v1"


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash_file(path: Path) -> str:
    h=sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""): h.update(block)
    return h.hexdigest()


def _safe_result(result: dict, elapsed: float) -> dict:
    usage=result.get("usage") if type(result.get("usage")) is dict else {}
    actions=[]
    for row in result.get("actions",[]):
        if type(row) is dict:
            actions.append({"tool":row.get("tool"),"outcome":row.get("outcome"),"code":row.get("code")})
    return {"status":result.get("status"),"code":result.get("code"),"wall_seconds":elapsed,
            "usage":{k:v for k,v in usage.items() if type(v) is int and not isinstance(v,bool)},
            "actions":actions}


def replay_record(case, before: dict, result: dict, elapsed: float) -> dict:
    old=before.get("result") if type(before.get("result")) is dict else {}
    return {"schema_version":SCHEMA,"case_id":case.case_id,"lane":case.lane,
            "source_sha256":case.source_sha256,"selection":{"status":old.get("status"),"code":old.get("code")},
            "after":_safe_result(result,elapsed),"semantic_answer_quality":"not_evaluated"}


def summarize(records: list[dict], *, source_pre_candidate: str, source_records_sha256: str,
              repaired_candidate: str, repaired_runner_commit: str, source_suite_sha256: str) -> dict:
    before=Counter(r["selection"]["code"] for r in records)
    after_status=Counter(r["after"]["status"] for r in records)
    after_code=Counter(str(r["after"].get("code")) for r in records if r["after"].get("code") is not None)
    usage=Counter()
    for r in records:
        usage.update(r["after"]["usage"])
    body={"schema_version":SCHEMA,"selection_basis":"frozen_pre_runtime_terminal_code_only",
          "semantic_answer_quality":"not_evaluated","source_pre_candidate_commit":source_pre_candidate,
          "source_pre_records_sha256":source_records_sha256,"source_suite_sha256":source_suite_sha256,
          "repaired_candidate_commit":repaired_candidate,"repaired_runner_commit":repaired_runner_commit,"selected_count":len(records),
          "before_code_counts":dict(sorted(before.items())),"after_status_counts":dict(sorted(after_status.items())),
          "after_code_counts":dict(sorted(after_code.items())),"usage":dict(sorted(usage.items()))}
    return body|{"summary_sha256":sha256(_canonical(body).encode()).hexdigest()}


def run(*, repo_root: Path, source_repo_root: Path, source_config: Path,
        runtime_data_root: Path, artifact_dir: Path, mlx_python: Path,
        model_dir: Path, model_manifest: Path, expected_revision: str,
        source_records: Path, source_aggregate: Path, output_dir: Path,
        repaired_candidate: str, limit: int | None = None) -> dict:
    runner_commit=_verify_candidate(repo_root.resolve(),repaired_candidate)
    if "private" not in output_dir.resolve().parts:
        raise ValueError("runtime_replay_private_output_required")
    rows=_read_records(source_records.resolve())
    aggregate=json.loads(source_aggregate.read_text())
    if aggregate.get("candidate_commit") is None or aggregate.get("records_sha256") is None:
        raise ValueError("runtime_replay_source_aggregate_invalid")
    if aggregate["records_sha256"] != sha256(_canonical(rows).encode()).hexdigest():
        raise ValueError("runtime_replay_source_records_mismatch")
    ids=list(runtime_failure_case_ids(rows))
    if limit is not None:
        if type(limit) is not int or limit < 1: raise ValueError("runtime_replay_limit_invalid")
        ids=ids[:limit]
    before={r["case_id"]:r for r in rows if r.get("case_id") in set(ids)}
    suite=verify_suite(repo_root=source_repo_root.resolve(),config_path=source_config.resolve())
    cases={c.case_id:c for c in suite.cases}
    if set(ids)-set(cases): raise ValueError("runtime_replay_case_missing")
    output_dir.mkdir(parents=True,exist_ok=False,mode=0o700)
    tools=load_hotline_tools(runtime_data_root.resolve(),artifact_dir.resolve(),device="mps")
    records=[]
    with PersistentMLXBackend(python=mlx_python,model_dir=model_dir,model_manifest=model_manifest,
                              expected_revision=expected_revision,startup_timeout=30.0,
                              stderr_path=output_dir/"mlx-worker.stderr") as backend:
        runner=EpisodeRunner(tools,LLMPolicy(backend),AnswerComposer(backend),budgets=Budgets(),experience=Experience())
        for case_id in ids:
            case=cases[case_id]; started=time.monotonic()
            if _is_followup(case): result,_prior=_end_to_end_followup(runner,case)
            else: result=runner.run(_base_request(case.request_template),record_trajectory=False)
            record=replay_record(case,before[case_id],result,time.monotonic()-started)
            records.append(record)
            with (output_dir/"records.jsonl").open("a",encoding="utf-8") as f:
                f.write(_canonical(record)+"\n"); f.flush()
    summary=summarize(records,source_pre_candidate=aggregate["candidate_commit"],
                      source_records_sha256=aggregate["records_sha256"],repaired_candidate=repaired_candidate,
                      repaired_runner_commit=runner_commit,source_suite_sha256=suite.eval_set_sha256)
    (output_dir/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,sort_keys=True,indent=2)+"\n")
    return summary
