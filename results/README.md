# 평가 결과 (results/)

`feat/rag-pipeline-and-eval` 브랜치의 실험 원시 결과 CSV. 각 파일이 어떤 실험인지, 수치 해석은
`docs/rag-pipeline-and-eval-summary.md`를 참고. 재현하려면 해당 스크립트를 다시 실행하면 된다
(`data/`가 있어야 함, git에는 없음 — 팀 공유 채널에서 받을 것).

| 파일 | 생성 스크립트 | 내용 |
|---|---|---|
| `eval_results.csv` | `scripts/step5_evaluate.py` | 초기 25문항 골든셋 retrieval 평가 |
| `embedding_compare_v6.csv` | `scripts/step11_embedding_compare.py` | KURE-v1 vs text-embedding-3-small A/B(공식 111건) |
| `context_fact_coverage_parent_child_compare.csv` / `_v6.csv` | `scripts/step9_parent_child_compare.py` / `step10_parent_child_compare_v6.py` | Parent-Child 청킹 전/후 context fact coverage |
| `generation_eval_v3.csv` / `generation_eval_v3_parent_child_compare.csv` | `scripts/step8_generation_golden_v3.py` / `step9_parent_child_compare.py` | 초기 generation 채점 |
| `v3_answer56_retrieval_compare.csv` | `scripts/step12_v3_answer_retrieval_compare.py` | rag-56(54건) retrieval, 팀 공유 API 기준선과 비교용 |
| `v3_answer56_generation_compare.csv` | `scripts/step13_v3_generation_compare.py` | rag-56 generation 최초 채점(버그 수정 전) |
| `v3_answer56_generation_rescore.csv` | `scripts/step14_v3_generation_rescore.py` | 채점 버그 수정 후 재채점(재생성 없음) — 최종 3지표 수치의 근거 |
| `rerank_compare_v6.csv` | `scripts/step15_rerank_compare.py` (BAAI/bge-reranker-v2-m3) | 리랭커 실험, 기각 |
| `rerank_compare_v6__Dongjin-kr_ko-reranker.csv` | `scripts/step15_rerank_compare.py` (Dongjin-kr/ko-reranker) | 리랭커 실험 2차, 기각 |
| `hybrid_weight_tuning_v6.csv` / `hybrid_weight_tuning_v6_detail.csv` | `scripts/step16_hybrid_weight_tuning.py` | BM25/벡터 가중치 스윕, 기본값(0.5/0.5) 유지 확정 |
| `v3_visual10_retrieval_compare.csv` | `scripts/step18_visual_retrieval_compare.py` | 표/그림 10건 문서 단위 retrieval + context fact coverage |
| `table_handling_stats.csv` | `scripts/analyze_table_handling_stats.py` | 표 처리(inline 삽입/폴백/중복 제거) 통계 |
| `missing_data_report.csv` / `missing_value_verification.csv` | `scripts/verify_all_missing_values.py` 등 | 예산/마감일 결측치 점검 |

`scripts/step17_generation_prompt_v2_compare.py`(프롬프트 v2 재검증)는 rag-56 56건을 실제로
재생성하는 API 호출이 필요해 이 브랜치 작성 시점 기준 아직 실행 전이면 결과 파일이 없다 — 실행 후
`v3_answer56_generation_promptv2_compare.csv`를 추가로 커밋할 것.
