# RAG 파이프라인 + 평가 실험 요약 (feat/rag-pipeline-and-eval)

이 브랜치가 추가하는 내용의 전체 요약이다. `src/data_processing` → `src/retrieval` → `src/generation` →
`src/evaluation`로 이어지는 RAG 파이프라인 전체 구현과, 그 위에서 실측으로 검증한 개선 실험들
(Parent-Child 청킹, 임베딩 A/B, 리랭커, BM25/벡터 가중치 튜닝, 프롬프트 개선, 표/그림 문항 평가)의
과정과 결론을 담는다. 실험은 전부 "가정하지 않고 실측 후 채택/기각을 결정"하는 방식으로 진행했다 —
그래서 "채택 안 함"으로 끝난 실험도 결론과 근거를 그대로 남겨뒀다.

## 1. 무엇을 구현했는가

```text
data/(원본 hwp/pdf + 메타데이터 CSV, git 비대상)
  → src/data_processing  : 파싱(hwp5txt/hwp5html, PyMuPDF+pdfplumber+OCR) → 문서유형 분류
                            → 표 내용 텍스트화(원래 위치에 inline 삽입 시도, 실패시 폴백)
                            → 청킹(Recursive + Parent-Child)
  → src/retrieval        : 임베딩(KURE-v1 기본, OpenAI 임베딩 옵션) → BM25+Vector 하이브리드
                            인덱싱(HybridIndex) → (실험용) cross-encoder 리랭커
  → src/generation        : 검색된 컨텍스트만 근거로 gpt-5-mini 답변 생성, 기권/인용 규칙 프롬프트
  → src/evaluation        : golden set 로더(공식 v6-111건 + golden-set-v3-share 보조 lane),
                            retrieval 지표(recall/coverage/mrr/ndcg), context fact coverage,
                            generation 채점(기권 일치율/인용 커버리지/사실 커버리지)
```

실행 방법과 각 모듈의 역할은 저장소 루트 `README.md`(프로젝트 개요/구조)와 `scripts/` 안 각 스크립트
상단 docstring을 참고. 대표 실행 순서:

```bash
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...   # generation 관련 스크립트에만 필요

python scripts/step1_load_metadata.py     # 메타데이터 정제
python scripts/step2_merge_text.py        # 원본 재파싱 + 표 병합
python scripts/step3_chunking.py          # Parent-Child 청킹
python scripts/step4_indexing.py          # Hybrid 인덱스 구축
python scripts/step5_evaluate.py          # retrieval 평가 (초기 25문항 골든셋)
```

`step6`~`step18`은 이후 순차적으로 추가한 평가/실험 스크립트다(아래 각 절에서 관련 스크립트를 명시).
공식 골든셋(111건, `data/golden_testset_verified_111_v6.json`)과 `golden-set-v3-share` 패키지
(`data/golden_set_v3/`, rag-56/set-13/document-structure-visual-qa 3개 lane)는 모두 `data/`
아래 있어야 하며 git에는 올리지 않는다(팀 README 11장 참고) — 필요하면 팀 공유 채널에서 받는다.

## 2. 최종 시스템 구성과 성능 수치

- 임베딩: **KURE-v1**(nlpai-lab, 로컬·무료) — 아래 3절에서 text-embedding-3-small과 실측 비교 후 유지
- 인덱스: `HybridIndex`(BM25 + 벡터, **vector_weight=0.5/bm25_weight=0.5**) — 아래 6절 튜닝 실험으로 확정
- 청킹: Parent-Child(검색은 child 단위, 컨텍스트는 parent로 확장, k=5) — 아래 4절 효과 검증
- 리랭커: **미도입**(아래 5절, cross-encoder 2종 실측 후 기각)
- 생성 모델: gpt-5-mini(OpenAI Responses API), 답변 끝에 사용한 근거 doc_id를 인용 표시

**Retrieval — 공식 golden set(111건) 기준:**

| 지표 | 값 |
|---|---:|
| recall@1 | 0.865 |
| recall@3 | 0.946 |
| recall@5 | 0.964 |
| coverage@5 | 0.904 |
| mrr | 0.911 |

