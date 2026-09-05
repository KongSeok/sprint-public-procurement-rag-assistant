# EH-RC0 재개 체크포인트

갱신: 2026-09-05 · EH2.6.c4.0.c 완료, parent c4.0/d2는 PARTIAL, 다음 READY는 EH2.6.c4.0.d. 토큰 절약을 위해 이 문서의 한눈에 보는 상태와 계약 §16.10부터 읽기.

## 중단/애매함 발생 시

- 짧은 재개 안내: `bidfit-evidence-harness-v1-rc0-resume.md`.
- private snapshot: `resources/context-backups/eh-rc0-context-20260903-165754-737633.zip` (repo 기준).
- 24파일 / 389,435 bytes. SHA-256: `63afe3171b138d099f6bba62fb4cf32ef535232f32629b6bd8769830382f99f9`.
- ZIP의 `START-HERE.md` → snapshot checkpoint → 필요한 계약/원문 절 순서로 읽는다.
- ZIP은 2026-09-03 16:57:54 KST의 문서 스냅샷이다. 최신 live checkpoint/사용자 지시와 대조한다.
  전체 대화/코드/dirty 변경 백업은 아니며 live repo 위에 덮어쓰지 않는다.

## 한눈에 보는 상태

- 전체 목표: BidFit Evidence-Harness v1-rc0. 목표 축소/완료 처리 없음.
- 실행 방식: 사용자 요청에 따라 leaf 하나씩 순차 처리. 새 독립 책임이 나타나면 해당 leaf를 다시 분할.
- repo: `/Users/pio/Documents/AIENGINEERCOURSE/MidProjectRAG` (ambient ChatGPT 사본 사용 금지).
- branch / 시작 HEAD: 현재 Phase 2 통합 작업대 `feat/total-integration`(이름 변경 전 `feature/visual-retrieval`) /
  `7ad229f8c85fb48ebb1c53f4424db4a224b562a7`.
  후속 전체 범위의 선택 commit·검증이 끝난 뒤 `feat/local-qwen-mini131-eval`에 병합한다.
  새 브랜치는 만들지 않는다.
- 완료: EH-A.1~3 감사·기준선·계약/flow 초안. 805 tests PASS, 실패/skip 0 (변경 전).
- 현재 IN_PROGRESS: **Phase 2**. EH2.1~2.5, EH2.6.a~d1, revision-0 `d2.i`, c4.0.a exact source-owner,
  c4.0.b typed source/outcome resolver, c4.0.c one-step claim/history PASS. parent c4.0/d2는 PARTIAL이다.
  다음 leaf는 validated selected target에서 parent/table/figure exact-one과 rerank prerequisite batch
  identity/order를 보존하는 `EH2.6.c4.0.d`다.
- 기존 평가 Batch 2의 활성 책임은 `EH2.EVAL`로 통합했다. EVAL.1~3은 완료, 사람 승인·qrels 보강과
  sealed held-out 실행은 EVAL.4~6에 남아 있으며 EH2 runtime에는 gold 값을 주입하지 않는다.
