import gc
import unittest
import weakref

from midprojectrag.evidence import Evidence, EvidenceStore, Locator, ProvenanceParent
import midprojectrag.orchestration.followup_binding as followup_binding_module
from midprojectrag.orchestration import (
    BoundFollowup,
    CatalogEntity,
    DeterministicPlanner,
    PlanningCatalog,
    PlanningResult,
    PlanningTrace,
    bind_followup,
    default_rule_registry,
    retrieve_followup_primary,
)
from midprojectrag.runtime_integrity import RuntimeRequest


class _NeverRetriever:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def search(self, query, *, dense_k, lexical_k, scope):
        self.calls.append(
            {
                "query": query,
                "dense_k": dense_k,
                "lexical_k": lexical_k,
                "scope": scope,
            }
        )
        raise AssertionError("invalid follow-up authority reached the provider")


class _ToDictBomb:
    def __init__(self) -> None:
        self.calls = 0

    def to_dict(self):
        self.calls += 1
        raise AssertionError("untrusted nested to_dict executed before identity rejection")


def _fixture():
    parent = ProvenanceParent(
        "doc-a",
        "pdf_page",
        "alpha evidence",
        ("block-doc-a",),
        Locator(page=1),
    )
    evidence = Evidence(
        "doc-a",
        "text",
        "alpha evidence",
        parent.parent_id,
        ("block-doc-a",),
        Locator(page=1, char_range=(0, len("alpha evidence"))),
    )
    store = EvidenceStore((parent,), (evidence,))
    registry = default_rule_registry()
    catalog = PlanningCatalog.synthetic(
        "followup-authority-fixture-v1",
        (
            CatalogEntity(
                "예약발매시스템",
                "예약발매시스템",
                "business",
                ("doc-a",),
                "business_alias",
            ),
        ),
    )
    planner = DeterministicPlanner.for_test(registry, catalog)
    request = RuntimeRequest(
        question="그 사업의 기간은?",
        history=(
            {
                "turn_id": "assistant-1",
                "role": "assistant",
                "content": "근거가 있는 이전 답변",
                "cited_doc_ids": ["doc-a"],
                "cited_evidence_ids": [evidence.evidence_id],
            },
        ),
        document_scope={"mode": "all", "doc_ids": []},
        options={"allow_global_fallback": True},
        prior_citation_state={
            "cited_doc_ids": ["doc-a"],
            "cited_evidence_ids": [evidence.evidence_id],
            "resolved_entities": [],
            "list_doc_ids": [],
            "comparison_doc_ids": [],
        },
    )
    bound = bind_followup(request, planner.plan(request), store, registry)
    return bound, store, registry


def _assert_rejected_before_provider(testcase, bound, store, registry, code):
    retriever = _NeverRetriever()
    with testcase.assertRaisesRegex(ValueError, code):
        retrieve_followup_primary(
            bound=bound,
            store=store,
            registry=registry,
            retriever=retriever,
        )
    testcase.assertEqual(retriever.calls, [])


class BoundFollowupAuthorityTests(unittest.TestCase):
    def test_raw_uninitialized_bound_has_no_runtime_authority(self):
        _issued, store, registry = _fixture()
        raw = object.__new__(BoundFollowup)

        _assert_rejected_before_provider(
            self,
            raw,
            store,
            registry,
            "bound_followup_runtime_authority_required",
        )

    def test_equal_looking_raw_clone_does_not_inherit_authority(self):
        issued, store, registry = _fixture()
        clone = object.__new__(BoundFollowup)
        object.__setattr__(clone, "planning", issued.planning)
        object.__setattr__(clone, "citations", issued.citations)
        object.__setattr__(clone, "trace", issued.trace)

        self.assertEqual(clone.to_dict(), issued.to_dict())
        self.assertEqual(clone.binding_sha256, issued.binding_sha256)
        _assert_rejected_before_provider(
            self,
            clone,
            store,
            registry,
            "bound_followup_runtime_authority_required",
        )

    def test_factory_issued_bound_rejects_nested_planning_trace_drift(self):
        issued, store, registry = _fixture()
        original_binding_sha256 = issued.binding_sha256
        drifted_trace = PlanningTrace(
            **{
                **issued.planning.trace.to_dict(),
                # These valid-looking attestation fields were not covered by the
                # legacy semantic checks or effective-plan hash.
                "catalog_source_sha256": "f" * 64,
            }
        )
        object.__setattr__(
            issued,
            "planning",
            PlanningResult(issued.planning.plan, drifted_trace),
        )
        # The public property recomputes a valid hash for the tampered tree;
        # the private issuance snapshot must still reject it.
        self.assertNotEqual(issued.binding_sha256, original_binding_sha256)

        _assert_rejected_before_provider(
            self,
            issued,
            store,
            registry,
            "bound_followup_nested_identity_drift",
        )

    def test_nested_identity_is_rejected_before_untrusted_to_dict(self):
        issued, store, registry = _fixture()
        bomb = _ToDictBomb()
        object.__setattr__(issued, "planning", bomb)

        _assert_rejected_before_provider(
            self,
            issued,
            store,
            registry,
            "bound_followup_nested_identity_drift",
        )
        self.assertEqual(bomb.calls, 0)

    def test_factory_authority_registry_uses_weakref_cleanup(self):
        issued, _store, _registry = _fixture()
        identity = id(issued)
        issued_ref = weakref.ref(issued)
        self.assertIn(
            identity, followup_binding_module._BOUND_FOLLOWUP_AUTHORITIES
        )

        del issued
        gc.collect()

        self.assertIsNone(issued_ref())
        self.assertNotIn(
            identity, followup_binding_module._BOUND_FOLLOWUP_AUTHORITIES
        )


if __name__ == "__main__":
    unittest.main()
