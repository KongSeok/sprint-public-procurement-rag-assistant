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
