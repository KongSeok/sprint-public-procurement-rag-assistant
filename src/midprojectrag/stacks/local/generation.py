from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal
from typing import Any

from midprojectrag.answering.generation import ANSWER_PLAN_SCHEMA, SYSTEM_INSTRUCTIONS


ALLOWED_OLLAMA_GENERATOR_MODELS = frozenset({"qwen3.8:27b-mlx"})
OLLAMA_MODEL_DIGESTS = {
    "qwen3.8:27b-mlx": "5642e97495e1a088883805981563dcdc4a040c2f53388b7a41d1f24d3622cf7e"
}
OLLAMA_RESPONSE_MAX_BYTES = 1_048_576
LOCAL_SYSTEM_INSTRUCTIONS = (
    SYSTEM_INSTRUCTIONS
    + "\n반드시 다른 설명이나 Markdown 없이 아래 JSON Schema를 만족하는 JSON 객체 하나만 반환한다.\n"
    + json.dumps(ANSWER_PLAN_SCHEMA, ensure_ascii=False, separators=(",", ":"))
)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        raise ValueError("ollama_redirect_not_allowed")


def _validated_ollama_base_url(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("invalid_ollama_base_url")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise ValueError("invalid_ollama_base_url") from error
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or port is None
        or not 1 <= port <= 65535
    ):
        raise ValueError("ollama_loopback_url_required")
    host = f"[{parsed.hostname}]" if parsed.hostname == "::1" else parsed.hostname
    return f"http://{host}:{port}"


class OllamaGenerator:
    """Proxy-free, redirect-free loopback client for the Mac experiment."""

    requires_budget = False
    seed = 0
    temperature = 0

    def __init__(
        self,
        *,
        model: str = "qwen3.8:27b-mlx",
        base_url: str = "http://127.0.0.1:11434",
        max_output_tokens: int = 1200,
        context_tokens: int = 16384,
        timeout_seconds: float = 180.0,
        system_instructions: str = LOCAL_SYSTEM_INSTRUCTIONS,
        opener: Any | None = None,
    ) -> None:
        if model not in ALLOWED_OLLAMA_GENERATOR_MODELS:
            raise ValueError("ollama_generator_model_not_allowlisted")
        if not isinstance(max_output_tokens, int) or not 1 <= max_output_tokens <= 4000:
            raise ValueError("invalid_max_output_tokens")
        if not isinstance(context_tokens, int) or not 4096 <= context_tokens <= 32768:
            raise ValueError("invalid_ollama_context_tokens")
        if not isinstance(timeout_seconds, (int, float)) or not 1 <= timeout_seconds <= 600:
            raise ValueError("invalid_ollama_timeout")
        if not isinstance(system_instructions, str) or not system_instructions.strip():
            raise ValueError("invalid_ollama_system_instructions")
        self.base_url = _validated_ollama_base_url(base_url)
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.context_tokens = context_tokens
        self.timeout_seconds = float(timeout_seconds)
        self.system_instructions = system_instructions
        self.model_digest = OLLAMA_MODEL_DIGESTS[model]
        self._model_verified = False
        self._opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _NoRedirectHandler(),
        )

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        return Decimal("0")

    def _open_json(self, request: urllib.request.Request) -> dict[str, Any]:
        try:
            with self._opener.open(request, timeout=self.timeout_seconds) as response:
                raw = response.read(OLLAMA_RESPONSE_MAX_BYTES + 1)
        except ValueError:
            raise
        except (OSError, TimeoutError, urllib.error.URLError) as error:
            raise ValueError("ollama_request_failed") from error
        if len(raw) > OLLAMA_RESPONSE_MAX_BYTES:
            raise ValueError("ollama_response_too_large")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("ollama_response_not_json") from error
        if not isinstance(payload, dict):
            raise ValueError("ollama_response_not_object")
        return payload

    def _verify_model(self) -> None:
        if self._model_verified:
            return
        request = urllib.request.Request(
            f"{self.base_url}/api/tags",
            headers={"Accept": "application/json"},
            method="GET",
        )
        payload = self._open_json(request)
        models = payload.get("models")
        if not isinstance(models, list):
            raise ValueError("ollama_tags_invalid")
        match = next(
            (
                row
                for row in models
                if isinstance(row, dict)
                and row.get("name") == self.model
                and row.get("model") == self.model
            ),
            None,
        )
        if not isinstance(match, dict):
            raise ValueError("ollama_model_not_installed")
        if match.get("digest") != self.model_digest:
            raise ValueError("ollama_model_digest_mismatch")
        capabilities = match.get("capabilities")
        if not isinstance(capabilities, list) or "completion" not in capabilities:
            raise ValueError("ollama_model_capability_missing")
        self._model_verified = True

    def generate(self, prompt: str) -> tuple[dict[str, Any], int | None, int | None]:
        if not isinstance(prompt, str) or not prompt:
            raise ValueError("invalid_generation_prompt")
        prompt_upper_bound = len(self.system_instructions.encode("utf-8")) + len(prompt.encode("utf-8"))
        if prompt_upper_bound + self.max_output_tokens + 256 > self.context_tokens:
            raise ValueError("ollama_context_budget_exceeded")
        self._verify_model()
        body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": self.system_instructions},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "think": False,
                "format": "json",
                "options": {
                    "temperature": self.temperature,
                    "seed": self.seed,
                    "num_ctx": self.context_tokens,
                    "num_predict": self.max_output_tokens,
                },
                "keep_alive": "10m",
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        payload = self._open_json(request)
        if payload.get("model") != self.model:
            raise ValueError("ollama_response_model_mismatch")
        if payload.get("done_reason") == "length" or payload.get("done") is False:
            raise ValueError("ollama_generation_truncated")
        message = payload.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content:
            raise ValueError("generation_output_missing")
        try:
            plan = json.loads(content)
        except json.JSONDecodeError as error:
            raise ValueError("generation_output_not_json") from error
        if not isinstance(plan, dict):
            raise ValueError("generation_output_not_object")
        input_tokens = payload.get("prompt_eval_count")
        output_tokens = payload.get("eval_count")
        for value in (input_tokens, output_tokens):
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
                raise ValueError("invalid_generation_usage")
        return plan, input_tokens, output_tokens
