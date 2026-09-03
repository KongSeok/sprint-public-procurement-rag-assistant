"""golden_testset_verified_111_v6.json의 expected_doc_id(source_documents)가
실제 코퍼스(merged_docs.pkl에 살아있는 doc_id)와 문자열까지 정확히 일치하는지
검증한다.

[배경] step5_evaluate.py를 111개짜리 팀 검증 golden set으로 처음 돌려보니
hybrid 기준 recall@5 단일 미스 5건 중 3건이 "의료기기산업 종합정보시스템"
관련 질문이었는데, 실제 top_hits를 보면 정답과 내용이 100% 같은 문서
(한국보건산업진흥원_의료기기산업 종합정보시스템(정보관리기관) 기능.hwp)가
버젓이 1위로 잡혀 있었다 - 그런데도 recall@5=False였다. 이건 검색 실패가
아니라 golden set의 expected_doc_id 문자열이 실제 코퍼스의 doc_id와 정확히
일치하지 않는다는 신호다.

원인 후보 두 가지:
  1) 근-중복 문서 쌍 문제(8/27 브리핑에서 이미 예고됨) - golden set이 파이프
     라인에서 제외된 중복 문서(예: BioIN_...(2차).hwp, dup_of로
     한국보건산업진흥원_...hwp에 흡수됨)를 정답으로 가리키고 있어서, 살아있는
     생존 문서를 아무리 잘 찾아도 절대 recall@5=True가 될 수 없는 경우.
  2) 단순 파일명 표기 불일치(트렁케이션/오타) - 코퍼스 doc_id 자체가
     Windows 경로 길이 제한 등으로 잘려있는 경우("...기능.hwp"처럼 "개선
     사업"이 잘림)가 있어서, golden set을 손으로 옮겨 적을 때 풀네임으로
     썼다면 글자 하나 안 틀려도 다른 문자열이 되어 매칭이 실패하는 경우.

이 스크립트는 golden set의 모든 expected_doc_id(source_documents에서 문서
확장자만 남긴 것)를 하나씩 코퍼스 doc_id와 대조해서 위 두 원인 중 어느 쪽인지
분류해 보여준다. 코퍼스 자체는 안 건드리고 순수 진단만 한다.

사용법: python scripts/diagnose_golden_set_doc_mismatches.py
"""
import difflib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from src.config import DUPLICATE_EXCLUSIONS_PATH  # noqa: E402
from src.evaluation.evaluation import load_golden_set  # noqa: E402
from src.data_processing.merge_text import load_merged  # noqa: E402

FUZZY_CUTOFF = 0.85  # difflib 유사도 임계값. 이 이상이면 "표기 불일치 후보"로 본다.


def main():
    golden_df = load_golden_set()

    df = load_merged()
    if df is None:
        print("output/merged_docs.pkl 캐시가 없습니다. step3_chunking.py를 먼저 실행하세요.")
        return
    corpus_doc_ids = set(df["doc_id"])

    dup_map = {}  # 제외된 중복 doc_id -> 코퍼스에 살아남은 정본 doc_id
    if DUPLICATE_EXCLUSIONS_PATH.exists():
        dup_df = pd.read_csv(DUPLICATE_EXCLUSIONS_PATH)
        dup_map = dict(zip(dup_df["doc_id"], dup_df["dup_of"]))

    ok, excluded_dup, fuzzy, unresolved = 0, [], [], []

    for _, row in golden_df.iterrows():
        for expected in row["expected_doc_id"]:
            if expected in corpus_doc_ids:
                ok += 1
                continue
            if expected in dup_map and dup_map[expected] in corpus_doc_ids:
                excluded_dup.append((row.get("id"), row["query"], expected, dup_map[expected]))
                continue
            candidates = difflib.get_close_matches(expected, corpus_doc_ids, n=1, cutoff=FUZZY_CUTOFF)
            if candidates:
                ratio = difflib.SequenceMatcher(None, expected, candidates[0]).ratio()
                fuzzy.append((row.get("id"), row["query"], expected, candidates[0], ratio))
            else:
                unresolved.append((row.get("id"), row["query"], expected))

    total = ok + len(excluded_dup) + len(fuzzy) + len(unresolved)
    print(f"golden set의 정답 문서 참조 총 {total}건 중:")
    print(f"  정확히 일치(OK): {ok}")
    print(f"  [원인 1] 파이프라인에서 제외된 근-중복 문서를 가리킴: {len(excluded_dup)}")
    print(f"  [원인 2] 표기 불일치 의심(유사도 {FUZZY_CUTOFF} 이상 후보 있음): {len(fuzzy)}")
    print(f"  원인 불명(유사 후보조차 없음 - 코퍼스에 아예 없는 문서일 수 있음): {len(unresolved)}")

    if excluded_dup:
        print(f"\n=== [원인 1] 근-중복 제외 문서를 가리키는 골든셋 항목 {len(excluded_dup)}건 ===")
        print("(duplicate_exclusions.csv 기준 - golden set의 expected_doc_id를 dup_of 값으로 고치면 해결)")
        for gid, query, expected, survivor in excluded_dup:
            print(f"  [{gid}] {query}")
            print(f"      golden set 정답 : {expected!r}  (제외된 중복)")
            print(f"      코퍼스 생존 문서 : {survivor!r}  <- 이걸로 고쳐야 함")

    if fuzzy:
        print(f"\n=== [원인 2] 표기 불일치 의심 {len(fuzzy)}건 ===")
        for gid, query, expected, candidate, ratio in fuzzy:
            print(f"  [{gid}] {query}")
            print(f"      golden set 정답 : {expected!r}")
            print(f"      코퍼스 최유사 doc_id: {candidate!r}  (유사도 {ratio:.3f})")

    if unresolved:
        print(f"\n=== 원인 불명 {len(unresolved)}건 (직접 확인 필요) ===")
        for gid, query, expected in unresolved:
            print(f"  [{gid}] {query}")
            print(f"      golden set 정답 : {expected!r}  <- 코퍼스에 이 문서도, 비슷한 이름도 없음")


if __name__ == "__main__":
    main()
