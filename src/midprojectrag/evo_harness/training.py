"""Pure contracts for Evo policy data, leakage control, SFT export and reward.

No training framework is imported here. Serving can validate datasets and preflight
an isolated trainer without installing TRL/PEFT/Transformers v5.
"""
from __future__ import annotations

from copy import deepcopy
from importlib import metadata
import json
import platform
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence

from midprojectrag.evaluation import normalize_question
from midprojectrag.ingest.common import canonical_json, sha256_text
from .state import action_from_json

TRAINING_CASE_SCHEMA = "evo-training-case-v1"
EXCLUSION_SCHEMA = "evo-training-exclusion-v1"
SPLIT_SCHEMA = "evo-training-splits-v1"
SFT_SCHEMA = "evo-policy-sft-v1"
REWARD_SCHEMA = "evo-policy-reward-v1"
TRAJECTORY_SCHEMA = "evo-policy-trajectory-v1"
SPLITS = ("train", "dev", "sealed_holdout")

# These names carry evaluation-only or answer-key information. The check is
# recursive and applies before training artifacts are written.
FORBIDDEN_TRAINING_KEYS = frozenset({
    "gold", "qrels", "qrel", "expected_answer", "reference_answer",
    "reference_answers", "expected_action", "expected_actions", "expected_tool",
    "expected_tool_sequence", "judgment", "judgments", "semantic_judgment",
    "semantic_review", "judge_output", "judge_score", "answer_components",
    "matched_key_point_ids", "required_fact_groups", "gold_reason", "passed",
})

TRAINING_DISTRIBUTIONS = ("transformers", "trl", "peft", "datasets", "accelerate", "torch")
QLORA_DISTRIBUTIONS = ("bitsandbytes",)
BACKEND_RECEIPT_SCHEMA = "evo-sft-backend-capability-v1"
SFT_FREEZE_SCHEMA = "evo-sft-freeze-v1"
MIN_TRANSFORMERS = (5, 2, 0)


