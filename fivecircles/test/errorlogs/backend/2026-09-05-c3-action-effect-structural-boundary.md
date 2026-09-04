# C3.4 action-effect structural boundary repair

- 발생: 2026-09-05 08:18:00 KST
- 문맥: EH2.6.c3.4 `ActionEffectReceipt` 독립 adversarial review

## 재현

- `follow_up` retrieval/fuse가 `controller_decision` source를 쓰면 lane/fusion 제한을 우회했다.
- `object.__setattr__`로 drift된 receipt가 `to_dict()`에서 stale hash JSON을 만들 수 있었다.

## 원인과 수정

- source receipt kind만 보던 follow-up gate를 action kind 기준으로 이동했다.
- 직렬화 전에 전체 structural/hash validator를 재실행하고 absence/context 결합도 더 닫았다.

## 결과

- focused 11/11, related 114/114, full 1,278/1,278, safety 861 PASS.
- 독립 재리뷰 APPROVE(P0/P1 없음), API/model/Langfuse 호출 0.
