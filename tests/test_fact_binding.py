from copy import deepcopy
from collections.abc import Mapping
import inspect
from types import MappingProxyType
import unittest
from unittest.mock import patch

from midprojectrag.evidence import Evidence, EvidenceStore, Locator, ProvenanceParent
from midprojectrag.orchestration import (
    BoundFact,
    CatalogEntity,
    DeterministicPlanner,
    FactBindingTrace,
    PlanningCatalog,
    PlanningResult,
    bind_fact,
    build_fact_harness_state,
    default_rule_registry,
    replay_bound_fact,
    replay_harness_state,
    validate_bound_fact,
    validate_harness_state,
)
from midprojectrag.runtime_integrity import MetadataPredicate, RuntimeRequest


def _store(doc_ids=("doc-a", "doc-b")):
    parents = []
    evidence = []
    for page, doc_id in enumerate(doc_ids, 1):
        text = f"{doc_id} 사업 예산 100원 수행기간 10일"
        parent = ProvenanceParent(
            doc_id,
            "pdf_page",
            text,
            (f"block-{doc_id}",),
            Locator(page=page),
        )
        child = Evidence(
            doc_id,
            "text",
            text,
            parent.parent_id,
            (f"block-{doc_id}",),
            Locator(page=page, char_range=(0, len(text))),
        )
        parents.append(parent)
        evidence.append(child)
    return EvidenceStore(parents, evidence), tuple(evidence)


def _catalog(doc_ids=("doc-a", "doc-b")):
    return PlanningCatalog.synthetic(
        "fact-binding-fixture-v1",
        tuple(
            CatalogEntity(
                f"사업{index}",
                f"사업{index}",
                "business",
                (doc_id,),
                "business_alias",
            )
            for index, doc_id in enumerate(doc_ids, 1)
        ),
    )


def _fixture(*, request=None, store=None, catalog=None):
    store = _store()[0] if store is None else store
    registry = default_rule_registry()
    planner = DeterministicPlanner.for_test(
        registry,
        _catalog() if catalog is None else catalog,
    )
    request = request or RuntimeRequest(
        question="사업 예산은 얼마인가?",
        document_scope={"mode": "explicit", "doc_ids": ["doc-a"]},
    )
    planning = planner.plan(request)
    return store, registry, planner, request, planning


class _BombCatalog(PlanningCatalog):
    calls = 0

    def to_dict(self):
        type(self).calls += 1
        raise AssertionError("untrusted catalog method executed")


def _bomb_catalog_from(source):
    result = object.__new__(_BombCatalog)
    for name in PlanningCatalog.__slots__:
        object.__setattr__(result, name, getattr(source, name))
    return result


class _BombRequestMap(Mapping):
    def __init__(self):
        self.calls = 0

    def __getitem__(self, key):
        self.calls += 1
        raise AssertionError("untrusted request mapping lookup executed")

    def __iter__(self):
        self.calls += 1
        raise AssertionError("untrusted request mapping iteration executed")

    def __len__(self):
        self.calls += 1
        raise AssertionError("untrusted request mapping length executed")


class _BombString(str):
    calls = 0

    def __hash__(self):
        type(self).calls += 1
        raise AssertionError("untrusted string hash executed")

    def __ne__(self, other):
        type(self).calls += 1
        raise AssertionError("untrusted string comparison executed")


class _ArmedRuntimeString(str):
    armed = False
    calls = 0

    def strip(self, *args, **kwargs):
        if type(self).armed:
            type(self).calls += 1
            raise AssertionError("issued runtime string method executed")
        return str.strip(self, *args, **kwargs)


