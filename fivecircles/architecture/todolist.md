# MidProjectRAG Task List

- [x] **TEST-ENV-20260906** 프로젝트 `.venv` 의존성 동기화·pip check 및 ML lock32 일치. 기존 실패 영역153/153·전체1498/1498 PASS(오류/실패/skip0). 실행 명령·오류 기록 정정.

## 현재 실행 큐 — 검색 비교 우선 (2026-09-05 승인)

목적: baseline을 immutable control로 두고 동일 Mini131의 검색 품질·효율을 측정해 개선 축을 선택한다.
연구안 전체/Controller 전체 구현이 첫 retrieval-only 비교의 선행 조건은 아니다.
아래는 **기존 ID의 실행 순서 참조**이며 중복 TODO가 아니다. Phase 상세 목록/완료 이력은 보존한다.
현재 폼·검증·릴레이: `../work/2026-09-05-search-first-relay.md`.

| 순서 | 기존 TODO / 단위 | 실행 조건·결과 |
| --- | --- | --- |
| 0 | 실행 큐·소유권·checkpoint/resume 정합화 | 완료·01426df push. 기존 체크박스 보존 |
| 1 | EH2.EVAL.4.a → 4.b / 4.c | .a/.b 구현·private131 생성 완료; 위치 의미 승인/보강 .c는 잔여 |
| 2 완료 | EH4.7b.1 → b.2 | recorder·실제 로컬12회 PASS; qrels/질문 제작 책임 없음 |
| 3 결정 필요 | EH4.7c.1 / .2.a.2.i 완료 → .ii | 재채점·전체131 사전 감사 완료. 비교 범위/승인·평가기준 확정 필요 |
| 4 | EXP-SELECT.3.a | 동일 승인 qrels에서 page KURE / compat child KURE / child+Kiwi BM25·RRF paired run |
| 5 | EXP-SELECT.3.b | 실패 경계·품질/효율 delta로 다음 개선 축 선택. 모든 연구 아이디어 자동 구현 금지 |
| 6 | 선택된 개선 + EH2/EH3/EH4 후속 | Controller·전문 경로·생성/인용·E2E는 해당 기존 선행 gate를 유지 |

- 순서 세부: EXP-SELECT.2.a의 최소 설정 schema 정의는 EH4.7b.1 전에 한다.
  승인 qrels·사전 threshold를 포함한 정식 freeze는 b.2 smoke 후, EXP-SELECT.3.a 실행 전에 완료한다.
- `EH2.6.c4.0`과 `EH2.6.c4.1`은 구현·검증 **DONE**이다. 최초 dense의 effect/ledger1 전이가 연결됐다.
  다음은 `EH2.6.d2.x`를 작은 ledger-aware decision 단위로 나누어 진행한다. 실제 E2E는 아직 미완성이다.
- 1~3의 코드/연결 smoke는 전체 EH2.G/EH3.G를 기다리지 않는 승인된 retrieval-only 예외다.
  공식 비교는 EVAL.4.c의 해당 지표 qrel 승인·EXP-SELECT.2.a 동결 후에만 실행한다.
- qrels/검수 lineage 단일 원천=EH2.EVAL.4, resolver/채점/기록=EH4.7, 비교 설정/선택=EXP-SELECT.
  resolver 구현 완료를 EVAL-GOLDSET 전체 완료로 세지 않는다. sealed holdout=EH2.EVAL.5~6 유지.
- 상태는 `코드 구현 / 실제 실행 / 품질 측정`으로 분리한다. Mini131 전체 inventory와 지표별
  eligible/missing/not-applicable 수를 함께 표시한다. 질문·답변·보조69 검수·11건 수정은 재사용한다.
- 현재 child는 `compat-newline-1600-v1`이다. 구조화 청킹 개선 완료로 부르지 않는다.
  VLM·API·기본 profile·기존 source/index는 이번 순서 변경으로 수정하거나 재실행하지 않는다.

## EH-RC0 — Evidence-Harness 재귀 실행 TODO (2026-09-03)

계약: `specs/bidfit-evidence-harness-v1-rc0.md`.
재개 지점: `../work/bidfit-evidence-harness-v1-rc0-checkpoint.md`.
원샷 전체 원장: `../work/bidfit-evidence-harness-v1-rc0-one-shot.md`.
사용자 최신 지시: 큰 범위를 재귀적으로 쪼개고 작은 작업을 하나씩 처리한다.
기존 아래 TODO/완료 이력은 그대로 보존한다.

### 실행 규칙 — 큰 항목을 한꺼번에 구현하지 않는다

- 구조: `EH-RC0 → Phase → leaf → 필요할 때 하위 leaf`. 실행 중인 leaf는 최대 1개다.
- leaf의 기본 크기: 한 가지 동작/불변식, 주 수정 파일 1~3개, 독립 focused test 1개 묶음.
  서로 다른 모듈/외부 의존성/판정 기준이 섞이면 `EH1.5.a`, `EH1.5.b`처럼 다시 나눈다.
- 각 leaf는 `계약 확인 → 실패 재현/테스트 → 구현 → focused 검증 → 체크포인트`로 닫는다.
  하위 항목이 생기면 부모는 직접 실행하지 않고 모든 자식의 검증이 끝나야 완료한다.
- `[ ]`는 미완료다. READY/IN_PROGRESS/BLOCKED와 검증 근거는 체크포인트에 기록한다.
  코드 구현, 실물 실행, 품질 측정은 서로 다른 항목이며 대신 완료 처리하지 않는다.
- 다음 leaf는 선행 의존성이 끝난 것만 선택한다. 순서 변경은 이유를 원장에 기록한다.
  구현은 순차, 별도 리뷰만 필요시 좁은 범위로 병렬 수행한다.
- 재개 시 체크포인트 + 현재 leaf의 계약 절/대상 파일만 읽는다. 전체 첨부/감사/리서치를
  반복 로드하지 않는다. 새 판단이 필요한 경우에만 원문 요구사항을 해당 절까지 조회한다.
- 전체 회귀는 Phase gate/통합 경계/최종 납품 때 실행한다. 모든 leaf마다 전체 suite나
  전체 Mermaid/HTML을 재생성하지 않는다. 실패는 해당 leaf만 재귀 분할해 수리한다.
- 공통 완료 기준을 공유하는 관련 leaf는 한 납품 cycle로 묶되 구현은 순차 처리한다.
  leaf=집중 검증·짧은 checkpoint, cycle=영향 기반 회귀·리뷰·보고·로그올·선택 push·다음 새 폼이다.
- 기존 artifact는 불변, 새 corpus/index/trace는 private 새 namespace에만 생성한다.
  외부 모델/실측 불가는 BLOCKED 또는 unavailable로 남기며 synthetic PASS로 대체하지 않는다.

### EXP-SELECT — baseline control → challenger → golden 선택 gate

- [x] **EXP-SELECT.1** 기준선을 최종 구조가 아닌 immutable control로, GPT research·EvoHarness·통합안을
  challenger hypothesis로 고정한다. 권위: `requirements/decisions.md` D-024,
  `requirements/current.md` §1.1, `specs/assembly-on-research-and-exp.md`의 실험 목적 계약.
- [ ] **EXP-SELECT.2** baseline/API control, local control과 각 challenger의 corpus/gold/qrels/judge/scope/
  budget/config hash 및 사전 metric threshold를 하나의 freeze receipt로 고정한다.
  - [ ] **EXP-SELECT.2.a** 선행 retrieval-only 동결: Mini131 입력·승인 qrels·source/store/index/KURE revision,
    동일 query 전처리/history/user scope·@k/중복 gain·lane 후보 수/RRF k/context 문자 예산·cache/측정 구간·
    source/code/config/scorer hash·사전 통과 기준을 고정한다. API/생성 judge는 미사용으로 표시한다.
    recorder 최소 설정 schema는 EH4.7b.1 전에 정의하고, 구성별 `pre_context_stage`도 지정한다.
    dense-only의 직전 단계는 lane_dense, hybrid는 fusion이다. b.2 smoke와 정식 동결/품질 판정을 구분한다.
    - [x] **EXP-SELECT.2.a.1** recorder용 local3종 closed draft 설정/검증 구현. focused8·관련58·독립 APPROVE.
      query/scope/history·예산·pre_context_stage·hash 구분, formal 승격/gold필드 거절. 실파일binding/정식 freeze는 다음 gate.
    - [ ] **EXP-SELECT.2.a.2** 승인 qrels/paired 분모·실물 artifact·지표 threshold를 정식 freeze receipt로 봉인한다.
      - [x] **EXP-SELECT.2.a.2.i** 전체131 모델0 사전 감사 완료. 관련127 PASS/독립 APPROVE, source와 요청 질문/이력/범위 결합.
        기술적 source30/doc84 후보, set13 request 없음. finalizer refs4필드/부분집합 차이 기록; 공식분모는 null 유지.
      - [ ] **EXP-SELECT.2.a.2.ii** `[WAIT_USER_DECISION]` metric/cutoff/threshold·오류 처리·paired 범위와 해당 qrels의 사람 승인을 확정한다.
        기존69 검수 이력은 보존/재사용하되 새로운 골드 승인으로 자동 승격하지 않는다. 전체131 ledger는 유지한다.
      - [ ] **EXP-SELECT.2.a.2.iii** 확정된 입력만 closed freeze로 검증·봉인한다. 기술 가용성이나 과거 검수 요약을 승인서로 대체하지 않는다.
  - [ ] **EXP-SELECT.2.b** E2E/후속 구성은 .2.a를 참조하고 generator/prompt/judge·추가 축만 확장 동결한다.
- [ ] **EXP-SELECT.3** parser→chunker→embedder→fusion→reranker→Harness 순으로 한 축씩 component ablation을
  실행하고 retrieval 품질·효율·guardrail을 분리 기록한다. 구현 회귀 PASS를 품질 향상으로 대체하지 않는다.
  - [ ] **EXP-SELECT.3.a** 선행 3종 검색 비교: page KURE(control) / compat child KURE / 같은 child+Kiwi·RRF.
    page→child는 granularity 축, child→hybrid는 fusion 축으로 분리한다. 전체131 ledger를 유지하되
    visual10/analytics10/parser2는 전용 평가로 표시하고 공통 paired eligible subset과 제외 사유를 공개한다.
    paired subset은 승인 qrel/지원범위로 실행 전에 봉인한다. arm 오류·stage 누락으로 사후 분모를
    줄이지 않으며 구성별 unavailable을 전체131 ledger 및 고정 paired 분모와 함께 보고한다.
  - [ ] **EXP-SELECT.3.b** 최초 실패를 위치 qrel/representation·retrieval·context·generation으로 구분한다.
    해당 단계 미실행이면 원인을 확정하지 않는다. 결과에 따라 다음 개선 TODO의 실행 순서를 재선택한다.
- [ ] **EXP-SELECT.4** 선택된 구성요소를 조립한 local-first challenger를 동일 frozen golden에서 baseline과
  E2E 비교한다. 실제 provider 실행 때만 Langfuse를 opt-in하고 trace/latency/token/cost를 계측한다.
- [ ] **EXP-SELECT.5** gate/Pareto 판정과 사람 리뷰 뒤에만 `feat/local-qwen-mini131-eval`의 기본 profile을
  전환한다. mixed/loss면 baseline 유지; winner여도 baseline artifact와 rollback 경로를 삭제하지 않는다.

### EH-A — 시작 기준선 (완료)

- [x] **EH-A.1** 현재 checkout/dirty 소유권/다른 branch와 경계를 감사한다. 근거: `feat/vlm-visual-retrieval`, `7ad229f`, 시작 tracked 수정 39개 보존.
- [x] **EH-A.2** 수정 전 회귀를 확보한다. 근거: `PYTHONPATH=src .venv/bin/python -m unittest discover -q -s tests -t .` → 805 tests, 실패/skip 0.
- [x] **EH-A.3** target/current flow와 구현 계약을 만든다. PNG 생성 완료; 브라우저 검증은 EH-D.3에서 별도 수행한다.

