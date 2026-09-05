from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from midprojectrag.evidence.artifacts import write_new_json
from midprojectrag.retrieval_readiness import audit_readiness, main
from midprojectrag.stage_checkpoints import canonical_sha
from tests import test_stage_inputs as fixtures
from tests.test_stage_document_qrels import sealed_inputs


class RetrievalReadinessTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.StageInputsTests()
        self.fixture.setUp()
        for case in self.fixture.cases:
            case.source.update(history=[], document_scope={"mode": "all", "doc_ids": []}, scope_doc_ids=[])
            self.fixture.refresh(case)
            case.request_template = None if case.lane in {"supplemental_set_rerun", "corpus_analytics"} else {
                "question": case.source["question"], "history": [], "document_scope": {"mode": "all", "doc_ids": []}}
        self.inventory, self.qrels, self.qrels_sha = sealed_inputs(self.fixture)
        self.suite = SimpleNamespace(cases=self.fixture.cases, ledger_rows=self.fixture.ledger,
            config={"sources": {k: {"sha256": v} for k, v in self.fixture.sources.items()}},
            config_sha256=fixtures.H, eval_set_sha256=fixtures.H, parser_receipt=self.fixture.parser)

    def audit(self):
        return audit_readiness(self.suite, self.inventory, self.qrels, snapshot=self.fixture.snapshot,
                               qrels_file_sha256=self.qrels_sha)

    def test_full_inventory_and_request_candidates_not_formal_pair(self):
        report = self.audit()
        self.assertEqual(report["summary"]["case_count"], 131)
        self.assertEqual(report["summary"]["request_status_counts"], {"available": 106, "unavailable": 23, "not_applicable": 2})
        self.assertEqual(report["summary"]["technical_candidate_counts"], {"source_anchor": 30, "document": 84})
        self.assertEqual(report["by_suite"]["set13"]["technical_candidate_counts"]["document"], 0)
        self.assertIsNone(report["formal_pair_count"])
        self.assertFalse(report["formal_comparison_authorized"])
        self.assertEqual(report["model_calls"], 0)

    def test_missing_set_request_never_filled_from_doc_gold(self):
        before = deepcopy(self.fixture.cases)
        report = self.audit()
        sets = [r for r in report["cases"] if r["suite"] == "set13"]
        self.assertTrue(all(r["document_qrel_status"] == "ready" for r in sets))
        self.assertTrue(all(r["request"]["reason"] == "runtime_request_missing" for r in sets))
        self.assertEqual(self.fixture.cases, before)

    def test_supported_request_fingerprint_not_query_hash_or_token_check(self):
        report = self.audit()
        request = report["cases"][0]["request"]
        self.assertEqual(len(request["fingerprint_sha256"]), 64)
        self.assertIsNone(request["actual_query_sha256"])
        self.assertEqual(request["query_token_budget"], "not_checked")
        self.assertEqual(report["index_runtime_validation"], "not_performed")
        self.assertNotIn("PRIVATE-", json.dumps(report))
        self.assertNotIn('"question"', json.dumps(report))

    def test_unsupported_options_invalid_request_and_unknown_scope(self):
        case = self.fixture.cases[0]
        original = deepcopy(case.request_template)
        for mutation, reason in (({"options": {"profile": "local"}}, "recorder_request_feature_not_supported"),
                                 ({"gold": "private"}, "invalid_original_runtime_request"),
                                 ({"document_scope": {"mode": "explicit", "doc_ids": ["doc_unknown"]}}, "source_request_mismatch")):
            case.request_template = original | mutation
            row = self.audit()["cases"][0]
            with self.subTest(reason=reason):
                self.assertEqual(row["request"]["reason"], reason)
                self.assertFalse(row["technical"]["document"]["candidate"])
                self.assertEqual(row["document_qrel_status"], "ready")

    def test_original_request_question_history_scope_and_missing_template_bound(self):
        case = self.fixture.cases[0]
        original = deepcopy(case.request_template)
        for change in ({"question": "different valid question"}, {"history": [{"role": "user", "content": "old"}]},
                       {"document_scope": {"mode": "explicit", "doc_ids": [fixtures.D]}}):
            case.request_template = original | change
            row = self.audit()["cases"][0]
            self.assertEqual(row["request"]["reason"], "source_request_mismatch")
            self.assertFalse(row["technical"]["document"]["candidate"])
        case.request_template = None
        self.assertEqual(self.audit()["cases"][0]["request"]["reason"], "runtime_request_missing")
        set_case = next(c for c in self.fixture.cases if c.lane == "supplemental_set_rerun")
        set_case.request_template = original
        row = next(r for r in self.audit()["cases"] if r["case_id"] == set_case.case_id)
        self.assertEqual(row["request"]["reason"], "source_request_mismatch")

    def test_original_unknown_scope_is_not_silently_intersected(self):
        case = self.fixture.cases[0]
        scope = {"mode": "explicit", "doc_ids": ["doc_unknown"]}
        case.source["document_scope"] = scope
        case.request_template["document_scope"] = deepcopy(scope)
        self.fixture.refresh(case)
        self.inventory, self.qrels, self.qrels_sha = sealed_inputs(self.fixture)
        row = self.audit()["cases"][0]
        self.assertEqual(row["request"]["reason"], "request_scope_outside_snapshot")
        self.assertFalse(row["technical"]["document"]["candidate"])

    def test_input_source_and_config_bindings_rejected_on_drift(self):
        self.suite.config_sha256 = "b" * 64
        with self.assertRaisesRegex(ValueError, "binding_mismatch"): self.audit()
        self.suite.config_sha256 = fixtures.H
        self.fixture.cases[0].source["question"] = "changed-private"
        with self.assertRaisesRegex(ValueError, "source_case_identity_mismatch"): self.audit()

    def test_source_review_approval_does_not_fabricate_formal_binding(self):
        self.fixture.cases[0].source["review"]["status"] = "approved"
        self.fixture.refresh(self.fixture.cases[0])
        self.inventory, self.qrels, self.qrels_sha = sealed_inputs(self.fixture)
        report = self.audit()
        self.assertEqual(report["cases"][0]["source_review_status"], "approved")
        self.assertEqual(report["cases"][0]["approval_binding"], "not_evaluated")
        self.assertFalse(report["formal_comparison_authorized"])
        self.assertEqual(report["report_sha256"], canonical_sha({k:v for k,v in report.items() if k != "report_sha256"}))

    def test_private_cli_exclusive_and_post_read_drift_rejected(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            inputs = root / "private/inputs"
            inputs.mkdir(parents=True)
            write_new_json(inputs / "inventory.json", self.inventory)
            (inputs / "qrels.jsonl").write_text("".join(json.dumps(q, sort_keys=True, separators=(",", ":")) + "\n" for q in self.qrels))
            target = root / "private/readiness.json"
            args = ["--repo-root", str(root), "--config", str(root / "config"), "--data-root", str(root),
                    "--bundle", str(root / "private/bundle"), "--manifest", str(root / "private/manifest"),
                    "--blocks-dir", str(root / "private/blocks"), "--inputs-dir", str(inputs), "--output", str(target)]
            with patch("midprojectrag.local_mini131_baseline.verify_suite", return_value=self.suite), \
                 patch("midprojectrag.retrieval_readiness.load_bundle", return_value=(SimpleNamespace(bundle_sha256=fixtures.H), {"input_hashes": {}})), \
                 patch("midprojectrag.retrieval_readiness.load_source_snapshot", return_value=self.fixture.snapshot):
                output = StringIO()
                with redirect_stdout(output): self.assertEqual(main(args), 0)
                self.assertEqual(target.stat().st_mode & 0o777, 0o600)
                self.assertNotIn("PRIVATE-", output.getvalue())
                self.assertNotIn(self.qrels[0]["case_id"], output.getvalue())
                with redirect_stdout(StringIO()): self.assertEqual(main(args), 2)
                drifted = deepcopy(self.suite)
                drifted.eval_set_sha256 = "b" * 64
                with patch("midprojectrag.local_mini131_baseline.verify_suite", side_effect=[self.suite, drifted]):
                    with redirect_stdout(StringIO()):
                        self.assertEqual(main(args[:-1] + [str(root / "private/rejected.json")]), 2)
                self.assertFalse((root / "private/rejected.json").exists())


if __name__ == "__main__":
    unittest.main()
