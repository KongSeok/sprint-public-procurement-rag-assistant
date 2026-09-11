import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from types import SimpleNamespace
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest

from streamlit_demo.local_generation import LocalGenerationClient, reset_generation_history
from streamlit_demo.shared_qwen_server import MODEL, GenerationError, complete, generate_text, handler_for, validate_request


def response(text='답변', finish='stop'):
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=text), finish_reason=finish)])


class FakeCompletions:
    def __init__(self):
        self.calls = []
        self.result = response()

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def test_local_chat_keeps_messages_and_binds_model_budget():
    delegate = FakeCompletions()
    client = LocalGenerationClient(SimpleNamespace(chat=SimpleNamespace(completions=delegate)), MODEL)
    messages = [{'role': 'user', 'content': '원본 근거/질문'}]
    client.chat.completions.create(model=MODEL, messages=messages,
                                  max_completion_tokens=8000, reasoning_effort='low')
    assert delegate.calls == [{'model': MODEL, 'messages': messages, 'max_tokens': 1024}]


def test_local_responses_summary_uses_same_model_chat_api():
    delegate = FakeCompletions()
    client = LocalGenerationClient(SimpleNamespace(chat=SimpleNamespace(completions=delegate)), MODEL)
    assert client.responses.create(model=MODEL, input='질문', instructions='근거만 사용').output_text == '답변'
    assert delegate.calls[0]['messages'] == [
        {'role': 'system', 'content': '근거만 사용'}, {'role': 'user', 'content': '질문'}]


@pytest.mark.parametrize('text,finish', [('', 'stop'), (' \n\t', 'stop'), ('잘림', 'length')])
def test_local_failure_has_no_retry_or_cloud_fallback(text, finish):
    delegate = FakeCompletions()
    delegate.result = response(text, finish)
    client = LocalGenerationClient(SimpleNamespace(chat=SimpleNamespace(completions=delegate)), MODEL)
    with pytest.raises(RuntimeError):
        client.chat.completions.create(model=MODEL, messages=[])
    assert len(delegate.calls) == 1


def test_model_mismatch_rejected_before_call():
    delegate = FakeCompletions()
    client = LocalGenerationClient(SimpleNamespace(chat=SimpleNamespace(completions=delegate)), MODEL)
    with pytest.raises(ValueError):
        client.chat.completions.create(model='gpt-5-mini', messages=[])
    assert delegate.calls == []


def test_switch_resets_answers_but_not_search_runtime():
    state = {'rag_history': [1], 'review_history': [2], 'index': object()}
    index = state['index']
    reset_generation_history(state, 'mini')
    reset_generation_history(state, 'mini')
    assert state['rag_history'] == [1]
    reset_generation_history(state, 'qwen')
    assert state['rag_history'] == state['review_history'] == []
    assert state['index'] is index


def valid(**updates):
    return {'model': MODEL, 'messages': [{'role': 'user', 'content': '안녕'}], **updates}


@pytest.mark.parametrize('updates', [
    {'model': 'other'}, {'stream': True}, {'temperature': 1}, {'tools': []},
    {'messages': []}, {'messages': [{'role': 'user', 'content': []}]},
    {'messages': [{'role': 'tool', 'content': 'text'}]}, {'max_tokens': 0},
    {'messages': [{'role': [], 'content': 'text'}]},
    {'max_tokens': True}, {'max_tokens': 8000}, {'max_tokens': 2, 'max_completion_tokens': 2},
])
def test_request_rejects_unsupported_features(updates):
    with pytest.raises(GenerationError) as exc:
        validate_request(valid(**updates))
    assert exc.value.status == 400


def application():
    app = SimpleNamespace(status='ready', backend=object(), lock=threading.Lock())
    app.health = lambda: {'status': app.status, 'busy': app.lock.locked()}
    return app


def fake_generate(backend, messages, limit):
    return '정상 답변', 12, 4, 'stop'


