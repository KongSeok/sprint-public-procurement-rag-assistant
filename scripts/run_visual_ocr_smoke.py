"""Bounded one-crop local OCR smoke; recognized text stays in the private root."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from midprojectrag.ingest.common import canonical_json
from midprojectrag.ingest.visual_evidence import load_jsonl_bounded, write_jsonl_artifact
from midprojectrag.ingest.visual_model_manifest import checked_root, file_sha256, verify_manifest
from midprojectrag.ingest.visual_understanding import (
    DARWIN_NETWORK_SANDBOX, LINUX_NETWORK_SANDBOX, PinnedLocalJsonCommandAdapter,
    PpStructureV3Config, VisualRetrievalPolicy,
)
from midprojectrag.ingest.visual_understanding_runner import run_visual_understanding_batch


class CountingAdapter(PinnedLocalJsonCommandAdapter):
    calls = 0

    def infer(self, operation, request):
        self.calls += 1
        return super().infer(operation, request)


def run(args) -> dict:
    private = checked_root(args.private_root)
    if "private" not in private.parts or not private.is_dir():
        raise ValueError("smoke_private_root_required")
    source = checked_root(args.occurrences)
    output = checked_root(args.output_root)
    if not source.is_relative_to(private) or not output.is_relative_to(private) or output == private:
        raise ValueError("smoke_path_escape")
    records = load_jsonl_bounded(source)
    selected = [record for record in records if record["occurrence_id"] == args.occurrence_id]
    if len(selected) != 1 or not selected[0].get("crop_relpath") or selected[0].get("retrieval_status") != "eligible":
        raise ValueError("smoke_requires_one_crop")
    weights = checked_root(args.model_root)
    manifest_hash = verify_manifest(weights)
    config_path = PROJECT_ROOT / "configs/visual/ppocrv5-cpu-minimal.json"
    config_data = json.loads(config_path.read_text())
    config = PpStructureV3Config(**{key: value for key, value in config_data.items()
                                  if key in PpStructureV3Config.__dataclass_fields__})
    if manifest_hash != config.weights_sha256:
        raise ValueError("smoke_model_profile_mismatch")
    python = PROJECT_ROOT / ".venv-ocr/bin/python"
    wrapper = PROJECT_ROOT / "scripts/paddle_ocr_json.py"
    files = [wrapper, config_path, PROJECT_ROOT / "configs/visual/requirements-ocr-cpu.lock",
             PROJECT_ROOT / "src/midprojectrag/ingest/paddle_ocr_runtime.py",
             PROJECT_ROOT / "src/midprojectrag/ingest/visual_model_manifest.py",
             PROJECT_ROOT / "src/midprojectrag/ingest/visual_understanding.py",
             PROJECT_ROOT / "src/midprojectrag/ingest/visual_understanding_runner.py",
             PROJECT_ROOT / "src/midprojectrag/ingest/visual_evidence.py", Path(__file__).resolve()]
    pins = {path: file_sha256(path) for path in files}
    code_hash = hashlib.sha256(canonical_json({str(p.relative_to(PROJECT_ROOT)): h
                                              for p, h in pins.items()}).encode()).hexdigest()
    darwin = platform.system() == "Darwin"
    sandbox = Path("/usr/bin/sandbox-exec" if darwin else "/usr/bin/bwrap")
    adapter = CountingAdapter(command=python, command_sha256=file_sha256(python),
        arguments=("-I", str(wrapper)), pinned_files=pins,
        model_artifact=weights / "model-manifest.json", model_artifact_sha256=manifest_hash,
        network_sandbox_backend=DARWIN_NETWORK_SANDBOX if darwin else LINUX_NETWORK_SANDBOX,
        network_sandbox_command=sandbox, network_sandbox_command_sha256=file_sha256(sandbox),
        timeout_seconds=120)
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    selected_path = output / "selected-occurrence.jsonl"
    if selected_path.exists():
        if load_jsonl_bounded(selected_path) != selected:
            raise ValueError("smoke_selected_source_changed")
    else:
        write_jsonl_artifact(selected, output=selected_path, private_root=private)
    started = time.monotonic()
    metadata = run_visual_understanding_batch(private_root=private, occurrences_path=selected_path,
        output_root=output / "evidence", adapter_code_sha256=code_hash, ocr_adapter=adapter,
        ocr_config=config, policy=VisualRetrievalPolicy())
    cold_seconds = time.monotonic() - started
    peak_rss_bytes = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * (1 if darwin else 1024)
    first_calls = adapter.calls
    started = time.monotonic()
    repeated = run_visual_understanding_batch(private_root=private, occurrences_path=selected_path,
        output_root=output / "evidence", adapter_code_sha256=code_hash, ocr_adapter=adapter,
        ocr_config=config, policy=VisualRetrievalPolicy())
    if metadata != repeated or adapter.calls != first_calls:
        raise ValueError("smoke_cache_reuse_failed")
    evidence = load_jsonl_bounded(output / "evidence/ocr-evidence-v1.jsonl")
    if (len(evidence) != 1 or evidence[0]["status"] != "success"
            or not evidence[0]["text_items"] or evidence[0]["table_cells"]
            or evidence[0]["occurrence_id"] != selected[0]["occurrence_id"]
            or evidence[0]["crop_sha256"] != selected[0]["crop_sha256"]):
        raise ValueError("smoke_real_ocr_result_not_successful")
    receipt = {"schema_version":"1.0", "status":"PASS_TECHNICAL_SMOKE_ONLY",
        "counts":metadata["counts"], "text_items":len(evidence[0]["text_items"]),
        "cold_seconds":round(cold_seconds, 3) if first_calls else None,
        "repeat_seconds":round(time.monotonic()-started, 3),
        "peak_child_rss_bytes":peak_rss_bytes, "inference_calls":first_calls,
        "repeat_inference_calls":adapter.calls-first_calls, "model_manifest_sha256":manifest_hash,
        "source_occurrences_sha256":file_sha256(source), "adapter_code_sha256":code_hash,
        "runtime_lock_sha256":file_sha256(PROJECT_ROOT / "configs/visual/requirements-ocr-cpu.lock"),
        "network_sandbox":adapter.identity["network_sandbox_backend"],
        "device":"cpu", "worker_count":1, "recognition_batch_size":1, "timeout_seconds":120,
        "external_api_calls":0, "caption_calls":0, "quality_gate":"NOT_EVALUATED",
        "active_runtime_changed":False, "note":"peak RSS is one child, not deployment budget proof"}
    # This local receipt is private; stdout is the same aggregate-only content.
    receipt_path = output / ("receipt.json" if first_calls else "reuse-receipt.json")
    try:
        fd = os.open(receipt_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass  # Preserve the first receipt of each kind on subsequent cache-only checks.
    else:
        with os.fdopen(fd, "w") as handle:
            json.dump(receipt, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--occurrences", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--occurrence-id", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(run(args), ensure_ascii=False))
        return 0
    except Exception as error:
        # Exception message is not safe to print: only known exception class names.
        print(json.dumps({"status":"failed", "error_type":type(error).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
