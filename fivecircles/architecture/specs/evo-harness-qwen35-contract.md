# EvoHarness on Hotline - Qwen3.5-9B v1

Contract ID: `evo-hotline-qwen35-v1`
Decision: D-026, explicit user direction on 2026-09-09.
Target branch: `feat/hotline-runtime`; inspected base: `2be2f4619b67bae89b6e2d522f42e9bb19ec9f95`.
Status: EVO35.1_IMPLEMENTED_SCOPED_TESTED / EVO35.2_BLOCKED_TOOL_PREFLIGHT. This contract is not live-model or training evidence.

## 1. Goal and authority

Keep the fixed hotline as the execution substrate. Add an LLM policy that selects real search/read/finish and Belief/Progress/Experience actions. Use **Qwen/Qwen3.5-9B** for both the new policy and new final-answer profile. Do not rebuild the retired recursive Controller. This is a RAG adaptation of EvoHarness ideas, not a reproduction of the paper's ALFWorld result.

The accepted design changes the application model from the proposed Qwen3-8B to Qwen3.5-9B. The user's subsequent explicit instruction changes this relay to solo: no Coder/Critic calls. Resolve conflicts through `agent/authority.md`. D-025's hotline-first direction remains active.

## 2. Research basis and deliberate adaptations

- Primary paper: https://arxiv.org/html/2608.05446v1, sections 2.1-2.4 and appendix 9. BPE state is external; the policy selects environment and harness actions. SFT precedes cost-aware GRPO.
- Official model: https://huggingface.co/Qwen/Qwen3.5-9B, post-trained model; non-thinking mode must be requested through the actual chat template/API, not the unsupported `/nothink` shortcut.
- Our `search/read/finish` tools replace ALFWorld environment actions. `track/commit/recall/note` retain their functional roles. Our single-JSON action wire, budgets and RAG reward definition are project adaptations, not claims about the paper.
- ALFWorld results and the paper's large training configuration are not RFP performance or single-L4 feasibility evidence.

## 3. Scope

Current implementation delivery: extract reusable hotline search/read/answer adapters; multi-evidence context; light BPE state; a real prompt-time policy adapter; bounded episode runner; model-free regression and an explicitly preflighted local model smoke when available. First functional acceptance is a two-document comparison that revisits only the missing field, plus ordinary fact/follow-up/abstention cases.

Future stages under this same design: policy-trajectory data, isolated SFT, reduced GRPO, frozen experience consolidation and fair evaluation. Real training requires a frozen split, environment/weights and explicit resource budget before dispatch; no unbounded GPU run is implied by this design.

Out of current scope: replacing shared VM/model servers, modifying other worktrees, re-embedding or corpus edits, changing frozen Mini131 assets, automatic cloud fallback, visual understanding without a supported tool, full UI rollout, new execution-authority frameworks, and runtime self-modifying code.

## 4. Model identity and runtime

| Field | Contract |
|---|---|
| Canonical policy model | `Qwen/Qwen3.5-9B` (post-trained; not `Qwen3.5-9B-Base`) |
| New final-answer model | Same canonical Qwen3.5-9B family |
| Local Mac derivative candidate | `mlx-community/Qwen3.5-9B-4bit`, explicitly labelled as a converted/quantized artifact |
| Existing derivative revision reference | `8b2b98c00a6b4d291155e4890773ca8f769aee53`, from the separate qwen35 experiment record; revalidate files before reuse |
| Canonical checkpoint revision | Resolve and record before real loading; unknown is not `main` and not a fabricated hash |
| Mode | Text-only, `enable_thinking=false`; test the actual backend/template behavior |
| Sampling | Initial controlled experiment temperature 0, seed 0 where supported; report unsupported seed controls |
| Model selection | No silent 8B, 27B, Base-model, third-party endpoint or CPU substitution |

Record checkpoint/derivative revision, tokenizer/template identity, precision, backend/version and device once per loaded profile/run. Exact template counting includes system instructions, tools, history, observations and generation reserve. A missing tokenizer or unsupported mode is a capability error, not an estimated successful count. Preserve the existing fixed hotline's historical Qwen3.8 profile and records; create a separate Qwen3.5 fixed-control profile for fair comparison.

Policy and final generation are separate logical clients and budgets. They may share one loaded backend sequentially. Do not mutate the one-POST historical transport to make it silently permit policy calls. No install, server replacement or model download is automatic.

## 5. Architecture and file ownership

`request -> episode -> Qwen3.5 policy -> bounded dispatcher -> hotline tools/BPE -> observation -> policy -> finish -> final generator -> response/citations`

Proposed small package: `src/midprojectrag/evo_harness/{state,tools,policy,runner,experience}.py`, a thin `__init__.py`, and at most one runtime/profile composition file if necessary. Put new configuration under `configs/rag/`. Reuse existing runtime request/evidence types and public retrieval APIs. Do not call retired `issue_harness_execution`, `decide_controller_action`, step claims, execution ledgers or retained-transition readers. Importing shared public retrieval code is not equivalent to executing the old Controller.

