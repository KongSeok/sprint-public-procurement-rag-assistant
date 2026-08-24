# Policies (Agent Guardrails)

## Folder Rules
- agent/: 행동 규칙(운영 절차)
- agent/skills/: 프로젝트 로컬 스킬과 프로토콜
- requirements/: 요구사항/논쟁/확정 결정
- architecture/specs/: 기술 분석/설계(운영 규칙 금지)
- architecture/: 배치/태스크 플랜
- work/: 실행 로그/근거
- test/: 테스트 정책/실패 로그
- maintenance/: 유지보수/환류
- scoring/: (옵션) 점수 기록

## Hard Gates
1) Test exit 조건을 만족하지 못하면 Integrate 금지
2) git push는 Integrate 단계에서만 허용
3) 테스트 통과 증거 없이 “pass”라고 기록 금지

## Protected Areas (추천)
- agent/
- requirements/decisions.md (확정 기록)
- test/testpolicy.md

변경이 필요하면:
- 먼저 work/worklog.md에 변경 사유/범위/롤백 방법 기록

Product behavior and data policy follow `fivecircles/agent/authority.md`; this file controls execution procedure only.

## Git Commit Message Convention (Default)
- feat(scope): message
- fix(scope): message
- refactor(scope): message
- test(scope): message
- docs(scope): message
- chore(scope): message

Minimum: 콜론 뒤 message 길이 10자 이상
