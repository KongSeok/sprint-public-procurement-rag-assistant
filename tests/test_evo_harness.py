"""Model-free tests. Scripted backends are test doubles, not learned policies."""
from __future__ import annotations

from dataclasses import replace
from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from midprojectrag.evo_harness.state import (Budgets, InvalidAction, LimitReached, Unsupported,
                                             action_from_json, action_schema, json_object)
from midprojectrag.evo_harness.experience import Experience
from midprojectrag.evo_harness.policy import (MODEL_ID, DERIVATIVE_ID, POLICY_SYSTEM, ANSWER_SYSTEM,
                                             ModelIdentity, Completion, LLMPolicy, AnswerComposer)
from midprojectrag.evo_harness.runtime import synthetic_tools, compose_runtime, verify_local_model
from midprojectrag.evo_harness.cli import main, _private


def action(tool, **arguments):
    return json.dumps({"tool":tool,"arguments":arguments})


def search(query="budget", docs=None, limit=10):
    return action("search",query=query,doc_ids=docs,limit=limit)


def _candidate(ref):
    if ref.startswith("cand:"):
        return ref
    if ref.startswith("ev:"):
        return "cand:" + ref[len("ev:"):]
    return "cand:" + ref


def _evidence(ref):
    if ref.startswith("ev:"):
        return ref
    if ref.startswith("cand:"):
        return "ev:" + ref[len("cand:"):]
    return "ev:" + ref


def read(*refs):
    return action("read",evidence_ids=[_candidate(ref) for ref in refs])


def finish(*refs,status="answered",unresolved=None):
    return action("finish",status=status,evidence_ids=[_evidence(ref) for ref in refs],unresolved=unresolved or [])


REQUEST={"question":"Compare the budget and performance period of Alpha and Beta.",
         "document_scope":{"mode":"explicit","doc_ids":["alpha","beta"]}}


