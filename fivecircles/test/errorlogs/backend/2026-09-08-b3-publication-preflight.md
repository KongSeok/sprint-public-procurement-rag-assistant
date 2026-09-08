# B3 공개 사전 검사 — 해시 숫자 패턴

상태: NATIVE_SAFETY_FAIL / FINAL_PAYLOAD_REVIEW_PENDING. 제품 테스트 결과와 구분한다.

- 2026-09-08 실제 scripts/validate_repo_safety.sh는 exit1, PII_PATTERN_FOUND / Repository safety check: FAIL을 반환했다. SECRET_PATTERN이나 금지 경로 출력은 없었다. git diff --check는 exit0이다.
- 같은 개인정보 패턴을 읽기 전용으로 적용한 보조 관측에서 비이미지 후보1258개 중4개 필드가 탐지됐다. 이 관측 수를 scanner의 native 완료 집계로 바꾸지 않는다.
- 기존 b.2 candidate와 implementation-report의 두 해시 필드는 과거 공개 검수 대상이다. 이번에는 QUICKQA.1 candidate_files/0/sha256 및 QUICKQA.2 evidence_files/22/sha256의 같은 코드 해시도 걸렸다. 기존 두 필드의 예외를 새 필드에 자동 확대하지 않는다.
- 해당 새 해시는 보존된 initial/run_controller_quick_qa.py의 실제 SHA256과 일치했다. 별도 Critic도 원본 바이트를 검산해 비개인정보 코드 digest임을 확인했다. immutable QUICKQA.2 provenance report를 포함할 경우 초기 구현 입력을 식별하는 필요성이 있다. QUICKQA.1 보고서를 이를 이유로 B3 payload에 넣을 필요는 없다.
- 적용 근거는 security.md §4의 reviewer-established nonpersonal and necessary 값 조건이다. 일반 해시 예외나 자동 scanner PASS가 아니다.
- 최종 공개 판정은 실제 고정된 payload manifest와 파일 내용 검토 후 별도로 기록한다. 해당 보고서의 원문·private artifacts를 따라가서 함께 포장하지 않는다.
- resources/** ignore를 확인했고 검증 로그는 그 아래 private/validation에만 보존했다. 이 사전 점검에서 stage/commit/push/외부 게시와 scanner/policy 수정은0이다.

새로 추가되거나 바뀐 공개 파일은 최종 검사를 다시 받아야 한다. native FAIL 기록은 이후 수동 판정으로 덮어쓰지 않는다.

### 공개 검수 실제 회신 — 2026-09-08

- 실제 fresh Astra REVIEW012 `first-parent-publication-review-1`: PUBLICATION_ONLY PASS. 제품 최종 PASS011과 구분한다.
- 검토 대상은 고정60파일이며 후속2추가/3마감기록 갱신만 최종 재대조한다. 기존 공유 파일의 HEAD+소유 부분 투영과 다른 작업의 로컬 수정은 유지한다.
- 자동 검사 결과는 FAIL/exit1 그대로다. QUICKQA.2 보고서의 `/body/evidence_files/22/sha256` 한 필드만 기존 security §4의 비개인정보·필요성 조건에 따라 유지한다. 일반 해시 예외·scanner PASS가 아니다.
- 실제 최종62파일 inventory/hash/내용 검사 및 후보·계약·증거 불변 대조는 `batches/EH2.6.c4.2.b.3/publication-clearance.json`과 그 참조 영수증에 기록한다. 제품·계약·필수 증거·보고 의미 변경은 없다.
- 이 기록은 사후 검수 회신 반영이며 commit/push 성공 기록이 아니다.
