from pathlib import Path
import tempfile
import unittest
from midprojectrag.evidence.builder import build_store
from midprojectrag.retrieval.kiwi_bm25 import KiwiBM25Lane, KiwiTokenizer
from tests.test_evidence_builder import chunk


class FakeTokens:
    identity = {"engine": "synthetic", "version": "1"}

    def tokenize(self, text):
        return tuple(text.lower().split())


class KiwiBM25Tests(unittest.TestCase):
    def test_independent_scope_tie_and_persistence(self):
        store = build_store([chunk("alpha common"), chunk("rescue common", block="block_" + "c" * 24, doc="doc_" + "d" * 24)])
        lane = KiwiBM25Lane.build(store, FakeTokens())
        hit = lane.search("rescue", 1)
        self.assertEqual(store.get(hit.candidates[0].evidence_id).text, "rescue common")
        self.assertEqual(hit.trace["query_tokens"], ("rescue",))
        self.assertEqual(lane.search("rescue", 1, allowed_doc_ids=frozenset({"doc_" + "b" * 24})).candidates, ())
        self.assertEqual(lane.search("rescue", 1, allowed_doc_ids=frozenset()).trace["tokenizer_calls"], 0)
        ties = lane.search("common", 2).candidates
        self.assertEqual([c.evidence_id for c in ties], sorted(c.evidence_id for c in ties))
        with tempfile.TemporaryDirectory() as temp:
            root, target = Path(temp), Path(temp) / "private" / "kiwi"
            lane.save(target, data_root=root)
            loaded = KiwiBM25Lane.load(store, FakeTokens(), target, data_root=root)
            self.assertEqual(loaded.search("rescue", 2).candidates, hit.candidates)
            with self.assertRaises(FileExistsError):
                lane.save(target, data_root=root)
            wrong = FakeTokens()
            wrong.identity = {"engine": "synthetic", "version": "2"}
            with self.assertRaises(ValueError):
                KiwiBM25Lane.load(store, wrong, target, data_root=root)

    def test_real_pinned_kiwi_korean_tokenization(self):
        tokenizer = KiwiTokenizer()
        tokens = tokenizer.tokenize("정보시스템의 구축과 운영비 100원 API")
        self.assertIn("구축", tokens)
        self.assertIn("api", tokens)
        self.assertIn("100", tokens)
        self.assertNotIn("의", tokens)
        self.assertEqual(tokenizer.identity["kiwi_version"], "0.23.2")
        self.assertEqual(len(tokenizer.identity["tokenizer_sha256"]), 64)
        self.assertIn("default.dict", tokenizer.identity["model_files_sha256"])

    def test_restricted_scores_ignore_out_of_scope_corpus(self):
        a, b, extra = "doc_" + "1" * 24, "doc_" + "2" * 24, "doc_" + "3" * 24
        base = build_store([chunk("alpha", doc=a), chunk("alpha alpha long long", block="block_" + "2" * 24, doc=b)])
        expanded = build_store([chunk("alpha", doc=a), chunk("alpha alpha long long", block="block_" + "2" * 24, doc=b),
                                chunk("alpha " + "noise " * 100, block="block_" + "3" * 24, doc=extra)])
        scope = frozenset({a, b})
        base_scores = {c.evidence_id: c.score for c in KiwiBM25Lane.build(base, FakeTokens()).search("alpha", 10, allowed_doc_ids=scope).candidates}
        expanded_scores = {c.evidence_id: c.score for c in KiwiBM25Lane.build(expanded, FakeTokens()).search("alpha", 10, allowed_doc_ids=scope).candidates}
        self.assertEqual(base_scores.keys(), expanded_scores.keys())
        for identity in base_scores:
            self.assertAlmostEqual(base_scores[identity], expanded_scores[identity])


if __name__ == "__main__":
    unittest.main()
