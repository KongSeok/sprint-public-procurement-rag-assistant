#!/usr/bin/env python3
"""통합 RAG 모델 실행.

예시:
  python scripts/run_integrated_model.py --provider openai --query "사업 예산은?"
  python scripts/run_integrated_model.py --provider vllm --query "사업 예산은?"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.generation.providers import create_generator  # noqa: E402
from src.integrated_pipeline import IntegratedRAGPipeline  # noqa: E402
from src.pipeline import run_pipeline  # noqa: E402
from src.runtime_integrity import build_runtime_manifest  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--provider", choices=("openai", "vllm", "ollama"), default="openai")
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--org")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--vector-weight", type=float, default=0.5)
    parser.add_argument("--bm25-weight", type=float, default=0.5)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--no-auto-filter", action="store_true")
    parser.add_argument("--output", type=Path, help="결과와 실행환경을 저장할 JSON 경로")
    args = parser.parse_args()

    _, _, index = run_pipeline(use_cache=not args.rebuild)
    generator = create_generator(
        args.provider,
        model=args.model,
        base_url=args.base_url,
        api_key=os.getenv("OPENAI_API_KEY") if args.provider == "openai" else None,
    )
    pipeline = IntegratedRAGPipeline(
        index,
        generator,
        top_k=args.k,
        vector_weight=args.vector_weight,
        bm25_weight=args.bm25_weight,
        auto_query_filter=not args.no_auto_filter,
    )
    result = pipeline.answer(args.query, organization=args.org).to_dict()
    payload = {
        "runtime": build_runtime_manifest(provider=generator.provider, model=generator.model),
        "result": result,
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
