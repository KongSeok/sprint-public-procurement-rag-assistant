from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from midprojectrag.supplemental_evaluation import validate_supplemental_cases
from tests.evaluation.supplemental_helpers import (
    SHA_A,
    block_id,
    doc_id,
    make_answer_case,
    make_answer_run,
    make_draft_suites,
    make_set_case,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = PROJECT_ROOT / "evaluation" / "schemas"
SCHEMA_FILES = {
    "answer": "supplemental-answer-case.schema.json",
    "answer_run": "supplemental-answer-run.schema.json",
    "set": "set-retrieval-case.schema.json",
    "run": "set-retrieval-run.schema.json",
    "decision": "gold-review-decision.schema.json",
}


def validator(name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMA_DIR / SCHEMA_FILES[name]).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


class SupplementalContractTests(unittest.TestCase):
    def test_registry_contains_all_supplemental_schemas_and_resolves_locally(self) -> None:
        registry = json.loads((SCHEMA_DIR / "registry.json").read_text(encoding="utf-8"))
        resources = registry["resources"]
        for filename in SCHEMA_FILES.values():
            with self.subTest(filename=filename):
                path = SCHEMA_DIR / filename
                schema = json.loads(path.read_text(encoding="utf-8"))
                self.assertIn(schema["$id"], resources)
                self.assertEqual((SCHEMA_DIR / resources[schema["$id"]]).resolve(), path.resolve())

    def test_valid_synthetic_values_match_every_new_schema(self) -> None:
        answer = make_answer_case(0)
        set_case = make_set_case(0)
        run = {
            "schema_version": "1.0",
            "case_id": set_case["case_id"],
            "eval_set_sha256": SHA_A,
            "returned_doc_ids": list(set_case["required_doc_ids"]),
            "error": None,
        }
        answer_run = make_answer_run(answer)
        answer_run["eval_set_sha256"] = SHA_A
        decision = {
            "schema_version": "1.0",
            "case_id": answer["case_id"],
            "case_sha256": SHA_A,
            "reviewer": "fixture-reviewer",
            "reviewed_at": "2026-08-31T01:00:00Z",
            "decision": "approved",
            "answer_verified": True,
            "evidence_refs": [
                {
                    "doc_id": doc_id(1),
                    "source_block_id": block_id(1),
                    "page": 1,
                    "locator_hash": SHA_A,
                }
            ],
            "absence_scope_doc_ids": [],
            "notes": None,
        }
        for name, value in (
            ("answer", answer),
            ("answer_run", answer_run),
            ("set", set_case),
            ("run", run),
            ("decision", decision),
        ):
            with self.subTest(schema=name):
                self.assertEqual(list(validator(name).iter_errors(value)), [])

    def test_new_schemas_are_closed_and_reject_bad_identity_or_timestamp(self) -> None:
        values = {
            "answer": make_answer_case(0),
            "set": make_set_case(0),
            "run": {
                "schema_version": "1.0",
                "case_id": "supplemental-set-s000",
                "eval_set_sha256": SHA_A,
                "returned_doc_ids": [doc_id(1)],
                "error": None,
            },
            "answer_run": {
                **make_answer_run(make_answer_case(0)),
                "eval_set_sha256": SHA_A,
            },
            "decision": {
                "schema_version": "1.0",
                "case_id": "supplemental-qa-x000",
                "case_sha256": SHA_A,
                "reviewer": "fixture-reviewer",
                "reviewed_at": "2026-08-31T01:00:00Z",
                "decision": "approved",
                "answer_verified": True,
                "evidence_refs": [],
                "absence_scope_doc_ids": [],
                "notes": None,
            },
        }
        for name, value in values.items():
            with self.subTest(schema=name):
                invalid = copy.deepcopy(value)
                invalid["private_payload"] = "must not be accepted"
                self.assertTrue(list(validator(name).iter_errors(invalid)))

        decision_schema = json.loads(
            (SCHEMA_DIR / SCHEMA_FILES["decision"]).read_text(encoding="utf-8")
        )
        self.assertEqual(
            decision_schema["properties"]["reviewed_at"]["format"], "date-time"
        )
        invalid_decision = copy.deepcopy(values["decision"])
        invalid_decision["reviewed_at"] = None
        self.assertTrue(list(validator("decision").iter_errors(invalid_decision)))
        blank_reviewer = copy.deepcopy(values["decision"])
        blank_reviewer["reviewer"] = "   "
        self.assertTrue(list(validator("decision").iter_errors(blank_reviewer)))
        non_rfc3339 = copy.deepcopy(values["decision"])
        non_rfc3339["reviewed_at"] = "2026-08-31 01:00:00+00:00"
        self.assertTrue(list(validator("decision").iter_errors(non_rfc3339)))

        invalid_run = copy.deepcopy(values["run"])
        invalid_run["returned_doc_ids"] = ["not-a-doc-id"]
        self.assertTrue(list(validator("run").iter_errors(invalid_run)))

        invalid_answer_run = copy.deepcopy(values["answer_run"])
        invalid_answer_run["status"] = "error"
        invalid_answer_run["answer"] = "must be empty"
        invalid_answer_run["error"] = None
        self.assertTrue(
            list(validator("answer_run").iter_errors(invalid_answer_run))
        )

    def test_manual_contract_fails_closed_for_unapproved_or_bad_approval_state(self) -> None:
        answers, sets = make_draft_suites()
        self.assertEqual(validate_supplemental_cases(answers, sets), [])

        require_approved = validate_supplemental_cases(
            answers, sets, require_approved=True
        )
        self.assertEqual(
            sum(issue["code"] == "case_not_approved" for issue in require_approved),
            69,
        )

        enabled_draft_answers = copy.deepcopy(answers)
        enabled_draft_answers[0]["enabled"] = True
        codes = {
            issue["code"]
            for issue in validate_supplemental_cases(enabled_draft_answers, sets)
        }
        self.assertIn("unapproved_case_enabled", codes)

        invalid_approval_answers = copy.deepcopy(answers)
        first = invalid_approval_answers[0]
        first["review"].update(
            {
                "status": "approved",
                "reviewer": first["review"]["author"],
                "reviewed_at": "2026-08-31T01:00:00Z",
            }
        )
        first["enabled"] = True
        approval_codes = {
            issue["code"]
            for issue in validate_supplemental_cases(invalid_approval_answers, sets)
        }
        self.assertIn("approval_metadata_invalid", approval_codes)
        self.assertIn("approved_evidence_coverage_missing", approval_codes)

        invalid_rejection_answers = copy.deepcopy(answers)
        rejected = invalid_rejection_answers[0]
        rejected["review"].update(
            {"status": "rejected", "reviewer": 123, "reviewed_at": "not-a-date"}
        )
        rejection_codes = {
            issue["code"]
            for issue in validate_supplemental_cases(invalid_rejection_answers, sets)
        }
        self.assertIn("rejection_metadata_invalid", rejection_codes)

    def test_expected_count_and_duplicate_targets_fail_closed(self) -> None:
        answers, sets = make_draft_suites()
        sets[0]["required_doc_ids"].append(sets[0]["required_doc_ids"][0])
        sets[0]["expected_count"] = 99
        codes = {
            issue["code"] for issue in validate_supplemental_cases(answers, sets)
        }
        self.assertIn("set_case_contract_invalid", codes)


if __name__ == "__main__":
    unittest.main()
