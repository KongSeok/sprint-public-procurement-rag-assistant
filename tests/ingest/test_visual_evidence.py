from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator
from PIL import Image

from midprojectrag.ingest.visual_evidence import (
    VisualEvidenceError,
    build_visual_corpus_metadata,
    crop_page_region,
    make_visual_occurrence,
    validate_visual_occurrence,
)


ROOT = Path(__file__).resolve().parents[2]
DOC_ID = "doc_0123456789abcdef01234567"
SOURCE_SHA = "a" * 64
OBJECT_SHA = "b" * 64


class VisualEvidenceV2Tests(unittest.TestCase):
    def _schema(self, name: str) -> dict:
        value = json.loads((ROOT / "contracts" / name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(value)
        return value

    def _occurrence(self) -> dict:
        return make_visual_occurrence(
            doc_id=DOC_ID,
            source_sha256=SOURCE_SHA,
            page=2,
            bbox={"x": 10, "y": 20, "w": 30, "h": 40},
            coordinate_space="rhwp_css_px_96dpi",
            sequence_in_page=3,
            container_path=["body", "paragraph:4", "control:1"],
            source_anchor={
                "kind": "body",
                "section_index": 0,
                "paragraph_index": 4,
                "control_index": 1,
                "table_block_id": None,
                "cell_path": [],
            },
            region_kind="raster_image",
            placement_status="page_bbox_verified",
            source_object_status="exact_resource_link",
            source_image_key="binData:7",
            source_object_sha256=OBJECT_SHA,
            source_object_media_type="image/png",
            link_method="document_resource_key",
            match_evidence=["document_resource_key"],
        )

    def test_all_new_schemas_are_valid(self) -> None:
        for name in (
            "visual-occurrence-v2.schema.json",
            "ocr-evidence-v1.schema.json",
            "caption-evidence-v1.schema.json",
            "visual-chunk-v1.schema.json",
            "visual-corpus-v2-metadata.schema.json",
        ):
            self._schema(name)

    def test_occurrence_is_stable_and_schema_valid(self) -> None:
        first = self._occurrence()
        second = self._occurrence()
        self.assertEqual(first, second)
        validate_visual_occurrence(first)
        Draft202012Validator(
            self._schema("visual-occurrence-v2.schema.json")
        ).validate(first)

    def test_occurrence_id_does_not_depend_on_crop(self) -> None:
        occurrence = self._occurrence()
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            page = root / "page.png"
            Image.new("RGB", (100, 100), (250, 250, 250)).save(page)
            promoted = crop_page_region(
                occurrence,
                page_image=page,
                private_root=root / "private",
                coordinate_page_bbox={"x": 0, "y": 0, "w": 100, "h": 100},
                render_profile={"renderer": "synthetic", "scale": 1},
            )
            repeated = crop_page_region(
                occurrence,
                page_image=page,
                private_root=root / "private",
                coordinate_page_bbox={"x": 0, "y": 0, "w": 100, "h": 100},
                render_profile={"renderer": "synthetic", "scale": 1},
            )
            self.assertEqual(occurrence["occurrence_id"], promoted["occurrence_id"])
            self.assertEqual(promoted, repeated)
            self.assertEqual(promoted["retrieval_status"], "eligible")
            self.assertTrue((root / "private" / promoted["crop_relpath"]).is_file())
            Draft202012Validator(
                self._schema("visual-occurrence-v2.schema.json")
            ).validate(promoted)

    def test_render_only_crop_is_eligible_but_ambiguous_is_withheld(self) -> None:
        render_only = make_visual_occurrence(
            doc_id=DOC_ID,
            source_sha256=SOURCE_SHA,
            page=1,
            bbox={"x": 0, "y": 0, "w": 10, "h": 10},
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
        ambiguous = dict(render_only)
        ambiguous["source_object_status"] = "ambiguous"
        ambiguous["region_kind"] = "ambiguous"
        ambiguous["occurrence_id"] = make_visual_occurrence(
            doc_id=DOC_ID,
            source_sha256=SOURCE_SHA,
            page=1,
            bbox={"x": 0, "y": 0, "w": 10, "h": 10},
            coordinate_space="pdf_points_top_left",
            sequence_in_page=0,
            container_path=["page:1", "geometry:0"],
            source_anchor=render_only["source_anchor"],
            region_kind="ambiguous",
            placement_status="page_bbox_verified",
            source_object_status="ambiguous",
        )["occurrence_id"]
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            page = root / "page.png"
            page_image = Image.new("RGB", (100, 100), "white")
            page_image.putpixel((2, 2), (20, 40, 60))
            page_image.save(page)
            promoted = crop_page_region(
                render_only,
                page_image=page,
                private_root=root / "private-a",
                coordinate_page_bbox={"x": 0, "y": 0, "w": 100, "h": 100},
                render_profile={"renderer": "synthetic"},
            )
            withheld = crop_page_region(
                ambiguous,
                page_image=page,
                private_root=root / "private-b",
                coordinate_page_bbox={"x": 0, "y": 0, "w": 100, "h": 100},
                render_profile={"renderer": "synthetic"},
            )
        self.assertEqual(promoted["source_object_status"], "render_only")
        self.assertEqual(promoted["retrieval_status"], "eligible")
        self.assertEqual(withheld["retrieval_status"], "withheld")

    def test_crop_rejects_pure_white_visual_evidence(self) -> None:
        occurrence = self._occurrence()
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            page = root / "page.png"
            Image.new("RGB", (100, 100), "white").save(page)
            with self.assertRaisesRegex(VisualEvidenceError, "^visual_crop_blank$"):
                crop_page_region(
                    occurrence,
                    page_image=page,
                    private_root=root / "private",
                    coordinate_page_bbox={"x": 0, "y": 0, "w": 100, "h": 100},
                    render_profile={"renderer": "synthetic"},
                )

    def test_validator_rejects_false_eligible_asset_only(self) -> None:
        occurrence = self._occurrence()
        occurrence.update(
            {
                "page": None,
                "bbox": None,
                "coordinate_space": None,
                "sequence_in_page": None,
                "placement_status": "doc_only_unlinked",
                "retrieval_status": "eligible",
            }
        )
        with self.assertRaisesRegex(VisualEvidenceError, "visual_occurrence_contract_invalid"):
            validate_visual_occurrence(occurrence)

    def test_corpus_metadata_binds_code_config_and_artifacts(self) -> None:
        occurrence = self._occurrence()
        metadata = build_visual_corpus_metadata(
            source_manifest_sha256="c" * 64,
            adapter_code_sha256="d" * 64,
            config={"profile": "local"},
            dependency_versions={"pypdf": "6.0.0"},
            occurrences=[occurrence],
            ocr_count=0,
            caption_count=0,
            chunk_count=0,
            artifact_hashes={"occurrences": "e" * 64},
        )
        self.assertEqual(metadata["external_api_calls"], 0)
        self.assertFalse(metadata["private_egress"])
        Draft202012Validator(
            self._schema("visual-corpus-v2-metadata.schema.json")
        ).validate(metadata)


if __name__ == "__main__":
    unittest.main()
