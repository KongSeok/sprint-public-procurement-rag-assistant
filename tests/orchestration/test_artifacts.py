from __future__ import annotations

import copy
import inspect
import json
import stat
import tempfile
import unittest
from pathlib import Path

from midprojectrag.orchestration import HarnessConfig
from midprojectrag.orchestration.artifacts import (
    DEFAULT_IO_MAX_BYTES,
    MAX_IO_BYTES,
    digest,
    jsonable,
    read_json,
    trace_record,
    write_private_json,
)
from tests.orchestration.test_controller import fixture


class TraceArtifactTests(unittest.TestCase):
    def setUp(self):
        self.store, _, _, _ = fixture()
        self.config = HarnessConfig()

    def make_trace(self, **kwargs):
        return trace_record(
            request={"request_id": "test"}, store=self.store,
            config=self.config, policy_id="test-policy", result={"status": "test"},
            **kwargs,
        )

    def test_omitted_runtime_preserves_exact_v1_record_and_hashes(self):
        expected = {
            "schema_version": "evidence-harness-trace-v1",
            "request": {"request_id": "test"},
            "config": jsonable(self.config),
            "config_sha256": digest(self.config),
            "evidence_sha256": digest(self.store.to_dict()),
            "policy_id": "test-policy",
            "synthetic": False,
            "official": False,
            "experience_enabled": False,
            "result": {"status": "test"},
            "provider_calls": [],
        }
        expected["trace_sha256"] = digest(expected)
        self.assertEqual(self.make_trace(), expected)
        self.assertEqual(self.make_trace(runtime=None), expected)

    def test_runtime_adds_v2_composite_config_without_new_top_level_fields(self):
        runtime = {
            "retrieval": {"lane": "legacy_page", "index_sha256": "a" * 64},
            "enumeration": {"max_documents": 100},
            "model": "test-model",
            "visual_available": False,
        }
        original = copy.deepcopy(runtime)
        trace = self.make_trace(runtime=runtime)
        self.assertEqual(set(trace), set(self.make_trace()))
        self.assertEqual(trace["schema_version"], "evidence-harness-trace-v2")
        self.assertEqual(trace["config"], {"harness": jsonable(self.config), "runtime": original})
        self.assertEqual(trace["config_sha256"], digest(trace["config"]))
        self.assertEqual(trace["trace_sha256"], digest({k: v for k, v in trace.items() if k != "trace_sha256"}))
        runtime["retrieval"]["index_sha256"] = "b" * 64
        self.assertEqual(trace["config"]["runtime"], original)
        self.assertNotEqual(self.make_trace(runtime=runtime)["config_sha256"], trace["config_sha256"])
        self.assertEqual(self.make_trace(runtime={})["schema_version"], "evidence-harness-trace-v2")

    def test_runtime_requires_finite_serializable_dictionary(self):
        for runtime in ([], True, "runtime", {"threshold": float("nan")}):
            with self.subTest(runtime=runtime), self.assertRaises(ValueError):
                self.make_trace(runtime=runtime)


class PrivateIOTests(unittest.TestCase):
    def test_size_cap_defaults_are_compatible_and_larger_evidence_cap_is_opt_in(self):
        self.assertEqual(DEFAULT_IO_MAX_BYTES, 64 * 1024 * 1024)
        self.assertEqual(MAX_IO_BYTES, 256 * 1024 * 1024)
        for function in (read_json, write_private_json):
            self.assertEqual(inspect.signature(function).parameters["max_bytes"].default, DEFAULT_IO_MAX_BYTES)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "private"
            target = root / "evidence.json"
            value = {"text": "synthetic"}
            write_private_json(target, value, private_root=root, max_bytes=MAX_IO_BYTES)
            self.assertEqual(read_json(target, max_bytes=MAX_IO_BYTES), value)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

    def test_exact_encoded_size_limit_and_overflow_do_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "private"
            target = root / "evidence.json"
            value = {"text": "한글"}
            size = len(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode())
            with self.assertRaisesRegex(ValueError, "trace_too_large"):
                write_private_json(target, value, private_root=root, max_bytes=size - 1)
            self.assertFalse(root.exists())
            write_private_json(target, value, private_root=root, max_bytes=size)
            self.assertEqual(read_json(target, max_bytes=size), value)
            with self.assertRaisesRegex(ValueError, "input_too_large"):
                read_json(target, max_bytes=size - 1)
            with self.assertRaises(FileExistsError):
                write_private_json(target, {"changed": True}, private_root=root, max_bytes=MAX_IO_BYTES)
            self.assertEqual(read_json(target), value)

    def test_invalid_limits_fail_before_filesystem_io(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "private"
            target = root / "evidence.json"
            for limit in (True, False, 0, -1, 1.5, None, MAX_IO_BYTES + 1):
                with self.subTest(limit=limit):
                    with self.assertRaisesRegex(ValueError, "invalid_io_size_limit"):
                        write_private_json(target, {}, private_root=root, max_bytes=limit)
                    with self.assertRaisesRegex(ValueError, "invalid_io_size_limit"):
                        read_json(target, max_bytes=limit)
            self.assertFalse(root.exists())


if __name__ == "__main__":
    unittest.main()
