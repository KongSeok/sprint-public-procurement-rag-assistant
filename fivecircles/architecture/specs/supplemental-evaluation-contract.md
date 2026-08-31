# Supplemental Evaluation Activation Contract

Status: PROVISIONAL_EXECUTION_AUTHORIZED · OFFICIAL_GOLD_APPROVAL_PENDING

Version: 1.1

Date: 2026-08-31

External calls: OpenAI 기준선 평가에 한해 명시적 private-corpus egress 승인과 비용 상한이 있을 때만 허용

## 1. Goal

기존 136개 취합 레코드에서 유지하기로 한 보조 평가 69개를 재현 가능한 실행 자산으로
전환하고, 사람 승인 전에도 `provisional` 등급으로 실제 기준선 평가를 허용한다. 사람 검수는
실행 차단 조건이 아니라 `official` 골드 승격 조건이다. 기존 4대 시나리오 dev 40의 동결된
평가 계약과 점수 문턱은 변경하지 않는다.

## 2. Background / Current Problem

69개는 다음 세 영역으로 확정돼 있다.

| 평가 영역 | 수 | 현재 문제 |
| --- | ---: | --- |
| 문서 조항·사실 답변 회귀 | 44 | 설명형 evidence만 있고 page/block qrel이 없음 |
| 조건·카탈로그 검색 | 13 | 순서 없는 정답 문서 집합과 전용 집합 채점이 필요함 |
| 정답·원문 일치 검수 | 12 | 기준 답변을 실제 원문과 사람이 대조해야 함 |

원본의 `source_document_ids`는 실제 `doc_id`가 아니라 원문 SHA-256이다. 총 112개 참조는
refined 98 manifest에서 모두 정확히 한 문서로 매핑되지만, 이를 명시적으로 변환해야 한다.
또한 필수 사실의 평면/중첩 형식, `very_easy`, 누락된 task type이 섞여 있고 11개 문항에는
알려진 내용 오류가 있다.

고정 입력:

- source 136 SHA-256: `2dab148e5c361f1d28facb1794a54da748b4b7da42252dbf1ad4668becbef79f`
- disposition SHA-256: `98a39d1e93a5adc34242eff2b47b1590d0fc212030ebcf233ed7216a64f910a6`
- correction override SHA-256: `535916fd703b3ce89a29b84858ae706c456457cdf9fd4845697b096fdc8e5a46`
- legacy CSV SHA-256: `5e4074d061bf4e38cad70446ff392e7aab8c6e7909f8bc90a7a6f2b270e6ed9d`
- refined manifest SHA-256: `6c91d30a4c01b12f1aae8924c88a2e5055446c841f5eabfbf687546fdc1fe1cb`
- refined snapshot: `snapshot_f14ad7018fae2d3905c4e604`

## 3. In Scope

- 44/13/12 ID를 원본과 disposition에서 정확히 추출한다.
- SHA-256 문서 참조를 refined `doc_id`로 변환한다.
- 필수 사실, 난이도, task type, source role을 정규화한다.
- 11개 알려진 정정을 private override로 적용하고 미적용 시 실패한다.
- 답변형 56개에 대해 문서별 page/block 근거 후보를 생성한다.
- 사람이 선택한 qrel과 정답 검수 결정을 별도 decision 파일로 기록한다.
- 집합검색형 13개에 대해 정답 문서 집합과 전용 Precision/Recall/F1 채점기를 제공한다.
- 답변형 56개와 집합검색형 13개를 현재 기준선에서 `provisional`로 실행·채점한다.
- 실행 기준선은 refined 98 page-only, `text-embedding-3-small`, `gpt-5-mini`, retrieval top-10,
  context top-5, citation 최대 3으로 고정한다.
- 모든 provisional 보고서에 등급, 승인 상태, 입력 hash와 metric coverage를 명시한다.
- 모든 산출물에 입력·출력 hash와 상태를 남긴다.

## 4. Out of Scope

- 기존 dev 40 / held-out 20 floor나 핵심 평가 점수 문턱 변경
- 질문·정답을 모델로 자동 수정하거나 LLM judge로 자동 승인
- 근거 후보를 사람 검수 없이 gold qrel로 승격
- provisional 결과를 official 골드 점수나 최종 모델 품질로 주장
- 현재 `RagResponse`의 citation 목록을 집합검색 결과 DTO로 오인
- private 질문·정답·원문·연락처를 Git이나 운영 로그에 기록
- GCP 비교 실행, corpus 재임베딩, 제품 runtime 기본값 변경

