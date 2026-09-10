from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from midprojectrag.catalog.errors import CatalogError
from midprojectrag.catalog.models import (
    EVIDENCE_KINDS,
    SUPPORTED_FIELDS,
    DocumentCard,
    EvidenceRef,
    MetadataCatalog,
    MetadataFact,
)
from midprojectrag.ingest.common import canonical_json, sha256_text


_DOC_ID = re.compile(r"^doc_[0-9a-f]{24}$")
_CORRECTION_ID = re.compile(r"^corr_[a-z0-9_]{1,64}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CANONICAL_DATETIME = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$"
)
_CANONICAL_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_AMOUNT = re.compile(r"^[0-9]+(?:\.0+)?$")
_LOCAL_PAGE = re.compile(r"^(doc_[0-9a-f]{24}):page:([1-9][0-9]*)$")
_LOCAL_STRUCTURE = re.compile(
    r"^(doc_[0-9a-f]{24}):section:(0|[1-9][0-9]*)/"
    r"paragraph:(0|[1-9][0-9]*)/table:(0|[1-9][0-9]*)$"
)

_DATETIME_FIELDS = {
    "published_at",
    "bid_start_at",
    "bid_end_at",
    "bid_open_at",
    "proposal_evaluation_at",
}
_VALUE_TYPE_BY_FIELD = {
    **{field: "text" for field in SUPPORTED_FIELDS},
    "project_amount_raw": "krw_amount",
    **{field: "kst_datetime" for field in _DATETIME_FIELDS},
    "source_format": "source_format",
}
_APPLY_REASONS = {
    "official_source_confirmed",
    "official_attachment_confirmed",
    "local_source_confirmed",
    "cross_source_confirmed",
    "date_mapping_corrected",
}
_CLEAR_STATES = {
    "sentinel_not_yet_finalized": "not_finalized",
    "sentinel_undisclosed": "undisclosed",
    "sentinel_exact_value_not_stated": "source_not_stated",
    "semantic_field_mismatch": "semantic_mismatch",
}
_NULL_STATES = {
    "source_not_stated": "source_not_stated",
    "not_applicable": "not_applicable",
    "unverified": "unverified",
}
_PRIMARY_EVIDENCE = {"official_web", "official_attachment", "local_source_block"}
_CORRECTION_EVIDENCE_KINDS = set(EVIDENCE_KINDS) - {"catalog_record"}
_CORRECTION_KEYS = {
    "correction_id",
    "csv_row_number",
    "row_sha256",
    "field",
    "old_value",
    "new_value",
    "decision",
    "reason_code",
    "confidence",
    "checked_at",
    "evidence",
}
_CORRECTION_SET_KEYS = {
    "schema_version",
    "source_csv_sha256",
    "created_at",
    "corrections",
}


def _cell(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, (str, int, float, Decimal)) or isinstance(value, bool):
        raise CatalogError("correction_set_catalog_mismatch")
    normalized = unicodedata.normalize("NFC", str(value)).strip()
    return normalized or None


def _valid_datetime(value: str) -> str:
    if not _CANONICAL_DATETIME.fullmatch(value):
        raise CatalogError("invalid_metadata_datetime")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError as error:
        raise CatalogError("invalid_metadata_datetime") from error
    if parsed.strftime("%Y-%m-%d %H:%M:%S") != value:
        raise CatalogError("invalid_metadata_datetime")
    return value


def _valid_checked_at(value: Any) -> str:
    if not isinstance(value, str) or not _CANONICAL_DATE.fullmatch(value):
        raise CatalogError("invalid_metadata_provenance")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise CatalogError("invalid_metadata_provenance") from error
    if parsed.isoformat() != value:
        raise CatalogError("invalid_metadata_provenance")
    return value


def _parse_amount(value: Any) -> int | None:
    raw = _cell(value)
    if raw is None:
        return None
    compact = re.sub(r"[,\s_원]", "", raw)
    if not compact or not _AMOUNT.fullmatch(compact):
        raise CatalogError("invalid_metadata_amount")
    try:
        amount = Decimal(compact)
    except InvalidOperation as error:
        raise CatalogError("invalid_metadata_amount") from error
    if not amount.is_finite() or amount != amount.to_integral_value() or amount < 0:
        raise CatalogError("invalid_metadata_amount")
    return int(amount)


