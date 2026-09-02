"""Whole-evidence packing with hard budgets and explicit coverage retention."""
from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from midprojectrag.evidence import Evidence, EvidenceStore
from midprojectrag.retrieval.types import Candidate, positive_int, validate_candidates


def select_context(
    store: EvidenceStore,
    candidates: tuple[Candidate, ...],
    *,
    max_chars: int,
    max_items: int,
    per_doc_limit: int,
    required_ids: Sequence[str] = (),
) -> tuple[Evidence, ...]:
    """Preserve all mandatory refs, then fill round-robin across documents.

    max_chars counts exact evidence text characters; the generation adapter must
    additionally check its model-token and serialized prompt budget. Evidence is
    never truncated. Mandatory refs may have been verified in earlier rounds.
    """
    positive_int(max_chars, "invalid_context_max_chars")
    positive_int(max_items, "invalid_context_max_items")
    positive_int(per_doc_limit, "invalid_context_per_doc_limit")
    validate_candidates(candidates)
    if isinstance(required_ids, (str, bytes)) or not isinstance(required_ids, Sequence):
        raise ValueError("invalid_required_evidence_ids")
    required = []
    seen: set[str] = set()
    for evidence_id in required_ids:
        if not isinstance(evidence_id, str):
            raise ValueError("invalid_required_evidence_ids")
        evidence = store.get(evidence_id)
        if evidence_id not in seen:
            required.append(evidence)
            seen.add(evidence_id)
    # Validate every candidate before making a budget decision, even a candidate
    # which would otherwise never reach the packed context.
    optional_by_doc: dict[str, list[Evidence]] = {}
    # The supplied tuple is the current stage's ranking; a learned reranker may
    # retain original retrieval ranks as diagnostics while changing tuple order.
    for candidate in candidates:
        evidence = store.get(candidate.evidence_id)
        if evidence.evidence_id not in seen:
            optional_by_doc.setdefault(evidence.doc_id, []).append(evidence)
            seen.add(evidence.evidence_id)
    selected = list(required)
    char_count = sum(len(evidence.text) for evidence in required)
    doc_counts = Counter(evidence.doc_id for evidence in required)
    if (
        len(selected) > max_items
        or char_count > max_chars
        or any(count > per_doc_limit for count in doc_counts.values())
    ):
        raise ValueError("context_budget_exceeded")
    # A mandatory item has already supplied that document's first coverage
    # opportunity; prioritize documents without one before adding another.
    document_order = sorted(optional_by_doc, key=lambda doc_id: bool(doc_counts[doc_id]))
    cursors = {doc_id: 0 for doc_id in document_order}
    while len(selected) < max_items:
        made_progress = False
        for doc_id in document_order:
            if doc_counts[doc_id] >= per_doc_limit:
                continue
            rows = optional_by_doc[doc_id]
            while cursors[doc_id] < len(rows):
                evidence = rows[cursors[doc_id]]
                cursors[doc_id] += 1
                if char_count + len(evidence.text) > max_chars:
                    continue
                selected.append(evidence)
                char_count += len(evidence.text)
                doc_counts[doc_id] += 1
                made_progress = True
                break
            if len(selected) >= max_items:
                break
        if not made_progress:
            break
    return tuple(selected)
