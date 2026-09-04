# EH2.6.b4 fusion/E0 실행 무결성 수리 기록

## 증상

- provider callback이 실행 중 child executor/validator global을 바꿀 수 있었다.
- 다음 obligation lane이 이전 obligation fusion보다 먼저 열릴 수 있었다.
- closure cell 교체와 receipt GC 뒤 fusion progress 단독 삭제가 replay 방어를 약화할 수 있었다.
- 해당 반례를 검사한 r27 cleanup이 progress만 복구해 역순 반복 테스트에 stale state를 남겼다.

## 원인

- E0가 child callable을 매 단계 global lookup했고 provider 반환 뒤 dependency를 재검증하지 않았다.
- b3 lane ledger와 b4 fusion completion 사이에 obligation advance gate가 없었다.
- runtime pin이 code/default/global identity까지만 포함했고 fusion 완료 이력은 한 map에만 있었다.
- 테스트 cleanup이 서로 identity를 공유해야 하는 두 closure-private map을 대칭 처리하지 않았다.

## 수정

- E0 진입 시 child executor/validator를 고정하고 매 provider 반환 뒤 dependency, exact type,
  public receipt validation을 재수행한다.
- lane claim 전에 이전 obligation fusion 완료를 확인한다.
- closure cell content identity를 runtime dependency에 고정한다.
- progress/history가 같은 immutable tuple object를 공유하는 ledger-lifetime 이중 이력을 사용한다.
- r27은 live ledger를 유지하고 두 map을 동일 entry로 대칭 복구한다.

## 예방 규칙

- provider 호출 전 검증만으로 실행 권위를 보장했다고 보지 않는다. untrusted callback 반환 뒤에도
  callable dependency와 typed child receipt를 재검증한다.
- 단계별 ledger를 분리할 때 다음 단계의 완료가 이전 ledger advance의 선행조건인지 명시한다.
- replay 방어 이력은 결과 DTO의 수명에 의존하지 않는다.
- private state를 직접 교란하는 회귀는 teardown에서 모든 mirror를 동일 identity로 복원하거나
  dead owner라면 모두 제거한다. 테스트 순서·반복 실행으로 격리를 검증한다.

## 검증

- b3+b4 정·역순 64/64 및 순서 교대 10회 총 640 PASS.
- 관련 214/214, 전체 1,175/1,175 PASS.
- 독립 최종 리뷰 APPROVE, P0/P1/P2 없음.
