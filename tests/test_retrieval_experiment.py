from copy import deepcopy
import unittest

from midprojectrag.retrieval_experiment import make_draft, validate_draft


class RetrievalExperimentTests(unittest.TestCase):
    def setUp(self):
        self.artifacts = dict.fromkeys(("input_inventory", "source_snapshot", "evidence_store",
                                       "page_index", "child_dense", "child_lexical"), "a" * 64)

    def test_draft_is_closed_retrieval_only_and_canonical(self):
        result = make_draft(self.artifacts)
        self.assertEqual(validate_draft(result), result["config_sha256"])
        self.assertFalse(result["formal_comparison_authorized"])
        self.assertEqual(result["status"], "draft")
        self.assertEqual(result["measurement_kind"], "retrieval_only")

    def test_arm_stage_and_granularity_are_explicit(self):
        arms = make_draft(self.artifacts)["arms"]
        self.assertEqual([a["arm_id"] for a in arms], ["page_kure", "child_kure", "child_bm25_rrf"])
        self.assertEqual([a["pre_context_stage"] for a in arms], ["lane_dense", "lane_dense", "fusion"])
        self.assertEqual([a["granularity"] for a in arms], ["page", "child", "child"])
        self.assertEqual([a["lexical_k"] for a in arms], [0, 0, 50])

    def test_common_query_scope_history_policy(self):
        result = make_draft(self.artifacts)
        self.assertEqual(result["query_policy"]["history_turns"], 4)
        self.assertEqual(result["query_policy"]["max_input_tokens"], 8192)
        self.assertEqual(result["scope_policy"], "original_user_scope_no_gold_fallback_v1")
        self.assertTrue(all("query" not in arm and "scope" not in arm for arm in result["arms"]))

    def test_unknown_or_gold_fields_are_rejected_even_with_recomputed_hash(self):
        from midprojectrag.stage_checkpoints import canonical_sha
        for extra in ("required_doc_ids", "question", "api_key", "generator", "runtime_request"):
            result = make_draft(self.artifacts)
            result[extra] = "not allowed"
            result["config_sha256"] = canonical_sha({k: v for k, v in result.items() if k != "config_sha256"})
            with self.assertRaises(ValueError): validate_draft(result)

    def test_formal_promotion_and_hash_drift_are_rejected(self):
        for key, value in (("status", "frozen"), ("formal_comparison_authorized", True),
                           ("measurement_kind", "end_to_end"), ("config_sha256", "b" * 64)):
            result = make_draft(self.artifacts)
            result[key] = value
            with self.assertRaises(ValueError): validate_draft(result)

    def test_artifact_identity_changes_config_and_does_not_mutate_input(self):
        before = deepcopy(self.artifacts)
        first = make_draft(self.artifacts)
        self.assertEqual(before, self.artifacts)
        first["artifact_hashes"]["evidence_store"] = "b" * 64
        self.assertEqual(before, self.artifacts)
        second = make_draft({**self.artifacts, "evidence_store": "b" * 64})
        self.assertNotEqual(make_draft(self.artifacts)["config_sha256"], second["config_sha256"])

    def test_hash_inventory_and_values_are_checked(self):
        for bad in ({}, {**self.artifacts, "extra": "a" * 64}, {**self.artifacts, "page_index": "bad"}):
            with self.assertRaises(ValueError): make_draft(bad)

    def test_arm_override_bool_zero_and_order_rejected(self):
        from midprojectrag.stage_checkpoints import canonical_sha
        for change in (lambda p: p["arms"][0].update(dense_k=True),
                       lambda p: p["arms"][0].update(dense_k=0),
                       lambda p: p["arms"][0].update(pre_context_stage="fusion"),
                       lambda p: p["arms"].reverse(),
                       lambda p: p["query_policy"].update(history_turns=4.0),
                       lambda p: p["context"].update(final_k=11),
                       lambda p: p["arms"][0].update(query="private")):
            payload = make_draft(self.artifacts)
            change(payload)
            payload["config_sha256"] = canonical_sha({k: v for k, v in payload.items() if k != "config_sha256"})
            with self.assertRaises(ValueError): validate_draft(payload)
