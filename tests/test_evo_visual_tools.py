"""Policy visual integration with synthetic providers/pixels, never real inference."""
from copy import deepcopy
from contextlib import redirect_stderr
from dataclasses import replace
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from midprojectrag.evo_harness import cli
from midprojectrag.evo_harness.experience import Experience
from midprojectrag.evo_harness.policy import Completion, ModelIdentity, MODEL_ID, DERIVATIVE_ID
from midprojectrag.evo_harness.runtime import MLXBackend, compose_runtime, synthetic_tools
from midprojectrag.evo_harness.state import Budgets, HarnessError, InvalidAction, LimitReached, Unsupported, action_from_json
from midprojectrag.evo_harness.visual import VisualAccess, VisualHotlineTools
from midprojectrag.evo_harness import visual_runtime
from midprojectrag.indexing import visual_ocr_index as index_api
from midprojectrag.stacks.local import visual_qa
from tests import test_evo_harness as text_fixture
from tests.indexing import test_visual_ocr_index as fixture
from tests.indexing.test_visual_fusion import _visual_chunk
from tests.stacks.local import test_visual_qa as qa_fixture


def action(tool, **args):
    return json.dumps({"tool": tool, "arguments": args})


class FakeMultimodalPolicy(text_fixture.FakeBackend):
    def complete(self, messages, *, max_tokens, timeout, json_schema=None):
        self.calls.append(deepcopy(messages))
        self.schemas.append(deepcopy(json_schema))
        payload = json.loads(messages[1]["content"])
        if "sources" in payload:
            output = json.dumps({"status": "answered", "answer": "Synthetic text and unreviewed image reading.",
                                 "citations": [s["label"] for s in payload["sources"]]})
        else:
            output = self.callback(payload) if self.callback else self.replies.pop(0)
        return Completion(output, self.count_messages(messages), min(50, max_tokens), "stop")


