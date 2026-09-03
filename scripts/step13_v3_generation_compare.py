"""13단계(신규): golden-set-v3-share의 rag-56(답변형 56건) 전체를 우리
시스템(HybridIndex + Parent-Child + gpt-5-mini)으로 실제 generation까지
돌려서, 팀원 쪽 `answer-56.metrics.json`이 잰 것과 "LLM 판정 없이 결정론적으로
계산 가능한" 세 지표만 같은 정의로 비교한다: abstention_behavior_match /
required_doc_citation_coverage / lexical_required_fact_coverage.

[배경 - 2026-09-02 밤] step12는 retrieval(문서를 찾았는지)만 비교했다. 이번엔
한 단계 더 나아가 "찾은 문서로 실제 생성한 답변"까지 팀원과 같은 축으로
재본다. 다만 팀원의 채점은 4개 축인데, correctness/faithfulness/completeness는
3중 블라인드 LLM 판정(`gpt-5.6-sol`)이 있어야 하고 우리는 아직 그 judge에
연결돼 있지 않다(팀 논의 중, daily-briefing 쟁점 1번) - 그래서 이번엔 LLM
판정 없이 코드로 결정론적으로 잴 수 있는 나머지 세 축만 돈다:
    - abstention_behavior_match: 기권해야 할 질문엔 기권하고, 답할 수 있는
      질문엔 답했는지(둘 다 기대와 일치해야 match)
    - required_doc_citation_coverage: 답변이 실제로 "필요한 문서를 인용했다"고
      밝혔는지(검색이 찾았는지가 아니라 "생성된 답변 텍스트"가 인용을 남겼는지)
    - lexical_required_fact_coverage: 기존 어휘 매칭(팀원도 diagnostic-only로
      취급 - 참고용으로만 같이 낸다)
생성 모델은 원래부터 우리도 gpt-5-mini를 쓰고 있어서(src/generation.py)
이 축은 이미 팀원과 모델까지 동일하다 - 이번 비교에서 남는 변수는 순수하게
"검색+프롬프트+청킹" 차이로 더 좁혀진다.

expected_should_abstain 판정 [반드시 확인 필요한 가정]: rag-56의 decision
분포는 answer 53 / abstain 2 / source_conflict 1이다. 이 스크립트는
`decision == "abstain"`인 2건만 "기권을 기대"로 보고, source_conflict(1건)는
"기권을 기대하지 않음"(무언가 답하되 상충을 알리는 것을 기대)으로 처리한다.
이건 golden-set-v3-share 패키지 안에서 이 필드의 정확한 채점 의도를 문서로
확인하지 못해서 세운 가정이다 - 팀원에게 검증 요청 필요(아래 출력에도
경고로 남김).

비교 대상 팀원 수치(2026-09-01 provisional-v1, answer-56.metrics.json):
    abstention_behavior_match=0.732143 (56건 전체 대상)
    required_doc_citation_coverage=0.472222 (54건 대상 - decision!=abstain)
    lexical_required_fact_coverage=0.280769 (39건 대상 - required_fact_groups
    있는 문항만, diagnostic-only)

검색 설정: 우리 "현재 최선" 구성(KURE-v1 + BM25 hybrid + Parent-Child
expand_to_parent=True, k=5)을 그대로 쓴다 - step10/11/12와 마찬가지로
output/chroma_db의 기존 컬렉션을 재사용하므로 재임베딩 없이 빠르게 끝난다.
비용: gpt-5-mini 호출 56회(기권 포함 전수) - 저렴하지만 0원은 아니다.

사용법: python scripts/step13_v3_generation_compare.py
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

RESULTS_PATH = OUTPUT_DIR / "v3_answer56_generation_compare.csv"
TOP_K = 5

TEAMMATE = {
    "abstention_behavior_match": 0.732143,
    "required_doc_citation_coverage": 0.472222,
    "lexical_required_fact_coverage": 0.280769,
}


def main():
    df = load_golden_set_v3()
    rag56 = df[df["source_lane"] == "answer"].reset_index(drop=True)  # 56건 전체(기권 포함)
    n_abstain = int((rag56["decision"] == "abstain").sum())
    n_source_conflict = int((rag56["decision"] == "source_conflict").sum())
    print(
        f"[step13] rag-56 로드: {len(rag56)}건 (decision: abstain={n_abstain}, "
        f"source_conflict={n_source_conflict}, answer={len(rag56) - n_abstain - n_source_conflict})"
    )
    print(
        "[step13] 가정: decision=='abstain'만 기권 기대로 처리, source_conflict는 "
        "기권 기대 아님으로 처리함 - 팀원 채점 의도와 다를 수 있으니 결과 공유 시 이 가정을 같이 밝힐 것."
    )

    chunks = load_chunks()
    if chunks is None:
        print("[step13] 캐시(output/chunks.pkl) 없음 -> step2~3부터 다시 계산합니다...")
        merged = load_merged()
        if merged is None:
            merged = merge_all(load_clean_metadata())
            save_merged(merged)
            merged = load_merged()
        chunks = chunk_all(merged)
        save_chunks(chunks)

    print("\n[step13] KURE-v1 인덱스 준비 중 (기존 컬렉션 재사용 시도)...")
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
        answer = generate_answer(client, query, context)

        # [2026-09-02 밤] citation coverage는 "기권이 정답이 아닌" 문항에서만 의미가
        # 있다(기권 문항은 애초에 인용하지 않는 게 맞는 행동이라, 인용이 없다고
        # 감점하면 안 된다) - 팀원 쪽 metric_coverage.citation=54(56건 중
        # decision==abstain 2건만 제외)와 정확히 맞추기 위해 abstain이면
        # citation_total을 0으로 둬서 분모(citation_total>0 필터) 계산에서
        # 아예 빠지게 한다. required_doc_ids가 (매칭 실패 등으로) 비어 있는
        # 경우도 마찬가지로 자연히 빠진다.
        if expected_should_abstain:
            citation_matched, citation_total = 0, 0
        elif answer is None:
            citation_matched, citation_total = 0, len(required_doc_ids)
        else:
            citation_matched, citation_total = compute_citation_coverage(answer, required_doc_ids)

        # [2026-09-02 밤] lexical_fact_coverage 분모 규칙은 answer-56.metrics.json을
        # 역추적해서 알아냈다(계약 문서에 명시돼 있지 않음): 팀원 쪽 39건 분모는
        # "required_fact_groups가 있는 문항" 전체(54건)가 아니라, 그중에서도
        # "실제 생성된 답변이 기권이 아니었던" 문항만 남긴 결과였다 - 반대로
        # required_doc_citation_coverage는 실제로 기권한 문항도 0점으로 그대로
        # 포함시켰다(citation은 "기권했으니 인용도 없다"를 실패로 채점하는 게
        # 타당하지만, fact coverage는 애초에 답변 텍스트에 사실을 넣을 기회 자체가
        # 없었던 경우라 채점 대상에서 제외하는 쪽이 합리적이라고 판단한 것으로
        # 보인다). 여기서도 같은 규칙을 재현한다: 실제 답변이 기권(is_abstention)이면
        # (기대 여부와 무관하게) fact_total을 0으로 둔다.
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

    ours = {
        "abstention_behavior_match": result_df["abstention_match"].mean(),
        "required_doc_citation_coverage": result_df.loc[result_df["citation_total"] > 0, "citation_coverage"].mean(),
        "lexical_required_fact_coverage": result_df.loc[result_df["fact_total"] > 0, "fact_coverage"].mean(),
    }
    n_citation = int((result_df["citation_total"] > 0).sum())
    n_fact = int((result_df["fact_total"] > 0).sum())

    print(f"\n{'=' * 70}\n우리 시스템 (KURE-v1 + HybridIndex + Parent-Child + gpt-5-mini) vs 팀원\n{'=' * 70}")
    print(f"{'지표':<32}{'우리':>10}{'(N)':>6}{'팀원':>10}{'(N)':>6}{'격차':>10}")
    print(f"{'abstention_behavior_match':<32}{ours['abstention_behavior_match']:>10.3f}{len(result_df):>6}"
          f"{TEAMMATE['abstention_behavior_match']:>10.3f}{56:>6}"
          f"{ours['abstention_behavior_match'] - TEAMMATE['abstention_behavior_match']:>+10.3f}")
    print(f"{'required_doc_citation_coverage':<32}{ours['required_doc_citation_coverage']:>10.3f}{n_citation:>6}"
          f"{TEAMMATE['required_doc_citation_coverage']:>10.3f}{54:>6}"
          f"{ours['required_doc_citation_coverage'] - TEAMMATE['required_doc_citation_coverage']:>+10.3f}")
    print(f"{'lexical_required_fact_coverage(참고용)':<32}{ours['lexical_required_fact_coverage']:>10.3f}{n_fact:>6}"
          f"{TEAMMATE['lexical_required_fact_coverage']:>10.3f}{39:>6}"
          f"{ours['lexical_required_fact_coverage'] - TEAMMATE['lexical_required_fact_coverage']:>+10.3f}")

    print(
        "\n주의: correctness/faithfulness/completeness(LLM 판정 필요)는 이 비교에 없다 - "
        "위 세 지표만으로 '우리 답변이 더 낫다'고 결론 내리지 말 것. 특히 abstention_behavior_match는 "
        "source_conflict 1건의 기권 기대 여부를 이 스크립트가 임의로 가정했으니(위 경고 참고), "
        "팀 공유 전 그 가정을 검증할 것."
    )


if __name__ == "__main__":
    main()
