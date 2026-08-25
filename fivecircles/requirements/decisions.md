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
