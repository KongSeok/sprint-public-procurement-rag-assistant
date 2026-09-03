#!/usr/bin/env python3
"""저장된 통합 결과의 근거·인용 계약을 오프라인으로 재검증한다."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.evaluation.offline_replay import load_results, summarize_integrated_results  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("result_path")
    args = parser.parse_args()
    summary = summarize_integrated_results(load_results(args.result_path))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
