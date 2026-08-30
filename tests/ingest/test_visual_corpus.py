from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from midprojectrag.ingest.common import (
    canonical_json,
    sha256_file,
    sha256_text,
    write_json,
    write_jsonl,
)
from midprojectrag.ingest.visual_corpus import (
    run_hwp_visual_corpus,
    select_hwp_visual_samples,
)


DOC_A = "doc_000000000000000000000001"
DOC_B = "doc_000000000000000000000002"
DOC_C = "doc_000000000000000000000003"
DOC_D = "doc_000000000000000000000004"
DOC_E = "doc_000000000000000000000005"
DOC_F = "doc_000000000000000000000006"
CONFIG_SHA256 = "c" * 64
SELECTION_SHA256 = "0" * 64


def _structural_stats(doc_id: str, **overrides: int) -> dict[str, int | str]:
    value: dict[str, int | str] = {
        "doc_id": doc_id,
        "page_count": 50,
        "table_count": 10,
        "schedule_facts": 0,
        "background_cells": 0,
        "images": 0,
        "table_nested_images": 0,
        "wrapper_flattened": 0,
        "merged_tables": 0,
        "spanned_cells": 0,
        "max_table_cell_count": 10,
        "max_table_page_span": 1,
        "multi_page_tables": 0,
        "unresolved_layouts": 0,
        "nonbody_unlinked": 0,
        "paragraph_anchor_candidates": 0,
        "risk_score": 0,
    }
    value.update(overrides)
    return value


