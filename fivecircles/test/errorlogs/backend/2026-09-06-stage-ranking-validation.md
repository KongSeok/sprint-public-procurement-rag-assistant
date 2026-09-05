# 순위 지표 연결 검증

- 시각: 2026-09-06 07:18 KST
- 문맥: EH4.7c.1.a/b/c, 전체131 평가 sidecar/원래 document gold/기존12기록 재채점.
- 오류: 보고 mmd와 별도 freeze 계약 파일명을 추측해 read-only 조회2건이 파일 없음으로 종료했다. 코드 테스트 실패는 없었다.
- 해결: `rg --files`로 실제 `*-current-flow.mmd` 및 단일 `stage-evaluation-v1.md`를 확인했다. 조회 실패를 구현 실패로 세지 않았다.
- 방지: 기존 보고/계약 이름을 생성 규칙으로 추측하지 않고 파일 목록부터 검색한다. private 질문·답변은 출력하지 않는다.
- 결과: 관련118 PASS/독립34 PASS·APPROVE. 실제6보고서·12기록 재채점 PASS/모델0, 반복 metric/입력 불변.
- 별도 위험: source gold30/doc gold97은 구조적 가용성이다. 정식 승인/paired freeze·전체131 검색 품질은 미완료다.
