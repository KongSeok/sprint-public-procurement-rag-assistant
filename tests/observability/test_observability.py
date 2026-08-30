from __future__ import annotations

import math
import unittest
from unittest.mock import patch

from midprojectrag.observability import (
    LangfuseObserver,
    MemoryObserver,
    NoopObservation,
    NoopObserver,
    create_observer,
    sanitize_metadata,
)

try:
    from langfuse import Langfuse as _InstalledLangfuse
except ImportError:
    _InstalledLangfuse = None


class _MustNotStringify:
    def __str__(self) -> str:
        raise AssertionError("unsafe values must never be stringified")

    def __repr__(self) -> str:
        raise AssertionError("unsafe values must never be represented")


class _FakeObservation:
    def __init__(self, *, fail_update: bool = False, fail_end: bool = False) -> None:
        self.trace_id = "0" * 32
        self.id = "1" * 16
        self.fail_update = fail_update
        self.fail_end = fail_end
        self.updates: list[dict[str, object]] = []
        self.end_count = 0

    def update(self, **kwargs: object) -> None:
        if self.fail_update:
            raise RuntimeError("synthetic exporter update failure")
        self.updates.append(dict(kwargs))

    def end(self) -> None:
        self.end_count += 1
        if self.fail_end:
            raise RuntimeError("synthetic exporter end failure")


class _FakeObservationContext:
    def __init__(self, observation: _FakeObservation) -> None:
        self.observation = observation
        self.exit_arguments: list[tuple[object, object, object]] = []

    def __enter__(self) -> _FakeObservation:
        return self.observation

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        self.exit_arguments.append((exc_type, exc, traceback))
        self.observation.end()
        return False


class _FakeClient:
    def __init__(
        self,
        *,
        observation: _FakeObservation | None = None,
        fail_start: bool = False,
        fail_flush: bool = False,
        fail_shutdown: bool = False,
    ) -> None:
        self.observation = observation or _FakeObservation()
        self.fail_start = fail_start
        self.fail_flush = fail_flush
        self.fail_shutdown = fail_shutdown
        self.start_calls: list[dict[str, object]] = []
        self.flush_count = 0
        self.shutdown_count = 0
        self.score_calls: list[dict[str, object]] = []
        self.contexts: list[_FakeObservationContext] = []

    def start_as_current_observation(self, **kwargs: object) -> _FakeObservationContext:
        self.start_calls.append(dict(kwargs))
        if self.fail_start:
            raise RuntimeError("synthetic exporter start failure")
        context = _FakeObservationContext(self.observation)
        self.contexts.append(context)
        return context

    def flush(self) -> None:
        self.flush_count += 1
        if self.fail_flush:
            raise RuntimeError("synthetic exporter flush failure")

    def shutdown(self) -> None:
        self.shutdown_count += 1
        if self.fail_shutdown:
            raise RuntimeError("synthetic exporter shutdown failure")

    def create_score(self, **kwargs: object) -> None:
        self.score_calls.append(dict(kwargs))


