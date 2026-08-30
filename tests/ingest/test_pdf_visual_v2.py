from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from jsonschema import Draft202012Validator
from PIL import Image

from midprojectrag.ingest.pdf_visual_v2 import (
    METADATA_ARTIFACT,
    OBJECT_MANIFEST_ARTIFACT,
    OCCURRENCE_ARTIFACT,
    RESOURCE_ARTIFACT,
    PdfVisualV2Error,
    PdfVisualV2Limits,
    collect_pypdf_image_resources,
    materialize_pdf_visual_v2_corpus,
    recover_pdf_visual_page,
)
from midprojectrag.ingest.visual_evidence import (
    source_object_id,
    validate_visual_occurrence,
)


ROOT = Path(__file__).resolve().parents[2]
DOC_ID = "doc_0123456789abcdef01234567"
SOURCE_SHA256 = "1" * 64
SOURCE_MANIFEST_SHA256 = "2" * 64
ADAPTER_SHA256 = "3" * 64
CONFIG_SHA256 = "4" * 64
DEPENDENCIES = {
    "Pillow": "fixture-12",
    "pdfplumber": "supplied-records-only",
    "pypdf": "fixture-6",
}


def _png(
    color: tuple[int, int, int] = (20, 40, 60),
    size: tuple[int, int] = (4, 3),
) -> tuple[bytes, Image.Image]:
    image = Image.new("RGB", size, color)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=False, compress_level=9)
    return output.getvalue(), image


class _Ref:
    def __init__(self, idnum: int, generation: int, value) -> None:
        self.idnum = idnum
        self.generation = generation
        self._value = value

    def get_object(self):
        return self._value


