# B안 통합 모델 Golden Set v3 평가 결과

평가일: 2026-09-08  
통합 버전: `hanbin-dahye-v1`  
통합 커밋: `330cd28` (`develop`)

## 1. 평가 대상

- Retrieval: 한빈님 `feat/rag-pipeline-and-eval` tip `d51633b`
- Generation: 다혜님 `experiment/DH` tip `5ea75c7`
- 제외: `uyt5041-lab`의 Evidence-Harness와 그 평가 구조
- 전체 구성: KURE-v1 + BM25 Hybrid Retrieval → Parent 문맥 확장 → GPT-5 mini 생성

이번 B안은 README 초기에 적은 API 임베딩 후보가 아니라, 한빈님 실험에서 선정한
로컬 KURE-v1 임베딩과 BM25를 사용한다. 다혜님 생성 실험의 GPT-5 mini 설정과
프롬프트를 이 검색 결과에 연결했다.

## 2. 데이터와 평가셋

| 항목 | 수량 |
| --- | ---: |
| RFP 문서 | 98 |
| 원본 파싱 | 97 |
| CSV fallback | 1 |
| 전체 청크 | 18,239 |
| Parent 청크 | 3,664 |
| Child 청크 | 14,572 |
| Recursive 청크 | 3 |
| 실제 검색 대상 | 14,575 |
| Golden Set v3 Answer/Visual | 66 |
| Golden Set v3 Set | 13 |
| 전체 평가 문항 | 79 |

Golden Set v3 패키지는 현재 79건 모두 `draft`이며, 69건은 `enabled=False`로
표시되어 있다. 이번 비교에서는 팀 공통 질문셋 전체를 보기 위해 79건을 모두
포함했다.

## 3. 실행 설정

### Retrieval

- 임베딩: `nlpai-lab/KURE-v1` (1,024차원)
- 검색: KURE Vector + 한국어 형태소 기반 BM25
- 가중치: Vector 0.5 / BM25 0.5
- Answer 문항: top-k 5
- Set 문항: 기본 top-k 10, 정답 문서 수가 많으면 `정답 수 + 5`
- Parent-Child: Child 검색 후 Parent 텍스트로 문맥 확장
- 메타데이터 필터: 질문에서 기관·금액·날짜 조건을 추출해 적용

### Generation

- 모델: `gpt-5-mini`
- API: OpenAI Chat Completions
- `reasoning_effort`: `low`
- `max_completion_tokens`: 8,000
- 다혜님 프롬프트의 문서 근거·기권·질문 유형별 답변 규칙 적용
- 검색 결과의 발주기관·사업금액·입찰마감일 메타데이터를 문맥에 포함
- 답변 마지막 줄: `[근거: doc_id1, doc_id2]`

## 4. 전체 실측 결과

| 지표 | 결과 |
| --- | ---: |
| 생성 성공률 | **100.0% (79/79)** |
| 평균 Retrieval Recall | **92.2%** |
| 필요 문서 전체 검색 성공 | **89.9% (71/79)** |
| 평균 Citation Coverage | **82.9%** |
| 필요 문서 전체 인용 성공 | **79.7% (63/79)** |
| 기권 행동 일치율 | **81.0% (64/79)** |
| 평균 Fact Coverage | **54.6%** |
| Fact 완전 통과율 | **37.7% (29/77)** |

Fact가 정의되지 않은 기권 문항 2건을 제외하고 77건을 Fact 채점했다.

## 5. 유형별 결과

| 유형 | 문항 | Retrieval Recall | Citation Coverage | 기권 일치 | Fact Coverage | Fact 완전 통과 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Answer | 56 | 96.7% | 91.4% | 82.1% | 58.3% | 40.7% (22/54) |
| Set | 13 | 74.4% | 48.4% | 92.3% | 49.3% | 38.5% (5/13) |
| Visual | 10 | 90.0% | 80.0% | 60.0% | 41.5% | 20.0% (2/10) |

