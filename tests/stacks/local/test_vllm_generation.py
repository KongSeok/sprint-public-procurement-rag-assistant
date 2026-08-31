from __future__ import annotations

import json
import unittest

from midprojectrag.answering.generation import ANSWER_PLAN_SCHEMA, SYSTEM_INSTRUCTIONS
from midprojectrag.stacks.local.vllm_generation import (
    QWEN3_AWQ_MODEL,
    QWEN3_AWQ_REVISION,
    VLLM_CONTEXT_TOKENS,
    VLLM_MAX_OUTPUT_TOKENS,
    VllmGenerator,
    _NoRedirectHandler,
)


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


class _Backend:
    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self.payloads = payloads
        self.calls: list[tuple[object, float, int]] = []

    def request_json(self, request, *, timeout_seconds, response_max_bytes):  # type: ignore[no-untyped-def]
        self.calls.append((request, timeout_seconds, response_max_bytes))
        return self.payloads[len(self.calls) - 1]


def _models_payload(**overrides: object) -> dict[str, object]:
    model = {
        "id": QWEN3_AWQ_MODEL,
        "root": QWEN3_AWQ_MODEL,
        "revision": QWEN3_AWQ_REVISION,
        "max_model_len": VLLM_CONTEXT_TOKENS,
    }
    model.update(overrides)
    return {"object": "list", "data": [model]}


def _plan() -> dict[str, object]:
    return {
        "status": "abstained",
        "answer": "",
        "citation_chunk_ids": [],
        "abstention_reason": "insufficient_evidence",
    }


def _chat_payload(
    *,
    content: str | None = None,
    finish_reason: object = "stop",
    usage: object | None = None,
    model: str = QWEN3_AWQ_MODEL,
) -> dict[str, object]:
    return {
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content if content is not None else json.dumps(_plan()),
                    "reasoning_content": None,
                },
                "finish_reason": finish_reason,
            }
        ],
        "usage": usage
        if usage is not None
        else {"prompt_tokens": 120, "completion_tokens": 12, "total_tokens": 132},
    }