## 5. Assumptions

- `golden-set-final/`은 감사 입력이며 runtime이 경로를 하드코딩하지 않는다.
- private 입력과 결과는 `evaluation/private/supplemental/`에 두고 Git에서 제외한다.
- `review.status`와 평가 실행 등급은 서로 독립이다. `draft`도 provisional 평가할 수 있다.
- `enabled`는 official 배포 자산 플래그이며 provisional 실행 자격을 뜻하지 않는다.
- 13개 카탈로그 문항은 하나의 동일 유형이 아니다.
  `list_condition 6`, `single_lookup 4`, `purpose_qa 1`, `argmax 1`, `compare 1`로 분리한다.
- 현재 3개 citation 한도와 top-k 10만으로 12문서 정답 집합을 완전 반환할 수 없으므로,
  제품 연결 전 `selected_doc_ids` 집합 응답 계약이 추가로 필요하다.

## 6. Existing System Touchpoints

- 기존 핵심 평가: `src/midprojectrag/evaluation.py`
- 기존 핵심 case schema: `evaluation/schemas/eval-case.schema.json`
- refined manifest/blocks: `resources/data_refined/private/`
- 감사 입력: `golden-set-final/source/golden_testset__v6_.jsonl`
- 용도 배치: `golden-set-final/notion-136-disposition.json`
- 보조 구현: `src/midprojectrag/supplemental_evaluation.py`
- private 출력: `evaluation/private/supplemental/`

## 7. Proposed Design

```text
source 136 + disposition + refined manifest + private overrides
                         |
                         v
              prepare-supplemental
                  /             \
          answer draft 56     set draft 13
                  |             |
                  +------ provisional run/score
                  |             |
          evidence candidates   target sets
                  \             /
                   review decisions
                         |
                         v
              finalize-supplemental
                         |
                 official assets only
```

기존 dev40 evaluator에 69개를 합치지 않는다. 답변형 56은 기존 case 의미를 재사용하되
`profile=supplemental`로 별도 검증하며, 집합검색 13은 전용 case/run schema와 scorer를 사용한다.

## 8. Contracts

### 8.1 CLI / Tool Contracts

#### `prepare-supplemental`

입력:

- `--source-136`: 원본 136 JSONL
- `--disposition`: 44/13/12 배치 JSON
- `--overrides`: 11개 정정과 subtype/target 규칙을 담은 private JSON
- `--legacy-csv`: metadata 보조 근거의 행·필드·값 hash를 검증할 고정 CSV
- `--manifest`: refined manifest JSONL
- `--blocks-dir`: stable source block 디렉터리
- `--output-dir`: private 출력 디렉터리

출력:

- `rag-56.draft.jsonl`
- `set-13.draft.jsonl`
- `evidence-review-queue.jsonl`
- `review-case-index.jsonl`: 69개 case별 정확한 draft hash와 검수 유형
- `build-report.json`

동작:

- 외부 호출 없이 결정적으로 생성한다.
- 질문·답변·원문을 stdout이나 오류 메시지에 출력하지 않는다.
- 입력 hash, 44/13/12 수량, 112/112 SHA 매핑, 11개 정정 적용을 검증한다.

#### `finalize-supplemental`

입력 draft와 `review-decisions.jsonl`을 결합한다. decision의 `case_sha256`이 정확한 draft와
일치해야 하며 reviewer와 author가 같거나, required doc별 검수된 근거가 없거나, 정답 일치
승인이 없으면 해당 case를 승인하지 않는다. source-conflict·기권 승인은 검수한 전체 문서
범위를 `absence_scope_doc_ids`로 명시하고, CSV 보조 근거는 고정 CSV에서 다시 검증한다.

#### `validate-supplemental`

핵심 dev40의 task floor를 우회하지 않고 별도 supplemental profile을 검증한다.
기본 실행은 draft를 유효한 `provisional` 입력으로 검증하고 성공 보고서에
`evaluation_tier=provisional`, `official_gold_ready=false`를 기록한다.
`--require-approved`가 있으면 draft가 한 건이라도 남을 때 official 검증이 실패한다. 이때 `--manifest`,
`--legacy-csv`, `--blocks-dir`가 필수이며 block/page/locator와 CSV row/field/value hash를 재검증한다.

#### `score-set`

