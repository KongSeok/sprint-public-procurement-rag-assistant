"""17단계(신규): 프롬프트 v2(2026-09-03 수정 - 다중 답변/상충 정보 처리
지시 추가) 효과 검증 - rag-56(56건) 전체를 실제로 다시 생성해서 프롬프트
v1(=step14 재채점 기준선) 대비 비교한다.

[배경 - 2026-09-03] step14(재생성 없이 채점 로직만 수정)로 확정한 기준선은
abstention_behavior_match=0.946(56건), required_doc_citation_coverage=0.935
(54건), lexical_required_fact_coverage=0.566(53건, 참고용)이었고, 남은
불일치 3건(g22/g24/c25)의 원문을 다시 뜯어보니 두 갈래였다:
  - c25(decision="source_conflict"): 근거 문서 사이에 내용이 상충하면
    "상충한다"고 알려주는 게 정답인데, 프롬프트에 그런 지시가 아예 없어서
    모델이 그냥 완전 기권해버렸다. -> 프롬프트로 고칠 수 있는 부분.
  - g22/g24(decision="abstain"): 모델이 질문의 일부(아는 부분)는 답하고
    나머지(모르는 부분)만 기권했는데, golden set은 "질문 전체 기권"을
    정답으로 본다. 부분 정보라도 알려주는 게 실사용 관점에서 더 나을 수
    있어서, "무조건 전체 기권"을 강제하는 지시는 넣지 않았다(daily-briefing
    한계로 기록) - 이 스크립트로도 이 2건이 여전히 안 바뀔 가능성이 높다는
    걸 미리 감안하고 결과를 봐야 한다.
프롬프트 변경 내용은 src/generation.py의 SYSTEM_PROMPT 및 그 위 주석
참고. 이 스크립트는 "재생성 없이"가 아니라 **실제로 gpt-5-mini를 56회
다시 호출**한다(프롬프트 자체가 달라졌으니 재생성 없이는 효과를 볼 수
없음) - step13/14와 달리 API 비용이 다시 발생한다(저렴하지만 0원은 아님).

비교 대상:
  1. 집계 3지표: 프롬프트 v1(=step14 결과, 아래 BASELINE_V1에 하드코딩) vs
     프롬프트 v2(이번 실행)
  2. g22/g24/c25: 답변 원문이 실제로 바뀌었는지 개별 출력(상충 처리가
     들어갔는지, 여전히 부분 답변인지)
  3. 회귀 체크: step14에서 새로 정상 판정으로 바뀐 8건(다중 답변 오분류
     수정분, c12/c13/c19/g12/g13/g14/g19/g23)이 프롬프트 v2에서도 여전히
     정상인지(프롬프트를 바꾸다 다른 걸 깨뜨리지 않았는지)

사용법: python scripts/step17_generation_prompt_v2_compare.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from src.data_processing.chunking import chunk_all, load_chunks, save_chunks  # noqa: E402
from src.config import OUTPUT_DIR  # noqa: E402
from src.retrieval.embeddings import SentenceTransformerEmbedding  # noqa: E402
from src.generation.generation import (  # noqa: E402
    build_context,
    check_required_facts,
    compute_abstention_match,
    compute_citation_coverage,
    generate_answer,
    is_abstention,
)
from src.evaluation.golden_set_v3 import load_golden_set_v3  # noqa: E402
from src.retrieval.indexing import HybridIndex  # noqa: E402
from src.data_processing.load_metadata import load_clean_metadata  # noqa: E402
from src.data_processing.merge_text import load_merged, merge_all, save_merged  # noqa: E402

RESULTS_PATH = OUTPUT_DIR / "v3_answer56_generation_promptv2_compare.csv"
TOP_K = 5

# step14_v3_generation_rescore.py 실제 실행 결과(2026-09-03, 프롬프트 v1 +
# 고친 is_abstention/extract_cited_doc_ids 기준) - 이번 프롬프트 v2와
# 비교하는 기준선.
BASELINE_V1 = {
    "abstention_behavior_match": (0.946, 56),
    "required_doc_citation_coverage": (0.935, 54),
    "lexical_required_fact_coverage": (0.566, 53),
}

# step14에서 채점 버그(다중 답변 오분류) 수정으로 틀림->맞음으로 바뀐 8건 -
# 프롬프트를 바꾸고 나서도 여전히 맞는지 회귀 체크용.
REGRESSION_CHECK_IDS = [
    "supplemental-qa-c12", "supplemental-qa-c13", "supplemental-qa-c19",
    "supplemental-qa-g12", "supplemental-qa-g13", "supplemental-qa-g14",
    "supplemental-qa-g19", "supplemental-qa-g23",
]
# 남은 불일치 3건 - 이번 프롬프트 변경의 주 타깃(c25는 개선 기대, g22/g24는
# 개선 안 될 수도 있음을 감안하고 볼 것).
FOCUS_IDS = ["supplemental-qa-c25", "supplemental-qa-g22", "supplemental-qa-g24"]


def main():
    df = load_golden_set_v3()
    rag56 = df[df["source_lane"] == "answer"].reset_index(drop=True)
    print(f"[step17] rag-56 로드: {len(rag56)}건 - 프롬프트 v2로 전부 재생성합니다 (gpt-5-mini {len(rag56)}회 호출)")

    chunks = load_chunks()
    if chunks is None:
        print("[step17] 캐시(output/chunks.pkl) 없음 -> step2~3부터 다시 계산합니다...")
        merged = load_merged()
        if merged is None:
            merged = merge_all(load_clean_metadata())
            save_merged(merged)
            merged = load_merged()
        chunks = chunk_all(merged)
        save_chunks(chunks)

    print("\n[step17] KURE-v1 인덱스 준비 중 (기존 컬렉션 재사용 시도)...")
    kure_backend = SentenceTransformerEmbedding()
    index = HybridIndex(chunks, embedding_backend=kure_backend)

    from openai import OpenAI
    client = OpenAI()

    rows = []
    for i, row in rag56.iterrows():
        query = row["query"]
        expected_should_abstain = bool(row["decision"] == "abstain")
        required_doc_ids = row["expected_doc_id"] if isinstance(row["expected_doc_id"], list) else []
        required_facts = row.get("required_fact_groups")

        hits = index.hybrid_search(query, k=TOP_K, expand_to_parent=True)
        context = build_context(hits)
        answer = generate_answer(client, query, context)  # src/generation.py의 새 SYSTEM_PROMPT(v2) 사용

        if expected_should_abstain:
            citation_matched, citation_total = 0, 0
        elif answer is None:
            citation_matched, citation_total = 0, len(required_doc_ids)
        else:
            citation_matched, citation_total = compute_citation_coverage(answer, required_doc_ids)

        if answer is None or is_abstention(answer):
            fact_matched, fact_total = 0, 0
        else:
            fact_matched, fact_total = check_required_facts(answer, required_facts)

        abstention_match = compute_abstention_match(answer, expected_should_abstain)

        rows.append({
            "id": row["id"],
            "query": query,
            "decision": row["decision"],
            "expected_should_abstain": expected_should_abstain,
            "answer": answer,
            "abstention_match": abstention_match,
            "citation_matched": citation_matched,
            "citation_total": citation_total,
            "citation_coverage": (citation_matched / citation_total) if citation_total else None,
            "fact_matched": fact_matched,
            "fact_total": fact_total,
            "fact_coverage": (fact_matched / fact_total) if fact_total else None,
        })
        print(f"  [{i + 1}/{len(rag56)}] {row['id']}: abstention_match={abstention_match} "
              f"citation={citation_matched}/{citation_total} fact={fact_matched}/{fact_total}")

    result_df = pd.DataFrame(rows)
    result_df.to_csv(RESULTS_PATH, index=False, encoding="utf-8-sig")
    print(f"\n상세 결과 저장: {RESULTS_PATH}")

    v2 = {
        "abstention_behavior_match": (result_df["abstention_match"].mean(), len(result_df)),
        "required_doc_citation_coverage": (
            result_df.loc[result_df["citation_total"] > 0, "citation_coverage"].mean(),
            int((result_df["citation_total"] > 0).sum()),
        ),
        "lexical_required_fact_coverage": (
            result_df.loc[result_df["fact_total"] > 0, "fact_coverage"].mean(),
            int((result_df["fact_total"] > 0).sum()),
        ),
    }

    print(f"\n{'=' * 78}\n프롬프트 v1(=step14 기준선) vs 프롬프트 v2(다중답변/상충 지시 추가) - rag-56\n{'=' * 78}")
    print(f"{'지표':<34}{'v1':>10}{'(N)':>5}{'v2':>10}{'(N)':>5}{'격차':>10}")
    for key, label in [
        ("abstention_behavior_match", "abstention_behavior_match"),
        ("required_doc_citation_coverage", "required_doc_citation_coverage"),
        ("lexical_required_fact_coverage", "lexical_required_fact_coverage(참고용)"),
    ]:
        v1_val, v1_n = BASELINE_V1[key]
        v2_val, v2_n = v2[key]
        print(f"{label:<34}{v1_val:>10.3f}{v1_n:>5}{v2_val:>10.3f}{v2_n:>5}{v2_val - v1_val:>+10.3f}")

    print(f"\n{'=' * 78}\n타깃 3건(c25/g22/g24) - 답변이 실제로 바뀌었는지 확인\n{'=' * 78}")
    for cid in FOCUS_IDS:
        r = result_df[result_df["id"] == cid]
        if len(r) == 0:
            print(f"  {cid}: 결과 없음(id 불일치?)")
            continue
        r = r.iloc[0]
        print(f"\n  [{cid}] decision={r['decision']} abstention_match={r['abstention_match']}")
        print(f"    답변: {r['answer']}")

    print(f"\n{'=' * 78}\n회귀 체크 - step14에서 정상 판정으로 바뀐 8건이 v2에서도 정상인지\n{'=' * 78}")
    reg = result_df[result_df["id"].isin(REGRESSION_CHECK_IDS)]
    print(reg[["id", "abstention_match"]].to_string(index=False))
    n_regressed = int((~reg["abstention_match"]).sum())
    if n_regressed:
        print(f"\n  경고: {n_regressed}건이 v2에서 다시 abstention_match=False로 회귀했습니다 - 원문 확인 필요")
    else:
        print("\n  회귀 없음 - 8건 전부 abstention_match=True 유지")

    print(
        "\n주의: g22/g24는 프롬프트 v2로도 안 바뀔 수 있다(모듈 docstring 참고 - "
        "부분 정보를 알려주는 게 실사용 관점에서 나을 수 있어 '무조건 전체 기권'을 "
        "강제하는 지시는 일부러 넣지 않았음). c25가 이제 상충을 알리는 답변으로 "
        "바뀌었는지가 이번 프롬프트 변경의 핵심 검증 포인트."
    )


if __name__ == "__main__":
    main()
