"""Read-only page control adapter. Never fuse its page IDs as child IDs."""
from midprojectrag.evidence import EvidenceStore
from .contracts import Candidate, SearchResult, validate_search
from .dense import _provider_identity, normalize


class LegacyPageLane:
    def __init__(self, index, store: EvidenceStore, provider, *, artifact_sha256: str):
        _provider_identity(provider)
        if index.dimensions != 1024 or len(artifact_sha256) != 64:
            raise ValueError("legacy_index_identity_mismatch")
        mapping = {}
        for page in store.candidates(kinds=("page",)):
            if len(page.source_chunk_ids) != 1 or page.source_chunk_ids[0] in mapping:
                raise ValueError("ambiguous_legacy_page_mapping")
            mapping[page.source_chunk_ids[0]] = page
        for row in index.chunks:
            page = mapping.get(row["chunk_id"])
            if page is None or (page.doc_id, page.content_sha256, page.source_block_ids) != (
                row["doc_id"], row["content_sha256"], tuple(row["source_block_ids"])
            ):
                raise ValueError("legacy_source_evidence_mismatch")
        self.index, self.store, self.provider = index, store, provider
        self._mapping, self.artifact_sha256 = mapping, artifact_sha256

    def search(self, query: str, limit: int, *, allowed_doc_ids=None):
        validate_search(query, limit, allowed_doc_ids)
        trace = {"lane": "legacy_page", "granularity": "page", "artifact_sha256": self.artifact_sha256,
                 "bundle_sha256": self.store.bundle_sha256, "profile": "legacy_page_control"}
        if allowed_doc_ids is not None and not any(r["doc_id"] in allowed_doc_ids for r in self.index.chunks):
            return SearchResult((), trace | {"encoder_calls": 0, "empty_scope": True})
        query_vector = normalize(self.provider.embed([query]).vectors, 1)[0]
        hits = self.index.search(query_vector, top_k=limit, allowed_doc_ids=allowed_doc_ids)
        return SearchResult(tuple(Candidate(self._mapping[h.chunk["chunk_id"]].evidence_id, h.chunk["doc_id"],
                                             h.score, "legacy_page", rank, "page")
                                  for rank, h in enumerate(hits, 1)), trace | {"encoder_calls": 1})