**Retrieval — rag-56 서브셋(기권 대상 제외 54건) 기준:**

| 지표 | 값 |
|---|---:|
| recall@1 | 0.870 |
| recall@3 | 0.981 |
| recall@5 | 0.981 |
| recall@10 | 1.000 |
| mrr@10 | 0.926 |
| ndcg@10 | 0.935 |

**Generation — rag-56 전체(56건), 결정론적 채점 3종(LLM 판정 없음, `scripts/step14_v3_generation_rescore.py`):**

| 지표 | 값 | 대상 건수 |
|---|---:|---:|
| abstention_behavior_match (기권 여부 판단 일치율) | 0.946 | 56 |
| required_doc_citation_coverage (필요 문서 인용률) | 0.935 | 54 |
| lexical_required_fact_coverage (어휘 매칭, 참고용) | 0.566 | 53 |

## 3. 임베딩 백엔드 A/B — KURE-v1 유지

`scripts/step11_embedding_compare.py`, 공식 111건 기준, retrieval-only(API 비용은 OpenAI 임베딩
호출분만 발생):

| 지표 | KURE-v1(로컬·무료) | text-embedding-3-small(API·유료) | 격차 |
|---|---:|---:|---:|
| recall@1 | 0.865 | 0.676 | +0.189 |
| recall@3 | 0.946 | 0.910 | +0.036 |
| recall@5 | 0.964 | 0.937 | +0.027 |
| coverage@5 | 0.904 | 0.863 | +0.041 |
| mrr | 0.911 | 0.797 | +0.114 |
| fact_coverage(baseline) | 0.467 | 0.413 | +0.054 |
| fact_coverage(parent-child) | 0.524 | 0.490 | +0.034 |

KURE-v1이 전 지표에서 우세하고, 특히 recall@1·mrr(1등으로 정확히 찍어내는 정밀도)에서 격차가 크다 —
한국어 RFP 도메인 특유의 행정 용어·규격 표현을 한국어 특화 모델이 더 세밀히 구분하는 것으로 해석된다.
**결론: 이 코퍼스에서는 유료 API로 바꿀 이유가 없다.** parent-child 개선 효과가 두 백엔드 모두에서
같은 방향(KURE +0.057, OpenAI +0.078)으로 나타난 것도 parent-child 효과가 임베딩 선택과 독립적인
구조적 개선이라는 교차검증이 된다.

## 4. Parent-Child 청킹 효과

검색은 child(작은) 청크로 하되, 실제 컨텍스트는 그 부모(더 넓은) 청크로 확장해서 모델에 넘기는 방식.
`context fact coverage`(검색된 컨텍스트 안에 정답에 필요한 사실이 실제로 들어있는 비율)로 검증:

| 데이터셋 | 완전 커버율 (전/후) | 평균 coverage (전/후) |
|---|---:|---:|
| 63건 세트 | 41.3% → 50.8% | 53.2% → 63.2% |
| 공식 111건 | 36.1% → 40.7% | 45.2% → 51.9% |

비용은 parent chunk를 검색 후보에서 빼는 것 자체로 recall@5가 111건 기준 0.982→0.973(-0.9%p) 소폭
하락 — 이 정도 비용에 이 정도 fact coverage 개선이면 채택할 가치가 있다고 판단해 기본값으로 유지.

## 5. 리랭커(cross-encoder) 도입 실험 — 채택 안 함

`src/retrieval/reranking.py`, `scripts/step15_rerank_compare.py`. hybrid_search가 찾아온 후보
풀을 cross-encoder로 재채점해 순위만 재조정하는 2단계 리랭킹을 공식 111건으로 검증
(retrieval-only, API 비용 0원).

- **BAAI/bge-reranker-v2-m3(다국어)**: 전 지표 소폭 악화(recall@5 -2.7%p, recall@10 -1.8%p,
  mrr -0.8%p). 원인 2가지를 CSV 상세 분석으로 특정: (1) "예산 1억 이상인 사업" 같은 필터/집계형
  질문은 개별 (질의,문서) 관련도만 보는 cross-encoder 구조에 안 맞음, (2) 하도급/공동수급/보상 같은
  RFP 표준 조항은 여러 기관 문서에서 문구가 거의 동일해서 범용 리랭커가 "어느 기관 문서인지"(고유명사)를
  못 가려내고 BM25가 잘 잡던 신호를 눌러버림(예: "한국철도공사" 질문에서 정답 문서가 1등→8등 밖으로).
