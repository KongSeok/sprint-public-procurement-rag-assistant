from __future__ import annotations

import unittest

from src.evaluation.offline_replay import summarize_integrated_results, validate_integrated_result


def valid_record():
    return {
        "query": "예산은?", "answer": "3억 원 [근거: doc.pdf]",
        "provider": "fake", "model": "fake", "abstained": False,
        "cited_doc_ids": ["doc.pdf"], "unsupported_citations": [],
        "evidence": [{"doc_id": "doc.pdf"}],
        "retrieval_config": {"method": "hybrid"},
    }


class OfflineReplayTest(unittest.TestCase):
    def test_valid_result(self):
        self.assertEqual(validate_integrated_result(valid_record()), [])

    def test_unsupported_citation_is_detected(self):
        record = valid_record()
        record["cited_doc_ids"] = ["other.pdf"]
        record["unsupported_citations"] = ["other.pdf"]
        self.assertIn("unsupported_citations_present", validate_integrated_result(record))

    def test_summary(self):
        summary = summarize_integrated_results([valid_record()])
        self.assertEqual(summary["valid"], 1)
        self.assertEqual(summary["answered_with_citation_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
