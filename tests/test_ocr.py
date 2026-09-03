from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from src.data_processing.ocr import TesseractOCRBackend, get_ocr_backend


class OCRBackendTest(unittest.TestCase):
    def test_default_backend_is_tesseract(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsInstance(get_ocr_backend(), TesseractOCRBackend)

    def test_paddle_requires_local_model_paths(self):
        with patch.dict(os.environ, {"RAG_OCR_BACKEND": "paddle"}, clear=True):
            with self.assertRaisesRegex(ValueError, "PADDLE_OCR_DET_MODEL_DIR"):
                get_ocr_backend()

    def test_unknown_backend_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "지원하지 않는 OCR"):
            get_ocr_backend("unknown")


if __name__ == "__main__":
    unittest.main()
