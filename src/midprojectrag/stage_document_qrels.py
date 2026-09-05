"""Verify original Mini131 document targets without deriving gold from hits.

Hash consistency preserves an input receipt, not human approval or live authority.
This module is evaluator-only and has no runtime, provider, or source-text imports.
"""
from collections import Counter
from dataclasses import dataclass
import re
from types import MappingProxyType

from .stage_checkpoints import canonical_sha

_SUITES = {"core40": 40, "answer56": 56, "set13": 13, "visual10": 10, "analytics10": 10, "parser2": 2}
_SOURCES = {"core40", "supplemental_answers", "supplemental_sets", "visual", "analytics",
            "analytics_calculations", "integrated_ledger", "parser_receipt"}
_FIELDS = {"schema_version", "case_count", "suite_counts", "source_file_sha256s", "source_snapshot_sha256",
           "qrel_counts", "formal_comparison_authorized", "model_calls", "cases", "inputs_sha256",
           "input_config_sha256", "qrels_file_sha256", "publication_status", "inventory_sha256"}
_CASE_FIELDS = {"case_id", "suite", "source_row_sha256", "source_manifest_status", "qrel_status", "reason",
                "required_anchor_count", "required_doc_ids", "source_review_status", "source_review_sha256",
                "reviewed_draft_sha256", "semantic_approval"}
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


@dataclass(frozen=True)
class DocumentQrels:
    status: str
    required: frozenset[str] = frozenset()
    reason: str | None = None


def _hash(value):
    if type(value) is not str or not _HASH.fullmatch(value):
        raise ValueError("invalid_document_inventory_hash")
    return value


def _counts(value, expected):
    if (type(value) is not dict or set(value) != set(expected)
            or any(type(n) is not int or n < 0 for n in value.values()) or value != expected):
        raise ValueError("document_inventory_count_mismatch")


def validate_document_inventory(inventory, qrels, *, snapshot, qrels_file_sha256):
    """Return independent document qrels only after binding the full input inventory.

The adapter CLI's config-bound 131-case receipt is required. A missing source-block
gold does not erase original document targets. Abstention/specialized suites stay
not-applicable even if their source rows retain document IDs for another purpose.
"""
    if type(inventory) is not dict or set(inventory) != _FIELDS:
        raise ValueError("invalid_document_inventory_schema")
    if (inventory["schema_version"] != "mini131-stage-inputs-v1" or inventory["publication_status"] != "complete"
            or inventory["formal_comparison_authorized"] is not False
            or type(inventory["model_calls"]) is not int or inventory["model_calls"] != 0):
        raise ValueError("invalid_document_inventory_policy")
    for name in ("source_snapshot_sha256", "inputs_sha256", "input_config_sha256", "qrels_file_sha256", "inventory_sha256"):
        _hash(inventory[name])
    if inventory["inventory_sha256"] != canonical_sha({k: v for k, v in inventory.items() if k != "inventory_sha256"}):
        raise ValueError("document_inventory_receipt_mismatch")
    if inventory["qrels_file_sha256"] != _hash(qrels_file_sha256):
        raise ValueError("document_inventory_qrels_file_mismatch")
    if inventory["source_snapshot_sha256"] != snapshot.snapshot_sha256:
        raise ValueError("document_inventory_snapshot_mismatch")
    body = {k: v for k, v in inventory.items()
            if k not in {"inventory_sha256", "qrels_file_sha256", "publication_status", "inputs_sha256"}}
    body["qrels"] = list(qrels)
    if inventory["inputs_sha256"] != canonical_sha(body):
        raise ValueError("document_inventory_inputs_mismatch")
    sources = inventory["source_file_sha256s"]
    if type(sources) is not dict or set(sources) != _SOURCES:
        raise ValueError("document_inventory_sources_incomplete")
    for value in sources.values():
        _hash(value)
    if type(inventory["case_count"]) is not int or inventory["case_count"] != 131 or len(qrels) != 131:
        raise ValueError("document_inventory_incomplete")
    _counts(inventory["suite_counts"], _SUITES)
    by_id = {}
    for qrel in qrels:
        if (type(qrel) is not dict or set(qrel) != {"case_id", "suite", "qrel_status", "required_anchors"}
                or type(qrel["case_id"]) is not str or not _ID.fullmatch(qrel["case_id"])
                or qrel["case_id"] in by_id or type(qrel["suite"]) is not str or qrel["suite"] not in _SUITES
                or type(qrel["qrel_status"]) is not str or qrel["qrel_status"] not in {"ready", "missing", "not_applicable"}
                or type(qrel["required_anchors"]) is not list
                or (qrel["qrel_status"] == "ready") != bool(qrel["required_anchors"])):
            raise ValueError("document_inventory_invalid_qrel")
        by_id[qrel["case_id"]] = qrel
    if dict(Counter(q["suite"] for q in qrels)) != _SUITES:
        raise ValueError("document_inventory_suite_mismatch")
    _counts(inventory["qrel_counts"], dict(Counter(q["qrel_status"] for q in qrels)))
    cases = inventory["cases"]
    if type(cases) is not list or len(cases) != 131:
        raise ValueError("document_inventory_cases_incomplete")
    known_docs = {doc for doc, _ in snapshot.locators}
    result = {}
    for case in cases:
        if type(case) is not dict or set(case) != _CASE_FIELDS:
            raise ValueError("document_inventory_invalid_case")
        cid = case["case_id"]
        if type(cid) is not str or cid not in by_id or cid in result:
            raise ValueError("document_inventory_case_identity")
        qrel = by_id[cid]
        if (case["suite"] != qrel["suite"] or case["qrel_status"] != qrel["qrel_status"]
                or type(case["required_anchor_count"]) is not int
                or case["required_anchor_count"] != len(qrel["required_anchors"])):
            raise ValueError("document_inventory_case_qrel_mismatch")
        if (case["source_manifest_status"] != "matched" or case["semantic_approval"] != "not_assessed_by_adapter"
                or type(case["source_review_status"]) is not str
                or case["source_review_status"] not in {"draft", "approved", "rejected", "pending", "reviewed", "unrecognized", "not_recorded"}):
            raise ValueError("document_inventory_review_contract")
        _hash(case["source_row_sha256"])
        _hash(case["source_review_sha256"])
        if case["reviewed_draft_sha256"] is not None:
            _hash(case["reviewed_draft_sha256"])
        docs = case["required_doc_ids"]
        if (type(docs) is not list or any(type(d) is not str or not _ID.fullmatch(d) or d not in known_docs for d in docs)
                or len(set(docs)) != len(docs)):
            raise ValueError("document_inventory_invalid_targets")
        status, reason = case["qrel_status"], case["reason"]
        specialized = case["suite"] in {"visual10", "analytics10", "parser2"}
        if specialized:
            if status != "not_applicable" or reason != "specialized_metric_required":
                raise ValueError("document_inventory_specialized_contract")
            result[cid] = DocumentQrels("not_applicable", reason=reason)
        elif status == "not_applicable":
            if case["suite"] == "set13" or reason != "positive_recall_not_applicable_to_abstention":
                raise ValueError("document_inventory_abstention_contract")
            result[cid] = DocumentQrels("not_applicable", reason=reason)
        else:
            if ((status == "ready" and reason is not None)
                    or (status == "missing" and reason not in ("source_block_qrels_missing", "qrel_source_anchor_unresolved"))):
                raise ValueError("document_inventory_reason_mismatch")
            result[cid] = (DocumentQrels("ready", frozenset(docs)) if docs
                           else DocumentQrels("missing", reason="original_document_qrels_missing"))
    return MappingProxyType(result)
