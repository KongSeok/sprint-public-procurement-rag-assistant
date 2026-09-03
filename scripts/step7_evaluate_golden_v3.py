"""신규: golden-set-v3-share 패키지(팀원이 공유한 3차 API 기준선/보조
골든셋)로 Retrieval 성능을 측정한다. step5_evaluate.py와 마찬가지로
Retrieval 평가만 다룬다(Answer 평가는 아직 별도 - 8/28 브리핑 참고).

[중요] src/golden_set_v3.py의 문서에 자세히 적어뒀지만 핵심만 다시 적는다:
    - 원본 패키지가 "131건"이라 말하지만, 우리 코퍼스와 매칭 가능한 건
      rag-56(답변형) + set-13(집합검색형) + visual-10(표/그림) = 79건뿐이다.
      core40/corpus_analytics 50건은 doc_id 매핑 정보가 이번 공유 패키지에
      없어서 이 스크립트가 아예 다루지 않는다.
    - 이 79건은 패키지 자체가 "enabled": false / "review.status": "draft"
      (사람 승인 0건)로 명시한 상태 그대로 포함시킨 것이다 - 결과 해석 시
      "아직 팀 검수 전인 문항들"이라는 점을 감안할 것.

채점 방식이 lane마다 다르다:
    - lane="answer"(rag-56 + visual-10, 66건): 기존 recall@k/MRR
      (evaluation.evaluate_retrieval, step5와 동일 함수).
    - lane="set"(set-13, 13건): Precision/Recall/F1
      (evaluation.evaluate_set_retrieval, 이번에 신규 추가).

사용법: python scripts/step7_evaluate_golden_v3.py
    (사전 준비: golden-set-v3-share 패키지에서 rag-56.draft.jsonl /
    set-13.draft.jsonl / document-structure-visual-qa.jsonl 3개를
    data/golden_set_v3/ 밑에 복사해둘 것)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_processing.chunking import chunk_all, load_chunks, save_chunks  # noqa: E402
from src.config import OUTPUT_DIR  # noqa: E402
from src.evaluation.evaluation import evaluate_retrieval, evaluate_set_retrieval  # noqa: E402
from src.evaluation.golden_set_v3 import load_golden_set_v3  # noqa: E402
from src.retrieval.indexing import HybridIndex  # noqa: E402
from src.data_processing.load_metadata import load_clean_metadata  # noqa: E402
from src.data_processing.merge_text import load_merged, merge_all, save_merged  # noqa: E402

ANSWER_RESULTS_PATH = OUTPUT_DIR / "eval_results_v3_answer.csv"
SET_RESULTS_PATH = OUTPUT_DIR / "eval_results_v3_set.csv"


def _drop_unscoreable(df, lane_label):
    """expected_doc_id가 완전히 빈 행(코퍼스와 매칭 실패했거나 decision=abstain)은
    recall/precision을 항상 0으로 만들어 평균을 왜곡하므로 평가에서 제외하고
    몇 건 제외했는지만 알려준다."""
    empty_mask = df["expected_doc_id"].apply(len) == 0
    n_empty = int(empty_mask.sum())
    if n_empty:
        print(f"[{lane_label}] 정답 문서를 하나도 못 찾은(매칭 실패 또는 decision=abstain) {n_empty}건은 평가에서 제외")
    return df[~empty_mask].reset_index(drop=True)


if __name__ == "__main__":
    golden_v3 = load_golden_set_v3()

    answer_df = _drop_unscoreable(golden_v3[golden_v3["lane"] == "answer"].reset_index(drop=True), "answer/visual lane")
    set_df = _drop_unscoreable(golden_v3[golden_v3["lane"] == "set"].reset_index(drop=True), "set lane")

    chunks = load_chunks()
    if chunks is None:
        print("[step7] 캐시(output/chunks.pkl) 없음 -> step2~3부터 다시 계산합니다...")
        df = load_merged()
        if df is None:
            df = merge_all(load_clean_metadata())
            save_merged(df)
            df = load_merged()
        chunks = chunk_all(df)
        save_chunks(chunks)

    index = HybridIndex(chunks)
    print(f"인덱싱 완료: chunk {len(chunks)}개, 임베딩 백엔드={index.embedding_backend.name}\n")

    print(f"=== answer/visual lane({len(answer_df)}건): recall@k / MRR ===")
    answer_detail, answer_summary = evaluate_retrieval(index, answer_df, methods=("vector", "bm25", "hybrid"), k_values=(1, 3, 5))
    print(answer_summary.to_string(index=False))
    answer_detail.to_csv(ANSWER_RESULTS_PATH, index=False, encoding="utf-8-sig")
    print(f"상세 결과 저장: {ANSWER_RESULTS_PATH}\n")

    print(f"=== set lane({len(set_df)}건): Precision / Recall / F1 ===")
    set_detail, set_summary = evaluate_set_retrieval(index, set_df, methods=("vector", "bm25", "hybrid"))
    print(set_summary.to_string(index=False))
    set_detail.to_csv(SET_RESULTS_PATH, index=False, encoding="utf-8-sig")
    print(f"상세 결과 저장: {SET_RESULTS_PATH}")
