from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
import unittest

from midprojectrag.evidence import Evidence, EvidenceStore, build_from_chunks
from midprojectrag.indexing.chunking import build_page_chunks, PageChunkConfig
from midprojectrag.ingest.common import canonical_json, sha256_text


DOC = "doc_" + "1" * 24
PAGE_BLOCK = "block_" + "2" * 24
OBJECT_BLOCK = "block_" + "3" * 24


def page(**overrides):
    args = dict(doc_id=DOC, page=1, kind="page", text="원문 첫 문단\n\n둘째 문단",
                source_block_ids=(PAGE_BLOCK,))
    return Evidence.create(**(args | overrides))


def child(parent=None, **overrides):
    parent = parent or page()
    args = dict(doc_id=parent.doc_id, page=parent.page, kind="text", text="첫 문단",
                source_block_ids=parent.source_block_ids, parent_id=parent.evidence_id)
    return Evidence.create(**(args | overrides))


def page_chunks(text="원문 첫 문단\n\n둘째 문단", *, max_chars=24000, page_number=1):
    block = dict(block_id=PAGE_BLOCK, doc_id=DOC, text=text, block_type="page_text",
                 page_start=page_number, page_end=page_number, section_path=["사업 개요"],
                 content_sha256=sha256_text(text), retrieval_role="primary")
    return build_page_chunks([block], PageChunkConfig(max_chars=max_chars))


def table_chunk(*, page_number=1, row_start=0, row_end=1):
    text = "|구분|값|\n|---|---|\n|금액|100|"
    content_hash = sha256_text(text)
    config_hash = "a" * 64
    structure_hash = "b" * 64
    identity = dict(block_id=OBJECT_BLOCK, config_sha256=config_hash, content_sha256=content_hash,
                    doc_id=DOC, part_count=1, part_index=0, row_end=row_end, row_start=row_start,
                    source_locator="section:1/table:1", table_structure_sha256=structure_hash)
    return dict(schema_version="1.1", chunk_id="chunk_" + sha256_text(canonical_json(identity))[:24],
                doc_id=DOC, text=text, display_markdown=text, source_block_ids=[OBJECT_BLOCK],
                section_path=[], page_start=page_number, page_end=page_number,
                source_locator=identity["source_locator"], row_start=row_start, row_end=row_end,
                part_index=0, part_count=1, retrieval_role="structured_auxiliary",
                chunker_id="table-md-rowgroup-v1", config_sha256=config_hash,
                content_sha256=content_hash, display_sha256=content_hash,
                source_structure_sha256=structure_hash, table_structure_sha256=structure_hash,
                header_source="explicit")


def visual_chunk(*, caption=False, support=None):
    kind = "caption" if caption else "ocr"
    text = "도식 안의 검증된 문구"
    occurrence = "vocc2_" + "4" * 24
    ids = [("cap_" if caption else "ocr_") + "5" * 24]
    identity = dict(doc_id=DOC, occurrence_id=occurrence, evidence_ids=ids,
                    content_sha256=sha256_text(text), evidence_type=kind,
                    chunker_id="image-caption-v1" if caption else "image-ocr-v1")
    if support is not None:
        identity["answer_support"] = support
    box = dict(x=10.0, y=20.0, w=30.0, h=40.0)
    record = dict(schema_version="1.0", chunk_id="vchunk_" + sha256_text(canonical_json(identity))[:24],
                  **{k: v for k, v in identity.items() if k != "answer_support"}, text=text, page=1, bbox=box,
                  crop_sha256="6" * 64, retrieval_role="visual_auxiliary", retrieval_weight=0.35 if caption else 1.0,
                  citation=dict(doc_id=DOC, page=1, bbox=box, occurrence_id=occurrence,
                                crop_sha256="6" * 64, evidence_ids=ids))
    if support is not None:
        record["answer_support"] = support
    return record


def mapped(chunk, **overrides):
    return dict(chunk=chunk, parent_source_block_id=PAGE_BLOCK, **overrides)