정답·예측 `doc_id` 집합으로 macro/micro Precision, Recall, F1, exact-set-match, count accuracy를
계산한다. `--manifest`가 필수다. 기본은 draft case도 `provisional`로 채점하며,
`--require-approved`를 지정한 official 실행만 승인·enabled case를 요구한다. 문서 순서는 채점하지
않고 중복·manifest에 없는 doc ID·누락 run은 실패한다. 보고서에는 `evaluation_tier`와
`official_gold_ready`를 반드시 기록한다.

#### `score-answer`

답변형 56개 실행 기록에서 document Recall@1/3/5/10, MRR@10, nDCG@10, required-doc citation
coverage, 기권 동작과 실행 오류율을 계산한다. 자동 사실 문자열 일치는 보조 진단으로만 기록하고
정답성·충실성의 official 판정으로 사용하지 않는다. 기본은 provisional이며 official 실행은
`--require-approved`를 요구한다.

#### `supplemental-baseline`

고정 config는 `evaluation/baselines/supplemental-provisional-v1/config.json`이다.

- `--preflight-only`: case/manifest/chunk/index hash와 56/13/98/9,331 수량을 외부 호출 없이 검증한다.
- `--score-existing`: 이미 생성된 private run만 오프라인 채점한다.
- `--run-openai --approve-private-corpus-egress`: OpenAI에 골든 질문과 검색된 RFP 근거를 보내는
  실제 기준선을 실행한다. 승인 플래그가 없으면 provider stack을 만들기 전에 실패한다.
- case별 run JSONL을 원자적으로 저장하고 config·answer eval·set eval hash checkpoint가 다르면
  재개하지 않는다. USD 2.00 전용 ledger를 사용한다.
- stdout 최종 receipt와 Git 추적 receipt에는 질문·답변·문서 발췌를 넣지 않는다.

### 8.2 DTO / Schema Contracts

#### Supplemental answer case

- `legacy_id`: 원본 ID
- `lane`: `qa_regression` 또는 `answer_alignment`
- `profile`: 항상 `supplemental`
- `task_type`: `single_doc`, `multi_doc_compare`, `unknown`
- `question`, `gold.reference_answer`, `gold.required_fact_groups`
- `source_sha256s`: 원본 필드에서 이름을 바로잡은 SHA 목록
- `required_doc_ids`: refined manifest에서 변환한 실제 ID
- `evidence_refs`: 사람이 승인한 `doc_id + block_id + page + locator_hash`
- `absence_scope_doc_ids`: 기권·source-conflict에서 사람이 전체 확인한 문서 범위
- `supporting_refs`: legacy CSV의 file hash + row + field + value hash + locator hash
- `source_labels`, `legacy_scoring_notes`: 정정된 감사 문맥을 private asset에 보존
- `review`: author, reviewer, status, reviewed_at
- `reviewed_draft_sha256`: 승인 asset이 어떤 draft를 검수했는지 보존
- `enabled`: `review.status=approved`일 때만 true

#### Set-retrieval case

- `case_id`, `legacy_id`, `profile=supplemental`
- `subtype`: `list_condition|single_lookup|purpose_qa|argmax|compare`
- `question`
- `required_doc_ids`: 순서 없는 전체 정답 집합
- `expected_count`: `required_doc_ids` 길이와 같아야 함
- `required_fact_groups`: subtype별 답변 채점용 사실 그룹
- `set_definition`: 정답 집합의 포함 기준과 snapshot hash
- `review`, `enabled`

#### Review decision

- `case_id`, `reviewer`, `reviewed_at`, `decision`
- `case_sha256`: 승인자가 확인한 정확한 draft에 결정을 결합
- `answer_verified`: 원문과 기준 답변의 일치 여부
- `evidence_refs`: required doc별 최소 1개
- `absence_scope_doc_ids`: 전체 부재 확인이 필요한 문서 ID
- `notes`: 선택 사항이며 원문 전문을 복제하지 않음

### 8.3 Normalization Rules

- NFC 정규화와 공백 축약을 적용한다.
- `very_easy`는 `easy`로 바꾸고 원래 값을 tag로 보존한다.
- `string[]` 필수 사실은 각 항목을 독립 그룹으로 만든 `string[][]`로 변환한다.
- CSV는 검색 문서가 아니라 `supporting_sources`로 분리한다.
- 설명형 legacy evidence는 `legacy_evidence_note`로만 보존하고 qrel로 사용하지 않는다.
- SHA 참조는 `source_sha256s`로 이름을 바로잡고 실제 `doc_id`를 별도로 추가한다.
- multi 문항의 comparison axis는 override로만 지정하며 질문에서 추정하지 않는다.

