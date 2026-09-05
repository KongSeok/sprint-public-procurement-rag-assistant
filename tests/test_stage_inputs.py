"""Synthetic Mini131 input projection tests; no production questions or providers."""
from copy import deepcopy
from contextlib import redirect_stdout
from hashlib import sha256
import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from midprojectrag.evidence.builder import build_store
from midprojectrag.stage_checkpoints import canonical_sha
from midprojectrag.stage_evaluation import SourceSnapshot, _qrels, evaluate_records
from midprojectrag.stage_inputs import build_inputs, write_inputs, main
from tests.test_evidence_builder import chunk

D, B, H = "doc_" + "a" * 24, "block_" + "a" * 24, "a" * 64
ANCHOR = {"doc_id": D, "source_block_id": B, "locator_hash": H}
SOURCE_KEYS = ("core40", "supplemental_answers", "supplemental_sets", "visual",
               "analytics", "analytics_calculations", "integrated_ledger", "parser_receipt")


class StageInputsTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = SourceSnapshot(H, H, {(D, B): H}, {"blocks_" + D: H})
        self.cases, self.ledger = [], {}
        self.sources = dict.fromkeys(SOURCE_KEYS, H)
        self.parser = {"artifacts": {"manifest_sha256": H}}
        for lane, count in (("core40", 40), ("supplemental_answer_legacy", 39),
                            ("supplemental_answer_rerun", 17), ("supplemental_set_rerun", 13),
                            ("visual", 10), ("corpus_analytics", 10)):
            for i in range(count):
                cid = f"{lane}-{i}"
                decision = "answer"
                if (lane == "core40" and i >= 30) or (lane == "supplemental_answer_rerun" and i >= 15):
                    decision = "abstain"
                if lane == "supplemental_answer_legacy" and i == 38:
                    decision = "source_conflict"
                row = {"case_id": cid, "question": "PRIVATE-QUESTION", "source_manifest_sha256": H,
                       "review": {"status": "draft", "reviewer": "PRIVATE-REVIEWER"},
                       "gold": {"decision": decision, "reference_answer": "PRIVATE-ANSWER"},
                       "required_doc_ids": [D]}
                if lane == "core40":
                    row["gold"]["evidence_refs"] = [deepcopy(ANCHOR)] if decision == "answer" else []
                    row["gold"]["required_doc_ids"] = [D] if decision == "answer" else []
                elif lane.startswith("supplemental_answer"):
                    row["evidence_refs"] = []
                elif lane == "corpus_analytics":
                    row.pop("source_manifest_sha256")
                    row["calculation_contract"] = {"manifest_sha256": H}
                self.cases.append(SimpleNamespace(case_id=cid, lane=lane, source=row,
                                                  source_sha256=canonical_sha(row)))
                self.ledger[cid] = {"case_id": cid, "lane": lane, "case_type": "rag"}
        for i in range(2):
            cid = f"parser-{i}"
            self.ledger[cid] = {"case_id": cid, "lane": "parser_regression", "case_type": "parser"}

    def build(self):
        return build_inputs(self.cases, self.ledger, self.snapshot, self.sources, self.parser)

    def refresh(self, case):
        case.source_sha256 = canonical_sha(case.source)

    def test_complete_inventory_and_source_block_availability(self):
        result = self.build()
        self.assertEqual(result["case_count"], 131)
        self.assertEqual(result["qrel_counts"], {"ready": 30, "missing": 67, "not_applicable": 34})
        self.assertEqual(len(result["qrels"]), len(result["cases"]))
        for row in result["qrels"]:
            _qrels(row, self.snapshot)
        self.assertTrue(all(r["semantic_approval"] == "not_assessed_by_adapter" for r in result["cases"]))

    def test_gold_and_review_text_never_copied_or_input_mutated(self):
        before = deepcopy(self.cases)
        output = json.dumps(self.build())
        self.assertNotIn("PRIVATE-", output)
        self.assertEqual(self.cases, before)
        self.assertEqual(self.build()["cases"][0]["source_review_sha256"],
                         canonical_sha(self.cases[0].source["review"]))

    def test_missing_case_and_ledger_mismatch_rejected(self):
        self.cases.pop()
        with self.assertRaises(ValueError): self.build()

    def test_duplicate_case_rejected(self):
        self.cases[-1] = self.cases[0]
        with self.assertRaises(ValueError): self.build()

    def test_lane_mismatch_rejected(self):
        self.ledger[self.cases[0].case_id]["lane"] = "visual"
        with self.assertRaises(ValueError): self.build()

    def test_source_row_hash_drift_rejected(self):
        self.cases[0].source["question"] = "CHANGED"
        with self.assertRaisesRegex(ValueError, "source_case_identity"): self.build()

    def test_manifest_mismatch_rejected(self):
        case = self.cases[0]
        case.source["source_manifest_sha256"] = "b" * 64
        self.refresh(case)
        with self.assertRaisesRegex(ValueError, "manifest"): self.build()

    def test_parser_manifest_mismatch_rejected(self):
        self.parser["artifacts"]["manifest_sha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "manifest"): self.build()

    def test_partial_anchor_resolution_is_not_reduced_gold(self):
        case = self.cases[0]
        case.source["gold"]["evidence_refs"].append({**ANCHOR, "source_block_id": "other-block"})
        self.refresh(case)
        output = self.build()
        self.assertEqual(output["qrels"][0]["qrel_status"], "missing")
        self.assertEqual(output["qrels"][0]["required_anchors"], [])
        self.assertEqual(output["cases"][0]["reason"], "qrel_source_anchor_unresolved")

    def test_candidate_refs_not_promoted_and_conflict_needs_positive_refs(self):
        case = self.cases[40]
        case.source["supporting_refs"] = [deepcopy(ANCHOR)]
        self.refresh(case)
        result = self.build()
        self.assertEqual(result["qrels"][40]["qrel_status"], "missing")
        self.assertEqual(result["qrels"][78]["qrel_status"], "missing")

    def test_unknown_decision_rejected(self):
        case = self.cases[0]
        case.source["gold"]["decision"] = "maybe"
        self.refresh(case)
        with self.assertRaises(ValueError): self.build()

    def test_nested_analytics_manifest_and_no_implicit_approval(self):
        case = self.cases[-1]
        case.source["review"]["status"] = "approved"
        self.refresh(case)
        result = self.build()["cases"][-3]
        self.assertEqual(result["source_manifest_status"], "matched")
        self.assertEqual(result["source_review_status"], "approved")
        self.assertEqual(result["semantic_approval"], "not_assessed_by_adapter")

    def test_private_write_hashes_permissions_and_no_overwrite(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "private").mkdir()
            target = root / "private" / "new-inputs"
            result = write_inputs(self.build(), output_dir=target, data_root=root)
            raw = (target / "qrels.jsonl").read_bytes()
            self.assertEqual(len(raw.splitlines()), 131)
            inventory = json.loads((target / "inventory.json").read_text())
            self.assertEqual(result["qrels_file_sha256"], sha256(raw).hexdigest())
            self.assertEqual(inventory["qrels_file_sha256"], result["qrels_file_sha256"])
            for name in ("qrels.jsonl", "inventory.json"):
                self.assertEqual((target / name).stat().st_mode & 0o777, 0o600)
            with self.assertRaises((ValueError, FileExistsError)):
                write_inputs(self.build(), output_dir=target, data_root=root)
            self.assertEqual((target / "qrels.jsonl").read_bytes(), raw)
            with self.assertRaises(ValueError):
                write_inputs(self.build(), output_dir=root / "public", data_root=root)

    def test_generated_qrels_connect_to_existing_evaluator_with_131_denominator(self):
        store = build_store([chunk("synthetic", block=B, doc=D)])
        report = evaluate_records(self.build()["qrels"], [], store=store, snapshot=self.snapshot, inventory_mode="mini131")
        self.assertEqual(report["case_count"], 131)
        metric = report["aggregate"]["pre_required_recall"]
        self.assertEqual((metric["available"], metric["unavailable"], metric["not_applicable"]), (0, 97, 34))
        self.assertIsNone(metric["macro_mean"])

    def test_cli_projects_verified_sources_and_sanitizes_failure(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "private").mkdir()
            suite = SimpleNamespace(cases=self.cases, ledger_rows=self.ledger,
                                    config={"sources": {k: {"sha256": v} for k, v in self.sources.items()}},
                                    parser_receipt=self.parser, config_sha256=H)
            args = ["--repo-root", str(root), "--config", str(root / "config"), "--data-root", str(root),
                    "--bundle", str(root / "private/bundle"), "--manifest", str(root / "private/manifest"),
                    "--blocks-dir", str(root / "private/blocks"), "--output-dir", str(root / "private/out")]
            with patch("midprojectrag.local_mini131_baseline.verify_suite", return_value=suite), \
                 patch("midprojectrag.stage_inputs.load_bundle", return_value=(None, {"input_hashes": {}})), \
                 patch("midprojectrag.stage_inputs.load_source_snapshot", return_value=self.snapshot):
                output = StringIO()
                with redirect_stdout(output): self.assertEqual(main(args), 0)
                self.assertEqual(json.loads(output.getvalue())["case_count"], 131)
                self.assertNotIn("PRIVATE-", output.getvalue())
                with redirect_stdout(StringIO()): self.assertEqual(main(args), 2)
            args[-1] = str(root / "private/another")
            with patch("midprojectrag.local_mini131_baseline.verify_suite", side_effect=ValueError("PRIVATE-ERROR")):
                output = StringIO()
                with redirect_stdout(output): self.assertEqual(main(args), 2)
                self.assertNotIn("PRIVATE-ERROR", output.getvalue())
                self.assertFalse((root / "private/another").exists())
