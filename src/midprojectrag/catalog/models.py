from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from types import MappingProxyType
from typing import Any, Mapping

from midprojectrag.catalog.errors import CatalogError


SUPPORTED_FIELDS = (
    "notice_id_namespace",
    "notice_number",
    "notice_round",
    "project_name",
    "project_amount_raw",
    "ordering_agency",
    "published_at",
    "bid_start_at",
    "bid_end_at",
    "bid_open_at",
    "proposal_evaluation_at",
    "source_format",
)
EVIDENCE_KINDS = (
    "official_web",
    "official_attachment",
    "local_source_block",
    "secondary_web",
    "local_audit",
    "catalog_record",
)
FACT_STATES = (
    "confirmed",
    "source_recorded",
    "source_not_stated",
    "not_applicable",
    "unverified",
    "not_finalized",
    "undisclosed",
    "semantic_mismatch",
    "suspect_sentinel",
    "unknown",
)
VALUE_TYPES = ("text", "krw_amount", "kst_datetime", "source_format")
DECISIONS = ("apply", "clear", "retain_null")
CONFIDENCE_LEVELS = ("high", "medium", "low")

_DOC_ID = re.compile(r"^doc_[0-9a-f]{24}$")
_FACT_ID = re.compile(r"^fact_[0-9a-f]{24}$")
_CORRECTION_ID = re.compile(r"^corr_[a-z0-9_]{1,64}$")
_REASON_CODE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_CANONICAL_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_VALUE_TYPE_BY_FIELD = {
    **{field_name: "text" for field_name in SUPPORTED_FIELDS},
    "project_amount_raw": "krw_amount",
    "published_at": "kst_datetime",
    "bid_start_at": "kst_datetime",
    "bid_end_at": "kst_datetime",
    "bid_open_at": "kst_datetime",
    "proposal_evaluation_at": "kst_datetime",
    "source_format": "source_format",
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


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _optional_filter_text(value: Any, *, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CatalogError("metadata_filter_invalid")
    normalized = _nfc(value).strip()
    if not normalized:
        return None
    if len(normalized) > maximum or "\n" in normalized or "\r" in normalized:
        raise CatalogError("metadata_filter_invalid")
    return normalized


def _calendar_date(value: str | None) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _CANONICAL_DATE.fullmatch(value):
        raise CatalogError("metadata_filter_invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise CatalogError("metadata_filter_invalid") from error
    if parsed.isoformat() != value:
        raise CatalogError("metadata_filter_invalid")
    return parsed


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    source_type: str
    locator: str = field(repr=False)

    def __post_init__(self) -> None:
        if self.source_type not in EVIDENCE_KINDS:
            raise CatalogError("invalid_metadata_provenance")
        if (
            not isinstance(self.locator, str)
            or not self.locator.strip()
            or len(self.locator) > 2048
            or "\n" in self.locator
            or "\r" in self.locator
        ):
            raise CatalogError("invalid_metadata_provenance")

    @property
    def kind(self) -> str:
        """Compatibility alias while keeping the correction vocabulary authoritative."""

        return self.source_type

    def to_public_dict(self) -> dict[str, str]:
        """Return the UI-safe evidence class; the private locator is intentionally omitted."""

        return {"source_type": self.source_type}


@dataclass(frozen=True, slots=True)
class MetadataFact:
    fact_id: str
    doc_id: str
    field: str
    value: str | None = field(repr=False)
    normalized_value: str | None = field(repr=False)
    value_type: str
    state: str
    decision: str | None
    reason_code: str | None
    confidence: str | None
    correction_id: str | None
    checked_at: str | None
    evidence: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.fact_id, str) or not _FACT_ID.fullmatch(self.fact_id):
            raise CatalogError("duplicate_metadata_fact")
        if not isinstance(self.doc_id, str) or not _DOC_ID.fullmatch(self.doc_id):
            raise CatalogError("correction_set_catalog_mismatch")
        if self.field not in SUPPORTED_FIELDS:
            raise CatalogError("invalid_metadata_field")
        if (
            self.value_type not in VALUE_TYPES
            or self.value_type != _VALUE_TYPE_BY_FIELD[self.field]
            or self.state not in FACT_STATES
        ):
            raise CatalogError("invalid_metadata_state")
        if self.value is not None and not isinstance(self.value, str):
            raise CatalogError("invalid_metadata_state")
        if self.normalized_value is not None and not isinstance(
            self.normalized_value, str
        ):
            raise CatalogError("invalid_metadata_state")
        if self.decision is not None and self.decision not in DECISIONS:
            raise CatalogError("invalid_metadata_state")
        if self.confidence is not None and self.confidence not in CONFIDENCE_LEVELS:
            raise CatalogError("invalid_metadata_state")
        if self.reason_code is not None and (
            not isinstance(self.reason_code, str)
            or not _REASON_CODE.fullmatch(self.reason_code)
        ):
            raise CatalogError("invalid_metadata_state")
        if self.correction_id is not None and (
            not isinstance(self.correction_id, str)
            or not _CORRECTION_ID.fullmatch(self.correction_id)
        ):
            raise CatalogError("invalid_metadata_state")
        if self.checked_at is not None:
            try:
                checked = date.fromisoformat(self.checked_at)
            except (TypeError, ValueError) as error:
                raise CatalogError("invalid_metadata_provenance") from error
            if checked.isoformat() != self.checked_at:
                raise CatalogError("invalid_metadata_provenance")
        if not isinstance(self.evidence, tuple) or not self.evidence:
            raise CatalogError("invalid_metadata_provenance")
        if not all(isinstance(item, EvidenceRef) for item in self.evidence):
            raise CatalogError("invalid_metadata_provenance")
        self._validate_state_mapping()

    def _validate_state_mapping(self) -> None:
        correction_fields = (
            self.reason_code,
            self.confidence,
            self.correction_id,
            self.checked_at,
        )
        if self.decision is None:
            if (
                any(item is not None for item in correction_fields)
                or self.state not in {"source_recorded", "suspect_sentinel", "unknown"}
                or any(item.source_type != "catalog_record" for item in self.evidence)
            ):
                raise CatalogError("invalid_metadata_state")
            return
        if any(item is None for item in correction_fields):
            raise CatalogError("invalid_metadata_state")
        if any(item.source_type == "catalog_record" for item in self.evidence):
            raise CatalogError("invalid_metadata_provenance")
        if self.decision == "apply":
            if self.state != "confirmed" or self.value is None or self.confidence != "high":
                raise CatalogError("invalid_metadata_state")
            return
        if self.value is not None:
            raise CatalogError("invalid_metadata_state")
        if self.decision == "clear":
            if self.state != _CLEAR_STATES.get(self.reason_code) or self.confidence != "high":
                raise CatalogError("invalid_metadata_state")
            return
        if self.state != _NULL_STATES.get(self.reason_code):
            raise CatalogError("invalid_metadata_state")

    def to_public_dict(self) -> dict[str, Any]:
        """Serialize a fact without raw evidence locators."""

        return {
            "fact_id": self.fact_id,
            "doc_id": self.doc_id,
            "field": self.field,
            "value": self.value,
            "normalized_value": self.normalized_value,
            "value_type": self.value_type,
            "state": self.state,
            "decision": self.decision,
            "reason_code": self.reason_code,
            "confidence": self.confidence,
            "correction_id": self.correction_id,
            "checked_at": self.checked_at,
            "evidence": [item.to_public_dict() for item in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class DocumentCard:
    doc_id: str
    facts: tuple[MetadataFact, ...] = field(repr=False)
    _facts_by_field: Mapping[str, MetadataFact] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.doc_id, str) or not _DOC_ID.fullmatch(self.doc_id):
            raise CatalogError("correction_set_catalog_mismatch")
        if not isinstance(self.facts, tuple):
            raise CatalogError("duplicate_metadata_fact")
        by_field: dict[str, MetadataFact] = {}
        for fact in self.facts:
            if not isinstance(fact, MetadataFact) or fact.doc_id != self.doc_id:
                raise CatalogError("correction_set_catalog_mismatch")
            if fact.field in by_field:
                raise CatalogError("duplicate_metadata_fact")
            by_field[fact.field] = fact
        if set(by_field) != set(SUPPORTED_FIELDS):
            raise CatalogError("invalid_metadata_field")
        object.__setattr__(
            self,
            "facts",
            tuple(by_field[field_name] for field_name in SUPPORTED_FIELDS),
        )
        object.__setattr__(self, "_facts_by_field", MappingProxyType(by_field))

    def get_fact(self, field: str) -> MetadataFact:
        if field not in SUPPORTED_FIELDS:
            raise CatalogError("invalid_metadata_field")
        return self._facts_by_field[field]

    @property
    def project_name(self) -> str | None:
        return self.get_fact("project_name").value

    @property
    def ordering_agency(self) -> str | None:
        return self.get_fact("ordering_agency").value

    @property
    def notice_number(self) -> str | None:
        return self.get_fact("notice_number").value

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "facts": [fact.to_public_dict() for fact in self.facts],
        }


@dataclass(frozen=True, slots=True)
class CatalogFilter:
    notice_id_namespace: str | None = None
    notice_number: str | None = None
    notice_round: str | None = None
    agency: str | None = None
    amount_min_krw: int | None = None
    amount_max_krw: int | None = None
    bid_end_from: str | None = None
    bid_end_to: str | None = None
    source_formats: tuple[str, ...] = ()
    text: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "notice_id_namespace",
            _optional_filter_text(self.notice_id_namespace, maximum=128),
        )
        object.__setattr__(
            self,
            "notice_number",
            _optional_filter_text(self.notice_number, maximum=128),
        )
        object.__setattr__(
            self,
            "notice_round",
            _optional_filter_text(self.notice_round, maximum=32),
        )
        object.__setattr__(self, "agency", _optional_filter_text(self.agency, maximum=256))
        object.__setattr__(self, "text", _optional_filter_text(self.text, maximum=512))

        for value in (self.amount_min_krw, self.amount_max_krw):
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value < 0
            ):
                raise CatalogError("metadata_filter_invalid")
        if (
            self.amount_min_krw is not None
            and self.amount_max_krw is not None
            and self.amount_min_krw > self.amount_max_krw
        ):
            raise CatalogError("metadata_filter_invalid")

        start = _calendar_date(self.bid_end_from)
        end = _calendar_date(self.bid_end_to)
        if start is not None and end is not None and start > end:
            raise CatalogError("metadata_filter_invalid")

        formats = self.source_formats
        if isinstance(formats, str) or not isinstance(formats, (tuple, list)):
            raise CatalogError("metadata_filter_invalid")
        normalized_formats: list[str] = []
        for item in formats:
            normalized = _optional_filter_text(item, maximum=32)
            if normalized is None:
                raise CatalogError("metadata_filter_invalid")
            normalized_formats.append(normalized.casefold())
        if len(normalized_formats) > 32 or len(set(normalized_formats)) != len(
            normalized_formats
        ):
            raise CatalogError("metadata_filter_invalid")
        object.__setattr__(self, "source_formats", tuple(normalized_formats))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "notice_id_namespace": self.notice_id_namespace,
            "notice_number": self.notice_number,
            "notice_round": self.notice_round,
            "agency": self.agency,
            "amount_min_krw": self.amount_min_krw,
            "amount_max_krw": self.amount_max_krw,
            "bid_end_from": self.bid_end_from,
            "bid_end_to": self.bid_end_to,
            "source_formats": list(self.source_formats),
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class CatalogSearchResult:
    total_count: int
    documents: tuple[DocumentCard, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.total_count, int)
            or isinstance(self.total_count, bool)
            or self.total_count < 0
            or not isinstance(self.documents, tuple)
            or self.total_count != len(self.documents)
        ):
            raise CatalogError("correction_set_catalog_mismatch")

    @property
    def cards(self) -> tuple[DocumentCard, ...]:
        return self.documents

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "total_count": self.total_count,
            "documents": [card.to_public_dict() for card in self.documents],
        }


