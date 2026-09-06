# Local RAG Baseline → Evidence-Harness Challenger 평가 진행 보고서


기준: 2026-09-06 · 현재 작업대 `feat/total-integration` · EH2.6.d2.x.a 전체 검증 완료 시점
최종 통합 대상: `feat/local-qwen-mini131-eval`

> **고정된 목적:** 기존 local KURE page-v1 RAG baseline은 최종 구조가 아니라 비교를 위한 control이다. GPT retrieval 연구,
> EvoHarness 연구와 통합안은 더 높은 검색 품질과 효율을 낼 것이라는 challenger 가설이다. 후보를 구현한 뒤
> 같은 frozen golden set으로 품질·효율·안전성을 비교하고, 실측으로 더 나은 아키텍처를 선택하는 것이
> 현재 작업의 목적이다. 측정 전에는 어떤 후보도 우승 또는 최종 구조로 부르지 않는다.

권위 계약: [D-024](../../requirements/decisions.md),
[Current Requirements §1.1](../../requirements/current.md),
[통합 아키텍처 실험 계약](assembly-on-research-and-exp.md),
[Evidence-Harness 구현 계약 §0](bidfit-evidence-harness-v1-rc0.md)

## 결론 먼저 — 지금 무엇을 쓰고 무엇을 만드는가

| 역할 | 현재 대상 | 상태 | 의미 |
| --- | --- | --- | --- |
| 주 비교 통제군 B0 | KURE page-v1 + local Qwen 계열 | Mac-equivalent 측정 완료·provisional | local-first retrieval 비교의 authoritative control. 계속 보존한다. |
| 별도 API arm | `text-embedding-3-small` + `gpt-5-nano` + Streamlit | 사용자-facing 호환 경로 | API-first는 과거 구현 순서이며 local control을 대체하지 않는다. |
| 현재 개발 대상 | `feat/total-integration`의 Evidence-Harness challenger | EH2.6.d2.x.a까지 구현 | 최초 dense 전이 후 ordinal2의 lexical/diagnostic/기권 선택 연결. 실제 두 번째 dispatch·후속 reducer·생성 E2E는 미완성이다. |
| 최종 전달 대상 | `feat/local-qwen-mini131-eval` | 병합·선택 전 | 같은 Evidence Pack 뒤에서 local/API generator를 갈아 끼운다. |
| 최종 선택 | baseline 대 assembled challenger | **미실행·미선정** | 동일 골든셋 A/B와 gate/Pareto 판정 뒤 결정한다. |

따라서 **현재 비교할 때 쓰는 것은 local baseline**, **현재 만드는 것은 challenger**, **나중에 기본으로 쓸 것은
아직 미정**이다. EH2.6.d2.x.a 작업은 실제 API를 실행한 것이 아니라
API/OpenAI/model/Langfuse/golden/VLM/provider/clock 호출 0회의 synthetic/offline temporal authority 검증 단계다.

### 현재 relay 판정

점수식은 `upstream + connection + safety + validation - risk`다.

| 후보 | 점수 | 상태 | 판정 |
| --- | ---: | --- | --- |
| EH2.6.c3.1 | 10 | DONE | MATCHED — bounded parent/bridge source receipt와 root-lifetime replay guard 완료 |
| EH2.6.c3.2 | 10 | DONE | MATCHED — ID-less rerank, global role order, owner budget, derived semantic/route one-shot 완료 |
| EH2.6.c3.3 | 8 | DONE | MATCHED — three-reason bounded zero-provider absence와 follow-up root-lifetime exact-once 완료 |
| EH2.6.c3.4 | 9 | DONE | MATCHED — closed ActionEffectReceipt DTO/validator, public mint fail-closed |
| EH2.6.c3.5 | 8 | DONE | MATCHED — replay/representation/nonpromotion 및 7종 source validator clone·mixed gate |
| EH2.6.d1 | 8 | DONE | MATCHED — initial-only execution ledger와 aggregate |
| EH2.6.d2.i | 8 | DONE | MATCHED — revision-0 fact/compare allowed action과 selected-first permit |
| EH2.6.c4.0.a | 8 | DONE | MATCHED — exact state-creation source owner와 execution identity 상속 |
| EH2.6.c4.0.b | 8 | DONE | MATCHED — exact typed source/outcome resolver와 sealed projection authority |
| EH2.6.c4.0.c | 8 | DONE | MATCHED — one-step claim/history, shared lane epoch/claim fence와 동시성·GC failed tombstone |
| EH2.6.c4.0.d | 8 | DONE | MATCHED — bounded target exact-one parent/table/figure와 complete rerank batch identity/order 보존 |
| EH2.6.c4.0.e | 8 | DONE | MATCHED — sourced claim + bounded target context 구조 bridge, clone/mixed/order/GC gate |
| EH2.6.c4.0 | 8 | DONE | a·b·c·d·e 구조 준비 연결 완료 |
| EH2.6.c4.1 | 8 | DONE | 최초 dense effect/transition·predecessor 보존. 전체1511 PASS·독립 APPROVE |
| EH2.6.d2.x.a | 8 | DONE | ordinal2 lexical/diagnostic/contract-error·budget 기권, closed reason·policy revision |
| EH2.6.c4.2.a | 8 | NEXT | GAP — 선택된 lexical을 실제 dispatch하고 revision2로 연결 |
| EH2.6.d2.x | 8 | PARTIAL | 첫 successor decision만 완료, 후속 fusion/context matrix는 revision2 발급 뒤 확장 |
| EH2.6.d2 | 8 | PARTIAL | initial slice 완료, cross-state slice와 full matrix 미완성 |
| EH2.6.c4 | 7 | PARTIAL | c4.0→c4.1→d2.x→c4.2 순서로 진행 |
| EH2.EVAL.4 | 5 | WAIT | GAP — 사람 승인·private qrels 선행 필요 |

