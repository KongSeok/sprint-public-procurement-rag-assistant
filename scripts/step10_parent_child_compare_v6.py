"""10단계(신규): Parent-Child retrieval 실험 - "검증된" golden set
(golden_testset_verified_111_v6.json, 팀 취합/검증본, 111건) 기준 재검증.

[배경 - 2026-09-02] step9_parent_child_compare.py는 golden-set-v3-share
(63~79건, `data/golden_set_v3/` 3개 파일)를 기준으로 Parent-Child 효과를
검증했다. 그런데 golden-set-v3-share는 팀이 "검증된 평가셋"으로 합의한
게 아니라, 표/그림/복수정답 등 "어려운 케이스"를 보강하려고 별도로
추가한 세트였다는 게 나중에 확인됐다(레코드마다 enabled:false /
review.status:draft가 박혀 있던 것도 이미 8/27~9/1 브리핑에서 확인된
정황과 일치). 팀이 실제로 "검증됨"으로 합의한 평가셋은 그보다 먼저
만들어진 golden_testset_verified_111_v6.json(111건)이고, 이건 이미
step5_evaluate.py(retrieval)와 step6_generation_baseline.py(generation)가
기본값으로 쓰고 있다(src/config.py의 GOLDEN_SET_PATH가 이 파일을 가리킴).

그래서 이 스크립트는 step9와 완전히 같은 3단계 로직(1단계 retrieval 회귀
확인 / 1.5단계 context fact coverage 비교(API 비용 0원) / 2단계 실제
generation 전수 비교)을, golden-set-v3-share 대신 이 "검증된 111건"
기준으로 그대로 재실행한다. 채점 로직(src/generation.py의
check_required_facts - 쉼표/조사·괄호/날짜 표기 등 이미 고친 버그들 포함)과
Parent-Child 구현(src/indexing.py) 자체는 golden set이 뭐든 동일하게
재사용되므로 새로 만들 게 없다 - 데이터 로딩 부분만 golden_set_v3 대신
load_golden_set()(기본 경로 = v6 111건)을 쓰도록 바꿨다.

golden-set-v3-share(step9) 결과는 무의미한 게 아니라 "어려운 케이스에서는
어떤지"를 보여주는 별도 참고 자료로 계속 쓸 수 있다 - 다만 팀에 보고할
"공식" Parent-Child 효과 수치는 이 스크립트(v6, 검증된 111건) 결과를
우선해야 한다.

v6 golden set에는 golden-set-v3-share의 lane("answer"/"set") 구분이 없다
(전부 단일 포맷 - expected_doc_id가 리스트라 다중 정답 질문도 이미
표현 가능, evaluate_retrieval()의 recall@k/coverage@k가 이를 자동으로
처리하므로 v3처럼 별도의 evaluate_set_retrieval()이 필요 없다).

사전 준비: step6_generation_baseline.py와 동일
    (pip install openai, OPENAI_API_KEY, data/golden_testset_verified_111_v6.json)

사용법: python scripts/step10_parent_child_compare_v6.py
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from src.data_processing.chunking import chunk_all, load_chunks, save_chunks  # noqa: E402
from src.config import EVAL_RESULTS_PATH, OUTPUT_DIR  # noqa: E402
from src.evaluation.evaluation import evaluate_context_fact_coverage, evaluate_retrieval, load_golden_set  # noqa: E402
from src.generation.generation import (  # noqa: E402
    build_context,
    check_required_facts,
    compute_abstention_match,
    compute_citation_coverage,
    generate_answer,
)
from src.retrieval.indexing import HybridIndex  # noqa: E402
from src.data_processing.load_metadata import load_clean_metadata  # noqa: E402
from src.data_processing.merge_text import load_merged, merge_all, save_merged  # noqa: E402

TOP_K = 5  # step5/step6과 동일하게 맞춤
# LIMIT을 쓰면 비용은 줄지만 표본이 전체를 대표하지 못할 위험이 있다 -
# "parent-child 손익" 결론용 헤드라인 숫자는 LIMIT=None(전체)으로 낸 결과를 쓸 것.
LIMIT = None

COVERAGE_RESULTS_PATH = OUTPUT_DIR / "context_fact_coverage_parent_child_compare_v6.csv"
GENERATION_RESULTS_PATH = OUTPUT_DIR / "generation_eval_parent_child_compare_v6.csv"


def _gradable_df(golden_df: pd.DataFrame) -> pd.DataFrame:
    """채점 가능한(정답 문서 + required_fact_groups가 다 있는) 행만 추려서
    반환한다 - 1.5단계/2단계가 공통으로 쓰는 필터라 함수로 뺐다.
    (step6과 동일하게 answerability=='answerable'인 것만 대상으로 함 - 컬럼이
    없으면 전부 대상)"""
    df = golden_df.copy()
    if "answerability" in df.columns:
        df = df[df["answerability"].fillna("answerable") == "answerable"].reset_index(drop=True)
    df = df[df["expected_doc_id"].apply(lambda v: isinstance(v, list) and len(v) > 0)].reset_index(drop=True)
    if "required_facts" in df.columns and "required_fact_groups" not in df.columns:
        df = df.rename(columns={"required_facts": "required_fact_groups"})
    if "required_fact_groups" not in df.columns:
        raise ValueError(
            "golden set에 required_facts/required_fact_groups 컬럼이 없습니다 - "
            "golden_testset_verified_111_v6.json이 맞는 파일인지 확인하세요."
        )
    df = df[df["required_fact_groups"].apply(lambda v: isinstance(v, list) and len(v) > 0)].reset_index(drop=True)
    return df


def _step1_retrieval_regression(index: HybridIndex, golden_df: pd.DataFrame) -> None:
    print("=" * 70)
    print("1단계: Retrieval 회귀/변화 확인 (parent chunk를 검색 후보에서 제외한 효과) - 검증된 111건 기준")
    print("=" * 70)

    df = golden_df[golden_df["expected_doc_id"].apply(lambda v: isinstance(v, list) and len(v) > 0)].reset_index(drop=True)

    _, summary = evaluate_retrieval(index, df, methods=("hybrid",), k_values=(1, 3, 5))
    print(f"\n[{len(df)}건] hybrid 결과(patch 후):")
    print(summary.to_string(index=False))
    if EVAL_RESULTS_PATH.exists():
        prev = pd.read_csv(EVAL_RESULTS_PATH)
        if "method" in prev.columns:
            prev_hybrid = prev[prev["method"] == "hybrid"]
        else:
            prev_hybrid = prev
        recall5_col = "recall@5" if "recall@5" in prev_hybrid.columns else None
        if recall5_col and len(prev_hybrid) > 0:
            prev_recall5 = prev_hybrid[recall5_col].mean()
            new_recall5 = summary.loc[summary["method"] == "hybrid", "recall@5"].iloc[0]
            print(f"  -> recall@5: 이전({EVAL_RESULTS_PATH.name}) {prev_recall5:.3f} -> "
                  f"패치 후 {new_recall5:.3f} (델타 {new_recall5 - prev_recall5:+.3f})")
    else:
        print(f"  ({EVAL_RESULTS_PATH.name} 없음 - 이전 결과와 자동 비교는 건너뜀)")
    print()


def _step1_5_context_fact_coverage(index: HybridIndex, golden_df: pd.DataFrame) -> None:
    print("=" * 70)
    print("1.5단계: Context Fact Coverage 비교 (API 호출 없음, 검증된 111건 기준)")
    print("=" * 70)

    df = _gradable_df(golden_df)

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

    COVERAGE_RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(COVERAGE_RESULTS_PATH, index=False, encoding="utf-8-sig")
    print(f"\n질의별 상세 결과 저장: {COVERAGE_RESULTS_PATH}\n")


def _grade(client, query: str, hits, required_facts, required_doc_ids, expected_should_abstain: bool) -> dict:
    """[2026-09-02 저녁 갱신] golden-set-v3-share 평가 계약을 읽고 나서,
    lexical fact 매칭(`pass`) 하나만으로 "맞는 답변"이라고 부르는 게 계약
    §8.1/8.7이 명시적으로 금지하는 방식이라는 걸 확인했다(diagnostic-only,
    pass/fail 판정에 쓰지 말 것). LLM 판정기가 아직 우리 쪽에 연결 안 됐으니
    correctness/faithfulness까지는 아직 못 재지만, 팀원 쪽이 코드로도 잴 수
    있다고 보여준 두 축 - citation_coverage(답변이 실제로 필요한 문서를
    인용했는지)와 abstention_match(기권 판단이 골든셋 기대와 맞는지) - 는
    여기서 같이 계산해서, `pass`(diagnostic) 하나로 손익을 판단하지 않고
    여러 축을 같이 보게 했다."""
    context = build_context(hits)
    answer = generate_answer(client, query, context)
    if answer is None:
        return {
            "answer": None, "matched": None, "total": None, "coverage": None, "pass": False,
            "citation_matched": None, "citation_total": None, "citation_coverage": None,
            "abstention_match": compute_abstention_match(None, expected_should_abstain),
        }
    matched, total = check_required_facts(answer, required_facts)
    citation_matched, citation_total = compute_citation_coverage(answer, required_doc_ids)
    return {
        "answer": answer, "matched": matched, "total": total,
        "coverage": (matched / total) if total else None,
        "pass": (matched == total) if total else None,  # diagnostic-only - 계약 §8.7 참고
        "citation_matched": citation_matched, "citation_total": citation_total,
        "citation_coverage": (citation_matched / citation_total) if citation_total else None,
        "abstention_match": compute_abstention_match(answer, expected_should_abstain),
    }


def _has_expandable_hit(index: HybridIndex, hits) -> bool:
    """검색 결과 안에 parent-child 확장이 실제로 적용될 chunk(strategy=="child")가
    하나라도 있는지 확인한다 - 없으면 expand_to_parent=True로 다시 검색해도 결과가
    baseline과 100% 동일하므로 재호출을 생략해 비용만 아낀다(step9와 동일 로직)."""
    for h in hits:
        chunk = index.by_id.get(h.chunk_id)
        if chunk is not None and chunk.strategy == "child":
            return True
    return False


def _step2_generation_compare(client, index: HybridIndex, golden_df: pd.DataFrame) -> None:
    print("=" * 70)
    print("2단계: Generation 전수 비교 (baseline vs parent-child context) - 검증된 111건 기준")
    print("=" * 70)

    df = _gradable_df(golden_df)

    if LIMIT:
        print(f"[step10] !! LIMIT={LIMIT}로 일부만 실행합니다 - 전체를 대표하지 않을 수 있어, "
              "\"parent-child 손익\" 결론용으로는 LIMIT 없이 돌린 결과를 우선하세요.")
        df = df.head(LIMIT)

    rows = []
    n = len(df)
    n_applicable = 0
    for i, (_, row) in enumerate(df.iterrows(), start=1):
        query = row["query"]
        required_facts = row["required_fact_groups"]
        required_doc_ids = row["expected_doc_id"]
        expected = set(required_doc_ids)
        # v6 golden set은 "answerability" 컬럼으로 기권 기대를 표시한다(step6과
        # 동일 규칙) - 컬럼이 없거나 값이 없으면 "답변 가능"으로 취급.
        expected_should_abstain = str(row.get("answerability", "answerable")) != "answerable"

        base_hits = index.hybrid_search(query, k=TOP_K, expand_to_parent=False)
        retrieved_set = {h.doc_id for h in base_hits}
        retrieval_recall = (len(retrieved_set & expected) / len(expected)) if expected else None
        base = _grade(client, query, base_hits, required_facts, required_doc_ids, expected_should_abstain)

        applicable = _has_expandable_hit(index, base_hits)
        if applicable:
            n_applicable += 1
            pc_hits = index.hybrid_search(query, k=TOP_K, expand_to_parent=True)
            pc = _grade(client, query, pc_hits, required_facts, required_doc_ids, expected_should_abstain)
        else:
            pc = dict(base)

        tag = "적용됨" if applicable else "해당없음(recursive만)"
        print(f"[{i}/{n}] ({tag}) {str(query)[:40]}... base_pass={base['pass']} pc_pass={pc['pass']} "
              f"base_citation={base['citation_coverage']} pc_citation={pc['citation_coverage']}")

        rows.append({
            "id": row.get("id"), "query": query, "pc_applicable": applicable,
            "retrieval_recall": retrieval_recall, "expected_should_abstain": expected_should_abstain,
            "base_answer": base["answer"], "base_facts_matched": base["matched"],
            "base_facts_total": base["total"], "base_pass": base["pass"],
            "base_citation_coverage": base["citation_coverage"], "base_abstention_match": base["abstention_match"],
            "pc_answer": pc["answer"], "pc_facts_matched": pc["matched"],
            "pc_facts_total": pc["total"], "pc_pass": pc["pass"],
            "pc_citation_coverage": pc["citation_coverage"], "pc_abstention_match": pc["abstention_match"],
        })
        time.sleep(0.2)

    result_df = pd.DataFrame(rows)
    GENERATION_RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    result_df.to_csv(GENERATION_RESULTS_PATH, index=False, encoding="utf-8-sig")
    print(f"\n질의별 상세 결과 저장: {GENERATION_RESULTS_PATH}")

    print(f"\n=== 전체 {len(result_df)}건 (parent-child 실제 적용 가능 {n_applicable}건, "
          f"나머지 {len(result_df) - n_applicable}건은 baseline과 동일 - 재호출 생략) ===")
    print("[주의] lexical fact pass율은 diagnostic-only입니다 - 동의어/자연스러운 표현 차이를 "
          "놓칠 수 있어(golden-set-v3-share 계약과 동일한 이유) 정답성의 최종 판정으로 쓰지 마세요. "
          "citation coverage/abstention match는 결정론적으로 잰 별도 축입니다.")
    base_rate = result_df["base_pass"].fillna(False).mean()
    pc_rate = result_df["pc_pass"].fillna(False).mean()
    print(f"[diagnostic] lexical fact pass율: baseline {base_rate:.3f} -> parent-child {pc_rate:.3f} "
          f"(델타 {pc_rate - base_rate:+.3f})")

    base_citation = result_df["base_citation_coverage"].mean()
    pc_citation = result_df["pc_citation_coverage"].mean()
    print(f"필수 문서 인용 커버리지: baseline {base_citation:.3f} -> parent-child {pc_citation:.3f} "
          f"(델타 {pc_citation - base_citation:+.3f})")

    base_abstention = result_df["base_abstention_match"].mean()
    pc_abstention = result_df["pc_abstention_match"].mean()
    print(f"기권 행동 일치율: baseline {base_abstention:.3f} -> parent-child {pc_abstention:.3f} "
          f"(델타 {pc_abstention - base_abstention:+.3f})")

    applicable_df = result_df[result_df["pc_applicable"]]
    flips_up = applicable_df[(applicable_df["base_pass"] != True) & (applicable_df["pc_pass"] == True)]  # noqa: E712
    flips_down = applicable_df[(applicable_df["base_pass"] == True) & (applicable_df["pc_pass"] != True)]  # noqa: E712
    print(f"\n(적용 가능 {len(applicable_df)}건 안에서) Fail -> Pass 개선: {len(flips_up)}건 {flips_up['id'].tolist()}")
    print(f"(적용 가능 {len(applicable_df)}건 안에서) Pass -> Fail 역행: {len(flips_down)}건 {flips_down['id'].tolist()}")
    if len(flips_down):
        print("  -> 역행 건은 parent context가 오히려 노이즈를 늘렸을 가능성 - "
              f"{GENERATION_RESULTS_PATH.name}에서 base_answer/pc_answer를 직접 비교해볼 것.")


def main():
    golden_df = load_golden_set()  # 기본 경로 = data/golden_testset_verified_111_v6.json
    print(f"[step10] golden set 로드: {len(golden_df)}건 (검증된 111건 기준)\n")

    chunks = load_chunks()
    if chunks is None:
        print("[step10] 캐시(output/chunks.pkl) 없음 -> step2~3부터 다시 계산합니다...")
        df = load_merged()
        if df is None:
            df = merge_all(load_clean_metadata())
            save_merged(df)
            df = load_merged()
        chunks = chunk_all(df)
        save_chunks(chunks)

    index = HybridIndex(chunks)
    print(f"인덱싱 완료: chunk {len(chunks)}개, 임베딩 백엔드={index.embedding_backend.name}\n")

    _step1_retrieval_regression(index, golden_df)
    _step1_5_context_fact_coverage(index, golden_df)

    if not os.environ.get("OPENAI_API_KEY"):
        print("=" * 70)
        print("OPENAI_API_KEY가 없어 2단계(실제 API 생성 비교)는 건너뜁니다.")
        print("위 1.5단계(API 비용 0원) 결과만으로 충분히 판단되시면 여기서 멈추셔도 됩니다 - ")
        print("2단계까지 보시려면 OPENAI_API_KEY를 설정한 뒤 다시 실행하세요.")
        print("=" * 70)
        return

    from openai import OpenAI

    client = OpenAI()
    _step2_generation_compare(client, index, golden_df)


if __name__ == "__main__":
    main()
