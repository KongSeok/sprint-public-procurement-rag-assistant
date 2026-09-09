#!/usr/bin/env python3
"""저장된 추론 답변을 API 재호출 없이 채점기 v3로 재채점한다."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

from src.evaluation.golden_set_v3 import load_golden_set_v3


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v2-run-dir", type=Path, required=True)
    parser.add_argument(
        "--scorer",
        type=Path,
        default=Path("src/evaluation/scoring_v3/scorer.py"),
    )
    args = parser.parse_args()

    spec = importlib.util.spec_from_file_location("scorer_v3", args.scorer)
    if spec is None or spec.loader is None:
        raise ImportError(args.scorer)
    scorer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scorer)

    golden = load_golden_set_v3()
    predictions = read_jsonl(args.v2_run_dir / "inference.jsonl")
    details, summary = scorer.evaluate(golden.to_dict("records"), predictions)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("TARGETS")
    target_ids = {
        "supplemental-qa-c16", "supplemental-qa-c19", "supplemental-qa-c20",
        "supplemental-qa-g11", "supplemental-qa-g16", "supplemental-qa-g21",
        "supplemental-qa-g22", "supplemental-qa-g24",
    }
    for row in details:
        if row["id"] in target_ids:
            print(
                row["id"], row["response_status"],
                row["end_to_end_score"], row.get("lexical_fact_score"),
            )
    print("ABSTENTION_MISMATCHES")
    for row in details:
        if row.get("abstention_match") is False:
            print(row["id"], row["response_status"], str(row.get("answer"))[:240])


if __name__ == "__main__":
    main()
