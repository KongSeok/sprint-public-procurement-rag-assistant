# gpt-5-mini Mini131 통합 기준선 — GPT-5.6 직접 판정 결과

Date: 2026-08-31

Evaluation tier: `provisional`

## 최종 통합 결과

고정 후보 `gpt-5-mini`의 RAG 129문항 답변을 고정 의미 채점기 ChatGPT
`gpt-5.6-sol`과 `gpt56-semantic-v2`로 판정했다. parser-fallback ETL 회귀 2건은
의미 평균에 섞지 않고 별도 PASS/FAIL로 합산했다.

- RAG 평균 의미점수: **54.845 / 100**
- accepted: **58/129 (44.96%)**
- rejected: **71/129 (55.04%)**
- 미해결 판정: **0/129**
- parser 회귀: **2/2 PASS**
- 통합 표시 문항: **131개**

public receipt의 `passed=true`는 131개 ledger·hash·판정 이력이 완결됐다는 뜻이다.
모델 품질은 accepted 58 대 rejected 71인 최초 개선 기준선으로 해석하며, 정답을 수정하거나
재생성하지 않았다.

### 평가 영역별 결과

| 영역 | 문항 | 평균점수 | accepted | rejected | 수용률 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Core 단일·다중·후속·기권 | 40 | 65.875 | 21 | 19 | 52.50% |
| 전체 말뭉치 EDA·집계 | 10 | 88.000 | 9 | 1 | 90.00% |
| 보조 조항·사실 — 기존 exact 답변 | 39 | 64.744 | 20 | 19 | 51.28% |
| 보조 조항·사실 — 재실행 | 17 | 12.353 | 2 | 15 | 11.76% |
| 조건별 공고 전체 목록 — 재실행 | 13 | 37.692 | 3 | 10 | 23.08% |
| HWP/PDF 표·그림 | 10 | 33.500 | 3 | 7 | 30.00% |
| **RAG 합계** | **129** | **54.845** | **58** | **71** | **44.96%** |

### 별도 객관 지표

| 지표 | 결과 |
| --- | ---: |
| 필수 문서 recall | 65.18% |
| 조건목록 Macro F1 | 61.23% |
| 조건목록 exact set match | 46.15% |
| 시각 대상 페이지 hit | 8/10 (80.00%) |
| 시각 대상 객체 bridge hit | 0/10 |
| EDA 결정론적 문항/필드 검증 | 10/10, 139/139 |
| parser C21/C22 | 2/2 PASS |

### 실행 계보·비용·기록 완전성

- 기존 exact 답변 39개는 `legacy_reconstructed`로 표시하고, 신규 90개는
  `prospective_rerun`으로 분리했다. 39개를 완전한 prospective transcript처럼 표시하지 않는다.
- prospective 90개는 embedding 50회와 generation 90회, 총 140회의 exact provider exchange를
  보존했다. legacy 39개는 당시 provider 요청·응답 원본이 없어 저장 답변 기반 복원 transcript만 있다.
- 후보 상태는 answered 93, abstained 31, error 5다. Core의 연결 오류 2건과 Gap의
  provider Schema 400 1건은 재시도하지 않고 원래 오류와 provider 시도를 보존했다.
- corpus vector는 다시 만들지 않았고 질문 embedding만 수행했다. 후보 provider 비용은
  **USD 0.21345322**이며, 승인된 최대 140회·USD 4 상한 안에서 닫혔다.
- source transcript **129/129**, 1차 판정 **129**, 교차 재심 **13**, 최종 조정 **13**을
  모두 private 기록에 보존했다. HTML에는 131개 카드와 RAG 129개의 전체 실행·판정 이력이 있다.

## 비공개 통합 산출물

- 문항·대화·근거·판정 통합 ledger:
  `evaluation/private/supplemental/runs/provisional-v1/case-records.jsonl`
- Sol 판정 이력:
  `evaluation/private/mini131/runs/baseline-v1/judgments.jsonl`
- 로컬 검토 화면:
  `evaluation/private/supplemental/runs/provisional-v1/gpt56-baseline-score.html`
