# HWP Visual Corpus Rollout Contract

상태: **LOCAL_ROLLOUT_COMPLETE / EXTERNAL_ACTIVATION_BLOCKED**
결정일: 2026-08-28
선행 계약: `ordered-layout-asset-extraction.md`, `local-visual-retrieval-and-pdf-poc.md`

## 1. 목표와 문제

대표 HWP 한 건에서 검증한 canonical text/table + RenderTree order/bbox/fill + DocLang image
asset 결합을 먼저 서로 다른 위험 유형 5건에 적용하고, 같은 계약으로 refined HWP 94건 전체를
재개 가능하게 materialize한다. 5건과 94건의 strict gate가 모두 통과하면 전체
`table-md-visual-context-v2` 청크까지 local-only로 만든다.

현재 문제는 대표 한 건의 성공만으로는 긴 문서, 표 과다 문서, 병합·중첩 표, 그림이 많은 문서,
render join 불확실 문서에서 같은 품질을 보장할 수 없고, 중단된 전수 실행을 안전하게 재개하는
corpus-level 계약이 없다는 점이다.

## 2. 범위

### 포함

- pinned `rhwp v0.8.4`와 refined extracted manifest를 입력으로 하는 HWP 전용 batch runner
- 위험 유형을 서로 다르게 대표하는 익명 `doc_id` 5건의 고정 selection artifact
- per-document private visual bundle의 생성, 검증, 재사용 및 실패 격리
- 5건 2회 결정성 검증과 known schedule/image regression
- HWP 94건 전수 reconciliation 및 content-free aggregate report
- 94건의 verified table overlay를 사용하는 전체 visual-context v2 table chunks
- 외부 전송이 없는 schema/hash/unit/full-regression/local index 적재 가능성 검증

### 제외

- PDF candidate를 verified retrieval로 승격하는 작업
- OCR, VLM, diagram semantic summary, Upstage 또는 다른 외부 parser 호출
- OpenAI embedding 호출, private corpus egress, 비용 원장 소비
- 사람 fidelity review 전에 Streamlit 기본 runtime을 v2로 원자 전환하는 작업
- 원문 filename, 본문, 표 셀, 이미지 bytes를 Git 또는 public report에 기록하는 작업

외부 embedding/index/runtime 전환은 local artifact 완료 뒤에도 별도 명시 승인 경계로 남는다.

## 3. 입력·정체성 계약

- manifest: `resources/data_refined/private/manifest.extracted.jsonl`
- blocks: `resources/data_refined/private/blocks/<doc_id>.jsonl`
- layout overlay: `resources/data_refined/private/table-layout-v1.jsonl`
- HWP source: manifest의 `source_relpath`가 가리키는 `data_dir` 내부 regular file
- parser binary: absolute regular executable이며 SHA-256
  `b55fdfc53bcf3a1ca1b6cfe168b997d37055759d1bd6bb6491a4de50b2b1d529`
- 대상 문서는 `status=ok`, `index_eligible=true`, `extension=.hwp`인 서로 다른 정확히 94건이다.
- source, binary, blocks, per-document layout, config의 hash가 실행 전후 동일해야 한다.
- canonical source blocks, page-v1, table-md-rowgroup-v1, table-layout-v1은 수정하지 않는다.

## 4. 대표 5건 선택 계약

선택기는 원문 문자열을 보고 질문에 유리한 문서를 고르지 않는다. manifest와 canonical/render
artifact의 구조 통계만 사용해 다음 다섯 위험 역할을 각각 적어도 한 번 포함하고, `doc_id`와 수치형
근거만 private selection report에 기록한다.

1. schedule fill + known page/title/image regression
2. image-heavy 또는 body/table-nested image occurrence
3. merged/nested table 구조 위험
4. long/multi-page table 또는 고 page-count 위험
5. unresolved/nonbody/anchor-candidate layout join 위험

역할이 겹칠 수는 있으나 5개 `doc_id`는 모두 달라야 한다. 동률은 `doc_id` 오름차순으로 해소하고,
선택 결과와 selection policy hash를 이후 실행에서 고정한다.

## 5. 산출물 계약

### 문서별 bundle

`resources/data_refined/private/visual-v1/<doc_id>/` 아래에 다음을 metadata-last 방식으로 둔다.

