"""평가(evaluation): Golden Test Set 기반 Retrieval 평가.

멘토링 노트가 강조한 대로 "Retrieval 평가"와 "Answer 평가"를 분리한다. 이
모듈은 Retrieval 평가만 다룬다 — 정답 문서가 검색 결과 상위 K개 안에
들어왔는지(Recall@K), 얼마나 상위에 있었는지(MRR)를 측정한다. LLM 답변
자체의 정확도(Answer 평가)는 여기서 다루지 않는다 — Retrieval이 맞았는지와
최종 답변이 맞았는지를 분리해야 어디가 문제인지 알 수 있기 때문(멘토링 노트 8번).

Golden Set 포맷 (data/golden_set.json) [2026-08-27 CSV -> JSON으로 변경]:
    [{"번호": int, "난이도": str, "질문": str, "정답_파일명": [str, ...], "비고": str}, ...]
    정답_파일명은 항상 리스트다 - 단일 정답 질문도 원소 1개짜리 리스트로 쓴다.
    "예산 1억 이상인 사업 전부" 같은 필터형 질문은 정답 문서가 여러 개인데,
    예전 CSV는 이걸 "a.hwp|b.hwp"처럼 "|"로 이어붙인 문자열로 표현했다 -
    파일명 자체에 "|"가 들어갈 일은 없다고 가정한 편법이었다. JSON 배열로
    바꾸면 이런 구분자 충돌 걱정 없이 다중 정답을 자연스럽게 표현할 수 있다.
    구버전 CSV(id/query/expected_doc_id/난이도/담당자/note, "|"구분 문자열)도
    호환을 위해 계속 읽을 수 있게 남겨뒀다.

    문서(doc_id) 단위로만 채점하고, chunk 단위 정답까지는 보지 않는다 -
    "그 문서의 어떤 chunk라도 찾아오면 맞다"는 기준.

[2026-09-02 추가] 위 한계(문서 단위 채점이라 표지/목차 같은 엉뚱한 chunk만
찾아도 hit으로 카운트되는 문제 - 8/27에 처음 지적됨)를 메우려면 원래 golden
set에 "정답 chunk"까지 새로 라벨링해야 하는데 손이 많이 간다. 대신
evaluate_context_fact_coverage()는 이미 generation 채점에 쓰던
required_fact_groups를 재사용해서, LLM 답변이 아니라 검색 직후의 context
텍스트 자체에 필요한 사실이 들어있는지를 확인한다 - LLM 호출이 전혀 없어
API 비용도 없고 매번 똑같은 결과가 나온다(결정론적). "정답 문서를 찾았는지"
(recall@k)와 "AI 최종 답변이 맞는지"(Answer 평가) 사이의 중간 지표로,
Parent-Child처럼 context의 완전성을 바꾸는 실험의 효과를 비용 없이 먼저
가늠하는 용도.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from ..config import DUPLICATE_EXCLUSIONS_PATH, GOLDEN_SET_PATH
from ..generation.generation import build_context, check_required_facts
from ..retrieval.indexing import HybridIndex


def load_golden_set(path=GOLDEN_SET_PATH) -> pd.DataFrame:
    """golden_set.json(신규) 또는 golden_set.csv(구버전)를 읽어, 아래 나머지
    코드가 기대하는 내부 컬럼명(id, query, expected_doc_id, 난이도, 담당자)으로
    정규화해서 돌려준다. expected_doc_id는 항상 list로 통일한다(구버전 CSV의
    "a.hwp|b.hwp" 문자열도 여기서 리스트로 풀어준다) - 그래야 아래에서
    "|"로 이어붙여진 것과 JSON 배열을 똑같이 다룰 수 있다."""
    path = Path(path)
    if path.suffix == ".json":
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        df = pd.DataFrame(raw)
        # [2026-08-31] golden_testset_verified_111_v6.json(팀 취합/검증본)이
        # 우리가 쓰던 golden_set.json과 컬럼명이 정확히 같다는 보장이 없어서
        # (버전이 올라가며 이름이 바뀌었을 수 있음), 후보 이름을 여러 개
        # 시도하도록 완화했다. 그래도 못 찾으면 실제 컬럼명을 그대로 보여주는
        # 에러를 던져서 바로 원인을 알 수 있게 한다(예전엔 그냥 KeyError).
        rename_candidates = {
            "id": ["번호", "id", "ID", "No", "no"],
            "query": ["질문", "query", "question"],
            "expected_doc_id": [
                "정답_파일명", "정답파일명", "정답_문서", "정답_doc_id",
                "expected_doc_id", "정답", "answer_doc_id", "정답_파일",
                "source_documents",
            ],
            "note": ["비고", "note", "notes"],
            "난이도": ["난이도", "difficulty", "level"],
            "담당자": ["담당자", "assignee", "owner"],
        }
        rename = {}
        for target, candidates in rename_candidates.items():
            for cand in candidates:
                if cand in df.columns:
                    rename[cand] = target
                    break
        df = df.rename(columns=rename)

        if "expected_doc_id" not in df.columns:
            raise ValueError(
                f"golden set({path})에서 정답 문서 컬럼을 찾지 못했습니다. "
                f"실제 컬럼명: {list(df.columns)} - src/evaluation.py의 "
                "rename_candidates['expected_doc_id']에 이 이름을 추가해주세요."
            )
        if "query" not in df.columns:
            raise ValueError(
                f"golden set({path})에서 질문 컬럼을 찾지 못했습니다. "
                f"실제 컬럼명: {list(df.columns)} - src/evaluation.py의 "
                "rename_candidates['query']에 이 이름을 추가해주세요."
            )
        if "담당자" not in df.columns:
            df["담당자"] = None
        if "난이도" not in df.columns:
            # step5_evaluate.py의 print_progress()가 이 컬럼을 바로 참조하므로
            # 없으면 KeyError로 죽는다 - 담당자 컬럼과 동일하게 안전한 기본값.
            df["난이도"] = None
        # 정답_파일명이 이미 list이므로 그대로 두되, 혹시 문자열로 들어온 경우
        # (수작업 편집 등)를 대비해 리스트로 변환.
        df["expected_doc_id"] = df["expected_doc_id"].apply(
            lambda v: v if isinstance(v, list) else str(v).split("|")
        )

        # [2026-08-31] golden_testset_verified_111_v6.json의 source_documents는
        # "이 답의 근거가 된 출처" 전체를 담고 있어서, RFP 원본 문서(.hwp/.pdf)
        # 뿐 아니라 data_list.csv 같은 메타데이터 파일도 섞여 들어온다(예: 발주
        # 기관명을 CSV 메타데이터에서만 확인한 질문). 우리 Retrieval 인덱스는
        # RFP 원본 문서만 청킹해서 넣었지 data_list.csv 자체를 chunk로 넣은 적이
        # 없으므로, 이런 비-문서 출처가 expected_doc_id에 섞여 있으면 "애초에
        # 검색 대상이 아닌 것"을 못 찾았다고 recall이 부당하게 깎인다. 문서
        # 확장자(.hwp/.hwpx/.pdf)로 끝나는 출처만 남기고 걸러낸다.
        DOC_EXTENSIONS = (".hwp", ".hwpx", ".pdf")
        dropped_examples = []

        def _filter_doc_sources(sources: list) -> list:
            kept = [s for s in sources if str(s).lower().endswith(DOC_EXTENSIONS)]
            if len(kept) != len(sources):
                dropped_examples.extend(s for s in sources if s not in kept)
            return kept

        df["expected_doc_id"] = df["expected_doc_id"].apply(_filter_doc_sources)
        if dropped_examples:
            preview = ", ".join(sorted(set(map(str, dropped_examples)))[:5])
            print(
                f"[load_golden_set] 문서가 아닌 출처 {len(dropped_examples)}건을 "
                f"expected_doc_id에서 제외했습니다(예: {preview}). "
                "이런 항목만 있던 질문은 정답 문서 수가 0이 되어 recall@k=False로 잡힙니다."
            )
        n_empty = int((df["expected_doc_id"].apply(len) == 0).sum())
        if n_empty:
            print(
                f"[load_golden_set] 정답 문서가 하나도 안 남은 질문 {n_empty}건 있음"
                "(source_documents가 전부 비-문서 출처였거나 answerability=unanswerable일 수 있음) - "
                "이 질문들은 recall@k 계산에서 항상 False로 잡히니 결과 해석 시 감안하세요."
            )

        # [2026-08-31] scripts/diagnose_golden_set_doc_mismatches.py로 확인된
        # 문제: golden_testset_verified_111_v6.json(팀 취합본)의 일부 항목이
        # 파이프라인에서 이미 근-중복으로 제외된 문서(예: BioIN_...(2차).hwp)를
        # 정답으로 가리키고 있다 - 그 문서는 duplicate_exclusions.csv에 의해
        # 코퍼스에서 제외되고 텍스트가 100% 동일한 정본 문서(예:
        # 한국보건산업진흥원_...hwp)로 흡수됐으므로, 아무리 정본 문서를 잘
        # 찾아도 영원히 recall@k=False가 나오는 구조적 오탐이었다(B9/H13/H22
        # 확인됨). golden_testset_verified_111_v6.json 원본(팀원이 준 공유
        # 파일)은 건드리지 않고, 이미 있는 duplicate_exclusions.csv 매핑을
        # 그대로 재사용해 로드 시점에 정본 doc_id로 자동 교정한다 - 이 CSV는
        # 원래 코퍼스 구축 단계에서 "이 문서는 저 문서의 중복이라 뺀다"고 이미
        # 확정해둔 근거이므로, 여기서 새 데이터를 만들 필요 없이 같은 진실을
        # 재사용하는 것.
        if DUPLICATE_EXCLUSIONS_PATH.exists():
            dup_df = pd.read_csv(DUPLICATE_EXCLUSIONS_PATH)
            dup_map = dict(zip(dup_df["doc_id"], dup_df["dup_of"]))

            remapped_count = 0

            def _remap_excluded_dups(sources: list) -> list:
                nonlocal remapped_count
                out = []
                seen = set()
                for s in sources:
                    mapped = dup_map.get(s, s)
                    if mapped != s:
                        remapped_count += 1
                    if mapped not in seen:
                        seen.add(mapped)
                        out.append(mapped)
                return out

            df["expected_doc_id"] = df["expected_doc_id"].apply(_remap_excluded_dups)
            if remapped_count:
                print(
                    f"[load_golden_set] 근-중복으로 제외된 문서를 가리키던 정답 {remapped_count}건을 "
                    "duplicate_exclusions.csv 기준 정본 doc_id로 자동 교정했습니다."
                )
    else:
        df = pd.read_csv(path)
        df["expected_doc_id"] = df["expected_doc_id"].apply(lambda v: str(v).split("|"))

    required = {"query", "expected_doc_id"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"golden set({path})에 필요한 컬럼이 없습니다: {missing}")
    return df


def _expected_set(row) -> set:
    expected = row["expected_doc_id"]
    if isinstance(expected, (list, set, tuple)):
        return set(expected)
    return set(str(expected).split("|"))


def _search_doc_ids(
    index: HybridIndex, query: str, method: str, pool_size: int, reranker=None,
    hybrid_kwargs: dict | None = None,
) -> list:
    """method에 맞는 검색을 한 번만 실행해 상위 pool_size개의 doc_id 리스트를 반환.
    같은 문서의 chunk가 여러 개 뽑혀도 doc_id 기준으로 중복 없이 순서만 유지한다.

    [2026-09-03 추가] method="hybrid_rerank"는 hybrid_search로 뽑은 "같은
    후보 풀"(pool_size개, hybrid와 동일)을 reranker(src/reranking.py)로 다시
    채점해서 순서만 바꾼다 - 후보 풀 크기는 그대로라 "hybrid"와 "hybrid_rerank"를
    나란히 비교하면 리랭킹 자체의 순수 효과(순위 재배치)만 볼 수 있다.

    [2026-09-03 버그 수정] hybrid_kwargs는 evaluate_retrieval() 시그니처에
    원래부터 있었지만 여기로 실제 전달되지 않는 죽은 파라미터였다(호출부에서
    받기만 하고 아래로 넘기질 않았음) - BM25/벡터 가중치 튜닝(vector_weight/
    bm25_weight)을 하려면 반드시 필요해서 이번에 실제로 연결했다. hybrid/
    hybrid_rerank 두 method 모두 hybrid_search() 호출에 그대로 풀어 넣는다."""
    hybrid_kwargs = hybrid_kwargs or {}
    if method == "vector":
        hits = index.vector_search(query, k=pool_size)
    elif method == "bm25":
        hits = index.bm25_search(query, k=pool_size)
    elif method == "hybrid":
        hits = index.hybrid_search(query, k=pool_size, **hybrid_kwargs)
    elif method == "hybrid_rerank":
        if reranker is None:
            raise ValueError("method='hybrid_rerank'를 쓰려면 evaluate_retrieval(..., reranker=...)를 넘겨야 합니다")
        candidates = index.hybrid_search(query, k=pool_size, **hybrid_kwargs)
        hits = reranker.rerank(query, candidates)
    else:
        raise ValueError(f"알 수 없는 method: {method}")

    seen = set()
    doc_ids = []
    for h in hits:
        if h.doc_id not in seen:
            seen.add(h.doc_id)
            doc_ids.append(h.doc_id)
    return doc_ids


def _ndcg_at_k(doc_ids: list, expected: set, k: int) -> float:
    """[2026-09-02 저녁 추가] nDCG@k(binary relevance) - 팀원 쪽
    answer-56.metrics.json이 recall/MRR과 함께 nDCG@10도 재고 있어서 같은
    축으로 비교할 수 있게 우리 쪽에도 추가했다. 정답 문서는 전부 관련도
    1(그 이상의 등급 구분은 golden set에 없음)로 취급하는 binary 버전."""
    if not expected:
        return 0.0
    dcg = 0.0
    for i, d in enumerate(doc_ids[:k], start=1):
        if d in expected:
            dcg += 1.0 / math.log2(i + 1)
    ideal_hits = min(len(expected), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
    return (dcg / idcg) if idcg else 0.0


def evaluate_retrieval(
    index: HybridIndex,
    golden_df: pd.DataFrame,
    methods: tuple = ("vector", "bm25", "hybrid"),
    k_values: tuple = (1, 3, 5),
    hybrid_kwargs: dict | None = None,
    reranker=None,
) -> tuple:
    """각 질의 x 방법에 대해 검색을 1회만 실행하고, 그 결과로 여러 k의
    Recall@k와 MRR을 한 번에 계산한다. (질의별 상세 DataFrame, 방법별 요약 DataFrame) 반환.

    recall@k와 coverage@k의 차이 [2026-08-27 golden_set이 다중 정답 필터형
    질문("예산 1억 이상인 사업 전부")을 포함하게 되면서 추가함]:
      - recall@k: 정답 문서 중 "하나라도" 상위 k 안에 있으면 True. 단일 정답
        질문에서는 이게 전부지만, 정답이 10개인 필터형 질문에서 1개만 찾고
        나머지 9개를 놓쳐도 recall@k=True가 되어 실제 품질을 과대평가한다.
      - coverage@k: 정답 문서 중 상위 k 안에서 실제로 찾은 비율
        (|찾은 정답 ∩ 상위 k| / |전체 정답 개수|). 단일 정답 질문에서는
        recall@k와 coverage@k가 항상 같은 값(0 또는 1)이 되고, 다중 정답
        필터형 질문에서만 둘이 갈린다 - "필터형 질문에서 정답을 얼마나
        빠짐없이 다 찾아오는지"는 coverage@k로 봐야 한다.

    reranker [2026-09-03 추가]: methods에 "hybrid_rerank"를 넣으면 이
    Reranker(src/reranking.py) 인스턴스로 hybrid 후보 풀을 재정렬한다.
    methods=("hybrid", "hybrid_rerank")처럼 둘 다 넘기면 같은 golden set/같은
    후보 풀에 대해 리랭킹 전/후를 summary_df 한 표에서 바로 비교할 수 있다.

    hybrid_kwargs [2026-09-03 실제로 연결함]: HybridIndex.hybrid_search()에
    그대로 전달할 kwargs(예: {"vector_weight": 0.3, "bm25_weight": 0.7}) -
    method="hybrid"/"hybrid_rerank"에만 적용된다("vector"/"bm25" 단독
    검색에는 가중치 개념이 없음). BM25/벡터 가중치 튜닝(scripts/
    step16_hybrid_weight_tuning.py)이 이 파라미터로 alpha를 스윕한다. (참고:
    이 파라미터 자체는 원래 시그니처에 있었지만 실제로는 아래로 전달되지
    않는 죽은 코드였다 - 이번에 처음 실제로 연결했다.)
    """
    hybrid_kwargs = hybrid_kwargs or {}
    max_k = max(k_values)
    rows = []

    for _, row in golden_df.iterrows():
        expected = _expected_set(row)
        for method in methods:
            # 다중 정답 필터형 질문은 정답 개수 자체가 많을 수 있어(예: 10건),
            # k*2짜리 좁은 pool로는 전부 찾을 기회가 없다 - pool을 "k*2"와
            # "정답 개수 + 여유분" 중 큰 쪽으로 잡는다.
            pool_size = max(max_k * 2, len(expected) + 5)
            doc_ids = _search_doc_ids(
                index, row["query"], method, pool_size=pool_size, reranker=reranker, hybrid_kwargs=hybrid_kwargs,
            )

            rank = next((i for i, d in enumerate(doc_ids, start=1) if d in expected), None)
            mrr = 1.0 / rank if rank else 0.0

            record = {
                "id": row.get("id"),
                "query": row["query"],
                "method": method,
                "mrr": mrr,
                "rank_found": rank,
                "n_expected": len(expected),
                "top_hits": " | ".join(doc_ids[:3]),
            }
            for k in k_values:
                found = expected.intersection(doc_ids[:k])
                record[f"recall@{k}"] = len(found) > 0
                record[f"coverage@{k}"] = (len(found) / len(expected)) if expected else 0.0
                record[f"ndcg@{k}"] = _ndcg_at_k(doc_ids, expected, k)
                # [2026-09-02 밤 추가] 위 "mrr"은 pool_size(최대 k_values, 기본은
                # k*2 이상) 전체에서 정답을 찾으면 그 순위로 점수를 준다 - k_values에
                # 10을 넣어도 "mrr"은 여전히 pool 전체(예: 20위) 안에서 찾은 순위를
                # 그대로 반영해버려서, 팀원 쪽 mrr@10(10위 밖이면 0점 처리)과 값이
                # 안 맞을 수 있다. 팀원 수치와 직접 비교하려면 "그 k 밖에서 찾으면
                # 0점"으로 자르는 mrr@k가 따로 필요해서 recall/ndcg와 같은 방식으로
                # k_values마다 추가했다.
                record[f"mrr@{k}"] = (1.0 / rank) if (rank and rank <= k) else 0.0
            rows.append(record)

    detail_df = pd.DataFrame(rows)
    summary_cols = (
        [f"recall@{k}" for k in k_values]
        + [f"coverage@{k}" for k in k_values]
        + [f"ndcg@{k}" for k in k_values]
        + [f"mrr@{k}" for k in k_values]
        + ["mrr"]
    )
    summary_df = detail_df.groupby("method")[summary_cols].mean().reset_index()
    return detail_df, summary_df


def evaluate_set_retrieval(
    index: HybridIndex,
    golden_df: pd.DataFrame,
    methods: tuple = ("vector", "bm25", "hybrid"),
    pool_k: int = 10,
) -> tuple:
    """"집합검색형" 질문(정답이 doc_id 하나가 아니라 문서 '집합') 전용 평가.

    [2026-09-01 추가] golden-set-v3-share 패키지의 set-13 lane처럼 "정답 문서가
    몇 개인지" 자체가 채점 대상인 질문에는 recall@k/MRR이 안 맞는다 - 예를 들어
    정답이 12건인데 top-5만 보면 아무리 잘 찾아도 recall@5 계산 대상에서
    12건 중 5건 이상은 원리적으로 못 찾는다. 그래서 "top-k 고정" 대신
    질문마다 "정답 개수 + 여유분"만큼 넉넉하게 뽑은 뒤(pool_size, 기존
    evaluate_retrieval의 다중 정답 처리와 동일한 방식), 그 검색 결과 집합
    전체를 "이 시스템이 이 질문에 대해 찾아온 문서 집합"으로 보고
    Precision/Recall/F1을 계산한다.

    - precision = |검색결과 ∩ 정답| / |검색결과|  (엉뚱한 문서를 얼마나 안 섞었는지)
    - recall    = |검색결과 ∩ 정답| / |정답|      (정답을 얼마나 빠짐없이 찾았는지)
    - f1        = precision/recall의 조화평균

    golden_df는 evaluation.py의 다른 함수들과 동일하게 query/expected_doc_id
    컬럼을 기대한다(src/golden_set_v3.py의 load_golden_set_v3()가 만드는
    lane="set" 행이 여기 해당).
    """
    rows = []
    for _, row in golden_df.iterrows():
        expected = _expected_set(row)
        for method in methods:
            pool_size = max(pool_k, len(expected) + 5)
            retrieved = set(_search_doc_ids(index, row["query"], method, pool_size=pool_size))

            tp = len(retrieved & expected)
            precision = (tp / len(retrieved)) if retrieved else 0.0
            recall = (tp / len(expected)) if expected else 0.0
            f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

            rows.append({
                "id": row.get("id"),
                "query": row["query"],
                "method": method,
                "n_expected": len(expected),
                "n_retrieved": len(retrieved),
                "n_correct": tp,
                "precision": precision,
                "recall": recall,
                "f1": f1,
            })

    detail_df = pd.DataFrame(rows)
    summary_df = detail_df.groupby("method")[["precision", "recall", "f1"]].mean().reset_index()
    return detail_df, summary_df


def evaluate_context_fact_coverage(
    index: HybridIndex,
    golden_df: pd.DataFrame,
    methods: tuple = ("hybrid",),
    k: int = 5,
    expand_to_parent: bool = False,
) -> tuple:
    """API 호출(LLM 생성) 없이, "검색된 context 안에 답에 필요한 사실이 실제로
    들어있는가"만 확인하는 retrieval 진단 지표. 모듈 docstring 상단의
    [2026-09-02 추가] 설명 참고.

    golden_df는 query/required_fact_groups 컬럼이 필요하다(golden_set_v3의
    answer lane 그대로 쓰거나, v6 golden set의 "required_facts" 컬럼을
    "required_fact_groups"로 rename해서 넘기면 된다). required_fact_groups가
    없거나 빈 리스트인 행은 채점 불가능하므로 건너뛴다.

    각 질문에 대해 index.{method}_search()로 검색 -> build_context()로
    LLM에 넘길 context 텍스트를 조립(generate_answer는 절대 호출 안 함) ->
    check_required_facts()로 그 context 텍스트 자체에 필요한 사실이
    들어있는지 검사한다. generation 평가의 "pass"에 해당하는 개념이지만,
    LLM이 그 사실들을 답으로 잘 뽑아 썼는지는 안 보고 "애초에 뽑아 쓸
    재료가 context 안에 있었는지"만 본다 - 그래서 이 지표가 낮으면 100%
    retrieval/context 문제이고, 이 지표는 높은데 generation pass율이
    낮으면 그건 LLM이 있는 재료를 못 살린 것(prompt/생성 문제)이라고
    원인을 구분할 수 있다.

    반환값: (질의별 상세 DataFrame, method x expand_to_parent별 요약 DataFrame).
    """
    rows = []
    for _, row in golden_df.iterrows():
        required_facts = row.get("required_fact_groups")
        if not isinstance(required_facts, list) or len(required_facts) == 0:
            continue
        query = row["query"]
        for method in methods:
            if method == "vector":
                hits = index.vector_search(query, k=k, expand_to_parent=expand_to_parent)
            elif method == "bm25":
                hits = index.bm25_search(query, k=k, expand_to_parent=expand_to_parent)
            elif method == "hybrid":
                hits = index.hybrid_search(query, k=k, expand_to_parent=expand_to_parent)
            else:
                raise ValueError(f"알 수 없는 method: {method}")

            context = build_context(hits)
            matched, total = check_required_facts(context, required_facts)
            rows.append({
                "id": row.get("id"),
                "query": query,
                "method": method,
                "expand_to_parent": expand_to_parent,
                "facts_matched": matched,
                "facts_total": total,
                "fact_coverage": (matched / total) if total else None,
                "fully_covered": (matched == total) if total else None,
            })

    detail_df = pd.DataFrame(rows)
    if len(detail_df) == 0:
        return detail_df, pd.DataFrame(columns=["method", "expand_to_parent", "fact_coverage", "fully_covered"])
    summary_df = (
        detail_df.groupby(["method", "expand_to_parent"])[["fact_coverage", "fully_covered"]]
        .mean()
        .reset_index()
    )
    return detail_df, summary_df
