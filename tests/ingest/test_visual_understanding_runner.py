from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping

from PIL import Image

from midprojectrag.ingest.visual_evidence import (
    crop_page_region,
    make_visual_occurrence,
    write_jsonl_artifact,
)
from midprojectrag.ingest.visual_understanding import (
    CaptionModelConfig,
    DeterministicFixtureAdapter,
    PpStructureV3Config,
    VisualRetrievalPolicy,
)
from midprojectrag.ingest.visual_understanding_runner import (
    VisualUnderstandingBatchError,
    run_visual_understanding_batch,
)


DOC_ID = "doc_0123456789abcdef01234567"
SOURCE_SHA256 = "1" * 64
OCR_WEIGHTS_SHA256 = "2" * 64
CAPTION_WEIGHTS_SHA256 = "3" * 64
ADAPTER_CODE_SHA256 = "4" * 64


def _polygon(x: float, y: float, w: float, h: float) -> list[list[float]]:
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def _ocr_response() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "status": "success",
        "text_items": [
            {
                "polygon": _polygon(0, 0, 40, 10),
                "text": "샘플 업무시스템",
                "confidence": 0.98,
                "reading_order": 0,
            },
            {
                "polygon": _polygon(0, 12, 40, 10),
                "text": "샘플 보안 영역",
                "confidence": 0.96,
                "reading_order": 1,
            },
        ],
        "table_cells": [
            {
                "row": 0,
                "column": 0,
                "row_span": 1,
                "column_span": 1,
                "polygon": _polygon(0, 0, 42, 24),
                "text": "샘플 업무시스템 샘플 보안 영역",
                "confidence": 0.95,
                "source_reading_orders": [0, 1],
            }
        ],
        "warnings": [],
    }


def _caption_response() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "status": "success",
        "description": "DB 서버와 연결된다.",
        "claims": [
            {
                "text": "DB 서버와 연결된다.",
                "support_refs": ["source:verified"],
            }
        ],
        "warnings": [],
    }


