"""First fusion reduces the first obligation into an effect-bound state."""

from hashlib import sha256
import json
import unittest

import midprojectrag.orchestration.execution_contracts as contracts
import midprojectrag.orchestration.harness_state as state_contracts
from midprojectrag.orchestration import validate_harness_state
import tests.test_controller_first_fusion_transition as fusion_fixtures
from tests.test_retrieval_obligations import _clone_slots


class ControllerFirstFusionStateTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fusion_fixtures.ControllerFirstFusionTransitionTests(
            methodName="runTest"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    @staticmethod
    def _fingerprint(state):
        payload = {
            "schema_version": "1.0",
            "obligations": [
                {
                    "obligation_key": entry.obligation_key,
                    "stage": entry.observation_stage,
                    "candidate_evidence_ids": list(entry.candidate_evidence_ids),
                    "verified_evidence_ids": list(entry.verified_evidence_ids),
                    "verifier_context_evidence_ids": [],
                }
                for entry in state.belief.evidence_map
            ],
        }
        return sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()

    def test_applied_fusion_mints_candidate_state_from_exact_effect(self):
        case = self.fixture._case()
        before_state = case["second"].state

        successor = self.fixture._execute(case)
        effect, transition = (
            contracts._require_controller_first_fusion_transition(
                execution=successor,
                **case["env"],
            )
        )

        self.assertIsNot(successor.state, before_state)
        entry = successor.state.belief.evidence_map[0]
        self.assertEqual(entry.observation_stage, "candidate")
        self.assertEqual(
            entry.candidate_evidence_ids,
            effect.ordered_evidence_ids,
        )
        self.assertEqual(entry.verified_evidence_ids, ())
        self.assertEqual(
            successor.state.belief.source_receipt_sha256,
            effect.effect_sha256,
        )
        self.assertEqual(
            transition.before_state_sha256,
            before_state.state_sha256,
        )
        self.assertEqual(
            transition.after_state_sha256,
            successor.state.state_sha256,
        )
        self.assertNotEqual(
            transition.before_progress_sha256,
            transition.after_progress_sha256,
        )
        validate_harness_state(state=successor.state, store=case["env"]["store"])

    def test_empty_compare_fusion_is_open_provisional_without_semantic_support(self):
        case = self.fixture._case(
            compare=True,
            mode="empty",
            lexical_mode="empty",
        )
        before_state = case["second"].state
        successor = self.fixture._execute(case)
        effect, _transition = (
            contracts._require_controller_first_fusion_transition(
                execution=successor,
                **case["env"],
            )
        )
        first = successor.state.belief.evidence_map[0]
        self.assertEqual((effect.outcome, effect.ordered_evidence_ids), ("empty", ()))
        self.assertEqual(
            (
                first.observation_stage,
                first.candidate_evidence_ids,
                first.verified_evidence_ids,
            ),
            ("provisional_missing", (), ()),
        )
        self.assertTrue(
            all(
                actual is previous
                for previous, actual in zip(
                    before_state.belief.evidence_map[1:],
                    successor.state.belief.evidence_map[1:],
                )
            )
        )
        progress = successor.state.progress
        self.assertEqual(
            progress.provisional_missing_obligation_keys,
            (first.obligation_key,),
        )
        self.assertEqual(progress.open_obligation_keys, progress.required_obligation_keys)
        self.assertEqual(
            (
                progress.verified_obligation_keys,
                progress.confirmed_missing_obligation_keys,
                progress.contradicted_obligation_keys,
                progress.slot_coverage_ratio,
                progress.answerability,
                progress.normal_stop_allowed,
                progress.abstain_required,
            ),
            ((), (), (), 0.0, "in_progress", False, False),
        )

    def test_effect_state_authority_rejects_clones_mixed_roots_and_tuple_drift(self):
        case = self.fixture._case(compare=True)
        successor = self.fixture._execute(case)
        effect, _transition = (
            contracts._require_controller_first_fusion_transition(
                execution=successor,
                **case["env"],
            )
        )
        authority = state_contracts._require_controller_first_fusion_state_authority(
            state=successor.state,
            store=case["env"]["store"],
        )
        self.assertIs(authority.before_state, case["second"].state)
        self.assertIs(authority.effect, effect)
        self.assertIs(
            authority.source_owner,
            state_contracts._require_harness_state_source_owner(
                state=case["second"].state,
                store=case["env"]["store"],
            ),
        )
        with self.assertRaises((TypeError, ValueError)):
            validate_harness_state(
                state=_clone_slots(successor.state),
                store=case["env"]["store"],
            )
        other = self.fixture._case()
        with self.assertRaises((TypeError, ValueError)):
            validate_harness_state(
                state=successor.state,
                store=other["env"]["store"],
            )
        with self.assertRaisesRegex(
            ValueError, "controller_effect_state_issuer_required"
        ):
            state_contracts._reduce_controller_first_fusion_state(
                before_state=case["second"].state,
                effect=effect,
                claim=authority.claim,
                **case["env"],
            )

        candidates = successor.state.belief.evidence_map[0].candidate_evidence_ids
        cloned_candidates = tuple(list(candidates))
        self.assertIsNot(cloned_candidates, candidates)
        object.__setattr__(
            successor.state.belief.evidence_map[0],
            "candidate_evidence_ids",
            cloned_candidates,
        )
        try:
            with self.assertRaises((TypeError, ValueError)):
                validate_harness_state(
                    state=successor.state,
                    store=case["env"]["store"],
                )
        finally:
            object.__setattr__(
                successor.state.belief.evidence_map[0],
                "candidate_evidence_ids",
                candidates,
            )
        validate_harness_state(
            state=successor.state,
            store=case["env"]["store"],
        )

    def test_transition_fingerprint_is_exact_semantics_and_readback_is_passive(self):
        case = self.fixture._case(compare=True, lexical_mode="empty")
        before_state = case["second"].state
        calls = self.fixture._calls_snapshot(case)
        successor = self.fixture._execute(case)
        effect, transition = (
            contracts._require_controller_first_fusion_transition(
                execution=successor,
                **case["env"],
            )
        )
        self.assertEqual(
            transition.before_progress_sha256,
            self._fingerprint(before_state),
        )
        self.assertEqual(
            transition.after_progress_sha256,
            self._fingerprint(successor.state),
        )
        self.assertEqual(successor.ledger.no_progress_streaks[0], 0)
        self.assertEqual(
            successor.ledger.no_progress_streaks[1:],
            case["second"].ledger.no_progress_streaks[1:],
        )
        owner = state_contracts._require_controller_first_fusion_state_authority(
            state=successor.state,
            store=case["env"]["store"],
        )
        self.assertIs(owner.effect, effect)
        contracts._require_controller_first_fusion_transition(
            execution=successor,
            **case["env"],
        )
        validate_harness_state(
            state=successor.state,
            store=case["env"]["store"],
        )
        self.assertEqual(self.fixture._calls_snapshot(case), calls)


if __name__ == "__main__":
    unittest.main()
