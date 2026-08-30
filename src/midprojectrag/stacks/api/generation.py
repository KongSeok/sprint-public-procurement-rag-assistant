from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from midprojectrag.answering.generation import SYSTEM_INSTRUCTIONS, BilledGenerationError


ALLOWED_GENERATOR_MODELS = frozenset({"gpt-5-mini", "gpt-5-nano"})
DEFAULT_REASONING_EFFORT = "minimal"
DEFAULT_SDK_MAX_RETRIES = 2
MODEL_PRICES_PER_MILLION = {
    "gpt-5-mini": (Decimal("0.25"), Decimal("2.00")),
    "gpt-5-nano": (Decimal("0.05"), Decimal("0.40")),
}


_PLAN_FIELDS = ["status", "answer", "citation_chunk_ids", "abstention_reason"]
_CHUNK_ID_SCHEMA = {"type": "string", "pattern": "^chunk_[0-9a-f]{24}$"}

def build_openai_answer_plan_schema(max_citations: int) -> dict[str, Any]:
    if (
        not isinstance(max_citations, int)
        or isinstance(max_citations, bool)
        or not 1 <= max_citations <= 20
    ):
        raise ValueError("invalid_max_citations")
    # OpenAI Structured Outputs does not allow an anyOf at the schema root.
    # Keep a required object envelope and put the status-specific union below
    # it.  The citation ceiling must equal the request contract; a looser
    # provider schema can produce a billable answer the application must reject.
    return {
        "type": "object",
        "required": ["result"],
        "properties": {
            "result": {
                "anyOf": [
                    {
                        "type": "object",
                        "required": _PLAN_FIELDS,
                        "properties": {
                            "status": {"type": "string", "enum": ["answered"]},
                            "answer": {
                                "type": "string",
                                "pattern": "\\S",
                                "maxLength": 30000,
                            },
                            "citation_chunk_ids": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": max_citations,
                                "items": _CHUNK_ID_SCHEMA,
                            },
                            "abstention_reason": {"type": "null"},
                        },
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "required": _PLAN_FIELDS,
                        "properties": {
                            "status": {"type": "string", "enum": ["abstained"]},
                            "answer": {"type": "string", "enum": [""]},
                            "citation_chunk_ids": {
                                "type": "array",
                                "maxItems": 0,
                                "items": _CHUNK_ID_SCHEMA,
                            },
                            "abstention_reason": {
                                "type": "string",
                                "enum": [
                                    "insufficient_evidence",
                                    "out_of_scope",
                                    "ambiguous",
                                ],
                            },
                        },
                        "additionalProperties": False,
                    },
                ]
            }
        },
        "additionalProperties": False,
    }


OPENAI_ANSWER_PLAN_SCHEMA = build_openai_answer_plan_schema(3)


class OpenAIGenerator:
    requires_budget = True
    seed: None = None
    temperature: None = None

    def __init__(
        self,
        *,
        client: Any | None = None,
        model: str = "gpt-5-mini",
        max_output_tokens: int = 1200,
        max_citations: int = 3,
        reasoning_effort: str = DEFAULT_REASONING_EFFORT,
        before_request: Callable[[], None] | None = None,
    ) -> None:
        if model not in ALLOWED_GENERATOR_MODELS:
            raise ValueError("generator_model_not_allowlisted")
        if not isinstance(max_output_tokens, int) or not 1 <= max_output_tokens <= 4000:
            raise ValueError("invalid_max_output_tokens")
        response_schema = build_openai_answer_plan_schema(max_citations)
        if reasoning_effort != DEFAULT_REASONING_EFFORT:
            raise ValueError("reasoning_effort_not_supported")
        if before_request is not None and not callable(before_request):
            raise ValueError("invalid_before_request_hook")
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as error:
                raise RuntimeError("openai_dependency_missing") from error
            client = OpenAI(max_retries=DEFAULT_SDK_MAX_RETRIES, timeout=120.0)
        self._client = client
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.max_citations = max_citations
        self.reasoning_effort = reasoning_effort
        self._response_schema = response_schema
        self._before_request = before_request

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        input_price, output_price = MODEL_PRICES_PER_MILLION[self.model]
        return (
            (Decimal(input_tokens) * input_price + Decimal(output_tokens) * output_price)
            / Decimal(1_000_000)
        ).quantize(Decimal("0.000000001"))

    def generate(self, prompt: str) -> tuple[dict[str, Any], int | None, int | None]:
        if not isinstance(prompt, str) or not prompt:
            raise ValueError("invalid_generation_prompt")
        if self._before_request is not None:
            self._before_request()
        response = self._client.responses.create(
            model=self.model,
            instructions=SYSTEM_INSTRUCTIONS,
            input=prompt,
            store=False,
            max_output_tokens=self.max_output_tokens,
            reasoning={"effort": self.reasoning_effort},
            text={
                "format": {
                    "type": "json_schema",
                    "name": "rag_answer_plan",
                    "strict": True,
                    "schema": self._response_schema,
                }
            },
        )
        input_tokens: int | None = None
        output_tokens: int | None = None
        try:
            usage = getattr(response, "usage", None)
            input_tokens = getattr(usage, "input_tokens", None)
            output_tokens = getattr(usage, "output_tokens", None)
            for value in (input_tokens, output_tokens):
                if value is not None and (
                    not isinstance(value, int)
                    or isinstance(value, bool)
                    or value < 0
                ):
                    raise ValueError("invalid_generation_usage")
            response_status = getattr(response, "status", None)
            if response_status is not None and response_status != "completed":
                raise ValueError("generation_output_incomplete")
            output_text = getattr(response, "output_text", None)
            if not isinstance(output_text, str) or not output_text:
                raise ValueError("generation_output_missing")
            try:
                envelope = json.loads(output_text)
            except json.JSONDecodeError as error:
                raise ValueError("generation_output_not_json") from error
            if not isinstance(envelope, dict):
                raise ValueError("generation_output_not_object")
            if set(envelope) != {"result"} or not isinstance(
                envelope["result"], dict
            ):
                raise ValueError("generation_output_envelope_invalid")
            plan = envelope["result"]
        except ValueError as error:
            safe_input_tokens = (
                input_tokens
                if isinstance(input_tokens, int)
                and not isinstance(input_tokens, bool)
                and input_tokens >= 0
                else None
            )
            safe_output_tokens = (
                output_tokens
                if isinstance(output_tokens, int)
                and not isinstance(output_tokens, bool)
                and output_tokens >= 0
                else None
            )
            raise BilledGenerationError(
                str(error),
                input_tokens=safe_input_tokens,
                output_tokens=safe_output_tokens,
            ) from error
        except Exception as error:
            raise BilledGenerationError(
                "generation_response_invalid",
                input_tokens=None,
                output_tokens=None,
            ) from error
        return plan, input_tokens, output_tokens
