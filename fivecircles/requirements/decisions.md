# MidProjectRAG Decisions

## D-001 — 프로젝트 정체성과 자료 권위

- Date: 2026-08-24
- Context: 복사된 fivecircles에 과거 프로젝트 요구사항이 남아 있었다.
- Chosen: 공식 프로젝트명은 `MidProjectRAG`로 고정한다. Codeit Notion은 과제 범위의 기준이고, 사용자가 지정한 Drive 폴더는 유일한 실제 corpus다.
- Impact: 가져온 프로젝트 자료는 `fivecircles/legacy/`에 격리하며 활성 요구사항·스펙의 권위를 갖지 않는다.

## D-002 — 기준선 우선 개발

- Date: 2026-08-24
- Context: 3주·4명 범위에서 검색 기법을 동시에 구현하면 실패 원인을 분리하기 어렵다.
- Chosen: 시나리오 B의 naive Dense RAG를 먼저 완성하고 dev 평가에서 확인된 실패만 단계적으로 개선한다.
- Impact: MMR·hybrid·multi-query·reranking은 Batch 4의 조건부 후순위다.

## D-003 — 원문과 CSV의 역할 분리

- Date: 2026-08-24
- Context: CSV `텍스트` 열은 원문 전체가 아니라 잘린 미리보기다.
- Chosen: CSV는 metadata 라우팅과 요약 신호로만 사용하고, 검색 근거는 HWP/PDF 원문에서 추출한다.
- Impact: `Copy of ` 제거와 Unicode NFC 정규화로 원문 100건을 CSV와 1:1 조인하며 실패를 manifest에 남긴다.

## D-004 — A/B 스택 순서와 공정성

- Date: 2026-08-24
- Chosen: OpenAI API 스택을 먼저 구현한 뒤 GCP L4 로컬 HF 스택을 구현한다. 두 스택은 동일 요청/응답 계약, corpus hash, 평가셋과 질문 순서를 사용한다.
- Constraints: OpenAI 허용 모델은 `gpt-5-mini`, `gpt-5-nano`, `text-embedding-3-small`; 총 예산은 USD 20. GCP는 단일 `g2-standard-4`(4 vCPU/16 GB)/L4 VM이며 디스크 hard max는 200 GB다. 운영 목표는 100 GB 이하이고 사용량 80 GB에서 경고한다. 기본 region은 `us-central1`, `sprint-ai-chunk4-0*` 배정은 `us-east1`이다.

## D-005 — restricted 데이터와 외부 전송

- Date: 2026-08-24
- Updated: 2026-08-25
- Status: APPROVED_FOR_COURSE_OPENAI_AND_GCP
- Confirmed: 원본, 추출문, 원문 수준 청크, 벡터 DB, private gold span과 PII는 restricted이며 제3자 서비스 전송은 금지한다.
- Approval: 사용자가 이 특정 Drive corpus를 과정 제공 OpenAI API로 처리하고 provider의 명시된 보존정책을 수용하는 것과, 팀의 과정 제공 GCP 프로젝트에서 처리하는 것을 승인했다.
- Scope: 승인 대상은 과정 제공 OpenAI와 팀 GCP뿐이다. API key·서비스 계정·원문·청크·벡터 DB는 Git과 공개 산출물에 남기지 않는다.
- Safeguard: OpenAI 호출은 `store=false`, transient connection/408/409/429/5xx에 한한 SDK `max_retries=2`, USD 20 hard stop과 명시적 egress flag를 유지한다. 자격증명이 없는 환경에서는 네트워크 호출 전에 중단한다.

## D-006 — 평가 동결

- Date: 2026-08-24
- Chosen: 단일 문서·다중 문서·후속 질문·미지 질문을 dev/held-out으로 분리하고 `group_id` 단위 누수를 금지한다. held-out은 튜닝 종료 후 한 번만 실행한다.

## D-007 — 팀 역할 방식

