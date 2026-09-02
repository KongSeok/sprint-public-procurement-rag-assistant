from __future__ import annotations

import copy
import unittest

from midprojectrag.evidence import Evidence, EvidenceStore
from midprojectrag.offline_harness.training import (
    export_training_rows,
    request_fingerprint,
    validate_evolution_candidate,
)
from midprojectrag.orchestration import Harness, QueryPlan, Slot, Verification
from midprojectrag.orchestration.artifacts import digest, trace_record


def _request(*, question: str = "지원 금액은?") -> dict:
    return {
        "schema_version": "1.0",
        "request_id": "request-1",
        "question": question,
        "history": [
            {"turn_id": "turn-1", "role": "user", "content": "첫 질문"},
            {"turn_id": "turn-2", "role": "assistant", "content": "문서에서 확인해 볼게요."},
        ],
        "document_scope": {
            "mode": "explicit",
            "doc_ids": ["doc_000000000000000000000001"],
        },
        "options": {"max_citations": 5},
    }


class _Retriever:
    def __init__(self, evidence: Evidence):
        self.evidence = evidence

    def search(self, query: str, *, limit: int, allowed_doc_ids):
        return (self._candidate(),)

    def _candidate(self):
        from midprojectrag.retrieval import Candidate

        return Candidate(self.evidence.evidence_id, 1.0, "fixture", 1)


class _Verifier:
    def __init__(self, evidence: Evidence):
        self.evidence = evidence

    def verify(self, slot, evidence):
        return Verification((self.evidence.evidence_id,))


def _fixture(*, status: str | None = None, runtime: dict | None = None) -> tuple[EvidenceStore, dict]:
    doc_id = "doc_000000000000000000000001"
    block_id = "block_000000000000000000000001"
    page = Evidence.create(
        doc_id=doc_id,
        page=1,
        kind="page",
        text="지원 금액은 1억원입니다.",
        source_block_ids=(block_id,),
    )
    child = Evidence.create(
        doc_id=doc_id,
        page=1,
        kind="text",
        text="지원 금액은 1억원입니다.",
        source_block_ids=(block_id,),
        parent_id=page.evidence_id,
    )
    store = EvidenceStore((page, child))
    request = _request()
    plan = QueryPlan(
        request["question"],
        (Slot("amount", "지원 금액", doc_id),),
        "fact",
        tuple((turn["role"], turn["content"]) for turn in request["history"]),
        frozenset({doc_id}),
    )
    harness = Harness(
        store=store,
        retriever=_Retriever(child),
        verifier=_Verifier(child),
    )
    result = harness.run(plan)
    if status is not None:
        # The fixture is otherwise a valid READY trace. This is used only for
        # fail-closed terminal-status tests; the hash is resealed below.
        result_dict = {
            "status": status,
            "reason": result.reason,
            "context": [item.to_dict() for item in result.context],
            "required_ids": list(result.required_ids),
            "state": result.state,
            "events": result.events,
            "elapsed_ms": result.elapsed_ms,
        }
        trace_result = result_dict
    else:
        trace_result = result
    trace = trace_record(
        request=request,
        store=store,
        config=harness.config,
        policy_id=harness.policy.policy_id,
        result=trace_result,
        runtime=runtime,
    )
    return store, trace


def _resign(trace: dict) -> dict:
    trace["trace_sha256"] = digest({key: value for key, value in trace.items() if key != "trace_sha256"})
    return trace