class FakeBackend:
    """Deterministic counting/response double; CLI never selects this backend."""
    def __init__(self, replies=None, callback=None, answer=None):
        self.identity=ModelIdentity(MODEL_ID,DERIVATIVE_ID,"a"*40,"b"*64,"fake","cpu-test","fake",True)
        self.replies=list(replies or [])
        self.callback=callback
        self.answer=answer
        self.calls=[]
        self.schemas=[]
        self.count_override=None
        self.finish_reason="stop"
        self.after_call=None

    def count_messages(self,messages):
        return self.count_override or max(1,len(json.dumps(messages))//8)

    def complete(self,messages,*,max_tokens,timeout,json_schema=None):
        self.calls.append(deepcopy(messages))
        self.schemas.append(deepcopy(json_schema))
        if self.after_call:
            self.after_call()
        if messages[0]["content"]==ANSWER_SYSTEM:
            sources=json.loads(messages[1]["content"])["sources"]
            output=self.answer or json.dumps({"status":"answered","answer":"Alpha and Beta have different budgets and periods.",
                                              "citations":[row["label"] for row in sources]})
        elif self.callback:
            output=self.callback(json.loads(messages[1]["content"]))
        else:
            output=self.replies.pop(0)
        return Completion(output,self.count_messages(messages),min(80,max_tokens),self.finish_reason)


class EvoWireTests(unittest.TestCase):
    def test_seven_valid_tools(self):
        rows=[search(),read("e1"),action("track",target="world"),
              action("commit",goal_id="period",summary="Need Beta period",status="open",evidence_ids=[]),
              action("recall",query="period",limit=3),action("note",insight="Use performance period, not deadline"),finish("e1")]
        self.assertEqual(len({action_from_json(row)["tool"] for row in rows}),7)

    def test_json_duplicate_unknown_nonfinite_and_scalar(self):
        for raw in ['{"tool":"search","tool":"read","arguments":{}}','[]','null','{"x":NaN}',
                    '{"tool":"shell","arguments":{}}','{"tool":"track","arguments":{"target":"world","x":1}}',
                    '{"tool":"track","arguments":{"target":"world"},"reasoning":"extra"}',
                    '{"tool":"track","arguments":{"target":"\\ud800"}}']:
            with self.subTest(raw=raw),self.assertRaises(InvalidAction):action_from_json(raw)

    def test_boolean_number_and_duplicate_alias_input(self):
        for raw in [search(limit=True),search(docs=["alpha","alpha"]),read(),read("e1","e1"),
                    finish(),finish("e1",status="abstained"),action("note",insight=" "*20)]:
            with self.subTest(raw=raw),self.assertRaises(InvalidAction):action_from_json(raw)

    def test_budgets_cannot_expand(self):
        for kw in [{"policy_calls":13},{"seconds":float("nan")},{"seconds":121},{"search_calls":True},
                   {"policy_context":200,"policy_output":256}]:
            with self.subTest(kw=kw),self.assertRaises(ValueError):Budgets(**kw)

    def test_wrong_models_and_unpinned_revision(self):
        base=FakeBackend().identity
        for kw in [{"canonical_model":"Qwen/Qwen3-8B"},{"artifact_model":"Qwen/Qwen3.5-9B-Base"},
                   {"revision":"main"},{"template_sha256":""}]:
            with self.subTest(kw=kw),self.assertRaises(ValueError):replace(base,**kw)


class EvoToolsTests(unittest.TestCase):
    def setUp(self):
        self.tools=synthetic_tools();self.ep=self.tools.begin(REQUEST);self.b=Budgets();self.bank=Experience()

    def do(self,raw):
        return self.tools.dispatch(self.ep,action_from_json(raw),self.b,lambda:100,self.bank)

    def test_scope_escape_and_unknown_before_retrieval(self):
        self.ep=self.tools.begin({"question":"Alpha budget","document_scope":{"mode":"explicit","doc_ids":["alpha"]}})
        for docs in [["beta"],["unknown"]]:
            with self.assertRaises(InvalidAction):self.do(search(docs=docs))
        self.assertEqual(self.ep.usage.search_calls,0)

    def test_empty_scope_calls_zero(self):
        obs=self.do(search(docs=[]))
        self.assertEqual(obs["candidates"],[]);self.assertEqual(self.ep.usage.search_calls,0)

    def test_search_read_and_provenance_for_multiple_documents(self):
        found=self.do(search())["candidates"]
        self.assertEqual({r["doc_id"] for r in found},{"alpha","beta"})
        read_result=self.do(read(*[r["id"] for r in found]))
        packet=self.tools.packet(self.ep,read_result["read"])
        self.assertEqual([r["label"] for r in packet],["S1","S2"])
        for row in packet:
            lo,hi=row["locator"]["char_range"]
            self.assertEqual(row["text"],self.tools.store.parent(row["parent_id"]).text[lo:hi])
            self.assertEqual(row["char_range_base"],"parent_text")
            self.assertFalse(row["semantic_verified"])

    def test_duplicate_cache_and_input_fingerprints(self):
        first=self.do(search());second=self.do(search())
        self.assertEqual(self.ep.usage.search_calls,1);self.assertTrue(second["duplicate"])
        ref=first["candidates"][0]["id"]
        self.do(read(ref));self.do(read(ref))
        self.assertEqual(self.ep.usage.read_calls,1)
        self.do(search(query="period"))
        self.assertEqual(self.ep.usage.search_calls,2)
        self.assertEqual(self.ep.usage.duplicates,2)

    def test_read_before_search_and_finish_before_read(self):
        with self.assertRaises(InvalidAction):self.do(read("e1"))
        self.do(search())
        with self.assertRaises(InvalidAction):self.tools.packet(self.ep,["e1"])

    def test_cache_is_episode_local(self):
        self.do(search());other=self.tools.begin(REQUEST)
        self.assertFalse(other.cache);self.assertFalse(other.candidates);self.assertEqual(other.usage.search_calls,0)

    def test_progress_is_not_semantic_truth(self):
        self.do(search())
        obs=self.do(action("commit",goal_id="g",summary="Candidate found",status="evidence_found",evidence_ids=["cand:e1"]))
        self.assertFalse(obs["goal"]["semantic_verified"])
        self.assertFalse(self.ep.windows)
        with self.assertRaises(InvalidAction):self.do(action("commit",goal_id="bad",summary="fake",status="verified",evidence_ids=[]))

    def test_notes_and_recall_quarantined(self):
        self.bank=Experience.from_reviewed({"version":"v1","reviewed":True,"entries":[{"id":"p","strategy":"performance period keywords"}]})
        before=self.bank.fingerprint
        self.do(action("note",insight="Never confuse deadlines with performance period"))
        obs=self.do(action("recall",query="performance period",limit=1))
        self.assertEqual(obs["strategies"][0]["id"],"p");self.assertEqual(before,self.bank.fingerprint)
        self.assertEqual(len(self.ep.notes),1)
        with self.assertRaises(InvalidAction):Experience.from_reviewed({"version":"v1","reviewed":False,"entries":[]})

    def test_unknown_track_and_note_capacity(self):
        with self.assertRaises(InvalidAction):self.do(action("track",target="missing"))
        for i in range(8):self.do(action("note",insight=f"strategy {i}"))
        with self.assertRaises(InvalidAction):self.do(action("note",insight="overflow"))

    def test_gold_and_filters_rejected(self):
        bad=deepcopy(REQUEST);bad["expected_answer"]="gold"
        with self.assertRaises(ValueError):self.tools.begin(bad)
        bad=deepcopy(REQUEST);bad["metadata_filters"]=[{"field":"amount","operator":"gt","value":1}]
        with self.assertRaises(Unsupported):self.tools.begin(bad)

    def test_explicit_followup_uses_citations_not_text_guess(self):
        eid=next(e.evidence_id for e in self.tools.store.evidence if e.doc_id=="beta")
        req={"question":"And its period?","history":[{"role":"assistant","content":"Beta budget is in the cited source.",
                 "cited_doc_ids":["beta"],"cited_evidence_ids":[eid]}]}
        ep=self.tools.begin(req,follow_up=True)
        self.assertEqual(ep.scope,frozenset({"beta"}))
        req["document_scope"]={"mode":"explicit","doc_ids":["alpha"]}
        self.assertEqual(self.tools.begin(req,follow_up=True).scope,frozenset())
        req["history"][0]["cited_evidence_ids"]=["missing"]
        with self.assertRaises(Unsupported):self.tools.begin(req,follow_up=True)

    def test_latest_assistant_only(self):
        eid=self.tools.store.evidence[0].evidence_id;doc=self.tools.store.evidence[0].doc_id
        req={"question":"And?","history":[{"role":"assistant","content":"prior","cited_doc_ids":[doc],"cited_evidence_ids":[eid]},
                                                   {"role":"assistant","content":"No citations now"}]}
        with self.assertRaises(Unsupported):self.tools.begin(req,follow_up=True)

    def test_search_and_read_budget(self):
        self.b=Budgets(search_calls=1,read_calls=1)
        self.do(search());self.do(read("e1"))
        with self.assertRaises(LimitReached):self.do(search(query="other"))
        with self.assertRaises(LimitReached):self.do(read("e2"))

    def test_duplicate_search_cooldown_breaks_stagnation(self):
        self.do(search()); duplicate=self.do(search())
        self.assertTrue(duplicate["duplicate"])
        self.assertNotIn('"const":"search"',json.dumps(action_schema(self.ep,self.b),separators=(",",":")))
        with self.assertRaisesRegex(InvalidAction,"stagnant_duplicate_search"):
            self.do(search())
        self.do(action("track",target="world"))
        self.assertTrue(self.do(search())["duplicate"])

    def test_tool_result_copy_cannot_mutate_cache(self):
        first=self.do(search());first["candidates"].clear()
        self.assertTrue(self.do(search())["candidates"])


class EvoRunnerTests(unittest.TestCase):
    def run_case(self,replies=None,backend=None,budgets=None,request=None,**kwargs):
        self.backend=backend or FakeBackend(replies)
        self.runner=compose_runtime(self.backend,synthetic_tools(),budgets=budgets)
        return self.runner.run(request or REQUEST,**kwargs)

    def test_complete_public_tools_and_no_controller_calls(self):
        forbidden={"issue_harness_execution","validate_harness_execution","decide_controller_action",
                   "validate_controller_decision_receipt","require_successor_record"}
        entered=[]
        def profile(frame,event,arg):
            if event=="call" and frame.f_code.co_name in forbidden:entered.append(frame.f_code.co_name)
        before=sys.getprofile()
        try:
            sys.setprofile(profile)
            result=self.run_case([search(),read("e1","e2"),finish("e1","e2")],record_trajectory=True)
        finally:sys.setprofile(before)
        self.assertEqual(result["status"],"answered",result)
        self.assertEqual(entered,[])
        self.assertEqual(result["usage"]["policy_calls"],3)
        self.assertEqual(result["usage"]["answer_calls"],1)
        self.assertEqual(result["response"]["citations"],["S1","S2"])
        self.assertFalse(result["trained_policy"])
        self.assertEqual(sum(r["kind"]=="policy" for r in result["trajectory"]),3)
        self.assertGreater(result["usage"]["policy_input_tokens"],0)

    def test_observation_driven_missing_document_revisit(self):
        def choose(state):
            known=state["known_evidence"];read_ids=[r["id"] for r in known if r["read"]]
            if not known:return search("Alpha budget and period",["alpha"])
            if not read_ids:return read(known[0]["id"])
            if {r["doc_id"] for r in known}=={"alpha"}:return search("Beta performance period and budget",["beta"])
            unread=[r["id"] for r in known if not r["read"]]
            if unread:return read(*unread)
            return finish(*read_ids)
        result=self.run_case(backend=FakeBackend(callback=choose))
        self.assertEqual(result["status"],"answered",result)
        searches=[r["arguments"] for r in result["actions"] if r.get("tool")=="search"]
        self.assertEqual([r["doc_ids"] for r in searches],[["alpha"],["beta"]])
        self.assertEqual(result["usage"]["search_calls"],2)

    def test_invalid_action_then_corrected_not_external_retry(self):
        result=self.run_case(['not json',finish(status="abstained")])
        self.assertEqual(result["status"],"abstained")
        self.assertEqual(result["usage"]["invalid_actions"],1);self.assertEqual(result["usage"]["answer_calls"],0)

    def test_invalid_limit_after_two_attempts(self):
        result=self.run_case(['bad','bad',search()])
        self.assertEqual(result["status"],"invalid_action_limit")
        self.assertEqual(len(self.backend.calls),2)

    def test_incomplete_output_stops_but_preserves_usage(self):
        backend=FakeBackend([search()]);backend.finish_reason="length"
        result=self.run_case(backend=backend)
        self.assertEqual(result["status"],"error")
        self.assertEqual(result["code"],"model_output_incomplete")
        self.assertEqual(result["usage"]["policy_output_tokens"],80)

    def test_policy_budget_and_context(self):
        result=self.run_case([action("track",target="world")],budgets=Budgets(policy_calls=1))
        self.assertEqual(result["status"],"budget_exhausted")
        backend=FakeBackend([search()]);backend.count_override=4096
        result=self.run_case(backend=backend)
        self.assertEqual(result["code"],"policy_context_budget_exceeded");self.assertFalse(backend.calls)

    def test_policy_compacts_read_previews_before_context_overflow(self):
        tools=synthetic_tools(); ep=tools.begin(REQUEST); budget=Budgets()
        found=tools.search(ep,{"query":"budget","doc_ids":None,"limit":10},budget,lambda:100)["candidates"]
        tools.read(ep,{"evidence_ids":[row["id"] for row in found]},budget,lambda:100)
        original={key: row["text"] for key,row in ep.windows.items()}
        for row in ep.windows.values(): row["text"]="K"*1600
        backend=FakeBackend(callback=lambda state: finish(*[row["id"] for row in state["read_evidence"]]))
        backend.count_messages=lambda messages: 2300 + len(messages[1]["content"])//2
        raw=LLMPolicy(backend).propose(ep,budget,lambda:100)
        self.assertEqual(action_from_json(raw)["tool"],"finish")
        state=json.loads(backend.calls[-1][1]["content"]); rows=state["read_evidence"]
        self.assertTrue(all(row.get("text_truncated") for row in rows))
        self.assertTrue(all(len(row["text"])<1600 for row in rows))
        self.assertEqual(set(ep.windows),set(original))
        self.assertTrue(all(len(row["text"])==1600 for row in ep.windows.values()))
        self.assertLessEqual(backend.count_messages(backend.calls[-1])+budget.policy_output,budget.policy_context)

    def test_abstain_and_clarification_do_not_generate(self):
        for status in ["abstained","needs_clarification"]:
            result=self.run_case([finish(status=status,unresolved=["Specify the project"])])
            self.assertEqual(result["status"],status);self.assertEqual(result["usage"]["answer_calls"],0)

    def test_answer_citation_rejected_without_retry(self):
        backend=FakeBackend([search(),read("e1"),finish("e1")],answer='{"status":"answered","answer":"unsupported","citations":["S99"]}')
        result=self.run_case(backend=backend)
        self.assertEqual(result["status"],"error");self.assertEqual(result["usage"]["answer_calls"],1)

    def test_deadline_before_policy(self):
        result=self.run_case([search()],deadline=0)
        self.assertEqual(result["status"],"timeout");self.assertFalse(self.backend.calls)

    def test_late_model_response_is_timeout_with_usage(self):
        now=[1.0];backend=FakeBackend([search()]);backend.after_call=lambda:now.__setitem__(0,200.0)
        runner=compose_runtime(backend,synthetic_tools());runner.clock=lambda:now[0]
        result=runner.run(REQUEST)
        self.assertEqual(result["status"],"timeout");self.assertEqual(result["usage"]["policy_calls"],1)
        self.assertEqual(result["usage"]["search_calls"],0)

    def test_provider_failure_not_empty_success_and_no_retry(self):
        backend=FakeBackend([search()])
        with patch.object(backend,"complete",side_effect=RuntimeError("private credential or text")):
            result=self.run_case(backend=backend)
        self.assertEqual(result["code"],"provider_error")
        self.assertNotIn("private credential",json.dumps(result));self.assertEqual(result["usage"]["policy_calls"],1)

    def test_fixed_control_same_answer_model_no_policy(self):
        backend=FakeBackend();runner=compose_runtime(backend,synthetic_tools())
        result=runner.run_fixed(REQUEST)
        self.assertEqual(result["status"],"answered",result)
        self.assertEqual(result["usage"]["policy_calls"],0);self.assertEqual(result["usage"]["answer_calls"],1)

    def test_followup_missing_citations_clarifies(self):
        result=self.run_case([search()],follow_up=True)
        self.assertEqual(result["status"],"needs_clarification");self.assertFalse(self.backend.calls)

    def test_empty_user_scope_is_not_global(self):
        result=self.run_case([search()],request={"question":"budget","document_scope":{"mode":"explicit","doc_ids":[]}})
        self.assertEqual(result["status"],"abstained");self.assertFalse(self.backend.calls)

    def test_unknown_options_and_metadata_are_explicit(self):
        request=deepcopy(REQUEST);request["options"]={"allow_global_fallback":True}
        result=self.run_case([search()],request=request)
        self.assertEqual(result["status"],"unsupported");self.assertFalse(self.backend.calls)


class EvoRuntimeTests(unittest.TestCase):
    def test_cli_budget_before_loading(self):
        for value in ["0","121","nan","inf","-1"]:
            with self.subTest(value=value),redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                main(["--data-dir","unused","--output-dir","unused","--model-dir","unused",
                      "--model-manifest","unused","--timeout-seconds",value])

    def test_cli_help_is_model_free(self):
        proc=subprocess.run([sys.executable,"-m","midprojectrag.evo_harness.cli","--help"],capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stderr);self.assertIn("--synthetic-corpus",proc.stdout)

    def test_paths_no_escape_no_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/"private").mkdir();(root/"private/existing").mkdir()
            with self.assertRaises(ValueError):_private(root/"public",root)
            with self.assertRaises(FileExistsError):_private(root/"private/existing",root,new=True)
            self.assertEqual(_private(root/"private/new",root,new=True),(root/"private/new").resolve())

    def test_local_model_missing_no_download(self):
        with tempfile.TemporaryDirectory() as folder,self.assertRaises(Unsupported):
            verify_local_model(Path(folder)/"missing",Path(folder)/"manifest.json")

    def test_manifest_cannot_name_other_model(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=root/"manifest.json";p.write_text(json.dumps({"repo":"other/model","files":{}}))
            with self.assertRaises(Unsupported):verify_local_model(root,p)

    def test_mismatched_policy_and_answer_profile_rejected(self):
        from midprojectrag.evo_harness.runner import EpisodeRunner
        a,b=FakeBackend(),FakeBackend();b.identity=replace(b.identity,revision="c"*40)
        with self.assertRaises(ValueError):EpisodeRunner(synthetic_tools(),LLMPolicy(a),AnswerComposer(b))


if __name__=="__main__":unittest.main()
