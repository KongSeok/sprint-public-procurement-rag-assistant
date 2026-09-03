# EH-RC0 활성 요약 (재개 시 이것만 먼저 읽기)

- repo: `/Users/pio/Documents/AIENGINEERCOURSE/MidProjectRAG`; ambient ChatGPT 사본 금지.
- branch routing: 현재 `feat/total-integration`(이름 변경 전 `feature/visual-retrieval`)에서 후속 전체 범위를
  선택 commit·검증한다. 완료 뒤 깨끗한 sibling worktree의 `feat/local-qwen-mini131-eval`에 병합한다.
  새 브랜치는 만들지 않으며 기존 dirty 사용자 변경을 보존한다.
- 요청: 실제 Evidence-Harness 구현. 작은 leaf 하나씩 검증하며 **릴레이 계속**, ZIP 생성 반복 금지.
- 현재: Phase 0 `c2c621c`, Phase 1 `ff9fa2e` origin push 완료. EH2.1~2 PASS; 다음 leaf EH2.3.
- 완료: runtime DTO/empty scope/typed predicate/scorer/replay. focused 47, 전체 852 PASS, skip 0. 앱 연결은 아직.
- 실물: 저장 답변/source-case hash 129/129, facts117/no-facts12, API/생성 호출0, 최종 replay-03 별도 private 보관.
- 실물 경로: private/evidence-harness/v1-rc0-20260903-01. parents9331/compat children9496/structured62382; KURE/MPS 9496 + Kiwi tokens2065474. source unchanged/generation0.
- gate: focused35/full887/skip0, safety780, review3 closure, browser PASS. 모델 생성 호출0 유지.
- 원칙: gold는 evaluator 전용; None≠empty; child≠parent; 기존 artifacts 불변; resources 비공개.
- runtime 원칙: local profile이 기본이고 LLM은 provider adapter로만 교체한다. API 자동 호출 금지.
- 계약: `../architecture/specs/bidfit-evidence-harness-v1-rc0.md` §8.5~8.6, §16.5~16.6와 원문 §5.2만 우선 읽기.
- TODO: `../architecture/todolist.md` EH-RC0. 상세/원문은 애매할 때만 checkpoint/resume 문서에서 찾기.
- 테스트: EH2.2 누적 focused51/full922 PASS. EH2.3은 actual citation 상속/fallback trace focused부터 시작.
- 종료 조건: 명시적 중단/실제 blocker/승인 범위 완료. 한두 단위 끝났다는 이유로 중단하지 않음.
