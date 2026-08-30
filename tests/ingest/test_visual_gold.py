from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from jsonschema import Draft202012Validator

from midprojectrag.ingest.visual_gold import VisualGoldError, validate_visual_gold
from midprojectrag.cli import main


ROOT = Path(__file__).resolve().parents[2]


class VisualGoldTests(unittest.TestCase):
    def _record(
        self,
        index: int,
        *,
        source_format: str,
        risk_type: str,
        critical_case: str = "none",
    ) -> dict:
        return {
            "schema_version": "1.0",
            "annotation_id": f"vgold_{index:024x}",
            "doc_id": f"doc_{index:024x}",
            "source_sha256": f"{index + 1:064x}",
            "source_format": source_format,
            "risk_type": risk_type,
            "page": index + 1,
            "bbox": {"x": 1.0, "y": 2.0, "w": 30.0, "h": 40.0},
            "coordinate_space": (
                "rhwp_css_px_96dpi"
                if source_format == "hwp"
                else "pdf_points_top_left"
            ),
            "region_kind": (
                "table" if "schedule" in risk_type else "vector_diagram"
            ),
            "nearby_title": "synthetic title",
            "expected_text": ["synthetic token"],
            "relationship_claims": [],
            "critical_case": critical_case,
            "reviewers": ["reviewer-a"],
            "status": "reviewed",
        }

    def _gate(self) -> list[dict]:
        risks = [
            ("hwp", "hwp_body_image", "none"),
            ("hwp", "hwp_table_nested", "schedule"),
            ("hwp", "hwp_vector_diagram", "system_diagram"),
            ("hwp", "hwp_unsupported_media", "none"),
            ("hwp", "hwp_repeated_mismatch", "none"),
            ("pdf", "pdf_raster", "none"),
            ("pdf", "pdf_inline_or_mask", "none"),
            ("pdf", "pdf_vector_diagram", "none"),
            ("pdf", "pdf_schedule_table", "schedule"),
        ]
        return [
            self._record(
                index,
                source_format=source_format,
                risk_type=risk_type,
                critical_case=critical,
            )
            for index, (source_format, risk_type, critical) in enumerate(risks, 1)
        ]

    def test_full_representative_gate_passes_without_text_output(self) -> None:
        records = self._gate()
        result = validate_visual_gold(records)
        self.assertEqual(result["hwp_document_count"], 5)
        self.assertEqual(result["pdf_document_count"], 4)
        self.assertNotIn("expected_text", result)
        schema = json.loads(
            (ROOT / "contracts" / "visual-gold-v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        for record in records:
            validator.validate(record)

    def test_missing_risk_type_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            VisualGoldError, "visual_gold_hwp_representative_gate_failed"
        ):
            validate_visual_gold(self._gate()[1:])

    def test_draft_record_fails_when_review_required(self) -> None:
        records = self._gate()
        records[0]["status"] = "draft"
        with self.assertRaisesRegex(VisualGoldError, "visual_gold_review_incomplete"):
            validate_visual_gold(records)

    def test_cli_partial_validation_outputs_counts_only(self) -> None:
        record = self._gate()[0]
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            annotations = root / "private" / "visual-gold.jsonl"
            annotations.parent.mkdir()
            annotations.write_text(
                json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            output = StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "visual-gold-validate",
                        "--data-dir",
                        str(root),
                        "--annotations",
                        str(annotations),
                        "--partial",
                    ]
                )
        self.assertEqual(code, 0)
        summary = json.loads(output.getvalue())
        self.assertEqual(summary["annotation_count"], 1)
        self.assertNotIn("expected_text", summary)


if __name__ == "__main__":
    unittest.main()
