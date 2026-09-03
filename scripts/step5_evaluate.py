"""평가: Golden Test Set(data/golden_set.json)으로 Retrieval 성능(Recall@k, MRR) 측정.

Vector-only / BM25-only / Hybrid 세 가지 방법을 같은 질문 세트로 비교해서
"Baseline보다 얼마나 좋아졌는지"를 수치로 보여주는 게 목적이다(멘토링 노트
전체 방향: "Baseline 62% -> Hybrid+Reranking+Parent-Child로 81%"처럼).

[2026-08-27] golden_set을 CSV에서 JSON으로 바꿨다 - 팀 표준 포맷(번호/난이도/
질문/정답_파일명 배열/비고)에 맞추고, "예산 1억 이상인 사업 전부" 같은 다중
정답 필터형 질문을 "|"로 이어붙인 문자열 대신 진짜 배열로 표현하기 위해서다.
다중 정답 질문에서는 recall@k(정답 중 하나라도 찾으면 True)보다
coverage@k(정답을 몇 % 찾았는지)가 더 정확한 지표라 같이 출력한다
(src/evaluation.py의 evaluate_retrieval 문서화 참고).

개인 목표: 쉬움10 + 중간8 + 어려움7 = 25개 (팀 전체는 4명 x 25 = 100개지만,
지금은 각자 자기 몫부터 채우는 단계). 질문을 추가할 땐 정답_파일명에
정답 문서의 파일명(doc_id)을 정확히 적어야 한다 — output/merged_docs_preview.csv
에서 doc_id 목록을 복사해서 쓰면 오타를 줄일 수 있다.

담당자 컬럼은 지금 당장 안 채워도 된다 — 아직 나 혼자(또는 담당자 미기입)면
개인 25개 기준으로만 보여주고, 나중에 팀원들 파일을 합쳐서 담당자가 2명
이상 채워지면 자동으로 팀 전체/담당자별 현황으로 전환된다.

파이참에서 우클릭 > Run으로 실행하면 된다(인자 불필요).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_processing.chunking import chunk_all, load_chunks, save_chunks  # noqa: E402
from src.evaluation.evaluation import evaluate_retrieval, load_golden_set  # noqa: E402
from src.retrieval.indexing import HybridIndex  # noqa: E402
from src.data_processing.load_metadata import load_clean_metadata  # noqa: E402
from src.data_processing.merge_text import load_merged, merge_all, save_merged  # noqa: E402
from src.config import EVAL_RESULTS_PATH  # noqa: E402

# 개인 목표: 쉬움10 + 중간8 + 어려움7 = 25개. (팀 전체는 이 x 4명 = 100개지만,
# 담당자 컬럼을 아직 안 쓰거나 한 사람만 쓰고 있으면 지금은 개인 25개 기준으로만 보여준다.
# 여러 명이 담당자를 채우기 시작하면 자동으로 팀 전체/담당자별 현황도 같이 보여준다.)
TARGET_PER_PERSON = {"쉬움": 10, "중간": 8, "어려움": 7}
TARGET_PER_PERSON_TOTAL = sum(TARGET_PER_PERSON.values())  # 25


def print_progress(golden_df):
    missing_assignee = golden_df["담당자"].isna() | (golden_df["담당자"].astype(str).str.strip() == "")
    assignees = golden_df.loc[~missing_assignee, "담당자"].unique()
    multi_person_mode = len(assignees) >= 2

    unknown_diff = ~golden_df["난이도"].isin(TARGET_PER_PERSON.keys())
    if unknown_diff.any():
        bad = golden_df.loc[unknown_diff, "난이도"].unique()
        print(f"  ! '난이도' 값이 쉬움/중간/어려움 중 하나가 아닌 행 있음: {list(bad)}\n")

    if not multi_person_mode:
        # 지금은 개인 작업 단계 -> 25개 기준으로만 보여줌 (담당자 안 채워도 경고 안 함)
        print(f"내 Golden Set 진행상황: {len(golden_df)} / {TARGET_PER_PERSON_TOTAL}건")
        for level, target in TARGET_PER_PERSON.items():
            count = (golden_df["난이도"] == level).sum()
            mark = "OK" if count >= target else "부족"
            print(f"  {level}: {count} / {target}  [{mark}]")
        print()
        return

    # 담당자가 2명 이상 채워지기 시작하면 팀 전체 기준으로 전환
    team_size_so_far = len(assignees)
    total_target = TARGET_PER_PERSON_TOTAL * team_size_so_far
    print(f"Golden Set 진행상황: {len(golden_df)} / {total_target}건 (담당자 {team_size_so_far}명 기준, 1인당 25개)")
    if missing_assignee.any():
        print(f"  ! 담당자가 비어있는 질문 {missing_assignee.sum()}건 있음 (팀 전체 집계에서 빠짐)")

    print("\n  난이도별 현황:")
    for level, target_per_person in TARGET_PER_PERSON.items():
        count = (golden_df["난이도"] == level).sum()
        target = target_per_person * team_size_so_far
        mark = "OK" if count >= target else "부족"
        print(f"    {level}: {count} / {target}  [{mark}]")

    print("\n  담당자별 현황 (개인 목표 25개 기준):")
    for name, group in golden_df[~missing_assignee].groupby("담당자"):
        by_level = {lvl: (group["난이도"] == lvl).sum() for lvl in TARGET_PER_PERSON}
        mark = "OK" if len(group) >= TARGET_PER_PERSON_TOTAL else "부족"
        print(f"    {name}: 총 {len(group)}/25  (쉬움{by_level.get('쉬움',0)}/중간{by_level.get('중간',0)}/어려움{by_level.get('어려움',0)})  [{mark}]")
    print()


if __name__ == "__main__":
    golden_df = load_golden_set()
    print_progress(golden_df)
    if len(golden_df) < 10:
        print(
            "  ! 질문이 너무 적어서 아래 Recall/MRR 수치가 통계적으로 의미 있다고 보기 어렵습니다. "
            "위 진행상황표를 보고 data/golden_set.csv를 계속 채워주세요.\n"
        )

    chunks = load_chunks()
    if chunks is None:
        print("[step5] 캐시(output/chunks.pkl) 없음 -> step2~3부터 다시 계산합니다...")
        df = load_merged()
        if df is None:
            df = merge_all(load_clean_metadata())
            save_merged(df)
            # [2026-08-27 수정] step3_chunking.py와 동일한 이유로 재로드 추가 -
            # load_merged()가 하는 정제(예산/마감일 재평가 + "<표>"/"<그림>"
            # 자리표시자 제거)를 캐시 유무와 무관하게 항상 똑같이 적용받기 위함.
            df = load_merged()
        chunks = chunk_all(df)
        save_chunks(chunks)

    index = HybridIndex(chunks)
    print(f"인덱싱 완료: chunk {len(chunks)}개, 임베딩 백엔드={index.embedding_backend.name}\n")

    detail_df, summary_df = evaluate_retrieval(
        index, golden_df, methods=("vector", "bm25", "hybrid"), k_values=(1, 3, 5)
    )

    print("=== 방법별 요약 (평균 Recall@k, MRR) ===")
    print(summary_df.to_string(index=False))

    detail_df.to_csv(EVAL_RESULTS_PATH, index=False, encoding="utf-8-sig")
    print(f"\n질의별 상세 결과 저장: {EVAL_RESULTS_PATH}")

    wrong = detail_df[(detail_df["method"] == "hybrid") & (~detail_df["recall@5"])]
    if len(wrong) > 0:
        print(f"\nhybrid 기준 recall@5에서 놓친 질문 {len(wrong)}건:")
        for _, r in wrong.iterrows():
            print(f"  - {r['query']}  (실제 상위: {r['top_hits']})")

    # 다중 정답 필터형 질문(n_expected > 1)은 recall@5=True여도 정답을 일부만
    # 찾았을 수 있다 - coverage@5(찾은 비율)가 1.0 미만인 것만 따로 보여준다.
    partial = detail_df[
        (detail_df["method"] == "hybrid") & (detail_df["n_expected"] > 1) & (detail_df["coverage@5"] < 1.0)
    ]
    if len(partial) > 0:
        print(f"\nhybrid 기준 다중 정답 질문 중 일부만 찾은 경우 {len(partial)}건 (coverage@5 기준):")
        for _, r in partial.iterrows():
            print(f"  - {r['query']}  (정답 {r['n_expected']}건 중 {r['coverage@5']*r['n_expected']:.0f}건만 찾음, 실제 상위: {r['top_hits']})")
