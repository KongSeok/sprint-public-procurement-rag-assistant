# HOTLINE.VISUAL.2 - Policy-selected OCR search and image inspection

Date: 2026-09-09. User: attach the imported visual path and test it. Solo implementation/review; no external agents.
Target: feat/hotline-runtime, starting bca3a64. D-027 imported code; this explicit follow-up authorizes the opt-in policy connection.

## Contract

Add opt-in `visual_search(query, doc_ids, limit)` (1..5 hits) and `inspect_image(evidence_id, question)` (one previously returned visual handle; question <=2000 chars). Existing seven actions and text-only defaults remain available and unchanged when visual capability is off. Policy selects the tools; do not hard-code an answer or mandatory visual action sequence.

The existing persisted OCR/layout KURE index supplies visual candidates. Pass document scope to VisualExactDenseIndex BEFORE ranking/top-k and repeat cheap returned-ID/scope checks at the adapter boundary. Unknown/empty/out-of-scope IDs cannot widen the episode scope. Unknown current handles fail before loading pixels or inference. OCR search does not become image reasoning.

Image inspection reuses the already loaded pinned Qwen3.5-9B MLX model and the imported pixel preparation/schema/uncertainty validator. Original PNG hash/page/bbox/occurrence are application-supplied citations. OCR text is not passed to the image model. No second 9B model, alternate model/server, new Controller, receipt authority or recursive history is introduced.

Use request-local candidates/read results. Successful visual interpretation may enter a clearly labelled `visual_inference` window only with `human_review_required=true`, `factual_evidence_promoted=false`, semantic_verified=false. Uncertain/abstained image results are not usable answer evidence. Final answer input and output must retain these flags and citations; a final wording pass must not upgrade the inference into verified source truth.

Shared budgets: policy <=12; text+visual search <=4; text read+image inspection <=4; image inference <=2; final answer <=1. All model/tool waits receive the actual remaining time; whole foreground episode includes initialization under the existing owned-process120-second supervisor. Do not inherit standalone visual QA's180-second timeout into an Evo episode. Cached duplicates consume policy attempts but do not dispatch models again; failed calls do not become empty cache successes. Preserve image-token/output usage and attempted-call accounting.

## Runtime

Reuse separate existing KURE Python/cache via a bounded, OS-network-denied child for query embedding/search; do not install Torch in the MLX environment. Parent MLX worker is also OS-network-denied for actual visual CLI runs. Public single-process injected providers are allowed only as explicit test/composition seams. Actual image inference shares the parent policy model. No arbitrary user filesystem path may be a model-selected action argument.

Expose explicit visual CLI configuration (index/private/crop roots, KURE Python/cache); allow `--visual-only` when no text artifact is loaded, with capability absence visible. With text artifacts, both branches are available to the same policy. Private outputs and diagnostic directories are new, no overwrite; existing corpus/crops/vectors/weights remain unchanged. No OCR rerun/re-index is necessary to query the already stored OCR index.

## Validation and bounded trial

Before model work: tests for scoped top-k/empty scope, handle lifetime, deadline expiry, duplicate reuse, failed-call consumption, model/schema/pixel proof, uncertainty not promoted, mixed text+visual citations, independent episodes, text default regression and CLI options. Then same-process original352 impact checks.

Actual trial: use existing pinned Qwen and OCR index/crop, no downloads/training/server mutation; each episode <=120seconds. One policy-selected live visual episode first, then at most a bounded second contrasting text/control or diagnosed repair test. Record exact actions, image tensor/token evidence, separate times and outcome. A one-occurrence index only proves integration, not ranking quality or corpus-wide OCR/VLM accuracy. Preserve failures. No SFT/GRPO, golden131, default UI switch, or unrelated follow-up repair.

## Delivery

Implement/tests/self-review, explicit results and updated TODO; selective commit/push on the already user-authorized hotline branch after checks. Do not call code-only or fake-model tests a real model success. The source VLM and other worktrees remain untouched.

## Review-label semantics clarified after live execution

The live model confused human_review_required with missing user input. This label qualifies a visual interpretation; it is not automatically a prohibition on returning one. A successful image result with usable_in_finish=true and no uncertainties may be cited as an explicitly unreviewed image reading. Uncertain/abstained results remain unusable and all original validation gates remain. No result status is coerced and no recognition text is corrected from OCR. One bounded same-input rerun tests this generic instruction clarification; the prior clarification-only result remains preserved.
