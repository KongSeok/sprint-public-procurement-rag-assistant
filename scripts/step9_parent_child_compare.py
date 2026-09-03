"""9단계(신규): Parent-Child retrieval 실험 - src/indexing.py에 새로 구현한
parent-child 검색(HybridIndex가 검색 후보에서 parent chunk를 빼고, child가
검색되면 expand_to_parent=True로 그 child가 속한 parent 전체 텍스트를
context로 확장하는 기능)이 실제로 도움이 되는지 세 단계로 확인한다.

[배경] 9/1 브리핑에서 발견된 문제: parent_child_chunk()는 parent/child chunk를
같은 리스트에 담아 반환하는데, HybridIndex가 이 둘을 구분 없이 그대로 검색
인덱스(Vector+BM25)에 다 넣고 있었다 - "검색은 작게, context는 크게"
(멘토링 노트 6번)가 chunking 단계에서는 준비돼 있었지만 indexing 단계에서
실제로 지켜지지 않고 있었다. src/indexing.py를 고쳐서 (1) 검색 후보에서
parent chunk를 제외하고(2026-09-02), (2) expand_to_parent 옵션으로 검색된
child를 parent 전체 텍스트로 context 확장할 수 있게 했다. 이 스크립트는
그 두 가지 변화의 효과를 각각 확인한다.

1단계 - Retrieval 회귀/변화 확인:
    parent chunk를 검색 후보에서 뺀 것 자체가 recall/precision/MRR에 영향을
    주는지 확인한다(순수 랭킹 변화라 여기서 진짜 차이가 날 수 있다 -
    expand_to_parent는 doc_id 기반 채점에는 영향이 없으므로 여기선 켜지 않는다).
    output/eval_results_v3_answer.csv / eval_results_v3_set.csv에 저장된 이전
    결과와 자동으로 비교해서 델타를 보여준다(파일이 없으면 이번 결과만 출력).

1.5단계 - Context Fact Coverage 비교(API 호출 없음) [2026-09-02 추가]:
    1단계(doc_id 단위 recall)는 "정답 문서를 찾았는지"만 보고 "찾은 chunk에
    실제로 쓸모있는 내용이 들어있는지"는 못 본다는 한계가 있다(8/27에 지적된
    문제 - 표지/목차 chunk만 걸려도 hit으로 카운트됨). 그렇다고 chunk 단위
    정답을 golden set에 새로 라벨링하는 건 손이 많이 든다. 그 대신 이미
    generation 채점에 쓰던 required_fact_groups를 재사용해서, LLM이 생성한
    답변이 아니라 검색 직후의 context 텍스트 자체에 필요한 사실이 들어있는지를
    확인한다(src/evaluation.py의 evaluate_context_fact_coverage()). LLM 호출이
    전혀 없어 API 비용이 0이고 매번 재실행해도 100% 같은 결과가 나온다
    (결정론적) - baseline과 parent-child의 context 완전성 차이를 비용/노이즈
    걱정 없이 answer lane 전체로 바로 비교할 수 있다. 이 결과가 이미 뚜렷하면
    아래 2단계(실제 API 비용이 드는 generation 비교)는 신호 확인용으로만
    가볍게 돌려도 충분할 수 있다.

2단계 - Generation 전수 비교(baseline vs parent-child):
    [2026-09-02 재설계] 처음엔 "retrieval은 맞았는데 baseline이 실패한" 문항만
    골라 parent-child를 다시 돌리는 TARGET_SUBSET_ONLY 방식이었는데, 이러면
    "Pass였던 문항이 parent-child로 오히려 나빠지는 역행"을 원천적으로 못
    본다는 문제가 지적됐다(baseline이 이미 Pass면 애초에 parent-child를
    재호출조차 안 하니까). LIMIT으로 앞부분만 자르는 것도 표본이
    answer lane 전체를 대표 못 할 위험이 있다 - parent-child는 table_heavy
    문서에만 적용되는데, 앞쪽 N개가 우연히 표 없는 문서 위주면 효과가 있어도
    과소평가되고 표 있는 문서 위주면 과대평가된다.

    그래서 이제는 answer lane 전체에 대해 baseline을 채점하고, 검색된 chunk
    중 하나라도 strategy=="child"(parent-child 청킹이 적용된 문서)가 있는
    문항만 parent-child로 실제로 다시 생성한다 - 전부 recursive 전략이면
    expand_to_parent=True로 다시 검색해도 text가 하나도 안 바뀔 게 구조적으로
    확실하므로(정의상 baseline과 100% 동일한 context), 그 경우는 baseline
    결과를 그대로 이어받고 재호출을 생략해 비용만 아낀다. "표본을 편향되게
    줄이는 것"과 "결과가 뻔한 호출을 생략하는 것"은 다르다 - 이 스크립트는
    후자만 한다. 그 결과 Fail->Pass 개선과 Pass->Fail 역행을 둘 다 정직하게
    집계할 수 있다("손익"을 보려면 이득/손해 둘 다 봐야 함).

    generation 자체가 매 호출마다 100% 같은 문장을 내지 않는다는 걸 이번
    세션에서 여러 번 확인했으므로(재호출 비결정성), baseline과 parent-child를
    "같은 실행 안에서" 순서대로 비교해 최소한 "그날그날 모델 컨디션 차이"라는
    교란 요인은 없앤다.

    비용을 더 줄이고 싶으면 LIMIT을 쓸 수는 있지만, 그러면 위에서 설명한
    표본 편향 위험이 다시 생긴다는 걸 감안할 것 - "parent-child 손익"을
    포트폴리오용 헤드라인 숫자로 쓸 거라면 LIMIT 없이 전체를 돌린 결과를
    써야 한다.

사전 준비: step8_generation_golden_v3.py와 동일
    (pip install openai, OPENAI_API_KEY, data/golden_set_v3/ 3개 파일)

사용법: python scripts/step9_parent_child_compare.py
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from src.data_processing.chunking import chunk_all, load_chunks, save_chunks  # noqa: E402
from src.config import OUTPUT_DIR  # noqa: E402
from src.evaluation.evaluation import (  # noqa: E402
    evaluate_context_fact_coverage,
    evaluate_retrieval,
    evaluate_set_retrieval,
)
from src.generation.generation import build_context, check_required_facts, generate_answer  # noqa: E402
from src.evaluation.golden_set_v3 import load_golden_set_v3  # noqa: E402
from src.retrieval.indexing import HybridIndex  # noqa: E402
from src.data_processing.load_metadata import load_clean_metadata  # noqa: E402
from src.data_processing.merge_text import load_merged, merge_all, save_merged  # noqa: E402

TOP_K = 5  # step8과 동일하게 맞춤(answer lane 기준)
# LIMIT을 쓰면 비용은 줄지만 표본이 answer lane 전체를 대표하지 못할 위험이 있다
# (모듈 docstring 2단계 설명 참고) - "parent-child 손익" 결론용 헤드라인 숫자는
# LIMIT=None(전체)으로 낸 결과를 쓸 것. 빠른 스모크 테스트용으로만 정수로 바꿀 것.
LIMIT = None

PREV_ANSWER_PATH = OUTPUT_DIR / "eval_results_v3_answer.csv"  # 이전 결과(있으면 델타 비교)
PREV_SET_PATH = OUTPUT_DIR / "eval_results_v3_set.csv"
COMPARE_RESULTS_PATH = OUTPUT_DIR / "generation_eval_v3_parent_child_compare.csv"


def _step1_retrieval_regression(index: HybridIndex, golden_v3: pd.DataFrame) -> None:
    print("=" * 70)
    print("1단계: Retrieval 회귀/변화 확인 (parent chunk를 검색 후보에서 제외한 효과)")
    print("=" * 70)

    answer_df = golden_v3[golden_v3["lane"] == "answer"].reset_index(drop=True)
    answer_df = answer_df[answer_df["expected_doc_id"].apply(len) > 0].reset_index(drop=True)
    set_df = golden_v3[golden_v3["lane"] == "set"].reset_index(drop=True)
    set_df = set_df[set_df["expected_doc_id"].apply(len) > 0].reset_index(drop=True)

    _, answer_summary = evaluate_retrieval(index, answer_df, methods=("hybrid",), k_values=(1, 3, 5))
    print(f"\n[answer/visual lane, {len(answer_df)}건] hybrid 결과(patch 후):")
    print(answer_summary.to_string(index=False))
    if PREV_ANSWER_PATH.exists():
        prev = pd.read_csv(PREV_ANSWER_PATH)
        prev_hybrid = prev[prev["method"] == "hybrid"]
        if len(prev_hybrid) > 0:
            prev_recall5 = prev_hybrid["recall@5"].mean()
            new_recall5 = answer_summary.loc[answer_summary["method"] == "hybrid", "recall@5"].iloc[0]
            print(f"  -> recall@5: 패치 전 {prev_recall5:.3f} -> 패치 후 {new_recall5:.3f} "
                  f"(델타 {new_recall5 - prev_recall5:+.3f})")
    else:
        print(f"  ({PREV_ANSWER_PATH.name} 없음 - 이전 결과와 자동 비교는 건너뜀)")

    _, set_summary = evaluate_set_retrieval(index, set_df, methods=("hybrid",))
    print(f"\n[set lane, {len(set_df)}건] hybrid 결과(patch 후):")
    print(set_summary.to_string(index=False))
    if PREV_SET_PATH.exists():
        prev = pd.read_csv(PREV_SET_PATH)
        prev_hybrid = prev[prev["method"] == "hybrid"]
        if len(prev_hybrid) > 0:
            prev_f1 = prev_hybrid["f1"].mean()
            new_f1 = set_summary.loc[set_summary["method"] == "hybrid", "f1"].iloc[0]
            print(f"  -> f1: 패치 전 {prev_f1:.3f} -> 패치 후 {new_f1:.3f} (델타 {new_f1 - prev_f1:+.3f})")
    else:
        print(f"  ({PREV_SET_PATH.name} 없음 - 이전 결과와 자동 비교는 건너뜀)")
    print()


def _answer_lane_df(golden_v3: pd.DataFrame) -> pd.DataFrame:
    """answer lane 중 채점 가능한(required_fact_groups가 있는) 행만 추려서
    반환한다 - 1.5단계/2단계가 공통으로 쓰는 필터라 함수로 뺐다."""
    df = golden_v3[golden_v3["lane"] == "answer"].reset_index(drop=True)
    df = df[~df["decision"].isin(["abstain", "source_conflict"])].reset_index(drop=True)
    df = df[df["expected_doc_id"].apply(len) > 0].reset_index(drop=True)
    df = df[df["required_fact_groups"].apply(lambda v: isinstance(v, list) and len(v) > 0)].reset_index(drop=True)
    return df


def _step1_5_context_fact_coverage(index: HybridIndex, golden_v3: pd.DataFrame) -> None:
    print("=" * 70)
    print("1.5단계: Context Fact Coverage 비교 (API 호출 없음 - baseline vs parent-child)")
    print("=" * 70)
    print("검색 직후 context 텍스트 자체에 답에 필요한 사실이 들어있는지만 확인 - LLM 생성 없이,")
    print("결정론적으로(재실행해도 항상 같은 결과) parent-child의 효과를 먼저 가늠한다.\n")

    df = _answer_lane_df(golden_v3)

    base_detail, _ = evaluate_context_fact_coverage(index, df, methods=("hybrid",), k=TOP_K, expand_to_parent=False)
    pc_detail, _ = evaluate_context_fact_coverage(index, df, methods=("hybrid",), k=TOP_K, expand_to_parent=True)

    merged = base_detail[["id", "query", "fact_coverage", "fully_covered"]].merge(
        pc_detail[["id", "fact_coverage", "fully_covered"]], on="id", suffixes=("_base", "_pc"),
    )

    n = len(merged)
    base_rate = merged["fully_covered_base"].mean()
    pc_rate = merged["fully_covered_pc"].mean()
    base_cov = merged["fact_coverage_base"].mean()
    pc_cov = merged["fact_coverage_pc"].mean()
    print(f"전체 {n}건 (API 비용 0원, 몇 번을 재실행해도 항상 같은 숫자)")
    print(f"완전 커버율(context 안에 필요한 사실이 다 있었는지): baseline {base_rate:.3f} -> "
          f"parent-child {pc_rate:.3f} (델타 {pc_rate - base_rate:+.3f})")
    print(f"평균 fact coverage: baseline {base_cov:.3f} -> parent-child {pc_cov:.3f} "
          f"(델타 {pc_cov - base_cov:+.3f})")

    flips_up = merged[(merged["fully_covered_base"] != True) & (merged["fully_covered_pc"] == True)]  # noqa: E712
    flips_down = merged[(merged["fully_covered_base"] == True) & (merged["fully_covered_pc"] != True)]  # noqa: E712
    print(f"\ncontext 완전 커버 개선(부족 -> 충분): {len(flips_up)}건 {flips_up['id'].tolist()}")
    print(f"context 완전 커버 역행(충분 -> 부족): {len(flips_down)}건 {flips_down['id'].tolist()}")
    print("\n-> 이 결과가 이미 뚜렷하면(개선 다수, 역행 거의 없음) 2단계(실제 API 생성 비교)는")
    print("   신호 재확인용으로만 가볍게 돌려도 충분할 수 있습니다. 애매하면 2단계로 넘어가세요.\n")

    path = OUTPUT_DIR / "context_fact_coverage_parent_child_compare.csv"
    merged.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"질의별 상세 결과 저장: {path}\n")


def _grade(client, query: str, hits, required_facts) -> dict:
    context = build_context(hits)
    answer = generate_answer(client, query, context)
    if answer is None:
        return {"answer": None, "matched": None, "total": None, "coverage": None, "pass": False}
    matched, total = check_required_facts(answer, required_facts)
    return {
        "answer": answer, "matched": matched, "total": total,
        "coverage": (matched / total) if total else None,
        "pass": (matched == total) if total else None,
    }


def _has_expandable_hit(index: HybridIndex, hits) -> bool:
    """이 검색 결과 안에 parent-child 확장이 실제로 적용될 chunk(strategy=="child")가
    하나라도 있는지 확인한다. 하나도 없으면(전부 recursive strategy - parent-child
    청킹이 안 된 일반 문서) expand_to_parent=True로 다시 검색해도 text가 하나도
    안 바뀌므로 - 정의상 baseline과 100% 동일한 context가 나온다 - generation을
    또 호출하는 건 순수 비용 낭비다(신호는 전혀 안 나옴)."""
    for h in hits:
        chunk = index.by_id.get(h.chunk_id)
        if chunk is not None and chunk.strategy == "child":
            return True
    return False


def _step2_generation_compare(client, index: HybridIndex, golden_v3: pd.DataFrame) -> None:
    print("=" * 70)
    print("2단계: Generation 전수 비교 (baseline vs parent-child context)")
    print("=" * 70)

    df = _answer_lane_df(golden_v3)

    if LIMIT:
        print(f"[step9] !! LIMIT={LIMIT}로 일부만 실행합니다 - answer lane 전체를 대표하지 "
              "않을 수 있어(parent-child가 적용되는 table_heavy 문서 비율이 앞부분에 몰려있거나 "
              "없을 수 있음), \"parent-child 손익\" 결론용으로는 LIMIT 없이 돌린 결과를 우선하세요.")
        df = df.head(LIMIT)

    rows = []
    n = len(df)
    n_applicable = 0
    for i, (_, row) in enumerate(df.iterrows(), start=1):
        query = row["query"]
        required_facts = row["required_fact_groups"]
        expected = set(row["expected_doc_id"])

        base_hits = index.hybrid_search(query, k=TOP_K, expand_to_parent=False)
        retrieved_set = {h.doc_id for h in base_hits}
        retrieval_recall = (len(retrieved_set & expected) / len(expected)) if expected else None
        base = _grade(client, query, base_hits, required_facts)

        applicable = _has_expandable_hit(index, base_hits)
        if applicable:
            n_applicable += 1
            pc_hits = index.hybrid_search(query, k=TOP_K, expand_to_parent=True)
            pc = _grade(client, query, pc_hits, required_facts)
        else:
            # parent-child가 구조적으로 no-op인 경우 - baseline 결과를 그대로 이어받는다.
            pc = dict(base)

        tag = "적용됨" if applicable else "해당없음(recursive만)"
        print(f"[{i}/{n}] ({tag}) {query[:40]}... base_pass={base['pass']} pc_pass={pc['pass']}")

        rows.append({
            "id": row.get("id"), "query": query, "pc_applicable": applicable,
            "retrieval_recall": retrieval_recall,
            "base_answer": base["answer"], "base_facts_matched": base["matched"],
            "base_facts_total": base["total"], "base_pass": base["pass"],
            "pc_answer": pc["answer"], "pc_facts_matched": pc["matched"],
            "pc_facts_total": pc["total"], "pc_pass": pc["pass"],
        })
        time.sleep(0.2)

    result_df = pd.DataFrame(rows)
    result_df.to_csv(COMPARE_RESULTS_PATH, index=False, encoding="utf-8-sig")
    print(f"\n질의별 상세 결과 저장: {COMPARE_RESULTS_PATH}")

    print(f"\n=== 전체 {len(result_df)}건 (parent-child 실제 적용 가능 {n_applicable}건, "
          f"나머지 {len(result_df) - n_applicable}건은 baseline과 동일 - 재호출 생략) ===")
    base_rate = result_df["base_pass"].fillna(False).mean()
    pc_rate = result_df["pc_pass"].fillna(False).mean()
    print(f"baseline pass율: {base_rate:.3f} -> parent-child pass율: {pc_rate:.3f} "
          f"(델타 {pc_rate - base_rate:+.3f}) <- 전체 모집단 기준, 이게 진짜 순손익")

    applicable_df = result_df[result_df["pc_applicable"]]
    flips_up = applicable_df[(applicable_df["base_pass"] != True) & (applicable_df["pc_pass"] == True)]  # noqa: E712
    flips_down = applicable_df[(applicable_df["base_pass"] == True) & (applicable_df["pc_pass"] != True)]  # noqa: E712
    print(f"\n(적용 가능 {len(applicable_df)}건 안에서) Fail -> Pass 개선: {len(flips_up)}건 {flips_up['id'].tolist()}")
    print(f"(적용 가능 {len(applicable_df)}건 안에서) Pass -> Fail 역행: {len(flips_down)}건 {flips_down['id'].tolist()}")
    if len(flips_down):
        print("  -> 역행 건은 parent context가 오히려 노이즈를 늘렸을 가능성 - "
              f"{COMPARE_RESULTS_PATH.name}에서 base_answer/pc_answer를 직접 비교해볼 것.")


def main():
    # [2026-09-02] 1단계/1.5단계는 LLM 생성이 전혀 없어(임베딩 백엔드는 로컬
    # KURE-v1) OPENAI_API_KEY 없이도 끝까지 돌아간다 - 그래서 이 체크를 맨 위가
    # 아니라 2단계(실제 generation 비교) 직전으로 옮겼다. 키가 없으면 2단계만
    # 건너뛰고 나머지는 정상 실행된다.
    golden_v3 = load_golden_set_v3()

    chunks = load_chunks()
    if chunks is None:
        print("[step9] 캐시(output/chunks.pkl) 없음 -> step2~3부터 다시 계산합니다...")
        df = load_merged()
        if df is None:
            df = merge_all(load_clean_metadata())
            save_merged(df)
            df = load_merged()
        chunks = chunk_all(df)
        save_chunks(chunks)

    index = HybridIndex(chunks)
    print(f"인덱싱 완료: chunk {len(chunks)}개, 임베딩 백엔드={index.embedding_backend.name}\n")

    _step1_retrieval_regression(index, golden_v3)
    _step1_5_context_fact_coverage(index, golden_v3)

    if not os.environ.get("OPENAI_API_KEY"):
        print("=" * 70)
        print("OPENAI_API_KEY가 없어 2단계(실제 API 생성 비교)는 건너뜁니다.")
        print("위 1.5단계(API 비용 0원) 결과만으로 충분히 판단되시면 여기서 멈추셔도 됩니다 - ")
        print("2단계까지 보시려면 OPENAI_API_KEY를 설정한 뒤 다시 실행하세요.")
        print("=" * 70)
        return

    from openai import OpenAI

    client = OpenAI()
    _step2_generation_compare(client, index, golden_v3)


if __name__ == "__main__":
    main()