- Date: 2026-08-24
- Chosen: PM·데이터·Retrieval·Generation을 완전한 사일로로 고정하지 않는다. 배치마다 주 담당자와 교차 검토자를 명시하고 모든 팀원이 전체 파이프라인을 이해한다.

## D-008 — HWP/PDF 추출기 기준

- Date: 2026-08-25
- Status: ACTIVE_RHWP_PRIMARY_WITH_FALLBACK
- Observed: 체크섬을 검증한 `rhwp v0.8.4` macOS ARM64 바이너리로 HWP 96건을 전수 점검한 결과 페이지 텍스트와 표 추출 모두 성공 96건·실패 0건이었다. 페이지 텍스트는 총 7,076,421자로 기존 `hwp5txt`/binary-model 결과 2,168,048자의 약 3.26배였고, 표 11,183개·병합셀 66,929개·중첩표 셀 571개가 구조적으로 검출됐다.
- Chosen: HWP/HWPX는 고정 버전 `rhwp`의 `export-text --json`과 `export-tables --json`을 주 추출기로 사용한다. 페이지별 텍스트와 병합셀 표 구조를 별도 canonical source block으로 보존하고, bbox가 필요한 표본은 `export-render-tree`, 시각 검증은 SVG 또는 한컴 PDF를 사용한다.
- Retrieval policy: 페이지 본문은 `primary`, 표 구조 block은 `structured_auxiliary`로 분리한다. naive 기준선은 primary만 임베딩하며, 표 구조 lane은 별도 실험 전까지 같은 ranking pool에 중복 투입하지 않는다.
- Reproducibility: production gate는 명시적 절대경로, `rhwp v0.8.4`, 실행 바이너리 SHA-256, adapter version이 모두 일치해야 통과한다. 페이지 절단/누락, 표 `cellCount` 불일치와 span 겹침은 실패-폐쇄형으로 처리한다.
- Fallback: `rhwp` 실행·파싱이 실패한 HWP5만 `hwp5txt` → 격리 `pyhwp` binary-model 순서로 복구한다. HWP를 PDF로 먼저 일괄 변환하지 않으며 PDF 변환은 특수문서 검증·fallback에 한정한다. 별도 `hwp-mcp`는 운영 추출 의존성이 아니다.
- Caveat: `export-tables`의 논리 표와 render-tree bbox는 별도 출력이라 자동 조인율을 검증해야 한다. `rhwp` 페이지 번호는 내부 출력끼리는 일치하지만 한컴 조판 페이지와 항상 같다고 가정하지 않는다.
- PDF: `pypdf` 페이지 텍스트를 최소 기준선으로 쓰고 문서별 격리 process timeout을 적용한다. 무텍스트·스캔 문서는 `ocr_may_be_required`로 실패시키며, 표·bbox 보존은 `pdfplumber` 보강 대상으로 둔다.
- Verified: 고정 실행 identity로 100건을 두 번 재추출해 각각 `ok=100`, `partial=0`, `failed=0`이었고 strict primary gate를 통과했다. 20,569개 source block과 문서별 metadata 산출은 반복 실행 간 byte-for-byte 동일했으며 실제 manifest 100행과 block 20,569행이 JSON Schema 오류 0건이었다.
- Gate: parser/manifest 전환은 완료했다. Batch 1 전체 fidelity gate는 팀원 데이터 탐색 리뷰 교차확인에 더해 5건 표본 page/table↔bbox 및 한컴 페이지 QA까지 통과해야 닫는다.

## D-009 — 공통 평가 계약과 성공 조건 동결

