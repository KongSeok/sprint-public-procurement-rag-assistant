"""The selected first fusion seals one exact effect-derived revision three."""

from concurrent.futures import ThreadPoolExecutor
import gc
import inspect
import sys
import threading
from threading import Barrier, Event
import unittest
from weakref import ref

import midprojectrag.orchestration as orchestration
import midprojectrag.orchestration.execution_contracts as contracts
from midprojectrag.orchestration import (
    decide_controller_action,
    execute_retrieval_fusion,
    validate_controller_decision_receipt,
    validate_fusion_receipt,
    validate_harness_execution,
    validate_harness_state,
)
import tests.test_controller_lexical_transition as lexical_fixtures
from tests.test_retrieval_obligations import _calls, _clone_slots


class ControllerFirstFusionTransitionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = lexical_fixtures.ControllerLexicalTransitionTests(
            methodName="runTest"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def _case(self, **options):
        case = self.fixture._case(**options)
        case["second"] = self.fixture._execute(case)
        case["third_decision"] = decide_controller_action(
            execution=case["second"], **case["env"]
        )
        return case

    @staticmethod
    def _execute(case, *, execution=None, decision=None, env=None):
        return contracts._execute_controller_first_fusion_step(
            execution=case["second"] if execution is None else execution,
            decision=(
                case["third_decision"] if decision is None else decision
            ),
            **(case["env"] if env is None else env),
        )

    def _sources(self, case):
        obligation, lexical = self.fixture._lexical_source(case)
        return obligation, case["receipt"], lexical

    @staticmethod
    def _fusion_sources(obligation):
        return tuple(
            receipt
            for authority in tuple(
                dict.values(contracts._ISSUED_FUSION_RECEIPT_AUTHORITIES)
            )
            if object.__getattribute__(authority, "obligation") is obligation
            for receipt in (object.__getattribute__(authority, "weak")(),)
            if receipt is not None
        )

    @staticmethod
    def _calls_snapshot(case):
        return _calls(case["dense_log"]), _calls(case["lexical_log"])

    def _assert_no_fusion(self, case):
        obligation, _dense, _lexical = self._sources(case)
        self.assertEqual(self._fusion_sources(obligation), ())

    def test_fact_compare_all_normal_pairs_seal_exact_revision_three(self):
        checked_private_surface = False
        for compare in (False, True):
            for dense_mode, lexical_mode in (
                ("valid", "valid"),
                ("valid", "empty"),
                ("empty", "valid"),
                ("empty", "empty"),
            ):
                with self.subTest(
                    compare=compare,
                    dense=dense_mode,
                    lexical=lexical_mode,
                ):
                    case = self._case(
                        compare=compare,
                        mode=dense_mode,
                        lexical_mode=lexical_mode,
                    )
                    zero, one, two = (
                        case["before"],
                        case["first"],
                        case["second"],
                    )
                    before_payload = two.to_dict()
                    calls = self._calls_snapshot(case)
                    obligation, dense, lexical = self._sources(case)

                    three = self._execute(case)
                    effect, transition = (
                        contracts._require_controller_first_fusion_transition(
                            execution=three, **case["env"]
                        )
                    )
                    fusion_sources = self._fusion_sources(obligation)
                    self.assertEqual(len(fusion_sources), 1)
                    fusion = fusion_sources[0]

                    expected_outcome = (
                        "empty"
                        if dense_mode == lexical_mode == "empty"
                        else "applied"
                    )
                    self.assertEqual(
                        (fusion.outcome, fusion.call_performed),
                        (expected_outcome, True),
                    )
                    self.assertEqual(
                        set(fusion.dense_only_evidence_ids),
                        set(dense.ordered_evidence_ids)
                        - set(lexical.ordered_evidence_ids),
                    )
                    self.assertEqual(
                        set(fusion.lexical_only_evidence_ids),
                        set(lexical.ordered_evidence_ids)
                        - set(dense.ordered_evidence_ids),
                    )
                    self.assertEqual(
                        set(fusion.both_evidence_ids),
                        set(dense.ordered_evidence_ids)
                        & set(lexical.ordered_evidence_ids),
                    )
                    self.assertEqual(
                        len(fusion.ordered_stable_anchors),
                        len(fusion.ordered_evidence_ids),
                    )
                    validate_fusion_receipt(
                        receipt=fusion,
                        obligation=obligation,
                        dense_receipt=dense,
                        lexical_receipt=lexical,
                        **case["env"],
                    )

                    self.assertEqual((three.step_index, three.ledger.revision), (3, 3))
                    self.assertEqual(three.ledger.nonterminal_action_count, 3)
                    self.assertEqual(
                        three.ledger.previous_ledger_sha256,
                        two.ledger.ledger_sha256,
                    )
                    self.assertEqual(
                        three.ledger.consumed_action_sha256s,
                        two.ledger.consumed_action_sha256s
                        + (case["third_decision"].selected_action.action_sha256,),
                    )
                    self.assertIs(
                        three.ledger.consumed_lane_keys,
                        two.ledger.consumed_lane_keys,
                    )
                    self.assertIs(three.ledger.round_indexes, two.ledger.round_indexes)
                    self.assertIs(
                        three.ledger.unavailable_action_sha256s,
                        two.ledger.unavailable_action_sha256s,
                    )
                    self.assertEqual(
                        three.ledger.no_progress_streaks,
                        (0,) + two.ledger.no_progress_streaks[1:],
                    )
                    self.assertIsNot(three.state, two.state)
                    self.assertIs(three.initial_state, two.initial_state)
                    self.assertEqual(two.to_dict(), before_payload)
                    before_entries = two.state.belief.evidence_map
                    after_entries = three.state.belief.evidence_map
                    self.assertEqual(
                        after_entries[0].observation_stage,
                        "provisional_missing"
                        if expected_outcome == "empty"
                        else "candidate",
                    )
                    self.assertIs(
                        after_entries[0].candidate_evidence_ids,
                        effect.ordered_evidence_ids,
                    )
                    self.assertEqual(after_entries[0].verified_evidence_ids, ())
                    self.assertTrue(
                        all(
                            after is before
                            for before, after in zip(
                                before_entries[1:], after_entries[1:]
                            )
                        )
                    )
                    self.assertEqual(
                        three.state.belief.source_receipt_sha256,
                        effect.effect_sha256,
                    )
                    self.assertIs(
                        three.state.belief.entities,
                        two.state.belief.entities,
                    )
                    self.assertIs(
                        three.state.belief.constraints,
                        two.state.belief.constraints,
                    )
                    self.assertIs(
                        three.state.belief.scope_doc_ids,
                        two.state.belief.scope_doc_ids,
                    )
                    self.assertEqual(
                        three.state.progress.open_obligation_keys,
                        two.state.progress.required_obligation_keys,
                    )
                    self.assertEqual(
                        three.state.progress.provisional_missing_obligation_keys,
                        ()
                        if expected_outcome == "applied"
                        else (after_entries[0].obligation_key,),
                    )
                    self.assertEqual(
                        (
                            three.state.progress.verified_obligation_keys,
                            three.state.progress.confirmed_missing_obligation_keys,
                            three.state.progress.contradicted_obligation_keys,
                            three.state.progress.slot_coverage_ratio,
                            three.state.progress.answerability,
                            three.state.progress.normal_stop_allowed,
                            three.state.progress.abstain_required,
                        ),
                        ((), (), (), 0.0, "in_progress", False, False),
                    )
                    self.assertTrue(
                        all(
                            entry.observation_stage == "unsearched"
                            for entry in before_entries
                        )
                    )
                    validate_harness_state(
                        state=three.state,
                        store=case["env"]["store"],
                    )

                    self.assertEqual(
                        (
                            effect.step_index,
                            effect.action_kind,
                            effect.source_receipt_kind,
                            effect.outcome,
                            effect.call_performed,
                        ),
                        (3, "fuse", "fusion", expected_outcome, True),
                    )
                    self.assertEqual(
                        effect.source_receipt_sha256,
                        fusion.receipt_sha256,
                    )
                    self.assertEqual(
                        effect.ordered_evidence_ids,
                        fusion.ordered_evidence_ids,
                    )
                    self.assertIsNone(effect.absence_confirmation_sha256)
                    self.assertEqual(
                        transition.previous_transition_sha256,
                        two.last_transition_sha256,
                    )
                    self.assertEqual(
                        transition.before_ledger_sha256,
                        two.ledger.ledger_sha256,
                    )
                    self.assertEqual(
                        transition.after_ledger_sha256,
                        three.ledger.ledger_sha256,
                    )
                    self.assertEqual(
                        transition.effect_sha256,
                        effect.effect_sha256,
                    )
                    self.assertEqual(
                        transition.before_state_sha256,
                        two.state.state_sha256,
                    )
                    self.assertEqual(
                        transition.after_state_sha256,
                        three.state.state_sha256,
                    )
                    self.assertNotEqual(
                        transition.before_state_sha256,
                        transition.after_state_sha256,
                    )
                    self.assertNotEqual(
                        transition.before_progress_sha256,
                        transition.after_progress_sha256,
                    )
                    self.assertTrue(transition.operational_progress)

                    authority = contracts._require_harness_execution_authority(
                        three
                    )
                    predecessor_authority = (
                        contracts._require_harness_execution_authority(two)
                    )
                    self.assertIs(authority[11], two)
                    self.assertIs(authority[12], zero)
                    self.assertIs(predecessor_authority[11], one)
                    self.assertIs(predecessor_authority[12], zero)
                    for execution in (zero, one, two, three):
                        validate_harness_execution(
                            execution=execution, **case["env"]
                        )
                    for execution, decision in (
                        (zero, case["decision"]),
                        (one, case["second_decision"]),
                        (two, case["third_decision"]),
                    ):
                        validate_controller_decision_receipt(
                            receipt=decision,
                            execution=execution,
                            **case["env"],
                        )
                    self.assertEqual(self._calls_snapshot(case), calls)

                    epoch_record = dict(
                        zip(
                            contracts._controller_source_attempt_epoch.__code__.co_freevars,
                            contracts._controller_source_attempt_epoch.__closure__,
                        )
                    )["receipts"].cell_contents[id(fusion)]
                    self.assertEqual(epoch_record[2], "fusion")

                    if not checked_private_surface:
                        with self.assertRaises((TypeError, ValueError)):
                            contracts._require_controller_initial_transition(
                                execution=three, **case["env"]
                            )
                        with self.assertRaises((TypeError, ValueError)):
                            contracts._require_controller_lexical_transition(
                                execution=three, **case["env"]
                            )
                        with self.assertRaises((TypeError, ValueError)):
                            contracts._require_controller_first_fusion_transition(
                                execution=two, **case["env"]
                            )
                        fourth_decision = decide_controller_action(
                            execution=three, **case["env"]
                        )
                        self.assertEqual(
                            (
                                fourth_decision.decision_ordinal,
                                fourth_decision.selected_action.kind,
                            ),
                            (4, "expand_parent"),
                        )
                        checked_private_surface = True

    def test_budget_and_error_derived_abstain_permits_dispatch_no_fusion(self):
        cases = (
            ({"max_actions": 2}, "action_budget_exhausted"),
            ({"mode": "provider_error"}, "provider_error"),
            ({"lexical_mode": "provider_error"}, "provider_error"),
            ({"lexical_mode": "post_call_contract"}, "contract_error"),
        )
        for options, reason in cases:
            with self.subTest(options=options):
                case = self._case(**options)
                calls = self._calls_snapshot(case)
                self.assertEqual(case["third_decision"].reason_code, reason)
                self.assertEqual(
                    case["third_decision"].selected_action.kind, "abstain"
                )
                with self.assertRaises((TypeError, ValueError)):
                    self._execute(case)
                self._assert_no_fusion(case)
                self.assertEqual(self._calls_snapshot(case), calls)

    def test_clones_mixed_graphs_and_wrong_snapshots_dispatch_no_fusion(self):
        case = self._case()
        other = self._case(compare=True)
        calls = self._calls_snapshot(case)
        attempts = (
            (_clone_slots(case["second"]), case["third_decision"], case["env"]),
            (case["second"], _clone_slots(case["third_decision"]), case["env"]),
            (case["first"], case["third_decision"], case["env"]),
            (case["second"], case["second_decision"], case["env"]),
            (case["second"], other["third_decision"], case["env"]),
            (other["second"], case["third_decision"], other["env"]),
            (
                case["second"],
                case["third_decision"],
                {**case["env"], "runtime": other["env"]["runtime"]},
            ),
        )
        for execution, decision, env in attempts:
            with self.subTest(step=getattr(execution, "step_index", None)):
                with self.assertRaises((TypeError, ValueError)):
                    self._execute(
                        case,
                        execution=execution,
                        decision=decision,
                        env=env,
                    )
        self._assert_no_fusion(case)
        self.assertEqual(
            contracts._controller_step_status(
                execution=case["second"],
                decision=case["third_decision"],
                **case["env"],
            ),
            "pristine",
        )
        self.assertEqual(self._calls_snapshot(case), calls)
        self._execute(case)

    def test_duplicate_and_concurrent_calls_have_one_winner_and_one_fusion(self):
        case = self._case()
        obligation, _dense, _lexical = self._sources(case)
        calls = self._calls_snapshot(case)
        barrier = Barrier(4)

        def attempt(_index):
            barrier.wait(timeout=10)
            try:
                return self._execute(case)
            except (TypeError, ValueError) as error:
                return error

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = tuple(pool.map(attempt, range(4)))
        issued = tuple(item for item in results if not isinstance(item, Exception))
        rejected = tuple(item for item in results if isinstance(item, Exception))
        self.assertEqual((len(issued), len(rejected)), (1, 3))
        self.assertEqual(len(self._fusion_sources(obligation)), 1)
        contracts._require_controller_first_fusion_transition(
            execution=issued[0], **case["env"]
        )
        with self.assertRaises((TypeError, ValueError)):
            self._execute(case)
        self.assertEqual(self._calls_snapshot(case), calls)

    def test_attempt_started_before_claim_and_completed_after_is_retroactive(self):
        case = self._case()
        obligation, dense, lexical = self._sources(case)
        started = Event()
        release = Event()
        fusion_code = contracts._FUSION_RUNTIME_MODULE.fuse_rrf.__code__

        def pause_fusion(frame, event, _argument):
            if event == "call" and frame.f_code is fusion_code:
                started.set()
                if not release.wait(timeout=10):
                    raise RuntimeError("synthetic-fusion-release-timeout")
            return pause_fusion

        previous_trace = threading.gettrace()
        try:
            threading.settrace(pause_fusion)
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    execute_retrieval_fusion,
                    obligation=obligation,
                    dense_receipt=dense,
                    lexical_receipt=lexical,
                    **case["env"],
                )
                self.assertTrue(started.wait(timeout=10))
                claim = contracts._claim_controller_step(
                    execution=case["second"],
                    decision=case["third_decision"],
                    **case["env"],
                )
                release.set()
                receipt = future.result(timeout=10)
        finally:
            release.set()
            threading.settrace(previous_trace)

        with self.assertRaisesRegex(
            ValueError, "controller_step_retroactive_source_forbidden"
        ):
            contracts._prepare_controller_step_source(
                claim=claim,
                source_receipt=receipt,
                **case["env"],
            )
        self.assertEqual(
            contracts._controller_step_status(
                execution=case["second"],
                decision=case["third_decision"],
                **case["env"],
            ),
            "failed",
        )
        with self.assertRaises((TypeError, ValueError)):
            self._execute(case)
        self.assertEqual(len(self._fusion_sources(obligation)), 1)

    def test_completed_preclaim_fusion_cannot_be_wrapped_by_private_executor(self):
        case = self._case()
        obligation, dense, lexical = self._sources(case)
        receipt = execute_retrieval_fusion(
            obligation=obligation,
            dense_receipt=dense,
            lexical_receipt=lexical,
            **case["env"],
        )
        with self.assertRaisesRegex(
            ValueError, "controller_first_fusion_step_source_required"
        ):
            self._execute(case)
        self.assertIs(self._fusion_sources(obligation)[0], receipt)
        self.assertEqual(
            contracts._controller_step_status(
                execution=case["second"],
                decision=case["third_decision"],
                **case["env"],
            ),
            "pristine",
        )

    def test_wrong_post_claim_fusion_source_tombstones_exact_claim(self):
        case = self._case()
        other = self._case(compare=True)
        claim = contracts._claim_controller_step(
            execution=case["second"],
            decision=case["third_decision"],
            **case["env"],
        )
        obligation, dense, lexical = self._sources(other)
        wrong = execute_retrieval_fusion(
            obligation=obligation,
            dense_receipt=dense,
            lexical_receipt=lexical,
            **other["env"],
        )
        with self.assertRaises((TypeError, ValueError)):
            contracts._prepare_controller_step_source(
                claim=claim,
                source_receipt=wrong,
                **case["env"],
            )
        self.assertEqual(
            contracts._controller_step_status(
                execution=case["second"],
                decision=case["third_decision"],
                **case["env"],
            ),
            "failed",
        )
        self._assert_no_fusion(case)

    def test_failure_after_fusion_before_successor_consumes_both_claims(self):
        case = self._case()
        obligation, dense, lexical = self._sources(case)
        registration_code = contracts._register_harness_execution_successor.__code__
        injected = []
        partial_states = []

        def fail_registration(frame, event, _argument):
            if event == "call" and frame.f_code is registration_code:
                injected.append(True)
                partial_states.append(frame.f_locals["state"])
                sys.settrace(None)
                raise RuntimeError("synthetic-fusion-registration-failure")
            return fail_registration

        previous_trace = sys.gettrace()
        try:
            sys.settrace(fail_registration)
            with self.assertRaisesRegex(
                RuntimeError, "synthetic-fusion-registration-failure"
            ):
                self._execute(case)
        finally:
            sys.settrace(previous_trace)
        self.assertEqual(injected, [True])
        self.assertEqual(len(partial_states), 1)
        with self.assertRaisesRegex(
            ValueError, "harness_state_runtime_authority_required"
        ):
            validate_harness_state(
                state=partial_states[0],
                store=case["env"]["store"],
            )
        self.assertEqual(
            contracts._controller_step_status(
                execution=case["second"],
                decision=case["third_decision"],
                **case["env"],
            ),
            "failed",
        )
        with self.assertRaises((TypeError, ValueError)):
            self._execute(case)
        with self.assertRaisesRegex(ValueError, "fusion.*consumed"):
            execute_retrieval_fusion(
                obligation=obligation,
                dense_receipt=dense,
                lexical_receipt=lexical,
                **case["env"],
            )

    def test_fusion_contract_error_is_sanitized_and_non_retriable(self):
        case = self._case()
        obligation, dense, lexical = self._sources(case)
        fusion_code = contracts._FUSION_RUNTIME_MODULE.fuse_rrf.__code__

        def fail_fusion(frame, event, _argument):
            if event == "call" and frame.f_code is fusion_code:
                sys.settrace(None)
                raise RuntimeError("private-fusion-detail")
            return fail_fusion

        previous_trace = sys.gettrace()
        try:
            sys.settrace(fail_fusion)
            with self.assertRaisesRegex(ValueError, "^fusion_contract_error$"):
                self._execute(case)
        finally:
            sys.settrace(previous_trace)
        self.assertEqual(self._fusion_sources(obligation), ())
        self.assertEqual(
            contracts._controller_step_status(
                execution=case["second"],
                decision=case["third_decision"],
                **case["env"],
            ),
            "failed",
        )
        with self.assertRaises((TypeError, ValueError)):
            self._execute(case)
        with self.assertRaisesRegex(ValueError, "fusion.*consumed"):
            execute_retrieval_fusion(
                obligation=obligation,
                dense_receipt=dense,
                lexical_receipt=lexical,
                **case["env"],
            )

    def test_all_predecessors_decisions_and_three_sources_survive_gc(self):
        case = self._case(compare=True)
        zero, one, two = case["before"], case["first"], case["second"]
        three = self._execute(case)
        effect, _transition = (
            contracts._require_controller_first_fusion_transition(
                execution=three, **case["env"]
            )
        )
        obligation, dense, lexical = self._sources(case)
        fusion = self._fusion_sources(obligation)[0]
        weak_values = tuple(
            ref(value)
            for value in (
                obligation,
                dense,
                lexical,
                fusion,
                effect,
                two.state,
                three.state,
            )
        )
        for name in ("claim", "projection", "bridge", "receipt"):
            case.pop(name, None)
        del obligation, dense, lexical, fusion, effect
        gc.collect()
        self.assertTrue(all(value() is not None for value in weak_values))
        self.assertEqual(
            weak_values[4]().source_receipt_sha256,
            weak_values[3]().receipt_sha256,
        )
        self.assertIs(weak_values[5](), two.state)
        self.assertIs(weak_values[6](), three.state)
        validate_harness_state(
            state=three.state,
            store=case["env"]["store"],
        )
        for execution in (zero, one, two, three):
            validate_harness_execution(execution=execution, **case["env"])
        for execution, decision in (
            (zero, case["decision"]),
            (one, case["second_decision"]),
            (two, case["third_decision"]),
        ):
            validate_controller_decision_receipt(
                receipt=decision,
                execution=execution,
                **case["env"],
            )

    def test_source_effect_ledger_and_transition_drift_fail_readback(self):
        case = self._case()
        three = self._execute(case)
        effect, transition = (
            contracts._require_controller_first_fusion_transition(
                execution=three, **case["env"]
            )
        )
        obligation, _dense, _lexical = self._sources(case)
        fusion = self._fusion_sources(obligation)[0]
        mutations = (
            (fusion, "receipt_sha256", "0" * 64),
            (effect, "effect_sha256", "0" * 64),
            (three.state.belief, "source_receipt_sha256", "0" * 64),
            (three.state, "state_sha256", "0" * 64),
            (transition, "transition_sha256", "0" * 64),
            (three.ledger, "consumed_lane_keys", ()),
        )
        for target, attribute, replacement in mutations:
            with self.subTest(attribute=attribute):
                original = object.__getattribute__(target, attribute)
                object.__setattr__(target, attribute, replacement)
                try:
                    with self.assertRaises((TypeError, ValueError)):
                        contracts._require_controller_first_fusion_transition(
                            execution=three, **case["env"]
                        )
                    with self.assertRaises((TypeError, ValueError)):
                        validate_harness_execution(
                            execution=three, **case["env"]
                        )
                finally:
                    object.__setattr__(target, attribute, original)
                contracts._require_controller_first_fusion_transition(
                    execution=three, **case["env"]
                )

    def test_private_entrypoints_do_not_expand_public_surface(self):
        self.assertEqual(
            tuple(
                inspect.signature(
                    contracts._execute_controller_first_fusion_step
                ).parameters
            ),
            ("execution", "decision", "store", "config", "runtime"),
        )
        self.assertEqual(
            tuple(
                inspect.signature(
                    contracts._require_controller_first_fusion_transition
                ).parameters
            ),
            ("execution", "store", "config", "runtime"),
        )
        self.assertFalse(
            hasattr(orchestration, "execute_controller_first_fusion_step")
        )
        self.assertFalse(
            hasattr(orchestration, "require_controller_first_fusion_transition")
        )
        self.assertNotIn("HarnessTransitionReceipt", orchestration.__all__)


if __name__ == "__main__":
    unittest.main()
