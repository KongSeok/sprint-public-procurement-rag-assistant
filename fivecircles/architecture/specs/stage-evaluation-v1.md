# 단계별 원문 근거 평가 v1

2026-09-05 · `feat/total-integration` · 사용자 승인: 기존 골든셋 유지, 누락된 평가부터 구현.

## 목적과 범위

베이스라인과 개선 아키텍처의 검색 품질·효율을 같은 시험지로 비교한다. 이번 선행 leaf는
EH4.7의 **오프라인 source-block 평가**다. EH2.EVAL.4의 qrels 소유권과
[evaluation-contract §9.1](evaluation-contract.md#91-retrieval-stage-checkpoint-and-offline-qrels-join)을 따른다.

- Mini131 질문·답변을 바꾸거나 40개로 축소하지 않는다. Core40+답변56+set13+visual10+analytics10+parser2를 유지한다.
- 보조69의 기존 홍우석 검수·11건 수정 기록을 재사용한다. 정형 qrel 미비를 ‘사람 검수 없음’으로 해석하지 않는다.
- 추가 대상은 지표·근거 위치 매핑·단계 기록이다. EDA10 추가나 신규 문항 작성은 이번 범위가 아니다.
- 런타임 검색/생성·VLM·임베딩·기본 앱 설정·API 호출은 변경하지 않는다. 골드는 evaluator에서만 결합한다.
- 모든 case를 ledger에 남긴다. visual/analytics/parser의 전용 평가는 이 지표와 혼합하지 않는다.

## 입력 / 소유권

`python -m midprojectrag.stage_evaluation`은 private 파일만 읽고 새 private 보고서만 생성한다.
입력은 `--data-root`, `--bundle`, `--manifest`, `--blocks-dir`, `--qrels`, `--records`, `--output`이다.
bundle은 기존 `load_bundle`로 검증한다. manifest와 block 파일 SHA가 bundle의 input_hashes와 맞아야 한다.
source snapshot SHA는 manifest SHA와 정렬된 `blocks_<doc_id>: file SHA` mapping의 canonical SHA다.

qrels JSONL은 질문/답변 복사가 없는 evaluator-only sidecar다. 각 행은
`case_id, suite, qrel_status, required_anchors`이고 status는 `ready|missing|not_applicable`이다.
ready의 anchor는 `doc_id, source_block_id, locator_hash`를 가진다. locator_hash는 private 원문
`source_locator` 문자열의 SHA256이다. source qrel을 새로 승인하는 기능은 없다.
missing과 not_applicable에는 anchor를 넣지 않는다. 빈 ready는 거절한다.
suite는 `core40|answer56|set13|visual10|analytics10|parser2` 여섯 값만 허용한다.
CLI 기본 `--inventory-mode mini131`은 각 suite 40/56/13/10/10/2 수량을 검사하고 한 행 누락도 거절한다.
연결 smoke만 `--inventory-mode partial`로 실행할 수 있으며 보고서에 `inventory.complete=false`를 남긴다.
inventory 완전성과 qrel/단계 기록 가용성은 별도다. 전체 131행이 있어도 모든 지표가 측정됐다는 뜻은 아니다.

실행 JSONL 한 행은 `schema_version='stage-evaluation-v1', case_id, run_id, binding, checkpoints`다.
binding은 `query_sha256, scope_sha256, evidence_store_sha256, run_config_sha256, execution_key_sha256`다.
execution_key는 같은 case 안의 obligation/round를 분리한다. 이번 v1은 case당 한 실행 chain만 받으며
다중 round/obligation 합산은 후속 adapter로 남긴다. 서로 다른 chain의 단계는 합치지 않는다.

checkpoint는 closed projection이며 stage/ordinal, binding, stage_config_sha256, source_receipt_sha256,
ordered_evidence_ids, ordered_stable_anchors, candidate_count, call_performed, outcome, projection_sha256을 가진다.
stage는 dense1/lexical2/visual3/fusion4/rerank5/final_context6이다. outcome은 `ok|unavailable|error`다.
원래 runtime checkpoint SHA와 별도로 projection SHA를 발급한다. 공개 projection에는 원문·질문·골드를 넣지 않는다.

기존 Lane/Fusion receipt의 실제 결과를 안전 projection으로 옮기는 adapter를 제공한다.
최종 context adapter는 실제 ContextPack의 선택된 child ID만 투영한다. parent window 원문은 복사하지 않는다.
후보/source anchor는 로드한 EvidenceStore에서 다시 확인한다. projection hash 검증은
**offline artifact consistency**이지 live owner authority나 실행 사실에 대한 암호학적 증명이 아니다.
최종 답변/fusion에서 없던 과거 단계를 역산하지 않는다. production 자동 기록 연결은 별도 후속이다.

## 계산 계약

Q=required source anchors, P=pre_context_stage(기본 fusion)의 모든 실제 후보 근거,
S=final_context의 선택된 child 근거다. 같은 block이 여러 child에 있으면 gain은 한 번만 준다.

| 지표 | 분자 / 분모 |
| --- | --- |
| 재랭킹 전 필수 근거 Recall | `|Q ∩ P| / |Q|` |
| 최종 context 필수 근거 Recall | `|Q ∩ S| / |Q|` |
| 관련 근거 유지율 | `|Q ∩ P ∩ S| / |Q ∩ P|` |
| lexical → dense rescue | `|Q ∩ (lexical − dense) ∩ fusion| / |Q − dense|` |
| 단계별 Recall@k | 실제 상위 k개 후보의 anchor 합집합과 Q의 교집합 / Q |

rescue는 대칭 방향도 별도 출력한다. raw 후보 수 유지율/단순 lexical-only 개수를 정답 근거 지표로 부르지 않는다.
기본 k=1,3,5,10. 중복 후보는 순위를 당기지 않으며 분모 0은 `not_applicable`,
단계 누락·오류·qrel 미비·unresolved anchor는 `unavailable`+사유+null이다.
실제 실행된 빈 검색 결과는 유효한 0점이다. 각 metric은 status/value/numerator/denominator/reason을 갖는다.
집계는 유효한 metric만 평균 내되 전체 case 수와 available/unavailable/not_applicable 수를 함께 표시한다.
선택된 block의 일부 child만 반환되어도 block recall은 올라갈 수 있다. **문장 완전성·의미 정답성 지표가 아니다.**
MRR/nDCG·slot·distinct-document 상세 채점과 실제 131 전 단계 실행은 EH4.7 후속이며 이번 네 핵심 지표와 완료를 구분한다.

## 순서 / DoD / 검증

1. EH4.7a.1: snapshot/owner/locator resolver와 append-only resolution receipt. chunk 변경 join 회귀.
2. EH4.7a.2: 순수 지표 함수. 중복 rank·실제 빈 결과·분모0·누락·rescue·context 손실 회귀.
3. EH4.7a.3: receipt/context projection 및 private CLI. 파일 기반 synthetic E2E, 입력 변조/chain 혼합/원문 누출 거절.
4. EH4.7a.G: 관련 회귀·독립 리뷰·도형/HTML 확인·로그. 실측 성능이나 EH4.7 전체 완료로 표기하지 않는다.

위험: 구형 결과에 단계 기록이 없으면 복구할 수 없다. 기존 검수는 보존하고 해당 case의 위치 qrel/실행 로그만 보강한다.
마이그레이션: 기존 evaluator와 run-record schema를 바꾸지 않는 병렬 CLI다. UI/production은 opt-in recorder 연결 후 별도 승인한다.

## Mini131 입력 adapter — EH2.EVAL.4.b (2026-09-06)

`stage_inputs.build_inputs(cases, ledger_rows, snapshot, source_file_hashes)`는 기존 검증된 Mini131 입력에서
closed qrels 131행과 content-free 가용성 ledger를 만든다. 기존 `verify_suite`를 CLI에서 먼저 사용한다.
입력 source case의 원본 row SHA/ID/lane 및 ledger와 정확한 집합 일치, suite별40/56/13/10/10/2를 확인한다.
원문 manifest가 명시된 row는 snapshot과 일치해야 한다. hash/owner가 어긋난 입력은 거절하고 재해석하지 않는다.

- core40의 `gold.evidence_refs`, answer56의 `evidence_refs`만 source-block anchor로 재사용한다.
  source_conflict는 positive 근거가 필요한 text case로 남긴다. unknown decision/refs shape는 거절한다.
- 기존 anchor 전부 owner/locator SHA가 확인될 때만 구조적 `ready`. 일부만 맞으면 전체 case `missing`으로
  남기고 일치한 일부로 분모를 줄이지 않는다. 없는 위치를 supporting_refs/검색 결과/모델 답변에서 추정하지 않는다.
- abstain text12와 visual10/analytics10/parser2는 이번 positive source-block recall에 `not_applicable`이다.
  전문 suite 및 기권 행동 평가는 제거된 것이 아니라 별도 지표 대상이다. set13의 doc qrels는 유지하지만
  source-block 위치가 없으므로 해당 block metric에는 `missing`이다.
- ledger: `case_id,suite,source_row_sha256,source_manifest_status,qrel_status,reason,required_anchor_count,
  required_doc_ids,source_review_status,source_review_sha256,reviewed_draft_sha256,semantic_approval`.
  `semantic_approval=not_assessed_by_adapter` 고정. source review status는 draft/approved 등 원래 필드만
  정규화해 기록하고 hash는 원래 검수 객체를 보존한다. 보조69 기존 검수 보고서는 EVAL.4.a/c에서 연결한다.
  `ready`는 의미 승인이나 공식 비교 허가가 아니다. doc qrel/검수 정보는 evaluator-only이며 request를 생성하지 않는다.

`python -m midprojectrag.stage_inputs --repo-root … --config … --data-root … --bundle … --manifest …
--blocks-dir … --output-dir …`는 기존 bundle/source snapshot을 검증하고 새 private 디렉터리(0700)에만
`qrels.jsonl`과 `inventory.json`(0600)을 만든다. inventory를 마지막에 기록하고 qrels file SHA를 봉인한다.
출력 디렉터리가 이미 있으면 거절한다. 중간 실패 폴더는 자동 덮어쓰기/삭제하지 않으며 완료 receipt 없이는 소비하지 않는다.
stdout은 status/count/hash만, 오류는 고정 코드만 출력한다. 모델/API/임베딩/runtime request 생성은 0이다.

검증: 전체131/130거절·중복/다른 lane·SHA drift·원문 locator mismatch·부분 근거 제외·gold 본문 비누출·
기존 질문/답변/검수 객체 불변·CLI private path/exclusive write/0600·기존 evaluator 연결.
공식 paired subset/승인 freeze와 hard-negative 보강은 .4.c/EXP-SELECT.2.a의 별도 gate다.

## 검색 recorder 최소 설정 — EXP-SELECT.2.a.1 (2026-09-06)

`retrieval_experiment.make_draft(artifact_hashes)` / `validate_draft(payload)`는 provider-free closed 설정을
생성·검증한다. `schema_version=retrieval-experiment-draft-v1`, `status=draft`,
`measurement_kind=retrieval_only`, `formal_comparison_authorized=false` 고정이며 E2E/공식 freeze를 발급하지 않는다.
질문·답변·문서 ID·gold·request·키/경로는 설정에 넣지 않는다.

- artifact_hashes의 키는 `input_inventory,source_snapshot,evidence_store,page_index,child_dense,child_lexical` 여섯 SHA256.
  이 leaf는 해시 형식만 검증한다. 실제 파일/실행 객체와의 결합은 EH4.7b.1/b.2, 정식 봉인은 .2.a.2다.
- query_policy: `legacy_pipeline_retrieval_query_v1`, latest history4, KURE8192 tokens/empty prompt.
  runner는 기존 `_retrieval_query`를 공통으로 사용하고 세 arm에 같은 query/scope를 전달해야 한다.
  scope policy는 원래 user scope만/all·empty를 구별, gold 기반 보충 금지다.
- 세 arm의 순서는 `page_kure,child_kure,child_bm25_rrf`. dense-only pre_context_stage는 lane_dense,
  hybrid는 fusion. page ID는 child RRF에 넣지 않는다. RRF k=60이며 raw 두 lane 기록을 먼저 보존한다.
- 첫 smoke 기본값: 각 dense50, hybrid lexical50, 반환10, 최종 선택5, 문서당 최대5, context12000자,
  parent expansion2400자. 이는 검색 품질 우승 설정이 아니며 동일 selector를 쓰는 새 retrieval-only 대조다.
  기존 앱의 생성/context 성능 재현 주장과 구분한다. positive integer/bool 거절·선택≤반환≤lane예산을 검증한다.
- config_sha256은 위 closed payload의 canonical SHA. load·query 문자열 생성·dense·lexical·fusion·context
  시간을 구분하며 cold load와 warm run을 섞지 않는다. 현재 dense 총시간에는 query embedding이 포함된다.
  native encoder timer가 없으면 query embedding 세부시간은 unavailable로 남기며 임의 차감/0으로 추정하지 않는다.
  반환 JSON은 입력과 분리한 사본이며 recorder 진입 때 hash/shape를 재검증한다. runtime trace 본문은 통째 저장하지 않는다.
- 최소 schema를 통과해도 .4.c 승인 qrels·paired 분모/threshold 동결 없이 formal run/우승/기본 profile 전환 금지.

DoD: schema/arm 구별·공통query/budget·불변 projection·hash drift·gold/임의키 거절·bool/0예산·draft 승격 거절
합성 테스트. 실제 recorder 연결과 KURE 실행은 다음 leaf에 남긴다.

## 실제 검색 관측 연결 — EH4.7b.1 (2026-09-06)

- 목표/범위: `stage_recorder.record_request`는 원래 RuntimeRequest의 질문/history/scope로 기존
  `_retrieval_query`를 만들고, 선택된 arm을 한 번 실행한다. qrels/정답/필수 문서 입력은 받지 않는다.
  metadata filter/옵션 override 등 아직 반영하지 않는 request 기능은 명시적으로 거절한다.
- page는 exact LegacyPageLane/ExactDenseIndex와 비주입 pinned KURE를 확인하고 mapping/hash를 재검증한다.
  child는 `require_production_hybrid`의 loader binding을 호출 전후 검사한다. page mapping 검증을
  child의 sealed production attestation과 같은 보증으로 표시하지 않는다. 실물 파일 해시 검증은 b.2 runner 책임이다.
- dense-only는 dense 한 번, hybrid는 dense/lexical 각 한 번 후 `fuse_rrf` 한 번이다.
  원시50 및 fusion 전체 union을 먼저 기록한 뒤 반환10 → 공통 `select_context`5를 적용한다.
  전체 검색을 반복 호출하여 중간 단계를 복원하지 않는다. VLM/reranker는 실행하지 않은 단계로 남긴다.
- 반환은 `{record, observations}`. record는 기존 stage-evaluation-v1 closed schema 그대로이며 한 arm씩 채점한다.
  observations는 ID/hash/호출 상태/고정 오류코드/시간/호출 수 allowlist만 포함하는 별도 관측 receipt다.
  run/case/arm은 execution key에, query/scope/config/store는 공통 binding에 묶인다. 각 stage receipt는
  upstream receipt hash와 출력 ID hash를 포함하고 checkpoint.source_receipt_sha256으로 연결된다.
  이는 offline 관측 기록이며 EH2 live-authority receipt나 공식 비교 승인서가 아니다.
- 실행한 빈 결과는 ok/0이며 wrapper call=true다. 내부 short-circuit의 encoder_calls=0은 관측될 때만 기록한다.
  실패 단계는 error/빈 ID/고정 코드, 미실행 downstream은 unavailable/null 시간이다. 오류 후 재시도·부분 fusion 금지.
  provider 오류 메시지, query/body, nested trace, parent window는 직렬화하지 않는다. binding 변조는 전체 실행 거절이다.
- 시간: query 생성 및 각 단계만 직접 측정한다. loader 시간은 runner의 별도 load receipt 대상이다.
  dense는 query embedding 포함이며 encoder 세부시간은 null이다. 모르는 호출 수는 null, 미실행은 0이다.
  이 leaf는 합성 실행으로 검증하며 실제 KURE query 호출은 b.2에서 별도 증명한다.
- DoD: 3종 호출 수/공통 query/scope, raw→fusion→return→context 순서, scoped empty/error/unavailable,
  owner/granularity/rank/hash drift, 합성 production 거절, content-free serialization, 기존 scorer 연결 회귀.

## Offline 연결 smoke — EH4.7b.2 (2026-09-06)

`python -m midprojectrag.retrieval_smoke --repo-root … --config … --data-root … --artifact-root …
--inputs-dir … --output-dir …`는 기존 suite/lock/store/source/input inventory 및 index를 재검증한다.
입력131은 유지하고 원래 core request 중 첫 explicit/첫 all 각1개만 연결 시험에 사용한다(gold 조건 선택 금지).
각 arm에서 동일2개 request를 2회 실행하며 arm/round별 독립 파일로 기록한다. 이는 131→2 평가셋 축소가 아니다.
질의 총12회, 실패 시 자동 재시도/범위 확대/전체 평가/생성/API 호출은 하지 않는다.

- HF cache offline-only, 고정 revision CPU KURE. 네트워크 다운로드·문서 재임베딩·index/source 변경 금지.
  page/child encoder는 서로 별개이며 child dense/hybrid만 같은 loaded backend를 재사용한다.
  `HF_HOME=<private/hf-cache> HF_HUB_CACHE=<private/hf-cache/hub> HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`을
  Python 시작 전에 설정한다. dense 모듈의 라이브러리 pin 과정에서 HF 상수가 초기화되므로 실행 중 env 변경으로
  cache를 전환하지 않는다. 시작 cache 불일치는 모델/출력 폴더 생성 전에 fail-fast한다.
  Hub 상수뿐 아니라 실제 tokenizer의 effective `TRANSFORMERS_CACHE`도 검사하여 legacy override를 거절한다.
- page_index digest는 metadata.json 파일 SHA, child lane digest는 각각 receipt.json 파일 SHA로 통일한다.
  실제 파일 및 원래8입력은 전후 SHA 비교하고 각 loader의 자체 검증을 유지한다.
- inventory는 canonical SHA·완료 상태·qrels file SHA·source/config/snapshot/131 case identity를 재검증한다.
  구조적 ready만 확인하며 qrels를 runtime에 전달하거나 의미 승인하지 않는다.
- 신규 private 디렉터리0700/파일0600/exclusive. arm/round별 records와 observations, 실행 전 계획,
  마지막 run receipt를 저장한다. 기존 디렉터리 거절, 중간 실패의 기록은 유지하고 완료 receipt 없이는 완료 취급 금지.
- loader별 시간과 실제 query 전체 wall time/단계 시간을 분리한다. 첫 backend query는 lazy model load를
  포함할 수 있다고 표시하고 native encoder/model-load 세부시간은 null이다. 전후 guard/관측 비용도 전체 wall에 포함한다.
  page와 child의 검증 보증 수준/비용이 다르므로 smoke wall time은 serving latency 비교 점수가 아니다.
- 완료 기준:12개 기록의 동일 case별 query/scope/config, required stages ok·calls 관측, untouched hashes,
  private 저장·누출 없는 집계. 오류/미실행이 있으면 smoke PASS를 주지 않는다. 성능 수치/우승은 판정하지 않는다.
