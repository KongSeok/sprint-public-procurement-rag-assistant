# Retrieval boundary — Phase 1

Public DTOs: immutable `Candidate`, `SearchResult`, `ContextPack`, `ParentWindow`.
Lane `search(query,limit,allowed_doc_ids=None)` returns exact EvidenceStore IDs;
None means global, an empty frozenset means no encoder/tokenizer/lane call.

| Owner | Public API | Boundaries |
| --- | --- | --- |
| dense.py | KURE_IDENTITY, DenseChildLane, build_dense, load_dense | pinned revision/prompt/pooling/1024d; child-only ordered vectors; offline provider adapter |
| legacy_page.py | LegacyPageLane | previously validated ExactDenseIndex; source chunk→page evidence binding; page granularity only |
| kiwi_bm25.py | KiwiTokenizer, KiwiBM25Lane | actual Kiwi/model versions+dictionary file hashes; persisted tokens; corpus-wide fixed IDF, scope before score |
| fusion.py | fuse_rrf, HybridChildRetriever | independent budgets, same child bundle/granularity, k=60; lexical rescue/duplicates/docs trace |
| context.py | expand_parents, select_context | bounded original parent windows, only child evidence IDs are citable; missing mandatory/docs explicit |

No lane reads evaluator gold, required gold IDs, expected answers, or scores.
No source artifact is rewritten. Saved vector/token receipts bind source bundle,
row order and file hashes; loading performs validation before search. Query
token traces are private query data, never public log payloads.

KURE tests using FakeKure are synthetic and labeled as such. The explicit local
build script uses existing pinned weights and sets offline mode. New KURE child
vectors are computed from child text; legacy page vectors are not relabeled.
Kiwi uses 1 worker and standard dialect. Model initialization is explicit, not a
regex fallback. Real dependency/model absence produces an unavailable error.

Parent windows are context only, not additional citations or verified facts.
The later harness must act on missing slots/mandatory evidence instead of
treating a truncated context as a complete answer. Reranking and generation are EH4.
