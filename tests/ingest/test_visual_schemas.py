from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]


class VisualSchemaTests(unittest.TestCase):
    def _schema(self, name: str) -> dict:
        value = json.loads((ROOT / "contracts" / name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(value)
        return value

    def test_table_visual_schema_accepts_verified_schedule(self) -> None:
        schema = self._schema("table-visual-overlay.schema.json")
        bbox = {"x": 1.0, "y": 2.0, "w": 3.0, "h": 4.0}
        record = {
            "schema_version": "1.0",
            "doc_id": "doc_0123456789abcdef01234567",
            "block_id": "block_0123456789abcdef01234567",
            "structure_sha256": "a" * 64,
            "status": "verified_render",
            "page_start": 7,
            "page_end": 7,
            "coordinate_space": "rhwp_css_px_96dpi",
            "render_key": {"section": 0, "paragraph": 1, "control": 0},
            "page_contexts": [{"page": 7, "sequence_in_page": 1, "bbox": bbox, "preceding_text": None}],
            "background_cells": [{"page": 7, "row": 2, "col": 3, "bbox": bbox, "kind": "background_present"}],
            "schedule_facts": [{
                "row": 2, "label": "synthetic task", "periods": ["M+2"],
                "text": "synthetic task: M+2",
                "evidence_cells": [{"page": 7, "row": 2, "col": 3, "bbox": bbox, "period": "M+2"}],
            }],
        }
        Draft202012Validator(schema).validate(record)

    def test_ordered_occurrence_schema_rejects_cross_type_links(self) -> None:
        schema = self._schema("ordered-visual-occurrence.schema.json")
        record = {
            "schema_version": "1.0",
            "ordered_occurrence_id": "vocc_0123456789abcdef01234567",
            "doc_id": "doc_0123456789abcdef01234567",
            "page": 1,
            "sequence_in_page": 1,
            "node_type": "table",
            "status": "verified_table_link",
            "bbox": {"x": 1.0, "y": 2.0, "w": 3.0, "h": 4.0},
            "coordinate_space": "rhwp_css_px_96dpi",
            "render_key": {"section": 0, "paragraph": 1, "control": 0},
            "text": None,
            "linked_block_id": "block_0123456789abcdef01234567",
            "linked_image_occurrence_id": None,
            "preceding_text": None,
            "link_method": "table_overlay_page_sequence_bbox_render_key_exact",
        }
        validator = Draft202012Validator(schema)
        validator.validate(record)
        invalid = dict(record)
        invalid["linked_block_id"] = None
        self.assertTrue(list(validator.iter_errors(invalid)))
        cross_type = dict(record)
        cross_type["linked_image_occurrence_id"] = "occ_0123456789abcdef01234567"
        self.assertTrue(list(validator.iter_errors(cross_type)))
        zero_area = dict(record)
        zero_area["bbox"] = {"x": 1.0, "y": 2.0, "w": 0.0, "h": 4.0}
        self.assertTrue(list(validator.iter_errors(zero_area)))

    def test_image_and_metadata_schemas_accept_verified_records(self) -> None:
        image_schema = self._schema("hwp-image-evidence.schema.json")
        bbox = {"x": 1.0, "y": 2.0, "w": 3.0, "h": 4.0}
        image = {
            "schema_version": "1.0", "occurrence_id": "occ_0123456789abcdef01234567",
            "doc_id": "doc_0123456789abcdef01234567", "ordinal": 0, "node_type": "image",
            "status": "verified_asset_render", "asset_id": "asset_0123456789abcdef01234567",
            "asset_sha256": "b" * 64, "asset_relpath": f"objects/{'b' * 64}.png", "media_type": "image/png",
            "byte_size": 10, "width": 3, "height": 4, "page_start": 1, "page_end": 1,
            "source_asset_sha256": "b" * 64, "source_byte_size": 10,
            "source_media_type": "image/png", "source_extension": ".png", "normalizations": [],
            "bbox": bbox, "coordinate_space": "rhwp_css_px_96dpi",
            "render_key": {"section": 0, "paragraph": 1, "control": 0},
            "sequence_in_page": 1, "image_ordinal_in_page": 0, "container_kind": "body",
            "preceding_text": None,
            "link_method": "doclang_picture_render_image_global_ordinal_exact_count",
            "doclang_loss_count": 0, "warnings": [],
        }
        image_validator = Draft202012Validator(image_schema)
        image_validator.validate(image)
        invalid_link_method = dict(image)
        invalid_link_method["link_method"] = "doclang_picture_unlinked"
        self.assertTrue(list(image_validator.iter_errors(invalid_link_method)))
        oversized_image = dict(image)
        oversized_image["width"] = 100001
        self.assertTrue(list(image_validator.iter_errors(oversized_image)))

        unsupported = dict(image)
        unsupported.update({
            "occurrence_id": "occ_abcdef0123456789abcdef01",
            "status": "unsupported_source_asset",
            "asset_id": None, "asset_sha256": None, "asset_relpath": None,
            "media_type": None, "byte_size": None, "width": None, "height": None,
            "source_asset_sha256": "c" * 64, "source_byte_size": 24,
            "source_media_type": "image/wmf", "source_extension": ".wmf",
            "normalizations": [], "page_start": None, "page_end": None,
            "bbox": None, "coordinate_space": None, "render_key": None,
            "sequence_in_page": None, "image_ordinal_in_page": None,
            "container_kind": None, "preceding_text": None,
            "link_method": "doclang_picture_unsupported_unlinked",
            "warnings": ["image_format_unsupported"],
        })
        image_validator.validate(unsupported)
        unsafe_unsupported = dict(unsupported)
        unsafe_unsupported["asset_relpath"] = f"objects/{'c' * 64}.wmf"
        self.assertTrue(list(image_validator.iter_errors(unsafe_unsupported)))

        metadata_schema = self._schema("visual-bundle-metadata.schema.json")
        metadata = {
            "schema_version": "1.0", "doc_id": image["doc_id"],
            "method": "rhwp-ordered-visual-evidence-v1", "coordinate_space": "rhwp_css_px_96dpi",
            "source_sha256": "1" * 64, "rhwp_binary_sha256": "2" * 64,
            "config_sha256": "3" * 64, "blocks_sha256": "4" * 64,
            "layout_records_sha256": "5" * 64, "table_artifact_sha256": "6" * 64,
            "image_artifact_sha256": "7" * 64, "ordered_artifact_sha256": "8" * 64,
            "asset_object_manifest_sha256": "9" * 64,
            "artifact_set_id": "visual_0123456789abcdef01234567", "page_count": 1,
            "tables": 1, "images": 1, "ordered_occurrences": 1,
            "asset_count": 1, "asset_reference_count": 1, "asset_bytes": 10,
            "asset_references_reconciled": True,
            "table_status_counts": {"verified_render": 1},
            "image_status_counts": {"verified_asset_render": 1},
            "ordered_status_counts": {"verified_image_link": 1},
        }
        Draft202012Validator(metadata_schema).validate(metadata)

        corpus_schema = self._schema("visual-corpus-rollout.schema.json")
        image_counts = corpus_schema["$defs"]["imageStatusCounts"]
        Draft202012Validator(image_counts).validate({"unsupported_source_asset": 1})
        self.assertTrue(
            list(
                Draft202012Validator(image_counts).iter_errors(
                    {"unsupported_source_asset": 0}
                )
            )
        )


if __name__ == "__main__":
    unittest.main()
