"""Synthetic composition tests for exhaustive list routing and private receipts."""
from __future__ import annotations

import json
import unittest
from dataclasses import asdict, replace

from midprojectrag.answering.evidence_adapter import EvidenceAnswerAdapter
from midprojectrag.evaluation import validate_response
from midprojectrag.evidence import EvidenceStore
from midprojectrag.orchestration import Harness, HarnessConfig, QueryPlan, Slot, Verification
from midprojectrag.orchestration.artifacts import digest, trace_record
from midprojectrag.orchestration.cli import ByteUpperCounter
from midprojectrag.orchestration.enumeration import BoundedListEnumerator, EnumerationConfig
from midprojectrag.orchestration.pipeline import EvidenceHarnessPipeline, EvidencePipelineResult, ListPipelineResult
from tests.orchestration.test_controller import ScriptedRetriever, ScriptedVerifier
from tests.orchestration.test_enumeration import ScriptedBackend, answer, ids, page
from tests.orchestration.test_integration import SyntheticGenerator
from tests.orchestration.test_llm import request


class ListPipelineTests(unittest.TestCase):
    def setUp(self):
        self.pages = tuple(page(i, f"Synthetic project {i}") for i in range(1, 13))
        self.store = EvidenceStore(self.pages)
        self.req = request()
        self.req["question"] = "해당 조건에 맞는 사업을 모두 나열해줘"
        self.req["document_scope"] = {"mode": "all", "doc_ids": []}
        self.plan = QueryPlan(self.req["question"], (Slot("list", "조건에 맞는 사업"),),
                              "list", (("user", "첫 문서"),))

    def compose(self, decide, *, store=None, config=HarnessConfig(),
                enumeration_config=EnumerationConfig(), batches=(), verifications=()):
        store = self.store if store is None else store
        backend = ScriptedBackend(decide)
        retriever = ScriptedRetriever(batches)
        verifier = ScriptedVerifier(verifications)
        harness = Harness(store=store, retriever=retriever, verifier=verifier, config=config)
        enumerator = BoundedListEnumerator(store, backend, config=enumeration_config)
        generator = SyntheticGenerator()
        pipeline = EvidenceHarnessPipeline(harness=harness, enumerator=enumerator,
            answer_adapter=EvidenceAnswerAdapter(generator=generator, counter=ByteUpperCounter()))
        return pipeline, backend, generator, retriever, verifier

    def test_all_positives_beyond_top_k_reach_answer_without_retrieval(self):
        positives = {p.doc_id for p in self.pages[-2:]}
        def decide(payload):
            return answer("match", ids(payload)) if payload["document_id"] in positives else answer("no_match")
        pipeline, backend, generator, retriever, verifier = self.compose(
            decide, config=HarnessConfig(max_candidates=1))
        result = pipeline.query(self.req, plan=self.plan)
        self.assertIsInstance(result, ListPipelineResult)
        self.assertEqual(result.status, "READY")
        self.assertTrue(result.enumeration.complete)
        self.assertEqual(result.answer.response["status"], "answered")
        self.assertFalse(validate_response(result.answer.response))
        expected_ids = {p.evidence_id for p in self.pages[-2:]}
        self.assertEqual(set(result.required_ids), expected_ids)
        self.assertEqual({e.evidence_id for e in result.context}, expected_ids)
        self.assertEqual(set(result.answer.citation_map.values()), expected_ids)
        self.assertEqual({c["doc_id"] for c in result.answer.response["citations"]}, positives)
        self.assertEqual(len(generator.prompts), 1)
        self.assertEqual(len(backend.calls), len(self.pages) * 2)
        self.assertFalse(retriever.calls)
        self.assertFalse(verifier.calls)

    def test_citation_cap_abstains_without_truncating_positive_set(self):
        req = {**self.req, "options": {"max_citations": 1}}
        pipeline, _, generator, retriever, _ = self.compose(
            lambda p: answer("match", ids(p)), store=EvidenceStore(self.pages[:2]))
        result = pipeline.query(req, plan=self.plan)
        self.assertEqual(result.status, "ABSTAINED")
        self.assertEqual(result.reason, "citation_budget_exceeded")
        self.assertEqual(len(result.enumeration.matched_doc_ids), 2)
        self.assertEqual(len(result.required_ids), 2)
        self.assertEqual(result.context, ())
        self.assertEqual(result.answer.response["status"], "abstained")
        self.assertFalse(generator.prompts)
        self.assertFalse(retriever.calls)

    def test_unknown_document_never_generates_partial_list(self):
        def decide(payload):
            return answer("unknown", ids(payload)) if payload["phase"] == "reduce" else answer("match", ids(payload))
        pipeline, _, generator, _, _ = self.compose(decide)
        result = pipeline.query(self.req, plan=self.plan)
        self.assertEqual(result.status, "ABSTAINED")
        self.assertEqual(result.reason, "document_decision_unknown")
        self.assertEqual(result.context, ())
        self.assertFalse(generator.prompts)

    def test_context_budget_keeps_full_receipt_but_abstains(self):
        pipeline, _, generator, _, _ = self.compose(lambda p: answer("match", ids(p)),
            store=EvidenceStore(self.pages[:2]), config=HarnessConfig(max_context_chars=1))
        result = pipeline.query(self.req, plan=self.plan)
        self.assertTrue(result.enumeration.complete)
        self.assertEqual(result.status, "ABSTAINED")
        self.assertEqual(result.reason, "enumeration_context_budget_exceeded")
        self.assertEqual(len(result.required_ids), 2)
        self.assertFalse(generator.prompts)

    def test_empty_match_set_returns_exhaustive_negative_receipt_and_abstains(self):
        pipeline, backend, generator, _, _ = self.compose(lambda _: answer("no_match"))
        result = pipeline.query(self.req, plan=self.plan)
        self.assertTrue(result.enumeration.complete)
        self.assertEqual(result.enumeration.matched_doc_ids, ())
        self.assertEqual(result.status, "ABSTAINED")
        self.assertEqual(result.reason, "enumeration_no_matches")
        self.assertEqual(len(backend.calls), len(self.pages) * 2)
        self.assertFalse(generator.prompts)

    def test_backend_failure_is_standard_operational_error_not_no_matches(self):
        def fail(_):
            raise RuntimeError("sensitive provider response")
        pipeline, _, generator, _, _ = self.compose(fail)
        result = pipeline.query(self.req, plan=self.plan)
        self.assertEqual(result.status, "ERROR")
        self.assertEqual(result.reason, "enumeration_backend_error")
        self.assertEqual(result.answer.response["status"], "error")
        self.assertEqual(result.answer.response["error"]["code"], "enumeration_backend_error")
        self.assertIsNone(result.answer.response["abstention"])
        self.assertFalse(validate_response(result.answer.response))
        self.assertNotIn("sensitive", repr(result))
        self.assertFalse(generator.prompts)

    def test_reference_outside_supplied_batch_is_standard_error(self):
        pipeline, _, generator, _, _ = self.compose(lambda _: answer("match", (self.pages[-1].evidence_id,)))
        result = pipeline.query(self.req, plan=self.plan)
        self.assertEqual(result.status, "ERROR")
        self.assertEqual(result.reason, "enumeration_reference_outside_supplied_evidence")
        self.assertEqual(result.answer.response["status"], "error")
        self.assertFalse(validate_response(result.answer.response))
        self.assertFalse(generator.prompts)

    def test_scope_and_history_mismatch_rejected_before_all_provider_calls(self):
        for bad_plan in (replace(self.plan, history=()),
                         replace(self.plan, allowed_doc_ids=frozenset({self.pages[0].doc_id})),
                         replace(self.plan, query="different question")):
            with self.subTest(plan=bad_plan):
                pipeline, backend, generator, retriever, _ = self.compose(lambda _: answer("no_match"))
                with self.assertRaisesRegex(ValueError, "plan_request_mismatch"):
                    pipeline.query(self.req, plan=bad_plan)
                self.assertFalse(backend.calls)
                self.assertFalse(generator.prompts)
                self.assertFalse(retriever.calls)

    def test_explicit_scope_and_history_preserved_through_enumeration_and_answer(self):
        wanted = self.pages[-1]
        req = {**self.req, "document_scope": {"mode": "explicit", "doc_ids": [wanted.doc_id]}}
        plan = replace(self.plan, allowed_doc_ids=frozenset({wanted.doc_id}))
        pipeline, backend, generator, _, _ = self.compose(lambda p: answer("match", ids(p)))
        result = pipeline.query(req, plan=plan)
        self.assertEqual(result.answer.response["status"], "answered")
        self.assertEqual(result.enumeration.scoped_doc_ids, (wanted.doc_id,))
        self.assertEqual({p["document_id"] for _, p in backend.calls}, {wanted.doc_id})
        self.assertTrue(all(p["history"] == [{"role": "user", "content": "첫 문서"}] for _, p in backend.calls))
        self.assertIn("첫 문서", generator.prompts[0])
        self.assertIn(wanted.doc_id, generator.prompts[0])
        self.assertNotIn(self.pages[0].doc_id, generator.prompts[0])

    def test_compare_still_uses_scoped_slot_retrieval_and_never_enumerates(self):
        pages = self.pages[:2]
        req = {**self.req, "question": "두 사업 비교", "document_scope": {
            "mode": "explicit", "doc_ids": [p.doc_id for p in pages]}}
        plan = QueryPlan(req["question"], tuple(Slot(f"s{i}", f"사업 {i}", p.doc_id) for i, p in enumerate(pages)),
                         "compare", self.plan.history, frozenset(p.doc_id for p in pages))
        pipeline, backend, generator, retriever, _ = self.compose(
            lambda _: answer("no_match"), batches=tuple((p,) for p in pages),
            verifications=tuple(Verification((p.evidence_id,)) for p in pages))
        result = pipeline.query(req, plan=plan)
        self.assertIsInstance(result, EvidencePipelineResult)
        self.assertEqual(result.harness.status, "READY")
        self.assertEqual(result.answer.response["status"], "answered")
        self.assertFalse(backend.calls)
        self.assertEqual([scope for _, scope in retriever.calls], [frozenset({p.doc_id}) for p in pages])
        self.assertIn("첫 문서", generator.prompts[0])

    def test_separate_store_instances_are_rejected_even_when_hash_matches(self):
        pipeline, backend, generator, _, _ = self.compose(lambda _: answer("no_match"))
        clone = EvidenceStore(self.store.all())
        self.assertEqual(clone.artifact_sha256, self.store.artifact_sha256)
        with self.assertRaisesRegex(ValueError, "enumeration_store_mismatch"):
            EvidenceHarnessPipeline(harness=pipeline.harness, answer_adapter=pipeline.answer_adapter,
                                    enumerator=BoundedListEnumerator(clone, backend))
        self.assertFalse(backend.calls)
        self.assertFalse(generator.prompts)

    def test_list_receipt_serializes_with_v2_effective_config_and_hash(self):
        pipeline, _, _, _, _ = self.compose(lambda p: answer("match", ids(p)),
                                            store=EvidenceStore(self.pages[:2]))
        result = pipeline.query(self.req, plan=self.plan)
        runtime = {"route": "list", "enumeration": asdict(pipeline.enumerator.config),
                   "generator": "synthetic-fixture-only"}
        trace = trace_record(request=self.req, store=pipeline.harness.store,
            config=pipeline.harness.config, policy_id=pipeline.harness.policy.policy_id,
            result=result, synthetic=True, runtime=runtime)
        self.assertEqual(trace["schema_version"], "evidence-harness-trace-v2")
        self.assertEqual(trace["config_sha256"], digest(trace["config"]))
        self.assertEqual(trace["trace_sha256"], digest({k: v for k, v in trace.items() if k != "trace_sha256"}))
        self.assertEqual(trace["config"]["runtime"]["enumeration"]["max_calls"], 128)
        self.assertEqual(trace["result"]["enumeration"]["artifact_sha256"], pipeline.harness.store.artifact_sha256)
        self.assertEqual(set(trace["result"]["required_ids"]), set(result.required_ids))
        self.assertNotIn("harness", trace["result"])
        self.assertFalse(trace["official"])
        self.assertEqual(json.loads(json.dumps(trace, ensure_ascii=False)), trace)

    def test_valid_larger_request_cap_respects_smaller_enumerator_cap(self):
        req = {**self.req, "options": {"max_citations": 20}}
        pipeline, _, generator, _, _ = self.compose(lambda p: answer("match", ids(p)),
            store=EvidenceStore(self.pages[:2]), enumeration_config=EnumerationConfig(citation_limit=1))
        result = pipeline.query(req, plan=self.plan)
        self.assertEqual(result.status, "ABSTAINED")
        self.assertEqual(result.reason, "citation_budget_exceeded")
        self.assertFalse(generator.prompts)

    def test_expired_shared_deadline_prevents_enumeration_and_generation(self):
        pipeline, backend, generator, retriever, _ = self.compose(lambda _: answer("no_match"))
        result = pipeline.query(self.req, plan=self.plan, deadline=0)
        self.assertEqual(result.status, "ABSTAINED")
        self.assertEqual(result.reason, "deadline_exceeded")
        self.assertFalse(backend.calls)
        self.assertFalse(generator.prompts)
        self.assertFalse(retriever.calls)


if __name__ == "__main__":
    unittest.main()
