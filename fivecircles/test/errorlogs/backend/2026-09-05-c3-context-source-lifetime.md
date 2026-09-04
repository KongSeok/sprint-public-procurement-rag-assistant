# EH2.6.c3.1 context source lifetime

## Context

`ParentContextReceipt`와 `BridgeContextReceipt`의 local at-most-once 발급 수명을 독립 감사했다.

## Issue

초기 구현은 claim/history/cache를 중간 `SemanticVerificationObligation` 객체의 identity와 weak lifetime에
결합했다. root retrieval/follow-up source가 살아 있어도 중간 obligation만 GC한 뒤 동등 obligation을
재발급하면 같은 payload SHA의 새 receipt authority를 다시 mint할 수 있었다.

## Resolution

- 실행 키를 semantic authority issuance key, obligation SHA, exact store/config/runtime identity로 구성했다.
- history/cache 정리는 중간 obligation이 아니라 exact owner root source의 weak lifetime에 연결했다.
- receipt authority도 root source와 semantic issuance identity를 함께 검증한다.
- 동등 semantic reissue는 기존 tuple과 내부 receipt 객체를 exact identity로 재사용한다.

## Prevention

at-most-once 권한의 tombstone 수명은 파생 DTO가 아니라 실행을 소유한 root authority에 묶는다. 중간 객체 GC,
동등 파생 객체 재발급, 성공·실패 뒤 재시도와 동시 실행을 각각 focused gate로 유지한다.

## Verification

- focused c3.1: 8/8 PASS
- semantic/retrieval/action/state 관련: 114/114 PASS
- full unittest: 1,220/1,220 PASS
- repository safety: 850 files PASS
- 외부 API/model/Langfuse/VLM/golden 호출: 0