- Date: 2026-08-24
- Status: ACTIVE_CONTRACT_PRIVATE_GOLD_PENDING
- Chosen: API와 GCP-local 스택은 동일한 요청·응답 Schema, corpus/evaluation/scoring hash와 4대 task 평가 계약을 사용한다. dev는 task별 10건, held-out은 task별 5건을 최소로 한다.
- Frozen gates: Recall@1/3/5/10, 검색·답변·인용·기권 품질, error rate, API USD 20, 비용/GPU 측정 coverage의 operator·값·stack scope를 `evaluation/config/metrics.json`에 고정한다.
- Unknown safety: 표준 비사실 기권문, gold reason 일치, `safe_abstention=true`, dev 1인/held-out 2인 검토를 모두 충족해야 성공으로 집계한다.
- Fairness: 비교는 통과한 API 1건과 GCP-local 1건만 허용하며 corpus, evaluation, scoring-config hash와 case/task 수가 일치해야 한다. 외부 Schema 참조는 로컬 registry로만 해석한다.
- Pending: 실제 private corpus로 dev 40건과 held-out 20건을 작성·교차검토·봉인하는 작업은 원문 materialization 뒤에 수행한다.

## D-010 — 기준선 관측성 및 Langfuse 전송 범위

- Date: 2026-08-25
- Status: APPROVED_METADATA_ONLY_SYNTHETIC_VALIDATED
- Chosen: 로컬 JSONL evaluator를 유일한 평가 원장으로 사용하고 Langfuse v4는 검색 rank·latency·token·cost·숫자 점수를 보는 선택형 보조 UI로만 사용한다.
- Approval: 사용자가 Langfuse Cloud로 비식별 metadata를 전송하는 것을 OpenAI corpus egress와 별도로 승인했다.
- Prohibited: 질문, history, source/chunk text, prompt, completion, 실제 filename/locator, gold answer와 reviewer memo는 Langfuse로 보내지 않는다. OpenAI wrapper와 자동 I/O capture도 사용하지 않는다.
- Runtime: 기본값은 disabled이며 `--approve-langfuse-metadata-egress`와 자격증명이 함께 있을 때만 활성화한다.
- Validation: 2026-08-26 합성 `RagPipeline`을 Langfuse Cloud에 실전송해 7개 observation, 6개 부모 연결, content-free I/O, token/cost와 Boolean score를 재조회했다. 원문 canary 유출과 adapter failure/drop은 0건이었다.
- Projection note: SDK 4.14.5 송신 직전 `embed.query`·`generate.answer`의 model 속성을 확인했으나 Observations API v2의 `providedModelName`은 null이었다. 애플리케이션은 allowlisted `embedding_model`·`generator_model` metadata를 유지하며 자동 I/O capture나 provider wrapper로 우회하지 않는다.

## D-011 — 개인 OpenAI API 2×2 잠정 기준선

- Date: 2026-08-26
- Status: APPROVED_PERSONAL_OPENAI_PROVISIONAL_BENCHMARK
- Approval: 사용자가 자신의 OpenAI API 키로 private corpus를 임베딩하고 dev 질의를 생성하는 것을 명시적으로 승인했다.
- Matrix: `text-embedding-3-small`/`text-embedding-3-large`와 `gpt-5-nano`/`gpt-5-mini`의 네 조합을 동일 corpus·dev case·retrieval/generation 설정으로 비교한다.
- Boundary: small 조합은 과정 허용 기준선 후보이고 large 조합은 개인 계정 탐색 실험이다. 팀 사람 리뷰 전 dev 40 결과는 공식 점수가 아닌 `provisional`이다.
- Budget: 네 조합은 별도 개인 API 비용 원장을 공유하며 USD 5에서 provider 호출 전에 hard stop한다. 기존 프로젝트 USD 20 상한은 완화하지 않는다.
- Privacy: OpenAI 호출은 `store=false`, transient 오류에 한한 SDK `max_retries=2`를 사용한다. 원문·질문·응답·벡터·키는 private 경로 밖이나 Git/표준 출력에 기록하지 않는다.

## D-012 — 메타데이터 결측·날짜 오매핑 정정

