"""Training/leakage contracts and typed evidence lifecycle; no external model calls."""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from midprojectrag.evo_harness.runtime import compose_runtime, synthetic_tools
from midprojectrag.evo_harness.state import Budgets, InvalidAction, action_from_json
from midprojectrag.evo_harness.training import (
    EXCLUSION_SCHEMA, SFT_SCHEMA, TRAINING_CASE_SCHEMA, build_exclusion_manifest,
    case_fingerprints, exclusion_collision, freeze_splits, reject_forbidden_training_fields,
    freeze_sft_examples, reward_episode, sft_examples_from_trajectory, training_backend_blockers, training_environment_preflight,
    validate_exclusion_manifest,
)
from tests.test_evo_harness import FakeBackend, REQUEST, search, read, finish


def training_case(case_id="train-1", *, split="train", group="group-a", question="What is Gamma budget?",
                  docs=None, conversation=None):
    request={"question":question,"document_scope":{"mode":"explicit","doc_ids":list(docs or ["gamma"])}}
    row={"schema_version":TRAINING_CASE_SCHEMA,"case_id":case_id,"group_id":group,
         "task_type":"single_doc" if len(request["document_scope"]["doc_ids"])==1 else "multi_doc_compare",
         "split":split,"question":question,"request":request}
    if conversation:
        row["conversation_id"]=conversation
    return row


class TypedEvidenceTests(unittest.TestCase):
    def test_current_candidate_and_read_namespaces_are_disjoint(self):
        tools=synthetic_tools();episode=tools.begin(REQUEST);budget=Budgets()
        found=tools.search(episode,{"query":"budget","doc_ids":None,"limit":2},budget,lambda:100)
        self.assertEqual([row["id"] for row in found["candidates"]],["cand:e1","cand:e2"])
        with self.assertRaisesRegex(InvalidAction,"read_evidence_handle_required"):
            tools.packet(episode,["cand:e1"])
        read_result=tools.read(episode,{"evidence_ids":["cand:e1"]},budget,lambda:100)
        self.assertEqual(read_result["read"],["ev:e1"])
        self.assertEqual(tools.packet(episode,["ev:e1"])[0]["doc_id"],"alpha")
        for invalid in ["e1", next(iter(episode.candidates)), "hist:t1:e1", "alpha"]:
            with self.subTest(invalid=invalid),self.assertRaises(InvalidAction):
                episode.reference(invalid)

    def test_history_is_projected_without_mutating_canonical_citations(self):
        tools=synthetic_tools();seed=next(e for e in tools.store.evidence if e.doc_id=="beta")
        request={"question":"And its period?","history":[{"turn_id":"t-old","role":"assistant","content":"Beta cited.",
                 "cited_doc_ids":["beta"],"cited_evidence_ids":[seed.evidence_id]}]}
        before=deepcopy(request);episode=tools.begin(request,follow_up=True);view=episode.observation(Budgets())
        self.assertEqual(view["history"][0]["cited_evidence_ids"],["hist:t1:e1"])
        self.assertEqual(episode.request["history"][0]["cited_evidence_ids"],[seed.evidence_id])
        self.assertEqual(request,before)
        with self.assertRaisesRegex(InvalidAction,"candidate_handle_required"):
            action_from_json(json.dumps({"tool":"read","arguments":{"evidence_ids":["hist:t1:e1"]}}))

    def test_action_wire_rejects_lifetime_confusion(self):
        invalid=[
            {"tool":"read","arguments":{"evidence_ids":["e1"]}},
            {"tool":"read","arguments":{"evidence_ids":["ev:e1"]}},
            {"tool":"finish","arguments":{"status":"answered","evidence_ids":["cand:e1"],"unresolved":[]}},
            {"tool":"inspect_image","arguments":{"evidence_id":"ev:e1","question":"read"}},
        ]
        for row in invalid:
            with self.subTest(row=row),self.assertRaises(InvalidAction):action_from_json(json.dumps(row))


