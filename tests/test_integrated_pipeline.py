from __future__ import annotations

import unittest
from dataclasses import dataclass

from src.integrated_pipeline import IntegratedRAGPipeline


@dataclass
class Hit:
    chunk_id: str = "doc.pdf::child::1"
    doc_id: str = "doc.pdf"
    text: str = "사업 예산은 3억 원이다."
    metadata: dict = None
    score: float = 0.9
    matched_by: str = "hybrid"

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {"사업_금액": 300_000_000, "발주_기관": "서울특별시"}


class FakeIndex:
    def __init__(self, hits):
        self.hits = hits
        self.kwargs = None

    def hybrid_search(self, query, **kwargs):
        self.kwargs = kwargs
        meta_filter = kwargs.get("meta_filter")
        return [hit for hit in self.hits if meta_filter is None or meta_filter(hit.metadata)]


class FakeGenerator:
    provider = "fake"
    model = "fake-model"

    def generate(self, query, context):
        return "사업 예산은 3억 원입니다.\n[근거: doc.pdf]"


class IntegratedPipelineTest(unittest.TestCase):
    def test_answer_connects_retrieval_generation_and_evidence(self):
        index = FakeIndex([Hit()])
        result = IntegratedRAGPipeline(index, FakeGenerator()).answer("예산 3억 이상인 지자체 사업")

        self.assertEqual(result.cited_doc_ids, ("doc.pdf",))
        self.assertEqual(result.unsupported_citations, ())
        self.assertEqual(result.evidence[0].doc_id, "doc.pdf")
        self.assertTrue(result.evidence[0].evidence_id.startswith("ev_"))
        self.assertTrue(index.kwargs["expand_to_parent"])

    def test_no_hit_abstains_without_generation(self):
        result = IntegratedRAGPipeline(FakeIndex([]), FakeGenerator()).answer("없는 내용")
        self.assertTrue(result.abstained)
        self.assertEqual(result.evidence, ())


if __name__ == "__main__":
    unittest.main()
