from __future__ import annotations
import unittest
from midprojectrag.evo_harness.training import build_exclusion_manifest
from midprojectrag.evo_harness.training_authoring_v2 import partition_supported_documents,author_supported_cases,audit_support


def row(i,fields):
    return {"doc_id":f"d{i:02d}","project_name":f"name{i}","ordering_agency":f"agency{i}",
            "notice_number":f"notice{i}","project_summary":"summary","project_amount_value":str(1000+i),
            "asset_count":1,"source_sha256":f"sha{i}","supported_fields":list(fields)}


def docs():
    out=[];i=0
    for n,fields in ((7,("project_name","ordering_agency","project_amount_value")),
                     (4,("project_name","project_amount_value")),(6,("project_name","ordering_agency")),
                     (12,())):
        for _ in range(n): out.append(row(i,fields));i+=1
    return out


def exclusion():
    return build_exclusion_manifest([{"question":"unrelated historical","group_id":"old","task_type":"single_doc",
                                      "document_scope":{"mode":"explicit","doc_ids":["old"]}}],source_id="history",source_sha256="a"*64)


class SeedV2Tests(unittest.TestCase):
    def test_capability_partition_and_authoring_are_stable(self):
        p=partition_supported_documents(docs())
        self.assertEqual({k:len(v) for k,v in p["partitions"].items()},{"sealed_holdout":6,"dev":6,"train":17})
        a=author_supported_cases(p["partitions"],exclusion_manifest=exclusion())
        self.assertEqual({k:len(v) for k,v in a["cases"].items()},{"train":37,"dev":15,"sealed_holdout":15})
        self.assertEqual(a["receipt"]["case_count"],67)
        self.assertEqual({r["task_type"] for r in a["cases"]["train"]},{"fact","compare","follow_up","abstain","visual","mixed"})
        # Use actual supported values as the synthetic chunk text.
        texts={d["doc_id"]:" ".join(str(d[k]) for k in d["supported_fields"]) for d in docs()}
        audit=audit_support(a["cases"],a["targets"],texts)
        self.assertEqual(audit["failed_count"],0)

    def test_capability_inventory_drift_fails_closed(self):
        changed=docs()[:-1]
        with self.assertRaisesRegex(ValueError,"nongolden_v2_capability_inventory_changed"):
            partition_supported_documents(changed)

if __name__=="__main__": unittest.main()
