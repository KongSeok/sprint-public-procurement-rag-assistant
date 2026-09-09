from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest

from midprojectrag.evo_harness.training_inventory import build_corpus_training_inventory, build_historical_exclusion_inventory
from midprojectrag.ingest.common import canonical_json, sha256_file


class HistoricalExclusionInventoryTests(unittest.TestCase):
    def _fixture(self, root: Path):
        counts={"core40":40,"supplemental_answers":56,"supplemental_sets":13,"visual":10,"analytics":10}
        sources={}
        ordinal=0
        for name,count in counts.items():
            path=root/f"{name}.jsonl";rows=[]
            for i in range(count):
                ordinal+=1
                rows.append({"case_id":f"c{ordinal}","question":f"eval question {ordinal}",
                             "group_id":f"g{ordinal}","task_type":"single_doc",
                             "document_scope":{"mode":"explicit","doc_ids":[f"d{ordinal}"]}})
            path.write_text("".join(canonical_json(r)+"\n" for r in rows),encoding="utf-8")
            sources[name]={"path":path.name,"sha256":sha256_file(path),"count":count}
        config=root/"mini.json";config.write_text(canonical_json({"suite_id":"gcp-local-kure-qwen3-8b-awq-mini131-v1","sources":sources}),encoding="utf-8")
        extra=root/"historical.jsonl";extra.write_text(canonical_json({"question":"rewritten legacy question","original_question":"original legacy question","source_document_ids":["dx","dy"]})+"\n",encoding="utf-8")
        return config,extra

    def test_inventory_is_hash_only_and_accounts_for_mini131(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);config,extra=self._fixture(root)
            result=build_historical_exclusion_inventory(source_repo_root=root,mini131_config=config,extra_evaluation_paths=[extra])
            self.assertEqual(result["receipt"]["mini131_rag_rows"],129)
            self.assertEqual(result["receipt"]["projected_exclusion_cases"],131)
            serialized=canonical_json(result)
            self.assertNotIn("eval question",serialized)
            self.assertNotIn("legacy question",serialized)
            self.assertGreaterEqual(result["receipt"]["fingerprint_counts"]["doc_pair_sha256"],1)

    def test_configured_source_hash_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);config,_=self._fixture(root)
            value=json.loads(config.read_text());value["sources"]["core40"]["sha256"]="0"*64;config.write_text(canonical_json(value))
            with self.assertRaisesRegex(ValueError,"source_hash_mismatch"):
                build_historical_exclusion_inventory(source_repo_root=root,mini131_config=config)


class CorpusInventoryTests(unittest.TestCase):
    def test_corpus_inventory_counts_pair_space_and_exclusions(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);manifest=root/"manifest.jsonl"
            rows=[{"doc_id":"a","extension":"pdf","page_count":1,"index_eligible":True},{"doc_id":"b","extension":"pdf","page_count":2,"index_eligible":True},{"doc_id":"c","extension":"hwp","page_count":1,"index_eligible":True}]
            manifest.write_text("".join(canonical_json(r)+"\n" for r in rows))
            cfg=root/"stack.json";cfg.write_text(canonical_json({"corpus":{"manifest_path":manifest.name,"manifest_sha256":sha256_file(manifest),"document_count":3}}))
            from midprojectrag.evo_harness.training import build_exclusion_manifest
            exclusion=build_exclusion_manifest([{"question":"x","task_type":"multi_doc_compare","document_scope":{"mode":"explicit","doc_ids":["a","b"]}}],source_id="eval")
            result=build_corpus_training_inventory(source_repo_root=root,stack_config=cfg,exclusion_manifest=exclusion)
            self.assertEqual(result["receipt"]["pair_space_count"],3)
            self.assertEqual(result["receipt"]["excluded_pair_count"],1)
            self.assertEqual(result["receipt"]["available_pair_count"],2)
            self.assertEqual(len(result["documents"]),3)


if __name__=="__main__":unittest.main()
