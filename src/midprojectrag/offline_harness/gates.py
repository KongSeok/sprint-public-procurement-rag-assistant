"""Read-only artifact readiness. Hash presence never implies review approval."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path


ROLES = ("evidence_bundle", "dense_checkpoint_manifest", "dense_index_manifest", "reranker_manifest",
         "visual_checkpoint_manifest", "policy_checkpoint_manifest", "approved_gold_receipt", "heldout_seal", "training_split_manifest")
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def inspect_artifacts(manifest: dict, *, base_dir: Path) -> dict:
    """Manifest paths are read-only. No torch/pickle/import, download or service start.

    A checkpoint directory must supply a manifest file, never an arbitrary executable.
    This checks the declared manifest file hash; internal checkpoint weights still need
    provider-specific validation before activation.
    """
    if (not isinstance(manifest, dict) or set(manifest) != {"schema_version", "artifacts"}
            or manifest["schema_version"] != "evidence-harness-artifacts-v1"
            or not isinstance(manifest["artifacts"], dict) or set(manifest["artifacts"]) != set(ROLES)):
        raise ValueError("invalid_artifact_manifest")
    checks = []
    for role in ROLES:
        entry = manifest["artifacts"][role]
        status = "not_configured"
        if entry is not None:
            if (not isinstance(entry, dict) or set(entry) != {"path", "sha256"}
                    or not isinstance(entry["path"], str) or not entry["path"].strip()
                    or not isinstance(entry["sha256"], str) or not _SHA.fullmatch(entry["sha256"])):
                raise ValueError("invalid_artifact_pin")
            path = Path(entry["path"])
            path = path if path.is_absolute() else base_dir / path
            if not path.is_file():
                status = "missing"
            elif path.is_symlink() or path.stat().st_size > 64 * 1024 * 1024:
                status = "invalid_manifest_file"
            else:
                hasher = hashlib.sha256()
                with path.open("rb") as stream:
                    while chunk := stream.read(1024 * 1024):
                        hasher.update(chunk)
                status = "manifest_hash_verified" if hasher.hexdigest() == entry["sha256"] else "hash_mismatch"
        checks.append({"role": role, "status": status})
    gaps = [row["role"] for row in checks if row["status"] != "manifest_hash_verified"]
    return {"schema_version": "evidence-harness-readiness-v1", "checks": checks, "gaps": gaps,
            "artifact_manifests_present": not gaps, "approved_for_runtime": False,
            "semantic_quality": "not_measured", "training_status": "not_run",
            "promotion_requires": ["provider_specific_weight_validation", "human_gold_approval",
                                    "sealed_holdout_evaluation", "fixed_gpt56_judge", "resource_measurements", "rollback_rehearsal"]}
