"""Provider-free deterministic QueryPlan construction from runtime-only input."""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from hashlib import sha256
import json
import re
import unicodedata
from typing import Any, Mapping

from midprojectrag.runtime_integrity import MetadataPredicate, RuntimeRequest

from .contracts import (
    PlanConstraint,
    PlanEntity,
    QueryPlan,
    RuleRegistry,
    SCOPE_ORIGINS,
)


_CATALOG_SOURCES = frozenset(
    {"agency_alias", "business_alias", "filename_tag", "domain_synonym"}
)
_PREDICATE_STATUSES = frozenset(
    {"supported", "unresolved_constraint", "unsupported_filter"}
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SEMANTIC_TOKEN = re.compile(r"[0-9A-Za-z가-힣]")
_CATALOG_FACTORY_TOKEN = object()
_PLANNER_TEST_TOKEN = object()


def _text(value: Any, code: str, *, maximum: int = 4096) -> str:
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise ValueError(code)
    value.encode("utf-8")
    return value


def _texts(value: Any, code: str, *, maximum: int = 256) -> tuple[str, ...]:
    if type(value) not in (list, tuple):
        raise TypeError(code)
    result = tuple(_text(item, code, maximum=maximum) for item in value)
    if len(result) != len(set(result)):
        raise ValueError(f"duplicate_{code}")
    return result


def _json_array(value: Any, code: str) -> list[Any]:
    if type(value) is not list:
        raise TypeError(code)
    return value


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


def _search_form(value: str) -> str:
    return _normalize(value).casefold()


def _rule_signal_matches(search: str, raw_needle: str) -> bool:
    needle = _search_form(raw_needle)
    if not needle:
        return False
    start = 0
    particles = (
        "에서는", "으로", "에서", "에게", "에는", "이며", "인지",
        "은", "는", "이", "가", "을", "를", "의", "로", "와",
    )
    while True:
        index = search.find(needle, start)
        if index < 0:
            return False
        left_ok = index == 0 or not search[index - 1].isalnum()
        end = index + len(needle)
        right_ok = end == len(search) or not search[end].isalnum()
        if not right_ok:
            remainder = search[end:]
            right_ok = any(
                remainder.startswith(particle)
                and (
                    len(remainder) == len(particle)
                    or not remainder[len(particle)].isalnum()
                )
                for particle in particles
            )
        if left_ok and right_ok:
            return True
        start = index + 1


def _entity_match_spans(search: str, raw_alias: str) -> tuple[tuple[int, int], ...]:
    alias = _search_form(raw_alias)
    spans: list[tuple[int, int]] = []
    start = 0
    while alias:
        index = search.find(alias, start)
        if index < 0:
            break
        end = index + len(alias)
        left_ok = index == 0 or not search[index - 1].isalnum()
        right_ok = end == len(search) or not search[end].isalnum() or not alias[-1].isalnum()
        if not right_ok:
            remainder = search[end:]
            particles = ("에서는", "으로", "에서", "에게", "에는", "은", "는", "이", "가", "을", "를", "의", "로", "와", "과")
            right_ok = any(
                remainder.startswith(particle)
                and (
                    len(remainder) == len(particle)
                    or not remainder[len(particle)].isalnum()
                )
                for particle in particles
            )
        if left_ok and right_ok:
            spans.append((index, end))
        start = index + 1
    return tuple(spans)


def _sha256(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CatalogEntity:
    alias: str
    canonical_value: str
    kind: str
    doc_ids: tuple[str, ...]
    source: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "alias", _normalize(_text(self.alias, "invalid_catalog_alias")))
        object.__setattr__(
            self,
            "canonical_value",
            _normalize(_text(self.canonical_value, "invalid_catalog_canonical_value")),
        )
        object.__setattr__(self, "kind", _text(self.kind, "invalid_catalog_entity_kind", maximum=128))
        object.__setattr__(self, "doc_ids", tuple(sorted(_texts(self.doc_ids, "catalog_doc_ids"))))
        if not self.doc_ids:
            raise ValueError("catalog_entity_requires_doc_ids")
        if self.source not in _CATALOG_SOURCES:
            raise ValueError("invalid_catalog_entity_source")

    def to_dict(self) -> dict[str, Any]:
        return {
            "alias": self.alias,
            "canonical_value": self.canonical_value,
            "kind": self.kind,
            "doc_ids": list(self.doc_ids),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> CatalogEntity:
        fields = {"alias", "canonical_value", "kind", "doc_ids", "source"}
        if not isinstance(raw, Mapping) or set(raw) != fields:
            raise ValueError("catalog_entity_fields")
        _json_array(raw["doc_ids"], "catalog_entity_doc_ids_array")
        return cls(**raw)


@dataclass(frozen=True, slots=True)
class CatalogDocument:
    """Minimal production metadata projection used to derive aliases."""

    doc_id: str
    title: str
    agency: str = ""
    filename: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "doc_id", _text(self.doc_id, "invalid_catalog_doc_id", maximum=256))
        object.__setattr__(self, "title", _normalize(_text(self.title, "invalid_catalog_title")))
        for name in ("agency", "filename"):
            value = getattr(self, name)
            if type(value) is not str or len(value) > 4096:
                raise ValueError(f"invalid_catalog_{name}")
            value.encode("utf-8")
            object.__setattr__(self, name, _normalize(value) if value.strip() else "")

    def to_dict(self) -> dict[str, str]:
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "agency": self.agency,
            "filename": self.filename,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> CatalogDocument:
        if not isinstance(raw, Mapping) or set(raw) != {"doc_id", "title", "agency", "filename"}:
            raise ValueError("catalog_document_fields")
        return cls(**raw)


def _catalog_entity_identity(value: CatalogEntity) -> tuple[Any, ...]:
    return (
        _search_form(value.alias),
        value.canonical_value,
        value.kind,
        value.source,
        value.doc_ids,
    )


def _canonical_entities(values: tuple[CatalogEntity, ...]) -> tuple[CatalogEntity, ...]:
    identities = tuple(_catalog_entity_identity(value) for value in values)
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate_catalog_entities")
    return tuple(
        value
        for _, value in sorted(
            zip(identities, values),
            key=lambda item: (-len(_search_form(item[1].alias)), item[0]),
        )
    )


def _derive_catalog_entities(
    documents: tuple[CatalogDocument, ...],
) -> tuple[CatalogEntity, ...]:
    grouped: dict[tuple[str, str, str, str], set[str]] = {}

    def add(alias: str, canonical: str, kind: str, source: str, doc_id: str) -> None:
        if not alias.strip():
            return
        key = (_normalize(alias), _normalize(canonical), kind, source)
        grouped.setdefault(key, set()).add(doc_id)

    for document in documents:
        add(document.title, document.title, "business", "business_alias", document.doc_id)
        add(document.agency, document.agency, "agency", "agency_alias", document.doc_id)
        for tag in re.findall(r"\[[^\[\]\n]{1,64}\]", document.filename):
            add(tag, tag[1:-1].strip(), "filename_tag", "filename_tag", document.doc_id)
    return _canonical_entities(tuple(
        CatalogEntity(alias, canonical, kind, tuple(sorted(doc_ids)), source)
        for (alias, canonical, kind, source), doc_ids in sorted(grouped.items())
    ))


def _catalog_source_sha256(
    source_kind: str,
    entities: tuple[CatalogEntity, ...],
    documents: tuple[CatalogDocument, ...],
) -> str:
    if source_kind == "production_metadata":
        payload = {
            "source_kind": source_kind,
            "documents": [value.to_dict() for value in documents],
        }
    else:
        payload = {
            "source_kind": source_kind,
            "entities": [value.to_dict() for value in entities],
        }
    return _sha256(payload)


@dataclass(frozen=True, slots=True)
class PlanningCatalog:
    catalog_version: str
    entities: tuple[CatalogEntity, ...]
    source_kind: str = ""
    source_sha256: str = ""
    source_documents: tuple[CatalogDocument, ...] = ()
    _factory_token: InitVar[object] = field(default=None, repr=False, kw_only=True)

    def __post_init__(self, _factory_token: object) -> None:
        if _factory_token is not _CATALOG_FACTORY_TOKEN:
            raise ValueError("planning_catalog_factory_required")
        object.__setattr__(
            self,
            "catalog_version",
            _text(self.catalog_version, "invalid_catalog_version", maximum=128),
        )
        entities = tuple(self.entities)
        if any(type(value) is not CatalogEntity for value in entities):
            raise TypeError("invalid_catalog_entities")
        if self.source_kind not in {"production_metadata", "synthetic_fixture"}:
            raise ValueError("invalid_catalog_source_kind")
        if type(self.source_sha256) is not str or not _HEX64.fullmatch(self.source_sha256):
            raise ValueError("invalid_catalog_source_sha256")
        documents = tuple(self.source_documents)
        if any(type(value) is not CatalogDocument for value in documents):
            raise TypeError("invalid_catalog_source_documents")
        if len({value.doc_id for value in documents}) != len(documents):
            raise ValueError("duplicate_catalog_document_ids")
        documents = tuple(sorted(documents, key=lambda value: value.doc_id))
        if self.source_kind == "synthetic_fixture" and documents:
            raise ValueError("synthetic_catalog_has_source_documents")
        if self.source_kind == "production_metadata" and not documents:
            raise ValueError("production_catalog_requires_source_documents")
        entities = _canonical_entities(entities)
        object.__setattr__(self, "source_documents", documents)
        object.__setattr__(self, "entities", entities)
        expected_source_sha256 = _catalog_source_sha256(
            self.source_kind, entities, documents
        )
        if self.source_sha256 != expected_source_sha256:
            raise ValueError("catalog_source_sha256_mismatch")
        if (
            self.source_kind == "production_metadata"
            and entities != _derive_catalog_entities(documents)
        ):
            raise ValueError("catalog_entities_not_derived_from_source")

    @classmethod
    def synthetic(
        cls, catalog_version: str, entities: tuple[CatalogEntity, ...] | list[CatalogEntity]
    ) -> PlanningCatalog:
        values = tuple(entities)
        if any(type(value) is not CatalogEntity for value in values):
            raise TypeError("invalid_catalog_entities")
        values = _canonical_entities(values)
        source_sha256 = _catalog_source_sha256("synthetic_fixture", values, ())
        return cls(
            catalog_version=catalog_version,
            entities=values,
            source_kind="synthetic_fixture",
            source_sha256=source_sha256,
            source_documents=(),
            _factory_token=_CATALOG_FACTORY_TOKEN,
        )

    @classmethod
    def from_metadata(
        cls,
        catalog_version: str,
        documents: tuple[CatalogDocument, ...] | list[CatalogDocument],
    ) -> PlanningCatalog:
        values = tuple(documents)
        if any(type(value) is not CatalogDocument for value in values):
            raise TypeError("catalog_documents_required")
        if len({value.doc_id for value in values}) != len(values):
            raise ValueError("duplicate_catalog_document_ids")
        ordered = tuple(sorted(values, key=lambda value: value.doc_id))
        source_sha256 = _catalog_source_sha256("production_metadata", (), ordered)
        entities = _derive_catalog_entities(ordered)
        return cls(
            catalog_version=catalog_version,
            entities=entities,
            source_kind="production_metadata",
            source_sha256=source_sha256,
            source_documents=ordered,
            _factory_token=_CATALOG_FACTORY_TOKEN,
        )

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "catalog_version": self.catalog_version,
            "source_kind": self.source_kind,
            "source_sha256": self.source_sha256,
            "source_documents": [value.to_dict() for value in self.source_documents],
            "entities": [value.to_dict() for value in self.entities],
        }

    @property
    def catalog_sha256(self) -> str:
        return _sha256(self._payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "catalog_sha256": self.catalog_sha256}

    @classmethod
    def from_dict(
        cls,
        raw: Mapping[str, Any],
        *,
        expected_source_sha256: str,
    ) -> PlanningCatalog:
        if type(expected_source_sha256) is not str or not _HEX64.fullmatch(expected_source_sha256):
            raise ValueError("expected_catalog_source_sha256_required")
        fields = {
            "schema_version", "catalog_version", "source_kind", "source_sha256",
            "source_documents", "entities", "catalog_sha256",
        }
        if not isinstance(raw, Mapping) or set(raw) != fields:
            raise ValueError("planning_catalog_fields")
        if raw["schema_version"] != "1.0":
            raise ValueError("unsupported_planning_catalog_version")
        if raw["source_sha256"] != expected_source_sha256:
            raise ValueError("catalog_source_attestation_mismatch")
        if type(raw["entities"]) is not list or type(raw["source_documents"]) is not list:
            raise TypeError("invalid_catalog_payload")
        entities = tuple(CatalogEntity.from_dict(value) for value in raw["entities"])
        if raw["source_kind"] == "production_metadata":
            documents = tuple(
                CatalogDocument.from_dict(value) for value in raw["source_documents"]
            )
            catalog = cls.from_metadata(raw["catalog_version"], documents)
            if entities != catalog.entities:
                raise ValueError("catalog_entities_not_derived_from_source")
        elif raw["source_kind"] == "synthetic_fixture":
            if raw["source_documents"]:
                raise ValueError("synthetic_catalog_has_source_documents")
            catalog = cls.synthetic(raw["catalog_version"], entities)
        else:
            raise ValueError("invalid_catalog_source_kind")
        if raw["source_sha256"] != catalog.source_sha256:
            raise ValueError("catalog_source_sha256_mismatch")
        if raw["catalog_sha256"] != catalog.catalog_sha256:
            raise ValueError("catalog_sha256_mismatch")
        return catalog


