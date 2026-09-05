# 단계별 평가 연결 검증 오류와 리뷰 보완

시간: 2026-09-05 22:43 KST

- 초기 연결 fixture의 doc/block ID가 기존 chunk 규격에 맞지 않아 setup 9건이 실패했다. 정규 prefix+24 hex로 수정했다.
- 관련 회귀 명령의 추정 모듈명이 없었다. `rg --files tests`로 실제 `test_harness_context`를 확인해 재실행했다.
- TODO 동시 편집으로 첫 마감 patch가 실패했다. 다른 작업의 상호 참조 코멘트를 재확인·보존하고 단일 행 patch로 갱신했다.

리뷰 보완:
- Mini131 sidecar 행 누락이 전체 결과처럼 보일 수 있어 기본 CLI suite별 수량 강제, partial 불완전 표기를 추가했다.
- suite를 6종으로 닫아 visual/analytics/parser의 텍스트 평균 혼입을 차단했다.

결과: 집중·관련 112건 PASS. 실제 source98/20,118블록 검증 PASS. 원본 질문·답변 수정 없음.
예방: fixture ID 계약·실제 테스트 모듈명을 확인하고, 가용성과 전체 inventory 완전성을 별도 검증한다.
