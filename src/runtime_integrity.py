"""통합 실험의 재현성을 위한 실행환경 정보."""
from __future__ import annotations

import importlib.metadata
import platform
import sys
from datetime import datetime, timezone
from typing import Any


SOURCE_BRANCH_TIPS = {
    "feat/rag-pipeline-and-eval": "d51633b",
    "experiment/DH": "5ea75c7",
    "feat/local-qwen-mini131-eval": "6fea63f",
    "feat/api-gpt5mini-mini131-eval": "33f8c2f",
    "feat/evidence-harness-v1": "46275c4",
    "feature/visual-retrieval": "c2c621c",
}


def _version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def build_runtime_manifest(*, provider: str, model: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "provider": provider,
        "model": model,
        "packages": {
            "chromadb": _version("chromadb"),
            "sentence-transformers": _version("sentence-transformers"),
            "openai": _version("openai"),
            "paddleocr": _version("paddleocr"),
        },
        "source_branch_tips": dict(SOURCE_BRANCH_TIPS),
    }
