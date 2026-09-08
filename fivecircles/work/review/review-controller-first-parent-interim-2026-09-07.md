# 첫 parent 실행 — 중간 위험 검수

## Scope

- EH2.6.c4.2.b.3 / source·claim·context 경계의 fresh Astra deep. 최종 납품 검수가 아니다.
- 후보 sha256:83a4351856743aef0232a926f0ea2512aad7637f8dd94f89b11762dd7ad41279; 계약 sha256:f8fe0041df23b81dc3e88b0138363535c504bf5e36269610af118884f72752de; 증거 sha256:87527c7539f5148ecd070958d49d108acc5ca942f7bb16c2e6e67bd2a27a5a4a.
- [원문 REVIEW](../collaboration/eh-relay-20260907/messages/EH2.6.c4.2.b.3/004-first-parent-interim-review-1.json).

## Findings

1. P1 FP-INTERIM-1: revision4 readback이 선택된 source만 검사하고 보존한 전체 parent/bridge context graph를 다시 검사하지 않는다. non-dispatching exact-context 검증을 등록/readback에 결속해야 한다.
2. P1 FP-INTERIM-2: preflight와 두 context batch 획득 사이 다른 bridge 발급이 끼면 cached tuple을 가져올 수 있다. 기존 cache 의미를 보존하면서 원자적 소유/실제 출처 경계를 닫아야 한다.
3. P2 FP-INTERIM-3: compare·실패·경쟁·수명 등 승인 matrix와 최종 필수 검사가 아직 남았다. 계획된 미완료이며 동일 finding 수리 실패로 세지 않는다.

## Decision

REQUEST_CHANGES / PATCH. 두 P1은 정적 호출경로/동기화 검토 결과다. Critic은 재현 테스트를 실행하지 않았고 main도 관련 실제 호출부를 읽어 확인했다. 기존 lane/fusion seal 유지 + parent once-only seal 방향은 유지한다. 검수 한 번을 전체 PASS나 통합 허가로 바꾸지 않는다.

## Next actions

- 같은 Sol Ultra Coder가 소유2파일 안에서 P1 수리·방어 회귀를 추가하고 기존 matrix를 끝낸다. 범위/계약 충돌은 QUESTION으로 올린다.
- 새 후보의 focused/adjacent/isolated/full 후 fresh final deep 검수. last-pass는 이전 Cycle24에 유지, Risk7 이력은 초기화하지 않는다.
- 모델/API/GPU/GCP/데이터·평가 조건·브랜치 변경 없음.
