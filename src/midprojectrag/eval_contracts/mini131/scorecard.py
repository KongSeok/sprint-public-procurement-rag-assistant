"""Provider-neutral Mini131 scorecard schema and invariants."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from midprojectrag.evaluation import EXPECTED_METRIC_KEYS
from midprojectrag.eval_contracts.mini131.judge import JUDGE_WEIGHTS
from midprojectrag.eval_contracts.mini131.taxonomy import (
    PRIMARY_CATEGORY_ORDER,
    SCENARIO_PURPOSES,
    VISUAL_SUBGROUP_DEFINITIONS,
)


SCORECARD_SCHEMA_VERSION = "mini131-scorecard-contract.v1"
SCORECARD_CONTRACT_ID = "mini131-scorecard-v1"
SCORECARD_CONTRACT_PATH = "evaluation/contracts/mini131/scorecard-v1.json"
ACCEPTANCE_POLICY = {
    "score_operator": "greater_than",
    "score_threshold": 85,
    "minimum_confidence": 0.70,
    "critical_flags": "none",
}


def expected_contract() -> dict[str, Any]:
    return {
        "schema_version": SCORECARD_SCHEMA_VERSION,
        "contract_id": SCORECARD_CONTRACT_ID,
        "primary_category_order": list(PRIMARY_CATEGORY_ORDER),
        "scenario_order": list(SCENARIO_PURPOSES),
        "visual_subgroup_order": list(VISUAL_SUBGROUP_DEFINITIONS),
        "metric_keys": {
            section: sorted(keys) for section, keys in EXPECTED_METRIC_KEYS.items()
        },
        "semantic_judge": {
            "weights": copy.deepcopy(JUDGE_WEIGHTS),
            "acceptance": copy.deepcopy(ACCEPTANCE_POLICY),
        },
    }


def validate_contract(value: Mapping[str, Any]) -> dict[str, Any]:
    expected = expected_contract()
    if dict(value) != expected:
        raise ValueError("mini131_scorecard_contract_invalid")
    return copy.deepcopy(expected)