- Date: 2026-08-26
- Status: COMPLETED_HIGH_CONFIDENCE_WITH_REVIEW_QUEUE
- Chosen: 원본 `data_list.csv`는 불변으로 보존하고, 공식 자료 또는 정확한 로컬 source block 근거가 있는 고신뢰 값만 private correction overlay를 통해 별도 수정본에 반영한다.
- Date semantics: 입찰서 제출 시작·마감과 개찰 일시를 서로 다른 필드로 취급한다. 기존 마감 열에 개찰 시각이 들어간 것이 확인되면 마감값을 바로잡고 개찰 필드로 분리한다.
- Unknown policy: 확인할 수 없는 값은 추정하지 않고 `원문 미기재`, `해당 없음`, `외부 확인 필요`로 구분한다.
- Deferred: 과거 입찰 히스토리 문서 수집은 이 정정 패스가 끝난 뒤 비용·권한·매핑 난이도를 검토하는 후순위다.
- Verified: 105개 감사 결정 중 apply 74·clear 3·retain-null 28, 실제 변경 77개다. 원본 hash를
  유지한 채 수정본 100행과 exact manifest join 100/100, 전체 207 tests와 repository safety를 통과했다.

## D-013 — small+nano Streamlit 기준선과 dual-manifest 경계

- Date: 2026-08-26
- Status: APPROVED_AUTOMATED_AND_HEALTH_VERIFIED_BROWSER_VISUAL_PENDING
- Chosen: 첫 Streamlit 데모는 과정 허용 임베더 `text-embedding-3-small`과 비용 대조 생성기
  `gpt-5-nano`를 사용하며 dense top-10, 생성 context top-5, citation 최대 3건을 고정한다.
- Boundary: UI는 `midprojectrag.application` facade만 호출한다. provider·index 조립과 artifact 검증은
  composition root가 담당하고 UI는 자동 재임베딩·자동 재색인을 수행하지 않는다.
- Data identity: retrieval manifest와 corrected catalog는 동일한 100개 `doc_id`·원본 SHA·정규화
  파일명을 공유하지만 metadata는 실제 77개 셀이 변경됐다. 두 hash를 별도 기록하며 표시 metadata만
  바뀐 경우 기존 vector를 재사용한다.
- Rebuild: 본문·청크 경계가 바뀌면 새 chunks/index가 필요하고, 임베더 또는 차원이 바뀌면 문서와
  query 임베더를 함께 교체해 전체 새 index를 만든다. 생성 모델만 바꾸면 재임베딩하지 않는다.
- Privacy: API key는 UI 입력으로 받지 않으며 corpus egress는 요청마다 명시 승인한다. 첫 bundle의
  Langfuse backend는 disabled다.

## D-014 — 교정 metadata의 답변 근거 경계

- Date: 2026-08-26
- Status: ACTIVE_UI_LABEL_ONLY_METADATA_RETRIEVAL_PENDING
- Observed: retrieval manifest와 corrected catalog은 문서 정체성 100/100이 같지만 metadata는
  실제 77셀이 변경됐다. 현 Streamlit composition은 corrected catalog의 사업명·발주기관만
  문서 선택과 인용 라벨에 사용하고, 나머지 교정 필드를 retrieval/generation prompt에 전달하지
  않는다.
- Chosen: locator 없는 catalog 값을 기존 page chunk의 근거로 위장하지 않는다. 현 범위를
  label overlay로 명시하고, 공고번호·금액·일정을 답변하기 전 field provenance/locator와
  metadata citation 정책을 먼저 계약한다.
- Reuse: label-only overlay는 기존 vector를 재사용할 수 있다. metadata를 dense 검색 대상으로
  합류하면 새 chunk/index version과 재임베딩이 필요하며, 별도 exact metadata lookup을 쓰면
  정답 문서 routing·citation validity를 gold set으로 검증한다.
- Review fixes: trace의 `config_sha256`는 run-config hash로 바로잡았고, OpenAI egress 동의에
  최근 history 전송을 명시했으며, catalog/섹션 라벨을 plain text로 렌더한다.

