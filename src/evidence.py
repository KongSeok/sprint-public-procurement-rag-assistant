"""검색 결과를 재현 가능한 근거 레코드로 변환한다."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    chunk_id: str
    doc_id: str
    text: str
    score: float
    matched_by: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _evidence_id(chunk_id: str, text: str) -> str:
    digest = hashlib.sha256(f"{chunk_id}\0{text}".encode("utf-8")).hexdigest()[:24]
    return f"ev_{digest}"


def build_evidence_records(hits: Iterable[Any]) -> tuple[EvidenceRecord, ...]:
    return tuple(
        EvidenceRecord(
            evidence_id=_evidence_id(hit.chunk_id, hit.text),
            chunk_id=hit.chunk_id,
            doc_id=hit.doc_id,
            text=hit.text,
            score=float(hit.score),
            matched_by=hit.matched_by,
            metadata=dict(hit.metadata),
        )
        for hit in hits
    )
