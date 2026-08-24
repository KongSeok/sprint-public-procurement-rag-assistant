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
- Constraints: OpenAI 허용 모델은 `gpt-5-mini`, `gpt-5-nano`, `text-embedding-3-small`; 총 예산은 USD 20. GCP는 단일 4 vCPU/16 GB/L4/100 GB 이하 VM이다.

## D-005 — restricted 데이터와 외부 전송

- Date: 2026-08-24
- Status: PENDING_EGRESS_APPROVAL
- Confirmed: 원본, 추출문, 원문 수준 청크, 벡터 DB, private gold span과 PII는 restricted이며 제3자 서비스 전송은 금지한다.
- Pending: 이 특정 Drive corpus를 과정 제공 OpenAI API와 팀 GCP 프로젝트로 전송할 권한, 보존·학습 설정과 PII 처리 범위를 운영진 또는 데이터 소유자 근거로 확인한다.
- Safeguard: 승인 전에는 로컬 처리만 허용한다. Batch 0~2에서는 외부 모델 호출을 하지 않는다.

## D-006 — 평가 동결

- Date: 2026-08-24
- Chosen: 단일 문서·다중 문서·후속 질문·미지 질문을 dev/held-out으로 분리하고 `group_id` 단위 누수를 금지한다. held-out은 튜닝 종료 후 한 번만 실행한다.

## D-007 — 팀 역할 방식

- Date: 2026-08-24
- Chosen: PM·데이터·Retrieval·Generation을 완전한 사일로로 고정하지 않는다. 배치마다 주 담당자와 교차 검토자를 명시하고 모든 팀원이 전체 파이프라인을 이해한다.

## D-008 — HWP/PDF 추출기 기준

- Date: 2026-08-24
- Status: PROVISIONAL_UNTIL_FULL_CORPUS_RUN
- Observed: 원격 HWP 표본 1건은 OLE CFB 기반 HWP5 v5.1 계열이며 표본 헤더상 암호화·DRM 징후가 없었다. 이 관찰을 96건 전체에 일반화하지 않는다.
- Chosen: HWP는 격리된 Python 3.11 환경의 `pyhwp`/`hwp5txt`를 1차 후보로 쓰고, 페이지·표 fidelity가 부족하면 HWP5→HTML/ODT→PDF→`pdfplumber` 경로를 검증한다. 로컬 LibreOffice의 HWP97 필터는 HWP5 직접 파서로 사용하지 않는다.
- PDF: `pypdf` 페이지 텍스트를 최소 기준선으로 쓰고 문서별 격리 process timeout을 적용한다. 무텍스트·스캔 문서는 `ocr_may_be_required`로 실패시키며, 표·bbox 보존은 `pdfplumber` 보강 대상으로 둔다.
- Gate: 실제 private snapshot에서 96 HWP와 4 PDF를 전수 실행하기 전에는 파서 선정을 확정 상태로 승격하지 않는다.