def _hash(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("training_identity_invalid")
    return sha256_text(value)


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", value or "")
    if not match:
        return (0, 0, 0)
    return tuple(int(part or 0) for part in match.groups())  # type: ignore[return-value]


def _conversation_id(case: Mapping[str, Any]) -> str | None:
    direct = case.get("conversation_id")
    if isinstance(direct, str) and direct:
        return direct
    conversation = case.get("conversation")
    if isinstance(conversation, Mapping):
        value = conversation.get("conversation_id")
        if isinstance(value, str) and value:
            return value
    request = case.get("request")
    if isinstance(request, Mapping):
        value = request.get("conversation_id")
        if isinstance(value, str) and value:
            return value
    return None


def _doc_pair(case: Mapping[str, Any]) -> tuple[str, ...] | None:
    task = case.get("task_type")
    docs: Any = None
    gold = case.get("gold")
    if isinstance(gold, Mapping) and isinstance(gold.get("required_doc_ids"), list):
        docs = gold["required_doc_ids"]
    if docs is None:
        request = case.get("request")
        if isinstance(request, Mapping):
            scope = request.get("document_scope")
            if isinstance(scope, Mapping) and isinstance(scope.get("doc_ids"), list):
                docs = scope["doc_ids"]
    if docs is None:
        scope = case.get("document_scope")
        if isinstance(scope, Mapping) and isinstance(scope.get("doc_ids"), list):
            docs = scope["doc_ids"]
    if task not in {"multi_doc_compare", "multi", "compare"} and not (isinstance(docs, list) and len(docs) == 2):
        return None
    if not isinstance(docs, list) or len(docs) < 2 or not all(isinstance(x, str) and x for x in docs):
        return None
    return tuple(sorted(set(docs)))


def case_fingerprints(case: Mapping[str, Any]) -> dict[str, str | None]:
    question = case.get("question")
    if not isinstance(question, str) or not question.strip():
        request = case.get("request")
        question = request.get("question") if isinstance(request, Mapping) else None
    if not isinstance(question, str) or not question.strip():
        raise ValueError("training_question_required")
    group = case.get("group_id")
    conversation = _conversation_id(case)
    pair = _doc_pair(case)
    return {
        "question_sha256": _hash(normalize_question(question)),
        "group_sha256": _hash(group) if isinstance(group, str) and group else None,
        "conversation_sha256": _hash(conversation) if conversation else None,
        "doc_pair_sha256": _hash(canonical_json(list(pair))) if pair else None,
    }


def build_exclusion_manifest(cases: Sequence[Mapping[str, Any]], *, source_id: str,
                             source_sha256: str | None = None) -> dict[str, Any]:
    if not isinstance(source_id, str) or not source_id:
        raise ValueError("training_exclusion_source_invalid")
    buckets = {key: set() for key in ("question_sha256", "group_sha256", "conversation_sha256", "doc_pair_sha256")}
    for case in cases:
        fingerprints = case_fingerprints(case)
        for key, value in fingerprints.items():
            if value is not None:
                buckets[key].add(value)
    manifest = {
        "schema_version": EXCLUSION_SCHEMA,
        "source_id": source_id,
        "source_sha256": source_sha256,
        "case_count": len(cases),
        "fingerprints": {key: sorted(values) for key, values in buckets.items()},
    }
    manifest["manifest_sha256"] = sha256_text(canonical_json(manifest))
    return manifest


def validate_exclusion_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schema_version") != EXCLUSION_SCHEMA:
        raise ValueError("training_exclusion_schema_invalid")
    fingerprints = manifest.get("fingerprints")
    if not isinstance(fingerprints, Mapping):
        raise ValueError("training_exclusion_manifest_invalid")
    for key in ("question_sha256", "group_sha256", "conversation_sha256", "doc_pair_sha256"):
        values = fingerprints.get(key)
        if not isinstance(values, list) or values != sorted(set(values)) or any(not re.fullmatch(r"[0-9a-f]{64}", str(v)) for v in values):
            raise ValueError("training_exclusion_manifest_invalid")
    expected = dict(manifest)
    actual = expected.pop("manifest_sha256", None)
    if actual != sha256_text(canonical_json(expected)):
        raise ValueError("training_exclusion_hash_mismatch")


def exclusion_collision(case: Mapping[str, Any], manifest: Mapping[str, Any]) -> list[str]:
    validate_exclusion_manifest(manifest)
    fingerprints = case_fingerprints(case)
    excluded = manifest["fingerprints"]
    return sorted(key for key, value in fingerprints.items() if value is not None and value in excluded[key])


def reject_forbidden_training_fields(value: Any, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).casefold()
            if normalized in FORBIDDEN_TRAINING_KEYS or normalized.startswith("gold_") or normalized.startswith("expected_"):
                raise ValueError(f"training_gold_projection_forbidden:{path}.{key}")
            reject_forbidden_training_fields(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_forbidden_training_fields(child, path=f"{path}[{index}]")


def validate_training_case(case: Mapping[str, Any], exclusion: Mapping[str, Any] | None = None) -> None:
    reject_forbidden_training_fields(case)
    if case.get("schema_version") != TRAINING_CASE_SCHEMA:
        raise ValueError("training_case_schema_invalid")
    for key in ("case_id", "group_id", "question", "split", "request"):
        if key not in case:
            raise ValueError("training_case_fields_invalid")
    if not all(isinstance(case.get(key), str) and case[key] for key in ("case_id", "group_id", "question")):
        raise ValueError("training_case_identity_invalid")
    if case.get("split") not in SPLITS or not isinstance(case.get("request"), Mapping):
        raise ValueError("training_case_split_invalid")
    if case["request"].get("question") != case["question"]:
        raise ValueError("training_case_question_mismatch")
    if exclusion is not None and exclusion_collision(case, exclusion):
        raise ValueError("training_case_evaluation_leakage")


def freeze_splits(cases: Sequence[Mapping[str, Any]], *, exclusion: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if not cases:
        raise ValueError("training_cases_required")
    split_rows: dict[str, list[dict[str, Any]]] = {split: [] for split in SPLITS}
    case_ids: set[str] = set()
    seen: dict[str, dict[str, str]] = {name: {} for name in ("question_sha256", "group_sha256", "conversation_sha256", "doc_pair_sha256")}
    for raw in cases:
        case = deepcopy(dict(raw))
        validate_training_case(case, exclusion)
        if case["case_id"] in case_ids:
            raise ValueError("training_duplicate_case_id")
        case_ids.add(case["case_id"])
        fingerprints = case_fingerprints(case)
        for name, value in fingerprints.items():
            if value is None:
                continue
            other = seen[name].get(value)
            if other is not None and other != case["split"]:
                raise ValueError("training_split_leakage")
            seen[name][value] = case["split"]
        split_rows[case["split"]].append(case)
    receipt: dict[str, Any] = {"schema_version": SPLIT_SCHEMA, "splits": {}, "total_cases": len(cases)}
    for split in SPLITS:
        rows = split_rows[split]
        receipt["splits"][split] = {
            "count": len(rows),
            "dataset_sha256": sha256_text(canonical_json(rows)),
            "sequence_sha256": sha256_text(canonical_json([row["case_id"] for row in rows])),
        }
    receipt["combined_sha256"] = sha256_text(canonical_json(receipt))
    return {"receipt": receipt, "cases": split_rows}


def sft_examples_from_trajectory(result: Mapping[str, Any], case: Mapping[str, Any]) -> list[dict[str, Any]]:
    validate_training_case(case)
    if case["split"] not in {"train", "dev"}:
        raise ValueError("training_sealed_holdout_export_forbidden")
    trajectory = result.get("trajectory")
    actions = result.get("actions")
    if not isinstance(trajectory, list) or not isinstance(actions, list):
        raise ValueError("training_trajectory_required")
    by_ordinal = {row.get("ordinal"): row for row in actions if isinstance(row, Mapping) and isinstance(row.get("ordinal"), int)}
    outputs: list[dict[str, Any]] = []
    for row in trajectory:
        if not isinstance(row, Mapping) or row.get("kind") != "policy" or row.get("outcome") != "completed":
            continue
        attempt = row.get("attempt")
        event = by_ordinal.get(attempt)
        if not isinstance(event, Mapping) or event.get("outcome") != "completed" or not isinstance(event.get("tool"), str):
            continue
        messages = deepcopy(row.get("messages"))
        if not isinstance(messages, list) or len(messages) != 2:
            raise ValueError("training_policy_messages_invalid")
        reject_forbidden_training_fields(messages)
        action = {"tool": event["tool"], "arguments": deepcopy(event.get("arguments"))}
        canonical_action = canonical_json(action)
        action_from_json(canonical_action)
        item = {
            "schema_version": SFT_SCHEMA,
            "prompt": messages,
            "completion": [{"role": "assistant", "content": canonical_action}],
            "metadata": {"case_id": case["case_id"], "group_id": case["group_id"],
                         "split": case["split"], "step": attempt},
        }
        reject_forbidden_training_fields(item)
        outputs.append(item)
    if not outputs:
        raise ValueError("training_no_positive_actions")
    trajectory_identity = {
        "case_id": case["case_id"],
        "request_sha256": sha256_text(canonical_json(case["request"])),
        "actions": [item["completion"][0]["content"] for item in outputs],
    }
    trajectory_id = sha256_text(canonical_json(trajectory_identity))
    for item in outputs:
        item["metadata"]["trajectory_id"] = trajectory_id
    return outputs


def reward_episode(*, success: bool, citation_success: bool, valid_abstention: bool,
                   invalid_actions: int = 0, duplicates: int = 0, scope_violations: int = 0,
                   unsupported_claims: int = 0, timeout: bool = False, budget_exhausted: bool = False,
                   policy_calls: int = 0, search_calls: int = 0, read_calls: int = 0,
                   image_calls: int = 0, total_tokens: int = 0) -> dict[str, Any]:
    if type(success) is not bool or type(citation_success) is not bool or type(valid_abstention) is not bool:
        raise ValueError("reward_external_gate_required")
    counts = (invalid_actions, duplicates, scope_violations, unsupported_claims,
              policy_calls, search_calls, read_calls, image_calls, total_tokens)
    if any(type(value) is not int or value < 0 for value in counts):
        raise ValueError("reward_count_invalid")
    components = {
        "success": 1.0 if success else 0.0,
        "citation": 0.2 if success and citation_success else 0.0,
        "valid_abstention": 0.2 if success and valid_abstention else 0.0,
        "invalid_action": -0.15 * invalid_actions,
        "duplicate": -0.05 * duplicates,
        "scope_violation": -0.5 * scope_violations,
        "unsupported_claim": -0.5 * unsupported_claims,
        "timeout": -0.5 if timeout else 0.0,
        "budget_exhausted": -0.3 if budget_exhausted else 0.0,
        "efficiency": 0.0,
    }
    if success:
        cost = policy_calls + search_calls + read_calls + 2 * image_calls + total_tokens / 4096.0
        components["efficiency"] = max(0.0, 0.25 - 0.01 * cost)
    return {"schema_version": REWARD_SCHEMA, "success_gate": success,
            "components": components, "total": float(sum(components.values()))}


def training_environment_preflight(*, mode: str | None = None) -> dict[str, Any]:
    if mode not in {None, "lora", "qlora4"}:
        raise ValueError("sft_mode_invalid")
    versions: dict[str, str | None] = {}
    reasons: list[str] = []
    distributions = TRAINING_DISTRIBUTIONS + (QLORA_DISTRIBUTIONS if mode == "qlora4" else ())
    for name in distributions:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
            reasons.append(f"missing:{name}")
    transformers = versions.get("transformers")
    if transformers is not None and _version_tuple(transformers) < MIN_TRANSFORMERS:
        reasons.append("transformers_lt_5_2")
    requirements = {"transformers": ">=5.2.0", "trl": "required", "peft": "required",
                    "datasets": "required", "accelerate": "required", "torch": "required"}
    if mode == "qlora4":
        requirements["bitsandbytes"] = "required_for_qlora4"
    return {"schema_version": "evo-training-environment-preflight-v1", "mode": mode,
            "compatible": not reasons, "versions": versions,
            "platform": {"system": platform.system(), "machine": platform.machine(), "python": platform.python_version()},
            "requirements": requirements, "reasons": reasons}


def training_backend_blockers(*, mode: str, environment: Mapping[str, Any], receipt: Mapping[str, Any] | None) -> list[str]:
    if mode == "lora":
        return []
    if mode != "qlora4":
        return ["sft_mode_invalid"]
    if receipt is None:
        return ["qlora_backend_receipt_missing"]
    required = {"schema_version", "mode", "probe", "available", "versions", "platform", "device"}
    if not required.issubset(receipt) or receipt.get("schema_version") != BACKEND_RECEIPT_SCHEMA or receipt.get("mode") != "qlora4" or receipt.get("probe") != "linear4bit_nf4_forward":
        return ["qlora_backend_receipt_invalid"]
    versions = receipt.get("versions"); env_versions = environment.get("versions")
    if not isinstance(versions, Mapping) or not isinstance(env_versions, Mapping):
        return ["qlora_backend_receipt_invalid"]
    if any(versions.get(name) != env_versions.get(name) for name in ("torch", "bitsandbytes")) or receipt.get("platform") != environment.get("platform"):
        return ["qlora_backend_receipt_environment_mismatch"]
    if receipt.get("available") is not True:
        return ["qlora_backend_unavailable"]
    return []

def freeze_sft_examples(sources: Sequence[tuple[str, Sequence[Mapping[str, Any]]]], *, exclusion: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if not sources:
        raise ValueError("training_sft_sources_required")
    if exclusion is not None:
        validate_exclusion_manifest(exclusion)
    rows=[]; seen=set(); duplicates=0; input_rows=0; source_receipts=[]
    for source_id, source_rows in sources:
        if not isinstance(source_id,str) or not source_id:
            raise ValueError("training_sft_source_id_invalid")
        count=0
        for raw in source_rows:
            row=deepcopy(dict(raw)); reject_forbidden_training_fields(row)
            if row.get("schema_version")!=SFT_SCHEMA or row.get("metadata",{}).get("split")!="train":
                raise ValueError("training_sft_train_only")
            prompt=row.get("prompt"); meta=row.get("metadata",{}); observation=None
            if not isinstance(prompt,list) or not isinstance(meta,Mapping):
                raise ValueError("training_sft_schema_invalid")
            for message in reversed(prompt):
                if isinstance(message,Mapping) and message.get("role")=="user" and isinstance(message.get("content"),str):
                    try: value=json.loads(message["content"])
                    except json.JSONDecodeError: continue
                    if isinstance(value,Mapping) and isinstance(value.get("question"),str): observation=value; break
            if observation is None:
                raise ValueError("training_sft_question_missing")
            scope=observation.get("scope_doc_ids") or []
            case={"schema_version":TRAINING_CASE_SCHEMA,"case_id":meta.get("case_id"),"group_id":meta.get("group_id"),"task_type":"multi_doc_compare" if len(scope)==2 else "single_doc","split":"train","question":observation["question"],"request":{"question":observation["question"],"document_scope":{"mode":"explicit","doc_ids":scope}}}
            if exclusion is not None and exclusion_collision(case,exclusion):
                raise ValueError("training_sft_evaluation_leakage")
            count+=1; input_rows+=1; encoded=canonical_json(row)
            if encoded in seen: duplicates+=1; continue
            seen.add(encoded); rows.append(row)
        source_receipts.append({"source_id":source_id,"input_rows":count})
    if not rows: raise ValueError("training_sft_rows_required")
    output_text=''.join(canonical_json(row)+'\n' for row in rows)
    receipt={"schema_version":SFT_FREEZE_SCHEMA,"sources":source_receipts,"input_rows":input_rows,"train_rows":len(rows),"exact_duplicate_rows_removed":duplicates,"unique_trajectory_ids":len({r["metadata"]["trajectory_id"] for r in rows}),"output_sha256":sha256_text(output_text),"mini131_used_for_selection":False,"sealed_holdout_executed":False}
    return {"rows":rows,"receipt":receipt}

def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("training_jsonl_object_required")
                rows.append(value)
    return rows


def write_jsonl_new(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        for row in rows:
            stream.write(canonical_json(dict(row)) + "\n")
    path.chmod(0o600)
