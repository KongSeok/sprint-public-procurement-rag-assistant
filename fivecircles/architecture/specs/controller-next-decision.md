# EH2.6.d2.x.a — 첫 전이 이후 다음 행동 선택

상태: 구현·검증 완료 · 2026-09-06. 기준: §16.10, Cycle18 `925f4ab`.

## 목적 / 범위

기존 `decide_controller_action(execution, store, config, runtime)`을 exact revision1 최초 dense successor까지 넓힌다.
revision0 fact/compare의 기존 행동·public signature를 보존한다. revision2, follow-up, fusion/context/reducer,
실제 두 번째 실행과 terminal result 발급은 이 단계가 아니다. provider/model/clock 호출0.

## 선택 규칙

항상 기존 execution live validator와 exact initial transition reader를 먼저 통과한다.
raw consumed lane/hash나 caller outcome을 권위로 삼지 않는다. 첫 obligation의 이미 소비한 dense는 재선택하지 않는다.

| 우선순위 / 조건 | allowed / selected | reason_code |
| --- | --- | --- |
| nonterminal_action_count >= max_nonterminal_actions | untargeted abstain 하나 | action_budget_exhausted |
| exact dense effect=contract_error | untargeted abstain 하나 | contract_error |
| exact dense effect=provider_error | 같은 obligation lexical, abstain | dense_provider_error_diagnostic |
| exact dense effect=applied/empty | 같은 obligation lexical, abstain | first_eligible_nonterminal |

이 최소 slice는 후속 obligation·fuse/context를 미리 eligible로 노출하지 않는다. provider_error 뒤 lexical은
진단 전용이며 fusion/다른 obligation 승격은 금지다. contract-error abstain은 기권 결정이며 아직 terminal
`HarnessRunResult`가 발급됐다는 의미가 아니다. deadline은 시간 authority가 없어 이번 단계에서 판정하지 않는다.
같은 round의 untouched lexical은 `max_retrieval_rounds_per_obligation=1`에도 허용한다.

## DTO / authority / 정책

- ordinal2, current state/ledger/snapshot, exact previous transition SHA를 봉인한다. before/after 의미 state는 같다.
- specs뿐 아니라 reason도 factory 내부에서 유도하고 live authority에 결합·재검증한다. caller reason 입력은 없다.
- terminal reason은 abstain-only, diagnostic reason은 lexical-selected인 closed shape만 허용한다.
- 같은 snapshot 반복/동시 발급은 same-object이고 GC remint/clone/mixed/tuple·source·effect 변조는 거절한다.
- 기존 policy hash payload의 revision-zero-only 선언을 새 slice에 맞게 명시적으로 갱신한다.
  초기 행동·signature는 같지만 새 process의 action/decision SHA는 달라진다. 동일 실행 내 action identity는 stable이다.
  baseline/index/golden/config는 바꾸지 않으며 역사 receipt를 새 policy로 덮어쓰지 않는다.

## 검증 및 인계

- fact/compare applied/empty/provider/contract-error·budget1·round1, consumed dense 재선택 금지, chain/ordinal.
- repeated/barrier concurrent same-object, previous decision 유지, source/effect/ledger drift 및 추가 호출0.
- c4.1의 '두 번째 decision 미지원' 테스트는 새 기능 경계에 맞춰 'advance 자체는 두 번째 dispatch 없음'으로 갱신한다.
- focused→initial/transition/history 인접→policy/shared validator 전체 회귀를 수행하고 독립 리뷰한다.
- d2.x 부모는 PARTIAL 유지; 다음은 감사로 선택하는 후속 matrix 또는 c4.2 dispatch leaf다.

검증: 신규11 포함 인접79 PASS, 전체1522 PASS(186.315초, errors/failures/skips0), 독립 APPROVE.
후속 순서: c4.2.a lexical dispatch/revision2 → d2.x.b outcome/fusion 자격 → 후속 reducer.
lexical은 새 obligations를 발급하지 않고 exact dense receipt가 보존한 obligation을 재사용해야 한다.