### 8.4 Required Correction Gate

다음 11개 ID의 정정 override가 모두 있어야 한다.

`G01`, `G21`, `G23`, `C14`, `C23`, `C25`, `B1`, `B14`, `B23`, `H13`, `H22`

특히 B14의 정답 집합은 pinned refined manifest와 pinned override가 지정한 project-name 기준
7건이어야 한다. C25를 포함한 CSV 보조 근거 7문항은 RFP와 metadata를 별도 source role로
표현하고, pinned CSV의 행·필드·값 hash를 검증한다. 정정 본문은 private override에만 둔다.

### 8.5 State Machine / Workflow Contracts

```text
prepared -> provisional_executable -> review_pending -> approved -> official_executable
                                           \-> rejected
```

- `prepared`: 기계 정규화와 문서 매핑 통과
- `provisional_executable`: draft 상태로 기준선 실행·점수 산출 가능
- `review_pending`: 근거 후보가 생성됐으나 사람 선택 전
- `approved`: 이름·시각이 있는 사람 결정과 qrel 검증 통과
- `official_executable`: approved asset만 모은 finalize 출력
- `rejected`: 정답 불일치 또는 원문 근거 부족

자동화는 provisional 결과를 만들 수 있지만 `approved`나 `official`을 만들 수 없다.

### 8.6 Permission / Risk Rules

- private 원문·질문·답변은 로컬 팀 공유 범위에서만 처리한다.
- 로그에는 ID, 수량, hash, 오류 코드만 남긴다.
- prepare/validate/score는 provider를 호출하지 않는다.
- 실제 baseline run은 `--approve-private-corpus-egress`가 있을 때만 OpenAI로 골든 질문과 검색된
  RFP 근거를 전송한다. 이 승인은 목적지가 OpenAI이고 전송 내용이 질문·문서 발췌라는 사실 및
  실행별 비용 상한을 명시해야 한다.
- 질문·답변·문서 발췌는 stdout, Git, 공개 receipt, observability backend로 보내지 않는다.
- Git 추적 대상에는 schema, 코드, synthetic test, aggregate 결과만 허용한다.
- `golden-set-final/`, `preview/`, `evaluation/private/`, `resources/data_refined/`는 Git에서 제외한다.

### 8.7 Error / Capability Gap Rules

다음은 non-zero 종료다.

- 수량이 44/13/12가 아니거나 ID 중복·교집합이 있음
- source/disposition/manifest hash가 다름
- correction override 또는 legacy CSV hash가 다름
- SHA가 0개 또는 여러 doc으로 매핑됨
- index 비대상 문서가 required target에 포함됨
- 질문·정답·필수사실·정답 문서 집합이 비어 있음
- 11개 정정 중 하나라도 미적용
- B14 target이 7이 아님
- 답변형 approved case가 required doc별 qrel을 갖지 않음
- 목록형 expected count와 target 길이가 다름
- 승인자·시각 없이 approved/enabled가 설정됨
- decision case hash가 draft와 다르거나 source-conflict/기권의 absence scope가 없음
- 승인 자산의 block·CSV locator가 고정 원본과 다름

Capability gap:

| Gap | Impact | Proposed resolution |
| --- | --- | --- |
| 제품 응답에 전체 `selected_doc_ids`가 없음 | 12문서 정답 case의 완전한 E2E 채점 불가 | 별도 structured catalog response DTO 추가 |
| 사람 qrel/정답 승인이 0건 | 69개를 공식 점수에 편입할 수 없음 | review queue를 팀원이 검수하고 decision 파일 작성 |

위 gap은 provisional 기준선 실행을 막지 않는다. 현재 baseline 최적화는 provisional 69 전체를
분모로 진행하고, official 보고서만 별도로 차단한다.

## 9. Acceptance Criteria

- [x] prepare가 정확히 56 answer draft와 13 set draft를 만든다.
- [x] 44/13/12 lane 수와 69 unique ID가 고정된다.
- [x] 112개 source SHA 참조가 refined doc ID로 100% 매핑된다.
- [x] 11개 정정 gate와 B14 7건 target gate가 통과한다.
- [x] 모든 answer draft가 required doc별 근거 후보 또는 명시적 blocker를 가진다.
- [x] 사람 승인 전 approved 수는 0이며 official 검증은 실패한다.
- [x] 사람 승인 전 56+13 전부 provisional 검증·실행·채점이 가능하다.
- [ ] provisional 보고서가 등급·승인 상태·입력 hash·coverage를 명시한다.
- [x] 고정 config와 실행 코드를 선별해 Git 추적 가능한 상태로 만들고, private run은 로컬 ignored
  경로로 제한한다.
