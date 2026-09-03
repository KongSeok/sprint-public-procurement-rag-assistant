from copy import deepcopy
import unittest
from midprojectrag.evidence.builder import build_store
from midprojectrag.indexing.exact_index import ExactDenseIndex
from midprojectrag.retrieval.legacy_page import LegacyPageLane
from tests.test_evidence_builder import chunk
from tests.test_child_dense import FakeKure


class LegacyPageLaneTests(unittest.TestCase):
    def test_actual_legacy_index_stays_page_granularity_and_unchanged(self):
        rows = [chunk("alpha"), chunk("beta", block="block_" + "c" * 24)]
        original = deepcopy(rows)
        provider = FakeKure()
        index = ExactDenseIndex(rows, provider.embed([r["text"] for r in rows]).vectors, engine="numpy")
        lane = LegacyPageLane(index, build_store(rows), provider, artifact_sha256="a" * 64)
        result = lane.search("alpha", 2)
        self.assertEqual(len(result.candidates), 2)
        self.assertTrue(all(c.granularity == "page" for c in result.candidates))
        self.assertEqual(lane.store.get(result.candidates[0].evidence_id).source_chunk_ids, (rows[0]["chunk_id"],))
        before = len(provider.calls)
        self.assertEqual(lane.search("alpha", 2, allowed_doc_ids=frozenset()).candidates, ())
        self.assertEqual(before, len(provider.calls))
        self.assertEqual(rows, original)


if __name__ == "__main__":
    unittest.main()
