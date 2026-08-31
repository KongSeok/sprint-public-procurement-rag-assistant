from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import statistics
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from midprojectrag.ingest.common import canonical_json, read_jsonl, sha256_file, write_json


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASELINE_ID = "corpus-analytics-deterministic-v1"
BASELINE_DIR = PROJECT_ROOT / "evaluation" / "baselines" / BASELINE_ID
CONFIG_PATH = BASELINE_DIR / "config.json"
PUBLIC_RECEIPT_PATH = BASELINE_DIR / "receipt.json"
PUBLIC_REPORT_PATH = (
    PROJECT_ROOT / "fivecircles" / "work" / "2026-08-31-corpus-analytics-deterministic-results.md"
)
PRIVATE_RUN_DIR = PROJECT_ROOT / "evaluation" / "private" / "corpus-analytics" / BASELINE_ID
PRIVATE_CASES_PATH = PRIVATE_RUN_DIR / "case-results.jsonl"
PRIVATE_METRICS_PATH = PRIVATE_RUN_DIR / "metrics.json"

CASES_PATH = PROJECT_ROOT / "golden-set-final" / "corpus-analytics-qa.jsonl"
TARGETS_PATH = PROJECT_ROOT / "golden-set-final" / "corpus-analytics-target-sets.json"
CATEGORIES_PATH = PROJECT_ROOT / "golden-set-final" / "project-category-v1.jsonl"
CSV_PATH = PROJECT_ROOT / "resources" / "data_refined" / "refined_data_list.csv"
MANIFEST_PATH = (
    PROJECT_ROOT / "resources" / "data_refined" / "private" / "manifest.extracted.jsonl"
)