def _normalize_field(field: str, value: str | None) -> str | None:
    if value is None:
        return None
    if field == "project_amount_raw":
        amount = _parse_amount(value)
        return str(amount) if amount is not None and amount > 0 else None
    if field in _DATETIME_FIELDS:
        return _valid_datetime(value)
    if field == "source_format":
        return value.casefold()
    return value


def _require_sequence(value: Any) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise CatalogError("correction_set_catalog_mismatch")
    return value


def _catalog_index(
    catalog_rows: Sequence[Mapping[str, Any]], expected_snapshot_id: str
) -> tuple[dict[int, Mapping[str, Any]], set[str]]:
    if not isinstance(expected_snapshot_id, str) or not expected_snapshot_id.strip():
        raise CatalogError("correction_set_catalog_mismatch")
    by_row_number: dict[int, Mapping[str, Any]] = {}
    doc_ids: set[str] = set()
    for row in catalog_rows:
        if not isinstance(row, Mapping):
            raise CatalogError("correction_set_catalog_mismatch")
        doc_id = row.get("doc_id")
        row_number = row.get("csv_row_number")
        if (
            not isinstance(doc_id, str)
            or not _DOC_ID.fullmatch(doc_id)
            or not isinstance(row_number, int)
            or isinstance(row_number, bool)
            or row_number < 2
            or row.get("snapshot_id") != expected_snapshot_id
            or not isinstance(row.get("metadata"), Mapping)
        ):
            raise CatalogError("correction_set_catalog_mismatch")
        if doc_id in doc_ids or row_number in by_row_number:
            raise CatalogError("correction_set_catalog_mismatch")
        doc_ids.add(doc_id)
        by_row_number[row_number] = row
    return by_row_number, doc_ids


def _retrieval_page_counts(
    retrieval_rows: Sequence[Mapping[str, Any]], catalog_doc_ids: set[str]
) -> dict[str, int]:
    page_counts: dict[str, int] = {}
    for row in retrieval_rows:
        if not isinstance(row, Mapping):
            raise CatalogError("correction_set_catalog_mismatch")
        doc_id = row.get("doc_id")
        page_count = row.get("page_count")
        if (
            not isinstance(doc_id, str)
            or not _DOC_ID.fullmatch(doc_id)
            or not isinstance(page_count, int)
            or isinstance(page_count, bool)
            or page_count < 1
            or doc_id in page_counts
        ):
            raise CatalogError("correction_set_catalog_mismatch")
        page_counts[doc_id] = page_count
    if set(page_counts) != catalog_doc_ids:
        raise CatalogError("correction_set_catalog_mismatch")
    return page_counts


def _validate_local_locator(locator: str, *, doc_id: str, page_count: int) -> None:
    page_match = _LOCAL_PAGE.fullmatch(locator)
    if page_match:
        if page_match.group(1) != doc_id or int(page_match.group(2)) > page_count:
            raise CatalogError("invalid_metadata_provenance")
        return
    structure_match = _LOCAL_STRUCTURE.fullmatch(locator)
    if structure_match and structure_match.group(1) == doc_id:
        return
    raise CatalogError("invalid_metadata_provenance")


def _evidence_refs(
    raw_evidence: Any, *, doc_id: str, page_count: int
) -> tuple[EvidenceRef, ...]:
    evidence = _require_sequence(raw_evidence)
    if not evidence or len(evidence) > 32:
        raise CatalogError("invalid_metadata_provenance")
    refs: list[EvidenceRef] = []
    for item in evidence:
        if not isinstance(item, Mapping) or set(item) != {"source_type", "locator"}:
            raise CatalogError("invalid_metadata_provenance")
        source_type = item.get("source_type")
        locator = item.get("locator")
        if (
            not isinstance(source_type, str)
            or source_type not in _CORRECTION_EVIDENCE_KINDS
            or not isinstance(locator, str)
        ):
            raise CatalogError("invalid_metadata_provenance")
        ref = EvidenceRef(source_type=source_type, locator=locator)
        if source_type == "local_source_block":
            _validate_local_locator(ref.locator, doc_id=doc_id, page_count=page_count)
        refs.append(ref)
    return tuple(refs)


