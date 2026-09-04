# EH2.6.c3.3 absence authority and follow-up replay

- 시각: 2026-09-05 07:25 KST
- 범위: bounded absence receipt와 기존 follow-up primary/progress/finalize 실행 경계
- 상태: RESOLVED

## 증상

- cached absence receipt 변조가 동일 호출의 fast path에서 재검증되지 않았고, visible authority 단독 교체로 forged receipt를 승인할 수 있었다.
- 동일 `BoundFollowup`에서 primary/progress/fallback을 다시 실행할 수 있었고 production source와 synthetic runtime 혼합도 거부되지 않았다.

## 원인과 수리

- cache/authority를 편의 저장소로만 보고 root 수명 전체의 실행 권한으로 봉인하지 않았다.
- cache hit 전체 재검증, closure-private authority mirror, root-lifetime exact-once FSM, execution-kind 일치 gate를 추가했다.

## 검증

- focused 67/67, 관련 192/192 PASS; 독립 최종 리뷰 APPROVE(P0/P1 없음).
- 전체 회귀와 repository safety 결과는 같은 사이클 update/flow ledger에 기록한다.
- API·model-provider·Langfuse 호출 0.

## 예방

- at-most-once claim/cache는 exact root 수명에 묶고, fast path도 최초 mint와 같은 authority·payload·dependency 검증을 수행한다.
- production/synthetic execution kind는 source owner에서 유도해 runtime preflight에 강제한다.
