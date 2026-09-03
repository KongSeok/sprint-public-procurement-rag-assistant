"""12단계(신규): golden-set-v3-share의 rag-56(답변형 보조 54건, retrieval
가능 대상)을 "우리 파이프라인"으로 직접 채점해서 팀원이 측정한
`answer-56.metrics.json`과 나란히 비교한다.

[배경 - 2026-09-02 밤] 앞서 111건 공식 golden set으로 KURE-v1 vs
text-embedding-3-small A/B(step11)를 한 뒤, 팀원 쪽 retrieval 수치
(`golden-set-v3-share/evaluation/private/supplemental/runs/provisional-v1/
answer-56.metrics.json`)와도 비교해봤다. 그런데 그 비교는 두 가지가 동시에
달랐다: (1) golden set 자체가 다름(우리 111 vs 팀원 보조 56) (2) retrieval
시스템 자체가 다름(우리 HybridIndex vs 팀원 "API 기준선" 브랜치, 실제
설정 불명) - 이러면 숫자 차이가 어느 쪽 때문인지 알 수 없다.

이 스크립트는 그 중 (1)을 제거한다: 팀원이 채점에 쓴 것과 "같은" golden
set(rag-56)을 우리 `src/golden_set_v3.py` 로더로 불러와서, 우리
HybridIndex(KURE-v1)로 직접 검색해 recall@k/MRR/MRR@10/nDCG@10을 계산한다.
이러면 남는 차이는 순수하게 "retrieval 시스템 자체의 차이"에 가까워진다
(단, 팀원 시스템의 정확한 임베딩/청킹 설정은 여전히 모른다는 한계는 남음 -
아래 출력의 주의사항 참고).

retrieval-eligible 필터: 팀원 쪽 answer-56.metrics.json은
"retrieval_eligible": 54(56건 중 2건 제외)라고 밝혔다. rag-56.draft.jsonl을
직접 열어보면 gold.decision 분포가 answer 53 / abstain 2 / source_conflict 1
이고, "abstain"(기권이 정답인 질문, 애초에 검색으로 찾을 문서가 없음) 2건만
빼면 정확히 54건이 남는다 - 그래서 이 스크립트도 decision != "abstain"으로
필터링한다(둘 다 54가 나오는 걸 이미 로컬에서 확인함).

비교 대상 팀원 수치(2026-09-01 provisional-v1, 54건):
    recall@1=0.753086 recall@3=0.808642 recall@5=0.845679 recall@10=0.845679
    mrr@10=0.824691 ndcg@10=0.811461

사용법: python scripts/step12_v3_answer_retrieval_compare.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from src.data_processing.chunking import chunk_all, load_chunks, save_chunks  # noqa: E402
from src.config import OUTPUT_DIR  # noqa: E402
from src.retrieval.embeddings import SentenceTransformerEmbedding  # noqa: E402
from src.evaluation.evaluation import evaluate_retrieval  # noqa: E402
from src.evaluation.golden_set_v3 import load_golden_set_v3  # noqa: E402
from src.retrieval.indexing import HybridIndex  # noqa: E402
from src.data_processing.load_metadata import load_clean_metadata  # noqa: E402
from src.data_processing.merge_text import load_merged, merge_all, save_merged  # noqa: E402

RESULTS_PATH = OUTPUT_DIR / "v3_answer56_retrieval_compare.csv"

TEAMMATE_54 = {
    "recall@1": 0.753086,
    "recall@3": 0.808642,
    "recall@5": 0.845679,
    "recall@10": 0.845679,
    "mrr@10": 0.824691,
    "ndcg@10": 0.811461,
}


def main():
    df = load_golden_set_v3()
    sub = df[df["source_lane"] == "answer"].copy()  # rag-56만(visual-10 제외) - 팀원 answer-56과 동일 lane
    eligible = sub[sub["decision"] != "abstain"].reset_index(drop=True)
    print(
        f"[step12] rag-56 로드: {len(sub)}건 -> decision=abstain 제외 후 "
        f"retrieval-eligible {len(eligible)}건 (팀원 answer-56.metrics.json의 "
        f"retrieval_eligible=54와 비교)"
    )
    n_empty = int((eligible["expected_doc_id"].apply(len) == 0).sum())
    if n_empty:
        print(f"[step12] 경고: expected_doc_id가 빈 항목 {n_empty}건 있음(코퍼스 매칭 실패) - recall이 부당하게 깎일 수 있음")

    chunks = load_chunks()
    if chunks is None:
        print("[step12] 캐시(output/chunks.pkl) 없음 -> step2~3부터 다시 계산합니다...")
        merged = load_merged()
        if merged is None:
            merged = merge_all(load_clean_metadata())
            save_merged(merged)
            merged = load_merged()
        chunks = chunk_all(merged)
        save_chunks(chunks)

    print("\n[step12] KURE-v1 인덱스 준비 중 (step10/11과 동일 collection 재사용 시도)...")
    kure_backend = SentenceTransformerEmbedding()
    index = HybridIndex(chunks, embedding_backend=kure_backend)

    detail_df, summary_df = evaluate_retrieval(
        index, eligible, methods=("hybrid",), k_values=(1, 3, 5, 10)
    )
    row = summary_df.iloc[0]

    print(f"\n{'=' * 70}\n우리 시스템 (KURE-v1 + HybridIndex) vs 팀원 (API 기준선) - 같은 rag-56 {len(eligible)}건\n{'=' * 70}")
    header = f"{'지표':<12}{'우리':>12}{'팀원':>12}{'격차':>12}"
    print(header)
    for metric in ["recall@1", "recall@3", "recall@5", "recall@10", "mrr@10", "ndcg@10"]:
        ours = row[metric]
        theirs = TEAMMATE_54[metric]
        print(f"{metric:<12}{ours:>12.3f}{theirs:>12.3f}{ours - theirs:>+12.3f}")

    print(
        "\n주의: golden set(rag-56, 54건)은 이제 완전히 동일하다. 다만 팀원 수치가 정확히 "
        "어떤 임베딩/청킹/hybrid 가중치로 나온 것인지는 공유 패키지에서 확인 못 했으므로, "
        "이 비교도 여전히 '우리 HybridIndex(KURE-v1) 구성' vs '팀원 API 기준선 구성' 간의 "
        "시스템 차이 전체를 반영한다 - 어느 한 설계 요소(예: hybrid weight) 때문이라고 "
        "단정하지 말 것."
    )

    detail_df.to_csv(RESULTS_PATH, index=False, encoding="utf-8-sig")
    print(f"\n상세 결과 저장: {RESULTS_PATH}")


if __name__ == "__main__":
    main()