EXPECTED_HASHES = {
    "cases": "e2324fea2cac26520ba371183675f933ab997b0ff5d54c796a608f6f44c37c2f",
    "targets": "a6eaf98780c3efc314f3998a116c42960a5c518f5df1306bd72cc2c61587bf4e",
    "categories": "968f8f9baf3449bce1985464ae1b800b73a5f70d3713b0172cb8736e0dbaecca",
    "refined_csv": "cef0a27602976af468206ad2fa855027cb6f686fc877a52ce8fb191c57cd7e5b",
    "manifest": "6c91d30a4c01b12f1aae8924c88a2e5055446c841f5eabfbf687546fdc1fe1cb",
}
EXPECTED_SNAPSHOT_ID = "snapshot_f14ad7018fae2d3905c4e604"
EXPECTED_SUITE_VERSION = "2026-08-31-local-draft-v1"
EXPECTED_CASE_IDS = tuple(f"analytics-{number:03d}" for number in range(1, 11))
EXPECTED_OPERATIONS = (
    "group_count_and_share",
    "amount_quality_counts",
    "argmax_group_count_with_ties",
    "mean_median_and_ratio",
    "quartiles_and_iqr",
    "category_count_and_positive_amount_median",
    "top_decile_share",
    "tukey_upper_outlier_concentration",
    "argmax_category_mean_to_median_ratio",
    "outlier_exclusion_sensitivity",
)
CATEGORY_KEYS = (
    "planning_consulting",
    "operations_maintenance",
    "new_build_rebuild",
    "enhancement_improvement",
    "other",
)
CATEGORY_LABELS = {
    "planning_consulting": "기획·컨설팅",
    "operations_maintenance": "운영·유지보수",
    "new_build_rebuild": "신규 구축·재구축",
    "enhancement_improvement": "고도화·개선",
    "other": "기타",
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _verify_hash(path: Path, expected: str, label: str) -> str:
    actual = sha256_file(path)
    if actual != expected:
        raise ValueError(f"{label}_sha256_mismatch:{actual}")
    return actual


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def _atomic_private_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(content)
        os.replace(temporary_path, path)
        path.chmod(0o600)
    finally:
        temporary_path.unlink(missing_ok=True)


def _write_private_json(path: Path, value: Any) -> None:
    _atomic_private_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _write_private_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    _atomic_private_text(path, "".join(canonical_json(dict(row)) + "\n" for row in rows))


def _read_csv(path: Path) -> list[dict[str, str]]:
    previous_limit = csv.field_size_limit()
    try:
        csv.field_size_limit(sys.maxsize)
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            rows = list(csv.DictReader(source))
    finally:
        csv.field_size_limit(previous_limit)
    return rows


def _amount_value(raw: str) -> int | None:
    stripped = raw.strip()
    return None if not stripped else int(Decimal(stripped))


def linear_quantile(values: Sequence[int], probability: float) -> float:
    if not values:
        raise ValueError("quantile_requires_values")
    if probability < 0 or probability > 1:
        raise ValueError("quantile_probability_out_of_range")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _round_won(value: float) -> int:
    return int(round(value))


def _load_and_bind_inputs() -> tuple[
    list[dict[str, Any]], dict[str, Any], list[dict[str, Any]], dict[str, Any]
]:
    paths = {
        "cases": CASES_PATH,
        "targets": TARGETS_PATH,
        "categories": CATEGORIES_PATH,
        "refined_csv": CSV_PATH,
        "manifest": MANIFEST_PATH,
    }
    for label, path in paths.items():
        _verify_hash(path, EXPECTED_HASHES[label], label)

    config = _read_json(CONFIG_PATH)
    if config.get("baseline_id") != BASELINE_ID:
        raise ValueError("baseline_config_id_mismatch")
    if config.get("input_sha256") != EXPECTED_HASHES:
        raise ValueError("baseline_config_hash_contract_mismatch")
    if tuple(config.get("operations", [])) != EXPECTED_OPERATIONS:
        raise ValueError("baseline_config_operations_mismatch")

    cases = read_jsonl(CASES_PATH)
    targets = _read_json(TARGETS_PATH)
    categories = read_jsonl(CATEGORIES_PATH)
    if tuple(case.get("case_id") for case in cases) != EXPECTED_CASE_IDS:
        raise ValueError("analytics_case_identity_mismatch")
    if tuple(case.get("calculation_contract", {}).get("operation") for case in cases) != EXPECTED_OPERATIONS:
        raise ValueError("analytics_case_operation_mismatch")
    if any(case.get("suite_version") != EXPECTED_SUITE_VERSION for case in cases):
        raise ValueError("analytics_suite_version_mismatch")
    if Counter(case.get("difficulty") for case in cases) != Counter(
        {"easy": 3, "medium": 4, "hard": 3}
    ):
        raise ValueError("analytics_difficulty_distribution_mismatch")
    if any(case.get("review", {}).get("status") != "draft" for case in cases):
        raise ValueError("analytics_review_state_changed")

    for case in cases:
        contract = case.get("calculation_contract", {})
        if contract.get("refined_csv_sha256") != EXPECTED_HASHES["refined_csv"]:
            raise ValueError("case_refined_csv_hash_mismatch")
        if contract.get("manifest_sha256") != EXPECTED_HASHES["manifest"]:
            raise ValueError("case_manifest_hash_mismatch")
        if contract.get("corpus_snapshot_id") != EXPECTED_SNAPSHOT_ID:
            raise ValueError("case_snapshot_id_mismatch")

    source_contract = targets.get("source_contract", {})
    if source_contract.get("refined_csv_sha256") != EXPECTED_HASHES["refined_csv"]:
        raise ValueError("targets_refined_csv_hash_mismatch")
    if source_contract.get("manifest_sha256") != EXPECTED_HASHES["manifest"]:
        raise ValueError("targets_manifest_hash_mismatch")
    if source_contract.get("corpus_snapshot_id") != EXPECTED_SNAPSHOT_ID:
        raise ValueError("targets_snapshot_id_mismatch")
    return cases, targets, categories, config


def _build_enriched(categories: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = _read_csv(CSV_PATH)
    manifest = read_jsonl(MANIFEST_PATH)
    if len(rows) != 98 or len(manifest) != 98 or len(categories) != 98:
        raise ValueError(
            f"refined98_count_mismatch:csv={len(rows)},manifest={len(manifest)},categories={len(categories)}"
        )
    snapshot_ids = {item.get("snapshot_id") for item in manifest}
    if snapshot_ids != {EXPECTED_SNAPSHOT_ID}:
        raise ValueError("manifest_snapshot_id_mismatch")
    row_to_doc = {
        int(item["csv_row_number"]) - 1: item["doc_id"]
        for item in manifest
    }
    category_by_row = {int(item["row_number"]): item for item in categories}
    expected_rows = set(range(1, 99))
    if set(row_to_doc) != expected_rows or set(category_by_row) != expected_rows:
        raise ValueError("row_join_coverage_mismatch")
    if len(set(row_to_doc.values())) != 98:
        raise ValueError("manifest_doc_id_duplicate")

    enriched: list[dict[str, Any]] = []
    for row_number, row in enumerate(rows, start=1):
        category_row = category_by_row[row_number]
        amount_won = _amount_value(row["사업 금액"])
        source_format = row["파일형식"].strip().lower()
        expected_projection = {
            "doc_id": row_to_doc[row_number],
            "project_name": row["사업명"],
            "ordering_agency": row["발주 기관"],
            "source_format": source_format,
            "amount_won": amount_won,
        }
        for field, expected in expected_projection.items():
            if category_row.get(field) != expected:
                raise ValueError(f"category_projection_mismatch:{row_number}:{field}")
        category = category_row.get("project_category_v1")
        if category not in CATEGORY_KEYS:
            raise ValueError(f"unknown_project_category:{row_number}")
        enriched.append(
            {
                "row_number": row_number,
                **expected_projection,
                "project_category_v1": category,
            }
        )
    return enriched


def _member_projection(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "row_number": item["row_number"],
        "doc_id": item["doc_id"],
        "project_name": item["project_name"],
        "amount_won": item["amount_won"],
    }


def _calculate(
    enriched: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    positives = [item for item in enriched if (item["amount_won"] or 0) > 0]
    amounts = [int(item["amount_won"]) for item in positives]
    q1 = linear_quantile(amounts, 0.25)
    median = linear_quantile(amounts, 0.50)
    q3 = linear_quantile(amounts, 0.75)
    iqr = q3 - q1
    outlier_threshold = q3 + 1.5 * iqr
    outliers = [item for item in positives if item["amount_won"] > outlier_threshold]
    non_outliers = [item for item in positives if item["amount_won"] <= outlier_threshold]
    top_n = math.ceil(len(positives) * 0.10)
    top_ten_percent = sorted(
        positives, key=lambda item: int(item["amount_won"]), reverse=True
    )[:top_n]

    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in enriched:
        groups[str(item["project_category_v1"])].append(item)
    category_stats: dict[str, dict[str, Any]] = {}
    for category in CATEGORY_KEYS:
        items = groups[category]
        category_amounts = [
            int(item["amount_won"])
            for item in items
            if (item["amount_won"] or 0) > 0
        ]
        mean = statistics.fmean(category_amounts) if category_amounts else None
        category_median = statistics.median(category_amounts) if category_amounts else None
        category_stats[category] = {
            "label_ko": CATEGORY_LABELS[category],
            "document_count": len(items),
            "positive_amount_count": len(category_amounts),
            "missing_amount_count": sum(item["amount_won"] is None for item in items),
            "mean_won_raw": mean,
            "mean_won_rounded": _round_won(mean) if mean is not None else None,
            "median_won": category_median,
            "mean_to_median_ratio": (
                mean / category_median
                if mean is not None and category_median not in (None, 0)
                else None
            ),
            "target_set_id": f"category.{category}",
        }

    target_members: dict[str, list[Mapping[str, Any]]] = {
        "corpus.all_98": list(enriched),
        "amount.positive_95": positives,
        "amount.top_10_percent_10": top_ten_percent,
        "amount.tukey_upper_outliers_9": sorted(
            outliers, key=lambda item: int(item["amount_won"]), reverse=True
        ),
        "amount.tukey_non_outliers_86": non_outliers,
        **{f"category.{category}": groups[category] for category in CATEGORY_KEYS},
    }
    computed_targets = {
        target_id: {
            "count": len(members),
            "members": [_member_projection(item) for item in members],
            "members_sha256": _json_sha256([_member_projection(item) for item in members]),
        }
        for target_id, members in target_members.items()
    }

    format_counts = Counter(str(item["source_format"]) for item in enriched)
    missing_amount_count = sum(item["amount_won"] is None for item in enriched)
    zero_amount_count = sum(item["amount_won"] == 0 for item in enriched)
    agency_counts = Counter(str(item["ordering_agency"]) for item in enriched)
    max_agency_count = max(agency_counts.values())
    leading_agencies = sorted(
        agency for agency, count in agency_counts.items() if count == max_agency_count
    )
    mean_amount = statistics.fmean(amounts)
    total_amount = sum(amounts)
    top_sum = sum(int(item["amount_won"]) for item in top_ten_percent)
    outlier_sum = sum(int(item["amount_won"]) for item in outliers)
    base_amounts = [int(item["amount_won"]) for item in non_outliers]
    base_mean = statistics.fmean(base_amounts)
    base_median = statistics.median(base_amounts)
    eligible_categories = [
        category
        for category in CATEGORY_KEYS
        if category_stats[category]["positive_amount_count"] >= 5
    ]
    winner = max(
        eligible_categories,
        key=lambda category: category_stats[category]["mean_to_median_ratio"],
    )

    outputs = {
        "analytics-001": {
            "total_documents": len(enriched),
            "counts": dict(format_counts),
            "percentages": {
                "hwp": round(format_counts["hwp"] / len(enriched) * 100, 2),
                "pdf": round(format_counts["pdf"] / len(enriched) * 100, 2),
            },
        },
        "analytics-002": {
            "positive": len(positives),
            "missing": missing_amount_count,
            "zero": zero_amount_count,
            "analysis_n": len(positives),
        },
        "analytics-003": {"max_count": max_agency_count, "agencies": leading_agencies},
        "analytics-004": {
            "n": len(positives),
            "sum_won": total_amount,
            "mean_won_raw": mean_amount,
            "mean_won_rounded": _round_won(mean_amount),
            "median_won": median,
            "mean_to_median_ratio": round(mean_amount / median, 4),
        },
        "analytics-005": {
            "n": len(positives),
            "q1_won": q1,
            "q2_won": median,
            "q3_won": q3,
            "iqr_won": iqr,
        },
        "analytics-006": {
            "new_build_rebuild": category_stats["new_build_rebuild"],
            "enhancement_improvement": category_stats["enhancement_improvement"],
        },
        "analytics-007": {
            "n": len(positives),
            "top_n": top_n,
            "top_sum_won": top_sum,
            "all_sum_won": total_amount,
            "share_percent": round(top_sum / total_amount * 100, 4),
            "cutoff_won": top_ten_percent[-1]["amount_won"],
            "top_project_doc_ids": [item["doc_id"] for item in top_ten_percent],
        },
        "analytics-008": {
            "threshold_won": outlier_threshold,
            "outlier_count": len(outliers),
            "outlier_document_share_percent": round(
                len(outliers) / len(positives) * 100, 4
            ),
            "outlier_sum_won": outlier_sum,
            "outlier_amount_share_percent": round(outlier_sum / total_amount * 100, 4),
            "outlier_doc_ids": [
                item["doc_id"]
                for item in sorted(
                    outliers, key=lambda item: int(item["amount_won"]), reverse=True
                )
            ],
        },
        "analytics-009": {
            "winner": winner,
            "winner_stats": category_stats[winner],
            "eligible_categories": eligible_categories,
            "all_category_stats": category_stats,
        },
        "analytics-010": {
            "all_n": len(positives),
            "non_outlier_n": len(non_outliers),
            "all_mean_won_raw": mean_amount,
            "non_outlier_mean_won_raw": base_mean,
            "non_outlier_mean_won_rounded": _round_won(base_mean),
            "mean_reduction_percent": round((mean_amount - base_mean) / mean_amount * 100, 4),
            "all_median_won": median,
            "non_outlier_median_won": base_median,
            "median_reduction_percent": round((median - base_median) / median * 100, 4),
        },
    }
    return outputs, computed_targets


def _compare_values(
    actual: Any,
    expected: Any,
    tolerances: Mapping[str, Any],
    path: str = "$",
) -> list[dict[str, Any]]:
    if isinstance(expected, Mapping):
        if not isinstance(actual, Mapping):
            return [{"path": path, "match": False, "reason": "type_mismatch"}]
        rows: list[dict[str, Any]] = []
        if set(actual) != set(expected):
            rows.append({"path": path, "match": False, "reason": "key_set_mismatch"})
        for key in sorted(set(actual) & set(expected)):
            rows.extend(_compare_values(actual[key], expected[key], tolerances, f"{path}.{key}"))
        return rows
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return [{"path": path, "match": False, "reason": "type_mismatch"}]
        rows = []
        if len(actual) != len(expected):
            rows.append({"path": path, "match": False, "reason": "length_mismatch"})
        for index, (actual_item, expected_item) in enumerate(zip(actual, expected)):
            rows.extend(
                _compare_values(actual_item, expected_item, tolerances, f"{path}[{index}]")
            )
        return rows
    if (
        isinstance(expected, (int, float))
        and not isinstance(expected, bool)
        and isinstance(actual, (int, float))
        and not isinstance(actual, bool)
    ):
        lowered = path.lower()
        if "percent" in lowered:
            tolerance = float(tolerances.get("percentage_point", 0.0))
        elif "ratio" in lowered:
            tolerance = float(tolerances.get("ratio", 0.0))
        elif "won" in lowered:
            tolerance = float(tolerances.get("money_won", 0.0))
        else:
            tolerance = 0.0
        return [
            {
                "path": path,
                "match": math.isclose(float(actual), float(expected), abs_tol=tolerance),
                "reason": "numeric_tolerance",
                "absolute_difference": abs(float(actual) - float(expected)),
                "tolerance": tolerance,
            }
        ]
    return [
        {
            "path": path,
            "match": actual == expected,
            "reason": "exact",
        }
    ]


def _verify_targets(
    cases: Sequence[Mapping[str, Any]],
    target_contract: Mapping[str, Any],
    computed_targets: Mapping[str, Mapping[str, Any]],
) -> None:
    frozen_targets = target_contract.get("target_sets")
    if not isinstance(frozen_targets, Mapping) or set(frozen_targets) != set(computed_targets):
        raise ValueError("target_set_identity_mismatch")
    for target_id, computed in computed_targets.items():
        frozen = frozen_targets[target_id]
        if not isinstance(frozen, Mapping):
            raise ValueError(f"target_set_contract_invalid:{target_id}")
        if frozen.get("count") != computed["count"]:
            raise ValueError(f"target_set_count_mismatch:{target_id}")
        if frozen.get("members_sha256") != computed["members_sha256"]:
            raise ValueError(f"target_set_hash_mismatch:{target_id}")
        if frozen.get("members") != computed["members"]:
            raise ValueError(f"target_set_members_mismatch:{target_id}")
    for case in cases:
        scope = case.get("document_scope", {})
        for target_id in scope.get("target_set_ids", []):
            if scope.get("target_set_hashes", {}).get(target_id) != computed_targets[target_id]["members_sha256"]:
                raise ValueError(f"case_target_hash_mismatch:{case['case_id']}:{target_id}")


def _build_public_report(receipt: Mapping[str, Any], receipt_sha256: str) -> str:
    metrics = receipt["metrics"]
    counts = receipt["counts"]
    return f"""# 코퍼스 집계 10문항 결정론적 베이스라인 결과

- 상태: **{receipt['result_label']}**
- 실행 방식: 외부 API·네트워크 없이 refined98 구조화 원천에서 재계산
- 문항: {counts['cases_total']}건 (쉬움 {counts['difficulty']['easy']} / 보통 {counts['difficulty']['medium']} / 어려움 {counts['difficulty']['hard']})
- 문항 정확도: {metrics['case_accuracy']:.4f} ({counts['cases_passed']}/{counts['cases_total']})
- 필드 정확도: {metrics['field_accuracy']:.4f} ({counts['fields_passed']}/{counts['fields_total']})
- 원천 무결성: {metrics['source_integrity_passed']}
- target-set 재구성 무결성: {metrics['target_set_integrity_passed']}
- 의미 불일치: {counts['semantic_mismatches']}건
- 외부 호출 / 비용: 0회 / USD 0
- 공개 receipt SHA-256: `{receipt_sha256}`

이 결과는 팀 승인 전 `draft` 골든 문항을 실행한 **provisional 평가**다. 정답 값은 공개 보고서에 복제하지 않았으며 문항별 계산값·정답 비교는 ignored private artifact에만 저장했다.
"""


def run_baseline() -> dict[str, Any]:
    cases, target_contract, categories, config = _load_and_bind_inputs()
    enriched = _build_enriched(categories)
    outputs, computed_targets = _calculate(enriched)
    _verify_targets(cases, target_contract, computed_targets)

    case_records: list[dict[str, Any]] = []
    difficulty_totals: Counter[str] = Counter()
    difficulty_passed: Counter[str] = Counter()
    fields_total = 0
    fields_passed = 0
    for case in cases:
        case_id = str(case["case_id"])
        expected = case["gold"]["expected"]
        computed = outputs[case_id]
        comparisons = _compare_values(
            computed,
            expected,
            case["gold"].get("numeric_tolerance", {}),
        )
        passed = bool(comparisons) and all(item["match"] for item in comparisons)
        difficulty = str(case["difficulty"])
        difficulty_totals[difficulty] += 1
        difficulty_passed[difficulty] += int(passed)
        fields_total += len(comparisons)
        fields_passed += sum(bool(item["match"]) for item in comparisons)
        case_records.append(
            {
                "schema_version": "1.0",
                "baseline_id": BASELINE_ID,
                "result_label": "provisional_draft_gold",
                "case_id": case_id,
                "difficulty": difficulty,
                "operation": case["calculation_contract"]["operation"],
                "question_sha256": hashlib.sha256(case["question"].encode("utf-8")).hexdigest(),
                "computed": computed,
                "gold_expected": expected,
                "comparisons": comparisons,
                "passed": passed,
            }
        )

    cases_passed = sum(record["passed"] for record in case_records)
    private_metrics = {
        "schema_version": "1.0",
        "baseline_id": BASELINE_ID,
        "result_label": "provisional_draft_gold",
        "input_sha256": EXPECTED_HASHES,
        "config_sha256": sha256_file(CONFIG_PATH),
        "counts": {
            "cases_total": len(case_records),
            "cases_passed": cases_passed,
            "fields_total": fields_total,
            "fields_passed": fields_passed,
            "difficulty": dict(difficulty_totals),
            "difficulty_passed": dict(difficulty_passed),
            "semantic_mismatches": len(case_records) - cases_passed,
        },
        "metrics": {
            "case_accuracy": cases_passed / len(case_records),
            "field_accuracy": fields_passed / fields_total,
            "difficulty_accuracy": {
                difficulty: difficulty_passed[difficulty] / difficulty_totals[difficulty]
                for difficulty in ("easy", "medium", "hard")
            },
            "source_integrity_passed": True,
            "target_set_integrity_passed": True,
        },
        "operations": {
            "external_provider_calls": 0,
            "network_access": False,
            "total_cost_usd": 0.0,
        },
    }
    _write_private_jsonl(PRIVATE_CASES_PATH, case_records)
    _write_private_json(PRIVATE_METRICS_PATH, private_metrics)

    private_cases_hash = sha256_file(PRIVATE_CASES_PATH)
    private_metrics_hash = sha256_file(PRIVATE_METRICS_PATH)
    receipt = {
        **private_metrics,
        "executed_at": _utc_now(),
        "private_artifacts": {
            "case_results": {
                "rows": len(case_records),
                "sha256": private_cases_hash,
            },
            "metrics": {"sha256": private_metrics_hash},
        },
        "privacy": {
            "contains_questions": False,
            "contains_answers": False,
            "contains_per_case_values": False,
        },
        "config_contract": {
            "suite_version": EXPECTED_SUITE_VERSION,
            "corpus_snapshot_id": EXPECTED_SNAPSHOT_ID,
            "gold_review_status": config["gold_review_status"],
        },
    }
    write_json(PUBLIC_RECEIPT_PATH, receipt)
    receipt_sha256 = sha256_file(PUBLIC_RECEIPT_PATH)
    PUBLIC_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC_REPORT_PATH.write_text(
        _build_public_report(receipt, receipt_sha256), encoding="utf-8"
    )
    return {
        "receipt_path": str(PUBLIC_RECEIPT_PATH),
        "receipt_sha256": receipt_sha256,
        "report_path": str(PUBLIC_REPORT_PATH),
        "report_sha256": sha256_file(PUBLIC_REPORT_PATH),
        "private_case_results_path": str(PRIVATE_CASES_PATH),
        "private_case_results_sha256": private_cases_hash,
        "private_metrics_path": str(PRIVATE_METRICS_PATH),
        "private_metrics_sha256": private_metrics_hash,
        "counts": receipt["counts"],
        "metrics": receipt["metrics"],
        "operations": receipt["operations"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the frozen local-only refined98 corpus analytics baseline."
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="recompute, score, and write private/public artifacts without network access",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.run:
        _parser().print_help()
        return 0
    summary = run_baseline()
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
