# 협업 계약 설치 후 EOF 해시 불일치

- 시각: 2026-09-07 12:42 KST; batch=EH2.6.d2.x.b.1.
- 현상: 설치 검증 스크립트 exit1. 제안 계약은 LF2개(8297 bytes), apply_patch 결과는 LF1개(8296 bytes).
- 원인: 문서 의미는 같지만 최종 개행 정규화가 byte-level contract_id를 바꿨다. 본문·제품 파일은 변하지 않았다.
- 처리: Coder dispatch 전에 차단. Design이 설치된 한 개행 계약에 결속한 완전한 directive2를 반환했다.
- 검증: 계약 a94c4e18…와 directive2 hash40f51608… 확인. 상태 RESOLVED, directive1 미사용 이벤트 보존.
- 예방: 전달 형식(UTF-8/LF/EOF)을 먼저 고정하고 실제 설치 bytes를 확인한 뒤 WORK를 시작한다. hash 비교를 생략하지 않는다.
