"""Additional boundary tests for solo code review; no external calls."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from midprojectrag.evo_harness.state import Budgets, InvalidAction, HarnessError, json_object
from midprojectrag.evo_harness.policy import ANSWER_SYSTEM, Completion
from midprojectrag.evo_harness.runtime import synthetic_tools, compose_runtime, verify_local_model
from midprojectrag.evo_harness.tools import HotlineTools
from midprojectrag.evo_harness.cli import _private
from midprojectrag.evidence import Evidence, EvidenceStore, Locator, ProvenanceParent
from midprojectrag.retrieval.contracts import SearchResult, Candidate
from tests.test_evo_harness import FakeBackend, REQUEST, action, search, read, finish


class EvoEdgeTests(unittest.TestCase):
    def test_numeric_overflow_is_invalid_action(self):
        with self.assertRaises(InvalidAction):json_object('{"number":1e999}')

    def test_duplicate_nested_keys(self):
        with self.assertRaises(InvalidAction):json_object('{"arguments":{"x":1,"x":2}}')

    def test_nan_library_deadline_rejected(self):
        with self.assertRaises(ValueError):compose_runtime(FakeBackend(),synthetic_tools()).run(REQUEST,deadline=float('nan'))

    def test_answer_overflow_tells_policy_all_omitted_ids(self):
        backend=FakeBackend([search(),read('e1','e2'),finish('e1','e2'),finish(status='needs_clarification')])
        orig=backend.count_messages
        backend.count_messages=lambda messages:9000 if messages[0]['content']==ANSWER_SYSTEM else orig(messages)
        result=compose_runtime(backend,synthetic_tools()).run(REQUEST)
        self.assertEqual(result['status'],'needs_clarification',result)
        state=json.loads(backend.calls[-1][1]['content'])
        self.assertEqual(state['last_observation']['omitted_evidence_ids'],['e1','e2'])
        self.assertEqual(result['usage']['answer_calls'],0)

    def test_unknown_read_handle_twice_limits_without_generator(self):
        result=compose_runtime(FakeBackend([read('fake'),read('fake')]),synthetic_tools()).run(REQUEST)
        self.assertEqual(result['status'],'invalid_action_limit')
        self.assertEqual(result['usage']['read_calls'],0)
        self.assertEqual(result['usage']['answer_calls'],0)

    def test_alias_and_canonical_duplicate_is_rejected(self):
        tools=synthetic_tools();ep=tools.begin(REQUEST)
        tools.search(ep,{'query':'budget','doc_ids':None,'limit':10},Budgets(),lambda:100)
        eid=ep.handles['e1']
        with self.assertRaises(InvalidAction):tools.read(ep,{'evidence_ids':['e1',eid]},Budgets(),lambda:100)

    def test_late_search_does_not_commit_partial_results(self):
        tools=synthetic_tools();ep=tools.begin(REQUEST);ticks=[0]
        def remaining():
            ticks[0]+=1
            if ticks[0]>1:raise TimeoutError()
            return 100
        with self.assertRaises(TimeoutError):tools.search(ep,{'query':'budget','doc_ids':None,'limit':10},Budgets(),remaining)
        self.assertEqual(ep.usage.search_calls,1);self.assertFalse(ep.candidates);self.assertFalse(ep.cache)

    def test_provider_error_not_cached_as_empty(self):
        tools=synthetic_tools();ep=tools.begin(REQUEST)
        with patch.object(tools.retriever,'search',side_effect=RuntimeError('offline')):
            with self.assertRaises(RuntimeError):tools.search(ep,{'query':'budget','doc_ids':None,'limit':10},Budgets(),lambda:100)
        self.assertFalse(ep.cache);self.assertEqual(ep.usage.search_calls,1)

    def test_out_of_scope_provider_result_is_not_admitted(self):
        tools=synthetic_tools();ep=tools.begin({'question':'alpha','document_scope':{'mode':'explicit','doc_ids':['alpha']}})
        beta=next(e for e in tools.store.evidence if e.doc_id=='beta')
        bad=SearchResult((Candidate(beta.evidence_id,'beta',1.0,'fusion',1),),{})
        with patch.object(tools.retriever,'search',return_value=bad):
            with self.assertRaises(HarnessError):tools.search(ep,{'query':'budget','doc_ids':None,'limit':10},Budgets(),lambda:100)
        self.assertFalse(ep.candidates)

    def test_unresolved_fields_preserved_in_response(self):
        backend=FakeBackend([search(),read('e1'),finish('e1',unresolved=['Beta period missing'])])
        result=compose_runtime(backend,synthetic_tools()).run(REQUEST)
        self.assertEqual(result['status'],'answered')
        self.assertTrue(result['response']['partial'])
        self.assertEqual(result['response']['unresolved'],['Beta period missing'])

    def test_final_citation_is_parent_window_not_child_locator(self):
        result=compose_runtime(FakeBackend([search(),read('e1'),finish('e1')]),synthetic_tools()).run(REQUEST)
        source=result['response']['citation_sources'][0]
        self.assertEqual(source['source_kind'],'parent_window')
        self.assertIn('retrieval_seed_evidence_ids',source)
        self.assertNotIn('evidence_id',source)
        self.assertNotIn('source_chunk_ids',source)

    def test_usage_mismatch_is_terminal_no_retry(self):
        backend=FakeBackend([search()]);orig=backend.complete
        def wrong(messages,**kwargs):
            result=orig(messages,**kwargs)
            return replace(result,input_tokens=result.input_tokens+1)
        backend.complete=wrong
        result=compose_runtime(backend,synthetic_tools()).run(REQUEST)
        self.assertEqual(result['code'],'template_token_count_mismatch');self.assertEqual(len(backend.calls),1)

    def test_final_abstention_counts_one_generation(self):
        backend=FakeBackend([search(),read('e1'),finish('e1')],answer='{"status":"abstained","answer":"","citations":[]}')
        result=compose_runtime(backend,synthetic_tools()).run(REQUEST)
        self.assertEqual(result['status'],'abstained');self.assertEqual(result['usage']['answer_calls'],1)

    def test_result_trajectory_opt_in(self):
        result=compose_runtime(FakeBackend([finish(status='abstained')]),synthetic_tools()).run(REQUEST)
        self.assertNotIn('trajectory',result)

    def test_private_symlink_escape(self):
        with tempfile.TemporaryDirectory() as a,tempfile.TemporaryDirectory() as b:
            root=Path(a);(root/'private').symlink_to(b,target_is_directory=True)
            with self.assertRaises(ValueError):_private(root/'private/out',root)

    def test_manifest_missing_revision_precedes_weights(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=root/'m.json';p.write_text(json.dumps({'repo':'mlx-community/Qwen3.5-9B-4bit','files':{}}))
            with self.assertRaisesRegex(HarnessError,'revision'):verify_local_model(root,p)

    def test_prior_citation_state_consistency(self):
        tools=synthetic_tools();seed=next(e for e in tools.store.evidence if e.doc_id=='beta')
        prior={'cited_doc_ids':['beta'],'cited_evidence_ids':[seed.evidence_id],
               'resolved_entities':[],'list_doc_ids':[],'comparison_doc_ids':[]}
        req={'question':'And the period?','history':[{'role':'assistant','content':'Beta source',
             'cited_doc_ids':['beta'],'cited_evidence_ids':[seed.evidence_id]}],'prior_citation_state':prior}
        self.assertEqual(tools.begin(req).scope,frozenset({'beta'}))
        req['prior_citation_state']['cited_doc_ids']=['alpha']
        with self.assertRaises(HarnessError):tools.begin(req)

    def test_episode_windows_do_not_cross_requests(self):
        tools=synthetic_tools();backend=FakeBackend([search(),read('e1'),finish('e1'),read('e1'),read('e1')])
        runner=compose_runtime(backend,tools)
        self.assertEqual(runner.run(REQUEST)['status'],'answered')
        second=runner.run(REQUEST)
        self.assertEqual(second['status'],'invalid_action_limit')
        self.assertEqual(second['usage']['answer_calls'],0)

    def test_token_counter_must_be_integer(self):
        backend=FakeBackend([search()]);backend.count_messages=lambda _:True
        result=compose_runtime(backend,synthetic_tools()).run(REQUEST)
        self.assertEqual(result['code'],'exact_token_count_required');self.assertFalse(backend.calls)

    def test_input_history_is_not_hidden_server_state(self):
        backend=FakeBackend([finish(status='needs_clarification')])
        req={'question':'What did I ask?','history':[{'role':'user','content':'Compare budgets'}]}
        compose_runtime(backend,synthetic_tools()).run(req)
        prompt=json.loads(backend.calls[0][1]['content'])
        self.assertEqual(prompt['history'],req['history'])


if __name__=='__main__':unittest.main()
