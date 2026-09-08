"""Exact predecessor-edge validation for retained Controller transitions."""

from __future__ import annotations

from contextlib import contextmanager
import sys
import unittest

import midprojectrag.orchestration.execution_contracts as contracts
from midprojectrag.orchestration import validate_harness_execution
import tests.test_controller_initial_transition as initial_fixtures
import tests.test_controller_lexical_transition as lexical_fixtures
from tests.test_retrieval_obligations import _calls, _clone_slots


def _closure_value(function, name):
    cells = dict(zip(function.__code__.co_freevars, function.__closure__ or ()))
    return cells[name].cell_contents


def _successor_reader():
    return _closure_value(
        contracts._require_controller_initial_transition,
        "require_successor_record",
    )


@contextmanager
def _replace_execution_predecessor(execution, replacement):
    reader = contracts._require_harness_execution_authority
    authorities = _closure_value(reader, "authorities")
    authority_shadow = _closure_value(reader, "authority_shadow")
    authority_lock = _closure_value(reader, "authority_lock")
    identity = id(execution)
    with authority_lock:
        original = authorities[identity]
        changed = original[:11] + (replacement,) + original[12:]
        authorities[identity] = changed
        authority_shadow[identity] = changed
    try:
        yield
    finally:
        with authority_lock:
            authorities[identity] = original
            authority_shadow[identity] = original


@contextmanager
def _replace_retained_projection(execution, replacement):
    reader = _successor_reader()
    records = _closure_value(reader, "records")
    records_shadow = _closure_value(
        _closure_value(reader, "prune_unlocked"),
        "records_shadow",
    )
    transition_lock = _closure_value(reader, "transition_lock")
    bridge_fields = _closure_value(reader, "bridge_fields")
    projection_index = bridge_fields.index("projection")
    with transition_lock:
        matches = [
            (key, record)
            for key, record in records.items()
            if record[8] is not None and record[8]() is execution
        ]
        if len(matches) != 1:
            raise AssertionError("unique retained successor record required")
        key, original = matches[0]
        bridge = original[0]
        original_projection = bridge.projection
        changed_values = (
            original[6][:projection_index]
            + (replacement,)
            + original[6][projection_index + 1 :]
        )
        changed = original[:6] + (changed_values,) + original[7:]
        object.__setattr__(bridge, "projection", replacement)
        records[key] = changed
        records_shadow[key] = changed
    try:
        yield
    finally:
        with transition_lock:
            object.__setattr__(bridge, "projection", original_projection)
            records[key] = original
            records_shadow[key] = original


class ControllerPredecessorValidationEdgeTests(unittest.TestCase):
    def setUp(self):
        self.initial = initial_fixtures.ControllerInitialTransitionTests(
            methodName="runTest"
        )
        self.initial.setUp()
        self.addCleanup(self.initial.doCleanups)

    def _revision_one(self):
        case = self.initial._case()
        return case, self.initial._advance(case)

    def _revision_two(self):
        fixture = lexical_fixtures.ControllerLexicalTransitionTests(
            methodName="runTest"
        )
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        case = fixture._case()
        return fixture, case, fixture._execute(case)

    def test_valid_revision_one_and_two_return_original_identities(self):
        case, one = self._revision_one()
        first = self.initial._read(case, one)
        second = self.initial._read(case, one)
        self.assertIs(first[0], second[0])
        self.assertIs(first[1], second[1])
        records = _closure_value(_successor_reader(), "records")
        self.assertIs(first[0], records[case["claim"].step_key][1])
        self.assertIs(
            first[1], contracts._require_harness_execution_authority(one)[8]
        )
        validate_harness_execution(execution=one, **case["env"])

        fixture, lexical_case, two = self._revision_two()
        lexical_first = fixture._read(lexical_case, two)
        lexical_second = fixture._read(lexical_case, two)
        self.assertIs(lexical_first[0], lexical_second[0])
        self.assertIs(lexical_first[1], lexical_second[1])
        self.assertIs(
            lexical_first[1],
            contracts._require_harness_execution_authority(two)[8],
        )
        validate_harness_execution(execution=two, **lexical_case["env"])

    def test_wrong_predecessor_type_clone_and_projection_graph_fail_closed(self):
        case, one = self._revision_one()
        with _replace_execution_predecessor(one, object()):
            with self.assertRaisesRegex(TypeError, "^harness_execution_required$"):
                self.initial._read(case, one)

        with _replace_execution_predecessor(one, _clone_slots(case["before"])):
            with self.assertRaisesRegex(
                ValueError, "^controller_initial_transition_authority_drift$"
            ):
                self.initial._read(case, one)

        other = self.initial._case()
        other_one = self.initial._advance(other)
        self.initial._read(other, other_one)
        with _replace_retained_projection(one, other["projection"]):
            with self.assertRaisesRegex(
                ValueError, "^controller_initial_transition_authority_drift$"
            ):
                self.initial._read(case, one)
        with _replace_retained_projection(one, object()):
            with self.assertRaisesRegex(
                TypeError, "^controller_source_outcome_projection_required$"
            ):
                self.initial._read(case, one)

        self.initial._read(case, one)
        self.assertEqual(_calls(case["dense_log"]), ("dense",))
        self.assertEqual(_calls(other["dense_log"]), ("dense",))

    def test_each_read_observes_later_predecessor_and_source_mutation(self):
        for target in ("predecessor", "source"):
            with self.subTest(target=target):
                case, one = self._revision_one()
                self.initial._read(case, one)
                if target == "predecessor":
                    object.__setattr__(
                        case["before"].ledger,
                        "ledger_sha256",
                        "0" * 64,
                    )
                else:
                    object.__setattr__(
                        case["receipt"],
                        "receipt_sha256",
                        "0" * 64,
                    )
                with self.assertRaises((TypeError, ValueError)):
                    self.initial._read(case, one)
                self.assertEqual(_calls(case["dense_log"]), ("dense",))
                self.assertEqual(_calls(case["lexical_log"]), ())

    def test_persistent_source_drift_at_delegated_handoff_rejects(self):
        case, one = self._revision_one()
        validate_record = _closure_value(_successor_reader(), "validate_record")
        injected = []

        def inject_source_drift(frame, event, _argument):
            if event == "call" and frame.f_code is validate_record.__code__:
                injected.append(True)
                sys.settrace(None)
                object.__setattr__(
                    case["receipt"],
                    "receipt_sha256",
                    "0" * 64,
                )
            return inject_source_drift

        previous_trace = sys.gettrace()
        try:
            sys.settrace(inject_source_drift)
            with self.assertRaises((TypeError, ValueError)):
                self.initial._read(case, one)
        finally:
            sys.settrace(previous_trace)
        self.assertEqual(injected, [True])
        self.assertEqual(_calls(case["dense_log"]), ("dense",))
        self.assertEqual(_calls(case["lexical_log"]), ())


if __name__ == "__main__":
    unittest.main()