def test_shared_lock_excludes_eh_and_generation_and_recovers():
    app = application()
    app.lock.acquire()
    with pytest.raises(GenerationError) as exc:
        complete(app, valid(), fake_generate)
    assert exc.value.status == 409
    assert app.lock.locked()
    app.lock.release()
    def failure(*args):
        raise RuntimeError('model failed')
    with pytest.raises(RuntimeError):
        complete(app, valid(), failure)
    assert not app.lock.locked()
    result = complete(app, valid(), fake_generate)
    assert result['model'] == MODEL
    assert result['usage']['total_tokens'] == 16
    assert not app.lock.locked()


def test_not_ready_does_not_generate():
    app = application()
    app.status = 'loading'
    with pytest.raises(GenerationError) as exc:
        complete(app, valid(), lambda *a: pytest.fail('must not generate'))
    assert exc.value.status == 503


def test_generation_disables_policy_adapter_and_restores(monkeypatch):
    import torch
    from contextlib import contextmanager
    state = {'adapter': True}
    class Batch(dict):
        @property
        def input_ids(self):
            return self['input_ids']
        def to(self, device):
            assert device == 'cuda:0'
            return self
    class Tokenizer:
        eos_token_id, pad_token_id = 2, 0
        def __call__(self, *args, **kwargs):
            return Batch(input_ids=torch.tensor([[3, 4, 5]]))
        def decode(self, tokens, **kwargs):
            return '답변'
    @contextmanager
    def adapter_context(*, is_policy):
        assert is_policy is False
        state['adapter'] = False
        try:
            yield
        finally:
            state['adapter'] = True
    def generate(**kwargs):
        assert state['adapter'] is False
        assert 'prefix_allowed_tokens_fn' not in kwargs
        assert kwargs['do_sample'] is False
        return torch.tensor([[3, 4, 5, 7, 2]])
    monkeypatch.setattr(torch.cuda, 'synchronize', lambda: None)
    backend = SimpleNamespace(formatted=lambda m: 'prompt', tokenizer=Tokenizer(),
        model=SimpleNamespace(generate=generate), adapter_context=adapter_context)
    assert generate_text(backend, [], 16) == ('답변', 3, 2, 'stop')
    assert state['adapter'] is True


def test_long_context_rejected_without_gpu_or_generation():
    class Tokenizer:
        def __call__(self, *args, **kwargs):
            return SimpleNamespace(input_ids=SimpleNamespace(shape=[1, 16384]))
    backend = SimpleNamespace(formatted=lambda m: 'long context', tokenizer=Tokenizer())
    with pytest.raises(GenerationError) as exc:
        generate_text(backend, [], 1)
    assert exc.value.code == 'context_length_exceeded'


class ExistingHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_json(self, status, data):
        encoded = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        self.send_json(200, {'existing': self.path})

    def do_POST(self):
        self.send_json(200, {'existing': self.path})


def test_http_generation_and_existing_routes_remain_separate():
    app = application()
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(app, ExistingHandler, fake_generate))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with urlopen(base + '/catalog') as res:
            assert json.load(res) == {'existing': '/catalog'}
        with urlopen(Request(base + '/ask', data=b'{}')) as res:
            assert json.load(res) == {'existing': '/ask'}
        with urlopen(base + '/health') as res:
            assert json.load(res)['generation_adapter'] is False
        request = Request(base + '/v1/chat/completions', data=json.dumps(valid()).encode(),
                          headers={'Content-Type': 'application/json'})
        with urlopen(request) as res:
            assert json.load(res)['choices'][0]['message']['content'] == '정상 답변'
        request.add_header('Origin', 'http://example.invalid')
        with pytest.raises(HTTPError) as exc:
            urlopen(request)
        assert exc.value.code == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_app_routes_shared_qwen_client_without_cloud(monkeypatch):
    import openai
    from streamlit_demo import app
    app.load_generation_client.clear()
    delegate = FakeCompletions()
    calls = []
    def factory(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(chat=SimpleNamespace(completions=delegate))
    monkeypatch.setattr(openai, 'OpenAI', factory)
    monkeypatch.setenv('BIDFIT_QWEN35_9B_URL', 'http://127.0.0.1:18631/v1')
    client = app.load_generation_client('qwen3.5-9b', MODEL)
    assert isinstance(client, LocalGenerationClient)
    assert calls[0]['base_url'] == 'http://127.0.0.1:18631/v1'
    assert calls[0]['max_retries'] == 0
    app.load_generation_client.clear()