- 공개 집계 영수증:
  `evaluation/baselines/mini131-bundle-v1/receipt.json`

private JSONL·HTML은 mode `0600`이며 Git에 올리지 않는다. 공개 영수증은 질문·답변·문서본문·
case ID·provider payload 없이 집계와 SHA-256만 포함한다.

## 이전 56문항 선행 중간 결과

아래 내용은 통합 129문항 판정 전에 생성한 보조 답변형 56문항의 역사 기록이다.
통합 기준선의 최종 점수로 사용하지 않는다.

답변형 56문항을 ChatGPT `gpt-5.6-sol`이 질문, 기준 답변, 필수 사실, 실제 답변,
검색 근거와 인용을 직접 읽어 판정했다. 코드 기반 문자열·정규식 판정은 의미점수에
사용하지 않았다.

- 평균 의미점수: **46.70 / 100**
- 중앙값: **37.50 / 100**
- accepted: **19/56 (33.93%)**
- rejected: **35/56 (62.50%)**
- needs human: **2/56 (3.57%)**
- 품질 게이트: **FAIL**

1차 판정은 56/56 완료했다. 경계 5문항은 별도 GPT-5.6이 독립적으로 재심했고,
세 번째 GPT-5.6이 최종 판정했다. 기존 실행에서 기권 응답 17건의 정확한 최종 문구가
저장되지 않았기 때문에, 원래 기권이 정답인 2문항은 의미를 추정하지 않고
`needs_human`으로 남겼다.

## GPT-5.6 구성점수

| 항목 | 평균 | 분모 |
| --- | ---: | ---: |
| 정확성 | 43.52% | 54 |
| 근거 충실성 | 45.37% | 54 |
| 완전성 | 43.52% | 54 |
| 주장별 인용 커버리지 | 70.37% | 54 |
| 인용 타당성 | 42.59% | 54 |

## 영역별 결과

| 영역 | 문항 | 평균점수 | accepted | rejected | 보류 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 조항·사실 답변 회귀 | 44 | 37.73 | 11 | 31 | 2 |
| 정답·원문 일치 검수 | 12 | 79.58 | 8 | 4 | 0 |
| 실제 답변 생성됨 | 39 | 64.49 | 19 | 20 | 0 |
| 모델이 기권함 | 17 | 5.88 | 0 | 15 | 2 |

현재 가장 큰 실패 원인은 과도한 기권과, 답변을 생성한 경우에도 핵심 사실을 지지하는
인용이 충분히 정확하지 않은 점이다. 다중 문서 비교 4문항은 accepted 0건이었다.

## 별도 객관 지표

아래는 GPT-5.6 의미점수와 합산하지 않는 검색·운영 진단이다.

| 지표 | 결과 |
| --- | ---: |
| 문서 Recall@5 | 84.57% |
| MRR@10 | 0.8247 |
| nDCG@10 | 0.8115 |
| 필수 문서 인용 커버리지 | 47.22% |
| 집합검색 13문항 Macro F1 | 23.28% |
| 집합검색 13문항 Exact set match | 0.00% |
| 런타임 오류율 | 0.00% |
| 기존 실행 비용 | $0.05369765 |

`passed=true`로 표시됐던 기존 규칙 기반 결과는 실행 완결성과 구조 검사의 통과를 뜻하며,
답변 의미 품질 통과가 아니다. 의미 품질의 최종 결과는 본 GPT-5.6 판정의 `FAIL`이다.

## 비공개 상세 산출물

- 문항별 최종 판정: `evaluation/private/supplemental/runs/provisional-v1/gpt56/final-judgments.jsonl`
- 집계 원본: `evaluation/private/supplemental/runs/provisional-v1/gpt56/summary.json`
- 로컬 검토 화면: `evaluation/private/supplemental/runs/provisional-v1/gpt56-baseline-score.html`

질문, 답변, 원문 근거와 판정 사유는 Git에 올리지 않는다. 공개 영수증은 집계값과 hash만
포함한다.
