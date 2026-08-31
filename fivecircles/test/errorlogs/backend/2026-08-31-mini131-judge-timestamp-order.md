# Mini131 judge timestamp ordering

- Date: 2026-08-31
- Stage: fixed gpt-5.6-sol secondary/adjudicator merge
- Scope: private judgment metadata ordering

## Issue

secondary decision 2건의 reviewer 작성 `reviewed_at` 값이 대응 primary보다 이른 시각으로
기록되어 fail-closed merge ordering 검사를 통과하지 못했다. 판정 내용과 reviewer 입출력은
정상적으로 보존돼 있었다.

## Resolution

- 원본 secondary decision, history와 adjudicator-visible input을 수정하거나 삭제하지 않았다.
- 실제 decision 파일 mtime을 근거로 metadata-only corrected ledger와 별도 private audit를 만들었다.
- `reviewed_at`을 제외한 semantic hash가 보정 전후 동일함을 검증했고, merge에는 corrected
  timestamp ledger만 사용했다. 의미 판정은 바뀌지 않았다.

## Prevention

- reviewer가 반환한 시각을 신뢰 경계 밖 metadata로 취급한다.
- 역할 순서는 sealed history와 검증 가능한 수신 시각으로 교차검사한다.
- timestamp 보정은 원본 보존, 근거, semantic-hash 불변 검증 없이는 허용하지 않는다.

## Pass evidence

- primary 129, secondary 13, adjudicator 13, unresolved 0.
- judgment history validation PASS, evaluation 210/210, 전체 unittest 728/728 PASS.
