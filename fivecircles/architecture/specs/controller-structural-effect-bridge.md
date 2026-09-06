# EH2.6.c4.0.e 구조적 effect bridge 계약

작성일: 2026-09-06
상태: 구현 완료 · c4.1 effect mint 전 단계

## 목적

c4.0.c의 정확한 one-step `claimed → sourced` 증거와 c4.0.d의 정확한 bounded
target context를 c4.1이 나중에 사용할 수 있는 구조적 재료로 결합한다. 이 단계는
검색·검증·상태 전이를 실행하거나 허가하지 않는다. 기존 local-first 비교 기준선과
실제 provider/model/clock/Langfuse 호출은 영향을 받지 않는다.

## 비범위

- `ActionEffectReceipt` live mint, effect-bound history, reducer, ledger advance, state transition
- provider, model, retriever, verifier, reranker, clock, Langfuse 호출
- public/package export 또는 arbitrary payload/hash/source 주입
- revision-0 d2 decision 범위 확장

## 비공개 API

`execution_contracts.py` 안의 closure-private API만 허용한다.

```text
_prepare_controller_structural_effect_bridge(
    claim, projection, target_context, store, config, runtime
) -> _ControllerStructuralEffectBridge
_require_controller_structural_effect_bridge(
    bridge, store, config, runtime
) -> _ControllerStructuralEffectBridge
```

입력은 발급된 exact claim, 그 claim에 weak-bind된 exact source/outcome projection,
선택적으로 같은 action/target의 exact target context뿐이다. action/source/outcome,
evidence ID, receipt SHA, call 여부는 입력에서 다시 받지 않고 live projection/context에서
도출한다.

## 불변식

1. claim은 현재 `sourced` 상태이고 projection의 execution/decision/action/source identity가
   claim과 모두 같아야 한다.
2. obligation-only/terminal action은 context가 없어야 한다. evidence-target action은
   context가 있어야 하며 action kind·target ID·selected receipt identity가 모두 일치해야 한다.
3. bridge는 immutable·non-serializable·redacted repr의 private value다. 구조적 digest는
   execution/decision/action/source/context의 SHA와 closed outcome row로만 계산하며 raw query/text,
   gold/qrels, provider detail, after-state를 포함하지 않는다.
4. 같은 live root에서 동일 입력을 반복하면 같은 bridge object를 반환한다. bridge가 GC된 뒤에도
   root가 살아 있으면 tombstone으로 재발급을 거부한다. root까지 GC된 경우에만 다음 진입에서
   cache/authority mirror를 수거한다.
5. clone, mixed store/config/runtime, projection/context mutation, out-of-order/retroactive source,
   duplicate/remint, dependency drift는 provider 호출 전에 fail-closed한다.
6. 성공 후에도 controller history는 `sourced`로 남고 `effect_bound`/`transitioned`로 바뀌지 않는다.

## 수용 기준

- normal lane sourced claim에서 bridge를 한 번 발급하고 반복 호출이 same-object인지 확인
- out-of-order, clone/mixed graph, mutation, GC remint 공격이 모두 거부됨
- target context가 없는 evidence-target 또는 context가 있는 obligation-only action이 거부됨
- bridge가 public `__all__`/package attribute에 노출되지 않음
- bridge 전후 provider/model/clock/Langfuse 호출 수가 0이고 `_bind_controller_step_effect`는 계속 dormant
- c4.0.c/d 관련 회귀와 전체 unittest·repository safety가 유지됨
