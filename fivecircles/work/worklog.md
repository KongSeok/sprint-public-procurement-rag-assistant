# Work Log (append-only)

- [YYYY-MM-DD HH:MM] Stage=Requirements
  - Summary:
  - Conflicts:
  - Decisions:
  - TODO:
  - Evidence:

- [YYYY-MM-DD HH:MM] Stage=Design
  - Summary:
  - Decisions:
  - TODO:
  - Evidence:

- [YYYY-MM-DD HH:MM] Stage=Implementation (Methodology=TDD)
  - Summary:
  - Decisions:
  - TODO:
  - Evidence:

- [YYYY-MM-DD HH:MM] Stage=Test
  - Summary:
  - Failures:
  - Fixes:
  - Evidence:

- [YYYY-MM-DD HH:MM] Stage=Integrate
  - Pre-check:
  - Commit:
  - Push:
  - Evidence:

- [2026-08-26 20:51] Stage=Requirements
  - Summary: corrected metadata lookup/display lane and Streamlit E2E scope review started.
  - Conflicts: peer-review queue/debate files are absent; product debates use requirements/debates.
  - Decisions: preserve RagResponse v1; exact metadata stays local and joins by doc_id.
  - TODO: write contract/plan, peer review, implement only after approval.
  - Evidence: D-014, metadata correction contract, current application/UI audit.

- [2026-08-26 21:05] Stage=Design
  - Summary: structured metadata lane contract and TDD delivery plan drafted.
  - Decisions: local deterministic catalog; RagResponse v1/body index unchanged.
  - TODO: peer review before production code.
  - Evidence: specs/structured-metadata-lane.md, work/structured-metadata-lane-plan.md.

- [2026-08-26 21:18] Stage=Design Review
  - Summary: first peer review requested eight contract hardening changes.
  - Decisions: all findings incorporated; implementation remains blocked pending re-review.
  - TODO: independent second review.
  - Evidence: work/review/review-structured-metadata-lane-2026-08-26.md.

- [2026-08-26 21:36] Stage=Design Review
  - Summary: second review tightened the provider data-flow boundary and locator grammar; final review approved implementation.
  - Decisions: D-015 separates local typed metadata lookup from body Dense RAG and keeps the current index/RagResponse v1.
  - TODO: implement catalog, lazy application composition, Streamlit flow and E2E evidence with TDD.
  - Evidence: agent/debate.md, work/review/review-structured-metadata-lane-2026-08-26.md.

- [2026-08-26 21:44] Stage=Implementation Review
  - Summary: application review caught raw locator exposure and unscoped metadata-runtime asks.
  - Decisions: project raw catalog facts into locator-free application DTOs; require explicit 1–20 scope in config 1.1.
  - TODO: complete full-suite, actual bundle/API, Streamlit health/browser and safety closeout.
  - Evidence: work/review/review-structured-metadata-lane-2026-08-26.md; application tests 19/19.

- [2026-08-26 21:52] Stage=Implementation (Methodology=TDD)
  - Summary: typed catalog, config 1.1 correction hash, lazy provider composition and Streamlit metadata routing/cards completed.
  - Decisions: reuse the 9,509-row small index; require explicit 1–20 scope; expose no locator-bearing DTO through application.
  - TODO: renewed destination-specific consent for the one live personal-OpenAI smoke.
  - Evidence: 100 cards, 1,200 facts, 105 audited targets; independent implementation re-review APPROVE.

- [2026-08-26 21:53] Stage=Test
  - Summary: local E2E, actual bundle, health and in-app browser visual flow passed.
  - Failures: sandbox/index-lock and custom-control environment issues were resolved; live API was blocked before process start by re-approval gate.
  - Fixes: matching approved local environment for lock/health; visible labels for controlled widgets; no live API retry.
  - Evidence: 249/249 tests, compileall, safety 448, diff-check, health=ok, browser metadata/card/consent flow.

- [2026-08-28 14:40] Stage=Implementation (Methodology=TDD)
  - Summary: refined 98문서 page/table dual lane, render-tree layout overlay, locator citation과 runtime v1.2를 구현했다.
  - Decisions: page/table은 별도 exact index로 유지하고 한 query vector를 RRF로 결합한다; nested·미검증 표의 page는 추정하지 않는다.
  - TODO: destination-specific OpenAI table egress 승인, table small index·gold, v1.2 Streamlit 전환.
  - Evidence: page 9,331, table 35,128, verified layout 10,728/10,782, linked chunks 33,338.

- [2026-08-28 14:40] Stage=Test
  - Summary: 실제 refined artifacts와 page vector subset migration을 검증했다.
  - Failures: 첫 table materialization의 반복 prefix token 초과와 page/table config hash 배치 오류를 발견했다.
  - Fixes: bounded prefix, lane별 config hash, layout exact coverage/page_count/nested-page gate를 추가했다.
  - Evidence: vector subset 9,509→9,331, byte delta 0, unittest 300/300, safety 474 files PASS.

- [2026-08-30 18:29] Stage=Implementation (Methodology=TDD)
  - Summary: additive visual v2 occurrence/crop, offline understanding, fusion/citation과 평가 계약을 구현했다.
  - Decisions: provenance-first, false-link-zero, supported caption만 답변 허용, private artifact는 Git 밖에 둔다.
  - TODO: reviewed 9-document gold와 pinned model weight 뒤 HWP 94건·실제 OCR 품질을 실행한다.
  - Evidence: HWP 대표 5건 27 occurrence, PDF 4건 1,110 occurrence, 동일 identity 재실행.

- [2026-08-30 18:29] Stage=Test
  - Summary: 공개 구현 전체 회귀와 flow report 정적 QA를 완료했다.
  - Failures: publish 권한·sandbox·identity/rank/support-ref/schema parity 결함을 발견했다.
  - Fixes: atomic fail-closed, OS network sandbox, bounded quota, exact visual gold와 parity test를 추가했다.
  - Evidence: focused 92/92, full 493/493, compileall, 23 schemas, safety 556, diff-check PASS.
