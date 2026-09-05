"""Original document qrels are bound, not reconstructed from retrieved anchors."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from midprojectrag.stage_checkpoints import canonical_sha
from midprojectrag.stage_document_qrels import validate_document_inventory
from midprojectrag.stage_evaluation import SourceSnapshot
from midprojectrag.stage_inputs import write_inputs
from tests import test_stage_inputs as fixtures


def sealed_inputs(fixture):
    inputs = fixture.build()
    inputs.pop("inputs_sha256")
    inputs["input_config_sha256"] = fixtures.H
    inputs["inputs_sha256"] = canonical_sha(inputs)
    with TemporaryDirectory() as temp:
        root = Path(temp)
        (root / "private").mkdir()
        inventory = write_inputs(inputs, output_dir=root / "private/inputs", data_root=root)
        raw = (root / "private/inputs/qrels.jsonl").read_bytes()
    return inventory, inputs["qrels"], sha256(raw).hexdigest()


def reseal(inventory, qrels):
    """Test semantic validation after internally consistent, unsigned hashes."""
    body = {k: v for k, v in inventory.items()
            if k not in {"inventory_sha256", "qrels_file_sha256", "publication_status", "inputs_sha256"}}
    body["qrels"] = qrels
    inventory["inputs_sha256"] = canonical_sha(body)
    inventory["inventory_sha256"] = canonical_sha({k: v for k, v in inventory.items() if k != "inventory_sha256"})


class DocumentInventoryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.StageInputsTests()
        self.fixture.setUp()
        self.inventory, self.qrels, self.file_sha = sealed_inputs(self.fixture)

    def validate(self, inventory=None, qrels=None, **kwargs):
        return validate_document_inventory(self.inventory if inventory is None else inventory,
                                           self.qrels if qrels is None else qrels,
                                           snapshot=kwargs.pop("snapshot", self.fixture.snapshot),
                                           qrels_file_sha256=kwargs.pop("qrels_file_sha256", self.file_sha), **kwargs)

    def test_missing_block_refs_do_not_erase_original_document_targets(self):
        before = deepcopy(self.inventory)
        result = self.validate()
        self.assertEqual(len(result), 131)
        missing = next(c for c in self.inventory["cases"] if c["suite"] == "answer56" and c["qrel_status"] == "missing")
        self.assertEqual(result[missing["case_id"]].status, "ready")
        self.assertEqual(result[missing["case_id"]].required, frozenset({fixtures.D}))
        self.assertEqual(self.inventory, before)
        with self.assertRaises(TypeError): result["new"] = result[missing["case_id"]]

    def test_original_doc_targets_are_not_anchor_owners(self):
        extra = "doc_" + "b" * 24
        self.fixture.snapshot = SourceSnapshot(fixtures.H, fixtures.H,
            {(fixtures.D, fixtures.B): fixtures.H, (extra, "block-b"): fixtures.H},
            {"blocks_" + fixtures.D: fixtures.H, "blocks_" + extra: fixtures.H})
        self.fixture.cases[0].source["gold"]["required_doc_ids"].append(extra)
        self.fixture.refresh(self.fixture.cases[0])
        self.inventory, self.qrels, self.file_sha = sealed_inputs(self.fixture)
        result = self.validate()[self.qrels[0]["case_id"]]
        self.assertEqual(result.required, frozenset({fixtures.D, extra}))
        self.assertEqual(len(self.qrels[0]["required_anchors"]), 1)

    def test_abstention_and_specialized_cases_not_positive_recall(self):
        result = self.validate()
        abstain = next(c for c in self.inventory["cases"]
                       if c["suite"] == "answer56" and c["qrel_status"] == "not_applicable")
        self.assertTrue(abstain["required_doc_ids"])
        self.assertEqual((result[abstain["case_id"]].status, result[abstain["case_id"]].required),
                         ("not_applicable", frozenset()))
        self.assertEqual(sum(r.status == "not_applicable" for r in result.values()), 34)
        self.assertTrue(all(c["semantic_approval"] == "not_assessed_by_adapter" for c in self.inventory["cases"]))

    def test_missing_original_doc_list_is_not_inferred(self):
        self.inventory["cases"][0]["required_doc_ids"] = []
        reseal(self.inventory, self.qrels)
        row = self.validate()[self.qrels[0]["case_id"]]
        self.assertEqual((row.status, row.required, row.reason), ("missing", frozenset(), "original_document_qrels_missing"))

    def test_outer_inner_file_and_snapshot_hash_binding(self):
        mutated = deepcopy(self.inventory)
        mutated["cases"][0]["source_row_sha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "receipt_mismatch"): self.validate(mutated)
        mutated["inventory_sha256"] = canonical_sha({k: v for k, v in mutated.items() if k != "inventory_sha256"})
        with self.assertRaisesRegex(ValueError, "inputs_mismatch"): self.validate(mutated)
        with self.assertRaisesRegex(ValueError, "qrels_file_mismatch"): self.validate(qrels_file_sha256="b" * 64)
        other = SourceSnapshot("b" * 64, fixtures.H, self.fixture.snapshot.locators, self.fixture.snapshot.file_hashes)
        with self.assertRaisesRegex(ValueError, "snapshot_mismatch"): self.validate(snapshot=other)

    def test_closed_policy_fields_types_and_full_counts(self):
        for mutation in ({"extra": "private"}, {"case_count": True}, {"model_calls": False},
                         {"formal_comparison_authorized": 0}, {"publication_status": "draft"},
                         {"source_file_sha256s": {}}, {"suite_counts": {}},
                         {"cases": self.inventory["cases"][:-1]}, {"qrel_counts": {"ready": 131}}):
            inventory = deepcopy(self.inventory) | mutation
            reseal(inventory, self.qrels)
            with self.subTest(mutation=list(mutation)), self.assertRaises(ValueError): self.validate(inventory)
        with self.assertRaises(ValueError): self.validate(qrels=self.qrels[:-1])

    def test_duplicate_case_id_and_qrel_identity_mismatch(self):
        for field, value in (("case_id", self.inventory["cases"][1]["case_id"]),
                             ("case_id", "unknown"), ("suite", "set13"),
                             ("required_anchor_count", True), ("qrel_status", "missing")):
            inventory = deepcopy(self.inventory)
            inventory["cases"][0][field] = value
            reseal(inventory, self.qrels)
            with self.subTest(field=field), self.assertRaises(ValueError): self.validate(inventory)
        qrels = deepcopy(self.qrels)
        qrels[1] = qrels[0]
        inventory = deepcopy(self.inventory)
        reseal(inventory, qrels)
        with self.assertRaises(ValueError): self.validate(inventory, qrels)

    def test_unknown_duplicate_or_malformed_docs_rejected_without_filtering(self):
        for targets in ([fixtures.D, "unknown"], [fixtures.D, fixtures.D], [None], [True], "not-a-list"):
            inventory = deepcopy(self.inventory)
            inventory["cases"][0]["required_doc_ids"] = targets
            reseal(inventory, self.qrels)
            with self.subTest(targets=targets), self.assertRaises(ValueError): self.validate(inventory)

    def test_review_receipt_preserved_but_not_promoted(self):
        self.inventory["cases"][0]["source_review_status"] = "approved"
        reseal(self.inventory, self.qrels)
        self.assertEqual(self.validate()[self.qrels[0]["case_id"]].status, "ready")
        for mutation in ({"semantic_approval": "approved"}, {"source_manifest_status": "missing"},
                         {"source_review_sha256": "bad"}, {"source_review_status": "fake"}):
            inventory = deepcopy(self.inventory)
            inventory["cases"][0].update(mutation)
            reseal(inventory, self.qrels)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): self.validate(inventory)

    def test_not_applicable_and_missing_reasons_are_not_interchangeable(self):
        for index, reason in ((0, "positive_recall_not_applicable_to_abstention"),
                              (30, "specialized_metric_required"), (40, None), (129, "source_block_qrels_missing")):
            inventory = deepcopy(self.inventory)
            inventory["cases"][index]["reason"] = reason
            reseal(inventory, self.qrels)
            with self.subTest(index=index), self.assertRaises(ValueError): self.validate(inventory)


if __name__ == "__main__":
    unittest.main()
