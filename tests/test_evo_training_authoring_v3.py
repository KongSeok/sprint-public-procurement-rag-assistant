from __future__ import annotations
import unittest
from midprojectrag.ingest.common import canonical_json,sha256_text
from midprojectrag.evo_harness.training_authoring_v2 import partition_supported_documents
from midprojectrag.evo_harness.training_authoring_v3 import GATE_SCHEMA,author_visual_gated_cases
from tests.test_evo_training_authoring_v2 import docs,exclusion

def gate(ids):
    value={"schema_version":GATE_SCHEMA,"eligible_doc_ids":sorted(ids),"source_receipt_sha256":"a"*64}
    value["gate_sha256"]=sha256_text(canonical_json(value));return value

class SeedV3Tests(unittest.TestCase):
    def test_visual_gate_reauthors_only_supported_capacity(self):
        p=partition_supported_documents(docs()); ids={d["doc_id"] for rows in p["partitions"].values() for d in rows}
        a=author_visual_gated_cases(p["partitions"],exclusion_manifest=exclusion(),visual_source_gate=gate(ids))
        counts=a["receipt"]["task_counts"]
        self.assertEqual(counts["train:visual"],6);self.assertEqual(counts["train:mixed"],5)
        self.assertEqual(counts["dev:visual"],2);self.assertEqual(counts["dev:mixed"],2)
        self.assertEqual(counts["sealed_holdout:visual"],2);self.assertEqual(counts["sealed_holdout:mixed"],2)
        self.assertTrue(all(c["case_id"].startswith("ng3-") for rows in a["cases"].values() for c in rows if c["task_type"] in {"visual","mixed"}))

    def test_visual_capacity_shortage_fails_closed(self):
        p=partition_supported_documents(docs()); ids={d["doc_id"] for rows in p["partitions"].values() for d in rows}
        train_amount=[d["doc_id"] for d in p["partitions"]["train"] if "project_amount_value" in d["supported_fields"]]
        ids-=set(train_amount)
        with self.assertRaisesRegex(ValueError,"visual_capacity_insufficient:train"):
            author_visual_gated_cases(p["partitions"],exclusion_manifest=exclusion(),visual_source_gate=gate(ids))

if __name__=="__main__":unittest.main()