## D-015 — 구조화 metadata lane과 본문 RAG의 분리

- Date: 2026-08-26
- Status: IMPLEMENTED_LIVE_API_CONTRACT_E2E_VERIFIED_ANSWERABLE_GOLD_PENDING
- Chosen: 공고번호·차수·금액·입찰일·발주기관은 corrected catalog와 correction overlay를
  결합한 로컬 typed catalog에서 exact/range/date 조회한다. 결과 `doc_id`만 기존 body Dense
  RAG의 explicit scope로 전달하며, 기존 9,509개 청크 임베딩과 RagResponse v1은 유지한다.
- Citation boundary: metadata 카드의 감사 상태·근거 종류와 생성 답변의 실제 본문 페이지
  citation을 분리한다. metadata fact를 임의 본문 페이지에 귀속시키지 않는다.
- Provider boundary: catalog DTO, fact, evidence, 공식 URL, locator를 RagRequest·provider prompt·
  trace·log에 직렬화하거나 주입하지 않는다. 사용자 질문 또는 승인된 본문 청크에 같은 문자열이
  독립적으로 존재하는 경우는 기존 body-query egress 계약을 따른다.
- Runtime: config 1.1은 correction artifact hash를 요구하고 provider 생성 전에 검증한다.
  metadata browse/filter는 자격증명 없이 동작하며 OpenAI pipeline은 승인된 첫 본문 질문에서만
  지연 생성한다.
- Review: 두 차례 변경 요청을 반영한 뒤 독립 최종 리뷰 `APPROVE`; 차단 P0/P1 없음.
- Live verification: 2026-08-27 승인된 단일 explicit-scope 호출에서 small 임베딩, dense 검색,
  top-5 context, nano 생성과 응답 계약 검증이 완료됐다. 첫 사례는 `insufficient_evidence`로
  정상 기권했으므로 answerable gold의 실제 인용 답변은 별도 품질 gate로 유지한다.

## D-016 — 중복 제거 98문서 refined source-of-truth 전환

- Date: 2026-08-28
- Status: SOURCE_MIGRATION_COMPLETE_DOWNSTREAM_REBUILD_PENDING
- Supersedes: D-003/D-008/D-012~D-015의 active corpus가 100문서라는 전제만 대체한다. 당시
  구현·실험·결과는 해당 100문서 snapshot의 역사 기록으로 유지한다.
- Chosen: `private/corpus_v1` 100문서는 비교·재현용 불변본으로 보존하고,
  `resources/data_refined`의 98문서(HWP 94/PDF 4)를 편집 가능한 현재 source of truth로 사용한다.
- Dedupe evidence: 서로 다른 파일명의 두 쌍이 각각 size와 SHA-256까지 같음을 확인하고 오표기
  파일 및 CSV 행을 한 건씩 제거했다. retained raw hash 98개는 모두 고유하다.
- Naming/identity: 실제 파일과 CSV를 `refined_`+NFC로 통일한다. `Copy of `와 `refined_`는
  non-identity prefix이므로 retained 98개 `doc_id`는 기존과 같다.
- Direct materialization: 기존 high-confidence corrected metadata 중 retained rows의 실제 변경
  69셀을 refined CSV에 직접 반영하고, `텍스트` 98행은 pinned `rhwp/pypdf` canonical primary
  blocks를 이어 붙인 full body로 교체했다. HWP/PDF 바이너리는 수정하지 않았다.
- Verified: refined CSV 98행×15열, raw 98개, literal/NFC join 98/98, missing/extra/collision 0,
  raw/content duplicate 0, body hash 98/98, stable doc ID 98/98, pending manifest/verify gate 통과.
- Runtime boundary: 기존 100문서 9,509-chunk index와 provisional run은 새 corpus 결과가 아니다.
  98문서 extraction manifest/chunks/catalog/index/evaluation을 재생성·검증한 뒤에만 Streamlit
  active config를 전환한다. retained chunk hash가 같으면 검증된 vector-filter reuse를 허용하고,
  다르면 전체 재임베딩한다.

