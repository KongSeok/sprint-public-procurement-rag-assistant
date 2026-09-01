from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal
from typing import Any, Protocol

from midprojectrag.answering.generation import ANSWER_PLAN_SCHEMA, SYSTEM_INSTRUCTIONS


QWEN3_AWQ_MODEL = "Qwen/Qwen3-8B-AWQ"
QWEN3_AWQ_REVISION = "4da05a8edb55c6046cce958586c33b61da07bb79"
VLLM_GENERATOR_MODEL = QWEN3_AWQ_MODEL
VLLM_GENERATOR_REVISION = QWEN3_AWQ_REVISION
VLLM_CONTEXT_TOKENS = 8192
VLLM_MAX_OUTPUT_TOKENS = 1024
VLLM_RESPONSE_MAX_BYTES = 1_048_576
VLLM_SYSTEM_INSTRUCTIONS = (
    SYSTEM_INSTRUCTIONS
    + "\n반드시 다른 설명이나 Markdown 없이 아래 JSON Schema를 만족하는 JSON 객체 하나만 반환한다.\n"
    + json.dumps(ANSWER_PLAN_SCHEMA, ensure_ascii=False, separators=(",", ":"))
)

_PLAN_FIELDS = frozenset(
    {"status", "answer", "citation_chunk_ids", "abstention_reason"}
)
_CHUNK_ID_RE = re.compile(r"^(?:chunk|vchunk)_[0-9a-f]{24}$")
_ABSTENTION_REASONS = frozenset(
    {"insufficient_evidence", "out_of_scope", "ambiguous"}
)


class JsonBackend(Protocol):
    def request_json(
        self,
        request: urllib.request.Request,
        *,
        timeout_seconds: float,
        response_max_bytes: int,
    ) -> dict[str, Any]: ...


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        raise ValueError("vllm_redirect_not_allowed")


class _UrllibJsonBackend:
    def __init__(self, opener: Any | None = None) -> None:
        self._opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _NoRedirectHandler(),
        )

    def request_json(
        self,
        request: urllib.request.Request,
        *,
        timeout_seconds: float,
        response_max_bytes: int,
    ) -> dict[str, Any]:
        try:
            with self._opener.open(request, timeout=timeout_seconds) as response:
                raw = response.read(response_max_bytes + 1)
        except ValueError:
            raise
        except (OSError, TimeoutError, urllib.error.URLError) as error:
            raise ValueError("vllm_request_failed") from error
        if len(raw) > response_max_bytes:
            raise ValueError("vllm_response_too_large")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("vllm_response_not_json") from error
        if not isinstance(payload, dict):
            raise ValueError("vllm_response_not_object")
        return payload


