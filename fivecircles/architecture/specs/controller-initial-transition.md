# EH2.6.c4.1 최초 검색 effect와 실행 전이

상태: 구현·검증 완료 · 2026-09-06. 권위: `bidfit-evidence-harness-v1-rc0.md` §16.10.

## 목표와 범위

현재 d2.i가 선택하는 revision-0 fact/compare의 첫 `retrieve_dense`를 실제 실행 기록과
ledger revision 1로 연결한다. lane 검색은 의미 상태를 바꾸지 않으므로 `after.state is before.state`이다.
두 번째 decision, semantic state 변경, follow-up 및 다른 action은 d2.x/c4.2에서 다룬다.
추가 검색·모델·verifier·reranker·clock 호출은 없다. 기존 artifacts와 local/API profile은 그대로다.

## 비공개 입력과 결과

- `_advance_initial_controller_step(bridge, store, config, runtime) -> HarnessExecution`
  exact sourced claim에 결합된 기존 structural bridge만 받는다. action/outcome/hash/effect/after-state를
  caller가 넣을 수 없다. 내부적으로 live effect 발급, history 결합, 전이 및 successor 발급을 수행한다.
- `_require_controller_initial_transition(execution, store, config, runtime)`는 발급된 successor의
  exact `(ActionEffectReceipt, HarnessTransitionReceipt)`를 반환한다. 다른 객체의 같은 hash는 허용하지 않는다.
- `HarnessTransitionReceipt`는 before/after state·ledger hash, stable execution identity, decision/effect hash,
  previous transition 및 semantic progress fingerprint를 봉인하는 immutable value이다. public mint는 없다.

## 전이 계약

1. 선행 조건: exact revision-0 execution/decision/selected dense action, fact 또는 compare source,
   `sourced` history 및 claim 이후 실행된 exact lane receipt. c4.0.e bridge 자체는 계속 non-authorizing이다.
2. effect는 기존 `ActionEffectReceipt` schema를 재사용하고 stable execution identity 및 before-state에 결합한다.
   source-derived applied/empty/provider_error/contract_error를 보존한다. 기존 schema의 1-based step_index를 유지해
   effect.step_index=decision.decision_ordinal=before.step_index+1이다.
3. ledger: revision=1, previous=before ledger hash, 첫 obligation round=1, selected action 소비1,
   consumed lane=(obligation key, 1, dense), nonterminal_action_count=1. no-progress와 다른 obligation은 그대로다.
4. after-state는 exact before-state 객체다. 검색만으로 verified/confirmed-missing/contradicted가 되지 않는다.
   semantic fingerprint는 stage·candidate/verified/context ID만 사용하고 timestamp/counter/provenance hash는 제외한다.
5. transition은 이전 transition=null인 첫 chain link다. successor는 stable identity를 유지하고 새 snapshot hash를 가진다.
   predecessor와 successor 모두 live validator를 통과해야 기존 decision/source provenance를 다시 검증할 수 있다.
6. 한 permit으로 successor를 중복 발급하지 않는다. 반복·동시 진입은 same-object를 반환하거나 소비된 step으로 거절한다.
   발급 도중 실패하면 partial success를 반환하지 않고 claim을 failed로 소비한다.
7. preparation bridge는 sourced 상태에서만 검증한다. 발급된 effect/transition의 readback은 별도 exact authority와
   source validation을 사용해 effect_bound/transitioned 뒤에도 정상 동작한다. 새 mint 권한으로 역승격하지 않는다.
8. clone/mixed graph, effect/transition/ledger/tuple 변조, out-of-order/replay를 거절한다.
   단일 root에 successor만 덮어써 predecessor가 무효화되는 구현은 금지한다.

## 실행 단위 및 수용 기준

- c4.1.a: source-derived effect/live registration 및 reserved history edge를 연결한다.
- c4.1.b: 첫 ledger·transition·successor와 predecessor 유지 검증을 연결한다.
- c4.1.c: fact/compare·성공/empty/error·중복/동시·변조·추가 provider0을 통합 검증한다.
- focused 및 기존 aggregate/decision/history/bridge 회귀를 먼저 실행하고 공통 authority 변경에 대한 전체 회귀를 한 번 수행한다.
- current/target report·로그올·선택 commit/push 후 다음 READY leaf를 재조회한다. API/골든셋 성능 비교는 수행하지 않는다.

## 검증 결과와 다음 경계

- 신규13+bridge7+history30=50 PASS, 인접41 PASS, 전체1511 PASS(174.977초, 오류/실패/skip0), 독립 APPROVE.
- 중간 발급 예외→failed 소비·동시성·전후 연결·tuple/source 변조·생존 successor provenance를 검증했다.
- 최초 unsearched 상태의 context fingerprint는 빈 ID다. c4.2에서 실제 context ID로 확장하며 successor GC 후 passive 정리도 검증한다.
- 원장: `../../work/2026-09-06-controller-initial-transition-relay.md`.
