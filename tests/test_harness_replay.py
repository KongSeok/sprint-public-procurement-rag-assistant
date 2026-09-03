import ast
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from midprojectrag.offline_harness.replay import answer_from_record, facts_from_case, replay_saved_answers


class ReplayTests(unittest.TestCase):
    def test_three_saved_shapes(self):
        for row in ({"response": {"answer": "text", "status": "answered"}},
                    {"candidate": {"answer": "text", "status": "answered"}},
                    {"run": {"response": {"answer": "text", "status": "answered"}}}):
            self.assertEqual(answer_from_record(row), ("text", "answered"))

    def test_fact_group_shapes(self):
        self.assertEqual(facts_from_case({"gold": {"required_key_points": ["a", "b"]}}), [["a"], ["b"]])
        self.assertEqual(facts_from_case({"expected": {"required_fact_groups": [["a", "b"]]}}), [["a", "b"]])
        self.assertEqual(facts_from_case({"gold": {"reference_answer": "not atomic facts"}}), [])
        self.assertEqual(facts_from_case({"expected": {"gold": {"required_key_points": ["a"]}}}), [["a"]])
        self.assertEqual(facts_from_case({"gold": {"required_key_points": [{"point_id": "p1", "text": "a"}]}}), [["a"]])

    def test_stale_gold_source_hash_fails_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "saved.jsonl"
            source.write_text(json.dumps({"case_id": "c1", "answer": "a", "source_case_sha256": "0" * 64}) + "\n")
            cases = root / "cases.jsonl"
            cases.write_text(json.dumps({"case_id": "c1", "gold": {"required_key_points": ["a"]}}) + "\n")
            out = root / "private" / "new"
            with self.assertRaisesRegex(ValueError, "case_source_hash_mismatch"):
                replay_saved_answers(source, out, data_root=root, case_paths=[cases])
            self.assertFalse(out.exists())

    def test_private_replay_no_network_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "saved.jsonl"
            source.write_text(json.dumps({"case_id": "case-1", "response": {"answer": "금액 1,000원", "status": "answered"}}) + "\n")
            cases = root / "cases.jsonl"
            cases.write_text(json.dumps({"id": "case-1", "gold": {"required_key_points": ["금액 1000원"]}}) + "\n")
            before = sha256(source.read_bytes()).hexdigest()
            out = root / "private" / "new-run"
            with patch("socket.socket", side_effect=AssertionError("network forbidden")):
                receipt = replay_saved_answers(source, out, data_root=root, case_paths=[cases])
            self.assertEqual(receipt["generator_calls"], 0)
            self.assertEqual(receipt["scorable_count"], 1)
            self.assertEqual(sha256(source.read_bytes()).hexdigest(), before)
            score = json.loads((out / "scores.jsonl").read_text())
            self.assertEqual(score["score"]["fact_coverage"], 1)
            self.assertEqual((out / "scores.jsonl").stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                replay_saved_answers(source, out, data_root=root)
            with self.assertRaises(ValueError):
                replay_saved_answers(source, root / "public", data_root=root)

    def test_runtime_does_not_import_offline_evaluator(self):
        import midprojectrag.runtime_integrity as module
        tree = ast.parse(Path(module.__file__).read_text())
        imports = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        self.assertFalse(any("offline_harness" in name or "evaluation" in name for name in imports))

    def test_missing_gold_reported_not_perfect(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "saved.jsonl"
            source.write_text(json.dumps({"id": "c1", "answer": "text"}) + "\n")
            receipt = replay_saved_answers(source, root / "private" / "new", data_root=root)
            self.assertEqual(receipt["scorable_count"], 0)
            self.assertEqual(receipt["unscorable_count"], 1)


if __name__ == "__main__":
    unittest.main()
