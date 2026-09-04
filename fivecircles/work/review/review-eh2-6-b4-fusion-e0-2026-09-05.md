# EH2.6.b4 same-round fusion·E0 control 리뷰

날짜: 2026-09-05
대상 브랜치: `feat/total-integration`
최종 판정: **APPROVE — P0/P1/P2 없음**

## 검토 범위

이번 leaf는 owner-issued obligation의 dense·lexical 결과를 같은 round에서만 RRF로 합치는
`FusionReceipt`와, 검색 결과를 상태 판정으로 과장하지 않는 `E0ControlReceipt`를 구현했다.

- 평가 checkpoint의 optional visual lane 자리를 보존해 fusion ordinal은 4다.
- 정상 dense·lexical pair의 obligation/query/scope/store/config/runtime identity가 모두 같아야 한다.
- E0는 전체 canonical obligation을 호출 전에 검사하고 obligation별 dense→lexical→fusion 순서를 지킨다.
- 공개 payload는 safe evidence/anchor/partition와 child SHA만 담고 raw query, provider trace,
  evaluator/gold/qrels 및 semantic READY 상태를 담지 않는다.
- 실제 API, 임베딩·생성 모델, Langfuse는 호출하지 않았다.

## 독립 리뷰에서 발견해 닫은 문제

초기 구현에 대해 독립 리뷰가 P1 네 가지와 테스트 격리 결함 한 가지를 발견했다.

1. provider callback 중 global child executor를 바꾸면 E0 다음 단계가 교체 구현을 신뢰할 수 있었다.
   E0 진입 시 executor/validator identity를 local로 고정하고 provider 반환 뒤 dependency gate,
   exact child DTO type, public validator를 다시 검사하도록 고쳤다.
2. 여러 obligation에서 다음 dense lane이 이전 obligation fusion보다 먼저 시작될 수 있었다.
   lane claim 전에 previous-fusion-complete gate를 추가했다.
3. code/default/global pin만으로는 closure cell 자체 교체를 감지하지 못했다. runtime dependency pin에
   closure tuple과 각 cell value의 exact identity를 추가했다.
4. fusion receipt가 수거된 뒤 단일 progress map이 지워지면 replay 이력이 사라질 수 있었다.
   ledger 수명의 별도 history를 두고 progress/history가 동일 immutable tuple object를 공유할 때만
   진행하도록 고쳤다. 둘 중 하나만 교체·삭제하면 public replay 전에 fail-closed한다.
5. r27 회귀의 cleanup이 progress만 복구해 역순 실행에 stale state를 남겼다. strong live-ledger를
   유지하며 두 미러를 같은 entry로 대칭 복구하도록 고쳤다.

## 최종 독립 검증

- 정방향·역방향 b3+b4 각각 64/64 PASS.
- 순서를 번갈아 10회 실행한 총 640개 테스트 PASS.
- 매 반복 GC 뒤 progress/history 0/0, key·entry identity 불일치 0.
- provider가 child executor/validator 다섯 지점을 바꾸는 재현 모두 dependency drift로 receipt 발급 전 차단.
- FusionReceipt 삭제와 두 번의 GC 뒤 progress 단독 삭제 및 history 단독 삭제 모두 public replay 차단.
- 다중 obligation은 dense→lexical→fusion→다음 lane 순서를 provider 호출 전에 강제.
- concurrent fusion/E0 회귀에서 race, deadlock 또는 우회 징후 없음.

명시적 비지원 범위인 여러 private closure mutable 객체의 동시 직접 변조는 이번 판정 범위에서
제외했다. 현재 공개 API와 단일 내부 상태 drift 계약에서는 P0/P1/P2가 남지 않았다.

## 전체 검증 결과

```text
b4 focused: 27/27 PASS
b3+b4: 64/64 PASS
retrieval related: 214/214 PASS
full unittest: 1,175/1,175 PASS
repository safety: 828 files PASS
```

다음 READY leaf는 `EH2.6.b5`다. 독립 lane, lexical rescue, fact empty, 호출 전 거부 시나리오를
focused gate로 한 번 더 고정한 뒤 effect/reducer/E1 controller로 이동한다.