class EvoVisualToolsTests(unittest.TestCase):
    write_inputs = fixture.VisualOCRIndexTests.write_inputs
    build = fixture.VisualOCRIndexTests.build

    def setUp(self):
        fixture.VisualOCRIndexTests.setUp(self)
        self.build()
        self.doc = self.chunks[0]["doc_id"]
        self.query_provider = fixture.FakeProvider()
        self.search_calls = []
        self.image_calls = []
        self.uncertain = False

        def searcher(*, query, allowed_doc_ids, top_k, remaining):
            self.search_calls.append((query, allowed_doc_ids, top_k))
            return index_api.search(**self.common, provider=self.query_provider, query=query,
                                    top_k=top_k, allowed_doc_ids=allowed_doc_ids)

        def inspector(request, *, remaining):
            self.image_calls.append(deepcopy(request))
            self.assertNotIn("text", request)
            self.assertNotIn("ocr", request)
            value = qa_fixture.raw_answer()
            value["runtime"]["crop_sha256"] = request["crop_sha256"]
            if self.uncertain:
                answer = json.loads(value["raw_text"])
                answer["uncertainties"] = ["Synthetic image is unclear"]
                value["raw_text"] = json.dumps(answer)
            return value

        self.access = VisualAccess(**self.common, searcher=searcher, inspector=inspector)
        self.tools = VisualHotlineTools(self.access, base=synthetic_tools())
        self.request = {"question": "Read the label in the drawing.",
                        "document_scope": {"mode": "explicit", "doc_ids": [self.doc]}}
        self.episode = self.tools.begin(self.request)
        self.budget = Budgets()

    def search(self, **overrides):
        return self.tools.visual_search(self.episode, {"query": "drawing label", "doc_ids": None, "limit": 5} | overrides,
                                        self.budget, lambda: 100)

    def inspect(self, **overrides):
        return self.tools.inspect_image(self.episode, {"evidence_id": "cand:e1", "question": "Read the image label."} | overrides,
                                        self.budget, lambda: 100)

    def test_strict_new_actions(self):
        for raw in [action("visual_search", query="label", doc_ids=None, limit=5),
                    action("inspect_image", evidence_id="cand:e1", question="label")]:
            self.assertIn(action_from_json(raw)["tool"], {"visual_search", "inspect_image"})
        for raw in [action("visual_search", query="label", doc_ids=[], limit=6),
                    action("inspect_image", evidence_id=["cand:e1"], question="label"),
                    action("inspect_image", evidence_id="cand:e1", question="label", crop_path="/tmp/x"),
                    action("inspect_image", evidence_id="cand:e1", question="x"*2001)]:
            with self.assertRaises(InvalidAction):
                action_from_json(raw)

    def test_scoped_search_discloses_only_current_handles(self):
        found = self.search()
        self.assertEqual(found["candidates"][0]["id"], "cand:e1")
        self.assertEqual(found["candidates"][0]["doc_id"], self.doc)
        self.assertNotIn("crop_path", json.dumps(found))
        self.assertEqual(self.search_calls[0][1], frozenset({self.doc}))
        self.assertEqual(self.episode.usage.search_calls, 1)
        self.assertEqual(self.episode.usage.visual_search_calls, 1)
        self.assertEqual(self.image_calls, [])
        self.assertIn("visual_search", self.episode.observation(self.budget)["available_tools"])

    def test_empty_scope_never_embeds(self):
        self.assertEqual(self.search(doc_ids=[])["candidates"], [])
        self.assertEqual(self.query_provider.calls, 0)
        self.assertEqual(self.episode.usage.search_calls, 0)
        result = index_api.search(**self.common, provider=self.query_provider, query="q", allowed_doc_ids=set())
        self.assertEqual(result["hits"], [])
        self.assertEqual(self.query_provider.calls, 0)

    def test_unknown_or_widened_scope_rejected_before_search(self):
        for docs in (["unknown"], ["alpha"]):
            with self.assertRaises(InvalidAction):
                self.search(doc_ids=docs)
        self.assertEqual(self.query_provider.calls, 0)

    def test_unknown_image_and_document_id_never_infer(self):
        for key in ("e1", self.doc, "/tmp/image.png"):
            with self.assertRaises(InvalidAction):
                self.inspect(evidence_id=key)
        self.assertEqual(self.image_calls, [])
        self.assertEqual(self.episode.usage.image_calls, 0)

    def test_visual_search_excerpt_cannot_be_read_as_verified_text(self):
        self.search()
        with self.assertRaisesRegex(InvalidAction, "use_inspect_image"):
            self.tools.read(self.episode, {"evidence_ids": ["cand:e1"]}, self.budget, lambda: 100)
        with self.assertRaisesRegex(InvalidAction, "unknown_read_evidence"):
            self.tools.packet(self.episode, ["ev:e1"])

    def test_pixels_interpretation_enters_typed_unreviewed_packet(self):
        self.search()
        observation = self.inspect()
        self.assertTrue(observation["usable_in_finish"])
        packet = self.tools.packet(self.episode, ["ev:e1"])
        self.assertEqual(packet[0]["locator"], self.chunks[0]["citation"])
        self.assertEqual(packet[0]["source_kind"], "visual_inference")
        self.assertTrue(packet[0]["human_review_required"])
        self.assertFalse(packet[0]["factual_evidence_promoted"])
        self.assertEqual(self.episode.usage.image_calls, 1)
        self.assertEqual(self.episode.usage.read_calls, 1)
        self.assertEqual(self.episode.usage.visual_input_tokens, 12)
        self.assertEqual(self.episode.usage.visual_output_tokens, 10)
        self.assertEqual(self.image_calls[0]["crop_sha256"], self.chunks[0]["crop_sha256"])

    def test_uncertainty_is_not_finish_evidence(self):
        self.search()
        self.uncertain = True
        result = self.inspect()
        self.assertEqual(result["status"], "abstained")
        self.assertFalse(result["usable_in_finish"])
        with self.assertRaises(InvalidAction):
            self.tools.packet(self.episode, ["ev:e1"])
        self.assertEqual(self.episode.windows, {})

    def test_request_local_duplicates_do_not_redispatch(self):
        self.search(); second = self.search()
        self.inspect(); duplicate = self.inspect()
        self.assertTrue(second["duplicate"])
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual((len(self.search_calls), len(self.image_calls)), (1, 1))
        self.assertEqual(self.episode.usage.duplicates, 2)
        other = self.tools.begin(self.request)
        with self.assertRaises(InvalidAction):
            self.tools.inspect_image(other, {"evidence_id": "cand:e1", "question": "label"}, self.budget, lambda: 100)

    def test_cached_different_question_restores_its_own_window(self):
        self.search(); self.inspect()
        original = deepcopy(self.episode.windows)
        self.uncertain = True
        self.inspect(question="Different image question")
        self.assertFalse(self.episode.windows)
        self.inspect()
        self.assertEqual(self.episode.windows, original)
        self.assertEqual(len(self.image_calls), 2)

    def test_image_and_common_read_budget_are_enforced(self):
        self.search(); self.inspect()
        with self.assertRaisesRegex(LimitReached, "image_budget"):
            self.tools.inspect_image(self.episode, {"evidence_id": "cand:e1", "question": "new"},
                                     Budgets(image_calls=1), lambda: 100)
        with self.assertRaisesRegex(LimitReached, "read_budget"):
            self.tools.inspect_image(self.episode, {"evidence_id": "cand:e1", "question": "new"},
                                     Budgets(read_calls=1), lambda: 100)
        self.assertEqual(len(self.image_calls), 1)

    def test_failure_consumes_attempt_and_does_not_cache_success(self):
        self.search()
        def failed(request, *, remaining):
            raise TimeoutError("test")
        self.access.inspector = failed
        with self.assertRaises(TimeoutError):
            self.inspect()
        self.assertEqual(self.episode.usage.image_calls, 1)
        self.assertFalse(self.episode.usage.visual_usage_complete)
        self.assertFalse(self.episode.windows)
        self.assertFalse(any(key[0] == "inspect_image" for key in self.episode.cache))

    def test_late_result_keeps_usage_but_no_accepted_window(self):
        self.search(); expired = [False]
        original = self.access.inspector
        def late(request, *, remaining):
            raw = original(request, remaining=remaining)
            expired[0] = True
            return raw
        def remaining():
            if expired[0]: raise TimeoutError("test")
            return 10
        self.access.inspector = late
        with self.assertRaises(TimeoutError):
            self.tools.inspect_image(self.episode, {"evidence_id": "cand:e1", "question": "label"}, self.budget, remaining)
        self.assertFalse(self.episode.windows)
        self.assertEqual(self.episode.usage.visual_output_tokens, 10)

    def test_expired_cache_lookup_cannot_start_or_return_work(self):
        self.search(); self.inspect()
        def expired(): raise TimeoutError("test")
        with self.assertRaises(TimeoutError):
            self.tools.inspect_image(self.episode, {"evidence_id": "cand:e1", "question": "label"}, self.budget, expired)
        self.assertEqual(len(self.image_calls), 1)

    def test_forged_result_rejected_before_candidates_are_added(self):
        raw = index_api.search(**self.common, provider=self.query_provider, query="drawing label")
        raw["hits"][0]["citation"]["doc_id"] = "alpha"
        self.access.searcher = lambda **kwargs: raw
        with self.assertRaises(HarnessError):
            self.search()
        self.assertFalse(self.episode.candidates)
        self.assertEqual(self.episode.usage.search_calls, 1)

    def test_changed_pixels_fail_before_model_attempt(self):
        self.search()
        self.crop.write_bytes(self.crop.read_bytes()+b"changed")
        with self.assertRaises(ValueError):
            self.inspect()
        self.assertEqual(self.image_calls, [])
        self.assertEqual(self.episode.usage.image_calls, 0)

    def test_policy_picks_visual_tools_and_final_output_keeps_flags(self):
        def choose(observation):
            if observation["read_evidence"]:
                return text_fixture.finish(observation["read_evidence"][0]["id"])
            if observation["known_evidence"]:
                return action("inspect_image", evidence_id=observation["known_evidence"][0]["id"], question="Read label")
            return action("visual_search", query="drawing label", doc_ids=None, limit=5)
        backend = FakeMultimodalPolicy(callback=choose)
        result = compose_runtime(backend, self.tools).run(self.request, record_trajectory=True)
        self.assertEqual(result["status"], "answered", result)
        self.assertEqual([event["tool"] for event in result["actions"]], ["visual_search", "inspect_image", "finish"])
        self.assertEqual(result["usage"]["policy_calls"], 3)
        self.assertEqual(result["usage"]["answer_calls"], 1)
        self.assertTrue(result["response"]["human_review_required"])
        self.assertFalse(result["response"]["factual_evidence_promoted"])
        self.assertTrue(result["synthetic_backend"])
        self.assertFalse(result["controller_executed"])
        self.assertIn("NOT a request for missing user information", backend.calls[0][0]["content"])
        self.assertIn("usable_in_finish=true", backend.calls[0][0]["content"])
        self.assertEqual(result["response"]["citation_sources"][0]["locator"], self.chunks[0]["citation"])
        source = json.loads(backend.calls[-1][1]["content"])["sources"][0]
        self.assertEqual(source["source_kind"], "visual_inference")

    def test_mixed_text_and_image_use_one_episode_and_shared_budgets(self):
        request = deepcopy(self.request)
        request["document_scope"]["doc_ids"] = ["alpha", self.doc]
        backend = FakeMultimodalPolicy([
            text_fixture.search(query="Alpha", docs=["alpha"], limit=1), text_fixture.read("e1"),
            action("visual_search", query="figure", doc_ids=[self.doc], limit=1),
            action("inspect_image", evidence_id="cand:e2", question="Read label"), text_fixture.finish("e1", "e2")])
        result = compose_runtime(backend, self.tools).run(request)
        self.assertEqual(result["status"], "answered", result)
        self.assertEqual((result["usage"]["search_calls"], result["usage"]["read_calls"], result["usage"]["image_calls"]), (2, 2, 1))
        self.assertEqual(set(result["response"]["cited_doc_ids"]), {"alpha", self.doc})
        self.assertEqual(result["response"]["citations"], ["S1", "S2"])

    def test_visual_only_does_not_claim_a_text_retriever(self):
        only = VisualHotlineTools(self.access)
        episode = only.begin(self.request)
        self.assertNotIn("search", episode.capabilities)
        self.assertIn("visual_search", episode.capabilities)
        with self.assertRaises(Unsupported):
            only.search(episode, {"query": "q", "doc_ids": None, "limit": 1}, self.budget, lambda: 100)

    def test_current_visual_prior_citations_can_resolve_scope_but_not_populate_handles(self):
        self.search(); self.inspect()
        packet = self.tools.packet(self.episode, ["ev:e1"])
        request = deepcopy(self.request)
        request["history"] = [{"role": "assistant", "content": "Earlier image reading",
                                "cited_doc_ids": [self.doc], "cited_evidence_ids": [packet[0]["evidence_id"]]}]
        episode = self.tools.begin(request, follow_up=True)
        self.assertEqual(episode.scope, frozenset({self.doc}))
        self.assertFalse(episode.candidates)
        with self.assertRaises(InvalidAction): episode.reference(packet[0]["evidence_id"])

    def test_shared_backend_passes_existing_objects_to_pixel_helper(self):
        backend = MLXBackend.__new__(MLXBackend)
        backend.model, backend.processor, backend.config = object(), object(), {"vision_config": {"ready": True}}
        backend.calls = 0
        backend.identity = ModelIdentity(MODEL_ID, DERIVATIVE_ID, visual_qa.REVISION, "b"*64,
                                         "mlx-vlm/0.7.0", "Device(gpu, 0)", "4bit")
        with patch.object(visual_qa, "infer_loaded", return_value={"test": True}) as infer:
            result = backend.inspect_image({"query": "label"}, remaining=lambda: 10)
        self.assertEqual(result, {"test": True})
        self.assertIs(infer.call_args.args[1], backend.model)
        self.assertIs(infer.call_args.args[2], backend.processor)
        self.assertEqual(backend.calls, 1)

    def test_query_child_uses_remaining_budget_and_no_egress(self):
        process = visual_runtime.QueryProcess(python=Path(sys.executable), hf_cache=self.root,
                    work_dir=self.root/"queries", **self.common)
        calls = []
        def child(command, **kwargs):
            calls.append((command, kwargs))
            path = Path(command[command.index("--output")+1])
            request = json.loads(Path(command[command.index("--request")+1]).read_text())
            self.assertEqual(request["doc_ids"], [self.doc])
            index_api._write(path, {"query": "label", "hits": []})
            return subprocess.CompletedProcess(command, 0)
        with patch.object(visual_runtime, "SANDBOX", Path(sys.executable)), patch.object(visual_runtime.subprocess, "run", side_effect=child):
            process(query="label", allowed_doc_ids=frozenset({self.doc}), top_k=1, remaining=lambda: 7.5)
        self.assertEqual(calls[0][1]["timeout"], 7.5)
        self.assertEqual(calls[0][0][2], "(version 1) (allow default) (deny network*)")
        self.assertNotIn("OPENAI_API_KEY", calls[0][1]["env"])
        self.assertIn("/src", calls[0][1]["env"]["PYTHONPATH"])

    def test_cli_preserves_virtualenv_python_path_instead_of_resolving_symlink(self):
        data = self.root/"cli-data"
        (data/"private").mkdir(parents=True)
        request = data/"private/request.json"
        request.write_text(json.dumps(self.request))
        model = self.root/"model"
        model.mkdir()
        cache = self.root/"cache"
        cache.mkdir()
        python = self.root/"virtualenv-python"
        python.symlink_to(Path(sys.executable).resolve())
        args = ["--data-dir", str(data), "--request", str(request),
                "--output-dir", str(data/"private/output"), "--model-dir", str(model),
                "--model-manifest", str(self.root/"manifest.json"), "--visual-only",
                "--visual-index", str(self.root/"index"), "--visual-private-root", str(self.root),
                "--visual-crop-root", str(self.root/"crops"), "--visual-python", str(python),
                "--visual-hf-cache", str(cache)]
        with patch.object(cli, "run_supervised", return_value={"status": "COMPLETED", "exit_code": 0}) as run, \
             patch.object(visual_runtime, "offline_command", side_effect=lambda cmd: ["test-offline"]+cmd):
            self.assertEqual(cli.main(args), 0)
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--visual-python")+1], str(python))
        self.assertNotEqual(str(python), str(python.resolve()))

    def test_incomplete_cli_visual_options_rejected_before_model(self):
        args = ["--data-dir", str(self.root), "--output-dir", str(self.root/"private/out"),
                "--model-dir", str(self.root), "--model-manifest", str(self.root/"m.json"),
                "--visual-only"]
        with patch.object(cli, "MLXBackend") as model, redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.main(args)
        model.assert_not_called()



    def test_validated_visual_teacher_exports_search_inspect_finish(self):
        from midprojectrag.evo_harness.training import TRAINING_CASE_SCHEMA, sft_examples_from_trajectory
        from midprojectrag.evo_harness.training_visual_teacher import run_visual_teacher_case
        case={"schema_version":TRAINING_CASE_SCHEMA,"case_id":"tv1","group_id":"tv1","split":"train","task_type":"visual",
              "question":"Confirm that this document contains an inserted image.",
              "request":{"question":"Confirm that this document contains an inserted image.","history":[],"document_scope":{"mode":"explicit","doc_ids":[self.doc]},"options":{"max_citations":3}}}
        target={"case_id":"tv1","split":"train","task_type":"visual","terminal_status":"answered","facts":{"has_inserted_image":True},"required_tools":["visual_search","inspect_image"]}
        result=run_visual_teacher_case(case,target,tools=self.tools,count_backend=FakeMultimodalPolicy([]))
        self.assertTrue(result["teacher_validation"]["success"],result)
        self.assertEqual([a["tool"] for a in result["actions"]],["visual_search","inspect_image","finish"])
        rows=sft_examples_from_trajectory(result,case)
        self.assertEqual([json.loads(r["completion"][0]["content"])["tool"] for r in rows],["visual_search","inspect_image","finish"])


