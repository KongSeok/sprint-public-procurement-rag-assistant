"""Opt-in local OCR/layout vector store; does not alter the application baseline."""
from __future__ import annotations

import argparse
import base64
import html
import importlib.metadata
import json
import os
from pathlib import Path
import time

import numpy as np

from midprojectrag.ingest.common import canonical_json, sha256_file
from midprojectrag.ingest.visual_understanding import _resolve_crop, _validated_occurrence
from midprojectrag.indexing.visual_fusion import VisualExactDenseIndex, validate_visual_chunk
from midprojectrag.stacks.local.gcp_config import KURE_DIMENSIONS, KURE_MODEL_ID, KURE_MODEL_REVISION

IDENTITY = {"model": KURE_MODEL_ID, "revision": KURE_MODEL_REVISION,
            "dimensions": KURE_DIMENSIONS, "prompt": "", "similarity": "cosine"}
MAX_BYTES = 128 * 1024 * 1024
MAX_CHUNKS = 5000


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _read(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("invalid_index_input_file")
    return path.read_bytes()


def _json(path):
    return json.loads(_read(path), object_pairs_hook=_pairs)


def _jsonl(path):
    rows = [json.loads(line, object_pairs_hook=_pairs) for line in _read(path).splitlines() if line.strip()]
    if not rows or len(rows) > MAX_CHUNKS:
        raise ValueError("invalid_visual_row_count")
    return rows


def _private_path(path, private_root):
    root = private_root.resolve(strict=True)
    absolute = Path(os.path.abspath(path))
    if root != private_root or not root.is_dir() or absolute == root or not absolute.is_relative_to(root):
        raise ValueError("output_outside_private_root")
    current = root
    for part in absolute.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("private_path_symlink")
    return absolute


def _write(path, value):
    with path.open("x", encoding="utf-8") as f:
        f.write(canonical_json(value) + "\n")
    path.chmod(0o600)


def _bindings(chunks, occurrences, crop_root):
    bound = {}
    for raw in occurrences:
        occurrence = _validated_occurrence(raw)
        key = occurrence["occurrence_id"]
        if key in bound:
            raise ValueError("duplicate_occurrence")
        bound[key] = occurrence
    seen = set()
    for chunk in chunks:
        validate_visual_chunk(chunk)
        if chunk["evidence_type"] not in {"ocr", "layout"}:
            raise ValueError("caption_not_enabled")
        if chunk["chunk_id"] in seen:
            raise ValueError("duplicate_visual_chunk_id")
        seen.add(chunk["chunk_id"])
        occurrence = bound.get(chunk["occurrence_id"])
        if occurrence is None or any(chunk[field] != occurrence[field]
                                     for field in ("doc_id", "page", "bbox", "crop_sha256")):
            raise ValueError("chunk_occurrence_mismatch")
        _resolve_crop(occurrence, crop_root)
    if set(bound) != {c["occurrence_id"] for c in chunks}:
        raise ValueError("unindexed_occurrence")
    return bound


def _provider_identity(provider):
    if (provider.model, provider.revision, provider.dimensions, provider.prompt) != (
        KURE_MODEL_ID, KURE_MODEL_REVISION, KURE_DIMENSIONS, ""
    ):
        raise ValueError("visual_embedding_identity_mismatch")


def build(*, chunks_path, occurrences_path, crop_root, index_dir, private_root, provider):
    destination = _private_path(index_dir, private_root)
    if destination.exists():
        raise ValueError("index_already_exists")
    _provider_identity(provider)
    sources = {"chunks": sha256_file(chunks_path), "occurrences": sha256_file(occurrences_path)}
    chunks, occurrences = _jsonl(chunks_path), _jsonl(occurrences_path)
    _bindings(chunks, occurrences, crop_root)
    started = time.perf_counter()
    batch = provider.embed([c["text"] for c in chunks])
    index = VisualExactDenseIndex(chunks, batch.vectors)
    if index.dimensions != KURE_DIMENSIONS:
        raise ValueError("visual_embedding_dimensions_mismatch")
    seconds = time.perf_counter() - started
    _bindings(chunks, occurrences, crop_root)
    if sources != {"chunks": sha256_file(chunks_path), "occurrences": sha256_file(occurrences_path)}:
        raise ValueError("visual_sources_changed")
    destination.mkdir(mode=0o700, parents=True)
    for name, rows in (("chunks.jsonl", chunks), ("occurrences.jsonl", occurrences)):
        with (destination / name).open("x", encoding="utf-8") as f:
            for row in rows:
                f.write(canonical_json(row) + "\n")
        (destination / name).chmod(0o600)
    with (destination / "vectors.npy").open("xb") as f:
        np.save(f, index.vectors, allow_pickle=False)
    (destination / "vectors.npy").chmod(0o600)
    metadata = {"schema_version": "visual-ocr-index-v1", "embedding": IDENTITY,
                "chunk_count": len(chunks), "occurrence_count": len(occurrences),
                "source_hashes": sources, "input_tokens": batch.input_tokens,
                "embedding_seconds": seconds, "runtime": getattr(provider, "runtime_receipt", {}),
                "files": {name: sha256_file(destination / name)
                          for name in ("chunks.jsonl", "occurrences.jsonl", "vectors.npy")},
                "baseline_changed": False, "pixel_embedding": False, "caption_enabled": False}
    # Metadata is the commit marker. Failed/incomplete directories are never accepted.
    _write(destination / "metadata.json", metadata)
    return metadata


def load(*, index_dir, private_root, crop_root):
    directory = _private_path(index_dir, private_root)
    metadata = _json(directory / "metadata.json")
    if metadata.get("schema_version") != "visual-ocr-index-v1" or metadata.get("embedding") != IDENTITY:
        raise ValueError("index_identity_mismatch")
    if set(metadata.get("files", {})) != {"chunks.jsonl", "occurrences.jsonl", "vectors.npy"}:
        raise ValueError("index_file_inventory_invalid")
    for name, expected in metadata["files"].items():
        _read(directory / name)
        if sha256_file(directory / name) != expected:
            raise ValueError("index_file_checksum_mismatch")
    chunks, occurrences = _jsonl(directory / "chunks.jsonl"), _jsonl(directory / "occurrences.jsonl")
    bound = _bindings(chunks, occurrences, crop_root)
    vectors = np.load(directory / "vectors.npy", allow_pickle=False)
    if vectors.shape != (len(chunks), KURE_DIMENSIONS) or vectors.dtype != np.float32:
        raise ValueError("index_vector_shape_invalid")
    if metadata["chunk_count"] != len(chunks) or metadata["occurrence_count"] != len(bound):
        raise ValueError("index_count_mismatch")
    return VisualExactDenseIndex(chunks, vectors), bound, metadata


def search(*, index_dir, private_root, crop_root, provider, query, top_k=5):
    if not isinstance(query, str) or not query.strip() or len(query) > 4000:
        raise ValueError("invalid_visual_query")
    if type(top_k) is not int or not 1 <= top_k <= 100:
        raise ValueError("invalid_top_k")
    _provider_identity(provider)
    index, bound, metadata = load(index_dir=index_dir, private_root=private_root, crop_root=crop_root)
    started = time.perf_counter()
    batch = provider.embed([query])
    ranked = index.search(batch.vectors[0], top_k=len(index.chunks))
    hits, seen = [], set()
    for hit in ranked:
        chunk = hit.chunk
        key = chunk["occurrence_id"]
        if key in seen:
            continue
        seen.add(key)
        crop = _resolve_crop(bound[key], crop_root)
        hits.append({"score": hit.score, "chunk_id": chunk["chunk_id"], "text": chunk["text"],
                     "evidence_type": chunk["evidence_type"], "citation": chunk["citation"],
                     "crop_path": str(crop)})
        if len(hits) == top_k:
            break
    return {"schema_version": "visual-ocr-query-v1", "query": query, "hits": hits,
            "seconds": time.perf_counter() - started, "input_tokens": batch.input_tokens,
            "indexed_chunks": metadata["chunk_count"], "runtime": getattr(provider, "runtime_receipt", {}),
            "meaning": "OCR text similarity; not visual reasoning or an LLM answer"}


def preview_html(result):
    sections = []
    for hit in result["hits"]:
        crop = Path(hit["crop_path"])
        if sha256_file(crop) != hit["citation"]["crop_sha256"]:
            raise ValueError("preview_crop_changed")
        encoded = base64.b64encode(_read(crop)).decode("ascii")
        citation = html.escape(json.dumps(hit["citation"], ensure_ascii=False))
        sections.append(f'<section><p>cosine {hit["score"]:.4f}</p><img alt="검색된 원본 그림" src="data:image/png;base64,{encoded}"><pre>{citation}</pre><pre>{html.escape(hit["text"])}</pre></section>')
    return ('<!doctype html><html lang="ko"><meta charset="utf-8">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'">'
            '<title>OCR 그림 검색</title><style>body{font:16px/1.6 system-ui;max-width:960px;margin:24px auto;padding:16px}img{max-width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere}section{border-top:1px solid #ccc}</style>'
            '<h1>OCR 텍스트로 찾은 그림</h1><p>OCR 유사도 검색 결과이며 VLM 해석·LLM 답변이 아닙니다.</p>'
            f'<h2>{html.escape(result["query"])}</h2>' + ''.join(sections) + '</html>')


def local_provider(hf_cache, device):
    # Set flags before importing Torch/Hugging Face. OS no-egress is provided by the caller.
    os.environ.update(HF_HOME=str(hf_cache), HF_HUB_CACHE=str(hf_cache / "hub"),
                      HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
                      PYTORCH_ENABLE_MPS_FALLBACK="0", TOKENIZERS_PARALLELISM="false")
    import torch
    from midprojectrag.stacks.local.hf_embeddings import KureEmbeddingProvider
    if device != "mps" or not torch.backends.mps.is_available():
        raise ValueError("mps_required_no_cpu_fallback")
    start = time.perf_counter()
    provider = KureEmbeddingProvider(device=device, batch_size=2)
    encoder = provider._get_encoder()
    actual = str(next(encoder.parameters()).device)
    if not actual.startswith("mps"):
        raise ValueError("embedding_encoder_not_on_mps")
    torch.mps.synchronize()
    provider.runtime_receipt = {"device": actual, "load_seconds": time.perf_counter()-start,
        "cpu_fallback": False, "offline": True,
        "packages": {name: importlib.metadata.version(name) for name in
                     ("torch", "numpy", "sentence-transformers", "transformers")}}
    return provider


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "search", "answer"))
    for name in ("private-root", "index-dir", "crop-root", "hf-cache"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--device", choices=("mps",), default="mps")
    parser.add_argument("--chunks", type=Path)
    parser.add_argument("--occurrences", type=Path)
    parser.add_argument("--query")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--result-dir", type=Path)
    parser.add_argument("--vlm-python", type=Path)
    parser.add_argument("--vlm-model", type=Path)
    parser.add_argument("--vlm-manifest", type=Path)
    args = parser.parse_args()
    if args.action == "build" and (args.chunks is None or args.occurrences is None):
        parser.error("build requires --chunks and --occurrences")
    if args.action in {"search", "answer"} and (args.query is None or args.result_dir is None):
        parser.error("search/answer requires --query and --result-dir")
    if args.action == "answer" and any(x is None for x in (args.vlm_python, args.vlm_model, args.vlm_manifest)):
        parser.error("answer requires --vlm-python, --vlm-model and --vlm-manifest")
    args.private_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    output = _private_path(args.index_dir if args.action == "build" else args.result_dir, args.private_root)
    if output.exists():
        raise ValueError("output_already_exists")
    provider = local_provider(args.hf_cache, args.device)
    common = dict(index_dir=args.index_dir, private_root=args.private_root, crop_root=args.crop_root, provider=provider)
    if args.action == "build":
        result = build(chunks_path=args.chunks, occurrences_path=args.occurrences, **common)
        print(canonical_json({k: result[k] for k in ("chunk_count", "occurrence_count", "embedding", "embedding_seconds", "runtime")}))
    else:
        result = search(query=args.query, top_k=1 if args.action == "answer" else args.top_k, **common)
        if args.action == "answer":
            from midprojectrag.stacks.local.visual_qa import answer_retrieval
            answer = answer_retrieval(result, index_dir=args.index_dir, private_root=args.private_root,
                crop_root=args.crop_root, output=output, python_executable=args.vlm_python,
                model_dir=args.vlm_model, manifest_path=args.vlm_manifest)
            print(canonical_json({"status": answer["status"], "image_count": 1,
                                  "vlm_seconds": answer["total_vlm_seconds"], "preview_written": True}))
            return
        document = preview_html(result)
        output.mkdir(mode=0o700, parents=True)
        _write(output / "result.json", result)
        with (output / "index.html").open("x", encoding="utf-8") as f:
            f.write(document)
        (output / "index.html").chmod(0o600)
        print(canonical_json({"hits": len(result["hits"]), "seconds": result["seconds"], "preview_written": True}))


if __name__ == "__main__":
    main()
