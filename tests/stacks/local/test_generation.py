from __future__ import annotations

import json
import unittest
from decimal import Decimal

from midprojectrag.answering.generation import (
    ANSWER_PLAN_SCHEMA,
    generate_with_budget,
)
from midprojectrag.stacks.local import OLLAMA_MODEL_DIGESTS, OllamaGenerator


class _Response:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self, limit: int) -> bytes:
        return self.payload[:limit]

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:  # type: ignore[no-untyped-def]
        return False


class _Opener:
    def __init__(self, payloads: list[dict[str, object] | bytes]) -> None:
        self.payloads = [
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if isinstance(payload, dict)
            else payload
            for payload in payloads
        ]
        self.calls: list[tuple[object, float]] = []

    def open(self, request, timeout):  # type: ignore[no-untyped-def]
        self.calls.append((request, timeout))
        return _Response(self.payloads[len(self.calls) - 1])


class _Counter:
    def count(self, text: str) -> int:
        return max(1, len(text))


def _ollama_payload() -> dict[str, object]:
    plan = {
        "status": "abstained",
        "answer": "",
        "citation_chunk_ids": [],
        "abstention_reason": "insufficient_evidence",
    }
    return {
        "model": "qwen3.8:27b-mlx",
        "message": {"role": "assistant", "content": json.dumps(plan)},
        "prompt_eval_count": 42,
        "eval_count": 9,
        "done": True,
        "done_reason": "stop",
    }


def _tags_payload(*, digest: str | None = None) -> dict[str, object]:
    return {
        "models": [
            {
                "name": "qwen3.8:27b-mlx",
                "model": "qwen3.8:27b-mlx",
                "digest": digest or OLLAMA_MODEL_DIGESTS["qwen3.8:27b-mlx"],
                "capabilities": ["completion", "vision", "tools", "thinking"],
            }
        ]
    }


def _valid_opener(chat_payload: dict[str, object] | bytes | None = None) -> _Opener:
    return _Opener([_tags_payload(), chat_payload or _ollama_payload()])


class OllamaGeneratorTests(unittest.TestCase):
    def test_only_loopback_http_url_is_accepted(self) -> None:
        for value in (
            "https://127.0.0.1:11434",
            "http://example.com:11434",
            "http://127.0.0.1:11434/redirect",
            "http://user@127.0.0.1:11434",
            "http://127.0.0.1",
            "http://localhost:11434",
        ):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "ollama_(loopback_url_required|base_url)"):
                    OllamaGenerator(base_url=value, opener=object())

    def test_request_is_non_streaming_non_thinking_and_schema_bounded(self) -> None:
        opener = _valid_opener()
        generator = OllamaGenerator(
            base_url="http://127.0.0.1:11435",
            max_output_tokens=100,
            opener=opener,
        )
        plan, input_tokens, output_tokens = generator.generate("합성 질문")
        self.assertEqual(plan["status"], "abstained")
        self.assertEqual((input_tokens, output_tokens), (42, 9))
        self.assertEqual(len(opener.calls), 2)
        self.assertEqual(opener.calls[0][0].full_url, "http://127.0.0.1:11435/api/tags")
        request, timeout = opener.calls[1]
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "http://127.0.0.1:11435/api/chat")
        self.assertEqual(timeout, 180.0)
        self.assertEqual(body["model"], "qwen3.8:27b-mlx")
        self.assertIs(body["stream"], False)
        self.assertIs(body["think"], False)
        self.assertEqual(body["format"], "json")
        self.assertIn(json.dumps(ANSWER_PLAN_SCHEMA, ensure_ascii=False, separators=(",", ":")), body["messages"][0]["content"])
        self.assertEqual(body["options"]["temperature"], 0)
        self.assertEqual(body["options"]["seed"], 0)

    def test_context_overflow_fails_before_opening_socket(self) -> None:
        opener = _valid_opener()
        generator = OllamaGenerator(
            max_output_tokens=100,
            context_tokens=4096,
            opener=opener,
        )
        with self.assertRaisesRegex(ValueError, "ollama_context_budget_exceeded"):
            generator.generate("가" * 2000)
        self.assertEqual(opener.calls, [])

    def test_local_generation_does_not_require_openai_price_or_budget(self) -> None:
        generator = OllamaGenerator(
            max_output_tokens=100,
            opener=_valid_opener(),
        )
        result = generate_with_budget(
            "합성 질문",
            generator=generator,
            counter=_Counter(),
            budget=None,
        )
        self.assertEqual(result.cost_usd, Decimal("0"))
        self.assertEqual((result.input_tokens, result.output_tokens), (42, 9))

    def test_malformed_provider_response_fails_with_safe_machine_code(self) -> None:
        generator = OllamaGenerator(opener=_valid_opener(b"not-json"))
        with self.assertRaisesRegex(ValueError, "ollama_response_not_json"):
            generator.generate("합성 질문")

    def test_digest_mismatch_and_truncated_generation_fail_closed(self) -> None:
        generator = OllamaGenerator(opener=_Opener([_tags_payload(digest="f" * 64)]))
        with self.assertRaisesRegex(ValueError, "ollama_model_digest_mismatch"):
            generator.generate("합성 질문")

        truncated = _ollama_payload()
        truncated["done_reason"] = "length"
        generator = OllamaGenerator(opener=_valid_opener(truncated))
        with self.assertRaisesRegex(ValueError, "ollama_generation_truncated"):
            generator.generate("합성 질문")


if __name__ == "__main__":
    unittest.main()
