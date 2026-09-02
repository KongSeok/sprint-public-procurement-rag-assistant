from __future__ import annotations

import unittest
import html
import json
from dataclasses import replace

from midprojectrag.evidence import Evidence, EvidenceStore
from midprojectrag.orchestration.enumeration import BoundedListEnumerator, EnumerationConfig
from midprojectrag.orchestration.types import QueryPlan, Slot


def page(doc: int, text: str = "Synthetic project", number: int = 1) -> Evidence:
    return Evidence.create(doc_id=f"doc_{doc:024x}", page=number, kind="page", text=text,
                           source_block_ids=(f"block_{doc * 100 + number:024x}",))


def answer(status, refs=(), complete=True):
    return {"status": status, "evidence_ids": list(refs), "scan_complete": complete}


def ids(payload):
    return tuple(dict.fromkeys(e["evidence_id"] for e in payload["evidence"]))


class ScriptedBackend:
    """Injected semantic fixture decisions, not a runtime lexical judge."""
    def __init__(self, decide):
        self.decide = decide
        self.calls = []

    def ask(self, purpose, payload):
        self.calls.append((purpose, payload))
        return self.decide(payload)


class EnumerationTests(unittest.TestCase):
    def setUp(self):
        self.pages = (page(1), page(2))
        self.store = EvidenceStore(self.pages)
        self.plan = QueryPlan("List all matching projects", (Slot("list", "matching projects"),), "list")

    def run_case(self, decide, *, store=None, plan=None, config=EnumerationConfig(), **kwargs):
        backend = ScriptedBackend(decide)
        enumerator = BoundedListEnumerator(store or self.store, backend, config=config,
                                           clock=kwargs.pop("clock", lambda: 0))
        return enumerator.enumerate(plan or self.plan, **kwargs), backend

    def test_enumerates_match_beyond_top_k(self):
        pages = tuple(page(i) for i in range(1, 36))
        last = pages[-1]
        def decide(payload):
            return answer("match", ids(payload)) if payload["document_id"] == last.doc_id else answer("no_match")
        result, backend = self.run_case(decide, store=EvidenceStore(pages))
        self.assertTrue(result.complete)
        self.assertEqual(result.matched_doc_ids, (last.doc_id,))
        self.assertEqual(result.supporting_ids, (last.evidence_id,))
        self.assertEqual(len(result.scanned_doc_ids), 35)
        self.assertEqual(len(backend.calls), 70)
        self.assertEqual({purpose for purpose, _ in backend.calls}, {"enumerate"})

    def test_scope_limits_full_universe(self):
        wanted = self.pages[1]
        plan = replace(self.plan, allowed_doc_ids=frozenset({wanted.doc_id}))
        result, backend = self.run_case(lambda p: answer("match", ids(p)), plan=plan)
        self.assertTrue(result.complete)
        self.assertEqual(result.scoped_doc_ids, (wanted.doc_id,))
        self.assertEqual({p["document_id"] for _, p in backend.calls}, {wanted.doc_id})
        self.assertTrue(all(e["doc_id"] == wanted.doc_id for _, p in backend.calls for e in p["evidence"]))

    def test_missing_requested_doc_does_not_shrink_scope(self):
        plan = replace(self.plan, allowed_doc_ids=frozenset({self.pages[0].doc_id, "missing"}))
        result, backend = self.run_case(lambda _: answer("no_match"), plan=plan)
        self.assertFalse(result.complete)
        self.assertEqual(result.reason, "document_scope_missing_from_store")
        self.assertFalse(backend.calls)

    def test_empty_universe_not_vacuously_complete(self):
        result, backend = self.run_case(lambda _: answer("no_match"), store=EvidenceStore(()))
        self.assertFalse(result.complete)
        self.assertEqual(result.reason, "empty_document_universe")
        self.assertFalse(backend.calls)

    def test_all_no_match_requires_scan_and_reduce_of_nonempty_universe(self):
        result, backend = self.run_case(lambda _: answer("no_match"))
        self.assertTrue(result.complete)
        self.assertEqual(result.matched_doc_ids, ())
        self.assertEqual(result.supporting_ids, ())
        self.assertEqual(len(backend.calls), 4)
        for _, payload in backend.calls:
            if payload["phase"] == "reduce":
                self.assertTrue(payload["scan_summary"]["all_unrelated"])

    def test_page_text_deduplicates_covered_child_but_keeps_table(self):
        parent = self.pages[0]
        child = Evidence.create(doc_id=parent.doc_id, page=1, kind="text", text=parent.text,
                                source_block_ids=parent.source_block_ids, parent_id=parent.evidence_id)
        table = Evidence.create(doc_id=parent.doc_id, page=1, kind="table", text="|stage|complete|",
                                source_block_ids=("table-block",), parent_id=parent.evidence_id,
                                object_id="table-object")
        result, backend = self.run_case(lambda _: answer("no_match"), store=EvidenceStore((parent, child, table)))
        self.assertTrue(result.complete)
        scanned = {i for _, p in backend.calls if p["phase"] == "scan" for i in ids(p)}
        self.assertEqual(scanned, {parent.evidence_id, table.evidence_id})
        self.assertEqual(result.chars_scanned, len(parent.text) + len(table.text))

    def test_distinct_child_text_is_not_dropped(self):
        parent = self.pages[0]
        child = Evidence.create(doc_id=parent.doc_id, page=1, kind="text", text="additional canonical fact",
                                source_block_ids=("extra",), parent_id=parent.evidence_id)
        result, backend = self.run_case(lambda _: answer("no_match"), store=EvidenceStore((parent, child)))
        self.assertTrue(result.complete)
        scanned = {i for _, p in backend.calls if p["phase"] == "scan" for i in ids(p)}
        self.assertEqual(scanned, {parent.evidence_id, child.evidence_id})

    def test_text_beneath_unscanned_figure_is_not_dropped(self):
        parent = self.pages[0]
        figure = Evidence.create(doc_id=parent.doc_id, page=1, kind="figure", text="OCR text",
                                 source_block_ids=("figure-block",), parent_id=parent.evidence_id,
                                 object_id="figure-object")
        child = Evidence.create(doc_id=parent.doc_id, page=1, kind="text", text=figure.text,
                                source_block_ids=figure.source_block_ids, parent_id=figure.evidence_id)
        result, backend = self.run_case(lambda _: answer("no_match"), store=EvidenceStore((parent, figure, child)))
        self.assertTrue(result.complete)
        scanned = {i for _, p in backend.calls if p["phase"] == "scan" for i in ids(p)}
        self.assertEqual(scanned, {parent.evidence_id, child.evidence_id})

    def test_missing_canonical_text_cannot_be_reduced_to_no_match(self):
        evidence = page(10)
        store = EvidenceStore((evidence,))
        # Defense in depth: a valid immutable store normally prevents this shape.
        object.__setattr__(evidence, "text", "")
        result, backend = self.run_case(lambda _: answer("no_match"), store=store)
        self.assertFalse(result.complete)
        self.assertEqual(result.reason, "canonical_document_text_missing")
        self.assertFalse(backend.calls)

    def test_cross_page_partial_facts_reduce_together(self):
        pages = (page(1, "Predicate A " * 20), page(1, "Predicate B " * 20, 2))
        def decide(payload):
            return answer("unknown" if payload["phase"] == "scan" else "match", ids(payload))
        config = EnumerationConfig(max_batch_chars=900)
        result, backend = self.run_case(decide, store=EvidenceStore(pages), config=config)
        self.assertTrue(result.complete)
        self.assertEqual(set(result.supporting_ids), {p.evidence_id for p in pages})
        reduce = [p for _, p in backend.calls if p["phase"] == "reduce"]
        self.assertEqual(len(reduce), 1)
        self.assertGreater(reduce[0]["scan_summary"]["batches"], 1)
        self.assertEqual(set(ids(reduce[0])), {p.evidence_id for p in pages})

    def test_early_match_does_not_skip_later_contradiction(self):
        pages = (page(1, "Positive fact " * 20), page(1, "Contradiction " * 20, 2))
        def decide(payload):
            return answer("match", ids(payload)) if payload["phase"] == "scan" else answer("unknown", ids(payload))
        result, backend = self.run_case(decide, store=EvidenceStore(pages),
                                        config=EnumerationConfig(max_batch_chars=900))
        self.assertFalse(result.complete)
        self.assertEqual(result.reason, "document_decision_unknown")
        self.assertEqual(result.chars_scanned, sum(len(p.text) for p in pages))
        self.assertTrue(any(p["phase"] == "reduce" for _, p in backend.calls))

    def test_late_negative_can_override_early_positive(self):
        result, _ = self.run_case(lambda p: answer("match", ids(p)) if p["phase"] == "scan" else answer("no_match", ids(p)))
        self.assertTrue(result.complete)
        self.assertEqual(result.matched_doc_ids, ())

    def test_unknown_without_locatable_facts_remains_incomplete(self):
        result, backend = self.run_case(lambda _: answer("unknown"))
        self.assertFalse(result.complete)
        self.assertEqual(result.reason, "document_decision_unknown")
        self.assertEqual(result.scanned_doc_ids, tuple(sorted(p.doc_id for p in self.pages)))
        self.assertTrue(all(p["phase"] == "scan" for _, p in backend.calls))

    def test_incomplete_scan_cannot_emit_receipt(self):
        result, _ = self.run_case(lambda _: answer("no_match", complete=False))
        self.assertFalse(result.complete)
        self.assertEqual(result.reason, "document_scan_incomplete")
        self.assertEqual(result.scanned_doc_ids, ())

    def test_incomplete_reduction_cannot_emit_receipt(self):
        result, _ = self.run_case(lambda p: answer("no_match", complete=p["phase"] == "scan"))
        self.assertFalse(result.complete)
        self.assertEqual(result.reason, "document_decision_unknown")

    def test_unknown_or_cross_document_ids_rejected(self):
        result, _ = self.run_case(lambda _: answer("match", (self.pages[1].evidence_id,)))
        self.assertFalse(result.complete)
        self.assertEqual(result.reason, "enumeration_reference_outside_supplied_evidence")

    def test_nested_hostile_response_shapes_fail_closed(self):
        bad = [
            {"status": {}, "evidence_ids": [], "scan_complete": True},
            {"status": "match", "evidence_ids": [{}], "scan_complete": True},
            {"status": "no_match", "evidence_ids": [], "scan_complete": 1},
            {"status": "no_match", "evidence_ids": [], "scan_complete": True, "extra": 1},
        ]
        for value in bad:
            with self.subTest(value=value):
                result, _ = self.run_case(lambda _: value)
                self.assertFalse(result.complete)
                self.assertEqual(result.reason, "invalid_enumeration_response")

    def test_duplicate_support_refs_rejected(self):
        result, _ = self.run_case(lambda p: answer("match", ids(p) * 2))
        self.assertEqual(result.reason, "enumeration_reference_outside_supplied_evidence")

    def test_match_needs_support(self):
        result, _ = self.run_case(lambda _: answer("match"))
        self.assertEqual(result.reason, "enumeration_match_without_support")

    def test_scan_no_match_cannot_discard_relevant_support(self):
        result, _ = self.run_case(lambda p: answer("no_match", ids(p)))
        self.assertEqual(result.reason, "enumeration_unrelated_scan_has_support")

    def test_long_text_is_scanned_exactly_without_truncation(self):
        evidence = page(1, "한글 \"quoted\" & newline\n" * 100)
        result, backend = self.run_case(lambda _: answer("no_match"), store=EvidenceStore((evidence,)),
                                        config=EnumerationConfig(max_batch_chars=900))
        self.assertTrue(result.complete)
        fragments = [e for _, p in backend.calls if p["phase"] == "scan" for e in p["evidence"]]
        self.assertGreater(len(fragments), 1)
        self.assertEqual("".join(e["text"] for e in fragments), evidence.text)
        self.assertEqual(fragments[0]["start"], 0)
        self.assertEqual(fragments[-1]["end"], len(evidence.text))
        self.assertTrue(all(a["end"] == b["start"] for a, b in zip(fragments, fragments[1:])))
        self.assertLessEqual(max(event.chars_sent for event in result.events if event.phase == "scan"), 900)

    def test_backend_escaped_utf8_capacity_controls_scan_splitting(self):
        evidence = page(1, '한글 "표" & 원문\n' * 100)
        class CapacityBackend(ScriptedBackend):
            def fits(self, purpose, payload):
                self.assert_purpose = purpose
                return len(html.escape(json.dumps(payload, ensure_ascii=False)).encode("utf-8")) <= 2200
        backend = CapacityBackend(lambda _: answer("no_match"))
        result = BoundedListEnumerator(EvidenceStore((evidence,)), backend, clock=lambda: 0).enumerate(self.plan)
        self.assertTrue(result.complete)
        self.assertTrue(all(backend.fits(purpose, payload) for purpose, payload in backend.calls))
        fragments = [e for _, p in backend.calls if p["phase"] == "scan" for e in p["evidence"]]
        self.assertGreater(len(fragments), 1)
        self.assertEqual("".join(e["text"] for e in fragments), evidence.text)

    def test_reduce_backend_capacity_is_checked_without_dropping_facts(self):
        class CapacityBackend(ScriptedBackend):
            def fits(self, purpose, payload):
                return payload["phase"] == "scan"
        backend = CapacityBackend(lambda p: answer("unknown", ids(p)))
        result = BoundedListEnumerator(self.store, backend, clock=lambda: 0).enumerate(self.plan)
        self.assertFalse(result.complete)
        self.assertEqual(result.reason, "enumeration_context_budget_exceeded")
        self.assertEqual(len(backend.calls), 1)

    def test_backend_capacity_too_small_for_one_character_prevents_call(self):
        class CapacityBackend(ScriptedBackend):
            def fits(self, purpose, payload):
                return False
        backend = CapacityBackend(lambda _: answer("no_match"))
        result = BoundedListEnumerator(self.store, backend, clock=lambda: 0).enumerate(self.plan)
        self.assertEqual(result.reason, "enumeration_context_budget_exceeded")
        self.assertFalse(backend.calls)

    def test_call_budget_includes_reduction(self):
        result, backend = self.run_case(lambda _: answer("no_match"), config=EnumerationConfig(max_calls=1))
        self.assertFalse(result.complete)
        self.assertEqual(result.reason, "call_budget_exhausted")
        self.assertEqual(len(backend.calls), 1)

    def test_total_character_budget_accounts_for_payload(self):
        result, backend = self.run_case(lambda _: answer("no_match"), config=EnumerationConfig(max_total_chars=1))
        self.assertEqual(result.reason, "total_character_budget_exceeded")
        self.assertFalse(backend.calls)

    def test_payload_too_large_even_for_one_character(self):
        result, backend = self.run_case(lambda _: answer("no_match"), config=EnumerationConfig(max_batch_chars=1))
        self.assertEqual(result.reason, "batch_character_budget_exceeded")
        self.assertFalse(backend.calls)

    def test_reduce_budget_never_drops_positive_or_partial_facts(self):
        result, backend = self.run_case(lambda p: answer("unknown", ids(p)),
                                        config=EnumerationConfig(max_reduce_chars=1))
        self.assertFalse(result.complete)
        self.assertEqual(result.reason, "reduce_character_budget_exceeded")
        self.assertEqual(len(backend.calls), 1)

    def test_expired_deadline_prevents_call(self):
        result, backend = self.run_case(lambda _: answer("no_match"), request_deadline=0)
        self.assertEqual(result.reason, "deadline_exceeded")
        self.assertFalse(backend.calls)

    def test_late_result_does_not_mark_document_scanned(self):
        now = [0.0]
        def decide(_):
            now[0] = 2
            return answer("no_match")
        result, backend = self.run_case(decide, clock=lambda: now[0], request_deadline=1)
        self.assertFalse(result.complete)
        self.assertEqual(result.reason, "deadline_exceeded")
        self.assertEqual(result.scanned_doc_ids, ())
        self.assertEqual(len(backend.calls), 1)

    def test_citation_limit_never_truncates_matching_documents(self):
        result, _ = self.run_case(lambda p: answer("match", ids(p)), citation_limit=1)
        self.assertFalse(result.complete)
        self.assertEqual(result.reason, "citation_budget_exceeded")
        self.assertEqual(len(result.matched_doc_ids), 2)
        self.assertEqual(len(result.supporting_ids), 2)

    def test_document_budget_prevents_implicit_subset(self):
        result, backend = self.run_case(lambda _: answer("no_match"), config=EnumerationConfig(max_documents=1))
        self.assertEqual(result.reason, "document_budget_exceeded")
        self.assertFalse(backend.calls)

    def test_backend_error_is_sanitized(self):
        def decide(_):
            raise RuntimeError("private source content")
        result, _ = self.run_case(decide)
        self.assertEqual(result.reason, "enumeration_backend_error")
        self.assertNotIn("private", repr(result))

    def test_backend_timeout_remains_incomplete(self):
        def decide(_):
            raise TimeoutError("private transport")
        result, _ = self.run_case(decide)
        self.assertEqual(result.reason, "backend_budget_exhausted")

    def test_history_is_present_in_every_call(self):
        plan = replace(self.plan, history=(("user", "Scope means these synthetic projects"),))
        result, backend = self.run_case(lambda _: answer("no_match"), plan=plan)
        self.assertTrue(result.complete)
        self.assertTrue(all(p["history"] == [{"role": "user", "content": plan.history[0][1]}] for _, p in backend.calls))

    def test_visual_slot_has_explicit_gap(self):
        plan = replace(self.plan, slots=(Slot("list", "visual matches", kind="figure"),))
        result, backend = self.run_case(lambda _: answer("no_match"), plan=plan)
        self.assertEqual(result.reason, "enumeration_visual_capability_gap")
        self.assertFalse(backend.calls)

    def test_no_cross_request_state(self):
        backend = ScriptedBackend(lambda p: answer("match", ids(p)))
        enumerator = BoundedListEnumerator(self.store, backend, clock=lambda: 0)
        first = enumerator.enumerate(self.plan)
        second = enumerator.enumerate(self.plan)
        self.assertEqual(first, second)
        self.assertEqual(first.calls, 4)

    def test_compatibility_gate_requires_every_match_in_context(self):
        backend = ScriptedBackend(lambda p: answer("match", ids(p)))
        enumerator = BoundedListEnumerator(self.store, backend, clock=lambda: 0)
        self.assertFalse(enumerator.is_complete(self.plan, (self.pages[0],)))
        self.assertTrue(enumerator.is_complete(self.plan, self.pages))

    def test_compatibility_gate_does_not_promote_empty_answer(self):
        backend = ScriptedBackend(lambda _: answer("no_match"))
        enumerator = BoundedListEnumerator(self.store, backend, clock=lambda: 0)
        self.assertFalse(enumerator.is_complete(self.plan, ()))

    def test_bad_configuration_and_request_types(self):
        with self.assertRaises(ValueError): EnumerationConfig(max_calls=True)
        with self.assertRaises(ValueError): EnumerationConfig(timeout_seconds=float("nan"))
        enumerator = BoundedListEnumerator(self.store, ScriptedBackend(lambda _: answer("no_match")))
        with self.assertRaises(ValueError): enumerator.enumerate(replace(self.plan, query_type="fact"))
        with self.assertRaises(ValueError): enumerator.enumerate(self.plan, citation_limit=True)
        with self.assertRaises(ValueError): enumerator.enumerate(self.plan, citation_limit=6)
        with self.assertRaises(ValueError): enumerator.enumerate(self.plan, request_deadline=float("nan"))


if __name__ == "__main__":
    unittest.main()
