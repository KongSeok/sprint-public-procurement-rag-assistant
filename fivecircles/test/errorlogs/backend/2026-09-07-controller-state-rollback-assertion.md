# 첫 fusion rollback 검증 — 오류 이름 assertion 교정

- 기록: 2026-09-07 16:22 KST. run=eh-relay-20260907 / batch=EH2.6.c4.2.b.2.
- 상태: 해당 assertion 교정 후 단일 재검증 PASS. 필수 focused/adjacent·최종 full/isolated·fresh 검수는 아직 대기다.

## 실패·원인

- 영향 subset 4건/317.700초, 실패1(나머지3 PASS), Coder 보고 process exit1.
- 등록 실패 후 포획한 중간 state는 공개 validator에서 거절됐다. 테스트가 private 오류 이름 controller_effect_state_runtime_authority_required를 예상했지만 실제 공개 계약은 harness_state_runtime_authority_required였다. rollback 동작 자체의 실패가 아니다.

## 수리·검증

- 기존 공개 오류에 맞게 테스트 assertion만 교정했다. 재검증 1건/41.605초 PASS, Coder 보고 exit0. final 후보에서 전체 필수 검증을 다시 결속한다.
- 예방: 공개 validator 경계 테스트는 실제 공개 오류 계약을 확인한다. 내부 helper의 이름을 공개 예외 계약으로 추정하지 않는다.

## 증거의 성격

- 아래 파일은 Coder가 unified-session의 정확한 출력으로 보존한 전사본이며 최초 실행부터 직접 redirect한 원시 파일은 아니다. 메인은 내용/해시를 확인했다. 명령·exit의 근거는 Coder 보고이며 최종 필수 실행은 직접 redirect와 결과 manifest로 별도 남긴다.
- 실패: /private/tmp/eh-relay-20260907.GNy8vE/first-fuse-state-affected-1.log — SHA256 afa32de237e07dd09eff69cc6b9856f7cca9a9cd377ab44cfb110d47b4c784ab.
- 수리: /private/tmp/eh-relay-20260907.GNy8vE/first-fuse-state-rollback-repair.log — SHA256 317faaa43ef3fc151af7ed82bdbee3483bcad658b88103ed2eea88b4e2a62918.
- [배치 폼](../../../work/2026-09-07-controller-fusion-state-relay.md), [계약](../../../architecture/specs/controller-first-fusion-transition.md).

## 최종 확인 — 2026-09-07 17:21 KST

- 집중25(779.422초)·관련202(230.049초)·격리227(944.217초)·전체1611(1161.717초) PASS, 실패/오류/skip0, exit0. fresh Astra first-fuse-state-review-1 PASS. 원래 실패·탐색 전사본은 보존하며 최종 실행과 혼합하지 않는다.
- 이 오류는 현재 후보의 미해결 필수 실패가 아니다. py_compile 대안을 실행한 것으로 소급 기록하지 않는다.
- [최종 배치 기록](../../../work/2026-09-07-controller-fusion-state-relay.md).