- blocker: 없음. 실제 생성/API 호출은 계속 0이며 Phase 2는 provider-free 합성 테스트로 진행한다.
- 직전 코드 상태: EH2.6.c2는 fact/compare/follow-up exact owner에서만 query·target·supplied evidence를
  유도하는 factory-only `SemanticVerificationObligation`을 추가했다. exact `verify(self, request)`를 local
  at-most-once로 호출하고 ID-less content projection을 닫힌 typed result로 정규화해 state-free
  `SemanticVerificationReceipt`를 발급한다. unavailable은 zero-call이며 provider/contract/post-call drift는
  fixed error로 소비한다. 전역·Unicode dependency rebinding, authority clone/mixed store, 동시 호출과 raw
  provider 비누출을 focused gate로 차단했다. focused26·관련118·전체1212·safety846와 HTML desktop/mobile
  검증이 PASS했다. API·Langfuse·실제 model/provider 호출은 0이고 synthetic verifier만 실행했다.
  EH2.6.c3.1은 immutable candidate seed prefix에서 parent=context-only와 table/figure actual bridge
  `applied|empty` receipt를 caller ID 없이 발급한다. root source 수명에 claim/history/cache를 결합해 중간
  semantic obligation GC·동등 재발급 뒤의 authority remint를 차단했다. focused8·관련114·전체1220·safety850
  PASS, API·model·Langfuse 호출 0이다. EH2.6 controller 전체 구현·실행 완료 주장이 아니며 원샷 전체는 미완료다.
  EH2.6.c3.2는 exact context batch에서 candidate+actual bridge를 ID 없이 한 번 rerank하고 global role order를
  owner budget으로 자른 derived semantic obligation을 발급한다. parent는 verifier의 unindexed auxiliary context로만
  전달하며 base/derived route는 root lifetime에서 한 번만 소비된다. provider 예외 뒤 dependency drift도 공통
  post-call gate에서 sanitized contract error로 닫았다. focused9·관련128·전체1229·safety854 PASS, 외부 호출 0이다.
  EH2.6.c3.3은 exact owner의 정상 종결만 three-reason `AbsenceConfirmationReceipt`로 봉인한다. cache hit도
  full validation하고 visible+closure-private authority, follow-up root-lifetime exact-once FSM, production/synthetic
  runtime kind 일치를 추가했다. focused67·관련192·전체1267·safety858·Playwright·독립 APPROVE, 외부 호출 0이다.
  EH2.6.c3.4는 19-field `ActionEffectReceipt`와 pure structural validator만 공개한다. action/receipt/outcome/call/
  source-kind 전수 matrix, evidence/context/absence projection, serialization drift를 닫았고 public mint/issuer/
  reducer/authority는 없다. focused11·관련114·전체1278·safety861·Playwright·독립 APPROVE, 외부 호출 0이다.
  EH2.6.c3.5는 effect namespace/public surface와 constant redacted repr를 봉인하고, lane/fusion/parent/bridge/
  rerank/semantic/absence validator가 exact receipt/dependency clone과 완성된 alternate live graph를 provider replay
  없이 거절함을 검증했다. focused18·관련147·전체1288·safety867·Playwright·독립 APPROVE, 외부 호출 0이다.
  EH2.6.d1은 b3 retrieval ledger와 분리된 controller `ExecutionLedger` 및 immutable `HarnessExecution`을
  exact initial state/store/config/runtime에서만 idempotent하게 발급한다. stable identity와 mutable-snapshot hash를
  분리하고 zero consumption, canonical obligation order, closure-private authority/history, 32-thread 단일 winner,
  GC tombstone과 clone·nested drift·mixed dependency·serialization 비승격을 닫았다. focused10·관련234·전체1298·
  safety868·Playwright·독립 APPROVE, 외부 호출 0이다. EH2.6.d2.i는 exact live revision-0 fact/compare
  all-unsearched execution에서 canonical action order와 selected-first `ControllerDecisionReceipt`를 발급·검증한다.
  stable identity/current snapshot/state/ledger를 결합하고 idempotence·32-thread winner·GC tombstone·clone/mixed
  graph·nonpromotion을 닫았다. focused8, d1+d2.i 18, 관련278, 전체1306, safety873, Playwright·독립 APPROVE이며
  외부 호출 0이다. EH2.6.c4.0.a는 state 생성 순간의 exact Bound/coverage/outcome/progress/registry/policy를
  closure-private mirror에 봉인하고 execution이 exact initial-state identity로만 상속하게 했다. equal-hash
  payload clone, owner 재사용·사후 부착, legacy follow-up 승격, validator/accessor drift를 차단했다.
  focused+인접43, 전체1315, safety874, Playwright·독립 APPROVE이며 커밋 `c0455f8`을 push했다.
  EH2.6.c4.0.b는 exact decision·source owner·live receipt authority를 역참조해 closed source/outcome
  projection을 유도한다. resolver-only issuer, identity mirror/reader revalidation, concurrency·GC tombstone,
  clone/mutation/dependency drift 차단을 구현했다. focused14·인접168·전체1329·safety877·Playwright·독립
  APPROVE이며 `ab5a223`을 push했다. EH2.6.c4.0.c는 exact step key로 single-winner claim을
  소유하고, claim-authorized prepare→source만 허용하는 closure-private history를 추가했다.
  `execute_retrieval_lane`의 monotonic source-attempt epoch와 동일 lock claim cutoff을 결합해 claim 이전에
  시작된 receipt를 사후 포장하지 못하게 했다. exact discard와 callback-free weak row
  pruning으로 실패 시 pending permit을 제거하고, duplicate/concurrent claim·direct resolver
  projection·clone/mixed/drift·GC/post-child 실패를 terminal failed tombstone으로 유지한다.
  focused30/30·인접249/249·전체1359/1359·safety881파일·`git diff --check`·독립 최종
  `APPROVE` PASS이며 API/OpenAI/model/Langfuse/golden/VLM/provider/clock 외부 호출은 0회다.
  c4.0.d~e per-target/structural bridge, c4 effect/advance, d2.x cross-state
  decision과 d3 run 권한은 아직 없다.

