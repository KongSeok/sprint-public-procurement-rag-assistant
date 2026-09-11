"""Local chat client; no cloud fallback, including Responses-based quick summaries."""
from types import SimpleNamespace


class LocalCompletions:
    def __init__(self, delegate, model, max_tokens=1024):
        self.delegate, self.model, self.max_tokens = delegate, model, max_tokens

    def create(self, *, model, messages, max_completion_tokens=None, max_tokens=None,
               reasoning_effort=None, **kwargs):
        if model != self.model:
            raise ValueError('선택한 로컬 모델과 요청 모델이 다릅니다.')
        requested = max_completion_tokens if max_completion_tokens is not None else max_tokens
        limit = self.max_tokens if requested is None else min(requested, self.max_tokens)
        result = self.delegate.create(model=model, messages=messages,
                                      max_tokens=limit, **kwargs)
        if not result.choices or not (result.choices[0].message.content or '').strip():
            raise RuntimeError('로컬 모델이 빈 답변을 반환했습니다.')
        if result.choices[0].finish_reason != 'stop':
            raise RuntimeError('로컬 답변이 출력 한도에서 잘렸습니다. 질문 범위를 좁혀 주세요.')
        return result


class LocalResponses:
    def __init__(self, completions):
        self.completions = completions

    def create(self, *, model, input, instructions=None, max_output_tokens=None, **kwargs):
        if kwargs:
            raise ValueError('로컬 요약에서 지원하지 않는 Responses 옵션입니다.')
        messages = [{'role': 'user', 'content': input}] if isinstance(input, str) else list(input)
        if instructions:
            messages.insert(0, {'role': 'system', 'content': instructions})
        response = self.completions.create(model=model, messages=messages,
                                          max_tokens=max_output_tokens)
        return SimpleNamespace(output_text=response.choices[0].message.content)


class LocalGenerationClient:
    def __init__(self, delegate, model, max_tokens=1024):
        self.chat = SimpleNamespace(completions=LocalCompletions(
            delegate.chat.completions, model, max_tokens))
        self.responses = LocalResponses(self.chat.completions)


def reset_generation_history(state, selection):
    """Do not label an old model's answers as the newly selected model."""
    previous = state.get('active_generation_selection')
    if previous is not None and previous != selection:
        state['rag_history'] = []
        state['review_history'] = []
    state['active_generation_selection'] = selection
