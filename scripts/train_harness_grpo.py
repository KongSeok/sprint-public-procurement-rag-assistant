#!/usr/bin/env python3
"""Preflight the bounded Evo policy GRPO stage without changing the serving env.

Actual rollout code is intentionally gated until EVO35.4, because the serving policy uses
one JSON action per turn while TRL environment_factory trains native tool calls. A compatible
custom JSON-action rollout adapter must be frozen before GRPO can execute.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
from midprojectrag.evo_harness.training import training_environment_preflight
from midprojectrag.ingest.common import canonical_json, sha256_file


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",type=Path,required=True);parser.add_argument("--preflight",action="store_true")
    parser.add_argument("--execute",action="store_true")
    args=parser.parse_args(argv);config=json.loads(args.config.read_text(encoding="utf-8"))
    if not isinstance(config,dict) or config.get("schema_version")!="evo-grpo-config-v1" or config.get("model_id")!="Qwen/Qwen3.5-9B": raise ValueError("grpo_config_invalid")
    env=training_environment_preflight();blockers=list(env["reasons"])
    if not isinstance(config.get("base_model_revision"),str) or len(config["base_model_revision"]) not in (40,64): blockers.append("base_model_revision_unfrozen")
    limits=config.get("resource_limits",{})
    if not isinstance(limits.get("max_wall_seconds"),int) or limits.get("max_wall_seconds",0)<=0: blockers.append("wall_budget_unfrozen")
    if not isinstance(limits.get("max_output_gb"),(int,float)) or limits.get("max_output_gb",0)<=0: blockers.append("storage_budget_unfrozen")
    if config.get("rollout_wire")!="custom_json_action_v1": blockers.append("grpo_rollout_wire_invalid")
    # This is a real implementation gate, not a missing-package disguise. EVO35.4 must
    # provide and test a rollout adapter that preserves the runtime JSON action semantics.
    if not config.get("rollout_adapter_frozen",False): blockers.append("grpo_rollout_adapter_not_frozen")
    receipt={"schema_version":"evo-grpo-preflight-v1","config_sha256":sha256_file(args.config),"environment":env,"blockers":sorted(set(blockers)),"ready":not blockers}
    print(canonical_json(receipt))
    if args.execute:
        if blockers: raise RuntimeError("grpo_preflight_blocked:"+",".join(sorted(set(blockers))))
        raise RuntimeError("grpo_execution_reserved_for_evo35_4")
    return 0 if not blockers else 2

if __name__=="__main__": raise SystemExit(main())
