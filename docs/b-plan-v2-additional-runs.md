# B-v2 추가 반복 실행 결과

- 실행일: 2026-09-08
- 대상: Golden Set v3 79문항
- 추가 실행: 3회 (`run-02`, `run-03`, `run-04`)
- 목적: 동일 조건 반복 실행 결과 기록
- 주의: 이 문서는 수치 기록만 포함하며 결과 해석이나 모델 우열 판단은 하지 않는다.

## 1. 고정된 실행 조건

| 항목 | 설정 |
| --- | --- |
| RFP 문서 | 98건 |
| 전체 청크 | 18,239개 |
| 실제 검색 대상 | 14,575개 |
| 평가 구성 | Answer 56 / Set 13 / Visual 10 |
| 검색 | KURE-v1 + BM25 Hybrid Retrieval |
| Context | Parent-Child + 문서 힌트 + 조건 필터 + 질문 유형별 구성 |
| 생성 모델 | OpenAI `gpt-5-mini` |
| 프롬프트 | `SYSTEM_PROMPT_V9` |
| API 설정 | `reasoning_effort=low`, `max_completion_tokens=8000` |
| VM | GCP `g2-standard-4` |
| GPU | NVIDIA L4 23,034 MiB |
| Python | 3.12.3 |
| PyTorch / CUDA | 2.14.0+cu130 / CUDA 13.0 |

세 실행 모두 기존 Chroma 임베딩 인덱스를 재사용했으며 재임베딩은 하지 않았다.

## 2. 추가 3회 전체 결과

| 지표 | run-02 | run-03 | run-04 |
| --- | ---: | ---: | ---: |
| 생성 성공률 | 100.00% | 100.00% | 100.00% |
| Retrieval Recall | 84.43% | 84.43% | 84.43% |
| Context Fact Coverage | 66.20% | 66.20% | 66.20% |
| 답변 Fact Coverage | 62.64% | 60.30% | 61.17% |
| Fact 완전 통과율 | 48.05% | 45.45% | 46.75% |
| 기권 행동 일치율 | 79.75% | 81.01% | 77.22% |
| 엄격한 Citation Coverage | 0.00% | 0.00% | 0.00% |
| 정답 문서명 언급률 | 82.53% | 77.22% | 78.73% |
| 호환 종합점수 | 63.59 | 61.31 | 62.15 |

## 3. 유형별 답변 Fact Coverage

| 유형 | 문항 | run-02 | run-03 | run-04 |
| --- | ---: | ---: | ---: | ---: |
| Answer | 56 | 65.96% | 63.18% | 64.04% |
| Set | 13 | 57.05% | 57.05% | 58.59% |
| Visual | 10 | 52.00% | 49.00% | 49.00% |

## 4. 유형별 호환 종합점수

| 유형 | 문항 | run-02 | run-03 | run-04 |
| --- | ---: | ---: | ---: | ---: |
| Answer | 56 | 67.17 | 64.49 | 65.33 |
| Set | 13 | 57.05 | 57.05 | 58.59 |
| Visual | 10 | 52.00 | 49.00 | 49.00 |

## 5. 결과 파일

GCP VM의 B-v2 전용 output 폴더 아래에 실행별로 분리 저장했다.

| 실행 | 상세 CSV | 요약 JSON | 로그 |
| --- | --- | --- | --- |
| run-02 | `repeat-02/golden_v3_results.csv` | `repeat-02/summary.json` | `repeat-02.log` |
| run-03 | `repeat-03/golden_v3_results.csv` | `repeat-03/summary.json` | `repeat-03.log` |
| run-04 | `repeat-04/golden_v3_results.csv` | `repeat-04/summary.json` | `repeat-04.log` |

상세 CSV에는 질문, Context 문서와 생성 답변이 포함되어 있어 공개 저장소에는
커밋하지 않았다.