## 이전 → 현재 → 목표

| 구분 | 이전 | 현재 | 목표 |
| --- | --- | --- | --- |
| baseline의 의미 | 먼저 만든 동작 경로 | 재현 가능한 immutable control로 명시 | 모든 후보의 공정한 비교·rollback 기준 |
| 연구 문서의 의미 | 좋은 구성의 참고안 | GPT/EvoHarness/통합안을 challenger 가설로 명시 | 실측에서 이긴 구성만 채택 |
| 구현 | page-only baseline + 분리된 실험 섬 | EvidenceStore, KURE child, Kiwi, RRF, QueryPlan, 첫 dense effect/ledger 전이 | bounded controller·전문 lane·교체형 generation E2E |
| 평가 | 각 실험의 부분 지표가 혼재 | 구현 PASS와 품질 우승을 분리 | 같은 frozen golden에서 component ablation + assembled A/B |
| 전달 | API UI와 local 실험 경로가 혼재 | 통합 작업대와 최종 local branch의 역할 분리 | local-first 기본 profile, API는 교체형 보조 arm |
| 선택 | 추천 스택을 바로 목표처럼 읽을 여지 | winner 미선정으로 고정 | 품질·효율·guardrail gate 및 Pareto 판정 |

## 같은 계층으로 정렬한 스펙 비교

| 계층 | Baseline control | Research/EvoHarness challenger | 평가 질문 |
| --- | --- | --- | --- |
| 데이터 | refined98 immutable | 동일 snapshot만 사용 | corpus/hash가 완전히 같은가? |
| 파서·근거 | rhwp/pypdf page source | provenance parent + source block/page/bbox | 정확도 향상과 처리비용 변화는? |
| 청킹 | page-v1 9,331개 | heading/paragraph child, table row-group, figure object | Recall과 context 효율이 좋아지는가? |
| 임베딩 | local KURE page control | KURE child 우선, OpenAI small/Qwen3은 별도 동일 조건 후보 | 같은 qrels에서 어떤 embedder가 Pareto 우위인가? |
| lexical | 없음 | Kiwi BM25 독립 child lane | dense miss를 얼마나 rescue하며 비용은 얼마인가? |
| fusion | Dense exact ranking | weighted control vs RRF k=60 | nDCG/MRR·중복·지연이 어떻게 변하는가? |
| reranker | identity/no rerank | optional Qwen3 reranker | pre/post retention과 p95 비용이 타당한가? |
| 질의 제어 | 단일 retrieval pass | QueryPlan, Belief/Progress, bounded verify loop | 복합·비교·후속 질문 completeness가 좋아지는가? |
| 전문 lane | catalog/analytics/visual이 분리 | list·analytics·table·figure bridge | top-N·전수·표·그림 실패가 줄어드는가? |
| 생성 | 비교 중 고정한 local Qwen | 같은 verified Evidence Pack + 교체형 adapter | retrieval 변화와 API/local generator 변화를 분리했는가? |
| 응답·UI | Streamlit 호환 UI | structured claim→evidence→locator | citation validity와 사용자 효용이 유지되는가? |
| 관측 | 오프라인 지표, Langfuse OFF | 실제 E2E에서만 Langfuse opt-in | trace·latency·token/cost가 재현 가능한가? |
| 실행 환경 | Mac provisional / API control | local-first, 최종 GCP L4 검증 | 환경 차이를 모델·검색 품질과 혼동하지 않는가? |