Keep `midprojectrag.hotline` behavior reproducible as the fixed control. Add only additive extraction seams needed by tool reuse. If changing an existing public API is unavoidable, return a QUESTION before changing its contract. Do not recreate an entire retrieval stack inside the policy package.

## 6. Runtime DTOs and tool wire

The existing allowlisted RuntimeRequest owns the user's question, explicit history and hard document scope. Gold/qrels/expected answers never enter the policy, tools or generator.

Each policy response is exactly one JSON object: `{"tool":"search","arguments":{...}}`. Reject duplicate JSON keys, unknown keys/tools, multiple actions, non-finite values and invalid shapes. Errors consume the attempt budget and return bounded content-free feedback. No repair by silently converting malformed output into success.

| Tool | Required arguments | Result and rules |
|---|---|---|
| `search` | `query`: nonempty string <=2000 chars; `doc_ids`: null or unique ID array; `limit`: integer 1..10 | One dense+lexical+RRF operation. Return ordered IDs, doc IDs, locators and bounded excerpts. Empty explicit scope stays empty; unknown/out-of-scope IDs are rejected before retrieval. |
| `read` | `evidence_ids`: unique array of 1..6 IDs | Only candidates already found in this episode. Return bounded parent windows with exact source span and document provenance; maintain a read-evidence registry. |
| `track` | `target`: `world` or an existing episode document/goal identifier | Bounded view of observed evidence and search history; no model call. |
| `commit` | `goal_id`: <=128 chars; `summary`: <=300 chars; `status`: open/working/evidence_found/blocked; `evidence_ids`: unique array | Progress update, at most 12 goals. Evidence references must be known. Policy claims are not semantic verification, permission or gold. |
| `recall` | `query`: <=1000 chars; `limit`: integer 1..3 | Read from the episode's fixed reviewed experience snapshot. Empty bank returns no hints, not an error. |
| `note` | `insight`: <=500 chars | Append to a bounded private episode buffer, at most 8 notes. Never publish to the skill bank during an episode or evaluation. |
| `finish` | `status`: answered/abstained/needs_clarification; `evidence_ids`: unique array of 0..6 IDs; `unresolved`: bounded string array | `answered` requires at least one read-evidence ID. Other statuses require no fact generation. Mark semantic validation unavailable unless independently performed. |

Do not expose dense, lexical and fusion as mandatory separate LLM turns. The first stage learns which search/query/scope is useful, not the routine internals of every retrieval call. Model-selected doc IDs can narrow hard scope, never widen it. With unrestricted user scope, only catalog-known IDs are allowed.

## 7. State, context and citations

Belief stores tool observations and references, not hidden evaluator facts. Progress stores policy-authored work notes. Experience is a reviewed versioned store read consistently within an episode/rollout batch. No exact-object authority token, closure pin, predecessor recursion or rehashed whole execution graph is introduced.

Read windows must retain the cited child and its exact location. Deduplicate repeated parent ranges without dropping required documents silently. The final packet maps S1..Sn to actual read windows, source IDs and locators. Validate citation membership and response shape; do not attach an expanded-parent-only claim to a smaller child's locator. Preserve locators for the text actually supplied. Unsupported source provenance yields a bounded error/partial result, not invented pages.

Pack whole evidence windows against the actual tokenizer. If some requested evidence does not fit, return the omitted IDs and token budget observation to the policy or terminate with an explicit context-budget reason. Do not silently trim away a document and claim complete comparison. History remains explicit; follow-up scope uses verified prior citations intersected with current user scope. No hidden server session or unverified prior IDs.

Retrieved text and recalled notes are untrusted data, not system instructions or authorizations. Restrict notes/experience to approved private storage. Experience filters cannot be treated as proof of non-leakage: promotion requires review and train/eval separation.

## 8. Budgets, repeat behavior and errors

Initial project settings, not paper hyperparameters:

- At most 12 policy attempts, including invalid outputs and BPE calls; at most 4 search dispatches and 4 read dispatches; at most 1 final generation attempt.
- Stop after 2 invalid actions. No automatic HTTP/model retry. If a timeout or incomplete response occurs, consume the attempted call and preserve the error.
- Policy output maximum 256 tokens, total policy template+input+output cap 4096; answer input+output cap 8192 with output reserve 1024. These are starting budgets, not evidence that all questions fit.
- Total worker budget at most 120 seconds using the existing owned-process supervisor pattern; check remaining time before and after each external action and cap each transport timeout. Report setup, policy, tools and answer time separately.
- Identical successful search/read requests may reuse request-local results keyed by all behavior-affecting inputs plus scope, corpus/index/profile identity. Repeated calls still consume a policy attempt and record a duplicate. Errors are not cached as empty success.
- Emit answered, abstained, needs_clarification, timeout, budget_exhausted, invalid_action_limit, unsupported or error distinctly. No forced success on budget exhaustion.
- State is isolated per episode. A deterministic fixed-control runner uses the same tools and Qwen3.5 final generator without policy calls for comparison.

