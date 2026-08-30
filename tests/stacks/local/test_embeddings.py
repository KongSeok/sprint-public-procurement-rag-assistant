from __future__ import annotations

import os
import subprocess
import sys
import unittest

import numpy as np

from midprojectrag.stacks.local import LocalHashEmbeddingProvider, LocalTextCounter


class LocalEmbeddingTests(unittest.TestCase):
    def test_hash_embedding_is_deterministic_and_nfc_stable(self) -> None:
        provider = LocalHashEmbeddingProvider()
        first = np.asarray(provider.embed(["입찰 예산 57,000,000원"]).vectors)
        second = np.asarray(provider.embed(["입찰 예산 57,000,000원"]).vectors)
        decomposed = np.asarray(provider.embed(["입찰 예산 57,000,000원"]).vectors)
        np.testing.assert_array_equal(first, second)
        np.testing.assert_array_equal(first, decomposed)
        self.assertEqual(first.shape, (1, 2048))

    def test_hash_is_identical_across_python_hash_seeds(self) -> None:
        script = (
            "import hashlib; import numpy as np; "
            "from midprojectrag.stacks.local import LocalHashEmbeddingProvider; "
            "v=np.asarray(LocalHashEmbeddingProvider().embed(['입찰 예산']).vectors,dtype=np.float32); "
            "print(hashlib.sha256(v.tobytes()).hexdigest())"
        )
        hashes = []
        for seed in ("1", "999"):
            environment = dict(os.environ)
            environment["PYTHONHASHSEED"] = seed
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            completed = subprocess.run(
                [sys.executable, "-B", "-c", script],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )
            hashes.append(completed.stdout.strip())
        self.assertEqual(hashes[0], hashes[1])

    def test_overlap_scores_above_unrelated_text(self) -> None:
        provider = LocalHashEmbeddingProvider()
        vectors = np.asarray(
            provider.embed(
                [
                    "기업 재생에너지 지원센터 용역비용",
                    "재생에너지 지원센터 사업 비용은 얼마인가",
                    "중이온가속기 극저온 냉각 시스템",
                ]
            ).vectors,
            dtype=np.float32,
        )
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
        self.assertGreater(float(vectors[0] @ vectors[1]), float(vectors[0] @ vectors[2]))

    def test_edge_inputs_are_finite_nonzero_and_dimensions_are_fixed(self) -> None:
        provider = LocalHashEmbeddingProvider()
        vectors = np.asarray(provider.embed(["!!!", "가", "12345", "ASCII", "한글"]).vectors)
        self.assertTrue(np.isfinite(vectors).all())
        self.assertTrue(np.all(np.linalg.norm(vectors, axis=1) > 0))
        with self.assertRaisesRegex(ValueError, "invalid_local_hash_dimensions"):
            LocalHashEmbeddingProvider(dimensions=1536)
        self.assertEqual(LocalTextCounter().count("가나다"), 3)


if __name__ == "__main__":
    unittest.main()
