"""EH2.6.c3.1 context source-receipt acceptance tests.

The tests are synthetic and offline.  Parent expansion is provenance context,
not Evidence, while table/figure bridges may add only exact store-linked
Evidence.  Neither factory accepts caller-selected IDs or invokes a provider.
"""

from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError
import gc
from hashlib import sha256
import inspect
import json
from pathlib import Path
import pickle
from tempfile import TemporaryDirectory
import unittest
from weakref import ref

from midprojectrag.evidence import Evidence, EvidenceStore, Locator, ProvenanceParent
from midprojectrag.orchestration import (
    BridgeContextReceipt,
    HarnessRuntimeBinding,
    ParentContextReceipt,
    create_harness_execution_config,
    execute_retrieval_fusion,
    execute_retrieval_lane,
    issue_bridge_context_receipts,
    issue_fact_retrieval_obligations,
    issue_fact_semantic_verification_obligation,
    issue_parent_context_receipts,
    validate_bridge_context_receipt,
    validate_parent_context_receipt,
)
from midprojectrag.retrieval.fusion import HybridChildRetriever

from tests.test_retrieval_obligations import (
    _SyntheticLane,
    _calls,
    _fact_bound,
)


def _canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _never_clock() -> int:
    raise AssertionError("context receipt issuance must not call the clock")


class _NeverVerifier:
    calls = 0

    def verify(self, request):
        type(self).calls += 1
        raise AssertionError("context receipt issuance must not call the verifier")


class _NeverReranker:
    calls = 0

    def rerank(self, request):
        type(self).calls += 1
        raise AssertionError("context receipt issuance must not call the reranker")


def _context_store() -> EvidenceStore:
    parents: list[ProvenanceParent] = []
    evidence: list[Evidence] = []
    for page in range(1, 4):
        doc_id = "doc-a"
        block_id = f"block-{page}"
        seed_text = f"private parent page {page}: budget evidence {page}"
        parent = ProvenanceParent(
            doc_id,
            "pdf_page",
            seed_text,
            (block_id,),
            Locator(page=page),
        )
        seed = Evidence(
            doc_id,
            "text",
            seed_text,
            parent.parent_id,
            (block_id,),
            Locator(page=page, char_range=(0, len(seed_text))),
        )
        parents.append(parent)
        evidence.append(seed)
        if page == 1:
            evidence.append(
                Evidence(
                    doc_id,
                    "table_row_group",
                    "private table bridge text",
                    parent.parent_id,
                    (block_id,),
                    Locator(page=page, row_range=(0, 1)),
                    support_refs=(seed.evidence_id,),
                )
            )
        elif page == 2:
            evidence.append(
                Evidence(
                    doc_id,
                    "figure_object",
                    "private figure bridge text",
                    parent.parent_id,
                    (block_id,),
                    Locator(page=page, bbox=(0.0, 0.0, 10.0, 10.0)),
                    support_refs=(seed.evidence_id,),
                )
            )
    return EvidenceStore(parents, evidence)


def _clone_slots(value):
    clone = object.__new__(type(value))
    for name in type(value).__slots__:
        if name != "__weakref__":
            object.__setattr__(clone, name, getattr(value, name))
    return clone


class ContextSourceReceiptAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.tempdir = Path(self._temporary.name)
        _NeverVerifier.calls = 0
        _NeverReranker.calls = 0
        self._root_graphs = {}

    def _case(self, *, name: str, context_limit: int = 8):
        store = _context_store()
        seeds = tuple(item for item in store.evidence if item.kind == "text")
        specs = tuple((item.evidence_id, item.doc_id) for item in reversed(seeds))
        dense_log = self.tempdir / f"{name}-dense.log"
        lexical_log = self.tempdir / f"{name}-lexical.log"
        retriever = HybridChildRetriever(
            store,
            _SyntheticLane(
                lane="dense",
                bundle_sha256=store.bundle_sha256,
                candidate_specs=specs,
                call_log_path=str(dense_log),
            ),
            _SyntheticLane(
                lane="lexical",
                bundle_sha256=store.bundle_sha256,
                candidate_specs=specs,
                call_log_path=str(lexical_log),
            ),
        )
        runtime = HarnessRuntimeBinding.for_test(
            store=store,
            retriever=retriever,
            verifier=_NeverVerifier(),
            reranker=_NeverReranker(),
            clock=_never_clock,
        )
        config = create_harness_execution_config(
            mode="e1_bounded",
            max_context_targets_per_obligation=context_limit,
        )
        bound = _fact_bound(store)
        retrieval = issue_fact_retrieval_obligations(
            bound=bound,
            store=store,
            config=config,
            runtime=runtime,
        )[0]
        dense = execute_retrieval_lane(
            obligation=retrieval,
            lane="dense",
            store=store,
            config=config,
            runtime=runtime,
        )
        lexical = execute_retrieval_lane(
            obligation=retrieval,
            lane="lexical",
            store=store,
            config=config,
            runtime=runtime,
        )
        fusion = execute_retrieval_fusion(
            obligation=retrieval,
            dense_receipt=dense,
            lexical_receipt=lexical,
            store=store,
            config=config,
            runtime=runtime,
        )
        semantic = issue_fact_semantic_verification_obligation(
            obligation=retrieval,
            fusion_receipt=fusion,
            store=store,
            config=config,
            runtime=runtime,
        )
        self._root_graphs[name] = (bound, retrieval, fusion)
        return (
            store,
            config,
            runtime,
            semantic,
            dense_log,
            lexical_log,
        )

    def _issue_parent(self, case):
        store, config, runtime, obligation, _dense, _lexical = case
        return issue_parent_context_receipts(
            obligation=obligation,
            store=store,
            config=config,
            runtime=runtime,
        )

    def _issue_bridge(self, case):
        store, config, runtime, obligation, _dense, _lexical = case
        return issue_bridge_context_receipts(
            obligation=obligation,
            store=store,
            config=config,
            runtime=runtime,
        )

    def test_parent_receipts_are_context_only_and_do_not_invent_evidence_ids(self):
        case = self._case(name="parent")
        store, config, runtime, obligation, dense_log, lexical_log = case
        provider_calls_before = (_calls(dense_log), _calls(lexical_log))

        receipts = self._issue_parent(case)

        expected_seeds = tuple(sorted(obligation.candidate_evidence_ids))
        self.assertEqual(
            tuple(receipt.seed_evidence_id for receipt in receipts), expected_seeds
        )
        self.assertTrue(receipts)
        for receipt in receipts:
            self.assertIs(type(receipt), ParentContextReceipt)
            seed = store.get(receipt.seed_evidence_id)
            parent = store.parent(seed.parent_id)
            self.assertEqual(receipt.outcome, "applied")
            self.assertEqual(receipt.semantic_obligation_sha256, obligation.obligation_sha256)
            self.assertEqual(receipt.parent_id, parent.parent_id)
            self.assertEqual(receipt.parent_kind, parent.kind)
            self.assertEqual(receipt.parent_doc_id, parent.doc_id)
            self.assertEqual(receipt.parent_content_sha256, parent.content_sha256)
            self.assertEqual(
                receipt.parent_locator_sha256,
                _canonical_sha256(parent.locator.to_dict()),
            )
            self.assertEqual(receipt.seed_stable_anchor.doc_id, seed.doc_id)
            self.assertEqual(receipt.seed_stable_anchor.evidence_kind, seed.kind)
            with self.assertRaises(KeyError):
                store.get(receipt.parent_id)
            payload = receipt.to_dict()
            serialized = json.dumps(payload, ensure_ascii=False)
            for forbidden_key in (
                "parent_evidence_id",
                "candidate_evidence_ids",
                "verified_evidence_ids",
                "support_evidence_ids",
                "citation_evidence_ids",
                "text",
            ):
                self.assertNotIn(forbidden_key, payload)
            self.assertNotIn(parent.text, serialized)
            self.assertNotIn(seed.text, serialized)
            validate_parent_context_receipt(
                receipt=receipt,
                obligation=obligation,
                store=store,
                config=config,
                runtime=runtime,
            )
        self.assertEqual((_calls(dense_log), _calls(lexical_log)), provider_calls_before)
        self.assertEqual((_NeverVerifier.calls, _NeverReranker.calls), (0, 0))

    def test_bridge_receipts_use_actual_links_and_record_applied_or_empty(self):
        case = self._case(name="bridge")
        store, config, runtime, obligation, dense_log, lexical_log = case
        provider_calls_before = (_calls(dense_log), _calls(lexical_log))

        receipts = self._issue_bridge(case)

        expected_seeds = tuple(sorted(obligation.candidate_evidence_ids))
        self.assertEqual(len(receipts), 2 * len(expected_seeds))
        self.assertEqual(
            tuple((item.bridge_kind, item.seed_evidence_id) for item in receipts),
            tuple(("table", seed) for seed in expected_seeds)
            + tuple(("figure", seed) for seed in expected_seeds),
        )
        kind_map = {"table": "table_row_group", "figure": "figure_object"}
        all_linked: set[str] = set()
        for receipt in receipts:
            self.assertIs(type(receipt), BridgeContextReceipt)
            evidence_kind = kind_map[receipt.bridge_kind]
            self.assertEqual(receipt.evidence_kind, evidence_kind)
            expected = store.bridge(
                receipt.seed_evidence_id, kinds=(evidence_kind,)
            )
            expected_ids = tuple(item.evidence_id for item in expected)
            self.assertEqual(receipt.linked_evidence_ids, expected_ids)
            self.assertEqual(
                receipt.outcome, "applied" if expected_ids else "empty"
            )
            self.assertEqual(
                tuple(anchor.doc_id for anchor in receipt.ordered_stable_anchors),
                tuple(item.doc_id for item in expected),
            )
            self.assertEqual(
                tuple(anchor.evidence_kind for anchor in receipt.ordered_stable_anchors),
                tuple(item.kind for item in expected),
            )
            self.assertEqual(receipt.semantic_obligation_sha256, obligation.obligation_sha256)
            validate_bridge_context_receipt(
                receipt=receipt,
                obligation=obligation,
                store=store,
                config=config,
                runtime=runtime,
            )
            all_linked.update(expected_ids)
        self.assertTrue(any(item.outcome == "applied" for item in receipts))
        self.assertTrue(any(item.outcome == "empty" for item in receipts))
        self.assertTrue(all_linked)
        self.assertEqual((_calls(dense_log), _calls(lexical_log)), provider_calls_before)
        self.assertEqual((_NeverVerifier.calls, _NeverReranker.calls), (0, 0))

    def test_seed_prefix_is_sorted_config_bounded_immutable_and_nonrecursive(self):
        case = self._case(name="prefix", context_limit=2)
        _store, _config, _runtime, obligation, _dense, _lexical = case
        expected_seeds = tuple(sorted(obligation.candidate_evidence_ids)[:2])

        parent_receipts = self._issue_parent(case)
        bridge_receipts = self._issue_bridge(case)

        self.assertEqual(
            tuple(item.seed_evidence_id for item in parent_receipts), expected_seeds
        )
        self.assertEqual(
            tuple((item.bridge_kind, item.seed_evidence_id) for item in bridge_receipts),
            tuple(("table", seed) for seed in expected_seeds)
            + tuple(("figure", seed) for seed in expected_seeds),
        )
        linked_ids = {
            linked
            for receipt in bridge_receipts
            for linked in receipt.linked_evidence_ids
        }
        self.assertTrue(
            linked_ids.isdisjoint(
                {receipt.seed_evidence_id for receipt in bridge_receipts}
            )
        )
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            parent_receipts[0].parent_id = "forged"  # type: ignore[misc]
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            bridge_receipts[0].outcome = "forged"  # type: ignore[misc]

    def test_public_factories_accept_no_caller_selected_ids_or_raw_authority(self):
        forbidden = {
            "candidate_ids",
            "candidate_evidence_ids",
            "seed_ids",
            "seed_evidence_id",
            "target_id",
            "target_evidence_id",
            "bridge_ids",
            "linked_evidence_ids",
            "parent_id",
            "query",
            "scope",
            "outcome",
            "gold",
            "qrels",
            "expected_answer",
        }
        for function in (
            issue_parent_context_receipts,
            issue_bridge_context_receipts,
            validate_parent_context_receipt,
            validate_bridge_context_receipt,
        ):
            with self.subTest(function=function.__name__):
                parameters = inspect.signature(function).parameters
                self.assertTrue(forbidden.isdisjoint(parameters))
                self.assertTrue(
                    all(
                        item.kind
                        not in {
                            inspect.Parameter.VAR_POSITIONAL,
                            inspect.Parameter.VAR_KEYWORD,
                        }
                        for item in parameters.values()
                    )
                )

    def test_receipts_are_factory_only_noncopyable_and_json_cannot_replay_authority(self):
        case = self._case(name="factory")
        store, config, runtime, obligation, _dense, _lexical = case
        receipts = (self._issue_parent(case)[0], self._issue_bridge(case)[0])
        validators = (
            validate_parent_context_receipt,
            validate_bridge_context_receipt,
        )

        with self.assertRaisesRegex(TypeError, "factory_required"):
            ParentContextReceipt()
        with self.assertRaisesRegex(TypeError, "factory_required"):
            BridgeContextReceipt()
        self.assertFalse(hasattr(ParentContextReceipt, "from_dict"))
        self.assertFalse(hasattr(BridgeContextReceipt, "from_dict"))
        for receipt, validator in zip(receipts, validators):
            with self.subTest(receipt=type(receipt).__name__):
                for operation in (copy.copy, copy.deepcopy, pickle.dumps):
                    with self.assertRaisesRegex(TypeError, "not_serializable"):
                        operation(receipt)
                with self.assertRaises((TypeError, ValueError)):
                    validator(
                        receipt=copy.deepcopy(receipt.to_dict()),
                        obligation=obligation,
                        store=store,
                        config=config,
                        runtime=runtime,
                    )

    def test_clone_drift_and_mixed_source_store_config_runtime_fail_closed(self):
        case = self._case(name="authority")
        store, config, runtime, obligation, _dense, _lexical = case
        parent = self._issue_parent(case)[0]
        bridge = self._issue_bridge(case)[0]
        provider_calls_before = (_calls(_dense), _calls(_lexical))

        for receipt, validator in (
            (parent, validate_parent_context_receipt),
            (bridge, validate_bridge_context_receipt),
        ):
            with self.subTest(receipt=type(receipt).__name__):
                with self.assertRaisesRegex(ValueError, "authority"):
                    validator(
                        receipt=_clone_slots(receipt),
                        obligation=obligation,
                        store=store,
                        config=config,
                        runtime=runtime,
                    )

        drifted = self._issue_parent(case)[1]
        object.__setattr__(drifted, "parent_id", "pr_forged")
        with self.assertRaisesRegex(ValueError, "drift|mismatch|hash"):
            validate_parent_context_receipt(
                receipt=drifted,
                obligation=obligation,
                store=store,
                config=config,
                runtime=runtime,
            )

        obligation_clone = _clone_slots(obligation)
        for issuer in (issue_parent_context_receipts, issue_bridge_context_receipts):
            with self.subTest(issuer=issuer.__name__, mixed="source"):
                with self.assertRaisesRegex(ValueError, "authority"):
                    issuer(
                        obligation=obligation_clone,
                        store=store,
                        config=config,
                        runtime=runtime,
                    )

        other_case = self._case(name="other-runtime")
        self._issue_parent(other_case)
        self._issue_bridge(other_case)
        cloned_store = EvidenceStore.from_dict(store.to_dict())
        cloned_config = type(config).from_dict(config.to_dict())
        other_runtime = other_case[2]
        validator_base = {
            "obligation": obligation,
            "store": store,
            "config": config,
            "runtime": runtime,
        }
        for receipt, validator in (
            (parent, validate_parent_context_receipt),
            (bridge, validate_bridge_context_receipt),
        ):
            for overrides in (
                {"obligation": obligation_clone},
                {"store": cloned_store},
                {"config": cloned_config},
                {"runtime": _clone_slots(runtime)},
                {"runtime": other_runtime},
                {
                    "obligation": other_case[3],
                    "store": other_case[0],
                    "config": other_case[1],
                    "runtime": other_case[2],
                },
            ):
                with self.subTest(
                    validator=validator.__name__, mixed=tuple(overrides)
                ):
                    with self.assertRaises((TypeError, ValueError)):
                        validator(
                            receipt=receipt,
                            **{**validator_base, **overrides},
                        )
        for overrides in (
            {"store": cloned_store},
            {"config": cloned_config},
            {"runtime": other_runtime},
        ):
            arguments = {
                "obligation": obligation,
                "store": store,
                "config": config,
                "runtime": runtime,
                **overrides,
            }
            for issuer in (
                issue_parent_context_receipts,
                issue_bridge_context_receipts,
            ):
                with self.subTest(issuer=issuer.__name__, mixed=tuple(overrides)):
                    with self.assertRaises((TypeError, ValueError)):
                        issuer(**arguments)
        self.assertEqual((_calls(_dense), _calls(_lexical)), provider_calls_before)
        self.assertEqual(
            (_calls(other_case[4]), _calls(other_case[5])),
            (("dense",), ("lexical",)),
        )
        self.assertEqual((_NeverVerifier.calls, _NeverReranker.calls), (0, 0))

    def test_receipt_payloads_are_content_free_and_repeat_issue_is_deterministic(self):
        case = self._case(name="no-leak")
        first_parent = self._issue_parent(case)
        first_bridge = self._issue_bridge(case)
        second_parent = self._issue_parent(case)
        second_bridge = self._issue_bridge(case)

        self.assertIs(second_parent, first_parent)
        self.assertIs(second_bridge, first_bridge)
        self.assertTrue(
            all(
                current is original
                for current, original in zip(second_parent, first_parent)
            )
        )
        self.assertTrue(
            all(
                current is original
                for current, original in zip(second_bridge, first_bridge)
            )
        )
        self.assertEqual(
            tuple(item.to_dict() for item in second_parent),
            tuple(item.to_dict() for item in first_parent),
        )
        self.assertEqual(
            tuple(item.to_dict() for item in second_bridge),
            tuple(item.to_dict() for item in first_bridge),
        )
        serialized = json.dumps(
            [item.to_dict() for item in first_parent + first_bridge],
            ensure_ascii=False,
        )
        for forbidden in (
            "private parent",
            "private table",
            "private figure",
            "사업 예산은 얼마인가?",
            "gold",
            "qrels",
            "expected_answer",
            "provider",
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual((_NeverVerifier.calls, _NeverReranker.calls), (0, 0))

    def test_context_history_survives_semantic_gc_while_root_source_is_live(self):
        case = self._case(name="root-lifetime")
        store, config, runtime, obligation, _dense, _lexical = case
        root_source, retrieval, fusion = self._root_graphs["root-lifetime"]
        first_parent = self._issue_parent(case)
        first_bridge = self._issue_bridge(case)
        obligation_sha256 = obligation.obligation_sha256
        old_obligation = ref(obligation)

        del case
        del obligation
        gc.collect()
        self.assertIsNone(old_obligation())

        equivalent = issue_fact_semantic_verification_obligation(
            obligation=retrieval,
            fusion_receipt=fusion,
            store=store,
            config=config,
            runtime=runtime,
        )
        self.assertEqual(equivalent.obligation_sha256, obligation_sha256)
        self.assertIsNotNone(root_source)

        second_parent = issue_parent_context_receipts(
            obligation=equivalent,
            store=store,
            config=config,
            runtime=runtime,
        )
        second_bridge = issue_bridge_context_receipts(
            obligation=equivalent,
            store=store,
            config=config,
            runtime=runtime,
        )
        self.assertTrue(
            all(first is second for first, second in zip(first_parent, second_parent))
        )
        self.assertTrue(
            all(first is second for first, second in zip(first_bridge, second_bridge))
        )
        validate_parent_context_receipt(
            receipt=first_parent[0],
            obligation=equivalent,
            store=store,
            config=config,
            runtime=runtime,
        )
        validate_bridge_context_receipt(
            receipt=first_bridge[0],
            obligation=equivalent,
            store=store,
            config=config,
            runtime=runtime,
        )


if __name__ == "__main__":
    unittest.main()
