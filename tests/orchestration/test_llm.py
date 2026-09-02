import unittest
from unittest.mock import patch

from midprojectrag.orchestration import Slot, Verification
from midprojectrag.orchestration.llm import LLMPlanner, LLMVerifier, LocalJSONBackend
from tests.orchestration.test_controller import fixture


def request():
    return {"schema_version": "1.0", "request_id": "synthetic-1", "question": "그 예산은?",
            "history": [{"turn_id": "t1", "role": "user", "content": "첫 문서"}],
            "document_scope": {"mode": "explicit", "doc_ids": ["doc_000000000000000000000001"]},
            "options": {"max_citations": 5}}


class Backend:
    def __init__(self, value): self.value, self.payloads = value, []
    def ask(self, purpose, payload):
        self.payloads.append((purpose, payload))
        return self.value


class LLMPortTests(unittest.TestCase):
    def test_history_and_scope_preserved(self):
        backend = Backend({"query_type": "followup", "slots": [{"key": "budget", "query": "첫 문서의 예산", "doc_id": request()["document_scope"]["doc_ids"][0], "kind": None}]})
        plan = LLMPlanner(backend).plan(request())
        self.assertEqual(plan.history, (("user", "첫 문서"),))
        self.assertEqual(plan.allowed_doc_ids, frozenset(request()["document_scope"]["doc_ids"]))
        self.assertEqual(backend.payloads[0][1]["history"], request()["history"])
    def test_gold_fields_forbidden(self):
        value = {"query_type": "fact", "slots": [], "required_facts": ["gold"]}
        with self.assertRaises(ValueError): LLMPlanner(Backend(value)).plan(request())
        value = request() | {"expected_answer": "gold"}
        with self.assertRaises(ValueError): LLMPlanner(Backend({})).plan(value)
    def test_unscoped_doc_not_invented(self):
        value = {"query_type": "fact", "slots": [{"key": "s1", "query": "x", "doc_id": "doc_other", "kind": None}]}
        with self.assertRaises(ValueError): LLMPlanner(Backend(value)).plan(request())
    def test_unknown_support_rejected(self):
        _, _, children, _ = fixture()
        with self.assertRaises(ValueError): LLMVerifier(Backend({"evidence_ids": ["ev_fake"], "contradiction": False})).verify(Slot("s1", "x"), children)
    def test_malformed_support_rejected(self):
        _, _, children, _ = fixture()
        for value in ({"evidence_ids": {}, "contradiction": False}, {"evidence_ids": [], "contradiction": "false"}, {"evidence_ids": [True], "contradiction": False}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                LLMVerifier(Backend(value)).verify(Slot("s1", "x"), children)
    def test_valid_support_comes_from_backend(self):
        _, _, children, _ = fixture()
        verifier = LLMVerifier(Backend({"evidence_ids": [children[0].evidence_id], "contradiction": False}))
        self.assertEqual(verifier.verify(Slot("s1", "x"), children), Verification((children[0].evidence_id,)))
    def test_no_call_after_deadline(self):
        with patch("midprojectrag.orchestration.llm.time.monotonic", return_value=5):
            with self.assertRaises(TimeoutError): LocalJSONBackend(deadline=5).ask("plan", {})
    def test_call_budget(self):
        backend = LocalJSONBackend(deadline=100, max_calls=1)
        backend.calls.append({})
        with patch("midprojectrag.orchestration.llm.time.monotonic", return_value=5):
            with self.assertRaises(TimeoutError): backend.ask("plan", {})


if __name__ == "__main__": unittest.main()
