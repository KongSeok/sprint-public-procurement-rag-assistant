from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from midprojectrag.retrieval_smoke import select_cases, verify_inputs, run_arms, run, require_offline_cache
from midprojectrag.runtime_integrity import ResolvedScope
from midprojectrag.stage_checkpoints import canonical_sha
from midprojectrag.stage_inputs import write_inputs
from midprojectrag.stage_recorder import _record
from tests import test_stage_recorder as recorder_fixtures
from tests import test_stage_inputs as inputs_fixtures


class RetrievalSmokeTests(unittest.TestCase):
    def test_hf_cache_must_be_set_before_import_no_late_cache_switch(self):
        from huggingface_hub import constants
        with patch.object(constants, "HF_HUB_CACHE", "/tmp/smoke-cache/hub"), \
             patch.object(constants, "HF_HUB_OFFLINE", True), \
             patch("transformers.utils.hub.TRANSFORMERS_CACHE", "/tmp/smoke-cache/hub"), \
             patch.dict("os.environ", {"TRANSFORMERS_OFFLINE": "1"}):
            require_offline_cache(Path("/tmp/smoke-cache"))
            with self.assertRaisesRegex(ValueError, "startup_mismatch"):
                require_offline_cache(Path("/tmp/other-smoke-cache"))
            with patch("transformers.utils.hub.TRANSFORMERS_CACHE", "/tmp/legacy-cache/hub"):
                with self.assertRaisesRegex(ValueError, "startup_mismatch"):
                    require_offline_cache(Path("/tmp/smoke-cache"))

    def requests(self, doc="doc_x"):
        def case(cid, mode):
            return SimpleNamespace(case_id=cid, lane="core40", request_template={"question": "private-question",
                   "history": [], "document_scope": {"mode": mode, "doc_ids": [doc] if mode == "explicit" else []}})
        return [case("explicit-first", "explicit"), case("all-first", "all"), case("explicit-later", "explicit")]

    def test_selection_uses_only_original_request_and_first_scope_cases(self):
        cases = self.requests()
        selected = select_cases(cases)
        self.assertEqual([c for c, _ in selected], ["explicit-first", "all-first"])
        self.assertEqual([r.document_scope["mode"] for _, r in selected], ["explicit", "all"])
        with self.assertRaises(ValueError): select_cases(cases[:1])

    def test_private_inventory_reconstruction_and_tamper_rejection(self):
        fixture = inputs_fixtures.StageInputsTests()
        fixture.setUp()
        suite = SimpleNamespace(cases=fixture.cases, ledger_rows=fixture.ledger, config_sha256="b" * 64,
                                config={"sources": {k: {"sha256": v} for k, v in fixture.sources.items()}},
                                parser_receipt=fixture.parser)
        payload = fixture.build()
        payload["input_config_sha256"] = suite.config_sha256
        payload.pop("inputs_sha256")
        payload["inputs_sha256"] = canonical_sha(payload)
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "private").mkdir()
            target = root / "private/inputs"
            inventory = write_inputs(payload, output_dir=target, data_root=root)
            self.assertEqual(verify_inputs(target, suite, fixture.snapshot), inventory)
            broken = deepcopy(inventory)
            broken["publication_status"] = "partial"
            (target / "inventory.json").write_text(json.dumps(broken))
            with self.assertRaises(ValueError): verify_inputs(target, suite, fixture.snapshot)

    def test_new_private_output_required_before_any_loader(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "private").mkdir()
            (root / "private/existing").mkdir()
            with self.assertRaisesRegex(ValueError, "new_output"):
                run(SimpleNamespace(data_root=root, output_dir=root / "private/existing"))
            with self.assertRaises(ValueError):
                run(SimpleNamespace(data_root=root, output_dir=root / "public"))

    def test_two_round_files_and_common_binding_no_content_leak(self):
        fixture = recorder_fixtures.StageRecorderTests()
        fixture.setUp()
        selected = select_cases(self.requests(fixture.rows[0].doc_id))
        calls = []
        def recorder(**kw):
            calls.append((kw["arm_id"], kw["case_id"], kw["run_id"]))
            # Use real observer/fusion/context with synthetic lane rows.
            page = kw["arm_id"] == "page_kure"
            rows = fixture.store.candidates(kinds=("page",)) if page else fixture.rows
            from midprojectrag.retrieval.contracts import Candidate, SearchResult
            def search(lane, limit):
                return SearchResult(tuple(Candidate(e.evidence_id, e.doc_id, 1.0, lane, i, "page" if page else "child")
                                          for i, e in enumerate(rows, 1)),
                                    {"granularity": "page" if page else "child", "bundle_sha256": fixture.store.bundle_sha256,
                                     "encoder_calls": 1})
            return _record(query="user: private-question", scope=ResolvedScope.from_request(kw["request"]),
                           store=fixture.store, config=fixture.config, run_id=kw["run_id"], case_id=kw["case_id"],
                           arm_id=kw["arm_id"], search=search)
        with TemporaryDirectory() as temp, redirect_stdout(StringIO()):
            output = Path(temp)
            rows = run_arms(selected, {"page": object(), "child": object()}, fixture.store, fixture.config,
                            output, run_id="smoke-test", recorder=recorder)
            self.assertEqual(len(calls), 12)
            self.assertTrue(all(r["required_stages_ok"] for r in rows))
            self.assertEqual(sum(r["encoder_calls"] for r in rows), 12)
            self.assertEqual(sum(r["backend_temperature"].startswith("first_query") for r in rows), 2)
            self.assertEqual(len(list(output.iterdir())), 12)
            for path in output.iterdir():
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertNotIn("private-question", path.read_text())
                self.assertEqual(len(path.read_text().splitlines()), 2)
            with self.assertRaises(FileExistsError):
                run_arms(selected, {"page": object(), "child": object()}, fixture.store, fixture.config,
                         output, run_id="smoke-test", recorder=recorder)


if __name__ == "__main__":
    unittest.main()
