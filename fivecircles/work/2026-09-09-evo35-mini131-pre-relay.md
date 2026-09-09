# EVO35.3c Mini131 PRE relay

## 0. Scope Intake
- Mode: solo relay-shot, explicit user request; no Coder/Critic delegation.
- Candidate: `52c2e24ba59c23653617cf04cab6e070d98ec646`.
- Goal: run the frozen untrained Qwen3.5 EvoHarness PRE benchmark before non-golden collection.
- Boundaries: original Mini131 checkout read-only; raw questions/gold/answers/trajectories private; no gold-assisted repair; unsupported specialist lanes stay in denominator.

## 1. Target / Current
- Target: frozen candidate -> 131 explicit terminal classifications -> aggregate PRE receipt -> publish -> EVO35.3d.
- Current: 96 text cases potentially executable; set13/visual10/analytics10 explicitly unsupported; parser2 separate ETL.
- Environment: project venv has KURE/MPS/Kiwi, MLX venv has Qwen3.5 but not torch/KURE/Kiwi.

## 2. Relay selection
- Selected unit: persistent local MLX worker + parent project-venv PRE adapter, then full supported text run.
- Connection score: 9 (required upstream freeze baseline; unlocks all learning data collection).

## 3. Contract
- `fivecircles/architecture/specs/evo-mini131-pre.md` / `evo35-mini131-pre-v1`.
- Follow-up ten cases use end-to-end prior-turn replay from candidate output; no fabricated historical evidence IDs.

## 4. Implementation
- Persistent worker loads Qwen once in MLX venv and serves count/structured-complete JSONL requests.
- Parent keeps KURE/MPS retrieval in project venv and runs current `EpisodeRunner`.
- Private resumable per-case records + aggregate receipt; public only aggregate/hash/limitations.

## 5. Validation
- Worker protocol/unit tests; Mini131 adapter tests with synthetic fixtures; real retrieval preflight; real Qwen structured preflight; then supported cases.
- Final impact regression and flow report after run.

## 6. Repair
- Fail closed; preserve runtime/environment failures. Never use per-case gold to repair behavior.

## 7. Publication
- Push aggregate code/contracts/results only after actual run; private source/results stay ignored.

## 8. Relay
- On PRE publication: `CONTINUE_WITH_NEXT_FORM` -> EVO35.3d non-golden data collection.
