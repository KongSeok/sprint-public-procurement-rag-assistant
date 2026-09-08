"""The selected first parent action seals one same-state revision four."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import gc
import inspect
import sys
from threading import Barrier, Event, Thread
import unittest
from weakref import ref

import midprojectrag.orchestration as orchestration
import midprojectrag.orchestration.execution_contracts as contracts
from midprojectrag.orchestration import (
    HarnessRuntimeBinding,
    build_compare_coverage,
    build_compare_harness_state,
    build_fact_harness_state,
    create_harness_execution_config,
    decide_controller_action,
    execute_retrieval_lane,
    issue_compare_retrieval_obligations,
    issue_bridge_context_receipts,
    issue_fact_retrieval_obligations,
    issue_harness_execution,
    issue_parent_context_receipts,
    validate_controller_decision_receipt,
    validate_harness_execution,
)
from midprojectrag.retrieval.fusion import HybridChildRetriever
from tests.test_action_effect_receipts import (
    _NeverReranker,
    _NeverVerifier,
    _context_store,
    _never_clock,
)
import tests.test_controller_first_fusion_transition as fusion_fixtures
from tests.test_retrieval_obligations import (
    _SyntheticLane,
    _calls,
    _clone_slots,
    _compare_bound,
    _fact_bound,
    _store,
)


class ControllerFirstParentTransitionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fusion_fixtures.ControllerFirstFusionTransitionTests(
            methodName="runTest"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.case_number = 0

    def _case(self, **options):
        case = self.fixture._case(**options)
        case["third"] = self.fixture._execute(case)
        case["fourth_decision"] = decide_controller_action(
            execution=case["third"], **case["env"]
        )
        return case

    def _custom_case(
        self,
        *,
        store,
        compare=False,
        dense_mode="valid",
        lexical_mode="valid",
        max_actions=24,
        context_limit=8,
    ):
        self.case_number += 1
        root = self.fixture.fixture.fixture.root
        dense_log = root / f"parent-dense-{self.case_number}.log"
        lexical_log = root / f"parent-lexical-{self.case_number}.log"
        specs = tuple(
            (item.evidence_id, item.doc_id)
            for item in reversed(store.evidence)
            if item.kind == "text"
        )
        runtime = HarnessRuntimeBinding.for_test(
            store=store,
            retriever=HybridChildRetriever(
                store,
                _SyntheticLane(
                    lane="dense",
                    bundle_sha256=store.bundle_sha256,
                    candidate_specs=specs,
                    call_log_path=str(dense_log),
                    mode=dense_mode,
                ),
                _SyntheticLane(
                    lane="lexical",
                    bundle_sha256=store.bundle_sha256,
                    candidate_specs=specs,
                    call_log_path=str(lexical_log),
                    mode=lexical_mode,
                ),
            ),
            verifier=_NeverVerifier(),
            reranker=_NeverReranker(),
            clock=_never_clock,
        )
        config = create_harness_execution_config(
            mode="e1_bounded",
            max_nonterminal_actions=max_actions,
            max_context_targets_per_obligation=context_limit,
        )
        env = {"store": store, "config": config, "runtime": runtime}
        if compare:
            bound, registry = _compare_bound(store)
            coverage = build_compare_coverage(
                bound=bound,
                store=store,
                candidate_results={},
                verified_evidence={},
                missing_reasons={},
                contradicted_evidence={},
            )
            state = build_compare_harness_state(
                bound=bound, coverage=coverage, store=store
            )
            retrieval_issuer = issue_compare_retrieval_obligations
        else:
            bound = _fact_bound(store)
            registry = None
            state = build_fact_harness_state(bound=bound, store=store)
            retrieval_issuer = issue_fact_retrieval_obligations
        before = issue_harness_execution(state=state, **env)
        decision = decide_controller_action(execution=before, **env)
        claim = contracts._claim_controller_step(
            execution=before, decision=decision, **env
        )
        obligation = retrieval_issuer(bound=bound, **env)[0]
        dense = execute_retrieval_lane(
            obligation=obligation, lane="dense", **env
        )
        projection = contracts._prepare_controller_step_source(
            claim=claim, source_receipt=dense, **env
        )
        contracts._source_controller_step(
            claim=claim, projection=projection, **env
        )
        bridge = contracts._prepare_controller_structural_effect_bridge(
            claim=claim, projection=projection, target_context=None, **env
        )
        first = contracts._advance_initial_controller_step(
            bridge=bridge, **env
        )
        second_decision = decide_controller_action(execution=first, **env)
        second = contracts._execute_controller_lexical_step(
            execution=first, decision=second_decision, **env
        )
        third_decision = decide_controller_action(execution=second, **env)
        third = contracts._execute_controller_first_fusion_step(
            execution=second, decision=third_decision, **env
        )
        fourth_decision = decide_controller_action(execution=third, **env)
        fusion = contracts._require_controller_first_fusion_transition(
            execution=third, **env
        )[0]
        fusion_receipt = next(
            receipt
            for authority in tuple(
                dict.values(contracts._ISSUED_FUSION_RECEIPT_AUTHORITIES)
            )
            if object.__getattribute__(authority, "obligation") is obligation
            for receipt in (object.__getattribute__(authority, "weak")(),)
            if receipt is not None
        )
        return {
            "env": env,
            "before": before,
            "decision": decision,
            "claim": claim,
            "receipt": dense,
            "first": first,
            "second_decision": second_decision,
            "second": second,
            "third_decision": third_decision,
            "third": third,
            "fourth_decision": fourth_decision,
            "obligation": obligation,
            "dense": dense,
            "lexical": contracts._read_fusion_receipt_authority(
                fusion_receipt
            ).lexical_receipt,
            "fusion": fusion_receipt,
            "fusion_effect": fusion,
            "bound": bound,
            "registry": registry,
            "dense_log": dense_log,
            "lexical_log": lexical_log,
        }

    @staticmethod
    def _execute(case, *, execution=None, decision=None, env=None):
        return contracts._execute_controller_first_parent_step(
            execution=case["third"] if execution is None else execution,
            decision=(
                case["fourth_decision"] if decision is None else decision
            ),
            **(case["env"] if env is None else env),
        )

    def _sources(self, case):
        if "obligation" in case:
            return (
                case["obligation"],
                case["dense"],
                case["lexical"],
                case["fusion"],
            )
        obligation, dense, lexical = self.fixture._sources(case)
        fusion = self.fixture._fusion_sources(obligation)[0]
        return obligation, dense, lexical, fusion

    @staticmethod
    def _semantic_for(fusion):
        matches = tuple(
            obligation
            for authority in tuple(
                dict.values(contracts._ISSUED_SEMANTIC_OBLIGATION_AUTHORITIES)
            )
            if object.__getattribute__(authority, "fusion_receipt") is fusion
            for obligation in (object.__getattribute__(authority, "weak")(),)
            if obligation is not None
        )
        if len(matches) != 1:
            raise AssertionError(f"expected one semantic obligation, got {len(matches)}")
        return matches[0]

    @staticmethod
    def _closure_value(function, name):
        return dict(
            zip(function.__code__.co_freevars, function.__closure__ or ())
        )[name].cell_contents

    def _target_context(self, execution):
        require_successor = self._closure_value(
            contracts._require_controller_first_parent_transition,
            "require_successor_record",
        )
        records = self._closure_value(require_successor, "records")
        matches = tuple(
            record
            for record in tuple(records.values())
            if record[8] is not None and record[8]() is execution
        )
        self.assertEqual(len(matches), 1)
        return matches[0][0].target_context

    @staticmethod
    def _context_receipts(case, semantic):
        semantic_authority = contracts._read_semantic_obligation_authority(
            semantic
        )
        env = case["env"]
        parents = contracts._begin_context_receipt_issuance(
            object.__getattribute__(semantic_authority, "source"),
            contracts._context_issuance_key(
                "parent", semantic_authority, semantic, **env
            ),
            contracts.ParentContextReceipt,
        )
        bridges = contracts._begin_context_receipt_issuance(
            object.__getattribute__(semantic_authority, "source"),
            contracts._context_issuance_key(
                "bridge", semantic_authority, semantic, **env
            ),
            contracts.BridgeContextReceipt,
        )
        return parents, bridges

    @staticmethod
    def _call_snapshot(case):
        return (
            _calls(case["dense_log"]),
            _calls(case["lexical_log"]),
            _NeverVerifier.calls,
            _NeverReranker.calls,
        )

    def _issue_semantic(self, case):
        obligation, _dense, _lexical, fusion = self._sources(case)
        issuer = (
            contracts.issue_fact_semantic_verification_obligation
            if case["third"].source_kind == "fact"
            else contracts.issue_compare_semantic_verification_obligation
        )
        return issuer(
            obligation=obligation,
            fusion_receipt=fusion,
            **case["env"],
        )

    @staticmethod
    def _live_context_receipts(source):
        batches = []
        for visible in (
            contracts._ISSUED_PARENT_CONTEXT_RECEIPT_AUTHORITIES,
            contracts._ISSUED_BRIDGE_CONTEXT_RECEIPT_AUTHORITIES,
        ):
            receipts = tuple(
                receipt
                for authority in tuple(dict.values(visible))
                if authority is not None
                and object.__getattribute__(
                    authority, "root_source_weak"
                )()
                is source
                for receipt in (
                    object.__getattribute__(authority, "weak")(),
                )
                if receipt is not None
            )
            batches.append(receipts)
        return tuple(batches)

    @staticmethod
    def _context_batch_statuses(case, semantic):
        authority = contracts._read_semantic_obligation_authority(semantic)
        return tuple(
            contracts._context_receipt_issuance_status(
                contracts._context_issuance_key(
                    family, authority, semantic, **case["env"]
                )
            )
            for family in ("parent", "bridge")
        )

    def test_private_first_parent_executor_exists_with_closed_signature(self):
        self.assertTrue(
            hasattr(contracts, "_execute_controller_first_parent_step"),
            "the contracted first-parent executor is not implemented",
        )
        executor = contracts._execute_controller_first_parent_step
        self.assertEqual(
            tuple(inspect.signature(executor).parameters),
            ("execution", "decision", "store", "config", "runtime"),
        )
        self.assertEqual(
            tuple(
                inspect.signature(
                    contracts._require_controller_first_parent_transition
                ).parameters
            ),
            ("execution", "store", "config", "runtime"),
        )
        self.assertFalse(
            hasattr(orchestration, "execute_controller_first_parent_step")
        )
        self.assertNotIn(
            "execute_controller_first_parent_step", orchestration.__all__
        )

    def test_fact_parent_seals_exact_same_state_revision_four(self):
        case = self._case()
        zero, one, two, three = (
            case["before"],
            case["first"],
            case["second"],
            case["third"],
        )
        before_payload = three.to_dict()
        calls = self._call_snapshot(case)
        obligation, dense, lexical, fusion = self._sources(case)

        codes = {
            contracts.issue_parent_context_receipts.__code__: "parent_batch",
            contracts.issue_bridge_context_receipts.__code__: "bridge_batch",
            contracts._mint_parent_context_receipt.__code__: "parent_mint",
            contracts._mint_bridge_context_receipt.__code__: "bridge_mint",
        }
        preparation_calls = {name: 0 for name in codes.values()}

        def count_preparation(frame, event, _argument):
            frame.f_trace_lines = False
            if event == "call" and frame.f_code in codes:
                name = codes[frame.f_code]
                preparation_calls[name] += 1
            return count_preparation

        previous_trace = sys.gettrace()
        try:
            sys.settrace(count_preparation)
            four = self._execute(case)
        finally:
            sys.settrace(previous_trace)
        effect, transition = (
            contracts._require_controller_first_parent_transition(
                execution=four, **case["env"]
            )
        )
        semantic = self._semantic_for(fusion)
        parents, bridges = self._context_receipts(case, semantic)
        target_context = self._target_context(four)
        selected = tuple(
            receipt
            for receipt in parents
            if receipt.seed_evidence_id
            == case["fourth_decision"].selected_action.target_evidence_id
        )

        self.assertEqual(len(selected), 1)
        self.assertEqual(len(parents), len(semantic.candidate_evidence_ids))
        self.assertEqual(len(bridges), 2 * len(parents))
        self.assertEqual(
            preparation_calls,
            {
                "parent_batch": 1,
                "bridge_batch": 1,
                "parent_mint": len(parents),
                "bridge_mint": len(bridges),
            },
        )
        self.assertIs(target_context.obligation, semantic)
        self.assertIs(target_context.parent_receipts, parents)
        self.assertIs(target_context.bridge_receipts, bridges)
        self.assertIs(target_context.selected_receipt, selected[0])
        self.assertEqual((four.step_index, four.ledger.revision), (4, 4))
        self.assertEqual(four.ledger.nonterminal_action_count, 4)
        self.assertIs(four.state, three.state)
        self.assertIs(four.initial_state, zero.initial_state)
        self.assertEqual(three.to_dict(), before_payload)
        self.assertEqual(
            four.ledger.previous_ledger_sha256,
            three.ledger.ledger_sha256,
        )
        self.assertEqual(
            four.ledger.consumed_action_sha256s,
            three.ledger.consumed_action_sha256s
            + (case["fourth_decision"].selected_action.action_sha256,),
        )
        for name in (
            "round_indexes",
            "consumed_lane_keys",
            "unavailable_action_sha256s",
            "no_progress_streaks",
        ):
            self.assertIs(getattr(four.ledger, name), getattr(three.ledger, name))
        self.assertEqual(
            (
                effect.step_index,
                effect.action_kind,
                effect.target_evidence_id,
                effect.source_receipt_kind,
                effect.outcome,
                effect.ordered_evidence_ids,
                effect.parent_context_receipt_sha256s,
                effect.bridge_context_receipt_sha256s,
                effect.absence_confirmation_sha256,
                effect.call_performed,
            ),
            (
                4,
                "expand_parent",
                selected[0].seed_evidence_id,
                "parent_context",
                "applied",
                (),
                (selected[0].receipt_sha256,),
                (),
                None,
                True,
            ),
        )
        self.assertEqual(
            transition.previous_transition_sha256,
            three.last_transition_sha256,
        )
        self.assertEqual(
            transition.before_state_sha256, transition.after_state_sha256
        )
        self.assertEqual(
            transition.before_progress_sha256,
            transition.after_progress_sha256,
        )
        authority = contracts._require_harness_execution_authority(four)
        self.assertIs(authority[11], three)
        self.assertIs(authority[12], zero)
        for execution in (zero, one, two, three, four):
            validate_harness_execution(execution=execution, **case["env"])
        for execution, decision in (
            (zero, case["decision"]),
            (one, case["second_decision"]),
            (two, case["third_decision"]),
            (three, case["fourth_decision"]),
        ):
            validate_controller_decision_receipt(
                receipt=decision, execution=execution, **case["env"]
            )
        self.assertEqual(self._call_snapshot(case), calls)
        self.assertIs(obligation, contracts._read_fusion_receipt_authority(fusion).obligation)
        self.assertIs(dense, contracts._read_fusion_receipt_authority(fusion).dense_receipt)
        self.assertIs(lexical, contracts._read_fusion_receipt_authority(fusion).lexical_receipt)
        attempt_records = self._closure_value(
            contracts._controller_source_attempt_epoch, "receipts"
        )
        fusion_epoch = attempt_records[id(fusion)][1]
        for receipt in parents:
            attempt = attempt_records[id(receipt)]
            self.assertEqual(attempt[2:], ("parent_context", True))
            self.assertGreater(attempt[1], fusion_epoch)
        for receipt in bridges:
            with self.assertRaisesRegex(
                ValueError, "source_attempt_authority_required"
            ):
                contracts._controller_source_attempt_epoch(receipt)
        self.assertTrue(all(item.outcome == "empty" for item in bridges))
        for old_reader in (
            contracts._require_controller_initial_transition,
            contracts._require_controller_lexical_transition,
            contracts._require_controller_first_fusion_transition,
        ):
            with self.assertRaises((TypeError, ValueError)):
                old_reader(execution=four, **case["env"])
        with self.assertRaises((TypeError, ValueError)):
            contracts._require_controller_first_parent_transition(
                execution=three, **case["env"]
            )
        with self.assertRaises((TypeError, ValueError)):
            decide_controller_action(execution=four, **case["env"])

        semantic_weak = ref(semantic)
        context_weak = ref(target_context)
        selected_weak = ref(selected[0])
        del semantic, parents, bridges, target_context, selected
        gc.collect()
        self.assertIsNotNone(semantic_weak())
        self.assertIsNotNone(context_weak())
        self.assertIsNotNone(selected_weak())
        with self.assertRaises((TypeError, ValueError)):
            self._execute(case)
        self.assertEqual(self._call_snapshot(case), calls)

    def test_fact_compare_and_lane_variants_preserve_original_first_source(self):
        variants = (
            (True, "valid", "valid"),
            (False, "valid", "empty"),
            (False, "empty", "valid"),
        )
        for compare, dense_mode, lexical_mode in variants:
            with self.subTest(
                compare=compare,
                dense=dense_mode,
                lexical=lexical_mode,
            ):
                case = self._case(
                    compare=compare,
                    mode=dense_mode,
                    lexical_mode=lexical_mode,
                )
                calls = self._call_snapshot(case)
                obligation, dense, lexical, fusion = self._sources(case)
                before_state = case["third"].state

                four = self._execute(case)
                effect, _transition = (
                    contracts._require_controller_first_parent_transition(
                        execution=four, **case["env"]
                    )
                )
                semantic = self._semantic_for(fusion)
                semantic_authority = (
                    contracts._read_semantic_obligation_authority(semantic)
                )
                retrieval_authority = (
                    contracts._require_retrieval_obligation_authority(
                        obligation
                    )
                )
                target_context = self._target_context(four)
                parents, bridges = self._context_receipts(case, semantic)
                bounded = contracts._context_seed_evidence_ids(
                    semantic, semantic_authority, case["env"]["config"]
                )

                self.assertEqual(semantic.source_kind, four.source_kind)
                self.assertIs(
                    semantic_authority.source,
                    retrieval_authority.source,
                )
                self.assertIs(
                    semantic_authority.retrieval_obligation, obligation
                )
                self.assertIs(semantic_authority.fusion_receipt, fusion)
                self.assertIs(semantic_authority.dense_receipt, dense)
                self.assertIs(semantic_authority.lexical_receipt, lexical)
                self.assertEqual(
                    semantic_authority.raw_query,
                    retrieval_authority.raw_query,
                )
                self.assertEqual(
                    semantic.query_sha256, obligation.query_sha256
                )
                self.assertEqual(
                    semantic.owner_binding_sha256,
                    obligation.execution_binding_sha256,
                )
                self.assertNotEqual(
                    semantic.owner_binding_sha256,
                    retrieval_authority.source.binding_sha256,
                )
                self.assertEqual(
                    semantic.candidate_evidence_ids,
                    fusion.ordered_evidence_ids,
                )
                self.assertEqual(
                    case["fourth_decision"].selected_action.target_evidence_id,
                    bounded[0],
                )
                self.assertEqual(
                    tuple(item.seed_evidence_id for item in parents), bounded
                )
                self.assertEqual(len(bridges), 2 * len(bounded))
                self.assertIs(
                    target_context.selected_receipt,
                    next(
                        item
                        for item in parents
                        if item.seed_evidence_id == bounded[0]
                    ),
                )
                self.assertIs(four.state, before_state)
                self.assertEqual(
                    effect.parent_context_receipt_sha256s,
                    (target_context.selected_receipt.receipt_sha256,),
                )
                self.assertEqual(effect.bridge_context_receipt_sha256s, ())
                self.assertEqual(effect.ordered_evidence_ids, ())
                if dense_mode == lexical_mode == "valid":
                    self.assertEqual(
                        fusion.both_evidence_ids,
                        fusion.ordered_evidence_ids,
                    )
                elif dense_mode == "valid":
                    self.assertEqual(
                        fusion.dense_only_evidence_ids,
                        fusion.ordered_evidence_ids,
                    )
                    self.assertEqual(lexical.ordered_evidence_ids, ())
                else:
                    self.assertEqual(
                        fusion.lexical_only_evidence_ids,
                        fusion.ordered_evidence_ids,
                    )
                    self.assertEqual(dense.ordered_evidence_ids, ())
                if compare:
                    self.assertEqual(retrieval_authority.projection_ordinal, 1)
                    self.assertGreater(len(four.ledger.obligation_keys), 1)
                    self.assertEqual(
                        four.ledger.round_indexes[1:],
                        (0,) * (len(four.ledger.obligation_keys) - 1),
                    )
                self.assertEqual(self._call_snapshot(case), calls)

    def test_complete_linked_batches_and_bounded_prefix_are_retained(self):
        linked_case = self._custom_case(
            store=_context_store(), context_limit=8
        )
        linked_calls = self._call_snapshot(linked_case)
        linked_four = self._execute(linked_case)
        _obligation, _dense, _lexical, fusion = self._sources(linked_case)
        semantic = self._semantic_for(fusion)
        semantic_authority = contracts._read_semantic_obligation_authority(
            semantic
        )
        expected_seeds = contracts._context_seed_evidence_ids(
            semantic,
            semantic_authority,
            linked_case["env"]["config"],
        )
        parents, bridges = self._context_receipts(linked_case, semantic)
        context = self._target_context(linked_four)
        effect, _transition = (
            contracts._require_controller_first_parent_transition(
                execution=linked_four, **linked_case["env"]
            )
        )

        self.assertEqual(
            tuple(item.seed_evidence_id for item in parents), expected_seeds
        )
        self.assertEqual(
            tuple((item.bridge_kind, item.seed_evidence_id) for item in bridges),
            tuple(("table", seed) for seed in expected_seeds)
            + tuple(("figure", seed) for seed in expected_seeds),
        )
        for receipt in bridges:
            expected_kind = {
                "table": "table_row_group",
                "figure": "figure_object",
            }[receipt.bridge_kind]
            expected_linked = linked_case["env"]["store"].bridge(
                receipt.seed_evidence_id, kinds=(expected_kind,)
            )
            self.assertEqual(
                receipt.linked_evidence_ids,
                tuple(item.evidence_id for item in expected_linked),
            )
            self.assertEqual(
                receipt.outcome,
                "applied" if expected_linked else "empty",
            )
        self.assertEqual(
            {(item.bridge_kind, item.outcome) for item in bridges},
            {
                ("table", "applied"),
                ("table", "empty"),
                ("figure", "applied"),
                ("figure", "empty"),
            },
        )
        self.assertIs(context.parent_receipts, parents)
        self.assertIs(context.bridge_receipts, bridges)
        self.assertEqual(
            effect.parent_context_receipt_sha256s,
            (context.selected_receipt.receipt_sha256,),
        )
        self.assertEqual(effect.bridge_context_receipt_sha256s, ())
        self.assertEqual(self._call_snapshot(linked_case), linked_calls)

        bounded_cases = (
            ("owner", _store(chunks_per_doc=12), 8, 6),
            ("config", _store(chunks_per_doc=3), 1, 1),
        )
        for limiter, store, context_limit, expected_count in bounded_cases:
            with self.subTest(limiter=limiter):
                case = self._custom_case(
                    store=store, context_limit=context_limit
                )
                calls = self._call_snapshot(case)
                four = self._execute(case)
                _retrieval, _dense, _lexical, fusion = self._sources(case)
                semantic = self._semantic_for(fusion)
                authority = contracts._read_semantic_obligation_authority(
                    semantic
                )
                _plan_sha, _plan_config, rerank_k, final_budget = (
                    contracts._source_owner_plan_budget(authority.source)
                )
                expected = tuple(
                    sorted(semantic.candidate_evidence_ids)[
                        : min(
                            context_limit,
                            final_budget,
                            rerank_k,
                            len(semantic.candidate_evidence_ids),
                        )
                    ]
                )
                parents, bridges = self._context_receipts(case, semantic)
                context = self._target_context(four)
                self.assertEqual(len(expected), expected_count)
                self.assertEqual(
                    tuple(item.seed_evidence_id for item in parents),
                    expected,
                )
                self.assertEqual(len(bridges), 2 * expected_count)
                self.assertEqual(
                    case["fourth_decision"].selected_action.target_evidence_id,
                    expected[0],
                )
                self.assertIs(context.selected_receipt, parents[0])
                if limiter == "owner":
                    self.assertGreater(
                        len(semantic.candidate_evidence_ids), expected_count
                    )
                    self.assertGreater(context_limit, expected_count)
                else:
                    self.assertEqual(context_limit, expected_count)
                self.assertEqual(self._call_snapshot(case), calls)

    def test_refused_permits_issue_zero_context(self):
        retained = []
        for options in (
            {"max_actions": 3},
            {"mode": "empty", "lexical_mode": "empty"},
        ):
            with self.subTest(options=options):
                case = self._case(**options)
                retained.append(case)
                calls = self._call_snapshot(case)
                obligation, _dense, _lexical, _fusion = self._sources(case)
                source = contracts._require_retrieval_obligation_authority(
                    obligation
                ).source
                self.assertEqual(self._live_context_receipts(source), ((), ()))
                with self.assertRaises((TypeError, ValueError)):
                    self._execute(case)
                self.assertEqual(self._live_context_receipts(source), ((), ()))
                self.assertEqual(
                    contracts._controller_step_status(
                        execution=case["third"],
                        decision=case["fourth_decision"],
                        **case["env"],
                    ),
                    "pristine",
                )
                self.assertEqual(self._call_snapshot(case), calls)

        with self.assertRaisesRegex(
            ValueError, "^retrieval_rounds_not_pinned_to_one$"
        ):
            self._case(max_rounds=2)

        error_case = self.fixture._case(mode="provider_error")
        retained.append(error_case)
        calls = self._call_snapshot(error_case)
        obligation, _dense, _lexical = self.fixture._sources(error_case)
        source = contracts._require_retrieval_obligation_authority(
            obligation
        ).source
        self.assertEqual(self._live_context_receipts(source), ((), ()))
        with self.assertRaises((TypeError, ValueError)):
            contracts._execute_controller_first_parent_step(
                execution=error_case["second"],
                decision=error_case["third_decision"],
                **error_case["env"],
            )
        self.assertEqual(self._live_context_receipts(source), ((), ()))
        self.assertEqual(self._call_snapshot(error_case), calls)
        self.assertEqual(len(retained), 3)

    def test_prestarted_precompleted_and_cached_context_are_refused_preclaim(self):
        prestarted = self._case()
        semantic = self._issue_semantic(prestarted)
        authority = contracts._read_semantic_obligation_authority(semantic)
        parent_key = contracts._context_issuance_key(
            "parent", authority, semantic, **prestarted["env"]
        )
        self.assertIsNone(
            contracts._begin_context_receipt_issuance(
                authority.source,
                parent_key,
                contracts.ParentContextReceipt,
            )
        )
        calls = self._call_snapshot(prestarted)
        with self.assertRaisesRegex(
            ValueError, "controller_first_parent_context_already_started"
        ):
            self._execute(prestarted)
        self.assertIsNotNone(self._context_batch_statuses(prestarted, semantic)[0])
        self.assertIsNone(self._context_batch_statuses(prestarted, semantic)[1])
        self.assertEqual(
            contracts._controller_step_status(
                execution=prestarted["third"],
                decision=prestarted["fourth_decision"],
                **prestarted["env"],
            ),
            "pristine",
        )
        self.assertEqual(self._call_snapshot(prestarted), calls)

        precompleted = self._case()
        semantic = self._issue_semantic(precompleted)
        parents = issue_parent_context_receipts(
            obligation=semantic, **precompleted["env"]
        )
        calls = self._call_snapshot(precompleted)
        with self.assertRaisesRegex(
            ValueError, "controller_first_parent_context_already_started"
        ):
            self._execute(precompleted)
        self.assertIs(
            issue_parent_context_receipts(
                obligation=semantic, **precompleted["env"]
            ),
            parents,
        )
        parent_status, bridge_status = self._context_batch_statuses(
            precompleted, semantic
        )
        self.assertIsNotNone(parent_status)
        self.assertIsNone(bridge_status)
        self.assertEqual(
            contracts._controller_step_status(
                execution=precompleted["third"],
                decision=precompleted["fourth_decision"],
                **precompleted["env"],
            ),
            "pristine",
        )
        self.assertEqual(self._call_snapshot(precompleted), calls)

        cached = self._case()
        semantic = self._issue_semantic(cached)
        context = contracts._accumulate_controller_target_context(
            obligation=semantic,
            action_kind="expand_parent",
            target_evidence_id=(
                cached["fourth_decision"].selected_action.target_evidence_id
            ),
            **cached["env"],
        )
        calls = self._call_snapshot(cached)
        with self.assertRaisesRegex(
            ValueError, "controller_first_parent_context_already_started"
        ):
            self._execute(cached)
        self.assertIs(
            contracts._accumulate_controller_target_context(
                obligation=semantic,
                action_kind="expand_parent",
                target_evidence_id=(
                    cached["fourth_decision"].selected_action.target_evidence_id
                ),
                **cached["env"],
            ),
            context,
        )
        self.assertTrue(
            all(
                status is not None
                for status in self._context_batch_statuses(cached, semantic)
            )
        )
        self.assertEqual(
            contracts._controller_step_status(
                execution=cached["third"],
                decision=cached["fourth_decision"],
                **cached["env"],
            ),
            "pristine",
        )
        self.assertEqual(self._call_snapshot(cached), calls)

    def test_mismatched_sources_targets_and_dependencies_issue_zero_context(self):
        case = self._case(compare=True)
        other = self._case(compare=True)
        calls = self._call_snapshot(case)
        obligation, _dense, _lexical, fusion = self._sources(case)
        retrieval_authority = (
            contracts._require_retrieval_obligation_authority(obligation)
        )
        source = retrieval_authority.source

        def reject(*, execution=None, decision=None, env=None):
            with self.assertRaises((TypeError, ValueError)):
                self._execute(
                    case,
                    execution=(
                        case["third"] if execution is None else execution
                    ),
                    decision=(
                        case["fourth_decision"]
                        if decision is None
                        else decision
                    ),
                    env=case["env"] if env is None else env,
                )

        reject(execution=_clone_slots(case["third"]))
        reject(decision=_clone_slots(case["fourth_decision"]))
        reject(decision=other["fourth_decision"])
        reject(execution=other["third"])
        for dependency in ("store", "config", "runtime"):
            reject(
                env={
                    **case["env"],
                    dependency: other["env"][dependency],
                }
            )

        action = case["fourth_decision"].selected_action
        issued_target = action.target_evidence_id
        object.__setattr__(action, "target_evidence_id", "ev_forged")
        try:
            reject()
        finally:
            object.__setattr__(action, "target_evidence_id", issued_target)

        issued_query = obligation.query_sha256
        object.__setattr__(obligation, "query_sha256", "0" * 64)
        try:
            reject()
        finally:
            object.__setattr__(obligation, "query_sha256", issued_query)

        issued_binding = source.binding_sha256
        object.__setattr__(source, "binding_sha256", "1" * 64)
        try:
            reject()
        finally:
            object.__setattr__(source, "binding_sha256", issued_binding)

        issued_candidates = fusion.ordered_evidence_ids
        object.__setattr__(
            fusion,
            "ordered_evidence_ids",
            tuple(reversed(issued_candidates)),
        )
        try:
            reject()
        finally:
            object.__setattr__(
                fusion, "ordered_evidence_ids", issued_candidates
            )

        self.assertEqual(self._live_context_receipts(source), ((), ()))
        self.assertEqual(
            contracts._controller_step_status(
                execution=case["third"],
                decision=case["fourth_decision"],
                **case["env"],
            ),
            "pristine",
        )
        self.assertEqual(self._call_snapshot(case), calls)

    def test_concurrent_execution_has_one_parent_winner_and_one_successor(self):
        case = self._case()
        calls = self._call_snapshot(case)
        barrier = Barrier(4)

        def invoke(_index):
            barrier.wait()
            try:
                return self._execute(case)
            except BaseException as error:
                return error

        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = tuple(pool.map(invoke, range(4)))
        winners = tuple(
            item
            for item in outcomes
            if type(item) is type(case["third"])
        )
        rejected = tuple(
            item for item in outcomes if isinstance(item, BaseException)
        )
        self.assertEqual(len(winners), 1)
        self.assertEqual(len(rejected), 3)
        four = winners[0]
        contracts._require_controller_first_parent_transition(
            execution=four, **case["env"]
        )
        _obligation, _dense, _lexical, fusion = self._sources(case)
        semantic = self._semantic_for(fusion)
        parents, bridges = self._context_receipts(case, semantic)
        self.assertEqual(
            tuple(item.seed_evidence_id for item in parents),
            contracts._context_seed_evidence_ids(
                semantic,
                contracts._read_semantic_obligation_authority(semantic),
                case["env"]["config"],
            ),
        )
        self.assertEqual(len(bridges), 2 * len(parents))
        self.assertEqual(
            contracts._controller_step_status(
                execution=case["third"],
                decision=case["fourth_decision"],
                **case["env"],
            ),
            "transitioned",
        )
        with self.assertRaises((TypeError, ValueError)):
            self._execute(case)
        self.assertEqual(self._call_snapshot(case), calls)

    def test_registration_failure_keeps_original_error_and_is_nonretrying(self):
        case = self._case()
        calls = self._call_snapshot(case)
        _obligation, _dense, _lexical, fusion = self._sources(case)
        registration_code = (
            contracts._register_harness_execution_successor.__code__
        )
        preparation_codes = {
            contracts.issue_parent_context_receipts.__code__: "parent_batch",
            contracts.issue_bridge_context_receipts.__code__: "bridge_batch",
            contracts._mint_parent_context_receipt.__code__: "parent_mint",
            contracts._mint_bridge_context_receipt.__code__: "bridge_mint",
        }
        preparation_calls = {
            name: 0 for name in preparation_codes.values()
        }
        injected = []

        def fail_registration(frame, event, _argument):
            if event != "call":
                return fail_registration
            if frame.f_code in preparation_codes:
                preparation_calls[preparation_codes[frame.f_code]] += 1
            if frame.f_code is registration_code:
                injected.append(True)
                sys.settrace(None)
                raise RuntimeError("synthetic-parent-registration-failure")
            return fail_registration

        previous_trace = sys.gettrace()
        try:
            sys.settrace(fail_registration)
            with self.assertRaisesRegex(
                RuntimeError, "^synthetic-parent-registration-failure$"
            ):
                self._execute(case)
        finally:
            sys.settrace(previous_trace)

        self.assertEqual(injected, [True])
        semantic = self._semantic_for(fusion)
        parents, bridges = self._context_receipts(case, semantic)
        self.assertEqual(
            preparation_calls,
            {
                "parent_batch": 1,
                "bridge_batch": 1,
                "parent_mint": len(parents),
                "bridge_mint": len(bridges),
            },
        )
        self.assertTrue(
            all(
                status is not None
                for status in self._context_batch_statuses(case, semantic)
            )
        )
        self.assertEqual(
            contracts._controller_step_status(
                execution=case["third"],
                decision=case["fourth_decision"],
                **case["env"],
            ),
            "failed",
        )
        self.assertIs(
            issue_parent_context_receipts(
                obligation=semantic, **case["env"]
            ),
            parents,
        )
        self.assertIs(
            issue_bridge_context_receipts(
                obligation=semantic, **case["env"]
            ),
            bridges,
        )
        with self.assertRaises((TypeError, ValueError)):
            self._execute(case)
        self.assertEqual(self._context_receipts(case, semantic), (parents, bridges))
        self.assertEqual(self._call_snapshot(case), calls)

    def test_preparation_failure_tombstones_reservation_and_claim(self):
        case = self._case()
        calls = self._call_snapshot(case)
        _obligation, _dense, _lexical, fusion = self._sources(case)
        bridge_mint_code = contracts._mint_bridge_context_receipt.__code__
        captured = {}

        def fail_bridge_preparation(frame, event, _argument):
            if event == "call":
                frame.f_trace_lines = False
                if frame.f_code is bridge_mint_code:
                    captured["semantic"] = frame.f_locals["obligation"]
                    sys.settrace(None)
                    raise RuntimeError(
                        "synthetic-parent-bridge-preparation-failure"
                    )
            return fail_bridge_preparation

        previous_trace = sys.gettrace()
        try:
            sys.settrace(fail_bridge_preparation)
            with self.assertRaisesRegex(
                RuntimeError,
                "^synthetic-parent-bridge-preparation-failure$",
            ):
                self._execute(case)
        finally:
            sys.settrace(previous_trace)

        semantic = captured["semantic"]
        semantic_authority = contracts._read_semantic_obligation_authority(
            semantic
        )
        parent_status, bridge_status = self._context_batch_statuses(
            case, semantic
        )
        self.assertIs(parent_status, contracts._CONTEXT_COMPLETED)
        self.assertIs(bridge_status, contracts._CONTEXT_FAILED)
        self.assertEqual(
            contracts._controller_step_status(
                execution=case["third"],
                decision=case["fourth_decision"],
                **case["env"],
            ),
            "failed",
        )
        parents = issue_parent_context_receipts(
            obligation=semantic, **case["env"]
        )
        self.assertTrue(parents)
        self.assertEqual(
            tuple(item.seed_evidence_id for item in parents),
            contracts._context_seed_evidence_ids(
                semantic,
                semantic_authority,
                case["env"]["config"],
            ),
        )
        with self.assertRaisesRegex(
            ValueError, "context_receipt_issuance_already_consumed"
        ):
            issue_bridge_context_receipts(
                obligation=semantic, **case["env"]
            )
        with self.assertRaises((TypeError, ValueError)):
            self._execute(case)
        self.assertEqual(
            self._live_context_receipts(semantic_authority.source),
            (parents, ()),
        )
        self.assertEqual(self._call_snapshot(case), calls)

    def test_readback_rejects_unselected_and_complete_context_drift(self):
        case = self._case()
        calls = self._call_snapshot(case)
        _obligation, _dense, _lexical, fusion = self._sources(case)
        four = self._execute(case)
        semantic = self._semantic_for(fusion)
        parents, bridges = self._context_receipts(case, semantic)
        context = self._target_context(four)
        selected = context.selected_receipt
        unselected_parent = next(item for item in parents if item is not selected)
        unselected_bridge = bridges[-1]

        mutations = (
            (unselected_parent, "receipt_sha256", "0" * 64),
            (unselected_bridge, "receipt_sha256", "1" * 64),
            (context, "parent_receipts", parents[:-1]),
            (context, "bridge_receipts", tuple(reversed(bridges))),
        )
        for value, field, replacement in mutations:
            with self.subTest(field=field, value_type=type(value).__name__):
                issued = object.__getattribute__(value, field)
                object.__setattr__(value, field, replacement)
                try:
                    with self.assertRaises((TypeError, ValueError)):
                        contracts._require_controller_first_parent_transition(
                            execution=four, **case["env"]
                        )
                finally:
                    object.__setattr__(value, field, issued)

        identity = id(unselected_parent)
        authority = dict.get(
            contracts._ISSUED_PARENT_CONTEXT_RECEIPT_AUTHORITIES, identity
        )
        dict.__setitem__(
            contracts._ISSUED_PARENT_CONTEXT_RECEIPT_AUTHORITIES,
            identity,
            None,
        )
        try:
            with self.assertRaises((TypeError, ValueError)):
                contracts._require_controller_first_parent_transition(
                    execution=four, **case["env"]
                )
        finally:
            dict.__setitem__(
                contracts._ISSUED_PARENT_CONTEXT_RECEIPT_AUTHORITIES,
                identity,
                authority,
            )

        contracts._require_controller_first_parent_transition(
            execution=four, **case["env"]
        )
        self.assertIs(context.parent_receipts, parents)
        self.assertIs(context.bridge_receipts, bridges)
        self.assertEqual(self._context_receipts(case, semantic), (parents, bridges))
        self.assertEqual(self._call_snapshot(case), calls)

    def test_parent_and_bridge_acquisition_races_fail_closed(self):
        for family in ("parent", "bridge"):
            with self.subTest(family=family):
                case = self._case()
                calls = self._call_snapshot(case)
                boundary = Event()
                release = Event()
                captured = {}
                outcome = {}
                reserve_code = (
                    contracts._reserve_controller_context_batches.__code__
                )

                def trace_reservation(frame, event, _argument):
                    if event == "call" and frame.f_code is reserve_code:
                        caller = frame.f_back
                        captured["semantic"] = caller.f_locals[
                            "semantic_obligation"
                        ]
                        boundary.set()
                        if not release.wait(timeout=180):
                            raise RuntimeError("reservation-race-timeout")
                        sys.settrace(None)
                    return trace_reservation

                def run_controller():
                    sys.settrace(trace_reservation)
                    try:
                        outcome["value"] = self._execute(case)
                    except BaseException as error:
                        outcome["value"] = error
                    finally:
                        sys.settrace(None)

                worker = Thread(target=run_controller, daemon=True)
                worker.start()
                self.assertTrue(boundary.wait(timeout=180))
                semantic = captured["semantic"]
                issuer = (
                    issue_parent_context_receipts
                    if family == "parent"
                    else issue_bridge_context_receipts
                )
                try:
                    raced_receipts = issuer(
                        obligation=semantic, **case["env"]
                    )
                finally:
                    release.set()
                worker.join(timeout=180)
                self.assertFalse(worker.is_alive())
                self.assertIsInstance(outcome.get("value"), ValueError)
                self.assertRegex(
                    str(outcome["value"]),
                    "context_batch_already_started",
                )
                self.assertEqual(
                    contracts._controller_step_status(
                        execution=case["third"],
                        decision=case["fourth_decision"],
                        **case["env"],
                    ),
                    "failed",
                )
                with self.assertRaises((TypeError, ValueError)):
                    self._execute(case)
                self.assertTrue(raced_receipts)
                if family == "parent":
                    with self.assertRaisesRegex(
                        ValueError, "source_attempt_authority_required"
                    ):
                        contracts._controller_source_attempt_epoch(
                            raced_receipts[0]
                        )
                self.assertEqual(self._call_snapshot(case), calls)


if __name__ == "__main__":
    unittest.main()
