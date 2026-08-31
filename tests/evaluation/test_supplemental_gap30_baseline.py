from __future__ import annotations

import copy
import json
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from midprojectrag.ingest.common import canonical_json
from midprojectrag.ingest.common import sha256_text
from midprojectrag.indexing.budget import BudgetLedger
from midprojectrag.supplemental_gap30_baseline import (
    ANSWER_GAP_IDS,
    BASELINE_ID,
    LEGACY_RUNTIME_CONTRACT_SHA256S,
    ProviderAudit,
    _answer_case,
    _checkpoint_payload,
    _checkpoint_path,
    _identity_with_runtime_contract,
    _legacy_set_args,
    _load_checkpoint,
    _materialize,
    _provider_call,
    _runtime_amendment,
    _runtime_contract_sha256s,
    _set_case,
    _validate_set_plan,
    _validate_interrupted_unique_items_400,
    _write_private_json,
    _write_private_jsonl,
    build_set_prompt,
    build_set_response_schema,
    preflight_report,
    recover_unique_items_400,
    run_gap30,
    verify_baseline,
)


class _FakeResponse:
    def __init__(self, payload: dict[str, object], output_text: str) -> None:
        self._payload = copy.deepcopy(payload)
        self.output_text = output_text
        self.status = payload.get("status")
        usage = payload.get("usage")
        self.usage = SimpleNamespace(**usage) if isinstance(usage, dict) else None

    def model_dump(self, *, mode: str) -> dict[str, object]:
        if mode != "json":
            raise AssertionError("audit must request JSON mode")
        return copy.deepcopy(self._payload)


class _FakeEndpoint:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> _FakeResponse:
        self.calls.append(copy.deepcopy(kwargs))
        return self.response


class _RaisingEndpoint:
    def create(self, **_kwargs: object) -> object:
        raise RuntimeError("synthetic uncertain transport failure")


def _checkpoint_verified(root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        config_sha256="a" * 64,
        answer_eval_set_sha256="b" * 64,
        set_eval_set_sha256="c" * 64,
        catalog_sha256="d" * 64,
        answer_cache_bundle_sha256="e" * 64,
        runtime_contract_sha256s=_runtime_contract_sha256s(),
        config={"artifacts": {"manifest_sha256": "f" * 64}},
    )


def _envelope(payload: dict[str, object]) -> dict[str, object]:
    return {
        "payload": copy.deepcopy(payload),
        "payload_sha256": sha256_text(canonical_json(payload)),
    }


