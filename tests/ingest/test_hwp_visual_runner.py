from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from PIL import Image

from midprojectrag.ingest.common import read_jsonl, write_json, write_jsonl
from midprojectrag.ingest.hwp_visual_runner import (
    HELPER_MANIFEST_ARTIFACT,
    METADATA_ARTIFACT,
    OBJECT_MANIFEST_ARTIFACT,
    OCCURRENCE_ARTIFACT,
    HwpVisualRunnerError,
    run_hwp_visual_v2_from_manifest,
)


DOC_ID = "doc_0123456789abcdef01234567"


def _png() -> bytes:
    image = Image.new("RGBA", (20, 20), (255, 255, 255, 255))
    for x in range(2, 10):
        for y in range(3, 9):
            image.putpixel((x, y), (25, 90, 180, 255))
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=False, compress_level=9)
    return output.getvalue()


def _tiff() -> bytes:
    image = Image.new("RGB", (8, 8), (120, 80, 40))
    output = io.BytesIO()
    image.save(output, format="TIFF")
    return output.getvalue()


def _bridge_source(
    page_png: bytes,
    *,
    source_bytes: bytes | None = None,
    source_media_type: str = "image/png",
    supported: bool = True,
) -> str:
    encoded = base64.b64encode(page_png).decode("ascii")
    encoded_source = base64.b64encode(source_bytes or page_png).decode("ascii")
    source_extension = "png" if source_media_type == "image/png" else "tiff"
    return textwrap.dedent(
        f"""\
        #!{sys.executable}
        import base64
        import hashlib
        import json
        import pathlib
        import sys

        def canonical(value):
            return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

        helper_marker = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
        args = {{}}
        for index in range(2, len(sys.argv), 2):
            args[sys.argv[index]] = sys.argv[index + 1]
        private_root = pathlib.Path(args["--private-root"])
        output = pathlib.Path(args["--output"])
        asset_dir = pathlib.Path(args["--asset-dir"])
        render_dir = pathlib.Path(args["--page-render-dir"])
        doc_id = args["--doc-id"]
        page_png = base64.b64decode("{encoded}")
        source_bytes = base64.b64decode("{encoded_source}")
        page_digest = hashlib.sha256(page_png).hexdigest()
        source_digest = hashlib.sha256(source_bytes).hexdigest()
        source_asset = asset_dir / (source_digest + ".{source_extension}")
        page_render = render_dir / (page_digest + ".png")
        source_asset.parent.mkdir(parents=True, exist_ok=True)
        page_render.parent.mkdir(parents=True, exist_ok=True)
        source_asset.write_bytes(source_bytes)
        page_render.write_bytes(page_png)
        anchor = {{
            "kind": "body",
            "section_index": 0,
            "paragraph_index": 0,
            "control_index": 0,
            "table_block_id": None,
            "cell_path": [],
        }}
        bbox = {{"x": 2, "y": 3, "w": 8, "h": 6}}
        occurrence = {{
            "schema_version": "1.0",
            "doc_id": doc_id,
            "render_occurrence_key": "render-0",
            "page": 1,
            "bbox": bbox,
            "coordinate_space": "rhwp_css_px_96dpi",
            "sequence_in_page": 0,
            "source_image_key": "img:1",
            "source_resource_sha256": source_digest,
            "embedded_raw_sha256": None,
            "normalized_rgba_sha256": None,
            "match_bbox": None,
            "source_anchor": anchor,
        }}
        source_object = {{
            "schema_version": "1.0",
            "doc_id": doc_id,
            "source_ordinal": 0,
            "source_image_key": "img:1",
            "source_object_sha256": source_digest,
            "source_object_media_type": "{source_media_type}",
            "normalized_rgba_sha256": None,
            "supported": {supported!r},
            "source_anchor": anchor,
        }}
        source_relpath = source_asset.relative_to(private_root).as_posix()
        render_relpath = page_render.relative_to(private_root).as_posix()
        page_hash = "0" * 64 if "bad-page-hash" in helper_marker else page_digest
        counts = {{
            "page_count": 1,
            "pages_with_image_ops": 1,
            "image_ops_total": 1,
            "placed_occurrences": 1,
            "unresolved_occurrences": 0,
            "source_objects": 1,
            "source_assets": 1,
            "unsupported_source_objects": {0 if supported else 1},
            "page_renders": 1,
        }}
        page_bbox = {{"x": 0, "y": 0, "w": 20, "h": 20}}
        envelope = {{
            "schema_version": "1.0",
            "helper": "rhwp_visual_helper",
            "doc_id": doc_id,
            "source_sha256": args["--source-sha256"],
            "dependency_pins": {{
                "core_js_sha256": args["--core-js-sha256"],
                "wasm_sha256": args["--wasm-sha256"],
                "canvas_entry_sha256": args["--canvas-sha256"],
            }},
            "render_profile": {{
                "profile": "screen",
                "omit_image_bytes": True,
                "coordinate_space": "rhwp_css_px_96dpi",
                "bbox_match_tolerance_px": 0.125,
            }},
            "occurrences": [occurrence],
            "source_objects": [source_object],
            "source_assets": [{{
                "source_ordinal": 0,
                "source_image_key_sha256": hashlib.sha256(b"img:1").hexdigest(),
                "source_object_sha256": source_digest,
                "source_object_media_type": "{source_media_type}",
                "byte_size": len(source_bytes),
                "relpath": source_relpath,
            }}],
            "page_sizes": [{{
                "page": 1,
                "width": 20,
                "height": 20,
                "coordinate_page_bbox": page_bbox,
            }}],
            "page_renders": [{{
                "page": 1,
                "width": 20,
                "height": 20,
                "coordinate_page_bbox": page_bbox,
                "page_render_sha256": page_hash,
                "relpath": render_relpath,
                "render_profile": {{
                    "renderer": "rhwp_core_renderPageSvg+napi_canvas+data_uri_overlay",
                    "profile": "screen",
                    "scale": 1,
                    "pixel_rounding": "ceil",
                }},
            }}],
            "unresolved": {{
                "bbox_match_ambiguous": 0,
                "source_anchor_unresolved": 0,
                "source_key_not_listed": 0,
                "inline_bytes_invalid": 0,
            }},
            "counts": counts,
        }}
        payload = (canonical(envelope) + "\\n").encode("utf-8")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payload)
        summary = {{
            "ok": True,
            "schema_version": "1.0",
            "doc_id": doc_id,
            "output_sha256": hashlib.sha256(payload).hexdigest(),
            "counts": counts,
        }}
        sys.stdout.write(canonical(summary) + "\\n")
        """
    )