- **Dongjin-kr/ko-reranker(한국어 특화)**: 고유명사 구별 개선을 기대하고 재시도했으나 결과 역시
  좋지 않았음(`output/rerank_compare_v6__Dongjin-kr_ko-reranker.csv`에서 상세 재분석 가능).

**결론:** 두 후보 다 hybrid 단독보다 못해 리랭커는 도입하지 않음. 코드는
`evaluate_retrieval(..., reranker=...)`에 opt-in으로만 남겨뒀다.

## 6. BM25/벡터 하이브리드 가중치 튜닝 — 기본값(0.5/0.5) 유지 확정

`scripts/step16_hybrid_weight_tuning.py`. `vector_weight`를 0.0(BM25 단독)~1.0(벡터 단독)까지
0.1 간격으로 스윕(재임베딩·API 호출 없음, 기존 인덱스 재조합만).

**vector_weight=0.5(현재 기본값)가 11개 후보 중 5개 지표(recall@1/3/5/10, mrr) 평균 1위(0.9335)** —
2위 0.3(0.9297)과도 차이가 있고 이하로 갈수록 격차가 커진다. 특정 지표만 보면 0.5보다 근소하게 나은
alpha가 있지만(예: 0.6에서 recall@1·5가 각각 +0.9%p) 대신 recall@3이 -6.3%p로 크게 깎이는
트레이드오프였다. BM25/벡터 단독 둘 다 중간 지점보다 뚜렷이 낮아 hybrid 구조 자체의 유효성도 재확인.
**결론: 가중치를 바꿀 이유 없음, 기본값 유지.**

## 7. 프롬프트 개선(v2) — 다중 답변/상충 정보 처리 지시 추가

rag-56 재채점(위 2절 수치) 후 남은 불일치 3건을 답변 원문까지 확인해 두 갈래로 구분했다:

- `supplemental-qa-c25`(source_conflict): 근거 문서 사이 내용이 상충하면 "상충한다"고 알리는 게
  정답인데 프롬프트에 그 지시가 없어 모델이 완전 기권 — **프롬프트로 고칠 수 있는 부분**.
- `supplemental-qa-g22`/`g24`(abstain): 모델이 질문 일부는 답하고 나머지만 기권했는데 golden set은
  "질문 전체 기권"을 정답으로 봄 — 부분 정보라도 알려주는 게 실사용 관점에서 나을 수 있어 "무조건 전체
  기권" 강제 지시는 의도적으로 넣지 않음(한계로 기록).

`src/generation/generation.py`의 `SYSTEM_PROMPT`에 (1) 질문에 여러 하위 항목이 있으면 항목별로
답변/기권을 분리하라는 지시, (2) 근거 문서 간 내용이 상충하면 기권 대신 상충 사실을 명시하라는 지시를
추가. `scripts/step17_generation_prompt_v2_compare.py`로 rag-56 전체를 재생성해 v1(기준선) 대비
비교하도록 준비해뒀다(rag-56 56건 재생성이라 API 비용 발생 — 이 브랜치 작성 시점 기준 아직 실행 전이면
`output/v3_answer56_generation_promptv2_compare.csv`가 없을 수 있음).

## 8. 표/그림(visual) 10건 — 문서 단위 retrieval + context fact coverage

`golden-set-v3-share`의 표/그림 문항은 실제로 10건(표 6건 + 그림 4건,
`data/golden_set_v3/document-structure-visual-qa.jsonl` 실측 확인).

