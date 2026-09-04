"""EH2.6.c3.4 closed ActionEffectReceipt schema acceptance tests.

These tests exercise only the structural value contract.  A structurally valid
receipt is not execution authority; EH2.6.d2/c4 owns the future permitted mint.
"""

from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError
from hashlib import sha256
import inspect
import json
import pickle
import unittest
from unittest.mock import patch

import midprojectrag.orchestration as orchestration
import midprojectrag.orchestration.action_effects as action_effects_module
from midprojectrag.orchestration import (
    ActionEffectReceipt,
    validate_action_effect_receipt,
)


def _canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _hash(label: str) -> str:
    return sha256(label.encode("utf-8")).hexdigest()


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "stage": "action_effect",
        "execution_sha256": _hash("execution"),
        "step_index": 1,
        "controller_decision_sha256": _hash("decision"),
        "action_kind": "retrieve_dense",
        "action_sha256": _hash("action"),
        "obligation_key": "budget",
        "target_evidence_id": None,
        "before_state_sha256": _hash("before-state"),
        "source_kind": "fact",
        "source_receipt_kind": "lane_search",
        "source_receipt_sha256": _hash("source-receipt"),
        "outcome": "applied",
        "ordered_evidence_ids": ("ev-a",),
        "parent_context_receipt_sha256s": (),
        "bridge_context_receipt_sha256s": (),
        "absence_confirmation_sha256": None,
        "call_performed": True,
    }
    payload.update(overrides)
    return payload


def _make(**overrides: object) -> ActionEffectReceipt:
    return ActionEffectReceipt._create(
        payload=_payload(**overrides),
        _token=action_effects_module._ACTION_EFFECT_RECEIPT_TOKEN,
    )