class ScopedVisualRankingTests(unittest.TestCase):
    write_inputs = fixture.VisualOCRIndexTests.write_inputs
    build = fixture.VisualOCRIndexTests.build

    def setUp(self):
        fixture.VisualOCRIndexTests.setUp(self)
        # Same synthetic pixel file; distinct documents/occurrences and valid chunk identities.
        second = _visual_chunk(2, 2)
        second["crop_sha256"] = second["citation"]["crop_sha256"] = self.chunks[0]["crop_sha256"]
        self.chunks.append(second)
        occurrence = {**deepcopy(self.occurrences[0]), **{k: deepcopy(second[k]) for k in
                      ("doc_id", "occurrence_id", "page", "bbox", "crop_sha256")}}
        self.occurrences.append(occurrence)
        self.write_inputs(); self.build()

    def test_filter_is_applied_before_top_k_not_after(self):
        provider = fixture.FakeProvider()
        chosen = self.chunks[-1]["doc_id"]
        result = index_api.search(**self.common, provider=provider, query="label", top_k=1,
                                  allowed_doc_ids=frozenset({chosen}))
        self.assertEqual(len(result["hits"]), 1)
        self.assertEqual(result["hits"][0]["citation"]["doc_id"], chosen)
        self.assertEqual(provider.calls, 1)

    def test_invalid_scope_type_rejected_without_embedding(self):
        provider = fixture.FakeProvider()
        for scope in ("all", ["doc"], {1}, {""}):
            with self.assertRaises(ValueError):
                index_api.search(**self.common, provider=provider, query="label", allowed_doc_ids=scope)
        self.assertEqual(provider.calls, 0)


if __name__ == "__main__":
    unittest.main()