**전제(코드 근거):** 파서는 표를 "표 모양"이 아니라 "표 내용"으로만 추출한다 — `pdfplumber`/`hwp5html`이
표 구조(행×열)를 뽑아내긴 하지만 `merge_text.py`의 `_flatten_one_table()`이 `" | "`로 이어붙인 순수
텍스트로 바꾸고, PDF는 표가 있으면 항상 문서 끝에 일괄 첨부(원본 위치 정보 없음), HWP는 "<표>"
자리표시자 위치에 끼워넣긴 하지만 이것도 페이지/bbox가 아니라 "어느 문단 다음"이라는 문맥적 위치일
뿐이다. 청크 메타데이터에도 page/bbox 관련 필드가 전혀 없다. 즉 **표/그림의 위치(페이지·bbox) 정답
여부는 지금 데이터 모델에서 원천적으로 검증 불가능**하다 — 그래서 이 실험은 "문서를 찾는지"와 "찾은
컨텍스트에 필요한 사실이 실제로 들어있는지"만 측정한다(`scripts/step18_visual_retrieval_compare.py`).

**문서 단위 retrieval(hybrid, k=5/10):** recall@1=0.700, recall@3=0.800, recall@5=0.900,
recall@10=0.900, mrr=0.758, ndcg@5=0.793.

**context fact coverage (baseline vs parent-child):**

| | 완전 커버율 | 평균 coverage |
|---|---:|---:|
| baseline | 0.300 | 0.390 |
| parent-child | 0.400 | 0.510 |

**표 vs 그림 격차(parent-child 기준):**

| evidence_type | fact_coverage | fully_covered |
|---|---:|---:|
| table (6건) | 0.783 | 0.667 |
| figure (4건) | 0.100 | 0.000 |

문항별 `rank_found`를 대조하면 그림 4건 중 3건은 정답 문서를 **1순위로 정확히 찾았음에도**
fact_coverage가 거의 0에 수렴한다 — 즉 원인은 retrieval이 아니라, 그림(구성도·다이어그램) 안의
정보가 파싱 단계에서 애초에 텍스트로 추출되지 않는다는 것이다. 표는 `_flatten_one_table()`로 내용이
텍스트로 남아 위치 없이도 검색·답변이 어느 정도 되지만(0.783/0.667), 그림은 그런 텍스트화 경로 자체가
없다. **결론: 문서 단위로는 표/그림 질문도 비교적 잘 찾지만(recall@5=0.9), 이를 "표/그림 문제를
풀었다"로 확대 해석하면 안 된다.** 표는 위치 없이도 내용이 있어 실사용 가치가 있는 반면, 그림은
내용 자체가 없어 지금 구조로는 근본적으로 못 푸는 별개의 문제다.

## 9. golden-set-v3-share 공통 골든셋(rag-56, 54건)으로 본 참고 비교

`scripts/step12_v3_answer_retrieval_compare.py`. 팀 공유 패키지의 `answer-56.metrics.json`
(API gpt-5-mini 기준선, 출처 브랜치 `feat/api-gpt5mini-mini131-eval`)과 **동일한 54건**을 이
브랜치의 `HybridIndex`(KURE-v1 + BM25 hybrid + Parent-Child)로 채점한 결과:

| 지표 | 이 브랜치 | 공유 패키지 API 기준선 |
|---|---:|---:|
| recall@1 | 0.870 | 0.753 |
| recall@3 | 0.981 | 0.809 |
| recall@5 | 0.981 | 0.846 |
| recall@10 | 1.000 | 0.846 |
| mrr@10 | 0.926 | 0.825 |
| ndcg@10 | 0.935 | 0.811 |

골든셋은 동일하지만, 비교 대상 브랜치의 정확한 시스템 구성(임베딩/청킹/hybrid 가중치/top_k 등)은
공유 패키지 안에서 확인할 수 없다 — 그래서 "이 브랜치 구성 전체가 같은 54문항에서 더 많이 정답 문서를
찾는다"까지만 defensible한 결론이고, 어느 설계 요소 덕분인지는 상대 브랜치 설정을 받아야 분리할 수
있다. 참고용으로 남겨둔다.

## 10. 오늘 고친 채점 코드 버그 (5종 + dead code 1건)

1. **쉼표 표기 차이**: "999,494,600원" vs "999494600" — 공백/쉼표 제거 후 비교.
2. **단어 순서/조사 차이**: "부가가치세(VAT) 포함"처럼 조사·괄호가 끼면 매칭 실패 — 단어 단위 순서
   무관 매칭으로 완화.
