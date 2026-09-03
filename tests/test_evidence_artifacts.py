import json
from pathlib import Path
import tempfile
import unittest

from midprojectrag.evidence.artifacts import freeze_bundle, load_bundle
from midprojectrag.evidence.builder import SplitConfig, build_store, split_spans
from tests.test_evidence_builder import chunk


class EvidenceArtifactTests(unittest.TestCase):
    def test_heading_split_keeps_exact_text_and_hash_separate(self):
        text = "# 사업\n내용\n\n# 금액\n100원\n\n" + "긴" * 3400
        compat, structured = SplitConfig(), SplitConfig("heading-paragraph-v1")
        spans = split_spans(text, structured)
        self.assertNotEqual(spans, split_spans(text, compat))
        self.assertNotEqual(compat.config_sha256, structured.config_sha256)
        self.assertTrue(all(0 < e-s <= 1600 for s, e in spans))
        represented = {i for s, e in spans for i in range(s, e)}
        self.assertTrue(all(text[i].isspace() for i in range(len(text)) if i not in represented))
        self.assertTrue(all(a[1] <= b[0] for a, b in zip(spans, spans[1:])))
        self.assertEqual("".join(c for s, e in spans for c in text[s:e] if not c.isspace()),
                         "".join(c for c in text if not c.isspace()))

    def test_freeze_load_no_overwrite_and_private_permissions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "private" / "new-bundle"
            store = build_store([chunk("sample")])
            receipt = freeze_bundle(store, SplitConfig(), {"chunks": "a" * 64}, output_dir=target, data_root=root)
            loaded, loaded_receipt = load_bundle(target, data_root=root)
            self.assertEqual(loaded.bundle_sha256, store.bundle_sha256)
            self.assertEqual(receipt, loaded_receipt)
            self.assertEqual((target / "store.json").stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                freeze_bundle(store, SplitConfig(), {"chunks": "a" * 64}, output_dir=target, data_root=root)
            with self.assertRaises(ValueError):
                freeze_bundle(store, SplitConfig(), {"chunks": "a" * 64}, output_dir=root / "public", data_root=root)

    def test_tampered_bundle_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "private" / "new-bundle"
            freeze_bundle(build_store([chunk("sample")]), SplitConfig(), {"chunks": "a" * 64}, output_dir=target, data_root=root)
            receipt_path = target / "receipt.json"
            value = json.loads(receipt_path.read_text())
            value["doc_count"] = 999
            receipt_path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                load_bundle(target, data_root=root)

    def test_config_must_describe_real_child_spans(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = build_store([chunk("# heading\nbody\n\n# next\nbody")])
            with self.assertRaises(ValueError):
                freeze_bundle(store, SplitConfig("heading-paragraph-v1"), {"chunks": "a" * 64},
                              output_dir=root / "private" / "bundle", data_root=root)
            self.assertFalse((root / "private").exists())

    def test_private_root_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "public").mkdir()
            (root / "private").symlink_to(root / "public", target_is_directory=True)
            with self.assertRaises(ValueError):
                freeze_bundle(build_store([chunk("text")]), SplitConfig(), {"chunks": "a" * 64},
                              output_dir=root / "private" / "bundle", data_root=root)
            self.assertEqual(list((root / "public").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