### EH-CONTEXT — 중단 복구용 보관 (별도 보조 작업)

- [x] **EH-CONTEXT.1** 사용자 원문 프롬프트·핵심 문서·재개 안내를 private 새 ZIP으로 보관했다. 24파일, SHA-256/CRC/원문 동일성/Git 제외 PASS. 재개 안내: `../work/bidfit-evidence-harness-v1-rc0-resume.md`. 앱 구현 leaf는 EH0.1.a로 유지.

### Phase 0 — 무결성부터 고정 (선행: EH-A)

- [x] **EH0.1** runtime/evaluation DTO와 allowlist projection을 분리했다. 9 focused tests PASS; planner 통합 lineage는 EH2.G에서 재검증.
  - [x] **EH0.1.a** runtime 입력 필드·거부 규칙 계약과 regression fixture를 작성했다. TDD red: 새 모듈 부재 ImportError 1건, 구현은 다음 b.
  - [x] **EH0.1.b** frozen RuntimeRequest/EvaluationCase 및 projection 구현. 닫힌 nested schema·mutation 방지 포함.
  - [x] **EH0.1.c** gold 값 metamorphic 직렬화/해시 불변 PASS. 명시적 user scope와 gold ID가 같아도 정상 입력 유지.
- [x] **EH0.2** None/empty/nonempty scope와 모든 lane 공통 empty short-circuit 구현. scope/filter 포함 focused 16 tests PASS.
- [x] **EH0.3** 미지원 predicate를 unsupported/unresolved로 명시. 실제 planner 실행 fail-closed 연결은 EH2.2 gate.
- [x] **EH0.4** 금액·날짜 정규화 구현. 쉼표/한글단위/ISO·점·한국어 날짜 동치, 숫자·날짜 뒤바뀜 회귀 PASS.
- [x] **EH0.5** 제한적 조사/괄호/어순 정규화·전체 파일명 보호 구현. entity-value association은 보존; semantic 평가는 아님.
- [x] **EH0.6** 부분/전체 기권·error·반대 극성을 분리. 숫자 일치+반대 극성 거부 회귀 PASS.
- [x] **EH0.7** provider-free replay CLI 구현. 실제 저장 답변 129건/source-case SHA 129건 일치, 새 private namespace, 기존 답변 불변.
- [x] **EH0.G** focused 47·전체 852 tests PASS/skip 0. 리뷰 5항목 수리/18재현 PASS. HTML browser PASS; 앱 연결은 EH2.G의 별도 gate.

### Phase 1 — Evidence와 검색 (선행: EH0.G)

- [x] **EH1.1** frozen/content-addressed Evidence/ProvenanceParent/Locator 구현. focused 7 PASS; 원문 char_range로 반복 occurrence 구별, 빈 crop-backed figure 허용.
- [x] **EH1.2** immutable EvidenceStore 구현. 타입/store 합계 13 PASS; parent/doc/source/span/locator/support graph 검증, 중복 거부, scoped child-only 조회.
- [x] **EH1.3** compat newline 1,600자 splitter/source-bound builder 구현. 타입/store/builder 17 PASS; 기존 split 출력 일치, 반복 span·source chunk ID 보존.
- [x] **EH1.4** heading/paragraph splitter + private bundle freeze/load 구현. 합계20 PASS; chunker/config/file/bundle hash, 원문 span, overwrite·경로 이탈 거부.
- [x] **EH1.5** pinned KURE child build/load/search 구현. synthetic provider 2 focused PASS; 1,024차원/row/vector/bundle identity, empty encoder 0회. 실제 빌드는 EH1.10.
- [x] **EH1.6** LegacyPageLane control 연결. 실제 ExactDenseIndex synthetic test PASS; page granularity/source ID 보존, child와 혼합하지 않음.
- [x] **EH1.7** Kiwi 0.23.2/model0.23.0 설치·pin, 독립 BM25+token artifact 구현. 2 focused PASS(실제 한국어 Kiwi 포함); 사전/모델 파일 SHA, query tokens/scope/tie 추적.
- [x] **EH1.8** 독립 budget + RRF k=60 연결. 3 focused PASS; lexical-only rescue, rank/formula/doc coverage, mixed granularity 거부, empty lane 호출0.
- [x] **EH1.9** bounded parent window + selector 구현. 3 focused PASS; char budget/필수 근거/요구 문서 coverage, 누락 명시, parent는 직접 인용 후보가 아님.
- [x] **EH1.10** 실제 private artifact 생성. 98docs/9,331 parent/9,496 child, KURE1024+Kiwi2,065,474 tokens; source unchanged, old/new SHA receipt, 생성0.
- [x] **EH1.G** Phase 1 gate PASS. focused35/full887/skip0, safety780, browser PASS, real child+legacy load/search, 리뷰 P1 3건 수리·재현 PASS. 성능 향상 주장 없음.

### Phase 2 — 계획과 bounded 실행 (선행: EH1.G)

전달 원칙(2026-09-04): VLM 직후 보존 상태는 `feat/vlm-visual-retrieval`에 유지하고, 후속 작업 브랜치는
`feat/total-integration`으로 통일했다. 이 통합 작업대에서 전체 범위를 구현·검증한 뒤
`feat/local-qwen-mini131-eval`에 병합한다.
runtime은 local profile 기본·LLM provider 교체형으로 유지하며 새 브랜치를 만들거나 API를 자동 호출하지 않는다.

#### EH2.EVAL — 기존 평가 Batch 2 흡수

소유권: `specs/evaluation-contract.md`가 질문·split·qrels·hash의 단일 원천이다. EH Phase 2는
평가 스키마를 복제하지 않고 실행 stage receipt만 제공한다. 리뷰:
`../work/review/review-eval-batch2-eh2-sequencing-2026-09-04.md`.

- [x] **EH2.EVAL.1 / EVAL-FOUNDATION** 공통 Schema, 누수 검사, hash, metrics와
  `validate/score/compare` CLI가 이미 완료됐음을 확인하고 재구현 범위에서 제외한다.
- [x] **EH2.EVAL.2 / CONTRACT-DELTA** 별도 전후 질문셋 없이 동일 qrels를 사용하고,
  dense/lexical raw lane→fusion→rerank→final context checkpoint와 stable source/object anchor,
  evaluator-only join 계약을 `evaluation-contract.md` §9.1 및 EH2 계약에 고정한다.
- [x] **EH2.EVAL.3 / DEV-INVENTORY** 기존 dev40 draft·52 source-block reference의 자동 검증 완료와
  named human 승인 0건을 확인한다. 이를 신규 40문항 작성으로 중복 계산하지 않는다.
- [ ] **EH2.EVAL.4 / EVAL-GOLDSET** 기존 Mini131 질문·답변과 보조69 홍우석 검수/11건 수정 기록을 재사용한다.
  strict dev40의 정형 승인 필드와 전체 사람 검수 유무를 구분하고 부족한 stable source anchor 위치만 보강한다.
  EDA10 strict 변환은 이미 존재하며 이번 ‘131+추가 지표’ 범위에 신규 문항으로 넣지 않는다.
  evaluator-only `AnchorResolutionReceipt`/청킹 변경 join 구현은 `EH4.7a.1`에서 연결했다.
  잔여: 전체131 sidecar 매핑·기존 검수 lineage 확인·positive/hard-negative 확정. gold는 runtime에 넣지 않는다.
  - 중복 방지 코멘트(2026-09-05): 위 `AnchorResolutionReceipt`/청킹 변경 join 구현·회귀는 `EH4.7a.1`에서 한 번만 수행하고 여기서는 해당 결과를 참조한다. qrels 보강·검수 책임은 이 항목에 유지하며, resolver 완료를 이 항목 전체 완료나 별도 구현 성과로 중복 계산하지 않는다.
  - [x] **EH2.EVAL.4.a** 기존 pinned8 source SHA/count·RAG129+parser2·고유ID131 검증.
    core30 answer/52 refs의 owner+locator 일치, supplemental69 block refs0. 기존69 검수/11수정 이력과 draft 필드를 구분한다.
  - [x] **EH2.EVAL.4.b** evaluator-only sidecar/가용성 adapter 구현. 집중15·관련65 PASS, 독립 APPROVE.
    기존131 private 생성: ready30/missing67/not-applicable34, 원문 owner/locator·source SHA 검증.
    질문/답변/검수 불변·후보186 gold 비승격·request/모델/API 생성0. 공식 비교 승인은 .4.c/EXP-SELECT.2.a 별도.
  - [ ] **EH2.EVAL.4.c** 기존 사람 검수 근거를 연결하고 부족한 positive/hard-negative 위치를 원문으로 보강·
    승인한다. 자동 ID/hash 검사를 의미 승인으로 승격하지 않는다. 전체 inventory와 지표별 승인 분모를 봉인한다.
- [ ] **EH2.EVAL.5 / SEALED-HOLDOUT** 이미 실행된 RAG129를 사후 held-out으로 바꾸지 않는다.
  별도 20건의 count 계약·격리 담당을 먼저 확정한 뒤 작성·2인 교차검토·순서/hash 봉인을 수행한다.
- [ ] **EH2.EVAL.6 / EVAL-RUN** dev/qrels 승인 전 tuning·우승 주장을 금지하고, sealed held-out은
  최종 config 동결 뒤 EH4.10~11에서 한 번만 실행한다. EH2.G는 합성 E2E·gold injection 차단·
  lineage·controller 종료와 Mini131 회귀만 담당한다.

- [x] **EH2.1** QueryPlan/budget과 versioned rule registry 구현. 닫힌 frozen/slotted DTO,
  query-type 예산 단일 원천, registry-bound plan load/hash 검증, unresolved 명시. focused27·전체898 PASS,
  독립 리뷰 P1 2건 수리 후 재리뷰 PASS.
- [x] **EH2.2** 결정론 planner 구현. production metadata에서만 파생되는 hash-attested catalog,
  gold-free rule routing, entity/predicate/scope provenance, fail-closed empty/ambiguity, Korean 표현 경계를 연결했다.
  focused51·전체922 PASS; 독립 감사에서 catalog 위조·alias 겹침/모호성·DTO 변조·JSON 배열
  shape·실제 list/count/table 문장 P1을 재현해 수리한 뒤 최종 PASS.
- [x] **EH2.3** 실제 citation-state 기반 follow-up 구현. 최신 assistant의 실제 cited doc/evidence를
  동일 EvidenceStore에서 재검증하고 hard scope와 교집합했다. 검증된 primary evidence progress가 부족할 때만
  순수 citation scope에서 global fallback 1회를 허용하며 primary/fallback을 분리했다. 후보 수 기반 충분성,
  raw bool, evaluator/provider trace 본문 유입을 차단했다. binding/retrieval 모듈을 분리했고 focused61·전체943
  PASS, 독립 리뷰 P1 3종(scope 위조·trace body·verifier ID)을 수리한 뒤 최종 PASS.
- [x] **EH2.4** compare의 doc×field slot을 구현했다. 전체 doc-major slot matrix, singleton-scoped
  search/field-relevance receipt, provisional missing과 문서 coverage를 봉인했고 typed receipt 없는
  verified/contradicted·조기 정상 종료를 차단했다. production retriever와 factory-issued binding/coverage
  identity를 재검증한다. focused107·전체987 PASS, 독립 리뷰 P1 수리 후 최종 PASS.