3. **날짜 표기 차이**: "2024. 10. 31." vs "2024-10-31" — YYYYMMDD 정규화 비교 fallback 추가.
4. **`is_abstention()` 다중 답변 오분류**: 기권 문구가 답변 어디에든 있으면 통째로 "완전 기권"으로
   본 로직이, 일부 하위 질문만 모른다고 답한 답변까지 완전 기권으로 오분류 — 기권 문구를 뺀 나머지에
   줄 단위 실질 내용(15자 이상)이 남는지로 판단하도록 수정. 재채점 결과 8건이 정상 판정으로 전환.
5. **`extract_cited_doc_ids()` 인용 파일명 절단**: "[근거: 파일명]" 파싱이 첫 "]"에서 멈춰서 파일명에
   "[재공고][긴급]" 같은 태그가 있으면 절단됨 — 문자열 끝까지 캡처하도록 수정. 재채점 결과 6건 전환.
6. (dead code) `evaluate_retrieval()`의 `hybrid_kwargs` 파라미터가 시그니처에만 있고 실제로는
   `_search_doc_ids()`까지 전달되지 않던 죽은 코드 — 6절 가중치 튜닝을 하려면 필요해서 연결.

버그 4·5는 **재생성 없이** 이미 저장된 답변 텍스트에 새 채점 로직만 다시 적용해서 검증(비용/시간
재발생 없음, `scripts/step14_v3_generation_rescore.py`).

## 11. 알려진 한계 / 다음 할 일

- **예/아니오형 질문 채점 사각지대**: `check_required_facts`가 결론이 반대로 뒤집혀도 관련 단어만
  답변에 들어있으면 통과시킬 수 있다(발견 사례: c12, required_fact_groups 단어 매칭이라 결론
  방향성을 안 봄) — 결론 방향성 체크 추가 검토 필요.
- **재채점 후 남은 불일치 2건(g22/g24)**: 모델이 "일부는 알고 일부는 모르는" 상황에서 golden set이
  기대하는 완전 기권과 다르게 부분 답변을 하는 사례. 7절 프롬프트 v2로도 의도적으로 안 고쳤음(위 참고).
- **집합형(정답 여러 개) 13건**: 채점 방식이 "정답 1개여도 최소 10개 채점 풀 강제"라 과다채점 위험 —
  개선 검토 필요.
- **표/그림 위치(페이지·bbox) 메타데이터 미지원**: 8절 참고. HWP는 파일 구조상 "페이지" 개념이 없어
  렌더링 기반 서브시스템을 새로 만들어야 하고, 그림은 내용 자체가 텍스트로 추출되지 않는 별개 문제.
  투자 대비 범위(10건)가 작아 현재 보류 — OCR-온-이미지 또는 캡션 추출 파이프라인이 필요.
- **LLM 기반 판정(correctness/faithfulness/completeness) 미연결**: 지금 채점한 세 지표는 전부
  결정론적(LLM 호출 없음) — "답변이 실제로 맞는 내용인지"는 아직 안 재고 있음.
- 111건 기준 ndcg@k 결과 아직 산출 안 함.
- (완료·기각 확정) 리랭커 도입은 실측 후 기각(5절). 가중치 튜닝도 실측 후 기본값 유지로 확정(6절).
  표/그림 문서 단위 실험도 완료(8절) — retrieval 쪽 저비용 실험은 소진된 상태. 다음 유망 후보는
  generation 쪽(7절 프롬프트 v2 결과 확인, 채점 사각지대 보강) 또는 LLM judge 연결.

## 12. 결과 파일 위치

`results/`에는 위 실험들의 원시 결과 CSV를 그대로 올려뒀다(정확한 파일명은 각 절에서 언급한
스크립트의 출력 경로와 동일). `output/`(캐시·중간 산출물, `merged_docs.pkl`/`chunks.pkl`/
`chroma_db/` 등 문서 원문이 사실상 그대로 들어있는 대용량 파일 포함)와 `data/`(원본 RFP,
golden set)는 README 11장 규칙에 따라 git에 올리지 않으므로, 각 스크립트를 순서대로 실행하면
로컬에 재생성된다.
