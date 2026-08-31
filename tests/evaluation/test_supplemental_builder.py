from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from midprojectrag.supplemental_evaluation import (
    finalize_supplemental,
    prepare_supplemental,
    read_jsonl,
)
from tests.evaluation.supplemental_helpers import (
    create_preparation_fixture,
    write_jsonl,
)


class SupplementalBuilderTests(unittest.TestCase):
    def test_prepare_builds_exact_lanes_and_is_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = create_preparation_fixture(root)
            first = root / "first"
            second = root / "second"
            kwargs = {
                "source_path": fixture["source_path"],
                "disposition_path": fixture["disposition_path"],
                "overrides_path": fixture["overrides_path"],
                "legacy_csv_path": fixture["legacy_csv_path"],
                "manifest_path": fixture["manifest_path"],
                "blocks_dir": fixture["blocks_dir"],
                "expected_hashes": None,
            }
            first_report = prepare_supplemental(output_dir=first, **kwargs)
            second_report = prepare_supplemental(output_dir=second, **kwargs)

            self.assertTrue(first_report["passed"], first_report["errors"])
            self.assertEqual(first_report, second_report)
            self.assertEqual(first_report["counts"]["source"], 136)
            self.assertEqual(first_report["counts"]["answer_total"], 56)
            self.assertEqual(first_report["counts"]["qa_regression"], 44)
            self.assertEqual(first_report["counts"]["answer_alignment"], 12)
            self.assertEqual(first_report["counts"]["set_retrieval"], 13)
            self.assertEqual(first_report["counts"]["supplemental_total"], 69)
            self.assertEqual(first_report["counts"]["approved"], 0)
            self.assertEqual(first_report["evaluation_tier"], "provisional")
            self.assertFalse(first_report["official_gold_ready"])
            self.assertEqual(first_report["counts"]["legacy_source_references"], 69)
            self.assertEqual(first_report["counts"]["effective_mapped_references"], 75)

            generated = (
                "rag-56.draft.jsonl",
                "set-13.draft.jsonl",
                "evidence-review-queue.jsonl",
                "review-case-index.jsonl",
                "build-report.json",
            )
            for filename in generated:
                with self.subTest(filename=filename):
                    self.assertEqual(
                        (first / filename).read_bytes(),
                        (second / filename).read_bytes(),
                    )

            answers = read_jsonl(first / "rag-56.draft.jsonl")
            sets = read_jsonl(first / "set-13.draft.jsonl")
            queue = read_jsonl(first / "evidence-review-queue.jsonl")
            self.assertEqual(len(answers), 56)
            self.assertEqual(len(sets), 13)
            self.assertEqual(len(queue), 56)
            self.assertTrue(all(case["enabled"] is False for case in answers + sets))
            self.assertTrue(all(case["review"]["status"] == "draft" for case in answers + sets))
            self.assertTrue(all(item["candidates"] for item in queue))
            self.assertTrue(all(not item["blockers"] for item in queue))

            b14 = next(case for case in sets if case["legacy_id"] == "B14")
            self.assertEqual(b14["expected_count"], 7)
            self.assertEqual(len(b14["required_doc_ids"]), 7)
            normalized = next(case for case in answers if "legacy-difficulty:very_easy" in case["tags"])
            self.assertEqual(normalized["difficulty"], "easy")
            self.assertEqual(normalized["gold"]["required_fact_groups"][0][0].split()[0], "fact")
            c25 = next(case for case in answers if case["legacy_id"] == "C25")
            self.assertEqual(c25["gold"]["decision"], "source_conflict")
            self.assertEqual(len(c25["supporting_refs"]), 1)
            self.assertEqual(c25["supporting_refs"][0]["source_type"], "legacy_csv")
            self.assertNotIn("synthetic amount", json.dumps(c25["supporting_refs"]))

    def test_prepare_fails_closed_when_required_correction_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = create_preparation_fixture(root)
            overrides = json.loads(fixture["overrides_path"].read_text(encoding="utf-8"))
            del overrides["cases"]["G01"]
            fixture["overrides_path"].write_text(
                json.dumps(overrides, ensure_ascii=False), encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, r"required_correction_missing:G01"):
                prepare_supplemental(
                    source_path=fixture["source_path"],
                    disposition_path=fixture["disposition_path"],
                    overrides_path=fixture["overrides_path"],
                    legacy_csv_path=fixture["legacy_csv_path"],
                    manifest_path=fixture["manifest_path"],
                    blocks_dir=fixture["blocks_dir"],
                    expected_hashes=None,
                )

    def test_prepare_fails_closed_on_unmapped_source_sha(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = create_preparation_fixture(root)
            source_rows = read_jsonl(fixture["source_path"])
            source_rows[0]["source_document_ids"] = ["f" * 64]
            write_jsonl(fixture["source_path"], source_rows)

            with self.assertRaisesRegex(ValueError, "source_sha_unmapped"):
                prepare_supplemental(
                    source_path=fixture["source_path"],
                    disposition_path=fixture["disposition_path"],
                    overrides_path=fixture["overrides_path"],
                    legacy_csv_path=fixture["legacy_csv_path"],
                    manifest_path=fixture["manifest_path"],
                    blocks_dir=fixture["blocks_dir"],
                    expected_hashes=None,
                )

    def test_finalize_requires_named_independent_reviewer_and_stable_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = create_preparation_fixture(root)
            draft_dir = root / "draft"
            report = prepare_supplemental(
                source_path=fixture["source_path"],
                disposition_path=fixture["disposition_path"],
                overrides_path=fixture["overrides_path"],
                legacy_csv_path=fixture["legacy_csv_path"],
                manifest_path=fixture["manifest_path"],
                blocks_dir=fixture["blocks_dir"],
                output_dir=draft_dir,
                expected_hashes=None,
            )
            self.assertTrue(report["passed"], report["errors"])
            candidate = read_jsonl(draft_dir / "evidence-review-queue.jsonl")[0]
            decision = {
                "schema_version": "1.0",
                "case_id": candidate["case_id"],
                "case_sha256": candidate["case_sha256"],
                "reviewer": "fixture-human-reviewer",
                "reviewed_at": "2026-08-31T02:00:00Z",
                "decision": "approved",
                "answer_verified": True,
                "evidence_refs": [
                    {
                        key: candidate["candidates"][0][key]
                        for key in ("doc_id", "source_block_id", "page", "locator_hash")
                    }
                ],
                "absence_scope_doc_ids": [],
                "notes": None,
            }
            decisions_path = root / "decisions.jsonl"
            write_jsonl(decisions_path, [decision])
            finalized_dir = root / "finalized"
            final_report = finalize_supplemental(
                answer_draft_path=draft_dir / "rag-56.draft.jsonl",
                set_draft_path=draft_dir / "set-13.draft.jsonl",
                decisions_path=decisions_path,
                blocks_dir=fixture["blocks_dir"],
                manifest_path=fixture["manifest_path"],
                legacy_csv_path=fixture["legacy_csv_path"],
                output_dir=finalized_dir,
            )
            self.assertTrue(final_report["passed"], final_report["errors"])
            self.assertEqual(final_report["counts"]["approved_answer"], 1)
            self.assertEqual(final_report["counts"]["approved_set"], 0)
            self.assertEqual(final_report["counts"]["pending"], 68)
            approved = read_jsonl(finalized_dir / "rag-approved.jsonl")
            self.assertEqual(len(approved), 1)
            self.assertTrue(approved[0]["enabled"])
            self.assertEqual(approved[0]["review"]["status"], "approved")

            conflict = copy.deepcopy(decision)
            conflict["reviewer"] = "legacy-import"
            write_jsonl(decisions_path, [conflict])
            with self.assertRaisesRegex(ValueError, "reviewer_author_conflict"):
                finalize_supplemental(
                    answer_draft_path=draft_dir / "rag-56.draft.jsonl",
                    set_draft_path=draft_dir / "set-13.draft.jsonl",
                    decisions_path=decisions_path,
                    blocks_dir=fixture["blocks_dir"],
                    manifest_path=fixture["manifest_path"],
                    legacy_csv_path=fixture["legacy_csv_path"],
                )

            normalized_conflict = copy.deepcopy(decision)
            normalized_conflict["reviewer"] = "  LEGACY-IMPORT  "
            write_jsonl(decisions_path, [normalized_conflict])
            with self.assertRaisesRegex(ValueError, "reviewer_author_conflict"):
                finalize_supplemental(
                    answer_draft_path=draft_dir / "rag-56.draft.jsonl",
                    set_draft_path=draft_dir / "set-13.draft.jsonl",
                    decisions_path=decisions_path,
                    blocks_dir=fixture["blocks_dir"],
                    manifest_path=fixture["manifest_path"],
                    legacy_csv_path=fixture["legacy_csv_path"],
                )

            stale = copy.deepcopy(decision)
            stale["case_sha256"] = "f" * 64
            write_jsonl(decisions_path, [stale])
            with self.assertRaisesRegex(ValueError, "review_decision_case_hash_mismatch"):
                finalize_supplemental(
                    answer_draft_path=draft_dir / "rag-56.draft.jsonl",
                    set_draft_path=draft_dir / "set-13.draft.jsonl",
                    decisions_path=decisions_path,
                    blocks_dir=fixture["blocks_dir"],
                    manifest_path=fixture["manifest_path"],
                    legacy_csv_path=fixture["legacy_csv_path"],
                )

            invalid_date = copy.deepcopy(decision)
            invalid_date["reviewed_at"] = "not-a-date"
            write_jsonl(decisions_path, [invalid_date])
            with self.assertRaisesRegex(ValueError, "review_decision_invalid"):
                finalize_supplemental(
                    answer_draft_path=draft_dir / "rag-56.draft.jsonl",
                    set_draft_path=draft_dir / "set-13.draft.jsonl",
                    decisions_path=decisions_path,
                    blocks_dir=fixture["blocks_dir"],
                    manifest_path=fixture["manifest_path"],
                    legacy_csv_path=fixture["legacy_csv_path"],
                )

            blank_reviewer = copy.deepcopy(decision)
            blank_reviewer["reviewer"] = "   "
            write_jsonl(decisions_path, [blank_reviewer])
            with self.assertRaisesRegex(ValueError, "review_decision_invalid"):
                finalize_supplemental(
                    answer_draft_path=draft_dir / "rag-56.draft.jsonl",
                    set_draft_path=draft_dir / "set-13.draft.jsonl",
                    decisions_path=decisions_path,
                    blocks_dir=fixture["blocks_dir"],
                    manifest_path=fixture["manifest_path"],
                    legacy_csv_path=fixture["legacy_csv_path"],
                )

            space_separated_date = copy.deepcopy(decision)
            space_separated_date["reviewed_at"] = "2026-08-31 02:00:00+00:00"
            write_jsonl(decisions_path, [space_separated_date])
            with self.assertRaisesRegex(ValueError, "review_decision_invalid"):
                finalize_supplemental(
                    answer_draft_path=draft_dir / "rag-56.draft.jsonl",
                    set_draft_path=draft_dir / "set-13.draft.jsonl",
                    decisions_path=decisions_path,
                    blocks_dir=fixture["blocks_dir"],
                    manifest_path=fixture["manifest_path"],
                    legacy_csv_path=fixture["legacy_csv_path"],
                )

            unknown = copy.deepcopy(decision)
            unknown["case_id"] = "supplemental-qa-unknown"
            unknown["case_sha256"] = "e" * 64
            write_jsonl(decisions_path, [unknown])
            with self.assertRaisesRegex(ValueError, "review_decision_unknown_case"):
                finalize_supplemental(
                    answer_draft_path=draft_dir / "rag-56.draft.jsonl",
                    set_draft_path=draft_dir / "set-13.draft.jsonl",
                    decisions_path=decisions_path,
                    blocks_dir=fixture["blocks_dir"],
                    manifest_path=fixture["manifest_path"],
                    legacy_csv_path=fixture["legacy_csv_path"],
                )

            tampered_csv = root / "tampered.csv"
            tampered_csv.write_bytes(fixture["legacy_csv_path"].read_bytes() + b"\n")
            write_jsonl(decisions_path, [decision])
            with self.assertRaisesRegex(ValueError, "draft_supporting_ref_invalid"):
                finalize_supplemental(
                    answer_draft_path=draft_dir / "rag-56.draft.jsonl",
                    set_draft_path=draft_dir / "set-13.draft.jsonl",
                    decisions_path=decisions_path,
                    blocks_dir=fixture["blocks_dir"],
                    manifest_path=fixture["manifest_path"],
                    legacy_csv_path=tampered_csv,
                )

    def test_source_conflict_approval_requires_full_absence_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = create_preparation_fixture(root)
            draft_dir = root / "draft"
            report = prepare_supplemental(
                source_path=fixture["source_path"],
                disposition_path=fixture["disposition_path"],
                overrides_path=fixture["overrides_path"],
                legacy_csv_path=fixture["legacy_csv_path"],
                manifest_path=fixture["manifest_path"],
                blocks_dir=fixture["blocks_dir"],
                output_dir=draft_dir,
                expected_hashes=None,
            )
            self.assertTrue(report["passed"], report["errors"])
            cases = read_jsonl(draft_dir / "rag-56.draft.jsonl")
            queue = read_jsonl(draft_dir / "evidence-review-queue.jsonl")
            conflict_case = next(case for case in cases if case["legacy_id"] == "C25")
            conflict_queue = next(item for item in queue if item["legacy_id"] == "C25")
            candidate = conflict_queue["candidates"][0]
            decision = {
                "schema_version": "1.0",
                "case_id": conflict_case["case_id"],
                "case_sha256": conflict_queue["case_sha256"],
                "reviewer": "fixture-human-reviewer",
                "reviewed_at": "2026-08-31T02:00:00Z",
                "decision": "approved",
                "answer_verified": True,
                "evidence_refs": [
                    {
                        key: candidate[key]
                        for key in ("doc_id", "source_block_id", "page", "locator_hash")
                    }
                ],
                "absence_scope_doc_ids": list(conflict_case["required_doc_ids"]),
                "notes": None,
            }
            decisions_path = root / "decisions.jsonl"
            write_jsonl(decisions_path, [decision])
            final_report = finalize_supplemental(
                answer_draft_path=draft_dir / "rag-56.draft.jsonl",
                set_draft_path=draft_dir / "set-13.draft.jsonl",
                decisions_path=decisions_path,
                blocks_dir=fixture["blocks_dir"],
                manifest_path=fixture["manifest_path"],
                legacy_csv_path=fixture["legacy_csv_path"],
            )
            self.assertTrue(final_report["passed"], final_report["errors"])

            decision["absence_scope_doc_ids"] = []
            write_jsonl(decisions_path, [decision])
            with self.assertRaisesRegex(ValueError, "review_absence_scope_invalid"):
                finalize_supplemental(
                    answer_draft_path=draft_dir / "rag-56.draft.jsonl",
                    set_draft_path=draft_dir / "set-13.draft.jsonl",
                    decisions_path=decisions_path,
                    blocks_dir=fixture["blocks_dir"],
                    manifest_path=fixture["manifest_path"],
                    legacy_csv_path=fixture["legacy_csv_path"],
                )


if __name__ == "__main__":
    unittest.main()