- [x] **EH2.5** Belief/Progress/typed Action을 구현했다. 상태 직렬화·허용 action 산출·decision-chain 회귀를 봉인했다. 실제 state transition/action-effect receipt는 EH2.6에서 구현한다.
  - [x] **EH2.5.a** 현재 EH2.3/EH2.4와 prototype을 read-only 감사하고 pure state/action 계약을 고정한다.
  - [x] **EH2.5.b** follow-up bound/attempt/progress/outcome을 factory identity·전체 hash·exact bound/store chain으로 봉인했다. focused34·전체1000 PASS, side-effect-first P1 수정 후 독립 리뷰 PASS.
  - [x] **EH2.5.c** compare/follow-up `Belief`·`Progress`·`HarnessState` projection/replay를 구현했다. factory/exact identity, live store canonical payload, source 재구성 replay를 봉인했고 focused9·전체1009 PASS(독립 P1 수정 후 재검토 PASS).
  - [x] **EH2.5.d** closed typed action·deterministic allowed order·decision hash chain을 구현했다. mixed contradiction 전역 abstain gate, sealed-store parent/bridge eligibility, strict replay를 포함해 focused10·state 통합19·전체1019 PASS, 독립 리뷰 PASS.
  - [x] **EH2.5.e** adversarial focused55·전체1020 회귀와 독립 리뷰를 통과했다. live store 및 `BoundCompare` nested identity P1을 수리·재검토하고 부모를 완료 처리했다.
- [ ] **EH2.6** E0/E1 bounded controller를 연결한다. 완료: fact/compare/follow-up의 독립 lane·effect·transition,
  round/action/deadline/no-progress 종료, 필수 obligation 검증 후 ready/partial abstain을 정확히 구분한다.
  - [x] **EH2.6.a** 실행 전 계약과 gap을 봉인했다.
    - [x] **EH2.6.a1** EH2.3~2.5와 retrieval runtime을 read-only 감사해 cross-state decision, hybrid lane,
      fact state, follow-up slot projection gap을 재현했다.
    - [x] **EH2.6.a2** §16.10과 module contract에 E0/E1 경계, DTO, action order, absence/reducer/종료/replay를 고정했다.
    - [x] **EH2.6.a3** 독립 계약 재리뷰 PASS로 P0/P1을 닫고 public owner API/구현 파일 경계를 확정했다.
  - [x] **EH2.6.b** source/runtime/검색 receipt 기반을 구현했다.
    - [x] **EH2.6.b1** planner replay·catalog/config/store-bound `BoundFact`와 fact 초기 state를 구현하고,
      unknown/stale doc 및 fact metadata predicate를 EH3.1 receipt 전까지 not-ready로 닫았다.
      follow-up metadata safe projection은 EH2.6.c1에서 닫는다. focused47·전체1034·독립 리뷰 PASS.
    - [x] **EH2.6.b2** context target quota를 포함한 immutable `HarnessExecutionConfig`와 exact nested
      lane/verifier/reranker identity의 production/synthetic runtime authority를 구현했다. evidence/dense/lexical/
      fusion/root 진입 gate와 registry entry까지 호출 전 봉인했으며 focused104·전체1109·safety811,
      독립 P1 10건 수리 후 최종 재리뷰 PASS.
    - [x] **EH2.6.b3** (선행: EH2.EVAL.2) owner-issued `RetrievalObligation`과 dense/lexical
      `LaneSearchReceipt`를 분리하고 public execution boundary에서 query/scope/budget/store/call 전
      검증·exact-once 소비를 봉인한다. 최초 focused36·관련186·전체1147·safety823 및 독립 리뷰를
      통과했으나 exact code를 공유하는 copied-globals executor clone 가설을 닫기 위해 재개했다.
      - [x] **EH2.6.b3.r1** ledger mutation은 issued executor의 exact code뿐 아니라 exact module-global
        namespace에서 온 frame만 허용한다. copied-globals clone이 provider 호출 0회로 permit/receipt를
        만들 수 없음을 회귀로 고정했다. b4와 함께 b3+b4 focused64·관련214·전체1175·독립 재리뷰를
        통과해 재개 상태를 닫았다.
    - [x] **EH2.6.b4** same-round `FusionReceipt`와 state 없는 E0 control receipt를 구현했다. visual 자리 때문에
      stage ordinal 4를 유지하고 dense→lexical→fusion의 obligation별 순서, exact-once fusion/E0 claim,
      post-provider child 재검증, closure-cell pin, receipt 수명과 독립적인 dual immutable history를 봉인했다.
      focused27·b3+b4 64·관련214·전체1175 PASS, API/model/Langfuse 호출 0, 독립 최종 리뷰 PASS.
    - [x] **EH2.6.b5** 독립 lane·lexical rescue·fact empty·호출 전 거부 focused gate를 통과했다.
      dense-empty→lexical-only fusion, fact all-empty retrieval-complete/state-free, pre-call zero-dispatch,
      provider-error lexical diagnostic/no-fusion을 전용 4건으로 고정하고 public validator·비누출까지 PASS.
  - [ ] **EH2.6.c** effect/reducer/absence transition을 구현한다.
    - [x] **EH2.6.c1** EH2.3 verified 주장을 candidate로 낮추고 follow-up 실제 slot에 doc-matching outcome
      candidate를 투영하며 추가 검색 0회를 고정했다. metadata predicate는 EH3.1 receipt 전까지 fail-closed,
      public extra/gold 입력과 foreign outcome/store clone을 차단했다. focused7·관련60 PASS, 독립 리뷰 3건 APPROVE.
    - [x] **EH2.6.c2** exact runtime verifier 호출로만 발급되는 supplied-evidence-bound semantic
      support/value/contradiction receipt를 구현했다. source-derived target, ID-less request, typed canonical
      result, unavailable zero-call과 local at-most-once를 봉인했고 focused26·관련118·전체1212·safety846 PASS.
      - [x] **EH2.6.c2.1** fact/compare/follow-up owner가 query와 supplied evidence를 유도하는 factory-only
        `SemanticVerificationObligation`, 닫힌 verifier request/result, typed canonical value 계약을 봉인한다.
      - [x] **EH2.6.c2.2** exact pinned verifier를 local at-most-once로 호출하고 unavailable zero-call 또는
        supplied-evidence-bound `SemanticVerificationReceipt`만 발급한다.
      - [x] **EH2.6.c2.3** clone/drift/mixed dependency, malformed output, contradiction independence,
        concurrency/replay/비누출 focused gate와 관련·전체·safety 회귀를 통과한다.
    - [ ] **EH2.6.c3** expansion/bridge/rerank/verify source receipt와 빈 후보 zero-provider exhaustion을
      포함한 bounded absence receipt를 구현하고, 최종 `ActionEffectReceipt` mint는 d2 decision permit 뒤로 닫는다.
      - [x] **EH2.6.c3.0** parent ID 부재, rerank source receipt 부재, d2 decision 선행 의존을 감사하고
        EH2.5 preview를 실행 권한으로 재사용하지 않는 source-receipt-first 계약으로 교정한다.
      - [x] **EH2.6.c3.1** immutable seed prefix 전체에서 parent=context-only와 table/figure actual bridge
        `applied|empty`를 caller ID 없이 발급하는 typed context receipt를 구현했다. root source 수명에 묶인
        at-most-once history로 중간 semantic obligation GC 뒤 재발급도 차단했다. focused8·관련114·전체1220·
        safety850 PASS, API/model/Langfuse 호출 0.
      - [x] **EH2.6.c3.2** ID-less exact-once rerank receipt와 parent/bridge/rerank를 반영한 derived semantic
        obligation을 구현하며 parent support/citation 승격을 금지한다.
        - [x] **EH2.6.c3.2.a** global rerank order↔role partition, owner `rerank_k`/`final_evidence_budget`,
          base/derived verifier slot과 parent unindexed ABI를 계약으로 교정한다.
        - [x] **EH2.6.c3.2.b** factory-only `RerankReceipt`와 exact one-call/zero-call unavailable,
          sanitized consumed failure·root-lifetime replay guard를 구현한다.
        - [x] **EH2.6.c3.2.c** rerank final prefix와 parent/bridge/rerank SHA에 묶인 derived semantic obligation을
          만들고 auxiliary parent를 support index 밖에 둔다.
        - [x] **EH2.6.c3.2.d** cross-role reorder, budget, base-vs-derived race, malformed/clone/GC/비누출
          focused gate와 관련·전체·safety 회귀를 통과한다.
      - [x] **EH2.6.c3.3** 모든 승인 경로가 bounded하게 닫힌 경우에만 three-reason
        `AbsenceConfirmationReceipt`를 zero-provider로 발급하고 timeout/error/unavailable/unresolved 단독 발급을 금지한다.
        - [x] **EH2.6.c3.3.a** fact/compare/follow-up별 세 reason과 exact prerequisite matrix,
          closed DTO/API, root-lifetime/nonpromotion 계약을 고정하고 TDD RED를 만든다.
        - [x] **EH2.6.c3.3.b** fact/compare의 모든 승인 검색 경로가 정상 empty로 닫힌 경우에만
          `bounded_no_candidate`를 owner-derived zero-provider receipt로 발급한다.
        - [x] **EH2.6.c3.3.c** nonempty 후보의 허용 verify 경로가 모두 정상 종결됐지만 support가 없을 때만
          `bounded_no_verified_support`를 발급하고 error/unavailable/drift를 차단한다.
        - [x] **EH2.6.c3.3.d** follow-up primary/승인 fallback exhaustion을 봉인하고 timeout/error/unavailable/
          unresolved/metadata predicate/partial·mixed lineage·단순 top-k empty의 no-mint와 회귀를 통과했다.
          cache-hit 재검증, closure-private authority, root-lifetime follow-up exact-once와 production/synthetic
          runtime kind 일치를 수리했으며 focused67·관련192·전체1267·safety858·독립 APPROVE·Playwright PASS다.
      - [x] **EH2.6.c3.4** closed `ActionEffectReceipt` DTO/validator를 추가하되 public mint는 exact d2
        `ControllerDecisionReceipt` permit 전까지 fail-closed한다.
        - [x] **EH2.6.c3.4.a** exact field/action-target/source-receipt/outcome/call matrix와 순수 validator의
          비권한 경계를 계약하고 public mint 부재를 TDD RED로 고정한다.
        - [x] **EH2.6.c3.4.b** `action_effects.py`에 module-token-only DTO와 closed structural validator를
          구현하고 package root에는 두 symbol만 공개한다.
        - [x] **EH2.6.c3.4.c** constructor/from-dict/public issuer 차단, serialization·malformed matrix,
          state/terminal/citation 비승격과 provider-zero focused gate를 통과했다. closed matrix는 source kind까지
          전수 교차검증했고 focused11·관련114·전체1278·safety861·독립 APPROVE를 확보했다.
      - [x] **EH2.6.c3.5** source/store/config/runtime clone·drift·mixed authority, replay/serialization,
        projection 비승격·비누출 focused gate와 관련·전체·safety 회귀를 통과한다.
        - [x] **EH2.6.c3.5.a** structural value와 d2/c4 live authority 책임을 분리하고 no-consumer/non-authority,
          representation 비누출 계약과 `repr` TDD RED를 고정한다.
        - [x] **EH2.6.c3.5.b** public/package callable·signature·module registry를 감사해 source/store/config/runtime
          clone·drift·mixed 입력이 effect authority로 승격될 현재 경로가 없음을 focused gate로 증명한다.
        - [x] **EH2.6.c3.5.c** equal-hash replay, exact/subclass clone, copy/pickle/from-dict, repr/to-dict,
          state/terminal/citation 비승격·금지 key/string과 provider-zero 회귀를 통과한다.
        - [x] **EH2.6.c3.5.d** 7종 source validator의 exact-class receipt/dependency clone·mixed graph를
          provider replay 없이 거절했다. focused18·관련147·전체1288·safety867, Playwright와 독립 APPROVE를
          통과했고 실제 API/model/Langfuse 호출은 0이다.
    - [ ] **EH2.6.c4** exact controller decision-bound `ActionEffectReceipt` mint, monotonic one-obligation reducer와
      hash-chained transition/no-progress를 구현한다.
      - [x] **EH2.6.c4.0** `[DONE]` opaque source-owner authority, ordered exact
        effect/outcome transition history, per-target parent/bridge issuer와 정식 structural-effect bridge를 추가한다.
        - [x] **EH2.6.c4.0.a** exact `BoundFact|BoundCompare|BoundFollowup`와 coverage/outcome/registry/policy를
          state 생성 시 private authority로 보존하고 `HarnessExecution`이 public payload 변경 없이 상속한다.
          equal-hash clone·사후 부착·legacy follow-up 승격과 validator/accessor drift를 차단했고 focused+인접43·
          전체1315·safety874·Playwright·독립 APPROVE를 통과했다. 외부 호출은 0이다.
        - [x] **EH2.6.c4.0.b** lane/fusion/parent/bridge/rerank/semantic/absence/decision receipt를 exact validator로
          역참조해 closed source kind·owner·outcome·call/evidence/context/absence projection으로 정규화했다.
          direct issuer·forced mutation·structural/equal-payload clone·cross-owner·dependency drift와 GC remint를
          차단했고 focused14·인접168·전체1329·safety877·Playwright를 통과했다. 외부 호출은 0이다.
        - [x] **EH2.6.c4.0.c** exact decision/source-owner preflight 뒤 closure-private one-step authority를
          claim-authorized prepare→source로 결합하고 shared lane attempt epoch/claim cutoff로 사후 receipt 포장을
          차단했다. duplicate/concurrent claim, direct resolver projection, clone/mixed/drift, claim·projection GC와
          post-child failure는 live execution 수명 동안 failed tombstone으로 닫았고 focused30·인접249·전체1359·
          safety881·독립 APPROVE를 통과했다. 외부 API/model/Langfuse/provider/clock 호출은 0이다.
        - [x] **EH2.6.c4.0.d** validated bounded context target에서만 parent/table/figure receipt를 exact-one 선택하고
          기존 rerank batch prerequisite의 canonical tuple identity/order를 보존하는 private accumulator를 구현했다.
          missing/duplicate/wrong-role/cross-root/clone·order drift와 live-root remint를 차단했고 focused13·인접175·
          전체1372·safety883·독립 APPROVE를 통과했다. 외부 API/model/Langfuse/provider/clock 호출은 0이다.
        - [x] **EH2.6.c4.0.e** `controller-structural-effect-bridge.md` 계약대로 exact sourced claim과 bounded
          target context를 closure-private 구조 재료로 결합했다. immutable/non-serializable/redacted bridge,
          same-object idempotence·root-lifetime remint tombstone, clone/mixed/out-of-order/retroactive/duplicate/
          GC/dependency gate를 focused7·관련50으로 검증했다. 최초1438건 환경 실패는 `.venv` 재실행으로
          해결했고 전체1498/1498 PASS를 확인했다. bridge 자체는 non-authorizing이며 추가 외부 호출은 0이다.
      - [x] **EH2.6.c4.1** initial decision permit의 selected action 하나만 exact source receipt/effect로 mint하고
        ledger claim·advance 및 transition authority를 구현한다.
        - [x] **EH2.6.c4.1.a** revision0 fact/compare selected dense의 source-derived live effect와 history 결합.
        - [x] **EH2.6.c4.1.b** same-state ledger revision1·transition·successor를 발급하고 predecessor authority를 유지.
        - [x] **EH2.6.c4.1.c** success/empty/error·중복/동시·변조·중간 실패를 신규13/인접91·전체1511 PASS로 검증. 독립 APPROVE.
          계약: `specs/controller-initial-transition.md`; 원장: `../work/2026-09-06-controller-initial-transition-relay.md`.
      - [ ] **EH2.6.c4.2** `[BLOCKED_BY_EH2.6.d2.x]` transition-aware full action matrix를 reducer에 연결한다.
        - [ ] 실제 verifier-context ID fingerprint와 successor GC 후 passive registry 정리 회귀를 포함한다.
    - [ ] **EH2.6.c5** verified/contradicted/confirmed-missing·raw bool/ID 공격 focused gate를 통과한다.
  - [ ] **EH2.6.d** bounded E1 controller와 replay를 구현한다.
    - [x] **EH2.6.d1** lane/action/capability/round 소비 스키마와 exact initial state/empty last-transition을
      함께 봉인하는 `ExecutionLedger`·`HarnessExecution` aggregate를 구현한다.
      - [x] **EH2.6.d1.a** controller ledger와 b3 `_RetrievalExecutionLedger`의 책임을 분리하고,
        initial-only schema·lifetime·non-authority 계약 및 첫 TDD RED를 고정한다.
      - [x] **EH2.6.d1.b** exact initial state/store/config/runtime에서만 idempotent하게 발급되는
        zero-consumption `ExecutionLedger`·`HarnessExecution`과 live validator를 구현한다.
      - [x] **EH2.6.d1.c** constructor/clone/nested drift/mixed dependency, repeat·concurrency·GC tombstone,
        serialization·public-surface 비승격과 provider/clock 0회 focused gate를 통과한다.
      - [x] **EH2.6.d1.d** focused10·관련234·전체1298·safety868, 독립 P0/P1 APPROVE와
        flow/HTML 검증을 통과했다. 실제 API/model/Langfuse/golden 호출은 0이다.
    - [ ] **EH2.6.d2** state+ledger 기반 allowed action과 cross-state `ControllerDecisionReceipt`, c4 effect mint
      permit을 구현한다.
      - [x] **EH2.6.d2.a** EH2.5 preview와 controller permit을 분리하고 ledger outcome/source-owner/per-target
        issuer 공백을 독립 감사했다. 전체 d2를 initial slice와 c4.0 뒤 cross-state slice로 분할하고 첫 RED를 고정했다.
      - [x] **EH2.6.d2.i** exact live revision-0 `fact|compare` all-unsearched execution에서만 stable
        `ControllerAction`과 selected-first `ControllerDecisionReceipt`를 발급·검증한다.
        - [x] **EH2.6.d2.i.1** exact order/signature, EH2.5·structural effect 비승격과 non-authorizing surface를 닫는다.
        - [x] **EH2.6.d2.i.2** repeat·32-thread single winner, GC tombstone, clone/nested tuple·action replacement,
          mixed graph·drift·serialization과 provider/clock 0회를 닫는다.
        - [x] **EH2.6.d2.i.3** 관련·전체·safety·독립 리뷰·flow/HTML·선택 push를 완료하되 parent d2는 열어 둔다.
      - [ ] **EH2.6.d2.x** `[READY / NEXT_RELAY]` exact transition/effect outcome과 source-owner
        authority로 consumed action/lane, fuse/context/capability eligibility와 cross-state chain을 완성한다.
      - [ ] **EH2.6.d2.d** d2.i+d2.x를 합친 full decision matrix와 c4 permit 연동을 회귀·리뷰한다.
    - [ ] **EH2.6.d3** start/step/run과 terminal `HarnessRunResult`를 구현한다.
    - [ ] **EH2.6.d4** action/round/deadline/post-deadline/no-progress/capability 종료를 호출 수까지 검증한다.
    - [ ] **EH2.6.d5** provider·clock 0회 strict execution replay와 fact/compare/follow-up 합성 E2E를 통과한다.
  - [ ] **EH2.6.e** authority clone/nested drift, mixed source/store/config/runtime, 악성 provider 출력,
    JSON scalar/shape·gold injection adversarial, focused/full 회귀와 독립 P0/P1 리뷰 후 부모를 완료 처리한다.
