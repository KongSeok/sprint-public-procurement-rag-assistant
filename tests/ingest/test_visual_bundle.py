from __future__ import annotations

import hashlib
import json
import os
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from midprojectrag.ingest.common import read_jsonl, sha256_file
from midprojectrag.ingest.visual_bundle import (
    _asset_manifest,
    _publish_staged,
    _validate_image_source_contract,
    materialize_hwp_visual_bundle,
)


DOC_ID = "doc_0123456789abcdef01234567"


def _png(width: int = 4, height: int = 2) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    pixels = b"".join(b"\x00" + b"\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


class VisualBundleTests(unittest.TestCase):
    def _paths(
        self, root: Path
    ) -> tuple[Path, Path, Path, Path, Path, Path, Path]:
        command = root / "rhwp"
        command.write_bytes(b"pinned-rhwp")
        command.chmod(0o700)
        source = root / "source.hwp"
        source.write_bytes(b"synthetic-source")
        return (
            command,
            source,
            root / "table.jsonl",
            root / "images.jsonl",
            root / "ordered.jsonl",
            root / "metadata.json",
            root / "assets",
        )

    def _kwargs(self, root: Path) -> dict:
        command, source, table, images, ordered, metadata, assets = self._paths(root)
        return {
            "command": str(command.resolve()),
            "source_path": source,
            "doc_id": DOC_ID,
            "blocks": [],
            "layout_records": [],
            "table_output": table,
            "image_output": images,
            "ordered_output": ordered,
            "metadata_output": metadata,
            "asset_root": assets,
            "private_root": root,
            "config_sha256": "c" * 64,
            "expected_source_sha256": sha256_file(source),
            "expected_rhwp_sha256": sha256_file(command),
        }

    def _records(self, asset_root: Path) -> tuple[dict, dict, dict, bytes]:
        asset_payload = _png()
        asset_sha256 = hashlib.sha256(asset_payload).hexdigest()
        asset_relpath = f"objects/{asset_sha256}.png"
        object_path = asset_root / asset_relpath
        object_path.parent.mkdir(parents=True, exist_ok=True)
        object_path.write_bytes(asset_payload)
        bbox = {"x": 1.0, "y": 2.0, "w": 4.0, "h": 2.0}
        table_record = {
            "schema_version": "1.0",
            "doc_id": DOC_ID,
            "block_id": "block_0123456789abcdef01234567",
            "status": "verified_render",
            "page_start": 1,
            "page_end": 1,
        }
        image_record = {
            "schema_version": "1.0",
            "doc_id": DOC_ID,
            "occurrence_id": "occ_0123456789abcdef01234567",
            "ordinal": 0,
            "node_type": "image",
            "status": "verified_asset_render",
            "asset_id": "asset_0123456789abcdef01234567",
            "asset_sha256": asset_sha256,
            "asset_relpath": asset_relpath,
            "byte_size": len(asset_payload),
            "media_type": "image/png",
            "width": 4,
            "height": 2,
            "source_asset_sha256": asset_sha256,
            "source_byte_size": len(asset_payload),
            "source_media_type": "image/png",
            "source_extension": ".png",
            "normalizations": [],
            "page_start": 1,
            "page_end": 1,
            "bbox": bbox,
            "coordinate_space": "rhwp_css_px_96dpi",
            "render_key": {"section": 0, "paragraph": 1, "control": 0},
            "sequence_in_page": 0,
            "image_ordinal_in_page": 0,
            "container_kind": "body",
            "preceding_text": None,
            "link_method": "doclang_picture_render_image_global_ordinal_exact_count",
            "doclang_loss_count": 0,
            "warnings": [],
        }
        ordered_record = {
            "schema_version": "1.0",
            "ordered_occurrence_id": "vocc_0123456789abcdef01234567",
            "doc_id": DOC_ID,
            "page": 1,
            "sequence_in_page": 0,
            "node_type": "image",
            "status": "verified_image_link",
            "bbox": bbox,
            "coordinate_space": "rhwp_css_px_96dpi",
            "render_key": {"section": 0, "paragraph": 1, "control": 0},
            "text": None,
            "linked_block_id": None,
            "linked_image_occurrence_id": image_record["occurrence_id"],
            "preceding_text": None,
            "link_method": "image_evidence_page_sequence_bbox_render_key_exact",
        }
        return table_record, image_record, ordered_record, asset_payload

    def test_materializes_deterministic_aggregate_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kwargs = self._kwargs(root)
            table_record, image_record, ordered_record, asset_payload = self._records(
                kwargs["asset_root"]
            )
            with (
                patch(
                    "midprojectrag.ingest.visual_bundle.load_rhwp_layout_inputs",
                    return_value=(
                        {"schemaVersion": "1.0", "pageCount": 1},
                        {0: {}},
                    ),
                ) as load_layout,
                patch(
                    "midprojectrag.ingest.visual_bundle.build_table_visual_overlay",
                    return_value=[table_record],
                ) as build_tables,
                patch(
                    "midprojectrag.ingest.visual_bundle.build_body_image_evidence",
                    return_value=[{"node_type": "image"}],
                ) as build_images,
                patch(
                    "midprojectrag.ingest.visual_bundle.materialize_hwp_assets",
                    return_value=[image_record],
                ) as materialize_assets,
                patch(
                    "midprojectrag.ingest.visual_bundle.build_ordered_visual_occurrences",
                    return_value=[ordered_record],
                ) as build_ordered,
            ):
                result = materialize_hwp_visual_bundle(**kwargs)

            self.assertEqual(result["tables"], 1)
            self.assertEqual(result["images"], 1)
            self.assertEqual(result["ordered_occurrences"], 1)
            self.assertEqual(result["page_count"], 1)
            self.assertEqual(result["table_status_counts"], {"verified_render": 1})
            self.assertEqual(
                result["image_status_counts"], {"verified_asset_render": 1}
            )
            self.assertEqual(
                result["ordered_status_counts"], {"verified_image_link": 1}
            )
            self.assertEqual(result["asset_count"], 1)
            self.assertEqual(result["asset_reference_count"], 1)
            self.assertEqual(result["asset_bytes"], len(asset_payload))
            self.assertTrue(result["asset_references_reconciled"])
            self.assertEqual(read_jsonl(kwargs["table_output"]), [table_record])
            self.assertEqual(read_jsonl(kwargs["image_output"]), [image_record])
            self.assertEqual(read_jsonl(kwargs["ordered_output"]), [ordered_record])
            self.assertEqual(
                result["table_artifact_sha256"], sha256_file(kwargs["table_output"])
            )
            self.assertEqual(
                result["image_artifact_sha256"], sha256_file(kwargs["image_output"])
            )
            self.assertEqual(
                result["ordered_artifact_sha256"],
                sha256_file(kwargs["ordered_output"]),
            )
            persisted_metadata = json.loads(
                kwargs["metadata_output"].read_text(encoding="utf-8")
            )
            self.assertEqual(persisted_metadata, result)
            load_layout.assert_called_once()
            build_tables.assert_called_once()
            build_images.assert_called_once()
            materialize_assets.assert_called_once()
            build_ordered.assert_called_once()

    def test_strict_reuse_contract_rejects_legacy_image_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kwargs = self._kwargs(root)
            _table, image, _ordered, _payload = self._records(kwargs["asset_root"])
            legacy = dict(image)
            legacy.pop("source_asset_sha256")
            with self.assertRaisesRegex(
                ValueError, "^visual_bundle_image_contract_invalid$"
            ):
                _validate_image_source_contract([legacy])

            normalized = dict(image)
            normalized.update(
                {
                    "source_asset_sha256": "f" * 64,
                    "source_byte_size": image["byte_size"] + 25,
                    "normalizations": ["png_trailing_bytes_removed"],
                }
            )
            _validate_image_source_contract([normalized])

            unsupported = dict(image)
            unsupported.update(
                {
                    "status": "unsupported_source_asset",
                    "asset_id": None,
                    "asset_sha256": None,
                    "asset_relpath": None,
                    "media_type": None,
                    "byte_size": None,
                    "width": None,
                    "height": None,
                    "source_asset_sha256": "e" * 64,
                    "source_byte_size": 24,
                    "source_media_type": "image/wmf",
                    "source_extension": ".wmf",
                    "normalizations": [],
                    "page_start": None,
                    "page_end": None,
                    "bbox": None,
                    "coordinate_space": None,
                    "render_key": None,
                    "sequence_in_page": None,
                    "image_ordinal_in_page": None,
                    "container_kind": None,
                    "preceding_text": None,
                    "link_method": "doclang_picture_unsupported_unlinked",
                    "warnings": ["image_format_unsupported"],
                }
            )
            _validate_image_source_contract([unsupported])

            missing_render_proof = dict(image)
            missing_render_proof["render_key"] = None
            with self.assertRaisesRegex(
                ValueError, "^visual_bundle_image_contract_invalid$"
            ):
                _validate_image_source_contract([missing_render_proof])

            with self.assertRaisesRegex(
                ValueError, "^visual_bundle_image_contract_invalid$"
            ):
                _validate_image_source_contract([image, unsupported])

    def test_asset_manifest_revalidates_magic_mime_and_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kwargs = self._kwargs(root)
            _table, image, _ordered, _payload = self._records(kwargs["asset_root"])

            valid_manifest, references = _asset_manifest(
                [image], asset_root=kwargs["asset_root"].resolve()
            )
            self.assertEqual(len(valid_manifest), 1)
            self.assertEqual(references, 1)

            wrong_dimensions = dict(image)
            wrong_dimensions["width"] = image["width"] + 1
            with self.assertRaisesRegex(
                ValueError, "^visual_bundle_asset_reference_invalid$"
            ):
                _asset_manifest(
                    [wrong_dimensions], asset_root=kwargs["asset_root"].resolve()
                )

            spoofed = b"not-a-png"
            spoofed_sha256 = hashlib.sha256(spoofed).hexdigest()
            spoofed_relpath = f"objects/{spoofed_sha256}.png"
            spoofed_path = kwargs["asset_root"] / spoofed_relpath
            spoofed_path.write_bytes(spoofed)
            spoofed_record = dict(image)
            spoofed_record.update(
                {
                    "asset_sha256": spoofed_sha256,
                    "asset_relpath": spoofed_relpath,
                    "byte_size": len(spoofed),
                    "source_asset_sha256": spoofed_sha256,
                    "source_byte_size": len(spoofed),
                }
            )
            with self.assertRaisesRegex(
                ValueError, "^visual_bundle_asset_reference_invalid$"
            ):
                _asset_manifest(
                    [spoofed_record], asset_root=kwargs["asset_root"].resolve()
                )

    def test_rejects_checksum_and_output_collisions_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kwargs = self._kwargs(root)
            with patch(
                "midprojectrag.ingest.visual_bundle.load_rhwp_layout_inputs"
            ) as load_layout:
                with self.assertRaisesRegex(
                    ValueError, "visual_bundle_rhwp_checksum_mismatch"
                ):
                    materialize_hwp_visual_bundle(
                        **{**kwargs, "expected_rhwp_sha256": "0" * 64}
                    )
                with self.assertRaisesRegex(
                    ValueError, "visual_bundle_source_checksum_mismatch"
                ):
                    materialize_hwp_visual_bundle(
                        **{**kwargs, "expected_source_sha256": "0" * 64}
                    )
                with self.assertRaisesRegex(
                    ValueError, "visual_bundle_output_collision"
                ):
                    materialize_hwp_visual_bundle(
                        **{
                            **kwargs,
                            "image_output": kwargs["table_output"],
                        }
                    )
                with self.assertRaisesRegex(
                    ValueError, "visual_bundle_output_collision"
                ):
                    materialize_hwp_visual_bundle(
                        **{
                            **kwargs,
                            "table_output": kwargs["source_path"],
                        }
                    )
            load_layout.assert_not_called()

    def test_rejects_private_root_escape_and_symlink_ancestor(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside_name:
            root = Path(directory)
            outside = Path(outside_name)
            kwargs = self._kwargs(root)
            with patch(
                "midprojectrag.ingest.visual_bundle.load_rhwp_layout_inputs"
            ) as load_layout:
                with self.assertRaisesRegex(
                    ValueError, "visual_bundle_table_output_invalid"
                ):
                    materialize_hwp_visual_bundle(
                        **{**kwargs, "table_output": outside / "table.jsonl"}
                    )
                escape = root / "escape"
                os.symlink(outside, escape)
                with self.assertRaisesRegex(
                    ValueError, "visual_bundle_table_output_invalid"
                ):
                    materialize_hwp_visual_bundle(
                        **{**kwargs, "table_output": escape / "table.jsonl"}
                    )
            load_layout.assert_not_called()

    def test_extraction_io_error_is_sanitized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kwargs = self._kwargs(root)
            with patch(
                "midprojectrag.ingest.visual_bundle.load_rhwp_layout_inputs",
                side_effect=OSError(f"private source path: {kwargs['source_path']}"),
            ), self.assertRaises(ValueError) as raised:
                materialize_hwp_visual_bundle(**kwargs)
            self.assertEqual(
                str(raised.exception), "visual_bundle_extraction_io_failed"
            )
            self.assertNotIn(directory, str(raised.exception))
            self.assertIsNone(raised.exception.__cause__)

    def test_detects_source_or_binary_mutation_before_staging(self) -> None:
        for identity in ("source", "command"):
            with self.subTest(identity=identity), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                kwargs = self._kwargs(root)

                def mutate_identity(*_args, **_kwargs):
                    target = (
                        kwargs["source_path"]
                        if identity == "source"
                        else Path(kwargs["command"])
                    )
                    target.write_bytes(b"mutated-private-input")
                    if identity == "command":
                        target.chmod(0o700)
                    return {"schemaVersion": "1.0", "pageCount": 1}, {0: {}}

                error = (
                    "visual_bundle_source_changed_during_extraction"
                    if identity == "source"
                    else "visual_bundle_rhwp_changed_during_extraction"
                )
                with (
                    patch(
                        "midprojectrag.ingest.visual_bundle.load_rhwp_layout_inputs",
                        side_effect=mutate_identity,
                    ),
                    patch(
                        "midprojectrag.ingest.visual_bundle.build_table_visual_overlay",
                        return_value=[],
                    ),
                    patch(
                        "midprojectrag.ingest.visual_bundle.build_body_image_evidence",
                        return_value=[],
                    ),
                    patch(
                        "midprojectrag.ingest.visual_bundle.materialize_hwp_assets",
                        return_value=[],
                    ),
                    patch(
                        "midprojectrag.ingest.visual_bundle.build_ordered_visual_occurrences",
                        return_value=[],
                    ),
                    self.assertRaisesRegex(ValueError, f"^{error}$"),
                ):
                    materialize_hwp_visual_bundle(**kwargs)
                self.assertFalse(kwargs["table_output"].exists())
                self.assertFalse(kwargs["metadata_output"].exists())

    def test_staging_failure_leaves_existing_generation_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kwargs = self._kwargs(root)
            old = {
                "table_output": b"old-table\n",
                "image_output": b"old-image\n",
                "ordered_output": b"old-ordered\n",
                "metadata_output": b"old-metadata\n",
            }
            for name, payload in old.items():
                kwargs[name].write_bytes(payload)
            with (
                patch(
                    "midprojectrag.ingest.visual_bundle.load_rhwp_layout_inputs",
                    return_value=(
                        {"schemaVersion": "1.0", "pageCount": 1},
                        {0: {}},
                    ),
                ),
                patch(
                    "midprojectrag.ingest.visual_bundle.build_table_visual_overlay",
                    return_value=[],
                ),
                patch(
                    "midprojectrag.ingest.visual_bundle.build_body_image_evidence",
                    return_value=[],
                ),
                patch(
                    "midprojectrag.ingest.visual_bundle.materialize_hwp_assets",
                    return_value=[],
                ),
                patch(
                    "midprojectrag.ingest.visual_bundle.build_ordered_visual_occurrences",
                    return_value=[],
                ),
                patch(
                    "midprojectrag.ingest.visual_bundle._publish_staged",
                    side_effect=ValueError("visual_bundle_publish_failed"),
                ),
                self.assertRaisesRegex(ValueError, "^visual_bundle_publish_failed$"),
            ):
                materialize_hwp_visual_bundle(**kwargs)
            for name, payload in old.items():
                self.assertEqual(kwargs[name].read_bytes(), payload)

    def test_publish_rolls_back_partial_replace_without_path_disclosure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage = root / "stage"
            stage.mkdir()
            staged_one = stage / "one.new"
            staged_two = stage / "two.new"
            destination_one = root / "one.jsonl"
            destination_two = root / "two.jsonl"
            staged_one.write_bytes(b"new-one")
            staged_two.write_bytes(b"new-two")
            destination_one.write_bytes(b"old-one")
            destination_two.write_bytes(b"old-two")
            real_replace = os.replace
            failed = False

            def fail_second_once(source, destination):
                nonlocal failed
                if Path(destination) == destination_two and not failed:
                    failed = True
                    raise OSError(f"private failure at {destination}")
                return real_replace(source, destination)

            with patch(
                "midprojectrag.ingest.visual_bundle.os.replace",
                side_effect=fail_second_once,
            ), self.assertRaises(ValueError) as raised:
                _publish_staged(
                    (
                        (staged_one, destination_one, hashlib.sha256(b"new-one").hexdigest()),
                        (staged_two, destination_two, hashlib.sha256(b"new-two").hexdigest()),
                    ),
                    backup_root=stage,
                )
            self.assertEqual(str(raised.exception), "visual_bundle_publish_failed")
            self.assertNotIn(directory, str(raised.exception))
            self.assertEqual(destination_one.read_bytes(), b"old-one")
            self.assertEqual(destination_two.read_bytes(), b"old-two")

    def test_asset_reference_tamper_fails_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kwargs = self._kwargs(root)
            _table, image, ordered, _payload = self._records(kwargs["asset_root"])
            (kwargs["asset_root"] / image["asset_relpath"]).write_bytes(b"tampered")
            with (
                patch(
                    "midprojectrag.ingest.visual_bundle.load_rhwp_layout_inputs",
                    return_value=(
                        {"schemaVersion": "1.0", "pageCount": 1},
                        {0: {}},
                    ),
                ),
                patch(
                    "midprojectrag.ingest.visual_bundle.build_table_visual_overlay",
                    return_value=[],
                ),
                patch(
                    "midprojectrag.ingest.visual_bundle.build_body_image_evidence",
                    return_value=[{"node_type": "image"}],
                ),
                patch(
                    "midprojectrag.ingest.visual_bundle.materialize_hwp_assets",
                    return_value=[image],
                ),
                patch(
                    "midprojectrag.ingest.visual_bundle.build_ordered_visual_occurrences",
                    return_value=[ordered],
                ),
                self.assertRaisesRegex(
                    ValueError, "^visual_bundle_asset_reference_invalid$"
                ),
            ):
                materialize_hwp_visual_bundle(**kwargs)
            self.assertFalse(kwargs["metadata_output"].exists())


if __name__ == "__main__":
    unittest.main()
