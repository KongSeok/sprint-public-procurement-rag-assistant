#!/usr/bin/env python3
"""B-v2 반복 실행 결과의 실행 간 분산과 문항별 변동성을 집계한다."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


DEFAULT_ROOT = Path("output/experiments/hanbin_dahye_v2")
RUN_FILES = (
    ("run-01", Path("golden_v3_results.csv")),
    ("run-02", Path("repeat-02/golden_v3_results.csv")),
    ("run-03", Path("repeat-03/golden_v3_results.csv")),
    ("run-04", Path("repeat-04/golden_v3_results.csv")),
)
BASELINE = {
    "answer_fact_coverage": 0.546,
    "fact_full_pass_rate": 0.377,
    "abstention_match_rate": 0.810,
    "compatible_overall_score": 55.77,
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    return parser.parse_args()


def _run_metrics(frame: pd.DataFrame) -> dict[str, float]:
    gradable = frame[frame["facts_total"].fillna(0) > 0]
    document_mentions = frame.apply(_document_mention_coverage, axis=1)
    return {
        "generation_success_rate": float(frame["generation_error"].isna().mean()),
        "retrieval_recall": float(frame["retrieval_recall"].mean()),
        "context_fact_coverage": float(gradable["context_fact_coverage"].mean()),
        "answer_fact_coverage": float(gradable["fact_coverage"].mean()),
        "fact_full_pass_rate": float(gradable["facts_pass"].mean()),
        "abstention_match_rate": float(frame["abstention_match"].mean()),
        "document_mention_coverage": float(document_mentions.mean()),
        "compatible_overall_score": float(frame["compatible_score"].mean()),
    }


def _document_mention_coverage(row: pd.Series) -> float | None:
    expected = [
        value.strip()
        for value in str(row.get("expected_doc_ids", "")).split(" | ")
        if value.strip()
    ]
    if not expected:
        return None
    answer = str(row.get("generated_answer", ""))
    return sum(doc_id in answer for doc_id in expected) / len(expected)


def _describe(values: pd.Series) -> dict[str, float]:
    return {
        "mean": round(float(values.mean()), 6),
        "sample_std": round(float(values.std(ddof=1)), 6),
        "min": round(float(values.min()), 6),
        "max": round(float(values.max()), 6),
        "range": round(float(values.max() - values.min()), 6),
    }


def _variable_case_ids(wide: pd.DataFrame, column: str) -> set[str]:
    values = wide.pivot(index="id", columns="run", values=column)
    return set(values.index[values.nunique(axis=1, dropna=True) > 1].astype(str))


def main() -> int:
    args = _parse_args()
    frames: list[pd.DataFrame] = []
    per_run: dict[str, dict[str, float]] = {}
    for run, relative_path in RUN_FILES:
        path = args.root / relative_path
        if not path.exists():
            raise FileNotFoundError(path)
        frame = pd.read_csv(path)
        if len(frame) != 79:
            raise ValueError(f"{run}: expected 79 cases, got {len(frame)}")
        frame["run"] = run
        frames.append(frame)
        per_run[run] = _run_metrics(frame)

    metric_frame = pd.DataFrame(per_run).T
    combined = pd.concat(frames, ignore_index=True)
    lane_runs: dict[str, dict[str, dict[str, float]]] = {}
    for frame in frames:
        run = str(frame["run"].iloc[0])
        for lane, group in frame.groupby("source_lane"):
            lane_runs.setdefault(str(lane), {})[run] = _run_metrics(group)

    variable_ids = {
        "fact_coverage_changed": _variable_case_ids(combined, "fact_coverage"),
        "full_pass_decision_changed": _variable_case_ids(combined, "facts_pass"),
        "abstention_match_changed": _variable_case_ids(combined, "abstention_match"),
        "compatible_score_changed": _variable_case_ids(combined, "compatible_score"),
    }
    id_to_lane = frames[0].set_index("id")["source_lane"].astype(str).to_dict()
    summary = {
        "runs": len(frames),
        "cases_per_run": 79,
        "per_run": per_run,
        "across_runs": {
            column: _describe(metric_frame[column]) for column in metric_frame.columns
        },
        "difference_from_single_run_baseline": {
            metric: round(float(metric_frame[metric].mean() - baseline), 6)
            for metric, baseline in BASELINE.items()
        },
        "lanes_across_runs": {
            lane: {
                metric: _describe(pd.DataFrame(runs).T[metric])
                for metric in pd.DataFrame(runs).T.columns
            }
            for lane, runs in lane_runs.items()
        },
        "case_variability": {
            "gradable_cases": int(
                combined[combined["facts_total"].fillna(0) > 0]["id"].nunique()
            ),
            **{name: len(ids) for name, ids in variable_ids.items()},
            "fact_coverage_changed_by_lane": {
                lane: sum(id_to_lane.get(case_id) == lane for case_id in ids)
                for lane in sorted(set(id_to_lane.values()))
                for ids in [variable_ids["fact_coverage_changed"]]
            },
            "full_pass_changed_by_lane": {
                lane: sum(id_to_lane.get(case_id) == lane for case_id in ids)
                for lane in sorted(set(id_to_lane.values()))
                for ids in [variable_ids["full_pass_decision_changed"]]
            },
        },
    }

    output = args.root / "reproducibility_summary.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"재현성 요약: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
