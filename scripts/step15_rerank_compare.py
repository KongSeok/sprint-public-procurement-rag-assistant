"""15단계(신규): 리랭커(cross-encoder) 도입 효과 검증 - hybrid vs
hybrid+rerank, 공식 골든셋(111건) 기준. 리랭커 모델은 커맨드라인 인자로
바꿔가며 후보를 비교할 수 있다(아래 사용법 참고).

[배경 - 2026-09-03] 지금까지의 retrieval 개선(Parent-Child, 임베딩 A/B)은
전부 "후보를 얼마나 잘 찾아오는지"(recall)에 관한 것이었다. 이번엔 다른
축이다: `HybridIndex.hybrid_search()`(BM25+벡터, 둘 다 bi-encoder)는 질의와
문서를 각각 독립적으로 인코딩해 유사도만 비교하는 방식이라, 후보 풀 안에
정답이 있어도 "그 안에서 가장 위로 올려놓는" 정밀도는 떨어질 수 있다.
Cross-encoder 리랭커는 (질의, 문서) 쌍을 통째로 봐서 관련도를 직접
판단하므로 이 부분을 보완할 후보다 - 다만 후보 풀 자체를 넓히지는 못하므로
"후보 풀에 정답이 아예 없는" 문제는 못 고친다(src/reranking.py 모듈
docstring 참고).

비교 범위: retrieval 단계만(generation 호출 없음 - 비용/시간 최소화). 같은
golden set/같은 hybrid 후보 풀에 대해 리랭킹 전(method="hybrid")과 후
(method="hybrid_rerank")를 evaluate_retrieval() 한 번 호출로 나란히 비교한다
(src/evaluation.py의 "hybrid_rerank" method 참고, 2026-09-03 추가).

[1차 후보 결과 - 2026-09-03] BAAI/bge-reranker-v2-m3(다국어 cross-encoder)로
먼저 돌려봤는데 전 지표에서 소폭 악화(recall@5 -2.7%p, recall@10 -1.8%p,
mrr -0.8%p, recall@1만 무변화)됐다. 상세 CSV를 까본 결과 버그가 아니라
이 코퍼스와 안 맞는 두 가지 패턴이 원인으로 보였다: (1) 필터/집계형 질문
(예: "예산 1억 이상인 사업")은 애초에 개별 (질의,문서) 쌍 관련도만 보는
cross-encoder 구조에 안 맞는 태스크, (2) 하도급/공동수급/보상 같은 RFP
표준 조항 질문은 여러 기관 문서에서 조항 문구 자체가 거의 동일해서, 범용
리랭커가 "어느 기관 문서인지"(고유명사)를 못 가려내고 오히려 BM25가 잘
잡던 신호를 눌러버렸다(예: "한국철도공사" 질문에서 정답 문서가 8등 밖으로
밀리고 엉뚱한 기관 문서가 올라옴). → 한국어 특화 리랭커가 고유명사
구별을 더 잘할지 확인하기 위해 2차 후보로 재시도.

리랭커: 기본값은 BAAI/bge-reranker-v2-m3이지만, 커맨드라인 인자로 다른
HuggingFace 모델 id를 넘기면 그걸 대신 쓴다(sentence-transformers
CrossEncoder로 로드 가능한 모델이어야 함). 결과 CSV 파일명에 모델 이름이
자동으로 들어가서 후보끼리 겹쳐쓰지 않는다. 로컬 실행이라 API 비용은
0원이고, 최초 실행 시 HuggingFace에서 모델을 내려받는다(모델마다 용량
다름).

비용/시간: 골든셋 111건 x 후보 풀(k_values 최대값의 2배, 기본 10*2=20개) =
최대 2,220번의 (질의, 문서) 쌍 forward pass가 CPU에서 돈다 - KURE-v1
임베딩보다 문항당 훨씬 오래 걸릴 수 있으니 처음 돌릴 때는 시간 여유를 두고
실행할 것.

사용법:
    python scripts/step15_rerank_compare.py                        # 기본값(bge-reranker-v2-m3)
    python scripts/step15_rerank_compare.py Dongjin-kr/ko-reranker  # 한국어 특화 2차 후보
"""
import re
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
from src.retrieval.reranking import DEFAULT_RERANKER_MODEL, CrossEncoderReranker  # noqa: E402