class VllmGeneratorTests(unittest.TestCase):
    def test_only_literal_loopback_http_url_is_accepted(self) -> None:
        for value in (
            "https://127.0.0.1:8000",
            "http://localhost:8000",
            "http://example.com:8000",
            "http://127.0.0.1",
            "http://127.0.0.1:8000/v1",
            "http://user@127.0.0.1:8000",
            "http://127.0.0.1:8000?x=1",
        ):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "vllm_(loopback_url_required|base_url)"):
                    VllmGenerator(base_url=value, opener=object())
        self.assertEqual(
            VllmGenerator(base_url="http://[::1]:8000", opener=object()).base_url,
            "http://[::1]:8000",
        )

    def test_profile_model_revision_and_token_limits_are_frozen(self) -> None:
        with self.assertRaisesRegex(ValueError, "vllm_generator_model_not_allowlisted"):
            VllmGenerator(model="Qwen/Qwen3-8B", opener=object())
        with self.assertRaisesRegex(ValueError, "vllm_generator_revision_not_pinned"):
            VllmGenerator(revision="main", opener=object())
        with self.assertRaisesRegex(ValueError, "vllm_max_output_tokens_not_frozen"):
            VllmGenerator(max_output_tokens=512, opener=object())
        with self.assertRaisesRegex(ValueError, "vllm_context_tokens_not_frozen"):
            VllmGenerator(context_tokens=4096, opener=object())

    def test_model_is_verified_before_strict_non_thinking_chat_request(self) -> None:
        opener = _Opener([_models_payload(), _chat_payload()])
        generator = VllmGenerator(base_url="http://127.0.0.1:8001", opener=opener)
        plan, input_tokens, output_tokens = generator.generate("합성 질문")
        self.assertEqual(plan, _plan())
        self.assertEqual((input_tokens, output_tokens), (120, 12))
        self.assertEqual(len(opener.calls), 2)
        models_request = opener.calls[0][0]
        self.assertEqual(models_request.full_url, "http://127.0.0.1:8001/v1/models")
        self.assertEqual(models_request.get_method(), "GET")
        self.assertIsNone(models_request.data)

        request, timeout = opener.calls[1]
        self.assertEqual(request.full_url, "http://127.0.0.1:8001/v1/chat/completions")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(timeout, 180.0)
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["model"], QWEN3_AWQ_MODEL)
        self.assertIs(body["stream"], False)
        self.assertEqual(body["temperature"], 0)
        self.assertEqual(body["seed"], 0)
        self.assertEqual(body["max_tokens"], VLLM_MAX_OUTPUT_TOKENS)
        self.assertIs(body["chat_template_kwargs"]["enable_thinking"], False)
        self.assertEqual(body["messages"][0]["role"], "system")
        self.assertIn(SYSTEM_INSTRUCTIONS, body["messages"][0]["content"])
        self.assertEqual(body["messages"][1], {"role": "user", "content": "합성 질문"})
        response_format = body["response_format"]
        self.assertEqual(response_format["type"], "json_schema")
        self.assertIs(response_format["json_schema"]["strict"], True)
        self.assertEqual(response_format["json_schema"]["schema"], ANSWER_PLAN_SCHEMA)

    def test_backend_injection_receives_bounded_requests(self) -> None:
        backend = _Backend([_models_payload(), _chat_payload()])
        generator = VllmGenerator(backend=backend, response_max_bytes=4096)
        generator.generate("합성 질문")
        self.assertEqual(len(backend.calls), 2)
        self.assertEqual(backend.calls[0][1:], (180.0, 4096))
        with self.assertRaisesRegex(ValueError, "vllm_backend_opener_conflict"):
            VllmGenerator(backend=backend, opener=object())

    def test_external_or_wrong_model_is_rejected_before_prompt(self) -> None:
        opener = _Opener([_models_payload(id="Qwen/Qwen3-8B")])
        generator = VllmGenerator(opener=opener)
        with self.assertRaisesRegex(ValueError, "vllm_model_not_served"):
            generator.generate("private prompt")
        self.assertEqual(len(opener.calls), 1)
        self.assertIsNone(opener.calls[0][0].data)

        opener = _Opener([_models_payload(revision="f" * 40)])
        with self.assertRaisesRegex(ValueError, "vllm_model_revision_mismatch"):
            VllmGenerator(opener=opener).generate("private prompt")
        self.assertEqual(len(opener.calls), 1)

    def test_redirects_are_rejected(self) -> None:
        handler = _NoRedirectHandler()
        with self.assertRaisesRegex(ValueError, "vllm_redirect_not_allowed"):
            handler.redirect_request(None, None, 302, "Found", {}, "http://127.0.0.1:8001")

    def test_malformed_or_fenced_json_is_not_salvaged(self) -> None:
        for content in ("not-json", "```json\n" + json.dumps(_plan()) + "\n```"):
            with self.subTest(content=content[:10]):
                generator = VllmGenerator(
                    opener=_Opener([_models_payload(), _chat_payload(content=content)])
                )
                with self.assertRaisesRegex(ValueError, "generation_output_not_json"):
                    generator.generate("합성 질문")

    def test_plan_schema_is_validated_after_json_decode(self) -> None:
        invalid = _plan()
        invalid["extra"] = True
        generator = VllmGenerator(
            opener=_Opener(
                [_models_payload(), _chat_payload(content=json.dumps(invalid))]
            )
        )
        with self.assertRaisesRegex(ValueError, "generation_output_schema_invalid"):
            generator.generate("합성 질문")

    def test_choice_index_and_reasoning_content_fail_closed(self) -> None:
        invalid_index = _chat_payload()
        invalid_index["choices"][0]["index"] = False  # type: ignore[index]
        generator = VllmGenerator(
            opener=_Opener([_models_payload(), invalid_index])
        )
        with self.assertRaisesRegex(ValueError, "vllm_choice_index_invalid"):
            generator.generate("합성 질문")

        thinking = _chat_payload()
        thinking["choices"][0]["message"]["reasoning_content"] = {  # type: ignore[index]
            "unexpected": True
        }
        generator = VllmGenerator(opener=_Opener([_models_payload(), thinking]))
        with self.assertRaisesRegex(ValueError, "vllm_thinking_not_disabled"):
            generator.generate("합성 질문")

    def test_finish_reason_model_and_usage_fail_closed(self) -> None:
        for finish_reason, code in (
            ("length", "vllm_generation_truncated"),
            (None, "vllm_finish_reason_invalid"),
        ):
            with self.subTest(finish_reason=finish_reason):
                generator = VllmGenerator(
                    opener=_Opener(
                        [_models_payload(), _chat_payload(finish_reason=finish_reason)]
                    )
                )
                with self.assertRaisesRegex(ValueError, code):
                    generator.generate("합성 질문")

        generator = VllmGenerator(
            opener=_Opener(
                [_models_payload(), _chat_payload(model="Qwen/Qwen3-8B")]
            )
        )
        with self.assertRaisesRegex(ValueError, "vllm_response_model_mismatch"):
            generator.generate("합성 질문")

        invalid_usages = (
            None,
            {"prompt_tokens": 120, "completion_tokens": -1, "total_tokens": 119},
            {"prompt_tokens": 120, "completion_tokens": 12, "total_tokens": 999},
            {
                "prompt_tokens": VLLM_CONTEXT_TOKENS,
                "completion_tokens": 1,
                "total_tokens": VLLM_CONTEXT_TOKENS + 1,
            },
        )
        for usage in invalid_usages:
            with self.subTest(usage=usage):
                payload = _chat_payload(usage=usage)
                if usage is None:
                    payload["usage"] = None
                generator = VllmGenerator(
                    opener=_Opener([_models_payload(), payload])
                )
                with self.assertRaisesRegex(ValueError, "invalid_generation_usage"):
                    generator.generate("합성 질문")

    def test_response_byte_cap_is_enforced(self) -> None:
        opener = _Opener([_models_payload(), b"x" * 513])
        generator = VllmGenerator(opener=opener, response_max_bytes=512)
        with self.assertRaisesRegex(ValueError, "vllm_response_too_large"):
            generator.generate("합성 질문")


if __name__ == "__main__":
    unittest.main()
