# Implementation Log

Per batch:
- Intent (what/why)
- Change summary
- Files touched
- Known limitations
- Next TODO

## 2026-08-28 — refined structured table lane

- Intent: refined 98문서로 page/table embedding과 runtime bundle을 교체하고 표 관계 검색 실패를 보완한다.
- Change summary: deterministic table Markdown, dual exact indexes, RRF fusion, table locator citation,
  render-tree layout overlay와 fail-closed runtime v1.2 계약을 구현했다. refined 98문서를 재추출하고
  page 9,331개·table 35,128개 청크 및 두 local index를 materialize했다.
- Files touched: contracts/indexing/ingest/answering/application/CLI와 관련 합성 테스트, refined private
  manifest·blocks·chunks·layout·local indexes.
- Verified: 98/98 extraction 성공, table render join 10,728/10,782(99.50%), page-linked table chunks
  33,338개, nested page 오귀속 0, page 범위 이탈 0, 모든 table text 600 tokens 이하. local 표 질문
  3건 중 2건은 top-k 적중했고 병합 header 1건은 table rank 8로 현재 fusion top-10에서 누락됐다.
- Review fixes: page-v1 config hash 오염을 복구했고, layout↔chunk exact coverage, manifest page_count,
  nested page null, 실제 chunk config hash와 index 선언 결합을 provider 이전 gate에 추가했다.
- Vector reuse: 기존 OpenAI small page index 9,509개에서 refined retained 9,331개를 chunk byte
  identity로 선택·재정렬했다. 제거 178개, 누락·변형 0, source/target vector byte delta 0이며
  provider/network 호출과 비용은 없었다.
- Known limitations: PDF 4건 structured table extraction, 한컴과의 시각적 pixel QA, OpenAI small table
  index와 human-reviewed table gold는 미완료다. local hash 검색 결과는 최종 성능 증거가 아니다.
- Next TODO: 사용자의 destination-specific corpus egress 승인 후 table index를 생성하고 OpenAI
  small 표 gold를 거쳐 v1.2 config를 원자 전환한다.

## 2026-08-30 — visual image recovery and understanding v2

- Intent: HWP/PDF에서 빠지거나 문맥을 잃은 표·이미지를 page/bbox occurrence로 복구한 뒤 local
  OCR/layout/caption과 검색·인용에 안전하게 연결한다.
- Change summary: additive occurrence/evidence/chunk/gold schemas, HWP helper/runner, PDF durable runner,
  checksum-pinned network-sandbox adapter, bounded visual fusion, caption support-ref·abstention과 exact
  visual evaluation을 구현했다.
- Private execution: HWP 대표 5건 27 occurrence(eligible 16, withheld 11), PDF 4건 570쪽
  1,110 occurrence(eligible 1,103, withheld 7)를 재현했다. 원문·파일명·crop·출력은 Git 밖이다.
- Review fixes: caption cap 전 visual overfetch, bounded visual quota, evidence ID prefix, caption-only
  answer guard, annotated-lane-only precision과 Schema/manual parity를 추가했다.
- Verified: focused 92/92, full unittest 493/493, compileall, Draft 2020-12 schemas 23개,
  `git diff --check`, repository safety 556 files와 static flow HTML QA를 통과했다.
- Known limitations: 실제 model inference는 pinned weight 부재로 0건이고, 인앱 browser의 local
  file 정책 때문에 live viewport QA는 environment-blocked다.
- Next TODO: 사람 검토 gold와 model weight가 준비되면 실제 OCR 품질 gate를 통과한 뒤 HWP 94건을
  별도 실행한다. 그 전에는 기본 runtime과 외부 parser/search API를 활성화하지 않는다.
- Published: 공개 구현 `df72d69`를 `origin/feat/hwp-visual-corpus-rollout`에 푸시했다. 릴레이는
  외부 입력 gate 때문에 `STOP_WITH_REASON`으로 닫았다.

## 2026-08-31 — GPT-5.6 direct supplemental baseline scoring

- Intent: 코드 문자열 판정 대신 ChatGPT `gpt-5.6-sol`이 기존 보조 베이스라인 답변을 직접
  의미 채점하고, 검색·집합 지표와 분리된 실제 품질 점수를 확정한다.
- Change summary: 56개 답변을 19/19/18로 나눠 1차 판정하고 경계 5건을 독립 2차·3차 판정했다.
  private final judgment/summary와 문항별 로컬 HTML, content-free 공개 receipt를 생성했다.
- Result: 평균 46.70/100, accepted 19/56, rejected 35/56, needs human 2/56, quality gate FAIL.
  객관 진단은 document Recall@5 0.845679, set-13 Macro F1 0.232845다.
- Safety boundary: 질문·답변·근거·판정 사유는 Git과 stdout에 기록하지 않고 ignored private
  artifact에만 보존했다. 공개 기록은 aggregate와 hash만 포함한다.
- Known limitation: 기존 실행이 기권 최종 문구를 보존하지 않아 정답 기권 2건은 의미를
  추정하지 않고 `needs_human`으로 남겼다. 골든 정답·qrel 승인과 run 품질 판정은 별도다.
- Next TODO: 과도한 기권과 인용 타당성 실패를 우선 개선한 뒤 동일 56문항으로 회귀 평가한다.

## 2026-08-31 — supplemental 69 evaluation draft

- Intent: 취합 136에서 유지한 44/13/12를 기존 dev40과 분리된 실행 자산으로 준비한다.
- Change summary: 56 answer draft, 13 set draft, qrel review queue, case-hash decision,
  manifest-aware set scorer와 pinned CSV support ref를 구현했다.
