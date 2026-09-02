# Local harness live routing / call budget

## Symptom and evidence

- A manually chosen, non-golden, history-dependent two-attribute request was planned as `list`.
  The first run scanned four batches before one enumeration provider call failed. Its private trace
  preserves failure; the old logger did not retain the underlying exception class, so its exact cause is unknown.
- After the planner definition was clarified, the same request produced two fact slots. Both KURE
  query embeddings completed (cold ~5.37s, warm ~0.06s), but verify ended at ~30.006s with a provider error.
  This is consistent with the configured 30-second local HTTP timeout, not a retrieval miss.

## Changes

- List means exhaustive matching DOCUMENT/PROJECT membership, not several attributes of one object.
  The semantic route remains model-selected; no regex answer judge or per-question code override was added.
- Controller keeps actual verify input IDs before dispatch, including failures.
- Exact same-source page/child text is deduplicated before verifier dispatch; distinct source provenance remains.
- CLI call budget is explicit, default 60s within the unchanged overall request ceiling. The 300s
  corpus smoke uses no automatic retry. Each manually diagnosed retry has a new private file.
- Private calls record safe exception/cause class and elapsed time; no raw provider error is exposed publicly.
- With 60s calls, both verifications completed (~48s and ~56s) and the harness reached READY,
  but final generation failed. The six-record pack contained one verified page plus five optional records.
  The CLI now packs only verified mandatory evidence; in this receipt that is one 861-character page.
  The old generation logger did not retain an exception cause, so the generation failure is not
  conclusively labelled a timeout. Updated generation logging preserves safe exception class and timing.

## Verification

Synthetic controller/LLM/trajectory tests pass. Live retry outcomes are recorded in the
[nonvisual report](../../../work/evidence-harness-report.html); this log does not claim a gold score.

Final same-request retry: answered with one mandatory page and one citation. Harness 5 actions,
two verifier calls ~53.4s/~58.4s, generation ~8.0s. Trace SHA-256
`6c9827def5955e46c53463165c326aa1991487f4b8f70bf46cdec9f255a4cdeb`.
The two requested attributes are present in the final answer; no semantic score was assigned.
This successful retry does not establish causal improvement or general reliability; settings changed
and live latency is variable. The slow verifier is an explicit follow-up measurement/optimization target.

## Prevention

Use history-dependent multi-attribute and true exhaustive-list smoke cases before calling the
planner production-ready. Record routing, query embedding, verification, generation and budget
failures separately. A syntactically valid plan is not semantic correctness.