## 완료된 첫 leaf 참고: EH0.1.a (현재 작업 아님)

- 목표: runtime 입력 allowlist와 evaluator-only 필드의 hard boundary를 테스트로 고정.
- 읽을 것: TODO의 EH0.1, 계약 §8.1~8.2, `src/midprojectrag/answering/pipeline.py`의 request 사용부.
- 수정 허용: 신규 `src/midprojectrag/runtime_integrity.py`, `tests/test_runtime_integrity.py`.
  먼저 public DTO signature/테스트만 고정; projection 구현은 EH0.1.b에서 마무리.
- 검증: `PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_runtime_integrity`.
- 판정: allowlist 밖 gold/qrels/required_doc_ids/reference/expected 및 임의 중첩 options를 runtime에 전달 불가.
  정상 user scope와 gold ID가 우연히 같은 값인 경우를 문자열 blacklist로 차단하지 않는다.
- 실패 테스트를 먼저 남길 경우 EH0.1.a의 red evidence로 명시한다. green 구현/푸시/완료 주장은 EH0.1.b~c 뒤에 한다.
- 다음 후보: EH0.1.b → EH0.1.c → EH0.2. 전체 tree는 `../architecture/todolist.md#eh-rc0--evidence-harness-재귀-실행-todo-2026-09-03`.

## 매 leaf 종료 시 갱신할 최소 항목

`ID | 상태 | 변경 파일 | focused 명령/결과 | 새 결정·남은 실패 | 다음 ID/선행조건`

새 완료 행은 아래 원장에 한 줄 추가하고 현재 READY만 이동한다. 새로 시작할 때 완료한 감사,
805-test baseline, 리서치 문서 전체를 다시 실행/읽지 않는다. 코드 영향이 있는 Phase gate에서만 전체 검증한다.

## 완료 원장