- [ ] **EH2.G** Phase 2 gate: 동일 합성 corpus의 단일/비교/후속 질의 end-to-end+gold-lineage 재검증+전체 회귀.

### Phase 3 — 전문 경로 (선행: EH2.G)

- [ ] **EH3.1** catalog predicate 실행기를 연결한다. 완료: 금액/날짜/기관/형식/긴급/재공고/category, unknown을 false로 숨기지 않음.
- [ ] **EH3.2** analytics 기본 연산을 구현한다. 완료: count/group/sum/mean/median/min/max의 null 정책 및 exact test.
- [ ] **EH3.3** analytics 확장·receipt를 구현한다. 완료: quantile/IQR/top-N share/outlier/ratio, corpus hash/formula/source/result.
- [ ] **EH3.4** 기존 analytics 10 fixture를 실제 재검증한다. 완료: RAG 평균과 분리한 exact result receipt; 원본 fixture 불변.
- [ ] **EH3.5** exhaustive list 전수 판정과 receipt를 구현한다. 완료: matched/rejected/unknown/visited/universe/complete 일관성, complete empty set.
- [ ] **EH3.6** list의 동적 context/citation을 연결한다. 완료: 미방문/unknown이면 incomplete, 고정 5개 인용 cap과 문서당 2LLM scan 없음.
- [ ] **EH3.7** table correction provenance schema/binding을 검증한다. 완료: hash/object/row-col/reviewer 승인 확인 전 수정값 사용 금지.
- [ ] **EH3.8** table/figure bridge를 연결한다. 완료: crop/occurrence 보존, text-first; image reader 부재는 visual_unavailable/부분 기권.
- [ ] **EH3.G** Phase 3 gate: analytics/list/table/visual 개별 결과+runtime 연동 회귀. full VLM 구현으로 표기하지 않음.

### Phase 4 — 생성·대조군·평가 (선행: EH3.G)

선행 예외: 상단 실행 큐의 EH4.7a/b/c.1 검색 평가·연결은 EH1.G 위에서 먼저 수행한다.
이 예외가 EH4.1~6·전문 경로·생성/E2E의 선행 gate를 생략한다는 뜻은 아니다.