_ACTIONS = (
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
_SOURCES = (
    "lane_search",
    "fusion",
    "parent_context",
    "bridge_context",
    "rerank",
    "semantic_verification",
    "absence_confirmation",
    "controller_decision",
)
_OUTCOMES = (
    "applied",
    "empty",
    "unsupported",
    "unavailable",
    "deadline_discarded",
    "provider_error",
    "contract_error",
    "terminal",
)


def _valid_rows() -> frozenset[tuple[str, str, str, bool]]:
    rows: set[tuple[str, str, str, bool]] = set()
    for action in ("retrieve_dense", "retrieve_lexical"):
        rows.update(
            {
                (action, "lane_search", "applied", True),
                (action, "lane_search", "empty", True),
                (action, "lane_search", "provider_error", True),
                (action, "lane_search", "contract_error", False),
                (action, "lane_search", "contract_error", True),
                (action, "controller_decision", "unavailable", False),
                (action, "controller_decision", "deadline_discarded", False),
                (action, "controller_decision", "deadline_discarded", True),
            }
        )
    rows.update(
        {
            ("fuse", "fusion", "applied", True),
            ("fuse", "fusion", "empty", True),
            ("fuse", "controller_decision", "deadline_discarded", False),
            ("fuse", "controller_decision", "contract_error", False),
            ("fuse", "controller_decision", "contract_error", True),
            ("expand_parent", "parent_context", "applied", True),
            ("expand_parent", "controller_decision", "deadline_discarded", False),
            ("expand_parent", "controller_decision", "contract_error", False),
            ("expand_parent", "controller_decision", "contract_error", True),
            ("rerank", "rerank", "applied", True),
            ("rerank", "rerank", "unavailable", False),
            ("rerank", "rerank", "provider_error", True),
            ("rerank", "rerank", "contract_error", True),
            ("rerank", "controller_decision", "deadline_discarded", False),
            ("rerank", "controller_decision", "deadline_discarded", True),
            ("rerank", "controller_decision", "contract_error", False),
            ("rerank", "controller_decision", "contract_error", True),
            ("verify_slot", "semantic_verification", "applied", True),
            ("verify_slot", "semantic_verification", "unsupported", True),
            ("verify_slot", "semantic_verification", "unavailable", False),
            ("verify_slot", "absence_confirmation", "empty", False),
            ("verify_slot", "controller_decision", "deadline_discarded", False),
            ("verify_slot", "controller_decision", "deadline_discarded", True),
            ("verify_slot", "controller_decision", "provider_error", True),
            ("verify_slot", "controller_decision", "contract_error", False),
            ("verify_slot", "controller_decision", "contract_error", True),
            ("stop", "controller_decision", "terminal", False),
            ("abstain", "controller_decision", "terminal", False),
        }
    )
    for action in ("bridge_table", "bridge_figure"):
        rows.update(
            {
                (action, "bridge_context", "applied", True),
                (action, "bridge_context", "empty", True),
                (action, "controller_decision", "unavailable", False),
                (action, "controller_decision", "deadline_discarded", False),
                (action, "controller_decision", "contract_error", False),
                (action, "controller_decision", "contract_error", True),
            }
        )
    return frozenset(rows)


_VALID_ROWS = _valid_rows()


def _row_overrides(
    action: str,
    source: str,
    outcome: str,
    call_performed: bool,
) -> dict[str, object]:
    source_sha256 = _hash("decision") if source == "controller_decision" else _hash(
        f"source:{source}"
    )
    ordered_evidence_ids: tuple[str, ...] = ()
    if outcome == "applied" and action != "expand_parent":
        ordered_evidence_ids = ("ev-a",)
    if action == "rerank" and outcome == "unavailable":
        ordered_evidence_ids = ("ev-a",)
    return {
        "action_kind": action,
        "obligation_key": None if action in {"stop", "abstain"} else "budget",
        "target_evidence_id": (
            "ev-a" if action in {"expand_parent", "bridge_table", "bridge_figure"} else None
        ),
        "source_receipt_kind": source,
        "source_receipt_sha256": source_sha256,
        "outcome": outcome,
        "ordered_evidence_ids": ordered_evidence_ids,
        "parent_context_receipt_sha256s": (
            (source_sha256,) if source == "parent_context" else ()
        ),
        "bridge_context_receipt_sha256s": (
            (source_sha256,) if source == "bridge_context" else ()
        ),
        "absence_confirmation_sha256": (
            source_sha256
            if source == "absence_confirmation"
            else _hash("absence")
            if source == "semantic_verification" and outcome == "unsupported"
            else None
        ),
        "call_performed": call_performed,
    }


class ActionEffectReceiptClosedContractTests(unittest.TestCase):
    def test_package_surface_is_dto_and_structural_validator_only(self):
        self.assertIs(ActionEffectReceipt, action_effects_module.ActionEffectReceipt)
        self.assertIs(
            validate_action_effect_receipt,
            action_effects_module.validate_action_effect_receipt,
        )
        parameters = inspect.signature(validate_action_effect_receipt).parameters
        self.assertEqual(tuple(parameters), ("receipt",))
        self.assertIs(
            parameters["receipt"].kind,
            inspect.Parameter.KEYWORD_ONLY,
        )
        for name in (
            "create_action_effect_receipt",
            "issue_action_effect_receipt",
            "mint_action_effect_receipt",
            "execute_action_effect",
            "action_effect_receipt_token",
            "_ACTION_EFFECT_RECEIPT_TOKEN",
        ):
            self.assertFalse(hasattr(orchestration, name), name)
        self.assertFalse(hasattr(ActionEffectReceipt, "from_dict"))

    def test_private_schema_factory_is_token_gated_and_receipt_is_nonserializable(self):
        with self.assertRaisesRegex(TypeError, "factory_required"):
            ActionEffectReceipt()
        with self.assertRaisesRegex(ValueError, "factory_required"):
            ActionEffectReceipt._create(payload=_payload(), _token=object())

        receipt = _make()
        self.assertFalse(hasattr(receipt, "__dict__"))
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            receipt.outcome = "empty"  # type: ignore[misc]
        for operation in (copy.copy, copy.deepcopy, pickle.dumps):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(TypeError, "not_serializable"):
                    operation(receipt)

    def test_exact_payload_and_canonical_hash_are_stable(self):
        receipt = _make()

        self.assertIsNone(validate_action_effect_receipt(receipt=receipt))
        first = receipt.to_dict()
        second = receipt.to_dict()
        self.assertEqual(first, second)
        self.assertEqual(
            set(first),
            {
                "schema_version",
                *ActionEffectReceipt.__slots__,
            }
            - {"__weakref__"},
        )
        effect_sha256 = first.pop("effect_sha256")
        self.assertEqual(effect_sha256, _canonical_sha256(first))
        self.assertEqual(receipt.effect_sha256, effect_sha256)

    def test_action_source_outcome_and_call_matrix_accepts_representative_rows(self):
        rows = (
            ({}, "lane applied"),
            (
                {
                    "outcome": "empty",
                    "ordered_evidence_ids": (),
                },
                "lane empty",
            ),
            (
                {
                    "action_kind": "fuse",
                    "source_receipt_kind": "fusion",
                },
                "fusion",
            ),
            (
                {
                    "action_kind": "expand_parent",
                    "target_evidence_id": "ev-a",
                    "source_receipt_kind": "parent_context",
                    "source_receipt_sha256": _hash("parent"),
                    "ordered_evidence_ids": (),
                    "parent_context_receipt_sha256s": (_hash("parent"),),
                },
                "parent",
            ),
            (
                {
                    "action_kind": "bridge_table",
                    "target_evidence_id": "ev-a",
                    "source_receipt_kind": "bridge_context",
                    "source_receipt_sha256": _hash("bridge"),
                    "bridge_context_receipt_sha256s": (_hash("bridge"),),
                },
                "bridge",
            ),
            (
                {
                    "action_kind": "rerank",
                    "source_receipt_kind": "rerank",
                },
                "rerank",
            ),
            (
                {
                    "action_kind": "verify_slot",
                    "source_receipt_kind": "semantic_verification",
                    "outcome": "unsupported",
                    "ordered_evidence_ids": (),
                    "absence_confirmation_sha256": _hash("absence"),
                },
                "semantic unsupported",
            ),
            (
                {
                    "action_kind": "verify_slot",
                    "source_receipt_kind": "absence_confirmation",
                    "source_receipt_sha256": _hash("absence"),
                    "outcome": "empty",
                    "ordered_evidence_ids": (),
                    "absence_confirmation_sha256": _hash("absence"),
                    "call_performed": False,
                },
                "absence",
            ),
            (
                {
                    "action_kind": "stop",
                    "obligation_key": None,
                    "source_receipt_kind": "controller_decision",
                    "source_receipt_sha256": _hash("decision"),
                    "outcome": "terminal",
                    "ordered_evidence_ids": (),
                    "call_performed": False,
                },
                "terminal",
            ),
        )
        for overrides, label in rows:
            with self.subTest(label=label):
                validate_action_effect_receipt(receipt=_make(**overrides))

    def test_every_closed_matrix_row_and_only_those_rows_are_accepted(self):
        for source_kind in ("fact", "compare", "follow_up"):
            for action in _ACTIONS:
                for source in _SOURCES:
                    for outcome in _OUTCOMES:
                        for call_performed in (False, True):
                            row = (action, source, outcome, call_performed)
                            allowed = row in _VALID_ROWS and not (
                                source_kind == "follow_up"
                                and action
                                in {"retrieve_dense", "retrieve_lexical", "fuse"}
                            )
                            label = "valid" if allowed else "invalid"
                            with self.subTest(
                                source_kind=source_kind,
                                **{label: row},
                            ):
                                if allowed:
                                    validate_action_effect_receipt(
                                        receipt=_make(
                                            source_kind=source_kind,
                                            **_row_overrides(*row),
                                        )
                                    )
                                else:
                                    with self.assertRaises((TypeError, ValueError)):
                                        _make(
                                            source_kind=source_kind,
                                            **_row_overrides(*row),
                                        )

    def test_malformed_closed_schema_and_cross_matrix_values_fail(self):
        mutations = (
            ("stage", "forged"),
            ("execution_sha256", "x" * 64),
            ("step_index", True),
            ("step_index", 0),
            ("action_kind", "search_everything"),
            ("obligation_key", None),
            ("target_evidence_id", "unexpected"),
            ("source_kind", "gold"),
            ("source_receipt_kind", "raw_dict"),
            ("outcome", "success"),
            ("ordered_evidence_ids", ["ev-a"]),
            ("ordered_evidence_ids", ("ev-a", "ev-a")),
            ("parent_context_receipt_sha256s", ("bad",)),
            ("absence_confirmation_sha256", _hash("unrelated-absence")),
            ("call_performed", 1),
        )
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                receipt = _make()
                object.__setattr__(receipt, field, value)
                with self.assertRaises((TypeError, ValueError)):
                    validate_action_effect_receipt(receipt=receipt)

        invalid_rows = (
            {"action_kind": "fuse", "source_receipt_kind": "lane_search"},
            {"action_kind": "stop", "outcome": "applied"},
            {"source_receipt_kind": "absence_confirmation"},
            {"outcome": "unavailable", "call_performed": True},
            {"outcome": "provider_error", "call_performed": False},
        )
        for overrides in invalid_rows:
            with self.subTest(overrides=overrides):
                with self.assertRaises((TypeError, ValueError)):
                    _make(**overrides)

    def test_error_terminal_absence_and_context_projections_do_not_promote(self):
        error = _make(
            source_receipt_kind="controller_decision",
            source_receipt_sha256=_hash("decision"),
            outcome="deadline_discarded",
            ordered_evidence_ids=(),
            call_performed=False,
        )
        self.assertIsNone(validate_action_effect_receipt(receipt=error))
        for forbidden in (
            "after_state_sha256",
            "transition_sha256",
            "answer",
            "citation_evidence_ids",
            "query",
            "text",
            "value",
            "gold",
            "qrels",
            "expected_answer",
            "provider_error_detail",
            "path",
            "api_key",
        ):
            self.assertNotIn(forbidden, error.to_dict())

        with self.assertRaises((TypeError, ValueError)):
            validate_action_effect_receipt(receipt=error.to_dict())  # type: ignore[arg-type]
        with self.assertRaises((TypeError, ValueError)):
            validate_action_effect_receipt(  # type: ignore[arg-type]
                receipt=json.dumps(error.to_dict())
            )

    def test_source_kind_context_absence_and_hash_bindings_are_fail_closed(self):
        follow_up_rows = (
            ("expand_parent", "parent_context", "applied", True),
            ("bridge_figure", "bridge_context", "applied", True),
            ("rerank", "rerank", "applied", True),
            ("verify_slot", "semantic_verification", "applied", True),
            ("stop", "controller_decision", "terminal", False),
        )
        for row in follow_up_rows:
            with self.subTest(follow_up=row):
                validate_action_effect_receipt(
                    receipt=_make(source_kind="follow_up", **_row_overrides(*row))
                )
        for row in (
            ("retrieve_dense", "lane_search", "applied", True),
            ("fuse", "fusion", "applied", True),
            (
                "retrieve_dense",
                "controller_decision",
                "deadline_discarded",
                False,
            ),
            ("retrieve_lexical", "controller_decision", "unavailable", False),
            ("fuse", "controller_decision", "contract_error", False),
        ):
            with self.subTest(forbidden_follow_up=row):
                with self.assertRaises((TypeError, ValueError)):
                    _make(source_kind="follow_up", **_row_overrides(*row))

        invalid = (
            {
                **_row_overrides("expand_parent", "parent_context", "applied", True),
                "parent_context_receipt_sha256s": (),
            },
            {
                **_row_overrides("bridge_table", "bridge_context", "applied", True),
                "bridge_context_receipt_sha256s": (),
            },
            {
                **_row_overrides(
                    "verify_slot", "semantic_verification", "unsupported", True
                ),
                "absence_confirmation_sha256": None,
            },
            {
                **_row_overrides(
                    "verify_slot", "absence_confirmation", "empty", False
                ),
                "absence_confirmation_sha256": _hash("other-absence"),
            },
            {
                **_row_overrides(
                    "verify_slot", "absence_confirmation", "empty", False
                ),
                "parent_context_receipt_sha256s": (_hash("parent"),),
            },
            {
                **_row_overrides(
                    "verify_slot", "semantic_verification", "unsupported", True
                ),
                "absence_confirmation_sha256": _hash(
                    "source:semantic_verification"
                ),
            },
            {
                **_row_overrides(
                    "rerank", "controller_decision", "deadline_discarded", False
                ),
                "parent_context_receipt_sha256s": (_hash("parent"),),
            },
            {
                **_row_overrides(
                    "retrieve_dense", "controller_decision", "unavailable", False
                ),
                "source_receipt_sha256": _hash("not-the-decision"),
            },
            {
                **_row_overrides("rerank", "rerank", "unavailable", False),
                "ordered_evidence_ids": (),
            },
        )
        for overrides in invalid:
            with self.subTest(invalid_binding=overrides):
                with self.assertRaises((TypeError, ValueError)):
                    _make(**overrides)

        upper_hash = _make()
        object.__setattr__(upper_hash, "source_receipt_sha256", _hash("source").upper())
        with self.assertRaises((TypeError, ValueError)):
            validate_action_effect_receipt(receipt=upper_hash)

        class Stage(str):
            pass

        subclass_stage = _make()
        object.__setattr__(subclass_stage, "stage", Stage("action_effect"))
        with self.assertRaises((TypeError, ValueError)):
            validate_action_effect_receipt(receipt=subclass_stage)

    def test_serialization_revalidates_mutated_receipt(self):
        receipt = _make()
        object.__setattr__(receipt, "outcome", "empty")
        with self.assertRaises((TypeError, ValueError)):
            receipt.to_dict()

    def test_subclass_and_unrelated_trace_cannot_promote_to_effect_receipt(self):
        class ForgedActionEffectReceipt(ActionEffectReceipt):
            pass

        original = _make()
        forged = object.__new__(ForgedActionEffectReceipt)
        for field in ActionEffectReceipt.__slots__:
            if field != "__weakref__":
                object.__setattr__(forged, field, getattr(original, field))
        with self.assertRaisesRegex(TypeError, "invalid_action_effect_receipt"):
            validate_action_effect_receipt(receipt=forged)

        trace = object.__new__(orchestration.ActionDecisionTrace)
        with self.assertRaisesRegex(TypeError, "invalid_action_effect_receipt"):
            validate_action_effect_receipt(receipt=trace)  # type: ignore[arg-type]

    def test_factory_rejects_open_payload_and_validator_has_no_provider_surface(self):
        opened = _payload(extra="forbidden")
        with self.assertRaises((TypeError, ValueError)):
            ActionEffectReceipt._create(
                payload=opened,
                _token=action_effects_module._ACTION_EFFECT_RECEIPT_TOKEN,
            )
        source = inspect.getsource(validate_action_effect_receipt)
        for forbidden in (
            "retriever",
            "verifier",
            "reranker",
            "clock(",
            "requests.",
            "openai",
            "langfuse",
        ):
            self.assertNotIn(forbidden, source.lower())

        receipt = _make()
        with (
            patch("builtins.open", side_effect=AssertionError("unexpected file call")),
            patch("socket.socket", side_effect=AssertionError("unexpected socket call")),
            patch(
                "subprocess.run",
                side_effect=AssertionError("unexpected subprocess call"),
            ),
            patch(
                "urllib.request.urlopen",
                side_effect=AssertionError("unexpected network call"),
            ),
        ):
            self.assertIsNone(validate_action_effect_receipt(receipt=receipt))


if __name__ == "__main__":
    unittest.main()