## D-017 — refined 구조화 표 검색 레인

- Date: 2026-08-28
- Status: LOCAL_IMPLEMENTATION_COMPLETE_API_ACTIVATION_PENDING
- Trigger: 표 중심 시험에서 병합 헤더 관계 질문과 다중 문서 비교 근거가 기존 page-only
  검색의 top-k/context에서 누락되어 D-002/D-008의 조건부 표 레인 승격 조건을 충족했다.
- Chosen: `resources/data_refined`의 canonical `table_structure`에서 결정적 Markdown row-group
  청크를 만들고, page와 table을 별도 exact dense index로 유지한다. 질문 임베딩은 한 번만
  생성하며 두 레인의 rank를 RRF로 합친다.
- Chunk policy: caption/문서 문맥 + 반복 header + 최대 8개 연속 행을 기본으로 하고 보수적
  크기 상한을 함께 적용한다. 병합셀은 검색 표현에서 값을 전개하되 원본 span·구조 hash와
  source locator는 metadata에 보존한다.
- Citation boundary: 검증된 page join이 없는 표에 페이지를 추정하지 않는다. table citation은
  구조 locator를 항상 보존하고, page/bbox는 render-tree join이 검증된 경우에만 채운다.
- Runtime boundary: 기존 100문서 v1 번들은 역사본으로 보존한다. 새 runtime config와 page/table
  artifact의 모든 hash가 refined 98문서와 일치한 뒤에만 기본 bundle을 원자 전환한다.
- PDF boundary: 1차 표 레인은 구조화 표가 존재하는 HWP 94건을 대상으로 한다. PDF 4건은
  별도 table extractor와 fidelity QA를 통과하기 전까지 page lane만 사용한다.
- Verified local artifacts: refined 98문서 extraction은 실패 0건이며 page 9,331개와 table
  Markdown 35,128개를 생성했다. render-tree exact join은 top-level table 10,782개 중
  10,728개(99.50%)이며, 연결된 table chunk 33,338개는 모두 실제 manifest page 범위와
  page chunk에 대응한다. 미검증 54개와 nested table 1,524개에는 page를 추정하지 않는다.
- Activation gate: 기존 page vector는 9,509개 중 retained 9,331개를 byte-for-byte 동일하게
  이관해 외부 호출 없이 완료했다. 별도 destination-specific 승인으로 table text를 OpenAI
  small에 임베딩한 뒤에만 v1.2 bundle과 Streamlit 기본 config를 전환한다.

## D-018 — HWP ordered visual evidence overlay와 asset 경계

- Date: 2026-08-28
- Status: LOCAL_CORPUS_COMPLETE_HUMAN_GOLD_AND_RUNTIME_ACTIVATION_PENDING
- Trigger: 사용자가 표를 plain text로 펼치면 제목·순서가 어긋나고 일정표 fill 의미와 그림이
  누락되는 문제를 확인했으며, 외부 API 없이 로컬 parser 기반으로 개선하기로 승인했다.
- Chosen: D-008/D-017의 pinned `rhwp v0.8.4` canonical text/table과 기존 source block ID를
  유지하고, RenderTree의 page order/bbox/Rect/Image 및 DocLang raw asset을 별도 versioned
  private overlay로 결합한다.
- Evidence boundary: Rect는 색상 이름이 아닌 fill evidence로 기록한다. 일정 의미는 strict
  `M`, `M+n` header mapping이 일의적일 때만 파생한다. raw image 추출은 OCR/diagram 이해와
  분리하며, page/bbox/asset은 독립 검증 없이 추정하지 않는다.
- Compatibility: current page-v1과 table-layout-v1은 불변으로 유지한다. overlay/search artifact는
  별도 hash/config를 사용하고 98문서 reference reconciliation과 fidelity QA 전에는 runtime을
  전환하지 않는다.
