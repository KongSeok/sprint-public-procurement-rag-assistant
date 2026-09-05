"""Synthetic observation tests: no local model or API invocation."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
import unittest

from midprojectrag.answering.pipeline import _retrieval_query
from midprojectrag.evidence.builder import build_store
from midprojectrag.indexing.exact_index import ExactDenseIndex
from midprojectrag.retrieval.contracts import Candidate, SearchResult
from midprojectrag.retrieval.fusion import HybridChildRetriever
from midprojectrag.retrieval.legacy_page import LegacyPageLane
from midprojectrag.retrieval_experiment import ARTIFACT_KEYS, make_draft
from midprojectrag.runtime_integrity import ResolvedScope, RuntimeRequest
from midprojectrag.stage_checkpoints import canonical_sha, validate_checkpoint
from midprojectrag.stage_recorder import _record, record_request
from tests.test_child_dense import FakeKure
from tests.test_evidence_builder import chunk


class StageRecorderTests(unittest.TestCase):
    def setUp(self):
        self.chunks = [chunk("private-source-sentinel " + str(i), block="block_" + f"{i:024x}") for i in range(20)]
        self.store = build_store(self.chunks)
        self.rows = self.store.candidates()
        self.config = make_draft({key: self.store.bundle_sha256 if key == "evidence_store" else "a" * 64
                                  for key in ARTIFACT_KEYS})

    def result(self, lane, rows, **extra):
        return SearchResult(tuple(Candidate(e.evidence_id, e.doc_id, 1.0, lane, i) for i, e in enumerate(rows, 1)),
                            {"granularity": "child", "bundle_sha256": self.store.bundle_sha256,
                             "private_debug": "nested-raw-sentinel", **extra})

    def run_arm(self, arm="child_bm25_rrf", search=None, **kwargs):
        return _record(query="user: private-query-sentinel", scope=kwargs.pop("scope", ResolvedScope()),
                       store=self.store, config=self.config, run_id="run-1", case_id="case-1", arm_id=arm,
                       search=search or (lambda lane, limit: self.result(lane, self.rows)), **kwargs)

    def stages(self, output):
        return {c["stage"]: c for c in output["record"]["checkpoints"]}

    def events(self, output):
        return {c["stage"]: c for c in output["observations"]["stage_observations"]}

    def test_single_calls_raw_union_before_return_and_context(self):
        calls = []
        def search(lane, limit):
            calls.append((lane, limit))
            return self.result(lane, self.rows[:12] if lane == "dense" else self.rows[8:], encoder_calls=1)
        out = self.run_arm(search=search)
        cp, events = self.stages(out), self.events(out)
        self.assertEqual(calls, [("dense", 50), ("lexical", 50)])
        self.assertEqual([cp[s]["candidate_count"] for s in ("lane_dense", "lane_lexical", "fusion", "final_context")],
                         [12, 12, 20, 5])
        self.assertEqual(events["final_context"]["input_ids_sha256"],
                         canonical_sha(cp["fusion"]["ordered_evidence_ids"][:10]))
        self.assertEqual(events["fusion"]["upstream_receipt_sha256s"],
                         [events[s]["receipt_sha256"] for s in ("lane_dense", "lane_lexical")])

    def test_dense_arm_no_fusion_or_lexical_call(self):
        calls = []
        def search(lane, limit):
            calls.append(lane)
            return self.result(lane, self.rows)
        out = self.run_arm("child_kure", search)
        self.assertEqual(calls, ["dense"])
        cp = self.stages(out)
        self.assertEqual(cp["lane_dense"]["candidate_count"], 20)
        self.assertEqual(cp["final_context"]["candidate_count"], 5)
        for s in ("fusion", "lane_lexical", "lane_visual", "rerank"):
            self.assertEqual(cp[s]["outcome"], "unavailable")
            self.assertFalse(cp[s]["call_performed"])
            self.assertIsNone(self.events(out)[s]["elapsed_ms"])

    def test_real_page_class_remains_page_and_production_rejects_fake(self):
        provider = FakeKure()
        index = ExactDenseIndex(self.chunks, provider.embed([r["text"] for r in self.chunks]).vectors, engine="numpy")
        page = LegacyPageLane(index, self.store, provider, artifact_sha256="a" * 64)
        before = len(provider.calls)
        out = self.run_arm("page_kure", lambda lane, limit: page.search("user: query", limit))
        self.assertEqual(len(provider.calls) - before, 1)
        self.assertEqual(self.stages(out)["final_context"]["candidate_count"], 5)
        self.assertEqual({r["evidence_kind"] for r in self.stages(out)["lane_dense"]["ordered_stable_anchors"]}, {"page"})
        with self.assertRaises(ValueError):
            record_request(request=RuntimeRequest(question="q"), backend=page, store=self.store, config=self.config,
                           run_id="r", case_id="c", arm_id="page_kure")

    def test_empty_scope_wrapper_called_but_no_internal_encoder_calls(self):
        calls = []
        class Lane:
            def search(self, query, limit, *, allowed_doc_ids):
                calls.append(1)
                raise AssertionError("must not be reached")
        hybrid = HybridChildRetriever(self.store, Lane(), Lane())
        scope = ResolvedScope.from_allowed(frozenset(), origin="user_explicit")
        out = self.run_arm(scope=scope, search=lambda lane, limit: hybrid.search_lane("q", lane=lane, limit=limit, scope=scope))
        self.assertFalse(calls)
        for stage in ("lane_dense", "lane_lexical", "fusion", "final_context"):
            self.assertEqual(self.stages(out)[stage]["outcome"], "ok")
            self.assertEqual(self.stages(out)[stage]["candidate_count"], 0)
            self.assertTrue(self.stages(out)[stage]["call_performed"])
        self.assertEqual(self.events(out)["lane_dense"]["encoder_calls"], 0)

    def test_error_is_not_empty_no_retry_no_partial_fusion(self):
        calls = []
        def search(lane, limit):
            calls.append(lane)
            if lane == "dense":
                raise RuntimeError("private-error-sentinel")
            return self.result(lane, self.rows)
        out = self.run_arm(search=search)
        self.assertEqual(calls, ["dense", "lexical"])
        self.assertEqual(self.stages(out)["lane_dense"]["outcome"], "error")
        self.assertEqual(self.stages(out)["fusion"]["outcome"], "unavailable")
        self.assertEqual(self.stages(out)["final_context"]["outcome"], "unavailable")
        self.assertIsNone(self.events(out)["lane_dense"]["encoder_calls"])
        self.assertNotIn("private-error-sentinel", json.dumps(out))

    def test_projection_is_closed_hash_bound_and_content_free(self):
        before = deepcopy(self.config)
        out = self.run_arm()
        text = json.dumps(out)
        for secret in ("private-query-sentinel", "private-source-sentinel", "nested-raw-sentinel"):
            self.assertNotIn(secret, text)
        self.assertEqual(set(out["record"]), {"schema_version", "case_id", "run_id", "binding", "checkpoints"})
        for cp in out["record"]["checkpoints"]:
            validate_checkpoint(cp, self.store, out["record"]["binding"])
            event = self.events(out)[cp["stage"]]
            self.assertEqual(cp["source_receipt_sha256"], event["receipt_sha256"])
            self.assertEqual(event["receipt_sha256"], canonical_sha({k: v for k, v in event.items() if k != "receipt_sha256"}))
        self.assertEqual(before, self.config)
        self.assertEqual(out["record"]["binding"]["query_sha256"], sha256(b"user: private-query-sentinel").hexdigest())
        self.assertIs(out["observations"]["formal_comparison_authorized"], False)
        self.assertEqual(out["observations"]["producer_kind"], "synthetic")
        self.assertIsNone(out["observations"]["load_elapsed_ms"])

    def test_arm_execution_key_separate_but_common_query_scope_config(self):
        a, b = [self.run_arm(arm)["record"]["binding"] for arm in ("child_kure", "child_bm25_rrf")]
        self.assertNotEqual(a["execution_key_sha256"], b["execution_key_sha256"])
        self.assertEqual({k: v for k, v in a.items() if k != "execution_key_sha256"},
                         {k: v for k, v in b.items() if k != "execution_key_sha256"})

    def test_wrong_granularity_owner_rank_scope_fail_closed(self):
        good = self.result("dense", self.rows[:1])
        for patch in ({"rank": 2}, {"granularity": "page"}, {"doc_id": "foreign"}):
            result = SearchResult((replace(good.candidates[0], **patch),), good.trace)
            out = self.run_arm("child_kure", lambda lane, limit: result)
            self.assertEqual(self.stages(out)["lane_dense"]["outcome"], "error")
        out = self.run_arm("child_kure", scope=ResolvedScope.from_allowed(frozenset({"foreign"}), origin="user_explicit"))
        self.assertEqual(self.stages(out)["lane_dense"]["outcome"], "error")

    def test_guard_drift_is_fatal_not_hidden_as_provider_error(self):
        calls = []
        def guard():
            calls.append(1)
            if len(calls) == 2:
                raise ValueError("guard_drift")
        with self.assertRaisesRegex(ValueError, "guard_drift"):
            self.run_arm(guard=guard)

    def test_bad_config_scope_identifiers_and_synthetic_child_production_rejected(self):
        bad = deepcopy(self.config)
        self.config["return_k"] = 9
        with self.assertRaises(ValueError): self.run_arm()
        self.config = bad
        with self.assertRaises(ValueError): self.run_arm(scope=ResolvedScope(origin="entity_resolution"))
        with self.assertRaises(ValueError):
            record_request(request=RuntimeRequest(question="q"), backend=object(), store=self.store, config=self.config,
                           run_id="raw question?", case_id="c", arm_id="child_kure")
        with self.assertRaises((ValueError, TypeError)):
            record_request(request=RuntimeRequest(question="q"), backend=HybridChildRetriever(self.store, object(), object()),
                           store=self.store, config=self.config, run_id="r", case_id="c", arm_id="child_kure")

    def test_query_policy_preserves_user_prefix_and_latest_four_turns(self):
        class Counter:
            def count(self, text): return len(text)
        req = RuntimeRequest(question="question", history=tuple({"role": "user", "content": str(i)} for i in range(6)))
        self.assertEqual(_retrieval_query(req.to_dict(), Counter(), max_tokens=8192),
                         "user: 2\nuser: 3\nuser: 4\nuser: 5\nuser: question")

    def test_record_connects_to_file_backed_source_resolver_and_scorer(self):
        from tests.test_stage_evaluation import StageEvaluationTests
        from midprojectrag.stage_evaluation import evaluate_records
        fixture = StageEvaluationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.store, self.rows = fixture.store, fixture.store.candidates()
        self.config = make_draft({key: self.store.bundle_sha256 if key == "evidence_store" else "a" * 64
                                  for key in ARTIFACT_KEYS})
        out = self.run_arm()
        qrel = dict(fixture.qrel, case_id="case-1")
        report = evaluate_records([qrel], [out["record"]], store=self.store, snapshot=fixture.snapshot)
        self.assertEqual(report["cases"][0]["metrics"]["pre_required_recall"]["value"], 1)
        self.assertEqual(report["cases"][0]["metrics"]["post_required_recall"]["value"], 1)
        self.assertFalse(report["semantic_answer_quality_measured"])


if __name__ == "__main__":
    unittest.main()
