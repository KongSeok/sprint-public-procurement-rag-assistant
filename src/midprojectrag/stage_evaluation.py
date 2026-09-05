"""Offline source-block evaluation; never invokes a model or changes a runtime.

Inputs/outputs are private. Checkpoint integrity is not live execution authority.
This module deliberately does not import generation, qrels into runtime, or the
legacy answer-required scoring CLI.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Mapping, Sequence

from .evidence.artifacts import load_bundle, private_path, write_new_json
from .evidence.store import EvidenceStore
from .stage_checkpoints import (
    SCHEMA, canonical_sha, source_block_anchor_sha, validate_checkpoint,
)
from .stage_metrics import StageInput, score_stages

Anchor = tuple[str, str, str]
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_BINDING = {"query_sha256", "scope_sha256", "evidence_store_sha256",
            "run_config_sha256", "execution_key_sha256"}
_TEXT_KINDS = {"text", "page", "table_row_group"}
MINI131_SUITE_COUNTS = {"core40": 40, "answer56": 56, "set13": 13,
                       "visual10": 10, "analytics10": 10, "parser2": 2}


def _closed(value: object, fields: set[str], code: str) -> dict:
    if type(value) is not dict or set(value) != fields:
        raise ValueError(code)
    return value


def _identifier(value: object) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError("invalid_evaluation_identifier")
    return value


def _hash(value: object) -> str:
    if type(value) is not str or not _HEX.fullmatch(value):
        raise ValueError("invalid_evaluation_hash")
    return value


def _json_rows(raw: bytes) -> list[dict]:
    # Duplicate keys must not silently change a sealed input's interpretation.
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    rows = [json.loads(line, object_pairs_hook=unique) for line in raw.decode("utf-8").splitlines() if line.strip()]
    if any(type(row) is not dict for row in rows):
        raise ValueError("jsonl_object_required")
    return rows


@dataclass(frozen=True)
class SourceSnapshot:
    """Evaluator-only exact owner/locator index, without source text."""

    snapshot_sha256: str
    manifest_sha256: str
    locators: Mapping[tuple[str, str], str]
    file_hashes: Mapping[str, str]

    def __post_init__(self):
        _hash(self.snapshot_sha256)
        _hash(self.manifest_sha256)
        object.__setattr__(self, "locators", MappingProxyType(dict(self.locators)))
        object.__setattr__(self, "file_hashes", MappingProxyType(dict(self.file_hashes)))


def load_source_snapshot(*, data_root: Path, manifest: Path, blocks_dir: Path,
                         store: EvidenceStore, input_hashes: Mapping[str, str]) -> SourceSnapshot:
    """Read the exact block files already sealed by the evidence bundle."""
    manifest = private_path(manifest, data_root)
    blocks_dir = private_path(blocks_dir, data_root)
    raw_manifest = manifest.read_bytes()
    manifest_sha = sha256(raw_manifest).hexdigest()
    if manifest_sha != input_hashes.get("manifest"):
        raise ValueError("snapshot_manifest_mismatch")
    entries = _json_rows(raw_manifest)
    manifest_docs: set[str] = set()
    files: dict[str, str] = {}
    locators: dict[tuple[str, str], str] = {}
    block_owners: dict[str, str] = {}
    for entry in entries:
        doc_id = _identifier(entry.get("doc_id"))
        if doc_id in manifest_docs:
            raise ValueError("duplicate_manifest_document")
        manifest_docs.add(doc_id)
        if doc_id not in store.doc_ids:
            continue
        relative = entry.get("output_relpath")
        if type(relative) is not str or not relative or Path(relative).is_absolute():
            raise ValueError("invalid_source_block_path")
        path = private_path(Path(data_root) / relative, data_root)
        if not path.is_relative_to(blocks_dir):
            raise ValueError("source_block_outside_directory")
        raw_blocks = path.read_bytes()
        block_file_sha = sha256(raw_blocks).hexdigest()
        key = "blocks_" + doc_id
        if block_file_sha != input_hashes.get(key):
            raise ValueError("snapshot_block_file_mismatch")
        files[key] = block_file_sha
        for block in _json_rows(raw_blocks):
            block_id = _identifier(block.get("block_id"))
            if block.get("doc_id") != doc_id:
                raise ValueError("snapshot_block_owner_mismatch")
            if block_id in block_owners:
                raise ValueError("ambiguous_source_block")
            locator = block.get("source_locator")
            if type(locator) is not str or not locator:
                raise ValueError("snapshot_locator_missing")
            block_owners[block_id] = doc_id
            locators[(doc_id, block_id)] = sha256(locator.encode("utf-8")).hexdigest()
    if set(files) != {"blocks_" + doc for doc in store.doc_ids}:
        raise ValueError("snapshot_corpus_coverage_mismatch")
    payload = {"schema_version": SCHEMA, "manifest_sha256": manifest_sha, "block_file_hashes": files}
    return SourceSnapshot(canonical_sha(payload), manifest_sha, locators, files)


def resolve_checkpoint(checkpoint: dict, *, store: EvidenceStore,
                       snapshot: SourceSnapshot, binding: dict) -> tuple[StageInput, list[dict]]:
    """Join observed source-block identities, never experiment-specific chunk IDs."""
    validate_checkpoint(checkpoint, store, binding)
    if checkpoint["outcome"] != "ok":
        return StageInput(status="unavailable", reason="stage_" + checkpoint["outcome"]), []
    rows = []
    receipts = []
    unresolved = False
    unsupported = False
    for projection in checkpoint["ordered_stable_anchors"]:
        unsupported |= projection["evidence_kind"] not in _TEXT_KINDS
        resolved: set[Anchor] = set()
        if not projection["source_block_ids"]:
            unresolved = True
        for block_id in projection["source_block_ids"]:
            doc_id = projection["doc_id"]
            locator_hash = snapshot.locators.get((doc_id, block_id))
            status = "resolved" if locator_hash is not None else "missing"
            payload = {
                "schema_version": SCHEMA,
                "checkpoint_sha256": checkpoint["projection_sha256"],
                "evidence_store_sha256": store.bundle_sha256,
                "source_snapshot_sha256": snapshot.snapshot_sha256,
                "source_block_anchor_sha256": source_block_anchor_sha(doc_id, block_id),
                "doc_id": doc_id, "source_block_id": block_id,
                "locator_hash": locator_hash, "status": status,
            }
            receipts.append(payload | {"receipt_sha256": canonical_sha(payload)})
            if locator_hash is None:
                unresolved = True
            else:
                resolved.add((doc_id, block_id, locator_hash))
        rows.append(frozenset(resolved))
    if unsupported or unresolved:
        reason = "unsupported_evidence_kind" if unsupported else "source_anchor_unresolved"
        return StageInput(status="unavailable", reason=reason), receipts
    return StageInput(rows=tuple(rows)), receipts


def _qrels(row: dict, snapshot: SourceSnapshot) -> tuple[str, frozenset[Anchor], str | None]:
    _closed(row, {"case_id", "suite", "qrel_status", "required_anchors"}, "invalid_qrel_row")
    _identifier(row["case_id"])
    if type(row["suite"]) is not str or row["suite"] not in MINI131_SUITE_COUNTS:
        raise ValueError("invalid_qrel_suite")
    status = row["qrel_status"]
    refs = row["required_anchors"]
    if status not in ("ready", "missing", "not_applicable") or type(refs) is not list:
        raise ValueError("invalid_qrel_status")
    if (status == "ready") != bool(refs):
        raise ValueError("invalid_qrel_status_evidence")
    if row["suite"] in {"visual10", "analytics10", "parser2"} and status == "ready":
        raise ValueError("specialized_suite_requires_separate_metric")
    anchors = set()
    for ref in refs:
        _closed(ref, {"doc_id", "source_block_id", "locator_hash"}, "invalid_qrel_anchor")
        anchor = (_identifier(ref["doc_id"]), _identifier(ref["source_block_id"]), _hash(ref["locator_hash"]))
        if anchor in anchors:
            raise ValueError("duplicate_required_anchor")
        anchors.add(anchor)
    if any(snapshot.locators.get((doc, block)) != locator for doc, block, locator in anchors):
        return "missing", frozenset(), "qrel_source_anchor_unresolved"
    return status, frozenset(anchors), None


def _record(row: dict, store: EvidenceStore) -> dict:
    _closed(row, {"schema_version", "case_id", "run_id", "binding", "checkpoints"}, "invalid_stage_record")
    if row["schema_version"] != SCHEMA:
        raise ValueError("invalid_stage_record_version")
    _identifier(row["case_id"])
    _identifier(row["run_id"])
    binding = _closed(row["binding"], _BINDING, "invalid_stage_binding")
    for value in binding.values():
        _hash(value)
    if binding["evidence_store_sha256"] != store.bundle_sha256:
        raise ValueError("stage_record_store_mismatch")
    if type(row["checkpoints"]) is not list:
        raise ValueError("stage_checkpoints_array_required")
    seen = set()
    for checkpoint in row["checkpoints"]:
        validate_checkpoint(checkpoint, store, binding)
        if checkpoint["stage"] in seen:
            raise ValueError("duplicate_stage_checkpoint")
        seen.add(checkpoint["stage"])
    return row


def _metric_paths(metrics: dict):
    for name, metric in metrics.items():
        if name == "stage_recall":
            for stage, at_k in metric.items():
                for k, value in at_k.items():
                    yield f"stage_recall.{stage}.{k}", value
        else:
            yield name, metric


def _aggregate(rows: Sequence[dict]) -> dict:
    bins: dict[str, list[dict]] = {}
    for row in rows:
        for name, metric in _metric_paths(row["metrics"]):
            bins.setdefault(name, []).append(metric)
    return {
        name: {
            "total": len(values),
            "available": sum(v["status"] == "available" for v in values),
            "unavailable": sum(v["status"] == "unavailable" for v in values),
            "not_applicable": sum(v["status"] == "not_applicable" for v in values),
            "macro_mean": (sum(v["value"] for v in values if v["status"] == "available") /
                           sum(v["status"] == "available" for v in values)
                           if any(v["status"] == "available" for v in values) else None),
        } for name, values in bins.items()
    }


def evaluate_records(qrels: Sequence[dict], records: Sequence[dict], *, store: EvidenceStore,
                     snapshot: SourceSnapshot, ks: tuple[int, ...] = (1, 3, 5, 10),
                     pre_context_stage: str = "fusion", inventory_mode: str = "partial") -> dict:
    """One fixed run configuration; missing cases remain visible in the ledger."""
    if pre_context_stage not in {"lane_dense", "lane_lexical", "fusion"}:
        raise ValueError("pre_context_stage_must_precede_rerank")
    if not qrels:
        raise ValueError("qrel_inventory_empty")
    if inventory_mode not in ("mini131", "partial"):
        raise ValueError("invalid_inventory_mode")
    cases = {}
    for row in qrels:
        status, anchors, issue = _qrels(row, snapshot)
        if row["case_id"] in cases:
            raise ValueError("duplicate_qrel_case")
        cases[row["case_id"]] = (row, status, anchors, issue)
    suite_counts = dict(Counter(row["suite"] for row in qrels))
    if inventory_mode == "mini131" and suite_counts != MINI131_SUITE_COUNTS:
        raise ValueError("mini131_inventory_incomplete")
    run_by_case = {}
    config_hashes = set()
    for raw in records:
        run = _record(raw, store)
        if run["case_id"] not in cases:
            raise ValueError("unknown_stage_case")
        if run["case_id"] in run_by_case:
            raise ValueError("multiple_runs_for_case_not_supported")
        run_by_case[run["case_id"]] = run
        config_hashes.add(run["binding"]["run_config_sha256"])
    if len(config_hashes) > 1:
        raise ValueError("mixed_run_configurations")
    case_results = []
    all_receipts = []
    for case_id, (qrel, status, anchors, issue) in cases.items():
        run = run_by_case.get(case_id)
        stages = {}
        checkpoint_hashes = {}
        if run is not None:
            for checkpoint in run["checkpoints"]:
                stage, receipts = resolve_checkpoint(checkpoint, store=store, snapshot=snapshot, binding=run["binding"])
                stages[checkpoint["stage"]] = stage
                checkpoint_hashes[checkpoint["stage"]] = checkpoint["projection_sha256"]
                all_receipts.extend(receipts)
        scores = score_stages(anchors, stages, qrel_status=status, ks=ks, pre_context_stage=pre_context_stage)
        case_results.append({
            "case_id": case_id, "suite": qrel["suite"], "qrel_status": status,
            "qrel_issue": issue, "run_status": "recorded" if run is not None else "missing",
            "run_id": run["run_id"] if run is not None else None,
            "checkpoint_hashes": checkpoint_hashes, "metrics": scores,
        })
    scoring = {"schema_version": SCHEMA, "ks": list(ks), "pre_context_stage": pre_context_stage,
               "unit": "source_block", "rank_policy": "raw_candidate_positions",
               "gain_policy": "distinct_required_anchors", "context_support": "selected_children_only"}
    report = {
        "schema_version": SCHEMA, "measurement_kind": "offline_source_block",
        "integrity_scope": "artifact_consistency_not_live_execution_authority",
        "semantic_answer_quality_measured": False, "model_calls": 0,
        "source_snapshot_sha256": snapshot.snapshot_sha256,
        "evidence_store_sha256": store.bundle_sha256,
        "run_config_sha256": next(iter(config_hashes), None),
        "qrels_sha256": canonical_sha(list(qrels)), "records_sha256": canonical_sha(list(records)),
        "scoring_config": scoring, "scoring_config_sha256": canonical_sha(scoring),
        "case_count": len(case_results), "suite_counts": suite_counts,
        "inventory": {"mode": inventory_mode, "complete": inventory_mode == "mini131",
                      "expected_suite_counts": MINI131_SUITE_COUNTS.copy(),
                      "qrels_ready": sum(row["qrel_status"] == "ready" for row in case_results)},
        "cases": case_results, "aggregate": _aggregate(case_results),
        "by_suite": {suite: _aggregate([r for r in case_results if r["suite"] == suite])
                     for suite in sorted({r["suite"] for r in case_results})},
        "anchor_resolution_receipts": all_receipts,
    }
    return report | {"report_sha256": canonical_sha(report)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data-root", "bundle", "manifest", "blocks-dir", "qrels", "records", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--ks", type=int, nargs="+", default=[1, 3, 5, 10])
    parser.add_argument("--inventory-mode", choices=["mini131", "partial"], default="mini131",
                        help="Default requires all 131 cases by suite; partial reports are explicitly incomplete.")
    parser.add_argument("--pre-context-stage", choices=["lane_dense", "lane_lexical", "fusion"], default="fusion")
    args = parser.parse_args(argv)
    try:
        output = private_path(args.output, args.data_root)
        if output.exists():
            raise ValueError("output_already_exists")
        store, bundle_receipt = load_bundle(args.bundle, data_root=args.data_root)
        snapshot = load_source_snapshot(data_root=args.data_root, manifest=args.manifest,
                                        blocks_dir=args.blocks_dir, store=store,
                                        input_hashes=bundle_receipt["input_hashes"])
        qrels_raw = private_path(args.qrels, args.data_root).read_bytes()
        records_raw = private_path(args.records, args.data_root).read_bytes()
        report = evaluate_records(_json_rows(qrels_raw), _json_rows(records_raw), store=store,
                                  snapshot=snapshot, ks=tuple(args.ks), pre_context_stage=args.pre_context_stage,
                                  inventory_mode=args.inventory_mode)
        report.pop("report_sha256")
        report["input_file_sha256s"] = {"qrels": sha256(qrels_raw).hexdigest(), "records": sha256(records_raw).hexdigest()}
        report["report_sha256"] = canonical_sha(report)
        # No directory creation or overwrite side effects; caller chooses an existing private parent.
        write_new_json(output, report)
        print(json.dumps({"status": "scored", "case_count": report["case_count"],
                          "report_sha256": report["report_sha256"], "model_calls": 0}))
        return 0
    except (ValueError, TypeError, KeyError, OSError, UnicodeError):
        # Exceptions may embed private source paths/text. Detailed status stays in a valid private report.
        print(json.dumps({"status": "rejected", "reason": "invalid_or_unavailable_private_evaluation_input"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
