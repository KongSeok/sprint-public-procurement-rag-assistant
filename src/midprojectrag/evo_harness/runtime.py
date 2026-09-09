"""Local-only Qwen3.5 MLX composition. Optional packages import only on execution."""
from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import importlib.metadata
import json
import math
import os
import re
from pathlib import Path
import time

from .policy import MODEL_ID, DERIVATIVE_ID, Completion, ModelIdentity, LLMPolicy, AnswerComposer
from .runner import EpisodeRunner
from .state import Budgets, HarnessError, Unsupported, json_object
from .tools import HotlineTools
from .experience import Experience


def file_hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8*1024*1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_local_model(model_dir: Path, manifest_path: Path) -> dict:
    directory = Path(model_dir).resolve()
    if not directory.is_dir() or not Path(manifest_path).is_file():
        raise Unsupported("local_model_files_required")
    manifest = json_object(Path(manifest_path).read_text(), maximum=1_048_576)
    if manifest.get("repo") != DERIVATIVE_ID:
        raise Unsupported("qwen35_mlx_derivative_required")
    if not re.fullmatch(r"[0-9a-f]{40}", str(manifest.get("revision", ""))):
        raise HarnessError("pinned_model_revision_required")
    files = manifest.get("files")
    if type(files) is not dict or not files or not any(name.endswith(".safetensors") for name in files):
        raise HarnessError("model_weight_manifest_required")
    actual = {str(p.relative_to(directory)) for p in directory.rglob("*")
              if p.is_file() and ".cache" not in p.relative_to(directory).parts}
    if actual != set(files):
        raise HarnessError("model_manifest_inventory_mismatch")
    for name, entry in files.items():
        if type(name) is not str or type(entry) is not dict:
            raise HarnessError("invalid_model_manifest")
        target = (directory/name).resolve()
        if not target.is_relative_to(directory) or not target.is_file():
            raise HarnessError("model_manifest_path_invalid")
        if target.stat().st_size != entry.get("bytes") or file_hash(target) != entry.get("sha256"):
            raise HarnessError("model_artifact_mismatch")
    config = json_object((directory/"config.json").read_text(), maximum=1_048_576)
    if config.get("model_type") not in {"qwen3_5", "qwen3_5_text"}:
        raise Unsupported("qwen35_architecture_required")
    return manifest


class MLXBackend:
    """One sequentially reused local model for policy and final generation."""
    def __init__(self, model_dir: Path, manifest_path: Path, *, expected_revision: str | None = None):
        started = time.monotonic()
        manifest = verify_local_model(model_dir, manifest_path)
        if expected_revision is not None and manifest["revision"] != expected_revision:
            raise HarnessError("model_revision_mismatch")
        os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
        try:
            import mlx.core as mx
            from mlx_vlm import load
        except ImportError as exc:
            raise Unsupported("mlx_runtime_not_installed") from exc
        if not mx.metal.is_available():
            raise Unsupported("metal_required_no_cpu_fallback")
        mx.set_default_device(mx.gpu)
        self.model, self.processor = load(str(Path(model_dir).resolve()), trust_remote_code=False)
        self.config = json_object((Path(model_dir)/"config.json").read_text(), maximum=1_048_576)
        self.tokenizer = getattr(self.processor, "tokenizer", self.processor)
        template = getattr(self.tokenizer, "chat_template", None)
        encoded = json.dumps(template, ensure_ascii=False, sort_keys=True)
        if not template or "enable_thinking" not in encoded:
            raise Unsupported("nonthinking_chat_template_required")
        self.identity = ModelIdentity(MODEL_ID, DERIVATIVE_ID, manifest.get("revision"),
                                      sha256(encoded.encode()).hexdigest(),
                                      "mlx-vlm/"+importlib.metadata.version("mlx-vlm"),
                                      str(mx.default_device()), "4bit")
        self.load_seconds = time.monotonic()-started
        self.manifest_sha256 = file_hash(Path(manifest_path))
        self.calls = 0

    def formatted(self, messages: list[dict]) -> str:
        return self.tokenizer.apply_chat_template(messages, tokenize=False,
                    add_generation_prompt=True, enable_thinking=False)

    def count_messages(self, messages: list[dict]) -> int:
        return len(self.tokenizer.encode(self.formatted(messages), add_special_tokens=False))

    def complete(self, messages: list[dict], *, max_tokens: int, timeout: float) -> Completion:
        if type(timeout) not in (float, int) or not math.isfinite(timeout) or timeout <= 0:
            raise TimeoutError("model_deadline")
        import mlx.core as mx
        from mlx_vlm import generate
        start = time.monotonic()
        formatted = self.formatted(messages)
        self.calls += 1
        mx.random.seed(0)
        result = generate(self.model, self.processor, formatted, max_tokens=max_tokens,
                          temperature=0.0, seed=0, enable_thinking=False, verbose=False)
        mx.synchronize()
        # The CLI supervisor enforces the process budget even during native work.
        # A late result is returned with usage; the runner performs its post-call
        # deadline check before accepting it.
        return Completion(result.text, int(result.prompt_tokens), int(result.generation_tokens), result.finish_reason)


    def inspect_image(self, request, *, remaining):
        from midprojectrag.stacks.local import visual_qa
        remaining()
        if (self.identity.artifact_model != visual_qa.MODEL or self.identity.revision != visual_qa.REVISION
                or self.identity.backend != "mlx-vlm/0.7.0"):
            raise Unsupported("visual_model_profile_mismatch")
        self.calls += 1
        return visual_qa.infer_loaded(request, self.model, self.processor, self.config, remaining=remaining)