일반 Answer 질문은 검색과 인용이 안정적이다. Set 질문은 여러 정답 문서를 모두
찾고 인용하는 단계가 병목이고, Visual 질문은 텍스트 파싱만으로 표·그림 정보를
충분히 복원하지 못해 생성 정확도가 낮다.

## 6. Retrieval 단독 비교

Answer/Visual 66건을 같은 조건으로 비교한 결과다.

| 방식 | Recall@1 | Recall@3 | Recall@5 | MRR@5 | nDCG@5 |
| --- | ---: | ---: | ---: | ---: | ---: |
| BM25 | 86.4% | 93.9% | 97.0% | 90.9% | 91.7% |
| Vector | 84.8% | 90.9% | 93.9% | 88.4% | 88.5% |
| **Hybrid** | **89.4%** | **95.5%** | **97.0%** | **92.3%** | **92.7%** |

Set 13건에서는 Hybrid가 Precision 32.7%, Recall 68.6%, F1 39.8%로 세 방식 중
가장 높았다. Hybrid는 BM25와 Recall@5가 같지만 정답 문서를 더 높은 순위에
배치해 MRR과 nDCG가 개선됐다.

## 7. 실패 분석

- 필요한 문서를 모두 찾지 못한 문항: 8건
- 인용 Coverage가 0인 문항: 10건
- Fact Coverage가 0인 문항: 21건
- 기권 행동 불일치: 15건
- API 생성 실패: 0건

주요 개선 대상은 다음과 같다.

1. Set 질문: 문서별 1개 결과 제한, 후보 수 확대, 조건 필터 개선이 필요하다.
2. Visual 질문: 표 구조와 그림 설명을 보존하는 별도 파싱이 필요하다.
3. 생성 프롬프트: 검색 근거가 있어도 모델이 보수적으로 기권하는 Answer 문항이 있다.
4. 인용: 답변에 사용한 모든 필요 문서를 마지막 근거 줄에 빠짐없이 기록해야 한다.

## 8. 해석 시 주의사항

- Fact Coverage는 `required_fact_groups`의 문자열·날짜 변형을 찾는 자동 진단
  지표다. 의미가 맞는 동의 표현을 놓치거나, 문자열만 같고 문맥이 틀린 답을
  통과시킬 수 있으므로 사람 또는 LLM Judge의 정답성 평가와 동일하지 않다.
- 기권 일치율은 다혜님 scoring notebook의 기권 표현 목록을 사용한 문구 기반
  판정이다. 일부만 답하고 나머지를 기권한 답변도 기권으로 잡힐 수 있다.
- Golden Set이 아직 draft이므로 팀 검수 후 점수는 달라질 수 있다.
- 공식 종합점수 산식은 정의되어 있지 않아 서로 다른 지표를 임의로 평균낸
  단일 점수는 만들지 않았다.

## 9. 실행 환경

| 항목 | 환경 |
| --- | --- |
| VM | GCP `g2-standard-4` |
| OS | Ubuntu 24.04.4 LTS |
| CPU / RAM | 4 vCPU / 15 GiB |
| GPU | NVIDIA L4 23,034 MiB |
| NVIDIA Driver | 580.173.02 |
| Python | 3.12.3 |
| PyTorch / CUDA | 2.14.0+cu130 / CUDA 13.0 |
| Sentence Transformers | 6.0.1 |
| ChromaDB | 1.5.9 |
| OpenAI SDK | 3.8.0 |
| pandas | 3.0.5 |
| rank-bm25 | 0.2.2 |

전체 실행 시간은 약 10분이며, 상세 CSV는 GCP VM의
`output/hanbin_dahye_v1_golden_v3.csv`에 저장했다. CSV에는 질문, 검색 문서,
생성 답변과 문항별 지표가 포함되어 있어 공개 저장소에는 커밋하지 않는다.
