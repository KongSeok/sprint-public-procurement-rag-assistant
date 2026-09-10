# EvoHarness Training, Leakage, and Evaluation Contract

Contract ID: `evo35-train-eval-v1`
Date: 2026-09-09
Authority: D-029 and explicit user instruction to proceed by solo relay-shot without collaboration-model restrictions.
Application baseline: `Qwen/Qwen3.5-9B`; execution-agent/model choice is unrestricted in solo mode and does not silently change the system-under-test.

## 1. Goal

Build a reproducible policy-learning pipeline around the existing hotline EvoHarness, repair the historical/current evidence-handle confusion before data collection, freeze a pre-training Mini131 benchmark, collect non-golden trajectories, train a next-action SFT adapter, optionally run bounded GRPO, and compare pre/post behavior without training on Mini131 questions or gold.

## 2. Background / Current Problem

The prompt-time Qwen3.5 policy, text retrieval, OCR/VLM tools and final answer path are executable. The remaining blocking runtime defect is explicit follow-up: the model has confused prior-answer citation IDs with current-episode tool handles. Two prompt-only repairs failed and were reverted. Training code does not yet exist. Mini131 has already been used repeatedly in historical evaluation and therefore is a historical benchmark/development-regression asset, not a new sealed holdout.

EvoHarness-RL motivates supervised harness action learning followed by cost-aware GRPO over policy-facing Belief/Progress/Experience state. This project adapts that sequence to RAG; it does not claim ALFWorld reproduction or paper hyperparameters.

## 3. In Scope

- episode-local typed handle namespaces and follow-up regression
- trajectory schema and private recorder/exporter
- hash-only Mini131 exclusion manifest and group/question/conversation/doc-pair leakage guards
- train/dev/sealed-holdout split freezer for new non-golden data
- next-action SFT dataset builder and isolated training entrypoint
- external reward contract and bounded GRPO environment/entrypoint
- pre/post benchmark runner receipts and policy adapter loading contract
- historical Mini131 PRE/POST paired comparison, with Mini131 excluded from training and tuning decisions
- frozen Experience snapshot per evaluation and rollout batch

## 4. Out of Scope

- changing Mini131 gold, qrels, questions, source anchors, judge rubric or old candidate transcripts
- using Mini131 answers, failures, paraphrases, same conversation groups or document-pair variants as training examples
- calling PRE Mini131 failure details a training curriculum
- full-model fine-tuning; default is PEFT/LoRA or QLoRA after measured feasibility
- upgrading the serving environment in place; training uses an isolated environment
- automatic private-data egress, external teacher models, unbounded GPU jobs, default UI rollout
- claiming sealed held-out results before tuning is frozen

## 5. Assumptions

- The application policy baseline remains Qwen3.5-9B for attribution. Training scripts accept a model path/ID so later challengers can be explicit experiments.
- Runtime serving remains on its current pinned MLX derivative; trainable weights use an HF-compatible checkpoint/adapter in an isolated Linux/CUDA training environment unless a separately verified backend is selected.
- Current TRL agent `environment_factory` support requires `transformers>=5.2.0`; the serving project currently pins `<5`, so one environment cannot satisfy both contracts safely.
- Mini131 can be rerun as a historical PRE/POST benchmark because it has already been exposed, but it is not a sealed holdout and must not steer training example selection.

## 6. Existing System Touchpoints

- `src/midprojectrag/evo_harness/state.py`: policy-visible BPE state and action wire
- `tools.py`, `visual.py`: scoped text/visual actions
- `policy.py`, `runner.py`: actual policy calls, trajectory capture, final answer
- `cli.py`: private output and owned-process limits
- `src/midprojectrag/evaluation.py`: existing group/question/conversation leakage rules
- Mini131 evaluation/baseline modules: historical benchmark only

## 7. Proposed Design

### 7.1 Typed evidence lifecycle

Policy-visible identifiers have disjoint namespaces:

- `hist:t<turn>:e<n>`: prior-turn citation reference; display/audit only, never valid tool input
- `cand:e<n>`: current-episode search candidate; valid for `read` or `inspect_image`
- `ev:e<n>`: current-episode successfully read/inspected evidence; valid for answered `finish`

Full canonical evidence IDs remain server-side in the RuntimeRequest, EvidenceStore, citations, audit records and final response. A policy action containing a canonical ID, `hist:*`, bare `e1`, document ID or path where `cand:*`/`ev:*` is required fails before tool execution. The namespace is type information, not an authority/receipt graph.

### 7.2 Trajectory record

Private `evo-policy-trajectory-v1` records include:

- `trajectory_id`, `case_id`, `group_id`, `split`, `question_sha256`, `request_sha256`
- model/profile/corpus/index/experience identities
- ordered policy steps: token-counted policy messages, parsed action, bounded observation, action outcome/error and usage
- terminal status and content-free quality/reward components
- no hidden chain-of-thought, qrels, reference answer, expected action sequence or semantic judge text

Raw question/source text stays in approved private storage. Public receipts contain only counts/hashes/metrics.

### 7.3 Exclusion and split freezer

