"""Pure source-anchor metrics for recorded retrieval stages, never semantic scores."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


Anchor = tuple[str, str, str]
_STAGES = (
    "lane_dense", "lane_lexical", "lane_visual", "fusion", "rerank", "final_context"
)


def _validate_anchors(value: object) -> None:
    # Locator identity is opaque here; the source snapshot resolver owns its hash.
    if type(value) is not frozenset or any(
        type(anchor) is not tuple
        or len(anchor) != 3
        or any(type(part) is not str or not part.strip() for part in anchor)
        for anchor in value
    ):
        raise ValueError("invalid_stage_anchors")


@dataclass(frozen=True)
class StageInput:
    rows: tuple[frozenset[Anchor], ...] = ()
    status: str = "available"
    reason: str | None = None

    def __post_init__(self) -> None:
        if type(self.status) is not str or self.status not in {"available", "unavailable"}:
            raise ValueError("invalid_stage_status")
        if type(self.rows) is not tuple:
            raise ValueError("invalid_stage_rows")
        for row in self.rows:
            _validate_anchors(row)
        if self.reason is not None and (
            type(self.reason) is not str or not self.reason.strip()
        ):
            raise ValueError("invalid_stage_reason")
        if self.status == "available" and self.reason is not None:
            raise ValueError("available_stage_has_reason")
        if self.status == "unavailable" and self.rows:
            raise ValueError("unavailable_stage_has_rows")


def _unscored(status: str, reason: str) -> dict:
    return {
        "status": status, "value": None, "numerator": None,
        "denominator": None, "reason": reason,
    }


def _ratio(numerator: int, denominator: int, *, zero_reason: str) -> dict:
    return {
        "status": "available" if denominator else "not_applicable",
        "value": numerator / denominator if denominator else None,
        "numerator": numerator,
        "denominator": denominator,
        "reason": None if denominator else zero_reason,
    }


def _stage_problem(stages: Mapping[str, StageInput], names: tuple[str, ...]) -> str | None:
    for name in names:
        stage = stages.get(name)
        if stage is None:
            return f"missing_stage:{name}"
        if stage.status == "unavailable":
            return f"unavailable_stage:{name}:{stage.reason or 'stage_unavailable'}"
    return None


def _anchors(stage: StageInput, k: int | None = None) -> frozenset[Anchor]:
    # Slice candidate rows before union: duplicate hits still consume their rank.
    return frozenset().union(*stage.rows[:k])


def score_stages(
    required: frozenset[Anchor],
    stages: Mapping[str, StageInput],
    *,
    qrel_status: str = "ready",
    ks: tuple[int, ...] = (1, 3, 5, 10),
    pre_context_stage: str = "fusion",
) -> dict:
    """Score one execution chain whose source anchors were resolved beforehand.

    Missing/unavailable stages take precedence over an empty metric denominator.
    Ready qrels must be nonempty; missing and inapplicable qrels must be empty.
    All six stages are reported, including absent stages with null values.
    """
    _validate_anchors(required)
    if type(qrel_status) is not str or qrel_status not in {"ready", "missing", "not_applicable"}:
        raise ValueError("invalid_qrel_status")
    if (qrel_status == "ready") != bool(required):
        raise ValueError("qrel_status_anchor_mismatch")
    if (
        type(ks) is not tuple or not ks
        or any(type(k) is not int or k < 1 for k in ks)
        or len(set(ks)) != len(ks)
    ):
        raise ValueError("invalid_stage_cutoffs")
    if type(pre_context_stage) is not str or pre_context_stage not in _STAGES:
        raise ValueError("invalid_pre_context_stage")
    if not isinstance(stages, Mapping):
        raise ValueError("invalid_stages_mapping")
    stage_inputs = dict(stages)
    for name, stage in stage_inputs.items():
        if type(name) is not str or name not in _STAGES:
            raise ValueError("invalid_stage_name")
        if not isinstance(stage, StageInput):
            raise ValueError("invalid_stage_input")
        stage.__post_init__()

    def unavailable(names: tuple[str, ...]) -> dict | None:
        if qrel_status == "missing":
            return _unscored("unavailable", "qrels_missing")
        if qrel_status == "not_applicable":
            return _unscored("not_applicable", "qrels_not_applicable")
        reason = _stage_problem(stage_inputs, names)
        return _unscored("unavailable", reason) if reason is not None else None

    def recall(name: str, k: int | None = None) -> dict:
        problem = unavailable((name,))
        if problem is not None:
            return problem
        return _ratio(
            len(required & _anchors(stage_inputs[name], k)), len(required),
            zero_reason="no_required_anchors",
        )

    def retention() -> dict:
        problem = unavailable((pre_context_stage, "final_context"))
        if problem is not None:
            return problem
        relevant_pre = required & _anchors(stage_inputs[pre_context_stage])
        return _ratio(
            len(relevant_pre & _anchors(stage_inputs["final_context"])),
            len(relevant_pre), zero_reason="no_relevant_pre_context_anchors",
        )

    def rescue(base: str, rescuer: str) -> dict:
        problem = unavailable((base, rescuer, "fusion"))
        if problem is not None:
            return problem
        missed = required - _anchors(stage_inputs[base])
        return _ratio(
            len(missed & _anchors(stage_inputs[rescuer]) & _anchors(stage_inputs["fusion"])),
            len(missed), zero_reason=f"no_required_anchors_missing_from:{base}",
        )

    return {
        "pre_required_recall": recall(pre_context_stage),
        "post_required_recall": recall("final_context"),
        "relevant_retention": retention(),
        "lexical_rescue": rescue("lane_dense", "lane_lexical"),
        "dense_rescue": rescue("lane_lexical", "lane_dense"),
        "stage_recall": {
            name: {str(k): recall(name, k) for k in ks} for name in _STAGES
        },
    }