class ObservabilityTests(unittest.TestCase):
    def test_personal_large_matrix_metadata_is_allowlisted_without_content(self) -> None:
        payload = {
            "api_profile": "personal_experimental",
            "embedding_model": "text-embedding-3-large",
            "embedding_dimensions": 3072,
            "generator_model": "gpt-5-nano",
            "index_config_sha256": "a" * 64,
            "config_sha256": "b" * 64,
        }
        self.assertEqual(sanitize_metadata(payload), payload)

    def test_default_is_noop_and_never_imports_langfuse(self) -> None:
        with patch("midprojectrag.observability._langfuse.importlib.import_module") as importer:
            observer = create_observer()
            self.assertIsInstance(observer, NoopObserver)
            with observer.start_observation("rag.query", metadata={"question": "restricted"}):
                pass
            observer.flush()
            importer.assert_not_called()

    def test_sanitizer_is_strict_metadata_only_and_never_stringifies_objects(self) -> None:
        safe = sanitize_metadata(
            {
                "request_id": "req_0123456789abcdef01234567",
                "generator_model": "gpt-5-mini",
                "top_k": 10,
                "score": -0.25,
                "cache_hit": False,
                "doc_ids": ["doc_0123456789abcdef01234567"],
                "corpus_manifest_sha256": "a" * 64,
                "question": "사업 담당자의 이메일은?",
                "prompt": "restricted prompt",
                "input": "restricted model input",
                "output": "restricted model output",
                "answer": "restricted answer",
                "content": "restricted source content",
                "retrieved_chunk_text": "restricted chunk",
                "error_code": "contains spaces and user text",
                "region": "person@example.com",
                "unknown": _MustNotStringify(),
                "latency_ms": math.inf,
                "cost_usd": math.nan,
                "chunk_ids": ["chunk_safe", "contains spaces"],
            }
        )
        self.assertEqual(safe, {})
        self.assertEqual(
            sanitize_metadata(
                {
                    "request_id": "req_0123456789abcdef01234567",
                    "generator_model": "gpt-5-mini",
                    "top_k": 10,
                    "score": -0.25,
                    "cache_hit": False,
                    "doc_ids": ["doc_0123456789abcdef01234567"],
                    "corpus_manifest_sha256": "a" * 64,
                }
            ),
            {
                "request_id": "req_0123456789abcdef01234567",
                "generator_model": "gpt-5-mini",
                "top_k": 10,
                "score": -0.25,
                "cache_hit": False,
                "doc_ids": ["doc_0123456789abcdef01234567"],
                "corpus_manifest_sha256": "a" * 64,
            },
        )

    def test_memory_sink_records_only_safe_metadata_and_is_idempotent(self) -> None:
        observer = MemoryObserver()
        observation = observer.start_observation(
            "retrieve.dense",
            as_type="retriever",
            metadata={"top_k": 10, "doc_ids": ["doc_0123456789abcdef01234567"]},
        )
        observation.update({"retrieval_count": 4, "content": "restricted"})
        observation.end({"latency_ms": 12.5})
        observation.end({"latency_ms": 99.0})
        observer.flush()

        self.assertEqual(len(observer.records), 1)
        record = observer.records[0]
        self.assertEqual(record.name, "retrieve.dense")
        self.assertEqual(record.as_type, "retriever")
        self.assertEqual(
            dict(record.metadata),
            {
                "top_k": 10,
                "doc_ids": ["doc_0123456789abcdef01234567"],
                "latency_ms": 12.5,
            },
        )
        self.assertGreaterEqual(record.duration_ms, 0)
        self.assertEqual(observer.flush_count, 1)

    def test_identifier_fields_require_pseudonymous_key_specific_shapes(self) -> None:
        self.assertEqual(sanitize_metadata({"request_id": "proposal.pdf"}), {})
        self.assertEqual(sanitize_metadata({"doc_ids": ["actual-filename"]}), {})
        self.assertEqual(sanitize_metadata({"environment": "/private/path"}), {})

    def test_invalid_observation_name_or_type_is_dropped_without_payload_storage(self) -> None:
        observer = MemoryObserver()
        observer.start_observation("user supplied question", metadata={"request_id": "req-1"}).end()
        observer.start_observation("rag.query", as_type="raw-prompt", metadata={"request_id": "req-2"}).end()
        self.assertEqual(observer.records, ())
        self.assertEqual(observer.dropped_count, 2)

    def test_memory_context_does_not_swallow_application_errors(self) -> None:
        observer = MemoryObserver()
        with self.assertRaisesRegex(ValueError, "application failure"):
            with observer.start_observation(
                "rag.query", metadata={"request_id": "req_0123456789abcdef01234567"}
            ):
                raise ValueError("application failure")
        self.assertEqual(
            dict(observer.records[0].metadata),
            {"request_id": "req_0123456789abcdef01234567", "success": False},
        )

    def test_langfuse_client_is_lazy_and_receives_privacy_safe_manual_calls(self) -> None:
        factory_calls = 0
        client = _FakeClient()

        def factory() -> _FakeClient:
            nonlocal factory_calls
            factory_calls += 1
            return client

        observer = LangfuseObserver(client_factory=factory)
        self.assertFalse(observer.initialized)
        observer.start_observation("raw question", metadata={"question": "restricted"})
        self.assertEqual(factory_calls, 0)
        observer.start_observation("generate.answer", metadata={"prompt": "restricted"})
        self.assertEqual(factory_calls, 0)
        observer.start_observation(
            "rag.query",
            as_type="chain",
            input={"question": "restricted"},
        )
        self.assertEqual(factory_calls, 0)

        observation = observer.start_observation(
            "generate.answer",
            as_type="generation",
            metadata={
                "generator_model": "gpt-5-mini",
                "input_tokens": 20,
            },
            input={"context_count": 5},
        )
        self.assertEqual(factory_calls, 1)
        self.assertTrue(observer.initialized)
        self.assertEqual(
            client.start_calls,
            [
                {
                    "name": "generate.answer",
                    "as_type": "generation",
                    "metadata": {"generator_model": "gpt-5-mini", "input_tokens": 20},
                    "model": "gpt-5-mini",
                    "input": {"context_count": 5},
                }
            ],
        )
        self.assertEqual(observation.trace_id, "0" * 32)
        self.assertEqual(observation.observation_id, "1" * 16)
        observation.update(
            {"output_tokens": 5},
            output={"status": "answered", "citation_count": 1},
        )
        observation.end({"latency_ms": 20.0})
        observation.end()
        self.assertEqual(
            client.observation.updates,
            [
                {
                    "metadata": {"output_tokens": 5},
                    "output": {"status": "answered", "citation_count": 1},
                    "usage_details": {"output": 5},
                },
                {"metadata": {"latency_ms": 20.0}},
            ],
        )
        self.assertEqual(client.observation.end_count, 1)

    def test_safe_observation_io_is_separate_immutable_and_fail_closed(self) -> None:
        observer = MemoryObserver()
        observation = observer.start_observation(
            "rag.query",
            as_type="chain",
            metadata={"trace_id": "a" * 32},
            input={"request_id": "req_0123456789abcdef01234567", "stack_id": "api"},
        )
        observation.update(
            {"status": "completed"},
            output={"status": "answered", "citation_count": 2},
        )
        observation.update(output={"answer": "restricted answer"})
        observation.end()

        self.assertEqual(observer.dropped_count, 1)
        self.assertEqual(len(observer.records), 1)
        record = observer.records[0]
        self.assertEqual(record.as_type, "chain")
        self.assertEqual(
            dict(record.input or {}),
            {"request_id": "req_0123456789abcdef01234567", "stack_id": "api"},
        )
        self.assertEqual(
            dict(record.output or {}),
            {"status": "answered", "citation_count": 2},
        )
        self.assertNotIn("restricted answer", repr(record))

    def test_invalid_end_io_is_dropped_but_observation_still_closes(self) -> None:
        observer = MemoryObserver()
        observation = observer.start_observation("contract.validate", as_type="guardrail")
        observation.end({"contract_valid": True}, output={"answer": "restricted"})
        observation.end({"contract_valid": False})
        self.assertEqual(observer.dropped_count, 1)
        self.assertEqual(len(observer.records), 1)
        self.assertEqual(dict(observer.records[0].metadata), {})
        self.assertIsNone(observer.records[0].output)

    def test_langfuse_import_initialization_and_export_failures_are_isolated(self) -> None:
        with patch(
            "midprojectrag.observability._langfuse.importlib.import_module",
            side_effect=ImportError("langfuse is not installed"),
        ) as importer:
            observer = LangfuseObserver()
            result = observer.start_observation(
                "rag.query", metadata={"request_id": "req_0123456789abcdef01234567"}
            )
            self.assertIsInstance(result, NoopObservation)
            result = observer.start_observation(
                "rag.query", metadata={"request_id": "req_1123456789abcdef01234567"}
            )
            self.assertIsInstance(result, NoopObservation)
            self.assertEqual(observer.failure_count, 1)
            importer.assert_called_once_with("langfuse")
            observer.flush()

        client = _FakeClient(fail_start=True, fail_flush=True)
        observer = LangfuseObserver(client_factory=lambda: client)
        self.assertIsInstance(observer.start_observation("rag.query"), NoopObservation)
        observer.flush()
        self.assertEqual(observer.failure_count, 2)

        broken_observation = _FakeObservation(fail_update=True, fail_end=True)
        client = _FakeClient(observation=broken_observation, fail_shutdown=True)
        observer = LangfuseObserver(client_factory=lambda: client)
        observation = observer.start_observation("rag.query")
        observation.update({"status": "completed"})
        observation.end({"latency_ms": 1.0})
        observer.shutdown()
        self.assertEqual(observer.failure_count, 4)

    def test_langfuse_flush_is_explicit_and_does_not_initialize_unused_adapter(self) -> None:
        factory_calls = 0
        client = _FakeClient()

        def factory() -> _FakeClient:
            nonlocal factory_calls
            factory_calls += 1
            return client

        observer = LangfuseObserver(client_factory=factory)
        observer.flush()
        self.assertEqual(factory_calls, 0)
        observer.start_observation("rag.query").end()
        observer.flush()
        self.assertEqual(client.flush_count, 1)

    @unittest.skipIf(_InstalledLangfuse is None, "optional langfuse package is not installed")
    def test_installed_langfuse_v4_manual_api_is_adapter_compatible_without_export(self) -> None:
        client = _InstalledLangfuse(
            public_key="pk-lf-synthetic-test",
            secret_key="sk-lf-synthetic-test",
            base_url="http://127.0.0.1:9",
            tracing_enabled=False,
        )
        observer = LangfuseObserver(client_factory=lambda: client)
        with observer.start_observation(
            "rag.query",
            as_type="chain",
            metadata={"trace_id": "a" * 32, "status": "started"},
            input={"request_id": "req_0123456789abcdef01234567", "stack_id": "api"},
        ) as root:
            with observer.start_observation(
                "contract.validate",
                as_type="guardrail",
                input={"context_count": 1},
            ) as guardrail:
                guardrail.update(
                    {"contract_valid": True},
                    output={"contract_valid": True, "status": "answered", "citation_count": 1},
                )
            root.end(
                {"status": "completed", "success": True},
                output={"status": "answered", "citation_count": 1},
            )
        observer.score("a" * 32, "correctness", 1.0)
        observer.flush()
        self.assertEqual(observer.failure_count, 0)
        observer.shutdown()

    def test_langfuse_never_forwards_application_exception_details(self) -> None:
        client = _FakeClient()
        observer = LangfuseObserver(client_factory=lambda: client)
        with self.assertRaisesRegex(RuntimeError, "restricted source detail"):
            with observer.start_observation("rag.query", metadata={"status": "started"}):
                raise RuntimeError("restricted source detail")
        self.assertEqual(client.contexts[0].exit_arguments, [(None, None, None)])
        self.assertNotIn("restricted source detail", repr(client.start_calls))

    def test_scores_are_numeric_or_boolean_only_and_reuse_safe_trace_id(self) -> None:
        trace_id = "a" * 32
        memory = MemoryObserver()
        memory.score(trace_id, "faithfulness", 0.75)
        memory.score(trace_id, "safe_abstention", True)
        memory.score(trace_id, "reviewer_comment", 1.0)
        memory.score("not-a-trace", "faithfulness", 1.0)
        self.assertEqual(len(memory.scores), 2)
        self.assertEqual(memory.dropped_count, 2)

        client = _FakeClient()
        observer = LangfuseObserver(client_factory=lambda: client)
        root = observer.start_observation("rag.query", metadata={"trace_id": trace_id})
        root.end()
        observer.score(trace_id, "correctness", 0.9)
        observer.score(trace_id, "safe_abstention", True)
        self.assertEqual(
            client.start_calls[0]["trace_context"],
            {"trace_id": trace_id},
        )
        self.assertEqual(
            client.score_calls,
            [
                {
                    "trace_id": trace_id,
                    "name": "correctness",
                    "value": 0.9,
                    "data_type": "NUMERIC",
                },
                {
                    "trace_id": trace_id,
                    "name": "safe_abstention",
                    "value": 1.0,
                    "data_type": "BOOLEAN",
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()