def load_hotline_tools(data_dir: Path, artifacts: Path, *, device: str = "mps") -> HotlineTools:
    """Load existing artifacts only; no model server changes or index generation."""
    root, target = Path(data_dir).resolve(), Path(artifacts).resolve()
    private = (root/"private").resolve()
    if not private.is_relative_to(root) or not target.is_relative_to(private):
        raise HarnessError("private_artifacts_required")
    if not all((target/name/"receipt.json").is_file() for name in ("compat", "dense", "lexical")):
        raise Unsupported("existing_hotline_artifacts_required")
    if device != "mps":
        raise Unsupported("explicit_mps_profile_required")
    os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "0"
    try:
        import torch
        if not torch.backends.mps.is_available():
            raise Unsupported("mps_required_no_cpu_fallback")
        from midprojectrag.gcp_local_baseline import _configure_hf_cache
        from midprojectrag.evidence.artifacts import load_bundle
        from midprojectrag.retrieval.dense import load_dense
        from midprojectrag.retrieval.kiwi_bm25 import KiwiBM25Lane, KiwiTokenizer
        from midprojectrag.retrieval.fusion import HybridChildRetriever
        from midprojectrag.stacks.local.hf_embeddings import KureEmbeddingProvider
    except ImportError as exc:
        raise Unsupported("hotline_retrieval_runtime_not_installed") from exc
    _configure_hf_cache(private/"hf-cache", offline=True)
    store, _receipt = load_bundle(target/"compat", data_root=root)
    provider = KureEmbeddingProvider(batch_size=1, device=device)
    dense = load_dense(store, provider, output_dir=target/"dense", data_root=root)
    lexical = KiwiBM25Lane.load(store, KiwiTokenizer(), target/"lexical", data_root=root)
    hybrid = HybridChildRetriever.from_loaded_artifacts(store, dense, lexical)
    manifest_path = private/"manifest.extracted.jsonl"
    catalog = {}
    if manifest_path.is_file():
        for line in manifest_path.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                if row["doc_id"] in store.doc_ids:
                    catalog[row["doc_id"]] = row.get("metadata", {}).get("project_name", "")
    identity = sha256(json.dumps({name:file_hash(target/name/"receipt.json")
                                 for name in ("compat", "dense", "lexical")},sort_keys=True).encode()).hexdigest()
    return HotlineTools(store, hybrid, catalog=catalog, identity=identity)


def synthetic_tools() -> HotlineTools:
    """EXPLICIT smoke corpus: real store/hybrid API, fake retrieval lanes, no KURE claim."""
    from midprojectrag.evidence import Evidence, EvidenceStore, Locator, ProvenanceParent
    from midprojectrag.retrieval.contracts import Candidate, SearchResult
    from midprojectrag.retrieval.fusion import HybridChildRetriever
    parents, evidence = [], []
    for doc_id, body in (("alpha", "Alpha project. Budget: 120 million KRW. Performance period: 6 months."),
                         ("beta", "Beta project. Budget: 80 million KRW. Performance period: 4 months.")):
        parent = ProvenanceParent(doc_id, "pdf_page", body, (f"synthetic-{doc_id}",), Locator(page=1))
        parents.append(parent)
        evidence.append(Evidence(doc_id, "text", body, parent.parent_id, parent.source_block_ids,
                                 Locator(page=1,char_range=(0,len(body)))))
    store = EvidenceStore(parents, evidence)

    class SmokeLane:
        def __init__(self, name):
            self.lane = name
            self.bundle_sha256 = store.bundle_sha256

        def search(self, query, limit, *, allowed_doc_ids):
            values = [item for item in store.evidence if allowed_doc_ids is None or item.doc_id in allowed_doc_ids]
            values.sort(key=lambda item: (-int(item.doc_id in query.lower()), item.doc_id))
            return SearchResult(tuple(Candidate(item.evidence_id,item.doc_id,1.0/rank,self.lane,rank)
                                      for rank,item in enumerate(values[:limit],1)),
                                {"lane":self.lane,"granularity":"child","bundle_sha256":store.bundle_sha256})
    return HotlineTools(store, HybridChildRetriever(store, SmokeLane("dense"), SmokeLane("lexical")),
                        catalog={"alpha":"Alpha synthetic RFP","beta":"Beta synthetic RFP"},
                        identity="synthetic-public-hybrid-v1")


def compose_runtime(backend, tools, *, budgets=None, experience=None):
    return EpisodeRunner(tools, LLMPolicy(backend), AnswerComposer(backend), budgets=budgets, experience=experience)
