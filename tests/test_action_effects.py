from dataclasses import FrozenInstanceError
import unittest

import midprojectrag.orchestration.action_effects as action_effects


def _result(disposition, support_indexes, values=()):
    return {
        "schema_version": "1.0",
        "disposition": disposition,
        "support_indexes": list(support_indexes),
        "values": list(values),
    }


def _value(value_type, canonical_value, support_indexes):
    return {
        "value_type": value_type,
        "canonical_value": canonical_value,
        "support_indexes": list(support_indexes),
    }


class SemanticVerifierNormalizationTests(unittest.TestCase):
    def _normalize(
        self,
        raw_result,
        *,
        field=None,
        supplied=("candidate-a", "context-a", "candidate-b"),
        promotable=("candidate-a", "candidate-b"),
    ):
        return action_effects._normalize_semantic_verifier_result(
            raw_result,
            field=field,
            ordered_supplied_ids=supplied,
            promotable_ids=promotable,
        )

    def test_fieldless_support_maps_indexes_and_is_immutable(self):
        projection = self._normalize(_result("supported", (2, 0)))

        self.assertEqual(projection.disposition, "supported")
        self.assertEqual(
            projection.verified_evidence_ids,
            ("candidate-a", "candidate-b"),
        )
        self.assertEqual(projection.contradicted_evidence_ids, ())
        self.assertEqual(projection.values, ())
        self.assertRegex(projection.result_sha256, r"^[0-9a-f]{64}$")
        with self.assertRaises(FrozenInstanceError):
            projection.disposition = "unsupported"
        with self.assertRaises(TypeError):
            action_effects.SemanticValueSupport()

    def test_field_support_canonicalizes_text_and_binds_exact_union(self):
        projection = self._normalize(
            _result(
                "supported",
                (2, 0),
                (_value("text", "한글", (0, 2)),),
            ),
            field="business_name",
        )

        self.assertEqual(projection.verified_evidence_ids, ("candidate-a", "candidate-b"))
        self.assertEqual(projection.values[0].canonical_value, "한글")
        self.assertEqual(
            projection.values[0].support_evidence_ids,
            ("candidate-a", "candidate-b"),
        )
        with self.assertRaises(FrozenInstanceError):
            projection.values[0].canonical_value = "forged"

    def test_contradiction_requires_distinct_values_and_independent_support(self):
        projection = self._normalize(
            _result(
                "contradicted",
                (1, 0),
                (
                    _value("krw_amount", "200", (1,)),
                    _value("krw_amount", "100", (0,)),
                ),
            ),
            field="budget",
            supplied=("evidence-a", "evidence-b"),
            promotable=("evidence-a", "evidence-b"),
        )

        self.assertEqual(projection.verified_evidence_ids, ())
        self.assertEqual(
            projection.contradicted_evidence_ids,
            ("evidence-a", "evidence-b"),
        )
        self.assertEqual(
            tuple(value.canonical_value for value in projection.values),
            ("100", "200"),
        )

        with self.assertRaisesRegex(ValueError, "support_not_independent"):
            self._normalize(
                _result(
                    "contradicted",
                    (0, 2),
                    (
                        _value("text", "one", (0, 2)),
                        _value("text", "two", (2,)),
                    ),
                ),
                field="score",
            )

    def test_schema_indexes_and_promotability_fail_closed(self):
        invalid_results = (
            True,
            {"schema_version": "1.0"},
            {**_result("supported", (0,)), "schema_version": "2.0"},
            _result("unavailable", ()),
            {
                **_result("supported", (0,)),
                "extra": "forbidden",
            },
            {
                **_result("supported", (0,)),
                "values": (),
            },
            {
                **_result("supported", (0,)),
                "support_indexes": (0,),
            },
            _result("supported", (True,)),
            _result("supported", (-1,)),
            _result("supported", (0, 0)),
            _result("supported", (3,)),
            _result("supported", (1,)),
        )
        for raw_result in invalid_results:
            with self.subTest(raw_result=raw_result):
                with self.assertRaises((TypeError, ValueError)):
                    self._normalize(raw_result)

    def test_value_shape_and_indexes_fail_closed(self):
        invalid_values = (
            "not-a-value-object",
            {
                **_value("text", "x", (0,)),
                "extra": "forbidden",
            },
            {
                "value_type": "text",
                "canonical_value": "x",
            },
            _value("text", "x", (3,)),
            _value("text", "x", (1,)),
            _value("text", "x", (0, 0)),
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises((TypeError, ValueError)):
                    self._normalize(
                        _result("supported", (0,), (value,)),
                        field="business_name",
                    )

    def test_disposition_and_value_coherence_fail_closed(self):
        invalid = (
            (_result("supported", ()), None),
            (_result("supported", (0,), (_value("text", "x", (0,)),)), None),
            (_result("supported", (0,)), "field"),
            (
                _result(
                    "supported",
                    (0, 2),
                    (_value("text", "x", (0,)),),
                ),
                "field",
            ),
            (_result("unsupported", (0,)), None),
            (
                _result("unsupported", (), (_value("text", "x", (0,)),)),
                "field",
            ),
            (
                _result(
                    "contradicted",
                    (0, 2),
                    (_value("text", "x", (0,)),),
                ),
                "field",
            ),
            (
                _result(
                    "contradicted",
                    (0, 2),
                    (
                        _value("text", "x", (0,)),
                        _value("text", "x", (2,)),
                    ),
                ),
                "field",
            ),
            (
                _result(
                    "contradicted",
                    (0, 2),
                    (
                        _value("text", "x", (0,)),
                        _value("number", "2", (2,)),
                    ),
                ),
                "field",
            ),
        )
        for raw_result, field in invalid:
            with self.subTest(raw_result=raw_result, field=field):
                with self.assertRaises((TypeError, ValueError)):
                    self._normalize(raw_result, field=field)

        fieldless_conflict = self._normalize(_result("contradicted", (2, 0)))
        self.assertEqual(fieldless_conflict.verified_evidence_ids, ())
        self.assertEqual(
            fieldless_conflict.contradicted_evidence_ids,
            ("candidate-a", "candidate-b"),
        )
        self.assertEqual(fieldless_conflict.values, ())

    def test_closed_value_types_accept_only_canonical_strings(self):
        accepted = (
            ("krw_amount", "0"),
            ("krw_amount", "57000000"),
            ("kst_datetime", "2026-09-05T15:39:00+09:00"),
            ("duration", "PT0S"),
            ("duration", "P1Y2M3DT4H5M6S"),
            ("boolean", "true"),
            ("number", "0"),
            ("number", "-0.5"),
            ("number", "12.34"),
        )
        for value_type, canonical_value in accepted:
            with self.subTest(value_type=value_type, canonical_value=canonical_value):
                self.assertEqual(
                    action_effects._canonical_value(value_type, canonical_value),
                    canonical_value,
                )

        rejected = (
            ("krw_amount", "01"),
            ("krw_amount", "-1"),
            ("krw_amount", True),
            ("kst_datetime", "2026-09-05T15:39:00Z"),
            ("kst_datetime", "2026-02-30T15:39:00+09:00"),
            ("duration", "P"),
            ("duration", "PT"),
            ("boolean", "True"),
            ("number", "-0"),
            ("number", "1.0"),
            ("number", "NaN"),
            ("number", "Infinity"),
            ("number", "1e3"),
            ("number", False),
            ("object", "x"),
        )
        for value_type, canonical_value in rejected:
            with self.subTest(value_type=value_type, canonical_value=canonical_value):
                with self.assertRaises((TypeError, ValueError)):
                    action_effects._canonical_value(
                        value_type,
                        canonical_value,
                    )

    def test_field_type_mapping_and_text_hygiene(self):
        cases = (
            ("budget", "krw_amount", "57000000"),
            ("duration", "duration", "P30D"),
            ("deadline", "kst_datetime", "2026-09-05T15:39:00+09:00"),
            ("joint_contract", "boolean", "true"),
            ("subcontract", "boolean", "false"),
            ("business_name", "text", " 사업\t 이름\n "),
        )
        for field, value_type, canonical_value in cases:
            with self.subTest(field=field):
                projection = self._normalize(
                    _result(
                        "supported",
                        (0,),
                        (_value(value_type, canonical_value, (0,)),),
                    ),
                    field=field,
                )
                expected = "사업 이름" if value_type == "text" else canonical_value
                self.assertEqual(projection.values[0].canonical_value, expected)

        for field, value_type, value in (
            ("budget", "text", "57000000"),
            ("duration", "number", "30"),
            ("deadline", "text", "2026-09-05"),
            ("joint_contract", "text", "true"),
            ("other", "number", "1"),
        ):
            with self.subTest(field=field, value_type=value_type):
                with self.assertRaisesRegex(ValueError, "not_approved_for_field"):
                    self._normalize(
                        _result(
                            "supported",
                            (0,),
                            (_value(value_type, value, (0,)),),
                        ),
                        field=field,
                    )

        for text in (
            "x\x00y",
            "x\x1cy",
            "x\u200by",
            "가" * 4097,
            "가" * 1366,
        ):
            with self.subTest(text_length=len(text)):
                with self.assertRaises(ValueError):
                    action_effects._canonical_value("text", text)
        with self.assertRaisesRegex(ValueError, "too_long"):
            action_effects._canonical_value("number", "1" * 129)

    def test_result_hash_is_stable_across_untrusted_array_order(self):
        first = self._normalize(
            _result(
                "contradicted",
                (0, 2),
                (
                    _value("text", "two", (2,)),
                    _value("text", "one", (0,)),
                ),
            ),
            field="score",
        )
        second = self._normalize(
            _result(
                "contradicted",
                (2, 0),
                (
                    _value("text", "one", (0,)),
                    _value("text", "two", (2,)),
                ),
            ),
            field="score",
        )

        self.assertEqual(first.to_dict(), second.to_dict())


if __name__ == "__main__":
    unittest.main()
