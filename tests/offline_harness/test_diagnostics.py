from __future__ import annotations

import ast
import json
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

from midprojectrag.evidence import Evidence, EvidenceStore
from midprojectrag.offline_harness.diagnostics import FrozenQrels, diagnose_harness_result
from midprojectrag.orchestration.types import Action, Event, HarnessResult, QueryPlan, Slot, Snapshot


def _fixture(count=3):
    records, children = [], []
    for index in range(count):
        page = Evidence.create(doc_id=f"doc_{index}", page=1, kind="page", text=f"synthetic private phrase {index}", source_block_ids=(f"block_{index}",))
        child = Evidence.create(doc_id=page.doc_id, page=1, kind="text", text=page.text, source_block_ids=page.source_block_ids, parent_id=page.evidence_id)
        records.extend((page, child))
        children.append(child)
    return EvidenceStore(records), tuple(children)


def _result(rows, *, events=(), context_indices=(0,), required_indices=(0,), candidate_indices=None, status="READY", reason="planned_support_retained"):
    plan = QueryPlan("synthetic question", (Slot("fact", "synthetic question"),))
    candidate_indices = range(len(rows)) if candidate_indices is None else candidate_indices
    required = tuple(rows[index].evidence_id for index in required_indices)
    state = Snapshot(plan, (("fact", required),) if required else (), () if required else ("fact",), tuple(rows[index].evidence_id for index in candidate_indices), (("fact", 1),), len(events), ())
    return HarnessResult(status, reason, tuple(rows[index] for index in context_indices), required, state, tuple(events), 1.0)


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.store, self.rows = _fixture()
        self.ids = tuple(row.evidence_id for row in self.rows)
        self.qrels = FrozenQrels(frozenset(self.ids), frozenset(row.doc_id for row in self.rows))

    def test_before_after_context_recall_and_stage_drop_attribution(self):
        events = (Event(Action("search", "fact", "query"), candidate_ids=self.ids[:2], pre_rerank_ids=self.ids),)
        result = _result(self.rows, events=events, candidate_indices=(0, 1))
        report = diagnose_harness_result(result, self.store, self.qrels)
        self.assertEqual(report.required_evidence_recall_before_rerank.value, 1)
        self.assertEqual(report.required_evidence_recall_after_rerank.value, 2 / 3)
        self.assertEqual(report.required_evidence_recall_after_context_selection.value, 1 / 3)
        self.assertEqual(report.required_dropped_by_rerank_ids, (self.ids[2],))
        self.assertEqual(report.required_available_not_in_context_ids, (self.ids[1],))
        self.assertEqual(report.required_never_observed_in_retrieval_ids, ())
        self.assertEqual(report.operational_verified_evidence_retention.value, 1)

    def test_iterative_aggregate_is_distinguished_from_per_search(self):
        events = tuple(Event(Action("search", "fact", f"query{index}"), candidate_ids=(value,), pre_rerank_ids=(value,)) for index, value in enumerate(self.ids))
        result = _result(self.rows, events=events)
        report = diagnose_harness_result(result, self.store, self.qrels)
        self.assertEqual(report.required_evidence_recall_before_rerank.value, 1)
        self.assertEqual([row.required_evidence_recall_before_rerank.value for row in report.per_search], [1 / 3] * 3)
        self.assertIn("iterative_first_seen_not_single_ranking", report.aggregation)
        self.assertEqual(report.iterative_first_seen_document_recall_at_k[0].before_rerank.value, 1)
        self.assertEqual(report.per_search[0].document_recall_at_k[0].before_rerank.value, 1 / 3)

    def test_bridge_recovery_not_credited_to_reranker(self):
        events = (
            Event(Action("search", "fact", "query"), candidate_ids=self.ids[:1], pre_rerank_ids=self.ids[:2]),
            Event(Action("bridge", "fact", evidence_id=self.rows[0].parent_id), candidate_ids=self.ids[:2]),
            Event(Action("verify", "fact"), candidate_ids=self.ids[:2], verified_ids=self.ids[:2]),
        )
        result = _result(self.rows, events=events, context_indices=(0, 1), required_indices=(0, 1), candidate_indices=(0, 1))
        report = diagnose_harness_result(result, self.store, self.qrels)
        self.assertEqual(report.required_evidence_recall_after_rerank.value, 1 / 3)
        self.assertEqual(report.required_evidence_recall_after_context_selection.value, 2 / 3)
        self.assertEqual(report.required_rerank_drops_recovered_by_bridge_ids, (self.ids[1],))
        self.assertEqual(report.required_never_observed_in_retrieval_ids, (self.ids[2],))

    def test_later_search_recovery_clears_aggregate_drop_not_event_drop(self):
        events = (
            Event(Action("search", "fact", "query1"), candidate_ids=self.ids[:1], pre_rerank_ids=self.ids[:2]),
            Event(Action("search", "fact", "query2"), candidate_ids=(self.ids[1],), pre_rerank_ids=(self.ids[1],)),
        )
        report = diagnose_harness_result(_result(self.rows, events=events), self.store, self.qrels)
        self.assertEqual(report.required_dropped_by_rerank_ids, ())
        self.assertEqual(report.per_search[0].required_dropped_by_rerank_ids, (self.ids[1],))

    def test_missing_labels_are_unavailable_not_zero(self):
        report = diagnose_harness_result(_result(self.rows), self.store, FrozenQrels())
        for metric in (report.required_evidence_recall_before_rerank, report.required_evidence_recall_after_context_selection, report.iterative_first_seen_document_recall_at_k[0].before_rerank):
            self.assertEqual(metric.status, "not_available")
            self.assertIsNone(metric.value)
            self.assertEqual(metric.reason, "qrels_missing")
        self.assertIsNone(report.required_never_observed_in_retrieval_ids)

    def test_empty_labels_have_undefined_recall(self):
        report = diagnose_harness_result(_result(self.rows), self.store, FrozenQrels(frozenset(), frozenset()))
        self.assertEqual(report.required_evidence_recall_before_rerank.reason, "qrels_empty_recall_undefined")

    def test_unknown_qrel_evidence_invalidates_metric_not_automatic_miss(self):
        qrels = FrozenQrels(frozenset({self.ids[0], "unknown"}), frozenset({self.rows[0].doc_id}))
        report = diagnose_harness_result(_result(self.rows), self.store, qrels)
        self.assertEqual(report.required_evidence_recall_after_context_selection.status, "not_available")
        self.assertEqual(report.required_evidence_recall_after_context_selection.reason, "qrel_mapping_incomplete")
        self.assertIsNone(report.required_dropped_by_rerank_ids)
        self.assertEqual(report.iterative_first_seen_document_recall_at_k[0].before_rerank.status, "available")

    def test_unknown_doc_labels_unavailable_independently(self):
        qrels = FrozenQrels(frozenset({self.ids[0]}), frozenset({"missing_doc"}))
        report = diagnose_harness_result(_result(self.rows), self.store, qrels)
        self.assertEqual(report.required_evidence_recall_after_context_selection.value, 1)
        self.assertEqual(report.iterative_first_seen_document_recall_at_k[0].after_rerank.reason, "qrel_mapping_incomplete")

    def test_operational_verified_retention_is_not_gold_recall(self):
        qrels = FrozenQrels(frozenset({self.ids[1]}))
        report = diagnose_harness_result(_result(self.rows), self.store, qrels)
        self.assertEqual(report.operational_verified_evidence_retention.value, 1)
        self.assertEqual(report.required_evidence_recall_after_context_selection.value, 0)

    def test_absent_verified_evidence_is_not_vacuous_perfect_retention(self):
        result = _result(self.rows, context_indices=(), required_indices=(), status="ABSTAINED", reason="insufficient_evidence")
        report = diagnose_harness_result(result, self.store, self.qrels)
        self.assertEqual(report.operational_verified_evidence_retention.reason, "no_runtime_verified_evidence")
        self.assertFalse(report.context_produced)
        self.assertTrue(report.generation_attribution.startswith("not_assessed"))

    def test_context_budget_abort_records_loss_without_claiming_generator_failure(self):
        result = _result(self.rows, context_indices=(), required_indices=(0, 1), status="ABSTAINED", reason="context_budget_exceeded")
        report = diagnose_harness_result(result, self.store, self.qrels)
        self.assertEqual(report.operational_verified_evidence_retention.value, 0)
        self.assertEqual(set(report.verified_not_in_context_ids), set(self.ids[:2]))
        self.assertTrue(report.generation_attribution.startswith("not_assessed"))

    def test_parent_child_identity_is_not_inferred_as_qrel_hit(self):
        parent_id = self.rows[0].parent_id
        qrels = FrozenQrels(frozenset({parent_id}))
        report = diagnose_harness_result(_result(self.rows), self.store, qrels)
        self.assertEqual(report.required_evidence_recall_after_context_selection.value, 0)

    def test_doc_at_k_counts_unique_docs_not_chunks(self):
        store, rows = _fixture(12)
        # Repeated same-document page/child evidence must not consume two ranks.
        ids = tuple(value for row in rows for value in (row.parent_id, row.evidence_id))
        event = Event(Action("search", "fact", "q"), candidate_ids=ids, pre_rerank_ids=ids)
        report = diagnose_harness_result(_result(rows, events=(event,)), store, FrozenQrels(required_doc_ids=frozenset(row.doc_id for row in rows)))
        metrics = report.per_search[0].document_recall_at_k
        self.assertEqual([item.k for item in metrics], [5, 10, 20, 50])
        self.assertEqual([item.before_rerank.value for item in metrics], [5 / 12, 10 / 12, 1, 1])

    def test_unknown_runtime_id_is_contract_error(self):
        event = Event(Action("search", "fact", "q"), candidate_ids=("unknown",))
        with self.assertRaisesRegex(ValueError, "unknown_runtime_evidence"):
            diagnose_harness_result(_result(self.rows, events=(event,)), self.store, self.qrels)

    def test_invalid_nested_runtime_ids_are_rejected_before_hashing(self):
        event = Event(Action("search", "fact", "q"), candidate_ids=([],))
        with self.assertRaisesRegex(ValueError, "invalid_runtime_evidence_ids"):
            diagnose_harness_result(_result(self.rows, events=(event,)), self.store, self.qrels)

    def test_malformed_context_and_state_are_explicit_contract_errors(self):
        result = _result(self.rows)
        for malformed, code in (
            (replace(result, context=({},)), "invalid_runtime_context"),
            (replace(result, state={}), "invalid_diagnostic_state"),
            (replace(result, events=(Event({}),)), "invalid_diagnostic_action"),
        ):
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, code):
                diagnose_harness_result(malformed, self.store, self.qrels)

    def test_rerank_invented_id_is_trace_error_not_retrieval_improvement(self):
        event = Event(Action("search", "fact", "q"), candidate_ids=self.ids[:2], pre_rerank_ids=self.ids[:1])
        with self.assertRaisesRegex(ValueError, "invalid_search_stage_evidence"):
            diagnose_harness_result(_result(self.rows, events=(event,)), self.store, self.qrels)

    def test_qrels_frozen_validation_and_deterministic_fingerprint(self):
        with self.assertRaises(FrozenInstanceError):
            self.qrels.required_evidence_ids = frozenset()
        for value in ({"a"}, frozenset({1}), "a"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                FrozenQrels(value)
        other = FrozenQrels(frozenset(reversed(self.ids)), self.qrels.required_doc_ids)
        self.assertEqual(other.fingerprint_sha256, self.qrels.fingerprint_sha256)

    def test_serialized_report_contains_no_document_or_question_text(self):
        report = diagnose_harness_result(_result(self.rows), self.store, self.qrels)
        serialized = json.dumps(report.to_dict())
        self.assertNotIn("synthetic private phrase", serialized)
        self.assertNotIn("synthetic question", serialized)

    def test_runtime_does_not_import_offline_qrel_package(self):
        root = Path(__file__).resolve().parents[2] / "src" / "midprojectrag" / "orchestration"
        for path in root.glob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                self.assertFalse(any("offline_harness" in name for name in names), path.name)


if __name__ == "__main__":
    unittest.main()
