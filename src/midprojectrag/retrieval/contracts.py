from dataclasses import dataclass
import json
import math
from types import MappingProxyType
from typing import Mapping


class RetrievalProviderError(RuntimeError):
    """Sanitized marker raised only around actual retriever provider I/O."""


class RetrievalPostCallContractError(ValueError):
    """Sanitized marker for a contract failure after provider I/O returned."""


def freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(v) for v in value)
    return value


def thaw(value):
    if isinstance(value, Mapping):
        return {k: thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [thaw(v) for v in value]
    return value


@dataclass(frozen=True, slots=True)
class Candidate:
    evidence_id: str
    doc_id: str
    score: float
    lane: str
    rank: int
    granularity: str = "child"

    def __post_init__(self):
        if any(type(v) is not str or not v for v in (self.evidence_id, self.doc_id, self.lane)):
            raise ValueError("invalid_candidate_identity")
        if type(self.score) not in (float, int) or not math.isfinite(self.score):
            raise ValueError("invalid_candidate_score")
        if type(self.rank) is not int or self.rank < 1 or self.granularity not in {"child", "page"}:
            raise ValueError("invalid_candidate_rank_or_granularity")

    def to_dict(self):
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class SearchResult:
    candidates: tuple[Candidate, ...]
    trace: Mapping

    def __post_init__(self):
        values = tuple(self.candidates)
        if any(type(v) is not Candidate for v in values):
            raise TypeError("invalid_search_candidate")
        if len({c.evidence_id for c in values}) != len(values):
            raise ValueError("duplicate_search_candidate")
        object.__setattr__(self, "candidates", values)
        canonical = json.loads(json.dumps(thaw(self.trace), allow_nan=False))
        object.__setattr__(self, "trace", freeze(canonical))

    def to_dict(self):
        return {"candidates": [c.to_dict() for c in self.candidates], "trace": thaw(self.trace)}


def validate_search(query, limit, allowed_doc_ids):
    if type(query) is not str or not query.strip() or type(limit) is not int or limit < 1:
        raise ValueError("invalid_search_request")
    if allowed_doc_ids is not None and (type(allowed_doc_ids) is not frozenset
            or any(type(d) is not str or not d for d in allowed_doc_ids)):
        raise ValueError("invalid_search_scope")