| ID | 결과 | 근거 |
| --- | --- | --- |
| EH-A.1 | COMPLETED | 원샷 기록의 시작 감사 스냅샷; dirty 사용자 변경 보존 |
| EH-A.2 | COMPLETED | unittest discover 805 tests / 33.493s / OK / skip 0 |
| EH-A.3 | COMPLETED | 계약+target/current MMD/PNG/HTML 초안; browser QA는 EH-D.3 |
| TODO-SPLIT | COMPLETED | Phase 0~4+납품을 독립 leaf/의존성/gate로 분해; 구현 동시 실행 1개; read-only 의존성/acceptance 리뷰 및 diff-check PASS |
| EH-CONTEXT.1 | COMPLETED | private ZIP 24파일; CRC/SHA/원문 동일성/기존 문서 불변/Git 제외 검증; 다음 leaf EH0.1.a 유지 |
| EH0.1~7 / EH0.G | COMPLETED | focused47/full852, 0 skip; case SHA129/129 provider-free replay; review18/18, HTML desktop/mobile PASS |
| EH1.1 | COMPLETED | evidence/model.py + public types; tests.test_evidence_model 7 PASS. char_range occurrence/빈 그림/immutable roundtrip |
| EH1.2 | COMPLETED | evidence/store.py; 타입/store 13 PASS. missing module TDD red→green. immutable/hash/source/span/locator/scope 검증 |
| EH1.3 | COMPLETED | evidence/builder.py; 합계17 PASS. source block SHA/doc/page + 원문span 검증, 기존 page chunks 불변 |
| EH1.4 | COMPLETED | evidence/artifacts.py + structured splitter; 리뷰 수리 포함 22 PASS. SHA/overwrite/private binding/원문 span |
| EH1.5 | COMPLETED | retrieval/contracts.py + dense.py; 2 focused PASS / evidence 포함24. 실제 모델 실행은 EH1.10 |
| EH1.6 | COMPLETED | retrieval/legacy_page.py; ExactDenseIndex control 1 focused PASS |
| EH1.7 | COMPLETED | Kiwi0.23.2/model0.23.0/1worker pinned; 한국어 실제 tokenize + BM25 artifact/scope tests 2 PASS |
| EH1.8 | COMPLETED | fusion.py; budget/lexical rescue/RRF/mixed granularity/empty tests 3 PASS |
| EH1.9 | COMPLETED | context.py; parent bound/mandatory/doc coverage/missing budget 3 PASS |
| EH1.10 | COMPLETED | private v1-rc0-20260903-01: 98docs/9,496 child KURE+Kiwi; load/search/source unchanged/generation0 |
| EH1.G | COMPLETED | focused35/full887/skip0; safety780/browser PASS; review P1 3건 수리 후 exact closure PASS |
| EH2.1 | COMPLETED | QueryPlan/budget/registry; focused27/full898/skip0. registry-bound load+slotted predicate 수리, 독립 재리뷰 PASS |
| EH2.2 | COMPLETED | deterministic planner; focused51/full922/skip0. catalog/alias/JSON/Korean routing adversarial repair 후 독립 감사 PASS |
| EH2.3 | COMPLETED | actual-citation follow-up; focused61/full943. exact citation scope, verified progress, bounded fallback, 독립 P1 수리 PASS |
| EH2.4 | COMPLETED | compare doc×field coverage; focused107/full987. provisional missing, typed receipt, complete matrix, 독립 P1 수리 PASS |
| EH2.5 | COMPLETED | sealed Belief/Progress/HarnessState + typed action/decision; focused55/full1020. store/nested identity P1 수리 후 독립 재검토 PASS |
| EH2.6.a | COMPLETED | §16.10 E0/E1 controller 계약·재귀 leaf·public owner 경계. 7 P1 수정 후 독립 재리뷰 PASS |
| EH2.6.b1 | COMPLETED | BoundFact/fact 초기 state/live request·store authority. focused47/full1034/safety807, 독립 재리뷰 PASS; 다음 EH2.6.b2 |
| EH2.6.b2 | COMPLETED | immutable execution config + exact production/synthetic runtime authority. focused104/full1109/safety811, 독립 P1 10건 수리·최종 재리뷰 PASS; 다음 EH2.6.b3 |
| EH2.6.b3 | COMPLETED | exact code+module namespace provenance로 copied-globals clone 차단. b4와 함께 focused64/related214/full1175, 독립 재리뷰 PASS |
| EH2.6.b4 | COMPLETED | stage-4 same-round FusionReceipt + state-free E0 control; post-provider validation, strict obligation order, closure-cell/dual-history replay 방어. focused27/full1175, API·model·Langfuse 0; 다음 EH2.6.b5 |
| EH2.6.b5 | COMPLETED | b3/b4 production 변경 없이 lexical-only rescue, fact empty state-free, pre-call zero-dispatch, provider-error diagnostic/no-fusion. focused4/b3~b5 68/related218/full1179/safety829 PASS; 다음 EH2.6.c1 |
| EH2.6.c1 | COMPLETED | `a9ac527` push. follow-up outcome을 E1 candidate/all-open state로 안전 투영. metadata fail-closed, retrieval 0, clone·단일 private drift 방어. focused7/related60/full1186/safety837, 독립 리뷰 3건 APPROVE; 다음 EH2.6.c2 |
| EH2.6.c2 | COMPLETED | `05fc4cc` push. exact owner-derived semantic obligation + one-call/zero-call verifier receipt. typed support/value/contradiction, at-most-once·dependency rebinding·clone/mixed-store·비누출 방어. focused26/related118/full1212/safety846, HTML desktop/mobile PASS; 다음 EH2.6.c3 |
| EH2.6.c3.1 | COMPLETED | parent/bridge source receipt. bounded candidate seed, parent nonpromotion, table/figure actual/empty attempt, root-lifetime replay guard. focused8/related114/full1220/safety850, provider 0; 다음 EH2.6.c3.2 |
| EH2.6.c3.2 | COMPLETED | ID-less rerank + derived semantic. global role order, owner budget, exact context batch, auxiliary parent 비승격, base/derived route와 provider-error post-call gate. focused9/related128/full1229/safety854, provider 0; 다음 EH2.6.c3.3.a |
| EH2.6.c3.3 | COMPLETED | three-reason bounded absence, exact proof matrix, zero-provider/nonpromotion, cache authority와 follow-up root-lifetime exact-once. focused67/related192/full1267/safety858, Playwright, independent APPROVE; 다음 EH2.6.c3.4 |
| EH2.6.c3.4 | COMPLETED | 19-field closed effect value와 pure validator. source-kind 포함 full matrix, context/absence/hash/serialization fail-closed, public authority 없음. focused11/related114/full1278/safety861, Playwright, independent APPROVE; 다음 EH2.6.c3.5 |
| EH2.6.c3.5 | COMPLETED | effect exact symbol inventory/redacted repr/nonpromotion과 7종 source validator clone·coherent mixed graph provider-zero gate. focused18/related147/full1288/safety867, Playwright, independent APPROVE; 다음 EH2.6.d1 |
| EH2.6.d1 | COMPLETED | `6ada15b` push. initial-only `ExecutionLedger`+`HarnessExecution`, stable identity/snapshot hash 분리, exact root authority/idempotence/concurrency/GC/clone gate. focused10/related234/full1298/safety868, Playwright, independent APPROVE; 다음 EH2.6.d2 |
| EH2.6.d2.i | COMPLETED | `dac3338` push. revision-0 fact/compare selected-first controller permit. stable identity+current snapshot/state/ledger binding, exact order, idempotence/concurrency/GC/clone/nonpromotion gate. focused8, d1+d2.i18, related278, full1306, safety873, Playwright, independent APPROVE; parent d2 PARTIAL, 다음 EH2.6.c4.0 |
| EH2.6.c4.0.a | COMPLETED | `c0455f8` push. exact state-creation source owner와 execution identity 상속. equal-hash clone·owner 재사용/사후 부착·legacy follow-up·dependency drift 차단. focused+인접43, full1315, safety874, Playwright, independent APPROVE; parent c4.0/d2 PARTIAL, 다음 EH2.6.c4.0.b |
| EH2.6.c4.0.b | COMPLETED | `ab5a223` push. exact typed source/outcome resolver와 sealed non-authorizing projection. direct issuer·forced mutation/clone·cross-owner·dependency drift·GC remint 차단. focused14, related168, full1329, safety877, Playwright, independent APPROVE; parent c4.0/d2 PARTIAL, 다음 EH2.6.c4.0.c |
| EH2.6.c4.0.c | COMPLETED | exact step identity를 closure-private single-winner history에 봉인하고 claim-authorized prepare→source, shared lane epoch/claim fence, terminal failed tombstone으로 사후 포장·중복·역순·clone/mixed/drift·GC를 차단. focused30/30, adjacent249/249, full1359/1359, safety881파일, diff-check, independent APPROVE, 외부 호출 0; parent c4.0/d2 PARTIAL, 다음 EH2.6.c4.0.d |

## 안전/컨텍스트 규칙

- 원래 tracked dirty 39개와 다수 untracked 파일은 사용자 소유다. broad add/reset/checkout/merge 금지.
- `resources/` 전체 비공개. gold/원문/벡터/key/private trace를 공개 로그로 복사하지 않는다.
- 기존 artifact overwrite 금지. 실제 모델 호출/임베딩은 해당 별도 leaf에서만 실행한다.
- 완료 체크는 test/receipt에 근거한다. code complete ≠ real run ≠ quality validated.
