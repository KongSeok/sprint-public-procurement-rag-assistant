# Full regression sandbox boundary

- 시각: 2026-09-05 07:22 KST
- 상태: RESOLVED_ENVIRONMENT

## 증상

- 기본 샌드박스 전체 회귀에서 ignored private index의 `.index.lock` 생성이 거부되고, nested `sandbox-exec` 적용이 허용되지 않아 2건이 실패했다.

## 해결과 예방

- 동일 두 테스트를 실제 프로젝트 권한 환경에서 재실행해 2/2 PASS를 확인한 뒤 전체 회귀도 같은 권한 환경으로 재검증했다.
- private artifact lock과 OS sandbox self-test가 포함된 full gate는 제품 실패와 실행 샌드박스 실패를 분리해 보고한다.
