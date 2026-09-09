"""Model-free tests for persistent MLX proxy and Mini131 PRE aggregation."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import textwrap
import unittest

from midprojectrag.evo_harness.mini131_pre import (
    SCHEMA_VERSION, UNSUPPORTED, _end_to_end_followup, _execution_record,
    _unsupported_record, aggregate, runtime_failure_case_ids,
)
from midprojectrag.evo_harness.worker_backend import PersistentMLXBackend


class WorkerProxyTests(unittest.TestCase):
    def worker(self, root: Path, *, slow=False):
        script=root/'worker.py'
        script.write_text(textwrap.dedent(f'''\
            import json,sys,time
            identity={{"canonical_model":"Qwen/Qwen3.5-9B","artifact_model":"mlx-community/Qwen3.5-9B-4bit",\
            "revision":"a"*40,"template_sha256":"b"*64,"backend":"fake-worker","device":"cpu-test","precision":"fake","synthetic":True}}
            print(json.dumps({{"op":"ready","identity":identity,"load_seconds":0.1,"manifest_sha256":"c"*64}}),flush=True)
            for line in sys.stdin:
                row=json.loads(line); rid=row["id"]
                if row["op"]=="shutdown": print(json.dumps({{"id":rid,"ok":True}}),flush=True); break
                if row["op"]=="count": print(json.dumps({{"id":rid,"ok":True,"count":7}}),flush=True); continue
                if row["op"]=="complete":
                    {"time.sleep(2)" if slow else "pass"}
                    value={{"text":"{{\\\"tool\\\":\\\"finish\\\",\\\"arguments\\\":{{\\\"status\\\":\\\"abstained\\\",\\\"evidence_ids\\\":[],\\\"unresolved\\\":[]}}}}","input_tokens":7,"output_tokens":5,"finish_reason":"stop"}}
                    print(json.dumps({{"id":rid,"ok":True,"completion":value}}),flush=True)
        '''))
        return [sys.executable,str(script)]

    def test_persistent_proxy_count_complete_and_close(self):
        with tempfile.TemporaryDirectory() as folder:
            with PersistentMLXBackend(command=self.worker(Path(folder)),network_sandbox=False,startup_timeout=2) as backend:
                self.assertTrue(backend.alive)
                self.assertEqual(backend.count_messages([{'role':'user','content':'x'}]),7)
                value=backend.complete([{'role':'user','content':'x'}],max_tokens=16,timeout=2,json_schema={'type':'object'})
                self.assertEqual(value.input_tokens,7); self.assertEqual(value.output_tokens,5)
                self.assertTrue(backend.identity.synthetic)
            self.assertIsNotNone(backend.process.poll())

    def test_proxy_timeout_terminates_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            backend=PersistentMLXBackend(command=self.worker(Path(folder),slow=True),network_sandbox=False,startup_timeout=2)
            with self.assertRaises(TimeoutError):
                backend.complete([{'role':'user','content':'x'}],max_tokens=16,timeout=.05)
            self.assertIsNotNone(backend.process.poll())
            self.assertFalse(backend.alive)
            backend.close()


class Mini131PreContractTests(unittest.TestCase):
    def case(self, lane='core40', task='single_doc', required=None, decision='answer'):
        required=required or ['doc_a']
        source={'task_type':task,'gold':{'decision':decision,'required_doc_ids':required}}
        if lane.startswith('supplemental_answer'):
            source['required_doc_ids']=required; source['gold'].pop('required_doc_ids',None)
        return SimpleNamespace(case_id='case-1',lane=lane,source=source,source_sha256='d'*64,
            request_template={'question':'q','history':[],'document_scope':{'mode':'explicit','doc_ids':['doc_a']}})

    def test_execution_record_objective_metrics(self):
        result={'status':'answered','code':None,'usage':{'policy_calls':3},'wall_seconds':1.0,
                'actions':[{'observation':{'candidates':[{'doc_id':'doc_a'}]}}],
                'response':{'cited_doc_ids':['doc_a']}}
        row=_execution_record(self.case(),result,elapsed=1.5)
        self.assertTrue(row['observed']['decision_match'])
        self.assertEqual(row['observed']['required_doc_citation_recall'],1.0)
        self.assertEqual(row['observed']['required_doc_retrieval_recall'],1.0)

    def test_unsupported_lanes_are_explicit(self):
        for lane,reason in UNSUPPORTED.items():
            row=_unsupported_record(self.case(lane=lane))
            self.assertEqual(row['classification'],'unsupported_specialist')
            self.assertEqual(row['reason'],reason)

    def test_aggregate_keeps_131_inventory_and_unjudged_semantics(self):
        result={'status':'answered','code':None,'usage':{'policy_calls':3,'search_calls':1},'wall_seconds':1.0,
                'actions':[{'observation':{'candidates':[{'doc_id':'doc_a'}]}}],
                'response':{'cited_doc_ids':['doc_a']}}
        executed=_execution_record(self.case(),result,elapsed=2.0)
        unsupported=_unsupported_record(self.case(lane='visual'))
        summary=aggregate([executed,unsupported],candidate_commit='e'*40,source_suite_sha256='f'*64,
                          tool_load_seconds=3,model_load_seconds=4,worker_manifest_sha256='a'*64)
        self.assertEqual(summary['semantic_answer_quality'],'unjudged')
        self.assertEqual(summary['inventory']['overall_total'],131)
        self.assertEqual(summary['inventory']['executed_text'],1)
        self.assertEqual(summary['inventory']['unsupported_specialist'],1)
        self.assertEqual(summary['objective']['decision_match_rate'],1.0)

    def test_runtime_failure_selection_uses_terminal_codes_only(self):
        rows=[
            {"case_id":"a","classification":"executed_text","result":{"status":"budget_exhausted","code":"policy_context_budget_exceeded"}},
            {"case_id":"b","classification":"executed_text","result":{"status":"budget_exhausted","code":"policy_attempt_budget_exhausted"}},
            {"case_id":"c","classification":"executed_text","result":{"status":"budget_exhausted","code":"search_budget_exhausted"}},
            {"case_id":"d","classification":"executed_text","result":{"status":"answered","code":None}},
        ]
        self.assertEqual(runtime_failure_case_ids(rows),("a","b"))

    def test_followup_uses_candidate_prior_citations_only(self):
        case=self.case(task='follow_up')
        case.request_template={'question':'follow','history':[{'role':'user','turn_id':'u1','content':'prior'},
            {'role':'assistant','turn_id':'a1','content':'fixed','cited_doc_ids':['doc_a']}],
            'document_scope':{'mode':'explicit','doc_ids':['doc_a']}}
        class Runner:
            def __init__(self): self.requests=[]
            def run(self,request,**kwargs):
                self.requests.append((request,kwargs))
                if len(self.requests)==1:
                    return {'status':'answered','response':{'answer':'candidate prior','cited_doc_ids':['doc_a'],
                        'prior_citation_state':{'cited_evidence_ids':['canonical-current']}}}
                return {'status':'answered','response':{'answer':'follow answer','cited_doc_ids':['doc_a']},'usage':{},'actions':[],'wall_seconds':1}
        runner=Runner(); final,prior=_end_to_end_followup(runner,case)
        self.assertEqual(final['status'],'answered'); self.assertEqual(prior['status'],'answered')
        follow=runner.requests[1][0]
        self.assertEqual(follow['history'][1]['content'],'candidate prior')
        self.assertEqual(follow['history'][1]['cited_evidence_ids'],['canonical-current'])
        self.assertNotEqual(follow['history'][1]['content'],'fixed')
        self.assertTrue(runner.requests[1][1]['follow_up'])


if __name__=='__main__': unittest.main()
