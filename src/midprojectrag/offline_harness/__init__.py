"""Offline-only evaluation. Runtime modules must never import this package."""
from .scoring import SCORER_VERSION, AnswerScore, fact_matches, normalize_text, score_answer

__all__ = ["SCORER_VERSION", "AnswerScore", "fact_matches", "normalize_text", "score_answer"]
