from copy import deepcopy
import hashlib
import unittest

from midprojectrag.evidence.builder import SplitConfig, build_store, split_spans
from midprojectrag.indexing.chunking import PageChunkConfig, _split_at_newlines
from midprojectrag.ingest.common import canonical_json


def chunk(text, *, block="block_" + "a" * 24, doc="doc_" + "b" * 24, page=1):
    sha = lambda s: hashlib.sha256(s.encode()).hexdigest()
    config = PageChunkConfig().config_sha256
    identity = dict(block_id=block, config_sha256=config, content_sha256=sha(text), doc_id=doc,
                    page_end=page, page_start=page, part_count=1, part_index=0)
    return dict(schema_version="1.0", chunk_id="chunk_" + sha(canonical_json(identity))[:24],
                doc_id=doc, text=text, source_block_ids=[block], section_path=[], page_start=page,
                page_end=page, part_index=0, part_count=1, retrieval_role="primary", chunker_id="page-v1",
                config_sha256=config, content_sha256=sha(text))


class EvidenceBuilderTests(unittest.TestCase):
    def test_compat_exact_legacy_split_policy_and_spans(self):
        texts = ("가" * 4000, "A" * 900 + "\n\n" + " B" * 1700, "x\n" * 1600, "한글\n\n영문\n")
        for text in texts:
            with self.subTest(length=len(text)):
                spans = split_spans(text, SplitConfig())
                self.assertEqual([text[s:e] for s, e in spans], _split_at_newlines(text, 1600))
                self.assertTrue(all(0 <= s < e <= len(text) and e-s <= 1600 for s, e in spans))

    def test_repeated_children_preserve_source_ids_without_mutation(self):
        row = chunk("X" * 3200)
        before = deepcopy(row)
        store = build_store([row])
        children = store.candidates()
        self.assertEqual(len(children), 2)
        self.assertNotEqual(children[0].evidence_id, children[1].evidence_id)
        self.assertEqual(len(store.parents), 1)
        self.assertEqual(len(store.candidates(kinds=("page",))), 1)
        self.assertEqual({e.source_chunk_ids for e in children}, {(row["chunk_id"],)})
        self.assertEqual(before, row)
        self.assertEqual(store.bundle_sha256, build_store([row]).bundle_sha256)

    def test_source_block_hash_doc_and_page_binding(self):
        row = chunk("abc")
        block = dict(block_id=row["source_block_ids"][0], doc_id=row["doc_id"], text=" abc ",
                     page_start=1, page_end=1, content_sha256=hashlib.sha256(b" abc ").hexdigest())
        store = build_store([row], source_blocks=[block], parent_kinds={row["doc_id"]: "pdf_page"})
        self.assertEqual(store.parents[0].text, " abc ")
        self.assertEqual(store.candidates()[0].locator.char_range, (1, 4))
        for change in ({"doc_id": "other"}, {"text": "xyz"}, {"page_start": 2}, {"section_path": ["foreign"]},
                       {"text": " abc tail", "content_sha256": hashlib.sha256(b" abc tail").hexdigest()}):
            with self.assertRaises(ValueError):
                build_store([row], source_blocks=[block | change])

    def test_invalid_input_rejected(self):
        row = chunk("abc")
        with self.assertRaises(ValueError):
            build_store([row, row])
        with self.assertRaises(ValueError):
            build_store([row | {"text": "injected"}])
        with self.assertRaises(ValueError):
            SplitConfig(max_chars=True)


if __name__ == "__main__":
    unittest.main()
