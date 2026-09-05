"""Synthetic offline projection checks; no provider, corpus, or gold I/O."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from midprojectrag.evidence import Evidence, EvidenceStore, Locator, ProvenanceParent
from midprojectrag.retrieval import Candidate
from midprojectrag.retrieval.context import ContextPack, select_context
from midprojectrag.stage_checkpoints import (
    SCHEMA, STAGES, canonical_sha, checkpoint_from_receipt,
    final_context_checkpoint, make_checkpoint, source_block_anchor_sha,
    stable_projection, validate_checkpoint,
)


def _store(*, kind="text", offset=0):
    body = "private-source-sentinel one\nprivate-source-sentinel two"
    parent = ProvenanceParent("doc-a", "pdf_page", body, ("block-a",), Locator(page=1))
    pieces = ("private-source-sentinel one", "private-source-sentinel two")
    evidence = tuple(Evidence(
        "doc-a", kind, text, parent.parent_id, ("block-a",),
        Locator(page=1, char_range=(start, start + len(text))),
    ) for text, start in zip(pieces, (offset, len(pieces[0]) + 1)))
    return EvidenceStore((parent,), evidence)


def _binding(store):
    return {
        "query_sha256": "a" * 64, "scope_sha256": "b" * 64,
        "evidence_store_sha256": store.bundle_sha256,
        "run_config_sha256": "c" * 64, "execution_key_sha256": "d" * 64,
    }


class StageCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.store = _store()
        self.ids = [item.evidence_id for item in self.store.evidence]
        self.binding = _binding(self.store)

    def checkpoint(self, *, stage="fusion", ids=None, **updates):
        return make_checkpoint(
            stage, self.ids if ids is None else ids, store=self.store,
            binding=self.binding, stage_config_sha256="e" * 64,
            source_receipt_sha256="f" * 64, **updates,
        )

    def test_all_stages_roundtrip_content_free_and_rank_preserving(self):
        for stage, ordinal in STAGES.items():
            with self.subTest(stage=stage):
                result = self.checkpoint(stage=stage)
                validate_checkpoint(result, self.store, self.binding)
                self.assertEqual((result["schema_version"], result["stage_ordinal"]), (SCHEMA, ordinal))
                self.assertEqual(result["ordered_evidence_ids"], self.ids)
                self.assertEqual(result["candidate_count"], 2)
                self.assertEqual(result["ordered_stable_anchors"][0], result["ordered_stable_anchors"][1])
                self.assertNotIn("private-source-sentinel", json.dumps(result))
                self.assertNotIn("parent_windows", result)
                self.assertEqual(result, json.loads(json.dumps(result)))

    def test_anchor_matches_runtime_join_key_and_retains_evidence_kind(self):
        from midprojectrag.orchestration.execution_contracts import StableEvidenceAnchor

        projected = stable_projection(self.store, self.ids[0])
        anchor = {
            "schema_version": "1.0", **projected,
            "locator_identity_sha256": "a" * 64,
        }
        runtime = StableEvidenceAnchor(
            "doc-a", ("block-a",), (source_block_anchor_sha("doc-a", "block-a"),),
            "text", "a" * 64, canonical_sha(anchor),
        )
        self.assertEqual(projected["source_block_anchor_sha256s"], list(runtime.source_block_anchor_sha256s))
        page_store = _store(kind="page")
        self.assertEqual(stable_projection(page_store, page_store.evidence[0].evidence_id)["evidence_kind"], "page")

    def test_actual_empty_search_is_distinct_from_unavailable_and_error(self):
        empty = self.checkpoint(ids=[])
        self.assertEqual((empty["outcome"], empty["call_performed"]), ("ok", True))
        for outcome in ("unavailable", "error"):
            result = self.checkpoint(ids=[], outcome=outcome, call_performed=False)
            validate_checkpoint(result, self.store, self.binding)
            with self.assertRaises(ValueError):
                self.checkpoint(outcome=outcome)
        with self.assertRaises(ValueError):
            self.checkpoint(ids=[], call_performed=False)

    def test_closed_bindings_ids_and_sha_values(self):
        with self.assertRaises(ValueError):
            self.checkpoint(ids=[self.ids[0], self.ids[0]])
        with self.assertRaises(ValueError):
            self.checkpoint(ids=["unknown-evidence"])
        for field, value in (("query_sha256", "A" * 64), ("scope_sha256", "gold"), ("expected", "e" * 64)):
            changed = {**self.binding, field: value}
            with self.subTest(field=field), self.assertRaises(ValueError):
                make_checkpoint("fusion", [], store=self.store, binding=changed,
                                stage_config_sha256="e" * 64, source_receipt_sha256="f" * 64)

    def test_changed_binding_and_wrong_store_are_rejected(self):
        result = self.checkpoint()
        for field in self.binding:
            changed = {**self.binding, field: "0" * 64}
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_checkpoint(result, self.store, changed)
        with self.assertRaises(ValueError):
            validate_checkpoint(result, _store(kind="page"), self.binding)

    def test_hash_is_not_a_substitute_for_schema_and_store_anchor_validation(self):
        original = self.checkpoint()
        changes = (
            ("stage_ordinal", True), ("candidate_count", True),
            ("call_performed", 1), ("stage", "unknown"),
            ("schema_version", "other"), ("question", "private-input"),
        )
        for key, value in changes:
            modified = {**deepcopy(original), key: value}
            modified["projection_sha256"] = canonical_sha({k: v for k, v in modified.items() if k != "projection_sha256"})
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_checkpoint(modified, self.store, self.binding)
        modified = deepcopy(original)
        modified["ordered_stable_anchors"][0]["doc_id"] = "another-doc"
        modified["projection_sha256"] = canonical_sha({k: v for k, v in modified.items() if k != "projection_sha256"})
        with self.assertRaises(ValueError):
            validate_checkpoint(modified, self.store, self.binding)
        modified = deepcopy(original)
        modified["projection_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            validate_checkpoint(modified, self.store, self.binding)

    def test_final_context_uses_actual_selection_without_parent_text(self):
        candidates = tuple(Candidate(item, "doc-a", 1.0 / rank, "dense", rank, "child")
                           for rank, item in enumerate(self.ids, 1))
        context = select_context(candidates, self.store, final_k=1)
        self.assertTrue(context.parent_windows)
        result = final_context_checkpoint(
            context, store=self.store, binding=self.binding,
            stage_config_sha256="e" * 64, source_receipt_sha256="f" * 64,
        )
        self.assertEqual(result["ordered_evidence_ids"], list(context.evidence_ids))
        self.assertEqual(result["candidate_count"], 1)
        self.assertNotIn("private-source-sentinel", json.dumps(result))
        validate_checkpoint(result, self.store, self.binding)

    def test_context_hash_count_and_plain_mapping_are_rejected(self):
        for trace in (
            {"bundle_sha256": "0" * 64},
            {"bundle_sha256": self.store.bundle_sha256, "post_count": 2},
        ):
            context = ContextPack((self.ids[0],), (), trace)
            with self.subTest(trace=trace), self.assertRaises(ValueError):
                final_context_checkpoint(context, store=self.store, binding=self.binding,
                                         stage_config_sha256="e" * 64, source_receipt_sha256="f" * 64)
        with self.assertRaises(TypeError):
            checkpoint_from_receipt(self.checkpoint(), store=self.store)

    def test_projection_does_not_retain_mutable_input_or_returned_binding(self):
        ids = list(self.ids)
        result = self.checkpoint(ids=ids)
        ids.clear()
        result["binding"]["scope_sha256"] = "0" * 64
        self.assertEqual(self.binding["scope_sha256"], "b" * 64)
        self.assertEqual(result["ordered_evidence_ids"], self.ids)

    def test_issued_lane_and_fusion_receipts_project_same_chain(self):
        from midprojectrag.orchestration import (
            create_harness_execution_config, execute_retrieval_fusion,
            execute_retrieval_lane, issue_fact_retrieval_obligations,
        )
        from tests.test_retrieval_obligations import _fact_bound, _runtime, _store as runtime_store

        with TemporaryDirectory() as directory:
            store = runtime_store(doc_ids=("doc-a",))
            runtime = _runtime(store=store, dense_log=Path(directory) / "dense.log",
                               lexical_log=Path(directory) / "lexical.log")
            config = create_harness_execution_config(mode="e0_once")
            obligation = issue_fact_retrieval_obligations(
                bound=_fact_bound(store), store=store, config=config, runtime=runtime,
            )[0]
            arguments = {"obligation": obligation, "store": store, "config": config, "runtime": runtime}
            dense = execute_retrieval_lane(lane="dense", **arguments)
            lexical = execute_retrieval_lane(lane="lexical", **arguments)
            fusion = execute_retrieval_fusion(dense_receipt=dense, lexical_receipt=lexical, **arguments)
            results = [checkpoint_from_receipt(item, store=store) for item in (dense, lexical, fusion)]
            self.assertEqual([item["stage_ordinal"] for item in results], [1, 2, 4])
            for source, result in zip((dense, lexical, fusion), results):
                self.assertEqual(result["binding"], results[0]["binding"])
                self.assertEqual(result["source_receipt_sha256"], source.receipt_sha256)
                validate_checkpoint(result, store, results[0]["binding"])
                self.assertNotIn("gold-must-not-leak", json.dumps(result))
                self.assertNotIn("question", result)


if __name__ == "__main__":
    unittest.main()
