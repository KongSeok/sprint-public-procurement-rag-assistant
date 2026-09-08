#!/usr/bin/env python3
"""Run a local OpenAI-compatible VLM over prepared visual inputs."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import time
from pathlib import Path
from typing import Any

from openai import OpenAI


DEFAULT_PRIVATE = Path("output/experiments/b_plan_v3_vlm/private")
DEFAULT_OUTPUT = Path("output/experiments/b_plan_v3_vlm/visual_evidence.jsonl")
SYSTEM_PROMPT = """당신은 공공 입찰 문서의 시각 근거 판독기다.
제공된 이미지에 실제로 보이는 글자, 표 구조, 화살표와 연결 관계만 사용한다.
질문에 필요한 내용을 찾지 못하면 추측하지 말고 evidence_text를 빈 문자열로 반환한다.
후보 이미지가 여러 장이면 질문에 해당하는 이미지를 스스로 골라야 한다.
반드시 JSON 객체 하나만 반환한다: {\"evidence_text\": \"판독한 근거\"}"""


def _data_url(path: Path) -> str:
    media_type = mimetypes.guess_type(path.name)[0] or "image/png"
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{payload}"


def _parse_answer(text: str | None) -> str:
    value = (text or "").strip()
    if value.startswith("```"):
        value = value.strip("`")
        if value.lstrip().startswith("json"):
            value = value.lstrip()[4:].lstrip()
    parsed = json.loads(value)
    evidence = parsed.get("evidence_text")
    if not isinstance(evidence, str):
        raise ValueError("vlm_evidence_contract_invalid")
    return evidence.strip()


def _evidence_id(case_id: str, model: str, evidence: str, refs: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        {"case_id": case_id, "model": model, "evidence": evidence, "refs": refs},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "vle_" + hashlib.sha256(payload).hexdigest()[:24]


def run(
    manifest_path: Path,
    output_path: Path,
    *,
    base_url: str,
    model: str,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    client = OpenAI(base_url=base_url, api_key="local-vllm")
    rows: list[dict[str, Any]] = []
    for item in manifest:
        if item["evidence_type"] != "figure":
            continue
        image_records = list(item["images"])
        images = [Path(value["path"]) for value in image_records]
        started = time.perf_counter()
        error = None
        evidence = ""
        try:
            if not images:
                raise RuntimeError("visual_input_missing")
            content: list[dict[str, Any]] = [
                {"type": "text", "text": f"질문: {item['question']}"}
            ]
            content.extend(
                {"type": "image_url", "image_url": {"url": _data_url(path)}}
                for path in images
            )
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": content},
                ],
                temperature=0,
                max_tokens=800,
            )
            evidence = _parse_answer(response.choices[0].message.content)
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
        rows.append(
            {
                "case_id": item["case_id"],
                "doc_id": item["doc_id"],
                "source_sha256": item.get("source_sha256"),
                "preparation_status": item["preparation_status"],
                "image_count": len(images),
                "model": model,
                "evidence_text": evidence,
                "evidence_id": _evidence_id(item["case_id"], model, evidence, image_records),
                "evidence_refs": [
                    {
                        key: record.get(key)
                        for key in (
                            "page",
                            "bbox",
                            "coordinate_space",
                            "image_sha256",
                            "source_image_sha256s",
                            "provenance_level",
                        )
                    }
                    for record in image_records
                ],
                "error": error,
                "latency_seconds": round(time.perf_counter() - started, 3),
            }
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )
        print(f"[{len(rows)}] {item['case_id']}: {'OK' if not error else error}")
    return {
        "cases": len(rows),
        "successes": sum(not row["error"] and bool(row["evidence_text"]) for row in rows),
        "output": str(output_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_PRIVATE / "visual_input_manifest.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--base-url", default="http://127.0.0.1:8003/v1")
    parser.add_argument("--model", default="Qwen/Qwen3-VL-8B-Instruct")
    args = parser.parse_args()
    print(json.dumps(run(args.manifest, args.output, base_url=args.base_url, model=args.model), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