def _correction_index(
    correction_set: Mapping[str, Any],
    *,
    catalog_by_row: Mapping[int, Mapping[str, Any]],
    page_counts: Mapping[str, int],
) -> dict[tuple[int, str], Mapping[str, Any]]:
    if set(correction_set) != _CORRECTION_SET_KEYS:
        raise CatalogError("correction_set_catalog_mismatch")
    if correction_set.get("schema_version") != "1.0":
        raise CatalogError("correction_set_catalog_mismatch")
    source_hash = correction_set.get("source_csv_sha256")
    created_at = correction_set.get("created_at")
    if (
        not isinstance(source_hash, str)
        or not _SHA256.fullmatch(source_hash)
        or not isinstance(created_at, str)
        or not created_at.strip()
    ):
        raise CatalogError("correction_set_catalog_mismatch")
    corrections = _require_sequence(correction_set.get("corrections"))
    by_target: dict[tuple[int, str], Mapping[str, Any]] = {}
    ids: set[str] = set()
    for correction in corrections:
        if not isinstance(correction, Mapping) or set(correction) != _CORRECTION_KEYS:
            raise CatalogError("correction_set_catalog_mismatch")
        correction_id = correction.get("correction_id")
        row_number = correction.get("csv_row_number")
        field = correction.get("field")
        if field not in SUPPORTED_FIELDS:
            raise CatalogError("invalid_metadata_field")
        if (
            not isinstance(correction_id, str)
            or not _CORRECTION_ID.fullmatch(correction_id)
            or not isinstance(row_number, int)
            or isinstance(row_number, bool)
            or row_number not in catalog_by_row
        ):
            raise CatalogError("correction_set_catalog_mismatch")
        target = (row_number, field)
        if correction_id in ids or target in by_target:
            raise CatalogError("duplicate_metadata_fact")
        ids.add(correction_id)
        by_target[target] = correction

        row_hash = correction.get("row_sha256")
        confidence = correction.get("confidence")
        if not isinstance(row_hash, str) or not _SHA256.fullmatch(row_hash):
            raise CatalogError("correction_set_catalog_mismatch")
        if not isinstance(confidence, str) or confidence not in {
            "high",
            "medium",
            "low",
        }:
            raise CatalogError("invalid_metadata_state")
        checked_at = _valid_checked_at(correction.get("checked_at"))
        row = catalog_by_row[row_number]
        doc_id = str(row["doc_id"])
        evidence = _evidence_refs(
            correction.get("evidence"), doc_id=doc_id, page_count=page_counts[doc_id]
        )
        decision = correction.get("decision")
        reason = correction.get("reason_code")
        if not isinstance(decision, str) or not isinstance(reason, str):
            raise CatalogError("invalid_metadata_state")
        if any(
            value is not None and not isinstance(value, str)
            for value in (correction.get("old_value"), correction.get("new_value"))
        ):
            raise CatalogError("correction_set_catalog_mismatch")
        new_value = _cell(correction.get("new_value"))
        old_value = _cell(correction.get("old_value"))
        source_types = {item.source_type for item in evidence}
        if decision == "apply":
            if (
                reason not in _APPLY_REASONS
                or confidence != "high"
                or new_value is None
                or not source_types & _PRIMARY_EVIDENCE
            ):
                raise CatalogError("invalid_metadata_state")
            if field == "project_amount_raw" and (
                not re.fullmatch(r"[0-9]+", new_value) or int(new_value) <= 0
            ):
                raise CatalogError("invalid_metadata_amount")
            _normalize_field(field, new_value)
        elif decision == "clear":
            if (
                reason not in _CLEAR_STATES
                or confidence != "high"
                or old_value is None
                or new_value is not None
                or not source_types & _PRIMARY_EVIDENCE
            ):
                raise CatalogError("invalid_metadata_state")
        elif decision == "retain_null":
            if reason not in _NULL_STATES or old_value is not None or new_value is not None:
                raise CatalogError("invalid_metadata_state")
        else:
            raise CatalogError("invalid_metadata_state")
        # Keep normalized objects private to this validation pass without mutating inputs.
        _ = checked_at
    return by_target


