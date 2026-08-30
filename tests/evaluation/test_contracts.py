from __future__ import annotations

import json
import copy
import unittest
from pathlib import Path
from urllib.parse import urldefrag, urljoin

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from midprojectrag.evaluation import validate_case, validate_request, validate_response, validate_run_record
from tests.evaluation.helpers import make_case, make_response, make_runs


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_schema(relative_path: str) -> dict[str, object]:
    return json.loads((PROJECT_ROOT / relative_path).read_text(encoding="utf-8"))


def _validator(relative_path: str) -> Draft202012Validator:
    schema = _load_schema(relative_path)
    response_schema = _load_schema("contracts/rag-response.schema.json")
    registry = Registry().with_resource(
        response_schema["$id"], Resource.from_contents(response_schema)
    )
    return Draft202012Validator(schema, registry=registry)


class ContractTests(unittest.TestCase):
    def assertManualSchemaParity(
        self,
        value: dict[str, object],
        manual_validator: object,
        schema_validator: Draft202012Validator,
    ) -> None:
        manual_errors = manual_validator(copy.deepcopy(value))
        schema_errors = list(schema_validator.iter_errors(value))
        self.assertEqual(
            bool(manual_errors),
            bool(schema_errors),
            {"manual": manual_errors, "schema": [error.message for error in schema_errors]},
        )

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

    def test_visual_response_and_run_preserve_occurrence_locator_contract(self) -> None:
        case = make_case("single_doc")
        doc_id = case["gold"]["required_doc_ids"][0]
        visual_citation = {
            "doc_id": doc_id,
            "chunk_id": "vchunk_" + "1" * 24,
            "occurrence_id": "vocc2_" + "2" * 24,
            "evidence_ids": ["ocr_" + "3" * 24],
            "evidence_type": "ocr",
            "locator": {
                "page": 7,
                "bbox": {"x": 1.0, "y": 2.0, "w": 3.0, "h": 4.0},
                "crop_sha256": "4" * 64,
            },
        }
        response = make_response(case)
        response["citations"] = [visual_citation]
        self.assertEqual(validate_response(response), [])

        run = make_runs([case])[0]
        run["retrieval"] = [
            {
                "rank": 1,
                "doc_id": doc_id,
                "chunk_id": visual_citation["chunk_id"],
                "score": 0.01,
                "occurrence_id": visual_citation["occurrence_id"],
                "evidence_ids": visual_citation["evidence_ids"],
                "evidence_type": "ocr",
                "page": 7,
                "bbox": visual_citation["locator"]["bbox"],
                "crop_sha256": visual_citation["locator"]["crop_sha256"],
                "lane": "visual",
                "lane_rank": 1,
                "dense_score": 0.9,
            }
        ]
        run["response"] = response
        self.assertEqual(validate_run_record(run), [])

        response["citations"][0]["locator"]["bbox"]["w"] = 0
        self.assertIn(
            "invalid_visual_bbox",
            {issue["code"] for issue in validate_response(response)},
        )

    def test_visual_gold_refs_are_closed_and_enforce_evidence_identity_prefix(self) -> None:
        case = make_case("single_doc")
        case["gold"]["evidence_refs"] = [
            {
                "doc_id": case["gold"]["required_doc_ids"][0],
                "occurrence_id": "vocc2_" + "2" * 24,
                "evidence_ids": ["ocr_" + "3" * 24],
                "evidence_type": "layout",
            }
        ]
        case_validator = _validator("evaluation/schemas/eval-case.schema.json")
        self.assertManualSchemaParity(case, validate_case, case_validator)
        self.assertEqual(validate_case(case), [])

        invalid = copy.deepcopy(case)
        invalid["gold"]["evidence_refs"][0]["evidence_ids"] = ["cap_" + "3" * 24]
        self.assertManualSchemaParity(invalid, validate_case, case_validator)
        self.assertIn(
            "visual_evidence_prefix_mismatch",
            {issue["code"] for issue in validate_case(invalid)},
        )

        unknown = copy.deepcopy(case)
        unknown["gold"]["evidence_refs"][0]["private_note"] = "not allowed"
        self.assertManualSchemaParity(unknown, validate_case, case_validator)

    def test_run_schema_and_manual_validator_match_dependent_and_stack_fields(self) -> None:
        run_validator = _validator("evaluation/schemas/run-record.schema.json")
        local_run = make_runs([make_case("single_doc")], stack_id="gcp_local")[0]
        self.assertManualSchemaParity(local_run, validate_run_record, run_validator)

        api_only_values = {
            "api_profile": "assignment",
            "embedding_dimensions": 1536,
            "index_config_sha256": "e" * 64,
            "reasoning_effort": "minimal",
        }
        for field, field_value in api_only_values.items():
            with self.subTest(field=field):
                invalid = copy.deepcopy(local_run)
                invalid[field] = field_value
                self.assertManualSchemaParity(invalid, validate_run_record, run_validator)
                self.assertIn(
                    "api_only_field_forbidden",
                    {issue["code"] for issue in validate_run_record(invalid)},
                )

        fused = make_runs([make_case("single_doc")])[0]
        fused["retrieval"][0].update(
            {"lane": "text", "lane_rank": 1, "dense_score": 0.9}
        )
        self.assertManualSchemaParity(fused, validate_run_record, run_validator)
        for field in ("lane", "lane_rank", "dense_score"):
            with self.subTest(missing_fusion_field=field):
                invalid = copy.deepcopy(fused)
                del invalid["retrieval"][0][field]
                self.assertManualSchemaParity(invalid, validate_run_record, run_validator)
                self.assertIn(
                    "incomplete_fusion_metadata",
                    {issue["code"] for issue in validate_run_record(invalid)},
                )

    def test_visual_response_and_run_schema_match_evidence_type_prefix(self) -> None:
        case = make_case("single_doc")
        doc_id = case["gold"]["required_doc_ids"][0]
        visual_citation = {
            "doc_id": doc_id,
            "chunk_id": "vchunk_" + "1" * 24,
            "occurrence_id": "vocc2_" + "2" * 24,
            "evidence_ids": ["cap_" + "3" * 24],
            "evidence_type": "caption",
            "locator": {
                "page": 7,
                "bbox": {"x": 1.0, "y": 2.0, "w": 3.0, "h": 4.0},
                "crop_sha256": "4" * 64,
            },
        }
        response = make_response(case)
        response["citations"] = [visual_citation]
        response_validator = _validator("contracts/rag-response.schema.json")
        self.assertManualSchemaParity(response, validate_response, response_validator)

        run = make_runs([case])[0]
        run["retrieval"] = [
            {
                "rank": 1,
                "doc_id": doc_id,
                "chunk_id": visual_citation["chunk_id"],
                "score": 0.9,
                "occurrence_id": visual_citation["occurrence_id"],
                "evidence_ids": visual_citation["evidence_ids"],
                "evidence_type": "caption",
                "page": 7,
                "bbox": visual_citation["locator"]["bbox"],
                "crop_sha256": visual_citation["locator"]["crop_sha256"],
                "lane": "visual",
                "lane_rank": 1,
                "dense_score": 0.9,
            }
        ]
        run["response"] = response
        run_validator = _validator("evaluation/schemas/run-record.schema.json")
        self.assertManualSchemaParity(run, validate_run_record, run_validator)
        for field in ("lane", "lane_rank", "dense_score"):
            with self.subTest(visual_missing_fusion_field=field):
                invalid_fusion = copy.deepcopy(run)
                del invalid_fusion["retrieval"][0][field]
                self.assertManualSchemaParity(
                    invalid_fusion, validate_run_record, run_validator
                )

        invalid_response = copy.deepcopy(response)
        invalid_response["citations"][0]["evidence_ids"] = ["ocr_" + "3" * 24]
        self.assertManualSchemaParity(
            invalid_response, validate_response, response_validator
        )
        self.assertIn(
            "visual_evidence_prefix_mismatch",
            {issue["code"] for issue in validate_response(invalid_response)},
        )

        invalid_run = copy.deepcopy(run)
        invalid_run["retrieval"][0]["evidence_ids"] = ["ocr_" + "3" * 24]
        self.assertManualSchemaParity(invalid_run, validate_run_record, run_validator)

    def test_answered_response_requires_citation(self) -> None:
        response = make_response(make_case("single_doc"))
        response["citations"] = []
        codes = {issue["code"] for issue in validate_response(response)}
        self.assertIn("answered_without_citation", codes)

    def test_table_citation_requires_structure_locator_when_page_is_unknown(self) -> None:
        response = make_response(make_case("single_doc"))
        locator = response["citations"][0]["locator"]
        locator.update(
            {
                "page_start": None,
                "page_end": None,
                "source_locator": "section:2/paragraph:7/table:1",
            }
        )
        self.assertEqual(validate_response(response), [])

        del locator["source_locator"]
        self.assertIn(
            "missing_source_locator",
            {issue["code"] for issue in validate_response(response)},
        )

    def test_citation_rejects_partial_page_range_and_invalid_structure_locator(self) -> None:
        response = make_response(make_case("single_doc"))
        locator = response["citations"][0]["locator"]
        locator.update(
            {
                "page_start": None,
                "page_end": 2,
                "source_locator": "section:2/paragraph:7/table:1",
            }
        )
        self.assertIn(
            "incomplete_page_range",
            {issue["code"] for issue in validate_response(response)},
        )

        locator.update({"page_end": None, "source_locator": "   "})
        self.assertIn(
            "invalid_source_locator",
            {issue["code"] for issue in validate_response(response)},
        )

    def test_legacy_page_citation_shape_remains_valid(self) -> None:
        response = make_response(make_case("single_doc"))
        original_locator = copy.deepcopy(response["citations"][0]["locator"])
        self.assertEqual(validate_response(response), [])
        self.assertEqual(response["citations"][0]["locator"], original_locator)

        project_root = Path(__file__).resolve().parents[2]
        schema = json.loads(
            (project_root / "contracts" / "rag-response.schema.json").read_text(
                encoding="utf-8"
            )
        )
        locator_schema = schema["$defs"]["locator"]
        self.assertIn("source_locator", locator_schema["properties"])
        self.assertFalse(locator_schema["additionalProperties"])

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

    def test_gcp_environment_contract_records_exact_allocation_and_200gb_hard_limit(self) -> None:
        local_run = make_runs([make_case("single_doc")], stack_id="gcp_local")[0]
        self.assertEqual(validate_run_record(local_run), [])

        local_run["environment"]["disk_gb"] = 150.0
        self.assertNotIn("gcp_disk_limit_exceeded", {issue["code"] for issue in validate_run_record(local_run)})
        local_run["environment"]["disk_gb"] = 200.1
        self.assertIn("gcp_disk_limit_exceeded", {issue["code"] for issue in validate_run_record(local_run)})

        local_run = make_runs([make_case("single_doc")], stack_id="gcp_local")[0]
        local_run["environment"]["region"] = "asia-northeast3"
        local_run["environment"]["machine_type"] = "g2-standard-8"
        codes = {issue["code"] for issue in validate_run_record(local_run)}
        self.assertIn("gcp_region_not_allowed", codes)
        self.assertIn("gcp_machine_type_mismatch", codes)

        local_run = make_runs([make_case("single_doc")], stack_id="gcp_local")[0]
        del local_run["environment"]["region"]
        del local_run["environment"]["machine_type"]
        missing_paths = {
            issue["path"] for issue in validate_run_record(local_run) if issue["code"] == "required_field_missing"
        }
        self.assertIn("run.environment.region", missing_paths)
        self.assertIn("run.environment.machine_type", missing_paths)

        api_run = make_runs([make_case("single_doc")])[0]
        api_run["environment"]["region"] = None
        api_run["environment"]["machine_type"] = None
        invalid_paths = {
            issue["path"] for issue in validate_run_record(api_run) if issue["code"] == "invalid_environment_value"
        }
        self.assertIn("run.environment.region", invalid_paths)
        self.assertIn("run.environment.machine_type", invalid_paths)

    def test_run_schema_matches_gcp_environment_contract(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        schema = json.loads((project_root / "evaluation" / "schemas" / "run-record.schema.json").read_text(encoding="utf-8"))
        environment = schema["$defs"]["environment"]
        self.assertIn("region", environment["required"])
        self.assertIn("machine_type", environment["required"])
        local_constraints = next(
            item["then"]["properties"]["environment"]["properties"]
            for item in schema["allOf"]
            if "environment" in item.get("then", {}).get("properties", {})
        )
        self.assertEqual(local_constraints["region"]["enum"], ["us-central1", "us-east1"])
        self.assertEqual(local_constraints["machine_type"]["const"], "g2-standard-4")
        self.assertEqual(local_constraints["disk_gb"]["maximum"], 200)

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
        missing_reasoning = copy.deepcopy(run)
        del missing_reasoning["reasoning_effort"]
        self.assertIn(
            "api_reasoning_effort_not_minimal",
            {issue["code"] for issue in validate_run_record(missing_reasoning)},
        )
        run["stack_id"] = []
        run["generator_model"] = []
        self.assertTrue(validate_run_record(run))


if __name__ == "__main__":
    unittest.main()
