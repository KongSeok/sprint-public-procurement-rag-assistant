from __future__ import annotations

import copy
import hashlib
import json
import os
import platform
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

from midprojectrag.ingest.common import canonical_json, sha256_file
from midprojectrag.ingest.visual_understanding import (
    CaptionModelConfig,
    DeterministicFixtureAdapter,
    PinnedLocalJsonCommandAdapter,
    PpStructureV3Config,
    VisualRetrievalPolicy,
    VisualUnderstandingError,
    apply_caption_caps,
    build_visual_chunks,
    caption_cache_key,
    ocr_cache_key,
    run_local_caption,
    run_local_ocr,
)


ROOT = Path(__file__).resolve().parents[2]
DOC_ID = "doc_0123456789abcdef01234567"
OCCURRENCE_ID = "vocc2_0123456789abcdef01234567"
OCR_WEIGHTS_SHA256 = "a" * 64
CAPTION_WEIGHTS_SHA256 = "b" * 64
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _polygon(x: float, y: float, w: float, h: float) -> list[list[float]]:
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def _ocr_response() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "status": "success",
        "text_items": [
            {
                "polygon": _polygon(0, 0, 80, 12),
                "text": "샘플 노드 A",
                "confidence": 0.99,
                "reading_order": 0,
            },
            {
                "polygon": _polygon(0, 14, 80, 12),
                "text": "샘플 업무시스템",
                "confidence": 0.91,
                "reading_order": 1,
            },
        ],
        "table_cells": [
            {
                "row": 0,
                "column": 0,
                "row_span": 1,
                "column_span": 2,
                "polygon": _polygon(0, 0, 100, 30),
                "text": "샘플 노드 A 샘플 업무시스템",
                "confidence": 0.94,
                "source_reading_orders": [0, 1],
            }
        ],
        "warnings": [],
    }


class VisualUnderstandingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ocr_validator = Draft202012Validator(
            json.loads((ROOT / "contracts" / "ocr-evidence-v1.schema.json").read_text())
        )
        cls.caption_validator = Draft202012Validator(
            json.loads((ROOT / "contracts" / "caption-evidence-v1.schema.json").read_text())
        )
        cls.chunk_validator = Draft202012Validator(
            json.loads((ROOT / "contracts" / "visual-chunk-v1.schema.json").read_text())
        )
        for validator in (cls.ocr_validator, cls.caption_validator, cls.chunk_validator):
            Draft202012Validator.check_schema(validator.schema)

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.private_root = Path(temporary.name).resolve()
        crop_bytes = PNG_SIGNATURE + b"synthetic-private-crop"
        crop_sha256 = hashlib.sha256(crop_bytes).hexdigest()
        crop_dir = self.private_root / "crops"
        crop_dir.mkdir()
        (crop_dir / f"{crop_sha256}.png").write_bytes(crop_bytes)
        self.occurrence: dict[str, object] = {
            "doc_id": DOC_ID,
            "occurrence_id": OCCURRENCE_ID,
            "page": 7,
            "bbox": {"x": 12.5, "y": 24.0, "w": 310.0, "h": 180.0},
            "coordinate_space": "pdf_points_top_left",
            "crop_sha256": crop_sha256,
            "crop_relpath": f"crops/{crop_sha256}.png",
            "crop_media_type": "image/png",
            "placement_status": "page_bbox_verified",
            "retrieval_status": "eligible",
        }
        self.ocr_config = PpStructureV3Config(
            model_version="3.2.0",
            weights_sha256=OCR_WEIGHTS_SHA256,
            runtime="paddlepaddle-3.2.0",
            device="cpu",
        )
        self.ocr_adapter = DeterministicFixtureAdapter(
            responses={"ocr_layout_v1": _ocr_response()},
            model_artifact_sha256=OCR_WEIGHTS_SHA256,
        )

    def _run_ocr(self) -> dict[str, object]:
        return run_local_ocr(
            self.occurrence,
            private_root=self.private_root,
            adapter=self.ocr_adapter,
            config=self.ocr_config,
        )

    def _caption_config(self, **overrides: object) -> CaptionModelConfig:
        values: dict[str, object] = {
            "model_name": "local-diagram-vlm",
            "model_version": "fixture-1",
            "weights_sha256": CAPTION_WEIGHTS_SHA256,
            "runtime": "transformers-offline",
            "device": "cpu",
            "prompt": "OCR support_refs가 있는 사실만 기술하라.",
        }
        values.update(overrides)
        return CaptionModelConfig(**values)  # type: ignore[arg-type]

    def test_pp_structure_identity_and_ocr_evidence_are_deterministic(self) -> None:
        identity = self.ocr_config.identity
        self.assertEqual(identity["pipeline"], "PP-StructureV3")
        self.assertEqual(identity["ocr_version"], "PP-OCRv5")
        self.assertEqual(identity["language"], "korean")
        self.assertEqual(identity["model_download"], "forbidden")

        first = self._run_ocr()
        second = self._run_ocr()
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "success")
        self.assertEqual(len(first["text_items"]), 2)
        self.assertEqual(first["model"]["language"], "korean")
        self.ocr_validator.validate(first)

        fixture_copy = self.ocr_adapter.infer("ocr_layout_v1", {})
        fixture_copy["warnings"].append("mutated")
        self.assertEqual(self.ocr_adapter.infer("ocr_layout_v1", {})["warnings"], [])

    def test_ocr_cache_is_crop_config_and_adapter_addressed(self) -> None:
        first = ocr_cache_key(self.occurrence, self.ocr_config, self.ocr_adapter)
        repeated_crop = dict(self.occurrence)
        repeated_crop["occurrence_id"] = "vocc2_fedcba9876543210fedcba98"
        second = ocr_cache_key(repeated_crop, self.ocr_config, self.ocr_adapter)
        self.assertEqual(first, second)
        self.assertRegex(first, r"^[0-9a-f]{64}$")

        different_config = PpStructureV3Config(
            model_version="3.2.1",
            weights_sha256=OCR_WEIGHTS_SHA256,
            runtime="paddlepaddle-3.2.0",
            device="cpu",
        )
        self.assertNotEqual(
            first,
            ocr_cache_key(self.occurrence, different_config, self.ocr_adapter),
        )

    def test_ocr_low_confidence_and_model_pin_mismatch_fail_closed(self) -> None:
        response = _ocr_response()
        response["text_items"][1]["confidence"] = 0.2
        adapter = DeterministicFixtureAdapter(
            responses={"ocr_layout_v1": response},
            model_artifact_sha256=OCR_WEIGHTS_SHA256,
        )
        evidence = run_local_ocr(
            self.occurrence,
            private_root=self.private_root,
            adapter=adapter,
            config=self.ocr_config,
        )
        self.assertEqual(evidence["status"], "low_confidence")
        self.assertIn("ocr_below_configured_threshold", evidence["warnings"])
        self.ocr_validator.validate(evidence)

        mismatched = DeterministicFixtureAdapter(
            responses={"ocr_layout_v1": _ocr_response()},
            model_artifact_sha256="c" * 64,
        )
        with self.assertRaisesRegex(VisualUnderstandingError, "model_artifact_config_mismatch"):
            run_local_ocr(
                self.occurrence,
                private_root=self.private_root,
                adapter=mismatched,
                config=self.ocr_config,
            )

    def test_missing_page_bbox_crop_or_eligible_state_fails_closed(self) -> None:
        corruptions = (
            ("page", None),
            ("bbox", None),
            ("crop_sha256", None),
            ("crop_relpath", None),
            ("crop_media_type", None),
            ("placement_status", "doc_only_unlinked"),
            ("retrieval_status", "withheld"),
        )
        for field, value in corruptions:
            with self.subTest(field=field), self.assertRaises(VisualUnderstandingError):
                invalid = dict(self.occurrence)
                invalid[field] = value
                run_local_ocr(
                    invalid,
                    private_root=self.private_root,
                    adapter=self.ocr_adapter,
                    config=self.ocr_config,
                )

        crop_path = self.private_root / str(self.occurrence["crop_relpath"])
        crop_path.write_bytes(PNG_SIGNATURE + b"tampered")
        with self.assertRaisesRegex(VisualUnderstandingError, "visual_crop_checksum_mismatch"):
            self._run_ocr()

        real_crop_dir = self.private_root / "real-crops"
        (self.private_root / "crops").rename(real_crop_dir)
        (self.private_root / "crops").symlink_to(real_crop_dir, target_is_directory=True)
        with self.assertRaisesRegex(VisualUnderstandingError, "visual_crop_symlink_forbidden"):
            self._run_ocr()

    def test_caption_support_refs_reject_unsupported_facts_and_sanitize_description(self) -> None:
        ocr = self._run_ocr()
        supported_ref = ocr["text_items"][0]["item_id"]
        response = {
            "schema_version": "1.0",
            "status": "success",
            "description": (
                "파란 상자가 있다. 샘플 노드 A와 연결된다. "
                "2027년에 완료된다. 운영서버가 승인한다."
            ),
            "claims": [
                {
                    "text": "샘플 노드 A와 연결된다.",
                    "support_refs": [supported_ref],
                },
                {"text": "파란 상자가 있다.", "support_refs": []},
                {"text": "2027년에 완료된다.", "support_refs": []},
                {
                    "text": "운영서버가 승인한다.",
                    "support_refs": ["ocri_ffffffffffffffffffffffff"],
                },
            ],
            "warnings": [],
        }
        config = self._caption_config()
        adapter = DeterministicFixtureAdapter(
            responses={"caption_v1": response},
            model_artifact_sha256=CAPTION_WEIGHTS_SHA256,
        )
        first_key = caption_cache_key(self.occurrence, ocr, config, adapter)
        second_key = caption_cache_key(self.occurrence, ocr, config, adapter)
        self.assertEqual(first_key, second_key)

        caption = run_local_caption(
            self.occurrence,
            ocr,
            private_root=self.private_root,
            adapter=adapter,
            config=config,
        )
        statuses = {claim["text"]: claim["status"] for claim in caption["claims"]}
        self.assertEqual(statuses["샘플 노드 A와 연결된다."], "supported")
        self.assertEqual(statuses["파란 상자가 있다."], "descriptive_only")
        self.assertEqual(statuses["2027년에 완료된다."], "rejected")
        self.assertEqual(statuses["운영서버가 승인한다."], "rejected")
        self.assertNotIn("2027년", caption["description"])
        self.assertNotIn("운영서버", caption["description"])
        self.assertIn("caption_unsupported_factual_claim", caption["warnings"])
        self.assertIn("caption_unknown_support_ref", caption["warnings"])
        self.assertEqual(caption["status"], "success")
        self.caption_validator.validate(caption)

    def test_caption_decode_must_be_deterministic(self) -> None:
        with self.assertRaisesRegex(VisualUnderstandingError, "caption_decode_nondeterministic"):
            self._caption_config(temperature=0.1)
        with self.assertRaisesRegex(VisualUnderstandingError, "caption_decode_nondeterministic"):
            self._caption_config(do_sample=True)

    def test_visual_chunks_are_separate_cited_and_caption_weighted(self) -> None:
        ocr = self._run_ocr()
        supported_ref = ocr["text_items"][0]["item_id"]
        caption_adapter = DeterministicFixtureAdapter(
            responses={
                "caption_v1": {
                    "schema_version": "1.0",
                    "status": "success",
                    "description": "파란 상자가 있다. 샘플 노드 A와 연결된다.",
                    "claims": [
                        {"text": "파란 상자가 있다.", "support_refs": []},
                        {
                            "text": "샘플 노드 A와 연결된다.",
                            "support_refs": [supported_ref],
                        },
                    ],
                    "warnings": [],
                }
            },
            model_artifact_sha256=CAPTION_WEIGHTS_SHA256,
        )
        caption = run_local_caption(
            self.occurrence,
            ocr,
            private_root=self.private_root,
            adapter=caption_adapter,
            config=self._caption_config(),
        )
        chunks = build_visual_chunks(
            self.occurrence,
            ocr_evidence=ocr,
            caption_evidence=caption,
        )
        self.assertEqual(
            {chunk["chunker_id"] for chunk in chunks},
            {"image-ocr-v1", "image-layout-v1", "image-caption-v1"},
        )
        self.assertEqual(
            {chunk["evidence_type"] for chunk in chunks},
            {"ocr", "layout", "caption"},
        )
        for chunk in chunks:
            self.chunk_validator.validate(chunk)
            self.assertEqual(chunk["page"], self.occurrence["page"])
            self.assertEqual(chunk["bbox"], self.occurrence["bbox"])
            self.assertEqual(chunk["crop_sha256"], self.occurrence["crop_sha256"])
            self.assertEqual(chunk["citation"]["page"], self.occurrence["page"])
            self.assertEqual(chunk["citation"]["bbox"], self.occurrence["bbox"])
            self.assertEqual(
                chunk["citation"]["crop_sha256"], self.occurrence["crop_sha256"]
            )
        caption_chunk = next(
            chunk for chunk in chunks if chunk["chunker_id"] == "image-caption-v1"
        )
        self.assertLessEqual(caption_chunk["retrieval_weight"], 0.35)
        self.assertEqual(caption_chunk["answer_support"]["status"], "supported")
        self.assertEqual(caption_chunk["answer_support"]["support_refs"], [supported_ref])

        forged = copy.deepcopy(caption)
        forged["claims"].append(
            {
                "claim_id": "claim_ffffffffffffffffffffffff",
                "text": "2027년에 운영서버가 승인한다.",
                "support_refs": [],
                "status": "descriptive_only",
            }
        )
        with self.assertRaisesRegex(
            VisualUnderstandingError, "caption_unsupported_factual_claim"
        ):
            build_visual_chunks(
                self.occurrence,
                ocr_evidence=ocr,
                caption_evidence=forged,
            )

    def test_caption_caps_are_hard_per_query_and_document(self) -> None:
        base = {
            "evidence_type": "caption",
            "retrieval_weight": 0.35,
            "doc_id": DOC_ID,
            "marker": "first",
        }
        ranked = [
            {"evidence_type": "ocr", "doc_id": DOC_ID, "marker": "ocr"},
            base,
            {**base, "marker": "same-document-second"},
            {
                **base,
                "doc_id": "doc_111111111111111111111111",
                "marker": "second-document",
            },
            {
                **base,
                "doc_id": "doc_222222222222222222222222",
                "marker": "third-document",
            },
        ]
        selected = apply_caption_caps(ranked)
        self.assertEqual(
            [chunk["marker"] for chunk in selected],
            ["ocr", "first", "second-document"],
        )
        with self.assertRaisesRegex(VisualUnderstandingError, "visual_caption_weight_exceeded"):
            VisualRetrievalPolicy(caption_weight=0.36)
        with self.assertRaisesRegex(VisualUnderstandingError, "visual_caption_query_cap_exceeded"):
            VisualRetrievalPolicy(caption_per_query=1.5)  # type: ignore[arg-type]
        overweight = [{**base, "retrieval_weight": 0.351}]
        with self.assertRaisesRegex(VisualUnderstandingError, "visual_caption_chunk_weight_invalid"):
            apply_caption_caps(overweight)
        with self.assertRaisesRegex(VisualUnderstandingError, "visual_caption_chunk_weight_invalid"):
            apply_caption_caps([{**base, "retrieval_weight": 0.0}])

    def test_checksum_pinned_local_command_is_bounded_and_reverified(self) -> None:
        command = self.private_root / "fixture-adapter"
        command.write_text(
            """#!/usr/bin/env python3
import json
import os
import sys
import time

envelope = json.load(sys.stdin)
assert envelope[\"schema_version\"] == \"1.0\"
assert os.environ[\"HF_HUB_OFFLINE\"] == \"1\"
assert os.environ[\"TRANSFORMERS_OFFLINE\"] == \"1\"
assert os.environ[\"MIDPROJECTRAG_NETWORK_DISABLED\"] == \"1\"
if envelope[\"operation\"] == \"overflow\":
    sys.stdout.write(\"x\" * 4096)
elif envelope[\"operation\"] == \"duplicate\":
    sys.stdout.write('{\"ok\":true,\"ok\":false}')
elif envelope[\"operation\"] == \"slow\":
    time.sleep(2)
    json.dump({\"late\": True}, sys.stdout)
else:
    json.dump({\"operation\": envelope[\"operation\"], \"ok\": True}, sys.stdout)
""",
            encoding="utf-8",
        )
        command.chmod(0o700)
        manifest = self.private_root / "model-manifest.json"
        manifest.write_text('{"weights":"fixture"}\n', encoding="utf-8")
        command_hash = sha256_file(command)
        model_hash = sha256_file(manifest)
        if platform.system() == "Darwin":
            sandbox_backend = "darwin-sandbox-exec-v1"
            sandbox_command = Path("/usr/bin/sandbox-exec")
        elif platform.system() == "Linux" and Path("/usr/bin/bwrap").is_file():
            sandbox_backend = "linux-bwrap-v1"
            sandbox_command = Path("/usr/bin/bwrap")
        else:
            self.skipTest("supported OS network sandbox is unavailable")
        sandbox_options = {
            "network_sandbox_backend": sandbox_backend,
            "network_sandbox_command": sandbox_command,
            "network_sandbox_command_sha256": sha256_file(sandbox_command),
        }
        dependency = self.private_root / "wrapper-dependency.py"
        dependency.write_text("# synthetic pinned dependency\n", encoding="utf-8")
        dependency_bytes = dependency.read_bytes()
        adapter = PinnedLocalJsonCommandAdapter(
            command=command,
            command_sha256=command_hash,
            model_artifact=manifest,
            model_artifact_sha256=model_hash,
            pinned_files={dependency: sha256_file(dependency)},
            **sandbox_options,
            timeout_seconds=1.0,
            max_stdout_bytes=256,
        )
        with patch(
            "midprojectrag.ingest.visual_understanding._run_bounded_json",
            return_value={"operation": "ok", "ok": True},
        ) as bounded:
            self.assertEqual(
                adapter.infer("ok", {"secret": "not-logged"}),
                {"operation": "ok", "ok": True},
            )
        sandboxed_argv = bounded.call_args.args[0]
        self.assertEqual(sandboxed_argv[0], str(sandbox_command))
        self.assertIn(str(command), sandboxed_argv)
        self.assertEqual(adapter.identity["network"], "os_sandbox_enforced")
        self.assertNotIn(str(command), canonical_json(adapter.identity))
        self.assertNotIn(str(manifest), canonical_json(adapter.identity))

        dependency.write_text("# tampered dependency\n", encoding="utf-8")
        with self.assertRaisesRegex(VisualUnderstandingError, "local_adapter_dependency_checksum_mismatch"):
            adapter.infer("ok", {})
        dependency.write_bytes(dependency_bytes)

        command.write_text(command.read_text() + "\n# tampered\n", encoding="utf-8")
        command.chmod(0o700)
        with self.assertRaisesRegex(VisualUnderstandingError, "local_adapter_command_checksum_mismatch"):
            adapter.infer("ok", {})

        with self.assertRaisesRegex(VisualUnderstandingError, "local_adapter_command_checksum_mismatch"):
            PinnedLocalJsonCommandAdapter(
                command=command,
                command_sha256="0" * 64,
                model_artifact=manifest,
                model_artifact_sha256=model_hash,
                **sandbox_options,
            )


if __name__ == "__main__":
    unittest.main()
