from __future__ import annotations

import re
from collections import Counter
from typing import Any, Mapping, Sequence

from midprojectrag.ingest.visual_evidence import normalize_bbox


HWP_RISK_TYPES = frozenset(
    {
        "hwp_body_image",
        "hwp_table_nested",
        "hwp_vector_diagram",
        "hwp_unsupported_media",
        "hwp_repeated_mismatch",
    }
)
PDF_RISK_TYPES = frozenset(
    {
        "pdf_raster",
        "pdf_inline_or_mask",
        "pdf_vector_diagram",
        "pdf_schedule_table",
    }
)
_DOC_ID = re.compile(r"^doc_[0-9a-f]{24}$")
_ANNOTATION_ID = re.compile(r"^vgold_[0-9a-f]{24}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class VisualGoldError(ValueError):
    pass


def validate_visual_gold(
    annotations: Sequence[Mapping[str, Any]],
    *,
    require_reviewed: bool = True,
    require_full_representative_gate: bool = True,
) -> dict[str, Any]:
    if not isinstance(annotations, Sequence) or isinstance(
        annotations, (str, bytes)
    ):
        raise VisualGoldError("visual_gold_records_invalid")
    annotation_ids: set[str] = set()
    hwp_docs: set[str] = set()
    pdf_docs: set[str] = set()
    hwp_risks: set[str] = set()
    pdf_risks: set[str] = set()
    critical_cases: set[str] = set()
    statuses: Counter[str] = Counter()
    for record in annotations:
        _validate_record(record)
        annotation_id = record["annotation_id"]
        if annotation_id in annotation_ids:
            raise VisualGoldError("visual_gold_annotation_duplicate")
        annotation_ids.add(annotation_id)
        statuses[record["status"]] += 1
        if require_reviewed and record["status"] != "reviewed":
            raise VisualGoldError("visual_gold_review_incomplete")
        if record["source_format"] == "hwp":
            hwp_docs.add(record["doc_id"])
            hwp_risks.add(record["risk_type"])
        else:
            pdf_docs.add(record["doc_id"])
            pdf_risks.add(record["risk_type"])
        if record["critical_case"] != "none":
            critical_cases.add(record["critical_case"])
    if require_full_representative_gate:
        if hwp_risks != HWP_RISK_TYPES or len(hwp_docs) < 5:
            raise VisualGoldError("visual_gold_hwp_representative_gate_failed")
        if pdf_risks != PDF_RISK_TYPES or len(pdf_docs) < 4:
            raise VisualGoldError("visual_gold_pdf_representative_gate_failed")
        if critical_cases != {"schedule", "system_diagram"}:
            raise VisualGoldError("visual_gold_critical_case_missing")
    return {
        "passed": True,
        "annotation_count": len(annotations),
        "hwp_document_count": len(hwp_docs),
        "pdf_document_count": len(pdf_docs),
        "hwp_risk_type_count": len(hwp_risks),
        "pdf_risk_type_count": len(pdf_risks),
        "critical_case_count": len(critical_cases),
        "status_counts": dict(sorted(statuses.items())),
    }


def _validate_record(record: Mapping[str, Any]) -> None:
    fields = {
        "schema_version",
        "annotation_id",
        "doc_id",
        "source_sha256",
        "source_format",
        "risk_type",
        "page",
        "bbox",
        "coordinate_space",
        "region_kind",
        "nearby_title",
        "expected_text",
        "relationship_claims",
        "critical_case",
        "reviewers",
        "status",
    }
    if not isinstance(record, Mapping) or set(record) != fields:
        raise VisualGoldError("visual_gold_record_invalid")
    if record["schema_version"] != "1.0":
        raise VisualGoldError("visual_gold_record_invalid")
    if (
        not isinstance(record["annotation_id"], str)
        or _ANNOTATION_ID.fullmatch(record["annotation_id"]) is None
        or not isinstance(record["doc_id"], str)
        or _DOC_ID.fullmatch(record["doc_id"]) is None
        or not isinstance(record["source_sha256"], str)
        or _SHA256.fullmatch(record["source_sha256"]) is None
    ):
        raise VisualGoldError("visual_gold_record_invalid")
    source_format = record["source_format"]
    risk_type = record["risk_type"]
    expected_space = (
        "rhwp_css_px_96dpi" if source_format == "hwp" else "pdf_points_top_left"
    )
    allowed_risks = HWP_RISK_TYPES if source_format == "hwp" else PDF_RISK_TYPES
    if (
        source_format not in {"hwp", "pdf"}
        or risk_type not in allowed_risks
        or record["coordinate_space"] != expected_space
        or not isinstance(record["page"], int)
        or isinstance(record["page"], bool)
        or record["page"] < 1
    ):
        raise VisualGoldError("visual_gold_record_invalid")
    try:
        normalize_bbox(record["bbox"], error_code="visual_gold_record_invalid")
    except ValueError:
        raise VisualGoldError("visual_gold_record_invalid") from None
    if record["region_kind"] not in {
        "raster_image",
        "inline_image",
        "vector_diagram",
        "table",
        "table_child_image",
        "decorative",
        "ambiguous",
    }:
        raise VisualGoldError("visual_gold_record_invalid")
    title = record["nearby_title"]
    if title is not None and (
        not isinstance(title, str) or len(title) > 500
    ):
        raise VisualGoldError("visual_gold_record_invalid")
    for field, maximum in (("expected_text", 500), ("relationship_claims", 1000)):
        values = record[field]
        if (
            not isinstance(values, list)
            or len(values) != len(set(values))
            or any(
                not isinstance(value, str)
                or not value
                or len(value) > maximum
                for value in values
            )
        ):
            raise VisualGoldError("visual_gold_record_invalid")
    reviewers = record["reviewers"]
    if (
        not isinstance(reviewers, list)
        or not 1 <= len(reviewers) <= 2
        or len(reviewers) != len(set(reviewers))
        or any(
            not isinstance(value, str) or not value or len(value) > 128
            for value in reviewers
        )
        or record["critical_case"] not in {"none", "schedule", "system_diagram"}
        or record["status"] not in {"draft", "reviewed"}
    ):
        raise VisualGoldError("visual_gold_record_invalid")


__all__ = ["VisualGoldError", "validate_visual_gold"]
