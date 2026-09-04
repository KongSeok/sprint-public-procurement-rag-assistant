Timestamp: 2026-09-04 11:10
Context: EH2.5 final authority-chain review

Issues
1) BoundCompare 내부 planning을 동일 payload의 새 객체로 교체해도 hash-only 검증이 통과했다.

Resolution
- planning/plan/trace 및 planning.plan/trace exact identity를 hash 전에 검사했다.

Prevention
- factory aggregate는 top-level hash와 모든 실행 관련 중첩 identity를 함께 봉인한다.
