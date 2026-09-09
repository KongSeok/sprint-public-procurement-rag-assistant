"""기존 텍스트 검색 결과 안에서 시각 후보를 만들고 VLM으로 선택한다.

이 모듈은 Golden Set의 정답 문서, page, bbox, object hash를 입력으로 받지 않는다.
기존 HybridIndex가 반환한 문서만 후보로 삼으며 검색 모델 자체는 수정하지 않는다.
"""
from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import re
import shutil
import subprocess
import unicodedata
import zipfile
from pathlib import Path
from typing import Any

import fitz
from openai import OpenAI
from PIL import Image, ImageDraw, ImageOps


VISUAL_MODEL = "Qwen/Qwen3-VL-8B-Instruct"
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}


def _normal_name(value: str) -> str:
    name = Path(str(value)).name.removeprefix("refined_")
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", name)).strip().casefold()


def _safe_slug(value: str) -> str:
    stem = re.sub(r"[^0-9a-zA-Z가-힣_-]+", "-", Path(value).stem).strip("-")[:48]
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
    return f"{stem or 'document'}-{digest}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _query_terms(question: str) -> set[str]:
    stop = {"문서", "사업", "관련", "알려주세요", "무엇", "어떻게", "있는지", "해주세요"}
    return {
        token.casefold()
        for token in re.findall(r"[0-9A-Za-z가-힣]{2,}", question)
        if token.casefold() not in stop
    }


def _text_score(question: str, text: str) -> int:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return sum(1 for term in _query_terms(question) if term in normalized)


class ArchiveIndex:
    """원본 압축 파일의 문서명을 코퍼스 doc_id와 연결한다."""

    def __init__(self, archive_path: Path):
        self.path = Path(archive_path)
        with zipfile.ZipFile(self.path) as archive:
            self.members = [name for name in archive.namelist() if not name.endswith("/")]
        self.by_name: dict[str, list[str]] = {}
        for member in self.members:
            self.by_name.setdefault(_normal_name(member), []).append(member)

    def member_for(self, doc_id: str) -> str | None:
        exact = self.by_name.get(_normal_name(doc_id), [])
        if len(exact) == 1:
            return exact[0]
        wanted = Path(_normal_name(doc_id)).stem
        candidates = [
            member
            for member in self.members
            if Path(_normal_name(member)).stem.startswith(wanted)
            or wanted.startswith(Path(_normal_name(member)).stem)
        ]
        return candidates[0] if len(candidates) == 1 else None

    def extract(self, doc_id: str, output_dir: Path) -> Path | None:
        member = self.member_for(doc_id)
        if member is None:
            return None
        target_dir = Path(output_dir) / _safe_slug(doc_id) / "source"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / Path(member).name
        if not target.exists():
            with zipfile.ZipFile(self.path) as archive, archive.open(member) as source:
                with target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
        return target


def retrieve_candidate_doc_ids(index: Any, question: str, *, k: int = 6) -> list[str]:
    """기존 HybridIndex를 수정하지 않고 상위 문서를 중복 제거해 반환한다."""
    hits = index.hybrid_search(
        question,
        k=max(k * 3, 10),
        candidate_k=max(k * 8, 40),
        expand_to_parent=True,
    )
    values: list[str] = []
    for hit in hits:
        doc_id = str(hit.doc_id)
        if doc_id not in values:
            values.append(doc_id)
        if len(values) >= k:
            break
    return values


def _pdf_candidates(
    source: Path,
    doc_id: str,
    question: str,
    output_dir: Path,
    *,
    max_pages: int,
) -> list[dict[str, Any]]:
    document = fitz.open(source)
    try:
        ranked = []
        for page_index in range(document.page_count):
            text = document[page_index].get_text("text")
            ranked.append((_text_score(question, text), page_index, text[:500]))
        ranked.sort(key=lambda value: (-value[0], value[1]))
        selected = ranked[:max_pages]
        records = []
        for _, page_index, snippet in selected:
            path = output_dir / f"page-{page_index + 1:04d}.jpg"
            if not path.exists():
                pixmap = document[page_index].get_pixmap(
                    matrix=fitz.Matrix(1.7, 1.7), alpha=False
                )
                pixmap.save(path)
            records.append(
                {
                    "doc_id": doc_id,
                    "page": page_index + 1,
                    "path": str(path.resolve()),
                    "image_sha256": _sha256(path),
                    "extraction_method": "blind_pdf_page",
                    "page_text_score": _text_score(question, snippet),
                }
            )
        return records
    finally:
        document.close()


