"""Local retrieval, interchangeable generation. No implicit API credentials/egress.

This application composition is outside answering/ and stacks.local: the shared
core remains provider-neutral, and frozen evaluation loaders
retain their original provider identity. Importing this module loads no model.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from midprojectrag.answering.generation import SYSTEM_INSTRUCTIONS
from midprojectrag.answering.pipeline import RagPipeline
from midprojectrag.indexing.budget import Budget
from midprojectrag.indexing.embeddings import TokenCounter


@dataclass(frozen=True)
class GenerationSelection:
    provider: str = "ollama"
    model: str | None = None

    def resolved_model(self) -> str:
        models = {
            "ollama": ("qwen3.8:27b-mlx",),
            "vllm": ("Qwen/Qwen3-8B-AWQ",),
            "openai": ("gpt-5-nano", "gpt-5-mini"),
        }
        if not isinstance(self.provider, str) or self.provider not in models:
            raise ValueError("generation_provider_not_allowlisted")
        model = models[self.provider][0] if self.model is None else self.model
        if model not in models[self.provider]:
            raise ValueError("generation_model_provider_mismatch")
        return model


@dataclass(frozen=True)
class ApiPrompt:
    destination: str
    model: str
    instructions: str
    prompt: str


@dataclass(frozen=True)
class ApiGenerationAccess:
    """Server-owned dependencies, never parsed from a request or environment.

    authorize must return literal True for this exact payload and raise/deny
    otherwise. It is responsible for an applicable destination/payload/profile/
    budget approval, including D-020 for any newly admitted OCR evidence.
    counter must be the selected model's offline-verified tokenizer.
    """

    client: Any
    counter: TokenCounter
    budget: Budget
    authorize: Callable[[ApiPrompt], bool]

    def validate(self) -> None:
        if (
            self.client is None
            or str(getattr(self.client, "base_url", "")).rstrip("/") != "https://api.openai.com/v1"
            or not callable(getattr(self.counter, "count", None))
            or not all(callable(getattr(self.budget, name, None)) for name in ("reserve", "commit", "release"))
            or not callable(self.authorize)
        ):
            raise ValueError("explicit_api_generation_access_required")


class _GuardedApiGenerator:
    requires_budget = True
    max_output_tokens = 1024

    def __init__(self, model: str, access: ApiGenerationAccess) -> None:
        from midprojectrag.stacks.api.generation import OpenAIGenerator

        self.model = model
        self._access = access
        self._delegate = OpenAIGenerator(
            client=access.client, model=model, max_output_tokens=self.max_output_tokens,
        )

    def estimate_cost(self, input_tokens: int, output_tokens: int):
        return self._delegate.estimate_cost(input_tokens, output_tokens)

    def generate(self, prompt: str):
        # Revalidate at dispatch, not merely when constructing the pipeline.
        self._access.validate()
        tokens = self._access.counter.count(SYSTEM_INSTRUCTIONS) + self._access.counter.count(prompt) + 256
        if tokens + self.max_output_tokens > 8192:
            raise ValueError("application_generation_context_exceeded")
        payload = ApiPrompt("https://api.openai.com/v1/responses", self.model, SYSTEM_INSTRUCTIONS, prompt)
        if self._access.authorize(payload) is not True:
            raise ValueError("api_generation_payload_not_approved")
        return self._delegate.generate(prompt)


_RETRIEVAL_FIELDS = frozenset({
    "index", "embedding_provider", "embedding_counter", "query_cache",
    "corpus_manifest_sha256", "retrieval_top_k", "context_top_k",
})


def build_local_first_pipeline(
    retrieval_components: Mapping[str, Any],
    *,
    generation: GenerationSelection = GenerationSelection(),
    api_access: ApiGenerationAccess | None = None,
    local_counter: Any | None = None,
    local_opener: Any | None = None,
    vllm_backend: Any | None = None,
) -> RagPipeline:
    """Reuse verified local components; select only the generation adapter.

    Production components come from load_mac_retrieval_components(verified).
    Injected counters/transports are supported for deterministic offline tests.
    No index build/save, model download, service startup, or query is performed.
    """
    if set(retrieval_components) != _RETRIEVAL_FIELDS:
        raise ValueError("invalid_local_retrieval_components")
    if retrieval_components["embedding_provider"].requires_budget:
        raise ValueError("local_embedding_provider_required")
    model = generation.resolved_model()
    if generation.provider == "openai":
        if api_access is None:
            raise ValueError("explicit_api_generation_access_required")
        if local_counter is not None or local_opener is not None or vllm_backend is not None:
            raise ValueError("generation_provider_options_conflict")
        api_access.validate()
        generator = _GuardedApiGenerator(model, api_access)
        counter = api_access.counter
        budget = api_access.budget
    else:
        if api_access is not None:
            raise ValueError("generation_provider_options_conflict")
        from midprojectrag.gcp_local_baseline import RecordingGenerator
        from midprojectrag.stacks.local.generation import LOCAL_SYSTEM_INSTRUCTIONS, OllamaGenerator
        from midprojectrag.stacks.local.qwen_tokenizer import PinnedQwenChatTokenCounter
        from midprojectrag.stacks.local.vllm_generation import VLLM_SYSTEM_INSTRUCTIONS, VllmGenerator

        counter = local_counter if local_counter is not None else PinnedQwenChatTokenCounter()
        if generation.provider == "ollama":
            if vllm_backend is not None:
                raise ValueError("generation_provider_options_conflict")
            delegate = OllamaGenerator(
                model=model, max_output_tokens=1024, context_tokens=32768, opener=local_opener,
            )
            instructions = LOCAL_SYSTEM_INSTRUCTIONS
        else:
            if local_opener is not None:
                raise ValueError("generation_provider_options_conflict")
            delegate = VllmGenerator(model=model, backend=vllm_backend)
            instructions = VLLM_SYSTEM_INSTRUCTIONS
        generator = RecordingGenerator(delegate, counter=counter, system_instructions=instructions)
        budget = None
    return RagPipeline(
        **dict(retrieval_components), generator=generator, generation_counter=counter,
        budget=budget, stack_id=f"local_application_{generation.provider}",
    )
