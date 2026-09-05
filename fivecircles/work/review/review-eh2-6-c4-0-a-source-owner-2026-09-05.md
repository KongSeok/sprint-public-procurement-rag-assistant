# EH2.6.c4.0.a Source-owner authority 리뷰

기준: 2026-09-05 · 브랜치 `feat/total-integration`

## 판정

`APPROVE` — c4.0.a의 exact source-owner 보존·상속 범위에서 P0/P1 문제는 없다. 다만 parent
`EH2.6.c4.0`은 `b→c→d→e`가 남아 있으므로 `PARTIAL`로 유지한다.

## 구현 범위

- fact/compare/follow-up state 생성 순간의 exact `Bound*`와 source receipt를 closure-private mirror에 보존했다.
- compare는 coverage, follow-up은 outcome/progress/registry/policy까지 exact identity로 봉인했다.
- public `HarnessState`, `HarnessExecution` payload와 `issue_harness_execution` signature는 바꾸지 않았다.
- execution private authority는 source owner를 exact initial-state identity를 통해서만 상속한다.
- compatibility follow-up의 `followup_legacy` owner는 E1-safe controller source로 승격하지 않는다.
- 이 leaf는 effect mint, ledger advance, reducer/transition, provider/clock 호출을 하지 않는다.

## 적대 검토에서 발견하고 수정한 P1

1. 초기 구현은 module validator를 바꾸고 nested source를 변조하면 검증을 우회할 수 있었다. validator,
   class method, canonical hash와 closure dependency를 identity로 pin하고 drift를 source dereference 전에 거절했다.
2. 초기 구현은 `_source_owner`를 private factory에 직접 넣어 동일 payload/hash의 다른 state root로 owner를
   재사용할 수 있었다. raw state factory에서 source 입력을 제거하고, state 생성과 owner 등록을 하나의
   closure-held 경계로 묶었다. owner→origin-state mirror와 tombstone도 exact identity로 유지한다.
3. source registrar/reader의 module alias를 삭제하고, state/execution reader가 캡처한 exact callable과 closure
   cell을 검증하도록 해 사후 monkeypatch를 fail-closed했다.

## 검증

- focused+인접: 43/43 PASS.
- 전체 회귀: 1,315/1,315 PASS.
- repository safety: 874 files PASS.
- 독립 적대적 재검토: equal-hash clone, owner 재사용, origin state GC, accessor/validator drift를 재검증해
  `APPROVE`, P0/P1 0건.
- 외부 호출: API/OpenAI/model/Langfuse/golden/VLM/provider/clock 0회.

## 비범위와 다음 gate

source owner는 live effect 권한이 아니다. 다음 leaf `EH2.6.c4.0.b`에서 기존 lane/fusion/parent/bridge/
rerank/semantic/absence/decision receipt를 exact validator로 역참조해 closed source/outcome projection으로
정규화한다. one-step claim/history, per-target issuer, structural bridge는 각각 c/d/e에서 이어서 닫는다.