- [ ] **EH4.1** IdentityReranker와 immutable candidate replay를 구현한다. 완료: 후보 ID/순서 보존, 동일 pool A/B 가능.
- [ ] **EH4.2** Qwen3-Reranker-0.6B optional adapter를 구현한다. 완료: score/model provenance/범위 검증, weight 없으면 unavailable. 실측은 별도.
- [ ] **EH4.3** structured claims/citations를 검증한다. 완료: claim→실제 EvidenceStore/parent/source/locator resolve; 문자열은 compatibility projection.
- [ ] **EH4.4** 교체형 generator profile을 연결한다. 완료: current_local/gpt5mini_api/qwen3_8b_awq 구분, 미보유 key/model은 unavailable, 무단 API 실행 없음.
- [ ] **EH4.5** 단일 versioned config로 R0~R4/E0~E1을 조립한다. 완료: budget/registry/artifact identity를 trace에 포함, E2는 연구/미활성 표시.
- [ ] **EH4.6** production CLI에서 opt-in harness 실행 경로를 연다. 완료: request→retrieval→harness→generator→structured result, legacy 유지.
- [ ] **EH4.7** retrieval/context/slot 계층 evaluator를 추가한다. 완료: Recall@1/3/5/10·MRR·nDCG·lane rescue·pre/post retention 별도 출력.
  - [x] **EH4.7a.1** 선행 승인(2026-09-05): Mini131 질문/답변·기존 보조69 검수를 유지하고 private source-anchor resolver를 만든다. 검증: owner/locator/hash/청킹 변경 join.
    - 상호 참조 코멘트(2026-09-05): `EH2.EVAL.4`의 resolver/receipt/join 회귀를 실행하는 단일 구현 leaf다. 그쪽에서 동일 기능을 다시 구현하지 않으며, 질문·정답·qrels 및 검수 책임은 `EH2.EVAL.4`를 참조한다. 상태 변경 시 동일 구현 결과를 연결하되 전체 항목을 일괄 완료 처리하지 않는다.
  - [x] **EH4.7a.2** 필수 근거 Recall 전후·관련 근거 retention·lane rescue 순수 채점. 검증: 중복 rank/분모0/미측정/실제 빈 검색.
  - [x] **EH4.7a.3** 단계 projection+오프라인 private CLI. 검증: 파일 E2E/chain 혼합 거절/원문·gold runtime 유입 없음.
  - [ ] **EH4.7a.G** 집중·관련 회귀/독립 리뷰/흐름 보고/로그. 네 핵심 지표 선행 leaf이며 EH4.7 전체·실제131 실측 완료와 구분.
    - 2026-09-05: 코드 집중·관련112 PASS, 실제98/20,118 source 검증, 리뷰 APPROVE, PNG/문서/로그 완료. 잔여는 HTML 브라우저 QA(file URL 정책 차단). 실제131 실측은 EH4.7b.
  - 계약: `specs/stage-evaluation-v1.md`. EDA10 추가/40개 축소/새 골든셋은 범위 밖. qrel 보강 원천은 `EH2.EVAL.4` 유지.
  - [x] **EH4.7b** 실제 검색 단계 recorder 연결·local12회 smoke 완료. Mini131 입력/qrels adapter는 EH2.EVAL.4.b,
    정식 paired 실측은 EXP-SELECT.3.a에서 한 번 수행한다. 없는 과거 단계를 역산하지 않는다.
    - [x] **EH4.7b.1** raw dense/lexical→전체 fusion→반환10/context5 기록기 구현. focused12·관련88 PASS/독립 APPROVE.
      관측 receipt와 EH2 live authority 구분, page 독립 provenance·content-free/error/unavailable 유지. 실제 모델 smoke는 b.2.
    - [x] **EH4.7b.2** offline KURE 실제12회 연결 PASS/관련93 PASS. 입력131 유지·sample2×3종×2회,
      동일 query/scope·반복 후보 일치·파일 불변·private0600. query embedding12/API·생성0, 품질 비교 아님.
  - [ ] **EH4.7c** MRR/nDCG·slot·문장/구간 완전성 등 나머지 계층 지표. block recall만으로 내용 완전성을 주장하지 않음.
    - [x] **EH4.7c.1** retrieval-only MRR/nDCG를 원문 anchor와 distinct-document 단위로 분리한다.
      @k/중복 gain/IDCG/qrel 결측·미실행 정의를 .7a 규칙과 정합화하고 합성 회귀한다. 공식값은 EXP-SELECT.3.a에서 측정한다.
      - [x] **EH4.7c.1.a** unique source-anchor / original document RR·binary nDCG 구현. focused24 PASS/독립 APPROVE.
      - [x] **EH4.7c.1.b** original doc qrels와 block 가용성 독립 연결. inventory/관련33 PASS, 전체 분모·hash 보존.
      - [x] **EH4.7c.1.c** CLI/전체131·unit별 집계/hash 통합. 관련118·독립 APPROVE, 실제12기록 재채점6파일 PASS/모델0.
    - [ ] **EH4.7c.2** slot·문장/구간 완전성은 해당 EH2/EH3 실행 기록을 확보한 후 별도 연결한다.
- [ ] **EH4.8** generation/list/analytics/visual 평가를 추가한다. 완료: 결정론/semantic adapter 분리, completeness/exact 검증, 혼합 평균 금지.
- [ ] **EH4.9** frozen corpus/gold/config의 재현 가능한 실행 receipt를 남긴다. 완료: 실제/합성/미실행 구분, old/new scorer·latency·모델 가용성 별도.
- [ ] **EH4.10** authoritative local page-v1 control과 단계별 challenger를 동일 frozen golden에서 paired run한다.
  완료: 비교축 외 generator/prompt/runtime/cache 고정, 오류·누락 분모 유지, case-level delta와 quality/efficiency 분리.
- [ ] **EH4.11** `ComparisonSelectionReceipt`를 발급한다. 완료: 사전 봉인 selection policy/hash와 hard gate에 따라
  `selected|retain_control|no_winner`를 기록하며 retrieval 결과와 API/local generation 결과를 섞지 않는다.
- [ ] **EH4.G** Phase 4 gate: 통합 CLI smoke+전체 회귀+privacy/hash gate+EH4.10~11. 미실행 성능을
  구현 완료에 섞지 않고 selection receipt 없이는 기본 runtime을 바꾸지 않음.

### EH-D — 납품 체크포인트 (선행: EH4.G)

- [ ] **EH-D.1** 구현 보고서의 요구사항↔파일↔테스트 표와 미구현/실측 미수행 경계를 작성한다.
- [ ] **EH-D.2** compile/전체 회귀/repository safety/사용자 dirty 보존을 최종 검증한다.
- [ ] **EH-D.3** current Mermaid/PNG/HTML을 최종 갱신하고 Playwright 렌더를 확인한다.
- [ ] **EH-D.4** logall/TODO/원장을 실제 결과로 동기화한다. 실패/수리 근거는 별도 error log로 연결한다.
- [ ] **EH-D.5** 이번 변경만 선택 stage/commit/push한다. 현재 브랜치 유지, 무관한 dirty·resources 제외, force 금지.
- [ ] **EH-D.6** 13항목 최종 보고와 relay 판단을 기록한다. 전체 완료 전 전체 완료/성능 개선을 주장하지 않음.

## 실행 원칙

- 프로젝트 기간: 3주
- 팀 규모: 4명
- 전략: 작동하는 naive Dense RAG 기준선을 먼저 만들고, 평가로 확인된 실패만 개선한다.
- 역할: 고정 사일로보다 배치별 주 담당 1명과 교차 검토자 1명을 둔다.
- 이번 실행 범위: Batch 0 → 운영 초기화 → Batch 1 → Batch 2

## 근거 자료

- 과제 가이드: https://codeit.notion.site/AI-1ee6fd228e8d80d4834bee9cef8f44c1
- 프로젝트 corpus: Git 밖 `private/deferred-references.md`의 내부 주소 레지스터 참조

## Batch 0 — 범위·보안·권위 체계 확정

상태: COMPLETED (교차검토 보완 및 재검증 완료)

- [x] `MidProjectRAG` 요구사항과 4대 평가 시나리오를 권위 문서에 고정한다.
- [x] Notion=과제 기준, 지정 Drive=유일 corpus로 기록한다.
- [x] 가져온 레거시 프로젝트가 활성 요구사항·스펙을 덮어쓰지 못하게 격리한다.
- [x] 원문·추출문·청크·벡터 DB·비밀키·PII의 Git 유입을 차단한다.
- [x] API/GCP 사용 범위, 총 OpenAI 비용 20달러, GCP L4 제약을 기록한다.
- [x] 외부 데이터 전송은 별도 승인 전 `PENDING`으로 두고 Batch 0~2를 로컬 전용으로 잠근다.
- [x] 운영 초기화 전에 안전 검사·ignore canary·활성 레거시 검사를 재통과한다.
- 검증: 권위 충돌 0건, 활성 레거시 계약 0건, 저장소 안전 검사 통과.

## Batch 1 — HWP/PDF 수집·변환 리스크 해소

상태: IN_PROGRESS_FIDELITY_QA (100건 전수 추출·무결성 검증 완료)

- [x] HWP5 표본 헤더와 로컬 parser 후보를 실사하고 HWP/PDF adapter의 명시적 실패 상태를 구현한다.
- [x] `Copy of ` 한 번 제거와 Unicode NFC 정규화 기반 CSV↔원문 exact join을 구현·합성 검증한다.
- [x] 해시·파서 버전·추출 상태·경고를 담는 manifest 계약과 `manifest/extract/verify` CLI를 구현한다.
- [x] CSV `텍스트`는 해시·길이만 manifest에 남기고 검색 본문으로 사용하지 않는다.
- [x] PDF 페이지와 HWP 문단의 stable source block 및 provenance를 생성한다.
- [x] private snapshot을 로컬 Git 밖에 materialize하고 CSV↔원문 100/100 조인과 96 HWP·4 PDF 재고를 검증한다.
- [x] 대용량 PDF worker IPC 순서 문제를 회귀 테스트와 함께 수정하고 PDF 4건을 재추출한다.
- [x] HWP 실패 2건을 비식별 진단하고 원문 바이너리 텍스트 fallback으로 복구한다.
- [x] HWP 96건·PDF 4건 전수 추출 manifest를 `require-extracted`로 재검증한다.
- [x] 체크섬 검증 `rhwp v0.8.4`로 HWP 96/96 페이지 텍스트·표 구조를 전수 실사하고 주 추출기 adapter를 구현한다.
- [x] `rhwp` 기반 별도 private manifest를 생성해 HWP 96·PDF 4 모두 `ok`, 실패 0건으로 재검증한다.
- [x] `rhwp` 절대경로·실행 SHA-256 production gate와 페이지/표 완전성 계약을 추가하고
  두 번의 100건 재추출 및 byte-for-byte 결정성을 검증한다.
- [x] page text를 primary, 구조화 table을 auxiliary retrieval lane으로 분리해 naive baseline의
  중복 임베딩을 금지한다.
- [ ] HWP 5건의 table↔render-tree bbox 조인율·한컴 페이지 정합과 PDF 4건의 표·bbox fidelity를 표본 QA한다.
- 검증: 전체 70개 테스트, 실제 manifest 100행·block 20,569행 Schema 오류 0건,
  strict primary gate 통과, 실패 문서 누락 0건, PII 포함 로그 0건.

### Batch 1 데이터 품질 정정 — 결측치·날짜 오매핑

상태: COMPLETED_HIGH_CONFIDENCE_WITH_REVIEW_QUEUE

- [x] 원본 `data_list.csv`는 불변으로 보존하고, 정정 오버레이·수정본·감사 기록을 분리한다.
- [x] `fivecircles/work/data-quality-corrections/`에 공개 가능한 근거·판정·전후 통계를 기록한다.
- [x] 공식 발주기관·나라장터 자료와 로컬 원문을 교차검증해 공고번호·차수·사업금액·입찰 제출 시작/마감 값을 보완한다.
- [x] `입찰 참여 마감일`에 섞인 개찰·제안서 평가 일시를 분리하고 확인된 오매핑을 수정한다.
- [x] 미해결 값은 `원문 미기재`, `해당 없음`, `외부 확인 필요`로 구분하며 추정값을 입력하지 않는다.
- [x] 중복 정정, 기존값 불일치, 날짜 역전, 근거 없는 확정값을 막는 자동 검증을 추가한다.
- [x] 100건 전체를 다시 프로파일링하고 정정 전후 결측·오매핑·미해결 목록을 확정한다.
- [x] 원래 결측 71셀과 잔여 결측 31셀을 사업명·필드·사유·예상 답변으로 handoff한다.
- [ ] 과거 입찰 히스토리 문서 확보는 현재 정정 패스 완료 뒤 비용·수집 가능성을 검토하는 후순위로 둔다.
- 후속 검토: 잔여 확인 4건, 후속 차수·일정 연장, 금액 정의 충돌,
  기존 82건의 번호 namespace/차수 문자열 정규화.
- 검증: 105개 결정, 실제 변경 77개, 원본 hash 불변, 100행·100/100 join 유지,
  확정값 provenance 누락 0건, 날짜 순서 위반 0건, 전체 219 tests·safety 428 files 통과.

### 2026-08-28 — refined 98문서 source-of-truth 전환

상태: DOWNSTREAM_LOCAL_COMPLETE_API_ACTIVATION_PENDING

- [x] 기존 100문서와 사용자 복제본을 대조해 유일한 바이너리 SHA 중복 두 쌍을 확정한다.
- [x] 삭제된 원문 2건과 대응 CSV 행 2개를 함께 제거해 98행·98파일로 맞춘다.
- [x] `resources/data_refined/**`와 `refined_data_list.csv`를 Git/safety restricted path로 고정한다.
- [x] 98개 원문과 CSV 파일명을 `refined_`+Unicode NFC로 통일한다.
- [x] retained rows의 검증된 metadata 교정 69셀을 refined CSV에 직접 반영한다.
- [x] CSV `텍스트` 98행을 pinned parser canonical primary body로 직접 materialize한다.
- [x] literal/NFC join 98/98, HWP 94/PDF 4, raw hash 중복 0, body 98/98,
  stable doc ID 98/98과 pending manifest/verify를 통과한다.
