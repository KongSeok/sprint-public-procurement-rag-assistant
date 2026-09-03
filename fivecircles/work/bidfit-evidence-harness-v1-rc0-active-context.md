# EH-RC0 활성 요약 (재개 시 이것만 먼저 읽기)

- repo: `/Users/pio/Documents/AIENGINEERCOURSE/MidProjectRAG`; ambient ChatGPT 사본 금지.
- branch: `feature/visual-retrieval`; 시작 `7ad229f`; 기존 dirty 사용자 변경 보존.
- 요청: 실제 Evidence-Harness 구현. 작은 leaf 하나씩 검증하며 **릴레이 계속**, ZIP 생성 반복 금지.
- 현재: Phase 0 구현/검증 완료, 선택 commit/push 진행. 다음 READY는 EH1.1.
- 완료: runtime DTO/empty scope/typed predicate/scorer/replay. focused 47, 전체 852 PASS, skip 0. 앱 연결은 아직.
- 실물: 저장 답변/source-case hash 129/129, facts117/no-facts12, API/생성 호출0, 최종 replay-03 별도 private 보관.
- 다음: EH1.1 Evidence/ProvenanceParent → EH1.2 immutable store → child splitter. score 8, 상류 의존성.
- 원칙: gold는 evaluator 전용; None≠empty; child≠parent; 기존 artifacts 불변; resources 비공개.
- 계약: `../architecture/specs/bidfit-evidence-harness-v1-rc0.md` §8.3만 우선 읽기.
- TODO: `../architecture/todolist.md` EH-RC0. 상세/원문은 애매할 때만 checkpoint/resume 문서에서 찾기.
- 테스트: `PYTHONPATH=src .venv/bin/python -m unittest -q tests.test_runtime_integrity tests.test_harness_scoring tests.test_harness_replay`.
- 종료 조건: 명시적 중단/실제 blocker/승인 범위 완료. 한두 단위 끝났다는 이유로 중단하지 않음.
