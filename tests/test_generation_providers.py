from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.generation.dahye_generation import DahyeGPT5MiniGenerator
from src.generation.providers import OpenAICompatibleGenerator, OpenAIResponsesGenerator


class FakeResponses:
    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(output_text="API 답변")


class FakeCompletions:
    def create(self, **kwargs):
        self.kwargs = kwargs
        message = SimpleNamespace(content="로컬 답변")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class GenerationProviderTest(unittest.TestCase):
    def test_openai_responses_provider(self):
        responses = FakeResponses()
        client = SimpleNamespace(responses=responses)
        generator = OpenAIResponsesGenerator(client)
        self.assertEqual(generator.generate("질문", "근거"), "API 답변")
        self.assertEqual(responses.kwargs["model"], "gpt-5-mini")

    def test_openai_compatible_local_provider(self):
        completions = FakeCompletions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        generator = OpenAICompatibleGenerator(client, "Qwen/Qwen3-8B-AWQ", "vllm")
        self.assertEqual(generator.generate("질문", "근거"), "로컬 답변")
        self.assertEqual(completions.kwargs["temperature"], 0)

    def test_dahye_gpt5_mini_provider_preserves_generation_contract(self):
        completions = FakeCompletions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        generator = DahyeGPT5MiniGenerator(client)

        self.assertEqual(generator.generate("예산은?", "[출처: 문서.hwp]\n1억원"), "로컬 답변")
        self.assertEqual(completions.kwargs["model"], "gpt-5-mini")
        self.assertEqual(completions.kwargs["reasoning_effort"], "low")
        self.assertEqual(completions.kwargs["max_completion_tokens"], 8000)
        prompt = completions.kwargs["messages"][0]["content"]
        self.assertIn("예산은?", prompt)
        self.assertIn("[출처: 문서.hwp]", prompt)
        self.assertIn("[근거: doc_id1, doc_id2]", prompt)


if __name__ == "__main__":
    unittest.main()
