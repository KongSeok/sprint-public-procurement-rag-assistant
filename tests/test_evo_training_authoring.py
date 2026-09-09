from __future__ import annotations
import json
import unittest
from midprojectrag.evo_harness.training import build_exclusion_manifest
from midprojectrag.evo_harness.training_authoring import author_non_golden_cases, partition_documents


def doc(i:int,amount:int=100,assets:int=1):
    return {"doc_id":f"doc-{i}","project_name":f"project-{i}","ordering_agency":f"agency-{i}",
            "notice_number":f"notice-{i}","project_summary":f"summary-{i}",
            "project_amount_value":str(amount+i),"asset_count":assets,"source_sha256":f"sha-{i}"}


def exclusion(question:str="historical unrelated question"):
    return build_exclusion_manifest([{"question":question,"group_id":"old-group","task_type":"single_doc",
                                      "document_scope":{"mode":"explicit","doc_ids":["old-doc"]}}],
                                    source_id="history",source_sha256="a"*64)


class DocumentPartitionTests(unittest.TestCase):
    def test_holdout_is_assigned_first_and_splits_are_doc_disjoint(self):
        docs=[doc(i) for i in range(6)]
        out=partition_documents(docs,split_counts={"sealed_holdout":2,"dev":2,"train":2})
        parts=out["partitions"]
        self.assertEqual({k:len(v) for k,v in parts.items()},{"sealed_holdout":2,"dev":2,"train":2})
        sets={k:{r["doc_id"] for r in v} for k,v in parts.items()}
        self.assertFalse(sets["sealed_holdout"]&sets["dev"])
        self.assertFalse(sets["sealed_holdout"]&sets["train"])
        self.assertFalse(sets["dev"]&sets["train"])
        self.assertEqual(out["receipt"]["splits"]["sealed_holdout"]["document_count"],2)

    def test_document_count_must_match_partition_contract(self):
        with self.assertRaisesRegex(ValueError,"nongolden_split_document_count_mismatch"):
            partition_documents([doc(i) for i in range(5)],split_counts={"sealed_holdout":2,"dev":2,"train":2})


class AuthoringTests(unittest.TestCase):
    def setUp(self):
        docs=[doc(i,1000+i*100) for i in range(6)]
        self.parts=partition_documents(docs,split_counts={"sealed_holdout":2,"dev":2,"train":2})["partitions"]

    def test_all_task_families_are_authored_with_targets_separate(self):
        out=author_non_golden_cases(self.parts,exclusion_manifest=exclusion())
        self.assertEqual(out["receipt"]["case_count"],27)
        for split in ("sealed_holdout","dev","train"):
            types={r["task_type"] for r in out["cases"][split]}
            self.assertEqual(types,{"fact","compare","follow_up","abstain","visual","mixed"})
        flat=[r for rows in out["cases"].values() for r in rows]
        targets=out["targets"]
        self.assertEqual({r["case_id"] for r in flat},{r["case_id"] for r in targets})
        self.assertFalse(any("facts" in r or "terminal_status" in r for r in flat))
        self.assertTrue(any(t["task_type"]=="mixed" and set(t["required_tools"])=={"search","read","visual_search","inspect_image"} for t in targets))
        follow=next(r for r in flat if r["task_type"]=="follow_up")
        self.assertIn("follow_up_parent_case_id",follow)
        self.assertEqual(follow["request"]["history"],[])

    def test_historical_question_collision_fails_closed(self):
        first=next(iter(self.parts["sealed_holdout"]))
        q=f"공고번호 {first['notice_number']} 문서의 사업명과 발주기관을 알려줘."
        with self.assertRaisesRegex(ValueError,"training_case_evaluation_leakage"):
            author_non_golden_cases(self.parts,exclusion_manifest=exclusion(q))


if __name__=="__main__": unittest.main()
