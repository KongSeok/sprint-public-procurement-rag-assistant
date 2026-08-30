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

from midprojectrag.ingest.hwp_assets import (
    COORDINATE_SPACE,
    _inspect_image,
    _run_export_doclang,
    materialize_hwp_assets,
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


def _jpeg(width: int = 4, height: int = 2) -> bytes:
    return (
        b"\xff\xd8"
        + b"\xff\xc0\x00\x0b\x08"
        + struct.pack(">HH", height, width)
        + b"\x01\x01\x11\x00"
        + b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"
        + b"\x01\x02\x03"
        + b"\xff\xd9"
    )


def _bmp(width: int = 4, height: int = 2) -> bytes:
    row_bytes = ((width * 24 + 31) // 32) * 4
    pixels = b"\x00" * (row_bytes * height)
    file_size = 14 + 40 + len(pixels)
    file_header = b"BM" + struct.pack("<IHHI", file_size, 0, 0, 54)
    dib = struct.pack(
        "<IiiHHIIiiII",
        40,
        width,
        height,
        1,
        24,
        0,
        len(pixels),
        0,
        0,
        0,
        0,
    )
    return file_header + dib + pixels


def _tiff(width: int = 4, height: int = 2) -> bytes:
    entries = 6
    pixel_offset = 8 + 2 + entries * 12 + 4
    pixel_bytes = (width + 7) // 8 * height
    return (
        b"II*\x00"
        + struct.pack("<I", 8)
        + struct.pack("<H", entries)
        + struct.pack("<HHII", 256, 4, 1, width)
        + struct.pack("<HHII", 257, 4, 1, height)
        + struct.pack("<HHII", 258, 3, 1, 1)
        + struct.pack("<HHII", 259, 3, 1, 1)
        + struct.pack("<HHII", 273, 4, 1, pixel_offset)
        + struct.pack("<HHII", 279, 4, 1, pixel_bytes)
        + struct.pack("<I", 0)
        + b"\x00" * pixel_bytes
    )


def _wmf(*, trailing: bytes = b"") -> bytes:
    header_words = 9
    eof_words = 3
    return (
        struct.pack(
            "<HHHIHIH",
            1,
            header_words,
            0x0300,
            header_words + eof_words,
            0,
            eof_words,
            0,
        )
        + struct.pack("<IH", eof_words, 0)
        + trailing
    )


def _gif() -> bytes:
    return (
        b"GIF89a"
        + struct.pack("<HHBBB", 1, 1, 0x80, 0, 0)
        + b"\x00\x00\x00\xff\xff\xff"
        + b"\x2c"
        + struct.pack("<HHHHB", 0, 0, 1, 1, 0)
        + b"\x02\x02\x44\x01\x00\x3b"
    )


def _render(
    ordinal: int,
    *,
    page: int = 9,
    sequence: int | None = None,
    width: float = 400.0,
    height: float = 200.0,
    preceding: bool = True,
) -> dict[str, object]:
    if sequence is None:
        sequence = ordinal
    return {
        "schema_version": "1.0",
        "doc_id": DOC_ID,
        "occurrence_id": f"occ_{ordinal + 1:024x}",
        "node_type": "image",
        "status": "render_only_unlinked",
        "page": page,
        "sequence_in_page": sequence,
        "image_ordinal_in_page": ordinal,
        "container_kind": "body",
        "bbox": {"x": 10, "y": 20, "w": width, "h": height},
        "coordinate_space": COORDINATE_SPACE,
        "render_key": {
            "section": 0,
            "paragraph": 100 + ordinal,
            "control": 0,
        },
        "preceding_text": (
            {
                "text": "synthetic heading",
                "bbox": {"x": 10, "y": 5, "w": 50, "h": 10},
                "render_key": {"section": 0, "paragraph": 99},
                "method": "nearest_prior_top_level_textline",
            }
            if preceding
            else None
        ),
        "extraction_method": "rhwp_render_tree_body_v1",
    }


def _fake_export(
    assets: list[tuple[str, bytes]],
    *,
    xml: bytes | None = None,
    loss_count: int = 7,
    metadata_updates: dict[str, object] | None = None,
    extra_files: list[tuple[str, bytes]] | None = None,
    symlink: tuple[str, str] | None = None,
):
    def run(command, source_path, workdir, timeout_seconds):
        del command, source_path, timeout_seconds
        assets_root = workdir / "assets"
        for name, data in assets:
            target = assets_root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        for name, data in extra_files or []:
            target = assets_root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        if symlink is not None:
            link_name, target_name = symlink
            os.symlink(target_name, assets_root / link_name)
        xml_value = xml
        if xml_value is None:
            pictures = "".join(
                f'<picture><src uri="assets/{name}"/></picture>'
                for name, _ in assets
            )
            # page_break is intentionally present. The materializer must never
            # infer page numbers from it.
            xml_value = f"<doclang><page_break/>{pictures}</doclang>".encode()
        (workdir / "document.xml").write_bytes(xml_value)
        metadata: dict[str, object] = {
            "schemaVersion": "1.0",
            "format": "doclang",
            "output": "document.xml",
            "assetsDir": "assets",
            "bytes": len(xml_value),
            "assetCount": len(assets),
            "lossCount": loss_count,
            "untrustedContent": False,
            "untrustedFields": [],
        }
        metadata.update(metadata_updates or {})
        return json.dumps(metadata).encode()

    return run


class HwpAssetMaterializerTests(unittest.TestCase):
    def _call(
        self,
        root: Path,
        *,
        fake_export,
        render_images,
    ):
        source = root / "synthetic.hwp"
        source.write_bytes(b"synthetic-hwp")
        output = root / "private-assets"
        with patch(
            "midprojectrag.ingest.hwp_assets._run_export_doclang",
            side_effect=fake_export,
        ):
            result = materialize_hwp_assets(
                command="unused-rhwp",
                source_path=source,
                doc_id=DOC_ID,
                render_images=render_images,
                output_root=output,
            )
        return output, result

    def test_exact_count_and_aspect_link_by_global_ordinal(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            output, result = self._call(
                root,
                fake_export=_fake_export(
                    [("first.png", _png()), ("second.jpg", _jpeg())],
                    loss_count=2818,
                ),
                render_images=[_render(0), _render(1, sequence=1)],
            )

            self.assertEqual(len(result), 2)
            self.assertEqual(
                [record["status"] for record in result],
                ["verified_asset_render", "verified_asset_render"],
            )
            self.assertEqual(
                [record["occurrence_id"] for record in result],
                ["occ_000000000000000000000001", "occ_000000000000000000000002"],
            )
            self.assertEqual(result[0]["page_start"], 9)
            self.assertEqual(result[0]["page_end"], 9)
            self.assertEqual(result[0]["doclang_loss_count"], 2818)
            self.assertEqual(result[0]["preceding_text"]["text"], "synthetic heading")
            self.assertEqual(result[0]["media_type"], "image/png")
            self.assertEqual((result[0]["width"], result[0]["height"]), (4, 2))
            self.assertRegex(
                result[0]["asset_relpath"], r"^objects/[0-9a-f]{64}\.png$"
            )
            self.assertEqual(
                (output / result[0]["asset_relpath"]).read_bytes(), _png()
            )

    def test_same_input_is_deterministic_and_reuses_object(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            fake = _fake_export([("image.png", _png())])
            output, first = self._call(
                root,
                fake_export=fake,
                render_images=[_render(0)],
            )
            _, second = self._call(
                root,
                fake_export=fake,
                render_images=[_render(0)],
            )

            self.assertEqual(first, second)
            self.assertEqual(len(list((output / "objects").iterdir())), 1)

    def test_count_mismatch_never_guesses_a_partial_link(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            _, result = self._call(
                Path(name),
                fake_export=_fake_export([("image.png", _png())]),
                render_images=[_render(0), _render(1)],
            )

            self.assertEqual(
                [record["status"] for record in result],
                [
                    "asset_only_unlinked",
                    "render_only_missing_asset",
                    "render_only_missing_asset",
                ],
            )
            self.assertTrue(
                all(record["warnings"] == ["image_count_mismatch"] for record in result)
            )
            self.assertIsNone(result[0]["page_start"])
            self.assertIsNone(result[1]["asset_sha256"])

    def test_missing_render_key_keeps_both_sides_explicitly_unlinked(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            render = _render(0)
            render["render_key"] = None
            _, result = self._call(
                Path(name),
                fake_export=_fake_export([("image.png", _png())]),
                render_images=[render],
            )

            self.assertEqual(
                [record["status"] for record in result],
                ["asset_only_unlinked", "render_only_missing_asset"],
            )
            self.assertTrue(
                all(
                    record["warnings"] == ["image_render_key_missing"]
                    for record in result
                )
            )
            self.assertIsNone(result[1]["render_key"])

    def test_nested_images_may_share_sequence_but_use_image_ordinal_order(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            first = _render(0, sequence=4)
            second = _render(1, sequence=4)
            second["container_kind"] = "table_nested"
            _, result = self._call(
                Path(name),
                fake_export=_fake_export(
                    [("first.png", _png()), ("second.png", _png())]
                ),
                render_images=[first, second],
            )

            self.assertEqual(
                [record["status"] for record in result],
                ["verified_asset_render", "verified_asset_render"],
            )
            self.assertEqual(
                [record["image_ordinal_in_page"] for record in result], [0, 1]
            )
            self.assertEqual(result[1]["container_kind"], "table_nested")

    def test_aspect_mismatch_unlinks_the_entire_ordinal_set(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            _, result = self._call(
                Path(name),
                fake_export=_fake_export([("image.png", _png())]),
                render_images=[_render(0, width=100, height=100)],
            )

            self.assertEqual(
                [record["status"] for record in result],
                ["asset_only_unlinked", "render_only_missing_asset"],
            )
            self.assertTrue(
                all(
                    record["warnings"] == ["image_aspect_ratio_mismatch"]
                    for record in result
                )
            )

    def test_magic_detection_supports_observed_rhwp_formats(self) -> None:
        self.assertEqual(_inspect_image(_png(), ".png"), ("image/png", ".png", 4, 2))
        self.assertEqual(_inspect_image(_png(), ".jpg"), ("image/png", ".png", 4, 2))
        self.assertEqual(
            _inspect_image(_jpeg(), ".jpeg"), ("image/jpeg", ".jpg", 4, 2)
        )
        self.assertEqual(_inspect_image(_bmp(), ".bmp"), ("image/bmp", ".bmp", 4, 2))
        self.assertEqual(
            _inspect_image(_tiff(), ".tiff"), ("image/tiff", ".tif", 4, 2)
        )

    def test_magic_led_suffix_canonicalization_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            output, result = self._call(
                root,
                fake_export=_fake_export([("image.jpg", _png())]),
                render_images=[_render(0)],
            )

            record = result[0]
            self.assertEqual(record["status"], "verified_asset_render")
            self.assertEqual(record["media_type"], "image/png")
            self.assertEqual(record["source_media_type"], "image/png")
            self.assertEqual(record["source_extension"], ".jpg")
            self.assertEqual(
                record["normalizations"], ["source_extension_canonicalized"]
            )
            self.assertEqual(record["source_asset_sha256"], record["asset_sha256"])
            self.assertTrue(record["asset_relpath"].endswith(".png"))
            self.assertEqual((output / record["asset_relpath"]).read_bytes(), _png())

    def test_png_trailing_bytes_are_removed_with_dual_provenance(self) -> None:
        canonical = _png()
        source = canonical + bytes.fromhex(
            "40001ef110000000ffff00000000ff0080808000f70000100f"
        )
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            output, result = self._call(
                root,
                fake_export=_fake_export([("image.png", source)]),
                render_images=[_render(0)],
            )

            record = result[0]
            self.assertEqual(record["status"], "verified_asset_render")
            self.assertEqual(record["normalizations"], ["png_trailing_bytes_removed"])
            self.assertEqual(
                record["source_asset_sha256"], hashlib.sha256(source).hexdigest()
            )
            self.assertEqual(record["source_byte_size"], len(source))
            self.assertEqual(record["asset_sha256"], hashlib.sha256(canonical).hexdigest())
            self.assertEqual(record["byte_size"], len(canonical))
            self.assertEqual(
                (output / record["asset_relpath"]).read_bytes(), canonical
            )

    def test_valid_wmf_is_explicitly_unsupported_and_unlinks_document(self) -> None:
        wmf = _wmf(trailing=b"private-binary-trailer")
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            output, result = self._call(
                root,
                fake_export=_fake_export(
                    [("legacy.wmf", wmf), ("supported.png", _png())]
                ),
                render_images=[_render(0), _render(1, sequence=1)],
            )

            self.assertEqual(
                [record["status"] for record in result],
                [
                    "unsupported_source_asset",
                    "asset_only_unlinked",
                    "render_only_missing_asset",
                    "render_only_missing_asset",
                ],
            )
            unsupported = result[0]
            self.assertEqual(unsupported["source_media_type"], "image/wmf")
            self.assertEqual(
                unsupported["source_asset_sha256"], hashlib.sha256(wmf).hexdigest()
            )
            self.assertEqual(unsupported["source_byte_size"], len(wmf))
            self.assertIsNone(unsupported["asset_relpath"])
            self.assertEqual(
                unsupported["link_method"],
                "doclang_picture_unsupported_unlinked",
            )
            self.assertEqual(
                unsupported["warnings"],
                ["image_format_unsupported", "wmf_trailing_bytes_present"],
            )
            self.assertFalse(
                any(record["status"] == "verified_asset_render" for record in result)
            )
            self.assertEqual(len(list((output / "objects").iterdir())), 1)

    def test_valid_gif_is_explicitly_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            _, result = self._call(
                Path(name),
                fake_export=_fake_export([("legacy.gif", _gif())]),
                render_images=[_render(0)],
            )

            self.assertEqual(
                [record["status"] for record in result],
                ["unsupported_source_asset", "render_only_missing_asset"],
            )
            self.assertEqual(result[0]["source_media_type"], "image/gif")
            self.assertEqual(result[0]["normalizations"], [])

    def test_malformed_recognized_legacy_formats_fail_closed(self) -> None:
        cases = [
            ("legacy.wmf", _wmf()[:-1], "rhwp_doclang_asset_invalid_wmf"),
            ("legacy.gif", _gif()[:-1], "rhwp_doclang_asset_invalid_gif"),
        ]
        for filename, payload, error_code in cases:
            with self.subTest(error_code=error_code):
                with tempfile.TemporaryDirectory() as name:
                    with self.assertRaisesRegex(ValueError, f"^{error_code}$"):
                        self._call(
                            Path(name),
                            fake_export=_fake_export([(filename, payload)]),
                            render_images=[_render(0)],
                        )

    def test_truncated_or_corrupt_image_payloads_fail_closed(self) -> None:
        corrupt_png = bytearray(_png())
        corrupt_png[-1] ^= 0x01
        cases = [
            (_png()[:-1], ".png", "rhwp_doclang_asset_invalid_png"),
            (bytes(corrupt_png), ".png", "rhwp_doclang_asset_invalid_png"),
            (_jpeg()[:-1], ".jpg", "rhwp_doclang_asset_invalid_jpeg"),
            (_bmp()[:-1], ".bmp", "rhwp_doclang_asset_invalid_bmp"),
            (_tiff()[:-1], ".tif", "rhwp_doclang_asset_invalid_tiff"),
        ]
        for payload, suffix, error_code in cases:
            with self.subTest(suffix=suffix, error_code=error_code), self.assertRaisesRegex(
                ValueError, f"^{error_code}$"
            ):
                _inspect_image(payload, suffix)

    def test_dimension_and_pixel_caps_fail_before_persistence(self) -> None:
        with patch(
            "midprojectrag.ingest.hwp_assets.MAX_IMAGE_DIMENSION", 3
        ), self.assertRaisesRegex(
            ValueError, "^rhwp_doclang_asset_dimensions_exceeded$"
        ):
            _inspect_image(_png(), ".png")
        with patch(
            "midprojectrag.ingest.hwp_assets.MAX_IMAGE_PIXELS", 7
        ), self.assertRaisesRegex(
            ValueError, "^rhwp_doclang_asset_dimensions_exceeded$"
        ):
            _inspect_image(_png(), ".png")

    def test_doctype_and_entity_are_rejected_before_xml_parse(self) -> None:
        unsafe = b'<!DOCTYPE doc [<!ENTITY x "boom">]><doclang>&x;</doclang>'
        with tempfile.TemporaryDirectory() as name:
            with self.assertRaisesRegex(ValueError, "^rhwp_doclang_xml_unsafe$"):
                self._call(
                    Path(name),
                    fake_export=_fake_export(
                        [],
                        xml=unsafe,
                        metadata_updates={"assetCount": 0},
                    ),
                    render_images=[],
                )

    def test_path_escape_is_rejected_without_disclosing_the_path(self) -> None:
        xml = b'<doclang><picture><src uri="outside.png"/></picture></doclang>'

        def escaped(command, source_path, workdir, timeout_seconds):
            del command, source_path, timeout_seconds
            (workdir / "outside.png").write_bytes(_png())
            (workdir / "document.xml").write_bytes(xml)
            return json.dumps(
                {
                    "schemaVersion": "1.0",
                    "format": "doclang",
                    "output": "document.xml",
                    "assetsDir": "assets",
                    "bytes": len(xml),
                    "assetCount": 1,
                    "lossCount": 0,
                    "untrustedContent": False,
                    "untrustedFields": [],
                }
            ).encode()

        with tempfile.TemporaryDirectory() as name:
            with self.assertRaises(ValueError) as raised:
                self._call(
                    Path(name),
                    fake_export=escaped,
                    render_images=[_render(0)],
                )
            self.assertEqual(str(raised.exception), "rhwp_doclang_asset_path_escape")
            self.assertNotIn(name, str(raised.exception))
            self.assertIsNone(raised.exception.__cause__)

    def test_unique_prefix_without_table_structure_fails_closed(self) -> None:
        xml = (
            b'<doclang><picture><src uri="assets/'
            b'section-0-block-3-cell-1-1-block-0.tif"/></picture></doclang>'
        )
        with tempfile.TemporaryDirectory() as name:
            with self.assertRaisesRegex(
                ValueError, "^rhwp_doclang_asset_uri_ambiguous$"
            ):
                self._call(
                    Path(name),
                    fake_export=_fake_export(
                        [("section-0-block-3-cell-3-block-0.tif", _tiff())],
                        xml=xml,
                    ),
                    render_images=[_render(0)],
                )

    def test_rhwp_filename_drift_fallback_rejects_ambiguous_prefix(self) -> None:
        xml = (
            b'<doclang><picture><src uri="assets/'
            b'section-0-block-3-cell-1-1-block-0.tif"/></picture></doclang>'
        )
        with tempfile.TemporaryDirectory() as name:
            with self.assertRaisesRegex(
                ValueError, "^rhwp_doclang_asset_uri_ambiguous$"
            ):
                self._call(
                    Path(name),
                    fake_export=_fake_export(
                        [("section-0-block-3-cell-3-block-0.tif", _tiff())],
                        xml=xml,
                        extra_files=[
                            ("section-0-block-3-cell-4-block-0.tif", _tiff())
                        ],
                    ),
                    render_images=[_render(0)],
                )

    def test_picture_block_ordinal_without_table_structure_fails_closed(self) -> None:
        xml = (
            b'<doclang><picture><src uri="assets/'
            b'section-0-block-363-cell-0-0-block-0.jpg"/></picture>'
            b'<picture><src uri="assets/'
            b'section-0-block-363-cell-0-0-block-1.jpg"/></picture></doclang>'
        )
        with tempfile.TemporaryDirectory() as name:
            with self.assertRaisesRegex(
                ValueError, "^rhwp_doclang_asset_uri_ambiguous$"
            ):
                self._call(
                    Path(name),
                    fake_export=_fake_export(
                        [
                            ("section-0-block-363-cell-0-block-0.jpg", _jpeg()),
                            ("section-0-block-363-cell-0-block-1.jpg", _jpeg()),
                        ],
                        xml=xml,
                    ),
                    render_images=[_render(0), _render(1, sequence=1)],
                )

    def test_namespaced_header_anchor_and_merge_tokens_reconstruct_exactly(self) -> None:
        xml = (
            b'<d:doclang xmlns:d="urn:rhwp-doclang"><d:table>'
            b"<d:ched/><d:text/><d:lcel/><d:nl/>"
            b"<d:ucel/><d:ched/>"
            b'<d:picture><d:src uri="assets/'
            b'section-0-block-51-cell-1-1-block-0.png"/></d:picture>'
            b"<d:nl/></d:table></d:doclang>"
        )
        with tempfile.TemporaryDirectory() as name:
            _, result = self._call(
                Path(name),
                fake_export=_fake_export(
                    [("section-0-block-51-cell-1-block-0.png", _png())],
                    xml=xml,
                ),
                render_images=[_render(0)],
            )

            self.assertEqual(result[0]["status"], "verified_asset_render")

    def test_nested_block_location_reconstructs_only_the_structural_cell(self) -> None:
        xml = (
            b"<doclang><table><fcel/><text/><fcel/>"
            b'<picture><src uri="assets/'
            b'section-0-block-674-block-0-cell-0-1-block-0.png"/>'
            b"</picture></table></doclang>"
        )
        with tempfile.TemporaryDirectory() as name:
            _, result = self._call(
                Path(name),
                fake_export=_fake_export(
                    [
                        (
                            "section-0-block-674-block-0-cell-1-block-0.png",
                            _png(),
                        )
                    ],
                    xml=xml,
                ),
                render_images=[_render(0)],
            )

            self.assertEqual(result[0]["status"], "verified_asset_render")

    def test_picture_after_empty_or_merge_token_fails_closed(self) -> None:
        for token in (b"ecel", b"lcel", b"ucel", b"xcel"):
            with self.subTest(token=token.decode()), tempfile.TemporaryDirectory() as name:
                xml = (
                    b"<doclang><table><fcel/><text/><"
                    + token
                    + b"/>"
                    + b'<picture><src uri="assets/'
                    + b'section-0-block-9-cell-0-1-block-0.png"/>'
                    + b"</picture></table></doclang>"
                )
                with self.assertRaisesRegex(
                    ValueError, "^rhwp_doclang_asset_uri_ambiguous$"
                ):
                    self._call(
                        Path(name),
                        fake_export=_fake_export(
                            [("section-0-block-9-cell-0-block-0.png", _png())],
                            xml=xml,
                        ),
                        render_images=[_render(0)],
                    )

    def test_rhwp_table_stream_disambiguates_with_empty_cell_positions(self) -> None:
        xml = (
            b"<doclang><table>"
            b"<fcel/><text/><lcel/><ecel/><nl/>"
            b'<fcel/><picture><src uri="assets/'
            b'section-0-block-10-cell-1-0-block-0.bmp"/></picture>'
            b'<fcel/><picture><src uri="assets/'
            b'section-0-block-10-cell-1-1-block-0.bmp"/></picture>'
            b"<lcel/><nl/>"
            b"</table></doclang>"
        )
        with tempfile.TemporaryDirectory() as name:
            _, result = self._call(
                Path(name),
                fake_export=_fake_export(
                    [
                        ("section-0-block-10-cell-2-block-0.bmp", _bmp()),
                        ("section-0-block-10-cell-3-block-0.bmp", _bmp()),
                    ],
                    xml=xml,
                ),
                render_images=[_render(0), _render(1, sequence=1)],
            )

            self.assertEqual(
                [record["status"] for record in result],
                ["verified_asset_render", "verified_asset_render"],
            )

    def test_ecel_hole_cannot_shift_a_later_picture_to_another_asset(self) -> None:
        xml = (
            b"<doclang><table>"
            b'<fcel/><picture><src uri="assets/'
            b'section-0-block-10-cell-0-0-block-0.png"/></picture>'
            b"<ecel/>"
            b'<fcel/><picture><src uri="assets/'
            b'section-0-block-10-cell-0-2-block-0.png"/></picture>'
            b"<nl/></table></doclang>"
        )
        # If ecel is a grid hole, rhwp's asset collector numbers the second
        # anchor as cell 1. The OTSL-only count yields cell 2, so the resolver
        # must stop instead of shifting the picture to a different asset.
        with tempfile.TemporaryDirectory() as name:
            with self.assertRaisesRegex(
                ValueError, "^rhwp_doclang_asset_uri_ambiguous$"
            ):
                self._call(
                    Path(name),
                    fake_export=_fake_export(
                        [
                            ("section-0-block-10-cell-0-block-0.png", _png()),
                            ("section-0-block-10-cell-1-block-0.png", _png()),
                        ],
                        xml=xml,
                    ),
                    render_images=[_render(0), _render(1, sequence=1)],
                )

    def test_rhwp_nested_table_stream_disambiguates_every_cell_depth(self) -> None:
        xml = (
            b"<doclang><table>"
            b"<fcel/><text/><ecel/><fcel/><table>"
            b"<fcel/><text/><ecel/>"
            b'<fcel/><picture><src uri="assets/'
            b"section-0-block-462-cell-0-7-block-0-cell-0-2-block-0.bmp"
            b'"/></picture><ecel/>'
            b'<fcel/><picture><src uri="assets/'
            b"section-0-block-462-cell-0-7-block-0-cell-1-1-block-0.bmp"
            b'"/></picture>'
            b"</table></table></doclang>"
        )
        with tempfile.TemporaryDirectory() as name:
            _, result = self._call(
                Path(name),
                fake_export=_fake_export(
                    [
                        (
                            "section-0-block-462-cell-2-block-0-cell-2-block-0.bmp",
                            _bmp(),
                        ),
                        (
                            "section-0-block-462-cell-2-block-0-cell-4-block-0.bmp",
                            _bmp(),
                        ),
                    ],
                    xml=xml,
                ),
                render_images=[_render(0), _render(1, sequence=1)],
            )

            self.assertEqual(
                [record["status"] for record in result],
                ["verified_asset_render", "verified_asset_render"],
            )

    def test_duplicate_uri_symlink_and_inventory_surplus_fail_closed(self) -> None:
        cases = [
            (
                _fake_export(
                    [("same.png", _png()), ("same.png", _png())]
                ),
                "rhwp_doclang_asset_uri_invalid",
            ),
            (
                _fake_export(
                    [("real.png", _png())],
                    xml=b'<doclang><picture><src uri="assets/link.png"/></picture></doclang>',
                    symlink=("link.png", "real.png"),
                ),
                "rhwp_doclang_asset_symlink",
            ),
            (
                _fake_export(
                    [("image.png", _png())],
                    extra_files=[("surplus.png", _png())],
                ),
                "rhwp_doclang_asset_inventory_mismatch",
            ),
        ]
        for fake, error_code in cases:
            with self.subTest(error_code=error_code):
                with tempfile.TemporaryDirectory() as name:
                    with self.assertRaisesRegex(ValueError, f"^{error_code}$"):
                        self._call(
                            Path(name),
                            fake_export=fake,
                            render_images=[_render(0)],
                        )

    def test_unknown_magic_and_size_bound_fail_closed(self) -> None:
        cases = [
            (
                _fake_export([("image.bin", b"not-an-image")]),
                "rhwp_doclang_asset_magic_unknown",
                None,
            ),
            (
                _fake_export([("image.png", _png())]),
                "rhwp_doclang_asset_too_large",
                4,
            ),
        ]
        for fake, error_code, size_limit in cases:
            with self.subTest(error_code=error_code):
                with tempfile.TemporaryDirectory() as name:
                    limit = (
                        patch(
                            "midprojectrag.ingest.hwp_assets.MAX_ASSET_BYTES",
                            size_limit,
                        )
                        if size_limit is not None
                        else patch(
                            "midprojectrag.ingest.hwp_assets.MAX_ASSET_BYTES",
                            64 * 1024 * 1024,
                        )
                    )
                    with limit, self.assertRaisesRegex(ValueError, f"^{error_code}$"):
                        self._call(
                            Path(name),
                            fake_export=fake,
                            render_images=[_render(0)],
                        )

    def test_all_source_assets_validate_before_any_object_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            with self.assertRaisesRegex(
                ValueError, "^rhwp_doclang_asset_magic_unknown$"
            ):
                output, _ = self._call(
                    root,
                    fake_export=_fake_export(
                        [("valid.png", _png()), ("invalid.bin", b"invalid")]
                    ),
                    render_images=[_render(0), _render(1)],
                )
            output = root / "private-assets"
            self.assertFalse((output / "objects").exists())

    def test_bounded_runner_sanitizes_stdout_overflow_and_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "synthetic.hwp"
            source.write_bytes(b"synthetic")
            overflow = root / "overflow-rhwp"
            overflow.write_text("#!/bin/sh\nprintf '12345'\n", encoding="utf-8")
            overflow.chmod(0o700)
            with patch(
                "midprojectrag.ingest.hwp_assets.MAX_DOCLANG_STDOUT_BYTES", 4
            ), self.assertRaisesRegex(
                ValueError, "^rhwp_doclang_output_too_large$"
            ):
                _run_export_doclang(overflow.as_posix(), source, root, 2)

            looping = root / "looping-rhwp"
            looping.write_text("#!/bin/sh\nwhile :; do :; done\n", encoding="utf-8")
            looping.chmod(0o700)
            with self.assertRaisesRegex(ValueError, "^rhwp_doclang_timeout$"):
                _run_export_doclang(looping.as_posix(), source, root, 1)

            closed = root / "closed-pipes-rhwp"
            closed.write_text(
                "#!/bin/sh\nexec 1>&-\nexec 2>&-\nexec sleep 2\n",
                encoding="utf-8",
            )
            closed.chmod(0o700)
            with self.assertRaisesRegex(ValueError, "^rhwp_doclang_timeout$"):
                _run_export_doclang(closed.as_posix(), source, root, 1)

    def test_malformed_render_contract_fails_before_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "synthetic.hwp"
            source.write_bytes(b"synthetic")
            bad = _render(0)
            bad["page"] = 0
            with patch(
                "midprojectrag.ingest.hwp_assets._run_export_doclang"
            ) as run, self.assertRaisesRegex(
                ValueError, "^render_image_contract_invalid$"
            ):
                materialize_hwp_assets(
                    command="unused",
                    source_path=source,
                    doc_id=DOC_ID,
                    render_images=[bad],
                    output_root=root / "output",
                )
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
