# fivecircles

이 폴더는 프로젝트에 “개발 5사이클(+Integrate)” 운영체제를 이식하기 위한 템플릿입니다.

## License
This project’s design and governance documents are licensed under **CC BY 4.0**.

## 시작하기
- architecture/specs/README.md를 읽고 워크플로우를 초기화합니다.

## 어디에 뭐가 있나
- architecture/specs/README.md 전체 워크플로우를 정의합니다.
- **agent-guidelines.md**: `MidProjectRAG` 프로젝트명과 루트 경로를 고정한 에이전트 실행 가이드입니다.
- **agent/skills/**: 프로젝트 로컬 스킬. 에이전트는 명령어가 스킬 트리거와 맞으면 해당 `SKILL.md`를 먼저 읽고 작업합니다.
- **requirements/**: 프로젝트 요구사항. 사용자와 합의/논쟁(debate)하고 확정하는 공간입니다.
- **architecture/specs/**: architecture/specs/README.md에 명시된 절차에 따라, 요구사항/결정에 기반해 “분석된 기술적 내용”만 기록합니다. (설계·API·DB·성능·보안 등)
- **architecture/todolist.md**: 작업 배치/태스크 분해(플랜)
- **work/**: 실행 로그(결정, 근거, 결과), 업데이트 기록
- **test/**: 테스트 정책 및 실패 로그, 개선사항 기록/제안
- **maintenance/**: 유지보수/새 요구사항 환류
- **scoring/**: 에이전트 점수 규칙/기록, 더 나은 코딩 절차 제안

## 시작 순서 (사람/에이전트 공통)
1) architecture/specs/README.md
2) agent-guidelines.md
3) agent/agent-guidelines.md
4) requirements/README.md
5) architecture/todolist.md 작성 후 사이클 시작

## 스킬등록방법
- 프롬프트 입력: "fivecircles/agent/skills/ 폴더를 보고 스킬을 등록하세요."
- 세션 시작 시 `fivecircles/agent/skills/`의 `SKILL.md`와 protocol 문서를 확인하면 컨텍스트 손실을 줄일 수 있습니다.

## 에이전트 스킬 (Agent Skills)

| 스킬명 | 파일명 | 발동 명령어 | 설명 |
| --- | --- | --- | --- |
| Fivecircles | `fivecircles/SKILL.md` | `"fivecircles"` | fivecircles 운영 워크플로를 시작하고 프로젝트 규칙을 적용합니다. |
| Philosopher / Coder 협업 | `collaboration/SKILL.md` | `"필로소퍼/코더 협업"`, `"협업 모드 릴레이샷"` | Astra 설계·fresh 검수와 Sol Ultra 구현, 로그올·통합·단일 릴레이를 연결합니다. |
| One Shot Delivery Orchestrator | `one-shot-delivery-orchestrator/SKILL.md` | `"원샷딜"`, `"원샷딜리버리"` | 요구사항, 계약, 구현, 테스트, 브라우저 검증, 로그까지 한 작업을 끝까지 배달합니다. |
| Batch Sequential Runner | `batch-sequential-runner/SKILL.md` | `"배치 순차 실행"`, `"끝까지 진행"` | 여러 단계/배치를 terminal state까지 순차 실행합니다. |
| Doc Contract Writer | `doc-contract-writer/SKILL.md` | `"계약 문서 작성"`, `"설계 먼저"` | 구현 전 요구사항, API/DTO/tool 계약, DoD, 검증 기준을 문서화합니다. |
| Test Runner | `test-runner/SKILL.md` | `"테스트 실행"`, `"검증해"` | 자동 테스트, API smoke, Playwright/browser 검증을 수행합니다. |
| Just Bash Workflow | `just-bash-workflow/SKILL.md` | `"just-bash"` | 안전한 bash 탐색 워크플로를 사용합니다. |
| Logall | `logall/SKILL.md` | `"로그올"` | update, todo, learn-from-log, errorlog를 정책에 맞게 기록합니다. |
| Logall Score | `logall-score/SKILL.md` | `"울트라 기록"` | 로그 기록과 scoring을 함께 수행합니다. |
| Request Queue | `request-queue/SKILL.md` | `"요청 큐"` | 요청을 큐로 정리하고 우선순위를 관리합니다. |
| 운영방침 초기화 | `protocol_operation_init.md` | `"운영방침 초기화"` | README, agent 문서, 요구사항, TODO를 읽고 운영 맥락을 재설정합니다. |
| 빠른 디버깅 | `protocol_quick_debug.md` | `"빠른 디버깅"` | mistakes-arrest와 learn-from-log를 먼저 검색해 재발 오류를 빠르게 잡습니다. |
| 로그 요약 | `protocol_logging_summary.md` | `"로그 요약"` | 작업 종료 시 update/todo/sync/error 기록을 표준화합니다. |
| 동료 리뷰 | `protocol_peer_review.md` | `"리뷰해"` | 변경사항과 의사결정을 검토하고 리뷰 기록을 남깁니다. |