@dataclass(frozen=True, slots=True)
class MetadataCatalog:
    _documents: tuple[DocumentCard, ...] = field(repr=False)
    _by_doc_id: Mapping[str, DocumentCard] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self._documents, tuple):
            raise CatalogError("correction_set_catalog_mismatch")
        by_doc_id: dict[str, DocumentCard] = {}
        for card in self._documents:
            if not isinstance(card, DocumentCard):
                raise CatalogError("correction_set_catalog_mismatch")
            if card.doc_id in by_doc_id:
                raise CatalogError("duplicate_metadata_fact")
            by_doc_id[card.doc_id] = card
        object.__setattr__(self, "_by_doc_id", MappingProxyType(by_doc_id))

    def list_documents(self) -> tuple[DocumentCard, ...]:
        return self._documents

    def get_document(self, doc_id: str) -> DocumentCard:
        try:
            return self._by_doc_id[doc_id]
        except (KeyError, TypeError) as error:
            raise CatalogError("metadata_document_not_found") from error

    def search(self, filters: CatalogFilter) -> CatalogSearchResult:
        if not isinstance(filters, CatalogFilter):
            raise CatalogError("metadata_filter_invalid")
        matched = tuple(card for card in self._documents if _matches(card, filters))
        return CatalogSearchResult(total_count=len(matched), documents=matched)


