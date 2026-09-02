import contextlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from midprojectrag.answering.evidence_adapter import EvidenceAnswerAdapter
from midprojectrag.evaluation import validate_response
from midprojectrag.orchestration import Harness, HarnessConfig, QueryPlan, Slot, Verification
from midprojectrag.orchestration.artifacts import digest, trace_record, write_private_json, read_json
from midprojectrag.orchestration.cli import ByteUpperCounter, main
from midprojectrag.orchestration.pipeline import EvidenceHarnessPipeline
from tests.orchestration.test_controller import fixture, ScriptedRetriever, ScriptedVerifier
from tests.orchestration.test_llm import request


class SyntheticGenerator:
    model = "synthetic-fixture-only"
    requires_budget = False
    max_output_tokens = 100
    def __init__(self): self.prompts = []
    def generate(self, prompt):
        self.prompts.append(prompt)
        ids = re.findall(r'<SOURCE chunk_id="(chunk_[a-f0-9]+)"', prompt)
        return {"status": "answered", "answer": "Synthetic fixture answer", "citation_chunk_ids": ids, "abstention_reason": None}, 100, 20
    def estimate_cost(self, inputs, outputs): return Decimal(0)


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.store, _, self.children, _ = fixture()
    def test_end_to_end_standard_response_and_private_trace(self):
        child = self.children[0]
        req = request()
        plan = QueryPlan(req["question"], (Slot("budget", "budget", child.doc_id),), "followup",
                         (("user", "첫 문서"),), frozenset({child.doc_id}))
        harness = Harness(store=self.store, retriever=ScriptedRetriever([[child]]), verifier=ScriptedVerifier([Verification((child.evidence_id,))]))
        generator = SyntheticGenerator()
        pipeline = EvidenceHarnessPipeline(harness=harness, answer_adapter=EvidenceAnswerAdapter(generator=generator, counter=ByteUpperCounter()))
        result = pipeline.query(req, plan=plan)
        self.assertEqual(result.answer.response["status"], "answered")
        self.assertFalse(validate_response(result.answer.response))
        self.assertIn("첫 문서", generator.prompts[0])
        self.assertEqual(set(result.answer.citation_map.values()), {child.evidence_id})
        trace = trace_record(request=req, store=self.store, config=harness.config, policy_id=harness.policy.policy_id, result=result, synthetic=True)
        self.assertEqual(trace["trace_sha256"], digest({k: v for k, v in trace.items() if k != "trace_sha256"}))
        self.assertFalse(trace["official"])
        for event in trace["result"]["harness"]["events"]:
            self.assertIsNotNone(event["state_before"])
            self.assertIsNotNone(event["state_after"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "private"
            path = root / "trace.json"
            write_private_json(path, trace, private_root=root)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(read_json(path)["trace_sha256"], trace["trace_sha256"])
            with self.assertRaises(FileExistsError): write_private_json(path, trace, private_root=root)
    def test_scope_or_history_mismatch_rejected_before_calls(self):
        h = Harness(store=self.store, retriever=ScriptedRetriever([]), verifier=ScriptedVerifier([]))
        g = SyntheticGenerator()
        p = EvidenceHarnessPipeline(harness=h, answer_adapter=EvidenceAnswerAdapter(generator=g, counter=ByteUpperCounter()))
        with self.assertRaises(ValueError): p.query(request(), plan=QueryPlan(request()["question"], (Slot("a", "x"),)))
        self.assertEqual(g.prompts, [])
    def test_no_support_never_generates(self):
        req = request()
        child = self.children[0]
        plan = QueryPlan(req["question"], (Slot("a", "x"),), history=(("user", "첫 문서"),), allowed_doc_ids=frozenset({child.doc_id}))
        h = Harness(store=self.store, retriever=ScriptedRetriever([[]]), verifier=ScriptedVerifier([]))
        g = SyntheticGenerator()
        result = EvidenceHarnessPipeline(harness=h, answer_adapter=EvidenceAnswerAdapter(generator=g, counter=ByteUpperCounter())).query(req, plan=plan)
        self.assertEqual(result.answer.response["status"], "abstained")
        self.assertFalse(g.prompts)
    def test_harness_provider_and_scope_errors_remain_standard_errors(self):
        class TimeoutRetriever:
            def search(self, query, *, limit, allowed_doc_ids):
                raise TimeoutError("private provider message must not escape")

        req = request()
        child = self.children[0]
        plan = QueryPlan(req["question"], (Slot("budget", "budget", child.doc_id),),
                         history=(("user", "첫 문서"),), allowed_doc_ids=frozenset({child.doc_id}))
        for case, retriever in (
            ("provider_timeout", TimeoutRetriever()),
            ("out_of_scope_candidate", ScriptedRetriever([[self.children[1]]])),
        ):
            with self.subTest(case=case):
                verifier = ScriptedVerifier([])
                harness = Harness(store=self.store, retriever=retriever, verifier=verifier)
                generator = SyntheticGenerator()
                pipeline = EvidenceHarnessPipeline(
                    harness=harness,
                    answer_adapter=EvidenceAnswerAdapter(generator=generator, counter=ByteUpperCounter()),
                )
                result = pipeline.query(req, plan=plan)
                response = result.answer.response
                self.assertEqual(result.harness.status, "ERROR")
                self.assertEqual(response["status"], "error")
                self.assertEqual(response["error"]["code"], result.harness.reason)
                self.assertEqual(result.answer.terminal_reason, result.harness.reason)
                self.assertEqual(result.harness.reason, "provider_or_contract_error")
                self.assertEqual(response["answer"], "")
                self.assertEqual(response["citations"], [])
                self.assertIsNone(response["abstention"])
                self.assertEqual(validate_response(response), [])
                self.assertNotIn("private provider message", repr(response))
                self.assertFalse(generator.prompts)
                self.assertFalse(verifier.calls)
    def test_visual_plan_is_capability_gap_until_reader_exists(self):
        req = request()
        child = self.children[0]
        plan = QueryPlan(req["question"], (Slot("a", "visual budget", child.doc_id),), "visual",
                         (("user", "첫 문서"),), frozenset({child.doc_id}))
        h = Harness(store=self.store, retriever=ScriptedRetriever([[child]]), verifier=ScriptedVerifier([Verification((child.evidence_id,))]))
        g = SyntheticGenerator()
        result = EvidenceHarnessPipeline(harness=h, answer_adapter=EvidenceAnswerAdapter(generator=g, counter=ByteUpperCounter())).query(req, plan=plan)
        self.assertEqual(result.answer.terminal_reason, "capability_gap")
        self.assertFalse(g.prompts)
    def test_private_path_symlink_and_nonfinite_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "private"
            root.mkdir()
            outside = Path(tmp) / "outside"
            outside.mkdir()
            (root / "escape").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError): write_private_json(root / "escape" / "trace.json", {}, private_root=root)
            with self.assertRaises(ValueError): write_private_json(outside / "trace.json", {}, private_root=root)
            with self.assertRaises(ValueError): write_private_json(root / "nan.json", {"v": float("nan")}, private_root=root)
    def test_cli_sanitizes_paths_and_bad_inputs(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["run", "--evidence", "/private/sensitive-missing.json", "--request", "/private/no.json", "--output", "/public/unsafe.json"])
        self.assertEqual(code, 2)
        self.assertNotIn("sensitive", out.getvalue())
        self.assertEqual(json.loads(out.getvalue())["status"], "error")
    def test_module_entrypoint(self):
        result = subprocess.run([sys.executable, "-m", "midprojectrag.orchestration.cli", "--help"], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertIn("opt-in", result.stdout)
    def test_runtime_does_not_import_training_or_gold(self):
        import ast
        root = Path(__file__).parents[2] / "src" / "midprojectrag" / "orchestration"
        for path in root.glob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    self.assertNotIn("offline_harness", node.module)
                    if node.module == "midprojectrag.evaluation":
                        self.assertEqual({n.name for n in node.names}, {"validate_request"})


if __name__ == "__main__": unittest.main()
