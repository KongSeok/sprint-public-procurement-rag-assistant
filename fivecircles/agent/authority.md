# MidProjectRAG Authority (Single Source)

문서 충돌 시 이 파일의 순서만 사용합니다. 다른 문서는 이 목록을 복제하지 않고 여기로 연결합니다.

## Priority — High to Low

1. 플랫폼·시스템·보안 제약
2. 현재 대화의 최신 명시적 사용자 지시
3. `fivecircles/requirements/decisions.md`
4. `fivecircles/requirements/current.md`
5. 관련 `fivecircles/architecture/specs/*` 기술 계약
6. `fivecircles/agent/workflow.md`, `policies.md`, `methodology.md` — 실행 절차에만 적용
7. `fivecircles/architecture/todolist.md`
8. 테스트·평가·실행 readback — 구현 상태를 입증하지만 요구사항을 변경하지 않음
9. `fivecircles/work/*`, `fivecircles/test/*`, `fivecircles/scoring/*` 기록
10. `fivecircles/legacy/*` — 보존용이며 권위 없음

## Boundary

- agent 문서는 제품 기능·데이터 정책을 새로 정의할 수 없습니다.
- runtime 증거는 구현 오류를 증명할 수 있지만 요구사항을 자동으로 뒤집지 않습니다.
- `legacy/`의 경로, 코드, 모델과 프로젝트명은 새 구현의 기본값으로 재사용하지 않습니다.

## Conflict Handling

충돌이 있으면 `fivecircles/work/worklog.md`에 다음을 기록합니다.

- Conflict
- Competing sources
- Winner and authority level
- Resolution
- Follow-up TODO or decision update
