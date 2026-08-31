# Fresh Request Handling

- New or changed product requests re-enter requirements analysis.
- Record confirmed decisions in `fivecircles/requirements/decisions.md` and update `current.md`.
- Update the relevant technical contract before adding or changing a batch.
- Direct fixes that do not alter requirements may use a small implementation→test→log cycle.

## Completed Requests

- [x] 2026-08-31: 보조 골든셋 69문항을 사람 승인 전에도 `provisional` 등급으로 실행·채점할 수 있게
  열고, 현재 refined 98문서 API 기준선으로 실제 평가한다. 사람 검수는 실행 차단 조건이 아니라
  `official` 승격 조건으로만 유지한다. 계약·구현·검증 후 관련 변경만 선별 커밋·푸시한다.
- [x] 2026-08-31: 기존 Mini exact 답변 39건을 보존하고 누락 30건과 core/visual/EDA 60건을
  `gpt-5-mini`로 실행한다. RAG 129건은 고정 `gpt-5.6-sol`로 판정하고 parser 회귀 2건을
  별도 합산해 같은 private HTML에 131건 채팅·점수·근거를 남긴 뒤 logall·선별 push한다.

완료 증거: RAG 평균 54.845, accepted 58/129, parser 2/2, transcript 129/129,
판정 이력 155행, 전체 회귀 728/728, 후보 비용 USD 0.21345322.

## Active Requests

- None. Current work is tracked in `fivecircles/architecture/todolist.md`.