- Safety boundary: 질문·정답·근거는 ignored private 경로에만 두고 로그에는 수량·hash·상태만 남겼다.
- Verified: 112/112 legacy SHA mapping, 11 correction gate, B14=7, deterministic outputs,
  evaluation 83/83, full 546/546 PASS.
- Known limitation: named human approval은 0/69이므로 official 점수로 승격할 수 없다. 다만 draft
  69개는 명시적으로 `provisional` 실행·채점할 수 있다.
- Next TODO: 고정 OpenAI baseline을 실행한 뒤 팀원이 review queue와 정답 정합성을 검수한다.

## 2026-08-31 — supplemental provisional baseline activation

- Intent: 검수 대기 69문항을 실행 불가 상태로 두지 않고, official 승격과 분리된 잠정 기준선으로
  실제 스택 최적화에 사용할 수 있게 고정한다.
- Change summary: refined 98 page-only, `text-embedding-3-small`, `gpt-5-mini`, top-10/context-5,
  citation 3, USD 2.00 설정을 hash로 고정했다. answer/set scorer, strict run schema, case별 atomic
  checkpoint/resume, content-free public receipt와 명시적 OpenAI egress gate를 구현했다.
- Safety boundary: private 질문·답변·run·문서 발췌는 ignored 경로에만 둔다. 실제 provider 실행은
  `--approve-private-corpus-egress`가 없으면 stack 생성 전 중단한다.
- Verified: frozen config preflight 56+13/98/9,331, 두 private build byte 동일, provisional validation
  PASS, official 69건 `case_not_approved`, evaluation 83/83, 전체 546/546.
- Known limitation: 실제 OpenAI run과 aggregate metric receipt는 egress 승인 뒤 생성한다.
- Next TODO: baseline code/config를 선별 commit·push하고 승인된 실제 69건 run을 실행한다.

## 2026-08-31 — Mini131 frozen baseline harness

- Intent: 기존 Mini exact 39건을 보존하고 재실행 90건과 parser 2건을 동일한 131건 ledger로
  평가하되 후보 스택과 고정 Sol 판정기를 분리한다.
- Change summary: Core40, Gap30, Visual/EDA 실행기와 runtime hash/resume/budget gate, opaque blind
  judge input, primary-secondary-adjudicator 이력, parser receipt 교차검증, private HTML을 구현했다.
- Safety boundary: corpus 재임베딩은 하지 않고 질문 임베딩만 허용한다. 질문·답변·근거·판정사유는
  ignored private 경로에만 두며 공개 receipt는 수량·비용·hash만 담는다.
- Verified: 세 preflight PASS(provider 0), parser C21/C22 2/2, 평가 범위 90/90,
  최초 전체 unittest 679/679, in-memory syntax 7개와 diff check PASS.
- Concurrent drift: 이후 별도 작업이 visual schema 필수 필드를 추가해 기존 fixture 1건이 실패했다.
  해당 파일은 수정하지 않았고 평가 범위는 재실행해 90/90 PASS를 유지했다.
- Blocker: OpenAI API에 보낼 private payload 종류와 최대 140회/$4를 명시 승인받기 전에는
  Mini 90건 실행, 129건 Sol 판정, 최종 HTML·receipt와 commit/push를 진행하지 않는다.

## 2026-08-31 — Mini131 live execution and frozen Sol scoring

- Intent: 승인된 범위에서 최초 통합 Mini 기준선을 끝까지 실행하고, 후보 답변을 고치지 않은 채
  고정 Sol 의미 채점기로 129개를 모두 판정한다.
- Candidate execution: 기존 exact 답변 39개를 계보 표시와 함께 보존하고 Core40, Gap30,
  Visual/EDA20을 prospectively 실행했다. corpus 재임베딩은 하지 않았고 query embedding만 수행했다.
- Provider recovery: Core API 연결 오류 2건과 Gap Structured Outputs 400 1건을 원래 error로
  보존하고 재시도하지 않았다. `uniqueItems`는 이후 요청에서 제거하고 중복성은 앱에서 검증했다.
- Judge workflow: blind primary 129, crossed secondary 13, fresh adjudicator 13을 고정
  `gpt-5.6-sol`/high로 실행했다. 모든 reviewer 입력·출력과 역할 순서를 private history에 남겼다.
- Final result: 평균 54.845, accepted 58, rejected 71, unresolved 0; parser 2/2 PASS.
  후보 비용 USD 0.21345322, source transcript 129/129, HTML 131카드다.
- Verification: Mini131 preflight 28/28·RAG 129, private mode 0600/public receipt 0644,
  evaluation 210/210과 전체 unittest 728/728 PASS. staged clean-checkout snapshot은 614개 PASS,
  private artifact가 없는 통합 테스트 8개만 의도대로 skip했다.
- Safety boundary: 문항·답변·근거·provider payload·판정 사유는 `evaluation/private/**`에만 두고,
  Git에는 content-free receipt·코드·합성 테스트·운영 문서만 포함한다.

## 2026-09-07 — EH2.6.c4.2.a lexical 실행·전이2

- Intent: ordinal2 결정에서 같은 exact dense obligation의 lexical 실행을 연결한다.
- Change: private lexical executor/readback, shared bounded transition, stable root와 immediate predecessor 분리.
- Repair: 미완성 factory wiring8개를 연결하고 authority seal 이후 dependency pin을 고정했다.
- Verified: lexical12·집중36·관련98·격리134·전체1534 PASS, fresh Astra APPROVE.
- Boundary: state/semantic fingerprint는 그대로이며 fusion/terminal/public Controller는 후속이다. 실모델/API 실행0.
- Next: 검수 제약을 적용한 d2.x.b. 증거와 통합 영수증은 work/collaboration/eh-relay-20260907/ 참조.
