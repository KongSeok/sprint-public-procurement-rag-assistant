"""답변 생성 모델을 교체하기 위한 공통 provider 인터페이스.

검색·청킹 코드는 그대로 두고 생성 모델만 GPT-5 mini, vLLM의 Qwen,
Ollama의 Qwen으로 바꿔 동일 조건에서 비교한다. 로컬 provider는 OpenAI 호환
Chat Completions API를 사용하므로 모델 서버 구현이 파이프라인에 새어 나오지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .generation import SYSTEM_PROMPT


class AnswerGenerator(Protocol):
    provider: str
    model: str

    def generate(self, query: str, context: str) -> str:
        """검색 컨텍스트에 근거한 답변을 반환한다."""


def _messages(query: str, context: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"[검색된 근거]\n{context}\n\n[질문]\n{query}"},
    ]


@dataclass
class OpenAIResponsesGenerator:
    """OpenAI Responses API 기반 GPT 생성기."""

    client: Any
    model: str = "gpt-5-mini"
    provider: str = "openai"

    def generate(self, query: str, context: str) -> str:
        response = self.client.responses.create(model=self.model, input=_messages(query, context))
        text = getattr(response, "output_text", None)
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("generation_empty_response")
        return text.strip()


@dataclass
class OpenAICompatibleGenerator:
    """vLLM/Ollama 등 OpenAI 호환 서버의 Chat Completions 생성기."""

    client: Any
    model: str
    provider: str

    def generate(self, query: str, context: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=_messages(query, context),
            temperature=0,
        )
        choices = getattr(response, "choices", None)
        text = choices[0].message.content if choices else None
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("generation_empty_response")
        return text.strip()


def create_generator(
    provider: str,
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> AnswerGenerator:
    """설정값으로 생성기를 만든다. import만으로 네트워크 호출은 하지 않는다."""
    provider = provider.strip().lower()
    defaults = {
        "openai": ("gpt-5-mini", None),
        "vllm": ("Qwen/Qwen3-8B-AWQ", "http://127.0.0.1:8001/v1"),
        "ollama": ("qwen3:8b", "http://127.0.0.1:11434/v1"),
    }
    if provider not in defaults:
        raise ValueError(f"지원하지 않는 생성 provider: {provider}")

    default_model, default_url = defaults[provider]
    selected_model = model or default_model
    from openai import OpenAI

    if provider == "openai":
        if not api_key:
            raise ValueError("OPENAI_API_KEY가 필요합니다")
        return OpenAIResponsesGenerator(OpenAI(api_key=api_key), model=selected_model)

    client = OpenAI(base_url=base_url or default_url, api_key=api_key or "local-not-used")
    return OpenAICompatibleGenerator(client, model=selected_model, provider=provider)
