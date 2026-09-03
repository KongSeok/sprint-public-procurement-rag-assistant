"""6단계: Indexing (Vector + BM25 Hybrid), 메타데이터 필터링 지원.

- Vector: chromadb persistent collection. embeddings.py의 EmbeddingBackend를
  chromadb의 EmbeddingFunction 인터페이스에 맞춰 래핑해서 사용.
- BM25: rank_bm25.BM25Okapi. 한국어 형태소 분석(kiwipiepy)으로 토큰화해
  제품명/모델명/규격/수량 같은 키워드 정확 일치 검색에 강하게 만든다
  (멘토링 노트 5번: RFP는 BM25가 특히 중요).
- Hybrid: 두 결과를 min-max 정규화 후 가중합으로 결합. vector_weight/bm25_weight를
  실험 파라미터로 노출해 멘토링 노트가 제안한 0.3/0.7 같은 가중치 튜닝을
  그대로 실험할 수 있게 했다.
- 메타데이터 필터링: chunk.metadata에 대한 python predicate(callable)를
  BM25/Vector 양쪽에 동일하게 후처리 필터로 적용해 필터 문법을 하나로 통일.

[2026-09-02 추가 - Parent-Child retrieval 실제 구현] chunking.py의
parent_child_chunk()는 parent/child chunk를 한 리스트에 같이 담아 반환하는데,
지금까지 HybridIndex는 이 둘을 구분 없이 그대로 검색 인덱스(Vector+BM25)에
다 넣고 있었다 - "검색은 작게, context는 크게"(멘토링 노트 6번)가 chunking
단계에서는 준비돼 있었지만 indexing 단계에서 실제로 지켜지지 않고 있었던
것(9/1 브리핑에서 발견). parent chunk는 child보다 훨씬 커서 BM25 term
frequency나 벡터 임베딩 희석 등으로 child와 공정하게 스코어링 경쟁을 하지
않고 오히려 검색 품질을 흐릴 수 있다. 이번에 두 가지로 고쳤다:
  1. 검색 후보(Vector/BM25 인덱스에 실제로 들어가는 대상)에서 strategy=="parent"
     chunk를 제외한다 - 검색은 child(+recursive)만으로 한다.
  2. HybridIndex.by_id(전체 chunk 조회용, parent 포함)는 그대로 유지해서,
     검색된 child가 속한 parent chunk의 전체 텍스트를 찾아 context로 확장하는
     expand_to_parent 옵션을 vector_search/bm25_search/hybrid_search에 추가했다.
     검색 순위/점수는 child 기준 그대로 두고, 최종 반환 직전에 text만
     parent 텍스트로 치환한다(같은 parent를 가리키는 중복 child는 하나로
     합쳐서 context 중복을 피함) - "검색은 작게, context는 크게"를 실제 코드로
     구현.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

import chromadb
import numpy as np
from rank_bm25 import BM25Okapi

from ..data_processing.chunking import Chunk
from ..config import CHROMA_DIR
from .embeddings import EmbeddingBackend, get_default_embedding_backend

MetaFilter = Callable[[dict], bool]

_kiwi = None


def _tokenize_ko(text: str) -> list[str]:
    """형태소 분석 후 내용어(명사/동사/형용사/외국어/숫자/한자)만 남긴다."""
    global _kiwi
    if _kiwi is None:
        from kiwipiepy import Kiwi
        _kiwi = Kiwi()
    keep_tags = {"NNG", "NNP", "NNB", "VV", "VA", "SL", "SH", "SN", "XR"}
    return [t.form for t in _kiwi.tokenize(text) if t.tag in keep_tags]


def _minmax(scores: np.ndarray) -> np.ndarray:
    if scores.size == 0:
        return scores
    lo, hi = scores.min(), scores.max()
    if hi - lo < 1e-9:
        # 후보가 1개뿐이거나 전부 동점이면 0으로 뭉개지 않고 만점 처리
        return np.ones_like(scores)
    return (scores - lo) / (hi - lo)


class _ChromaEmbeddingFn(chromadb.EmbeddingFunction):
    """chromadb가 요구하는 EmbeddingFunction 인터페이스 래퍼."""

    def __init__(self, backend: EmbeddingBackend):
        self.backend = backend

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        return self.backend.encode(list(input)).tolist()

    @staticmethod
    def name() -> str:
        return "custom_backend_wrapper"


@dataclass
class SearchHit:
    chunk_id: str
    doc_id: str
    text: str
    metadata: dict
    score: float
    matched_by: str  # "vector" | "bm25" | "hybrid"


class HybridIndex:
    def __init__(
        self,
        chunks: list[Chunk],
        persist: bool = True,
        collection_name: str | None = None,
        embedding_backend: EmbeddingBackend | None = None,
    ):
        self.chunks = chunks  # parent 포함 전체 - by_id 조회(=parent context 확장)용
        self.by_id = {c.chunk_id: c for c in chunks}
        # [2026-09-02] 실제 검색 후보는 parent를 뺀 것만 - 아래 인덱스 구축/BM25
        # 전부 이걸 기준으로 한다(모듈 docstring 참고).
        self._searchable_chunks = [c for c in chunks if c.strategy != "parent"]
        n_excluded = len(chunks) - len(self._searchable_chunks)
        if n_excluded:
            print(
                f"[HybridIndex] parent 전략 chunk {n_excluded}개는 검색 후보에서 제외"
                f"(context 확장 조회 전용) - 실제 검색 대상 {len(self._searchable_chunks)}개"
            )
        # [2026-09-02 저녁] embedding_backend를 주입 가능하게 열었다 - KURE-v1 vs
        # text-embedding-3-small A/B 비교(scripts/step11_embedding_compare.py)를
        # 하려면 같은 프로세스 안에서 서로 다른 백엔드로 HybridIndex를 두 번
        # 만들어야 하는데, 기존처럼 get_default_embedding_backend()를 무조건
        # 호출하면 항상 KURE-v1만 나온다. None이면(기존 스크립트 전부 해당)
        # 예전과 100% 동일하게 동작한다.
        self.embedding_backend = embedding_backend or get_default_embedding_backend()

        # [2026-09-02 저녁] collection_name을 backend별로 자동 구분한다. 이전엔
        # collection_name 기본값이 "rfp_chunks" 하나뿐이고, 재사용 판단이
        # "existing.count() == len(self._searchable_chunks)"(chunk 개수만 비교)
        # 였다 - 임베딩 백엔드를 바꿔도 chunk 개수가 같으면 예전 백엔드로 만든
        # 벡터를 그대로 "재사용"해버리는 조용한 사고 위험이 있었다(예:
        # text-embedding-3-small로 바꿨다고 생각했는데 실제로는 KURE-v1 벡터를
        # 계속 쓰고 있는 상황 - A/B 비교 자체가 무의미해짐). collection_name을
        # 명시적으로 안 넘기면 backend.name을 그대로 이름에 포함시켜 서로 다른
        # 백엔드가 절대 같은 컬렉션을 공유할 수 없게 했다. 기존 KURE-v1
        # 사용자는 이 변경으로 collection_name이 바뀌어(예전 "rfp_chunks" ->
        # "rfp_chunks__nlpai-lab_KURE-v1") 다음 실행에서 한 번은 재임베딩이
        # 일어난다 - 로컬 모델이라 비용은 없고 시간만 드는 일회성 비용이다.
        if collection_name is None:
            safe_backend_name = re.sub(r"[^a-zA-Z0-9_-]", "_", self.embedding_backend.name)
            collection_name = f"rfp_chunks__{safe_backend_name}"

        # --- Vector index (chromadb) ---
        if persist:
            CHROMA_DIR.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        else:
            client = chromadb.EphemeralClient()

        # [2026-09-01] 원래는 실행할 때마다 컬렉션을 무조건 지우고 새로 임베딩했다
        # (아래 delete_collection). 그런데 팀원이 "임베딩까지 끝난 output/chroma_db
        # 폴더"를 통째로 받아서 재계산 없이 그대로 쓰고 싶어했는데, 이 무조건 삭제
        # 로직 때문에 폴더를 받아봤자 step4/step5를 실행하는 순간 바로 지워지고
        # 처음부터 다시 임베딩되는 문제가 있었다. 이제 persist 모드에서는 기존
        # 컬렉션이 있고 chunk 개수까지 지금 넘겨받은 chunks와 정확히 같으면(=데이터가
        # 안 바뀌었다는 최소한의 신호) 재계산 없이 그대로 재사용한다. 개수가 다르면
        # (원본 문서가 추가/삭제됐거나 청킹 로직이 바뀐 것) 안전하게 예전처럼
        # 지우고 처음부터 다시 만든다 - "개수만 같고 내용은 바뀐" 경우까지는 못
        # 잡아내는 느슨한 체크이니, 코퍼스를 바꿨는데 우연히 chunk 개수가 같다면
        # output/chroma_db 폴더를 수동으로 지우고 다시 실행할 것.
        reused_existing = False
        if persist:
            try:
                existing = client.get_collection(
                    collection_name, embedding_function=_ChromaEmbeddingFn(self.embedding_backend)
                )
                # [2026-09-02] 예전엔 여기서 len(chunks)(parent 포함)와 비교했는데,
                # 이제 컬렉션에는 self._searchable_chunks(parent 제외)만 들어가므로
                # 그 개수와 비교해야 한다 - 안 고치면 parent 제외 적용 전 기존
                # 컬렉션(개수가 더 많음)이 절대 재사용 조건을 못 맞춰 매번 새로
                # 만들거나, 반대로 우연히 개수가 같은 엉뚱한 컬렉션을 재사용하는
                # 사고가 날 수 있다. 이번 배포 첫 실행은 어차피 컬렉션에 parent가
                # 섞여 있던 이전 인덱스라 개수가 안 맞아 자동으로 재생성된다(의도된
                # 동작 - 아래 else 브랜치 참고).
                if existing.count() == len(self._searchable_chunks):
                    self._collection = existing
                    reused_existing = True
                    print(
                        f"[HybridIndex] 기존 임베딩 인덱스 재사용: output/chroma_db "
                        f"(collection={collection_name}, backend={self.embedding_backend.name}, "
                        f"검색 대상 chunk {len(self._searchable_chunks)}개 일치, 재임베딩 건너뜀)"
                    )
            except Exception:  # noqa: BLE001
                pass  # 컬렉션이 아직 없으면(첫 실행) 여기로 옴 - 정상, 아래에서 새로 만듦

        if not reused_existing:
            print(
                f"[HybridIndex] 새로 임베딩 진행: collection={collection_name}, "
                f"backend={self.embedding_backend.name} ({len(self._searchable_chunks)}개 chunk)"
            )
            try:
                client.delete_collection(collection_name)
            except Exception:  # noqa: BLE001
                pass
            self._collection = client.create_collection(
                collection_name, embedding_function=_ChromaEmbeddingFn(self.embedding_backend)
            )
        if self._searchable_chunks and not reused_existing:
            # [2026-08-27 발견] chromadb(rust 바인딩)는 client.add() 한 번에 넣을 수
            # 있는 최대 개수(max batch size)가 있다 - 이 환경에서는 5461. RFP 100건을
            # 표/그림 자리표시자까지 정리하고 나니 chunk가 11568개(> 5461)까지
            # 늘어나서 한 번에 add()하면 ValueError("Batch size ... is greater than
            # max batch size ...")로 죽는다. client.get_max_batch_size()로 실제
            # 한도를 물어봐서 그 크기 이하로 나눠 넣으면 데이터 손실 없이 해결된다
            # (하드코딩하지 않는 이유: 이 한도는 chromadb 버전/빌드에 따라 달라질 수
            # 있어서, 실행 중인 환경에 직접 물어보는 쪽이 더 안전하다).
            ids = [c.chunk_id for c in self._searchable_chunks]
            documents = [c.text for c in self._searchable_chunks]
            metadatas = [self._safe_meta(c) for c in self._searchable_chunks]
            max_batch = client.get_max_batch_size()
            for start in range(0, len(self._searchable_chunks), max_batch):
                end = start + max_batch
                self._collection.add(
                    ids=ids[start:end],
                    documents=documents[start:end],
                    metadatas=metadatas[start:end],
                )

        # --- BM25 index ---
        self._tokenized_corpus = [_tokenize_ko(c.text) for c in self._searchable_chunks]
        self._bm25 = BM25Okapi(self._tokenized_corpus) if self._searchable_chunks else None

    @staticmethod
    def _safe_meta(c: Chunk) -> dict:
        # chromadb 메타데이터는 None/복합타입을 허용하지 않으므로 문자열/기본형으로 정리
        out = {}
        for k, v in c.metadata.items():
            if v is None:
                continue
            if isinstance(v, (str, int, float, bool)):
                out[k] = v
            else:
                out[k] = str(v)
        out["doc_id"] = c.doc_id
        out["strategy"] = c.strategy
        return out

    def _expand_hits_to_parent(self, hits: list[SearchHit]) -> list[SearchHit]:
        """child chunk의 text를 parent chunk의 전체 text로 치환한다("검색은
        작게, context는 크게" - 멘토링 노트 6번 - 을 실제로 구현하는 부분).
        순위/점수/matched_by는 그대로 두고 text만 바꾼다. 여러 child가 같은
        parent에 속해 있으면(예: top-5 중 2~3개가 한 parent 안의 서로 다른
        child) 같은 parent 텍스트를 context에 중복으로 넣지 않도록, 먼저 나온
        (=더 상위 랭크) 히트만 남기고 이후 같은 parent를 가리키는 히트는
        건너뛴다 - 그 결과 반환 개수가 k보다 적어질 수 있다(의도된 동작).
        child가 아닌 chunk(recursive strategy - parent/child 구조가 없는
        일반 문서)는 원래 text 그대로 통과시킨다."""
        seen_parents: set[str] = set()
        expanded: list[SearchHit] = []
        for h in hits:
            chunk = self.by_id.get(h.chunk_id)
            if chunk is not None and chunk.strategy == "child" and chunk.parent_chunk_id:
                parent_id = chunk.parent_chunk_id
                if parent_id in seen_parents:
                    continue  # 이미 이 parent 텍스트를 context에 넣었음 - 중복 스킵
                parent_chunk = self.by_id.get(parent_id)
                if parent_chunk is not None:
                    seen_parents.add(parent_id)
                    expanded.append(SearchHit(
                        chunk_id=h.chunk_id,  # 실제로 매칭된(검색 근거) child chunk_id는 그대로 유지
                        doc_id=h.doc_id, text=parent_chunk.text, metadata=h.metadata,
                        score=h.score, matched_by=h.matched_by,
                    ))
                    continue
            expanded.append(h)
        return expanded

    def vector_search(
        self, query: str, k: int = 5, meta_filter: Optional[MetaFilter] = None,
        expand_to_parent: bool = False,
    ) -> list[SearchHit]:
        fetch_k = k * 4 if meta_filter else k
        res = self._collection.query(
            query_texts=[query], n_results=min(fetch_k, len(self._searchable_chunks) or 1)
        )
        hits = []
        ids = res["ids"][0] if res["ids"] else []
        docs = res["documents"][0] if res["documents"] else []
        dists = res["distances"][0] if res["distances"] else []
        for cid, doc_text, dist in zip(ids, docs, dists):
            meta = self.by_id[cid].metadata
            if meta_filter and not meta_filter(meta):
                continue
            hits.append(SearchHit(cid, self.by_id[cid].doc_id, doc_text, meta, score=1 - dist, matched_by="vector"))
            if len(hits) >= k:
                break
        return self._expand_hits_to_parent(hits) if expand_to_parent else hits

    def bm25_search(
        self, query: str, k: int = 5, meta_filter: Optional[MetaFilter] = None,
        expand_to_parent: bool = False,
    ) -> list[SearchHit]:
        if self._bm25 is None:
            return []
        tokens = _tokenize_ko(query)
        scores = self._bm25.get_scores(tokens)
        order = np.argsort(scores)[::-1]
        hits = []
        for idx in order:
            if scores[idx] <= 0:
                break
            # [2026-09-02 수정] BM25Okapi는 self._tokenized_corpus(=검색 후보인
            # self._searchable_chunks 순서 그대로) 기준으로 스코어를 매기므로,
            # idx는 self._searchable_chunks의 위치다. parent를 검색 후보에서
            # 빼기 전에는 self.chunks와 순서가 같아서 우연히 맞았지만, 이제는
            # self.chunks(parent 포함)를 쓰면 완전히 엉뚱한(순서가 밀린) chunk를
            # 반환하는 버그가 된다 - self._searchable_chunks로 고쳤다.
            chunk = self._searchable_chunks[idx]
            if meta_filter and not meta_filter(chunk.metadata):
                continue
            hits.append(SearchHit(chunk.chunk_id, chunk.doc_id, chunk.text, chunk.metadata, float(scores[idx]), "bm25"))
            if len(hits) >= k:
                break
        return self._expand_hits_to_parent(hits) if expand_to_parent else hits

    def hybrid_search(
        self, query: str, k: int = 5, meta_filter: Optional[MetaFilter] = None,
        vector_weight: float = 0.5, bm25_weight: float = 0.5, candidate_k: int = 20,
        expand_to_parent: bool = False,
    ) -> list[SearchHit]:
        # 후보 풀(v_hits/b_hits)은 항상 child 단위 그대로 모은다 - parent 확장은
        # 최종 top-k를 뽑은 뒤 한 번만 적용해야 랭킹/스코어가 왜곡되지 않는다.
        v_hits = self.vector_search(query, k=candidate_k, meta_filter=meta_filter)
        b_hits = self.bm25_search(query, k=candidate_k, meta_filter=meta_filter)

        v_scores = _minmax(np.array([h.score for h in v_hits])) if v_hits else np.array([])
        b_scores = _minmax(np.array([h.score for h in b_hits])) if b_hits else np.array([])

        combined: dict[str, SearchHit] = {}
        combined_score: dict[str, float] = {}
        for h, s in zip(v_hits, v_scores):
            combined[h.chunk_id] = h
            combined_score[h.chunk_id] = combined_score.get(h.chunk_id, 0.0) + vector_weight * float(s)
        for h, s in zip(b_hits, b_scores):
            combined[h.chunk_id] = h
            combined_score[h.chunk_id] = combined_score.get(h.chunk_id, 0.0) + bm25_weight * float(s)

        ranked_ids = sorted(combined_score, key=combined_score.get, reverse=True)[:k]
        hits = [
            SearchHit(
                combined[cid].chunk_id, combined[cid].doc_id, combined[cid].text,
                combined[cid].metadata, combined_score[cid], "hybrid",
            )
            for cid in ranked_ids
        ]
        return self._expand_hits_to_parent(hits) if expand_to_parent else hits


if __name__ == "__main__":
    from .chunking import chunk_all
    from .load_metadata import load_clean_metadata
    from .merge_text import merge_all

    df = merge_all(load_clean_metadata())
    chunks = chunk_all(df)
    index = HybridIndex(chunks)
    print(f"인덱싱 완료: chunk {len(chunks)}개, 임베딩 백엔드={index.embedding_backend.name}")

    q = "학사정보시스템 고도화 사업 예산"
    print("--- expand_to_parent=False(기존) ---")
    for h in index.hybrid_search(q, k=3):
        print(f"[{h.matched_by} {h.score:.3f}] {h.doc_id} :: len={len(h.text)} :: {h.text[:60]}")
    print("--- expand_to_parent=True(parent-child context 확장) ---")
    for h in index.hybrid_search(q, k=3, expand_to_parent=True):
        print(f"[{h.matched_by} {h.score:.3f}] {h.doc_id} :: len={len(h.text)} :: {h.text[:60]}")
