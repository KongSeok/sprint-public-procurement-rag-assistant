from __future__ import annotations

import dataclasses
import unittest

from midprojectrag.catalog import CatalogError, CatalogFilter, materialize_catalog
from tests.catalog.helpers import DOC_1, DOC_2, SNAPSHOT_ID, artifacts


class CatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        rows, corrections, retrieval = artifacts()
        self.catalog = materialize_catalog(
            rows,
            corrections,
            retrieval,
            expected_snapshot_id=SNAPSHOT_ID,
        )

    def test_models_are_immutable_and_public_projection_hides_locators(self) -> None:
        card = self.catalog.get_document(DOC_1)
        fact = card.get_fact("notice_id_namespace")
        self.assertEqual(fact.state, "confirmed")
        self.assertEqual(fact.decision, "apply")
        self.assertEqual(fact.evidence[0].source_type, "official_web")
        self.assertNotIn("locator", repr(fact.evidence[0]))
        self.assertNotIn("locator", fact.to_public_dict()["evidence"][0])
        self.assertNotIn("example.test", repr(fact.to_public_dict()))
        self.assertNotIn("AI 관제 구축", repr(fact))
        self.assertNotIn("AI 관제 구축", repr(card))
        self.assertNotIn("AI 관제 구축", repr(self.catalog))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            fact.state = "unknown"  # type: ignore[misc]

    def test_materializes_exactly_twelve_facts_and_amount_sentinel(self) -> None:
        documents = self.catalog.list_documents()
        self.assertEqual(len(documents), 2)
        self.assertTrue(all(len(card.facts) == 12 for card in documents))
        amount = self.catalog.get_document(DOC_1).get_fact("project_amount_raw")
        self.assertEqual(amount.value, "1,000,000원")
        self.assertEqual(amount.normalized_value, "1000000")
        sentinel = self.catalog.get_document(DOC_2).get_fact("project_amount_raw")
        self.assertEqual(sentinel.state, "suspect_sentinel")
        self.assertEqual(sentinel.normalized_value, "1")

    def test_search_combines_filters_with_and_and_never_truncates(self) -> None:
        result = self.catalog.search(
            CatalogFilter(
                notice_id_namespace="g2b",
                agency="가각",
                amount_min_krw=1_000_000,
                amount_max_krw=1_000_000,
                bid_end_from="2026-01-03",
                bid_end_to="2026-01-03",
                source_formats=("HWP",),
                text="n-001",
            )
        )
        self.assertEqual(result.total_count, 1)
        self.assertEqual(tuple(card.doc_id for card in result.documents), (DOC_1,))
        self.assertEqual(self.catalog.search(CatalogFilter()).total_count, 2)

    def test_sentinel_amount_never_participates_in_numeric_filter(self) -> None:
        result = self.catalog.search(CatalogFilter(amount_min_krw=0, amount_max_krw=1))
        self.assertEqual(result.total_count, 0)

    def test_invalid_filter_and_missing_document_have_stable_codes(self) -> None:
        invalid_values = (
            {"amount_min_krw": 2, "amount_max_krw": 1},
            {"bid_end_from": "2026-02-01", "bid_end_to": "2026-01-01"},
            {"bid_end_from": "2026-1-1"},
            {"source_formats": ("pdf", "PDF")},
        )
        for values in invalid_values:
            with self.subTest(values=values):
                with self.assertRaises(CatalogError) as raised:
                    CatalogFilter(**values)
                self.assertEqual(raised.exception.code, "metadata_filter_invalid")
        with self.assertRaises(CatalogError) as raised:
            self.catalog.get_document("doc_ffffffffffffffffffffffff")
        self.assertEqual(raised.exception.code, "metadata_document_not_found")


if __name__ == "__main__":
    unittest.main()
