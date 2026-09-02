# Evidence-Harness 비시각 로컬 실행

2026-09-02 · opt-in / nonofficial · 기존 baseline 변경 없음

## 프로필

| 항목 | 현재 구현 |
| --- | --- |
| 근거 저장소 | 98문서, 9,331 page + 9,513 text = 18,844 Evidence |
| 검색 | 기존 KURE 9,331×1,024 page-part vectors + 새 child BM25, RRF k=60 |
| 임베딩 | `nlpai-lab/KURE-v1`, revision `4ed4540949c70b7da2c74004a915e1f2d5e46e4f`, CPU query-only |
| planner / policy / verifier / generator | 실제 Mac `qwen3.8:27b-mlx`, pinned digest; 정책은 미학습 |
| reranker | Identity/no-op. learned reranker로 표시하지 않음 |
| 로컬 기본 실행 한도 | request 180초, HTTP call 60초, context 32,768, output ceiling 1,800 |
| harness 한도 | 24 actions, slot별 3 rounds, 후보 20, 필수 검증 근거만 context에 포함; 9,000 chars / 12 items / doc당 6 |
| list 한도 | scan+reduce 128 calls, batch 6,000 chars, reduce 12,000 chars, total 500,000 chars |
| visual | 멀티모달 임베딩/실제 reader 미연결, capability gap |
| 의미 품질 평가 | runtime과 분리. 고정 ChatGPT `gpt-5.6-sol`만 담당; 이번 실행에서는 점수 미산출 |

페이지 part 벡터를 새 child 임베딩으로 전환한 것이 아니다. 기존 parser·corpus·chunk와
모델 파일 해시를 검증하여 재사용하며 원본에 index lock이나 새 파일을 쓰지 않는다.
기존 corpus에서 만드는 store는 표의 구조화 객체나 그림을 새로 복원하지 않는다.
그 구조는 explicit source linkage가 검증된 별도 auxiliary artifact를 연결해야 한다.

## 실행

활성 worktree 루트에서 Python 3.12와 프로젝트 의존성을 사용한다. 기존 corpus/cache를 가진
저장소 경로를 `HARNESS_SOURCE_ROOT`에 직접 지정한다. 문서·gold는 원격으로 보내지 않는다.

```sh
export HARNESS_SOURCE_ROOT=/path/to/existing/repository
PYTHONPATH=src python -m midprojectrag.orchestration.cli prepare-legacy \
  --source-root "$HARNESS_SOURCE_ROOT" \
  --output private/evidence-harness/kure-page-evidence-v1.json

HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONPATH=src \
python -m midprojectrag.orchestration.cli run \
  --source-root "$HARNESS_SOURCE_ROOT" \
  --evidence private/evidence-harness/kure-page-evidence-v1.json \
  --request private/evidence-harness/request.json \
  --output private/evidence-harness/new-run.json \
  --timeout-seconds 300 --per-call-seconds 60
```

출력은 새 private 파일만 허용하며 덮어쓰지 않는다. 재실행은 다른 이름을 지정한다.
request는 기존 표준 schema의 question/history/document_scope/options만 허용하고 gold 필드는 거부한다.
`--source-root`를 생략하면 lexical-only다. dense가 실패했다고 자동 lexical로 전환하지 않는다.
`--policy bounded`는 단순 허용 행동 정책 비교용이며 기본값은 local LLM policy다.

모델을 부르지 않는 fixture 준비와 실제 loopback 호출은 구분한다.

```sh
PYTHONPATH=src python scripts/evidence_harness_smoke.py
PYTHONPATH=src python scripts/evidence_harness_smoke.py --run --output-name fact-new.json
PYTHONPATH=src python scripts/evidence_harness_smoke.py --scenario list --run --output-name list-new.json
```

## 결과 읽기

- `READY`는 계획한 근거를 검증·보존했다는 운영 상태이며, 정답/accepted 점수가 아니다.
- `list`는 top-k가 아니라 scoped 문서를 전수 scan/reduce한다. 작은 예산 내에서 끝나지 않으면
  부분 목록을 완전한 목록으로 내지 않는다. 98문서 전수 실행의 지연·커버리지는 아직 실측하지 않았다.
- 모델/범위/계약 실패는 표준 `error`, 근거·예산·capability 부족은 `abstained`로 구분한다.
- private trace v2에 retrieval/model/prompt/budget seal, 단계별 실제 후보·공급 근거·LLM 응답을 남긴다.
  외부 공유할 때 원문/질문/응답 대신 집계와 해시만 사용한다.
- v1 trace 호환은 유지한다. 학습 export는 allowlist/heldout gate를 요구하며 list receipt는
  `list_trajectory_not_trainable`로 거부한다. 학습 데이터 승인은 별도다.
- CPU embedding deadline은 반환 전후 검사다. 프로세스 강제취소나 GCP 성능 보장은 아니다.

## 다음 검증의 경계

동일한 고정 골든셋·동일 judge로 baseline과 새 프로필의 품질/지연을 비교하기 전까지
예상 향상 점수나 운영 승격을 주장하지 않는다. GCP Qwen3-8B-AWQ 측정, 학습된 정책,
learned reranker, 새로운 child embedding, visual reader는 이번 로컬 연결과 별개다.

[보고서](evidence-harness-report.html) · [계약](../architecture/specs/evidence-harness-contract.md)