class FactBindingTests(unittest.TestCase):
    def test_ready_fact_is_planner_catalog_store_bound_and_builds_unsearched_state(self):
        store, _registry, planner, request, planning = _fixture()
        bound = bind_fact(
            request=request,
            planning=planning,
            store=store,
            planner=planner,
        )
        self.assertEqual(bound.trace.status, "ready")
        self.assertEqual(bound.trace.reason, "ready")
        self.assertEqual(bound.trace.resolved_doc_ids, ("doc-a",))
        self.assertEqual(bound.trace.evidence_bundle_sha256, store.bundle_sha256)
        self.assertEqual(bound.trace.catalog_sha256, planner.catalog.catalog_sha256)
        self.assertEqual(bound.trace.request_fingerprint, request.fingerprint)

        state = build_fact_harness_state(bound=bound, store=store)
        self.assertEqual(state.belief.source_kind, "fact")
        self.assertEqual(state.belief.query_type, "fact")
        self.assertEqual(state.progress.required_obligation_keys, ("$answer_support",))
        self.assertEqual(state.progress.open_obligation_keys, ("$answer_support",))
        self.assertEqual(state.belief.evidence_map[0].observation_stage, "unsearched")
        self.assertFalse(state.progress.normal_stop_allowed)
        self.assertFalse(state.progress.abstain_required)
        validate_bound_fact(bound=bound, store=store)
        validate_harness_state(state=state, store=store)
        serialized = str(state.to_dict()).lower()
        self.assertNotIn(planning.plan.normalized_query.lower(), serialized)
        self.assertNotIn("gold", serialized)
        self.assertNotIn("qrels", serialized)

    def test_unfiltered_fact_is_ready_but_empty_and_metadata_scopes_fail_closed(self):
        unfiltered = RuntimeRequest(question="일반 사업 예산을 알려줘")
        store, _registry, planner, request, planning = _fixture(request=unfiltered)
        bound = bind_fact(
            request=request,
            planning=planning,
            store=store,
            planner=planner,
        )
        self.assertEqual((bound.trace.status, bound.trace.reason), ("ready", "ready"))
        self.assertEqual(bound.trace.scope_state, "unfiltered")

        empty = RuntimeRequest(
            question="사업 예산은 얼마인가?",
            document_scope={"mode": "explicit", "doc_ids": []},
        )
        store, _registry, planner, request, planning = _fixture(request=empty)
        empty_bound = bind_fact(
            request=request,
            planning=planning,
            store=store,
            planner=planner,
        )
        self.assertEqual(
            (empty_bound.trace.status, empty_bound.trace.reason),
            ("not_ready", "fact_scope_empty"),
        )
        with self.assertRaisesRegex(ValueError, "fact_binding_not_ready"):
            build_fact_harness_state(bound=empty_bound, store=store)

        filtered = RuntimeRequest(
            question="사업 예산은 얼마인가?",
            metadata_filters=(
                {"field": "agency", "operator": "eq", "value": "기관A"},
            ),
        )
        store, _registry, planner, request, planning = _fixture(request=filtered)
        filtered_bound = bind_fact(
            request=request,
            planning=planning,
            store=store,
            planner=planner,
        )
        self.assertEqual(
            (filtered_bound.trace.status, filtered_bound.trace.reason),
            ("not_ready", "fact_metadata_scope_receipt_required"),
        )

        unsupported = RuntimeRequest(
            question="사업 예산은 얼마인가?",
            metadata_filters=(
                {"field": "unknown", "operator": "eq", "value": "x"},
            ),
        )
        store, _registry, planner, request, planning = _fixture(request=unsupported)
        unsupported_bound = bind_fact(
            request=request,
            planning=planning,
            store=store,
            planner=planner,
        )
        self.assertEqual(
            (unsupported_bound.trace.status, unsupported_bound.trace.reason),
            ("not_ready", "fact_metadata_unresolved"),
        )

        empty_catalog = PlanningCatalog.synthetic("empty-fact-catalog-v1", ())
        store, _registry, planner, request, planning = _fixture(
            request=RuntimeRequest(question="사업 예산을 알려줘"),
            catalog=empty_catalog,
        )
        no_catalog_bound = bind_fact(
            request=request,
            planning=planning,
            store=store,
            planner=planner,
        )
        self.assertEqual(
            (no_catalog_bound.trace.status, no_catalog_bound.trace.reason),
            ("not_ready", "fact_catalog_universe_empty"),
        )

    def test_restricted_scope_must_exist_in_both_catalog_and_store(self):
        request = RuntimeRequest(
            question="없는 문서의 예산은?",
            document_scope={"mode": "explicit", "doc_ids": ["doc-z"]},
        )
        store, _registry, planner, request, planning = _fixture(request=request)
        bound = bind_fact(
            request=request,
            planning=planning,
            store=store,
            planner=planner,
        )
        self.assertEqual(
            (bound.trace.status, bound.trace.reason),
            ("not_ready", "fact_document_not_in_catalog"),
        )
        with self.assertRaisesRegex(ValueError, "fact_binding_not_ready"):
            build_fact_harness_state(bound=bound, store=store)

        store_with_z, _evidence = _store(("doc-a", "doc-z"))
        store, _registry, planner, request, planning = _fixture(
            request=request,
            store=store_with_z,
        )
        missing_catalog = bind_fact(
            request=request,
            planning=planning,
            store=store,
            planner=planner,
        )
        self.assertEqual(missing_catalog.trace.reason, "fact_document_not_in_catalog")

        catalog_with_z = _catalog(("doc-a", "doc-z"))
        store_without_z, _evidence = _store(("doc-a",))
        store, _registry, planner, request, planning = _fixture(
            request=request,
            store=store_without_z,
            catalog=catalog_with_z,
        )
        missing_store = bind_fact(
            request=request,
            planning=planning,
            store=store,
            planner=planner,
        )
        self.assertEqual(missing_store.trace.reason, "fact_document_not_in_store")

    def test_unfiltered_fact_uses_the_exact_bound_store_without_catalog_clipping(self):
        store, _evidence = _store(("doc-a", "doc-extra"))
        store, _registry, planner, request, planning = _fixture(
            request=RuntimeRequest(question="사업 예산을 알려줘"),
            store=store,
            catalog=_catalog(("doc-a",)),
        )
        bound = bind_fact(
            request=request,
            planning=planning,
            store=store,
            planner=planner,
        )
        self.assertEqual((bound.trace.status, bound.trace.reason), ("ready", "ready"))
        self.assertEqual(bound.trace.resolved_doc_ids, ())
        build_fact_harness_state(bound=bound, store=store)

    def test_non_fact_planning_and_replayed_plan_mismatch_are_rejected(self):
        store, _registry, planner, _request, _planning = _fixture()
        compare = RuntimeRequest(
            question="사업1과 사업2의 예산을 비교해줘",
            document_scope={"mode": "explicit", "doc_ids": ["doc-a", "doc-b"]},
        )
        with self.assertRaisesRegex(ValueError, "fact_plan_required"):
            bind_fact(
                request=compare,
                planning=planner.plan(compare),
                store=store,
                planner=planner,
            )

        first = RuntimeRequest(question="첫 질문")
        second = RuntimeRequest(question="둘째 질문")
        with self.assertRaisesRegex(ValueError, "fact_planning_replay_mismatch"):
            bind_fact(
                request=first,
                planning=planner.plan(second),
                store=store,
                planner=planner,
            )

    def test_factory_identity_nested_identity_and_live_store_drift_are_rejected(self):
        store, _registry, planner, request, planning = _fixture()
        bound = bind_fact(
            request=request,
            planning=planning,
            store=store,
            planner=planner,
        )
        with self.assertRaises(TypeError):
            BoundFact()
        with self.assertRaises(TypeError):
            FactBindingTrace()

        clone = object.__new__(BoundFact)
        for name in BoundFact.__slots__:
            if name != "__weakref__":
                object.__setattr__(clone, name, getattr(bound, name))
        with self.assertRaisesRegex(ValueError, "bound_fact_runtime_authority_required"):
            validate_bound_fact(bound=clone, store=store)

        replacement = PlanningResult(bound.planning.plan, bound.planning.trace)
        object.__setattr__(bound, "planning", replacement)
        with self.assertRaisesRegex(ValueError, "bound_fact_nested_identity_drift"):
            validate_bound_fact(bound=bound, store=store)

        store, _registry, planner, request, planning = _fixture()
        bound = bind_fact(
            request=request,
            planning=planning,
            store=store,
            planner=planner,
        )
        child = store.evidence[0]
        object.__setattr__(child, "text", child.text + " 변조")
        with self.assertRaisesRegex(ValueError, "bound_fact_store_payload_drift"):
            validate_bound_fact(bound=bound, store=store)

        store, _registry, planner, request, planning = _fixture()
        bound = bind_fact(
            request=request,
            planning=planning,
            store=store,
            planner=planner,
        )
        evidence = store.evidence[0]
        object.__setattr__(
            store,
            "_evidence",
            MappingProxyType(
                {
                    **{
                        key: value
                        for key, value in store._evidence.items()
                        if key != evidence.evidence_id
                    },
                    "wrong-key": evidence,
                }
            ),
        )
        with self.assertRaisesRegex(ValueError, "bound_fact_store_payload_drift"):
            validate_bound_fact(bound=bound, store=store)

    def test_planner_catalog_identity_drift_is_rejected_before_replay(self):
        store, registry, planner, request, planning = _fixture()
        bound = bind_fact(
            request=request,
            planning=planning,
            store=store,
            planner=planner,
        )
        replacement = DeterministicPlanner.for_test(registry, _catalog())
        object.__setattr__(planner, "catalog", replacement.catalog)
        with self.assertRaisesRegex(ValueError, "bound_fact_planner_identity_drift"):
            validate_bound_fact(bound=bound, store=store)

    def test_catalog_subclass_is_rejected_before_overridden_methods_or_replay(self):
        store, _registry, planner, request, planning = _fixture()
        _BombCatalog.calls = 0
        object.__setattr__(planner, "catalog", _bomb_catalog_from(planner.catalog))
        with self.assertRaisesRegex(ValueError, "fact_planner_child_type_drift"):
            bind_fact(
                request=request,
                planning=planning,
                store=store,
                planner=planner,
            )
        self.assertEqual(_BombCatalog.calls, 0)

        store, _registry, planner, request, planning = _fixture()
        bound = bind_fact(
            request=request,
            planning=planning,
            store=store,
            planner=planner,
        )
        raw = deepcopy(bound.to_dict())
        _BombCatalog.calls = 0
        object.__setattr__(planner, "catalog", _bomb_catalog_from(planner.catalog))
        with self.assertRaisesRegex(ValueError, "fact_planner_child_type_drift"):
            replay_bound_fact(
                raw,
                request=request,
                store=store,
                planner=planner,
            )
        self.assertEqual(_BombCatalog.calls, 0)

    def test_request_mapping_drift_is_rejected_before_planner_calls(self):
        store, _registry, planner, request, planning = _fixture()
        bomb = _BombRequestMap()
        object.__setattr__(request, "options", MappingProxyType(bomb))
        bomb.calls = 0
        with patch.object(
            DeterministicPlanner,
            "plan",
            side_effect=AssertionError("planner should not run"),
        ):
            with self.assertRaisesRegex(ValueError, "fact_request_payload_drift"):
                bind_fact(
                    request=request,
                    planning=planning,
                    store=store,
                    planner=planner,
                )
        self.assertEqual(bomb.calls, 0)

        store, _registry, planner, request, planning = _fixture()
        bound = bind_fact(
            request=request,
            planning=planning,
            store=store,
            planner=planner,
        )
        raw = deepcopy(bound.to_dict())
        bomb = _BombRequestMap()
        object.__setattr__(request, "options", MappingProxyType(bomb))
        bomb.calls = 0
        with patch.object(
            DeterministicPlanner,
            "plan",
            side_effect=AssertionError("planner should not run"),
        ):
            with self.assertRaisesRegex(ValueError, "fact_request_payload_drift"):
                replay_bound_fact(
                    raw,
                    request=request,
                    store=store,
                    planner=planner,
                )
        self.assertEqual(bomb.calls, 0)

    def test_issued_runtime_string_subclass_is_rejected_before_methods(self):
        _ArmedRuntimeString.armed = False
        _ArmedRuntimeString.calls = 0
        request = RuntimeRequest(question=_ArmedRuntimeString("사업 예산은?"))
        store, _registry, planner, request, planning = _fixture(request=request)
        _ArmedRuntimeString.armed = True
        try:
            with patch.object(
                DeterministicPlanner,
                "plan",
                side_effect=AssertionError("planner should not run"),
            ):
                with self.assertRaisesRegex(ValueError, "fact_request_payload_drift"):
                    bind_fact(
                        request=request,
                        planning=planning,
                        store=store,
                        planner=planner,
                    )
            self.assertEqual(_ArmedRuntimeString.calls, 0)
        finally:
            _ArmedRuntimeString.armed = False

    def test_planning_predicate_mapping_drift_is_rejected_without_traversal(self):
        request = RuntimeRequest(
            question="기관A 사업 예산은?",
            metadata_filters=(
                {"field": "agency", "operator": "eq", "value": "기관A"},
            ),
        )
        store, _registry, planner, request, planning = _fixture(request=request)
        predicate = planning.plan.metadata_predicates[0]
        self.assertIsInstance(predicate, MetadataPredicate)
        bomb = _BombRequestMap()
        object.__setattr__(predicate, "value", MappingProxyType(bomb))
        bomb.calls = 0
        with patch.object(
            DeterministicPlanner,
            "plan",
            side_effect=AssertionError("planner should not run"),
        ):
            with self.assertRaisesRegex(ValueError, "fact_planning_child_type_drift"):
                bind_fact(
                    request=request,
                    planning=planning,
                    store=store,
                    planner=planner,
                )
        self.assertEqual(bomb.calls, 0)

    def test_trace_and_binding_string_subclasses_fail_before_magic_methods(self):
        store, _registry, planner, request, planning = _fixture()
        bound = bind_fact(
            request=request,
            planning=planning,
            store=store,
            planner=planner,
        )
        _BombString.calls = 0
        object.__setattr__(bound.trace, "catalog_source_kind", _BombString("synthetic_fixture"))
        with self.assertRaisesRegex(ValueError, "bound_fact_trace_child_type_drift"):
            validate_bound_fact(bound=bound, store=store)
        self.assertEqual(_BombString.calls, 0)

        store, _registry, planner, request, planning = _fixture()
        bound = bind_fact(
            request=request,
            planning=planning,
            store=store,
            planner=planner,
        )
        _BombString.calls = 0
        object.__setattr__(bound, "binding_sha256", _BombString(bound.binding_sha256))
        with self.assertRaisesRegex(ValueError, "invalid_binding_sha256"):
            validate_bound_fact(bound=bound, store=store)
        self.assertEqual(_BombString.calls, 0)

    def test_bound_and_state_replay_are_strict_and_provider_free(self):
        store, registry, planner, request, planning = _fixture()
        bound = bind_fact(
            request=request,
            planning=planning,
            store=store,
            planner=planner,
        )
        state = build_fact_harness_state(bound=bound, store=store)
        replayed_bound = replay_bound_fact(
            deepcopy(bound.to_dict()),
            request=request,
            store=store,
            planner=planner,
        )
        replayed_state = replay_harness_state(
            deepcopy(state.to_dict()),
            bound=replayed_bound,
            source_receipt=None,
            store=store,
        )
        self.assertEqual(replayed_bound.to_dict(), bound.to_dict())
        self.assertEqual(replayed_state.to_dict(), state.to_dict())

        malformed = deepcopy(bound.to_dict())
        malformed["trace"]["resolved_doc_ids"] = tuple(
            malformed["trace"]["resolved_doc_ids"]
        )
        with self.assertRaisesRegex(TypeError, "bound_fact_replay_json_required"):
            replay_bound_fact(
                malformed,
                request=request,
                store=store,
                planner=planner,
            )

        wrong_state = deepcopy(state.to_dict())
        wrong_state["progress"]["slot_coverage_ratio"] = 0
        with self.assertRaisesRegex(ValueError, "harness_state_replay_payload_mismatch"):
            replay_harness_state(
                wrong_state,
                bound=bound,
                source_receipt=None,
                store=store,
            )

        signature = inspect.signature(bind_fact)
        forbidden = {"gold", "qrels", "expected", "reference_answer", "required_doc_ids"}
        self.assertTrue(forbidden.isdisjoint(signature.parameters))
        self.assertEqual(registry.config_sha256, bound.trace.config_sha256)


if __name__ == "__main__":
    unittest.main()
