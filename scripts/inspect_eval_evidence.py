"""근거 청크 확인: golden set 질문마다 실제로 검색된 chunk의 본문을 그대로
보여줘서, recall@k가 "정답 문서"만 맞혔는지 아니면 진짜 "정답 근거"를
찾아왔는지 눈으로 확인하기 위한 진단 스크립트.

[2026-08-27] evaluate_retrieval()은 문서(doc_id) 단위로만 채점한다 - "그
문서의 어떤 chunk라도 찾아오면 맞다"는 기준(src/evaluation.py 모듈
docstring 참고). 그래서 recall@1이 0.96~1.0으로 세 방법(BM25/Vector/
Hybrid) 다 비슷하게 높게 나왔을 때, 진짜 검색이 잘 되는 건지 아니면
정답 문서의 엉뚱한 chunk(표지, 목차 등)가 우연히 걸려서 doc_id만 맞은
건지 구분이 안 됐다. 이 스크립트는 그 구분을 위해, golden set 25개 질문
전부에 대해 hybrid_search 상위 TOP_K개 chunk의 실제 본문을 그대로 보여주고
CSV로도 저장한다 - 그 본문 안에 질문의 진짜 답(예산 숫자, 마감일 날짜,
조항 내용 등)이 실제로 들어있는지는 사람이 눈으로 확인해야 한다(golden
set에 "정답 chunk"까지는 아직 없어서 자동 판정은 못 함).

[2026-08-28] TOP_K를 3 -> 5로 올림. 1차 실행(top3) 결과 19/20/23번
질문(하자보수보증금율, 평가 배점 비율, 하도급 허용여부)은 상위 3개
안에서 실제 근거를 못 찾았는데, step5_evaluate.py의 recall@5 지표와
비교하려면 같은 k=5까지는 봐야 "진짜 놓친 건지" 판단할 수 있어서
맞춰줬다. top4~5위에서 근거가 나오면 "Retrieval이 못 찾은 게 아니라
단지 순위가 조금 밀린 것"이라는 뜻이고, 5위 안에도 없으면 진짜
Retrieval이 약한 지점이라는 뜻이다.

파이참에서 우클릭 > Run으로 실행하면 된다(인자 불필요). HybridIndex는
매번 새로 만드는 구조라 임베딩 계산 시간이 다시 걸린다(chunk 자체는
캐시를 그대로 씀).
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_processing.chunking import chunk_all, load_chunks, save_chunks  # noqa: E402
from src.config import OUTPUT_DIR  # noqa: E402
from src.evaluation.evaluation import _expected_set, load_golden_set  # noqa: E402
from src.retrieval.indexing import HybridIndex  # noqa: E402
from src.data_processing.load_metadata import load_clean_metadata  # noqa: E402
from src.data_processing.merge_text import load_merged, merge_all, save_merged  # noqa: E402

TOP_K = 5
OUT_PATH = OUTPUT_DIR / "eval_evidence_check.csv"


def main():
    golden_df = load_golden_set()

    chunks = load_chunks()
    if chunks is None:
        print("[inspect_eval_evidence] 캐시(output/chunks.pkl) 없음 -> step2~3부터 다시 계산합니다...")
        df = load_merged()
        if df is None:
            df = merge_all(load_clean_metadata())
            save_merged(df)
            df = load_merged()
        chunks = chunk_all(df)
        save_chunks(chunks)
    else:
        print("[inspect_eval_evidence] 캐시(output/chunks.pkl) 불러옴")

    index = HybridIndex(chunks)
    print(f"인덱싱 완료: chunk {len(chunks)}개\n")

    rows = []
    for _, grow in golden_df.iterrows():
        query = grow["query"]
        expected = _expected_set(grow)
        hits = index.hybrid_search(query, k=TOP_K)

        print("=" * 100)
        print(f"[{grow.get('id')}] ({grow.get('난이도')}) {query}")
        print(f"  정답_파일명: {sorted(expected)}")

        if not hits:
            print("  (검색 결과 없음)")

        for rank, h in enumerate(hits, start=1):
            is_expected = h.doc_id in expected
            mark = "O 정답 문서" if is_expected else "X 다른 문서"
            print(f"  [{rank}위 | {h.matched_by} {h.score:.3f} | {mark}] {h.doc_id}")
            snippet = h.text.strip().replace("\n", " ")[:300]
            print(f"      본문: {snippet}")
            rows.append(
                {
                    "id": grow.get("id"),
                    "난이도": grow.get("난이도"),
                    "질문": query,
                    "정답_파일명": " | ".join(sorted(expected)),
                    "순위": rank,
                    "doc_id": h.doc_id,
                    "matched_by": h.matched_by,
                    "score": h.score,
                    "정답_문서_일치": is_expected,
                    "chunk_id": h.chunk_id,
                    "chunk_text": h.text,
                }
            )
        print()

    if rows:
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(OUT_PATH, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"전체 근거 청크(질문 {len(golden_df)}건 x top{TOP_K}) 저장: {OUT_PATH}")
        print("이 CSV를 엑셀로 열어서 chunk_text 컬럼에 실제 정답(예산 숫자/마감일/조항 등)이 들어있는지 확인해줘.")
        print("특히 '정답_문서_일치'가 True인 행이라도, chunk_text에 그 질문의 실제 답이 없으면")
        print("문서만 맞고 근거는 못 찾은 것 - recall@k 수치가 과대평가됐다는 뜻이야.")


if __name__ == "__main__":
    main()
