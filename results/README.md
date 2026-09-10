# results/

Generation 파이프라인 평가 결과 요약. 세부 채점 과정과 원본 실행 로그는
각 항목에 표시된 노트북을 참고.

평가 기준은 core40(40문항)·rag-56(56문항)·set-13(13문항) 골든셋이며,
채점기는 팀 공식 버전을 사용했다.

## Generation 자체 평가 (core40 / rag-56 / set-13)

| | core40 | rag-56 | set-13 (F1) | 출처 노트북 |
|---|---|---|---|---|
| 최초(v2) | 88.96 | 63.18 | 미측정 | `pipeline_construction_and_visual_test.ipynb`, `pipeline_scoring_and_grading_fix.ipynb` |
| v9 완성 | 93.96~96.04 | 66.88 | 미측정 | `generation_prompt_and_variance_experiment.ipynb` |
| Citation 형식 통일 + 목록형 질문 처리 후 | 95.21~95.83 | 75.09~79.23 | 0.991 | `citation_format_experiment.ipynb` |
| 낮은 점수 재조사 + 규칙 기반 후처리 적용 후 | 96.04 | 94.29 | 0.991 | `low_score_reanalysis_experiment.ipynb`, (채점기 v3.0.1 검증 세션) |

*core40/rag-56은 LLM 생성 자체의 변동성으로 재실행마다 점수가 소폭
오르내림. 표에 적힌 값은 관측된 범위 또는 대표값.

## 팀 통합 평가 (Golden Set v3, 79문항)

| 실행 | End-to-End | 어휘 사실 점수 | 비고 |
|---|---|---|---|
| B-v1 | 55.77 | - | 초기 버전 |
| B-v2 | 63.88 | - | Set 개선 반영 |
| 채점기 v3.0.1 기준 재채점 | 70.12 | 74.24 | 이전 생성 결과 재채점 |
| 최신 생성 + 인용 통일 | 82.33 | 82.32 | 텍스트 중심 |
| 최신 생성 + 인용 통일 + VLM | 85.37 | 87.63 | 최종 통합 |
| 규칙 기반 후처리 적용(01:51 실행) | 86.71 | 86.54 | KEYWORD_COMPLETION_RULES 반영, 채점기 v3.1.0 |
| 규칙 기반 후처리 재실행(02:21) | 86.97 | 86.85 | 재현성 확인용 재실행, 인용 형식 저하 발견 → 근거 블록 위치 수정으로 후속 조치 |

## 참고

- 각 수치가 나온 배경과 과정: `docs/generation-pipeline-summary.md`
- 채점 기준 자체의 이슈(조사·어미, 표기 충돌, 골든셋 누락 등): `docs/scoring-issues-report.md`
- 세부 실험 노트북 전체 목록: `notebooks/README.md`