def _validated_vllm_base_url(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("invalid_vllm_base_url")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise ValueError("invalid_vllm_base_url") from error
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
        raise ValueError("vllm_loopback_url_required")
    host = f"[{parsed.hostname}]" if parsed.hostname == "::1" else parsed.hostname
    return f"http://{host}:{port}"


def _usage_integer(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("invalid_generation_usage")
    return value


def _validate_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("generation_output_not_object")
    if set(value) != _PLAN_FIELDS:
        raise ValueError("generation_output_schema_invalid")

    status = value.get("status")
    answer = value.get("answer")
    citations = value.get("citation_chunk_ids")
    reason = value.get("abstention_reason")
    if status not in {"answered", "abstained"}:
        raise ValueError("generation_output_schema_invalid")
    if not isinstance(answer, str) or len(answer) > 30_000:
        raise ValueError("generation_output_schema_invalid")
    if (
        not isinstance(citations, list)
        or len(citations) > 20
        or any(not isinstance(item, str) or _CHUNK_ID_RE.fullmatch(item) is None for item in citations)
    ):
        raise ValueError("generation_output_schema_invalid")
    if reason is not None and reason not in _ABSTENTION_REASONS:
        raise ValueError("generation_output_schema_invalid")
    if status == "answered":
        if not answer.strip() or not citations or reason is not None:
            raise ValueError("generation_output_schema_invalid")
    elif answer != "" or citations or reason not in _ABSTENTION_REASONS:
        raise ValueError("generation_output_schema_invalid")
    return dict(value)


class VllmGenerator:
    """Strict loopback vLLM client for the pinned GCP-local generation profile."""

    requires_budget = False
    seed = 0
    temperature = 0
    runtime = "vllm"
    quantization = "awq-int4"

    def __init__(
        self,
        *,
        model: str = VLLM_GENERATOR_MODEL,
        revision: str = VLLM_GENERATOR_REVISION,
        base_url: str = "http://127.0.0.1:8000",
        max_output_tokens: int = VLLM_MAX_OUTPUT_TOKENS,
        context_tokens: int = VLLM_CONTEXT_TOKENS,
        timeout_seconds: float = 180.0,
        response_max_bytes: int = VLLM_RESPONSE_MAX_BYTES,
        backend: JsonBackend | None = None,
        opener: Any | None = None,
    ) -> None:
        if model != VLLM_GENERATOR_MODEL:
            raise ValueError("vllm_generator_model_not_allowlisted")
        if revision != VLLM_GENERATOR_REVISION:
            raise ValueError("vllm_generator_revision_not_pinned")
        if max_output_tokens != VLLM_MAX_OUTPUT_TOKENS:
            raise ValueError("vllm_max_output_tokens_not_frozen")
        if context_tokens != VLLM_CONTEXT_TOKENS:
            raise ValueError("vllm_context_tokens_not_frozen")
        if (
            not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or not 1 <= timeout_seconds <= 600
        ):
            raise ValueError("invalid_vllm_timeout")
        if (
            not isinstance(response_max_bytes, int)
            or isinstance(response_max_bytes, bool)
            or not 1 <= response_max_bytes <= VLLM_RESPONSE_MAX_BYTES
        ):
            raise ValueError("invalid_vllm_response_max_bytes")
        if backend is not None and opener is not None:
            raise ValueError("vllm_backend_opener_conflict")
        if backend is not None and not callable(getattr(backend, "request_json", None)):
            raise ValueError("invalid_vllm_backend")

        self.base_url = _validated_vllm_base_url(base_url)
        self.model = model
        self.revision = revision
        self.model_revision = revision
        self.max_output_tokens = max_output_tokens
        self.context_tokens = context_tokens
        self.timeout_seconds = float(timeout_seconds)
        self.response_max_bytes = response_max_bytes
        self._backend: JsonBackend = backend or _UrllibJsonBackend(opener)
        self._model_verified = False
        self._response_schema = json.loads(json.dumps(ANSWER_PLAN_SCHEMA))

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        return Decimal("0")

    def _request_json(self, request: urllib.request.Request) -> dict[str, Any]:
        try:
            payload = self._backend.request_json(
                request,
                timeout_seconds=self.timeout_seconds,
                response_max_bytes=self.response_max_bytes,
            )
        except ValueError:
            raise
        except Exception as error:
            raise ValueError("vllm_request_failed") from error
        if not isinstance(payload, dict):
            raise ValueError("vllm_response_not_object")
        return payload

    def _verify_model(self) -> None:
        if self._model_verified:
            return
        request = urllib.request.Request(
            f"{self.base_url}/v1/models",
            headers={"Accept": "application/json"},
            method="GET",
        )
        payload = self._request_json(request)
        if payload.get("object") not in {None, "list"}:
            raise ValueError("vllm_models_response_invalid")
        data = payload.get("data")
        if not isinstance(data, list):
            raise ValueError("vllm_models_response_invalid")
        matches = [
            row
            for row in data
            if isinstance(row, dict) and row.get("id") == self.model
        ]
        if len(matches) != 1:
            raise ValueError("vllm_model_not_served")
        match = matches[0]
        if match.get("root") not in {None, self.model}:
            raise ValueError("vllm_model_identity_mismatch")
        served_revision = match.get("revision")
        if served_revision is not None and served_revision != self.revision:
            raise ValueError("vllm_model_revision_mismatch")
        max_model_len = match.get("max_model_len")
        if max_model_len is not None and max_model_len != self.context_tokens:
            raise ValueError("vllm_model_context_mismatch")
        self._model_verified = True

    def generate(self, prompt: str) -> tuple[dict[str, Any], int | None, int | None]:
        if not isinstance(prompt, str) or not prompt:
            raise ValueError("invalid_generation_prompt")
        self._verify_model()
        body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": VLLM_SYSTEM_INSTRUCTIONS},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "temperature": self.temperature,
                "seed": self.seed,
                "max_tokens": self.max_output_tokens,
                "chat_template_kwargs": {"enable_thinking": False},
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "rag_answer_plan",
                        "strict": True,
                        "schema": self._response_schema,
                    },
                },
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        payload = self._request_json(request)
        if payload.get("model") != self.model:
            raise ValueError("vllm_response_model_mismatch")
        choices = payload.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise ValueError("vllm_choices_invalid")
        choice = choices[0]
        choice_index = choice.get("index")
        if (
            not isinstance(choice_index, int)
            or isinstance(choice_index, bool)
            or choice_index != 0
        ):
            raise ValueError("vllm_choice_index_invalid")
        finish_reason = choice.get("finish_reason")
        if finish_reason == "length":
            raise ValueError("vllm_generation_truncated")
        if finish_reason != "stop":
            raise ValueError("vllm_finish_reason_invalid")
        message = choice.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise ValueError("generation_output_missing")
        reasoning_content = message.get("reasoning_content")
        if reasoning_content is not None and reasoning_content != "":
            raise ValueError("vllm_thinking_not_disabled")
        content = message.get("content")
        if not isinstance(content, str) or not content:
            raise ValueError("generation_output_missing")
        try:
            decoded = json.loads(content)
        except json.JSONDecodeError as error:
            raise ValueError("generation_output_not_json") from error
        plan = _validate_plan(decoded)

        usage = payload.get("usage")
        if not isinstance(usage, dict):
            raise ValueError("invalid_generation_usage")
        input_tokens = _usage_integer(usage.get("prompt_tokens"))
        output_tokens = _usage_integer(usage.get("completion_tokens"))
        total_tokens = _usage_integer(usage.get("total_tokens"))
        if (
            total_tokens != input_tokens + output_tokens
            or output_tokens > self.max_output_tokens
            or total_tokens > self.context_tokens
        ):
            raise ValueError("invalid_generation_usage")
        return plan, input_tokens, output_tokens
