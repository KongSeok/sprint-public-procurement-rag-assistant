# EH2.6.c3.3 bounded absence 통합 리뷰

날짜: 2026-09-05
대상: `feat/total-integration`의 bounded absence receipt 및 follow-up 실행 권한
최종 판정: **APPROVE — P0/P1 없음**

## 검토 범위

- 세 absence reason의 exact prerequisite matrix와 zero-provider/nonpromotion 경계
- factory-only DTO, package/module 공개면, validator와 root-lifetime cache/authority
- follow-up primary→progress→finalize의 동시성·재진입·실패·GC 수명
- production source와 synthetic runtime 실행 종류 일치

## 발견 및 수리

1. 동일 호출 cache fast path가 변조된 receipt를 전체 재검증하지 않았다. cache hit에도 payload/hash/dependency/owner projection 검증을 적용했다.
2. visible authority 단독 교체로 forged receipt를 승인할 수 있었다. closure-private shadow와 쌍 검증을 추가했다.
3. 같은 `BoundFollowup`에서 실행 단계를 다시 시작할 수 있었다. root-lifetime exact-once FSM과 한 winner lock/CAS를 추가했다.
4. production follow-up source가 synthetic runtime과 결합될 수 있었다. source-derived execution kind를 runtime validator에 강제했다.

## 증거

- focused absence/follow-up: 67/67 PASS
- 관련 semantic/retrieval/action/state: 192/192 PASS
- 전체 unittest: 1,267/1,267 PASS
- repository safety: 858 files PASS
- Mermaid/HTML Playwright: images2, tables8, page errors0, mobile overflow0 PASS
- API·OpenAI·model-provider·Langfuse 호출: 0

## 잔여 경계

- receipt는 sealed query/scope/budget에서 support를 찾지 못했다는 증명일 뿐 corpus 전체의 사실 부재가 아니다.
- state/effect/terminal 권한은 없다. `ActionEffectReceipt` public mint는 EH2.6.d2 decision permit 전까지 계속 차단한다.