## 현재 구현 흐름

![현재 control·challenger 상태](evidence-harness-progress-current-flow.png)

원본: [current Mermaid](evidence-harness-progress-current-flow.mmd)

## 목표 실험·선택 흐름

![목표 실험과 선택 흐름](evidence-harness-progress-target-flow.png)

원본: [target Mermaid](evidence-harness-progress-target-flow.mmd)

## 골든셋에서 무엇을 비교하는가

### 단일변수 실험군

| Arm | 기준선에서 바꾸는 것 | 검증할 가설 | 현재 상태 |
| --- | --- | --- | --- |
| B0 | 없음: page-v1 + KURE Dense top-10 → context-5 + fixed local generator | 비교 출발점 | Mac-equivalent 측정 완료·provisional |
| R1 | child evidence + KURE Dense | 작은 검색 단위가 근거 recall/context 효율을 개선 | 구성요소 구현, paired run 전 |
| R2 | R1 + Kiwi BM25 + RRF k=60 | lexical rescue와 다중문서 coverage 개선 | 구성요소 구현, paired run 전 |
| R3 | R2 + optional Qwen3 reranker | 상위 evidence 순위/retention 개선 | adapter·실측 전 |
| H1 | 선택된 R arm + QueryPlan/slot/coverage/bounded loop | 비교·목록·후속·기권 완전성 개선 | controller 미완성 |
| V1 | 선택된 text arm + table/figure bridge | 표·그림 object recall 개선 | 별도 gate, E2E 전 |

embedder(KURE/OpenAI small/Qwen3) 비교와 API/local generator 비교도 각각 별도 arm으로 수행한다. child,
fusion, reranker, generator를 한 번에 모두 바꾼 결과만으로 원인을 추정하지 않는다.

### B0 측정 출발점

현재 공개 가능한 control receipt는 Mac Ollama/NumPy exact의 `mac_local_equivalent`이며
`official=false`, `passed=false`, named human gold 승인 전 provisional이다.

| 지표 | B0 값 | Challenger |
| --- | ---: | --- |
| Document Recall@1 / @5 / @10 | 0.921986 / 0.987589 / 0.991135 | 미측정 |
| MRR@10 | 1.000000 | 미측정 |
| Set precision / recall / F1 | 0.608974 / 0.692308 / 0.630769 | 미측정 |
| Set exact / count accuracy | 0.538462 / 0.538462 | 미측정 |
| Visual page / object Recall@10 | 0.600000 / 0.000000 | 미측정 |
| Semantic accepted / mean | 88/129 (0.682171) / 70.135659 | 미측정 |
| Runtime error | 6/129 (0.046512) | 미측정 |
| Total latency p50 / p95 | 33,405.49 ms / 263,840.61 ms | 미측정 |

근거: [Mac-equivalent deterministic receipt](../../../evaluation/baselines/gcp-local-kure-qwen3-8b-awq-mini131-v1/mac-local-equivalent-receipt.json),
[semantic receipt](../../../evaluation/baselines/gcp-local-kure-qwen3-8b-awq-mini131-v1/mac-local-equivalent-semantic-receipt.json).
이 값은 challenger가 넘어야 할 출발점이지 현재 구조가 충분하다는 판정도, 공식 GCP 성능도 아니다.

| 축 | 핵심 지표 | 선택에 쓰는 이유 |
| --- | --- | --- |
| 검색 품질 | Recall@1/3/5/10, MRR, nDCG, all-required-doc recall | 정답 근거를 찾는지와 상위 순위를 분리 확인 |
| 위치·객체 | required page/object recall, table/figure locator validity | 문서만 맞고 실제 표·그림을 못 찾는 허상을 방지 |
| 집합 완전성 | set precision/recall/F1, exact count, completeness receipt | top-N·전수 목록 질문의 누락을 검출 |
| 효율 | build/query p50·p95, RAM/VRAM, index size, token·비용 | 품질이 같을 때 더 작은 구성을 선택 |
| 안전성 | citation validity, abstention, error, baseline regression | 품질 향상과 환각·오류 증가의 교환을 차단 |

metric threshold와 non-inferiority 범위는 실제 run 전에 config/freeze receipt로 고정한다. 기존 local
Mini131 결과와 unit/full regression은 출발점·안전성 증거지만 새 assembled challenger의 승리를 증명하지 않는다.

## 현재 완료와 남은 gap

