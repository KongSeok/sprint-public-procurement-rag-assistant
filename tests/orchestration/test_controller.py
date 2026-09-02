from __future__ import annotations

import unittest
from dataclasses import replace

from midprojectrag.evidence import Evidence, EvidenceStore
from midprojectrag.retrieval import Candidate, BM25Retriever, HybridRetriever
from midprojectrag.orchestration import (Action, Harness, HarnessConfig, QueryPlan, Slot, Verification)


def fixture():
    pages = tuple(Evidence.create(doc_id=f"doc_{i:024x}", page=1, kind="page",
                                  text=f"document {i}", source_block_ids=(f"block_{i:024x}",)) for i in (1, 2))
    children = tuple(Evidence.create(doc_id=p.doc_id, page=1, kind="text", text=f"budget {i * 10}",
                                     source_block_ids=p.source_block_ids, parent_id=p.evidence_id)
                     for i, p in enumerate(pages, 1))
    table = Evidence.create(doc_id=pages[1].doc_id, page=1, kind="table", text="|budget|20|",
                            source_block_ids=("block_000000000000000000000003",),
                            parent_id=pages[1].evidence_id, object_id="table_1")
    return EvidenceStore((*pages, *children, table)), pages, children, table


class ScriptedRetriever:
    def __init__(self, batches):
        self.batches = iter(batches)
        self.calls = []
    def search(self, query, *, limit, allowed_doc_ids):
        self.calls.append((query, allowed_doc_ids))
        return tuple(Candidate(e.evidence_id, 1.0, "scripted", i+1) for i, e in enumerate(next(self.batches)))


