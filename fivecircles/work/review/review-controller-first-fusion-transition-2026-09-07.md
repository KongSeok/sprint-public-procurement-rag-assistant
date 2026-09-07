# 첫 fusion 실행·전이3 검수 — 2026-09-07

## Scope

- EH2.6.c4.2.b.1 / feat/total-integration / run=eh-relay-20260907. Sol Ultra 구현, fresh Astra deep 검수.
- 후보 sha256:b6ba30e02e09b6090f7ec1c17315cbe316ceefd1dc31544a352251c55cbcf17b; 계약 sha256:088d1280b7ccae54370aeb5d5fbcb648d4eea857ee8b1663e8d228a8efd06d7c; 증거 sha256:f1a433dbec5603855a6a418a17711589361d57a963b8d9a31bc66a66a657b03a.
- [원문 JSON REVIEW](../collaboration/eh-relay-20260907/messages/EH2.6.c4.2.b.1/003-first-fuse-review-1.json).

## 검수 결과

- 차단 지적 없음. 두 검색 결과의 실제 원본과 실행 권한을 따라 첫 fusion을 실행하고 전이3로 연결했다. 검색을 합쳤다는 이유만으로 의미 상태나 답변 가능 여부를 승격하지 않는다.
- 참고 의견 FF-INFO-1: 실행·결정·이전 상태·원본·RRF 결과를 여러 경계에서 다시 검증한다. 향후 성능 개선 작업이 승인되면 각 비용을 따로 측정할 수 있다. 현재 비용은 실측하지 않았으며, 이 검수로 검증 생략·새 응답시간 기준·최적화 작업을 승인한 것은 아니다.
- 추가 독립 검사: 동시 요청2개에서 실제 fuse_rrf 진입1회·후속 상태1개. 중복 요청과 전이3 재검증에서는 추가 실행0회, exit0. 원문 JSON에 재현 명령·입력·출력이 있다.

## 판정

APPROVE / REVIEW PASS. 집중12(747.497초)·관련185(289.662초)·격리197(846.583초)·전체1577(1079.654초) PASS, 실패/오류/skip0, exit0.

- 코드·테스트4개(실제 변경2개)와 계약2개 hash 전후 동일. 전체1577은 타 작업 테스트를 포함한 현재 저장소 수집 수다.
- 같은 첫 obligation의 두 원본으로 RRF를 1회 실행해 effect/ledger3/transition3를 만든다. action은1개 증가하지만 lane tuple·의미 상태는 그대로다.
- 실행 시작 시점과 claim 경계를 공유해 이전 실행 결과의 소급 결속을 막는다. 중복·동시 요청과 실패 후 재시도를 차단하고 이전 상태·결정·원본3개의 수명을 보존한다.
- 점수 기준을 정의하지 않아 direction_score=null. 이 결과는 합성 구현 검수이지 실제 검색 품질 향상이나 최종 구조 선정 결과가 아니다.

## 후속 제약 요약

1. c4.2.b/d2.x.b/Controller/E2E는 PARTIAL이다. 이번 PASS는 결속된 첫 fusion 후보와 계약·증거만 승인한다.
2. fusion 이후 행동 자격·상태 처리는 별도 Design에서 정한다. 둘 다 빈 검색 결과여도 부재 확정이나 답변 가능으로 취급하지 않는다.
3. 원자적 claim·공유 시작 시점·정확한 executor/minter/모듈/종류 결속·1회 소비·실패 후 재시도 금지를 유지한다.
4. 이전 실행·결정·원본3개를 유지한다. 과거 기록을 조회하는 일이 새 권한 발급이나 검색/fusion 재실행이 되면 안 된다.
5. 다음 비교 항목 실행 전 전체 canonical sibling-obligation 수명 계약을 정하고 검증한다. 만료된 항목을 얻으려고 tuple을 다시 만들지 않는다.
6. ordinal4/context/rerank/verify/reducer/follow-up/deadline/terminal/public start-step-run은 이번 승인 범위 밖이다. 후속 지시가 명시적으로 선택해야 한다.
7. 합성·오프라인 검증을 유지한다. baseline/corpus/gold/evaluation/runtime 설정을 바꾸거나 실제 모델·API·private 데이터를 실행하지 않는다. 별도 DIAG131의 소유권과 공유 호스트 진단 지연을 구분한다.
8. 프로파일링·최적화는 기존 실측 기반 개선 선택 절차를 따른다. 현재 테스트 시간으로 실제 서비스 병목이나 우위를 단정하지 않는다.
9. 검수된 파일과 계약만 선택 통합한다. 다른 dirty 작업은 보존하고 resources는 Git에서 제외한다. 제품·계약·필수 증거 변경은 재검수하며, 마감 기록은 별도로 남길 수 있다.

전체 제약과 근거는 위 원문 JSON REVIEW가 보존한다.

## 병렬 운영 판단

Controller 제품 코드는 한 Coder가 소유한다. 기존 DIAG131은 frozen snapshot/private 결과로 별도 실행하며 지연은 shared-host diagnostic이다. EH4.7a.G HTML QA는 독립 가능, EXP-SELECT.3.b 원인 분석은 완료 receipt 후 가능하다. 현재 판정만으로 새 업무를 실행하거나 미완료 평가를 완료로 처리하지 않는다.