| 상태 | 항목 | 현재 판정 | 다음 gate |
| --- | --- | --- | --- |
| DONE | baseline 보존 | page-only/API·local control 계보 보존 | 매 비교에서 재현 확인 |
| DONE | challenger 검색 골격 | EvidenceStore, child KURE, Kiwi, RRF, QueryPlan/상태 타입 | 회귀 유지 |
| DONE | 실행 권한 경계 | immutable config + exact runtime authority + zero-dispatch | 회귀 유지 |
| DONE | E0 검색 실행·focused gate | owner obligation → dense → lexical → RRF fusion exact-once; rescue/empty/pre-call/error 경계 | 회귀 유지 |
| DONE | follow-up E1 초기 투영 | verified→candidate, primary/fallback dedupe, slot doc-match, metadata fail-closed, 추가 검색 0 | 회귀 유지 |
| DONE | semantic 검증 receipt | source-derived target, exact one-call, typed support/contradiction, zero-call unavailable, state-free receipt | EH2.6.c3 effect/absence |
| DONE | parent/bridge source receipt | candidate-only bounded seed, parent context-only, table/figure actual link와 empty attempt, root-source replay 방지 | 회귀 유지 |
| DONE | rerank/derived semantic | ID-less strict ABI, cross-role global order, exact owner budget, auxiliary parent 비승격, base/derived route 단일 소비 | EH2.6.c3.3 absence |
| DONE | bounded absence | 세 owner-derived reason, exact proof matrix, zero-provider·state-free receipt, follow-up exact-once | EH2.6.c3.4 effect DTO |
| DONE | closed effect value | 19-field canonical schema, closed action/source/outcome/call matrix, no public mint/authority | EH2.6.c3.5 adversarial gate |
| DONE | effect 비권한 gate | repr/copy/pickle/from-dict/subclass 비누출·비승격, 7종 source validator exact clone/mixed graph 거절·provider replay 0 | EH2.6.d1 aggregate |
| DONE | initial execution aggregate | exact initial root에서 zero-consumption ledger/aggregate 발급, stable identity/snapshot 분리, idempotence·concurrency·GC·clone/mixed gate | EH2.6.d2 decision |
| DONE | initial decision permit | exact live revision-0 fact/compare all-unsearched 상태에서 canonical allowed action과 selected-first receipt 발급, EH2.5/effect 비승격·동시성·GC gate | EH2.6.c4.0 |
| DONE | exact source-owner authority | state 생성 시 exact Bound/coverage/outcome/registry/policy를 private mirror에 봉인하고 execution이 exact initial-state identity로만 상속; equal-hash clone·사후 부착·legacy follow-up 승격 차단 | EH2.6.c4.0.b resolver |
| DONE | typed source/outcome resolver | exact decision·source-owner·live receipt graph에서 source kind/outcome/call/evidence/context/absence를 closed projection으로 유도; direct issuer·clone·mutation·dependency drift 차단, 추가 dispatch 0 | EH2.6.c4.0.c history |
| DONE | one-step temporal authority | exact step key의 single-winner claim, claim-authorized prepare→source, shared lane attempt epoch/claim cutoff, duplicate/concurrent/direct projection/clone·drift·GC/post-child failure의 terminal tombstone | EH2.6.c4.0.d accumulator |
| DONE | per-target context accumulator | semantic obligation의 bounded target에서 parent/table/figure receipt exact-one 선택, complete parent/bridge tuple identity·canonical order 보존, root-lifetime remint·변조 차단 | c4.0.e structural bridge |
| DONE | structural-effect bridge | sourced claim + exact target context에서 구조 재료를 도출; immutable/non-serializable/redacted, same-object·root remint·clone/mixed/order/GC gate | EH2.6.c4.1 effect/transition |
| DONE | 최초 dense 전이 | live effect·ledger1·transition·successor, 동일 state 유지, predecessor와 원본 receipt 재검증 | d2.x 다음 decision |
| DONE | 첫 successor 다음 결정 | same-obligation lexical, provider-error 진단, contract-error·budget 기권; ordinal2 chain과 비소비 조회 | c4.2.a 실제 lexical |
| NOT DONE | 후속 상태 전이·종료 | revision2 이후 matrix, state-changing reducer, bounded controller 미완성 | c4.2.a→d2.x.b→후속 c4.2→d3~d4 |
| NOT DONE | 전문 lane E2E | analytics/list/table/figure가 controller 밖 | EH3.1~EH3.G |
| NOT DONE | 생성·평가 조립 | reranker/generator/CLI/layer evaluator 미완성 | EH4.1~EH4.G |
| NOT DONE | 공정 비교 동결 | 공통 freeze receipt와 threshold 미동결 | EXP-SELECT.2 |
| NOT DONE | component/assembled A/B | 실제 동일 golden 비교 미실행 | EXP-SELECT.3~4 |
| NOT DONE | 최종 선택·local 병합 | winner 미선정 | EXP-SELECT.5 + 사람 리뷰 |