- `table-visual-v1.jsonl`
- `images-v1.jsonl`
- `ordered-v1.jsonl`
- `metadata.json`

이미지 object는 공용 content-addressed
`resources/data_refined/private/hwp-assets-v1/objects/<sha256>.<ext>`에 저장한다.

### corpus-level private artifact

- `visual-v1/sample-selection-v1.json`
- `visual-v1/sample-run-v1.metadata.json`
- `visual-v1/corpus-run-v1.metadata.json`
- `chunks.table-md-visual-context-v2.jsonl`
- `chunks.table-md-visual-context-v2.jsonl.metadata.json`

corpus report에는 schema/method/config/input artifact hash, requested/succeeded/reused/failed counts,
익명 doc IDs, status count 합계, asset count/bytes, artifact-set digest만 둔다. source path, filename,
본문, 표 text, provider error는 포함하지 않는다.

## 6. 실행·재개 상태 계약

문서 상태는 다음 terminal state 중 하나다.

- `materialized`: 이번 실행에서 새 bundle을 원자 게시하고 재검증했다.
- `reused`: 기존 metadata와 3개 artifact, source/binary/config/blocks/layout hash, 모든 referenced asset의
  hash/size/MIME/dimensions를 다시 검증했다.
- `failed`: bounded machine error code로 실패했으며 성공 수에 포함하지 않는다.

기존 파일 존재만으로 skip하지 않는다. 검증 실패 bundle은 같은 문서 경로에 원자 재생성할 수 있지만,
source/binary identity 불일치, private-root escape, symlink ancestor, manifest 중복은 전체 실행을 즉시
중단한다. 문서 추출 실패는 sample에서는 fail-fast, 94건에서는 나머지 문서를 계속 진단한 뒤 전체
결과를 실패로 판정한다. 실행 순서는 항상 `doc_id` 오름차순이고 기본 concurrency는 1이다.

## 7. 단계별 합격 조건

### Gate A — 대표 5건

- selection report가 정확히 5개의 서로 다른 HWP와 다섯 위험 역할을 포함한다.
- 5/5 bundle이 strict verifier를 통과하고 failed=0이다.
- 같은 isolated output root에서 한 번 더 실행한 결과의 table/image/ordered/asset-manifest hash와
  aggregate artifact-set digest가 첫 실행과 byte-identical이다.
- 모든 canonical table block이 정확히 하나의 table overlay record로 reconciliation된다.
- 모든 image asset reference가 실제 object hash/size/MIME/dimensions와 일치한다.
- ordered occurrence는 page/sequence 단조 증가이고 manifest page count 밖을 참조하지 않는다.
- known representative에서 일정표 row-scoped fact와 body image exact join regression이 유지된다.
- unresolved/render-only 항목은 누락하거나 추정하지 않고 명시적 status로 보존한다.

### Gate B — HWP 94건

- 대상 집합이 정확히 94건이며 succeeded=94, failed=0, unexpected=0이다.
- 94/94 metadata와 모든 referenced artifact/asset을 실행 종료 시 다시 검증한다.
- per-document table 수 합계가 canonical HWP table block 및 layout overlay와 exact reconciliation된다.
- page count 합계와 각 문서 page 범위가 extracted manifest와 일치한다.
- unresolved/nonbody/render-only status는 집계되며 임의로 verified로 승격되지 않는다.
- 동일 입력 재실행은 94건을 모두 `reused`로 판정하고 corpus artifact-set digest가 변하지 않는다.

### Gate C — 전체 visual-context v2

- 기존 HWP `table-md-rowgroup-v1` 94문서의 모든 청크가 exact `block_id`/structure join된다.
- output 문서 수·청크 수가 source table chunk artifact와 동일하다.
- 기존 `display_markdown`, locator, page range, source/table structure hash는 불변이다.
- output은 단일 `table-md-visual-context-v2` contract/config hash를 사용하고 모든 chunk validator를
  통과한다.
- metadata가 source chunks, corpus run, concatenated overlay artifact hash를 고정한다.
- local-only index loader smoke가 통과해도 provider index 생성과 Streamlit 전환은 승인 전 수행하지 않는다.

## 8. 오류·보안 계약

