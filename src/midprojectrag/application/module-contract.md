# Application Module Contract

- `application` is the only RAG-facing dependency allowed from interactive UI code.
- It owns versioned runtime-bundle validation, composition, request construction and private catalog joins.
- `answering` and `indexing` remain provider-neutral; concrete OpenAI construction occurs only in `composition.py`.
- Every query requires an explicit per-call external-corpus egress approval.
- Retrieval-manifest and display-catalog hashes are separate. Metadata-only catalog swaps do not imply re-embedding.
- A bundle mismatch fails before provider construction; the UI never rebuilds an index automatically.
- Questions, prompts, answers and source text are not persisted or sent to observability by this module.
