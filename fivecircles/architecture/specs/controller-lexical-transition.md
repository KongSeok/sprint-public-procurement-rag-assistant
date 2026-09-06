# EH2.6.c4.2.a — 같은 항목 lexical 실행과 revision2

상태: 구현 중 · 2026-09-06. 기준: §16.10 + controller-next-decision.md, 시작853c7ee.

## 범위와 입력

- private `_execute_controller_lexical_step(execution, decision, store, config, runtime) -> HarnessExecution`.
- exact revision1 fact/compare successor와 해당 snapshot의 ordinal2 selected lexical permit만 받는다.
  caller는 source receipt/obligation/outcome/evidence/hash를 주입하지 않는다. public start/step/run은 추가하지 않는다.
- 최초 dense의 exact source receipt authority에서 보존된 obligation을 재사용한다.
  compare issuer 전체를 재호출하면 이미 GC된 다른 obligation 때문에 expired될 수 있으므로 재발급하지 않는다.

## 실행과 전이

1. execution/decision/selected action/budget·exact dense lineage를 검증하고 기존 one-step claim을 소비한다.
2. 기존 lane executor로 같은 obligation/round1 lexical 한 번 실행. claim→prepare source→source→bridge의 기존 epoch/identity 경계를 유지한다.
3. live effect는 lexical source-derived outcome/call/evidence를 보존하고 step_index=2, stable execution identity에 묶는다.
4. ledger revision2, previous ledger=revision1 hash, consumed action/lane에 lexical 하나만 추가, nonterminal count2.
   round1·no-progress·exact state는 그대로다. 실제 semantic 승격은 없다.
5. transition step2, previous transition=exact step1 hash. before/after state 및 ledger·decision/effect·동일 semantic fingerprint를 봉인한다.
6. execution 권위는 stable initial root와 immediate predecessor를 구분한다. revision0/1/2와 양쪽 source receipt를 모두 유지/재검증한다.
   initial readback은 계속 revision1 전용이며 새 `_require_controller_lexical_transition(execution, store, config, runtime)`은 revision2 전용이다.
7. duplicate/concurrent는 최대 한 번 dispatch/한 successor다. dispatch 뒤 fail은 claim을 failed로 소비하고 partial result/retry를 허용하지 않는다.

## 결과별 경계

- dense 정상/empty 뒤 lexical applied/empty/provider/contract-error receipt를 전이2에 그대로 기록한다.
- dense provider_error 뒤 lexical은 진단용 한 번뿐이다. 성공해도 dense 오류를 지우거나 정상 fusion 가능으로 승격하지 않는다.
- d2.x.a가 abstain을 선택한 contract-error/budget 경로에는 lexical을 호출하지 않는다.
- terminal 결과/세 번째 decision/fusion/다른 obligation/semantic reducer/deadline 측정은 이 단위에서 구현하지 않는다.
  별도 provider/model/clock 호출을 추가하지 않고, 테스트에는 synthetic lane만 사용한다.

## 수용 기준 / 후속

- first dense1+lexical1·query scope 보존, 입력 clone/다른 permit/예산 차단은 lexical0.
- compare tuple 재발급 없음, revision0/1/2 chain과 source GC 유지, 동시성·중간 예외·변조 검증.
- production code 변경 전후 focused/기존91 등 관련 gate 및 shared authority 전체 회귀, 독립 리뷰, report/logall/push.
- 후속 d2.x.b는 exact 두 lane outcome으로 fuse 또는 sanitized error 종료를 선택한다.
  다른 compare obligation의 canonical tuple 전체 수명 보존은 해당 실행 확대 전에 별도 검증한다.
