# Mini131 clean-checkout private fixture boundary

- Date: 2026-08-31
- Stage: selective staged-snapshot verification

## Issue

Git index만 임시 디렉터리에 내보내 전체 테스트를 실행했을 때 Gap30 테스트 6개가
`gap30_answer_cases_hash_mismatch`로 실패했다. 테스트가 Git에서 의도적으로 제외한 실제
질문·근거·index artifact를 직접 요구했기 때문이다. canonical private 환경에서는 통과했지만,
깨끗한 checkout의 공개 테스트 계약으로는 재현되지 않았다.

## Resolution

- production runner와 private artifact hash는 변경하지 않았다.
- 실제 private preflight를 호출하는 6개 테스트만, 기준 artifact가 checkout에 없을 때
  `skipTest`하도록 경계를 명시했다.
- provider/schema/budget/transcript 관련 합성 테스트는 계속 필수로 실행한다.

## Prevention

- private corpus 통합 테스트와 공개 합성 계약 테스트를 같은 class에 두더라도 availability gate를
  테스트별로 분리한다.
- commit 전 현재 working tree뿐 아니라 `git checkout-index`로 만든 staged snapshot을 별도로
  실행해 누락 dependency와 private fixture 결합을 찾는다.

## Pass evidence

- canonical 전체: 728/728 PASS.
- staged clean checkout: 614/614 PASS, private artifact 통합 8개 expected skip.
- private artifact와 golden set은 Git에 추가하지 않았다.
