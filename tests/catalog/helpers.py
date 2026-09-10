from __future__ import annotations

from copy import deepcopy


DOC_1 = "doc_000000000000000000000001"
DOC_2 = "doc_000000000000000000000002"
SNAPSHOT_ID = "snapshot_test"


def catalog_rows() -> list[dict[str, object]]:
    return [
        {
            "schema_version": "1.0",
            "snapshot_id": SNAPSHOT_ID,
            "doc_id": DOC_1,
            "csv_row_number": 2,
            "metadata": {
                "notice_id_namespace": "g2b",
                "notice_number": "N-001",
                "notice_round": "00",
                "project_name": "AI 관제 구축",
                "project_amount_raw": "1,000,000원",
                "project_amount_value": "1000000",
                "ordering_agency": "가각 공사",
                "published_at": "2026-01-01 09:00:00",
                "bid_start_at": "2026-01-02 09:00:00",
                "bid_end_at": "2026-01-03 23:59:59",
                "bid_open_at": "",
                "proposal_evaluation_at": "",
                "source_format": "hwp",
            },
        },
        {
            "schema_version": "1.0",
            "snapshot_id": SNAPSHOT_ID,
            "doc_id": DOC_2,
            "csv_row_number": 3,
            "metadata": {
                "notice_id_namespace": "",
                "notice_number": "N-002",
                "notice_round": "01",
                "project_name": "데이터 플랫폼",
                "project_amount_raw": "1",
                "project_amount_value": "1",
                "ordering_agency": "나나 대학교",
                "published_at": "2026-02-01 10:00:00",
                "bid_start_at": "",
                "bid_end_at": "2026-02-10 00:00:00",
                "bid_open_at": "",
                "proposal_evaluation_at": "",
                "source_format": "pdf",
            },
        },
    ]


def retrieval_rows() -> list[dict[str, object]]:
    return [
        {"doc_id": DOC_1, "page_count": 10},
        {"doc_id": DOC_2, "page_count": 2},
    ]


def correction_set() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "source_csv_sha256": "a" * 64,
        "created_at": "2026-08-26T00:00:00Z",
        "corrections": [
            {
                "correction_id": "corr_notice_namespace",
                "csv_row_number": 2,
                "row_sha256": "b" * 64,
                "field": "notice_id_namespace",
                "old_value": None,
                "new_value": "g2b",
                "decision": "apply",
                "reason_code": "official_source_confirmed",
                "confidence": "high",
                "checked_at": "2026-08-26",
                "evidence": [
                    {
                        "source_type": "official_web",
                        "locator": "https://example.test/notices/N-001",
                    }
                ],
            },
            {
                "correction_id": "corr_missing_open",
                "csv_row_number": 3,
                "row_sha256": "c" * 64,
                "field": "bid_open_at",
                "old_value": None,
                "new_value": None,
                "decision": "retain_null",
                "reason_code": "source_not_stated",
                "confidence": "medium",
                "checked_at": "2026-08-26",
                "evidence": [
                    {
                        "source_type": "local_audit",
                        "locator": "audit:synthetic",
                    }
                ],
            },
        ],
    }


def artifacts() -> tuple[
    list[dict[str, object]], dict[str, object], list[dict[str, object]]
]:
    return deepcopy(catalog_rows()), deepcopy(correction_set()), deepcopy(retrieval_rows())