## 다음 실행 순서

1. c4.2.a lexical dispatch/revision2 → d2.x.b outcome/fusion eligibility → 후속 c4.2 reducer 순으로 연결한다.
2. EH3에서 catalog/analytics/list/table/figure specialist를 같은 evidence contract에 연결한다.
3. EH4에서 identity/reranker, local/API generator adapter, CLI와 계층별 evaluator를 완성한다.
4. baseline·local control·challenger의 corpus/gold/qrels/judge/budget/hash와 metric threshold를 동결한다.
5. parser→chunker→embedder→fusion→reranker→Harness component ablation을 수행한다.
6. 가장 좋은 구성의 assembled challenger를 baseline과 full golden E2E로 비교한다.
7. gate/Pareto 판정과 사람 리뷰 뒤에만 local branch 기본 profile을 전환한다. baseline은 rollback용으로 남긴다.

## 검증 상태

- d2.x.a 신규11 포함 인접79 PASS(21.052초), 독립 APPROVE/신규11 재실행 PASS. 전체1522/1522 PASS(186.315초, 오류/실패/skip0, exit0).
- 새 policy revision=`initial_and_first_dense_successor_v1`; initial signature/행동 유지, action/decision SHA는 새 정책으로 변경된다.
- 후속 dispatch에서 진단 lexical의 fusion 금지와 exact dense receipt의 obligation 재사용을 유지해야 한다.

### 선행 c4.1 검증

- c4.1 신규13+bridge7+history30=50 PASS, aggregate/decision/source 인접41 PASS. 독립 리뷰 APPROVE(신규13 재실행 PASS).
- 발급 중간 예외→failed 소비, barrier 동시성, transition 연결 hash, ledger tuple·원본 provenance 변조를 검증했다.
- c4.1 전체 회귀: `.venv` 1511/1511 PASS, 오류/실패/skip0, 174.977초, exit0. 이전1498에 신규13 추가.
- 후속 제한: 최초 unsearched state 밖에서는 실제 verifier-context ID fingerprint를 확장해야 한다. successor GC 후 정리 테스트도 c4.2에 연결한다.
- current/target mmdc PNG·Chrome/Playwright desktop/mobile PASS(images2, tables8, 오류/외부요청0).
  증거: `../../test/playwright-screenshots/controller-initial-transition-2026-09-06.png`.

### 선행 c4.0.e 환경 수리 이력

- EH2.6.c4.0.e focused 7/7, c4.0.c/d/e 인접 50/50 PASS.
- 전체 회귀 재검증(2026-09-06 11:53 KST): 프로젝트 `.venv`에서 **1,498/1,498 PASS**,
  errors/failures/skipped 0, 211.055초. 최초 bare Miniconda 실행의 1,438건·23 errors/2 failures는
  잘못 선택한 Python과 당시 sandbox 권한 문제였다. 의존성 동기화 및 정상 환경 재실행으로 해결했다.
  import 실패 모듈 복구로 수집 수가 늘었다. 근거: `../../test/errorlogs/backend/2026-09-06-eh2-6-c40e-full-regression-environment.md`.
- repository safety 941파일과 `git diff --check`는 PASS이며, c4.0.e 과정의
  API/OpenAI/model/Langfuse/golden/VLM/provider/clock 호출은 0이고 synthetic/offline fixture만 사용했다.
- 이 수치는 구현 무결성 결과이며 retrieval 성능 향상 수치가 아니다.
- current/target Mermaid PNG 재생성·직접 시각 검사와 HTML 로컬 자산/상태 참조 확인 PASS.
- 설치된 Chrome+bundled Playwright desktop/mobile QA는 이번 c4.0.e에 재실행하지 않았다.
  로컬 file URL 접근 정책 때문에 기존 c4.0.d 증거를 신규 PASS로 소급하지 않는다.
- c4.0.e focused/인접 결과는 당시 작업 원장에 기록했다. 현재 c4.0은 닫혔으며 d2는 여전히 PARTIAL이다.
- repository safety 941 files PASS.

판정: **실험 방향은 고정됐고 challenger 골격은 부분 구현됐지만, 동일 골든셋 성능 비교와 최종 아키텍처
선택은 아직 시작 전이다.**