class ScriptedVerifier:
    """A fixture, never a runtime semantic scorer."""
    def __init__(self, decisions):
        self.decisions = iter(decisions)
        self.calls = []
    def verify(self, slot, evidence):
        self.calls.append((slot, evidence))
        return next(self.decisions)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.store, self.pages, self.children, self.table = fixture()
    def run_case(self, batches, decisions, plan=None, **kwargs):
        retriever = ScriptedRetriever(batches)
        verifier = ScriptedVerifier(decisions)
        harness = Harness(store=self.store, retriever=retriever, verifier=verifier, **kwargs)
        result = harness.run(plan or QueryPlan("budget?", (Slot("a", "budget?"),)))
        return result, retriever, verifier
    def test_targeted_compare_doc_scope_and_retention(self):
        a, b = self.children
        plan = QueryPlan("compare budget", (Slot("a", "first budget", a.doc_id), Slot("b", "second budget", b.doc_id)), "compare")
        result, retriever, _ = self.run_case([[a], [b]], [Verification((a.evidence_id,)), Verification((b.evidence_id,))], plan)
        self.assertEqual(result.status, "READY")
        self.assertEqual(retriever.calls, [("first budget", frozenset({a.doc_id})), ("second budget", frozenset({b.doc_id}))])
        self.assertEqual({e.evidence_id for e in result.context}, {a.evidence_id, b.evidence_id})
        self.assertEqual([e.action.kind for e in result.events], ["search", "verify", "search", "verify", "stop"])
    def test_table_bridge_from_page(self):
        plan = QueryPlan("table budget", (Slot("a", "budget", self.table.doc_id, "table"),))
        result, _, _ = self.run_case([[self.pages[1]]], [Verification((self.table.evidence_id,))], plan)
        self.assertEqual(result.status, "READY")
        self.assertIn("bridge", [e.action.kind for e in result.events])
        self.assertIn(self.table.evidence_id, result.required_ids)
    def test_nested_child_bridge_walks_to_page(self):
        nested = Evidence.create(doc_id=self.table.doc_id, page=1, kind="text", text="nested row",
                                 source_block_ids=self.table.source_block_ids, parent_id=self.table.evidence_id)
        self.store = EvidenceStore((*self.store.all(), nested))
        result, _, _ = self.run_case([[nested]], [Verification(()), Verification((self.table.evidence_id,))])
        self.assertEqual(result.status, "READY")
    def test_unknown_verified_id_fails(self):
        result, _, _ = self.run_case([[self.children[0]]], [Verification((self.table.evidence_id,))])
        self.assertEqual(result.status, "ERROR")
        self.assertEqual(result.reason, "verification_outside_supplied_evidence")
    def test_list_without_enumerator_abstains(self):
        a = self.children[0]
        plan = QueryPlan("list all budgets", (Slot("a", "budgets"),), "list")
        result, _, _ = self.run_case([[a]], [Verification((a.evidence_id,))], plan)
        self.assertEqual(result.reason, "enumeration_capability_missing")
    def test_enumerator_false_is_not_complete(self):
        class Enumerator:
            def is_complete(self, plan, evidence): return False
        a = self.children[0]
        result, _, _ = self.run_case([[a]], [Verification((a.evidence_id,))],
                                     QueryPlan("all", (Slot("a", "all"),), "list"), enumeration=Enumerator())
        self.assertEqual(result.reason, "enumeration_incomplete")
    def test_no_progress_bounded(self):
        result, retriever, _ = self.run_case([[self.children[0]]], [Verification(())])
        self.assertEqual(result.reason, "no_progress")
        self.assertEqual(len(retriever.calls), 1)
    def test_empty_search_never_verifies_or_ready(self):
        result, _, verifier = self.run_case([[]], [])
        self.assertEqual(result.status, "ABSTAINED")
        self.assertFalse(verifier.calls)
    def test_contradiction_abstains(self):
        result, _, _ = self.run_case([[self.children[0]]], [Verification((), True)])
        self.assertEqual(result.reason, "contradictory_evidence")
    def test_too_small_context_abstains(self):
        a = self.children[0]
        result, _, _ = self.run_case([[a]], [Verification((a.evidence_id,))], config=HarnessConfig(max_context_chars=1))
        self.assertEqual(result.reason, "context_budget_exceeded")
    def test_action_budget(self):
        result, _, _ = self.run_case([[self.children[0]]], [], config=HarnessConfig(max_actions=1))
        self.assertEqual(result.reason, "action_budget_exhausted")
    def test_malicious_reranker(self):
        table = self.table
        class Reranker:
            def rerank(self, query, candidates): return (Candidate(table.evidence_id, 2, "evil", 1),)
        result, _, _ = self.run_case([[self.children[0]]], [], reranker=Reranker())
        self.assertEqual(result.status, "ERROR")
    def test_reranker_error_preserves_pre_rerank_observation(self):
        a = self.children[0]
        class Reranker:
            def rerank(self, query, candidates): raise TimeoutError("private provider message")
        result, _, _ = self.run_case([[a]], [], reranker=Reranker())
        self.assertEqual(result.status, "ERROR")
        self.assertEqual(result.events[0].pre_rerank_ids, (a.evidence_id,))
        self.assertEqual(result.events[0].candidate_ids, ())
    def test_scope_leak_fails(self):
        plan = QueryPlan("budget", (Slot("a", "budget"),), allowed_doc_ids=frozenset({self.children[0].doc_id}))
        result, _, _ = self.run_case([[self.children[1]]], [], plan)
        self.assertEqual(result.status, "ERROR")
    def test_illegal_stop(self):
        class Policy:
            policy_id = "test"
            def choose(self, state): return Action("stop")
        result, _, _ = self.run_case([], [], policy=Policy())
        self.assertEqual(result.reason, "illegal_policy_action")
    def test_policy_can_rewrite_missing_slot(self):
        a = self.children[0]
        class Policy:
            policy_id = "scripted"
            def choose(self, state):
                action = state.allowed_actions[0]
                if action.kind == "search" and dict(state.rounds)["a"] == 1:
                    return Action("search", "a", "funding amount")
                return action
        result, retriever, _ = self.run_case([[a], [a]], [Verification(()), Verification((a.evidence_id,))], policy=Policy())
        self.assertEqual(result.status, "READY")
        self.assertEqual(retriever.calls[-1][0], "funding amount")
    def test_deadline_provider_result_not_promoted(self):
        now = [0.0]
        class Slow:
            def search(inner, query, *, limit, allowed_doc_ids):
                now[0] = 5
                return ()
        h = Harness(store=self.store, retriever=Slow(), verifier=ScriptedVerifier([]),
                    config=HarnessConfig(timeout_seconds=1), clock=lambda: now[0])
        result = h.run(QueryPlan("budget", (Slot("a", "budget"),)))
        self.assertEqual(result.reason, "deadline_exceeded")
    def test_run_state_not_shared(self):
        a = self.children[0]
        h = Harness(store=self.store, retriever=ScriptedRetriever([[a], [a]]),
                    verifier=ScriptedVerifier([Verification((a.evidence_id,)), Verification((a.evidence_id,))]))
        plan = QueryPlan("budget", (Slot("a", "budget"),))
        self.assertEqual(h.run(plan).status, "READY")
        self.assertEqual(h.run(plan).state.actions_spent, 3)
    def test_hybrid_keeps_per_lane_trace(self):
        a = self.children[0]
        hybrid = HybridRetriever(self.store, {"lexical": BM25Retriever(self.store, evidence_ids=(a.evidence_id,))})
        h = Harness(store=self.store, retriever=hybrid, verifier=ScriptedVerifier([Verification((a.evidence_id,))]))
        result = h.run(QueryPlan("budget", (Slot("a", "budget"),)))
        self.assertEqual(result.events[0].ranks[0][1], "lexical")
    def test_invalid_dto_shapes(self):
        with self.assertRaises(ValueError): QueryPlan("x", (Slot("a", "a"), Slot("a", "b")))
        with self.assertRaises(ValueError): QueryPlan("x", (Slot("a", "a", "doc_2"),), allowed_doc_ids=frozenset({"doc_1"}))
        with self.assertRaises(ValueError): HarnessConfig(timeout_seconds=float("nan"))
        with self.assertRaises(ValueError): HarnessConfig(max_actions=True)
        with self.assertRaises(ValueError): Action("bogus")
        with self.assertRaises(ValueError): Action("stop", "a")
        with self.assertRaises(ValueError): Verification(("a", "a"))

    def test_prepared_subset_is_the_only_supplied_and_traced_verifier_input(self):
        a, b = self.children
        class PreparingVerifier(ScriptedVerifier):
            def prepare(self, slot, evidence):
                self.preparation_input = evidence
                return evidence[1:]
        verifier = PreparingVerifier([Verification((b.evidence_id,))])
        harness = Harness(store=self.store, retriever=ScriptedRetriever([[a, b]]), verifier=verifier)
        result = harness.run(QueryPlan("budget", (Slot("a", "budget"),)))
        self.assertEqual(result.status, "READY")
        self.assertEqual(verifier.preparation_input, (a, b))
        self.assertEqual(verifier.calls[0][1], (b,))
        search = next(event for event in result.events if event.action.kind == "search")
        verify = next(event for event in result.events if event.action.kind == "verify")
        self.assertEqual(search.candidate_ids, (a.evidence_id, b.evidence_id))
        self.assertEqual(verify.candidate_ids, (b.evidence_id,))
        self.assertEqual(verify.verified_ids, (b.evidence_id,))

    def test_invalid_preparation_cannot_invent_duplicate_or_mutate_batch(self):
        a, b = self.children
        for prepared in ((b,), (a, a), [a], (object(),)):
            class PreparingVerifier(ScriptedVerifier):
                def prepare(self, slot, evidence): return prepared
            verifier = PreparingVerifier([])
            harness = Harness(store=self.store, retriever=ScriptedRetriever([[a]]), verifier=verifier)
            with self.subTest(prepared=prepared):
                result = harness.run(QueryPlan("budget", (Slot("a", "budget"),)))
                self.assertEqual(result.status, "ERROR")
                self.assertEqual(result.reason, "invalid_verifier_preparation")
                self.assertEqual(verifier.calls, [])

    def test_prepared_empty_batch_skips_provider_and_records_empty_input(self):
        a = self.children[0]
        class EmptyPreparation(ScriptedVerifier):
            def prepare(self, slot, evidence): return ()
        verifier = EmptyPreparation([])
        harness = Harness(store=self.store, retriever=ScriptedRetriever([[a]]), verifier=verifier)
        result = harness.run(QueryPlan("budget", (Slot("a", "budget"),)))
        self.assertEqual(result.status, "ABSTAINED")
        self.assertEqual(result.reason, "no_progress")
        self.assertEqual(verifier.calls, [])
        verify = next(event for event in result.events if event.action.kind == "verify")
        self.assertEqual(verify.candidate_ids, ())
        self.assertEqual(verify.verified_ids, ())

    def test_verifier_cannot_claim_candidate_removed_by_preparation(self):
        a, b = self.children
        class PreparingVerifier(ScriptedVerifier):
            def prepare(self, slot, evidence): return (b,)
        verifier = PreparingVerifier([Verification((a.evidence_id,))])
        result = Harness(store=self.store, retriever=ScriptedRetriever([[a, b]]), verifier=verifier).run(
            QueryPlan("budget", (Slot("a", "budget"),)))
        self.assertEqual(result.reason, "verification_outside_supplied_evidence")

    def test_bridge_action_is_unique_for_candidates_with_same_parent(self):
        states = []
        class FirstPolicy:
            policy_id = "scripted"
            def choose(self, state):
                states.append(state)
                return state.allowed_actions[0]
        result, _, _ = self.run_case([[self.pages[1], self.children[1]]],
                                     [Verification(()), Verification((self.table.evidence_id,))],
                                     policy=FirstPolicy())
        self.assertEqual(result.status, "READY")
        available_bridges = [[action for action in state.allowed_actions if action.kind == "bridge"]
                             for state in states]
        self.assertEqual([len(actions) for actions in available_bridges if actions], [1])
        self.assertEqual([event.action.evidence_id for event in result.events if event.action.kind == "bridge"],
                         [self.pages[1].evidence_id])

    def test_nonfinite_request_deadline_rejected_before_retrieval(self):
        retriever = ScriptedRetriever([])
        harness = Harness(store=self.store, retriever=retriever, verifier=ScriptedVerifier([]), clock=lambda: 0)
        plan = QueryPlan("budget", (Slot("a", "budget"),))
        for deadline in (float("nan"), float("inf"), float("-inf"), True, "5"):
            with self.subTest(deadline=deadline), self.assertRaisesRegex(ValueError, "invalid_request_deadline"):
                harness.run(plan, request_deadline=deadline)
        self.assertEqual(retriever.calls, [])

    def test_shorter_request_deadline_limits_harness_and_longer_cannot_extend_config(self):
        for configured, requested in ((20, 1), (1, 20)):
            now = [0.0]
            class SlowRetriever:
                def search(self, query, *, limit, allowed_doc_ids):
                    now[0] = 2.0
                    return ()
            harness = Harness(store=self.store, retriever=SlowRetriever(), verifier=ScriptedVerifier([]),
                              config=HarnessConfig(timeout_seconds=configured), clock=lambda: now[0])
            with self.subTest(configured=configured, requested=requested):
                result = harness.run(QueryPlan("budget", (Slot("a", "budget"),)), request_deadline=requested)
                self.assertEqual(result.reason, "deadline_exceeded")

    def test_deadline_exhausted_during_preparation_never_calls_verifier(self):
        a = self.children[0]
        now = [0.0]
        class SlowPreparation(ScriptedVerifier):
            def prepare(self, slot, evidence):
                now[0] = 2.0
                return evidence
        verifier = SlowPreparation([Verification((a.evidence_id,))])
        harness = Harness(store=self.store, retriever=ScriptedRetriever([[a]]), verifier=verifier,
                          config=HarnessConfig(timeout_seconds=1), clock=lambda: now[0])
        result = harness.run(QueryPlan("budget", (Slot("a", "budget"),)))
        self.assertEqual(result.reason, "deadline_exceeded")
        self.assertEqual(verifier.calls, [])

    def test_failed_verifier_preserves_actual_supplied_ids_and_state_without_support(self):
        a, b = self.children
        for error in (TimeoutError("sensitive verifier timeout"), ValueError("sensitive verifier failure")):
            class FailingVerifier:
                def prepare(self, slot, evidence): return (b,)
                def verify(self, slot, evidence):
                    self.supplied = evidence
                    raise error
            verifier = FailingVerifier()
            harness = Harness(store=self.store, retriever=ScriptedRetriever([[a, b]]), verifier=verifier)
            with self.subTest(error_type=type(error).__name__):
                result = harness.run(QueryPlan("budget", (Slot("a", "budget"),)))
                self.assertEqual(result.status, "ERROR")
                self.assertEqual(result.reason, "provider_or_contract_error")
                self.assertEqual(verifier.supplied, (b,))
                self.assertEqual(result.required_ids, ())
                self.assertEqual(result.context, ())
                verify_events = [event for event in result.events if event.action.kind == "verify"]
                self.assertEqual(len(verify_events), 1)
                event = verify_events[0]
                self.assertEqual(event.candidate_ids, (b.evidence_id,))
                self.assertEqual(event.verified_ids, ())
                self.assertIsNotNone(event.state_before)
                self.assertIsNotNone(event.state_after)
                self.assertEqual(event.state_before.missing, ("a",))
                self.assertEqual(event.state_before.verified, ())
                self.assertEqual(event.state_after.missing, ("a",))
                self.assertEqual(event.state_after.verified, ())
                self.assertEqual(event.state_after.terminal_reason, "provider_or_contract_error")
                self.assertNotIn("sensitive verifier", str(result))

    def test_verified_only_context_and_stop_trace_exclude_optional_candidates(self):
        a, b = self.children
        result, _, _ = self.run_case([[self.pages[0], a, b]], [Verification((a.evidence_id,))],
                                     pack_verified_only=True)
        self.assertEqual(result.status, "READY")
        self.assertEqual(result.context, (a,))
        self.assertEqual(result.required_ids, (a.evidence_id,))
        search = next(event for event in result.events if event.action.kind == "search")
        self.assertEqual(search.candidate_ids, (self.pages[0].evidence_id, a.evidence_id, b.evidence_id))
        stop = next(event for event in result.events if event.action.kind == "stop")
        self.assertEqual(stop.candidate_ids, result.required_ids)

    def test_verified_only_keeps_required_support_across_slots_and_documents(self):
        a, b = self.children
        plan = QueryPlan("compare budgets", (Slot("a", "first budget", a.doc_id),
                                             Slot("b", "second budget", b.doc_id)), "compare")
        result, _, _ = self.run_case([[self.pages[0], a], [self.pages[1], self.table, b]],
                                     [Verification((a.evidence_id,)), Verification((b.evidence_id,))], plan,
                                     pack_verified_only=True, config=HarnessConfig(max_context_items=2))
        self.assertEqual(result.status, "READY")
        self.assertEqual(result.context, (a, b))
        self.assertEqual(result.required_ids, (a.evidence_id, b.evidence_id))
        self.assertEqual(result.events[-1].candidate_ids, result.required_ids)

    def test_default_context_policy_still_retains_fitting_optional_candidates(self):
        a, b = self.children
        supplied = (self.pages[0], a, b)
        result, _, _ = self.run_case([supplied], [Verification((a.evidence_id,))])
        self.assertEqual(result.status, "READY")
        self.assertEqual(set(result.context), set(supplied))
        self.assertEqual(result.required_ids, (a.evidence_id,))
        self.assertEqual(result.events[-1].candidate_ids, tuple(record.evidence_id for record in result.context))

    def test_context_policy_requires_actual_boolean(self):
        for value in (0, 1, "true", None, [], {}):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "invalid_context_policy"):
                Harness(store=self.store, retriever=ScriptedRetriever([]), verifier=ScriptedVerifier([]),
                        pack_verified_only=value)


if __name__ == "__main__": unittest.main()