- [x] 98문서 extracted manifest와 source blocks bundle을 별도 materialize하고 strict primary gate를 통과한다.
- [x] 98문서 page chunks와 local page index를 재생성하고 direct manifest metadata를 catalog 입력으로 검증한다.
- [x] 기존 small page vector를 byte-identical 9,331개 subset으로 검증·이관한다.
- [ ] 새 table OpenAI index를 생성하고 두 API index의 identity를 결합한다.
- [ ] dev40을 새 manifest/source block hash로 재검증하고 과거 v5 결과와 분리한다.
- [ ] 새 versioned runtime config를 만든 뒤 Streamlit 기본 data root를 refined bundle로 전환한다.

검증 완료값: CSV 98행×15열, raw 98개, metadata 직접 변경 69셀, canonical body 7,430,548자,
pending snapshot `snapshot_f14ad7018fae2d3905c4e604`. 기존 100문서 artifacts는 역사본으로 보존한다.

### 2026-08-28 — HWP ordered visual evidence overlay v1

상태: LOCAL_CORPUS_COMPLETE_HUMAN_AND_EXTERNAL_ACTIVATION_PENDING
방법론: contract-first + one-shot delivery + evidence-gated relay

- [x] D-018과 `ordered-layout-asset-extraction.md`에 호환성·보안·실패 계약을 고정한다.
- [x] target/current Mermaid 시작 리포트와 gap/relay 점수를 기록한다.
- [x] strict JSON Schema와 synthetic fixtures를 먼저 만든다.
- [x] top-level text/table/image 순서, canonical table join, cell Rect evidence를 구현한다.
- [x] bounded DocLang asset 추출·content-address 저장·image occurrence 검증을 구현한다.
- [x] 알려진 69페이지 HWP p.7/p.8 private opt-in 회귀와 byte determinism을 검증한다.
- [x] 기존 source block/page-v1 hash 불변, 전체 회귀, compile, safety를 검증한다.
- [x] 완료 리포트·work log를 갱신하고 PDF local parser PoC를 같은 릴레이에서 실행한다.

대표 gate 뒤 94건 전체 결과: 8,762쪽·표 10,787개·ordered occurrence 77,607개를 exact
reconciliation했다. source image reference 452개 중 440개는 canonical 지원 형식으로 보존했고
12개 WMF/GIF는 provenance-only unsupported로 남겼다. strict page render 연결은 58개이며 나머지는
추정하지 않고 명시적 unlinked 상태다. 검색용 visual-context v2 표 청크 35,128개와 provider-free
local index까지 생성했지만 semantic API index와 기본 runtime에는 연결하지 않았다.

### 2026-08-28 — PDF local visual candidate PoC

상태: POC_COMPLETE_NOT_ADOPTED_AS_SOLE_PARSER

- [x] refined PDF 4건 570쪽을 `pdfplumber` lines strategy로 두 번 전수 실행한다.
- [x] table/image bbox, same-page prior text와 direct fill rect를 bounded private record로 만든다.
- [x] 1,270개 record를 strict schema로 검증하고 두 실행의 byte determinism을 확인한다.
- [x] 조직도/box diagram의 선이 table로 과검출될 수 있어 결과를 verified가 아닌 candidate로 고정한다.
- [ ] 일정표 row text-cell 정렬과 선 없는 표를 포함한 사람 fidelity gold를 만든다.
- [ ] OCR/diagram lane과 PDF candidate calibration을 통과한 뒤에만 검색 runtime 채택을 결정한다.
- [x] HWP visual rollout을 대표 위험 유형 5건 → 94건 전수 순서로 수행한다. 5/5와 94/94
  strict·재실행 결정성 gate, page/table/asset reconciliation, 35,128개 visual-context v2 chunk,
  provider-free local index와 RRF/citation smoke를 완료했다.
- [ ] 대표 5건의 private 사람 fidelity gold에서 표 제목·행/열/fill과 그림 위치를 원본과 대조한다.
- [ ] 목적지별 private corpus egress·비용을 명시 승인한 뒤에만 v2 semantic embedding/index와
  기본 runtime 전환을 수행한다.

### 2026-08-30 — HWP/PDF 이미지 복구·OCR·도식 이해

상태: PUBLIC_CORRECTION_COMPLETE_PRIVATE_GATES_BLOCKED

결정: OCR·이미지 설명만 추가하지 않는다. `doc_id + page + bbox + crop hash` occurrence를 먼저
복구하고 그 위에 OCR/layout/caption과 검색 인용을 연결한다.

- [x] HWP 94건과 PDF 4건의 완료·미완료 상태, 실패 원인, 해결 계약을 문서화한다.
- [ ] `[BLOCKED_EXTERNAL_REVIEW]` HWP 대표 5유형과 PDF 4건의
  object/page/bbox/title/OCR/관계 human gold를 동결한다.
- [x] rhwp `sourceImageKey` helper와 occurrence별 verified/unresolved 혼합 schema·validator를 구현한다.
- [x] table-nested image의 exact row/column/nested-cell path를 보존하고 top-level 중복을 금지한다.
- [x] HWP SVG data URI와 nested viewBox/viewport clip을 반영한 deterministic occurrence crop 경로를 만든다.
- [x] ID 부재 HWP는 raw SHA 또는 normalized RGBA SHA+bbox exact match만 verified로 승격한다.
- [x] 현 canvas가 디코딩하지 못하는 TIFF/GIF/WMF/SVG는 source provenance만 보존하고 crop 없이
  quarantined한다. 향후 변환은 pinned converter와 source/derived 이중 provenance로 분리한다.
- [x] PDF raster XObject/inline image/vector drawing/table을 분리하고 bytes·resource/bbox provenance를 만든다.
- [x] PyMuPDF는 AGPL/상용 license 결정 전 spike-only로 두고 pypdf+pdfplumber를 기본으로 유지한다.
- [x] PDF visual corpus durable CLI/runner로 4건 570쪽 v2 artifact를 재생성하고 strict reuse를 확인한다.
- [x] stale v1 artifact는 검색 승격을 금지하고 current-code v2 재생성만 허용한다.
- [ ] `[BLOCKED_MODEL_WEIGHT]` PP-StructureV3 + Korean PP-OCRv5 실제 weight로
  OCR polygon/confidence/reading order/table cell 품질을 측정한다.
- [ ] `[BLOCKED_MODEL_WEIGHT_AND_GOLD]` OCR로 부족한 구성도·조직도만 local caption 모델을 비교한다.
- [x] `image-ocr-v1`/`image-layout-v1`/저가중치 `image-caption-v1`과 page/bbox crop 인용을 연결한다.
- [ ] `[BLOCKED_HUMAN_GOLD]` 대표 gate 통과 뒤 HWP 94건을 전수 실행하고 visual retrieval gold를 검증한다.
- [x] human gold, local model checksum, offline·resource gate 전에는 기본 runtime이 fail closed한다.
- [x] `[REGRESSION_VISUAL_CROP]` SVG embedded raster 누락과 nested viewBox 좌표를 수리하고
  rect clip·관측된 linear filter/opacity를 보존하며 pure-white crop을 fail closed한다. CSS
  style/class, hidden image와 definition-only image는 지원하지 않고 거부한다. 대표 crop 15/15
  및 page render 14/14 nonblank와 strict reuse를 재확인했다.

실행 증거: HWP 대표 5건은 27 occurrence 중 15 eligible/1 TIFF quarantined/11 withheld이며
unique crop 15개는 전부 nonblank다. 이전 순백 crop 14개 bundle은 incident archive로 보존했다.
최종 helper `0b7ab8ed…`, artifact set `visualv2_1a25cd3f5f6c34dfe2e8ff9c`를 pin했고 관련
31/31·전체 505/505 테스트와 독립 산출물 재감사를 통과했다.
PDF 4건은 1,110 occurrence 중 1,103 eligible/7 withheld다. HWP 94 corpus mode는 reviewed gold 없이
실행 전 차단됐고 실제 OCR/caption inference는 pinned weight 부재로 0건이다.

구현 계약: `fivecircles/architecture/specs/visual-image-recovery-and-understanding.md`
incident: `fivecircles/test/errorlogs/backend/2026-08-30-pdf-visual-artifact-stale.md`
HWP blank-crop incident: `fivecircles/test/errorlogs/backend/2026-08-31-visual-crop-blank-regression.md`

## Batch 2 — 평가 세트와 공통 계약 선확정

상태: READY_PRIVATE_GOLD (공개 계약·평가 도구·합성 검증 완료, 실제 60문항 작성 가능)

- [x] 단일 문서, 다중 문서 비교, 후속 질문, 미지 질문/기권 평가 스키마를 구현한다.
- [x] dev/held-out 분리와 group·질문·문서쌍·conversation 단위 누수 방지 규칙을 구현한다.
- [x] API와 GCP 로컬 스택이 공유할 요청·응답 JSON Schema와 오프라인 registry를 구현한다.
- [x] 검색·생성·인용·기권·latency·비용 지표 설정과 `validate/score/compare` CLI를 구현한다.
- [x] 평가 task floor·hard gate·explicit scope·안전 기권·A/B hash/shape 검사를 fail-closed로 고정한다.
- [x] 기존 source-verified EDA 풀에서 private seed 10문항을 난이도 easy/medium/hard=3/4/3으로
  고정하고 원본 행·source hash·subset hash를 보존한다. 질문·정답 본문은 Git과 로그에서 제외한다.
- [ ] private EDA seed 10문항을 strict evaluator schema로 변환하면서 legacy activation/source
  scope 필드를 명시적으로 정규화하고, named human review 뒤 공식 dev/held-out gold 편입 여부를 결정한다.
- [ ] private corpus 근거로 dev 40문항과 held-out 20문항을 작성하고 2인 교차검토한다.
- [ ] held-out 파일과 질문 순서를 hash로 봉인하고 실제 source block·locator hash 무결성을 검증한다.
- 검증: 평가 테스트 31개, 오프라인 Schema 참조, split 누수, 응답·실행 기록 불변식 통과.

### 2026-08-31 — 보조 평가 69문항 실행 자산화

상태: PROVISIONAL_BASELINE_GPT56_SCORED

- [x] 문서 조항·사실 44, 조건·카탈로그 13, 정답·원문 검수 12의 용도와 수량을 고정한다.
- [x] 기존 dev40 floor와 점수 계약을 유지하고 supplemental evaluator를 분리한다.
- [x] source/disposition/refined manifest hash와 11개 정정 fail-closed gate를 계약한다.
- [x] set case/run 및 LLM review decision schema와 offline registry를 구현한다.
- [x] 69문항을 56 answer draft + 13 set draft로 변환하는 CLI를 구현한다.
- [x] source SHA 112개를 refined doc ID로 전수 변환하고 문서별 근거 후보를 생성한다.
- [x] 집합 검색 Precision/Recall/F1·exact match·count accuracy scorer를 구현한다.
- [x] 실제 private draft와 evidence review queue를 결정적으로 생성한다.
- [x] 정정 override·legacy CSV를 hash로 고정하고 CSV 7문항의 행·필드·값 hash 근거를 분리한다.
- [x] LLM decision을 case hash에 결합하고 official gold 승격을 차단한다.
- [x] 56 answer + 13 set을 LLM 검수 전 `provisional` 평가 입력으로 실행 가능하게 연다.
- [x] refined 98·small+mini·top-10/context-5 config, offline preflight, case별 resume와 USD 2.00
  ledger를 고정하고 egress flag가 없으면 provider 생성 전에 차단한다.
