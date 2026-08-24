# Methodology Profiles (Implementation)

Implementation은 Batch마다 프로파일 1개를 선택한다.
선택은 architecture/todolist.md의 Batch 헤더에 적는다.

## TDD (Red-Green-Refactor)
- Red: 실패하는 테스트 먼저
- Green: 최소 구현
- Refactor: 구조 개선(행동 불변)

규칙:
- 새 행동 추가 시 테스트 우선(정당화 가능)
- 작은 사이클, 자주 통과

## CUSTOM (Project-defined)
프로젝트 내부 방법론을 정의한다. (예: IMO)
추천 템플릿:
- Intent(what/why/scope)
- Minimal slice
- Observe(테스트/로그 증거)

## NONE
엄격한 절차 없음
단, 기본 테스트 1개 이상 + worklog 기록은 필수
