"""File-backed synthetic offline E2E. No models, production data, or source edits."""
from contextlib import redirect_stdout
from copy import deepcopy
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from midprojectrag.evidence.artifacts import file_sha, freeze_bundle, write_new_json
from midprojectrag.evidence.builder import SplitConfig, build_store
from midprojectrag.retrieval import Candidate
from midprojectrag.retrieval.context import select_context
from midprojectrag.stage_checkpoints import SCHEMA, canonical_sha, final_context_checkpoint, make_checkpoint
from midprojectrag.stage_evaluation import evaluate_records, load_source_snapshot, main, resolve_checkpoint
from tests.test_evidence_builder import chunk

D1, D2 = "doc_" + "a" * 24, "doc_" + "b" * 24
B1, B2 = "block_" + "a" * 24, "block_" + "b" * 24

class StageEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.private = self.root / "private"
        self.blocks_dir = self.private / "blocks"
        self.blocks_dir.mkdir(parents=True)
        self.chunks = [chunk("private-source-sentinel " + "가" * 2100, block=B1, doc=D1),
                       chunk("second private source", block=B2, doc=D2)]
        self.blocks = [{"block_id": row["source_block_ids"][0], "doc_id": row["doc_id"],
                        "text": row["text"], "page_start": 1, "page_end": 1,
                        "content_sha256": row["content_sha256"], "source_locator": "source://" + row["doc_id"]}
                       for row in self.chunks]
        self.store = build_store(self.chunks, source_blocks=self.blocks)
        self.manifest = self.private / "manifest.jsonl"
        manifest_rows = [{"doc_id": row["doc_id"], "output_relpath": "private/blocks/" + row["doc_id"] + ".jsonl"}
                         for row in self.blocks]
        self.manifest.write_text("".join(json.dumps(row) + "\n" for row in manifest_rows))
        for block in self.blocks:
            write_new_json(self.blocks_dir / (block["doc_id"] + ".jsonl"), block)
        self.hashes = {"manifest": file_sha(self.manifest),
                       **{"blocks_" + b["doc_id"]: file_sha(self.blocks_dir / (b["doc_id"] + ".jsonl"))
                          for b in self.blocks}}
        self.bundle = self.private / "bundle"
        freeze_bundle(self.store, SplitConfig(), self.hashes, output_dir=self.bundle, data_root=self.root)
        self.snapshot = self.load_snapshot()
        self.binding = {"query_sha256": "a" * 64, "scope_sha256": "b" * 64,
                        "evidence_store_sha256": self.store.bundle_sha256,
                        "run_config_sha256": "c" * 64, "execution_key_sha256": "d" * 64}
        self.a = [e.evidence_id for e in self.store.candidates() if e.doc_id == D1]
        self.b = [e.evidence_id for e in self.store.candidates() if e.doc_id == D2]
        self.qrel = {"case_id": "c01", "suite": "core40", "qrel_status": "ready",
                     "required_anchors": [{"doc_id": b["doc_id"], "source_block_id": b["block_id"],
                                           "locator_hash": sha256(b["source_locator"].encode()).hexdigest()}
                                          for b in self.blocks]}

    def load_snapshot(self, hashes=None):
        return load_source_snapshot(data_root=self.root, manifest=self.manifest, blocks_dir=self.blocks_dir,
                                    store=self.store, input_hashes=self.hashes if hashes is None else hashes)

    def checkpoint(self, stage, ids, **kwargs):
        return make_checkpoint(stage, ids, store=self.store, binding=self.binding,
                               stage_config_sha256="e" * 64, source_receipt_sha256="f" * 64, **kwargs)

    def record(self, checkpoints=None, case_id="c01"):
        if checkpoints is None:
            candidates = tuple(Candidate(eid, self.store.get(eid).doc_id, 1.0, "fusion", rank)
                               for rank, eid in enumerate([self.b[0], self.a[0]], 1))
            context = select_context(candidates, self.store, final_k=1)
            checkpoints = [self.checkpoint("lane_dense", self.a), self.checkpoint("lane_lexical", self.b),
                           self.checkpoint("fusion", self.a + self.b),
                           final_context_checkpoint(context, store=self.store, binding=self.binding,
                                                    stage_config_sha256="1" * 64, source_receipt_sha256="2" * 64)]
        return {"schema_version": SCHEMA, "case_id": case_id, "run_id": "run-" + case_id,
                "binding": dict(self.binding), "checkpoints": checkpoints}

    def evaluate(self, qrels=None, records=None):
        return evaluate_records([self.qrel] if qrels is None else qrels,
                                [self.record()] if records is None else records,
                                store=self.store, snapshot=self.snapshot)

    def test_actual_context_selection_scores_required_not_candidate_retention(self):
        report = self.evaluate()
        metrics = report["cases"][0]["metrics"]
        self.assertEqual(metrics["pre_required_recall"]["value"], 1)
        self.assertEqual(metrics["post_required_recall"]["value"], 0.5)
        self.assertEqual(metrics["relevant_retention"]["value"], 0.5)
        self.assertEqual(metrics["lexical_rescue"]["value"], 1)
        self.assertEqual(metrics["stage_recall"]["fusion"]["1"]["value"], 0.5)
        self.assertEqual(metrics["stage_recall"]["fusion"]["3"]["value"], 1)
        self.assertEqual(metrics["stage_recall"]["rerank"]["1"]["status"], "unavailable")
        self.assertEqual(report["model_calls"], 0)
        self.assertNotIn("private-source-sentinel", json.dumps(report))
        for receipt in report["anchor_resolution_receipts"]:
            self.assertEqual(receipt["receipt_sha256"], canonical_sha({k: v for k, v in receipt.items() if k != "receipt_sha256"}))

    def test_missing_records_keep_full_131_ledger_without_fake_zero(self):
        suites = {"core40": 40, "answer56": 56, "set13": 13, "visual10": 10, "analytics10": 10, "parser2": 2}
        qrels = []
        for suite, count in suites.items():
            for index in range(count):
                qrels.append({"case_id": f"{suite}-{index}", "suite": suite,
                              "qrel_status": "not_applicable" if suite in {"visual10", "analytics10", "parser2"} else "missing",
                              "required_anchors": []})
        before = deepcopy(qrels)
        report = self.evaluate(qrels=qrels, records=[])
        self.assertEqual(report["case_count"], 131)
        self.assertEqual(report["suite_counts"], suites)
        metric = report["aggregate"]["pre_required_recall"]
        self.assertEqual((metric["available"], metric["unavailable"], metric["not_applicable"]), (0, 109, 22))
        self.assertIsNone(metric["macro_mean"])
        self.assertEqual(qrels, before)
        full = evaluate_records(qrels, [], store=self.store, snapshot=self.snapshot, inventory_mode="mini131")
        self.assertTrue(full["inventory"]["complete"])
        with self.assertRaisesRegex(ValueError, "inventory_incomplete"):
            evaluate_records(qrels[:-1], [], store=self.store, snapshot=self.snapshot, inventory_mode="mini131")
        self.assertFalse(self.evaluate()["inventory"]["complete"])

    def test_empty_search_zero_is_not_unavailable(self):
        record = self.record([self.checkpoint("fusion", [])])
        scores = self.evaluate(records=[record])["cases"][0]["metrics"]
        self.assertEqual((scores["pre_required_recall"]["status"], scores["pre_required_recall"]["value"]), ("available", 0))
        self.assertIsNone(scores["post_required_recall"]["value"])

    def test_unresolved_gold_and_retrieved_anchor_are_not_silent_misses(self):
        qrel = deepcopy(self.qrel)
        qrel["required_anchors"][0]["locator_hash"] = "0" * 64
        report = self.evaluate(qrels=[qrel])
        self.assertEqual(report["cases"][0]["qrel_issue"], "qrel_source_anchor_unresolved")
        self.assertIsNone(report["cases"][0]["metrics"]["pre_required_recall"]["value"])
        from midprojectrag.stage_evaluation import SourceSnapshot
        partial = SourceSnapshot(self.snapshot.snapshot_sha256, self.snapshot.manifest_sha256, {}, {})
        stage, receipts = resolve_checkpoint(self.checkpoint("fusion", self.a), store=self.store,
                                             snapshot=partial, binding=self.binding)
        self.assertEqual(stage.status, "unavailable")
        self.assertTrue(all(r["status"] == "missing" for r in receipts))

    def test_chunk_change_keeps_canonical_source_anchor_join(self):
        changed = build_store(self.chunks, SplitConfig(max_chars=800), source_blocks=self.blocks)
        self.assertNotEqual(changed.bundle_sha256, self.store.bundle_sha256)
        changed_binding = self.binding | {"evidence_store_sha256": changed.bundle_sha256}
        ids = [e.evidence_id for e in changed.candidates()]
        cp = make_checkpoint("fusion", ids, store=changed, binding=changed_binding,
                             stage_config_sha256="e" * 64, source_receipt_sha256="f" * 64)
        resolved, receipts = resolve_checkpoint(cp, store=changed, snapshot=self.snapshot, binding=changed_binding)
        gold = frozenset((r["doc_id"], r["source_block_id"], r["locator_hash"]) for r in self.qrel["required_anchors"])
        self.assertEqual(frozenset().union(*resolved.rows), gold)
        self.assertEqual({r["source_snapshot_sha256"] for r in receipts}, {self.snapshot.snapshot_sha256})

    def test_no_mixed_chain_configs_duplicate_stages_or_unknown_cases(self):
        run = self.record()
        for field in ("query_sha256", "scope_sha256", "execution_key_sha256", "run_config_sha256"):
            modified = deepcopy(run)
            cp = modified["checkpoints"][0]
            cp["binding"][field] = "9" * 64
            cp["projection_sha256"] = canonical_sha({k: v for k, v in cp.items() if k != "projection_sha256"})
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.evaluate(records=[modified])
        with self.assertRaises(ValueError):
            self.evaluate(records=[self.record(run["checkpoints"] * 2)])
        with self.assertRaises(ValueError):
            self.evaluate(records=[run, run])
        with self.assertRaises(ValueError):
            self.evaluate(records=[self.record(case_id="unknown")])
        second = self.record([], case_id="c02")
        second["binding"]["run_config_sha256"] = "9" * 64
        with self.assertRaises(ValueError):
            self.evaluate(qrels=[self.qrel, self.qrel | {"case_id": "c02"}], records=[run, second])

    def test_sealed_source_hash_owner_duplicate_and_locator_validation(self):
        path = self.blocks_dir / (D1 + ".jsonl")
        original = path.read_bytes()
        for update, expected in (({"doc_id": "wrong-doc"}, "owner"), ({"source_locator": ""}, "locator")):
            path.write_text(json.dumps(self.blocks[0] | update) + "\n")
            hashes = self.hashes | {"blocks_" + D1: file_sha(path)}
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                self.load_snapshot(hashes)
        path.write_bytes(original + original)
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.load_snapshot(self.hashes | {"blocks_" + D1: file_sha(path)})
        path.write_bytes(original + b"\n")
        with self.assertRaisesRegex(ValueError, "file_mismatch"):
            self.load_snapshot()

    def test_sidecar_closed_no_new_questions_or_runtime_gold(self):
        for qrel in (self.qrel | {"question": "private-question"},
                     self.qrel | {"qrel_status": "ready", "required_anchors": []},
                     self.qrel | {"suite": "visual10"},
                     self.qrel | {"suite": "visual"},
                     self.qrel | {"suite": "corpus_analytics"}):
            with self.assertRaises(ValueError):
                self.evaluate(qrels=[qrel])
        run = self.record()
        run["gold"] = self.qrel
        with self.assertRaises(ValueError):
            self.evaluate(records=[run])

    def test_cli_real_files_append_only_private_output_and_sanitized_stdout(self):
        qrels = self.private / "qrels.jsonl"
        records = self.private / "records.jsonl"
        output = self.private / "score.json"
        write_new_json(qrels, self.qrel)
        write_new_json(records, self.record())
        input_before = {str(p): file_sha(p) for p in (qrels, records, self.manifest)}
        args = ["--inventory-mode", "partial", "--data-root", str(self.root), "--bundle", str(self.bundle), "--manifest", str(self.manifest),
                "--blocks-dir", str(self.blocks_dir), "--qrels", str(qrels), "--records", str(records), "--output", str(output)]
        stdout = StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(main(args), 0)
        report = json.loads(output.read_text())
        self.assertEqual(report["aggregate"]["relevant_retention"]["macro_mean"], 0.5)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("private-source-sentinel", stdout.getvalue())
        self.assertNotIn("c01", stdout.getvalue())
        before = file_sha(output)
        with redirect_stdout(StringIO()):
            self.assertEqual(main(args), 2)
            self.assertEqual(main(args[:-1] + [str(self.root / "outside-private.json")]), 2)
            self.assertEqual(main(args[2:-1] + [str(self.private / "incomplete-mini131.json")]), 2)
        self.assertEqual(before, file_sha(output))
        self.assertEqual(input_before, {str(p): file_sha(p) for p in (qrels, records, self.manifest)})


if __name__ == "__main__":
    unittest.main()