- [x] refined 98 page-only small+mini 고정 기준선으로 69문항 평가를 실행하고 hash·점수를 남긴다.
- [x] 답변형 56문항을 고정된 ChatGPT `gpt-5.6-sol`이 직접 의미 판정하고, 경계 5문항은
  독립 재심과 3차 판정을 거쳐 집계한다. 결과는 평균 46.70점, accepted 19, rejected 35,
  needs human 2이며 품질 gate는 실패했다.
- [x] 실행 계약·코드·합성 테스트·비민감 집계 영수증만 선별 커밋·푸시한다.
- [ ] 생성답변 품질 판정과 별도로 골든 정답·qrel을 검수한 뒤 승인된 문항만 `official` asset으로 finalize한다.
- [ ] 제품의 `selected_doc_ids` 집합 응답 DTO는 core RAG 안정화 뒤 별도 batch로 구현한다.
- 구현 계약: `fivecircles/architecture/specs/supplemental-evaluation-contract.md`
- 검증: evaluation 83/83, 전체 546/546, provider gate와 fake resume, private build 5종
  byte-identical 재실행, provisional 69/69 validation PASS. official gate는 승인 0/69로 의도대로 실패한다.
- 실행 계약: 골든 정답·qrel 승인이 0/69이어도 `provisional` 평가·점수 산출은 허용한다.
  `--require-approved`는 별도 official gate로 69건 전부를 `case_not_approved` 차단해야 한다.

### 2026-08-31 — gpt-5-mini 131개 통합 기준선

상태: COMPLETED_PROVISIONAL_MINI_BASELINE

- [x] Mini131 실행·판정·보고서 계약과 세 live suite preflight를 고정하고 전체 회귀를 통과한다.
- [x] 현재 정본 `rhwp` parser 회귀 C21/C22를 재실행하고 2/2 PASS 영수증을 교차검증한다.

- [x] 기존 supplemental 39개 정확 답변은 보존하고, 최종 답변 누락·생략 30개를 Mini로 재실행해
  runtime-exact transcript를 남긴다.
- [x] 나머지 62개를 처리한다: core40 40, HWP/PDF 표·그림 10, EDA 10,
  parser-fallback ETL 회귀 2.
- [x] RAG 129개 후보 답변을 고정 `gpt-5.6-sol`/`gpt56-semantic-v2`로 판정하고,
  목록 집합·EDA 수치·파서 PASS/FAIL 객관 지표를 별도 병기한다.
- [x] 기존 `gpt56-baseline-score.html`에 131개 통합 결과와 문항별 채팅 기록을 누적한다.
- [x] private 원문·답변을 Git에서 제외한 채 aggregate receipt/report만 선별하고, 회귀검증·
  logall 후 현재 branch에 커밋·푸시한다.
- 승인·실행: 사용자가 OpenAI 목적지, private payload, 최대 140회와 USD 4 상한을 명시 승인했다.
  corpus vector 재임베딩 없이 query embedding과 생성만 실행했고 후보 비용은 총 USD 0.21345322다.
- 최종 결과: RAG 129개 평균 54.845/100, accepted 58, rejected 71, 미해결 0;
  parser C21/C22 2/2 PASS. 후보 계보는 legacy reconstructed 39와 prospective 90으로 분리한다.
- 보존 증거: source transcript 129/129, primary 129·secondary 13·adjudicator 13 판정 이력,
  private HTML 131카드, 전체 회귀 728/728 PASS. public receipt는 본문 없이 집계·hash만 포함한다.

## Batch 3 — 시나리오 B API naive 기준선

상태: PROVISIONAL_API_2X2_COMPLETE_PENDING_HUMAN_REVIEW_AND_GCP_FAISS_SMOKE

### 2026-08-26 — 정식 루트 통합 및 Langfuse 실연결

- [x] 현재 저장소를 유일한 원본으로 고정하고 작업 사본의 Langfuse 변경만 선별 이식한다.
- [x] content-free trace I/O, `chain/retriever/generation/guardrail` 계층, `.env` 지연 로딩과 최신 Langfuse SDK를 반영한다.
- [x] 비밀값을 출력하지 않고 자격증명·활성화 설정을 점검한 뒤 synthetic metadata trace를 전송·재조회·감사한다.
- [x] 관측성 대상/전체 테스트와 저장소 안전 검사를 통과한 뒤 잘못된 작업 사본을 삭제한다.
- 검증: 실제 trace 계층·I/O·model/token/cost 필드 감사, 전체 테스트, safety, 중복 경로 부재.

- [x] deterministic page chunk + `text-embedding-3-small` adapter + FAISS `IndexFlatIP`/NumPy smoke + Dense top-k 기준선을 구현한다.
- [x] 실제 small/large 임베딩과 각 9,509행 NumPy exact index를 생성하고 hash를 고정한다.
- [ ] 팀원이 사전 데이터 리뷰와 manifest·추출 결과·index metadata를 교차확인한다.
- [ ] GCP L4에서 production FAISS `IndexFlatIP` 저장·복원 smoke를 수행한다.
- [x] `gpt-5-mini`/`gpt-5-nano` adapter로 인용·대화 문맥·기권 응답과 합성 4대 시나리오를 구현한다.
- [x] embedding cache·중복 fan-out·process-safe 비용 원장·20달러 hard stop을 구현한다.
- [x] 공개 tokenizer asset을 별도 승인으로만 warmup하고, 크기·SHA-256 검증 후 runtime을 완전 오프라인으로 고정한다.
- [x] 기본 OFF인 provider-neutral 관측성과 metadata-only Langfuse adapter, evaluator score bridge를 구현한다.
- [x] draft dev 40문항의 개인 API 2×2 잠정 실행 기록과 승인된 content-free trace를 생성한다.
- [ ] 사람 교차검토 후 small 기준선을 공식 dev 결과로 승격한다.
- [ ] Langfuse post-run programmatic audit의 Observations v2 schema drift를 해소한다.
- 검증: `dev40-provisional-v5` 160/160, error 0, corpus/eval/config hash 고정, 비용 USD 0.111497070, budget clean. 사람 품질 판정과 GCP FAISS smoke는 미완료다.

### Batch 3 다음 실행 순서 — Retrieval/Generation

- 상세 계약: `fivecircles/architecture/specs/api-baseline-observability.md`의
  `Retrieval/Generation 다음 실행 계획`을 따른다.
- [x] query builder·top-k·prompt version을 담은 단일 RAG config와 hash를 고정한다.
- [ ] 후속 질문 검색에서 assistant 답변을 검색·사실 근거와 분리하고, explicit scope와
  2~5개 문서 context coverage를 회귀 테스트한다.
- [ ] claim 단위 citation 검증과 `원문 미기재/정보 없음/추가 확인 필요` 의미를 구현한다.
- [ ] private presentation layer에서 30초 입찰 검토 카드와 페이지 citation을 연결한다.
- [ ] 현재 잠정 결과를 사람 검토하고 GCP FAISS smoke를 통과한 뒤 dev 40문항 공식 기준선으로 승격한다.
- [ ] 기준선 실패 유형을 분류한 뒤 Batch 4 후보를 한 번에 하나만 승격한다.

### 2026-08-26 — 개인 OpenAI API 2×2 잠정 기준선

- [x] 개인 OpenAI 키의 `text-embedding-3-small`, `text-embedding-3-large`, `gpt-5-nano`, `gpt-5-mini` 접근성과 실행 가격을 확인한다.
- [x] small 1,536차원과 large 3,072차원 인덱스·cache·config hash를 분리하고 합계 USD 5 전용 hard stop을 둔다.
- [x] 동일한 draft dev 40문항으로 small/large × nano/mini 네 조합의 검색·생성 실행 기록을 만든다.
- [x] Recall@1/3/5/10, MRR@10, required-doc coverage, 응답 계약, 인용, 기권, latency와 실제 비용을 같은 표로 비교한다.
- [x] 팀 사람 리뷰 전 결과를 `provisional`로 표시하고, large 조합은 과정 공식 small 기준선과 분리된 개인 계정 실험으로 기록한다.
- [ ] dev 40건의 named human review와 정답성·충실성·인용 타당성 점수를 완료한다.
- 검증: `dev40-provisional-v5` 160/160, error 0, corpus/eval/config hash 고정, 비용 USD 0.111497070, budget clean. Langfuse metadata-only tracing은 활성화했으나 post-run API 감사는 schema drift에서 안전 중단됐다.

### 2026-08-26 — small+nano Streamlit 첫 데모

상태: AUTOMATED_AND_HEALTH_VERIFIED_BROWSER_VISUAL_PENDING

- [x] UI의 첫 고정 조합을 `text-embedding-3-small + gpt-5-nano`, top-10/context-5/citation-3으로 정한다.
- [x] Streamlit이 provider/index를 직접 import하지 않고 public application facade만 호출하게 한다.
- [x] 전체 문서와 최대 20건 explicit scope, 대화 초기화, 답변·기권·오류, 페이지 인용과 실행 정보를 구현한다.
- [x] 검색 manifest와 교정 catalog의 hash·역할을 분리하고, 100개 문서 정체성 일치를 검증한다.
- [x] 매 요청 corpus egress 동의, 별도 USD 5 원장, 기본 Langfuse OFF를 적용한다.
- [x] provider-free application/UI 테스트와 실제 9,509행 bundle startup을 통과한다.
- [x] Streamlit loopback health와 AppTest의 범위 선택→질문→근거/기권 흐름을 검증한다.
- [ ] 실제 브라우저에서 범위 선택→질문→근거→초기화 흐름을 시각 검증한다.
  현재 Codex in-app browser의 localhost admin policy 검증 불가로 환경 차단됐다.
- [ ] 승인된 개인 API로 small+nano 단일 질의 smoke를 수행하고 비용·인용·기권 상태를 기록한다.
- [ ] 본문/청크 전처리 확정 시 새 versioned index를 생성하고 bundle config만 원자 전환한다.
- 검증: UI 신규 12 tests, 전체 219/219, compile, safety 428 files, diff-check, 실제 bundle load,
  `/_stcore/health=ok`. OpenAI API 질의는 실행하지 않았다.
- [x] `doc_id`·원본 hash 100/100 일치와 metadata 77셀 변경을 별개 사실로 기록한다.
- [x] 현 Streamlit의 교정 catalog 사용 범위를 사업명·발주기관 라벨 overlay로 한정해
  문서화한다.
- [x] trace에 run-config hash를 전송하고, egress 동의에 history를 포함하며, catalog
  문자열을 plain text로 렌더한다.
- [ ] 공고번호·차수·금액·입찰일을 답변 근거로 쓰기 전 provenance/locator를 가진
  구조화 metadata retrieval·citation 계약을 정하고 gold case로 검증한다.
- 최종 리뷰 수정 검증: application/UI 9/9, 전체 220/220, compile, safety 429 files,
  `git diff --check` 통과. OpenAI API 질의는 실행하지 않았다.

### 2026-08-26 — 구조화 metadata lane + Streamlit E2E

상태: LIVE_API_CONTRACT_E2E_COMPLETE_ANSWERABLE_GOLD_PENDING
방법론: TDD

- [x] corrected catalog·correction overlay·RagResponse v1의 provenance 경계를 감사한다.
- [x] 재임베딩 없는 exact/range/date filter, `doc_id` routing, metadata card 계약을 작성한다.
- [x] 1차 peer review의 audit DTO·필드명·locator·provider 경계·날짜·UI state·config
  변경 요청을 계약에 반영한다.
- [x] 2차 peer review의 catalog data-flow 경계·정확한 structured locator 문법·spec index
  정합성 변경 요청을 계약에 반영한다.
