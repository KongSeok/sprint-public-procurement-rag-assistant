# EH2.6.c3.1 parent/bridge source receipt review

## Scope

- `ParentContextReceipt` / `BridgeContextReceipt` factory, validator, runtime binding과 public export
- caller-ID-free bounded seed, parent nonpromotion, actual table/figure bridge와 empty attempt
- exact authority, at-most-once, concurrency, failure, copy/pickle/JSON replay와 비누출

## Findings and repair

### P1 — intermediate semantic lifetime replay

초기 history/cache가 중간 `SemanticVerificationObligation` weak lifetime에 묶여 있었다. root source가 살아
있어도 중간 객체를 GC하고 동등 obligation을 재발급하면 같은 payload의 새 receipt authority를 mint할 수
있었다.

수리 후 실행 키는 semantic issuance key·obligation SHA·exact store/config/runtime identity에 결합되고,
history/cache 수명은 exact owner root source가 소유한다. 동등 semantic reissue는 기존 receipt tuple/item의
exact identity를 재사용한다. semantic-only GC 회귀를 추가했다.

## Final review

- P0: 없음
- P1: 없음(발견 1건 수리·회귀 통과)
- P2: 없음
- parent가 synthetic Evidence/support/citation으로 승격되지 않음
- bridge가 caller target을 받지 않고 exact store linkage만 봉인함
- 정상 반복·동시 winner·실패 후 retry·semantic GC·비직렬화·비누출 경계 통과

## Verification

- focused: 8/8 PASS
- related: 114/114 PASS
- full: 1,220/1,220 PASS
- repository safety: 850 files PASS
- Playwright: images 2, tables 8, page errors 0, mobile overflow 0 PASS
- external API/model/Langfuse/VLM/golden calls: 0

판정: **APPROVE — c3.1 범위 완료.** EH2.6.c3 전체·검색 성능 개선·E2E 완료를 의미하지 않는다.
