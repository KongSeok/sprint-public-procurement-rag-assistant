"""Offline OCR-only implementation of the local visual adapter JSON protocol.

Never instantiate PP-StructureV3: existing crop locators already supply the region.
Only detection and Korean recognition are enabled; no table or semantic claims.
"""
from __future__ import annotations

import importlib.metadata
import json
import math
import os
import sys
import tempfile
from pathlib import Path

from midprojectrag.ingest.visual_model_manifest import (
    checked_root, file_sha256, strict_json, verify_manifest,
)

RUNTIME = "paddleocr-3.3.2-ocr-only-cpu-v1"
DISABLED = ("use_doc_orientation_classify", "use_textline_orientation",
            "use_table_recognition", "use_ocr_results_with_table_cells")


def validate_request(envelope: dict) -> tuple[Path, Path, dict]:
    if (not isinstance(envelope, dict)
            or set(envelope) != {"schema_version", "operation", "model_artifact_path", "request"}
            or envelope["schema_version"] != "1.0" or envelope["operation"] != "ocr_layout_v1"):
        raise ValueError("ocr_request_contract_invalid")
    request = envelope["request"]
    if (not isinstance(request, dict) or set(request) != {
        "schema_version", "crop_path", "crop_sha256", "occurrence_id", "page", "bbox",
        "coordinate_space", "config"
    } or request["schema_version"] != "1.0"):
        raise ValueError("ocr_request_contract_invalid")
    config = request["config"]
    expected = {
        "config_contract", "pipeline", "ocr_version", "language", "model_version", "weights_sha256",
        "runtime", "device", "text_rec_score_thresh", *DISABLED, "max_text_items", "max_table_cells",
        "model_download",
    }
    if (not isinstance(config, dict) or set(config) != expected
            or config["runtime"] != RUNTIME or config["device"] != "cpu"
            or config["model_download"] != "forbidden" or config["max_table_cells"] != 0
            or any(config[key] is not False for key in DISABLED)
            or config["pipeline"] != "PP-StructureV3" or config["ocr_version"] != "PP-OCRv5"
            or config["language"] != "korean" or config["model_version"] != "paddle3.0.0-official"
            or config["config_contract"] != "pp-structure-v3-korean-ppocrv5-v1"
            or type(config["max_text_items"]) is not int or not 1 <= config["max_text_items"] <= 10000
            or type(config["text_rec_score_thresh"]) not in (int, float)
            or not 0 <= config["text_rec_score_thresh"] <= 1):
        raise ValueError("ocr_minimal_profile_required")
    manifest = Path(envelope["model_artifact_path"])
    if (not manifest.is_absolute() or manifest.name != "model-manifest.json"
            or manifest.is_symlink()):
        raise ValueError("ocr_manifest_path_invalid")
    root = checked_root(manifest.parent)
    if verify_manifest(root) != config["weights_sha256"]:
        raise ValueError("ocr_manifest_pin_mismatch")
    crop = Path(request["crop_path"])
    if (not crop.is_absolute() or crop.is_symlink() or crop.resolve() != crop
            or not crop.is_file() or not 8 <= crop.stat().st_size <= 128 * 1024 * 1024
            or file_sha256(crop) != request["crop_sha256"]):
        raise ValueError("ocr_crop_invalid")
    from PIL import Image
    with Image.open(crop) as image:
        if (image.format != "PNG" or getattr(image, "n_frames", 1) != 1
                or image.width * image.height > 40_000_000):
            raise ValueError("ocr_crop_invalid")
        image.verify()
    return root, crop, config


def check_runtime(lock: Path) -> None:
    for line in lock.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        name, expected = line.split("==")
        if importlib.metadata.version(name) != expected:
            raise ValueError("ocr_runtime_version_mismatch")


def pipeline_options(root: Path, config: dict) -> dict:
    return {
        "text_detection_model_name": "PP-OCRv5_server_det",
        "text_detection_model_dir": str(root / "PP-OCRv5_server_det_infer"),
        "text_recognition_model_name": "korean_PP-OCRv5_mobile_rec",
        "text_recognition_model_dir": str(root / "korean_PP-OCRv5_mobile_rec_infer"),
        "use_doc_orientation_classify": False, "use_doc_unwarping": False,
        "use_textline_orientation": False, "text_recognition_batch_size": 1,
        "text_det_limit_side_len": 1280, "text_det_limit_type": "max",
        "text_rec_score_thresh": config["text_rec_score_thresh"],
        "device": "cpu", "cpu_threads": 1, "enable_mkldnn": False,
        "enable_hpi": False,
    }


