Timestamp: 2026-09-04 15:32 KST
Context: EH2.6.b2 execution config/runtime authority implementation and independent review

Issues
1) Root/fusion/dense/lexical validation entrypoints trusted mutable checker aliases or defaults. A self-consistent copied namespace or coordinated alias replacement could run a replacement before rejection.
2) Runtime, dense, lexical, and hybrid authority registries dereferenced weak references or attributes before exact entry type/shape validation.
3) Runtime binding construction/serialization did not initially seal every internal class method and public entrypoint before dispatch.
4) Evidence-store snapshot validation and lane preflights were pinned only at their outer callable, leaving transitive helpers, class descriptors, registries, and module attributes mutable before traversal.
5) One ad-hoc inspection command omitted `PYTHONPATH=src` and raised `ModuleNotFoundError`; the same read-only command succeeded immediately with the repository runtime convention.

Resolution
- Added factory-issued immutable `HarnessExecutionConfig` and exact production/synthetic `HarnessRuntimeBinding` authority.
- Added call-site anchors for checker identity/code/globals/defaults and fail-closed copied-namespace/coordinated-replacement checks.
- Pinned the complete evidence/dense/lexical/fusion/root callable, class/descriptor, module-attribute, registry, backing-store, and entry surfaces before traversal or weakref dereference.
- Routed runtime bind/validate/serialize/test factory through the same root gate and used issued aliases only after validation.
- Added armed zero-call regressions for every independently reported P1 category.

Verification
- Focused EH2.6.b2/evidence/retrieval suite: 104/104 PASS.
- Full unittest discovery: 1,109/1,109 PASS.
- Repository safety: 811 files PASS; py_compile and diff-check PASS.
- Independent final re-review: PASS after the coordinated dense checker replacement was rejected with zero armed calls.
- API, Langfuse, retriever, tokenizer, model/provider, verifier, reranker, and clock calls during bind/validate: 0.

Prevention
- A validator is not a safe boundary merely because its outer function is pinned. Authenticate its first dispatch and complete reachable dependency/registry surface before touching untrusted state.
- Registry identity is insufficient: validate exact entry container/authority type and `ReferenceType` before dereferencing.
- Keep coordinated multi-alias/default replacement regressions alongside single-name monkeypatch tests.
