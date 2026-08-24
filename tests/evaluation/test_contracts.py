from __future__ import annotations

import json
import copy
import unittest
from pathlib import Path
from urllib.parse import urldefrag, urljoin

from midprojectrag.evaluation import validate_case, validate_request, validate_response, validate_run_record
from tests.evaluation.helpers import make_case, make_response, make_runs


class ContractTests(unittest.TestCase):
    def test_all_json_schema_files_parse_and_are_closed_objects(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        paths = [
            project_root / "contracts" / "rag-request.schema.json",
            project_root / "contracts" / "rag-response.schema.json",
            project_root / "evaluation" / "schemas" / "eval-case.schema.json",
            project_root / "evaluation" / "schemas" / "run-record.schema.json",
        ]
        for path in paths:
            with self.subTest(path=path.name):
                schema = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
                self.assertEqual(schema["type"], "object")
                self.assertFalse(schema["additionalProperties"])

    def test_schema_registry_resolves_every_external_reference_offline(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        registry_path = project_root / "evaluation" / "schemas" / "registry.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        resources = registry["resources"]

        def refs(value: object) -> list[str]:
            if isinstance(value, dict):
                found = [value["$ref"]] if isinstance(value.get("$ref"), str) else []
                for child in value.values():
                    found.extend(refs(child))
                return found
            if isinstance(value, list):
                found: list[str] = []
                for child in value:
                    found.extend(refs(child))
                return found
            return []

        for schema_id, relative_path in resources.items():
            with self.subTest(schema_id=schema_id):
                schema_path = (registry_path.parent / relative_path).resolve()
                schema = json.loads(schema_path.read_text(encoding="utf-8"))
                self.assertEqual(schema["$id"], schema_id)
                for reference in refs(schema):
                    if reference.startswith("#"):
                        continue
                    resolved, _ = urldefrag(urljoin(schema_id, reference))
                    self.assertIn(resolved, resources)

    def test_valid_request_and_answered_response(self) -> None:
        case = make_case("single_doc")
        request = {
            "schema_version": "1.0",
            "request_id": "request-001",
            "question": case["question"],
            "history": [],
            "document_scope": {"mode": "explicit", "doc_ids": case["gold"]["required_doc_ids"]},
            "options": {"max_citations": 5},
        }
        self.assertEqual(validate_request(request), [])
        self.assertEqual(validate_response(make_response(case)), [])

    def test_answered_response_requires_citation(self) -> None:
        response = make_response(make_case("single_doc"))
        response["citations"] = []
        codes = {issue["code"] for issue in validate_response(response)}
        self.assertIn("answered_without_citation", codes)

    def test_abstention_is_not_runtime_error_and_cannot_cite(self) -> None:
        response = make_response(make_case("unknown"))
        response["citations"] = make_response(make_case("single_doc"))["citations"]
        response["error"] = {"code": "provider_error", "message": "synthetic"}
        codes = {issue["code"] for issue in validate_response(response)}
        self.assertIn("abstained_with_citation", codes)
        self.assertIn("abstained_with_error", codes)

    def test_abstention_cannot_add_a_factual_answer(self) -> None:
        response = make_response(make_case("unknown"))
        response["answer"] = "지원 예산은 1억 원입니다."
        codes = {issue["code"] for issue in validate_response(response)}
        self.assertIn("nonstandard_abstention_answer", codes)

    def test_manual_run_validator_matches_schema_uniqueness_and_total_timing(self) -> None:
        run = make_runs([make_case("single_doc")])[0]
        block_id = run["retrieval"][0]["source_block_ids"][0]
        run["retrieval"][0]["source_block_ids"] = [block_id, block_id]
        point_id = run["judgment"]["matched_key_point_ids"][0]
        run["judgment"]["matched_key_point_ids"] = [point_id, point_id]
        run["timing_ms"]["total"] = None
        codes = {issue["code"] for issue in validate_run_record(run)}
        self.assertIn("duplicate_source_block_id", codes)
        self.assertIn("duplicate_matched_key_point", codes)
        self.assertIn("invalid_total_timing", codes)

        run = make_runs([make_case("single_doc")])[0]
        run["judgment"]["reviewer_ids"] = ["r" * 129]
        self.assertIn("invalid_reviewer_ids", {issue["code"] for issue in validate_run_record(run)})

        local_run = make_runs([make_case("single_doc")], stack_id="gcp_local")[0]
        local_run["environment"]["gpu_model"] = "nvidia l4"
        self.assertIn("gcp_gpu_not_l4", {issue["code"] for issue in validate_run_record(local_run)})

    def test_unhashable_enum_values_return_issues_instead_of_crashing(self) -> None:
        case = make_case("single_doc")
        mutations = (
            ("difficulty", lambda value: value.__setitem__("difficulty", [])),
            ("task_type", lambda value: value.__setitem__("task_type", [])),
            ("review_status", lambda value: value["review"].__setitem__("status", [])),
            ("gold_decision", lambda value: value["gold"].__setitem__("decision", [])),
        )
        for label, mutate in mutations:
            with self.subTest(label=label):
                invalid = copy.deepcopy(case)
                mutate(invalid)
                self.assertTrue(validate_case(invalid))

        follow_up = make_case("follow_up")
        follow_up["conversation"]["depends_on_turn_ids"] = [[]]
        self.assertIn("invalid_id", {issue["code"] for issue in validate_case(follow_up)})

        response = make_response(case)
        response["status"] = []
        self.assertTrue(validate_response(response))
        abstention = make_response(make_case("unknown"))
        abstention["abstention"]["reason"] = []
        self.assertIn("invalid_abstention_reason", {issue["code"] for issue in validate_response(abstention)})
        run = make_runs([case])[0]
        run["stack_id"] = []
        run["generator_model"] = []
        self.assertTrue(validate_run_record(run))


if __name__ == "__main__":
    unittest.main()
