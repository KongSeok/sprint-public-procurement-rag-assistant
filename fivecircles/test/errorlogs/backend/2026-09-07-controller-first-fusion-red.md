# 첫 fusion 실행 — 기대 TDD RED

- 기록: 2026-09-07 13:53 KST / EH2.6.c4.2.b.1 / first-fuse-directive-1.
- 명령: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.test_controller_first_fusion_transition.
- 결과: exit1, 1 test / fact·compare subtest 오류2, 6.451초.
- 원인: 기존 모듈에 _execute_controller_first_fusion_step이 아직 없어 AttributeError. 새 동작의 기대 RED이며 기존 기능 회귀가 아니다.
- 근거: /private/tmp/eh-relay-20260907.GNy8vE/first-fuse-focused-red.log; SHA256 2d56982dc0ba9788b36a7d45f9833f40bac5e6164b852123c31a260813faa6f2.
- 처리: 기존 공유 attempt registry와 transition factory를 확장하는 구현 진행 중. 아직 해결/PASS로 기록하지 않는다.
- 경계: synthetic 최소 검사만 실행. 별도131 비교의 shared-host 실측 중이며 큰 회귀는 사전 조정한다.

## 확장 테스트의 anchor 필드 참조 오류 — 2026-09-07 14:13 KST

- 결과: first-fuse-focused-2.log, 12 tests / 439.790초 / exit1 / errors6, failures0.
- SHA256: 56fe83897b4f69edddc5a1f38c155805cbd26416127f6edea0cb3abcf3d2d36e.
- 원인: 정상 결과가 있는 fact/compare6개 분기에서 새 테스트가 StableEvidenceAnchor에 없는 evidence_id를 읽었다. 동시성/trace 실패 추정은 최종 로그로 확인되지 않았다.
- 수리: 테스트의 anchor/ID 위치 수 일치와 기존 validate_fusion_receipt의 정확한 근거 검증을 사용한다. 제품 코드·스키마·계약을 이 오류 때문에 변경하지 않는다.
- 상태: 재검증 대기. 통과 또는 전체 완료로 간주하지 않으며 실제 결과로 아래 갱신한다.

## 최종 해결 — 2026-09-07

- 초기 missing-executor RED는 구현으로 해결. 확장 테스트의 evidence_id AttributeError는 실제 anchor 스키마·기존 validator를 쓰는 test-only 수정으로 해결했다. 실패 원시 기록은 보존한다.
- 집중12(747.497초)·관련185(289.662초)·격리197(846.583초)·전체1577(1079.654초) PASS, 실패/오류/skip0, exit0. final 후보/계약6개 동일, fresh Astra PASS. 상태 RESOLVED.
- 초기 trace/concurrency 가설은 최종 traceback과 달라 원인으로 채택하지 않는다. 실제 제품/RAG 검색 실패로 집계하지 않는다.
