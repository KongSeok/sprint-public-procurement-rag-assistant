# Workflow OS (Agent Runtime)

이 문서는 “에이전트가 어떻게 행동해야 하는가”를 정의합니다.
기술 설계/분석 내용은 **fivecircles/architecture/specs/**에만 기록하고, 여기에는 운영 절차만 둡니다.

## Development Cycle (6-stage)
1) Requirements
2) Design
3) Implementation
4) Test
5) Integrate (Commit/Push)
6) Maintenance

---

## Stage 1) Requirements
Goal: 요구사항을 명확히 하고, 모순을 발견하고, 합의 가능한 형태로 고정한다.

Actions:
- requirements/current.md 읽기
- 불명확/충돌/리스크가 있으면 requirements/debates/에 debate 파일 생성
- 합의된 결론을 requirements/decisions.md에 기록(확정)

Exit checklist:
- DoD(성공조건) 최소 1개
- 범위(in/out) 명시
- 모호한 용어 정의(필요 시)
- 결정사항이 decisions.md에 “확정”으로 남음

---

## Stage 2) Design(Architecture)
!중요: 에이전트는 구현 전 `fivecircles/architecture/specs/`의 관련 계약을 확인한다.
Goal: Batch를 작은 태스크로 분해하고 테스트 접근을 함께 적는다.

Actions:
- requirements/current.md, requirements/decisions.md 확인 후 상세스펙 작성:프로젝트 architecture, api contract, data model, matching rules, schema.sql, docker.md, frontend.md, evaluatenvolve.md
- architecture/todolist.md에 Batch 작성/수정
- todo 완료 체크 후 정리, 남은것 확인, 작업추가

Exit checklist:
- 태스크가 작은 산출물로 분해됨
- 각 태스크별 테스트 접근(단위/통합) 1줄 이상

---

## Stage 3) Implementation
!중요: 에이전트는 구현 전 `fivecircles/architecture/specs/`의 관련 계약을 확인한다.
Goal: 선택된 방법론 프로파일(TDD/Custom/None)에 따라 구현한다.

Actions:
- work/implementation-log.md에 Intent/변경점 기록
- 필요한 기술 분석은 `fivecircles/architecture/specs/`에 정리(예: API, 데이터 schema, 성능 고려)

Exit checklist:
- 변경점(what/why)이 로그에 남음
- 최소 단위 기능 1개 완료

---

## Stage 4) Test
Goal: 자동화된 테스트로 기능을 검증한다.

Actions:
- testpolicy에 따라 unit/integration 실행
- 실패 시 test/errorlogs/에 날짜 파일 생성
- work/worklog.md에 증거(출력/CI 링크 등) 기록

Exit checklist:
- unit tests pass
- integration tests pass (해당 시)
- 리그레션 체크 기록

---

## Stage 5) Integrate (Commit/Push)
Goal: 테스트 통과 상태를 Git 커밋/푸시로 고정한다.

Actions:
- format/lint → tests → git status clean 확인
- 규칙에 맞게 커밋 메시지 작성
- push 수행
- work/integrate-log.md에 commit hash/결과 기록

Exit checklist:
- format/lint pass
- git status clean
- commit message convention 만족
- commit hash 기록
- push 완료

---

## Stage 6) Maintenance
Goal: 기술부채/새 요구사항을 정리하고 Requirements로 환류한다.

Actions:
- maintenance/maintenance.md 업데이트
- 요구사항 변경이 있으면 requirements/current.md 업데이트 + decisions.md에 기록

Exit checklist:
- 기술부채 후보 기록
- 요구사항 변경 시 Requirements로 환류 완료
