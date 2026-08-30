from __future__ import annotations

import unittest
from types import SimpleNamespace

from midprojectrag.answering.generation import (
    BilledGenerationError,
    generate_with_budget,
)
from midprojectrag.stacks.api import OpenAIGenerator
from midprojectrag.stacks.api.generation import (
    OPENAI_ANSWER_PLAN_SCHEMA,
    build_openai_answer_plan_schema,
)


class _Counter:
    def count(self, text: str) -> int:
        return max(1, len(text))


class _Budget:
    def __init__(self) -> None:
        self.commits = []
        self.releases = []

    def reserve(self, estimated_usd, operation_id):
        return "reservation"

    def commit(self, reservation_id, actual_usd):
        self.commits.append((reservation_id, actual_usd))

    def release(self, reservation_id):
        self.releases.append(reservation_id)


class OpenAIGeneratorTests(unittest.TestCase):
    def test_responses_api_uses_strict_structured_output_without_storage(self) -> None:
        calls = []
        response = SimpleNamespace(
            output_text=(
                '{"result":{"status":"abstained","answer":"",'
                '"citation_chunk_ids":[],"abstention_reason":'
                '"insufficient_evidence"}}'
            ),
            usage=SimpleNamespace(input_tokens=12, output_tokens=5),
        )
        client = SimpleNamespace(
            responses=SimpleNamespace(create=lambda **kwargs: calls.append(kwargs) or response)
        )
        starts = []
        generator = OpenAIGenerator(
            client=client,
            before_request=lambda: starts.append("started"),
        )
        plan, input_tokens, output_tokens = generator.generate("synthetic")
        self.assertEqual(plan["status"], "abstained")
        self.assertEqual((input_tokens, output_tokens), (12, 5))
        self.assertEqual(calls[0]["model"], "gpt-5-mini")
        self.assertIs(calls[0]["store"], False)
        self.assertEqual(calls[0]["reasoning"], {"effort": "minimal"})
        self.assertEqual(calls[0]["text"]["format"]["type"], "json_schema")
        schema = calls[0]["text"]["format"]["schema"]
        self.assertEqual(schema, OPENAI_ANSWER_PLAN_SCHEMA)
        self.assertEqual(schema["type"], "object")
        self.assertNotIn("anyOf", schema)
        variants = schema["properties"]["result"]["anyOf"]
        self.assertEqual(len(variants), 2)
        answered, abstained = variants
        self.assertEqual(
            answered["properties"]["citation_chunk_ids"]["minItems"], 1
        )
        self.assertEqual(
            answered["properties"]["citation_chunk_ids"]["maxItems"], 3
        )
        self.assertEqual(answered["properties"]["answer"]["pattern"], "\\S")
        self.assertEqual(
            abstained["properties"]["citation_chunk_ids"]["maxItems"], 0
        )
        self.assertNotIn(
            "uniqueItems",
            answered["properties"]["citation_chunk_ids"],
        )
        self.assertEqual(starts, ["started"])

    def test_response_schema_citation_limit_matches_generator_contract(self) -> None:
        for max_citations in (1, 5, 20):
            with self.subTest(max_citations=max_citations):
                schema = build_openai_answer_plan_schema(max_citations)
                answered = schema["properties"]["result"]["anyOf"][0]
                self.assertEqual(
                    answered["properties"]["citation_chunk_ids"]["maxItems"],
                    max_citations,
                )
        for invalid in (None, True, 0, 21):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "invalid_max_citations"):
                    build_openai_answer_plan_schema(invalid)

    def test_invalid_structured_output_envelope_is_a_billed_error(self) -> None:
        response = SimpleNamespace(
            output_text=(
                '{"status":"abstained","answer":"",'
                '"citation_chunk_ids":[],"abstention_reason":'
                '"insufficient_evidence"}'
            ),
            usage=SimpleNamespace(input_tokens=12, output_tokens=5),
        )
        client = SimpleNamespace(
            responses=SimpleNamespace(create=lambda **_kwargs: response)
        )

        with self.assertRaisesRegex(
            BilledGenerationError, "generation_output_envelope_invalid"
        ):
            OpenAIGenerator(client=client).generate("synthetic")

    def test_model_allowlist_is_owned_by_api_stack(self) -> None:
        with self.assertRaisesRegex(ValueError, "generator_model_not_allowlisted"):
            OpenAIGenerator(client=object(), model="qwen3.8:27b-mlx")

    def test_reasoning_effort_is_fail_closed_to_minimal(self) -> None:
        with self.assertRaisesRegex(ValueError, "reasoning_effort_not_supported"):
            OpenAIGenerator(client=object(), reasoning_effort="low")

    def test_billable_parse_failure_commits_actual_usage(self) -> None:
        response = SimpleNamespace(
            output_text="not-json",
            usage=SimpleNamespace(input_tokens=12, output_tokens=5),
        )
        client = SimpleNamespace(
            responses=SimpleNamespace(create=lambda **_kwargs: response)
        )
        generator = OpenAIGenerator(client=client)
        budget = _Budget()

        with self.assertRaisesRegex(
            BilledGenerationError, "generation_output_not_json"
        ):
            generate_with_budget(
                "synthetic",
                generator=generator,
                counter=_Counter(),
                budget=budget,
            )

        self.assertEqual(
            budget.commits,
            [("reservation", generator.estimate_cost(12, 5))],
        )
        self.assertEqual(budget.releases, [])

    def test_incomplete_response_commits_reported_usage(self) -> None:
        response = SimpleNamespace(
            status="incomplete",
            output_text='{"result":',
            usage=SimpleNamespace(input_tokens=120, output_tokens=2000),
        )
        client = SimpleNamespace(
            responses=SimpleNamespace(create=lambda **_kwargs: response)
        )
        generator = OpenAIGenerator(
            client=client,
            max_output_tokens=2000,
        )
        budget = _Budget()

        with self.assertRaisesRegex(
            BilledGenerationError, "generation_output_incomplete"
        ):
            generate_with_budget(
                "synthetic",
                generator=generator,
                counter=_Counter(),
                budget=budget,
            )

        self.assertEqual(
            budget.commits,
            [("reservation", generator.estimate_cost(120, 2000))],
        )
        self.assertEqual(budget.releases, [])

    def test_provider_call_exception_releases_reservation(self) -> None:
        def fail(**_kwargs):
            raise RuntimeError("provider_unavailable")

        client = SimpleNamespace(responses=SimpleNamespace(create=fail))
        generator = OpenAIGenerator(client=client)
        budget = _Budget()

        with self.assertRaisesRegex(RuntimeError, "provider_unavailable"):
            generate_with_budget(
                "synthetic",
                generator=generator,
                counter=_Counter(),
                budget=budget,
            )

        self.assertEqual(budget.commits, [])
        self.assertEqual(budget.releases, ["reservation"])


if __name__ == "__main__":
    unittest.main()
