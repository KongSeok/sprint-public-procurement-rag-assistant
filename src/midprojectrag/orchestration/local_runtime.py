"""Explicit local composition helpers. No downloads, gold reads or index writes."""
from __future__ import annotations

import hashlib
import math
import time
from pathlib import Path

from midprojectrag.evidence import EvidenceStore
from midprojectrag.retrieval import BM25Retriever, HybridRetriever
from .llm import LocalJSONBackend


KURE_REVISION = "4ed4540949c70b7da2c74004a915e1f2d5e46e4f"
# Observed and audited snapshot. These pins are model assets, not evaluation data.
SNAPSHOT_PINS = {
    "model.safetensors": "c18156e80caf8ff45eb84a24a853130c3bca03087ccb41b051f86e7556bae02c",
    "tokenizer.json": "fb3c3b93c46fd5a8634e262e1b7de7da11a18b527aa2282b312952b692781dfd",
    "config.json": "852d42e020c7f989c2acaf30fc683b7f768e8c6d1ab17166e835442162bd825d",
    "config_sentence_transformers.json": "8c73684c2160f2209f3706d6cbe0e933287fe6945d9546042be4c105cdb5252e",
    "modules.json": "84e40c8e006c9b1d6c122e02cba9b02458120b5fb0c87b746c41e0207cf642cf",
    "sentence_bert_config.json": "eb9b44b13c0f52a3b3685c3b1cbdea1ba8b04bea123b98f61610048940776eb1",
    "special_tokens_map.json": "8c785abebea9ae3257b61681b4e6fd8365ceafde980c21970d001e834cf10835",
    "tokenizer_config.json": "b87c8703482b0300d3da30e201519aa641f6a450f5eb5bf1e624afbf70c74d80",
    "1_Pooling/config.json": "13e69897522ee8255104483ed9f219465d1be3936654a54a318758738052789e",
}


def legacy_paths(source_root: Path) -> tuple[Path, Path, Path]:
    private = source_root.resolve() / "resources" / "data_refined" / "private"
    return (private / "chunks.page-v1.jsonl",
            private / "indexes" / "local" / "kure-v1-1024" / "page-v1",
            private / "hf-cache" / "hub" / "models--nlpai-lab--KURE-v1" / "snapshots" / KURE_REVISION)


def verify_snapshot(snapshot: Path) -> dict[str, str]:
    if snapshot.name != KURE_REVISION or not snapshot.is_dir():
        raise ValueError("pinned_snapshot_missing")
    for relative, expected in SNAPSHOT_PINS.items():
        path = snapshot / relative
        with path.open("rb") as source:
            actual = hashlib.file_digest(source, "sha256").hexdigest()
        if actual != expected:
            raise ValueError("snapshot_sha256_mismatch")
    return dict(SNAPSHOT_PINS)


def compose_retriever(store: EvidenceStore, *, source_root: Path | None,
                      deadline: float, calls: list[dict]):
    if type(deadline) not in (int, float) or not math.isfinite(deadline):
        raise ValueError("invalid_retrieval_deadline")
    # Parent pages and children are separate retrieval units, named in the receipt.
    child_ids = tuple(e.evidence_id for e in store.all() if e.kind != "page")
    lanes = {"lexical": BM25Retriever(store, evidence_ids=child_ids)}
    provenance = {"profile": "lexical_child", "tier": "provisional_non_official", "lexical_unit": "child", "rrf_k": 60,
                  "reranker": "identity-noop", "dense": None, "visual_enabled": False}
    if source_root is not None:
        from midprojectrag.retrieval.legacy_page import load_legacy_page_retriever
        from midprojectrag.stacks.local.hf_embeddings import KureEmbeddingProvider
        chunks, index, snapshot = legacy_paths(source_root)
        hashes = verify_snapshot(snapshot)

        def tokenizer_loader(**kwargs):
            from transformers import AutoTokenizer
            kwargs["pretrained_model_name_or_path"] = str(snapshot)
            kwargs.pop("revision", None)
            return AutoTokenizer.from_pretrained(**kwargs)

        def encoder_loader(**kwargs):
            from sentence_transformers import SentenceTransformer
            kwargs["model_name_or_path"] = str(snapshot)
            kwargs.pop("revision", None)
            return SentenceTransformer(**kwargs)

        provider = KureEmbeddingProvider(device="cpu", batch_size=1,
                    tokenizer_loader=tokenizer_loader, encoder_loader=encoder_loader)

        def embed_query(query):
            if time.monotonic() >= deadline:
                raise TimeoutError("embedding_deadline_exceeded")
            started = time.monotonic()
            receipt = {"purpose": "query_embedding", "model": provider.model,
                       "revision": provider.revision, "status": "attempted"}
            calls.append(receipt)
            try:
                batch = provider.embed([query])
                if time.monotonic() >= deadline:
                    raise TimeoutError("embedding_deadline_exceeded")
                receipt.update(status="completed", input_tokens=batch.input_tokens,
                               elapsed_ms=(time.monotonic() - started) * 1000)
                return batch.vectors[0]
            except Exception:
                receipt.update(status="error", elapsed_ms=(time.monotonic() - started) * 1000)
                raise

        dense = load_legacy_page_retriever(store, index_dir=index, chunks_path=chunks,
                                          query_embedder=embed_query)
        lanes[dense.lane] = dense
        provenance.update(profile="kure_legacy_page_plus_lexical_child",
                          dense={**dict(dense.provenance), "model_snapshot_files": hashes,
                                 "device": "cpu", "local_files_only": True})
    return HybridRetriever(store, lanes), provenance


class DeadlineGenerator:
    """Pinned model and same request deadline/call ceiling as controller calls."""
    requires_budget = False

    def __init__(self, backend: LocalJSONBackend) -> None:
        from midprojectrag.stacks.local.generation import OllamaGenerator
        self.backend = backend
        self._template = OllamaGenerator(model=backend.model, base_url=backend.base_url,
                                        max_output_tokens=1800, context_tokens=32768, timeout_seconds=1)
        self.model = self._template.model
        self.model_digest = self._template.model_digest
        self.max_output_tokens = self._template.max_output_tokens
        self.system_instructions = self._template.system_instructions

    def estimate_cost(self, inputs, outputs):
        return self._template.estimate_cost(inputs, outputs)

    def generate(self, prompt):
        from midprojectrag.stacks.local.generation import OllamaGenerator
        remaining = self.backend.deadline - time.monotonic()
        if remaining < 2 or len(self.backend.calls) >= self.backend.max_calls:
            raise TimeoutError("generation_budget_exhausted")
        provider = OllamaGenerator(model=self.model, base_url=self.backend.base_url,
                    max_output_tokens=self.max_output_tokens, context_tokens=32768,
                    timeout_seconds=min(self.backend.per_call_seconds, remaining / 2))
        started = time.monotonic()
        record = {"purpose": "answer", "model": self.model, "model_digest": self.model_digest,
                  "status": "attempted", "prompt": prompt}
        self.backend.calls.append(record)
        try:
            result, inputs, outputs = provider.generate(prompt)
            record.update(status="completed", response=result, input_tokens=inputs, output_tokens=outputs,
                          elapsed_ms=(time.monotonic() - started) * 1000)
            if time.monotonic() >= self.backend.deadline:
                raise TimeoutError("deadline_exceeded")
            return result, inputs, outputs
        except Exception as error:
            record.update(status="error", error_type=type(error).__name__,
                          cause_type=type(error.__cause__).__name__ if error.__cause__ is not None else None,
                          elapsed_ms=(time.monotonic() - started) * 1000)
            raise