- [x] 수정 계약을 재리뷰하고 `APPROVE`를 받은 뒤만 구현한다.
- [x] typed metadata fact와 correction provenance join을 provider-neutral catalog module로 구현한다.
- [x] runtime config에 correction artifact hash를 고정하고 provider 생성 전 drift를 차단한다.
- [x] Streamlit에 필터→결과→최대 20건 선택→metadata card→본문 질의 흐름을 연결한다.
- [x] provider-free/full/health/safety 및 실제 브라우저 흐름을 검증한다.
- [x] destination-specific 승인 후 private corpus 단일 small+nano 질의를 실행하고 aggregate만 기록한다.
- [ ] human-reviewed answerable gold 1건 이상에서 실제 페이지 인용 답변을 확인한다.
- [x] metadata-citation vNext, 공식 웹 근거 snapshot, 20건 이상 server-side scope를 후속 gate로 기록한다.
- 검증: 105개 감사 상태·77개 변경값 일치, 묵시적 top-20 절단 0, provider 전 drift 차단,
  metadata/body 근거 분리, 전체 회귀·UI 흐름·저장소 안전 검사.

### 2026-08-27 — metadata query·document scope 재검토

상태: REVIEW_PENDING

- [ ] **메타데이터 비교 부재:** `사업금액 상위 5개`처럼 top-N·정렬·최대/최소·집계가 필요한
  자연어 질의를 body RAG가 아닌 deterministic catalog query로 처리할 범위와 계약을 검토한다.
  null·0/1원 sentinel 제외, 동률 처리, 정렬 방향, metadata 근거 카드 표시를 함께 결정한다.
- [ ] **전체 문서 검색 차단:** metadata-enabled UI에서 explicit scope를 20개로 제한하고
  기존 `mode=all`을 숨긴 결정을 재검토한다. 수동/필터 선택은 최대 20개를 유지하더라도,
  전체 100문서·9,509청크 Dense 검색을 독립 mode로 복원할지 품질·UX·인용 기준으로 결정한다.
- 현재 판정: 20개는 vector index의 성능 한계가 아니라 explicit request/schema와 사용자 선택의
  안전 경계다. underlying body RAG에는 전체 문서 검색 경로가 있으므로 복원 가능성을 우선 검토한다.
- 이 항목은 검토 TODO이며 구현 확정이 아니다. 계약·gold case·UI 상태 전이를 승인한 뒤 구현한다.

### Mac 로컬 Qwen3.8 탐색 경로 — 독립 기준선 완료

- [x] 공식 Ollama 매니페스트·로컬 사양을 확인하고 `qwen3.8:27b-mlx` structured JSON 합성 생성을 검증한다.
- [x] `local-hash-char-v1` 검색 인덱스를 기존 9,509개 chunk로 생성한다.
- [x] loopback-only Ollama 생성기와 `local-query`를 연결한다.
- [x] 합성 end-to-end 및 private corpus 단일 질의를 실행한다.
- 제한: 이 경로는 `mac_local_experimental`이며 공식 API/GCP L4 성능 비교나 제출 점수로 사용하지 않는다.
- 검증: 100문서·9,509청크 exact NumPy 인덱스, cache 재실행 9,509/9,509 hit,
  실제 단일 질의 1건의 검색·생성·인용 완료, 전체 152개 테스트와 안전 검사 389파일 통과.

## Batch 4 — 검색 개선과 절제된 ablation

상태: PENDING

### 2026-08-28 — refined page/table dual-lane 전환

상태: LOCAL_IMPLEMENTATION_COMPLETE_API_ACTIVATION_PENDING
방법론: TDD + versioned bundle migration

- [x] refined 98문서 extracted manifest/source blocks를 materialize하고 strict gate를 통과한다.
- [x] 기존 page-v1과 하위호환되는 `table-md-rowgroup-v1` 계약·생성기·CLI를 구현한다.
- [x] 병합셀 전개, header 반복, Markdown escaping, row-group 무손실을 합성 테스트로 검증한다.
- [x] page/table exact index를 분리하고 query 1회 임베딩 + RRF fusion을 구현한다.
- [x] runtime config v1.2에서 두 lane·layout artifact/hash를 provider 생성 전에 검증한다.
- [x] HWP table locator→page join을 전수 측정하고 불확실한 page를 추정하지 않는다.
- [x] 표 질문 3건의 로컬 smoke와 page/table 인용 위치 정합성을 확인하고 실패 1건도 기록한다.
- [ ] OpenAI small 의미 임베딩으로 표 전용 gold를 실행해 page-only 대비 개선을 판정한다.
- [ ] 새 refined bundle을 생성·검증한 뒤 Streamlit 기본 config를 원자 전환한다.
- 테스트: chunk/schema unit, index fusion unit, application bundle integration, private opt-in
  refined artifact audit, 전체 회귀·compile·repository safety.

- [ ] 구조적 청킹 → 메타데이터 라우팅 → top-k 조정 순으로 한 요소씩 비교한다.
- [ ] 검색 중복이 확인될 때만 MMR 또는 hybrid search를 실험한다.
- [ ] 정답 청크가 top-k 안에 있으나 순위가 낮을 때만 reranking을 실험한다.
- [ ] Multi-query는 앞 단계 이후에도 남은 실패 사례가 있을 때만 실험한다.
- 검증: dev 품질·latency·비용 ablation 표와 채택/기각 근거 기록.

### 후순위 참고 주소 — baseline 완료 후에만 사용

- 정확한 로컬·Drive 주소는 Git 밖 `private/deferred-references.md`에 기록한다.
- Mission14 재사용 범위: Dense/RRF/reranker 실험 구조와 평가 방식만 참고한다. 당시 단일 PDF 성능 수치는 새 corpus 결론으로 사용하지 않는다.
- MMR: top-k가 동일 문서·유사 청크로 과도하게 중복될 때만 적용 후보로 승격한다.
- Reranking: 관련 청크가 검색됐지만 하위 순위에 머무는 실패가 반복될 때만 적용 후보로 승격한다.

### 심화·후순위 — INFO21C 유사 서비스 화면 참고

`resources/snapshot/`의 4개 화면은 기능 우선순위를 정하는 참고 자료이며 현재 corpus의
구현 가능 범위를 넓히는 근거로 사용하지 않는다.

#### 간단 기능 — 현재 100문서로 가능

- [ ] 기관·사업명·금액·파일형식 catalog filter와 검색 결과 목록을 explicit scope에 연결한다.
- [ ] 공고 상세 카드에 금액·일정·자격·요구사항·위험 요소와 입찰 일정 타임라인을 표시한다.
  날짜가 확인되지 않으면 임의 보정하지 않고 결측 상태를 표시한다.
- [ ] 북마크·메모·비교함과 검토 카드 내보내기를 local/private UI 상태로 제공한다.
- [ ] 같은 발주기관, 사업 요약, 예산대와 의미 유사도를 이용해 `관련 RFP`를 추천하고
  추천 이유와 원문 페이지 근거를 함께 표시한다.
- 업종·지역은 현재 정식 metadata 컬럼이 아니므로 근거 추출·검증 전에는 확정 필터로 약속하지 않는다.

#### 복잡 기능 — 외부 데이터 없이는 불가

- [ ] 사업자번호 기반 자사·경쟁사 투찰 이력, 투찰금액·투찰률·순위·1순위 업체를 분석한다.
- [ ] 발주처·업종·지역·기간별 낙찰/사정률 분포와 적중 분석을 제공한다.
- 외부 회사·기관·개찰 데이터 연동은 출처·이용권한·보존정책·회사/기관명 entity resolution을
  확인한 뒤 여는 하나의 후순위 gate로 두며, 현재 3주 MVP 범위에는 포함하지 않는다.

## Batch 5 — 시나리오 A GCP L4 로컬 HF 및 공정한 A/B

상태: MAC_EQUIVALENT_MINI131_DETERMINISTIC_COMPLETE_LIVE_GCP_BLOCKED
방법론: contract-first TDD + sequential relay

- [x] 첫 스택을 KURE-v1 1,024-d + CPU FAISS exact + Qwen3-8B-AWQ/vLLM로 고정한다.
- [x] user-confirmed storage hard max 100 GB, 80 GB warning, free 10 GB abort 계약을 기록한다.
- [x] Mac equivalent와 공식 `gcp_local` 결과의 증거 경계를 고정한다.
- [x] **5.2 Provider/record:** pinned HF embedder, loopback vLLM generator, GCP telemetry run-record와
  100 GB Schema/manual validator parity를 TDD로 구현한다.
- [x] **5.3 Mac retrieval:** refined98 9,331 page chunks를 KURE로 임베딩하고 NumPy exact
  save/load·hash와 provisional Recall@1/3/5/10, MRR@10, nDCG@10을 측정한다. GCP FAISS
  재현은 5.5에 남긴다.
- [x] **5.4 Local equivalent E2E:** Mac에서 가능한 생성기로 synthetic와 40 golden candidate를
  실행하되 공식 GCP 점수와 분리된 private transcript/content-free receipt를 만든다.
- [x] **5.4b Full local Mini131:** Core40에만 머물지 않고 RAG 129개와 parser 2개를 전부 실행한다.
  답변형 96개는 KURE page-v1+Qwen, 집합형 13개는 98문서 14개씩 map→global reduce,
  visual 10개는 page-text-only 한계를 명시하고, EDA 10개는 gold-free deterministic evidence와
  Qwen 설명을 함께 기록한다. parser 2개는 live rerun하고 RAG 의미평균과 분리한다.
- [x] Full local candidate 129행·parser 2건·lane별 결정론 점수·content-free receipt를 검증한다.
  완료 결과는 RAG 129/129, parser 2/2이며 결정론 receipt는 `suite_complete=true`다.
- [x] 새 로컬 후보의 fresh Sol blind ledger를 aggregate-validate한다. primary 129·secondary 4·
  adjudicator 3, accepted 88·rejected 41, acceptance 0.682171, mean 70.135659이다.
- [x] **5.4c Per-question performance:** 129개 골든 질문의 정답 기준·실제 Qwen 답변·근거·
  결정론 지표·Sol 구성점수/판정/사유를 하나의 private 원장으로 결합하고, parser 2건을 별도
  ETL 카드로 더해 난이도·목적·lane별 HTML 성능표와 content-free receipt를 생성한다.
  검증: 131행/해시/0600, easy·medium·hard 41/48/40, semantic aggregate exact reconcile,
  HTML 정적/JS QA와 `file://` 자동화 정책 차단 기록, private artifact Git 추적 0건.
- [ ] Named human gold review 상태를 별도 승인한다. 완료 전에는 `mac_local_equivalent`,
  `official=false`, provisional 상태를 유지한다.
- [ ] **5.5 GCP live:** 정확한 `g2-standard-4`/L4에서 vLLM 8K smoke, GPU seconds, peak VRAM,
  cold/warm latency, disk를 기록하고 가능한 provisional set을 실행한 뒤 VM을 종료한다.
- [ ] 동일 corpus/eval/scoring hash로 API와 controlled/best-stack 두 비교를 생성한다.
- 검증: provider/security/schema unit, shared pipeline integration, full regression/safety,
  flow target/current report, local provisional metrics, GCP VRAM <22 GB·GPU coverage 100%.

## Batch 6 — 통합 검증·재현성·제출

상태: PENDING

- [ ] `--data-dir` 지정만으로 manifest→추출→인덱스→평가를 재현한다.
- [ ] 4대 시나리오와 인용·기권을 실제 사용자 흐름으로 검증한다.
- [ ] 원문·키·PII·restricted artifact 유입을 검사한다.
- [ ] GitHub, PDF 보고서, 발표 및 개인 협업 일지를 마감 전에 동결한다.
- 검증: 깨끗한 환경 재현, 제출물 안전 검사, 발표 20분+Q&A 5분 리허설.

## 명시적 제외 범위

- 프로덕션급 인증·다중 사용자·관리자 기능
- 대규모 배포·모니터링과 파인튜닝
- 제공된 100개 밖의 corpus 확장
- 모든 검색 기법의 무차별 구현
- 원문·원문 수준 청크·벡터 DB의 공개 배포