- [x] set scorer가 순서 불변이며 perfect/extra/missing 예측을 정확히 채점한다.
- [x] 기존 dev40/evaluation/api-matrix 테스트가 회귀 없이 통과한다.
- [x] private 텍스트가 Git·stdout·운영 로그에 유출되지 않는다.

## 10. Implementation Batches

### Batch 1: Contract and schema

**Goal:** 보조 평가 경계와 fail-closed schema를 고정한다.

**Scope:** 본 문서, set case/run, review decision schema, registry.

**Done when:** synthetic schema tests와 offline registry 검사가 통과한다.

### Batch 2: Deterministic preparation

**Goal:** 136+disposition+manifest에서 56/13 draft와 review queue를 만든다.

**Scope:** 정규화, SHA→doc ID, private override, 근거 후보 생성, hash report.

**Done when:** 수량·매핑·정정 gate가 모두 통과하고 재실행 byte hash가 같다.

### Batch 3: Human review finalization

**Goal:** 승인 결정만 official 실행 자산으로 승격한다.

**Scope:** reviewer 분리, qrel 검증, answer alignment, 승인/거절 상태.

**Done when:** 승인 없는 자동 승격이 불가능하고 synthetic 승인 흐름이 통과한다.

### Batch 4: Set scorer

**Goal:** 13개 집합 검색을 순서와 무관하게 채점한다.

**Scope:** set run validation, macro/micro P/R/F1, exact match, count accuracy.

**Done when:** perfect/extra/missing/duplicate/unknown/missing-run 테스트가 통과한다.

### Batch 5: Private build and handoff

**Goal:** 실제 69 draft와 review queue를 생성하고 팀 검수에 넘긴다.

**Done when:** aggregate report만 로그에 남고 private 내용은 ignored 경로에만 존재한다.

### Batch 6: Provisional baseline execution

**Goal:** 56 answer + 13 set 전체를 고정된 refined 98 기준선으로 실행·채점한다.

**Scope:** provisional run schema, answer/set scorer, resumable private runner, content-free aggregate receipt.

**Done when:** 69/69 run record와 등급·hash·coverage가 있는 점수 보고서가 생성되고 official gate는
계속 실패한다.

## 11. Test Plan

- Unit: mixed required facts, difficulty mapping, SHA mapping, deterministic IDs, correction gate.
- Contract: closed schema, registry offline resolution, reviewer/author 분리, target uniqueness.
- Integration: private input으로 56/13/69 수량과 112/112 mapping, byte-deterministic rerun.
- Set metrics: perfect 1.0, extra→precision 감소, missing→recall 감소, order invariant.
- Provisional: draft 56+13 validation and scoring pass; reports state provisional and official false.
- Official: the same draft inputs fail with `case_not_approved` when `--require-approved` is set.
- Provider gate: `--run-openai` 단독 실행은 provider 생성 전 실패하고, 명시적 egress 플래그만 실제
  adapter를 호출한다. fake pipeline으로 answer/set atomic checkpoint와 complete resume 0-call을 검증한다.
- Regression: `tests/evaluation`, `tests/test_api_matrix.py`, compile, diff-check, repository safety.
- Privacy: 실패 메시지에 question/gold/source text가 포함되지 않는지 검사.

## 12. Open Questions

- 실제 검수자 이름과 승인 시각은 팀 검수 때 입력한다.
- 13개 집합 검색을 제품 UI에 연결할 `selected_doc_ids` DTO는 별도 구현 승인이 필요하다.
- held-out 20은 이 69개와 별도이며 이번 범위에 포함하지 않는다.

## 13. Handoff Notes for Implementation Agent

- 기존 `evaluation.py`의 task floor나 `api_matrix.py`의 40건 gate를 완화하지 않는다.
- private 문항 내용을 tracked 코드·tests·docs에 복사하지 않는다.
- 실제 build는 정본 루트 `/Users/pio/Documents/AIENGINEERCOURSE/MidProjectRAG`에서만 실행한다.
- 실패 시 ID와 오류 코드만 남기고 질문·답변·원문은 출력하지 않는다.
