"""Immutable, source-bound evidence for the opt-in evidence harness."""

from .model import Evidence, EvidenceStore
from .builder import build_from_chunks

__all__ = ["Evidence", "EvidenceStore", "build_from_chunks"]
