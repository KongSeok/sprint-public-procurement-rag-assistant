# Agent Command Center (Start Here)

당신은 이 저장소에서 “개발 운영”을 수행하는 코딩 에이전트입니다.
가장 중요한 목표는: **요구사항을 명확히 하고, 작은 배치로 구현하며, 테스트 통과 상태를 커밋/푸시로 고정**하는 것입니다.

## Mandatory Read Order
1) fivecircles/README.md
2) fivecircles/agent-guidelines.md
3) agent/agent-guidelines.md
4) agent/authority.md
5) agent/workflow.md
6) agent/policies.md
7) agent/methodology.md
8) agent/operational-guidance.md
9) agent/skills/ relevant `SKILL.md` files for the user request
10) work/workpolicy.md
11) test/testpolicy.md
12) requirements/* (현재 유효한 요구사항)

## Working Mode
- 모든 작업은 `architecture/todolist.md`의 **Batch** 단위로 수행합니다.
- 작업 중 의사결정/충돌/근거는 `work/worklog.md`에 남깁니다.
- 기술적 분석 결과는 `architecture/specs/`에 정리합니다. (agent 문서에 기술 분석을 쓰지 않습니다.)
- 사용자의 표현이 `agent/skills/**/SKILL.md`의 트리거와 맞으면 해당 로컬 스킬을 먼저 읽고 따른다.

## Debate Mode (Requirements)
- 요구사항이 불명확/모순/충돌이면, 먼저 `requirements/debates/`에 논쟁 기록을 생성합니다.
- 합의된 결론은 `requirements/decisions.md`에 “확정”으로 남깁니다.
- 확정 이후에만 `architecture/specs/`에 기술 설계를 고정합니다.

## Cycle (6-stage)
Requirements → Design → Implementation → Test → Integrate(Commit/Push) → Maintenance

## What you do first
1) `fivecircles/agent/skills/` 존재 여부와 관련 스킬 확인
2) requirements/README.md 확인
3) requirements/current.md에서 현재 요구사항 읽기
4) architecture/todolist.md에서 현재 Batch 확인 또는 작성
5) work/worklog.md에 필요한 Stage 엔트리 추가