K_VALUES = (1, 3, 5, 10)


def main():
    model_name = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_RERANKER_MODEL
    safe_model_name = re.sub(r"[^a-zA-Z0-9_-]", "_", model_name)
    results_path = OUTPUT_DIR / f"rerank_compare_v6__{safe_model_name}.csv"

    golden_df = load_golden_set()  # 기본 경로 = 공식 111건(golden_testset_verified_111_v6.json)
    retrieval_df = golden_df[golden_df["expected_doc_id"].apply(lambda v: isinstance(v, list) and len(v) > 0)]
    print(f"[step15] golden set 로드: {len(golden_df)}건 (retrieval 평가 대상 {len(retrieval_df)}건)")
    print(f"[step15] 리랭커 후보: {model_name}")

    chunks = load_chunks()
    if chunks is None:
        print("[step15] 캐시(output/chunks.pkl) 없음 -> step2~3부터 다시 계산합니다...")
        df = load_merged()
        if df is None:
            df = merge_all(load_clean_metadata())
            save_merged(df)
            df = load_merged()
        chunks = chunk_all(df)
        save_chunks(chunks)

    print("\n[1/2] HybridIndex 준비 중 (기존 컬렉션 재사용 시도, KURE-v1)...")
    index = HybridIndex(chunks)

    print(f"\n[2/2] 리랭커 로드 중: {model_name} "
          f"(최초 실행이면 HuggingFace에서 내려받습니다)...")
    reranker = CrossEncoderReranker(model_name=model_name)

    print(f"\n리랭킹 비교 실행 중... (골든셋 {len(retrieval_df)}건 x 후보 풀 최대 "
          f"{max(K_VALUES) * 2}개 - CPU라면 다소 시간이 걸릴 수 있습니다)")
    detail_df, summary_df = evaluate_retrieval(
        index, retrieval_df, methods=("hybrid", "hybrid_rerank"), k_values=K_VALUES, reranker=reranker,
    )

    print(f"\n{'=' * 70}\nhybrid vs hybrid+rerank({model_name}) - 공식 111건 기준\n{'=' * 70}")
    header = f"{'지표':<12}{'hybrid':>12}{'+rerank':>12}{'격차':>12}"
    print(header)
    hybrid_row = summary_df[summary_df["method"] == "hybrid"].iloc[0]
    rerank_row = summary_df[summary_df["method"] == "hybrid_rerank"].iloc[0]
    metrics = [f"recall@{k}" for k in K_VALUES] + [f"mrr@{k}" for k in K_VALUES] + [f"ndcg@{k}" for k in K_VALUES] + ["mrr"]
    for metric in metrics:
        before = hybrid_row[metric]
        after = rerank_row[metric]
        print(f"{metric:<12}{before:>12.3f}{after:>12.3f}{after - before:>+12.3f}")

    print(
        "\n주의: 후보 풀(hybrid_search 결과)은 리랭킹 전/후가 완전히 동일하다 - "
        "그래서 recall@(후보 풀 크기)는 이론적으로 안 바뀌어야 하고, 바뀐다면 "
        "그건 리랭킹이 '더 상위로 끌어올린' 효과가 아니라 후보 풀 크기(=pool_size, "
        "질문마다 max(k_values)*2 또는 정답 개수+5) 경계 근처에서 순서가 재배치되며 "
        "생긴 계산상 차이일 수 있다 - recall@10처럼 pool_size(기본 20)보다 뚜렷이 "
        "작은 k에서 나타나는 개선이 진짜 리랭킹 효과로 더 믿을 만하다."
    )

    detail_df.to_csv(results_path, index=False, encoding="utf-8-sig")
    print(f"\n상세 결과 저장: {results_path}")


if __name__ == "__main__":
    main()
