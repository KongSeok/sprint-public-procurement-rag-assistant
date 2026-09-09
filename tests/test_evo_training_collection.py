from __future__ import annotations
import unittest
from midprojectrag.evo_harness.training_collection import evaluate_result,_follow_request


def case(task="fact"):
    return {"schema_version":"evo-training-case-v1","case_id":"c1","group_id":"g1","split":"train","task_type":task,
            "question":"q","request":{"question":"q","history":[],"document_scope":{"mode":"explicit","doc_ids":["d1"]}}}


class EvaluationTests(unittest.TestCase):
    def test_answer_success_requires_facts_tools_and_scoped_citation(self):
        c=case();t={"case_id":"c1","split":"train","terminal_status":"answered","facts":{"project_name":"Alpha","left_amount":"1200000"},"required_tools":["search","read"]}
        r={"status":"answered","actions":[{"tool":"search","outcome":"completed"},{"tool":"read","outcome":"completed"}],
           "response":{"answer":"Alpha 1,200,000원","cited_doc_ids":["d1"]}}
        self.assertTrue(evaluate_result(c,t,r)["success"])
        r["response"]["cited_doc_ids"]=["outside"]
        self.assertFalse(evaluate_result(c,t,r)["success"])

    def test_visual_boolean_is_gated_by_visual_tools(self):
        c=case("visual");t={"case_id":"c1","split":"train","terminal_status":"answered","facts":{"has_inserted_image":True},"required_tools":["visual_search","inspect_image"]}
        r={"status":"answered","actions":[{"tool":"visual_search","outcome":"completed"},{"tool":"inspect_image","outcome":"completed"}],"response":{"answer":"확인됨","cited_doc_ids":["d1"]}}
        self.assertTrue(evaluate_result(c,t,r)["success"])
        r["actions"].pop();self.assertFalse(evaluate_result(c,t,r)["success"])

    def test_abstention_success_needs_expected_terminal(self):
        c=case("abstain");t={"case_id":"c1","split":"train","terminal_status":"abstained","facts":{"reason":"out_of_scope"},"required_tools":[]}
        self.assertTrue(evaluate_result(c,t,{"status":"abstained","actions":[],"response":{"answer":"","cited_doc_ids":[]}})["success"])


class FollowupTests(unittest.TestCase):
    def test_parent_runtime_citations_become_followup_history(self):
        child=case("follow_up");child["question"]="그중?";child["request"]["question"]="그중?"
        parent=case("compare");parent["case_id"]="p";parent["question"]="compare"
        result={"status":"answered","response":{"answer":"A","cited_doc_ids":["d1"],"prior_citation_state":{"cited_evidence_ids":["canonical-e1"]}}}
        request=_follow_request(child,parent,result)
        self.assertEqual(request["history"][1]["cited_evidence_ids"],["canonical-e1"])
        self.assertEqual(request["question"],"그중?")

if __name__=="__main__": unittest.main()
