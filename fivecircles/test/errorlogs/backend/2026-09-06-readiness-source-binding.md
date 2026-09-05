# 사전 감사의 원본 요청 결합 보강

- 시각: 2026-09-06 07:33 KST
- 문맥: EXP-SELECT.2.a.2.i 순수 readiness helper 독립 리뷰.
- 문제: 원래 source는 그대로인데 template.question만 유효한 다른 질문으로 바꾼 합성 사례가 기술적 후보로 남았다.
- 원인: source hash와 RuntimeRequest shape를 각각 검사하고 두 투영의 일치를 검사하지 않았다.
- 해결: lane별 원래 question/history/scope와 template을 직접 대조. 불일치/fabricated set request는 source_request_mismatch.
- 검증: focused9/관련127 PASS, 독립 재리뷰9 PASS·APPROVE. 실제 최신002 전체131 감사 PASS/모델0, source30/doc84 유지.
- 이력: 실제001 CLI는 fresh verifier가 원래 template을 만들었으므로 실제 불일치는 관측되지 않았다. 001 보존·최신 정책002 별도 저장.
- 방지: 입력·요청의 개별 유효성뿐 아니라 연결 자체를 검증한다. fingerprint를 실제 query SHA/토큰 검사나 formal 승인으로 해석하지 않는다.
