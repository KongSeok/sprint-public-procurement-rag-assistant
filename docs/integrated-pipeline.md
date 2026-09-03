# 통합 RAG 파이프라인

## 목적

팀원 브랜치를 통째로 이어 붙이는 작업이 아니라, 각 브랜치에서 검증된 기능을
공통 입력·출력 계약으로 연결해 같은 Golden Set에서 비교하는 작업이다.

```text
HWP/PDF
  → 텍스트·표·OCR 추출
  → Parent-Child 청킹
  → KURE + BM25 하이브리드 검색
  → 근거 레코드 생성
  → GPT-5 mini 또는 Local Qwen
  → 답변·인용 검증
  → 오프라인 재평가
```

## 최신 브랜치 반영 기준

2026-09-03 통합 시작 직전 `git fetch --prune origin`으로 확인한 각 브랜치의
최신 tip을 기준으로 삼았다. 겹치는 기능은 더 최신 후속 브랜치만 사용한다.

| 원본 브랜치 | 확인한 최신 tip | 통합한 내용 |
| --- | --- | --- |
| `feat/rag-pipeline-and-eval` | `d51633b` | 전체 파이프라인, Parent-Child, KURE+BM25, 평가 코드 |
| `experiment/DH` | `5ea75c7` | 예산·지자체 질의 필터 아이디어. Colab 경로와 40문항 전용 코드는 제외 |
| `feat/local-qwen-mini131-eval` | `6fea63f` | vLLM/Ollama 생성 provider와 PP-OCRv5 선택 구조 |
| `feat/api-gpt5mini-mini131-eval` | `33f8c2f` | GPT-5 mini Responses API provider |
| `feat/evidence-harness-v1` | `46275c4` | 해시 기반 근거 ID와 인용 출처 검증 |
| `feature/visual-retrieval` | `c2c621c` | 저장 결과의 오프라인 재검증과 실행환경 기록 |

`feat/vlm-visual-retrieval`의 최신 tip `5c732eb`는
`feat/local-qwen-mini131-eval`에 포함되어 있으므로 중복 반영하지 않았다.

## 실행

API 기준선:

```bash
export OPENAI_API_KEY="..."
python scripts/run_integrated_model.py \
  --provider openai \
  --query "예산 3억 이상인 지자체 사업을 알려줘" \
  --output output/openai-result.json
```

GCP VM의 vLLM Qwen:

```bash
python scripts/run_integrated_model.py \
  --provider vllm \
  --model Qwen/Qwen3-8B-AWQ \
  --base-url http://127.0.0.1:8001/v1 \
  --query "예산 3억 이상인 지자체 사업을 알려줘" \
  --output output/qwen-result.json
```

저장 결과의 근거·인용 계약은 모델을 다시 호출하지 않고 검사할 수 있다.

```bash
python scripts/replay_integrated_results.py output/openai-result.json
```

## 비교 원칙

- 같은 데이터, Golden Set, `top_k`, 하이브리드 가중치를 사용한다.
- 생성 모델을 비교할 때 검색 결과를 바꾸지 않는다.
- OCR 비교 시 OCR backend 외의 설정을 고정한다.
- 결과 JSON의 `runtime.source_branch_tips`와 패키지 버전을 함께 보관한다.
- 정확도뿐 아니라 인용 지원 여부, 기권률, 지연시간, 비용, GPU 메모리를 기록한다.
