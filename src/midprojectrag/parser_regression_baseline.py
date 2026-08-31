"""Deterministic current-parser regression for the two legacy fallback cases.

The original C21/C22 assets asserted a specific pyhwp failure and native
fallback.  The refined source of truth now uses the pinned ``rhwp`` adapter as
the primary HWP parser.  This lane therefore checks the user-visible invariant:
both historically troublesome documents are fully extracted and indexable in
the current canonical manifest.  It intentionally does not claim that an
obsolete fallback branch ran.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from midprojectrag.ingest.common import canonical_json, read_jsonl, sha256_file


SCHEMA_VERSION = "1.0"
BASELINE_ID = "parser-regression-rhwp-v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _repo_root(config_path: Path) -> Path:
    for candidate in (config_path.resolve().parent, *config_path.resolve().parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise ValueError("repository_root_not_found")


def _resolve(repo_root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError("parser_regression_path_invalid")
    path = (repo_root / value).resolve()
    try:
        path.relative_to(repo_root.resolve())
    except ValueError as error:
        raise ValueError("parser_regression_path_outside_repository") from error
    return path


def _load_config(path: Path) -> tuple[Path, dict[str, Any]]:
    repo_root = _repo_root(path)
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("parser_regression_config_invalid") from error
    if not isinstance(config, dict) or set(config) != {
        "schema_version", "baseline_id", "contract", "artifacts", "cases", "outputs"
    }:
        raise ValueError("parser_regression_config_invalid")
    if config.get("schema_version") != SCHEMA_VERSION or config.get("baseline_id") != BASELINE_ID:
        raise ValueError("parser_regression_config_invalid")
    contract = config.get("contract")
    if contract != {
        "current_invariant": "canonical_rhwp_extraction_and_indexability",
        "legacy_fallback_activation_scored": False,
        "semantic_judge_required": False,
    }:
        raise ValueError("parser_regression_contract_invalid")
    artifacts = config.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {"manifest", "manifest_sha256"}:
        raise ValueError("parser_regression_artifacts_invalid")
    if not isinstance(artifacts.get("manifest_sha256"), str) or not SHA256_RE.fullmatch(
        artifacts["manifest_sha256"]
    ):
        raise ValueError("parser_regression_artifacts_invalid")
    cases = config.get("cases")
    if not isinstance(cases, list) or len(cases) != 2:
        raise ValueError("parser_regression_cases_invalid")
    required = {
        "case_id", "doc_id", "input_sha256", "expected_extractor", "expected_status",
        "expected_index_eligible", "expected_block_count", "expected_primary_text_chars",
        "expected_page_count",
    }
    if any(not isinstance(row, dict) or set(row) != required for row in cases):
        raise ValueError("parser_regression_cases_invalid")
    if {row["case_id"] for row in cases} != {"C21", "C22"}:
        raise ValueError("parser_regression_cases_invalid")
    outputs = config.get("outputs")
    if not isinstance(outputs, dict) or set(outputs) != {"receipt"}:
        raise ValueError("parser_regression_outputs_invalid")
    return repo_root, config


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def run(config_path: Path) -> dict[str, Any]:
    repo_root, config = _load_config(config_path)
    artifacts = config["artifacts"]
    manifest_path = _resolve(repo_root, artifacts["manifest"])
    if sha256_file(manifest_path) != artifacts["manifest_sha256"]:
        raise ValueError("parser_regression_manifest_hash_mismatch")
    rows = read_jsonl(manifest_path)
    by_doc_id: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        doc_id = row.get("doc_id")
        if isinstance(doc_id, str):
            if doc_id in by_doc_id:
                raise ValueError("parser_regression_duplicate_doc_id")
            by_doc_id[doc_id] = row

    results: list[dict[str, Any]] = []
    for expected in config["cases"]:
        row = by_doc_id.get(expected["doc_id"])
        checks: dict[str, bool] = {}
        if row is None:
            checks["manifest_row_present"] = False
            results.append({"case_id": expected["case_id"], "doc_id": expected["doc_id"], "passed": False, "checks": checks})
            continue
        checks = {
            "manifest_row_present": True,
            "input_sha256_match": row.get("input_hash") == expected["input_sha256"],
            "status_match": row.get("status") == expected["expected_status"],
            "extractor_match": row.get("extractor") == expected["expected_extractor"],
            "index_eligible_match": row.get("index_eligible") is expected["expected_index_eligible"],
            "block_count_match": row.get("block_count") == expected["expected_block_count"],
            "primary_text_chars_match": row.get("primary_text_chars") == expected["expected_primary_text_chars"],
            "page_count_match": row.get("page_count") == expected["expected_page_count"],
            "error_absent": row.get("error_code") is None,
        }
        output_relpath = row.get("output_relpath")
        block_path = _resolve(repo_root / "resources/data_refined", output_relpath) if isinstance(output_relpath, str) else None
        checks["block_file_present"] = bool(block_path and block_path.is_file())
        if block_path and block_path.is_file():
            actual_block_count = sum(1 for _ in read_jsonl(block_path))
            checks["block_file_count_match"] = actual_block_count == expected["expected_block_count"]
            block_sha256: str | None = sha256_file(block_path)
        else:
            checks["block_file_count_match"] = False
            block_sha256 = None
        results.append(
            {
                "case_id": expected["case_id"],
                "doc_id": expected["doc_id"],
                "passed": all(checks.values()),
                "checks": checks,
                "observed": {
                    "status": row.get("status"),
                    "extractor": row.get("extractor"),
                    "index_eligible": row.get("index_eligible"),
                    "block_count": row.get("block_count"),
                    "primary_text_chars": row.get("primary_text_chars"),
                    "page_count": row.get("page_count"),
                    "block_file_sha256": block_sha256,
                },
            }
        )

    receipt = {
        "schema_version": SCHEMA_VERSION,
        "baseline_id": BASELINE_ID,
        "passed": all(row["passed"] for row in results),
        "scoring_contract": {
            "lane": "deterministic_etl_regression",
            "current_invariant": "canonical_rhwp_extraction_and_indexability",
            "legacy_fallback_activation_scored": False,
            "semantic_judge_required": False,
        },
        "artifacts": {
            "config_sha256": sha256_file(config_path),
            "manifest_sha256": sha256_file(manifest_path),
        },
        "counts": {
            "total": len(results),
            "passed": sum(row["passed"] for row in results),
            "failed": sum(not row["passed"] for row in results),
        },
        "cases": results,
    }
    output_path = _resolve(repo_root, config["outputs"]["receipt"])
    _atomic_write_json(output_path, receipt)
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the two-case current parser regression")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("evaluation/baselines/parser-regression-rhwp-v1/config.json"),
    )
    args = parser.parse_args(argv)
    try:
        receipt = run(args.config)
        print(canonical_json(receipt))
        return 0 if receipt["passed"] else 1
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        code = str(error)
        if re.fullmatch(r"[a-z][a-z0-9_]{0,127}", code) is None:
            code = "parser_regression_failed"
        print(canonical_json({"schema_version": SCHEMA_VERSION, "passed": False, "error": {"code": code}}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
