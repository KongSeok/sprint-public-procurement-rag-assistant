from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

from midprojectrag.ingest.common import read_jsonl, write_jsonl
from midprojectrag.ingest.pdf_visual_runner import (
    PdfVisualRunnerError,
    run_pdf_visual_v2_from_manifest,
    _vector_candidates,
)
from midprojectrag.ingest.pdf_visual_v2 import (
    METADATA_ARTIFACT,
    OBJECT_MANIFEST_ARTIFACT,
    OCCURRENCE_ARTIFACT,
    RESOURCE_ARTIFACT,
    PdfVisualV2Error,
)


DOC_ID = "doc_0123456789abcdef01234567"


def _image_pdf() -> bytes:
    image = Image.new("RGB", (48, 32), (20, 90, 180))
    output = io.BytesIO()
    image.save(output, format="PDF", resolution=72.0)
    return output.getvalue()


def _ruled_table_pdf() -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    stream = DecodedStreamObject()
    stream.set_data(
        b"0 0 0 RG 1 w "
        b"20 20 m 20 180 l S 100 20 m 100 180 l S 180 20 m 180 180 l S "
        b"20 20 m 180 20 l S 20 100 m 180 100 l S 20 180 m 180 180 l S"
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def _vector_diagram_pdf() -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=240, height=200)
    stream = DecodedStreamObject()
    stream.set_data(
        b"0 0 0 RG 1 w "
        b"20 120 60 40 re S 140 120 60 40 re S "
        b"80 140 m 140 140 l S 110 140 m 110 100 l S "
        b"110 100 m 160 100 l S 160 100 m 160 120 l S"
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class PdfVisualRunnerTests(unittest.TestCase):
    def _fixture(
        self,
        root: Path,
        *,
        source_bytes: bytes | None = None,
        source_relpath: str = "files/sample.pdf",
        manifest_sha256: str | None = None,
        include_ignored_rows: bool = False,
    ) -> tuple[Path, Path, Path]:
        data_dir = root / "data"
        private_root = data_dir / "private"
        source = data_dir / "files" / "sample.pdf"
        private_root.mkdir(parents=True)
        source.parent.mkdir(parents=True)
        payload = source_bytes or _image_pdf()
        source.write_bytes(payload)
        row = {
            "schema_version": "1.0",
            "doc_id": DOC_ID,
            "source_relpath": source_relpath,
            "extension": ".pdf",
            "mime_type": "application/pdf",
            "size_bytes": len(payload),
            "sha256": manifest_sha256 or hashlib.sha256(payload).hexdigest(),
            "status": "ok",
            "page_count": 1,
        }
        rows = [row]
        if include_ignored_rows:
            rows.extend(
                [
                    {
                        "extension": ".hwp",
                        "status": "ok",
                        "source_relpath": "../../must-not-open.hwp",
                    },
                    {
                        "extension": ".pdf",
                        "status": "failed",
                        "source_relpath": "../../must-not-open.pdf",
                    },
                ]
            )
        manifest = private_root / "manifest.extracted.jsonl"
        write_jsonl(manifest, rows)
        return data_dir.resolve(), private_root.resolve(), manifest.resolve()

    def test_real_pdf_image_is_linked_cropped_and_eligible_offline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir, private_root, manifest = self._fixture(
                Path(directory), include_ignored_rows=True
            )
            output = (private_root / "visual-v2").resolve()

            summary = run_pdf_visual_v2_from_manifest(
                manifest_path=manifest,
                data_dir=data_dir,
                private_root=private_root,
                output_dir=output,
            )

            self.assertEqual(summary["document_count"], 1)
            self.assertEqual(summary["occurrence_count"], 1)
            self.assertEqual(summary["external_api_calls"], 0)
            self.assertFalse(summary["private_egress"])
            self.assertTrue(summary["strict_reuse_eligible"])
            self.assertNotIn("source_relpath", summary)
            self.assertNotIn("text", summary)
            occurrence = read_jsonl(output / OCCURRENCE_ARTIFACT)[0]
            self.assertEqual(occurrence["region_kind"], "raster_image")
            self.assertEqual(occurrence["source_object_status"], "exact_resource_link")
            self.assertEqual(occurrence["retrieval_status"], "eligible")
            self.assertIn("page_render", occurrence["match_evidence"])
            self.assertRegex(occurrence["page_render_sha256"], r"^[0-9a-f]{64}$")
            crop = output / str(occurrence["crop_relpath"])
            self.assertTrue(crop.is_file())
            self.assertEqual(
                hashlib.sha256(crop.read_bytes()).hexdigest(),
                occurrence["crop_sha256"],
            )
            self.assertEqual(len(read_jsonl(output / RESOURCE_ARTIFACT)), 1)
            self.assertTrue((output / OBJECT_MANIFEST_ARTIFACT).is_file())
            self.assertTrue((output / METADATA_ARTIFACT).is_file())

    def test_two_fresh_outputs_are_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir, private_root, manifest = self._fixture(Path(directory))
            first = (private_root / "first").resolve()
            second = (private_root / "second").resolve()

            first_summary = run_pdf_visual_v2_from_manifest(
                manifest_path=manifest,
                data_dir=data_dir,
                private_root=private_root,
                output_dir=first,
            )
            second_summary = run_pdf_visual_v2_from_manifest(
                manifest_path=manifest,
                data_dir=data_dir,
                private_root=private_root,
                output_dir=second,
            )

            self.assertEqual(first_summary, second_summary)
            first_files = sorted(
                path.relative_to(first) for path in first.rglob("*") if path.is_file()
            )
            second_files = sorted(
                path.relative_to(second) for path in second.rglob("*") if path.is_file()
            )
            self.assertEqual(first_files, second_files)
            for relative in first_files:
                self.assertEqual((first / relative).read_bytes(), (second / relative).read_bytes())

    def test_strict_ruled_grid_becomes_a_render_only_table_crop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir, private_root, manifest = self._fixture(
                Path(directory), source_bytes=_ruled_table_pdf()
            )
            output = (private_root / "table-v2").resolve()

            summary = run_pdf_visual_v2_from_manifest(
                manifest_path=manifest,
                data_dir=data_dir,
                private_root=private_root,
                output_dir=output,
            )

            self.assertEqual(summary["occurrence_count"], 1)
            occurrence = read_jsonl(output / OCCURRENCE_ARTIFACT)[0]
            self.assertEqual(occurrence["region_kind"], "table")
            self.assertEqual(occurrence["source_object_status"], "render_only")
            self.assertEqual(occurrence["retrieval_status"], "eligible")
            self.assertEqual(occurrence["link_method"], "render_region_only")

    def test_strict_connected_geometry_becomes_a_vector_crop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir, private_root, manifest = self._fixture(
                Path(directory), source_bytes=_vector_diagram_pdf()
            )
            output = (private_root / "vector-v2").resolve()

            summary = run_pdf_visual_v2_from_manifest(
                manifest_path=manifest,
                data_dir=data_dir,
                private_root=private_root,
                output_dir=output,
            )

            self.assertEqual(summary["occurrence_count"], 1)
            occurrence = read_jsonl(output / OCCURRENCE_ARTIFACT)[0]
            self.assertEqual(occurrence["region_kind"], "vector_diagram")
            self.assertEqual(occurrence["source_object_status"], "render_only")
            self.assertEqual(occurrence["retrieval_status"], "eligible")

    def test_overcomplex_vector_page_is_explicitly_withheld_not_dropped(self) -> None:
        class ComplexPage:
            width = 200.0
            height = 300.0
            rects = [
                {"x0": 1.0, "top": 1.0, "x1": 2.0, "bottom": 2.0}
            ] * 6
            lines: list[dict[str, float]] = []
            curves: list[dict[str, float]] = []

        candidates = _vector_candidates(
            ComplexPage(), excluded=(), max_drawing_objects=5
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["region_kind"], "ambiguous")
        self.assertFalse(candidates[0]["verified"])
        self.assertEqual(
            candidates[0]["bbox"],
            {"x": 0.0, "y": 0.0, "w": 200.0, "h": 300.0},
        )

    def test_source_escape_and_hash_mismatch_fail_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_dir, private_root, manifest = self._fixture(
                root,
                source_relpath="../outside.pdf",
            )
            with self.assertRaisesRegex(
                PdfVisualRunnerError,
                "^pdf_visual_runner_source_outside_data_dir$",
            ):
                run_pdf_visual_v2_from_manifest(
                    manifest_path=manifest,
                    data_dir=data_dir,
                    private_root=private_root,
                    output_dir=(private_root / "escape-output").resolve(),
                )
            self.assertFalse((private_root / "escape-output").exists())

            data_dir, private_root, manifest = self._fixture(
                root / "hash-case",
                manifest_sha256="0" * 64,
            )
            with self.assertRaisesRegex(
                PdfVisualRunnerError,
                "^pdf_visual_runner_source_hash_mismatch$",
            ):
                run_pdf_visual_v2_from_manifest(
                    manifest_path=manifest,
                    data_dir=data_dir,
                    private_root=private_root,
                    output_dir=(private_root / "hash-output").resolve(),
                )
            self.assertFalse((private_root / "hash-output").exists())

    def test_existing_output_with_changed_render_contract_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir, private_root, manifest = self._fixture(Path(directory))
            output = (private_root / "corpus").resolve()
            run_pdf_visual_v2_from_manifest(
                manifest_path=manifest,
                data_dir=data_dir,
                private_root=private_root,
                output_dir=output,
                render_scale=1.0,
            )

            with self.assertRaisesRegex(
                PdfVisualV2Error,
                "^pdf_visual_v2_stale_artifact_identity$",
            ):
                run_pdf_visual_v2_from_manifest(
                    manifest_path=manifest,
                    data_dir=data_dir,
                    private_root=private_root,
                    output_dir=output,
                    render_scale=1.5,
                )

    def test_manifest_must_be_private_and_page_count_must_be_fresh(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir, private_root, manifest = self._fixture(Path(directory))
            public_manifest = data_dir / "manifest.extracted.jsonl"
            public_manifest.write_bytes(manifest.read_bytes())
            with self.assertRaisesRegex(
                PdfVisualRunnerError,
                "^pdf_visual_runner_manifest_outside_private_root$",
            ):
                run_pdf_visual_v2_from_manifest(
                    manifest_path=public_manifest.resolve(),
                    data_dir=data_dir,
                    private_root=private_root,
                    output_dir=(private_root / "public-manifest-output").resolve(),
                )

            row = json.loads(manifest.read_text(encoding="utf-8").strip())
            row["page_count"] = 2
            write_jsonl(manifest, [row])
            with self.assertRaisesRegex(
                PdfVisualRunnerError,
                "^pdf_visual_runner_manifest_page_count_mismatch$",
            ):
                run_pdf_visual_v2_from_manifest(
                    manifest_path=manifest,
                    data_dir=data_dir,
                    private_root=private_root,
                    output_dir=(private_root / "stale-manifest-output").resolve(),
                )


if __name__ == "__main__":
    unittest.main()
