# 검색 단계 recorder 검증

- 시각: 2026-09-06 06:13 KST.
- 독립 리뷰: child granularity와 Evidence.kind(text)를 혼동한 검사를 수정했다. UTF-8 query SHA 규칙과 호출 timer도 정합화했다.
- 최초 focused11 PASS. scorer 연결 추가 후 관련 실행74 PASS/모듈 discovery 실패1(test_child_context 이름 추정).
- 재발 방지: `rg --files tests`로 실제 test_harness_context를 확인하고 재실행한다. 원시 결과/본문은 로그에 남기지 않는다.
- 실제 로컬 query 호출·품질 측정은 b.2/정식 비교와 분리한다.
- 재실행: recorder12 포함 관련88 PASS(0.458s), 독립 APPROVE. 실제 core40 request shape도 원문 출력 없이 검증했다.
