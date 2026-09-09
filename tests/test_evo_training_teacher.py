from __future__ import annotations
import json,unittest
from midprojectrag.evo_harness.runtime import synthetic_tools
from midprojectrag.evo_harness.training import TRAINING_CASE_SCHEMA,sft_examples_from_trajectory
from midprojectrag.evo_harness.training_teacher import run_teacher_case
from tests.test_evo_harness import FakeBackend

def case(cid,task,question,docs,parent=None,group=None,conv=None):
    row={"schema_version":TRAINING_CASE_SCHEMA,"case_id":cid,"group_id":group or cid,"split":"train","task_type":task,
         "question":question,"request":{"question":question,"history":[],"document_scope":{"mode":"explicit","doc_ids":docs},"options":{"max_citations":3}}}
    if parent:row["follow_up_parent_case_id"]=parent
    if conv:row["conversation_id"]=conv
    return row

def target(cid,task,facts,status="answered"):
    return {"case_id":cid,"split":"train","task_type":task,"terminal_status":status,"facts":facts,"required_tools":[]}

class TeacherTests(unittest.TestCase):
    def test_fact_teacher_uses_real_handles_and_no_policy_completion(self):
        backend=FakeBackend();c=case("f","fact","What is the Alpha project budget?",["alpha"])
        r=run_teacher_case(c,target("f","fact",{"budget":"120 million KRW"}),tools=synthetic_tools(),count_backend=backend)
        self.assertTrue(r["teacher_validation"]["success"])
        self.assertEqual([a["tool"] for a in r["actions"]],["search","read","finish"]);self.assertEqual(backend.calls,[])
        rows=sft_examples_from_trajectory(r,c)
        self.assertEqual([json.loads(x["completion"][0]["content"])["tool"] for x in rows],["search","read","finish"])
        finish=json.loads(rows[-1]["completion"][0]["content"])
        self.assertTrue(all(x.startswith("ev:e") for x in finish["arguments"]["evidence_ids"]))
    def test_compare_reads_both_documents(self):
        backend=FakeBackend();c=case("p","compare","Compare Alpha and Beta budgets.",["alpha","beta"],group="g",conv="conv-g")
        t=target("p","compare",{"left_budget":"120 million KRW","right_budget":"80 million KRW"})
        r=run_teacher_case(c,t,tools=synthetic_tools(),count_backend=backend)
        self.assertTrue(r["teacher_validation"]["success"]);self.assertTrue(r["teacher_validation"]["required_docs_read"])
        self.assertEqual([a["tool"] for a in r["actions"]].count("search"),2)
        self.assertEqual([a["tool"] for a in r["actions"]].count("read"),2)

    def test_followup_researches_current_episode(self):
        backend=FakeBackend();tools=synthetic_tools()
        parent=case("p","compare","Compare Alpha and Beta budgets.",["alpha","beta"],group="g",conv="conv-g")
        pr=run_teacher_case(parent,target("p","compare",{"a":"120 million KRW","b":"80 million KRW"}),tools=tools,count_backend=backend)
        child=case("c","follow_up","Of Alpha and Beta, give the larger budget again.",["alpha","beta"],parent="p",group="g",conv="conv-g")
        cr=run_teacher_case(child,target("c","follow_up",{"winner_budget":"120 million KRW"}),tools=tools,count_backend=backend,parent_case=parent,parent_result=pr)
        self.assertTrue(cr["teacher_validation"]["success"]);self.assertEqual(cr["actions"][0]["tool"],"search")
        self.assertTrue(all(not x.startswith("hist:") for a in cr["actions"] for x in a.get("arguments",{}).get("evidence_ids",[])))

    def test_abstain_is_direct_valid_finish(self):
        backend=FakeBackend();c=case("a","abstain","Unknown scoped fact?",["alpha"])
        r=run_teacher_case(c,target("a","abstain",{"reason":"out_of_scope"},status="abstained"),tools=synthetic_tools(),count_backend=backend)
        self.assertEqual(r["status"],"abstained");self.assertTrue(r["teacher_validation"]["success"]);self.assertEqual([a["tool"] for a in r["actions"]],["finish"])

if __name__=="__main__":unittest.main()
