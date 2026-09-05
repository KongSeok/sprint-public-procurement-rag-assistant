"""Rank metrics end-to-end with original 131-case document inventory."""
from contextlib import redirect_stdout
from copy import deepcopy
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from midprojectrag.evidence.artifacts import write_new_json
from midprojectrag.evidence.builder import build_store
from midprojectrag.stage_checkpoints import SCHEMA, canonical_sha, make_checkpoint
from midprojectrag.stage_evaluation import SourceSnapshot, _json_object, _json_rows, evaluate_records, main
from tests import test_stage_inputs as fixtures
from tests.test_evidence_builder import chunk
from tests.test_stage_document_qrels import reseal, sealed_inputs


class RankingEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.StageInputsTests()
        self.fixture.setUp()
        self.other_doc = "doc_" + "b" * 24
        self.fixture.snapshot = SourceSnapshot(fixtures.H, fixtures.H,
            {(fixtures.D, fixtures.B): fixtures.H, (self.other_doc, "block-b"): fixtures.H},
            {"blocks_" + fixtures.D: fixtures.H, "blocks_" + self.other_doc: fixtures.H})
        self.fixture.cases[0].source["gold"]["required_doc_ids"].append(self.other_doc)
        self.fixture.refresh(self.fixture.cases[0])
        self.inventory, self.qrels, self.qrels_sha = sealed_inputs(self.fixture)
        self.store = build_store([chunk("synthetic", doc=fixtures.D, block=fixtures.B)])
        self.binding = dict.fromkeys(("query_sha256", "scope_sha256", "run_config_sha256", "execution_key_sha256"), fixtures.H)
        self.binding["evidence_store_sha256"] = self.store.bundle_sha256
        self.ids = [e.evidence_id for e in self.store.candidates()]

    def record(self, index=0, ids=None):
        cid = self.qrels[index]["case_id"]
        cp = make_checkpoint("lane_dense", self.ids if ids is None else ids, store=self.store,
                             binding=self.binding, stage_config_sha256=fixtures.H, source_receipt_sha256=fixtures.H)
        return {"schema_version": SCHEMA, "case_id": cid, "run_id": "run-" + cid,
                "binding": self.binding, "checkpoints": [cp]}

    def evaluate(self, records=None, **kwargs):
        return evaluate_records(self.qrels, [self.record()] if records is None else records,
            store=self.store, snapshot=self.fixture.snapshot, pre_context_stage="lane_dense", inventory_mode="mini131",
            input_inventory=kwargs.pop("input_inventory", self.inventory), qrels_file_sha256=self.qrels_sha, **kwargs)

    def test_original_doc_denominator_does_not_shrink_to_source_anchors(self):
        report = self.evaluate()
        case = report["cases"][0]
        metrics = case["metrics"]
        self.assertEqual(case["required_document_count"], 2)
        self.assertEqual(metrics["stage_rank"]["source_anchor"]["lane_dense"]["10"]["ndcg"]["value"], 1)
        self.assertAlmostEqual(metrics["stage_rank"]["document"]["lane_dense"]["10"]["ndcg"]["value"], .6131471927654584)
        self.assertEqual(metrics["stage_recall"]["lane_dense"]["10"]["value"], 1)
        self.assertFalse(report["formal_comparison_authorized"])
        self.assertEqual(report["model_calls"], 0)

    def test_block_missing_document_ready_and_full_131_aggregation(self):
        report = self.evaluate(records=[self.record(0), self.record(40)])
        case = report["cases"][40]
        self.assertEqual((case["qrel_status"], case["document_qrel_status"]), ("missing", "ready"))
        block = report["aggregate"]["stage_rank.source_anchor.lane_dense.10.rr"]
        doc = report["aggregate"]["stage_rank.document.lane_dense.10.rr"]
        self.assertEqual((block["total"], block["available"], block["unavailable"], block["not_applicable"]), (131, 1, 96, 34))
        self.assertEqual((doc["total"], doc["available"], doc["unavailable"], doc["not_applicable"]), (131, 2, 95, 34))
        self.assertEqual(doc["macro_mean"], 1)
        self.assertEqual(report["by_suite"]["parser2"]["stage_rank.document.lane_dense.10.ndcg"]["not_applicable"], 2)
        self.assertEqual(report["inventory"]["document_qrels_ready"], 97)

    def test_empty_zero_missing_null_and_absent_inventory_explicit(self):
        empty = self.evaluate(records=[self.record(ids=[])])["cases"][0]["metrics"]["stage_rank"]
        self.assertEqual(empty["document"]["lane_dense"]["5"]["ndcg"]["value"], 0)
        missing = self.evaluate(records=[])["aggregate"]["stage_rank.document.lane_dense.5.ndcg"]
        self.assertIsNone(missing["macro_mean"])
        absent = self.evaluate(input_inventory=None)
        metric = absent["cases"][0]["metrics"]["stage_rank"]["document"]["lane_dense"]["5"]["ndcg"]
        self.assertEqual((metric["value"], metric["reason"]), (None, "document_inventory_missing"))
        self.assertIsNone(absent["input_inventory_sha256"])

    def test_scoring_and_report_hashes_pin_rank_policy(self):
        report = self.evaluate()
        self.assertEqual(report["scoring_config_sha256"], canonical_sha(report["scoring_config"]))
        self.assertEqual(report["report_sha256"], canonical_sha({k: v for k, v in report.items() if k != "report_sha256"}))
        self.assertEqual(report["input_inventory_sha256"], self.inventory["inventory_sha256"])
        self.assertEqual(report["scoring_config"]["ranking"]["aggregate_reciprocal_rank"], "mrr")
        self.assertNotEqual(report["scoring_config_sha256"], self.evaluate(ks=(5,))["scoring_config_sha256"])
        self.assertNotIn("PRIVATE-", json.dumps(report))

    def test_strict_json_rejects_duplicate_keys_at_any_level(self):
        for raw in (b'{"case_id":"one","case_id":"two"}', b'{"nested":{"value":1,"value":2}}'):
            for parser in (_json_object, _json_rows):
                with self.subTest(parser=parser.__name__), self.assertRaisesRegex(ValueError, "duplicate_json_key"):
                    parser(raw)
        with self.assertRaises(ValueError): _json_object(b'[]')

    def test_inventory_mismatch_precedes_scoring(self):
        self.inventory["cases"][0]["required_doc_ids"].append("outside-snapshot")
        reseal(self.inventory, self.qrels)
        with self.assertRaisesRegex(ValueError, "invalid_targets"): self.evaluate()

    def test_private_cli_inventory_hashes_permissions_no_overwrite_or_leak(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            private = root / "private"
            private.mkdir()
            qrels = private / "qrels.jsonl"
            qrels.write_text("".join(json.dumps(q, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for q in self.qrels))
            inventory = private / "inventory.json"
            write_new_json(inventory, self.inventory)
            records = private / "records.jsonl"
            write_new_json(records, self.record())
            output = private / "scores.json"
            args = ["--data-root", str(root), "--bundle", str(private / "bundle"), "--manifest", str(private / "manifest"),
                    "--blocks-dir", str(private / "blocks"), "--qrels", str(qrels), "--records", str(records),
                    "--output", str(output), "--input-inventory", str(inventory), "--pre-context-stage", "lane_dense"]
            originals = {p: p.read_bytes() for p in (qrels, inventory, records)}
            with patch("midprojectrag.stage_evaluation.load_bundle", return_value=(self.store, {"input_hashes": {}})), \
                 patch("midprojectrag.stage_evaluation.load_source_snapshot", return_value=self.fixture.snapshot):
                stdout = StringIO()
                with redirect_stdout(stdout): self.assertEqual(main(args), 0)
                report = json.loads(output.read_text())
                self.assertEqual(report["input_file_sha256s"]["input_inventory"], sha256(originals[inventory]).hexdigest())
                self.assertEqual(output.stat().st_mode & 0o777, 0o600)
                self.assertEqual(report["case_count"], 131)
                self.assertNotIn(self.qrels[0]["case_id"], stdout.getvalue())
                self.assertNotIn("PRIVATE-", stdout.getvalue())
                with redirect_stdout(StringIO()): self.assertEqual(main(args), 2)
                bad = deepcopy(self.inventory)
                bad["input_config_sha256"] = "bad-private-sentinel"
                inventory.write_text(json.dumps(bad))
                args[args.index("--output") + 1] = str(private / "rejected.json")
                stdout = StringIO()
                with redirect_stdout(stdout): self.assertEqual(main(args), 2)
                self.assertNotIn("bad-private-sentinel", stdout.getvalue())
                self.assertFalse((private / "rejected.json").exists())
                self.assertEqual(qrels.read_bytes(), originals[qrels])
                self.assertEqual(records.read_bytes(), originals[records])


if __name__ == "__main__":
    unittest.main()