@dataclass(frozen=True, slots=True)
class PlanningTrace:
    request_fingerprint: str
    config_sha256: str
    catalog_sha256: str
    catalog_source_kind: str
    catalog_source_sha256: str
    execution_kind: str
    matched_rule_ids: tuple[str, ...]
    matched_rule_sources: tuple[str, ...]
    scope_state: str
    scope_origin: str
    resolved_doc_ids: tuple[str, ...]
    predicate_statuses: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "request_fingerprint", "config_sha256", "catalog_sha256", "catalog_source_sha256"
        ):
            value = getattr(self, name)
            if type(value) is not str or not _HEX64.fullmatch(value):
                raise ValueError(f"invalid_{name}")
        if self.catalog_source_kind not in {"production_metadata", "synthetic_fixture"}:
            raise ValueError("invalid_trace_catalog_source_kind")
        if self.execution_kind not in {"production", "synthetic"}:
            raise ValueError("invalid_planner_execution_kind")
        if (self.catalog_source_kind == "synthetic_fixture") != (self.execution_kind == "synthetic"):
            raise ValueError("planner_execution_kind_mismatch")
        object.__setattr__(self, "matched_rule_ids", _texts(self.matched_rule_ids, "matched_rule_ids", maximum=128))
        object.__setattr__(self, "matched_rule_sources", _texts(self.matched_rule_sources, "matched_rule_sources", maximum=128))
        if len(self.matched_rule_ids) != len(self.matched_rule_sources):
            raise ValueError("matched_rule_trace_mismatch")
        if self.scope_state not in {"unfiltered", "empty", "restricted"}:
            raise ValueError("invalid_planning_scope_state")
        if self.scope_origin not in SCOPE_ORIGINS:
            raise ValueError("invalid_planning_scope_origin")
        object.__setattr__(self, "resolved_doc_ids", _texts(self.resolved_doc_ids, "trace_doc_ids"))
        if (self.scope_state == "restricted") != bool(self.resolved_doc_ids):
            raise ValueError("inconsistent_planning_scope")
        statuses = tuple(self.predicate_statuses)
        if any(value not in _PREDICATE_STATUSES for value in statuses):
            raise ValueError("invalid_predicate_status_trace")
        object.__setattr__(self, "predicate_statuses", statuses)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_fingerprint": self.request_fingerprint,
            "config_sha256": self.config_sha256,
            "catalog_sha256": self.catalog_sha256,
            "catalog_source_kind": self.catalog_source_kind,
            "catalog_source_sha256": self.catalog_source_sha256,
            "execution_kind": self.execution_kind,
            "matched_rule_ids": list(self.matched_rule_ids),
            "matched_rule_sources": list(self.matched_rule_sources),
            "scope_state": self.scope_state,
            "scope_origin": self.scope_origin,
            "resolved_doc_ids": list(self.resolved_doc_ids),
            "predicate_statuses": list(self.predicate_statuses),
        }