def _state_for(
    correction: Mapping[str, Any] | None,
    *,
    value: str | None,
    amount: int | None,
) -> str:
    if correction is None:
        if amount in {0, 1}:
            return "suspect_sentinel"
        return "source_recorded" if value is not None else "unknown"
    decision = correction["decision"]
    reason = correction["reason_code"]
    if decision == "apply":
        return "confirmed"
    if decision == "clear":
        return _CLEAR_STATES[str(reason)]
    return _NULL_STATES[str(reason)]


def _catalog_record_evidence(doc_id: str, field_name: str) -> tuple[EvidenceRef, ...]:
    return (
        EvidenceRef(
            source_type="catalog_record",
            locator=f"catalog:{doc_id}:field:{field_name}",
        ),
    )


def materialize_catalog(
    catalog_rows: Sequence[Mapping[str, Any]],
    correction_set: Mapping[str, Any],
    retrieval_rows: Sequence[Mapping[str, Any]],
    *,
    expected_snapshot_id: str,
) -> MetadataCatalog:
    """Build a deterministic immutable catalog without any provider or index call."""

    catalog_rows = _require_sequence(catalog_rows)
    retrieval_rows = _require_sequence(retrieval_rows)
    if not isinstance(correction_set, Mapping):
        raise CatalogError("correction_set_catalog_mismatch")
    catalog_by_row, doc_ids = _catalog_index(catalog_rows, expected_snapshot_id)
    page_counts = _retrieval_page_counts(retrieval_rows, doc_ids)
    corrections = _correction_index(
        correction_set,
        catalog_by_row=catalog_by_row,
        page_counts=page_counts,
    )
    try:
        correction_identity = sha256_text(canonical_json(correction_set))
    except (TypeError, ValueError) as error:
        raise CatalogError("correction_set_catalog_mismatch") from error

    cards: list[DocumentCard] = []
    for row in catalog_rows:
        row_number = int(row["csv_row_number"])
        doc_id = str(row["doc_id"])
        metadata = row["metadata"]
        facts: list[MetadataFact] = []
        for field_name in SUPPORTED_FIELDS:
            value = _cell(metadata.get(field_name))
            amount = _parse_amount(value) if field_name == "project_amount_raw" else None
            normalized = _normalize_field(field_name, value)
            if field_name == "project_amount_raw":
                derived = _parse_amount(metadata.get("project_amount_value"))
                if derived != amount:
                    raise CatalogError("correction_set_catalog_mismatch")

            correction = corrections.get((row_number, field_name))
            if correction is not None:
                effective_expected = (
                    _cell(correction.get("new_value"))
                    if correction["decision"] == "apply"
                    else None
                )
                if value != effective_expected:
                    raise CatalogError("correction_set_catalog_mismatch")
                evidence = _evidence_refs(
                    correction["evidence"],
                    doc_id=doc_id,
                    page_count=page_counts[doc_id],
                )
                decision = str(correction["decision"])
                reason_code = str(correction["reason_code"])
                confidence = str(correction["confidence"])
                correction_id = str(correction["correction_id"])
                checked_at = str(correction["checked_at"])
            else:
                evidence = _catalog_record_evidence(doc_id, field_name)
                decision = None
                reason_code = None
                confidence = None
                correction_id = None
                checked_at = None

            fact_payload = {
                "catalog_identity": expected_snapshot_id,
                "correction_identity": correction_identity,
                "doc_id": doc_id,
                "field": field_name,
            }
            fact_id = "fact_" + sha256_text(canonical_json(fact_payload))[:24]
            facts.append(
                MetadataFact(
                    fact_id=fact_id,
                    doc_id=doc_id,
                    field=field_name,
                    value=value,
                    normalized_value=normalized,
                    value_type=_VALUE_TYPE_BY_FIELD[field_name],
                    state=_state_for(correction, value=value, amount=amount),
                    decision=decision,
                    reason_code=reason_code,
                    confidence=confidence,
                    correction_id=correction_id,
                    checked_at=checked_at,
                    evidence=evidence,
                )
            )
        cards.append(DocumentCard(doc_id=doc_id, facts=tuple(facts)))
    return MetadataCatalog(tuple(cards))
