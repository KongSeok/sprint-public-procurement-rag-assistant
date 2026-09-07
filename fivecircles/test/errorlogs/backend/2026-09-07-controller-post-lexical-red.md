# revision2 다음 행동 선택 — 기대 RED

- 기록 시각: 2026-09-07 12:51 KST; batch=EH2.6.d2.x.b.1.
- 명령: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.test_controller_post_lexical_decision.
- 결과: exit1, 1 test / fact·compare subtest 오류2, 3.813초. 기존 코드의 controller_decision_cross_state_not_ready.
- 해석: step_index!=1 거부 경계에서 새 revision2 동작이 실패하는 기대 TDD RED다. 기존 완료 기능의 회귀가 아니다.
- 근거: /private/tmp/eh-relay-20260907.GNy8vE/post-lexical-focused-red.log.
- 처리: 기존 issuer/validator의 revision2 분기·closed reason·policy를 구현 중. 아직 해결/PASS로 기록하지 않는다.
- 경계: synthetic 테스트만 사용; 실제 검색 모델/API·gold·기준선 변경 없음.

## 최종 해결 — 2026-09-07

- revision2 action plan/reason/policy를 구현해 기대 RED 해결. 초기 실패 기록은 보존한다.
- 집중11·관련105·격리132·전체1545 PASS, 실패/오류/skip0, exit0. 제품/계약5개 동일, fresh Astra PASS.
- 상태 RESOLVED. 실제 RAG 실행 결과와 구분한다.