class _Stream(dict):
    def __init__(self, *args, data: bytes | None = None, image=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._data = data
        self.image = image
        self.indirect_reference = None

    def get_data(self) -> bytes:
        if self._data is None:
            raise AssertionError("stream has no bytes")
        return self._data


class _Images:
    def __init__(self, entries) -> None:
        self._entries = list(entries)

    def keys(self):
        return [key for key, _ in self._entries]

    def __getitem__(self, key):
        for candidate, value in self._entries:
            if candidate == key:
                return value
        raise KeyError(key)


class _Page:
    def __init__(self, entries) -> None:
        self.images = _Images(entries)


def _image_file(
    *,
    name: str,
    idnum: int | None,
    color: tuple[int, int, int] = (20, 40, 60),
    size: tuple[int, int] = (4, 3),
    is_inline: bool = False,
    xobject: _Stream | None = None,
):
    data, image = _png(color, size)
    if xobject is None:
        xobject = _Stream({"/Width": size[0], "/Height": size[1]})
    reference = None if idnum is None else _Ref(idnum, 0, xobject)
    xobject.indirect_reference = reference
    return SimpleNamespace(
        name=name,
        data=data,
        image=image,
        indirect_reference=reference,
        is_inline=is_inline,
        is_displayed=True,
    )


def _placements() -> list[dict[str, object]]:
    return [
        {
            "name": "Im1",
            "srcsize": [4, 3],
            "x0": 10,
            "top": 20,
            "x1": 50,
            "bottom": 50,
        },
        {
            "name": "Im1",
            "srcsize": [4, 3],
            "x0": 70,
            "top": 80,
            "x1": 110,
            "bottom": 110,
        },
    ]


class PdfVisualV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.occurrence_schema = json.loads(
            (ROOT / "contracts" / "visual-occurrence-v2.schema.json").read_text(
                encoding="utf-8"
            )
        )
        cls.metadata_schema = json.loads(
            (ROOT / "contracts" / "visual-corpus-v2-metadata.schema.json").read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator.check_schema(cls.occurrence_schema)
        Draft202012Validator.check_schema(cls.metadata_schema)

    def _page(self) -> _Page:
        return _Page([("/Im1", _image_file(name="Im1.png", idnum=10))])

    def _document(self, page: _Page | None = None) -> dict[str, object]:
        return {
            "doc_id": DOC_ID,
            "source_sha256": SOURCE_SHA256,
            "pages": [
                {
                    "page_number": 1,
                    "pypdf_page": page or self._page(),
                    "placements": _placements(),
                    "table_candidates": [],
                    "vector_candidates": [],
                }
            ],
        }

    def _materialize(self, private_root: Path, output_name: str, *, adapter=ADAPTER_SHA256):
        return materialize_pdf_visual_v2_corpus(
            documents=[self._document()],
            output_dir=(private_root / output_name).resolve(),
            private_root=private_root.resolve(),
            source_manifest_sha256=SOURCE_MANIFEST_SHA256,
            adapter_code_sha256=adapter,
            config_sha256=CONFIG_SHA256,
            dependency_versions=DEPENDENCIES,
        )

    def test_one_resource_preserves_one_to_many_repeated_placements(self) -> None:
        recovery = recover_pdf_visual_page(
            page=self._page(),
            doc_id=DOC_ID,
            source_sha256=SOURCE_SHA256,
            page_number=1,
            placements=_placements(),
        )

        self.assertEqual(len(recovery.resources), 1)
        self.assertEqual(len(recovery.occurrences), 2)
        first, second = recovery.occurrences
        self.assertNotEqual(first["occurrence_id"], second["occurrence_id"])
        self.assertEqual(first["source_object_id"], second["source_object_id"])
        self.assertEqual(
            first["source_object_id"], source_object_id(first["source_object_sha256"])
        )
        self.assertEqual(first["source_image_key"], "Im1")
        self.assertEqual(second["source_image_key"], "Im1")
        self.assertEqual(
            [first["region_kind"], second["region_kind"]],
            ["raster_image", "raster_image"],
        )
        self.assertEqual(
            [first["sequence_in_page"], second["sequence_in_page"]], [0, 1]
        )
        for occurrence in recovery.occurrences:
            Draft202012Validator(self.occurrence_schema).validate(occurrence)
            validate_visual_occurrence(occurrence)
            self.assertEqual(occurrence["source_object_status"], "exact_resource_link")
            self.assertEqual(occurrence["link_method"], "document_resource_key")
            self.assertEqual(
                occurrence["match_evidence"],
                ["document_resource_key", "unique_candidate"],
            )

    def test_table_contained_image_has_exact_parent_and_no_top_level_duplication(self) -> None:
        recovery = recover_pdf_visual_page(
            page=self._page(),
            doc_id=DOC_ID,
            source_sha256=SOURCE_SHA256,
            page_number=1,
            placements=[
                {
                    "resource_path": ["Im1"],
                    "bbox": {"x": 20, "y": 30, "w": 10, "h": 10},
                }
            ],
            table_candidates=[
                {
                    "verified": True,
                    "bbox": {"x": 10, "y": 20, "w": 100, "h": 80},
                }
            ],
        )

        self.assertEqual(len(recovery.occurrences), 2)
        table = next(row for row in recovery.occurrences if row["region_kind"] == "table")
        child = next(
            row for row in recovery.occurrences if row["region_kind"] == "table_child_image"
        )
        self.assertEqual(child["parent_occurrence_id"], table["occurrence_id"])
        self.assertNotIn(
            "raster_image", [row["region_kind"] for row in recovery.occurrences]
        )
        Draft202012Validator(self.occurrence_schema).validate(table)
        Draft202012Validator(self.occurrence_schema).validate(child)

    def test_non_unique_resource_name_match_remains_ambiguous(self) -> None:
        page = _Page(
            [
                (("FormA", "Im1"), _image_file(name="Im1.png", idnum=11)),
                (("FormB", "Im1"), _image_file(name="Im1.png", idnum=12)),
            ]
        )
        recovery = recover_pdf_visual_page(
            page=page,
            doc_id=DOC_ID,
            source_sha256=SOURCE_SHA256,
            page_number=1,
            placements=[
                {
                    "name": "Im1",
                    "srcsize": [4, 3],
                    "bbox": {"x": 10, "y": 20, "w": 40, "h": 30},
                }
            ],
        )

        self.assertEqual(len(recovery.resources), 2)
        occurrence = recovery.occurrences[0]
        self.assertEqual(occurrence["region_kind"], "ambiguous")
        self.assertEqual(occurrence["source_object_status"], "ambiguous")
        self.assertIsNone(occurrence["source_object_id"])
        self.assertIsNone(occurrence["source_image_key"])
        self.assertIn("pdf_resource_match_ambiguous", occurrence["warnings"])
        self.assertNotIn("unique_candidate", occurrence["match_evidence"])
        Draft202012Validator(self.occurrence_schema).validate(occurrence)

    def test_page_crop_without_resource_is_render_only_and_eligible(self) -> None:
        crop_bytes, _ = _png()
        recovery = recover_pdf_visual_page(
            page=_Page([]),
            doc_id=DOC_ID,
            source_sha256=SOURCE_SHA256,
            page_number=1,
            placements=[
                {
                    "bbox": {"x": 10, "y": 20, "w": 40, "h": 30},
                    "crop_bytes": crop_bytes,
                    "page_render_sha256": "7" * 64,
                    "render_profile_sha256": "8" * 64,
                }
            ],
        )

        self.assertEqual(len(recovery.resources), 0)
        occurrence = recovery.occurrences[0]
        self.assertEqual(occurrence["region_kind"], "raster_image")
        self.assertEqual(occurrence["source_object_status"], "render_only")
        self.assertEqual(occurrence["link_method"], "render_region_only")
        self.assertEqual(occurrence["retrieval_status"], "eligible")
        self.assertIn("page_render", occurrence["match_evidence"])
        validate_visual_occurrence(occurrence)

    def test_soft_mask_is_combined_and_keeps_base_and_mask_indirect_provenance(self) -> None:
        mask_bytes = bytes((0, 85, 170, 255))
        mask_image = Image.frombytes("L", (2, 2), mask_bytes)
        mask_stream = _Stream(
            {"/Width": 2, "/Height": 2}, data=mask_bytes, image=mask_image
        )
        mask_ref = _Ref(21, 2, mask_stream)
        mask_stream.indirect_reference = mask_ref
        xobject = _Stream({"/Width": 2, "/Height": 2, "/SMask": mask_ref})
        image_file = _image_file(
            name="Masked.png",
            idnum=20,
            color=(200, 10, 20),
            size=(2, 2),
            xobject=xobject,
        )
        page = _Page([("/Masked", image_file)])

        resources = collect_pypdf_image_resources(
            page,
            doc_id=DOC_ID,
            source_sha256=SOURCE_SHA256,
            page_number=1,
        )

        self.assertEqual(len(resources), 1)
        resource = resources[0]
        record = resource.record
        self.assertEqual(record["indirect_ref"], {"idnum": 20, "generation": 0})
        self.assertEqual(len(record["mask_provenance"]), 1)
        mask = record["mask_provenance"][0]
        self.assertEqual(mask["kind"], "soft_mask")
        self.assertEqual(mask["indirect_ref"], {"idnum": 21, "generation": 2})
        self.assertEqual(mask["decoded_sha256"], hashlib.sha256(mask_bytes).hexdigest())
        self.assertEqual(mask["byte_size"], 4)
        self.assertIsNotNone(resource.canonical_bytes)
        with Image.open(io.BytesIO(resource.canonical_bytes or b"")) as canonical:
            self.assertEqual(canonical.mode, "RGBA")
            self.assertEqual(list(canonical.getchannel("A").tobytes()), [0, 85, 170, 255])
        self.assertEqual(
            record["canonical_sha256"], hashlib.sha256(resource.canonical_bytes or b"").hexdigest()
        )

    def test_inline_vector_and_decorative_classifications_are_separate(self) -> None:
        page = _Page(
            [
                ("~0~", _image_file(name="inline.png", idnum=None, is_inline=True)),
                ("/Logo", _image_file(name="Logo.png", idnum=31, color=(1, 2, 3))),
            ]
        )
        recovery = recover_pdf_visual_page(
            page=page,
            doc_id=DOC_ID,
            source_sha256=SOURCE_SHA256,
            page_number=1,
            placements=[
                {
                    "resource_path": ["~0~"],
                    "bbox": {"x": 10, "y": 10, "w": 20, "h": 20},
                },
                {
                    "resource_path": ["Logo"],
                    "classification": "decorative",
                    "bbox": {"x": 40, "y": 10, "w": 20, "h": 20},
                },
            ],
            vector_candidates=[
                {
                    "region_kind": "vector_diagram",
                    "bbox": {"x": 10, "y": 60, "w": 100, "h": 70},
                }
            ],
        )

        self.assertEqual(
            {row["region_kind"] for row in recovery.occurrences},
            {"inline_image", "decorative", "vector_diagram"},
        )
        for occurrence in recovery.occurrences:
            Draft202012Validator(self.occurrence_schema).validate(occurrence)

    def test_materializer_is_byte_deterministic_and_schema_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private_root = Path(directory).resolve()
            first = self._materialize(private_root, "first")
            second = self._materialize(private_root, "second")

            Draft202012Validator(self.metadata_schema).validate(first)
            self.assertEqual(first, second)
            self.assertTrue(first["strict_reuse_eligible"])
            self.assertEqual(first["external_api_calls"], 0)
            self.assertFalse(first["private_egress"])
            self.assertEqual(first["occurrence_count"], 2)
            self.assertEqual(first["status_counts"]["pdf_resources"], 1)

            first_root = private_root / "first"
            second_root = private_root / "second"
            first_files = sorted(
                path.relative_to(first_root)
                for path in first_root.rglob("*")
                if path.is_file()
            )
            second_files = sorted(
                path.relative_to(second_root)
                for path in second_root.rglob("*")
                if path.is_file()
            )
            self.assertEqual(first_files, second_files)
            for relative in first_files:
                self.assertEqual(
                    (first_root / relative).read_bytes(),
                    (second_root / relative).read_bytes(),
                )
            for filename in (
                RESOURCE_ARTIFACT,
                OCCURRENCE_ARTIFACT,
                OBJECT_MANIFEST_ARTIFACT,
                METADATA_ARTIFACT,
            ):
                self.assertTrue((first_root / filename).is_file())
            for line in (first_root / OCCURRENCE_ARTIFACT).read_text(
                encoding="utf-8"
            ).splitlines():
                occurrence = json.loads(line)
                Draft202012Validator(self.occurrence_schema).validate(occurrence)
                validate_visual_occurrence(occurrence)

    def test_existing_output_with_different_adapter_identity_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private_root = Path(directory).resolve()
            self._materialize(private_root, "corpus")

            with self.assertRaisesRegex(
                PdfVisualV2Error, "^pdf_visual_v2_stale_artifact_identity$"
            ):
                self._materialize(private_root, "corpus", adapter="9" * 64)

            metadata = json.loads(
                (private_root / "corpus" / METADATA_ARTIFACT).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(metadata["adapter_code_sha256"], ADAPTER_SHA256)

    def test_limits_reject_oversized_resource_before_publication(self) -> None:
        limits = PdfVisualV2Limits(max_image_bytes=16)
        with self.assertRaisesRegex(
            PdfVisualV2Error, "^pdf_visual_v2_image_bytes_exceeded$"
        ):
            collect_pypdf_image_resources(
                self._page(),
                doc_id=DOC_ID,
                source_sha256=SOURCE_SHA256,
                page_number=1,
                limits=limits,
            )


if __name__ == "__main__":
    unittest.main()
