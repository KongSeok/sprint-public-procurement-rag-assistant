# EVO35.3c Mini131 PRE closeout

Date: 2026-09-09. Mode: solo relay-shot. Semantic answer quality remains unjudged.

## Freeze identity

- Core runtime candidate: `52c2e24ba59c23653617cf04cab6e070d98ec646`.
- PRE runner: `803a30fdf7f051cdb0d6d90f42426482c3b93a02`.
- Mini131 suite SHA256: `04bf998b75e959b498e485587c8df8116e64fee4235a1dffb5f5c76458366357`.
- Canonical records SHA256: `4615926ef6c3c42ebb1151f657b6d41a71935e85f40de6118eae7509300f5e17`.
- Private aggregate file SHA256: `78a267a352227cfade48d9dd5ba838afc41d1dc49e98bf904a84668a22a18bdd`.
- Qwen derivative revision remained `8b2b98c00a6b4d291155e4890773ca8f769aee53`.

## Inventory

- Overall inventory: 131 = 129 RAG + 2 parser regression.
- RAG records classified: 129/129.
- Executed text: 96.
- Explicit unsupported specialist lanes: 33 = set13 + visual10 + analytics10.
- Parser regression: 2, separate ETL lane, not blended into RAG metrics and not run by this PRE runner.

## Aggregate PRE result

Terminal counts over the 96 executed text cases:

- answered: 49
- abstained: 11
- needs_clarification: 9
- budget_exhausted: 25
- invalid_action_limit: 2

Objective metrics only:

- decision match rate: 0.5052631578947369
- required-document citation recall mean: 0.5714285714285714
- all-required-docs cited rate: 0.5714285714285714
- required-document retrieval recall mean: 0.9980158730158729
- all-required-docs retrieved rate: 0.9880952380952381

Latency over executed text:

- mean: 47.537933807264686 s
- p50: 33.63896206195932 s
- p95: 109.78890182296163 s

Usage aggregate:

- policy calls: 449
- search calls: 144
- read calls: 159
- answer calls: 66
- duplicate actions: 36
- invalid actions: 4
- policy input/output tokens: 781213 / 19967
- answer input/output tokens: 63104 / 5529

## Interpretation boundary

Mini131 is a previously exposed historical benchmark, not a new sealed holdout and not training curriculum. No per-case answer/gold delta from this PRE may be used to select prompts, examples, rewards or hyperparameters. Semantic answer correctness is deliberately `unjudged` in this closeout. The only permitted repair follow-up is runtime-terminal replay selected by the two system-level exhaustion codes, with answer/gold quality excluded from the replay output.

## Next gate

`EVO35.3c.R1` completed on repaired candidate `24c2bf2`: the terminal-code-only 25-case recorded-PRE-search/live-Qwen3.5 isolation replay produced zero runtime failure codes. This accepts the policy/runtime repair only; semantic answer quality remains unevaluated and fresh-KURE end-to-end quality is not claimed. Proceed to integration, then EVO35.3d non-golden TRAIN/DEV/SEALED-HOLDOUT work.
