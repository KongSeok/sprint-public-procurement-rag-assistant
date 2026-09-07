# 공개 검사: 합성 테스트 diff 해시의 숫자열 탐지

- 시각: 2026-09-07 17:31 KST. run=eh-relay-20260907 / batch=EH2.6.c4.2.b.2.
- 명령: bash scripts/validate_repo_safety.sh, exit1. 출력은 PII_PATTERN_FOUND / Repository safety check: FAIL.
- 대상은 candidate.json artifacts.untracked_diff.sha256 및 구현 보고 candidate_manifest.new_test_diff_sha256 두 필드다. 실제 합성 테스트 diff의 SHA-256을 재계산해 동일함을 확인했다.
- 매칭 숫자열은 각 64자리 해시 내부에 있으며 여기에는 복사하지 않았다. 키·전화번호·원문을 발견했다는 뜻으로 단정하지 않는다.
- 제품/테스트/계약과 원본 candidate/report·탐지 스크립트를 수정하지 않았다. 전체/격리 제품 검증 PASS와 공개 검사의 exit1을 구분한다.
- 기존 security §1·§4·§6의 비개인·필수 값 확인 절차에 따라 fresh 공개 검수 대기. 자동 검사를 PASS로 표기하거나 범용 예외를 추가하지 않는다.
- 원시 명령/출력·파일 hash·content-free 위치 근거: /private/tmp/eh-relay-20260907.GNy8vE/first-fuse-state-publication-audit.json.
- [현재 배치](../../../work/2026-09-07-controller-fusion-state-relay.md), [기존 공개 정책](../../../architecture/specs/security.md).

## 독립 판정 — 2026-09-07 17:42 KST

- first-fuse-state-publication-review-1 PASS: 기존 보안 정책 §1·§4에 따라 두 원본 JSON pointer의 값이 비개인·필수 SHA256임을 독립 확인했다.
- 자동 결과 FAIL/exit1은 그대로다. 이는 scanner 통과나 범용 해시 예외가 아니며, 후보·구현 보고·탐지기·정책은 수정하지 않았다.
- 검수한 공개 payload38개와 이후 명시된 검수/상태/오류 metadata만 최종 재대조한다. 미검수 추가 탐지·내용 변경은 공개를 차단한다.
- [원문 공개 REVIEW](../../../work/collaboration/eh-relay-20260907/messages/EH2.6.c4.2.b.2/005-first-fuse-state-publication-review-1.json). 최종 실제 패키지 검증 전 공개 완료로 처리하지 않는다.
