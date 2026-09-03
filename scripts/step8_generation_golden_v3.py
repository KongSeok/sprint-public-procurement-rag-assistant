"""신규: golden-set-v3-share 패키지(79건, src/golden_set_v3.py 참고)로
Generation baseline을 돌린다. step6_generation_baseline.py(v6 golden set)와
쌍을 이루는 스크립트 - 호출/채점 로직은 src/generation.py를 공유한다.

[중요 - 다시 강조] 이 79건은 원본 패키지가 "enabled": false /
"review.status": draft(사람 승인 0건)로 명시한, 아직 팀 검수 전인
문항이다. 그대로 포함해서 baseline을 잡되, 결과 해석 시 이 점을 감안할 것.
lane="set"(집합검색형, 정답이 여러 문서)은 gold_answer(전체 정답 문장)가
없고 required_fact_groups만 있다 - "정답 문서들의 이름/사업명이 답변에
들어있는지"로 채점한다(정답 개수가 많은 문항은 근거 chunk도 더 넓게 가져와야
해서 answer lane과 top-k를 다르게 뒀다, 아래 TOP_K_SET 참고).

사전 준비:
    - `pip install openai`, 환경변수 OPENAI_API_KEY 설정
    - data/golden_set_v3/ 밑에 rag-56.draft.jsonl / set-13.draft.jsonl /
      document-structure-visual-qa.jsonl 3개 있어야 함(scripts/
      step7_evaluate_golden_v3.py와 동일한 준비물)

사용법: python scripts/step8_generation_golden_v3.py
    - 79건 다 돌리면 API 비용이 드니, 처음엔 LIMIT을 작은 수로.
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from src.data_processing.chunking import chunk_all, load_chunks, save_chunks  # noqa: E402
from src.config import OUTPUT_DIR  # noqa: E402
from src.generation.generation import build_context, check_required_facts, generate_answer  # noqa: E402
from src.evaluation.golden_set_v3 import load_golden_set_v3  # noqa: E402
from src.retrieval.indexing import HybridIndex  # noqa: E402
from src.data_processing.load_metadata import load_clean_metadata  # noqa: E402
from src.data_processing.merge_text import load_merged, merge_all, save_merged  # noqa: E402

TOP_K_ANSWER = 5  # lane="answer"(단일 정답 위주): step5/step6과 동일하게 맞춤
TOP_K_SET_BASE = 10  # lane="set"(다중 정답): 정답 개수 + 여유분과 이 값 중 큰 쪽 사용
LIMIT = None  # 테스트 삼아 일부만 돌려보고 싶으면 정수로 바꾸기 (예: 5)
GEN_RESULTS_PATH = OUTPUT_DIR / "generation_eval_v3.csv"


def main():
    if not os.environ.get("OPENAI_API_KEY"):
        print(
            "! 환경변수 OPENAI_API_KEY가 설정되어 있지 않습니다. "
            "터미널에서 export OPENAI_API_KEY=sk-... 로 설정하거나 "
            "PyCharm Run Configuration의 Environment variables에 추가한 뒤 다시 실행하세요."
        )
        return

    from openai import OpenAI

    client = OpenAI()

    golden_df = load_golden_set_v3()

    # decision이 있는 행(answer/visual lane)에서만 abstain/source_conflict 제외.
    # set lane은 decision 필드 자체가 없어서(항상 None) 영향 없음.
    n_before = len(golden_df)
    golden_df = golden_df[~golden_df["decision"].isin(["abstain", "source_conflict"])].reset_index(drop=True)
    n_skipped_decision = n_before - len(golden_df)
    if n_skipped_decision:
        print(f"[step8] decision=abstain/source_conflict {n_skipped_decision}건은 이번 baseline에서 제외")

    empty_mask = golden_df["expected_doc_id"].apply(len) == 0
    n_empty = int(empty_mask.sum())
    if n_empty:
        print(f"[step8] 정답 문서를 하나도 못 찾은(코퍼스 매칭 실패) {n_empty}건은 제외 - step7 retrieval 평가 대상과 population을 맞추기 위함")
    golden_df = golden_df[~empty_mask].reset_index(drop=True)

    if LIMIT:
        golden_df = golden_df.head(LIMIT)
        print(f"[step8] LIMIT={LIMIT} - 앞 {LIMIT}개 질문만 실행")

    chunks = load_chunks()
    if chunks is None:
        print("[step8] 캐시(output/chunks.pkl) 없음 -> step2~3부터 다시 계산합니다...")
        df = load_merged()
        if df is None:
            df = merge_all(load_clean_metadata())
            save_merged(df)
            df = load_merged()
        chunks = chunk_all(df)
        save_chunks(chunks)

    index = HybridIndex(chunks)
    print(f"인덱싱 완료: chunk {len(chunks)}개, 임베딩 백엔드={index.embedding_backend.name}\n")

    rows = []
    n = len(golden_df)
    for i, (_, row) in enumerate(golden_df.iterrows(), start=1):
        query = row["query"]
        expected = set(row["expected_doc_id"])
        lane = row["lane"]

        top_k = TOP_K_ANSWER if lane == "answer" else max(TOP_K_SET_BASE, len(expected) + 5)
        print(f"[{i}/{n}] ({lane}, top_k={top_k}) {query[:45]}...")

        hits = index.hybrid_search(query, k=top_k)
        context = build_context(hits)
        retrieved_doc_ids = [h.doc_id for h in hits]
        retrieved_set = set(retrieved_doc_ids)
        retrieval_recall = (len(retrieved_set & expected) / len(expected)) if expected else None

        answer = generate_answer(client, query, context)

        record = {
            "id": row.get("id"),
            "lane": lane,
            "source_lane": row.get("source_lane"),
            "query": query,
            "generated_answer": answer,
            "gold_answer": row.get("gold_answer"),
            "n_expected_docs": len(expected),
            "retrieved_doc_ids": " | ".join(retrieved_doc_ids),
            "retrieval_recall": retrieval_recall,
        }

        required_facts = row.get("required_fact_groups")
        if answer is not None:
            matched, total = check_required_facts(answer, required_facts)
            record["facts_matched"] = matched
            record["facts_total"] = total
            record["fact_coverage"] = (matched / total) if total else None
            record["pass"] = (matched == total) if total else None
        else:
            record["facts_matched"] = None
            record["facts_total"] = None
            record["fact_coverage"] = None
            record["pass"] = False  # 생성 자체가 실패했으면 채점상 Fail로 기록

        rows.append(record)
        time.sleep(0.2)  # 과도한 연속 호출로 인한 rate limit 방지용 소폭 지연

    result_df = pd.DataFrame(rows)
    result_df.to_csv(GEN_RESULTS_PATH, index=False, encoding="utf-8-sig")
    print(f"\n질의별 상세 결과 저장: {GEN_RESULTS_PATH}")

    n_errors = int(result_df["generated_answer"].isna().sum())
    if n_errors:
        print(f"생성 실패(API 에러 등) {n_errors}건 - 콘솔 로그에서 에러 메시지 확인")

    print("\n=== Generation Baseline 요약 (golden-set-v3-share, lane별) ===")
    for lane, group in result_df.groupby("lane"):
        gradable = group[group["facts_total"] > 0]
        if len(gradable) == 0:
            continue
        print(f"[{lane}] {len(gradable)}건 채점 가능 - Pass율: {gradable['pass'].mean():.3f}, 평균 fact coverage: {gradable['fact_coverage'].mean():.3f}")

    gradable_all = result_df[result_df["facts_total"] > 0]
    if len(gradable_all) > 0:
        print(f"\n전체 {len(gradable_all)}건 - Pass율: {gradable_all['pass'].mean():.3f}, 평균 fact coverage: {gradable_all['fact_coverage'].mean():.3f}")
        avg_recall = result_df["retrieval_recall"].mean()
        print(f"참고: 이번 배치의 hybrid retrieval_recall 평균 = {avg_recall:.3f}")
        print("-> Retrieval은 맞았는데 Generation이 틀린 케이스는 generation_eval_v3.csv에서")
        print("   retrieval_recall=1.0인데 pass=False인 행들을 직접 확인하세요.")


if __name__ == "__main__":
    main()
