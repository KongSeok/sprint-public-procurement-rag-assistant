# MidProjectRAG Task List

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
- [ ] HWP 페이지·표 및 PDF 표·bbox fidelity를 표본 QA하고 필요 시 결정된 fallback을 구현한다.
- 검증: manifest/schema 테스트, 실패 문서 누락 0건, PII 포함 로그 0건.

## Batch 2 — 평가 세트와 공통 계약 선확정

상태: READY_PRIVATE_GOLD (공개 계약·평가 도구·합성 검증 완료, 실제 60문항 작성 가능)

- [x] 단일 문서, 다중 문서 비교, 후속 질문, 미지 질문/기권 평가 스키마를 구현한다.
- [x] dev/held-out 분리와 group·질문·문서쌍·conversation 단위 누수 방지 규칙을 구현한다.
- [x] API와 GCP 로컬 스택이 공유할 요청·응답 JSON Schema와 오프라인 registry를 구현한다.
- [x] 검색·생성·인용·기권·latency·비용 지표 설정과 `validate/score/compare` CLI를 구현한다.
- [x] 평가 task floor·hard gate·explicit scope·안전 기권·A/B hash/shape 검사를 fail-closed로 고정한다.
- [ ] private corpus 근거로 dev 40문항과 held-out 20문항을 작성하고 2인 교차검토한다.
- [ ] held-out 파일과 질문 순서를 hash로 봉인하고 실제 source block·locator hash 무결성을 검증한다.
- 검증: 평가 테스트 31개, 오프라인 Schema 참조, split 누수, 응답·실행 기록 불변식 통과.

## Batch 3 — 시나리오 B API naive 기준선

상태: PENDING

- [ ] 단순 청킹 + `text-embedding-3-small` + Dense top-k 기준선을 구현한다.
- [ ] `gpt-5-mini` 또는 `gpt-5-nano`로 인용·대화 문맥·기권을 포함한 응답을 생성한다.
- [ ] 캐시·비용 원장·20달러 hard stop을 구현한다.
- 검증: 4대 시나리오 smoke test와 dev 기준선 리포트 생성.

## Batch 4 — 검색 개선과 절제된 ablation

상태: PENDING

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

## Batch 5 — 시나리오 A GCP L4 로컬 HF 및 공정한 A/B

상태: PENDING

- [ ] 4 vCPU/16GB/L4/디스크 100GB 이하에서 구동할 생성·임베딩 모델을 각 1개 선정한다.
- [ ] 공통 corpus snapshot·요청/응답 계약·평가셋으로 API 스택과 비교한다.
- [ ] 품질, cold/warm latency, GPU 시간, VRAM, 추정 비용을 기록한다.
- 검증: 동일 검색 설정 통제 비교와 각 스택 최선 설정 end-to-end 비교.

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
