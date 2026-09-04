"""Authority-bound typed actions and deterministic EH2.5 decisions.

This module deliberately does not execute actions or mutate ``HarnessState``.  It
only projects the actions permitted by one exact, factory-issued state/store pair
and records the deterministic first choice in a replayable hash chain.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
import json
import math
import re
from typing import Any
from weakref import ReferenceType, ref

from midprojectrag.evidence import EvidenceStore

from .harness_state import HarnessState, validate_harness_state


_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ACTION_KINDS = (
    "retrieve_dense",
    "retrieve_lexical",
    "fuse",
    "expand_parent",
    "rerank",
    "bridge_table",
    "bridge_figure",
    "verify_slot",
    "stop",
    "abstain",
)
_ACTION_KIND_SET = frozenset(_ACTION_KINDS)
_OBLIGATION_ONLY_KINDS = frozenset(
    {"retrieve_dense", "retrieve_lexical", "fuse", "rerank", "verify_slot"}
)
_EVIDENCE_TARGET_KINDS = frozenset(
    {"expand_parent", "bridge_table", "bridge_figure"}
)
_TERMINAL_KINDS = frozenset({"stop", "abstain"})
_POLICY_ID = "bounded-deterministic-e1-v1"
_POLICY_PAYLOAD = {
    "schema_version": "1.0",
    "policy_id": _POLICY_ID,
    "closed_action_kinds": list(_ACTION_KINDS),
    "obligation_order": "sealed_state_order",
    "within_obligation_order": [
        "retrieve_dense",
        "retrieve_lexical",
        "expand_parent",
        "bridge_table",
        "bridge_figure",
        "rerank",
        "verify_slot",
    ],
    "target_order": "evidence_id_ascending",
    "fuse_eligible": False,
    "source_stage_actions": {
        "compare": {
            "unsearched": ["retrieve_dense", "retrieve_lexical"],
            "candidate": [
                "expand_parent",
                "bridge_table",
                "bridge_figure",
                "rerank",
                "verify_slot",
            ],
            "provisional_missing": ["retrieve_dense", "retrieve_lexical"],
            "verified": [],
            "confirmed_missing": [],
            "contradicted": ["abstain"],
        },
        "follow_up": {
            "unsearched": [],
            "candidate": [
                "expand_parent",
                "bridge_table",
                "bridge_figure",
                "rerank",
                "verify_slot",
            ],
            "provisional_missing": [],
            "verified": [],
            "confirmed_missing": [],
            "contradicted": ["abstain"],
        },
    },
    "terminal_gate_precedence": ["stop", "abstain", "open"],
    "global_contradiction_gate": "abstain",
    "open_fallback": "abstain",
}
_ACTION_TOKEN = object()
_TRACE_TOKEN = object()
_ACTION_AUTHORITIES: dict[int, tuple[Any, ...]] = {}
_TRACE_AUTHORITIES: dict[int, tuple[Any, ...]] = {}


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


_POLICY_SHA256 = _canonical_sha256(_POLICY_PAYLOAD)


def _require_hash(value: Any, code: str) -> str:
    if type(value) is not str or not _HEX64.fullmatch(value):
        raise ValueError(code)
    return value


def _strict_json_value(value: Any, code: str) -> None:
    if value is None or type(value) in {str, bool, int}:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(code)
        return
    if type(value) is list:
        for item in value:
            _strict_json_value(item, code)
        return
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise TypeError(code)
        for item in value.values():
            _strict_json_value(item, code)
        return
    raise TypeError(code)


def _drop_authority(
    authorities: dict[int, tuple[Any, ...]],
    identity: int,
    dead: ReferenceType[Any],
) -> None:
    current = authorities.get(identity)
    if current is not None and current[0] is dead:
        authorities.pop(identity, None)


def _register_authority(
    authorities: dict[int, tuple[Any, ...]],
    value: Any,
    payload: Mapping[str, Any],
    *context: Any,
) -> None:
    identity = id(value)
    weak = ref(
        value,
        lambda dead, identity=identity, authorities=authorities: _drop_authority(
            authorities, identity, dead
        ),
    )
    authorities[identity] = (weak, _canonical_sha256(payload), *context)


def _authority_record(
    authorities: dict[int, tuple[Any, ...]],
    value: Any,
    *,
    code: str,
) -> tuple[Any, ...]:
    current = authorities.get(id(value))
    if current is None or current[0]() is not value:
        raise ValueError(code)
    return current


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class HarnessAction:
    """One closed action identifier with no caller-controlled query or scope."""

    kind: str
    obligation_key: str | None
    evidence_id: str | None
    action_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("harness_action_factory_required")

    @classmethod
    def _create(
        cls,
        *,
        kind: str,
        obligation_key: str | None,
        evidence_id: str | None,
        state: HarnessState,
        store: EvidenceStore,
        _token: object,
    ) -> HarnessAction:
        if _token is not _ACTION_TOKEN:
            raise ValueError("harness_action_factory_required")
        result = object.__new__(cls)
        object.__setattr__(result, "kind", kind)
        object.__setattr__(result, "obligation_key", obligation_key)
        object.__setattr__(result, "evidence_id", evidence_id)
        object.__setattr__(
            result, "action_sha256", _canonical_sha256(result._payload())
        )
        result._validate_payload()
        _register_authority(
            _ACTION_AUTHORITIES,
            result,
            result.to_dict(),
            state,
            store,
        )
        result._validate(state=state, store=store)
        return result

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "kind": self.kind,
            "obligation_key": self.obligation_key,
            "evidence_id": self.evidence_id,
        }

    def _validate_payload(self) -> None:
        if type(self.kind) is not str or self.kind not in _ACTION_KIND_SET:
            raise ValueError("invalid_harness_action_kind")
        if self.kind in _TERMINAL_KINDS:
            if self.obligation_key is not None or self.evidence_id is not None:
                raise ValueError("terminal_action_must_be_untargeted")
        elif self.kind in _OBLIGATION_ONLY_KINDS:
            if type(self.obligation_key) is not str or not self.obligation_key:
                raise ValueError("action_obligation_required")
            if self.evidence_id is not None:
                raise ValueError("obligation_action_forbids_evidence_target")
        elif self.kind in _EVIDENCE_TARGET_KINDS:
            if type(self.obligation_key) is not str or not self.obligation_key:
                raise ValueError("action_obligation_required")
            if type(self.evidence_id) is not str or not self.evidence_id:
                raise ValueError("action_evidence_target_required")
        else:  # Defensive even if the closed set changes without updating shapes.
            raise ValueError("unsupported_harness_action_shape")
        _require_hash(self.action_sha256, "invalid_action_sha256")
        if self.action_sha256 != _canonical_sha256(self._payload()):
            raise ValueError("harness_action_hash_mismatch")

    def _validate(self, *, state: HarnessState, store: EvidenceStore) -> None:
        current = _authority_record(
            _ACTION_AUTHORITIES,
            self,
            code="harness_action_runtime_authority_required",
        )
        if current[2] is not state or current[3] is not store:
            raise ValueError("harness_action_context_identity_mismatch")
        self._validate_payload()
        if current[1] != _canonical_sha256(self.to_dict()):
            raise ValueError("harness_action_runtime_authority_drift")

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "action_sha256": self.action_sha256}


def _action(
    kind: str,
    *,
    state: HarnessState,
    store: EvidenceStore,
    obligation_key: str | None = None,
    evidence_id: str | None = None,
) -> HarnessAction:
    return HarnessAction._create(
        kind=kind,
        obligation_key=obligation_key,
        evidence_id=evidence_id,
        state=state,
        store=store,
        _token=_ACTION_TOKEN,
    )


def _candidate_action_specs(
    *,
    obligation_key: str,
    candidate_evidence_ids: tuple[str, ...],
    store: EvidenceStore,
) -> tuple[tuple[str, str, str | None], ...]:
    candidates = tuple(sorted(candidate_evidence_ids))
    specs: list[tuple[str, str, str | None]] = []
    for evidence_id in candidates:
        evidence = store.get(evidence_id)
        try:
            store.parent(evidence.parent_id)
        except KeyError:
            pass
        else:
            specs.append(("expand_parent", obligation_key, evidence_id))
    for evidence_id in candidates:
        if store.bridge(evidence_id, kinds=("table_row_group",)):
            specs.append(("bridge_table", obligation_key, evidence_id))
    for evidence_id in candidates:
        if store.bridge(evidence_id, kinds=("figure_object",)):
            specs.append(("bridge_figure", obligation_key, evidence_id))
    specs.extend(
        (
            ("rerank", obligation_key, None),
            ("verify_slot", obligation_key, None),
        )
    )
    return tuple(specs)


def _allowed_action_specs(
    state: HarnessState,
    *,
    store: EvidenceStore,
) -> tuple[tuple[str, str | None, str | None], ...]:
    validate_harness_state(state=state, store=store)
    progress = state.progress
    if progress.normal_stop_allowed:
        return (("stop", None, None),)
    if progress.abstain_required or progress.contradicted_obligation_keys:
        return (("abstain", None, None),)

    specs: list[tuple[str, str | None, str | None]] = []
    for entry in state.belief.evidence_map:
        stage = entry.observation_stage
        if state.belief.source_kind == "compare" and stage in {
            "unsearched",
            "provisional_missing",
        }:
            specs.extend(
                (
                    ("retrieve_dense", entry.obligation_key, None),
                    ("retrieve_lexical", entry.obligation_key, None),
                )
            )
        elif stage == "candidate" and state.belief.source_kind in {
            "compare",
            "follow_up",
        }:
            specs.extend(
                _candidate_action_specs(
                    obligation_key=entry.obligation_key,
                    candidate_evidence_ids=entry.candidate_evidence_ids,
                    store=store,
                )
            )
    # An open EH2.5 state always has exactly one safe terminal escape hatch.
    specs.append(("abstain", None, None))
    return tuple(specs)


def allowed_harness_actions(
    state: HarnessState,
    *,
    store: EvidenceStore,
) -> tuple[HarnessAction, ...]:
    """Return the exact deterministic action order for a sealed state/store pair."""

    if type(state) is not HarnessState:
        raise TypeError("harness_state_required")
    if type(store) is not EvidenceStore:
        raise TypeError("evidence_store_required")
    return tuple(
        _action(
            kind,
            state=state,
            store=store,
            obligation_key=obligation_key,
            evidence_id=evidence_id,
        )
        for kind, obligation_key, evidence_id in _allowed_action_specs(
            state, store=store
        )
    )


def _execution_identity(state: HarnessState) -> str:
    belief = state.belief
    return _canonical_sha256(
        {
            "schema_version": "1.0",
            "policy_id": _POLICY_ID,
            "policy_sha256": _POLICY_SHA256,
            "source_kind": belief.source_kind,
            "request_fingerprint": belief.request_fingerprint,
            "binding_sha256": belief.binding_sha256,
            "effective_plan_sha256": belief.effective_plan_sha256,
            "config_sha256": belief.config_sha256,
            "evidence_bundle_sha256": belief.evidence_bundle_sha256,
        }
    )


def _allowed_actions_sha256(actions: tuple[HarnessAction, ...]) -> str:
    return _canonical_sha256(
        {
            "schema_version": "1.0",
            "allowed_actions": [action.to_dict() for action in actions],
        }
    )


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class ActionDecisionTrace:
    """Factory-issued proof of one deterministic E1 action decision."""

    policy_id: str
    policy_sha256: str
    execution_identity_sha256: str
    decision_ordinal: int
    previous_decision_sha256: str | None
    state_sha256: str
    allowed_actions: tuple[HarnessAction, ...]
    allowed_actions_sha256: str
    selected_action: HarnessAction
    reason_code: str
    decision_sha256: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("action_decision_trace_factory_required")

    @classmethod
    def _create(
        cls,
        *,
        state: HarnessState,
        store: EvidenceStore,
        allowed_actions: tuple[HarnessAction, ...],
        selected_action: HarnessAction,
        reason_code: str,
        previous: ActionDecisionTrace | None,
        _token: object,
    ) -> ActionDecisionTrace:
        if _token is not _TRACE_TOKEN:
            raise ValueError("action_decision_trace_factory_required")
        result = object.__new__(cls)
        values = {
            "policy_id": _POLICY_ID,
            "policy_sha256": _POLICY_SHA256,
            "execution_identity_sha256": _execution_identity(state),
            "decision_ordinal": (
                1 if previous is None else previous.decision_ordinal + 1
            ),
            "previous_decision_sha256": (
                None if previous is None else previous.decision_sha256
            ),
            "state_sha256": state.state_sha256,
            "allowed_actions": allowed_actions,
            "allowed_actions_sha256": _allowed_actions_sha256(allowed_actions),
            "selected_action": selected_action,
            "reason_code": reason_code,
        }
        for name, value in values.items():
            object.__setattr__(result, name, value)
        object.__setattr__(
            result, "decision_sha256", _canonical_sha256(result._payload())
        )
        result._validate_payload()
        _register_authority(
            _TRACE_AUTHORITIES,
            result,
            result.to_dict(),
            state,
            store,
            allowed_actions,
            tuple(allowed_actions),
            selected_action,
            previous,
        )
        result._validate(state=state, store=store, previous=previous)
        return result

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "policy_id": self.policy_id,
            "policy_sha256": self.policy_sha256,
            "execution_identity_sha256": self.execution_identity_sha256,
            "decision_ordinal": self.decision_ordinal,
            "previous_decision_sha256": self.previous_decision_sha256,
            "state_sha256": self.state_sha256,
            "allowed_actions": [action.to_dict() for action in self.allowed_actions],
            "allowed_actions_sha256": self.allowed_actions_sha256,
            "selected_action": self.selected_action.to_dict(),
            "reason_code": self.reason_code,
        }

    def _validate_payload(self) -> None:
        if self.policy_id != _POLICY_ID:
            raise ValueError("action_decision_policy_id_mismatch")
        if self.policy_sha256 != _POLICY_SHA256:
            raise ValueError("action_decision_policy_hash_mismatch")
        for name in (
            "policy_sha256",
            "execution_identity_sha256",
            "state_sha256",
            "allowed_actions_sha256",
            "decision_sha256",
        ):
            _require_hash(getattr(self, name), f"invalid_{name}")
        if type(self.decision_ordinal) is not int or self.decision_ordinal < 1:
            raise ValueError("invalid_action_decision_ordinal")
        if self.previous_decision_sha256 is not None:
            _require_hash(
                self.previous_decision_sha256,
                "invalid_previous_decision_sha256",
            )
        if type(self.allowed_actions) is not tuple or not self.allowed_actions:
            raise ValueError("action_decision_allowed_actions_required")
        if any(type(action) is not HarnessAction for action in self.allowed_actions):
            raise TypeError("invalid_action_decision_allowed_action")
        if type(self.selected_action) is not HarnessAction:
            raise TypeError("invalid_action_decision_selected_action")
        if self.selected_action is not self.allowed_actions[0]:
            raise ValueError("action_decision_must_select_first_allowed")
        if self.reason_code not in {
            "normal_stop_allowed",
            "abstain_required",
            "first_eligible_nonterminal",
            "no_eligible_nonterminal_safe_abstain",
        }:
            raise ValueError("invalid_action_decision_reason")
        if self.allowed_actions_sha256 != _allowed_actions_sha256(
            self.allowed_actions
        ):
            raise ValueError("allowed_actions_hash_mismatch")
        if self.decision_sha256 != _canonical_sha256(self._payload()):
            raise ValueError("action_decision_hash_mismatch")

    def _validate(
        self,
        *,
        state: HarnessState,
        store: EvidenceStore,
        previous: ActionDecisionTrace | None,
    ) -> None:
        current = _authority_record(
            _TRACE_AUTHORITIES,
            self,
            code="action_decision_runtime_authority_required",
        )
        issued_actions = current[5]
        if (
            current[2] is not state
            or current[3] is not store
            or current[4] is not self.allowed_actions
            or len(issued_actions) != len(self.allowed_actions)
            or any(
                issued is not actual
                for issued, actual in zip(issued_actions, self.allowed_actions)
            )
            or current[6] is not self.selected_action
            or current[7] is not previous
        ):
            raise ValueError("action_decision_nested_identity_drift")
        validate_harness_state(state=state, store=store)
        if self.state_sha256 != state.state_sha256:
            raise ValueError("action_decision_state_hash_mismatch")
        if self.execution_identity_sha256 != _execution_identity(state):
            raise ValueError("action_decision_execution_identity_mismatch")
        for action in self.allowed_actions:
            action._validate(state=state, store=store)
        expected_specs = _allowed_action_specs(state, store=store)
        actual_specs = tuple(
            (action.kind, action.obligation_key, action.evidence_id)
            for action in self.allowed_actions
        )
        if actual_specs != expected_specs:
            raise ValueError("action_decision_allowed_actions_mismatch")
        if previous is None:
            if self.decision_ordinal != 1 or self.previous_decision_sha256 is not None:
                raise ValueError("action_decision_initial_chain_mismatch")
        else:
            if type(previous) is not ActionDecisionTrace:
                raise TypeError("previous_action_decision_required")
            previous_record = _authority_record(
                _TRACE_AUTHORITIES,
                previous,
                code="action_decision_runtime_authority_required",
            )
            previous._validate(
                state=state,
                store=store,
                previous=previous_record[7],
            )
            if previous.execution_identity_sha256 != self.execution_identity_sha256:
                raise ValueError("action_decision_execution_chain_mismatch")
            if previous.selected_action.kind in _TERMINAL_KINDS:
                raise ValueError("terminal_action_decision_cannot_continue")
            if self.decision_ordinal != previous.decision_ordinal + 1:
                raise ValueError("action_decision_ordinal_chain_mismatch")
            if self.previous_decision_sha256 != previous.decision_sha256:
                raise ValueError("action_decision_previous_hash_mismatch")
        self._validate_payload()
        if current[1] != _canonical_sha256(self.to_dict()):
            raise ValueError("action_decision_runtime_authority_drift")

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "decision_sha256": self.decision_sha256}


def _decision_reason(state: HarnessState, selected: HarnessAction) -> str:
    if state.progress.normal_stop_allowed:
        return "normal_stop_allowed"
    if (
        state.progress.abstain_required
        or state.progress.contradicted_obligation_keys
    ):
        return "abstain_required"
    if selected.kind == "abstain":
        return "no_eligible_nonterminal_safe_abstain"
    return "first_eligible_nonterminal"


def decide_harness_action(
    state: HarnessState,
    *,
    store: EvidenceStore,
    previous: ActionDecisionTrace | None = None,
) -> ActionDecisionTrace:
    """Choose the first allowed action and seal it into a deterministic chain."""

    if type(state) is not HarnessState:
        raise TypeError("harness_state_required")
    if type(store) is not EvidenceStore:
        raise TypeError("evidence_store_required")
    validate_harness_state(state=state, store=store)
    if previous is not None:
        if type(previous) is not ActionDecisionTrace:
            raise TypeError("previous_action_decision_required")
        previous_record = _authority_record(
            _TRACE_AUTHORITIES,
            previous,
            code="action_decision_runtime_authority_required",
        )
        previous._validate(
            state=state,
            store=store,
            previous=previous_record[7],
        )
        if previous.selected_action.kind in _TERMINAL_KINDS:
            raise ValueError("terminal_action_decision_cannot_continue")
    actions = allowed_harness_actions(state, store=store)
    selected = actions[0]
    return ActionDecisionTrace._create(
        state=state,
        store=store,
        allowed_actions=actions,
        selected_action=selected,
        reason_code=_decision_reason(state, selected),
        previous=previous,
        _token=_TRACE_TOKEN,
    )


def replay_action_decision(
    raw: Mapping[str, Any],
    *,
    state: HarnessState,
    store: EvidenceStore,
    previous: ActionDecisionTrace | None = None,
) -> ActionDecisionTrace:
    """Rebuild a decision from authority and compare strict canonical JSON."""

    if type(raw) is not dict:
        raise TypeError("action_decision_replay_mapping_required")
    _strict_json_value(raw, "action_decision_replay_json_required")
    expected = decide_harness_action(state, store=store, previous=previous)
    if _canonical_json(raw) != _canonical_json(expected.to_dict()):
        raise ValueError("action_decision_replay_payload_mismatch")
    return expected
