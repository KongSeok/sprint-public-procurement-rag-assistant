"""Focused adapter/timing checks; no model loading or real inference."""
from __future__ import annotations

import importlib.util
import inspect
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import urllib.request

from midprojectrag.orchestration import HarnessRuntimeBinding
from midprojectrag.retrieval.fusion import HybridChildRetriever
from tests.test_retrieval_obligations import (
    _SyntheticLane,
    _calls,
    _clock,
    _planner,
    _store,
)

RUNNER = Path(__file__).resolve().parents[1] / "scripts/run_controller_quick_qa.py"
spec = importlib.util.spec_from_file_location("quickqa_under_test", RUNNER)
quickqa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quickqa)


class QuickQaTests(unittest.TestCase):
    def store(self, text="0123456789abcdefghij", start=12, end=16):
        locator = SimpleNamespace(char_range=(start, end), to_dict=lambda: {"char_range": [start, end]})
        seed = SimpleNamespace(doc_id="d1", evidence_id="e1", parent_id="p1", locator=locator, text=text[start:end])
        parent = SimpleNamespace(doc_id="d1", text=text, content_sha256="a" * 64)
        return SimpleNamespace(get=lambda key: seed, parent=lambda key: parent), seed, parent

    def public_case(self, tmp, *, dense_mode="valid", lexical_mode="valid"):
        store = _store(doc_ids=("doc-a",), chunks_per_doc=3)
        specs = tuple(sorted(
            ((item.evidence_id, item.doc_id) for item in store.evidence),
            reverse=True,
        ))
        dense_log = Path(tmp) / "dense.log"
        lexical_log = Path(tmp) / "lexical.log"
        retriever = HybridChildRetriever(
            store,
            _SyntheticLane(
                lane="dense",
                bundle_sha256=store.bundle_sha256,
                candidate_specs=specs,
                call_log_path=str(dense_log),
                mode=dense_mode,
            ),
            _SyntheticLane(
                lane="lexical",
                bundle_sha256=store.bundle_sha256,
                candidate_specs=specs,
                call_log_path=str(lexical_log),
                mode=lexical_mode,
            ),
        )
        runtime = HarnessRuntimeBinding.for_test(
            store=store, retriever=retriever, clock=_clock
        )
        loaded = {
            "env": {"store": store, "runtime": runtime},
            "planner": _planner(("doc-a",)),
            "identity": {"controller_config": None},
        }
        request = {
            "question": "사업 예산은 얼마인가?",
            "document_scope": {"mode": "explicit", "doc_ids": ["doc-a"]},
        }
        return loaded, request, specs, dense_log, lexical_log

    def test_hotline_public_pipeline_reaches_answer_adapter_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded, request, specs, dense_log, lexical_log = self.public_case(tmp)
            generation = []

            def generate(prompt):
                generation.append(prompt)
                return {
                    "status": "answered",
                    "answer": "예산 근거가 있습니다.",
                    "citations": ["S1"],
                }, 10, 4

            loaded["generator"] = SimpleNamespace(generate=generate)
            result = quickqa.execute_question(
                request,
                loaded,
                quickqa.Timer(),
                controller=quickqa.fixed_public_pipeline,
            )

            trajectory = result["trajectory"]
            expected_candidates = {evidence_id for evidence_id, _doc_id in specs}
            quota = loaded["env"]["config"].max_context_targets_per_obligation
            expected_seeds = sorted(expected_candidates)[:quota]
            self.assertEqual((_calls(dense_log), _calls(lexical_log)), (("dense",), ("lexical",)))
            self.assertEqual(set(trajectory["candidate_evidence_ids"]), expected_candidates)
            self.assertEqual(trajectory["parent_seed_evidence_ids"], expected_seeds)
            self.assertEqual(result["context"]["evidence_id"], expected_seeds[0])
            seed = loaded["env"]["store"].get(expected_seeds[0])
            parent = loaded["env"]["store"].parent(seed.parent_id)
            self.assertEqual(result["context"]["text"], parent.text)
            self.assertEqual(
                result["context"]["parent_context_receipt_sha256s"],
                [trajectory["selected_parent_receipt"]["receipt_sha256"]],
            )
            self.assertEqual(len(generation), 1)
            self.assertEqual(result["response"]["citations"], ["S1"])
            self.assertEqual(
                (trajectory["classification"], trajectory["controller_executed"],
                 trajectory["completed_e1"], trajectory["verifier_executed"]),
                ("fixed_public_pipeline", False, False, False),
            )

    def test_hotline_empty_or_provider_failure_never_generates(self):
        cases = (
            ("empty", "empty", "hotline_fusion_candidates_required", (("dense",), ("lexical",))),
            ("provider_error", "valid", "hotline_dense_failed", (("dense",), ())),
        )
        for dense_mode, lexical_mode, error, expected_calls in cases:
            with self.subTest(dense_mode=dense_mode), tempfile.TemporaryDirectory() as tmp:
                loaded, request, _specs, dense_log, lexical_log = self.public_case(
                    tmp, dense_mode=dense_mode, lexical_mode=lexical_mode
                )
                generation = []
                loaded["generator"] = SimpleNamespace(
                    generate=lambda prompt: generation.append(prompt)
                )
                with self.assertRaisesRegex(ValueError, error):
                    quickqa.execute_question(
                        request,
                        loaded,
                        quickqa.Timer(),
                        controller=quickqa.fixed_public_pipeline,
                    )
                self.assertEqual((_calls(dense_log), _calls(lexical_log)), expected_calls)
                self.assertEqual(generation, [])

    def test_hotline_deadline_and_parent_readback_fail_before_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded, request, _specs, dense_log, lexical_log = self.public_case(tmp)
            generation = []
            loaded["generator"] = SimpleNamespace(
                generate=lambda prompt: generation.append(prompt)
            )
            with self.assertRaisesRegex(TimeoutError, "quickqa_total_deadline"):
                quickqa.execute_question(
                    request,
                    loaded,
                    quickqa.Timer(lambda: 1.0, deadline=1.0),
                    controller=quickqa.fixed_public_pipeline,
                )
            self.assertEqual((_calls(dense_log), _calls(lexical_log)), ((), ()))
            self.assertEqual(generation, [])

        store, _seed, _parent = self.store()
        generation = []
        loaded = {"generator": SimpleNamespace(generate=lambda prompt: generation.append(prompt))}

        def failed_parent_readback(_request, _loaded, _timer):
            return quickqa.parent_context(store, "e1", []), {}, []

        with self.assertRaisesRegex(ValueError, "parent_readback_required"):
            quickqa.execute_question(
                {"question": "question"},
                loaded,
                quickqa.Timer(),
                controller=failed_parent_readback,
            )
        self.assertEqual(generation, [])

    def test_hotline_is_default_and_uses_no_controller_private_helpers(self):
        source = inspect.getsource(quickqa.fixed_public_pipeline)
        for required in (
            "issue_fact_retrieval_obligations",
            "execute_retrieval_lane",
            "execute_retrieval_fusion",
            "issue_fact_semantic_verification_obligation",
            "issue_parent_context_receipts",
            "validate_parent_context_receipt",
        ):
            self.assertIn(required, source)
        for forbidden in (
            "issue_harness_execution",
            "decide_controller_action",
            "_claim_controller_step",
            "_execute_controller_",
            "_require_controller_",
        ):
            self.assertNotIn(forbidden, source)
        main_source = inspect.getsource(quickqa.main)
        self.assertIn('"--path"', main_source)
        self.assertIn('default="hotline"', main_source)
        self.assertIn('choices=("hotline",)', main_source)
        self.assertFalse(hasattr(quickqa, "four_steps"))

    def test_window_preserves_selected_child_and_marks_truncation(self):
        store, seed, parent = self.store()
        context = quickqa.parent_context(store, "e1", ["b" * 64], max_chars=8)
        self.assertEqual(context["used_char_range"], [10, 18])
        self.assertIn(seed.text, context["text"])
        self.assertTrue(context["truncated"])
        self.assertFalse(context["semantically_verified"])

    def test_full_parent_and_invalid_child_or_receipt(self):
        store, seed, parent = self.store()
        context = quickqa.parent_context(store, "e1", ["b" * 64])
        self.assertEqual(context["text"], parent.text)
        self.assertFalse(context["truncated"])
        with self.assertRaisesRegex(ValueError, "parent_readback_required"):
            quickqa.parent_context(store, "e1", [])
        with self.assertRaisesRegex(ValueError, "selected_child_context_invalid"):
            quickqa.parent_context(store, "e1", ["b" * 64], max_chars=2)
        seed.text = "wrong"
        with self.assertRaisesRegex(ValueError, "selected_child_text_mismatch"):
            quickqa.parent_context(store, "e1", ["b" * 64])

    def test_citations_closed_shape_and_abstention(self):
        context = {"label": "S1", "text": "private source", "doc_id": "d1"}
        answer = quickqa.validate_answer({"status": "answered", "answer": "answer", "citations": ["S1"]}, context)
        self.assertEqual(answer["citation_sources"], [{"label": "S1", "doc_id": "d1"}])
        self.assertEqual(quickqa.validate_answer({"status": "abstained", "answer": "", "citations": []}, context)["citation_sources"], [])
        for bad in [{"status": "answered", "answer": "answer", "citations": ["S2"]},
                    {"status": "abstained", "answer": "guess", "citations": []},
                    {"status": "answered", "answer": "answer", "citations": ["S1"], "extra": 1}]:
            with self.assertRaises(ValueError):
                quickqa.validate_answer(bad, context)

    def test_transport_one_generation_and_private_raw_capture(self):
        raw = b'{"done":true,"load_duration":42}'
        with tempfile.TemporaryDirectory() as tmp:
            recorder = quickqa.RecordingOpener(SimpleNamespace(open=lambda request, timeout: io.BytesIO(raw)), Path(tmp))
            tags = urllib.request.Request(quickqa.BASE_URL + "/api/tags")
            recorder.open(tags, 1)
            self.assertEqual(recorder.generation_calls, 0)
            chat = urllib.request.Request(quickqa.BASE_URL + "/api/chat", data=b"{}")
            self.assertEqual(recorder.open(chat, 1).read(), raw)
            self.assertEqual((Path(tmp) / "provider-response.bin").read_bytes(), raw)
            self.assertEqual(recorder.payload["load_duration"], 42)
            with self.assertRaisesRegex(ValueError, "generation_retry_forbidden"):
                recorder.open(chat, 1)
            self.assertEqual(recorder.generation_calls, 1)

    def test_failed_transport_consumes_generation_budget(self):
        def fail(request, timeout):
            raise TimeoutError("test timeout")
        with tempfile.TemporaryDirectory() as tmp:
            recorder = quickqa.RecordingOpener(SimpleNamespace(open=fail), Path(tmp))
            with self.assertRaisesRegex(ValueError, "local_endpoint_required"):
                recorder.open(urllib.request.Request("https://example.com"), 1)
            chat = urllib.request.Request(quickqa.BASE_URL + "/api/chat", data=b"{}")
            with self.assertRaises(TimeoutError):
                recorder.open(chat, 1)
            with self.assertRaisesRegex(ValueError, "generation_retry_forbidden"):
                recorder.open(chat, 1)

    def test_generation_deadline_prevents_post_and_caps_http_timeout(self):
        now, calls = [10.0], []
        timer = quickqa.Timer(lambda: now[0], deadline=13.0)
        with tempfile.TemporaryDirectory() as tmp:
            recorder = quickqa.RecordingOpener(
                SimpleNamespace(open=lambda request, timeout: (
                    calls.append(timeout) or io.BytesIO(b'{"done":true}')
                )),
                Path(tmp),
                timer,
            )
            chat = urllib.request.Request(quickqa.BASE_URL + "/api/chat", data=b"{}")
            recorder.open(chat, 180)
            self.assertEqual(calls, [3.0])

        now[0] = 13.0
        calls.clear()
        with tempfile.TemporaryDirectory() as tmp:
            recorder = quickqa.RecordingOpener(
                SimpleNamespace(open=lambda request, timeout: calls.append(timeout)),
                Path(tmp),
                timer,
            )
            with self.assertRaisesRegex(TimeoutError, "generation_post"):
                recorder.open(chat, 180)
            self.assertEqual(calls, [])
            self.assertEqual(recorder.generation_calls, 0)

    def test_failed_post_has_one_durable_attempt_and_no_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = quickqa.DurableJournal(Path(tmp) / "journal.jsonl")
            timer = quickqa.Timer(lambda: 1.0, deadline=10.0, journal=journal)

            def fail(request, timeout):
                rows = [
                    json.loads(line)
                    for line in journal.path.read_text().splitlines()
                ]
                self.assertEqual(
                    [
                        row["attempt"]
                        for row in rows
                        if row["event"] == "generation_attempt"
                    ],
                    [1],
                )
                raise TimeoutError("test timeout")

            recorder = quickqa.RecordingOpener(SimpleNamespace(open=fail), Path(tmp), timer)
            chat = urllib.request.Request(quickqa.BASE_URL + "/api/chat", data=b"{}")
            with self.assertRaises(TimeoutError):
                recorder.open(chat, 180)
            with self.assertRaisesRegex(ValueError, "generation_retry_forbidden"):
                recorder.open(chat, 180)
            rows = [json.loads(line) for line in journal.path.read_text().splitlines()]
            self.assertEqual([row["attempt"] for row in rows
                              if row["event"] == "generation_attempt"], [1])

    def test_remaining_budget_helpers_never_exceed_deadline(self):
        now = [5.25]
        timer = quickqa.Timer(lambda: now[0], deadline=8.0)
        self.assertEqual(quickqa.remaining_timeout_ms(timer), 2750)
        self.assertEqual(quickqa.remaining_http_timeout(timer), 2.75)
        now[0] = 8.0
        with self.assertRaisesRegex(
            TimeoutError, "quickqa_total_deadline:phase:late"
        ):
            with timer.phase("late"):
                self.fail("expired phase must not start")
        self.assertEqual(timer.phases, [])

    def test_request_timer_includes_controller_generation_and_validation(self):
        clock = iter(range(30)).__next__
        timer = quickqa.Timer(clock)
        calls = []
        def controller(request, loaded, timer):
            with timer.phase("controller"):
                pass
            return {"label": "S1", "text": "evidence"}, {"step_index": 4}, [object()]
        def generate(prompt):
            calls.append(prompt)
            return {"status": "answered", "answer": "reply", "citations": ["S1"]}, 10, 3
        result = quickqa.execute_question({"question": "question"}, {"generator": SimpleNamespace(generate=generate)}, timer, controller)
        self.assertEqual(result["request_wall_seconds"], 7)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["response"]["citations"], ["S1"])
        self.assertEqual([p["name"] for p in timer.phases], ["controller", "generate", "answer_and_citation_validation"])

    def test_failed_controller_prevents_generation(self):
        calls, progress = [], {}
        def controller(request, loaded, timer):
            raise ValueError("unexpected_controller_action")
        generator = SimpleNamespace(generate=lambda prompt: calls.append(prompt))
        with self.assertRaisesRegex(ValueError, "unexpected_controller_action"):
            quickqa.execute_question({"question": "question"}, {"generator": generator}, quickqa.Timer(), controller, progress)
        self.assertEqual(calls, [])
        self.assertIn("request_wall_seconds", progress)

    def test_device_probe_returns_fresh_lazy_provider(self):
        providers, warmed, sync = [], [], []
        def factory():
            provider = SimpleNamespace()
            provider._get_encoder = lambda: (warmed.append(provider) or SimpleNamespace(
                parameters=lambda: iter([SimpleNamespace(device="mps:0")])) )
            providers.append(provider)
            return provider
        torch = SimpleNamespace(mps=SimpleNamespace(synchronize=lambda: sync.append(True)))
        provider, device = quickqa.lazy_provider_after_device_probe(factory, torch)
        self.assertIs(provider, providers[1])
        self.assertEqual(warmed, [providers[0]])
        self.assertEqual(device, "mps:0")
        self.assertEqual(sync, [True])

    def test_failed_generation_preserves_elapsed_context_and_no_retry(self):
        timer = quickqa.Timer(iter(range(30)).__next__)
        calls, progress = [], {}
        def controller(request, loaded, timer):
            return {"label": "S1", "text": "evidence"}, {"step_index": 4}, []
        def generate(prompt):
            calls.append(prompt)
            raise ValueError("truncated")
        with self.assertRaisesRegex(ValueError, "truncated"):
            quickqa.execute_question({"question": "question"}, {"generator": SimpleNamespace(generate=generate)}, timer, controller, progress)
        self.assertEqual(len(calls), 1)
        self.assertEqual(progress["context"]["text"], "evidence")
        self.assertGreater(progress["request_wall_seconds"], 0)
        self.assertEqual(timer.phases[-1]["status"], "FAIL")

if __name__ == "__main__":
    unittest.main()