class CountingFixtureAdapter(DeterministicFixtureAdapter):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.calls = 0

    def infer(self, operation: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls += 1
        return super().infer(operation, request)


class VisualUnderstandingBatchRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.private_root = Path(temporary.name).resolve()
        self.output_root = self.private_root / "understanding-v1"
        self.occurrences_path = self.private_root / "visual-occurrences-v2.jsonl"

        page = self.private_root / "page.png"
        Image.new("RGB", (120, 120), "white").save(page)
        base = make_visual_occurrence(
            doc_id=DOC_ID,
            source_sha256=SOURCE_SHA256,
            page=1,
            bbox={"x": 10, "y": 15, "w": 80, "h": 55},
            coordinate_space="pdf_points_top_left",
            sequence_in_page=0,
            container_path=["page:1", "geometry:0"],
            source_anchor={
                "kind": "pdf_geometry",
                "section_index": None,
                "paragraph_index": None,
                "control_index": None,
                "table_block_id": None,
                "cell_path": [],
            },
            region_kind="vector_diagram",
            placement_status="page_bbox_verified",
        )
        self.eligible = crop_page_region(
            base,
            page_image=page,
            private_root=self.private_root,
            coordinate_page_bbox={"x": 0, "y": 0, "w": 120, "h": 120},
            render_profile={"renderer": "fixture", "version": "1"},
        )
        self.ineligible = make_visual_occurrence(
            doc_id="doc_fedcba9876543210fedcba98",
            source_sha256="5" * 64,
            page=None,
            bbox=None,
            coordinate_space=None,
            sequence_in_page=None,
            container_path=["document", "asset:0"],
            source_anchor=None,
            region_kind="raster_image",
            placement_status="doc_only_unlinked",
            source_object_status="missing",
        )
        self._write_occurrences([self.eligible, self.ineligible])

        self.ocr_config = PpStructureV3Config(
            model_version="fixture-1",
            weights_sha256=OCR_WEIGHTS_SHA256,
            runtime="fixture-offline",
            device="cpu",
        )
        self.caption_config = CaptionModelConfig(
            model_name="fixture-caption",
            model_version="fixture-1",
            weights_sha256=CAPTION_WEIGHTS_SHA256,
            runtime="fixture-offline",
            device="cpu",
            prompt="근거 식별자가 있는 사실만 기술하라.",
        )
        self.policy = VisualRetrievalPolicy()

    def _write_occurrences(self, records: list[dict[str, Any]]) -> None:
        write_jsonl_artifact(
            records,
            output=self.occurrences_path,
            private_root=self.private_root,
        )

    def _ocr_adapter(self) -> CountingFixtureAdapter:
        return CountingFixtureAdapter(
            responses={"ocr_layout_v1": _ocr_response()},
            model_artifact_sha256=OCR_WEIGHTS_SHA256,
        )

    def _caption_adapter(self) -> CountingFixtureAdapter:
        return CountingFixtureAdapter(
            responses={"caption_v1": _caption_response()},
            model_artifact_sha256=CAPTION_WEIGHTS_SHA256,
        )

    def _run(
        self,
        *,
        ocr_adapter: CountingFixtureAdapter,
        caption_adapter: CountingFixtureAdapter | None = None,
    ) -> dict[str, Any]:
        return run_visual_understanding_batch(
            private_root=self.private_root,
            occurrences_path=self.occurrences_path,
            output_root=self.output_root,
            adapter_code_sha256=ADAPTER_CODE_SHA256,
            ocr_adapter=ocr_adapter,
            ocr_config=self.ocr_config,
            policy=self.policy,
            caption_adapter=caption_adapter,
            caption_config=self.caption_config if caption_adapter is not None else None,
            additional_support_refs=(
                {self.eligible["occurrence_id"]: ["source:verified"]}
                if caption_adapter is not None
                else None
            ),
        )

    def _read_jsonl(self, name: str) -> list[dict[str, Any]]:
        path = self.output_root / name
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def test_ocr_only_skips_ineligible_and_returns_counts_without_private_text(self) -> None:
        adapter = self._ocr_adapter()
        summary = self._run(ocr_adapter=adapter)

        self.assertEqual(adapter.calls, 1)
        self.assertEqual(summary["counts"]["occurrence_total"], 2)
        self.assertEqual(summary["counts"]["eligible_occurrence"], 1)
        self.assertEqual(summary["counts"]["skipped_ineligible"], 1)
        self.assertEqual(summary["counts"]["ocr_evidence"], 1)
        self.assertEqual(summary["counts"]["caption_evidence"], 0)
        self.assertFalse(summary["caption_enabled"])
        self.assertFalse((self.output_root / "caption-evidence-v1.jsonl").exists())
        self.assertNotIn("샘플 업무시스템", json.dumps(summary, ensure_ascii=False))
        self.assertEqual(len(self._read_jsonl("ocr-evidence-v1.jsonl")), 1)
        self.assertGreaterEqual(len(self._read_jsonl("visual-chunks-v1.jsonl")), 2)

    def test_resume_reuses_content_addressed_cache_and_is_deterministic(self) -> None:
        first_adapter = self._ocr_adapter()
        first = self._run(ocr_adapter=first_adapter)
        artifact_bytes = {
            path.name: path.read_bytes()
            for path in self.output_root.iterdir()
            if path.is_file()
        }

        second_adapter = self._ocr_adapter()
        second = self._run(ocr_adapter=second_adapter)

        self.assertEqual(first_adapter.calls, 1)
        self.assertEqual(second_adapter.calls, 0)
        self.assertEqual(first, second)
        self.assertEqual(
            artifact_bytes,
            {
                path.name: path.read_bytes()
                for path in self.output_root.iterdir()
                if path.is_file()
            },
        )

    def test_repeated_crop_is_inferred_once_and_rebound_to_each_occurrence(self) -> None:
        repeated_base = make_visual_occurrence(
            doc_id="doc_aaaaaaaaaaaaaaaaaaaaaaaa",
            source_sha256="6" * 64,
            page=1,
            bbox={"x": 10, "y": 15, "w": 80, "h": 55},
            coordinate_space="pdf_points_top_left",
            sequence_in_page=0,
            container_path=["page:1", "geometry:0"],
            source_anchor={
                "kind": "pdf_geometry",
                "section_index": None,
                "paragraph_index": None,
                "control_index": None,
                "table_block_id": None,
                "cell_path": [],
            },
            region_kind="vector_diagram",
            placement_status="page_bbox_verified",
        )
        repeated = crop_page_region(
            repeated_base,
            page_image=self.private_root / "page.png",
            private_root=self.private_root,
            coordinate_page_bbox={"x": 0, "y": 0, "w": 120, "h": 120},
            render_profile={"renderer": "fixture", "version": "1"},
        )
        self.assertEqual(repeated["crop_sha256"], self.eligible["crop_sha256"])
        self._write_occurrences([self.eligible, repeated])

        adapter = self._ocr_adapter()
        summary = self._run(ocr_adapter=adapter)
        evidence = self._read_jsonl("ocr-evidence-v1.jsonl")

        self.assertEqual(adapter.calls, 1)
        self.assertEqual(summary["counts"]["eligible_occurrence"], 2)
        self.assertEqual(len(evidence), 2)
        self.assertEqual(
            {record["occurrence_id"] for record in evidence},
            {self.eligible["occurrence_id"], repeated["occurrence_id"]},
        )
        self.assertEqual(len({record["evidence_id"] for record in evidence}), 2)

    def test_caption_lane_keeps_supported_claims_and_enforces_weight_cap(self) -> None:
        ocr_adapter = self._ocr_adapter()
        caption_adapter = self._caption_adapter()
        summary = self._run(
            ocr_adapter=ocr_adapter,
            caption_adapter=caption_adapter,
        )

        self.assertEqual(ocr_adapter.calls, 1)
        self.assertEqual(caption_adapter.calls, 1)
        self.assertTrue(summary["caption_enabled"])
        captions = self._read_jsonl("caption-evidence-v1.jsonl")
        self.assertEqual(captions[0]["claims"][0]["status"], "supported")
        self.assertEqual(captions[0]["claims"][0]["support_refs"], ["source:verified"])
        caption_chunks = [
            chunk
            for chunk in self._read_jsonl("visual-chunks-v1.jsonl")
            if chunk["evidence_type"] == "caption"
        ]
        self.assertEqual(len(caption_chunks), 1)
        self.assertLessEqual(caption_chunks[0]["retrieval_weight"], 0.35)
        self.assertEqual(summary["counts"]["caption_evidence"], 1)

    def test_stale_identity_corrupt_cache_and_corrupt_output_fail_closed(self) -> None:
        self._run(ocr_adapter=self._ocr_adapter())

        self._write_occurrences([self.eligible])
        with self.assertRaisesRegex(VisualUnderstandingBatchError, "visual_batch_stale_identity"):
            self._run(ocr_adapter=self._ocr_adapter())

        self._write_occurrences([self.eligible, self.ineligible])
        cache_path = next((self.output_root / "cache" / "ocr").glob("*.json"))
        original_cache = cache_path.read_bytes()
        cache_path.write_text("{not-json", encoding="utf-8")
        with self.assertRaisesRegex(VisualUnderstandingBatchError, "visual_batch_ocr_cache_corrupt"):
            self._run(ocr_adapter=self._ocr_adapter())

        cache_path.write_bytes(original_cache)
        artifact = self.output_root / "ocr-evidence-v1.jsonl"
        artifact.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(
            VisualUnderstandingBatchError, "visual_batch_artifact_corrupt_or_stale"
        ):
            self._run(ocr_adapter=self._ocr_adapter())

    def test_path_escape_is_rejected_before_inference(self) -> None:
        outside = self.private_root.parent / "outside-understanding"
        adapter = self._ocr_adapter()
        with self.assertRaisesRegex(VisualUnderstandingBatchError, "output_root_escape"):
            run_visual_understanding_batch(
                private_root=self.private_root,
                occurrences_path=self.occurrences_path,
                output_root=outside,
                adapter_code_sha256=ADAPTER_CODE_SHA256,
                ocr_adapter=adapter,
                ocr_config=self.ocr_config,
                policy=self.policy,
            )
        self.assertEqual(adapter.calls, 0)


if __name__ == "__main__":
    unittest.main()