class EvidenceTests(unittest.TestCase):
    def test_identity_stable_and_frozen(self):
        record = page()
        self.assertEqual(record, page())
        self.assertRegex(record.evidence_id, r"^ev_[0-9a-f]{24}$")
        self.assertEqual(record.content_sha256, sha256_text(record.text))
        with self.assertRaises(FrozenInstanceError):
            record.text = "changed"

    def test_provenance_is_in_identity(self):
        base = page()
        for changed in (page(doc_id="other"), page(page=2), page(source_block_ids=("another",)),
                        page(text=base.text + " "), page(section_path=("다른 절",))):
            self.assertNotEqual(base.evidence_id, changed.evidence_id)
        self.assertNotEqual(child(base).evidence_id, child(page(text="다른 부모")).evidence_id)

    def test_bbox_normalization_has_stable_numeric_identity(self):
        integer = child(kind="table", object_id="t1", bbox=(0, 0, 2, 3))
        floating = child(kind="table", object_id="t1", bbox=(0.0, 0.0, 2.0, 3.0))
        self.assertEqual(integer, floating)

    def test_serialization_roundtrip_and_detached_lists(self):
        record = child(kind="table", object_id="t1", bbox=(1, 2, 3, 4))
        data = json.loads(json.dumps(record.to_dict(), ensure_ascii=False))
        self.assertEqual(Evidence.from_dict(data), record)
        data["source_block_ids"].append("changed")
        self.assertEqual(record.source_block_ids, (PAGE_BLOCK,))

    def test_serialization_rejects_tampering_and_unknown_fields(self):
        for key, value in (("evidence_id", "ev_" + "0" * 24), ("text", "tampered"),
                           ("content_sha256", "f" * 64), ("page", 99)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                Evidence.from_dict(page().to_dict() | {key: value})
        with self.assertRaisesRegex(ValueError, "shape"):
            Evidence.from_dict(page().to_dict() | {"gold": "not allowed"})

    def test_malformed_nested_values_fail_as_value_errors(self):
        fields = {"source_block_ids": [["bad"]], "section_path": [1], "bbox": [0, 0, [], 2],
                  "kind": [], "page": True, "parent_id": {}, "doc_id": {}, "text": []}
        for key, value in fields.items():
            with self.subTest(key=key), self.assertRaises(ValueError):
                Evidence.from_dict(page().to_dict() | {key: value})

    def test_invalid_source_refs_rejected(self):
        for refs in ((), ("",), ("x", "x"), ["x"], ({"bad": "value"},)):
            with self.subTest(refs=refs), self.assertRaises(ValueError):
                page(source_block_ids=refs)

    def test_repeated_section_titles_are_valid(self):
        self.assertEqual(page(section_path=("요건", "요건")).section_path, ("요건", "요건"))

    def test_page_and_object_parent_contract(self):
        for call in (lambda: page(parent_id=page().evidence_id),
                     lambda: child(parent_id=None), lambda: child(kind="table"),
                     lambda: child(kind="figure"), lambda: page(object_id="unneeded")):
            with self.assertRaises(ValueError):
                call()

    def test_bbox_rejects_reverse_zero_bool_and_nonfinite(self):
        for bbox in ((1, 0, 0, 1), (0, 0, 0, 1), (0, 0, float("nan"), 2),
                     (0, 0, float("inf"), 2), (0, 0, 10 ** 1000, 2),
                     (0, 0, True, 2), [0, 0, 1, 2]):
            with self.subTest(bbox=bbox), self.assertRaises(ValueError):
                child(kind="figure", object_id="f1", bbox=bbox)

    def test_pixel_only_object_requires_crop_and_preserves_empty_text(self):
        with self.assertRaises(ValueError):
            child(kind="figure", object_id="f1", text="")
        record = child(kind="figure", object_id="f1", text="", crop_ref="private/crop.png")
        self.assertEqual(record.text, "")
        self.assertEqual(Evidence.from_dict(record.to_dict()), record)

    def test_provenance_extension_roundtrip_and_identity(self):
        record = child(kind="table", object_id="t1", source_chunk_ids=("chunk_a",),
                       support_refs=("source:a",), row_range=(0, 2))
        self.assertEqual(Evidence.from_dict(record.to_dict()), record)
        for change in ({"source_chunk_ids": ["chunk_b"]}, {"support_refs": ["source:b"]},
                       {"row_range": [0, 3]}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "identity_mismatch"):
                Evidence.from_dict(record.to_dict() | change)

    def test_provenance_extension_nested_values_and_immutable_types(self):
        for key, invalid in (("source_chunk_ids", [[]]), ("support_refs", [{}]),
                             ("evidence_type", []), ("row_range", [True, 2])):
            with self.subTest(key=key), self.assertRaises(ValueError):
                Evidence.from_dict(child(kind="table", object_id="t1").to_dict() | {key: invalid})
        for kwargs in ({"source_chunk_ids": ["chunk_a"]}, {"support_refs": ["source:a"]},
                       {"source_chunk_ids": ("a", "a")}, {"support_refs": ("a", "a")}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                child(**kwargs)

    def test_row_range_is_exact_nonnegative_inclusive_table_pair(self):
        for rows in ((-1, 1), (2, 1), (True, 2), (0, 1.5), (0,), [0, 1]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                child(kind="table", object_id="t1", row_range=rows)
        with self.assertRaisesRegex(ValueError, "invalid_evidence_row_range"):
            child(row_range=(0, 1))
        self.assertEqual(child(kind="table", object_id="t1", row_range=(2, 2)).row_range, (2, 2))

    def test_visual_type_is_not_lost_in_identity(self):
        ocr = child(kind="figure", object_id="f1", evidence_type="ocr")
        caption = child(kind="figure", object_id="f1", evidence_type="caption")
        self.assertNotEqual(ocr.evidence_id, caption.evidence_id)
        with self.assertRaisesRegex(ValueError, "type_kind_mismatch"):
            child(evidence_type="ocr")


class EvidenceStoreTests(unittest.TestCase):
    def test_order_independent_hash_and_roundtrip(self):
        root = page()
        leaf = child(root)
        first = EvidenceStore([root, leaf])
        second = EvidenceStore([leaf, root])
        self.assertEqual(first.artifact_sha256, second.artifact_sha256)
        self.assertEqual(EvidenceStore.from_dict(first.to_dict()).all(), first.all())
        with self.assertRaises(AttributeError):
            first._records = ()
        with self.assertRaises(AttributeError):
            del first._records

    def test_duplicate_unknown_and_missing_parent(self):
        root = page()
        with self.assertRaisesRegex(ValueError, "duplicate_evidence_id"):
            EvidenceStore([root, root])
        with self.assertRaisesRegex(ValueError, "parent_missing"):
            EvidenceStore([child(root)])
        store = EvidenceStore([root])
        for value in ("unknown", [], None):
            with self.assertRaisesRegex(ValueError, "unknown_evidence_id"):
                store.get(value)

    def test_cross_document_and_page_links_rejected(self):
        root = page()
        for leaf in (child(root, doc_id="other"), child(root, page=2)):
            with self.assertRaisesRegex(ValueError, "provenance_mismatch"):
                EvidenceStore([root, leaf])

    def test_text_cannot_own_children(self):
        root = page()
        text = child(root)
        grandchild = child(root, parent_id=text.evidence_id, text="nested")
        with self.assertRaisesRegex(ValueError, "parent_kind"):
            EvidenceStore([root, text, grandchild])

    def test_explicit_bridge_is_filtered_and_recursive(self):
        root = page()
        text = child(root)
        table = child(root, kind="table", object_id="t1", text="table")
        figure = child(root, kind="figure", object_id="f1", parent_id=table.evidence_id, text="figure")
        other_page = page(page=2)
        other_figure = child(other_page, kind="figure", object_id="other")
        store = EvidenceStore([other_page, root, table, text, figure, other_figure])
        self.assertEqual(set(store.bridge(root.evidence_id)), {table, figure})
        self.assertEqual(store.bridge(root.evidence_id, "figure"), (figure,))
        self.assertEqual(set(store.children(root.evidence_id)), {table, text})
        with self.assertRaisesRegex(ValueError, "bridge_requires_page"):
            store.bridge(text.evidence_id)
        with self.assertRaisesRegex(ValueError, "invalid_bridge_kind"):
            store.bridge(root.evidence_id, "text")

    def test_store_shape_and_hash_tampering(self):
        data = EvidenceStore([page()]).to_dict()
        for changed in (data | {"artifact_sha256": "wrong"}, data | {"records": {}},
                        data | {"schema_version": "unexpected"}):
            with self.assertRaises(ValueError):
                EvidenceStore.from_dict(changed)


class EvidenceBuilderTests(unittest.TestCase):
    def test_page_children_are_source_exact_and_bounded(self):
        text = " 첫 문단은 띄어쓰기  보존\n\n두번째 문단\n셋째 줄 "
        store = build_from_chunks(page_chunks(text), max_chars=10)
        root = next(e for e in store.all() if e.kind == "page")
        # The legacy page builder strips outer whitespace; compare its actual text.
        original = page_chunks(text)[0]["text"]
        self.assertEqual(root.text, original)
        for record in store.children(root.evidence_id):
            self.assertIn(record.text, original)
            self.assertLessEqual(len(record.text), 10)
            self.assertEqual(record.source_block_ids, (PAGE_BLOCK,))

    def test_split_parts_reordered_deterministically(self):
        chunks = page_chunks("가" * 220 + "\n\n" + "나" * 220, max_chars=256)
        first = build_from_chunks(chunks)
        second = build_from_chunks(list(reversed(chunks)))
        self.assertEqual(first.artifact_sha256, second.artifact_sha256)
        root = next(e for e in first.all() if e.kind == "page")
        self.assertEqual(root.text, "\n\n".join(c["text"] for c in chunks))
        self.assertEqual(root.source_chunk_ids, tuple(c["chunk_id"] for c in chunks))

    def test_identical_source_text_in_distinct_page_parts_remains_distinct(self):
        chunks = page_chunks("가" * 600, max_chars=256)
        store = build_from_chunks(chunks, max_chars=256)
        children = [record for record in store.all() if record.kind == "text" and record.text == "가" * 256]
        self.assertEqual(len(children), 2)
        self.assertNotEqual(children[0].source_chunk_ids, children[1].source_chunk_ids)

    def test_incomplete_split_parts_fail(self):
        chunks = page_chunks("가" * 600, max_chars=256)
        with self.assertRaisesRegex(ValueError, "incomplete_or_inconsistent"):
            build_from_chunks(chunks[:-1])

    def test_legacy_hash_and_duplicate_inputs_fail(self):
        chunks = page_chunks()
        with self.assertRaisesRegex(ValueError, "duplicate_input_chunk_id"):
            build_from_chunks(chunks + chunks)
        with self.assertRaisesRegex(ValueError, "chunk_content_hash_mismatch"):
            build_from_chunks([chunks[0] | {"text": "changed"}])

    def test_invalid_input_types_are_sanitized(self):
        for chunks in ([], None, "bad", {}, [None], [{"retrieval_role": []}]):
            with self.subTest(chunks=chunks), self.assertRaises(ValueError):
                build_from_chunks(chunks)
        for limit in (0, -1, True, 1.5):
            with self.assertRaisesRegex(ValueError, "invalid_evidence_max_chars"):
                build_from_chunks(page_chunks(), max_chars=limit)

    def test_explicit_table_bridge_preserves_source_without_bbox_guess(self):
        chunk = table_chunk()
        store = build_from_chunks([*page_chunks(), mapped(chunk)])
        root = next(e for e in store.all() if e.kind == "page")
        table = store.bridge(root.evidence_id, "table")[0]
        self.assertEqual(table.text, chunk["text"])
        self.assertEqual(table.source_block_ids, (OBJECT_BLOCK,))
        self.assertIsNone(table.bbox)
        self.assertIsNotNone(table.object_id)
        self.assertEqual(table.row_range, (0, 1))
        self.assertEqual(table.source_chunk_ids, (chunk["chunk_id"],))

    def test_identical_table_text_in_different_rows_preserves_both_units(self):
        first = table_chunk(row_start=0, row_end=1)
        second = table_chunk(row_start=2, row_end=3)
        store = build_from_chunks([*page_chunks(), mapped(first), mapped(second)])
        tables = [e for e in store.all() if e.kind == "table"]
        self.assertEqual(len(tables), 2)
        self.assertEqual(tables[0].object_id, tables[1].object_id)
        self.assertNotEqual(tables[0].source_chunk_ids, tables[1].source_chunk_ids)
        self.assertEqual({e.row_range for e in tables}, {(0, 1), (2, 3)})

    def test_page_coincidence_does_not_create_table_link(self):
        with self.assertRaisesRegex(ValueError, "auxiliary_parent_mapping_required"):
            build_from_chunks([*page_chunks(), table_chunk()])
        with self.assertRaisesRegex(ValueError, "mapping_not_found"):
            build_from_chunks([*page_chunks(), mapped(table_chunk()) | {"parent_source_block_id": OBJECT_BLOCK}])

    def test_pageless_and_mismapped_table_fail(self):
        with self.assertRaisesRegex(ValueError, "single_page_required"):
            build_from_chunks([*page_chunks(), mapped(table_chunk(page_number=None))])
        with self.assertRaisesRegex(ValueError, "source_mapping_mismatch"):
            build_from_chunks([*page_chunks(), mapped(table_chunk(), source_block_ids=[PAGE_BLOCK])])

    def test_multi_page_table_is_not_assigned_an_arbitrary_page(self):
        chunk = table_chunk() | {"page_end": 2}
        with self.assertRaisesRegex(ValueError, "auxiliary_single_page_required"):
            build_from_chunks([*page_chunks(), mapped(chunk)])

    def test_visual_requires_canonical_source_and_converts_bbox(self):
        visual = visual_chunk()
        with self.assertRaisesRegex(ValueError, "invalid_auxiliary_source_mapping"):
            build_from_chunks([*page_chunks(), mapped(visual)])
        store = build_from_chunks([*page_chunks(), mapped(visual, source_block_ids=[OBJECT_BLOCK])])
        root = next(e for e in store.all() if e.kind == "page")
        figure = store.bridge(root.evidence_id, "figure")[0]
        self.assertEqual(figure.bbox, (10.0, 20.0, 40.0, 60.0))
        self.assertEqual(figure.object_id, visual["occurrence_id"])
        self.assertEqual(figure.text, visual["text"])
        self.assertEqual(figure.crop_ref, "sha256:" + visual["crop_sha256"])
        self.assertEqual(figure.source_chunk_ids, (visual["chunk_id"],))
        self.assertEqual(figure.evidence_type, "ocr")
        self.assertEqual(set(figure.support_refs), {*visual["evidence_ids"], "crop-sha256:" + visual["crop_sha256"]})

    def test_visual_crop_change_alters_evidence_identity(self):
        first = visual_chunk()
        second = visual_chunk() | {"crop_sha256": "7" * 64}
        second["citation"] = second["citation"] | {"crop_sha256": "7" * 64}
        first_store = build_from_chunks([*page_chunks(), mapped(first, source_block_ids=[OBJECT_BLOCK])])
        second_store = build_from_chunks([*page_chunks(), mapped(second, source_block_ids=[OBJECT_BLOCK])])
        self.assertNotEqual(first_store.artifact_sha256, second_store.artifact_sha256)
        # A reused path must not obscure the different image bytes either.
        first_store = build_from_chunks([*page_chunks(), mapped(first, source_block_ids=[OBJECT_BLOCK], crop_ref="private/same.png")])
        second_store = build_from_chunks([*page_chunks(), mapped(second, source_block_ids=[OBJECT_BLOCK], crop_ref="private/same.png")])
        self.assertNotEqual(first_store.artifact_sha256, second_store.artifact_sha256)

    def test_envelope_extra_fields_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "mapping_shape"):
            build_from_chunks([*page_chunks(), mapped(table_chunk(), unknown="bad")])

    def test_visual_non_finite_bbox_fails_closed(self):
        visual = visual_chunk()
        visual["bbox"]["w"] = 10 ** 1000
        with self.assertRaises(ValueError):
            build_from_chunks([*page_chunks(), mapped(visual, source_block_ids=[OBJECT_BLOCK])])

    def test_descriptive_or_unreviewed_captions_never_become_answer_evidence(self):
        for support in (None, {"status": "descriptive_only", "support_refs": []}):
            with self.subTest(support=support), self.assertRaisesRegex(ValueError, "descriptive_caption"):
                build_from_chunks([*page_chunks(), mapped(visual_chunk(caption=True, support=support), source_block_ids=[OBJECT_BLOCK])])

    def test_supported_caption_contract_is_preserved(self):
        caption = visual_chunk(caption=True, support={"status": "supported", "support_refs": ["source:verified"]})
        store = build_from_chunks([*page_chunks(), mapped(caption, source_block_ids=[OBJECT_BLOCK])])
        figures = [e for e in store.all() if e.kind == "figure"]
        self.assertEqual(len(figures), 1)
        figure = figures[0]
        self.assertEqual(figure.evidence_type, "caption")
        self.assertEqual(set(figure.support_refs), {*caption["evidence_ids"], "source:verified", "crop-sha256:" + caption["crop_sha256"]})
        self.assertEqual(Evidence.from_dict(figure.to_dict()), figure)

    def test_nested_caption_support_is_rejected_not_hashed(self):
        caption = visual_chunk(caption=True, support={"status": "supported", "support_refs": [{"unverified": "claim"}]})
        with self.assertRaisesRegex(ValueError, "invalid_visual_answer_support"):
            build_from_chunks([*page_chunks(), mapped(caption, source_block_ids=[OBJECT_BLOCK])])

    def test_untrusted_visual_nested_lists_fail_cleanly(self):
        visual = visual_chunk()
        visual["evidence_ids"] = [{}]
        with self.assertRaisesRegex(ValueError, "invalid_visual_source_refs"):
            build_from_chunks([*page_chunks(), mapped(visual, source_block_ids=[OBJECT_BLOCK])])


if __name__ == "__main__":
    unittest.main()