class SupplementalGap30BaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[2]
        cls.config_path = (
            cls.repo_root
            / "evaluation/baselines/supplemental-mini-gap30-v1/config.json"
        )

    def _verify_private_baseline(self):
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        answer_cases = self.repo_root / config["artifacts"]["answer_cases"]
        if not answer_cases.is_file():
            self.skipTest("private Gap30 artifacts are not present in this checkout")
        return verify_baseline(self.config_path)

    def test_real_preflight_is_offline_and_finds_exact_30_gaps(self) -> None:
        with patch(
            "midprojectrag.supplemental_gap30_baseline._load_openai_client",
            side_effect=AssertionError("provider must be unreachable in preflight"),
        ):
            verified = self._verify_private_baseline()
            report = preflight_report(verified)

        self.assertEqual(tuple(case["case_id"] for case in verified.answer_cases), ANSWER_GAP_IDS)
        self.assertEqual(len(verified.set_cases), 13)
        self.assertEqual(len(verified.catalog_rows), 98)
        self.assertEqual(report["counts"], {"answer": 17, "set": 13, "total": 30, "catalog": 98})
        self.assertEqual(report["runtime"]["generator_model"], "gpt-5-mini")
        self.assertEqual(report["runtime"]["embedding_model"], "text-embedding-3-small")
        self.assertLess(report["estimated_cost_upper_bound"]["suite_usd"], 1.0)
        self.assertFalse(report["provider_called"])
        self.assertEqual(
            report["runtime_contract_sha256s"],
            verified.runtime_contract_sha256s,
        )
        self.assertEqual(len(report["runtime_contract_sha256"]), 64)
        self.assertIn(
            "midprojectrag.supplemental_gap30_baseline",
            verified.runtime_contract_sha256s["module_bytes"],
        )
        self.assertIn(
            "set_response_schema",
            verified.runtime_contract_sha256s["prompt_contracts"],
        )

    def test_set_prompt_uses_full_catalog_but_is_independent_of_gold(self) -> None:
        verified = self._verify_private_baseline()
        original = verified.set_cases[0]
        altered = copy.deepcopy(original)
        altered["required_doc_ids"] = ["doc_" + "f" * 24]
        altered["expected_count"] = 999

        first = build_set_prompt(original, verified.catalog_rows)
        second = build_set_prompt(altered, verified.catalog_rows)

        self.assertEqual(first, second)
        self.assertIn("<CATALOG_DOCUMENT_COUNT>98</CATALOG_DOCUMENT_COUNT>", first)
        self.assertNotIn("required_doc_ids", first)
        for row in verified.catalog_rows:
            self.assertEqual(first.count(row["doc_id"]), 1)

    def test_set_schema_has_manifest_ceiling_not_top10_or_ui20_cap(self) -> None:
        schema = build_set_response_schema()
        rendered = canonical_json(schema)
        self.assertIn('"maxItems":98', rendered)
        self.assertNotIn('"maxItems":10', rendered)
        self.assertNotIn('"maxItems":20', rendered)
        self.assertNotIn('"uniqueItems"', rendered)

    def test_validate_set_plan_requires_a_citation_for_every_selection(self) -> None:
        ids = [f"doc_{value:024x}" for value in range(12)]
        known = set(ids)
        plan = {
            "status": "answered",
            "answer": "12개 문서를 선택했습니다.",
            "selected_doc_ids": ids,
            "citations": [
                {"doc_id": doc_id, "reason": "조건에 부합"} for doc_id in ids
            ],
            "abstention_reason": None,
        }
        self.assertEqual(_validate_set_plan(plan, known), plan)
        invalid = copy.deepcopy(plan)
        invalid["citations"].pop()
        with self.assertRaisesRegex(ValueError, "gap30_set_citation_coverage_invalid"):
            _validate_set_plan(invalid, known)
        duplicated = copy.deepcopy(plan)
        duplicated["selected_doc_ids"].append(ids[0])
        duplicated["citations"].append(
            {"doc_id": ids[0], "reason": "중복은 애플리케이션에서 거부"}
        )
        with self.assertRaisesRegex(
            ValueError, "gap30_set_selected_doc_ids_invalid"
        ):
            _validate_set_plan(duplicated, known)

    def test_egress_gate_runs_before_paths_or_client_factory(self) -> None:
        client_calls: list[bool] = []

        def factory(_verified: object) -> object:
            client_calls.append(True)
            raise AssertionError("client factory must remain unreachable")

        with patch(
            "midprojectrag.supplemental_gap30_baseline._runtime_paths"
        ) as runtime_paths:
            with self.assertRaisesRegex(ValueError, "gap30_openai_egress_not_approved"):
                run_gap30(
                    SimpleNamespace(),
                    approve_openai_egress=False,
                    client_factory=factory,
                )
        runtime_paths.assert_not_called()
        self.assertEqual(client_calls, [])

    def test_provider_audit_preserves_exact_arguments_and_full_response(self) -> None:
        payload = {
            "id": "resp_synthetic",
            "status": "completed",
            "usage": {"input_tokens": 11, "output_tokens": 7},
            "output": [{"type": "message", "synthetic": True}],
        }
        output_text = json.dumps(
            {
                "result": {
                    "status": "abstained",
                    "answer": "",
                    "selected_doc_ids": [],
                    "citations": [],
                    "abstention_reason": "insufficient_evidence",
                }
            },
            sort_keys=True,
        )
        raw = _FakeEndpoint(_FakeResponse(payload, output_text))
        audit = ProviderAudit()
        endpoint = audit.endpoint(raw)
        arguments = {
            "model": "gpt-5-mini",
            "instructions": "synthetic",
            "input": "synthetic catalog",
            "store": False,
        }

        endpoint.create(**arguments)

        self.assertEqual(raw.calls, [arguments])
        self.assertEqual(audit.event["request_arguments"], arguments)
        self.assertEqual(
            audit.event["response"], {**payload, "output_text": output_text}
        )

    def test_answer_lane_persists_exact_final_abstention_prose(self) -> None:
        verified = self._verify_private_baseline()
        output_text = json.dumps(
            {
                "result": {
                    "status": "abstained",
                    "answer": "",
                    "citation_chunk_ids": [],
                    "abstention_reason": "insufficient_evidence",
                }
            },
            ensure_ascii=False,
        )
        payload = {
            "id": "resp_abstention",
            "status": "completed",
            "usage": {"input_tokens": 100, "output_tokens": 20},
            "output": [{"type": "message"}],
        }
        raw = _FakeEndpoint(_FakeResponse(payload, output_text))
        audit = ProviderAudit()
        endpoint = audit.endpoint(raw)
        with tempfile.TemporaryDirectory() as directory:
            ledger = BudgetLedger(Path(directory) / "budget.json", limit_usd=1)
            run, transcript = _answer_case(
                verified,
                verified.answer_cases[0],
                endpoint,
                audit,
                ledger,
            )

        expected = "제공된 문서에서 답변 근거를 찾지 못했습니다."
        self.assertEqual(run["status"], "abstained")
        self.assertEqual(run["answer"], expected)
        self.assertEqual(run["config_sha256"], verified.config_sha256)
        self.assertEqual(transcript["assistant"]["final_answer"], expected)
        self.assertEqual(transcript["config_sha256"], verified.config_sha256)
        self.assertEqual(
            transcript["assistant"]["final_response"]["answer"], expected
        )
        self.assertEqual(raw.calls[0]["model"], "gpt-5-mini")
        self.assertEqual(
            transcript["provider_exchange"]["generation"]["request_arguments"],
            raw.calls[0],
        )

    def test_set_lane_binds_run_and_transcript_to_frozen_config(self) -> None:
        verified = self._verify_private_baseline()
        doc_id = sorted(verified.known_doc_ids)[0]
        output_text = json.dumps(
            {
                "result": {
                    "status": "answered",
                    "answer": "합성 목록 답변",
                    "selected_doc_ids": [doc_id],
                    "citations": [{"doc_id": doc_id, "reason": "합성 근거"}],
                    "abstention_reason": None,
                }
            },
            ensure_ascii=False,
        )
        payload = {
            "id": "resp_set",
            "status": "completed",
            "usage": {"input_tokens": 100, "output_tokens": 20},
            "output": [{"type": "message"}],
        }
        raw = _FakeEndpoint(_FakeResponse(payload, output_text))
        audit = ProviderAudit()
        with tempfile.TemporaryDirectory() as directory:
            ledger = BudgetLedger(Path(directory) / "budget.json", limit_usd=1)
            run, transcript = _set_case(
                verified,
                verified.set_cases[0],
                audit.endpoint(raw),
                audit,
                ledger,
            )

        self.assertEqual(run["config_sha256"], verified.config_sha256)
        self.assertEqual(transcript["config_sha256"], verified.config_sha256)

    def test_uncertain_provider_error_keeps_reservation_for_manual_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = BudgetLedger(Path(directory) / "budget.json", limit_usd=1)
            args = {
                "model": "gpt-5-mini",
                "instructions": "synthetic",
                "input": "synthetic",
                "max_output_tokens": 100,
            }
            with self.assertRaisesRegex(RuntimeError, "uncertain transport failure"):
                _provider_call(_RaisingEndpoint(), args, ledger)
            snapshot = ledger.snapshot()
            self.assertEqual(float(snapshot.committed_usd), 0.0)
            self.assertEqual(float(snapshot.reserved_usd), 0.025)

    def test_private_writers_are_atomic_and_enforce_0700_0600(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "nested" / "private"
            object_path = private / "object.json"
            rows_path = private / "rows.jsonl"
            _write_private_json(object_path, {"secret": "synthetic"})
            _write_private_jsonl(rows_path, [{"row": 1}, {"row": 2}])
            self.assertEqual(stat.S_IMODE(private.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(object_path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(rows_path.stat().st_mode), 0o600)
            self.assertEqual(json.loads(object_path.read_text()), {"secret": "synthetic"})

    def test_started_or_interrupted_checkpoint_requires_budget_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            verified = _checkpoint_verified(root)
            path = root / "checkpoint.json"
            case_id = "supplemental-qa-synthetic"
            for state in ("started", "interrupted"):
                with self.subTest(state=state):
                    envelope = _checkpoint_payload(
                        verified,
                        "answer",
                        case_id,
                        state,
                        request={"question": "synthetic"},
                    )
                    _write_private_json(path, envelope)
                    with self.assertRaisesRegex(
                        ValueError, "gap30_case_requires_budget_audit"
                    ):
                        _load_checkpoint(path, verified, "answer", case_id)

    def test_checkpoint_resume_rejects_current_runtime_contract_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            verified = _checkpoint_verified(root)
            path = root / "checkpoint.json"
            case_id = "supplemental-qa-synthetic"
            envelope = _checkpoint_payload(
                verified,
                "answer",
                case_id,
                "completed",
                run_record={"case_id": case_id},
                chat_transcript={"case_id": case_id},
            )
            _write_private_json(path, envelope)
            drifted = copy.deepcopy(verified.runtime_contract_sha256s)
            drifted["prompt_contracts"]["set_system_instructions"] = "0" * 64
            with patch(
                "midprojectrag.supplemental_gap30_baseline._runtime_contract_sha256s",
                return_value=drifted,
            ):
                with self.assertRaisesRegex(
                    ValueError, "gap30_runtime_contract_drift"
                ):
                    _load_checkpoint(path, verified, "answer", case_id)

    def test_runtime_amendment_accepts_only_the_pinned_schema_delta(self) -> None:
        verified = self._verify_private_baseline()
        source_identity = _identity_with_runtime_contract(
            verified, LEGACY_RUNTIME_CONTRACT_SHA256S
        )
        amendment = _runtime_amendment(verified, source_identity)
        self.assertEqual(
            amendment["amendment_id"],
            "gap30-set-schema-unique-items-400-v1",
        )
        self.assertEqual(
            amendment["allowed_changes"]["prompt_contracts"],
            ["set_response_schema"],
        )
        drifted = copy.deepcopy(source_identity)
        drifted["runtime_contract_sha256s"]["prompt_contracts"][
            "answer_system_instructions"
        ] = "0" * 64
        drifted["runtime_contract_sha256"] = sha256_text(
            canonical_json(drifted["runtime_contract_sha256s"])
        )
        with self.assertRaisesRegex(
            ValueError, "gap30_amendment_source_identity_invalid"
        ):
            _runtime_amendment(verified, drifted)

        case = verified.set_cases[0]
        wrong_error = {
            "type": "BadRequestError",
            "message": "Error code: 400 - an unrelated invalid request",
        }
        interrupted = {
            "schema_version": "1.0",
            "artifact_type": "supplemental_gap30_case_checkpoint",
            "baseline_id": BASELINE_ID,
            "lane": "set",
            "case_id": case["case_id"],
            "state": "interrupted",
            "identity": source_identity,
            "request": {"question": case["question"]},
            "provider_exchange": {
                "generation": {
                    "attempt_number": 1,
                    "request_arguments": _legacy_set_args(
                        build_set_prompt(case, verified.catalog_rows),
                        verified.config["runtime"],
                    ),
                    "response": None,
                    "error": wrong_error,
                }
            },
            "runtime_error": wrong_error,
        }
        with self.assertRaisesRegex(
            ValueError,
            "gap30_amendment_provider_error_not_unique_items_400",
        ):
            _validate_interrupted_unique_items_400(
                verified, case, _envelope(interrupted), source_identity
            )

    def test_explicit_recovery_preserves_400_and_never_retries_failed_set(
        self,
    ) -> None:
        verified = self._verify_private_baseline()
        source_identity = _identity_with_runtime_contract(
            verified, LEGACY_RUNTIME_CONTRACT_SHA256S
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "private"
            paths = {
                "answer_runs": run_dir / "answer-runs.jsonl",
                "set_runs": run_dir / "set-runs.jsonl",
                "chat_transcripts": run_dir / "chat-transcripts.jsonl",
                "private_summary": run_dir / "summary.json",
                "receipt": root / "public" / "receipt.json",
                "run_dir": run_dir,
                "checkpoints": run_dir / "case-checkpoints",
                "run_state": run_dir / "run-state.json",
                "runtime_amendment": run_dir / "runtime-contract-amendment.json",
                "budget": run_dir / "budget-ledger.json",
                "lock": run_dir / ".run.lock",
            }
            _write_private_json(paths["run_state"], source_identity)
            answer_rows: list[dict[str, object]] = []
            answer_transcripts: list[dict[str, object]] = []
            for case in verified.answer_cases:
                run = {
                    "case_id": case["case_id"],
                    "status": "answered",
                    "answer": "synthetic",
                }
                transcript = {
                    "case_id": case["case_id"],
                    "lane": "answer",
                    "assistant": {"final_answer": "synthetic"},
                }
                answer_rows.append(run)
                answer_transcripts.append(transcript)
                payload = {
                    "schema_version": "1.0",
                    "artifact_type": "supplemental_gap30_case_checkpoint",
                    "baseline_id": BASELINE_ID,
                    "lane": "answer",
                    "case_id": case["case_id"],
                    "state": "completed",
                    "identity": source_identity,
                    "run_record": run,
                    "chat_transcript": transcript,
                }
                _write_private_json(
                    _checkpoint_path(paths, "answer", case["case_id"]),
                    _envelope(payload),
                )
            _write_private_jsonl(paths["answer_runs"], answer_rows)
            _write_private_jsonl(paths["set_runs"], [])
            _write_private_jsonl(paths["chat_transcripts"], answer_transcripts)

            failed_case = verified.set_cases[0]
            expected_args = _legacy_set_args(
                build_set_prompt(failed_case, verified.catalog_rows),
                verified.config["runtime"],
            )
            provider_error = {
                "type": "BadRequestError",
                "message": (
                    "Error code: 400 - Invalid schema: uniqueItems is not permitted"
                ),
            }
            event = {
                "attempt_number": 1,
                "request_arguments": expected_args,
                "response": None,
                "error": provider_error,
            }
            interrupted = {
                "schema_version": "1.0",
                "artifact_type": "supplemental_gap30_case_checkpoint",
                "baseline_id": BASELINE_ID,
                "lane": "set",
                "case_id": failed_case["case_id"],
                "state": "interrupted",
                "identity": source_identity,
                "request": {"question": failed_case["question"]},
                "provider_exchange": {"generation": event},
                "runtime_error": provider_error,
            }
            _write_private_json(
                _checkpoint_path(paths, "set", failed_case["case_id"]),
                _envelope(interrupted),
            )
            ledger = BudgetLedger(paths["budget"], limit_usd=1)
            ledger.reserve(
                0.025,
                f"{BASELINE_ID}:{sha256_text(canonical_json(expected_args))}",
            )

            with patch(
                "midprojectrag.supplemental_gap30_baseline._runtime_paths",
                return_value=paths,
            ), patch(
                "midprojectrag.supplemental_gap30_baseline._load_openai_client",
                side_effect=AssertionError("recovery must never reach provider"),
            ):
                receipt = recover_unique_items_400(verified)

            self.assertEqual(receipt["counts"]["completed"], 18)
            self.assertEqual(receipt["status_counts"]["error"], 1)
            self.assertFalse(
                receipt["runtime_contract_amendment"]["failed_case_retried"]
            )
            self.assertEqual(float(ledger.snapshot().reserved_usd), 0.0)
            set_rows = [
                json.loads(line)
                for line in paths["set_runs"].read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(set_rows[0]["status"], "error")
            self.assertEqual(set_rows[0]["provider_error"], provider_error)
            transcripts = [
                json.loads(line)
                for line in paths["chat_transcripts"]
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            failed_transcript = transcripts[-1]
            self.assertEqual(
                failed_transcript["provider_exchange"]["generation"], event
            )
            recovered_checkpoint = json.loads(
                _checkpoint_path(paths, "set", failed_case["case_id"]).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                recovered_checkpoint["payload"][
                    "recovered_from_interrupted_checkpoint"
                ]["payload"]["provider_exchange"]["generation"],
                event,
            )

    def test_new_outputs_do_not_overlap_legacy_run(self) -> None:
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        legacy = "evaluation/private/supplemental/runs/provisional-v1/"
        new = "evaluation/private/supplemental/runs/mini-gap30-v1/"
        for field in ("answer_runs", "set_runs", "chat_transcripts", "private_summary"):
            self.assertTrue(config["outputs"][field].startswith(new))
            self.assertFalse(config["outputs"][field].startswith(legacy))

    def test_public_receipt_excludes_private_content(self) -> None:
        secrets = {
            "question": "SYNTHETIC_PRIVATE_QUESTION",
            "answer": "SYNTHETIC_PRIVATE_ANSWER",
            "source": "SYNTHETIC_PRIVATE_SOURCE",
            "provider": "SYNTHETIC_PRIVATE_PROVIDER_RESPONSE",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {
                "answer_runs": root / "private" / "answer.jsonl",
                "set_runs": root / "private" / "set.jsonl",
                "chat_transcripts": root / "private" / "chat.jsonl",
                "private_summary": root / "private" / "summary.json",
                "budget": root / "private" / "budget.json",
                "receipt": root / "public" / "receipt.json",
            }
            BudgetLedger(paths["budget"], limit_usd=1).snapshot()
            verified = SimpleNamespace(
                answer_cases=[{"case_id": "supplemental-qa-synthetic"}],
                set_cases=[],
                config_sha256="a" * 64,
                answer_eval_set_sha256="b" * 64,
                set_eval_set_sha256="c" * 64,
                catalog_sha256="d" * 64,
                answer_cache_bundle_sha256="e" * 64,
                config={
                    "artifacts": {
                        "manifest_sha256": "f" * 64,
                    }
                },
            )
            completed = {
                "supplemental-qa-synthetic": {
                    "run_record": {
                        "case_id": "supplemental-qa-synthetic",
                        "status": "answered",
                        "answer": secrets["answer"],
                    },
                    "chat_transcript": {
                        "question": secrets["question"],
                        "source_text": secrets["source"],
                        "provider_response": secrets["provider"],
                    },
                }
            }

            receipt = _materialize(verified, paths, completed)
            public_text = canonical_json(receipt)

        for secret in secrets.values():
            self.assertNotIn(secret, public_text)
        self.assertEqual(receipt["privacy"]["contains_questions"], False)
        self.assertEqual(receipt["privacy"]["contains_provider_responses"], False)


if __name__ == "__main__":
    unittest.main()
