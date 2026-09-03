"""Replay saved answers without importing, constructing, or calling a generator."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping, Sequence

from .scoring import SCORER_VERSION, score_answer
from . import scoring


def _identity(row: Mapping) -> str:
    value = row.get("case_id", row.get("id"))
    if not isinstance(value, str) or not value:
        raise ValueError("missing_case_identity")
    return value


def _read(path: Path) -> tuple[list[dict], str]:
    data = path.read_bytes()
    rows = [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("invalid_record")
    return rows, sha256(data).hexdigest()


def answer_from_record(row: Mapping) -> tuple[str, str | None]:
    if isinstance(row.get("run"), Mapping):
        row = row["run"]
    if isinstance(row.get("response"), Mapping):
        row = row["response"]
    elif isinstance(row.get("candidate"), Mapping):
        row = row["candidate"]
    answer = row.get("answer")
    if not isinstance(answer, str):
        raise ValueError("missing_saved_answer")
    status = row.get("status")
    if status is not None and not isinstance(status, str):
        raise ValueError("invalid_saved_status")
    return answer, status


def facts_from_case(row: Mapping | None) -> list:
    if row is None:
        return []
    case = row.get("case", row)
    if not isinstance(case, Mapping):
        raise ValueError("invalid_case")
    gold = case.get("gold", case.get("expected", case))
    if not isinstance(gold, Mapping):
        return []
    if isinstance(gold.get("gold"), Mapping):
        gold = gold["gold"]  # Mini131 expected.gold, never candidate.companion.
    for key in ("required_fact_groups", "required_key_points", "required_facts", "fact_groups"):
        values = gold.get(key)
        if values is not None:
            if not isinstance(values, (list, tuple)):
                raise ValueError("invalid_fact_groups")
            result = []
            for value in values:
                if isinstance(value, str):
                    result.append([value])
                elif isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value):
                    result.append(list(value))
                elif isinstance(value, Mapping) and isinstance(value.get("alternatives"), (list, tuple)):
                    result.append(list(value["alternatives"]))
                elif isinstance(value, Mapping) and set(value) == {"point_id", "text"} and isinstance(value["text"], str):
                    result.append([value["text"]])
                else:
                    raise ValueError("unsupported_fact_group_shape")
            return result
    return []  # A reference paragraph is not silently substituted for atomic facts.


def replay_saved_answers(input_path: Path, output_dir: Path, *, data_root: Path,
                         case_paths: Sequence[Path] = ()) -> dict:
    root = data_root.resolve()
    output = output_dir.resolve()
    if output == root / "private" or not output.is_relative_to(root / "private"):
        raise ValueError("output_must_be_new_private_directory")
    if output.exists():
        raise FileExistsError("replay_output_already_exists")
    records, input_hash = _read(input_path)
    cases = {}
    case_hashes = {}
    for path in case_paths:
        rows, digest = _read(path)
        case_hashes[str(path)] = digest
        for row in rows:
            identity = _identity(row)
            if identity in cases:
                raise ValueError("duplicate_case_identity")
            cases[identity] = row
    seen = set()
    result = []
    for record in records:
        identity = _identity(record)
        if identity in seen:
            raise ValueError("duplicate_saved_identity")
        seen.add(identity)
        answer, status = answer_from_record(record)
        case = cases.get(identity)
        if case is None and ("gold" in record or "expected" in record or "case" in record):
            case = record
        source_hash_verified = False
        if case is not None and "source_case_sha256" in record:
            source_hash = sha256(json.dumps(case, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            if record["source_case_sha256"] != source_hash:
                raise ValueError("case_source_hash_mismatch")
            source_hash_verified = True
        facts = facts_from_case(case)
        score = score_answer(answer, facts, status=status)
        result.append({"case_id": identity, "answer_sha256": sha256(answer.encode()).hexdigest(),
                       "case_joined": case is not None, "source_case_hash_verified": source_hash_verified,
                       "facts_available": bool(facts), "score": score.to_dict()})
    receipt = {
        "schema_version": "bidfit-offline-replay.v1", "scorer_version": SCORER_VERSION,
        "scorer_code_sha256": sha256(Path(scoring.__file__).read_bytes()).hexdigest(),
        "created_at": datetime.now(timezone.utc).isoformat(), "input_sha256": input_hash,
        "case_file_sha256": case_hashes, "row_count": len(result),
        "case_joined_count": sum(r["case_joined"] for r in result),
        "source_case_hash_verified_count": sum(r["source_case_hash_verified"] for r in result),
        "scorable_count": sum(r["facts_available"] for r in result),
        "unscorable_count": sum(not r["facts_available"] for r in result),
        "generator_calls": 0, "source_answers_modified": False,
        "comparison_kind": "stored_answers_new_deterministic_scorer_only",
        "performance_improvement_claim": False,
    }
    # Check once more immediately before publication. Never overwrite old answers.
    if sha256(input_path.read_bytes()).hexdigest() != input_hash:
        raise ValueError("input_changed_during_replay")
    for path in case_paths:
        if sha256(path.read_bytes()).hexdigest() != case_hashes[str(path)]:
            raise ValueError("cases_changed_during_replay")
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    payloads = {
        "scores.jsonl": "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in result),
        "receipt.json": json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
    }
    for name, payload in payloads.items():
        path = output / name
        with path.open("x", encoding="utf-8") as handle:
            path.chmod(0o600)
            handle.write(payload)
    return receipt
