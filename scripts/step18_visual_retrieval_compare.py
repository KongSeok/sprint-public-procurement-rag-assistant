"""18단계(신규): 표/그림(visual) 문항 10건 - 문서 단위 retrieval만 평가.

[먼저 정정] "20건"이라고 했지만 실제로는 10건이다(`data/golden_set_v3/
document-structure-visual-qa.jsonl` 실측 확인, 팀원 receipt.json의
visual_case_count도 10과 일치) - 표 6건 + 그림 4건. 아마 팀원 receipt.json의
by_lane 중 visual(10) + corpus_analytics(10) 두 lane을 합쳐 "20"으로
기억했을 가능성이 있다(daily-briefing 저녁 2 참고) - corpus_analytics는
코퍼스 전체 통계 질문(예: "HWP/PDF가 각각 몇 건")이라 표/그림과 무관하고,
애초에 doc_id가 내부 해시뿐이라 우리 코퍼스와 매칭할 방법이 없어서
golden_set_v3.py가 아예 안 읽는 lane이다(계속 스킵 대상).

[할 수 있는 것 vs 여전히 안 되는 것] daily-briefing 저녁 5에서 검토했던
건 "팀원과 같은 기준"(페이지/표 블록/객체 단위, bbox 좌표까지) 채점이었고
- 이건 여전히 안 된다(HWP 렌더링 서브시스템이 없어서 페이지/bbox 자체가
없음, 보류 유지). 그런데 `src/golden_set_v3.py`가 이 10건도 이미 "문서
단위" expected_doc_id로는 매핑해두고 있었다(document.source_filename의
"refined_" 접두어만 떼면 우리 코퍼스 doc_id와 그대로 일치) - 그래서 "이
표/그림 질문에 대해 정답 문서 자체는 찾아오는지"(document-level recall)와
"검색된 컨텍스트 텍스트 안에 표/그림의 사실이 실제로 들어있는지"
(context_fact_coverage, 표는 파서가 텍스트로 이미 추출해둠)는 새 인프라
없이 지금 바로 잴 수 있다. 이건 팀원의 page/chunk/object 단위 채점보다
훨씬 관대한 기준이라는 점을 반드시 감안해서 해석할 것 - 팀원 자신의
베이스라인도 visual_target_page(문서 안 페이지 단위) hit_rate는 80%였지만
visual_target_chunk(표 블록 단위)는 0%, visual_target_object_bridge(객체
단위)는 0%였다(daily-briefing 저녁 4) - "문서를 찾았다"와 "그 안의 정확한
표/그림을 찾았다"는 완전히 다른 질문이니, 이 스크립트 결과가 좋게 나와도
"표/그림 문제를 풀었다"고 결론 내리면 안 된다.

비교 범위: retrieval 단계만(generation 호출 없음, API 비용 0원).
  1. document-level recall@k/mrr/ndcg (evaluate_retrieval)
  2. context fact coverage(검색된 컨텍스트에 필요한 사실이 있는지,
     baseline vs parent-child) - 10건 전부 required_fact_groups가 있어서
     채점 가능함을 미리 확인함(표 6건 평균 4개, 그림 4건 평균 6개 사실)

사용법: python scripts/step18_visual_retrieval_compare.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from src.data_processing.chunking import chunk_all, load_chunks, save_chunks  # noqa: E402
from src.config import OUTPUT_DIR  # noqa: E402
from src.evaluation.evaluation import evaluate_context_fact_coverage, evaluate_retrieval  # noqa: E402
from src.evaluation.golden_set_v3 import load_golden_set_v3  # noqa: E402
from src.retrieval.indexing import HybridIndex  # noqa: E402
from src.data_processing.load_metadata import load_clean_metadata  # noqa: E402
from src.data_processing.merge_text import load_merged, merge_all, save_merged  # noqa: E402

RESULTS_PATH = OUTPUT_DIR / "v3_visual10_retrieval_compare.csv"
K_VALUES = (1, 3, 5, 10)
TOP_K = 5


def main():
    df = load_golden_set_v3()
    visual = df[df["source_lane"] == "visual"].reset_index(drop=True)
    print(f"\n[step18] visual 문항 로드: {len(visual)}건")
    n_empty = int((visual["expected_doc_id"].apply(len) == 0).sum())
    if n_empty:
        print(f"[step18] 경고: expected_doc_id가 빈 항목 {n_empty}건(파일명 매칭 실패) - recall이 부당하게 깎일 수 있음")

    chunks = load_chunks()
    if chunks is None:
        print("[step18] 캐시(output/chunks.pkl) 없음 -> step2~3부터 다시 계산합니다...")
        merged = load_merged()
        if merged is None:
            merged = merge_all(load_clean_metadata())
            save_merged(merged)
            merged = load_merged()
        chunks = chunk_all(merged)
        save_chunks(chunks)

    print("\n[step18] HybridIndex 준비 중 (기존 컬렉션 재사용 시도, KURE-v1)...")
    index = HybridIndex(chunks)

    # --- 1. document-level recall@k/mrr/ndcg ---
    detail_df, summary_df = evaluate_retrieval(index, visual, methods=("hybrid",), k_values=K_VALUES)
    row = summary_df.iloc[0]
    print(f"\n{'=' * 70}\n표/그림 10건 - 문서 단위(document-level) retrieval\n{'=' * 70}")
    for k in K_VALUES:
        print(f"  recall@{k}={row[f'recall@{k}']:.3f}  ", end="")
    print(f"\n  mrr={row['mrr']:.3f}  ndcg@5={row['ndcg@5']:.3f}  ndcg@10={row['ndcg@10']:.3f}")

    print("\n  문항별 상세 (10건 전부 - 표본이 작아서 집계보다 개별 확인이 더 유용함):")
    detail_cols = ["id", "query", "rank_found", "n_expected", "top_hits"]
    print(detail_df[detail_cols].to_string(index=False))

    # --- 2. context fact coverage (baseline vs parent-child) ---
    print(f"\n{'=' * 70}\n표/그림 10건 - context fact coverage (baseline vs parent-child)\n{'=' * 70}")
    base_detail, _ = evaluate_context_fact_coverage(index, visual, methods=("hybrid",), k=TOP_K, expand_to_parent=False)
    pc_detail, _ = evaluate_context_fact_coverage(index, visual, methods=("hybrid",), k=TOP_K, expand_to_parent=True)
    print(f"  완전 커버율: baseline={base_detail['fully_covered'].mean():.3f}  "
          f"parent-child={pc_detail['fully_covered'].mean():.3f}")
    print(f"  평균 coverage: baseline={base_detail['fact_coverage'].mean():.3f}  "
          f"parent-child={pc_detail['fact_coverage'].mean():.3f}")

    # evidence_type(표/그림) 별 breakdown - visual jsonl 원본에만 있는 필드라 case_id로 다시 참조
    import json
    from src.config import DATA_DIR
    raw = {r["case_id"]: r.get("evidence_type") for r in (
        json.loads(line) for line in open(DATA_DIR / "golden_set_v3" / "document-structure-visual-qa.jsonl", encoding="utf-8") if line.strip()
    )}
    pc_detail = pc_detail.copy()
    pc_detail["evidence_type"] = pc_detail["id"].map(raw)
    print("\n  evidence_type별(parent-child 기준):")
    print(pc_detail.groupby("evidence_type")[["fact_coverage", "fully_covered"]].mean().to_string())

    detail_df.to_csv(RESULTS_PATH, index=False, encoding="utf-8-sig")
    print(f"\n상세 결과 저장: {RESULTS_PATH}")

    print(
        "\n주의: 이건 '문서 단위' retrieval/context 채점이다 - 팀원의 page/chunk/object "
        "단위 채점(daily-briefing 저녁 4/5 참고)과는 기준이 다르고 훨씬 관대하다. "
        "팀원 자신의 baseline도 문서 안 페이지 단위(visual_target_page)는 80% 맞혔지만 "
        "표 블록 단위(visual_target_chunk)는 0%였다 - 이 스크립트 결과가 좋아도 "
        "'표/그림 문제를 풀었다'고 확대 해석하지 말 것. 페이지/bbox 단위 채점 자체는 "
        "여전히 보류 상태(HWP 렌더링 서브시스템 필요, daily-briefing 저녁 5)."
    )


if __name__ == "__main__":
    main()
