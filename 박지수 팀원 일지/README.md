# 박지수 팀원 일지

`feat/total-integration` 브랜치에서 진행한 Evidence-Harness 작업을 팀에 공유하기 위한 보고 문서 모음입니다.
원본 RFP, 추출 본문, 청크, 벡터, 질문·답변 원문과 API 키는 포함하지 않습니다.

## 문서 인덱스

| 권장 순서 | 문서 | 내용 |
| ---: | --- | --- |
| 1 | [Evidence-Harness 2단계 구현 진행 보고서](./2026-09-04-evidence-harness-phase2-progress-report.md) | EH2.1부터 EH2.6.b2까지의 전체 진행, 현재 위치, 변경량과 후속 작업 |
| 2 | [EH2.4 비교 근거 누락 방지 보고서](./2026-09-04-eh24-compare-doc-field-coverage-report.md) | 여러 사업 비교를 문서×항목 단위로 추적하는 구조와 검증 결과 |
| 3 | [EH2.6.b2 실행 경로 보안 강화 보고서](./2026-09-04-eh26-b2-runtime-integrity-security-report.md) | 검색기·실행 설정의 무결성 검증과 실행 전 차단 범위 |

## 읽을 때 주의할 점

- 현재 사용 가능한 기준선은 Mini131 로컬 베이스라인입니다.
- Evidence-Harness는 구현 중인 비교 실험군이며 아직 기본 실행 번들이 아닙니다.
- 보고서의 테스트 수치는 코드와 계약의 회귀 검증 결과입니다. Recall, nDCG, 답변 정확도 같은 RAG 성능 점수가 아닙니다.
- 검색 성능과 효율은 전체 controller와 생성 경로를 연결한 뒤 동일 골든셋 A/B로 판단합니다.
