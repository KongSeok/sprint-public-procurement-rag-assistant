from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Callable

from .vllm_generation import QWEN3_AWQ_MODEL, QWEN3_AWQ_REVISION


TokenizerLoader = Callable[..., Any]

QWEN_TOKENIZER_ALLOW_PATTERNS = (
    "added_tokens.json",
    "chat_template.jinja",
    "chat_templates/*.jinja",
    "config.json",
    "generation_config.json",
    "merges.txt",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
)

QWEN_TOKENIZER_IGNORE_PATTERNS = (
    "*.bin",
    "*.ckpt",
    "*.gguf",
    "*.h5",
    "*.msgpack",
    "*.onnx",
    "*.ot",
    "*.pt",
    "*.pth",
    "*.safetensors",
    "model.safetensors.index.json",
)


def _default_tokenizer_loader(**kwargs: Any) -> Any:
    try:
        from transformers import AutoTokenizer
    except ImportError as error:
        raise RuntimeError("transformers_dependency_missing") from error
    try:
        return AutoTokenizer.from_pretrained(**kwargs)
    except Exception as error:
        raise RuntimeError("qwen_tokenizer_load_failed") from error


class PinnedQwenChatTokenCounter:
    """Offline counter for the exact Qwen chat template used by the baseline."""

    def __init__(
        self,
        *,
        model: str = QWEN3_AWQ_MODEL,
        revision: str = QWEN3_AWQ_REVISION,
        tokenizer: Any | None = None,
        tokenizer_loader: TokenizerLoader | None = None,
        local_files_only: bool = True,
        trust_remote_code: bool = False,
    ) -> None:
        if model != QWEN3_AWQ_MODEL:
            raise ValueError("generator_tokenizer_model_not_allowlisted")
        if revision != QWEN3_AWQ_REVISION:
            raise ValueError("generator_tokenizer_revision_not_pinned")
        if local_files_only is not True:
            raise ValueError("local_files_only_required")
        if trust_remote_code is not False:
            raise ValueError("trust_remote_code_not_allowed")
        self.model = model
        self.revision = revision
        self._tokenizer = tokenizer
        self._tokenizer_loader = tokenizer_loader or _default_tokenizer_loader

    def _get_tokenizer(self) -> Any:
        if self._tokenizer is None:
            self._tokenizer = self._tokenizer_loader(
                pretrained_model_name_or_path=self.model,
                revision=self.revision,
                local_files_only=True,
                trust_remote_code=False,
                use_fast=True,
            )
        return self._tokenizer

    @staticmethod
    def _token_count(value: Any) -> int:
        if isinstance(value, Mapping):
            value = value.get("input_ids")
        if (
            not isinstance(value, Sequence)
            or isinstance(value, (str, bytes))
            or any(isinstance(item, Sequence) and not isinstance(item, (str, bytes)) for item in value)
            or any(not isinstance(item, int) or isinstance(item, bool) for item in value)
        ):
            raise ValueError("qwen_tokenizer_output_invalid")
        if not value:
            raise ValueError("qwen_tokenizer_output_invalid")
        return len(value)

    def count(self, text: str) -> int:
        if not isinstance(text, str):
            raise ValueError("invalid_counter_input")
        payload = self._get_tokenizer()(
            text,
            add_special_tokens=True,
            return_attention_mask=False,
            return_token_type_ids=False,
            truncation=False,
        )
        return self._token_count(payload)

    def count_chat(self, *, system: str, prompt: str) -> int:
        if not isinstance(system, str) or not system or not isinstance(prompt, str) or not prompt:
            raise ValueError("invalid_chat_counter_input")
        payload = self._get_tokenizer().apply_chat_template(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            tokenize=True,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        return self._token_count(payload)
