"""Binary ranking metrics on explicit unique units, separate from raw recall."""
from math import log2
from collections.abc import Mapping

from .stage_metrics import StageInput, _STAGES, _validate_anchors, _unscored


def _status(status, required):
    if type(status) is not str or status not in {"ready", "missing", "not_applicable"} or (status == "ready") != bool(required):
        raise ValueError("ranking_qrel_status_mismatch")


def _project(stage, unit):
    ordered, seen = [], set()
    for row in stage.rows:
        if not row:
            return None, "unresolved_empty_rank_row"
        values = row if unit == "source_anchor" else frozenset(anchor[0] for anchor in row)
        if len(values) != 1:
            return None, "grouped_source_anchor_rank" if unit == "source_anchor" else "grouped_document_rank"
        value = next(iter(values))
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered, None


def _value(numerator, denominator):
    return {"status": "available", "value": numerator / denominator, "numerator": numerator,
            "denominator": denominator, "reason": None}


def score_rankings(required_anchors, stages, *, source_status="ready", required_doc_ids=frozenset(),
                   document_status="missing", document_missing_reason="document_qrels_missing", ks=(1, 3, 5, 10)):
    """Case values are RR; only the cross-case macro mean is MRR.

    Documents use an independent original gold set, never anchor-owner inference.
    Unknown ordering does not create arbitrary first/last positions or fake zeros.
    """
    _validate_anchors(required_anchors)
    if type(required_doc_ids) is not frozenset or any(type(d) is not str or not d for d in required_doc_ids):
        raise ValueError("invalid_ranking_document_qrels")
    _status(source_status, required_anchors)
    _status(document_status, required_doc_ids)
    if type(document_missing_reason) is not str or not document_missing_reason:
        raise ValueError("invalid_document_missing_reason")
    if type(ks) is not tuple or not ks or any(type(k) is not int or k < 1 for k in ks) or len(set(ks)) != len(ks):
        raise ValueError("invalid_ranking_cutoffs")
    if not isinstance(stages, Mapping) or any(name not in _STAGES or type(stage) is not StageInput for name, stage in stages.items()):
        raise ValueError("invalid_ranking_stages")
    for stage in stages.values():
        stage.__post_init__()
    result = {}
    for unit, required, status in (("source_anchor", required_anchors, source_status),
                                   ("document", required_doc_ids, document_status)):
        result[unit] = {}
        for name in _STAGES:
            problem, ordered = None, None
            stage = stages.get(name)
            if status == "missing":
                problem = _unscored("unavailable", document_missing_reason if unit == "document" else "source_qrels_missing")
            elif status == "not_applicable":
                problem = _unscored("not_applicable", "qrels_not_applicable")
            elif stage is None or stage.status == "unavailable":
                problem = _unscored("unavailable", "missing_stage" if stage is None else stage.reason or "stage_unavailable")
            else:
                ordered, reason = _project(stage, unit)
                if reason:
                    problem = _unscored("unavailable", reason)
            scores = {}
            for k in ks:
                if problem is not None:
                    scores[str(k)] = {"rr": dict(problem), "ndcg": dict(problem)}
                    continue
                relevant_ranks = [rank for rank, value in enumerate(ordered[:k], 1) if value in required]
                dcg = sum(1 / log2(rank + 1) for rank in relevant_ranks)
                ideal = sum(1 / log2(rank + 1) for rank in range(1, min(k, len(required)) + 1))
                scores[str(k)] = {"rr": _value(1, relevant_ranks[0]) if relevant_ranks else _value(0, 1),
                                  "ndcg": _value(dcg, ideal)}
            result[unit][name] = scores
    return result
