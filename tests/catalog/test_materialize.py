from __future__ import annotations

import copy
import unittest

from midprojectrag.catalog import CatalogError, materialize_catalog
from tests.catalog.helpers import DOC_1, SNAPSHOT_ID, artifacts


class CatalogMaterializationTests(unittest.TestCase):
    def _assert_code(self, expected: str, mutate) -> None:
        rows, corrections, retrieval = artifacts()
        mutate(rows, corrections, retrieval)
        with self.assertRaises(CatalogError) as raised:
            materialize_catalog(
                rows,
                corrections,
                retrieval,
                expected_snapshot_id=SNAPSHOT_ID,
            )
        self.assertEqual(raised.exception.code, expected)

    def test_correction_joins_by_csv_row_not_manifest_order(self) -> None:
        rows, corrections, retrieval = artifacts()
        rows.reverse()
        catalog = materialize_catalog(
            rows,
            corrections,
            retrieval,
            expected_snapshot_id=SNAPSHOT_ID,
        )
        self.assertEqual(
            catalog.get_document(DOC_1).get_fact("notice_id_namespace").correction_id,
            "corr_notice_namespace",
        )

    def test_duplicate_target_unknown_field_and_effective_value_drift_fail(self) -> None:
        self._assert_code(
            "duplicate_metadata_fact",
            lambda _r, c, _v: c["corrections"].append(copy.deepcopy(c["corrections"][0])),
        )
        self._assert_code(
            "invalid_metadata_field",
            lambda _r, c, _v: c["corrections"][0].__setitem__("field", "project_summary"),
        )
        self._assert_code(
            "correction_set_catalog_mismatch",
            lambda r, _c, _v: r[0]["metadata"].__setitem__("notice_id_namespace", ""),
        )

    def test_untrusted_correction_types_fail_with_stable_codes(self) -> None:
        self._assert_code(
            "invalid_metadata_state",
            lambda _r, c, _v: c["corrections"][0].__setitem__("reason_code", []),
        )
        self._assert_code(
            "invalid_metadata_state",
            lambda _r, c, _v: c["corrections"][0].__setitem__("confidence", []),
        )
        self._assert_code(
            "invalid_metadata_provenance",
            lambda _r, c, _v: c["corrections"][0]["evidence"][0].__setitem__(
                "source_type", []
            ),
        )

    def test_invalid_datetime_and_amount_are_rejected(self) -> None:
        self._assert_code(
            "invalid_metadata_datetime",
            lambda r, _c, _v: r[0]["metadata"].__setitem__("bid_end_at", "2026-1-3"),
        )
        self._assert_code(
            "invalid_metadata_amount",
            lambda r, _c, _v: r[0]["metadata"].__setitem__("project_amount_raw", "12.5"),
        )

        def noncanonical_applied_amount(rows, corrections, _retrieval) -> None:
            rows[0]["metadata"]["project_amount_raw"] = "1000000.0"
            rows[0]["metadata"]["project_amount_value"] = "1000000"
            correction = corrections["corrections"][0]
            correction["field"] = "project_amount_raw"
            correction["new_value"] = "1000000.0"

        self._assert_code("invalid_metadata_amount", noncanonical_applied_amount)

    def test_local_page_and_structural_locator_validation(self) -> None:
        def add_local(rows, corrections, retrieval, locator: str) -> None:
            corrections["corrections"][0]["evidence"] = [
                {"source_type": "local_source_block", "locator": locator}
            ]

        rows, corrections, retrieval = artifacts()
        add_local(rows, corrections, retrieval, f"{DOC_1}:page:10")
        materialize_catalog(rows, corrections, retrieval, expected_snapshot_id=SNAPSHOT_ID)

        rows, corrections, retrieval = artifacts()
        add_local(
            rows,
            corrections,
            retrieval,
            f"{DOC_1}:section:0/paragraph:2/table:1",
        )
        materialize_catalog(rows, corrections, retrieval, expected_snapshot_id=SNAPSHOT_ID)

        for locator in (
            f"{DOC_1}:page:11",
            "doc_ffffffffffffffffffffffff:page:1",
            f"{DOC_1}:page:0",
            f"{DOC_1}:section:-1/paragraph:0/table:0",
        ):
            with self.subTest(locator=locator):
                self._assert_code(
                    "invalid_metadata_provenance",
                    lambda r, c, v, locator=locator: add_local(r, c, v, locator),
                )

    def test_correction_overlay_cannot_forge_synthetic_catalog_evidence(self) -> None:
        self._assert_code(
            "invalid_metadata_provenance",
            lambda _r, c, _v: c["corrections"][0].__setitem__(
                "evidence",
                [{"source_type": "catalog_record", "locator": "catalog:forged"}],
            ),
        )

    def test_snapshot_and_retrieval_document_set_must_match(self) -> None:
        self._assert_code(
            "correction_set_catalog_mismatch",
            lambda r, _c, _v: r[0].__setitem__("snapshot_id", "snapshot_other"),
        )
        self._assert_code(
            "correction_set_catalog_mismatch",
            lambda _r, _c, v: v.pop(),
        )

    def test_fact_ids_are_deterministic_and_sensitive_to_correction_identity(self) -> None:
        rows, corrections, retrieval = artifacts()
        first = materialize_catalog(
            rows,
            corrections,
            retrieval,
            expected_snapshot_id=SNAPSHOT_ID,
        )
        second = materialize_catalog(
            copy.deepcopy(rows),
            copy.deepcopy(corrections),
            copy.deepcopy(retrieval),
            expected_snapshot_id=SNAPSHOT_ID,
        )
        self.assertEqual(
            first.get_document(DOC_1).facts,
            second.get_document(DOC_1).facts,
        )
        corrections["created_at"] = "2026-08-27T00:00:00Z"
        changed = materialize_catalog(
            rows,
            corrections,
            retrieval,
            expected_snapshot_id=SNAPSHOT_ID,
        )
        self.assertNotEqual(
            first.get_document(DOC_1).facts[0].fact_id,
            changed.get_document(DOC_1).facts[0].fact_id,
        )


if __name__ == "__main__":
    unittest.main()
