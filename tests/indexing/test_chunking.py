from __future__ import annotations

import unittest

from midprojectrag.ingest.common import sha256_text
from midprojectrag.indexing.chunking import PageChunkConfig, build_page_chunks, chunk_artifact_sha256


def _block(
    *,
    block_id: str = "block_0123456789abcdef01234567",
    doc_id: str = "doc_0123456789abcdef01234567",
    text: str = "첫 문단\n\n둘째 문단",
    page: int = 3,
    retrieval_role: str = "primary",
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "block_id": block_id,
        "doc_id": doc_id,
        "sequence": page - 1,
        "block_type": "page_text" if retrieval_role == "primary" else "table",
        "section_path": ["사업개요"],
        "page_start": page,
        "page_end": page,
        "bbox": None,
        "text": text,
        "content_sha256": sha256_text(text),
        "extractor": "test",
        "extractor_version": "1",
        "source_locator": f"page:{page}",
        "retrieval_role": retrieval_role,
    }


class PageChunkingTests(unittest.TestCase):
    def test_build_is_deterministic_and_excludes_auxiliary_tables(self) -> None:
        first = _block()
        auxiliary = _block(
            block_id="block_1123456789abcdef01234567",
            text="표 내용",
            retrieval_role="structured_auxiliary",
        )
        forward = build_page_chunks([first, auxiliary])
        reverse = build_page_chunks([auxiliary, first])
        self.assertEqual(forward, reverse)
        self.assertEqual(len(forward), 1)
        self.assertEqual(forward[0]["retrieval_role"], "primary")
        self.assertEqual(forward[0]["source_block_ids"], [first["block_id"]])
        self.assertRegex(forward[0]["chunk_id"], r"^chunk_[0-9a-f]{24}$")
        self.assertEqual(chunk_artifact_sha256(forward), chunk_artifact_sha256(reverse))

    def test_long_page_splits_on_newline_with_same_locator(self) -> None:
        text = ("가" * 180) + "\n\n" + ("나" * 180) + "\n\n" + ("다" * 180)
        chunks = build_page_chunks([_block(text=text)], PageChunkConfig(max_chars=256))
        self.assertGreater(len(chunks), 1)
        self.assertEqual([item["part_index"] for item in chunks], list(range(len(chunks))))
        self.assertTrue(all(item["part_count"] == len(chunks) for item in chunks))
        self.assertTrue(all(item["page_start"] == 3 for item in chunks))

    def test_content_hash_mismatch_fails_closed(self) -> None:
        block = _block()
        block["content_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "source_content_hash_mismatch"):
            build_page_chunks([block])

    def test_duplicate_source_block_fails_closed(self) -> None:
        block = _block()
        with self.assertRaisesRegex(ValueError, "duplicate_source_block_id"):
            build_page_chunks([block, dict(block)])

    def test_no_primary_blocks_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "no_primary_blocks"):
            build_page_chunks([_block(retrieval_role="structured_auxiliary")])

    def test_empty_section_path_item_fails_before_it_can_break_citations(self) -> None:
        block = _block()
        block["section_path"] = [""]
        with self.assertRaisesRegex(ValueError, "invalid_section_path"):
            build_page_chunks([block])


if __name__ == "__main__":
    unittest.main()