def normalize_prediction(result: dict, *, maximum: int, width: int, height: int) -> dict:
    texts, scores, polygons = result["rec_texts"], result["rec_scores"], result["rec_polys"]
    if len(texts) != len(scores) or len(texts) != len(polygons) or len(texts) > maximum:
        raise ValueError("ocr_result_lengths_invalid")
    items = []
    for text, score, polygon in zip(texts, scores, polygons, strict=True):
        points = [[float(x), float(y)] for x, y in polygon]
        if (not isinstance(text, str) or not text.strip() or len(text) > 10000
                or not math.isfinite(float(score)) or not 0 <= float(score) <= 1
                or len(points) != 4 or any(not math.isfinite(x) or not math.isfinite(y)
                    or not 0 <= x <= width or not 0 <= y <= height for x, y in points)):
            raise ValueError("ocr_result_item_invalid")
        items.append({"text": text, "confidence": float(score), "polygon": points,
                      "reading_order": len(items)})
    return {"schema_version": "1.0", "status": "success" if items else "low_confidence",
            "text_items": items, "table_cells": [],
            "warnings": ["ocr_only_no_document_layout", "ocr_only_no_table_recognition"]
                        + ([] if items else ["ocr_no_text_detected"])}


def infer(envelope: dict, *, lock: Path) -> dict:
    if os.environ.get("MIDPROJECTRAG_NETWORK_DISABLED") != "1":
        raise ValueError("ocr_requires_network_sandbox_adapter")
    check_runtime(lock)
    root, crop, config = validate_request(envelope)
    # The OS sandbox, not these hints, enforces zero egress. Hints avoid checks/download attempts.
    os.environ.update({"PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
                       "PADDLE_PDX_MODEL_SOURCE": "BOS", "HF_HUB_OFFLINE": "1",
                       "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
                       "VECLIB_MAXIMUM_THREADS": "1", "MKL_NUM_THREADS": "1"})
    # Any incidental PaddleX cache stays in a private, task-owned temporary directory.
    with tempfile.TemporaryDirectory(prefix=".ocr-runtime-", dir=root.parent) as cache:
        os.environ["PADDLE_PDX_CACHE_HOME"] = cache
        from paddleocr import PaddleOCR
        from PIL import Image
        engine = PaddleOCR(**pipeline_options(root, config))
        results = engine.predict(str(crop))
        if len(results) != 1:
            raise ValueError("ocr_result_count_invalid")
        with Image.open(crop) as image:
            output = normalize_prediction(results[0], maximum=config["max_text_items"],
                                          width=image.width, height=image.height)
    # Recheck consumed files and source after inference as well.
    if verify_manifest(root) != config["weights_sha256"] or file_sha256(crop) != envelope["request"]["crop_sha256"]:
        raise ValueError("ocr_input_changed_during_inference")
    return output


def main() -> int:
    # Suppress native stdout as well as Python logs; protocol stdout contains one JSON object only.
    protocol_fd = os.dup(1)
    with open(os.devnull, "w") as sink:
        os.dup2(sink.fileno(), 1)
        os.dup2(sink.fileno(), 2)
        try:
            data = sys.stdin.buffer.read(1024 * 1024 + 1)
            if len(data) > 1024 * 1024:
                raise ValueError("ocr_request_too_large")
            lock = Path(__file__).resolve().parents[3] / "configs/visual/requirements-ocr-cpu.lock"
            output = infer(strict_json(data.decode("utf-8")), lock=lock)
            payload = (json.dumps(output, ensure_ascii=False, allow_nan=False) + "\n").encode()
            if len(payload) > 8 * 1024 * 1024:
                raise ValueError("ocr_response_too_large")
        except Exception:
            # Never emit exception messages/tracebacks that could contain private paths or text.
            os.close(protocol_fd)
            return 2
        with os.fdopen(protocol_fd, "wb") as output:
            output.write(payload)
    return 0