@dataclass(frozen=True, slots=True)
class PlanningResult:
    plan: QueryPlan
    trace: PlanningTrace

    def __post_init__(self) -> None:
        if type(self.plan) is not QueryPlan or type(self.trace) is not PlanningTrace:
            raise TypeError("invalid_planning_result")
        if self.plan.config_sha256 != self.trace.config_sha256:
            raise ValueError("planning_result_config_mismatch")
        if self.plan.resolved_doc_ids != self.trace.resolved_doc_ids:
            raise ValueError("planning_result_scope_mismatch")
        if (
            self.plan.scope_state != self.trace.scope_state
            or self.plan.scope_origin != self.trace.scope_origin
        ):
            raise ValueError("planning_result_scope_trace_mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {"plan": self.plan.to_dict(), "trace": self.trace.to_dict()}


@dataclass(frozen=True, slots=True)
class DeterministicPlanner:
    registry: RuleRegistry
    catalog: PlanningCatalog
    _test_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if type(self.registry) is not RuleRegistry:
            raise TypeError("rule_registry_required")
        if type(self.catalog) is not PlanningCatalog:
            raise TypeError("planning_catalog_required")
        from .contracts import default_rule_registry

        if self.registry.config_sha256 != default_rule_registry().config_sha256:
            raise ValueError("unapproved_rule_registry")
        if self.catalog.source_kind == "synthetic_fixture" and self._test_token is not _PLANNER_TEST_TOKEN:
            raise ValueError("synthetic_catalog_requires_test_planner")

    @classmethod
    def for_test(
        cls, registry: RuleRegistry, catalog: PlanningCatalog
    ) -> DeterministicPlanner:
        if type(catalog) is not PlanningCatalog or catalog.source_kind != "synthetic_fixture":
            raise ValueError("synthetic_planning_catalog_required")
        return cls(registry, catalog, _PLANNER_TEST_TOKEN)

    def _select_rule(self, request: RuntimeRequest, query: str):
        search = _search_form(query)
        prior = request.prior_citation_state
        has_actual_citation = False
        if (
            prior
            and prior["cited_doc_ids"]
            and prior["cited_evidence_ids"]
        ):
            for turn in reversed(request.history):
                if turn["role"] != "assistant":
                    continue
                has_actual_citation = (
                    tuple(turn.get("cited_doc_ids", ()))
                    == tuple(prior["cited_doc_ids"])
                    and tuple(turn.get("cited_evidence_ids", ()))
                    == tuple(prior["cited_evidence_ids"])
                )
                break
        for rule in self.registry.rules:
            if rule.source == "history_citation" and not has_actual_citation:
                continue
            if rule.source not in {"history_citation", "query_expression"}:
                continue
            if any(_rule_signal_matches(search, signal) for signal in rule.signals):
                return rule
        return None

    def _entities(self, query: str):
        search = _search_form(query)
        matched: list[PlanEntity] = []
        unresolved: list[str] = []
        accepted_spans: list[tuple[int, int]] = []
        grouped: dict[str, list[CatalogEntity]] = {}
        for value in self.catalog.entities:
            grouped.setdefault(_search_form(value.alias), []).append(value)
        entity_signal_seen = False
        for alias, values in sorted(grouped.items(), key=lambda item: (-len(item[0]), item[0])):
            spans = tuple(
                span
                for span in _entity_match_spans(search, alias)
                if not any(
                    span[0] < end and start < span[1]
                    for start, end in accepted_spans
                )
            )
            if not spans:
                continue
            entity_signal_seen = True
            accepted_spans.extend(spans)
            if len(values) != 1:
                unresolved.append(f"ambiguous_entity_alias:{sha256(alias.encode('utf-8')).hexdigest()[:12]}")
                continue
            value = values[0]
            matched.append(
                PlanEntity(
                    value=value.canonical_value,
                    kind=value.kind,
                    source=value.source,
                    resolved_doc_ids=value.doc_ids,
                )
            )
        return tuple(matched), tuple(unresolved), entity_signal_seen

    @staticmethod
    def _predicates(request: RuntimeRequest):
        predicates = tuple(
            MetadataPredicate.from_dict(
                {"field": raw["field"], "operator": raw["operator"], "value": raw["value"]}
            )
            for raw in request.metadata_filters
        )
        constraints = tuple(
            PlanConstraint(
                kind=f"metadata:{value.field}",
                value=json.dumps(
                    value.to_dict()["value"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                source="metadata_predicate",
                status={
                    "supported": "resolved",
                    "unresolved_constraint": "unresolved",
                    "unsupported_filter": "unsupported",
                }[value.status],
            )
            for value in predicates
        )
        unresolved = tuple(
            f"metadata_predicate:{index}:{value.status}"
            for index, value in enumerate(predicates)
            if value.status != "supported"
        )
        return predicates, constraints, unresolved

    @staticmethod
    def _scope(
        request: RuntimeRequest,
        entities: tuple[PlanEntity, ...],
        entity_signal_seen: bool,
        entity_resolution_failed: bool,
    ):
        entity_docs = frozenset(
            doc_id for entity in entities for doc_id in entity.resolved_doc_ids
        )
        if request.document_scope["mode"] == "explicit":
            explicit = tuple(request.document_scope["doc_ids"])
            if entity_signal_seen:
                resolved = () if entity_resolution_failed else tuple(
                    doc_id for doc_id in explicit if doc_id in entity_docs
                )
                origin = "user_explicit+entity_resolution"
            else:
                resolved = explicit
                origin = "user_explicit"
            state = "restricted" if resolved else "empty"
            return resolved, state, origin
        if entity_signal_seen:
            resolved = () if entity_resolution_failed else tuple(sorted(entity_docs))
            return resolved, ("restricted" if resolved else "empty"), "entity_resolution"
        return (), "unfiltered", "all"

    def plan(self, request: RuntimeRequest) -> PlanningResult:
        if type(request) is not RuntimeRequest:
            raise TypeError("runtime_request_required")
        normalized_query = _normalize(request.question)
        rule = self._select_rule(request, normalized_query)
        if not _SEMANTIC_TOKEN.search(normalized_query):
            query_type = "unknown_or_out_of_scope"
            unresolved_query = ("no_semantic_query_token",)
            rule = None
        else:
            query_type = rule.output_query_type if rule is not None else "fact"
            unresolved_query = ()
        entities, unresolved_entities, entity_signal_seen = self._entities(normalized_query)
        entity_resolution_failed = any(
            value.startswith("ambiguous_entity_alias:") for value in unresolved_entities
        )
        resolved_doc_ids, scope_state, scope_origin = self._scope(
            request, entities, entity_signal_seen, entity_resolution_failed
        )
        predicates, constraints, unresolved_predicates = self._predicates(request)
        unresolved = unresolved_query + unresolved_entities + unresolved_predicates
        requested_fallback = bool(request.options.get("allow_global_fallback", False))
        allow_global_fallback = (
            requested_fallback
            and query_type != "unknown_or_out_of_scope"
            and request.document_scope["mode"] == "all"
            and scope_state != "empty"
            and scope_origin == "all"
        )
        plan = self.registry.make_plan(
            query_type=query_type,
            normalized_query=normalized_query,
            entities=entities,
            resolved_doc_ids=resolved_doc_ids,
            scope_state=scope_state,
            scope_origin=scope_origin,
            constraints=constraints,
            metadata_predicates=predicates,
            allow_global_fallback=allow_global_fallback,
            unresolved_constraints=unresolved,
        )
        matched_rule_ids = () if rule is None else (rule.rule_id,)
        matched_rule_sources = () if rule is None else (rule.source,)
        trace = PlanningTrace(
            request_fingerprint=request.fingerprint,
            config_sha256=self.registry.config_sha256,
            catalog_sha256=self.catalog.catalog_sha256,
            catalog_source_kind=self.catalog.source_kind,
            catalog_source_sha256=self.catalog.source_sha256,
            execution_kind=(
                "synthetic" if self.catalog.source_kind == "synthetic_fixture" else "production"
            ),
            matched_rule_ids=matched_rule_ids,
            matched_rule_sources=matched_rule_sources,
            scope_state=scope_state,
            scope_origin=scope_origin,
            resolved_doc_ids=resolved_doc_ids,
            predicate_statuses=tuple(value.status for value in predicates),
        )
        return PlanningResult(plan, trace)
