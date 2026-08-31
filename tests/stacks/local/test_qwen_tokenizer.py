from __future__ import annotations

import unittest
from typing import Any

from midprojectrag.stacks.local.qwen_tokenizer import PinnedQwenChatTokenCounter
from midprojectrag.stacks.local.vllm_generation import (
    QWEN3_AWQ_MODEL,
    QWEN3_AWQ_REVISION,
)


_DEFAULT = object()


class _Tokenizer:
    def __init__(
        self,
        *,
        count_output: Any = _DEFAULT,
        chat_output: Any = _DEFAULT,
    ) -> None:
        self.count_output = (
            {"input_ids": [1, 2, 3]} if count_output is _DEFAULT else count_output
        )
        self.chat_output = (
            [4, 5, 6, 7] if chat_output is _DEFAULT else chat_output
        )
        self.count_calls: list[tuple[str, dict[str, object]]] = []
        self.chat_calls: list[tuple[list[dict[str, str]], dict[str, object]]] = []

    def __call__(self, text: str, **kwargs: object) -> Any:
        self.count_calls.append((text, dict(kwargs)))
        return self.count_output

    def apply_chat_template(
        self,
        messages: list[dict[str, str]],
        **kwargs: object,
    ) -> Any:
        self.chat_calls.append((messages, dict(kwargs)))
        return self.chat_output


class PinnedQwenChatTokenCounterTests(unittest.TestCase):
    def test_model_revision_and_offline_safety_are_exactly_enforced(self) -> None:
        with self.assertRaisesRegex(
            ValueError, "generator_tokenizer_model_not_allowlisted"
        ):
            PinnedQwenChatTokenCounter(model="Qwen/Qwen3-8B")
        with self.assertRaisesRegex(
            ValueError, "generator_tokenizer_revision_not_pinned"
        ):
            PinnedQwenChatTokenCounter(revision="main")
        with self.assertRaisesRegex(ValueError, "local_files_only_required"):
            PinnedQwenChatTokenCounter(local_files_only=False)
        with self.assertRaisesRegex(ValueError, "trust_remote_code_not_allowed"):
            PinnedQwenChatTokenCounter(trust_remote_code=True)

    def test_loader_is_lazy_exactly_pinned_and_reused(self) -> None:
        tokenizer = _Tokenizer(count_output={"input_ids": [10, 11]})
        loader_calls: list[dict[str, object]] = []

        def loader(**kwargs: object) -> _Tokenizer:
            loader_calls.append(dict(kwargs))
            return tokenizer

        counter = PinnedQwenChatTokenCounter(tokenizer_loader=loader)
        self.assertEqual(loader_calls, [])

        self.assertEqual(counter.count("입찰 공고"), 2)
        self.assertEqual(counter.count("재사용 확인"), 2)

        self.assertEqual(
            loader_calls,
            [
                {
                    "pretrained_model_name_or_path": QWEN3_AWQ_MODEL,
                    "revision": QWEN3_AWQ_REVISION,
                    "local_files_only": True,
                    "trust_remote_code": False,
                    "use_fast": True,
                }
            ],
        )
        self.assertEqual(
            tokenizer.count_calls,
            [
                (
                    "입찰 공고",
                    {
                        "add_special_tokens": True,
                        "return_attention_mask": False,
                        "return_token_type_ids": False,
                        "truncation": False,
                    },
                ),
                (
                    "재사용 확인",
                    {
                        "add_special_tokens": True,
                        "return_attention_mask": False,
                        "return_token_type_ids": False,
                        "truncation": False,
                    },
                ),
            ],
        )

    def test_chat_count_uses_non_thinking_system_user_template(self) -> None:
        tokenizer = _Tokenizer(chat_output={"input_ids": [1, 2, 3, 4, 5]})
        counter = PinnedQwenChatTokenCounter(tokenizer=tokenizer)

        self.assertEqual(
            counter.count_chat(system="근거만 사용하세요.", prompt="마감일은 언제인가요?"),
            5,
        )
        self.assertEqual(
            tokenizer.chat_calls,
            [
                (
                    [
                        {"role": "system", "content": "근거만 사용하세요."},
                        {"role": "user", "content": "마감일은 언제인가요?"},
                    ],
                    {
                        "tokenize": True,
                        "add_generation_prompt": True,
                        "enable_thinking": False,
                    },
                )
            ],
        )

    def test_malformed_nested_non_integer_and_empty_outputs_are_rejected(self) -> None:
        invalid_outputs = (
            None,
            {"unexpected": [1, 2]},
            {"input_ids": "12"},
            7,
            [[1, 2]],
            [1, "2"],
            [1, True],
            [],
            {"input_ids": []},
        )
        for output in invalid_outputs:
            with self.subTest(method="count", output=output):
                counter = PinnedQwenChatTokenCounter(
                    tokenizer=_Tokenizer(count_output=output)
                )
                with self.assertRaisesRegex(
                    ValueError, "qwen_tokenizer_output_invalid"
                ):
                    counter.count("검증")
            with self.subTest(method="count_chat", output=output):
                counter = PinnedQwenChatTokenCounter(
                    tokenizer=_Tokenizer(chat_output=output)
                )
                with self.assertRaisesRegex(
                    ValueError, "qwen_tokenizer_output_invalid"
                ):
                    counter.count_chat(system="시스템", prompt="질문")


if __name__ == "__main__":
    unittest.main()
