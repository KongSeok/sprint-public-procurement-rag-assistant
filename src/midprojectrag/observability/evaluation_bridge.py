from __future__ import annotations

from typing import Any

from midprojectrag.observability._core import Observer
from midprojectrag.observability._metadata import valid_score, valid_trace_id


JUDGMENT_SCORE_FIELDS = (
    "correctness",
    "faithfulness",
    "factual_claim_coverage",
    "citation_validity",
    "follow_up_success",
    "safe_abstention",
)


def export_run_judgment_scores(run_record: dict[str, Any], observer: Observer) -> int:
    """Replicate only numeric/boolean judgments; never gold text or comments."""

    response = run_record.get("response")
    judgment = run_record.get("judgment")
    if not isinstance(response, dict) or not isinstance(judgment, dict):
        raise ValueError("invalid_score_run_record")
    trace_id = response.get("trace_id")
    if not valid_trace_id(trace_id):
        raise ValueError("invalid_score_trace_id")
    exported = 0
    for name in JUDGMENT_SCORE_FIELDS:
        value = judgment.get(name)
        if value is None:
            continue
        expects_boolean = name in {"follow_up_success", "safe_abstention"}
        if expects_boolean and isinstance(value, bool):
            observer.score(trace_id, name, value)
        elif not expects_boolean and isinstance(value, (int, float)) and not isinstance(value, bool):
            if not valid_score(name, value):
                raise ValueError("invalid_judgment_score")
            observer.score(trace_id, name, float(value))
        else:
            raise ValueError("invalid_judgment_score")
        exported += 1
    return exported
