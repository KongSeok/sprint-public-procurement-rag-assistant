# Local-first visual integration / LLM adapter contract

## 1. Goal — 2026-09-03 superseding decision

사용자 승인: **그림/OCR 작업은 로컬 설계에만 통합한다. API 브랜치 전체는 병합하지 않는다.**
파서·청크·KURE 임베딩·로컬 인덱스·검색을 유지하고 답변 생성 LLM만 로컬/API로 교체한다.
LLM 교체는 재임베딩 사유가 아니다. 기존 visual 계약의 API-first 순서를 이 결정으로 대체한다.

## 2. Scope and Git contract

- 공통 시작점 `7ad229f8c85fb48ebb1c53f4424db4a224b562a7`에 검증한 OCR/safety 파일만 선택 커밋한다.
- local tip `6e5da2284b67f7ad648a3e8e18a12fbe1a6dccef`을 `integration/local-visual`에 병합한다.
- sibling worktree `MidProjectRAG-local-visual`을 사용한다. 원본 dirty checkout/다른 worktree는 보존한다.
- API tip `33f8c2f`, harness tip `46275c4`, 타 작업자의 미커밋 UI/catalog/table 변경은 제외한다.
- main/push, 실물 전체 OCR/재임베딩, 유료 API 실행, 자동 visual 활성화, VLM 구현은 범위 밖이다.
- resources 전체·.env·모델·venv는 복사/커밋하지 않는다. 운영본 TODO/계약에 작업 위치와 결과를 남긴다.

## 3. Runtime contracts

- 기존 `load_mac_pipeline`과 동결 Mini131 설정/평가 증거는 보존한다.
- 새 application composition은 동일 검증된 local retrieval components를 재사용한다.
- 생성 provider는 `ollama`(기본), `vllm`, `openai`; provider별 기존 allowlist·토큰상한을 유지한다.
- OpenAI는 `gpt-5-nano`/`gpt-5-mini`만, 기존 생성 adapter를 재사용한다.
- OpenAI에는 명시적 client, 모델에 맞는 token counter, budget, 매 요청 실제 prompt 승인 guard가 필요하다.
- 키 존재만으로 승인하지 않는다. 미승인 호출과 실패 후 provider 자동 우회는 금지한다.
- 공통 `generate(prompt) -> (answer_plan, input_tokens, output_tokens)`와 인용/기권 검사를 따른다.
- application stack ID를 동결 `mac_local_equivalent`/`gcp_local` 평가 ID와 구분한다.
- OCR은 로컬 KURE 별도 인덱스 우선. page index는 보존하고 모델/revision/차원/청킹 식별자를 고정한다.
- OCR chunk는 현재 offline 산출물이며 R2–R5 gate 전 검색·답변에 자동 투입하지 않는다.
- D-020 private OCR/crop 외부전송 제한을 유지한다. LLM 교체 기능과 실제 전송 승인은 별개다.

## 4. Batches / acceptance and tests

1. 선택 통합: OCR wrapper/9파일 검증/캐시/resources 제외를 local branch와 통합한다.
2. LLM composition: retrieval loading 공유, 생성 설정만 교체, frozen loader 동작 보존.
3. 실제 pipeline + provider stub으로 동일 검색순위·인용·캐시 재사용과 미승인 API 차단을 검증한다.
4. 전체 unittest·safety·diff 검사, target/current 흐름 보고서 렌더와 logall로 마감한다.

## 5. Follow-up / known gaps

- GOLDEN-E2E-OCR: OCR→로컬 임베딩→검색→생성/인용→UI 골든·자원·비그림 회귀 검증은 후속이다.
- occurrence dedup/relevance admission, caption 배제, opt-in UI, object-aware gold 이후 활성화한다.
- GCP vLLM/FAISS 실물 재현, API 생성 교체 성능, VLM 해석은 fixture 검증으로 대체하지 않는다.

## 6. Validation

검증 내역은 `local-first-generation-flow.md`와 연결된 HTML에 기록한다.
원본 API UI 서버/활성 bundle은 전환하지 않는다. 이번 완료 범위는 로컬 코드 통합과 생성기 조립 함수다.

## 7. Application usage

`src/midprojectrag/local_application.py`는 shared core 밖의 composition root다.
기존 `load_mac_pipeline`은 frozen evaluation 전용으로 남기고 아래 경로를 새 application에서 사용한다.

```python
import json
from pathlib import Path
from midprojectrag.gcp_local_baseline import load_mac_retrieval_components
from midprojectrag.local_application import GenerationSelection, build_local_first_pipeline

# verified: 기존 load_verified_baseline으로 source/hash 확인한 로컬 baseline 객체
retrieval = load_mac_retrieval_components(verified)
settings = json.loads(Path("configs/rag/local-first-ollama.json").read_text())
pipeline = build_local_first_pipeline(retrieval, generation=GenerationSelection(**settings))
result = pipeline.query(request)
```

OpenAI profile을 선택할 때는 `ApiGenerationAccess(client, counter, budget, authorize)`를 명시적으로
전달해야 한다. 공식 OpenAI endpoint만 허용하며 counter는 선택 모델의 offline-verified
`TiktokenCounter`, budget은 private `BudgetLedger`를 사용한다. authorize는 실제 prompt/instructions,
destination/model별 승인 정책을 확인하고 literal True를 반환해야 한다. 키만으로 활성화하지 않는다.
새 API profile로 고른다고 OCR/crop 전송이 승인되는 것은 아니다. 자동 fallback은 없다.

기본 generation 상한은 output 1,024, logical context 8,192 token이다. Ollama transport는 32,768이고
별도 pinned Qwen counter로 logical 상한을 확인한다. vLLM은 기존 model revision/8K 설정을 유지한다.
프로필은 `local-first-{ollama,vllm,openai-nano,openai-mini}.json`이다. CLI/UI 선택기는 후속 연결이다.

통합 브랜치 검증 후 로컬 `feat/local-qwen-mini131-eval`을 fast-forward로 갱신한다.
분기되어 FF가 불가능하면 덮어쓰지 않는다. 원격 push/main/API branch 변경은 하지 않는다.