class TrainingLeakageTests(unittest.TestCase):
    def setUp(self):
        self.eval_cases=[{"case_id":"gold-1","group_id":"gold-group","task_type":"multi_doc_compare",
                          "question":"Compare Alpha and Beta.","conversation":{"conversation_id":"conv-gold"},
                          "gold":{"required_doc_ids":["alpha","beta"]}}]
        self.exclusion=build_exclusion_manifest(self.eval_cases,source_id="mini131-history",source_sha256="a"*64)

    def test_exclusion_manifest_is_hash_only_and_detects_all_exact_axes(self):
        validate_exclusion_manifest(self.exclusion);self.assertEqual(self.exclusion["schema_version"],EXCLUSION_SCHEMA)
        self.assertNotIn("Compare Alpha",json.dumps(self.exclusion))
        probes=[
            training_case(question="  COMPARE alpha and beta. ",group="new",docs=["x"]),
            training_case(question="different",group="gold-group",docs=["x"]),
            training_case(question="different",group="new",docs=["x"],conversation="conv-gold"),
            training_case(question="different",group="new",docs=["beta","alpha"]),
        ]
        for probe in probes:
            self.assertTrue(exclusion_collision(probe,self.exclusion))

    def test_recursive_gold_projection_is_forbidden(self):
        for value in [{"gold":{"answer":"x"}},{"request":{"metadata":{"expected_answer":"x"}}},
                      {"rows":[{"judge_score":1}]}]:
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,"training_gold_projection_forbidden"):
                reject_forbidden_training_fields(value)

    def test_freeze_rejects_exclusion_and_cross_split_leakage(self):
        with self.assertRaisesRegex(ValueError,"training_case_evaluation_leakage"):
            freeze_splits([training_case(question="Compare Alpha and Beta.",docs=["alpha","beta"])],exclusion=self.exclusion)
        cases=[training_case("a",split="train",group="shared",question="a"),
               training_case("b",split="dev",group="shared",question="b")]
        with self.assertRaisesRegex(ValueError,"training_split_leakage"):freeze_splits(cases)
        cases=[training_case("a",split="train",group="a",question="SAME"),
               training_case("b",split="dev",group="b",question=" same ")]
        with self.assertRaisesRegex(ValueError,"training_split_leakage"):freeze_splits(cases)

    def test_clean_three_way_split_has_stable_hashes(self):
        cases=[training_case("t",split="train",group="gt",question="train q"),
               training_case("d",split="dev",group="gd",question="dev q"),
               training_case("h",split="sealed_holdout",group="gh",question="held q")]
        one=freeze_splits(cases);two=freeze_splits(deepcopy(cases))
        self.assertEqual(one["receipt"],two["receipt"])
        self.assertEqual([one["receipt"]["splits"][s]["count"] for s in ("train","dev","sealed_holdout")],[1,1,1])


