"""16단계(신규): BM25/벡터 가중치(vector_weight/bm25_weight) 튜닝 - 공식
골든셋(111건) 기준.

[배경 - 2026-09-03] 리랭커 실험(step15, BAAI/bge-reranker-v2-m3 /
Dongjin-kr/ko-reranker 둘 다 hybrid 단독보다 못해 기각)에 이어 시도하는
다음 후보. `HybridIndex.hybrid_search()`는 벡터 유사도와 BM25 점수를 각각
min-max 정규화한 뒤 `vector_weight * v_score + bm25_weight * b_score`로
합쳐서 순위를 매기는데(src/indexing.py), 기본값은 0.5/0.5로 딱히 실측
근거 없이 정해둔 값이었다. 리랭커와 달리 이건 이미 인덱싱까지 끝난
`HybridIndex` 하나로 후보 풀(BM25/벡터 각각의 결과)만 다른 비율로
재조합하는 거라 재임베딩·재인덱싱이 전혀 없다 - API 호출도 없고, 모델
다운로드도 없고, alpha 하나 바꿔 도는 데 걸리는 시간은 검색 자체
시간뿐이라 리랭커 실험보다 훨씬 빠르고 싸게 돌 수 있다.

[2026-09-03 버그 수정 선행] evaluate_retrieval()의 hybrid_kwargs 파라미터가
시그니처에는 있었지만 실제로는 아래(_search_doc_ids)까지 전달되지 않는
죽은 코드였다 - 이 튜닝을 하려면 반드시 필요해서 이번에 실제로 연결했다
(src/evaluation.py, 2026-09-03 버그 수정 주석 참고).

방법: vector_weight를 0.0~1.0까지 스윕(bm25_weight = 1 - vector_weight로
항상 합이 1이 되게 고정 - min-max 정규화 이후라 절대값이 아니라 "상대
비율"만 의미 있음). alpha=0.0은 BM25 단독, alpha=1.0은 벡터 단독과
동치이므로 기존 "vector"/"bm25" 단독 method 결과와도 자연스럽게
비교된다.

사용법: python scripts/step16_hybrid_weight_tuning.py
    (선택) 커맨드라인 인자로 grid를 콤마로 직접 지정 가능:
    python scripts/step16_hybrid_weight_tuning.py 0.3,0.4,0.5,0.6,0.7
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from src.data_processing.chunking import chunk_all, load_chunks, save_chunks  # noqa: E402
from src.config import OUTPUT_DIR  # noqa: E402
from src.evaluation.evaluation import evaluate_retrieval, load_golden_set  # noqa: E402
from src.retrieval.indexing import HybridIndex  # noqa: E402
from src.data_processing.load_metadata import load_clean_metadata  # noqa: E402
from src.data_processing.merge_text import load_merged, merge_all, save_merged  # noqa: E402

RESULTS_PATH = OUTPUT_DIR / "hybrid_weight_tuning_v6.csv"
DETAIL_PATH = OUTPUT_DIR / "hybrid_weight_tuning_v6_detail.csv"
K_VALUES = (1, 3, 5, 10)
DEFAULT_GRID = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)


def main():
    if len(sys.argv) > 1:
        grid = tuple(float(x) for x in sys.argv[1].split(","))
    else:
        grid = DEFAULT_GRID

    golden_df = load_golden_set()  # 기본 경로 = 공식 111건(golden_testset_verified_111_v6.json)
    retrieval_df = golden_df[golden_df["expected_doc_id"].apply(lambda v: isinstance(v, list) and len(v) > 0)]
    print(f"[step16] golden set 로드: {len(golden_df)}건 (retrieval 평가 대상 {len(retrieval_df)}건)")
    print(f"[step16] vector_weight 스윕 grid: {grid} (bm25_weight = 1 - vector_weight)")

    chunks = load_chunks()
    if chunks is None:
        print("[step16] 캐시(output/chunks.pkl) 없음 -> step2~3부터 다시 계산합니다...")
        df = load_merged()
        if df is None:
            df = merge_all(load_clean_metadata())
            save_merged(df)
            df = load_merged()
        chunks = chunk_all(df)
        save_chunks(chunks)

    print("\nHybridIndex 준비 중 (기존 컬렉션 재사용 시도, KURE-v1)...")
    index = HybridIndex(chunks)

    rows = []
    detail_frames = []
    for alpha in grid:
        bm25_weight = round(1.0 - alpha, 4)
        detail_df, summary_df = evaluate_retrieval(
            index, retrieval_df, methods=("hybrid",), k_values=K_VALUES,
            hybrid_kwargs={"vector_weight": alpha, "bm25_weight": bm25_weight},
        )
        detail_df["vector_weight"] = alpha
        detail_df["bm25_weight"] = bm25_weight
        detail_frames.append(detail_df)

        row = summary_df.iloc[0].to_dict()
        row["vector_weight"] = alpha
        row["bm25_weight"] = bm25_weight
        rows.append(row)
        print(f"  vector_weight={alpha:.1f} bm25_weight={bm25_weight:.1f}  "
              f"recall@1={row['recall@1']:.3f} recall@5={row['recall@5']:.3f} "
              f"recall@10={row['recall@10']:.3f} mrr={row['mrr']:.3f}")

    result_df = pd.DataFrame(rows)
    result_df.to_csv(RESULTS_PATH, index=False, encoding="utf-8-sig")
    pd.concat(detail_frames, ignore_index=True).to_csv(DETAIL_PATH, index=False, encoding="utf-8-sig")

    print(f"\n{'=' * 78}\n요약 (vector_weight 스윕, 공식 111건 기준)\n{'=' * 78}")
    cols = ["vector_weight", "bm25_weight", "recall@1", "recall@3", "recall@5", "recall@10", "mrr"]
    print(result_df[cols].to_string(index=False))

    default_row = result_df[result_df["vector_weight"] == 0.5]
    print("\n현재 기본값(0.5/0.5) 대비 각 지표 최고 alpha:")
    for metric in ["recall@1", "recall@3", "recall@5", "recall@10", "mrr"]:
        best_idx = result_df[metric].idxmax()
        best = result_df.loc[best_idx]
        base = default_row.iloc[0][metric] if len(default_row) else None
        delta_str = f" (기본값 대비 {best[metric] - base:+.3f})" if base is not None else ""
        print(f"  {metric}: vector_weight={best['vector_weight']:.1f} -> {metric}={best[metric]:.3f}{delta_str}")

    print(
        "\n주의: 111건 golden set 전체에 대한 평균이라, 특정 alpha가 한 지표에서만 "
        "근소하게 앞선다고 바로 채택하지 말 것 - 여러 지표(recall@1/5/10, mrr)에서 "
        "고르게 기본값(0.5)보다 나은 alpha가 있는지를 봐야 하고, 격차가 몇 %p 이내로 "
        "작으면 golden set 111건 규모에서는 노이즈일 수 있다(상세 CSV로 어떤 문항이 "
        "바뀌었는지 확인 권장, step15 리랭커 분석 때와 같은 방식)."
    )
    print(f"\n요약 결과 저장: {RESULTS_PATH}")
    print(f"질의별 상세 결과 저장(모든 alpha 포함): {DETAIL_PATH}")


if __name__ == "__main__":
    main()
