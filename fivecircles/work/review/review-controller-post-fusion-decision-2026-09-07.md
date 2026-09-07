# 첫 fusion 이후 행동 선택 검수

## Scope

- EH2.6.d2.x.b.2 / feat/total-integration. Sol Ultra 구현, fresh Astra deep 독립 검수.
- 후보 sha256:8d3172b1ec96ce2d11a1892d41cd2a8d3dddc9aa83dc6c050df72b0f401fba24; 계약 sha256:6d80a97e9261b359ad3d80fa05f986f19340c9b905b737c5714183511ba512a4; 증거 sha256:eaf054ab203e73671d84ba9f9b035bbcaf45027f12bb6c8c21a7e331c8366771.
- [원문 REVIEW](../collaboration/eh-relay-20260907/messages/EH2.6.d2.x.b.2/011-post-fusion-review-1.json).

## Findings

- 차단 지적 없음. exact fusion/state/owner에서 ordinal4를 선택하며, 선택된 행동의 실행이나 의미상 정답 판정은 하지 않는다.
- budget3은 기권, applied는 첫 bounded parent target, empty는 zero-provider 결측 확인 의도다. 원래 후보 순서/형제/계보/상태/예산은 보존한다.

## Decision

APPROVE / post-fusion-review-1. 집중11·관련205·격리216 PASS. 원래 전체1657은 CSV 동결 해시 오류1로 FAIL; 동결 사본 analytics5 재검증 PASS 및 fresh deep의 증거 결합 승인.

COMPOSED_VALIDATION_PASS는 단일 전체 실행 PASS가 아니다. canonical CSV는 UNREPAIRED이며, 중복 검사를 더해1662개로 세지 않는다. 과거 metadata probe의 상속 PYTHONPATH는 UNKNOWN으로 보존하고 현재 관측 재현의 한계를 독립 검수했다.

- TDD·compare 수리, 계측 preflight 및 첫 회복 discovery 오류는 보존했다. actual5 재검증은0.073초/exit0, missing/skipped/xfail/xpass0이다.
- 새 Controller/unit wall time은 모델/RAG 성능 지표가 아니다. 실모델·API·GCP·DIAG131 실행은 이 배치에서0이다.
- 제품3+계약참조3, 격리 base+owned 검사로 다른 담당 코드와 분리했다. 보고서/공개 안전성/선택 통합은 별도 후속 관문이다.

## Next actions

1. Incorporate all 13 next_batch_constraints from first-fuse-state-review-1 at fivecircles/work/collaboration/eh-relay-20260907/messages/EH2.6.c4.2.b.2/003-first-fuse-state-review-1.json, SHA256 616886f94d9c71a968a7a662a3d3ad94b59afbddc92ceaff0fc348e3bf0fe945. Preserve their historical wording and prospective first-fusion state amendment. This reviewed directive adds only the explicitly selected ordinal4 decision permission.
2. Incorporate all nine next_batch_constraints from first-fuse-state-publication-review-1 at fivecircles/work/collaboration/eh-relay-20260907/messages/EH2.6.c4.2.b.2/005-first-fuse-state-publication-review-1.json. Its prior payload and exact-two-field exception provide no clearance for new bytes or findings.
3. Keep EH2.6.c4.2.b, EH2.6.d2.x.b, Controller and E2E PARTIAL. No fourth execution, revision4 successor, semantic/context/absence minting, claim consumption, state/progress/ledger mutation, later compare execution or whole Controller completion is approved.
4. Preserve exact predecessor/source-owner identity, source candidate order, sibling identity, open progress, coverage0.0, in_progress, false terminal gates, round1 and rejection of round-cap2 before dispatch. Specify complete canonical sibling-obligation lifetime before later compare execution.
5. Main may record the accepted composed gate only while retaining native_full_status=FAIL, native_full_exit_code=1 and canonical_input_status=UNREPAIRED_FROZEN_HASH_MISMATCH. Unique effective coverage remains1657. Preserve original v3 manifests, native failure, recovery1 discovery failure with zero required tests, intermediate unknown exit and every other failed/preflight diagnostic artifact.
6. Preserve the accepted runtime and input limitations explicitly. Current probes are not historical environment reconstruction; listed nonignored inputs are not a private whole-filesystem inventory. Changes affecting candidate, contract, required evidence, dependencies or evaluation inputs require renewed applicability assessment and review.
7. Complete actual report/browser validation, closeout/log records, safety review and final scoped Git/publication reconciliation separately. This product/composition PASS is not publication clearance, automated safety PASS, commit/push permission or acceptance of future closeout bytes.
8. Integrate only reviewed product and bound behavior-reference bytes with separately reconciled closeout records. Preserve unrelated dirty work; do not attribute shared-worktree changes or the full collection wholly to this batch. Keep resources and independently owned measurement changes excluded.
9. Continue the authorized local-first implementation path and preserve the authoritative control baseline and API compatibility boundary. Code regression PASS does not establish retrieval superiority; same-golden controlled comparison remains a separate required outcome.
10. No duplicated GCP/DIAG131 measurement, model/API/Langfuse/VLM execution, profiling, benchmark or baseline/corpus/gold/configuration change follows from this review. Carry canonical-locator recurrence and the actual context-execution gap into the next complete Design directive.
