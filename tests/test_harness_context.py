import unittest
from midprojectrag.evidence.builder import SplitConfig, build_store
from midprojectrag.retrieval.contracts import Candidate
from midprojectrag.retrieval.context import expand_parents, select_context
from tests.test_evidence_builder import chunk


class HarnessContextTests(unittest.TestCase):
    def setUp(self):
        self.store = build_store([chunk("A" * 4000), chunk("other doc", block="block_" + "c" * 24, doc="doc_" + "d" * 24)])
        ordered = sorted(self.store.candidates(), key=lambda e: (e.doc_id, e.locator.char_range))
        self.candidates = tuple(Candidate(e.evidence_id, e.doc_id, 1.0, "rrf", i) for i, e in enumerate(ordered, 1))

    def test_bounded_parent_preserves_actual_child_and_locator(self):
        windows = expand_parents(self.candidates, self.store, max_chars=2000)
        for window in windows:
            self.assertLessEqual(len(window.text), 2000)
            parent = self.store.parent(window.parent_id)
            self.assertEqual(window.text, parent.text[slice(*window.char_range)])
            self.assertIn(self.store.get(window.child_evidence_id).text, window.text)
        self.assertTrue(any(w.parent_truncated for w in windows))

    def test_coverage_mandatory_and_character_budget(self):
        mandatory = self.candidates[1].evidence_id
        pack = select_context(self.candidates, self.store, final_k=2, max_per_doc=1, char_budget=2000,
                              mandatory_ids=(mandatory,), required_docs=self.store.doc_ids)
        self.assertIn(mandatory, pack.evidence_ids)
        self.assertEqual(pack.trace["post_distinct_docs"], 2)
        self.assertEqual(pack.trace["missing_required_docs"], ())
        self.assertLessEqual(pack.trace["used_chars"], 2000)
        self.assertFalse(pack.trace["parent_context_citable"])

    def test_impossible_mandatory_budget_is_explicit(self):
        mandatory = self.candidates[0].evidence_id
        pack = select_context(self.candidates, self.store, char_budget=10, mandatory_ids=(mandatory,))
        self.assertIn(mandatory, pack.trace["missing_mandatory_ids"])
        self.assertLessEqual(pack.trace["used_chars"], 10)


if __name__ == "__main__":
    unittest.main()