## 9. Training and evaluation boundary

Start with actual prompt-time model selection, not a newly expanded rule-based E1. Add SFT only after valid trajectories exist; label scripted policies as test doubles. SFT targets next tool+arguments, not gold answer memorization or inaccessible/private chain-of-thought. Keep assistant action loss separate from tool messages and final-answer generation.

Use separately frozen training/development/held-out groups and reviewed experience snapshots. Mini131 and paraphrases of its held-out facts cannot be copied into training and then reported as untouched evaluation. Do not turn previously used development data into a new sealed holdout.

GRPO requires independent episode state and a fixed experience bank within each rollout batch. External task/citation/abstention success gates efficiency reward; early unwarranted abstention does not earn success. Unsupported semantic judgment is not replaced by lexical scores and called semantic PASS. Reward coefficients, group size, hardware/runtime budget and rollout limits must be versioned before real training. LoRA/QLoRA feasibility on the selected backend is measured, never assumed from the old AWQ/MLX inference profile.

Compare: historical hotline; improved fixed Qwen3.5 control; same tools + prompt policy; +SFT; +GRPO. Freeze generator/retrieval/data when attributing policy gains. Report quality, citation/abstention errors, policy and generation tokens, tool calls, p50/p95, memory and timeouts separately. Preserve full evaluation inventory and explicit unsupported visual/list/analytics cases.

## 10. Acceptance and validation

1. The new profile names Qwen3.5-9B for both roles; missing model identity fails before inference; old profile is unchanged.
2. Two synthetic episodes with different observations cause different next actions without a hard-coded dense/lexical/fusion action schedule.
3. A two-document missing-field scenario searches only the unresolved field/document; scope escape, unknown/read-before-search evidence and unsupported filters fail before external calls.
4. Search/read use real public hotline components with synthetic fixtures. A call trace confirms zero retired Controller execution/decision/history-reader entry calls.
5. Fact, comparison, explicit follow-up and abstention/clarification behaviors are tested. Test labels are never runtime features.
6. Strict action/result shapes, context limits, citations, duplicate suppression, note quarantine, immutable experience and cross-episode isolation are tested.
7. Timeout, failure consumption, invalid-action limit, final-generation count and token accounting cover policy plus answer paths. No model downloads/network occur in unit tests.
8. A real Qwen3.5 action-sequence smoke is a separate acceptance item after model/backend/artifact/device preflight. Synthetic PASS does not satisfy it.
9. Same-candidate solo code review and applicable regression precede integration (explicit user solo authorization; no independent-review claim). End-to-end quality/training completion require their own evidence.

## 11. Ordered delivery batches

- **EVO35.1 / HOTLINE.3:** toolize search/read/answer, multi-evidence packet, BPE, real policy adapter and bounded loop; model-free tests first. Common delivery cycle for tool extraction and prompt-time policy.
- **EVO35.2:** bind exact local Qwen3.5 profile and perform bounded synthetic-document live-model smoke; then approved private representative questions. Missing runtime is BLOCKED, not fallback.
- **EVO35.3:** freeze a separate trajectory dataset and isolated SFT environment; implement/train within measured resource budget.
- **EVO35.4:** small GRPO and reviewed experience consolidation; compare with the SFT reference.
- **EVO35.5 / HOTLINE.4:** support-matrix evaluation and application/UI integration. Unsupported specialist features stay explicit.

## 12. Relay handoff

Mode: **solo**, explicitly requested by the user on 2026-09-09. The current assistant performs implementation, tests and review without external Coder/Critic calls. Run `evo35-hotline-20260909`, batch `EVO35.1`. Previous blocked delegation is retained in the historical probe record, not an implementation prerequisite.

## 13. Adapter clarification before implementation

- Tool search uses the existing public `HybridChildRetriever.search` and `ResolvedScope`, without creating Controller obligations or receipts. Read uses public EvidenceStore lookup and validates returned text/source boundaries. Existing retriever checks stay enabled.
- Explicit follow-up is selected by `prior_citation_state` or an explicit runner input, not a speculative string heuristic; latest assistant citation IDs are resolved against the store and intersected with hard scope. Missing/invalid prior evidence produces clarification, not a global search.
- Canonical full evidence IDs remain in server state/output; short episode-local handles may be used in model observations/actions and resolved before tools run. They are not authority tokens and have no cross-episode meaning.
- Unknown metadata filters or runtime options fail as unsupported rather than being silently ignored. Full policy inputs are recounted before every call; overflow is explicit and never hides selected evidence.
- Real local-model smoke is a separately recorded EVO35.2 cycle with synthetic documents only and the existing <=120-second worker budget. No private corpus inference, downloads or environment upgrades in EVO35.1.