class TrainingExportTests(unittest.TestCase):
    def setUp(self):
        self.store, self.trace = _fixture()
        self.fingerprint = request_fingerprint(self.trace["request"])
        self.training = frozenset({self.fingerprint})
        self.heldout = frozenset({"a" * 64})

    def export(self, trace=None, **kwargs):
        return export_training_rows(
            self.trace if trace is None else trace,
            store=self.store,
            training_allowlist=kwargs.pop("training_allowlist", self.training),
            heldout_fingerprints=kwargs.pop("heldout_fingerprints", self.heldout),
            **kwargs,
        )

    def test_fingerprint_ignores_metadata_but_preserves_ordered_content(self):
        first = _request(question="  지원   금액은?\n")
        second = copy.deepcopy(first)
        second["request_id"] = "a-different-request"
        second["options"] = {"max_citations": 1}
        second["document_scope"] = {"mode": "all", "doc_ids": []}
        second["history"][0]["turn_id"] = "different-turn"
        second["question"] = "지원 금액은?"
        self.assertEqual(request_fingerprint(first), request_fingerprint(second))

        reordered = copy.deepcopy(first)
        reordered["history"].reverse()
        self.assertNotEqual(request_fingerprint(first), request_fingerprint(reordered))

    def test_valid_export_is_preparation_only_and_rl_reward_is_unset(self):
        result = self.export()
        self.assertTrue(result["preparation_only"])
        self.assertFalse(result["ready_for_training"])
        self.assertFalse(result["official"])
        self.assertEqual(result["trace_sha256"], self.trace["trace_sha256"])
        self.assertEqual(result["evidence_sha256"], self.trace["evidence_sha256"])
        self.assertEqual(result["manifest_sha256"], result["split_manifest_sha256"])
        self.assertTrue(result["sft_rows"])
        self.assertEqual(len(result["sft_rows"]), len(result["rl_rows"]))
        self.assertTrue(all(row["reward"] is None for row in result["rl_rows"]))

    def test_v2_export_keeps_composite_runtime_configuration_seal(self):
        runtime = {
            "retrieval": {"lane": "legacy_page", "index_sha256": "b" * 64},
            "model": "test-local-model",
            "visual_available": False,
        }
        _, trace = _fixture(runtime=runtime)
        self.assertEqual(trace["schema_version"], "evidence-harness-trace-v2")
        result = self.export(trace)
        self.assertEqual(result["config_sha256"], digest(trace["config"]))
        self.assertNotEqual(result["config_sha256"], digest(trace["config"]["harness"]))
        self.assertEqual(len(result["sft_rows"]), len(self.export()["sft_rows"]))

    def test_v2_runtime_tampering_cannot_bypass_either_seal(self):
        _, trace = _fixture(runtime={"retrieval": {"index_sha256": "b" * 64}})
        trace["config"]["runtime"]["retrieval"]["index_sha256"] = "c" * 64
        with self.assertRaisesRegex(ValueError, "trace_sha256_mismatch"):
            self.export(trace)
        _resign(trace)
        with self.assertRaisesRegex(ValueError, "training_config_seal_mismatch"):
            self.export(trace)

    def test_v2_harness_configuration_and_runtime_shapes_are_validated(self):
        for mutation in ("harness_missing", "harness_list", "harness_budget", "runtime_list", "extra_key"):
            _, trace = _fixture(runtime={})
            if mutation == "harness_missing":
                del trace["config"]["harness"]
            elif mutation == "harness_list":
                trace["config"]["harness"] = []
            elif mutation == "harness_budget":
                trace["config"]["harness"]["max_actions"] = True
            elif mutation == "runtime_list":
                trace["config"]["runtime"] = []
            else:
                trace["config"]["unexpected"] = "value"
            trace["config_sha256"] = digest(trace["config"])
            _resign(trace)
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, "training_config_invalid"):
                self.export(trace)

    def test_list_route_is_explicitly_not_an_action_training_trajectory(self):
        _, trace = _fixture(runtime={"route": "list"})
        trace["result"] = {
            "enumeration": {"complete": True},
            "answer": {},
            "status": "READY",
            "reason": "enumeration_complete",
            "context": trace["result"]["context"],
            "required_ids": trace["result"]["required_ids"],
        }
        _resign(trace)
        with self.assertRaisesRegex(ValueError, "list_trajectory_not_trainable"):
            self.export(trace)

    def test_request_must_be_allowlisted_and_disjoint_from_heldout(self):
        with self.assertRaisesRegex(ValueError, "request_not_allowlisted"):
            self.export(training_allowlist=frozenset({"b" * 64}))
        with self.assertRaisesRegex(ValueError, "heldout_training_trace"):
            self.export(
                training_allowlist=frozenset({"b" * 64}),
                heldout_fingerprints=frozenset({self.fingerprint}),
            )
        with self.assertRaisesRegex(ValueError, "training_heldout_overlap"):
            self.export(heldout_fingerprints=frozenset({self.fingerprint, "a" * 64}))

    def test_synthetic_trace_requires_explicit_opt_in(self):
        trace = copy.deepcopy(self.trace)
        trace["synthetic"] = True
        _resign(trace)
        with self.assertRaisesRegex(ValueError, "synthetic_training_trace_forbidden"):
            self.export(trace)
        result = self.export(trace, allow_synthetic=True)
        self.assertTrue(result["synthetic"])
        self.assertFalse(result["official"])

    def test_trace_and_evidence_seals_are_checked(self):
        trace = copy.deepcopy(self.trace)
        trace["trace_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "trace_sha256_mismatch"):
            self.export(trace)

        trace = copy.deepcopy(self.trace)
        trace["evidence_sha256"] = "0" * 64
        _resign(trace)
        with self.assertRaisesRegex(ValueError, "training_evidence_seal_mismatch"):
            self.export(trace)

    def test_official_experience_and_terminal_failure_traces_are_rejected(self):
        for field, value, reason in (
            ("official", True, "official_or_online_experience_trace_forbidden"),
            ("experience_enabled", True, "official_or_online_experience_trace_forbidden"),
        ):
            trace = copy.deepcopy(self.trace)
            trace[field] = value
            _resign(trace)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, reason):
                self.export(trace)

        for status in ("ERROR", "ABSTAINED"):
            _, trace = _fixture(status=status)
            with self.subTest(status=status), self.assertRaisesRegex(ValueError, "error_trajectory_not_training_ready"):
                self.export(trace)

    def test_missing_event_snapshot_and_unknown_evidence_fail_closed(self):
        trace = copy.deepcopy(self.trace)
        event = trace["result"]["events"][0]
        event["state_before"] = None
        _resign(trace)
        with self.assertRaisesRegex(ValueError, "trajectory_state_missing"):
            self.export(trace)

        trace = copy.deepcopy(self.trace)
        trace["result"]["required_ids"].append("ev_" + "f" * 24)
        _resign(trace)
        with self.assertRaisesRegex(ValueError, "trajectory_unknown_evidence"):
            self.export(trace)

    def test_candidate_batch_cannot_exceed_configured_limit(self):
        trace = copy.deepcopy(self.trace)
        trace["config"]["max_candidates"] = 1
        trace["config_sha256"] = digest(trace["config"])
        first_event = trace["result"]["events"][0]
        page_id = self.store.all()[0].evidence_id
        first_event["candidate_ids"].append(page_id)
        first_event["pre_rerank_ids"].append(page_id)
        _resign(trace)
        with self.assertRaisesRegex(ValueError, "trajectory_candidate_limit"):
            self.export(trace)

    def test_illegal_action_is_not_a_training_target(self):
        trace = copy.deepcopy(self.trace)
        event = trace["result"]["events"][0]
        event["action"]["kind"] = "stop"
        event["action"]["slot_key"] = None
        event["action"]["query"] = None
        event["action"]["evidence_id"] = None
        _resign(trace)
        with self.assertRaisesRegex(ValueError, "trajectory_illegal_action"):
            self.export(trace)