class VisualCorpusTests(unittest.TestCase):
    def _runtime(self, root: Path) -> tuple[Path, Path, str]:
        command = root / "rhwp"
        command.write_bytes(b"pinned-rhwp")
        command.chmod(0o700)
        private_root = root / "private"
        private_root.mkdir(exist_ok=True)
        return command, private_root, sha256_file(command)

    def _job(self, private_root: Path, doc_id: str) -> dict[str, Any]:
        source = private_root / "sources" / f"{doc_id}.hwp"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(f"synthetic-{doc_id}".encode("ascii"))
        return {
            "doc_id": doc_id,
            "source_path": source,
            "expected_source_sha256": sha256_file(source),
            "page_count": 1,
            "blocks": [],
            "layout_records": [],
        }

    def _runner_kwargs(
        self,
        root: Path,
        documents: list[dict[str, Any]],
        *,
        stream: io.StringIO | None = None,
        continue_on_error: bool = False,
    ) -> dict[str, Any]:
        command, private_root, command_sha256 = self._runtime(root)
        return {
            "command": str(command.resolve()),
            "documents": documents,
            "output_root": private_root / "visual-v1",
            "asset_root": private_root / "hwp-assets-v1",
            "private_root": private_root,
            "config_sha256": CONFIG_SHA256,
            "expected_rhwp_sha256": command_sha256,
            "continue_on_error": continue_on_error,
            "stream": stream,
            "run_id": "run_test",
            "mode": "sample",
            "selection_sha256": SELECTION_SHA256,
            "report_output": None,
        }

    @staticmethod
    def _fake_materialize(**kwargs: Any) -> dict[str, Any]:
        kwargs["asset_root"].mkdir(parents=True, exist_ok=True)
        table_output = kwargs["table_output"]
        image_output = kwargs["image_output"]
        ordered_output = kwargs["ordered_output"]
        metadata_output = kwargs["metadata_output"]
        write_jsonl(table_output, [])
        write_jsonl(image_output, [])
        write_jsonl(ordered_output, [])
        blocks_sha256 = sha256_text(canonical_json(list(kwargs["blocks"])))
        layout_sha256 = sha256_text(
            canonical_json(list(kwargs["layout_records"]))
        )
        identity = {
            "doc_id": kwargs["doc_id"],
            "source_sha256": kwargs["expected_source_sha256"],
            "rhwp_binary_sha256": kwargs["expected_rhwp_sha256"],
            "config_sha256": kwargs["config_sha256"],
            "blocks_sha256": blocks_sha256,
            "layout_records_sha256": layout_sha256,
            "table_artifact_sha256": sha256_file(table_output),
            "image_artifact_sha256": sha256_file(image_output),
            "ordered_artifact_sha256": sha256_file(ordered_output),
            "asset_object_manifest_sha256": sha256_text(canonical_json([])),
            "page_count": 1,
        }
        metadata = {
            "schema_version": "1.0",
            "doc_id": kwargs["doc_id"],
            "method": "rhwp-ordered-visual-evidence-v1",
            "coordinate_space": "rhwp_css_px_96dpi",
            **identity,
            "artifact_set_id": "visual_"
            + sha256_text(canonical_json(identity))[:24],
            "tables": 0,
            "images": 0,
            "ordered_occurrences": 0,
            "asset_count": 0,
            "asset_reference_count": 0,
            "asset_bytes": 0,
            "asset_references_reconciled": True,
            "table_status_counts": {},
            "image_status_counts": {},
            "ordered_status_counts": {},
        }
        write_json(metadata_output, metadata)
        return metadata

    def test_sample_selection_is_structural_deterministic_and_tie_broken(self) -> None:
        stats = [
            _structural_stats(
                DOC_A,
                schedule_facts=14,
                background_cells=602,
                images=6,
                table_nested_images=5,
                risk_score=100,
            ),
            _structural_stats(
                DOC_B,
                wrapper_flattened=3,
                merged_tables=22,
                spanned_cells=520,
                max_table_cell_count=1491,
                risk_score=90,
            ),
            _structural_stats(
                DOC_C,
                page_count=116,
                max_table_page_span=10,
                risk_score=80,
            ),
            _structural_stats(
                DOC_D,
                page_count=183,
                table_count=247,
                unresolved_layouts=8,
                paragraph_anchor_candidates=8,
                risk_score=70,
            ),
            _structural_stats(DOC_E, risk_score=60),
            _structural_stats(DOC_F, risk_score=60),
        ]

        first = select_hwp_visual_samples(stats)
        second = select_hwp_visual_samples(list(reversed(stats)))

        self.assertEqual(first, second)
        self.assertRegex(first["selection_policy_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(len(first["documents"]), 5)
        selected_ids = [row["doc_id"] for row in first["documents"]]
        self.assertEqual(len(selected_ids), len(set(selected_ids)))
        self.assertEqual(set(selected_ids), {DOC_A, DOC_B, DOC_C, DOC_D, DOC_E})
        self.assertNotIn(DOC_F, selected_ids)
        roles_by_doc = {
            row["doc_id"]: set(row["roles"]) for row in first["documents"]
        }
        self.assertTrue({"schedule", "image"}.issubset(roles_by_doc[DOC_A]))
        self.assertIn("merged_nested_table", roles_by_doc[DOC_B])
        self.assertIn("long_multi_page_table", roles_by_doc[DOC_C])
        self.assertIn("layout_unresolved", roles_by_doc[DOC_D])
        serialized = canonical_json(first)
        self.assertNotIn("filename", serialized)
        self.assertNotIn("source_path", serialized)
        self.assertNotIn("text", serialized)

    def test_strict_reuse_and_tampered_artifact_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private_root = root / "private"
            private_root.mkdir()
            job = self._job(private_root, DOC_A)
            kwargs = self._runner_kwargs(root, [job])

            with patch(
                "midprojectrag.ingest.visual_corpus.materialize_hwp_visual_bundle",
                side_effect=self._fake_materialize,
            ) as materialize:
                first = run_hwp_visual_corpus(**kwargs)
            self.assertEqual(first["totals"]["materialized"], 1)
            self.assertEqual(first["documents"][0]["terminal_state"], "materialized")
            materialize.assert_called_once()

            with patch(
                "midprojectrag.ingest.visual_corpus.materialize_hwp_visual_bundle"
            ) as materialize:
                second = run_hwp_visual_corpus(**kwargs)
            self.assertEqual(second["totals"]["reused"], 1)
            self.assertEqual(second["documents"][0]["terminal_state"], "reused")
            materialize.assert_not_called()

            table_output = (
                kwargs["output_root"] / DOC_A / "table-visual-v1.jsonl"
            )
            table_output.write_text("{}\n", encoding="utf-8")
            with patch(
                "midprojectrag.ingest.visual_corpus.materialize_hwp_visual_bundle",
                side_effect=self._fake_materialize,
            ) as materialize:
                third = run_hwp_visual_corpus(**kwargs)
            self.assertEqual(third["totals"]["materialized"], 1)
            self.assertEqual(third["totals"]["reused"], 0)
            self.assertEqual(third["documents"][0]["terminal_state"], "materialized")
            materialize.assert_called_once()

    def test_execution_order_is_sorted_by_doc_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private_root = root / "private"
            private_root.mkdir()
            documents = [
                self._job(private_root, DOC_C),
                self._job(private_root, DOC_A),
                self._job(private_root, DOC_B),
            ]
            kwargs = self._runner_kwargs(root, documents)
            calls: list[str] = []

            def materialize(**materialize_kwargs: Any) -> dict[str, Any]:
                calls.append(materialize_kwargs["doc_id"])
                return self._fake_materialize(**materialize_kwargs)

            with patch(
                "midprojectrag.ingest.visual_corpus.materialize_hwp_visual_bundle",
                side_effect=materialize,
            ):
                report = run_hwp_visual_corpus(**kwargs)

            self.assertEqual(calls, [DOC_A, DOC_B, DOC_C])
            self.assertEqual(
                [row["doc_id"] for row in report["documents"]],
                [DOC_A, DOC_B, DOC_C],
            )
            self.assertEqual(report["totals"]["requested"], 3)
            self.assertEqual(report["totals"]["succeeded"], 3)

    def test_continue_on_error_aggregates_and_sanitizes_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private_root = root / "private"
            private_root.mkdir()
            documents = [
                self._job(private_root, DOC_C),
                self._job(private_root, DOC_B),
                self._job(private_root, DOC_A),
            ]
            stream = io.StringIO()
            kwargs = self._runner_kwargs(
                root,
                documents,
                stream=stream,
                continue_on_error=True,
            )
            calls: list[str] = []

            def materialize(**materialize_kwargs: Any) -> dict[str, Any]:
                doc_id = materialize_kwargs["doc_id"]
                calls.append(doc_id)
                if doc_id == DOC_B:
                    raise ValueError(
                        f"secret proposal body at {materialize_kwargs['source_path']}"
                    )
                return self._fake_materialize(**materialize_kwargs)

            with patch(
                "midprojectrag.ingest.visual_corpus.materialize_hwp_visual_bundle",
                side_effect=materialize,
            ):
                report = run_hwp_visual_corpus(**kwargs)

            self.assertEqual(calls, [DOC_A, DOC_B, DOC_C])
            self.assertEqual(report["totals"]["requested"], 3)
            self.assertEqual(report["totals"]["succeeded"], 2)
            self.assertEqual(report["totals"]["materialized"], 2)
            self.assertEqual(report["totals"]["reused"], 0)
            self.assertEqual(report["totals"]["failed"], 1)
            failed = next(
                row
                for row in report["documents"]
                if row["terminal_state"] == "failed"
            )
            self.assertEqual(failed["doc_id"], DOC_B)
            self.assertRegex(failed["error_code"], r"^[a-z][a-z0-9_]{0,63}$")
            self.assertNotEqual(failed["error_code"], "secret proposal body")
            streamed = json.loads(stream.getvalue())
            self.assertEqual(streamed, report)
            for rendered in (canonical_json(report), stream.getvalue()):
                self.assertNotIn("secret proposal body", rendered)
                self.assertNotIn(str(private_root), rendered)
                self.assertNotIn("source_path", rendered)


if __name__ == "__main__":
    unittest.main()
