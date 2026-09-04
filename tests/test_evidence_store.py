from dataclasses import FrozenInstanceError, replace
from collections.abc import Mapping
from types import MappingProxyType
import unittest
from unittest.mock import patch

import midprojectrag.evidence.store as store_module

from midprojectrag.evidence import (
    Evidence,
    EvidenceStore,
    Locator,
    ProvenanceParent,
    validate_evidence_store_snapshot,
)


class _FlipChildren:
    def __init__(self, child):
        self.child = child
        self.calls = 0

    def __iter__(self):
        self.calls += 1
        return iter((self.child,) if self.calls == 1 else ())


class _BombEvidence(Evidence):
    calls = 0

    def to_dict(self):
        type(self).calls += 1
        raise AssertionError("untrusted evidence method executed")


def _bomb_evidence_from(source):
    result = object.__new__(_BombEvidence)
    for name in Evidence.__slots__:
        object.__setattr__(result, name, getattr(source, name))
    return result


class _ArmedKey(str):
    armed = False
    calls = 0

    def __hash__(self):
        if type(self).armed:
            type(self).calls += 1
            raise AssertionError("untrusted key hash executed")
        return str.__hash__(self)


class _BombMap(Mapping):
    def __init__(self):
        self.calls = 0

    def __getitem__(self, key):
        self.calls += 1
        raise AssertionError("untrusted mapping lookup executed")

    def __iter__(self):
        self.calls += 1
        raise AssertionError("untrusted mapping iteration executed")

    def __len__(self):
        self.calls += 1
        raise AssertionError("untrusted mapping length executed")


class _BombHash(str):
    calls = 0

    def __ne__(self, other):
        type(self).calls += 1
        raise AssertionError("untrusted hash comparison executed")


