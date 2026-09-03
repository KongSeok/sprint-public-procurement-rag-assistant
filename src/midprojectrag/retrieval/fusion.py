"""Same-child-unit reciprocal rank fusion with independent lane budgets."""
from midprojectrag.evidence import EvidenceStore
from midprojectrag.runtime_integrity import ResolvedScope
from .contracts import Candidate, SearchResult


def fuse_rrf(dense: SearchResult, lexical: SearchResult, store: EvidenceStore, *, rrf_k=60) -> SearchResult:
    if type(rrf_k) is not int or rrf_k != 60:
        raise ValueError("rrf_constant_not_pinned")
    scores, docs, sets = {}, {}, []
    for result, lane in ((dense, "dense"), (lexical, "lexical")):
        if result.trace.get("granularity") != "child" or result.trace.get("bundle_sha256") != store.bundle_sha256:
            raise ValueError("fusion_lane_artifact_or_granularity_mismatch")
        ids = set()
        for position, c in enumerate(result.candidates, 1):
            e = store.get(c.evidence_id)
            if c.lane != lane or c.granularity != "child" or c.rank != position or e.kind != "text" or e.doc_id != c.doc_id:
                raise ValueError("fusion_candidate_contract_mismatch")
            scores[c.evidence_id] = scores.get(c.evidence_id, 0) + 1 / (rrf_k + position)
            docs[c.evidence_id] = c.doc_id
            ids.add(c.evidence_id)
        sets.append(ids)
    a, b = sets
    ordered = sorted(scores, key=lambda identity: (-scores[identity], identity))
    candidates = tuple(Candidate(identity, docs[identity], scores[identity], "rrf", rank)
                       for rank, identity in enumerate(ordered, 1))
    return SearchResult(candidates, {"lane": "rrf", "rrf_k": rrf_k, "granularity": "child",
        "bundle_sha256": store.bundle_sha256, "dense_only": sorted(a-b), "lexical_only": sorted(b-a),
        "both": sorted(a & b), "duplicate_count": len(a & b), "distinct_doc_count": len(set(docs.values())),
        "dense": dense.to_dict()["trace"], "lexical": lexical.to_dict()["trace"]})


class HybridChildRetriever:
    def __init__(self, store, dense, lexical):
        self.store, self.dense, self.lexical = store, dense, lexical

    def search(self, query, *, dense_k, lexical_k, scope: ResolvedScope):
        if type(scope) is not ResolvedScope or any(type(k) is not int or k < 1 for k in (dense_k, lexical_k)):
            raise ValueError("invalid_hybrid_scope_or_budget")
        if scope.state == "empty":
            empty = SearchResult((), {"granularity": "child", "bundle_sha256": self.store.bundle_sha256,
                                      "empty_scope": True, "lane_calls": 0})
            return fuse_rrf(empty, empty, self.store)
        dense = self.dense.search(query, dense_k, allowed_doc_ids=scope.allowed_doc_ids)
        lexical = self.lexical.search(query, lexical_k, allowed_doc_ids=scope.allowed_doc_ids)
        return fuse_rrf(dense, lexical, self.store)
