"""Explicit local build; inputs stay private and existing artifacts stay unchanged."""
import argparse
import json
import os
from pathlib import Path
import time

from midprojectrag.evidence.artifacts import file_sha, freeze_bundle, private_path, write_new_json
from midprojectrag.evidence.builder import SplitConfig, build_store
from midprojectrag.retrieval.dense import build_dense, load_dense
from midprojectrag.retrieval.kiwi_bm25 import KiwiTokenizer, KiwiBM25Lane
from midprojectrag.retrieval.fusion import HybridChildRetriever
from midprojectrag.retrieval.context import select_context
from midprojectrag.runtime_integrity import ResolvedScope
from midprojectrag.stacks.local.hf_embeddings import KureEmbeddingProvider


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "mps", "cuda"), default="cpu")
    parser.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()
    data = args.data_root.resolve()
    target = private_path(args.output_dir, data)
    if target.exists():
        raise FileExistsError(target)
    os.environ["HF_HOME"] = str(data / "private" / "hf-cache")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    started = time.monotonic()

    def event(stage, **values):
        print(json.dumps({"stage": stage, "elapsed_s": round(time.monotonic()-started, 2), **values}), flush=True)

    chunk_path = data / "private" / "chunks.page-v1.jsonl"
    manifest_path = data / "private" / "manifest.extracted.jsonl"
    chunks = [json.loads(line) for line in chunk_path.open() if line.strip()]
    manifests = [json.loads(line) for line in manifest_path.open() if line.strip()]
    needed = {row["source_block_ids"][0] for row in chunks}
    docs = {row["doc_id"] for row in chunks}
    blocks, kinds = [], {}
    hashes = {"chunks": file_sha(chunk_path), "manifest": file_sha(manifest_path)}
    for row in manifests:
        if row["doc_id"] not in docs:
            continue
        if row["doc_id"] in kinds:
            raise ValueError("duplicate_manifest_document")
        path = private_path(data / row["output_relpath"], data)
        hashes["blocks_" + row["doc_id"]] = file_sha(path)
        for line in path.open():
            block = json.loads(line)
            if block["block_id"] in needed:
                blocks.append(block)
        if row["extension"] == ".pdf":
            kinds[row["doc_id"]] = "pdf_page"
        elif row["extractor"] == "rhwp":
            kinds[row["doc_id"]] = "rendered_hwp_page"
        else:
            kinds[row["doc_id"]] = "page_v1"
    if set(kinds) != docs:
        raise ValueError("manifest_corpus_coverage_mismatch")
    compat = SplitConfig()
    store = build_store(chunks, compat, source_blocks=blocks, parent_kinds=kinds)
    structured_config = SplitConfig("heading-paragraph-v1")
    structured = build_store(chunks, structured_config, source_blocks=blocks, parent_kinds=kinds)
    target.mkdir(parents=True, exist_ok=False, mode=0o700)
    receipts = {"compat": freeze_bundle(store, compat, hashes, output_dir=target / "compat", data_root=data),
                "structured": freeze_bundle(structured, structured_config, hashes,
                                             output_dir=target / "structured", data_root=data)}
    event("bundles_frozen", docs=len(docs), parents=len(store.parents), children=len(store.candidates()),
          structured_children=len(structured.candidates()))
    tokenizer = KiwiTokenizer()
    lexical = KiwiBM25Lane.build(store, tokenizer)
    receipts["lexical"] = lexical.save(target / "lexical", data_root=data)
    event("lexical_frozen", token_count=sum(map(len, lexical.tokens)))
    provider = KureEmbeddingProvider(batch_size=args.batch_size, device=args.device)
    last_update = [time.monotonic()]

    def progress(done, total):
        if done == total or time.monotonic()-last_update[0] >= 20:
            event("embedding", done=done, total=total)
            last_update[0] = time.monotonic()

    receipts["dense"] = build_dense(store, provider, output_dir=target / "dense", data_root=data,
                                    batch_size=args.batch_size, progress=progress)
    dense = load_dense(store, provider, output_dir=target / "dense", data_root=data)
    loaded_lexical = KiwiBM25Lane.load(store, tokenizer, target / "lexical", data_root=data)
    hybrid = HybridChildRetriever(store, dense, loaded_lexical)
    result = hybrid.search("정보시스템 구축 사업의 수행 기간과 예산", dense_k=30, lexical_k=30, scope=ResolvedScope())
    context = select_context(result.candidates, store)
    if not result.candidates or not context.evidence_ids:
        raise ValueError("real_retrieval_smoke_empty")
    unchanged = file_sha(chunk_path) == hashes["chunks"] and file_sha(manifest_path) == hashes["manifest"]
    if not unchanged:
        raise ValueError("source_changed_during_build")
    summary = {"schema_version": "1.0", "device": args.device, "batch_size": args.batch_size,
               "elapsed_s": round(time.monotonic()-started, 2), "input_hashes": hashes,
               "receipts": receipts, "smoke": {"candidate_count": len(result.candidates),
                   "lexical_only_count": len(result.trace["lexical_only"]), "context_count": len(context.evidence_ids),
                   "context_used_chars": context.trace["used_chars"]},
               "source_unchanged": unchanged, "generation_calls": 0, "performance_improvement_claim": False}
    write_new_json(target / "build-receipt.json", summary)
    event("complete", **summary["smoke"])


if __name__ == "__main__":
    main()