class EvidenceStoreTests(unittest.TestCase):
    def setUp(self):
        self.p = ProvenanceParent("d", "pdf_page", "abc abc", ("b",), Locator(page=1))
        self.e = Evidence("d", "text", "abc", self.p.parent_id, ("b",), Locator(page=1, char_range=(0, 3)))

    def test_immutable_roundtrip_and_order_independent_hash(self):
        second = replace(self.e, locator=Locator(page=1, char_range=(4, 7)))
        mutable = [self.e, second]
        store = EvidenceStore([self.p], mutable)
        mutable.clear()
        self.assertEqual(len(store.candidates()), 2)
        self.assertEqual(store.bundle_sha256, EvidenceStore([self.p], [second, self.e]).bundle_sha256)
        self.assertEqual(store.bundle_sha256, EvidenceStore.from_dict(store.to_dict()).bundle_sha256)
        self.assertEqual(store.get(self.e.evidence_id), self.e)
        self.assertEqual(store.parent(self.p.parent_id), self.p)
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            store.bundle_sha256 = "fake"

    def test_parent_source_doc_and_locator_must_bind(self):
        for kwargs in (dict(doc_id="foreign"), dict(parent_id="pr_" + "0" * 64),
                       dict(source_block_ids=("foreign",)), dict(locator=Locator(page=2)),
                       dict(locator=Locator(page=1, char_range=(1, 4))), dict(text="injected")):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                EvidenceStore([self.p], [replace(self.e, **kwargs)])

    def test_duplicate_and_unknown_support_rejected(self):
        with self.assertRaises(ValueError):
            EvidenceStore([self.p], [self.e, self.e])
        with self.assertRaises(ValueError):
            EvidenceStore([self.p, self.p], [self.e])
        with self.assertRaises(ValueError):
            EvidenceStore([self.p], [replace(self.e, support_refs=("missing",))])

    def test_default_candidates_scope_and_explicit_legacy(self):
        page = replace(self.e, kind="page")
        store = EvidenceStore([self.p], [self.e, page])
        self.assertEqual(store.candidates(), (self.e,))
        self.assertEqual(store.candidates(allowed_doc_ids=frozenset()), ())
        self.assertEqual(store.candidates(allowed_doc_ids=frozenset({"other"})), ())
        self.assertEqual(store.candidates(kinds=("page",)), (page,))
        with self.assertRaises(KeyError):
            store.get("unknown")

    def test_bridge_returns_existing_same_parent_objects_only(self):
        fig = replace(self.e, kind="figure_object", text="", crop_ref="crop/a.png", support_refs=(self.e.evidence_id,))
        store = EvidenceStore([self.p], [self.e, fig])
        self.assertEqual(store.bridge(self.e.evidence_id, kinds=("figure_object",)), (fig,))
        self.assertEqual(store.for_document("d", kinds=("figure_object",)), (fig,))

    def test_locator_bounds_and_flow_binding(self):
        p = replace(self.p, locator=Locator(page=1, section_path=("A",), bbox=(0, 0, 10, 10), row_range=(0, 5)))
        good = replace(self.e, parent_id=p.parent_id, locator=Locator(page=1, section_path=("A", "B"), bbox=(1, 1, 5, 5), row_range=(1, 2)))
        EvidenceStore([p], [good])
        for loc in (replace(good.locator, section_path=("B",)), replace(good.locator, bbox=(0, 0, 20, 20)),
                    replace(good.locator, row_range=(0, 6))):
            with self.assertRaises(ValueError):
                EvidenceStore([p], [replace(good, locator=loc)])

    def test_live_snapshot_rejects_lookup_and_children_index_drift(self):
        store = EvidenceStore([self.p], [self.e])
        validate_evidence_store_snapshot(store, store.bundle_sha256)

        object.__setattr__(
            store,
            "_evidence",
            MappingProxyType({"wrong-key": store.evidence[0]}),
        )
        with self.assertRaisesRegex(ValueError, "evidence_store_payload_drift"):
            validate_evidence_store_snapshot(store, store.bundle_sha256)

        for field in ("_parents", "_evidence", "_children"):
            with self.subTest(field=field):
                store = EvidenceStore([self.p], [self.e])
                bomb = _BombMap()
                forged = MappingProxyType(bomb)
                bomb.calls = 0
                object.__setattr__(store, field, forged)
                with self.assertRaisesRegex(
                    ValueError, "evidence_store_payload_drift"
                ):
                    validate_evidence_store_snapshot(store, store.bundle_sha256)
                self.assertEqual(bomb.calls, 0)

        store = EvidenceStore([self.p], [self.e])
        _BombHash.calls = 0
        object.__setattr__(store, "bundle_sha256", _BombHash(store.bundle_sha256))
        with self.assertRaisesRegex(ValueError, "evidence_store_payload_drift"):
            validate_evidence_store_snapshot(store, str(store.bundle_sha256))
        self.assertEqual(_BombHash.calls, 0)

        store = EvidenceStore([self.p], [self.e])
        _ArmedKey.armed = False
        _ArmedKey.calls = 0
        armed_key = _ArmedKey(self.p.parent_id)
        forged_children = MappingProxyType(
            {armed_key: (store.evidence[0],)}
        )
        _ArmedKey.armed = True
        try:
            object.__setattr__(store, "_children", forged_children)
            with self.assertRaisesRegex(
                ValueError, "evidence_store_payload_drift"
            ):
                validate_evidence_store_snapshot(store, store.bundle_sha256)
            self.assertEqual(_ArmedKey.calls, 0)
        finally:
            _ArmedKey.armed = False

        store = EvidenceStore([self.p], [self.e])
        flip = _FlipChildren(store.evidence[0])
        object.__setattr__(
            store,
            "_children",
            MappingProxyType({self.p.parent_id: flip}),
        )
        with self.assertRaisesRegex(ValueError, "evidence_store_payload_drift"):
            validate_evidence_store_snapshot(store, store.bundle_sha256)
        self.assertEqual(flip.calls, 0)

        store = EvidenceStore([self.p], [self.e])
        _BombEvidence.calls = 0
        bomb = _bomb_evidence_from(store.evidence[0])
        object.__setattr__(
            store,
            "_evidence",
            MappingProxyType({bomb.evidence_id: bomb}),
        )
        with self.assertRaisesRegex(ValueError, "evidence_store_payload_drift"):
            validate_evidence_store_snapshot(store, store.bundle_sha256)
        self.assertEqual(_BombEvidence.calls, 0)

        store = EvidenceStore([self.p], [self.e])
        equal_clone = Evidence.from_dict(store.evidence[0].to_dict())
        self.assertEqual(equal_clone, store.evidence[0])
        self.assertIsNot(equal_clone, store.evidence[0])
        object.__setattr__(
            store,
            "_children",
            MappingProxyType({self.p.parent_id: (equal_clone,)}),
        )
        with self.assertRaisesRegex(ValueError, "evidence_store_payload_drift"):
            validate_evidence_store_snapshot(store, store.bundle_sha256)

        store = EvidenceStore([self.p], [self.e])
        object.__setattr__(
            store,
            "_children",
            MappingProxyType({self.p.parent_id: ()}),
        )
        with self.assertRaisesRegex(ValueError, "evidence_store_payload_drift"):
            validate_evidence_store_snapshot(store, store.bundle_sha256)

    def test_snapshot_gate_rejects_store_method_drift_before_call(self):
        store = EvidenceStore([self.p], [self.e])
        for name in ("to_dict", "from_dict", "parent", "children", "get"):
            calls = []

            def armed(*_args, **_kwargs):
                calls.append(name)
                raise AssertionError("drifted store method executed")

            with self.subTest(name=name), patch.object(
                EvidenceStore, name, armed
            ):
                with self.assertRaisesRegex(
                    ValueError, "evidence_store_validation_dependency_drift"
                ):
                    validate_evidence_store_snapshot(
                        store, store.bundle_sha256
                    )
            self.assertEqual(calls, [])

    def test_snapshot_gate_rejects_helper_drift_before_call(self):
        store = EvidenceStore([self.p], [self.e])
        for name in (
            "_exact_strings",
            "_validate_locator_shape",
            "_validate_parent_shape",
            "_validate_evidence_shape",
            "_bound",
            "_drop_store_authority",
        ):
            calls = []

            def armed(*_args, **_kwargs):
                calls.append(name)
                raise AssertionError("drifted validation helper executed")

            with self.subTest(name=name), patch.object(
                store_module, name, armed
            ):
                with self.assertRaisesRegex(
                    ValueError, "evidence_store_validation_dependency_drift"
                ):
                    validate_evidence_store_snapshot(
                        store, store.bundle_sha256
                    )
            self.assertEqual(calls, [])

    def test_snapshot_gate_rejects_registry_replacement_without_lookup(self):
        store = EvidenceStore([self.p], [self.e])
        bomb = _BombMap()
        with patch.object(store_module, "_STORE_AUTHORITIES", bomb):
            with self.assertRaisesRegex(
                ValueError, "evidence_store_validation_dependency_drift"
            ):
                validate_evidence_store_snapshot(store, store.bundle_sha256)
        self.assertEqual(bomb.calls, 0)

    def test_snapshot_gate_rejects_forged_checker_defaults(self):
        store = EvidenceStore([self.p], [self.e])
        checker = store_module._validate_store_validation_dependencies
        issued_defaults = checker.__defaults__
        copied_namespace = dict(issued_defaults[0])
        calls = []

        def armed_to_dict(_store):
            calls.append("to_dict")
            raise AssertionError("store traversal executed")

        forged_defaults = (copied_namespace, *issued_defaults[1:])
        with patch.object(checker, "__defaults__", forged_defaults), patch.object(
            EvidenceStore, "to_dict", armed_to_dict
        ):
            with self.assertRaisesRegex(
                ValueError, "evidence_store_validation_dependency_drift"
            ):
                validate_evidence_store_snapshot(store, store.bundle_sha256)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
