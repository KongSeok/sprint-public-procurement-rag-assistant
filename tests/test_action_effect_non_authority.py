"""EH2.6.c3.5 negative authority and representation acceptance tests."""

from __future__ import annotations

import copy
import inspect
import pickle
import unittest
from unittest.mock import patch

import midprojectrag.orchestration as orchestration
import midprojectrag.orchestration.action_effects as action_effects_module
from midprojectrag.orchestration import (
    ActionEffectReceipt,
    validate_action_effect_receipt,
)

from tests.test_action_effect_receipt_contract import _make


_FORBIDDEN_PUBLIC_NAMES = (
    "create_action_effect_receipt",
    "issue_action_effect_receipt",
    "mint_action_effect_receipt",
    "execute_action_effect",
    "reduce_action_effect",
    "authorize_action_effect",
    "validate_live_action_effect",
)
_EFFECT_MODULE_SYMBOLS = frozenset(
    {
        "_ACTION_EFFECT_RECEIPT_TOKEN",
        "_ACTION_EFFECT_ACTION_KINDS",
        "_ACTION_EFFECT_SOURCE_KINDS",
        "_ACTION_EFFECT_SOURCE_RECEIPT_KINDS",
        "_ACTION_EFFECT_OUTCOMES",
        "_ACTION_EFFECT_OBLIGATION_ACTIONS",
        "_ACTION_EFFECT_EVIDENCE_ACTIONS",
        "_ACTION_EFFECT_TERMINAL_ACTIONS",
        "_ACTION_EFFECT_PROVIDER_ACTIONS",
        "_ACTION_EFFECT_CORE_ROWS",
        "_ACTION_EFFECT_PAYLOAD_FIELDS",
        "_effect_require_hash",
        "_effect_string_tuple",
        "_valid_action_effect_row",
        "_validate_action_effect_receipt_payload",
        "ActionEffectReceipt",
        "validate_action_effect_receipt",
    }
)
_FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "query",
        "text",
        "value",
        "provider_error_detail",
        "gold",
        "qrels",
        "expected_answer",
        "path",
        "api_key",
        "after_state_sha256",
        "transition_sha256",
        "answer",
        "citation_evidence_ids",
        "ready",
        "authorized",
        "authority",
    }
)


class ActionEffectNonAuthorityTests(unittest.TestCase):
    def test_repr_does_not_emit_structural_projection_or_lineage(self):
        receipt = _make()

        rendered = repr(receipt)
        self.assertEqual(rendered, "ActionEffectReceipt(<redacted>)")

        values = tuple(
            item
            for field in ActionEffectReceipt.__slots__
            if field != "__weakref__"
            for item in (
                getattr(receipt, field)
                if type(getattr(receipt, field)) is tuple
                else (getattr(receipt, field),)
            )
            if type(item) is str and item
        )
        for forbidden in tuple(ActionEffectReceipt.__slots__) + values:
            self.assertNotIn(forbidden, rendered)

    def test_package_has_no_effect_issuer_consumer_or_authority_registry(self):
        self.assertEqual(
            {name for name in orchestration.__all__ if "effect" in name.casefold()},
            {"ActionEffectReceipt", "validate_action_effect_receipt"},
        )
        self.assertEqual(
            action_effects_module.__all__,
            (
                "ActionEffectReceipt",
                "SemanticValueSupport",
                "validate_action_effect_receipt",
            ),
        )
        self.assertEqual(
            {
                name
                for name in vars(action_effects_module)
                if "effect" in name.casefold()
            },
            _EFFECT_MODULE_SYMBOLS,
        )
        for name in _FORBIDDEN_PUBLIC_NAMES:
            self.assertFalse(hasattr(orchestration, name), name)
            self.assertNotIn(name, orchestration.__all__)

        consumers: list[str] = []
        for name in orchestration.__all__:
            value = getattr(orchestration, name)
            if value is ActionEffectReceipt or not callable(value):
                continue
            try:
                parameters = inspect.signature(value).parameters.values()
            except (TypeError, ValueError):
                continue
            for parameter in parameters:
                annotation = parameter.annotation
                annotation_name = getattr(annotation, "__name__", str(annotation))
                if "ActionEffectReceipt" in annotation_name:
                    consumers.append(name)
        self.assertEqual(consumers, ["validate_action_effect_receipt"])

    def test_structural_validator_has_no_live_dependency_input_surface(self):
        receipt = _make()
        dependencies = {
            "source_receipt": object(),
            "store": object(),
            "config": object(),
            "runtime": object(),
            "controller_decision": object(),
        }
        for name, dependency in dependencies.items():
            with self.subTest(name=name):
                with self.assertRaises(TypeError):
                    validate_action_effect_receipt(
                        receipt=receipt,
                        **{name: dependency},  # type: ignore[arg-type]
                    )

    def test_equal_hash_replay_and_exact_clone_are_non_authorizing_values(self):
        first = _make()
        second = _make()
        self.assertIsNot(first, second)
        self.assertEqual(first.effect_sha256, second.effect_sha256)

        clone = object.__new__(ActionEffectReceipt)
        for field in ActionEffectReceipt.__slots__:
            if field != "__weakref__":
                object.__setattr__(clone, field, getattr(first, field))
        self.assertIsNone(validate_action_effect_receipt(receipt=clone))
        self.assertEqual(first.to_dict(), clone.to_dict())

        self.assertFalse(hasattr(first, "authorized"))
        self.assertFalse(hasattr(first, "transition_sha256"))
        self.assertFalse(hasattr(first, "citation_evidence_ids"))

    def test_constructor_copy_pickle_and_from_dict_cannot_remint(self):
        receipt = _make()

        with self.assertRaisesRegex(TypeError, "factory_required"):
            ActionEffectReceipt()
        self.assertFalse(hasattr(ActionEffectReceipt, "from_dict"))
        for operation in (copy.copy, copy.deepcopy, pickle.dumps):
            with self.subTest(operation=operation.__name__):
                with self.assertRaisesRegex(TypeError, "not_serializable"):
                    operation(receipt)

    def test_subclass_clone_is_rejected_and_cannot_gain_authority(self):
        class ForgedActionEffectReceipt(ActionEffectReceipt):
            pass

        source = _make()
        forged = object.__new__(ForgedActionEffectReceipt)
        for field in ActionEffectReceipt.__slots__:
            if field != "__weakref__":
                object.__setattr__(forged, field, getattr(source, field))

        with self.assertRaisesRegex(TypeError, "invalid_action_effect_receipt"):
            validate_action_effect_receipt(receipt=forged)
        for name in ("authorized", "transition_sha256", "citation_evidence_ids"):
            self.assertFalse(hasattr(forged, name))

    def test_public_serialization_is_allowlisted_and_provider_free(self):
        receipt = _make()
        with (
            patch("builtins.open", side_effect=AssertionError("unexpected file call")),
            patch("socket.socket", side_effect=AssertionError("unexpected socket call")),
            patch("subprocess.run", side_effect=AssertionError("unexpected process call")),
            patch(
                "urllib.request.urlopen",
                side_effect=AssertionError("unexpected network call"),
            ),
        ):
            payload = receipt.to_dict()
        self.assertFalse(_FORBIDDEN_PAYLOAD_KEYS.intersection(payload))
        self.assertEqual(payload["effect_sha256"], receipt.effect_sha256)


if __name__ == "__main__":
    unittest.main()
