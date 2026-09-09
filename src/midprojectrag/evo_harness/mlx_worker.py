"""Persistent offline MLX Qwen worker for the Evo PRE evaluator.

Protocol is newline-delimited JSON on stdin/stdout. Model/library chatter is
redirected to stderr so stdout remains protocol-only.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import time


def _emit(value: dict) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")
    sys.stdout.flush()


def _request(line: str) -> dict:
    value = json.loads(line)
    if type(value) is not dict or type(value.get("id")) is not int or type(value.get("op")) is not str:
        raise ValueError("worker_request_invalid")
    return value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--model-manifest", required=True, type=Path)
    parser.add_argument("--expected-revision", required=True)
    args = parser.parse_args(argv)

    os.environ.update(
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_TELEMETRY="1",
        TOKENIZERS_PARALLELISM="false",
    )
    # Keep the JSON-line stdout channel clean even if a dependency prints while loading.
    with redirect_stdout(sys.stderr):
        from midprojectrag.evo_harness.runtime import MLXBackend
        backend = MLXBackend(args.model_dir, args.model_manifest, expected_revision=args.expected_revision)
    _emit({"op": "ready", "identity": asdict(backend.identity),
           "load_seconds": backend.load_seconds, "manifest_sha256": backend.manifest_sha256})

    for line in sys.stdin:
        if not line.strip():
            continue
        request_id = None
        try:
            row = _request(line)
            request_id = row["id"]
            op = row["op"]
            if op == "shutdown":
                _emit({"id": request_id, "ok": True, "op": "shutdown"})
                return 0
            if op == "inspect_image":
                request = row.get("request")
                timeout = row.get("timeout")
                if type(request) is not dict or type(timeout) not in (int, float) or timeout <= 0:
                    raise ValueError("worker_visual_args_invalid")
                deadline = time.monotonic() + float(timeout)
                def remaining():
                    value = deadline - time.monotonic()
                    if value <= 0:
                        raise TimeoutError("visual_deadline")
                    return value
                with redirect_stdout(sys.stderr):
                    result = backend.inspect_image(request, remaining=remaining)
                _emit({"id": request_id, "ok": True, "visual": result})
                continue
            messages = row.get("messages")
            if type(messages) is not list:
                raise ValueError("worker_messages_invalid")
            if op == "count":
                with redirect_stdout(sys.stderr):
                    count = backend.count_messages(messages)
                _emit({"id": request_id, "ok": True, "count": count})
                continue
            if op == "complete":
                max_tokens = row.get("max_tokens")
                timeout = row.get("timeout")
                schema = row.get("json_schema")
                if type(max_tokens) is not int or max_tokens < 1 or type(timeout) not in (int, float) or timeout <= 0:
                    raise ValueError("worker_generation_args_invalid")
                if schema is not None and type(schema) is not dict:
                    raise ValueError("worker_schema_invalid")
                with redirect_stdout(sys.stderr):
                    result = backend.complete(messages, max_tokens=max_tokens, timeout=float(timeout), json_schema=schema)
                _emit({"id": request_id, "ok": True, "completion": asdict(result)})
                continue
            raise ValueError("worker_op_invalid")
        except Exception as exc:
            # Never reflect private prompt/source text or arbitrary exception strings.
            from midprojectrag.evo_harness.state import HarnessError
            code = str(exc) if isinstance(exc, HarnessError) else (
                str(exc) if isinstance(exc, ValueError) and str(exc).startswith("worker_") else "worker_error"
            )
            _emit({"id": request_id, "ok": False, "code": code, "error_type": type(exc).__name__})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
