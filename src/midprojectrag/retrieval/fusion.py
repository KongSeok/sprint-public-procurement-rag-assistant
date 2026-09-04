"""Same-child-unit reciprocal rank fusion with independent lane budgets."""
from dataclasses import dataclass
from hashlib import sha256
import json
from weakref import WeakKeyDictionary

from midprojectrag.evidence import EvidenceStore
from midprojectrag.runtime_integrity import ResolvedScope
from .contracts import Candidate, SearchResult


_HYBRID_PRODUCTION_BINDING = object()
_PRODUCTION_HYBRIDS: WeakKeyDictionary = WeakKeyDictionary()


def _digest(value) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def _row_hash(store: EvidenceStore) -> str:
    return _digest([row.evidence_id for row in store.candidates()])


@dataclass(frozen=True, slots=True, init=False)
class HybridProductionBinding:
    """Opaque binding for an exact, loader-attested production hybrid stack."""

    bundle_sha256: str
    rows_sha256: str
    dense_attestation_sha256: str
    lexical_attestation_sha256: str
    dense_artifact_sha256: str
    lexical_artifact_sha256: str
    fusion_config_sha256: str
    binding_sha256: str

    def __init__(self, payload: dict, *, _token=None):
        if _token is not _HYBRID_PRODUCTION_BINDING:
            raise TypeError("hybrid_production_binding_is_factory_sealed")
        expected = {
            "bundle_sha256", "rows_sha256", "dense_attestation_sha256",
            "lexical_attestation_sha256", "dense_artifact_sha256",
            "lexical_artifact_sha256", "fusion_config_sha256",
        }
        if type(payload) is not dict or set(payload) != expected or any(
            type(value) is not str
            or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)
            for value in payload.values()
        ):
            raise ValueError("invalid_hybrid_production_binding")
        for name, value in payload.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "binding_sha256", _digest(payload))


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

    @classmethod
    def from_loaded_artifacts(cls, store, dense, lexical):
        """Build a production retriever from loader-attested exact lane objects."""

        if cls is not HybridChildRetriever or type(store) is not EvidenceStore:
            raise ValueError("exact_hybrid_production_factory_required")
        from .dense import require_loaded_dense_artifact
        from .kiwi_bm25 import require_loaded_lexical_artifact

        dense_attestation = require_loaded_dense_artifact(dense, store, production=True)
        lexical_attestation = require_loaded_lexical_artifact(
            lexical, store, production=True
        )
        retriever = cls(store, dense, lexical)
        binding = HybridProductionBinding(
            {
                "bundle_sha256": store.bundle_sha256,
                "rows_sha256": _row_hash(store),
                "dense_attestation_sha256": dense_attestation.attestation_sha256,
                "lexical_attestation_sha256": lexical_attestation.attestation_sha256,
                "dense_artifact_sha256": dense.artifact_sha256,
                "lexical_artifact_sha256": lexical.artifact_sha256,
                "fusion_config_sha256": _digest(
                    {"algorithm": "reciprocal_rank_fusion", "rrf_k": 60}
                ),
            },
            _token=_HYBRID_PRODUCTION_BINDING,
        )
        _PRODUCTION_HYBRIDS[retriever] = binding
        return retriever

    @property
    def production_binding(self) -> HybridProductionBinding:
        return require_production_hybrid(self, self.store)

    def search(self, query, *, dense_k, lexical_k, scope: ResolvedScope):
        if self in _PRODUCTION_HYBRIDS:
            require_production_hybrid(self, self.store)
        if type(scope) is not ResolvedScope or any(type(k) is not int or k < 1 for k in (dense_k, lexical_k)):
            raise ValueError("invalid_hybrid_scope_or_budget")
        if scope.state == "empty":
            empty = SearchResult((), {"granularity": "child", "bundle_sha256": self.store.bundle_sha256,
                                      "empty_scope": True, "lane_calls": 0})
            return fuse_rrf(empty, empty, self.store)
        dense = self.dense.search(query, dense_k, allowed_doc_ids=scope.allowed_doc_ids)
        lexical = self.lexical.search(query, lexical_k, allowed_doc_ids=scope.allowed_doc_ids)
        return fuse_rrf(dense, lexical, self.store)


def require_production_hybrid(
    retriever: HybridChildRetriever, store: EvidenceStore
) -> HybridProductionBinding:
    """Revalidate a factory-issued binding immediately before production use."""

    if type(retriever) is not HybridChildRetriever or type(store) is not EvidenceStore:
        raise ValueError("hybrid_production_binding_required")
    binding = _PRODUCTION_HYBRIDS.get(retriever)
    if type(binding) is not HybridProductionBinding:
        raise ValueError("hybrid_production_binding_required")
    if retriever.store is not store or "search" in vars(retriever):
        raise ValueError("hybrid_production_runtime_drift")
    from .dense import require_loaded_dense_artifact
    from .kiwi_bm25 import require_loaded_lexical_artifact

    dense = require_loaded_dense_artifact(retriever.dense, store, production=True)
    lexical = require_loaded_lexical_artifact(retriever.lexical, store, production=True)
    checks = {
        "bundle_sha256": store.bundle_sha256,
        "rows_sha256": _row_hash(store),
        "dense_attestation_sha256": dense.attestation_sha256,
        "lexical_attestation_sha256": lexical.attestation_sha256,
        "dense_artifact_sha256": retriever.dense.artifact_sha256,
        "lexical_artifact_sha256": retriever.lexical.artifact_sha256,
        "fusion_config_sha256": _digest(
            {"algorithm": "reciprocal_rank_fusion", "rrf_k": 60}
        ),
    }
    if any(getattr(binding, name) != value for name, value in checks.items()):
        raise ValueError("hybrid_production_binding_drift")
    return binding