def _hwp_candidates(
    source: Path,
    doc_id: str,
    output_dir: Path,
    *,
    max_images: int,
) -> list[dict[str, Any]]:
    html_root = output_dir / "hwp-html"
    if not html_root.exists():
        command = shutil.which("hwp5html")
        if not command:
            raise RuntimeError("hwp5html_not_found")
        html_root.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [command, "--output", str(html_root), str(source)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    ranked: list[tuple[int, Path, int, int]] = []
    for path in html_root.rglob("*"):
        if path.suffix.lower() not in _IMAGE_SUFFIXES:
            continue
        try:
            with Image.open(path) as image:
                width, height = image.size
            area = width * height
            if width >= 160 and height >= 100 and area >= 40_000:
                ranked.append((area, path, width, height))
        except OSError:
            continue
    ranked.sort(key=lambda value: (-value[0], value[1].as_posix()))
    records = []
    for position, (_, path, width, height) in enumerate(ranked[:max_images], start=1):
        records.append(
            {
                "doc_id": doc_id,
                "page": None,
                "path": str(path.resolve()),
                "image_sha256": _sha256(path),
                "extraction_method": "blind_hwp_embedded_image",
                "candidate_position": position,
                "width": width,
                "height": height,
            }
        )
    return records


def build_visual_candidates(
    archive: ArchiveIndex,
    doc_ids: list[str],
    question: str,
    output_root: Path,
    *,
    max_per_document: int = 6,
) -> tuple[list[dict[str, Any]], list[str]]:
    """검색된 문서에서만 PDF 페이지와 HWP 내장 이미지를 추출한다."""
    records: list[dict[str, Any]] = []
    missing_documents: list[str] = []
    for doc_rank, doc_id in enumerate(doc_ids, start=1):
        source = archive.extract(doc_id, output_root)
        if source is None:
            missing_documents.append(doc_id)
            continue
        document_root = output_root / _safe_slug(doc_id) / "visual"
        document_root.mkdir(parents=True, exist_ok=True)
        suffix = source.suffix.lower()
        if suffix == ".pdf":
            candidates = _pdf_candidates(
                source,
                doc_id,
                question,
                document_root,
                max_pages=max_per_document,
            )
        elif suffix in {".hwp", ".hwpx"}:
            candidates = _hwp_candidates(
                source,
                doc_id,
                document_root,
                max_images=max_per_document,
            )
        else:
            candidates = []
        for record in candidates:
            record["candidate_doc_rank"] = doc_rank
            record["candidate_id"] = f"C{len(records) + 1:04d}"
            records.append(record)
    return records, missing_documents


def _data_url(path: Path) -> str:
    media_type = mimetypes.guess_type(path.name)[0] or "image/png"
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{payload}"


def _parse_json(text: str | None) -> dict[str, Any]:
    value = (text or "").strip()
    if value.startswith("```"):
        value = value.strip("`")
        if value.lstrip().startswith("json"):
            value = value.lstrip()[4:].lstrip()
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("vlm_json_contract_invalid")
    return parsed


def _complete(
    client: OpenAI,
    *,
    model: str,
    system_prompt: str,
    user_text: str,
    images: list[Path],
    max_tokens: int = 700,
) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
    content.extend(
        {"type": "image_url", "image_url": {"url": _data_url(path)}} for path in images
    )
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
        temperature=0,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    return _parse_json(response.choices[0].message.content)


def _selection_sheet(records: list[dict[str, Any]], path: Path) -> Path:
    # L4 24GB에서 Qwen3-VL의 이미지 인코딩 여유를 확보하기 위해 후보 시트를
    # 과도하게 크게 만들지 않는다. 원본 판독은 선택된 후보를 별도로 다시 한다.
    cell_width, cell_height, columns = 600, 450, 2
    rows = (len(records) + columns - 1) // columns
    sheet = Image.new("RGB", (cell_width * columns, cell_height * rows), "white")
    draw = ImageDraw.Draw(sheet)
    for index, record in enumerate(records):
        with Image.open(record["path"]) as raw:
            image = ImageOps.exif_transpose(raw).convert("RGB")
            image.thumbnail((cell_width - 20, cell_height - 60))
            x = (index % columns) * cell_width + 10
            y = (index // columns) * cell_height + 45
            sheet.paste(image, (x, y))
            label = f"{record['candidate_id']}  page={record.get('page') or '-'}"
            draw.text((x, y - 30), label, fill="black")
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path, format="JPEG", quality=90, optimize=True)
    return path


def select_and_read_visual_evidence(
    question: str,
    candidates: list[dict[str, Any]],
    output_root: Path,
    *,
    base_url: str = "http://127.0.0.1:8003/v1",
    model: str = VISUAL_MODEL,
    batch_size: int = 4,
    max_selected: int = 3,
) -> dict[str, Any]:
    """VLM이 후보를 선택하고 선택한 이미지에서만 근거를 판독한다."""
    if not candidates:
        return {"evidence_text": "", "selected": [], "error": "no_visual_candidates"}
    client = OpenAI(base_url=base_url, api_key="local-vllm")
    by_id = {record["candidate_id"]: record for record in candidates}
    selected_ids: list[str] = []
    selection_prompt = (
        "질문의 답을 확인하는 데 직접 도움이 되는 후보 ID를 최대 2개 선택한다. "
        "관련 후보가 없으면 빈 배열을 반환한다. 반드시 JSON만 반환한다: "
        '{"candidate_ids": ["C0001"]}'
    )
    for batch_number, start in enumerate(range(0, len(candidates), batch_size), start=1):
        batch = candidates[start:start + batch_size]
        sheet = _selection_sheet(
            batch, Path(output_root) / f"selection-sheet-{batch_number:03d}.jpg"
        )
        mapping = "\n".join(
            f"{row['candidate_id']}: {row['doc_id']} / page={row.get('page') or '-'}"
            for row in batch
        )
        parsed = _complete(
            client,
            model=model,
            system_prompt=selection_prompt,
            user_text=f"질문: {question}\n후보 목록:\n{mapping}",
            images=[sheet],
            max_tokens=200,
        )
        for candidate_id in parsed.get("candidate_ids", []):
            if candidate_id in by_id and candidate_id not in selected_ids:
                selected_ids.append(candidate_id)

    # 배치 순서가 최종 선택을 좌우하지 않도록 각 배치의 후보를 한 번 더
    # 같은 기준으로 비교한다. 이 단계에도 정답 위치 정보는 전달하지 않는다.
    if len(selected_ids) > max_selected:
        finalists = [by_id[candidate_id] for candidate_id in selected_ids]
        final_sheet = _selection_sheet(
            finalists, Path(output_root) / "selection-sheet-final.jpg"
        )
        final_mapping = "\n".join(
            f"{row['candidate_id']}: {row['doc_id']} / page={row.get('page') or '-'}"
            for row in finalists
        )
        parsed = _complete(
            client,
            model=model,
            system_prompt=(
                f"질문의 답을 확인하는 데 가장 직접적인 후보 ID를 최대 {max_selected}개 "
                "선택한다. 관련 후보가 없으면 빈 배열을 반환한다. 반드시 JSON만 "
                '반환한다: {"candidate_ids": ["C0001"]}'
            ),
            user_text=f"질문: {question}\n최종 후보 목록:\n{final_mapping}",
            images=[final_sheet],
            max_tokens=200,
        )
        selected_ids = [
            candidate_id
            for candidate_id in parsed.get("candidate_ids", [])
            if candidate_id in by_id
        ][:max_selected]
    else:
        selected_ids = selected_ids[:max_selected]
    evidence_parts: list[str] = []
    selected_records: list[dict[str, Any]] = []
    evidence_prompt = (
        "당신은 공공 입찰 문서의 시각 근거 판독기다. 이미지에 실제로 보이는 "
        "글자, 표 구조, 도형과 연결 관계만 사용한다. 질문의 답을 찾지 못하면 "
        "빈 문자열을 반환한다. 반드시 JSON만 반환한다: "
        '{"evidence_text": "500자 이내의 판독 근거"}'
    )
    for candidate_id in selected_ids:
        record = by_id[candidate_id]
        parsed = _complete(
            client,
            model=model,
            system_prompt=evidence_prompt,
            user_text=f"질문: {question}\n문서: {record['doc_id']}\n후보: {candidate_id}",
            images=[Path(record["path"])],
        )
        evidence = str(parsed.get("evidence_text") or "").strip()
        if evidence:
            evidence_parts.append(
                f"[{record['doc_id']} / page={record.get('page') or 'unknown'} / {candidate_id}] {evidence}"
            )
            selected_records.append(record)
    payload = {
        "evidence_text": "\n".join(evidence_parts),
        "selected": selected_records,
        "candidate_count": len(candidates),
        "model": model,
        "selection_method": "blind_vlm_contact_sheet",
        "gold_locator_used": False,
        "error": None if evidence_parts else "no_relevant_visual_evidence_selected",
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:24]
    payload["evidence_id"] = f"blind_vle_{digest}"
    return payload
