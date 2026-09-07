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

- [2026-08-30 18:47] Stage=Integrate
  - Pre-check: staged-only 414/414, 20 schemas, compileall, safety 460과 공개 경로·개인경로 검사를 통과했다.
  - Commit: `df72d69` — `feat(ingest): recover and index local visual evidence`.
  - Push: `origin/feat/hwp-visual-corpus-rollout` 신규 추적 브랜치 publication 성공.
  - Evidence: private/resources/scoring/apps/configs-rag 제외, stale v1 report screenshot 제외.

- [2026-08-31 19:11] Stage=Implementation/Test (Methodology=TDD)
  - Summary: Mini131 실행·Sol 판정·parser·private HTML 하네스와 blind/hash/resume/budget gate를 고정했다.
  - Decisions: corpus vector는 재사용하고 query만 임베딩한다; candidate와 judge를 분리하고 판정 이력을 보존한다.
  - Blocker: 이번 90문항 private OpenAI payload와 최대 140회/$4에 대한 명시 승인이 필요하다.
  - Evidence: preflight 40/30/20, parser 2/2, 평가 90/90 PASS; 최초 full 679/679 뒤 concurrent visual fixture 1건 분리.

- [2026-08-31 21:30] Stage=Execute/Evaluate (Methodology=Frozen-candidate + blind LLM judge)
  - Summary: 승인된 `gpt-5-mini` Mini131 기준선을 완료하고 RAG 129개를 고정 Sol 5.6으로 판정했다.
  - Decisions: 후보 답변은 수정하지 않는다; 39 legacy reconstructed와 90 prospective를 분리한다;
    parser 2개는 의미 평균에 섞지 않는다; 모든 채팅·검색·provider·판정 이력을 private로 보존한다.
  - Incidents: Core 연결 오류 2건과 Gap Schema 400 1건을 재시도 없이 보존했고, secondary 2건의
    timestamp 순서는 semantic hash 불변을 입증한 metadata-only 감사 보정으로 닫았다.
  - Evidence: 평균 54.845, accepted 58/129, rejected 71/129, unresolved 0, parser 2/2,
    transcript 129/129, judgment 155행, candidate USD 0.21345322.

- [2026-08-31 21:31] Stage=Test/Integrate
  - Summary: final receipt·private ledger·HTML의 수량, SHA-256, 권한과 전체 회귀를 재검증했다.
  - Evidence: preflight 28/28·129/129, private 0600, public 0644, evaluation 210/210,
    전체 unittest 728/728, staged clean-checkout 614/614 PASS(비공개 통합 8 expected skip).
    private 산출물은 Git 대상에서 제외한다.

- [2026-09-06 11:53] Stage=Environment Repair/Test
  - User request: 필요한 테스트 의존성 설치 및 기존 환경 오류 해소.
  - Cause: 프로젝트 `.venv` 대신 Miniconda Python 3.13을 실행했다. 필요한 패키지는 `.venv`에 이미 있었다.
  - Repair: 선언한 extras를 ML lock 제약으로 동기화, pip check 및 32개 ML pin 검증; README/testpolicy 실행 명령 정정.
  - Evidence: 기존 실패 영역153/153, 전체1498/1498 PASS(211.055초), errors/failures/skipped0.
  - Scope: 앱 코드·테스트·모델 lock 변경 없음. 기존1438건 실패 기록과 이번 정상 재실행 결과를 분리 기록했다.
  - Reference: ../test/errorlogs/backend/2026-09-06-eh2-6-c40e-full-regression-environment.md.

- [2026-09-06 14:21] Stage=Implementation/Test/Review (Cycle18)
  - Summary: 최초 fact/compare dense 결과를 effect/history와 ledger1/successor로 연결. 동일 state·predecessor 보존.
  - Evidence: 신규13, 인접합91, 전체1511 PASS(174.977초), 독립 APPROVE; Chrome desktop/mobile 정적 보고서 PASS.
  - Scope: synthetic/offline; 실제 API/model/Langfuse/golden 호출0. default local/API profile·resources 불변.
  - Reference: 2026-09-06-controller-initial-transition-relay.md. 다음 d2.x 새 폼은 선택 push 뒤 시작한다.

- [2026-09-06 14:43] Stage=Implementation/Test/Review (Cycle19)
  - Summary: exact dense successor에서 ordinal2 lexical/진단/기권 decision 발급. budget 우선·비소비 조회·정책 revision 고정.
  - Evidence: 신규11·인접79·전체1522 PASS(186.315초), 독립 APPROVE; Chrome desktop/mobile 보고서 PASS.
  - Boundary: 실제 두 번째 실행·terminal result는 없음. API/model/clock0, baseline/index/golden 불변.
  - Next: c4.2.a lexical 실행/전이2 뒤 d2.x.b를 연결해 전체 매트릭스와 reducer의 순환 선행을 풀어간다.

## 2026-09-07 — 협업 릴레이 스킬 저장소 동기화

- Scope: 협업/릴레이 관련 스킬과 연결 참조만 반영. 제품 코드·데이터·기존 타인 수정은 제외.
- Intent: 프로젝트 설치본에서도 Astra Design → Sol Ultra → fresh Astra → 로그올/허용 통합 → 재진입 규칙 사용.
- Method: CUSTOM, 스킬 형식·JSON·참조·경로/미러 검사 및 scoped diff 검수 후 현재 브랜치에 커밋/푸시.
- Rollback: 이번 커밋의 지정 스킬 변경만 역적용. 기존 작업 트리 전체 reset/삭제 금지.
- Evidence: `fivecircles/work/2026-09-07-collaboration-skill-sync.md`.

- [2026-09-07 12:27] Stage=Implementation/Test/Review (Cycle20 / EH2.6.c4.2.a)
  - Method: Philosopher Design → Sol Ultra → fresh Astra deep review; run=eh-relay-20260907.
  - Summary: lexical ordinal2 실행과 revision2 연결. 최초 root/직전 predecessor·기존 source를 보존한다.
  - Evidence: 집중36·관련98·격리134·전체1534 PASS, fresh REVIEW PASS.
  - Boundary: 앱 API/model/Langfuse0, baseline/corpus/gold/resources 불변. 스킬-only 동시 커밋은 분리 확인.
  - Closeout: 2026-09-06-controller-lexical-transition-relay.md. 선택 통합 후 d2.x.b Design.

- [2026-09-07 13:26] Stage=Implementation/Test/Review (Cycle21 / EH2.6.d2.x.b.1)
  - Method: Astra Design → Sol Ultra → fresh Astra deep JSON REVIEW.
  - Result: ordinal3 fuse/기권 선택. 집중11·관련105·격리132·전체1545 PASS, 후보0bf15494·증거0b905e12 결속.
  - Boundary: fusion 실제 실행·semantic 승격·전체 E2E는 후속. baseline/corpus/gold/resources/runtime 불변.
  - Closeout: 2026-09-07-controller-post-lexical-decision-relay.md. 선택 통합 후 첫 fuse Design; 별도 retrieval 비교와 파일/자원 경계 조정.
