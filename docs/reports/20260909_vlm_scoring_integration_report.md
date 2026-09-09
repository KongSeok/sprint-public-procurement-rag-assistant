# VLM + 채점기 v3.0.1 통합 실험

작성일: 2026-09-09

## 목적

최신 생성 파이프라인에 저장된 Qwen3-VL 시각 근거를 연결하고, 결정론적 채점기
v3.0.1로 Golden Set v3 79문항을 평가했다. 답변 생성은 `gpt-5-mini`, 시각 근거는
`Qwen3-VL-8B` 출력물을 사용했다.

## 실험 결과

| 지표 | 결과 |
| --- | ---: |
| 평가 문항 | 79 |
| 생성 성공률 | 100% |
| 실행 오류 | 0건 |
| End-to-End 점수 | 85.3687 |
| 어휘 사실 점수 | 87.6302 |
| 검색 Recall | 0.8188 |
| Context 사실 포함률 | 0.9041 |
| 기권 일치율 | 0.9242 |
| Set Macro Precision | 0.7423 |
| Set Macro Recall | 0.9500 |
| Set Macro F1 | 0.7968 |
| 인용 형식 통과율 | 100% |
| 인용 Recall | 0.9177 |
| 인용 Precision | 0.9215 |
| 시각 문항 평균 | 85.0 |
| 그림 기반 4문항 평균 | 100.0 |
| 표 기반 6문항 평균 | 75.0 |

응답 상태는 `answered` 68건, `partial_answer` 6건, `abstained` 5건이며
`execution_error`는 없었다.

## 해석 시 주의사항

- 이번 실행은 VLM을 매 문항마다 새로 호출한 것이 아니라 이전에 저장한 시각 근거를
  재사용했다.
- 시각 근거 생성 시 Golden Set의 근거 참조값을 이용해 대상 이미지를 선택했으므로,
  완전한 블라인드 시각 검색 성능으로 해석하면 안 된다.
- 당시 노트북의 문서 ID 추출 정규식은 파일명 내부의 `]` 문자를 끝표시로 오인할 수
  있었다. 따라서 검색 Recall, Set 지표와 이를 포함하는 End-to-End 점수는 잠정값이다.
- 이번에 저장소에 포함한 노트북은 `[문서: ...]` 한 줄 전체를 읽도록 이 문제를
  수정했다. 다음 실행부터 수정된 문서 ID 기준으로 비교한다.

## 재현 방법

1. GCP 저장소에서 이 실험 브랜치를 최신화한다.
2. `myenv` 커널을 선택한다.
3. `notebooks/20260909_vlm_generation_eval_kongseok.ipynb`를 첫 셀부터 실행한다.
4. 생성된 `output/` 결과는 Git에 올리지 않고 요약 보고서만 공유한다.

## 관련 파일

- `notebooks/20260909_vlm_generation_eval_kongseok.ipynb`
- `src/evaluation/scoring_v3/scorer.py`
- `src/evaluation/scoring_v3/_base.py`
- `tests/test_scorer_v3.py`