class EvolutionGateTests(unittest.TestCase):
    def manifest(self, **changes):
        value = {
            "schema_version": "evidence-harness-evolution-manifest-v1",
            "policy_code_sha256": "1" * 64,
            "evidence_sha256": "2" * 64,
            "gold_sha256": "3" * 64,
            "judge_sha256": "4" * 64,
            "config_sha256": "5" * 64,
        }
        value.update(changes)
        return value

    def test_policy_change_keeps_immutable_seals_and_stays_unapproved(self):
        result = validate_evolution_candidate(
            self.manifest(), self.manifest(policy_code_sha256="a" * 64)
        )
        self.assertTrue(result["preparation_only"])
        self.assertTrue(result["eligible_for_offline_evaluation"])
        self.assertFalse(result["approved_for_runtime"])
        self.assertEqual(result["readiness"], "sealed_candidate_requires_external_evaluation")
        self.assertTrue(result["policy_changed"])

    def test_evidence_gold_judge_or_config_change_is_rejected(self):
        for field in ("evidence_sha256", "gold_sha256", "judge_sha256", "config_sha256"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "evolution_immutable_artifact_changed"):
                validate_evolution_candidate(self.manifest(), self.manifest(**{field: "a" * 64}))

    def test_candidate_manifest_is_hash_only_and_not_executed(self):
        candidate = self.manifest(policy_code_sha256="/tmp/candidate.py")
        with self.assertRaisesRegex(ValueError, "evolution_manifest_hash_invalid"):
            validate_evolution_candidate(self.manifest(), candidate)


if __name__ == "__main__":
    unittest.main()
