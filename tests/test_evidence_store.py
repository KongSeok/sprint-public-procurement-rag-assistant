from dataclasses import FrozenInstanceError, replace
import unittest

from midprojectrag.evidence import Evidence, Locator, ProvenanceParent
from midprojectrag.evidence.store import EvidenceStore


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


if __name__ == "__main__":
    unittest.main()
