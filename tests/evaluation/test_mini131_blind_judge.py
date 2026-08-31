from __future__ import annotations

import copy
import io
import json
import stat
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from midprojectrag.ingest.common import (
    canonical_json,
    read_jsonl,
    sha256_file,
    sha256_text,
)
from midprojectrag.mini131_blind_judge import (
    ADJUDICATION_INPUT_FIELDS,
    BLIND_DECISION_FIELDS,
    BLIND_DECISION_SCHEMA_VERSION,
    REVIEW_HISTORY_FIELDS,
    BlindJudgePaths,
    build_review_history,
    main,
    seal_blind_decisions,
    select_adjudication_inputs,
    select_secondary_inputs,
    shard_review_inputs,
    slice_blind_inputs,
    translate_blind_decisions,
)
from midprojectrag.mini131_bundle import (
    BLIND_ADJUDICATION_INPUT_SCHEMA_VERSION,
    BLIND_REVIEW_HISTORY_SCHEMA_VERSION,
    JUDGMENT_FIELDS,
    _expected_behavior,
    _judgment_id,
    build_judge_packets,
)
from tests.evaluation.test_mini131_bundle import Mini131Fixture


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(canonical_json(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _nested_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for nested in value.values():
            keys.update(_nested_keys(nested))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for nested in value:
            keys.update(_nested_keys(nested))
        return keys
    return set()


def _paths(fixture: Mini131Fixture) -> BlindJudgePaths:
    return BlindJudgePaths(
        blind_inputs=fixture.paths.blind_judge_inputs,
        judge_packets=fixture.paths.judge_packets,
        rubric=fixture.paths.rubric,
        judge_config=fixture.paths.judge_config,
        judgments=fixture.root / "private" / "translated-judgments.jsonl",
    )


def _decision(
    fixture: Mini131Fixture,
    blind_row: dict[str, object],
    *,
    role: str = "primary",
    reviewed_at: str = "2026-08-31T12:00:00+09:00",
) -> dict[str, object]:
    packets = read_jsonl(fixture.paths.judge_packets)
    packet = next(
        row
        for row in packets
        if row["hashes"]["judge_input_sha256"]
        == blind_row["judge_input_sha256"]
    )
    expected_behavior = _expected_behavior(packet)
    abstention = expected_behavior == "abstain"
    observed_status = packet["judge_input"]["candidate"]["status"]
    expected_status = "abstained" if abstention else "answered"
    decision = "accepted" if observed_status == expected_status else "rejected"
    return {
        "schema_version": BLIND_DECISION_SCHEMA_VERSION,
        "blind_id": blind_row["blind_id"],
        "judge_input_sha256": blind_row["judge_input_sha256"],
        "review_config_sha256": sha256_file(fixture.paths.judge_config),
        "rubric_version": "gpt56-semantic-v2",
        "reviewer_type": "llm",
        "model": "gpt-5.6-sol",
        "judge_role": role,
        "scores": {
            "correctness": None if abstention else 1,
            "faithfulness": None if abstention else 1,
            "completeness": None if abstention else 1,
            "factual_claim_coverage": None if abstention else 1,
            "citation_validity": None if abstention else 1,
            "abstention_quality": 1 if abstention else None,
        },
        "matched_key_point_ids": [],
        "follow_up_success": None,
        "safe_abstention": True if abstention else None,
        "critical_flags": [],
        "confidence": 0.9,
        "judge_decision": decision,
        "rationale": "Private semantic review rationale.",
        "reviewed_at": reviewed_at,
    }


def _needs_review(row: dict[str, object]) -> dict[str, object]:
    changed = copy.deepcopy(row)
    changed["scores"]["correctness"] = 0.5  # type: ignore[index]
    changed["judge_decision"] = "needs_review"
    return changed


def _all_primary_decisions(
    fixture: Mini131Fixture,
    blind_rows: list[dict[str, object]],
    *,
    trigger_blind_id: str | None = None,
) -> list[dict[str, object]]:
    rows = [_decision(fixture, blind_row) for blind_row in blind_rows]
    if trigger_blind_id is not None:
        index = next(
            number
            for number, row in enumerate(rows)
            if row["blind_id"] == trigger_blind_id
        )
        rows[index] = _needs_review(rows[index])
    return rows


class Mini131BlindJudgeTests(unittest.TestCase):
    def test_translates_blind_binding_to_closed_full_judgment_and_mode_0600(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Mini131Fixture(Path(directory))
            build_judge_packets(fixture.paths)
            paths = _paths(fixture)
            blind_row = read_jsonl(paths.blind_inputs)[0]
            decision = _decision(fixture, blind_row)
            self.assertEqual(set(decision), BLIND_DECISION_FIELDS)
            self.assertFalse(set(decision) & {"case_id", "lane", "lineage"})
            decision_path = fixture.root / "private" / "primary.jsonl"
            _write_jsonl(decision_path, [decision])

            translated = translate_blind_decisions(paths, [decision_path])

            self.assertEqual(len(translated), 1)
            judgment = translated[0]
            self.assertEqual(set(judgment), JUDGMENT_FIELDS)
            self.assertEqual(judgment["judge_input_sha256"], decision["judge_input_sha256"])
            self.assertEqual(judgment["judgment_id"], _judgment_id(judgment))
            packet = next(
                row
                for row in read_jsonl(paths.judge_packets)
                if row["hashes"]["judge_input_sha256"]
                == decision["judge_input_sha256"]
            )
            self.assertEqual(judgment["case_id"], packet["case_id"])
            self.assertEqual(judgment["case_sha256"], packet["hashes"]["case_sha256"])
            self.assertEqual(
                judgment["run_record_sha256"], packet["hashes"]["run_sha256"]
            )
            self.assertEqual(stat.S_IMODE(paths.judgments.stat().st_mode), 0o600)
            self.assertEqual(read_jsonl(paths.judgments), translated)

    def test_combines_primary_secondary_and_adjudicator_batches_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Mini131Fixture(Path(directory))
            build_judge_packets(fixture.paths)
            paths = _paths(fixture)
            blind_row = read_jsonl(paths.blind_inputs)[0]
            primary = _decision(fixture, blind_row, role="primary")
            secondary = _decision(
                fixture,
                blind_row,
                role="secondary",
                reviewed_at="2026-08-31T12:01:00+09:00",
            )
            adjudicator = _decision(
                fixture,
                blind_row,
                role="adjudicator",
                reviewed_at="2026-08-31T12:02:00+09:00",
            )
            paths_by_role: list[Path] = []
            for role, row in (
                ("adjudicator", adjudicator),
                ("primary", primary),
                ("secondary", secondary),
            ):
                path = fixture.root / "private" / f"{role}.jsonl"
                _write_jsonl(path, [row])
                paths_by_role.append(path)

            translated = translate_blind_decisions(
                paths,
                paths_by_role,
                write=False,
            )

            self.assertEqual(
                [row["judge_role"] for row in translated],
                ["primary", "secondary", "adjudicator"],
            )

    def test_rejects_closed_schema_drift_wrong_binding_and_duplicate_role(self) -> None:
        mutations = (
            (
                "extra case id",
                lambda row: row.__setitem__("case_id", "leak"),
                "mini131_blind_decision_fields_invalid",
            ),
            (
                "wrong input hash",
                lambda row: row.__setitem__("judge_input_sha256", "0" * 64),
                "mini131_blind_decision_binding_mismatch",
            ),
            (
                "wrong config",
                lambda row: row.__setitem__("review_config_sha256", "0" * 64),
                "mini131_blind_decision_review_config_mismatch",
            ),
            (
                "wrong model",
                lambda row: row.__setitem__("model", "gpt-5-mini"),
                "mini131_blind_decision_model_mismatch",
            ),
        )
        for label, mutate, error in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                fixture = Mini131Fixture(Path(directory))
                build_judge_packets(fixture.paths)
                paths = _paths(fixture)
                blind_row = read_jsonl(paths.blind_inputs)[0]
                decision = _decision(fixture, blind_row)
                mutate(decision)
                decision_path = fixture.root / "private" / "decision.jsonl"
                _write_jsonl(decision_path, [decision])
                with self.assertRaisesRegex(ValueError, error):
                    translate_blind_decisions(paths, [decision_path], write=False)

        with tempfile.TemporaryDirectory() as directory:
            fixture = Mini131Fixture(Path(directory))
            build_judge_packets(fixture.paths)
            paths = _paths(fixture)
            blind_row = read_jsonl(paths.blind_inputs)[0]
            decision = _decision(fixture, blind_row)
            first = fixture.root / "private" / "first.jsonl"
            second = fixture.root / "private" / "second.jsonl"
            _write_jsonl(first, [decision])
            _write_jsonl(second, [copy.deepcopy(decision)])
            with self.assertRaisesRegex(
                ValueError, "mini131_blind_duplicate_role_decision"
            ):
                translate_blind_decisions(paths, [first, second], write=False)

    def test_fixed_judge_config_requires_high_reasoning_effort(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Mini131Fixture(Path(directory))
            build_judge_packets(fixture.paths)
            paths = _paths(fixture)
            config = json.loads(paths.judge_config.read_text(encoding="utf-8"))
            self.assertEqual(config["reasoning_effort"], "high")
            self.assertEqual(
                config["review_io"]["allowed_inputs"]["common"],
                [
                    "evaluation/rubric.md",
                    "evaluation/baselines/mini131-bundle-v1/judge-config.json",
                ],
            )
            role_inputs = config["review_io"]["allowed_inputs"]
            self.assertEqual(
                role_inputs["primary"]["selection"],
                "all_rows_or_deterministic_slice",
            )
            self.assertEqual(
                role_inputs["secondary"]["selection"],
                "validated_secondary_trigger_subset_or_deterministic_slice",
            )
            self.assertEqual(
                role_inputs["adjudicator"]["prior_decisions"],
                ["primary", "secondary"],
            )
            self.assertEqual(
                config["review_io"]["review_history_schema_version"],
                BLIND_REVIEW_HISTORY_SCHEMA_VERSION,
            )
            self.assertEqual(
                config["review_io"]["forbidden_inputs"],
                [
                    "evaluation/private/mini131/runs/baseline-v1/judge-packets.jsonl"
                ],
            )
            self.assertEqual(
                config["blinding"]["hidden_fields"],
                [
                    "candidate_model",
                    "candidate_stack",
                    "case_id",
                    "execution_lane",
                    "provider",
                    "lineage",
                ],
            )
            config["reasoning_effort"] = "medium"
            paths.judge_config.write_text(
                json.dumps(config, ensure_ascii=False), encoding="utf-8"
            )
            blind_row = read_jsonl(paths.blind_inputs)[0]
            decision = _decision(fixture, blind_row)
            decision_path = fixture.root / "private" / "decision.jsonl"
            _write_jsonl(decision_path, [decision])
            with self.assertRaisesRegex(
                ValueError, "mini131_blind_judge_config_mismatch"
            ):
                translate_blind_decisions(paths, [decision_path], write=False)

    def test_cli_emits_no_stdout_for_validate_or_translate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Mini131Fixture(Path(directory))
            build_judge_packets(fixture.paths)
            paths = _paths(fixture)
            blind_row = read_jsonl(paths.blind_inputs)[0]
            decision_path = fixture.root / "private" / "decision.jsonl"
            _write_jsonl(decision_path, [_decision(fixture, blind_row)])
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch(
                "midprojectrag.mini131_blind_judge.default_paths",
                return_value=paths,
            ), redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(
                    main(["validate", "--decisions", str(decision_path)]), 0
                )
                self.assertEqual(
                    main(["translate", "--decisions", str(decision_path)]), 0
                )
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(stderr.getvalue(), "")
            self.assertEqual(stat.S_IMODE(paths.judgments.stat().st_mode), 0o600)

    def test_seals_output_and_selects_only_secondary_trigger_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Mini131Fixture(Path(directory))
            build_judge_packets(fixture.paths)
            paths = _paths(fixture)
            blind_rows = read_jsonl(paths.blind_inputs)
            trigger_id = blind_rows[0]["blind_id"]
            primary_rows = _all_primary_decisions(
                fixture,
                blind_rows,
                trigger_blind_id=trigger_id,
            )
            raw_path = fixture.root / "private" / "primary-raw.jsonl"
            sealed_path = fixture.root / "private" / "primary-sealed.jsonl"
            secondary_inputs = fixture.root / "private" / "secondary-inputs.jsonl"
            _write_jsonl(raw_path, primary_rows)

            sealed = seal_blind_decisions(
                paths,
                [raw_path],
                output_path=sealed_path,
            )
            selected = select_secondary_inputs(
                paths,
                [sealed_path],
                output_path=secondary_inputs,
            )

            self.assertEqual(read_jsonl(sealed_path), sealed)
            self.assertEqual(stat.S_IMODE(sealed_path.stat().st_mode), 0o600)
            self.assertEqual([row["blind_id"] for row in selected], [trigger_id])
            self.assertEqual(selected, read_jsonl(secondary_inputs))
            self.assertEqual(stat.S_IMODE(secondary_inputs.stat().st_mode), 0o600)
            self.assertFalse(
                _nested_keys(selected[0]) & {"case_id", "lane", "lineage"}
            )
            shards = []
            for number in (1, 2, 3):
                shard_path = (
                    fixture.root
                    / "private"
                    / f"secondary-inputs-{number}-of-3.jsonl"
                )
                shards.extend(
                    shard_review_inputs(
                        paths,
                        input_path=secondary_inputs,
                        slice_number=number,
                        slice_count=3,
                        output_path=shard_path,
                    )
                )
                self.assertEqual(stat.S_IMODE(shard_path.stat().st_mode), 0o600)
            self.assertEqual(shards, selected)

            incomplete = fixture.root / "private" / "primary-incomplete.jsonl"
            _write_jsonl(incomplete, primary_rows[:-1])
            with self.assertRaisesRegex(
                ValueError, "mini131_primary_decision_ledger_incomplete"
            ):
                select_secondary_inputs(
                    paths,
                    [incomplete],
                    output_path=fixture.root / "private" / "must-not-write.jsonl",
                )

    def test_builds_nonidentifying_adjudication_packet_for_disagreement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Mini131Fixture(Path(directory))
            build_judge_packets(fixture.paths)
            paths = _paths(fixture)
            blind_rows = read_jsonl(paths.blind_inputs)
            target = blind_rows[0]
            primary_rows = _all_primary_decisions(
                fixture,
                blind_rows,
                trigger_blind_id=target["blind_id"],
            )
            primary_path = fixture.root / "private" / "primary.jsonl"
            _write_jsonl(primary_path, primary_rows)
            secondary = _decision(
                fixture,
                target,
                role="secondary",
                reviewed_at="2026-08-31T12:01:00+09:00",
            )
            secondary_path = fixture.root / "private" / "secondary.jsonl"
            _write_jsonl(secondary_path, [secondary])
            adjudication_path = fixture.root / "private" / "adjudication.jsonl"

            selected = select_adjudication_inputs(
                paths,
                [primary_path, secondary_path],
                output_path=adjudication_path,
            )

            self.assertEqual(len(selected), 1)
            packet = selected[0]
            self.assertEqual(set(packet), ADJUDICATION_INPUT_FIELDS)
            self.assertEqual(
                packet["schema_version"], BLIND_ADJUDICATION_INPUT_SCHEMA_VERSION
            )
            self.assertEqual(packet["blind_input"], target)
            self.assertEqual(packet["primary_decision"]["judge_role"], "primary")
            self.assertEqual(
                packet["secondary_decision"]["judge_role"], "secondary"
            )
            payload = {key: value for key, value in packet.items() if key != "input_sha256"}
            self.assertEqual(packet["input_sha256"], sha256_text(canonical_json(payload)))
            self.assertFalse(
                _nested_keys(packet) & {"case_id", "lane", "lineage"}
            )
            self.assertEqual(stat.S_IMODE(adjudication_path.stat().st_mode), 0o600)

            tampered = copy.deepcopy(packet)
            tampered["primary_decision"]["rationale"] = "tampered"
            tampered_path = fixture.root / "private" / "adjudication-tampered.jsonl"
            _write_jsonl(tampered_path, [tampered])
            adjudicator = _decision(
                fixture,
                target,
                role="adjudicator",
                reviewed_at="2026-08-31T12:02:00+09:00",
            )
            adjudicator_path = fixture.root / "private" / "adjudicator.jsonl"
            _write_jsonl(adjudicator_path, [adjudicator])
            with self.assertRaisesRegex(
                ValueError, "mini131_adjudication_input_hash_mismatch"
            ):
                build_review_history(
                    paths,
                    role="adjudicator",
                    input_paths=[tampered_path],
                    decision_paths=[adjudicator_path],
                    output_path=fixture.root / "private" / "tampered-history.jsonl",
                )

    def test_review_history_preserves_exact_input_output_with_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Mini131Fixture(Path(directory))
            build_judge_packets(fixture.paths)
            paths = _paths(fixture)
            blind_row = read_jsonl(paths.blind_inputs)[0]
            input_path = fixture.root / "private" / "primary-input.jsonl"
            raw_output = fixture.root / "private" / "primary-output-raw.jsonl"
            sealed_output = fixture.root / "private" / "primary-output.jsonl"
            history_path = fixture.root / "private" / "primary-history.jsonl"
            decision = _decision(fixture, blind_row)
            _write_jsonl(input_path, [blind_row])
            _write_jsonl(raw_output, [decision])
            seal_blind_decisions(
                paths,
                [raw_output],
                output_path=sealed_output,
            )

            histories = build_review_history(
                paths,
                role="primary",
                input_paths=[input_path],
                decision_paths=[sealed_output],
                output_path=history_path,
            )

            self.assertEqual(len(histories), 1)
            history = histories[0]
            self.assertEqual(set(history), REVIEW_HISTORY_FIELDS)
            self.assertEqual(
                history["schema_version"], BLIND_REVIEW_HISTORY_SCHEMA_VERSION
            )
            self.assertEqual(history["review_input"], blind_row)
            self.assertEqual(history["review_output"], decision)
            self.assertEqual(
                history["input_sha256"], sha256_text(canonical_json(blind_row))
            )
            self.assertEqual(
                history["output_sha256"], sha256_text(canonical_json(decision))
            )
            payload = {
                key: value
                for key, value in history.items()
                if key != "history_sha256"
            }
            self.assertEqual(
                history["history_sha256"], sha256_text(canonical_json(payload))
            )
            self.assertFalse(
                _nested_keys(history) & {"case_id", "lane", "lineage"}
            )
            self.assertEqual(stat.S_IMODE(history_path.stat().st_mode), 0o600)

    def test_slice_is_contiguous_exact_blind_rows_private_and_stdout_free(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Mini131Fixture(Path(directory))
            build_judge_packets(fixture.paths)
            paths = _paths(fixture)
            source = read_jsonl(paths.blind_inputs)
            slice_path = fixture.root / "private" / "slice-2-of-4.jsonl"

            sliced = slice_blind_inputs(
                paths,
                slice_number=2,
                slice_count=4,
                output_path=slice_path,
            )

            start = len(source) * 1 // 4
            end = len(source) * 2 // 4
            self.assertEqual(sliced, source[start:end])
            self.assertEqual(read_jsonl(slice_path), source[start:end])
            self.assertEqual(stat.S_IMODE(slice_path.stat().st_mode), 0o600)
            for row in sliced:
                self.assertFalse(set(row) & {"case_id", "lane", "lineage"})
                self.assertFalse(
                    _nested_keys(row["judge_input"])
                    & {"case_id", "lane", "lineage"}
                )

            cli_slice = fixture.root / "private" / "slice-1-of-4.jsonl"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch(
                "midprojectrag.mini131_blind_judge.default_paths",
                return_value=paths,
            ), redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(
                    main(
                        [
                            "slice",
                            "--slice-number",
                            "1",
                            "--slice-count",
                            "4",
                            "--output",
                            str(cli_slice),
                        ]
                    ),
                    0,
                )
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(stderr.getvalue(), "")
            self.assertEqual(read_jsonl(cli_slice), source[: len(source) // 4])


if __name__ == "__main__":
    unittest.main()
