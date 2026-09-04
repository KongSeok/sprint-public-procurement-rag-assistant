# EH2.6.b5 focused retrieval gate 리뷰

날짜: 2026-09-05
대상 브랜치: `feat/total-integration`
최종 판정: **APPROVE — P0/P1/P2 없음**

## 검토 범위

이번 leaf는 b3/b4 production surface를 넓히지 않고 검색 실행 경계 네 가지를 전용 회귀로
고정하는 acceptance gate다.

1. dense가 정상 empty이고 lexical이 후보를 찾으면 lexical-only partition으로 fusion한다.
2. fact의 두 lane이 모두 empty이면 bounded retrieval은 완료되지만 semantic READY·answerable·verified
   상태를 만들지 않는다.
3. 호출 전 contract rejection은 dense/lexical provider side effect를 0으로 유지하고 lexical/fusion
   child receipt를 만들지 않는다.
4. dense provider error 뒤 lexical 한 번은 진단 receipt일 뿐 fusion rescue로 승격하지 않는다.

각 테스트는 공개 `validate_fusion_receipt` 또는 `validate_e0_control_receipt`를 다시 호출하며,
private provider detail이 공개 payload에 들어가지 않는지도 확인한다. 실제 API, 임베딩·생성 모델,
Langfuse 및 VLM 경로는 호출하거나 변경하지 않았다.

## 독립 리뷰

두 독립 검토가 production 코드 추가 없이 현재 b3/b4 계약으로 네 시나리오가 모두 충족됨을 확인했다.

- b5 focused 정방향 4/4 PASS.
- b3+b4+b5 정방향·역방향 각각 68/68 PASS.
- public validator와 private detail 비노출 assertion PASS.
- `git diff --check` PASS.
- P0/P1/P2 없음. 선택적 보강 사항도 전용 테스트에 포함했다.

## 전체 검증 결과

```text
b5 focused: 4/4 PASS
b3+b4+b5: 68/68 PASS
retrieval related: 218/218 PASS
full unittest: 1,179/1,179 PASS
repository safety: 829 files PASS
```

따라서 parent `EH2.6.b`의 source/runtime/retrieval receipt 기반은 완료로 닫는다. 다음 READY leaf는
`EH2.6.c1`이며, EH2.3의 verified 주장을 candidate로 낮추고 실제 retrieval outcome을 follow-up slot에
투영하는 effect/reducer 단계부터 진행한다. 이 판정은 golden 품질 개선이나 E2E 완성을 뜻하지 않는다.