A hash-only exclusion manifest is generated from all Mini131 cases and any existing evaluation groups before training collection. It stores normalized-question hashes, group hashes, conversation hashes and normalized multi-document-pair hashes. Training/dev candidates are rejected on any exact hash collision. Human review is still required for semantic paraphrase leakage.

New non-golden data is frozen into:

- `train`: trajectory generation and parameter updates
- `dev`: prompt/reward/hyperparameter/model selection
- `sealed_holdout`: created and hashed before tuning; run once after final configuration freeze

No group, normalized question, conversation or multi-document pair may cross splits. Sealed holdout cannot be relabelled from previously inspected Mini131 cases.

### 7.4 SFT dataset

SFT target is only the next valid action JSON. Use prompt-completion records so loss is computed on the completion/action, not observations or final answer. Successful direct trajectories and valid recovery trajectories may be included. Invalid/rejected actions can be retained as negative analysis metadata but are not positive action targets.

Minimum exported record:

```json
{"prompt":[{"role":"system","content":"<policy system>"},{"role":"user","content":"<state JSON>"}],"completion":[{"role":"assistant","content":"{\"tool\":...}"}],"metadata":{"trajectory_id":"...","step":2,"split":"train"}}
```

The builder rejects gold/evaluation-only keys recursively and rejects any case found in the exclusion manifest.

### 7.5 SFT training entrypoint

`train_harness_sft.py` runs only inside the isolated training environment. Initial default is PEFT LoRA/QLoRA, not full fine-tuning. Starting proposal: LoRA rank16/alpha32; actual target modules, quantization, batch size, sequence length and gradient settings must be preflighted on the selected hardware and recorded in a resolved config/receipt before a real run.

The serving MLX 4-bit conversion is not treated as a trainable checkpoint. Adapter output records base model revision, tokenizer/chat-template hash, dependency lock, dataset hashes and training config hash.

### 7.6 Reward contract

`evo-policy-reward-v1` components are external to policy self-reports:

- success gate: task/evidence/citation/valid-abstention success from deterministic or approved evaluator
- penalties: invalid action, repeated identical action, scope violation attempt, unsupported claim, timeout/budget exhaustion
- efficiency bonus: search/read/image/policy/token/time savings only when success gate is true

Early abstention without a valid abstention target cannot earn success. Policy-authored `commit(evidence_found)` is not reward evidence.

### 7.7 GRPO environment

Each rollout receives a fresh episode, immutable task, hard scope and one frozen Experience version. No state/cache leaks across rollouts. The environment exposes the same action semantics as runtime. Current TRL `environment_factory` support is used only in an isolated environment with compatible Transformers; alternatively a custom rollout adapter must preserve the same per-rollout isolation and reward contract.

Group size, max steps, reward weights, generation settings, vLLM mode and GPU/resource cap are versioned before launch. Start small; no paper-scale hardware assumption.

### 7.8 Evaluation sequence

1. Finish typed-handle repair and live follow-up regression.
2. Freeze implementation commit and benchmark configuration.
3. Run Mini131 PRE once for this experiment series. Store complete private results, but expose only aggregate/hashes to training orchestration.
4. Build non-golden exclusion-safe train/dev/sealed-holdout data and collect trajectories.
5. SFT; choose changes on non-golden dev only.
6. Optional bounded GRPO; choose changes on non-golden dev only.
7. Freeze final adapter/config/Experience.
8. Run Mini131 POST paired comparison as historical benchmark.
9. Run new sealed holdout once and report it separately as the untouched final estimate.

Mini131 PRE may be viewed for reporting and regression triage, but its per-case failures must not be used to create/select training questions, rewards, prompts or hyperparameters.

### 7.8.1 Paired Golden131 semantic benchmark

For the SFT experiment, the historical Mini131/Golden131 suite is the paired PRE/POST benchmark, not the model-selection gate. PRE and POST must bind the same 129 RAG case identities, parser-2 separation, source/config hashes, retrieval/runtime identities, semantic rubric and fixed GPT-5.6 Sol blind-judge contract; only the policy/adapter stage may differ. All 129 RAG assets remain in the denominator. A specialist lane that the candidate cannot execute is recorded as an explicit error/unsupported failure and is never dropped or promoted to abstention success. Semantic score, accepted/rejected, deterministic retrieval/citation metrics and runtime error are reported together. No PRE or POST per-case failure, judgment, rationale or gold delta may influence TRAIN/DEV examples, prompt changes, reward weights, hyperparameters or adapter selection; those decisions use non-golden DEV only. Parser regressions remain separate ETL PASS/FAIL and never enter the RAG semantic mean.

## 8. Contracts

### 8.1 Dataset / receipt files

Private artifacts:

- trajectory JSONL
- train/dev/heldout case JSONL
- SFT prompt-completion JSONL
- reward/rollout records
- adapter/checkpoints and resolved dependency lock
- PRE/POST candidate transcripts

Public/redacted artifacts:

- exclusion/split/data/config hashes and counts
- aggregate evaluation/reward/latency/tool-call metrics
- model/adapter identity and reproducibility receipt

