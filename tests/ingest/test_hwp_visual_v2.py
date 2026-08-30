from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from midprojectrag.ingest.common import canonical_json
from midprojectrag.ingest.hwp_visual_v2 import (
    COORDINATE_SPACE,
    HwpVisualV2Error,
    parse_hwp_helper_occurrences,
    recover_hwp_occurrences,
    top_level_hwp_occurrences,
)


DOC_ID = "doc_0123456789abcdef01234567"
SOURCE_SHA256 = hashlib.sha256(b"synthetic-hwp-document").hexdigest()
TABLE_BLOCK_ID = "block_0123456789abcdef01234567"


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _body_anchor(
    *, paragraph: int | None = 3, control: int | None = 4
) -> dict[str, object]:
    return {
        "kind": "body",
        "section_index": 0,
        "paragraph_index": paragraph,
        "control_index": control,
        "table_block_id": None,
        "cell_path": [],
    }


def _nested_anchor() -> dict[str, object]:
    return {
        "kind": "table_nested",
        "section_index": 0,
        "paragraph_index": 8,
        "control_index": 2,
        "table_block_id": TABLE_BLOCK_ID,
        "cell_path": [
            {
                "control_index": 2,
                "cell_index": 5,
                "cell_paragraph_index": 1,
                "row": 1,
                "column": 2,
            },
            {
                "control_index": 0,
                "cell_index": 3,
                "cell_paragraph_index": 0,
                "row": None,
                "column": None,
            },
        ],
    }


def _source(
    ordinal: int,
    *,
    key: str | None,
    raw: str | None = None,
    rgba: str | None = None,
    supported: bool = True,
    media_type: str = "image/png",
    anchor: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "doc_id": DOC_ID,
        "source_ordinal": ordinal,
        "source_image_key": key,
        "source_object_sha256": raw or _digest(f"source-{ordinal}"),
        "source_object_media_type": media_type,
        "normalized_rgba_sha256": rgba,
        "supported": supported,
        "source_anchor": anchor if anchor is not None else _body_anchor(),
    }


def _helper(
    ordinal: int,
    *,
    key: str | None,
    source_resource_sha256: str | None = None,
    embedded_raw_sha256: str | None = None,
    rgba_sha256: str | None = None,
    bbox: dict[str, float] | None = None,
    match_bbox: dict[str, float] | None = None,
    page: int = 1,
    sequence: int | None = None,
    anchor: dict[str, object] | None = None,
) -> dict[str, object]:
    if bbox is None:
        bbox = {"x": 10.0, "y": 20.0 + ordinal, "w": 80.0, "h": 40.0}
    if sequence is None:
        sequence = ordinal
    if key is not None and source_resource_sha256 is None:
        source_resource_sha256 = _digest(f"source-{ordinal}")
    if match_bbox is None and (embedded_raw_sha256 is not None or rgba_sha256 is not None):
        match_bbox = dict(bbox)
    return {
        "schema_version": "1.0",
        "doc_id": DOC_ID,
        "render_occurrence_key": f"page:{page}:image:{ordinal}",
        "page": page,
        "bbox": bbox,
        "coordinate_space": COORDINATE_SPACE,
        "sequence_in_page": sequence,
        "source_image_key": key,
        "source_resource_sha256": source_resource_sha256,
        "embedded_raw_sha256": embedded_raw_sha256,
        "normalized_rgba_sha256": rgba_sha256,
        "match_bbox": match_bbox,
        "source_anchor": anchor if anchor is not None else _body_anchor(),
    }


