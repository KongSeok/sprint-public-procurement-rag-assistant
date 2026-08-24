# Batch 2 Closeout — Shared RAG Evaluation Contract

상태: READY_PRIVATE_GOLD

날짜: 2026-08-24

## 구현 완료

- provider-neutral request/response JSON Schema와 로컬-only Schema registry
- 단일 문서·다중 문서·후속 질문·미지 질문 eval case 및 run-record 계약
- dev/held-out group, normalized question, multi-document pair, conversation 누수 검사
- order-sensitive combined/dev/held-out dataset·sequence hash
- document/source-block Recall@1/3/5/10, MRR@10, nDCG@10과 다중 문서 coverage
- key-point, correctness, faithfulness, citation, follow-up, 안전 기권 지표
- p50/p95 latency, API token/USD, GCP GPU seconds/VRAM 및 환경 제약 기록
- offline `validate`, `score`, `compare` CLI와 Git-safe 합성 예제

## Fail-closed 경계

- score는 동결된 config, SHA-256, task별 최소 case 수와 정확한 k 값을 요구한다.
- hard gate의 metric/operator/value/stack scope가 빠지거나 약화되면 실패한다.
- explicit scope 밖 retrieval hit 또는 citation을 거부한다.
- unknown 성공은 응답 계약, gold reason, `safe_abstention=true`, dev 1인/held-out 2인 검토를 모두 요구한다.
- A/B 비교는 완전하고 통과한 API/GCP-local 보고서 한 쌍만 허용하며 hash, case/task 수, metric shape와 threshold evidence를 재검증한다.
- malformed JSON shape와 schema/manual parity 회귀를 구조화 오류로 처리하고 비공개 입력 내용을 출력하지 않는다.

## 검증

- 평가 `unittest` 31개 통과
- Batch 1 포함 전체 `unittest` 53개 통과 (`pypdf` 6.10.0 포함 Python 3.12 runtime)
- JSON Schema 4개와 registry/config/template JSON·JSONL 문법 검사 통과
- Draft 2020-12 engine에서 모든 외부 `$ref`가 네트워크 없이 로컬 `$id`로 해석됨
- 합성 dev/held-out validation 및 40-case API↔GCP-local score/compare smoke 통과
- `compileall`, `git diff --check`, 저장소 safety 검사를 통합 커밋 직전에 통과했다.

## 다음 실행 항목

- 실제 source blocks가 materialize되어 dev 40문항과 held-out 20문항 작성이 가능하다.
- 질문 작성 후 2인 교차검토·held-out 순서 봉인·locator hash 검증이 필요하다.

공개 계약과 도구 구현은 완료됐다. 다음 상태 변경은 실제 gold set을 만들고 validation seal을
남겼을 때 수행한다.
