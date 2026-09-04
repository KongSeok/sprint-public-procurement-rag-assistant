# EH2.6.c3.2 ID-less rerank / derived semantic review

## Scope

- `RerankReceipt`, strict ID-less request/result, exact context batch와 owner budget
- candidate/bridge global order, derived semantic obligation, auxiliary parent nonpromotion
- base/derived route one-shot, root-lifetime history, provider/contract failure sanitization

## Findings and repair

### P1 — provider exception post-call validation bypass

초기 구현은 reranker가 예외를 던진 경로에서 source/store/config/runtime/prerequisite/component의
post-call 재검증을 건너뛰었다. provider가 자기 상태를 바꾸고 예외를 던지면 `provider_error` receipt를
반환한 뒤 public validator가 그 receipt를 즉시 거부하는 불일치가 재현됐다.

정상 반환과 예외를 하나의 post-call gate로 합쳤다. 무변조 예외는 sanitized `provider_error`, 상태 변경 뒤
예외는 sanitized `contract_error`로 닫고 둘 다 `call_performed=true`와 one-shot route consumption을 유지한다.
상태를 복원한 뒤에도 재실행되지 않는 회귀를 추가했다.

## Final review

- P0: 없음
- P1: 없음(발견 1건 수리·회귀 통과)
- global rerank order와 candidate/bridge role subsequence가 일치함
- `rerank_k`/`final_evidence_budget`가 exact root owner plan에서 유도됨
- parent는 private unindexed context이며 support/citation/evidence로 승격되지 않음
- unavailable은 provider 0회 identity prefix, applied/error는 live route를 한 번만 소비함
- package root는 DTO/validator/derived issuer만 공개하고 executor는 module-only임

## Verification

- focused: 9/9 PASS
- related semantic/retrieval/action/state: 128/128 PASS
- full: 1,229/1,229 PASS
- repository safety: 854 files PASS
- Playwright: images 2, tables 8, page errors 0, mobile overflow 0 PASS
- external API/model/Langfuse/VLM/golden calls: 0

판정: **APPROVE — c3.2 범위 완료.** bounded absence, effect/reducer/controller와 동일 golden 성능 비교는
후속 범위이며 아직 완료되지 않았다.