class HwpVisualV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        schema_path = (
            Path(__file__).resolve().parents[2]
            / "contracts"
            / "visual-occurrence-v2.schema.json"
        )
        cls.schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema)

    def _recover(
        self,
        helpers: list[dict[str, object]],
        sources: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        records = recover_hwp_occurrences(
            doc_id=DOC_ID,
            source_sha256=SOURCE_SHA256,
            helper_payload={"schema_version": "1.0", "occurrences": helpers},
            source_objects=sources,
        )
        for record in records:
            self.validator.validate(record)
        return records

    def test_document_local_key_reuse_links_one_object_to_81_occurrences(self) -> None:
        raw = _digest("shared-source")
        source = _source(0, key="bindata:7", raw=raw)
        helpers = [
            _helper(
                ordinal,
                key="bindata:7",
                source_resource_sha256=raw,
                page=(ordinal // 9) + 1,
                sequence=ordinal % 9,
                bbox={
                    "x": 10.0 + (ordinal % 3),
                    "y": 20.0 + ordinal,
                    "w": 80.0,
                    "h": 40.0,
                },
            )
            for ordinal in range(81)
        ]

        first = self._recover(helpers, [source])
        second = self._recover(list(reversed(helpers)), [source])

        self.assertEqual(first, second)
        self.assertEqual(len(first), 81)
        self.assertEqual(len({row["occurrence_id"] for row in first}), 81)
        self.assertEqual(len({row["source_object_id"] for row in first}), 1)
        self.assertTrue(
            all(row["source_object_status"] == "exact_resource_link" for row in first)
        )
        self.assertTrue(
            all(row["link_method"] == "document_resource_key" for row in first)
        )

    def test_stretched_image_still_links_by_resource_key(self) -> None:
        raw = _digest("stretched-source")
        source = _source(0, key="bindata:11", raw=raw)
        helper = _helper(
            0,
            key="bindata:11",
            source_resource_sha256=raw,
            bbox={"x": 2.0, "y": 4.0, "w": 303.3, "h": 37.8},
        )

        record = self._recover([helper], [source])[0]

        self.assertEqual(record["source_object_status"], "exact_resource_link")
        self.assertEqual(record["link_method"], "document_resource_key")
        self.assertEqual(record["bbox"], helper["bbox"])

    def test_six_sources_five_renders_preserve_one_doc_only_source(self) -> None:
        sources = [_source(index, key=f"bindata:{index}") for index in range(6)]
        helpers = [
            _helper(
                index,
                key=f"bindata:{index}",
                source_resource_sha256=sources[index]["source_object_sha256"],
            )
            for index in range(5)
        ]

        records = self._recover(helpers, sources)
        placed = [row for row in records if row["placement_status"] == "page_bbox_verified"]
        doc_only = [row for row in records if row["placement_status"] == "doc_only_unlinked"]

        self.assertEqual(len(records), 6)
        self.assertEqual(len(placed), 5)
        self.assertEqual(len(doc_only), 1)
        self.assertEqual(doc_only[0]["source_image_key"], "bindata:5")
        self.assertIn("source_object_without_render_occurrence", doc_only[0]["warnings"])

    def test_unsupported_source_does_not_poison_supported_sibling(self) -> None:
        png_raw = _digest("supported-png")
        wmf_raw = _digest("unsupported-wmf")
        sources = [
            _source(0, key="bindata:1", raw=png_raw),
            _source(
                1,
                key="bindata:2",
                raw=wmf_raw,
                supported=False,
                media_type="image/wmf",
            ),
        ]
        helpers = [
            _helper(0, key="bindata:1", source_resource_sha256=png_raw),
            _helper(1, key="bindata:2", source_resource_sha256=wmf_raw),
        ]

        records = self._recover(helpers, sources)

        self.assertEqual(records[0]["source_object_status"], "exact_resource_link")
        self.assertEqual(records[0]["retrieval_status"], "withheld")
        self.assertEqual(records[1]["source_object_status"], "unsupported")
        self.assertEqual(records[1]["retrieval_status"], "quarantined")

    def test_ambiguous_duplicate_pixels_never_choose_a_source_reference(self) -> None:
        rgba = _digest("same-decoded-pixels")
        sources = [
            _source(0, key="bindata:a", raw=_digest("raw-a"), rgba=rgba),
            _source(1, key="bindata:b", raw=_digest("raw-b"), rgba=rgba),
        ]
        helper = _helper(0, key=None, rgba_sha256=rgba)

        records = self._recover([helper], sources)
        placed = records[0]

        self.assertEqual(placed["source_object_status"], "ambiguous")
        self.assertIsNone(placed["source_object_id"])
        self.assertEqual(placed["link_method"], "none")
        self.assertEqual(
            placed["match_evidence"],
            ["normalized_rgba_sha256", "bbox_exact"],
        )
        self.assertEqual(
            placed["warnings"], ["normalized_rgba_sha256_candidate_ambiguous"]
        )
        self.assertEqual(
            sum(row["placement_status"] == "doc_only_unlinked" for row in records),
            2,
        )

    def test_missing_paragraph_and_control_indices_do_not_block_exact_key(self) -> None:
        raw = _digest("missing-pi-ci")
        anchor = _body_anchor(paragraph=None, control=None)
        source = _source(0, key="bindata:missing", raw=raw, anchor=anchor)
        helper = _helper(
            0,
            key="bindata:missing",
            source_resource_sha256=raw,
            anchor=anchor,
        )

        record = self._recover([helper], [source])[0]

        self.assertEqual(record["source_object_status"], "exact_resource_link")
        self.assertIsNone(record["source_anchor"]["paragraph_index"])
        self.assertIsNone(record["source_anchor"]["control_index"])

    def test_nested_cell_path_is_exact_and_never_duplicated_top_level(self) -> None:
        body_raw = _digest("body-image")
        nested_raw = _digest("nested-image")
        nested_anchor = _nested_anchor()
        sources = [
            _source(0, key="bindata:body", raw=body_raw),
            _source(1, key="bindata:nested", raw=nested_raw, anchor=nested_anchor),
        ]
        helpers = [
            _helper(0, key="bindata:body", source_resource_sha256=body_raw),
            _helper(
                1,
                key="bindata:nested",
                source_resource_sha256=nested_raw,
                anchor=nested_anchor,
            ),
        ]

        records = self._recover(helpers, sources)
        nested = records[1]
        top_level = top_level_hwp_occurrences(records)

        self.assertEqual(nested["region_kind"], "table_child_image")
        self.assertEqual(nested["source_anchor"], nested_anchor)
        self.assertEqual(
            nested["container_path"],
            [
                f"table:{TABLE_BLOCK_ID}",
                "section:0",
                "paragraph:8",
                "control:2",
                "cell:2:5:1:1:2",
                "cell:0:3:0:null:null",
            ],
        )
        self.assertEqual(len(top_level), 1)
        self.assertEqual(top_level[0]["source_image_key"], "bindata:body")
        self.assertNotIn(nested["occurrence_id"], {row["occurrence_id"] for row in top_level})

    def test_unique_raw_sha_and_exact_bbox_promote_visual_match(self) -> None:
        raw = _digest("raw-exact")
        source = _source(0, key="bindata:raw", raw=raw)
        helper = _helper(0, key=None, embedded_raw_sha256=raw)

        record = self._recover([helper], [source])[0]

        self.assertEqual(record["source_object_status"], "verified_exact_visual_match")
        self.assertEqual(record["link_method"], "raw_sha256_bbox_exact")
        self.assertEqual(
            record["match_evidence"],
            ["raw_sha256", "bbox_exact", "unique_candidate"],
        )

    def test_unique_rgba_sha_and_exact_bbox_promote_visual_match(self) -> None:
        rgba = _digest("rgba-exact")
        source = _source(0, key="bindata:rgba", rgba=rgba)
        helper = _helper(0, key=None, rgba_sha256=rgba)

        record = self._recover([helper], [source])[0]

        self.assertEqual(record["source_object_status"], "verified_exact_visual_match")
        self.assertEqual(record["link_method"], "rgba_sha256_bbox_exact")
        self.assertEqual(
            record["match_evidence"],
            ["normalized_rgba_sha256", "bbox_exact", "unique_candidate"],
        )

    def test_fallback_digest_without_exact_bbox_remains_render_only(self) -> None:
        raw = _digest("raw-with-wrong-bbox")
        source = _source(0, key="bindata:wrong-bbox", raw=raw)
        helper = _helper(
            0,
            key=None,
            embedded_raw_sha256=raw,
            match_bbox={"x": 11.0, "y": 20.0, "w": 80.0, "h": 40.0},
        )

        records = self._recover([helper], [source])

        self.assertEqual(records[0]["source_object_status"], "render_only")
        self.assertEqual(records[0]["link_method"], "render_region_only")
        self.assertEqual(records[0]["warnings"], ["exact_visual_match_bbox_mismatch"])
        self.assertEqual(records[1]["placement_status"], "doc_only_unlinked")

    def test_none_helper_is_optional_and_preserves_source_inventory(self) -> None:
        source = _source(0, key="bindata:inventory")

        records = recover_hwp_occurrences(
            doc_id=DOC_ID,
            source_sha256=SOURCE_SHA256,
            helper_payload=None,
            source_objects=[source],
        )

        self.assertEqual(len(records), 1)
        self.validator.validate(records[0])
        self.assertEqual(records[0]["placement_status"], "doc_only_unlinked")

    def test_keyless_render_without_exact_fingerprint_stays_render_only(self) -> None:
        record = self._recover([_helper(0, key=None)], [])[0]

        self.assertEqual(record["source_object_status"], "render_only")
        self.assertEqual(record["link_method"], "render_region_only")
        self.assertEqual(record["warnings"], ["source_identity_evidence_missing"])

    def test_jsonl_parser_is_deterministic_and_fails_closed(self) -> None:
        first = _helper(0, key="bindata:0")
        second = _helper(1, key="bindata:1", page=2)
        payload = "\n".join(canonical_json(row) for row in reversed([first, second]))

        parsed = parse_hwp_helper_occurrences(payload, doc_id=DOC_ID)

        self.assertEqual(
            [row["render_occurrence_key"] for row in parsed],
            [first["render_occurrence_key"], second["render_occurrence_key"]],
        )
        invalid = dict(first)
        invalid["unexpected"] = True
        with self.assertRaisesRegex(
            HwpVisualV2Error, "hwp_visual_v2_helper_record_invalid"
        ):
            parse_hwp_helper_occurrences([invalid], doc_id=DOC_ID)


if __name__ == "__main__":
    unittest.main()