class HwpVisualRunnerTests(unittest.TestCase):
    def _fixture(
        self,
        root: Path,
        *,
        helper_marker: str = "fixture-helper",
        source_relpath: str = "files/sample.hwp",
        unsupported_source: bool = False,
    ) -> dict[str, object]:
        data_dir = root / "data"
        private_root = data_dir / "private"
        blocks_dir = private_root / "blocks"
        files_dir = data_dir / "files"
        tools_dir = root / "tools"
        blocks_dir.mkdir(parents=True)
        files_dir.mkdir(parents=True)
        tools_dir.mkdir(parents=True)
        source = files_dir / "sample.hwp"
        source_payload = b"synthetic-hwp-fixture"
        source.write_bytes(source_payload)
        blocks = blocks_dir / f"{DOC_ID}.jsonl"
        write_jsonl(blocks, [{"doc_id": DOC_ID, "block_id": "block_" + "0" * 24}])
        manifest = private_root / "manifest.extracted.jsonl"
        manifest_row = {
            "schema_version": "1.0",
            "doc_id": DOC_ID,
            "source_relpath": source_relpath,
            "output_relpath": f"private/blocks/{DOC_ID}.jsonl",
            "extension": ".hwp",
            "mime_type": "application/x-hwp-ole",
            "size_bytes": len(source_payload),
            "sha256": hashlib.sha256(source_payload).hexdigest(),
            "status": "ok",
            "index_eligible": True,
            "page_count": 1,
        }
        write_jsonl(manifest, [manifest_row])
        manifest_sha256 = hashlib.sha256(manifest.read_bytes()).hexdigest()
        selection = private_root / "sample-selection.json"
        write_json(
            selection,
            {
                "schema_version": "1.0",
                "source_manifest_sha256": manifest_sha256,
                "documents": [{"doc_id": DOC_ID, "roles": ["image"], "stats": {}}],
            },
        )
        node = tools_dir / "fake-node"
        node.write_text(
            _bridge_source(
                _png(),
                source_bytes=_tiff() if unsupported_source else None,
                source_media_type="image/tiff" if unsupported_source else "image/png",
                supported=not unsupported_source,
            ),
            encoding="utf-8",
        )
        node.chmod(0o700)
        helper = tools_dir / "rhwp_visual_helper.mjs"
        helper.write_text(helper_marker, encoding="utf-8")
        core_js = tools_dir / "rhwp_core.js"
        wasm = tools_dir / "rhwp_core_bg.wasm"
        canvas = tools_dir / "canvas.js"
        core_js.write_bytes(b"fixture-core-js")
        wasm.write_bytes(b"fixture-wasm")
        canvas.write_bytes(b"fixture-canvas")

        def digest(path: Path) -> str:
            return hashlib.sha256(path.read_bytes()).hexdigest()

        return {
            "manifest_path": manifest.resolve(),
            "data_dir": data_dir.resolve(),
            "blocks_dir": blocks_dir.resolve(),
            "selection_path": selection.resolve(),
            "private_root": private_root.resolve(),
            "node_executable": node.resolve(),
            "node_sha256": digest(node),
            "helper_path": helper.resolve(),
            "helper_sha256": digest(helper),
            "core_js_path": core_js.resolve(),
            "core_js_sha256": digest(core_js),
            "wasm_path": wasm.resolve(),
            "wasm_sha256": digest(wasm),
            "canvas_module_path": canvas.resolve(),
            "canvas_module_sha256": digest(canvas),
            "timeout_seconds": 30.0,
        }

    def _run(self, fixture: dict[str, object], output_name: str, **overrides: object):
        arguments = dict(fixture)
        private_root = arguments["private_root"]
        assert isinstance(private_root, Path)
        arguments["output_dir"] = (private_root / output_name).resolve()
        arguments.update(overrides)
        return run_hwp_visual_v2_from_manifest(**arguments), arguments["output_dir"]

    def test_representative_run_crops_and_publishes_aggregate_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            summary, output = self._run(fixture, "visual-v2")
            assert isinstance(output, Path)

            self.assertEqual(summary["document_count"], 1)
            self.assertEqual(summary["occurrence_count"], 1)
            self.assertEqual(summary["external_api_calls"], 0)
            self.assertFalse(summary["private_egress"])
            self.assertTrue(summary["strict_reuse_eligible"])
            self.assertNotIn("path", json.dumps(summary))
            self.assertNotIn("sample.hwp", json.dumps(summary))
            occurrence = read_jsonl(output / OCCURRENCE_ARTIFACT)[0]
            self.assertEqual(occurrence["source_object_status"], "exact_resource_link")
            self.assertEqual(occurrence["retrieval_status"], "eligible")
            self.assertIn("page_render", occurrence["match_evidence"])
            crop = output / occurrence["crop_relpath"]
            self.assertEqual(hashlib.sha256(crop.read_bytes()).hexdigest(), occurrence["crop_sha256"])
            self.assertEqual(len(read_jsonl(output / HELPER_MANIFEST_ARTIFACT)), 1)
            self.assertEqual(len(read_jsonl(output / OBJECT_MANIFEST_ARTIFACT)), 3)
            self.assertTrue((output / METADATA_ARTIFACT).is_file())
            self.assertFalse((output / "helper-output" / f"{DOC_ID}.json").exists())

    def test_two_outputs_and_strict_reuse_are_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            first_summary, first = self._run(fixture, "first")
            second_summary, second = self._run(fixture, "second")
            reused_summary, _ = self._run(fixture, "first")
            assert isinstance(first, Path) and isinstance(second, Path)
            self.assertEqual(first_summary, second_summary)
            self.assertEqual(first_summary, reused_summary)
            first_files = sorted(path.relative_to(first) for path in first.rglob("*") if path.is_file())
            second_files = sorted(path.relative_to(second) for path in second.rglob("*") if path.is_file())
            self.assertEqual(first_files, second_files)
            for relative in first_files:
                self.assertEqual((first / relative).read_bytes(), (second / relative).read_bytes())

    def test_unsupported_source_is_quarantined_without_a_blank_crop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory), unsupported_source=True)
            summary, output = self._run(fixture, "unsupported")
            assert isinstance(output, Path)
            occurrence = read_jsonl(output / OCCURRENCE_ARTIFACT)[0]
            self.assertEqual(occurrence["source_object_status"], "unsupported")
            self.assertEqual(occurrence["retrieval_status"], "quarantined")
            self.assertIsNone(occurrence["crop_sha256"])
            self.assertIsNone(occurrence["crop_relpath"])
            self.assertEqual(summary["status_counts"]["retrieval:quarantined"], 1)
            self.assertNotIn("retrieval:eligible", summary["status_counts"])

    def test_changed_contract_refuses_stale_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            self._run(fixture, "corpus")
            with self.assertRaisesRegex(
                HwpVisualRunnerError, "^hwp_visual_runner_stale_artifact_identity$"
            ):
                self._run(fixture, "corpus", timeout_seconds=31.0)

    def test_source_escape_and_runtime_pin_mismatch_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory), source_relpath="../outside.hwp")
            with self.assertRaisesRegex(
                HwpVisualRunnerError, "^hwp_visual_runner_source_path_invalid$"
            ):
                self._run(fixture, "escape")

            fixture = self._fixture(Path(directory) / "pin-case")
            with self.assertRaisesRegex(
                HwpVisualRunnerError,
                "^hwp_visual_runner_node_invalid_hash_mismatch$",
            ):
                self._run(fixture, "bad-pin", node_sha256="0" * 64)

    def test_helper_page_hash_mismatch_is_rejected_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory), helper_marker="bad-page-hash")
            private_root = fixture["private_root"]
            assert isinstance(private_root, Path)
            with self.assertRaisesRegex(
                HwpVisualRunnerError, "^hwp_visual_runner_page_render_mismatch$"
            ):
                self._run(fixture, "bad-helper")
            self.assertFalse((private_root / "bad-helper").exists())

    def test_corpus_mode_is_closed_until_reviewed_full_gold_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            with self.assertRaisesRegex(
                HwpVisualRunnerError, "^hwp_visual_runner_gold_gate_required$"
            ):
                self._run(fixture, "full", mode="corpus")

            private_root = fixture["private_root"]
            assert isinstance(private_root, Path)
            gold = private_root / "visual-gold.jsonl"
            write_jsonl(
                gold,
                [
                    {
                        "schema_version": "1.0",
                        "annotation_id": "vgold_" + "0" * 24,
                        "doc_id": DOC_ID,
                        "source_sha256": "0" * 64,
                        "source_format": "hwp",
                        "risk_type": "hwp_body_image",
                        "page": 1,
                        "bbox": {"x": 0, "y": 0, "w": 1, "h": 1},
                        "coordinate_space": "rhwp_css_px_96dpi",
                        "region_kind": "raster_image",
                        "nearby_title": None,
                        "expected_text": [],
                        "relationship_claims": [],
                        "critical_case": "none",
                        "reviewers": ["reviewer"],
                        "status": "draft",
                    }
                ],
            )
            with self.assertRaisesRegex(
                HwpVisualRunnerError, "^hwp_visual_runner_gold_gate_failed$"
            ):
                self._run(
                    fixture,
                    "full-with-draft",
                    mode="corpus",
                    visual_gold_path=gold.resolve(),
                )


if __name__ == "__main__":
    unittest.main()
