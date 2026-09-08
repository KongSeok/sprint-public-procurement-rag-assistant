#!/usr/bin/env python3
"""Prepare private, case-scoped image inputs for Golden Set v3 visual questions.

The source archive and generated images stay under ``output/`` and must not be
committed.  Gold answers and required facts are deliberately excluded from the
manifest consumed by the VLM.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import unicodedata
import zipfile
from pathlib import Path
from typing import Any

import fitz
from PIL import Image, ImageDraw, ImageOps


DEFAULT_ARCHIVE = Path("denoising-dirty-documents.Zip")
DEFAULT_GOLDEN = Path("data/golden_set_v3/document-structure-visual-qa.jsonl")
DEFAULT_OUTPUT = Path("output/experiments/b_plan_v3_vlm/private")


def _normal_name(value: str) -> str:
    name = Path(value).name.removeprefix("refined_")
    return " ".join(unicodedata.normalize("NFC", name).split()).casefold()


def _safe_case_id(value: Any) -> str:
    text = str(value)
    if not text or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for ch in text):
        raise ValueError("invalid_case_id")
    return text


def _load_cases(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _find_member(archive: zipfile.ZipFile, source_filename: str) -> str:
    wanted = _normal_name(source_filename)
    matches = [name for name in archive.namelist() if _normal_name(name) == wanted]
    if len(matches) != 1:
        raise ValueError(f"source_member_match_count:{len(matches)}")
    return matches[0]


def _extract_source(archive: zipfile.ZipFile, member: str, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / Path(member).name
    with archive.open(member) as source, target.open("wb") as output:
        shutil.copyfileobj(source, output)
    return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _render_pdf_regions(case: dict[str, Any], source: Path, output: Path) -> list[dict[str, Any]]:
    rendered: list[dict[str, Any]] = []
    document = fitz.open(source)
    try:
        for index, ref in enumerate(case.get("gold", {}).get("evidence_refs", []), start=1):
            page_number = int(ref["page"])
            page = document[page_number - 1]
            bbox = ref.get("bbox") or {}
            clip = fitz.Rect(
                float(bbox["x"]),
                float(bbox["y"]),
                float(bbox["x"]) + float(bbox["w"]),
                float(bbox["y"]) + float(bbox["h"]),
            ) & page.rect
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=clip, alpha=False)
            crop_path = output / f"region-{index:02d}-page-{page_number}.png"
            pixmap.save(crop_path)
            page_path = output / f"full-page-{page_number}.png"
            page.get_pixmap(matrix=fitz.Matrix(1.25, 1.25), alpha=False).save(page_path)

            with Image.open(crop_path) as crop_source, Image.open(page_path) as page_source:
                crop_image = crop_source.convert("RGB")
                page_image = page_source.convert("RGB")
                crop_image.thumbnail((1200, 650))
                page_image.thumbnail((1200, 1500))
                width = max(crop_image.width, page_image.width) + 20
                height = crop_image.height + page_image.height + 100
                context_sheet = Image.new("RGB", (width, height), "white")
                draw = ImageDraw.Draw(context_sheet)
                draw.text((10, 10), "TARGET REGION", fill="black")
                context_sheet.paste(crop_image, (10, 35))
                page_label_y = crop_image.height + 55
                draw.text((10, page_label_y), "FULL PAGE CONTEXT", fill="black")
                context_sheet.paste(page_image, (10, page_label_y + 25))
            path = output / f"figure-context-{index:02d}-page-{page_number}.jpg"
            context_sheet.save(path, format="JPEG", quality=94, optimize=True)
            rendered.append(
                {
                    "path": str(path.resolve()),
                    "page": page_number,
                    "bbox": {key: float(bbox[key]) for key in ("x", "y", "w", "h")},
                    "coordinate_space": str(ref.get("coordinate_space") or "pdf_points_top_left"),
                    "image_sha256": _sha256(path),
                    "source_image_sha256s": [_sha256(crop_path), _sha256(page_path)],
                    "provenance_level": "page_bbox_verified",
                }
            )
    finally:
        document.close()
    return rendered


def _extract_hwp_candidates(source: Path, output: Path, limit: int) -> list[dict[str, Any]]:
    html_root = output / "hwp-html"
    html_root.mkdir(parents=True, exist_ok=True)
    command = shutil.which("hwp5html")
    if not command:
        raise RuntimeError("hwp5html_not_found")
    subprocess.run(
        [command, "--output", str(html_root), str(source)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    ranked: list[tuple[int, Path]] = []
    for path in html_root.rglob("*"):
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp", ".gif"}:
            continue
        try:
            with Image.open(path) as image:
                width, height = image.size
            area = width * height
            if width >= 160 and height >= 100 and area >= 40_000:
                ranked.append((area, path))
        except OSError:
            continue
    ranked.sort(key=lambda item: (-item[0], item[1].as_posix()))
    candidates = output / "candidates"
    candidates.mkdir(exist_ok=True)
    selected: list[dict[str, Any]] = []
    for index, (_, source_image) in enumerate(ranked[:limit], start=1):
        target = candidates / f"candidate-{index:02d}{source_image.suffix.lower()}"
        shutil.copy2(source_image, target)
        selected.append(
            {
                "path": str(target.resolve()),
                "page": None,
                "bbox": None,
                "coordinate_space": None,
                "image_sha256": _sha256(target),
                "provenance_level": "document_candidate_only",
            }
        )
    if not selected:
        return []

    cell_width, cell_height = 700, 520
    columns = 2
    rows = (len(selected) + columns - 1) // columns
    sheet = Image.new("RGB", (cell_width * columns, cell_height * rows), "white")
    draw = ImageDraw.Draw(sheet)
    for index, record in enumerate(selected, start=1):
        with Image.open(record["path"]) as source_image:
            image = ImageOps.exif_transpose(source_image).convert("RGB")
            image.thumbnail((cell_width - 20, cell_height - 50))
            x = ((index - 1) % columns) * cell_width + 10
            y = ((index - 1) // columns) * cell_height + 35
            sheet.paste(image, (x, y))
            draw.text((x, y - 25), f"CANDIDATE {index:02d}", fill="black")
    sheet_path = output / "hwp-candidate-contact-sheet.jpg"
    sheet.save(sheet_path, format="JPEG", quality=92, optimize=True)
    return [
        {
            "path": str(sheet_path.resolve()),
            "page": None,
            "bbox": None,
            "coordinate_space": None,
            "image_sha256": _sha256(sheet_path),
            "source_image_sha256s": [record["image_sha256"] for record in selected],
            "source_candidates": selected,
            "provenance_level": "document_candidate_contact_sheet",
        }
    ]


def prepare(
    archive_path: Path,
    golden_path: Path,
    output_root: Path,
    *,
    max_hwp_candidates: int = 8,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    cases = _load_cases(golden_path)
    manifest: list[dict[str, Any]] = []
    with zipfile.ZipFile(archive_path) as archive:
        for case in cases:
            case_id = _safe_case_id(case["case_id"])
            case_root = output_root / case_id
            case_root.mkdir(parents=True, exist_ok=True)
            source_filename = case["document"]["source_filename"]
            member = _find_member(archive, source_filename)
            source = _extract_source(archive, member, case_root / "source")
            evidence_type = str(case.get("evidence_type", ""))
            images: list[dict[str, Any]] = []
            preparation_status = "not_required_for_structured_table"
            if evidence_type == "figure":
                if source.suffix.lower() == ".pdf":
                    images = _render_pdf_regions(case, source, case_root)
                    preparation_status = "exact_pdf_region"
                elif source.suffix.lower() == ".hwp":
                    images = _extract_hwp_candidates(source, case_root, max_hwp_candidates)
                    preparation_status = "hwp_candidate_contact_sheet"
            manifest.append(
                {
                    "case_id": case_id,
                    "question": case["question"],
                    "doc_id": case["document"]["source_filename"].removeprefix("refined_"),
                    "source_sha256": case["document"].get("source_sha256"),
                    "evidence_type": evidence_type,
                    "source_format": case["document"]["source_format"],
                    "preparation_status": preparation_status,
                    "images": images,
                }
            )
    manifest_path = output_root / "visual_input_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "cases": len(manifest),
        "figure_cases": sum(item["evidence_type"] == "figure" for item in manifest),
        "images": sum(len(item["images"]) for item in manifest),
        "manifest": str(manifest_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-hwp-candidates", type=int, default=8)
    args = parser.parse_args()
    summary = prepare(
        args.archive,
        args.golden,
        args.output_root,
        max_hwp_candidates=args.max_hwp_candidates,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
