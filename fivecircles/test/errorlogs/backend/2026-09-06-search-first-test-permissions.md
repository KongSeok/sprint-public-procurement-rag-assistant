# 검색 선행 납품 회귀 — 환경 권한 재검증

- 시각: 2026-09-06 00:01 KST (최초 전체 실행 종료 2026-09-05 23:58 KST).
- 증상: 전체1393건에서 인덱스 `.index.lock` 접근 PermissionError 1건, 중첩 sandbox_apply 거절 1건; skip1.
- 원인: 제한된 실행 환경의 private lock 쓰기·macOS sandbox 실행 권한. 이번 변경 모듈의 실패가 아니다.
- 조치: 코드/원본을 바꾸지 않고 실패한 아래 두 테스트만 승인된 실행 권한으로 재시도했다. 2/2 PASS(0.445초).
- 결과: 최초1390 PASS + 재검증2 PASS, skip1 유지. 전체1393/1393 단일 실행 PASS로 표기하지 않는다.
- 예방: private artifact read가 lock write를 요구할 수 있음을 사전 확인한다. 환경 오류는 해당 테스트만 재검증한다.

재검증 대상: `tests.application.test_refined_real_bundle.RefinedRealBundleTests.test_loads_98_document_page_index_without_provider_or_credentials`,
`tests.ingest.test_paddle_ocr_runtime.PaddleOcrRuntimeTests.test_actual_os_sandbox_denies_loopback_bind`.
모델/API 호출 없음. 조사 중 `ps`도 환경에서 거절됐으며 우회 조회하지 않았다.
