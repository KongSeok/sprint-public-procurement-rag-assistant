"""Gold-free compare target and document-by-field slot binding."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
import unicodedata
from collections.abc import Mapping
from typing import Any
from weakref import ReferenceType, ref

from midprojectrag.evidence import EvidenceStore
from midprojectrag.runtime_integrity import RuntimeRequest

from .contracts import PlanConstraint, QueryPlan, RequiredSlot
from .planner import DeterministicPlanner, PlanningResult, PlanningTrace


_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_FIELD = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_COMPARE_REGISTRY_TOKEN = object()
_BOUND_COMPARE_TOKEN = object()
_BOUND_COMPARE_AUTHORITIES: dict[int, tuple[ReferenceType[BoundCompare], str]] = {}
_COMPARE_REASONS = frozenset(
    {
        "ready",
        "compare_scope_unresolved",
        "compare_scope_empty",
        "compare_requires_multiple_documents",
        "compare_targets_ambiguous",
        "compare_target_limit_exceeded",
        "compare_document_not_in_store",
        "compare_fields_unresolved",
        "compare_fields_unsupported",
        "compare_targets_unresolved",
        "compare_field_limit_exceeded",
        "compare_slot_limit_exceeded",
        "compare_metadata_unresolved",
        "compare_metadata_scope_receipt_required",
    }
)

_FIELD_RULE_FIELDS = frozenset({"rule_id", "field", "signals", "priority"})
_FIELD_REGISTRY_FIELDS = frozenset(
    {
        "schema_version",
        "registry_version",
        "selection_policy",
        "rules",
        "max_documents",
        "max_fields",
        "max_slots",
        "config_sha256",
    }
)
_BINDING_TRACE_FIELDS = frozenset(
    {
        "schema_version",
        "request_fingerprint",
        "routing_config_sha256",
        "compare_config_sha256",
        "catalog_sha256",
        "catalog_source_kind",
        "catalog_source_sha256",
        "execution_kind",
        "planning_trace_sha256",
        "planning_result_sha256",
        "base_plan_sha256",
        "effective_plan_sha256",
        "evidence_bundle_sha256",
        "status",
        "reason",
        "scope_source",
        "resolved_doc_ids",
        "selected_fields",
        "matched_field_rule_ids",
        "required_slot_keys",
    }
)
_BOUND_COMPARE_FIELDS = frozenset(
    {"schema_version", "planning", "effective_plan", "trace", "binding_sha256"}
)


def _canonical_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _validated_planning_hashes(planning: PlanningResult) -> tuple[str, str]:
    """Canonicalize every plan/trace field before it can carry authority."""

    if type(planning) is not PlanningResult:
        raise TypeError("compare_planning_result_required")
    if type(planning.plan) is not QueryPlan or type(planning.trace) is not PlanningTrace:
        raise TypeError("compare_planning_result_required")
    try:
        # Reconstruct through the closed production contracts. Calling to_dict
        # alone is insufficient because object.__new__/object.__setattr__ can
        # bypass dataclass post-init validation.
        from .contracts import default_rule_registry

        registry = default_rule_registry()
        canonical_plan = registry.plan_from_dict(planning.plan.to_dict())
        trace_payload = planning.trace.to_dict()
        canonical_trace = PlanningTrace(**trace_payload)
        canonical = PlanningResult(canonical_plan, canonical_trace)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("compare_planning_integrity_mismatch") from exc
    supplied_payload = planning.to_dict()
    canonical_payload = canonical.to_dict()
    if _canonical_sha256(supplied_payload) != _canonical_sha256(canonical_payload):
        raise ValueError("compare_planning_integrity_mismatch")
    return (
        _canonical_sha256(trace_payload),
        _canonical_sha256(canonical_payload),
    )


def _bound_compare_payload(
    planning: PlanningResult,
    plan: QueryPlan,
    trace: CompareBindingTrace,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "planning": planning.to_dict(),
        "effective_plan": plan.to_dict(),
        "trace": trace.to_dict(),
    }


def _drop_bound_compare_authority(identity: int, dead: ReferenceType[Any]) -> None:
    current = _BOUND_COMPARE_AUTHORITIES.get(identity)
    if current is not None and current[0] is dead:
        _BOUND_COMPARE_AUTHORITIES.pop(identity, None)


def _register_bound_compare_authority(bound: BoundCompare) -> None:
    """Bind authority to object identity and its complete canonical payload."""

    identity = id(bound)
    weak = ref(
        bound,
        lambda dead, identity=identity: _drop_bound_compare_authority(identity, dead),
    )
    _BOUND_COMPARE_AUTHORITIES[identity] = (
        weak,
        _canonical_sha256(
            _bound_compare_payload(bound.planning, bound.plan, bound.trace)
        ),
    )


def _require_bound_compare_authority(bound: BoundCompare) -> None:
    """Require the exact factory-issued, unchanged BoundCompare instance."""

    if type(bound) is not BoundCompare:
        raise TypeError("bound_compare_required")
    current = _BOUND_COMPARE_AUTHORITIES.get(id(bound))
    if current is None or current[0]() is not bound:
        raise ValueError("bound_compare_runtime_authority_required")
    expected = _canonical_sha256(
        _bound_compare_payload(bound.planning, bound.plan, bound.trace)
    )
    if current[1] != expected:
        raise ValueError("bound_compare_runtime_authority_drift")


def _closed(value: Any, fields: frozenset[str], code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(code)
    if any(type(key) is not str for key in value):
        raise TypeError(code)
    return value


def _json_list(value: Any, code: str) -> list[Any]:
    if type(value) is not list:
        raise TypeError(code)
    return value


def _text(value: Any, code: str, *, maximum: int = 4096) -> str:
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise ValueError(code)
    value.encode("utf-8")
    return value


def _texts(value: Any, code: str, *, maximum: int = 256) -> tuple[str, ...]:
    if type(value) not in (tuple, list):
        raise TypeError(code)
    result = tuple(_text(item, code, maximum=maximum) for item in value)
    if len(result) != len(set(result)):
        raise ValueError(f"duplicate_{code}")
    return result


def _hash(value: str, code: str) -> str:
    if type(value) is not str or not _HEX64.fullmatch(value):
        raise ValueError(code)
    return value


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split()).casefold()


def _signal_matches(query: str, signal: str) -> bool:
    """Match a registry signal without accepting arbitrary compound substrings."""

    return bool(_signal_match_spans(query, signal))


def _signal_match_spans(query: str, signal: str) -> tuple[tuple[int, int], ...]:
    """Return boundary-aware signal spans in a normalized compare query."""

    search = _normalize(query)
    needle = _normalize(signal)
    particles = (
        "에서는",
        "으로",
        "에서",
        "에게",
        "에는",
        "이며",
        "인지",
        "은",
        "는",
        "이",
        "가",
        "을",
        "를",
        "의",
        "로",
        "와",
        "과",
        "만",
        "도",
        "하고",
        "랑",
        "이랑",
    )
    matches: list[tuple[int, int]] = []
    start = 0
    while needle:
        index = search.find(needle, start)
        if index < 0:
            break
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
            matches.append((index, end))
        start = index + 1
    return tuple(matches)


_FIELD_NEGATION = re.compile(
    r"^(?:은|는|이|가|을|를|도|만은)?\s*"
    r"(?:(?:비교|대조)\s*)?"
    r"(?:하지\s*말고|하지\s*않고|하지\s*않으며|"
    r"제외(?:하고|해서|해|하여)?|빼고|말고)"
)
_COMPARE_GRAMMAR_WORDS = frozenset(
    {
        "은", "는", "이", "가", "을", "를", "의", "과", "와", "로", "으로",
        "에서", "에서는", "에게", "에는", "만", "도", "및", "하고", "랑", "이랑",
        "또는", "두", "세", "네", "여러", "각", "각각", "서로", "사이", "간",
        "문서", "문서의", "문서에서", "사업", "사업의", "사업에서", "공고", "공고의",
        "제안서", "제안서의", "중", "중에서", "어느", "어떤",
        "더", "가장", "큰지", "작은지", "높은지", "낮은지", "같이", "함께",
        "기준으로", "대해서", "관해", "표", "표로",
        "비교", "비교해", "비교해줘", "비교해주세요", "비교하여", "비교해서",
        "비교하면", "비교하고", "비교한", "비교하지", "대조", "대조해줘",
        "차이", "차이를", "차이는", "차이가", "차이점", "차이점을", "말고",
        "않고", "않으며", "제외하고", "빼고", "알려줘", "알려주세요", "보여줘",
        "보여주세요", "정리해줘", "정리해주세요", "설명해줘", "설명해주세요",
    }
)


def _span_is_negated(query: str, end: int) -> bool:
    return bool(_FIELD_NEGATION.match(query[end : end + 32]))


def _select_requested_fields(
    query: str,
    registry: CompareFieldRegistry,
) -> tuple[tuple[CompareFieldRule, ...], tuple[tuple[int, int], ...]]:
    """Select only positively requested fields and retain all consumed spans."""

    selected: list[CompareFieldRule] = []
    consumed: list[tuple[int, int]] = []
    for rule in registry.rules:
        spans = tuple(
            span
            for signal in sorted(rule.signals, key=lambda item: (-len(_normalize(item)), item))
            for span in _signal_match_spans(query, signal)
        )
        consumed.extend(spans)
        if spans and any(not _span_is_negated(query, end) for _start, end in spans):
            selected.append(rule)
    return tuple(selected), tuple(sorted(set(consumed)))


def _unconsumed_compare_terms(
    query: str,
    consumed_spans: tuple[tuple[int, int], ...],
) -> tuple[str, ...]:
    chars = list(query)
    for start, end in consumed_spans:
        chars[start:end] = " " * (end - start)
    tokens = re.findall(r"[0-9a-z가-힣]+", "".join(chars).casefold())
    return tuple(token for token in tokens if token not in _COMPARE_GRAMMAR_WORDS)


def _mask_query_spans(
    query: str, spans: tuple[tuple[int, int], ...]
) -> str:
    chars = list(query)
    for start, end in spans:
        chars[start:end] = " " * (end - start)
    return _normalize("".join(chars))


def _unresolved_field_intent_reason(
    query: str,
    selected_rules: tuple[CompareFieldRule, ...],
    consumed_spans: tuple[tuple[int, int], ...],
    *,
    scope_source: str,
) -> str | None:
    """Fail closed when an explicit compare axis or named target was dropped."""

    if not selected_rules:
        return None
    residual = _unconsumed_compare_terms(query, consumed_spans)
    if not residual:
        return None
    if scope_source == "named_business_entities" and any(
        "사업" in token or token.endswith(("사", "기관", "학교"))
        for token in residual
    ):
        return "compare_targets_unresolved"
    return "compare_fields_unsupported"


@dataclass(frozen=True, slots=True)
class CompareFieldRule:
    rule_id: str
    field: str
    signals: tuple[str, ...]
    priority: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "rule_id", _text(self.rule_id, "invalid_compare_field_rule_id", maximum=128)
        )
        if type(self.field) is not str or not _FIELD.fullmatch(self.field):
            raise ValueError("invalid_compare_field")
        object.__setattr__(
            self,
            "signals",
            _texts(self.signals, "compare_field_signals", maximum=128),
        )
        if not self.signals:
            raise ValueError("compare_field_signals_required")
        if type(self.priority) is not int or self.priority < 0:
            raise ValueError("invalid_compare_field_priority")

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "field": self.field,
            "signals": list(self.signals),
            "priority": self.priority,
        }

    def matches(self, text: str) -> bool:
        value = _text(text, "invalid_compare_field_match_text", maximum=1_000_000)
        return any(_signal_matches(value, signal) for signal in self.signals)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> CompareFieldRule:
        value = _closed(raw, _FIELD_RULE_FIELDS, "compare_field_rule_fields")
        _json_list(value["signals"], "compare_field_rule_signals_array")
        return cls(
            rule_id=value["rule_id"],
            field=value["field"],
            signals=tuple(value["signals"]),
            priority=value["priority"],
        )


@dataclass(frozen=True, slots=True, init=False)
class CompareFieldRegistry:
    registry_version: str
    rules: tuple[CompareFieldRule, ...]
    max_documents: int
    max_fields: int
    max_slots: int
    config_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("compare_field_registry_factory_required")

    @classmethod
    def _create(
        cls,
        *,
        registry_version: str,
        rules: tuple[CompareFieldRule, ...],
        max_documents: int,
        max_fields: int,
        max_slots: int,
        _token: object,
    ) -> CompareFieldRegistry:
        if _token is not _COMPARE_REGISTRY_TOKEN:
            raise ValueError("compare_field_registry_factory_required")
        version = _text(
            registry_version, "invalid_compare_registry_version", maximum=128
        )
        if any(type(rule) is not CompareFieldRule for rule in rules):
            raise TypeError("invalid_compare_field_rules")
        rule_ids = tuple(rule.rule_id for rule in rules)
        fields = tuple(rule.field for rule in rules)
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("duplicate_compare_field_rule_ids")
        if len(fields) != len(set(fields)):
            raise ValueError("duplicate_compare_fields")
        normalized_signals = tuple(
            _normalize(signal) for rule in rules for signal in rule.signals
        )
        if len(normalized_signals) != len(set(normalized_signals)):
            raise ValueError("ambiguous_compare_field_signal")
        for name, value in (
            ("max_documents", max_documents),
            ("max_fields", max_fields),
            ("max_slots", max_slots),
        ):
            if type(value) is not int or value < 2:
                raise ValueError(f"invalid_compare_{name}")
        ordered = tuple(sorted(rules, key=lambda rule: (-rule.priority, rule.field)))
        payload = {
            "schema_version": "1.0",
            "registry_version": version,
            "selection_policy": "explicit-positive-signals-complete-intent-v2",
            "rules": [rule.to_dict() for rule in ordered],
            "max_documents": max_documents,
            "max_fields": max_fields,
            "max_slots": max_slots,
        }
        result = object.__new__(cls)
        for name, value in (
            ("registry_version", version),
            ("rules", ordered),
            ("max_documents", max_documents),
            ("max_fields", max_fields),
            ("max_slots", max_slots),
            ("config_sha256", _canonical_sha256(payload)),
        ):
            object.__setattr__(result, name, value)
        result._validate()
        return result

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "registry_version": self.registry_version,
            "selection_policy": "explicit-positive-signals-complete-intent-v2",
            "rules": [rule.to_dict() for rule in self.rules],
            "max_documents": self.max_documents,
            "max_fields": self.max_fields,
            "max_slots": self.max_slots,
        }

    def _validate(self) -> None:
        _text(
            self.registry_version, "invalid_compare_registry_version", maximum=128
        )
        if any(type(rule) is not CompareFieldRule for rule in self.rules):
            raise TypeError("invalid_compare_field_rules")
        if self.config_sha256 != _canonical_sha256(self._payload()):
            raise ValueError("compare_registry_hash_mismatch")

    def select(self, normalized_query: str) -> tuple[CompareFieldRule, ...]:
        self._validate()
        query = _text(normalized_query, "invalid_compare_query")
        selected, _consumed = _select_requested_fields(_normalize(query), self)
        return selected

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "config_sha256": self.config_sha256}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> CompareFieldRegistry:
        value = _closed(raw, _FIELD_REGISTRY_FIELDS, "compare_field_registry_fields")
        if value["schema_version"] != "1.0":
            raise ValueError("unsupported_compare_field_registry_version")
        if value["selection_policy"] != "explicit-positive-signals-complete-intent-v2":
            raise ValueError("unapproved_compare_field_selection_policy")
        rules = tuple(
            CompareFieldRule.from_dict(item)
            for item in _json_list(value["rules"], "compare_field_rules_array")
        )
        registry = cls._create(
            registry_version=value["registry_version"],
            rules=rules,
            max_documents=value["max_documents"],
            max_fields=value["max_fields"],
            max_slots=value["max_slots"],
            _token=_COMPARE_REGISTRY_TOKEN,
        )
        if value["config_sha256"] != registry.config_sha256:
            raise ValueError("compare_registry_hash_mismatch")
        return registry


def default_compare_field_registry() -> CompareFieldRegistry:
    rules = (
        CompareFieldRule(
            "compare.field.budget.v1",
            "budget",
            ("예산", "사업비", "사업 예산", "사업예산", "사업 금액", "사업금액", "용역비", "용역 비용", "용역비용", "금액"),
            200,
        ),
        CompareFieldRule(
            "compare.field.duration.v1",
            "duration",
            ("사업 기간", "사업기간", "수행 기간", "수행기간", "계약 기간", "계약기간", "과업 기간", "과업기간", "구축 기간", "구축기간", "기간"),
            190,
        ),
        CompareFieldRule(
            "compare.field.maintenance.v1",
            "maintenance",
            ("유지보수", "유지 보수", "유지관리", "유지 관리", "하자보수", "하자 보수", "무상보수", "무상 보수", "무상 유지보수", "무상 유지 보수"),
            180,
        ),
        CompareFieldRule(
            "compare.field.deadline.v1",
            "deadline",
            ("입찰 마감", "입찰마감", "제출 기한", "제출기한", "마감 일시", "마감일시"),
            170,
        ),
        CompareFieldRule(
            "compare.field.eligibility.v1",
            "eligibility",
            ("참가 자격", "참가자격", "입찰 자격", "입찰자격", "신청 자격", "신청자격"),
            160,
        ),
        CompareFieldRule(
            "compare.field.joint-contract.v1",
            "joint_contract",
            ("공동 수급", "공동수급", "공동 계약", "공동계약"),
            150,
        ),
        CompareFieldRule(
            "compare.field.subcontract.v1",
            "subcontract",
            ("하도급", "재하도급"),
            140,
        ),
        CompareFieldRule(
            "compare.field.proposal-submission.v1",
            "proposal_submission",
            ("제안서 제출 방식", "제안서 제출방법", "제안서 제출 방법", "제안서 제출"),
            130,
        ),
        CompareFieldRule(
            "compare.field.target-scope.v1",
            "target_scope",
            ("대응 대상", "지원 대상", "적용 대상", "대상 범위"),
            120,
        ),
        CompareFieldRule(
            "compare.field.core-function.v1",
            "core_function",
            ("핵심 기능", "주요 기능", "시스템 기능"),
            110,
        ),
        CompareFieldRule(
            "compare.field.user-problem.v1",
            "user_problem",
            ("사용자 문제", "해결 문제", "추진 배경"),
            100,
        ),
        CompareFieldRule(
            "compare.field.deliverables.v1",
            "deliverables",
            ("산출물", "납품물", "제출 산출물"),
            90,
        ),
        CompareFieldRule(
            "compare.field.vat-terms.v1",
            "vat_terms",
            ("부가세", "부가 가치세", "부가가치세", "VAT"),
            80,
        ),
        CompareFieldRule(
            "compare.field.evaluation.v1",
            "evaluation",
            ("평가 기준", "평가기준", "평가 항목", "평가항목", "배점"),
            70,
        ),
        CompareFieldRule(
            "compare.field.scope.v1",
            "scope",
            ("과업 범위", "과업범위", "사업 범위", "사업범위", "업무 범위", "업무범위"),
            60,
        ),
    )
    return CompareFieldRegistry._create(
        registry_version="compare-fields-v2",
        rules=rules,
        max_documents=8,
        max_fields=8,
        max_slots=32,
        _token=_COMPARE_REGISTRY_TOKEN,
    )


@dataclass(frozen=True, slots=True)
class CompareBindingTrace:
    request_fingerprint: str
    routing_config_sha256: str
    compare_config_sha256: str
    catalog_sha256: str
    catalog_source_kind: str
    catalog_source_sha256: str
    execution_kind: str
    planning_trace_sha256: str
    planning_result_sha256: str
    base_plan_sha256: str
    effective_plan_sha256: str
    evidence_bundle_sha256: str
    status: str
    reason: str
    scope_source: str
    resolved_doc_ids: tuple[str, ...]
    selected_fields: tuple[str, ...]
    matched_field_rule_ids: tuple[str, ...]
    required_slot_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "request_fingerprint",
            "routing_config_sha256",
            "compare_config_sha256",
            "catalog_sha256",
            "catalog_source_sha256",
            "planning_trace_sha256",
            "planning_result_sha256",
            "base_plan_sha256",
            "effective_plan_sha256",
            "evidence_bundle_sha256",
        ):
            _hash(getattr(self, name), f"invalid_{name}")
        if self.catalog_source_kind not in {
            "production_metadata",
            "synthetic_fixture",
        }:
            raise ValueError("invalid_compare_catalog_source_kind")
        if self.execution_kind not in {"production", "synthetic"}:
            raise ValueError("invalid_compare_execution_kind")
        if (self.catalog_source_kind == "synthetic_fixture") != (
            self.execution_kind == "synthetic"
        ):
            raise ValueError("compare_execution_kind_mismatch")
        if self.status not in {"ready", "unresolved"}:
            raise ValueError("invalid_compare_binding_status")
        if self.reason not in _COMPARE_REASONS:
            raise ValueError("invalid_compare_binding_reason")
        if (self.status == "ready") != (self.reason == "ready"):
            raise ValueError("compare_binding_status_reason_mismatch")
        if self.scope_source not in {
            "user_explicit",
            "named_business_entities",
            "unresolved",
        }:
            raise ValueError("invalid_compare_scope_source")
        for name in (
            "resolved_doc_ids",
            "selected_fields",
            "matched_field_rule_ids",
            "required_slot_keys",
        ):
            maximum = 512 if name == "required_slot_keys" else 256
            object.__setattr__(
                self, name, _texts(getattr(self, name), name, maximum=maximum)
            )
        if len(self.selected_fields) != len(self.matched_field_rule_ids):
            raise ValueError("compare_field_rule_trace_mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "request_fingerprint": self.request_fingerprint,
            "routing_config_sha256": self.routing_config_sha256,
            "compare_config_sha256": self.compare_config_sha256,
            "catalog_sha256": self.catalog_sha256,
            "catalog_source_kind": self.catalog_source_kind,
            "catalog_source_sha256": self.catalog_source_sha256,
            "execution_kind": self.execution_kind,
            "planning_trace_sha256": self.planning_trace_sha256,
            "planning_result_sha256": self.planning_result_sha256,
            "base_plan_sha256": self.base_plan_sha256,
            "effective_plan_sha256": self.effective_plan_sha256,
            "evidence_bundle_sha256": self.evidence_bundle_sha256,
            "status": self.status,
            "reason": self.reason,
            "scope_source": self.scope_source,
            "resolved_doc_ids": list(self.resolved_doc_ids),
            "selected_fields": list(self.selected_fields),
            "matched_field_rule_ids": list(self.matched_field_rule_ids),
            "required_slot_keys": list(self.required_slot_keys),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> CompareBindingTrace:
        value = _closed(raw, _BINDING_TRACE_FIELDS, "compare_binding_trace_fields")
        if value["schema_version"] != "1.0":
            raise ValueError("unsupported_compare_binding_trace_version")
        sequence_fields = (
            "resolved_doc_ids",
            "selected_fields",
            "matched_field_rule_ids",
            "required_slot_keys",
        )
        for name in sequence_fields:
            _json_list(value[name], f"compare_binding_{name}_array")
        return cls(**{name: value[name] for name in _BINDING_TRACE_FIELDS - {"schema_version"}})


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class BoundCompare:
    planning: PlanningResult
    plan: QueryPlan
    trace: CompareBindingTrace
    binding_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("bound_compare_factory_required")

    @classmethod
    def _create(
        cls,
        *,
        planning: PlanningResult,
        plan: QueryPlan,
        trace: CompareBindingTrace,
        _token: object,
    ) -> BoundCompare:
        if _token is not _BOUND_COMPARE_TOKEN:
            raise ValueError("bound_compare_factory_required")
        result = object.__new__(cls)
        object.__setattr__(result, "planning", planning)
        object.__setattr__(result, "plan", plan)
        object.__setattr__(result, "trace", trace)
        object.__setattr__(
            result,
            "binding_sha256",
            _canonical_sha256(_bound_compare_payload(planning, plan, trace)),
        )
        result._validate_payload()
        _register_bound_compare_authority(result)
        result._validate()
        return result

    def _validate(self) -> None:
        _require_bound_compare_authority(self)
        self._validate_payload()

    def _validate_payload(self) -> None:
        if type(self.planning) is not PlanningResult:
            raise TypeError("compare_planning_result_required")
        if type(self.plan) is not QueryPlan:
            raise TypeError("compare_effective_plan_required")
        if type(self.trace) is not CompareBindingTrace:
            raise TypeError("compare_binding_trace_required")
        if self.planning.plan.query_type != "compare" or self.plan.query_type != "compare":
            raise ValueError("compare_plan_required")
        if self.planning.plan.required_slots:
            raise ValueError("base_compare_slots_must_be_empty")
        if self.plan.allow_global_fallback:
            raise ValueError("compare_global_fallback_forbidden")
        if self.planning.trace.request_fingerprint != self.trace.request_fingerprint:
            raise ValueError("compare_request_trace_mismatch")
        if self.plan.config_sha256 != self.trace.routing_config_sha256:
            raise ValueError("compare_routing_config_mismatch")
        if self.planning.trace.catalog_sha256 != self.trace.catalog_sha256:
            raise ValueError("compare_catalog_trace_mismatch")
        planning_trace_sha256, planning_result_sha256 = _validated_planning_hashes(
            self.planning
        )
        if self.planning.trace.catalog_source_kind != self.trace.catalog_source_kind:
            raise ValueError("compare_catalog_source_kind_mismatch")
        if self.planning.trace.catalog_source_sha256 != self.trace.catalog_source_sha256:
            raise ValueError("compare_catalog_source_hash_mismatch")
        if self.planning.trace.execution_kind != self.trace.execution_kind:
            raise ValueError("compare_execution_kind_mismatch")
        if planning_trace_sha256 != self.trace.planning_trace_sha256:
            raise ValueError("compare_planning_trace_hash_mismatch")
        if planning_result_sha256 != self.trace.planning_result_sha256:
            raise ValueError("compare_planning_result_hash_mismatch")
        if _canonical_sha256(self.planning.plan.to_dict()) != self.trace.base_plan_sha256:
            raise ValueError("compare_base_plan_hash_mismatch")
        if _canonical_sha256(self.plan.to_dict()) != self.trace.effective_plan_sha256:
            raise ValueError("compare_effective_plan_hash_mismatch")
        if self.plan.resolved_doc_ids != self.trace.resolved_doc_ids:
            raise ValueError("compare_scope_trace_mismatch")
        comparison_constraints = tuple(
            constraint
            for constraint in self.plan.constraints
            if constraint.kind == "comparison_field"
        )
        expected_constraints = tuple(
            PlanConstraint("comparison_field", field, "rule_registry")
            for field in self.trace.selected_fields
        )
        if comparison_constraints != expected_constraints:
            raise ValueError("compare_field_constraints_mismatch")
        if self.trace.compare_config_sha256 != default_compare_field_registry().config_sha256:
            raise ValueError("unapproved_compare_field_registry")
        expected_slots = tuple(
            f"{doc_id}.{field}"
            for doc_id in self.trace.resolved_doc_ids
            for field in self.trace.selected_fields
        )
        if self.trace.status == "ready":
            if len(self.trace.resolved_doc_ids) < 2 or not self.trace.selected_fields:
                raise ValueError("ready_compare_requires_targets_and_fields")
            if tuple(slot.key for slot in self.plan.required_slots) != expected_slots:
                raise ValueError("compare_slot_matrix_mismatch")
            if self.trace.required_slot_keys != expected_slots:
                raise ValueError("compare_slot_trace_mismatch")
            if self.trace.scope_source == "unresolved":
                raise ValueError("ready_compare_scope_unresolved")
        else:
            if self.plan.required_slots or self.trace.required_slot_keys:
                raise ValueError("unresolved_compare_has_slots")
            if self.trace.reason not in self.plan.unresolved_constraints:
                raise ValueError("compare_unresolved_reason_missing")
        if self.binding_sha256 != _canonical_sha256(
            _bound_compare_payload(self.planning, self.plan, self.trace)
        ):
            raise ValueError("compare_binding_hash_mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "planning": self.planning.to_dict(),
            "effective_plan": self.plan.to_dict(),
            "trace": self.trace.to_dict(),
            "binding_sha256": self.binding_sha256,
        }

    @classmethod
    def from_dict(
        cls,
        raw: Mapping[str, Any],
        *,
        request: RuntimeRequest,
        planner: DeterministicPlanner,
        store: EvidenceStore,
        compare_registry: CompareFieldRegistry,
    ) -> BoundCompare:
        value = _closed(raw, _BOUND_COMPARE_FIELDS, "bound_compare_fields")
        if value["schema_version"] != "1.0":
            raise ValueError("unsupported_bound_compare_version")
        # Hashes alone are not execution proof.  Re-run the planner/binder and
        # accept persisted authority only when it exactly matches this runtime.
        result = prepare_compare_slots(
            request=request,
            planning=planner.plan(request),
            store=store,
            planner=planner,
            compare_registry=compare_registry,
        )
        if _canonical_sha256(result.to_dict()) != _canonical_sha256(dict(value)):
            raise ValueError("bound_compare_payload_mismatch")
        return result


def _resolved_compare_scope(
    request: RuntimeRequest,
    planning: PlanningResult,
) -> tuple[str, tuple[str, ...], str | None]:
    plan = planning.plan
    if plan.scope_state == "empty":
        return "unresolved", plan.resolved_doc_ids, "compare_scope_empty"
    if plan.scope_state != "restricted":
        return "unresolved", plan.resolved_doc_ids, "compare_scope_unresolved"
    if request.document_scope["mode"] == "explicit":
        if len(plan.resolved_doc_ids) < 2:
            return (
                "user_explicit",
                plan.resolved_doc_ids,
                "compare_requires_multiple_documents",
            )
        business_entities = tuple(
            entity for entity in plan.entities if entity.kind == "business"
        )
        if any(len(entity.resolved_doc_ids) != 1 for entity in business_entities):
            return "user_explicit", plan.resolved_doc_ids, "compare_targets_ambiguous"
        named_doc_ids = {
            entity.resolved_doc_ids[0] for entity in business_entities
        }
        if not named_doc_ids.issubset(plan.resolved_doc_ids):
            # Explicit scope may constrain retrieval, but it must not silently
            # truncate an additional business target named in the same compare.
            return "user_explicit", plan.resolved_doc_ids, "compare_targets_unresolved"
        return "user_explicit", plan.resolved_doc_ids, None

    business_entities = tuple(
        entity for entity in plan.entities if entity.kind == "business"
    )
    if not business_entities and plan.entities:
        return "unresolved", plan.resolved_doc_ids, "compare_targets_ambiguous"
    if any(len(entity.resolved_doc_ids) != 1 for entity in business_entities):
        return "unresolved", plan.resolved_doc_ids, "compare_targets_ambiguous"
    directly_named = tuple(
        dict.fromkeys(entity.resolved_doc_ids[0] for entity in business_entities)
    )
    if len(directly_named) < 2:
        return "unresolved", plan.resolved_doc_ids, "compare_requires_multiple_documents"
    if set(directly_named) != set(plan.resolved_doc_ids):
        return "unresolved", plan.resolved_doc_ids, "compare_targets_ambiguous"
    return "named_business_entities", plan.resolved_doc_ids, None


def _field_selection_query(
    planning: PlanningResult,
    planner: DeterministicPlanner,
) -> str:
    """Remove resolved entity names before selecting requested compare axes."""

    query = _normalize(planning.plan.normalized_query)
    used_spans: list[tuple[int, int]] = []
    seen_identities: set[tuple[str, str, tuple[str, ...]]] = set()
    for entity in planning.plan.entities:
        identity = (entity.value, entity.kind, entity.resolved_doc_ids)
        if identity in seen_identities:
            continue
        seen_identities.add(identity)
        aliases = {entity.value}
        aliases.update(
            catalog_entity.alias
            for catalog_entity in planner.catalog.entities
            if (
                catalog_entity.canonical_value,
                catalog_entity.kind,
                catalog_entity.doc_ids,
            )
            == identity
        )
        candidates = tuple(
            (start, end, -len(_normalize(alias)))
            for alias in aliases
            for start, end in _signal_match_spans(query, alias)
            if not any(
                start < used_end and used_start < end
                for used_start, used_end in used_spans
            )
        )
        if candidates:
            start, end, _negative_length = min(candidates)
            used_spans.append((start, end))
    return _mask_query_spans(query, tuple(sorted(used_spans)))


def prepare_compare_slots(
    *,
    request: RuntimeRequest,
    planning: PlanningResult,
    store: EvidenceStore,
    planner: DeterministicPlanner,
    compare_registry: CompareFieldRegistry,
) -> BoundCompare:
    """Replay a runtime plan, then seal its complete compare slot matrix."""

    if type(request) is not RuntimeRequest:
        raise TypeError("runtime_request_required")
    if type(planning) is not PlanningResult:
        raise TypeError("planning_result_required")
    if type(store) is not EvidenceStore:
        raise TypeError("evidence_store_required")
    if type(planner) is not DeterministicPlanner:
        raise TypeError("deterministic_planner_required")
    if type(compare_registry) is not CompareFieldRegistry:
        raise TypeError("compare_field_registry_required")
    compare_registry._validate()
    if compare_registry.config_sha256 != default_compare_field_registry().config_sha256:
        raise ValueError("unapproved_compare_field_registry")
    replayed = planner.plan(request)
    replayed_trace_sha256, replayed_result_sha256 = _validated_planning_hashes(
        replayed
    )
    planning_trace_sha256, planning_result_sha256 = _validated_planning_hashes(
        planning
    )
    if (
        replayed_trace_sha256 != planning_trace_sha256
        or replayed_result_sha256 != planning_result_sha256
    ):
        raise ValueError("compare_planning_replay_mismatch")
    planner.registry.validate_plan(planning.plan)
    if planning.plan.query_type != "compare":
        raise ValueError("compare_plan_required")
    if planning.plan.required_slots:
        raise ValueError("base_compare_slots_must_be_empty")

    field_query = _field_selection_query(planning, planner)
    selected_rules, consumed_field_spans = _select_requested_fields(
        field_query, compare_registry
    )
    fields = tuple(rule.field for rule in selected_rules)
    scope_source, doc_ids, reason = _resolved_compare_scope(request, planning)
    intent_reason = _unresolved_field_intent_reason(
        field_query,
        selected_rules,
        consumed_field_spans,
        scope_source=scope_source,
    )
    if reason is None and intent_reason is not None:
        reason = intent_reason
    predicate_statuses = tuple(
        predicate.status for predicate in planning.plan.metadata_predicates
    )
    if any(status != "supported" for status in predicate_statuses):
        reason = "compare_metadata_unresolved"
    elif predicate_statuses:
        # The planner records predicate syntax support, not the filtered result
        # set.  EH2.4 has no catalog-filter execution receipt to prove that the
        # comparison scope actually reflects these predicates.
        reason = "compare_metadata_scope_receipt_required"
    if reason is None and len(doc_ids) > compare_registry.max_documents:
        reason = "compare_target_limit_exceeded"
    if reason is None and any(doc_id not in store.doc_ids for doc_id in doc_ids):
        reason = "compare_document_not_in_store"
    if reason is None and not fields:
        reason = "compare_fields_unresolved"
    if reason is None and len(fields) > compare_registry.max_fields:
        reason = "compare_field_limit_exceeded"
    if reason is None and len(doc_ids) * len(fields) > compare_registry.max_slots:
        reason = "compare_slot_limit_exceeded"
    status = "ready" if reason is None else "unresolved"
    final_reason = "ready" if reason is None else reason
    slots = (
        tuple(RequiredSlot(doc_id, field) for doc_id in doc_ids for field in fields)
        if status == "ready"
        else ()
    )
    comparison_constraints = tuple(
        PlanConstraint("comparison_field", field, "rule_registry")
        for field in fields
        if not any(
            constraint.kind == "comparison_field" and constraint.value == field
            for constraint in planning.plan.constraints
        )
    )
    unresolved = planning.plan.unresolved_constraints
    if status == "unresolved" and final_reason not in unresolved:
        unresolved += (final_reason,)
    effective = planner.registry.make_plan(
        query_type="compare",
        normalized_query=planning.plan.normalized_query,
        entities=planning.plan.entities,
        resolved_doc_ids=planning.plan.resolved_doc_ids,
        inherited_doc_ids=planning.plan.inherited_doc_ids,
        scope_state=planning.plan.scope_state,
        scope_origin=planning.plan.scope_origin,
        constraints=planning.plan.constraints + comparison_constraints,
        metadata_predicates=planning.plan.metadata_predicates,
        required_slots=slots,
        allow_global_fallback=False,
        unresolved_constraints=unresolved,
    )
    base_plan_sha256 = _canonical_sha256(planning.plan.to_dict())
    effective_plan_sha256 = _canonical_sha256(effective.to_dict())
    trace = CompareBindingTrace(
        request_fingerprint=request.fingerprint,
        routing_config_sha256=planner.registry.config_sha256,
        compare_config_sha256=compare_registry.config_sha256,
        catalog_sha256=planner.catalog.catalog_sha256,
        catalog_source_kind=planning.trace.catalog_source_kind,
        catalog_source_sha256=planning.trace.catalog_source_sha256,
        execution_kind=planning.trace.execution_kind,
        planning_trace_sha256=planning_trace_sha256,
        planning_result_sha256=planning_result_sha256,
        base_plan_sha256=base_plan_sha256,
        effective_plan_sha256=effective_plan_sha256,
        evidence_bundle_sha256=store.bundle_sha256,
        status=status,
        reason=final_reason,
        scope_source=scope_source,
        resolved_doc_ids=effective.resolved_doc_ids,
        selected_fields=fields,
        matched_field_rule_ids=tuple(rule.rule_id for rule in selected_rules),
        required_slot_keys=tuple(slot.key for slot in slots),
    )
    return BoundCompare._create(
        planning=planning,
        plan=effective,
        trace=trace,
        _token=_BOUND_COMPARE_TOKEN,
    )
