"""Private-output CLI, owned-process budget, and explicit live synthetic-corpus smoke."""
from __future__ import annotations
import argparse
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import sys
import time

from midprojectrag.hotline import run_supervised
from .experience import Experience
from .policy import MODEL_ID
from .runtime import MLXBackend, compose_runtime, load_hotline_tools, synthetic_tools
from .state import Budgets, HarnessError, json_object, exact


def _seconds(raw):
    try:
        value = float(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("finite budget required") from exc
    if not math.isfinite(value) or not 0 < value <= 120:
        raise argparse.ArgumentTypeError("budget must be in (0,120]")
    return value


def _deadline(raw):
    try:
        value = float(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("finite deadline required") from exc
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("finite positive deadline required")
    return value


def _private(path, data, *, new=False):
    data = Path(data).resolve()
    base = (data/"private").resolve()
    value = Path(path).resolve()
    if base == data or not base.is_relative_to(data) or value == base or not value.is_relative_to(base):
        raise ValueError("private_path_required")
    if new and value.exists():
        raise FileExistsError("output_already_exists")
    return value


def _write_new(path: Path, payload: dict):
    descriptor = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(descriptor,"w",encoding="utf-8") as stream:
        json.dump(payload,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write("\n")


def load_profile(path):
    value = exact(json_object(Path(path).read_text()), {"schema_version", "profile_id", "canonical_model", "artifact_model", "artifact_revision", "enable_thinking", "training_stage", "budgets", "retrieval"})
    if (value["schema_version"] != "1.0" or value["profile_id"] != "evo-hotline-qwen35-v1"
            or value["canonical_model"] != MODEL_ID or value["artifact_model"] != "mlx-community/Qwen3.5-9B-4bit"
            or value["enable_thinking"] is not False or value["training_stage"] != "prompt_time"):
        raise ValueError("unsupported_evo_profile")
    budget = Budgets(**value["budgets"])
    exact(value["retrieval"], {"lane_k", "window_chars"})
    if value["retrieval"] != {"lane_k":10,"window_chars":1600}:
        raise ValueError("unsupported_retrieval_profile")
    import re
    if not re.fullmatch(r"[0-9a-f]{40}", str(value["artifact_revision"])):
        raise ValueError("pinned_model_revision_required")
    return value, budget


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parents[3]/"configs/rag/evo-hotline-qwen35-v1.json")
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--model-manifest", required=True, type=Path)
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--experience", type=Path)
    parser.add_argument("--mode", choices=("policy","fixed"),default="policy")
    parser.add_argument("--follow-up", action="store_true")
    parser.add_argument("--record-trajectory", action="store_true")
    parser.add_argument("--synthetic-corpus", action="store_true",
                        help="real Qwen policy, synthetic documents and fake retrieval lanes; NOT a production RAG benchmark")
    parser.add_argument("--timeout-seconds",type=_seconds,default=120.0)
    parser.add_argument("--worker-deadline",type=_deadline,default=None,help=argparse.SUPPRESS)
    args=parser.parse_args(argv)
    os.umask(0o077)
    profile, configured_budget = load_profile(args.config)
    args.timeout_seconds = min(args.timeout_seconds, configured_budget.seconds)
    target=_private(args.output_dir,args.data_dir,new=True)
    if args.request:
        request_path=_private(args.request,args.data_dir)
        if not request_path.is_file() or request_path.stat().st_size>1_048_576:
            raise ValueError("request_file_invalid")
        if request_path.is_relative_to(target):
            raise ValueError("request_output_overlap")
    elif not args.synthetic_corpus:
        parser.error("--request is required except for explicit synthetic-corpus smoke")
    if args.experience:
        _private(args.experience,args.data_dir)
    artifacts=args.artifacts or args.data_dir/"private/evidence-harness/v1-rc0-20260903-01"
    if not args.synthetic_corpus:
        artifact_path=_private(artifacts,args.data_dir)
        if target==artifact_path or target.is_relative_to(artifact_path) or artifact_path.is_relative_to(target):
            raise ValueError("artifact_output_overlap")
    if args.worker_deadline is not None:
        if args.worker_deadline<=time.monotonic():
            raise TimeoutError("worker_deadline")
        return _worker(args,target,artifacts)
    end=time.monotonic()+args.timeout_seconds
    cmd=[sys.executable,"-m","midprojectrag.evo_harness.cli","--config",str(args.config.resolve()),"--data-dir",str(args.data_dir.resolve()),
         "--output-dir",str(target),"--model-dir",str(args.model_dir.resolve()),
         "--model-manifest",str(args.model_manifest.resolve()),"--timeout-seconds",str(args.timeout_seconds),
         "--worker-deadline",str(end),"--mode",args.mode]
    for name in ("request","artifacts","experience"):
        if getattr(args,name) is not None:
            cmd += ["--"+name.replace("_","-"),str(getattr(args,name).resolve())]
    for name in ("follow_up","record_trajectory","synthetic_corpus"):
        if getattr(args,name):
            cmd += ["--"+name.replace("_","-")]
    receipt=run_supervised(cmd,timeout_seconds=args.timeout_seconds)
    if target.is_dir():
        _write_new(target/"supervisor.json",receipt)
    print(json.dumps({"supervisor_status":receipt["status"],"exit_code":receipt["exit_code"]}))
    return receipt["exit_code"]


def _worker(args,target,artifacts):
    started=time.monotonic()
    deadline=min(args.worker_deadline,started+args.timeout_seconds)
    target.mkdir(mode=0o700,parents=True,exist_ok=False)
    _write_new(target/"started.json",{"model":MODEL_ID,"started_monotonic":started,
               "deadline":deadline,"synthetic_corpus":args.synthetic_corpus})
    result={"status":"error","code":"initialization_not_completed"}
    try:
        request=(json_object(args.request.read_text(),maximum=1_048_576) if args.request else
                 {"question":"Compare the budget and performance period of Alpha and Beta. Cite both documents.",
                  "document_scope":{"mode":"explicit","doc_ids":["alpha","beta"]}})
        from midprojectrag.runtime_integrity import RuntimeRequest
        RuntimeRequest.from_dict(request)
        profile, configured_budget = load_profile(args.config)
        backend=MLXBackend(args.model_dir,args.model_manifest,expected_revision=profile["artifact_revision"])
        if time.monotonic()>=deadline:
            raise TimeoutError("initialization_deadline")
        tools=synthetic_tools() if args.synthetic_corpus else load_hotline_tools(args.data_dir,artifacts)
        experience=Experience.from_reviewed(json_object(args.experience.read_text(),maximum=1_048_576)) if args.experience else Experience()
        runner=compose_runtime(backend,tools,budgets=Budgets(**(profile["budgets"]|{"seconds":args.timeout_seconds})),experience=experience)
        setup=time.monotonic()-started
        if args.mode=="fixed":
            result=runner.run_fixed(request,follow_up=args.follow_up,deadline=deadline)
        else:
            result=runner.run(request,follow_up=args.follow_up,deadline=deadline,record_trajectory=args.record_trajectory)
        from .runtime import file_hash
        result.update(profile_sha256=file_hash(args.config),setup_seconds=setup,model_load_seconds=backend.load_seconds,
                      model_manifest_sha256=backend.manifest_sha256,
                      retrieval_kind="synthetic_public_hybrid" if args.synthetic_corpus else "existing_hotline_artifacts",
                      canonical_model_revision=None,converted_artifact_revision=backend.identity.revision)
    except TimeoutError:
        result={"status":"timeout","code":"initialization_deadline"}
    except Exception as exc:
        result={"status":"error","code":str(exc) if isinstance(exc,HarnessError) else "initialization_error",
                "error_type":type(exc).__name__}
    result["total_worker_seconds"]=time.monotonic()-started
    _write_new(target/"result.json",result)
    print(json.dumps({"status":result["status"],"code":result.get("code"),
                      "usage":result.get("usage"),"total_worker_seconds":result["total_worker_seconds"]}))
    return 0 if result["status"] in {"answered","abstained","needs_clarification"} else 1


if __name__=="__main__":
    raise SystemExit(main())
