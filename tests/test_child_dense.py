import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
import numpy as np

from midprojectrag.evidence.builder import build_store
from midprojectrag.retrieval.dense import KURE_IDENTITY, DenseChildLane, build_dense, load_dense
from tests.test_evidence_builder import chunk


class FakeKure:
    def __init__(self):
        self.__dict__.update(KURE_IDENTITY)
        self.calls = []

    def embed(self, texts):
        self.calls.append(tuple(texts))
        matrix = np.zeros((len(texts), 1024), dtype=np.float32)
        for i, text in enumerate(texts):
            matrix[i, 0 if "alpha" in text else 1] = 1
        return SimpleNamespace(vectors=matrix)


class ChildDenseTests(unittest.TestCase):
    def setUp(self):
        self.store = build_store([chunk("alpha"), chunk("beta", block="block_" + "c" * 24, doc="doc_" + "d" * 24)])

    def test_independent_actual_child_text_build_load_search(self):
        provider = FakeKure()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "private" / "dense"
            receipt = build_dense(self.store, provider, output_dir=target, data_root=root, batch_size=1)
            self.assertEqual(receipt["execution_kind"], "synthetic")
            self.assertEqual(provider.calls, [(e.text,) for e in self.store.candidates()])
            lane = load_dense(self.store, provider, output_dir=target, data_root=root)
            result = lane.search("alpha", 2)
            self.assertEqual(self.store.get(result.candidates[0].evidence_id).text, "alpha")
            self.assertTrue(all(c.granularity == "child" for c in result.candidates))
            before = len(provider.calls)
            self.assertEqual(lane.search("alpha", 2, allowed_doc_ids=frozenset()).candidates, ())
            self.assertEqual(before, len(provider.calls))
            self.assertEqual(len(lane.search("alpha", 2, allowed_doc_ids=frozenset({"doc_" + "d" * 24})).candidates), 1)
            with self.assertRaises(ValueError):
                lane.vectors.flags.writeable = True
            with self.assertRaises(FileExistsError):
                build_dense(self.store, provider, output_dir=target, data_root=root)

    def test_identity_dimensions_and_artifact_tampering_fail_closed(self):
        provider = FakeKure()
        with self.assertRaises(ValueError):
            DenseChildLane(self.store, np.ones((2, 768)), provider)
        with self.assertRaises(ValueError):
            DenseChildLane(self.store, np.eye(2, 1024), provider)
        provider.revision = "wrong"
        with self.assertRaises(ValueError):
            DenseChildLane(self.store, np.ones((2, 1024)), provider)
        provider = FakeKure()
        with tempfile.TemporaryDirectory() as temp:
            root, target = Path(temp), Path(temp) / "private" / "dense"
            build_dense(self.store, provider, output_dir=target, data_root=root)
            path = target / "receipt.json"
            receipt = json.loads(path.read_text())
            receipt["rows_sha256"] = "0" * 64
            path.write_text(json.dumps(receipt))
            with self.assertRaises(ValueError):
                load_dense(self.store, provider, output_dir=target, data_root=root)

    def test_fake_provider_cannot_claim_real_execution(self):
        provider = FakeKure()
        provider.execution_kind = "real_local_model"
        with tempfile.TemporaryDirectory() as temp:
            root, target = Path(temp), Path(temp) / "private" / "dense"
            receipt = build_dense(self.store, provider, output_dir=target, data_root=root)
            self.assertEqual(receipt["execution_kind"], "synthetic")


if __name__ == "__main__":
    unittest.main()
