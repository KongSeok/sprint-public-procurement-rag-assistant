from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from midprojectrag.orchestration.golden_v3 import (
    EXPECTED_LANES,
    GoldenV3Inventory,
    build_runtime_requests,
)


class GoldenV3RequestTests(unittest.TestCase):
    def test_runtime_request_omits_gold_and_preserves_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "golden-set-final" / "dev.refined.review-candidate.jsonl"
            source.parent.mkdir(parents=True)
            source.write_text(json.dumps({
                "case_id": "dev-single-001",
                "question": "예산은 얼마인가요?",
                "history": [],
                "document_scope": {"mode": "explicit", "doc_ids": ["doc_000000000000000000000001"]},
                "task_type": "single_doc",
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            inventory = GoldenV3Inventory(
                root=root,
                index_sha256="0" * 64,
                set_id="third-integrated-evaluation-inventory-v3",
                status="provisional",
                counts={},
                lanes=(),
                source_sha256={},
            )
            # The helper is intentionally exercised through a minimal source
            # override rather than the full package validator.
            import midprojectrag.orchestration.golden_v3 as module
            old_counts = module.SOURCE_COUNTS.copy()
            old_sources = module.NONVISUAL_REQUEST_SOURCES
            try:
                module.SOURCE_COUNTS.clear()
                module.SOURCE_COUNTS[source.relative_to(root).as_posix()] = 1
                module.NONVISUAL_REQUEST_SOURCES = (source.relative_to(root).as_posix(),)
                rows = build_runtime_requests(inventory)
            finally:
                module.SOURCE_COUNTS.clear()
                module.SOURCE_COUNTS.update(old_counts)
                module.NONVISUAL_REQUEST_SOURCES = old_sources
            self.assertEqual(len(rows), 1)
            self.assertNotIn("gold", rows[0])
            self.assertEqual(rows[0]["request"]["document_scope"]["mode"], "explicit")
            self.assertEqual(rows[0]["request"]["options"], {"max_citations": 5})

    def test_lane_contract_is_not_a_single_gold_file(self):
        self.assertEqual(sum(EXPECTED_LANES.values()), 131)
        self.assertEqual(EXPECTED_LANES["parser_regression"], 2)
        self.assertEqual(EXPECTED_LANES["visual"], 10)

