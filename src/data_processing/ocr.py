"""스캔 PDF OCR backend 선택.

기본 Tesseract 동작을 유지하면서 최신 시각 검색 브랜치의 PP-OCRv5 방식을
선택적으로 사용할 수 있게 한다. Paddle 모델 경로를 명시해야 하며 실행 중
모델을 자동 다운로드하지 않는다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


class OCRBackend(Protocol):
    name: str

    def recognize(self, image: Any) -> str:
        """PIL 이미지에서 텍스트를 추출한다."""


@dataclass
class TesseractOCRBackend:
    name: str = "tesseract-kor-eng"

    def recognize(self, image: Any) -> str:
        import pytesseract

        command = os.getenv("TESSERACT_CMD")
        if command:
            pytesseract.pytesseract.tesseract_cmd = command
        return pytesseract.image_to_string(image, lang="kor+eng")


@dataclass
class PaddleOCRV5Backend:
    detection_model_dir: Path
    recognition_model_dir: Path
    minimum_score: float = 0.5
    name: str = "paddleocr-ppocrv5-korean"
    _engine: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.detection_model_dir = Path(self.detection_model_dir).resolve()
        self.recognition_model_dir = Path(self.recognition_model_dir).resolve()
        if not self.detection_model_dir.is_dir() or not self.recognition_model_dir.is_dir():
            raise ValueError("PaddleOCR 모델 폴더가 존재하지 않습니다")
        if not 0 <= self.minimum_score <= 1:
            raise ValueError("OCR 최소 신뢰도는 0~1이어야 합니다")

    def _load_engine(self):
        if self._engine is None:
            os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            from paddleocr import PaddleOCR

            self._engine = PaddleOCR(
                text_detection_model_name="PP-OCRv5_server_det",
                text_detection_model_dir=str(self.detection_model_dir),
                text_recognition_model_name="korean_PP-OCRv5_mobile_rec",
                text_recognition_model_dir=str(self.recognition_model_dir),
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                text_recognition_batch_size=1,
                text_det_limit_side_len=1280,
                text_det_limit_type="max",
                text_rec_score_thresh=self.minimum_score,
                device="cpu",
                cpu_threads=1,
                enable_mkldnn=False,
                enable_hpi=False,
            )
        return self._engine

    def recognize(self, image: Any) -> str:
        import numpy as np

        results = self._load_engine().predict(np.asarray(image))
        if len(results) != 1:
            raise RuntimeError("ocr_result_count_invalid")
        result = results[0]
        texts = result["rec_texts"]
        scores = result["rec_scores"]
        if len(texts) != len(scores):
            raise RuntimeError("ocr_result_lengths_invalid")
        accepted = [
            str(text).strip()
            for text, score in zip(texts, scores, strict=True)
            if str(text).strip() and float(score) >= self.minimum_score
        ]
        return "\n".join(accepted)


def get_ocr_backend(name: str | None = None) -> OCRBackend:
    selected = (name or os.getenv("RAG_OCR_BACKEND", "tesseract")).strip().lower()
    if selected == "tesseract":
        return TesseractOCRBackend()
    if selected != "paddle":
        raise ValueError(f"지원하지 않는 OCR backend: {selected}")
    detection = os.getenv("PADDLE_OCR_DET_MODEL_DIR")
    recognition = os.getenv("PADDLE_OCR_REC_MODEL_DIR")
    if not detection or not recognition:
        raise ValueError("PADDLE_OCR_DET_MODEL_DIR와 PADDLE_OCR_REC_MODEL_DIR가 필요합니다")
    return PaddleOCRV5Backend(Path(detection), Path(recognition))
