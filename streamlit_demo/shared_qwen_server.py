"""Opt-in generation endpoint sharing the existing EH process and GPU lock.

Existing EH runtime and weights are imported unchanged, not copied or patched.
Only non-thinking base-model text generation is exposed on the new route.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from http.server import ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import threading
import time
import uuid

MODEL = 'Qwen/Qwen3.5-9B'
MAX_BODY = 256 * 1024
MAX_TOKENS = 1024
CONTEXT_TOKENS = 16384
TIMEOUT = 120


class GenerationError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code = status, code


def validate_request(value):
    allowed = {'model', 'messages', 'max_tokens', 'max_completion_tokens', 'stream', 'temperature'}
    def invalid(message):
        raise GenerationError(400, 'invalid_request', message)
    if type(value) is not dict or set(value) - allowed:
        invalid('지원하지 않는 생성 요청입니다.')
    if value.get('model') != MODEL:
        invalid('지원하지 않는 모델입니다.')
    if value.get('stream', False) is not False or value.get('temperature', 0) != 0:
        invalid('non-streaming deterministic 생성만 지원합니다.')
    messages = value.get('messages')
    if type(messages) is not list or not 1 <= len(messages) <= 32:
        invalid('messages는 1..32개가 필요합니다.')
    for message in messages:
        if (type(message) is not dict or set(message) != {'role', 'content'}
                or not isinstance(message['role'], str)
                or message['role'] not in {'system', 'user', 'assistant'}
                or not isinstance(message['content'], str) or not message['content'].strip()):
            invalid('문자열 대화만 지원합니다.')
    if 'max_tokens' in value and 'max_completion_tokens' in value:
        invalid('출력 토큰 한도는 하나만 지정해 주세요.')
    limit = value.get('max_tokens', value.get('max_completion_tokens', MAX_TOKENS))
    if type(limit) is not int or not 1 <= limit <= MAX_TOKENS:
        invalid('출력 토큰 한도는 1..1024입니다.')
    return messages, limit


def generate_text(backend, messages, limit):
    """No EH schema constraint and no policy adapter; shared caller holds lock."""
    import torch
    from transformers import StoppingCriteria, StoppingCriteriaList

    prompt = backend.formatted(messages)  # existing non-thinking chat template
    tokens = backend.tokenizer(prompt, add_special_tokens=False, return_tensors='pt')
    input_count = int(tokens.input_ids.shape[-1])
    if input_count + limit > CONTEXT_TOKENS:
        raise GenerationError(400, 'context_length_exceeded',
            f'입력 {input_count} + 출력 {limit} 토큰이 {CONTEXT_TOKENS} 한도를 넘습니다. 질문 범위를 좁혀 주세요.')
    started = time.monotonic()

    class Deadline(StoppingCriteria):
        def __call__(self, input_ids, scores, **kwargs):
            return time.monotonic() - started >= TIMEOUT

    try:
        tokens = tokens.to('cuda:0')
        with backend.adapter_context(is_policy=False), torch.inference_mode():
            output = backend.model.generate(**tokens, max_new_tokens=limit,
                do_sample=False, use_cache=True, logits_to_keep=1,
                eos_token_id=backend.tokenizer.eos_token_id,
                pad_token_id=backend.tokenizer.pad_token_id,
                stopping_criteria=StoppingCriteriaList([Deadline()]))
        torch.cuda.synchronize()
        generated = output[0, input_count:].tolist()
        if time.monotonic() - started >= TIMEOUT:
            raise GenerationError(504, 'generation_timeout', '로컬 생성 제한 시간을 초과했습니다.')
        text = backend.tokenizer.decode(generated, skip_special_tokens=True)
        if not text.strip():
            raise GenerationError(502, 'empty_generation', '로컬 모델이 빈 답변을 반환했습니다.')
        reason = 'stop' if generated and generated[-1] == backend.tokenizer.eos_token_id else 'length'
        return text, input_count, len(generated), reason
    except torch.cuda.OutOfMemoryError as exc:
        torch.cuda.empty_cache()
        raise GenerationError(503, 'gpu_memory_busy', 'GPU 메모리가 부족합니다. 요청 범위를 좁혀 주세요.') from exc


def complete(application, value, generate=generate_text):
    messages, limit = validate_request(value)
    if application.status != 'ready' or application.backend is None:
        raise GenerationError(503, 'not_ready', 'VM 모델이 준비 중입니다.')
    if not application.lock.acquire(blocking=False):
        raise GenerationError(409, 'model_busy', '다른 EH/생성 요청을 처리 중입니다. 완료 후 다시 시도해 주세요.')
    try:
        text, prompt_tokens, completion_tokens, reason = generate(application.backend, messages, limit)
    finally:
        application.lock.release()
    return {'id': 'chatcmpl-' + uuid.uuid4().hex, 'object': 'chat.completion',
        'created': int(time.time()), 'model': MODEL,
        'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': text}, 'finish_reason': reason}],
        'usage': {'prompt_tokens': prompt_tokens, 'completion_tokens': completion_tokens,
                  'total_tokens': prompt_tokens + completion_tokens}}


def handler_for(application, base_handler, generate=generate_text):
    class Handler(base_handler):
        def generation_failure(self, exc):
            self.send_json(exc.status, {'error': {'message': str(exc), 'type': 'generation_error',
                                                'code': exc.code}})

        def do_GET(self):
            if self.path == '/v1/models':
                return self.send_json(200, {'object': 'list', 'data': [
                    {'id': MODEL, 'object': 'model', 'owned_by': 'local'}]})
            if self.path == '/health':
                return self.send_json(200, dict(application.health(),
                    generation_api='/v1/chat/completions', generation_model=MODEL,
                    generation_adapter=False, context_tokens=CONTEXT_TOKENS,
                    max_output_tokens=MAX_TOKENS))
            return super().do_GET()

        def do_POST(self):
            if self.path != '/v1/chat/completions':
                return super().do_POST()
            if self.headers.get('Origin') or self.headers.get_content_type() != 'application/json':
                return self.generation_failure(GenerationError(403, 'forbidden', '서버 측 JSON 요청만 허용합니다.'))
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= MAX_BODY:
                    raise GenerationError(413, 'body_too_large', '요청 크기 한도를 초과했습니다.')
                self.connection.settimeout(10)
                value = json.loads(self.rfile.read(size))
                self.connection.settimeout(TIMEOUT + 10)
                result = complete(application, value, generate=generate)
            except GenerationError as exc:
                return self.generation_failure(exc)
            except (ValueError, UnicodeError):
                return self.generation_failure(GenerationError(400, 'invalid_json', 'JSON 요청을 확인해 주세요.'))
            except Exception:
                return self.generation_failure(GenerationError(500, 'generation_failed', '로컬 생성 처리에 실패했습니다.'))
            self.send_json(200, result)
    return Handler


def load_existing(path, expected_sha):
    if sha256(path.read_bytes()).hexdigest() != expected_sha:
        raise ValueError('기존 서버 코드가 달라졌습니다. 재검토 후 실행해 주세요.')
    spec = importlib.util.spec_from_file_location('bidfit_existing_eh_server', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--existing-server', type=Path, required=True)
    parser.add_argument('--expected-sha', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--port', type=int, default=18631)
    args = parser.parse_args()
    os.umask(0o077)
    original = load_existing(args.existing_server, args.expected_sha)
    application = original.Application(args.output)
    server = ThreadingHTTPServer(('127.0.0.1', args.port),
        handler_for(application, original.handler_for(application)))
    application.save_health()
    threading.Thread(target=application.load, args=(original.VM_ROOT,), daemon=True).start()
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
