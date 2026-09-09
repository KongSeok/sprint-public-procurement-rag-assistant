#!/usr/bin/env python3
"""Train a next-action Qwen policy adapter in an isolated HF/TRL environment."""
from __future__ import annotations
import argparse, inspect, json, os, time
from pathlib import Path

from midprojectrag.evo_harness.training import read_jsonl, training_environment_preflight
from midprojectrag.ingest.common import canonical_json, sha256_file


def _config(path: Path):
    value=json.loads(path.read_text(encoding="utf-8"))
    required={"schema_version","model_id","base_model_revision","mode","lora","training","resource_limits"}
    if not isinstance(value,dict) or set(value)!=required or value["schema_version"]!="evo-sft-config-v1" or value["model_id"]!="Qwen/Qwen3.5-9B":
        raise ValueError("sft_config_invalid")
    return value


def _blockers(config, env):
    reasons=list(env["reasons"])
    if not isinstance(config["base_model_revision"],str) or len(config["base_model_revision"]) not in (40,64): reasons.append("base_model_revision_unfrozen")
    limits=config["resource_limits"]
    if not isinstance(limits,dict) or not isinstance(limits.get("max_wall_seconds"),int) or limits.get("max_wall_seconds",0)<=0: reasons.append("wall_budget_unfrozen")
    if not isinstance(limits,dict) or not isinstance(limits.get("max_output_gb"),(int,float)) or limits.get("max_output_gb",0)<=0: reasons.append("storage_budget_unfrozen")
    return sorted(set(reasons))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",type=Path,required=True);parser.add_argument("--train-data",type=Path)
    parser.add_argument("--dev-data",type=Path);parser.add_argument("--model-path",type=Path);parser.add_argument("--output-dir",type=Path)
    parser.add_argument("--preflight",action="store_true")
    args=parser.parse_args(argv);config=_config(args.config);env=training_environment_preflight();reasons=_blockers(config,env)
    receipt={"schema_version":"evo-sft-preflight-v1","environment":env,"config_sha256":sha256_file(args.config),"blockers":reasons,"ready":not reasons}
    if args.preflight:
        print(canonical_json(receipt));return 0 if not reasons else 2
    if reasons: raise RuntimeError("isolated_training_environment_required:"+",".join(reasons))
    if None in (args.train_data,args.model_path,args.output_dir): parser.error("training requires --train-data --model-path --output-dir")
    model_path=args.model_path.resolve(strict=True);output=args.output_dir.resolve()
    if output.exists(): raise FileExistsError("training_output_exists")
    train_rows=read_jsonl(args.train_data);dev_rows=read_jsonl(args.dev_data) if args.dev_data else []
    if not train_rows or any(row.get("schema_version")!="evo-policy-sft-v1" or row.get("metadata",{}).get("split")!="train" for row in train_rows): raise ValueError("sft_train_data_invalid")
    if any(row.get("schema_version")!="evo-policy-sft-v1" or row.get("metadata",{}).get("split")!="dev" for row in dev_rows): raise ValueError("sft_dev_data_invalid")

    # Imports occur only after the isolated-environment and resource gates pass.
    import torch
    from datasets import Dataset
    from peft import LoraConfig, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from trl import SFTConfig, SFTTrainer

    tokenizer=AutoTokenizer.from_pretrained(str(model_path),local_files_only=True,trust_remote_code=False)
    if tokenizer.pad_token is None: tokenizer.pad_token=tokenizer.eos_token
    def render(row):
        prompt=tokenizer.apply_chat_template(row["prompt"],tokenize=False,add_generation_prompt=True,enable_thinking=False)
        completion=row["completion"][0]["content"] + (tokenizer.eos_token or "")
        return {"prompt":prompt,"completion":completion,"trajectory_id":row["metadata"]["trajectory_id"]}
    train=Dataset.from_list([render(row) for row in train_rows]);dev=Dataset.from_list([render(row) for row in dev_rows]) if dev_rows else None
    lora=config["lora"];lora_config=LoraConfig(r=lora["r"],lora_alpha=lora["alpha"],lora_dropout=lora["dropout"],target_modules=lora["target_modules"],bias="none",task_type="CAUSAL_LM")
    model=None
    if config["mode"]=="qlora4":
        quant=BitsAndBytesConfig(load_in_4bit=True,bnb_4bit_quant_type="nf4",bnb_4bit_use_double_quant=True,bnb_4bit_compute_dtype=torch.bfloat16)
        model=AutoModelForCausalLM.from_pretrained(str(model_path),local_files_only=True,trust_remote_code=False,quantization_config=quant,device_map="auto")
        model=prepare_model_for_kbit_training(model)
    elif config["mode"]!="lora": raise ValueError("sft_mode_invalid")
    tr=config["training"]
    sft_args=SFTConfig(output_dir=str(output),max_steps=tr["max_steps"],learning_rate=tr["learning_rate"],per_device_train_batch_size=tr["micro_batch_size"],gradient_accumulation_steps=tr["gradient_accumulation_steps"],max_length=tr["max_length"],completion_only_loss=True,packing=False,report_to="none",save_strategy="steps",save_steps=tr["save_steps"],logging_steps=tr["logging_steps"],seed=tr["seed"],data_seed=tr["seed"],bf16=True,gradient_checkpointing=True)
    started=time.time();trainer=SFTTrainer(model=model or str(model_path),args=sft_args,train_dataset=train,eval_dataset=dev,processing_class=tokenizer,peft_config=lora_config)
    trainer.train();trainer.save_model(str(output/"adapter"))
    output.mkdir(parents=True,exist_ok=True)
    out={**receipt,"ready":True,"completed":True,"train_rows":len(train_rows),"dev_rows":len(dev_rows),"train_data_sha256":sha256_file(args.train_data),"dev_data_sha256":sha256_file(args.dev_data) if args.dev_data else None,"model_path":str(model_path),"elapsed_seconds":time.time()-started,"trl_has_processing_class":"processing_class" in inspect.signature(SFTTrainer.__init__).parameters}
    (output/"training-receipt.json").write_text(canonical_json(out)+"\n",encoding="utf-8")
    print(canonical_json({"status":"completed","output":str(output),"train_rows":len(train_rows)}));return 0

if __name__=="__main__": raise SystemExit(main())