### 8.2 Failure rules

- exclusion collision -> `training_case_evaluation_leakage`
- split collision -> `training_split_leakage`
- forbidden gold/evaluator key -> `training_gold_projection_forbidden`
- unpinned model/template/dataset -> preflight failure, no training
- serving-env Transformers/TRL conflict -> `isolated_training_environment_required`
- missing sealed holdout hash -> final holdout BLOCKED
- resource estimate beyond configured cap -> training BLOCKED, never silently reduce model/change model

## 9. Acceptance Criteria

1. Historical, candidate and read evidence cannot be confused syntactically; real Qwen follow-up performs current search/read/finish or safely terminates without using old citation IDs as current evidence.
2. Existing text/visual action, scope, citation and 120-second guards remain green.
3. Training data builder rejects Mini131 hash collisions and forbidden gold/evaluator fields before writing output.
4. Split freezer rejects group/question/conversation/doc-pair leakage and emits immutable hashes/order.
5. SFT/GRPO scripts support `--preflight`/dry configuration without importing training packages into serving runtime or installing/upgrading it.
6. Real training cannot start without model revision, dataset/split hashes, output directory, resource limits and isolated compatible dependency receipt.
7. PRE/POST runner binds exact runtime/model/retrieval/eval identities. Mini131 content is excluded from training.
8. Sealed holdout is a new non-golden split and is not run until final freeze.

## 10. Implementation Batches

### EVO35.3a - Training/evaluation pipeline skeleton

**Goal:** pure-Python schemas, exclusion/split freezer, SFT exporter, reward contract and preflight-only SFT/GRPO entrypoints.

**Expected files/modules:** `evo_harness/training.py`, `scripts/freeze_evo_training_data.py`, `scripts/train_harness_sft.py`, `scripts/train_harness_grpo.py`, training config templates/tests.

**Done when:** serving environment imports remain unchanged; synthetic leakage/preflight tests pass.

### EVO35.3b - Typed evidence protocol / follow-up repair

**Goal:** hist/cand/ev namespace at the policy boundary and a real-Qwen follow-up regression.

**Done when:** old IDs cannot dispatch; current candidates become read/inspect handles; only read evidence finishes; existing 378 impact checks plus namespace cases pass; bounded live follow-up no longer repeats historical IDs.

### EVO35.3c - Frozen Mini131 PRE

**Goal:** freeze commit and execute current learned=false policy against the historical Mini131 inventory using the new harness adapter; no tuning from results.

**Done when:** case inventory, unsupported lanes, model/tool/corpus/config hashes and aggregate metrics are complete; output explicitly labels historical benchmark, not sealed holdout.

### EVO35.3d - Non-golden collection and split freeze

**Goal:** generate/import new approved train/dev/heldout questions that do not collide with Mini131; collect action trajectories.

**Done when:** exclusion audit0 unresolved, split audit0 unresolved, trajectory/schema checks pass, sealed holdout hash recorded before tuning.

### EVO35.3e - SFT

**Goal:** train a bounded policy adapter and compare it with prompt-time base on non-golden dev.

**Done when:** resource/config/dependency receipts are frozen; adapter produced; dev action/task/efficiency metrics reported; no Mini131 selection feedback.

### EVO35.4 - GRPO

**Goal:** bounded cost-aware GRPO from the accepted SFT reference.

**Done when:** isolated rollout state, external reward and fixed Experience are verified; SFT vs GRPO dev comparison recorded.

### EVO35.5 - Final evaluation

**Goal:** freeze final candidate, run Mini131 POST historical comparison and one-time new sealed holdout.

**Done when:** fixed/harness-base/SFT/GRPO table reports quality, citation/abstention, invalid actions, tool calls, tokens, p50/p95, timeout and visual support separately.

## 11. Test Plan

- Unit: namespace parser, history projection, exclusion fingerprinting, recursive forbidden keys, split leakage, reward gating, configs/receipts.
- Integration: synthetic text, follow-up, visual and mixed episodes -> trajectory -> SFT export; no Controller calls.
- Live regression: exact prior failed Korean follow-up with Qwen3.5, bounded and private.
- Training preflight: incompatible serving environment must fail with no install; isolated compatible environment reports versions/model/device/resource plan.
- Evaluation: PRE/POST identity equality except adapter/policy stage; Mini131 IDs/hashes never appear in train/dev records.

## 12. Open Questions

No blocking product decision for EVO35.3a/b. Before a real SFT/GRPO run, the selected training machine/GPU and maximum wall-clock/storage budget must be measured and frozen. The relay may implement/preflight the pipeline but must not invent or exceed a resource budget.

## 13. Handoff / Relay Mode

Run ID: `evo35-train-20260909`. Mode: `solo`, explicitly requested. No external Coder/Critic. Collaboration/development model restrictions are removed for this solo relay, while the application experiment baseline remains Qwen3.5-9B unless a later explicit experiment contract changes it. Execute sequentially because 3b defines the action schema consumed by 3a exports and 3c baseline freeze. Relay continues after each published terminal batch until the next batch is blocked by a concrete resource/data prerequisite.