def _fact_value(card: DocumentCard, field_name: str) -> str | None:
    return card.get_fact(field_name).normalized_value


def _folded(value: str | None) -> str:
    return _nfc(value or "").casefold()


def _matches(card: DocumentCard, filters: CatalogFilter) -> bool:
    for field_name, expected in (
        ("notice_id_namespace", filters.notice_id_namespace),
        ("notice_number", filters.notice_number),
        ("notice_round", filters.notice_round),
    ):
        if expected is not None and _fact_value(card, field_name) != expected:
            return False

    if filters.agency is not None and _folded(filters.agency) not in _folded(
        _fact_value(card, "ordering_agency")
    ):
        return False

    if filters.amount_min_krw is not None or filters.amount_max_krw is not None:
        amount_text = _fact_value(card, "project_amount_raw")
        if amount_text is None:
            return False
        amount = int(amount_text)
        if amount <= 1:
            return False
        if filters.amount_min_krw is not None and amount < filters.amount_min_krw:
            return False
        if filters.amount_max_krw is not None and amount > filters.amount_max_krw:
            return False

    if filters.bid_end_from is not None or filters.bid_end_to is not None:
        bid_end = _fact_value(card, "bid_end_at")
        if bid_end is None:
            return False
        bid_date = datetime.strptime(bid_end, "%Y-%m-%d %H:%M:%S").date()
        if filters.bid_end_from is not None and bid_date < date.fromisoformat(
            filters.bid_end_from
        ):
            return False
        if filters.bid_end_to is not None and bid_date > date.fromisoformat(filters.bid_end_to):
            return False

    if filters.source_formats:
        source_format = _folded(_fact_value(card, "source_format"))
        if source_format not in filters.source_formats:
            return False

    if filters.text is not None:
        haystack = "\n".join(
            _folded(_fact_value(card, field_name))
            for field_name in ("project_name", "ordering_agency", "notice_number")
        )
        if _folded(filters.text) not in haystack:
            return False
    return True