- Relay: HWP evidence v1 완료 뒤 PDF 4건 bounded local parser PoC, visual retrieval/citation,
  local OCR/VLM을 각각 독립 gate로 평가한다. 외부 parser API와 HWP 전건 PDF 변환은 채택하지 않는다.

## D-019 — 로컬 visual retrieval과 PDF candidate PoC 경계

- Date: 2026-08-28
- Status: IMPLEMENTED_REPRESENTATIVE_AND_PDF_POC_RUNTIME_ACTIVATION_PENDING
- Chosen: 기존 checksum-pinned `rhwp v0.8.4`를 유지하고, 대표 HWP에서 ordered occurrence,
  cell fill evidence, content-addressed image asset을 별도 private bundle로 만든다. 검증된 overlay는
  기존 table Markdown 앞에 prior title과 row-scoped schedule fact만 붙이는 v2 변환기로 소비한다.
- PDF: `pdfplumber >=0.11,<0.12` lines strategy 결과는 table/image 확정 객체가 아니라 candidate다.
  일반 ruled table은 유용하지만 box diagram 과검출과 일정표 row text 정렬 손실이 확인되어 단독
  canonical parser 또는 기본 retrieval lane으로 채택하지 않는다.
- External boundary: 98문서 9,332쪽을 Upstage Document Parse로 처리하면 공개 단가 기준 Standard
  약 $93.32, Enhanced 약 $279.96(VAT 전)라서 기본 ingest로 채택하지 않는다. 외부 egress가 허용된
  별도 품질 비교에서만 선택적으로 평가하며 retrieval은 계속 자체 구현한다.
- Alternatives: `rhwp-python`, `unhwp`, `hwp-hwpx-parser`는 표·중첩표·image API가 유망하지만
  현재 94-HWP corpus와 fill/bbox 정합을 통과하지 않았으므로 주 parser를 교체하지 않는다.
- Activation gate: 94-HWP materialization, 사람 fidelity gold, PDF candidate calibration/OCR 분리,
  v2 재임베딩·index identity·citation 검증 뒤에만 Streamlit 기본 runtime을 전환한다.

## D-020 — visual occurrence v2와 local understanding 증거 경계

- Date: 2026-08-30
- Status: PUBLIC_IMPLEMENTATION_COMPLETE_PRIVATE_GATES_BLOCKED
- Trigger: HWP image link가 문서 단위 ordinal/count/aspect gate 때문에 58/950만 연결되고, PDF visual
  PoC가 actual resource provenance와 durable runner 없이 stale artifact로 남은 문제를 해결한다.
- Chosen: source object와 page occurrence를 분리한 additive `VisualOccurrenceV2`를 먼저 만들고,
  `doc_id + page + bbox + crop_sha256`가 검증된 region에만 local OCR/layout과 선택 caption을 붙인다.
- Identity: rhwp document-local source key가 최우선이다. key가 없으면 raw SHA 또는 normalized
  RGBA SHA와 exact bbox evidence가 모두 일치하고 후보가 유일할 때만 verified link다. ordinal,
  aspect, proximity, OCR, pHash, CLIP, caption은 verified identity 근거가 아니다.
- PDF: pypdf resource bytes/path와 pdfplumber placement를 reconciliation하고 raster, inline,
  vector, table, table-child, decorative, ambiguous를 분리한다. PyMuPDF는 라이선스 결정 전 제외한다.
- Understanding: PP-StructureV3/Korean PP-OCRv5가 첫 local 후보이며 caption은 support ref가 있는
  claim만 factual evidence다. 외부 parser/search API와 private egress는 계속 금지한다.
- Activation: public code/schema/fixture gate와 private human/model/5→94 실행 gate를 분리한다.
  private gate가 끝나기 전 기본 Streamlit/runtime을 전환하지 않는다.
