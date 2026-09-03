"""11단계(신규): 임베딩 백엔드 A/B 비교 - KURE-v1(로컬) vs text-embedding-3-small(API).

[배경 - 2026-09-02 저녁] "지금 임베딩(KURE-v1)이 최선인가, OpenAI
text-embedding-3-small로 바꾸면 더 나은가"를 실제로 재보기 전에, 이 비교를
안전하게 하려면 먼저 고쳐야 하는 버그가 있었다: `HybridIndex`의 chroma
컬렉션 재사용 판단이 "chunk 개수가 같으면 재사용"이었고 임베딩 백엔드가
같은지는 전혀 확인하지 않았다 - 백엔드를 바꿔도 chunk 개수가 그대로면
예전 백엔드로 만든 벡터를 조용히 재사용해버릴 위험이 있었다(A/B 비교 자체가
무의미해지는 사고). `src/indexing.py`에 `embedding_backend` 주입 파라미터를
추가하고, `collection_name`을 backend 이름 기준으로 자동 구분하도록 고쳐서
이 위험을 없앴다(HybridIndex 자체의 docstring/주석 참고). 이 스크립트는 그
위에서 두 백엔드를 실제로 비교한다.

비교 범위: retrieval 단계만(generation 호출 없음 - 비용/시간을 최소화하려고
일부러 이렇게 설계했다). 두 가지를 본다.

1단계 - doc 단위 retrieval 회귀: recall@1/3/5, coverage@1/3/5, MRR
    (evaluate_retrieval, "검증된" golden_testset_verified_111_v6.json 기준)
1.5단계 - context fact coverage(API 비용 0원, generation 없이 검색 직후
    context 텍스트에 필요한 사실이 있는지만 확인 - step10과 동일 함수 재사용)

Parent-Child(expand_to_parent)는 두 백엔드 모두에서 켜고 끄고 두 번씩 돌려서,
"임베딩을 바꿨을 때도 parent-child 효과가 같은 방향으로 나오는지"까지 같이
확인한다 - 임베딩과 parent-child는 서로 다른 축이라 상호작용이 있을 수
있다.

주의: text-embedding-3-small은 OpenAI API 호출이라 OPENAI_API_KEY가
필요하고 요금이 든다(1M 토큰당 $0.02 - 이 코퍼스 전체를 임베딩해도 보통
1달러 미만이지만 0원은 아니다). RFP 청크 텍스트를 OpenAI로 보낸다는 점도
팀의 private-corpus egress 정책과 같은 종류이니 참고할 것.

사용법: python scripts/step11_embedding_compare.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from src.data_processing.chunking import chunk_all, load_chunks, save_chunks  # noqa: E402
from src.config import OUTPUT_DIR  # noqa: E402
from src.retrieval.embeddings import OpenAIEmbedding, SentenceTransformerEmbedding  # noqa: E402
from src.evaluation.evaluation import evaluate_context_fact_coverage, evaluate_retrieval, load_golden_set  # noqa: E402
from src.retrieval.indexing import HybridIndex  # noqa: E402
from src.data_processing.load_metadata import load_clean_metadata  # noqa: E402
from src.data_processing.merge_text import load_merged, merge_all, save_merged  # noqa: E402

TOP_K = 5
RESULTS_PATH = OUTPUT_DIR / "embedding_compare_v6.csv"


def _gradable_df(golden_df: pd.DataFrame) -> pd.DataFrame:
    df = golden_df.copy()
    if "answerability" in df.columns:
        df = df[df["answerability"].fillna("answerable") == "answerable"].reset_index(drop=True)
    df = df[df["expected_doc_id"].apply(lambda v: isinstance(v, list) and len(v) > 0)].reset_index(drop=True)
    if "required_facts" in df.columns and "required_fact_groups" not in df.columns:
        df = df.rename(columns={"required_facts": "required_fact_groups"})
    if "required_fact_groups" in df.columns:
        df = df[df["required_fact_groups"].apply(lambda v: isinstance(v, list) and len(v) > 0)].reset_index(drop=True)
    return df


def _evaluate_backend(label: str, index: HybridIndex, retrieval_df, coverage_df) -> dict:
    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")

    _, retrieval_summary = evaluate_retrieval(index, retrieval_df, methods=("hybrid",), k_values=(1, 3, 5))
    row = retrieval_summary.iloc[0]
    print(f"[retrieval, {len(retrieval_df)}건] recall@1={row['recall@1']:.3f} "
          f"recall@3={row['recall@3']:.3f} recall@5={row['recall@5']:.3f} "
          f"coverage@5={row['coverage@5']:.3f} mrr={row['mrr']:.3f}")

    result = {"label": label, **{k: row[k] for k in ["recall@1", "recall@3", "recall@5", "coverage@5", "mrr"]}}

    if len(coverage_df):
        base_detail, _ = evaluate_context_fact_coverage(
            index, coverage_df, methods=("hybrid",), k=TOP_K, expand_to_parent=False
        )
        pc_detail, _ = evaluate_context_fact_coverage(
            index, coverage_df, methods=("hybrid",), k=TOP_K, expand_to_parent=True
        )
        base_rate = base_detail["fully_covered"].mean()
        pc_rate = pc_detail["fully_covered"].mean()
        base_cov = base_detail["fact_coverage"].mean()
        pc_cov = pc_detail["fact_coverage"].mean()
        print(f"[context fact coverage, {len(coverage_df)}건] "
              f"완전커버율 baseline={base_rate:.3f} parent-child={pc_rate:.3f} "
              f"(델타 {pc_rate - base_rate:+.3f}) / "
              f"평균coverage baseline={base_cov:.3f} parent-child={pc_cov:.3f} "
              f"(델타 {pc_cov - base_cov:+.3f})")
        result.update({
            "fully_covered_base": base_rate, "fully_covered_pc": pc_rate,
            "fact_coverage_base": base_cov, "fact_coverage_pc": pc_cov,
        })
    return result


def main():
    golden_df = load_golden_set()  # 기본 경로 = 검증된 111건(golden_testset_verified_111_v6.json)
    retrieval_df = golden_df[golden_df["expected_doc_id"].apply(lambda v: isinstance(v, list) and len(v) > 0)]
    coverage_df = _gradable_df(golden_df)
    print(f"[step11] golden set 로드: {len(golden_df)}건 (retrieval 평가 대상 {len(retrieval_df)}건, "
          f"context coverage 평가 대상 {len(coverage_df)}건)")

    chunks = load_chunks()
    if chunks is None:
        print("[step11] 캐시(output/chunks.pkl) 없음 -> step2~3부터 다시 계산합니다...")
        df = load_merged()
        if df is None:
            df = merge_all(load_clean_metadata())
            save_merged(df)
            df = load_merged()
        chunks = chunk_all(df)
        save_chunks(chunks)

    results = []

    print("\n[1/2] KURE-v1 (로컬, 무료) 인덱싱 중...")
    kure_backend = SentenceTransformerEmbedding()
    kure_index = HybridIndex(chunks, embedding_backend=kure_backend)
    results.append(_evaluate_backend(f"KURE-v1 ({kure_backend.name})", kure_index, retrieval_df, coverage_df))

    if not os.environ.get("OPENAI_API_KEY"):
        print("\n" + "=" * 70)
        print("OPENAI_API_KEY가 없어 text-embedding-3-small 비교는 건너뜁니다.")
        print("키를 설정한 뒤 다시 실행하면 2/2까지 이어집니다.")
        print("=" * 70)
    else:
        print("\n[2/2] text-embedding-3-small (OpenAI API, 유료) 인덱싱 중...")
        te3_backend = OpenAIEmbedding()
        te3_index = HybridIndex(chunks, embedding_backend=te3_backend)
        results.append(_evaluate_backend(f"text-embedding-3-small ({te3_backend.name})", te3_index, retrieval_df, coverage_df))

    result_df = pd.DataFrame(results)
    result_df.to_csv(RESULTS_PATH, index=False, encoding="utf-8-sig")
    print(f"\n비교 결과 저장: {RESULTS_PATH}")
    if len(result_df) > 1:
        print("\n" + "=" * 70)
        print("요약 비교")
        print("=" * 70)
        print(result_df.to_string(index=False))


if __name__ == "__main__":
    main()