- stdout과 public logs에는 aggregate와 bounded error code만 출력한다.
- 예외 문자열에서 source path, filename, corpus text, provider payload를 노출하지 않는다.
- 모든 input/output은 `data_dir`/private root containment와 symlink 검사를 통과해야 한다.
- output metadata는 content artifacts 뒤에 게시하고, 부분 게시 실패는 이전 generation으로 rollback한다.
- 중단 후 orphan temp directory는 성공으로 인식하지 않으며, material artifact 삭제를 자동 수행하지 않는다.
- 외부 API와 네트워크는 이 배치의 구현·실행·검증에 필요하지 않다.

## 9. 구현 배치

1. Batch A: strict bundle verifier, corpus schema, resumable runner와 CLI
2. Batch B: 구조 통계 기반 5건 selection 고정, 2회 결정성 및 fidelity gate
3. Batch C: 94건 sequential rollout, 실패 수리, 재실행 reuse gate
4. Batch D: 94문서 visual-context v2 chunk materialization과 metadata
5. Batch E: provider-free loader/local index smoke, 전체 회귀, visual flow report 갱신
6. Batch F: 사람 fidelity review 및 명시적 egress/비용 승인 뒤에만 API embedding/index/runtime 전환

각 배치는 `COMPLETED`, `BLOCKED`, `FAILED_AFTER_RETRY`, `SKIPPED_WITH_REASON` 중 하나로 닫은 뒤
다음 배치를 시작한다.

## 10. 테스트 계획

- unit: manifest/selection validation, resume verifier, tamper/hash/symlink/path escape, sanitized error,
  continue-on-error, deterministic ordering, aggregate reconciliation
- unit: visual v2 corpus join, missing/duplicate overlay, mixed config, metadata hash, atomic publication
- integration: synthetic 5-doc runner와 두 번째 전부 reuse 실행
- private Gate A: 고정 5건 두 isolated run의 artifact hash 비교와 대표 page visual/text 대조
- private Gate B: 94/94 생성, strict rescan, 즉시 재실행 94/94 reuse
- private Gate C: 35,128개 source table chunks와 count/identity 불변 비교(현재 snapshot 기준)
- regression: compileall, 전체 unittest, `git diff --check`, repository safety
- report QA: Mermaid target/current PNG를 갱신하고 HTML을 실제 browser/Playwright로 렌더 확인

## 11. 열린 승인 경계와 handoff

Gate A~E는 local-only이므로 이 원샷에서 계속 수행한다. Gate F의 OpenAI embedding 또는 다른 외부
parser에 private 원문/청크를 보내는 행위는 사용자의 목적지별 명시 승인 없이는 `BLOCKED`로 닫는다.
사람 fidelity review가 필요한 항목은 private 비교 artifact와 정확한 검토 위치를 handoff하되,
그 전까지 runtime 지원을 전건 verified라고 과장하지 않는다.

## 12. 실행 결과

- Gate A: 대표 위험 유형 5건 5/5 생성, 재실행 5/5 reuse, 동일 artifact-set digest.
- Gate B: HWP 94/94 성공·실패 0, 재실행 94/94 reuse, page 8,762개와 canonical table
  10,787개 exact reconciliation.
- 표: verified render 10,687개, layout unresolved 59개, render occurrence unresolved 41개.
- 이미지: supported source reference 440개(per-document unique 합계 410개, global object 406개), verified asset/render 58개,
  asset-only unlinked 382개, unsupported WMF/GIF source evidence 12개, render-only 498개.
- Gate C: source와 같은 35,128개 visual-context v2 chunk, prior-context 19,828개,
  strict schedule-context 70개, 두 실행 동일 chunk hash.
- provider-free local index: 35,128개 생성, 재실행 cache hit 35,128/35,128, known schedule
  page/table RRF와 page citation identity smoke 통과, 외부 API 호출·비용 0.

strict link 조건을 만족하지 못한 source asset은 bytes/provenance를 보존하되 page render와 연결하지
않았다. 따라서 local rollout 완료는 image semantic search 또는 전 이미지 page placement 완료를
뜻하지 않는다. 사람 fidelity review와 외부 embedding/runtime 활성화는 원래 승인 경계대로 남는다.
