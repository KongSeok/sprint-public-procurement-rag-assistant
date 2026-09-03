import dataclasses
import json
import unittest

from midprojectrag.evidence import Evidence, Locator, ProvenanceParent


class EvidenceModelTests(unittest.TestCase):
    def setUp(self):
        self.parent = ProvenanceParent("doc_a", "pdf_page", "abc abc", ["block_a"], Locator(page=1))

    def evidence(self, **overrides):
        values = dict(doc_id="doc_a", kind="text", text="abc", parent_id=self.parent.parent_id,
                      source_block_ids=["block_a"], locator=Locator(page=1, char_range=(0, 3)),
                      source_chunk_ids=["original_chunk"])
        return Evidence(**(values | overrides))

    def test_roundtrip_identity_and_immutability(self):
        evidence = self.evidence()
        for obj in (self.parent.locator, self.parent, evidence):
            self.assertEqual(obj, type(obj).from_dict(json.loads(json.dumps(obj.to_dict()))))
            self.assertFalse(hasattr(obj, "__dict__"))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            evidence.text = "changed"
        snapshot = evidence.to_dict()
        snapshot["source_block_ids"].append("foreign")
        self.assertEqual(evidence.source_block_ids, ("block_a",))
        self.assertEqual(evidence.source_chunk_ids, ("original_chunk",))

    def test_repeated_text_occurrence_has_distinct_id_same_content(self):
        first, second = self.evidence(), self.evidence(locator=Locator(page=1, char_range=(4, 7)))
        self.assertNotEqual(first.evidence_id, second.evidence_id)
        self.assertEqual(first.content_sha256, second.content_sha256)

    def test_forged_identity_or_unknown_field_rejected(self):
        for obj, key in ((self.parent, "parent_id"), (self.evidence(), "evidence_id")):
            for mutation in ({key: "forged"}, {"content_sha256": "0" * 64}, {"gold": "bad"}, {"text": "changed"}):
                with self.subTest(mutation=tuple(mutation)), self.assertRaises(ValueError):
                    type(obj).from_dict(obj.to_dict() | mutation)

    def test_invalid_locators(self):
        for kw in (dict(page=True), dict(page=0), dict(bbox=(0, 0, float("nan"), 1)),
                   dict(bbox=(2, 0, 1, 2)), dict(row_range=(2, 1)), dict(char_range=(0, 0)),
                   dict(char_range=(False, 2)), dict(char_range=(-1, 2)), dict(bbox=(2**53+1, 0, 2**53+2, 1))):
            with self.subTest(kw=kw), self.assertRaises((TypeError, ValueError)):
                Locator(**kw)

    def test_parent_kinds_and_flow_do_not_fabricate_page(self):
        flow = ProvenanceParent("d", "hwp_section_flow", "", ("b",), Locator(flow_id="section_1"))
        self.assertIsNone(flow.locator.page)
        for kind, locator in (("hwp_section_flow", Locator(page=1, flow_id="flow")),
                              ("pdf_page", Locator()), ("invalid", Locator(page=1))):
            with self.assertRaises(ValueError):
                ProvenanceParent("d", kind, "x", ("b",), locator)

    def test_empty_figure_requires_crop(self):
        self.assertEqual(self.evidence(kind="figure_object", text="", crop_ref="crops/a.png").text, "")
        for kwargs in (dict(text=""), dict(kind="figure_object", text=""), dict(source_block_ids=[]),
                       dict(source_block_ids=["b", "b"]), dict(parent_id="page_1")):
            with self.assertRaises((TypeError, ValueError)):
                self.evidence(**kwargs)

    def test_crop_traversal_and_remote_refs_rejected(self):
        for path in ("/tmp/a.png", "../a.png", "a/../b", "https://host/a", "a\\b", "a//b", "a?b"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.evidence(crop_ref=path)


if __name__ == "__main__":
    unittest.main()
