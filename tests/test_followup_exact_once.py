import gc
from threading import Barrier, Lock, Thread
import unittest
from weakref import ref

from midprojectrag.orchestration import (
    CatalogEntity,
    DeterministicPlanner,
    FollowupEvidencePolicy,
    PlanningCatalog,
    bind_followup,
    bind_primary_evidence_progress,
    default_rule_registry,
    finalize_followup_retrieval,
    retrieve_followup_primary,
)
from midprojectrag.runtime_integrity import RuntimeRequest
from midprojectrag.orchestration import followup_retrieval as followup_module
from tests import test_followup as fixtures


class _ScriptedRetriever:
    def __init__(self, *outcomes):
        self._outcomes = outcomes
        self._lock = Lock()
        self.calls = []

    def search(self, query, *, dense_k, lexical_k, scope):
        with self._lock:
            index = len(self.calls)
            self.calls.append((query, dense_k, lexical_k, scope))
        outcome = self._outcomes[index]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FollowupExactOnceTests(unittest.TestCase):
    def setUp(self):
        self.store, (self.ev_a, self.ev_b) = fixtures._evidence_store()
        self.registry = default_rule_registry()
        catalog = PlanningCatalog.synthetic(
            "followup-exact-once-v1",
            (
                CatalogEntity(
                    "예약발매시스템",
                    "예약발매시스템",
                    "business",
                    ("doc-a",),
                    "business_alias",
                ),
                CatalogEntity(
                    "다른사업",
                    "다른사업",
                    "business",
                    ("doc-b",),
                    "business_alias",
                ),
            ),
        )
        self.planner = DeterministicPlanner.for_test(self.registry, catalog)

    def _bound(self, *, document_scope=None):
        request = RuntimeRequest(
            question="그 사업의 기간은?",
            history=(
                fixtures._assistant_turn(
                    ("doc-a",), (self.ev_a.evidence_id,)
                ),
            ),
            document_scope=(
                {"mode": "all", "doc_ids": []}
                if document_scope is None
                else document_scope
            ),
            options={"allow_global_fallback": True},
            prior_citation_state=fixtures._prior(
                ("doc-a",), (self.ev_a.evidence_id,)
            ),
        )
        return bind_followup(
            request,
            self.planner.plan(request),
            self.store,
            self.registry,
        )

    def _primary(self, bound, retriever):
        return retrieve_followup_primary(
            bound=bound,
            store=self.store,
            registry=self.registry,
            retriever=retriever,
        )

    def _progress(self, bound, primary, verified=()):
        return bind_primary_evidence_progress(
            bound=bound,
            primary=primary,
            store=self.store,
            registry=self.registry,
            policy=FollowupEvidencePolicy.v1(),
            verified_answer_evidence_ids=tuple(verified),
            verifier_id="deterministic-evidence-verifier-v1",
            verifier_config_sha256="1" * 64,
        )

    def _finalize(self, bound, primary, progress, retriever):
        return finalize_followup_retrieval(
            bound=bound,
            primary=primary,
            progress=progress,
            store=self.store,
            registry=self.registry,
            policy=FollowupEvidencePolicy.v1(),
            retriever=retriever,
        )

    def test_scripted_empty_then_candidate_second_primary_never_calls_again(self):
        bound = self._bound()
        retriever = _ScriptedRetriever(
            fixtures._result(self.store),
            fixtures._result(self.store, (self.ev_a,)),
        )

        primary = self._primary(bound, retriever)
        self.assertEqual(primary.result.candidates, ())
        with self.assertRaisesRegex(ValueError, "followup_primary_already_consumed"):
            self._primary(bound, retriever)
        self.assertEqual(len(retriever.calls), 1)

    def test_empty_scope_is_claimed_once_without_provider_calls(self):
        bound = self._bound(
            document_scope={"mode": "explicit", "doc_ids": ["doc-b"]}
        )
        retriever = _ScriptedRetriever()
        primary = self._primary(bound, retriever)
        self.assertFalse(primary.retriever_called)
        with self.assertRaisesRegex(ValueError, "followup_primary_already_consumed"):
            self._primary(bound, retriever)
        self.assertEqual(retriever.calls, [])

    def test_concurrent_primary_has_one_provider_winner(self):
        bound = self._bound()
        retriever = _ScriptedRetriever(fixtures._result(self.store, (self.ev_a,)))
        start = Barrier(3)
        successes = []
        errors = []

        def run():
            start.wait()
            try:
                successes.append(self._primary(bound, retriever))
            except Exception as exc:
                errors.append(exc)

        threads = (Thread(target=run), Thread(target=run))
        for thread in threads:
            thread.start()
        start.wait()
        for thread in threads:
            thread.join()

        self.assertEqual(len(retriever.calls), 1)
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(errors), 1)
        self.assertEqual(str(errors[0]), "followup_primary_already_consumed")

    def test_reentrant_primary_is_rejected_before_nested_provider_call(self):
        bound = self._bound()

        class ReentrantRetriever:
            def __init__(inner_self):
                inner_self.calls = 0
                inner_self.error = None

            def search(inner_self, query, *, dense_k, lexical_k, scope):
                inner_self.calls += 1
                try:
                    self._primary(bound, inner_self)
                except Exception as exc:
                    inner_self.error = exc
                return fixtures._result(self.store, (self.ev_a,))

        retriever = ReentrantRetriever()
        self._primary(bound, retriever)
        self.assertEqual(retriever.calls, 1)
        self.assertEqual(str(retriever.error), "followup_primary_already_consumed")

    def test_preflight_failure_is_retry_safe_but_provider_failure_is_terminal(self):
        bound = self._bound()
        with self.assertRaisesRegex(TypeError, "child_retriever_required"):
            self._primary(bound, object())

        exploding = _ScriptedRetriever(RuntimeError("boom"))
        with self.assertRaisesRegex(RuntimeError, "boom"):
            self._primary(bound, exploding)
        retry = _ScriptedRetriever(fixtures._result(self.store, (self.ev_a,)))
        with self.assertRaisesRegex(ValueError, "followup_primary_already_consumed"):
            self._primary(bound, retry)
        self.assertEqual(len(exploding.calls), 1)
        self.assertEqual(retry.calls, [])

    def test_malformed_primary_result_is_terminal_after_one_provider_call(self):
        bound = self._bound()
        retriever = _ScriptedRetriever(
            fixtures._result(self.store, bundle="0" * 64),
            fixtures._result(self.store, (self.ev_a,)),
        )
        with self.assertRaisesRegex(ValueError, "search_result_bundle_mismatch"):
            self._primary(bound, retriever)
        with self.assertRaisesRegex(ValueError, "followup_primary_already_consumed"):
            self._primary(bound, retriever)
        self.assertEqual(len(retriever.calls), 1)

    def test_provider_callback_bound_drift_is_caught_and_closes_failed(self):
        bound = self._bound()

        class DriftingRetriever:
            def __init__(inner_self):
                inner_self.calls = 0

            def search(inner_self, query, *, dense_k, lexical_k, scope):
                inner_self.calls += 1
                object.__setattr__(
                    bound.trace,
                    "fallback_authorized",
                    not bound.trace.fallback_authorized,
                )
                return fixtures._result(self.store, (self.ev_a,))

        retriever = DriftingRetriever()
        with self.assertRaisesRegex(
            ValueError, "followup_execution_claim_authority_drift"
        ):
            self._primary(bound, retriever)
        self.assertEqual(retriever.calls, 1)
        self.assertEqual(
            followup_module._FOLLOWUP_EXECUTION_CLAIMS[id(bound)].state,
            "primary_failed",
        )

    def test_progress_and_fallback_advance_the_same_single_claim(self):
        bound = self._bound()
        retriever = _ScriptedRetriever(
            fixtures._result(self.store),
            fixtures._result(self.store, (self.ev_b,)),
            fixtures._result(self.store, (self.ev_a,)),
        )
        primary = self._primary(bound, retriever)
        progress = self._progress(bound, primary)

        with self.assertRaisesRegex(ValueError, "followup_progress_already_consumed"):
            self._progress(bound, primary)
        outcome = self._finalize(bound, primary, progress, retriever)
        self.assertIsNotNone(outcome.fallback)
        with self.assertRaisesRegex(ValueError, "followup_finalize_already_consumed"):
            self._finalize(bound, primary, progress, retriever)
        self.assertEqual(len(retriever.calls), 2)

    def test_invalid_progress_preflight_can_be_retried(self):
        bound = self._bound()
        retriever = _ScriptedRetriever(fixtures._result(self.store, (self.ev_a,)))
        primary = self._primary(bound, retriever)
        with self.assertRaisesRegex(ValueError, "invalid_verifier_id"):
            bind_primary_evidence_progress(
                bound=bound,
                primary=primary,
                store=self.store,
                registry=self.registry,
                policy=FollowupEvidencePolicy.v1(),
                verified_answer_evidence_ids=(self.ev_a.evidence_id,),
                verifier_id="not-approved",
                verifier_config_sha256="1" * 64,
            )
        progress = self._progress(bound, primary, (self.ev_a.evidence_id,))
        self.assertTrue(progress.sufficient)

    def test_fallback_preflight_retry_and_provider_failure_are_exact_once(self):
        bound = self._bound()
        primary_retriever = _ScriptedRetriever(fixtures._result(self.store))
        primary = self._primary(bound, primary_retriever)
        progress = self._progress(bound, primary)

        with self.assertRaisesRegex(TypeError, "child_retriever_required"):
            self._finalize(bound, primary, progress, object())
        exploding = _ScriptedRetriever(RuntimeError("fallback boom"))
        with self.assertRaisesRegex(RuntimeError, "fallback boom"):
            self._finalize(bound, primary, progress, exploding)
        retry = _ScriptedRetriever(fixtures._result(self.store, (self.ev_b,)))
        with self.assertRaisesRegex(ValueError, "followup_finalize_already_consumed"):
            self._finalize(bound, primary, progress, retry)
        self.assertEqual(len(exploding.calls), 1)
        self.assertEqual(retry.calls, [])

    def test_reentrant_fallback_is_rejected_before_nested_provider_call(self):
        bound = self._bound()
        primary_retriever = _ScriptedRetriever(fixtures._result(self.store))
        primary = self._primary(bound, primary_retriever)
        progress = self._progress(bound, primary)

        class ReentrantRetriever:
            def __init__(inner_self):
                inner_self.calls = 0
                inner_self.error = None

            def search(inner_self, query, *, dense_k, lexical_k, scope):
                inner_self.calls += 1
                try:
                    self._finalize(bound, primary, progress, inner_self)
                except Exception as exc:
                    inner_self.error = exc
                return fixtures._result(self.store, (self.ev_b,))

        retriever = ReentrantRetriever()
        outcome = self._finalize(bound, primary, progress, retriever)
        self.assertIsNotNone(outcome.fallback)
        self.assertEqual(retriever.calls, 1)
        self.assertEqual(str(retriever.error), "followup_finalize_already_consumed")

    def test_concurrent_fallback_has_one_provider_winner(self):
        bound = self._bound()
        retriever = _ScriptedRetriever(
            fixtures._result(self.store),
            fixtures._result(self.store, (self.ev_b,)),
        )
        primary = self._primary(bound, retriever)
        progress = self._progress(bound, primary)
        start = Barrier(3)
        successes = []
        errors = []

        def run():
            start.wait()
            try:
                successes.append(self._finalize(bound, primary, progress, retriever))
            except Exception as exc:
                errors.append(exc)

        threads = (Thread(target=run), Thread(target=run))
        for thread in threads:
            thread.start()
        start.wait()
        for thread in threads:
            thread.join()

        self.assertEqual(len(retriever.calls), 2)
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(errors), 1)
        self.assertEqual(str(errors[0]), "followup_finalize_already_consumed")

    def test_completion_history_outlives_attempt_and_outcome_gc(self):
        bound = self._bound()
        retriever = _ScriptedRetriever(fixtures._result(self.store, (self.ev_a,)))
        primary = self._primary(bound, retriever)
        del primary
        gc.collect()
        self.assertIn(id(bound), followup_module._FOLLOWUP_EXECUTION_CLAIMS)
        with self.assertRaisesRegex(ValueError, "followup_primary_already_consumed"):
            self._primary(bound, retriever)
        self.assertEqual(len(retriever.calls), 1)

        second_bound = self._bound()
        second_retriever = _ScriptedRetriever(
            fixtures._result(self.store, (self.ev_a,))
        )
        primary = self._primary(second_bound, second_retriever)
        progress = self._progress(second_bound, primary, (self.ev_a.evidence_id,))
        outcome = self._finalize(second_bound, primary, progress, second_retriever)
        del outcome
        gc.collect()
        with self.assertRaisesRegex(ValueError, "followup_finalize_already_consumed"):
            self._finalize(second_bound, primary, progress, second_retriever)
        self.assertEqual(len(second_retriever.calls), 1)

    def test_claim_history_is_removed_when_bound_root_dies(self):
        bound = self._bound()
        identity = id(bound)
        bound_weak = ref(bound)
        retriever = _ScriptedRetriever(fixtures._result(self.store))
        primary = self._primary(bound, retriever)
        self.assertIn(identity, followup_module._FOLLOWUP_EXECUTION_CLAIMS)

        del primary
        del bound
        gc.collect()

        self.assertIsNone(bound_weak())
        self.assertNotIn(identity, followup_module._FOLLOWUP_EXECUTION_CLAIMS)


if __name__ == "__main__":
    unittest.main()