class SFTAndRewardTests(unittest.TestCase):
    def test_trajectory_exports_only_completed_valid_policy_actions(self):
        backend=FakeBackend([search(),read("e1"),finish("e1")])
        result=compose_runtime(backend,synthetic_tools()).run(REQUEST,record_trajectory=True)
        case=training_case(question=REQUEST["question"],docs=["alpha","beta"])
        case["request"]=deepcopy(REQUEST);case["task_type"]="multi_doc_compare"
        rows=sft_examples_from_trajectory(result,case)
        self.assertEqual(len(rows),3);self.assertTrue(all(row["schema_version"]==SFT_SCHEMA for row in rows))
        self.assertEqual([json.loads(row["completion"][0]["content"])["tool"] for row in rows],["search","read","finish"])
        self.assertFalse(any("final answer" in row["completion"][0]["content"].lower() for row in rows))
        self.assertTrue(all(row["metadata"]["trajectory_id"]==rows[0]["metadata"]["trajectory_id"] for row in rows))

    def test_invalid_action_is_not_a_positive_sft_target(self):
        backend=FakeBackend(["bad-json",search(),read("e1"),finish("e1")])
        result=compose_runtime(backend,synthetic_tools()).run(REQUEST,record_trajectory=True)
        case=training_case(question=REQUEST["question"],docs=["alpha","beta"]);case["request"]=deepcopy(REQUEST);case["task_type"]="multi_doc_compare"
        rows=sft_examples_from_trajectory(result,case)
        self.assertEqual([json.loads(row["completion"][0]["content"])["tool"] for row in rows],["search","read","finish"])

    def test_sealed_holdout_cannot_export_sft(self):
        result=compose_runtime(FakeBackend([finish(status="abstained")]),synthetic_tools()).run(REQUEST,record_trajectory=True)
        case=training_case(split="sealed_holdout",question=REQUEST["question"]);case["request"]=deepcopy(REQUEST)
        with self.assertRaisesRegex(ValueError,"sealed_holdout"):sft_examples_from_trajectory(result,case)

    def test_efficiency_reward_never_pays_failure(self):
        failed=reward_episode(success=False,citation_success=False,valid_abstention=False,policy_calls=1,search_calls=0,total_tokens=1)
        passed=reward_episode(success=True,citation_success=True,valid_abstention=False,policy_calls=1,search_calls=1,total_tokens=100)
        self.assertEqual(failed["components"]["efficiency"],0.0);self.assertGreater(passed["components"]["efficiency"],0.0)
        self.assertGreater(passed["total"],failed["total"])

    def test_qlora_preflight_requires_bitsandbytes_and_backend_receipt(self):
        versions={"transformers":"5.2.1","trl":"1.8.0","peft":"0.20.0","datasets":"4.0.0","accelerate":"1.0.0","torch":"2.8.0"}
        def version(name):
            if name=="bitsandbytes": raise __import__("importlib").metadata.PackageNotFoundError(name)
            return versions[name]
        with patch("midprojectrag.evo_harness.training.metadata.version",side_effect=version):
            env=training_environment_preflight(mode="qlora4")
        self.assertIn("missing:bitsandbytes",env["reasons"])
        self.assertEqual(training_backend_blockers(mode="qlora4",environment=env,receipt=None),["qlora_backend_receipt_missing"])

    def test_sft_freeze_is_stable_train_only_and_deduplicates(self):
        backend=FakeBackend([search(),read("e1"),finish("e1")])
        result=compose_runtime(backend,synthetic_tools()).run(REQUEST,record_trajectory=True)
        case=training_case(question=REQUEST["question"],docs=["alpha","beta"]);case["request"]=deepcopy(REQUEST);case["task_type"]="multi_doc_compare"
        rows=sft_examples_from_trajectory(result,case)
        one=freeze_sft_examples([("teacher",rows),("live",[deepcopy(rows[0])])])
        two=freeze_sft_examples([("teacher",deepcopy(rows)),("live",[deepcopy(rows[0])])])
        self.assertEqual(one,two);self.assertEqual(one["receipt"]["input_rows"],4);self.assertEqual(one["receipt"]["train_rows"],3);self.assertEqual(one["receipt"]["exact_duplicate_rows_removed"],1)
        bad=deepcopy(rows[0]);bad["metadata"]["split"]="dev"
        with self.assertRaisesRegex(ValueError,"training_sft_train_only"): freeze_sft_examples([("bad",[bad])])

    def test_environment_preflight_is_metadata_only(self):
        versions={"transformers":"5.2.1","trl":"1.8.0","peft":"0.20.0","datasets":"4.0.0","accelerate":"1.0.0","torch":"2.8.0"}
        with patch("midprojectrag.evo_harness.training.metadata.version",side_effect=lambda name:versions[name]):
            result=training_environment_preflight()
        self.assertTrue(result["compatible"]);self.assertEqual(result["versions"]["transformers"],"5.2.1")
        versions["transformers"]="4.57.0"
        with patch("midprojectrag.evo_harness.training.metadata.version",side_effect=lambda name:versions[name]):
            self.assertIn("transformers_lt_5_2",training_environment_preflight()["reasons"])


class TrainingCLITests(unittest.TestCase):
    def test_sft_preflight_requires_matching_base_identity_receipt(self):
        root=Path(__file__).resolve().parents[1]
        receipt=root/"resources/data_refined/private/training/evo35-3e-20260910/base-identity-receipt.json"
        done=subprocess.run([sys.executable,str(root/"scripts/train_harness_sft.py"),"--config",str(root/"configs/training/evo35-sft-v1.json"),"--base-identity-receipt",str(receipt),"--preflight"],cwd=root,env={**dict(__import__("os").environ),"PYTHONPATH":str(root/"src")},text=True,capture_output=True,timeout=20)
        self.assertIn(done.returncode,(0,2),done.stderr)
        payload=json.loads(done.stdout)
        self.assertNotIn("base_model_revision_unfrozen",payload["blockers"])
        self.assertNotIn("base_identity_receipt_missing",payload["blockers"])

    def test_serving_environment_sft_preflight_does_not_train(self):
        root=Path(__file__).resolve().parents[1]
        done=subprocess.run([sys.executable,str(root/"scripts/train_harness_sft.py"),"--config",str(root/"configs/training/evo35-sft-v1.json"),"--preflight"],cwd=root,env={**dict(__import__("os").environ),"PYTHONPATH":str(root/"src")},text=True,capture_output=True,timeout=20)
        self.assertIn(done.returncode,(0,2),done.stderr)
        payload=json.loads(done.stdout);self.assertFalse(payload["ready"])
        self.assertIn("base_identity_receipt_missing",payload["blockers"])
        self.assertNotIn("completed",payload)


if __name__=="__main__":unittest.main()
