"""임베딩 백엔드 추상화.

기본 모델은 config.py의 EMBEDDING_MODEL_NAME(현재 nlpai-lab/KURE-v1, 한국어
검색에 특화된 bge-m3 파인튜닝 모델)을 그대로 따른다. 모델을 바꾸고 싶으면
이 파일이 아니라 config.py의 EMBEDDING_MODEL_NAME 한 곳만 고치면 된다.
SentenceTransformerEmbedding이 HuggingFace에서 이 모델을 내려받아 사용하고,
네트워크가 막혀 다운로드가 실패하면(예: 이 개발 샌드박스) 자동으로 오프라인
TfidfHashEmbedding으로 폴백해 파이프라인이 계속 동작하게 했다.
TfidfHashEmbedding은 의미 기반 임베딩이 아니라 어휘 기반 근사치이므로,
실제 서비스/평가에는 반드시 SentenceTransformer(또는 API 임베딩)로 교체할 것.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from ..config import EMBEDDING_MODEL_NAME


class EmbeddingBackend(ABC):
    name: str = "base"
    dim: int = 0

    @abstractmethod
    def encode(self, texts: list[str]) -> np.ndarray:
        ...


class SentenceTransformerEmbedding(EmbeddingBackend):
    """다국어 문장 임베딩. 네트워크로 HuggingFace Hub에서 모델을 내려받는다.

    기본값 BAAI/bge-m3는 dim=1024, 모델 용량 약 2.2GB라 최초 실행 시 다운로드에
    시간이 좀 더 걸리고(회선에 따라 수 분~십수 분), CPU로 4,800개 chunk를 인코딩하는
    데도 기존 MiniLM(dim=384, ~470MB)보다 시간이 더 든다. 대신 다국어 검색
    벤치마크(한국어 포함)에서 성능이 더 좋다고 알려져 있어 실 서비스/평가용으로
    바꾼 것. GPU가 있으면 훨씬 빨라진다.
    """

    def __init__(self, model_name: str = EMBEDDING_MODEL_NAME):
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)
        self.name = model_name
        # sentence-transformers 최신 버전은 get_sentence_embedding_dimension()이
        # get_embedding_dimension()으로 이름이 바뀌었다(FutureWarning). 설치된
        # 버전에 맞는 쪽을 골라 쓴다.
        if hasattr(self._model, "get_embedding_dimension"):
            self.dim = self._model.get_embedding_dimension()
        else:
            self.dim = self._model.get_sentence_embedding_dimension()

    def encode(self, texts: list[str]) -> np.ndarray:
        return np.asarray(self._model.encode(texts, normalize_embeddings=True, show_progress_bar=True))


class OpenAIEmbedding(EmbeddingBackend):
    """OpenAI API 임베딩(기본 text-embedding-3-small). KURE-v1(로컬,
    한국어 특화 sentence-transformers)과의 A/B 비교용으로 [2026-09-02 저녁]
    추가했다 - 어느 쪽이 이 RFP 코퍼스에서 retrieval 품질이 더 나은지
    확인하는 게 목적이므로, 기본 백엔드(get_default_embedding_backend)는
    그대로 KURE-v1을 쓰고 이 클래스는 명시적으로 골라 써야만 사용된다
    (기존 스크립트 동작에 영향 없음).

    OPENAI_API_KEY 환경변수가 필요하고, 호출당 요금이 든다(다만
    text-embedding-3-small은 1M 토큰당 $0.02로 매우 저렴 - 이 코퍼스
    chunk 전체를 임베딩해도 보통 1달러 미만). 한 번의 요청에 넣을 수 있는
    입력 개수/토큰 수에 상한이 있어 batch_size만큼 나눠서 호출한다.
    """

    def __init__(self, model_name: str = "text-embedding-3-small", batch_size: int = 200):
        from openai import OpenAI

        self._client = OpenAI()
        self.name = model_name
        self._batch_size = batch_size
        # text-embedding-3-small=1536, text-embedding-3-large=3072 - 모델별로
        # 다르므로 첫 인코딩 결과에서 실제 차원을 확인해 채운다(아래 encode 참고).
        self.dim = 1536 if "small" in model_name else 3072

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors: list[list[float]] = []
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            # 빈 문자열을 그대로 보내면 API가 오류를 내는 경우가 있어 최소 1글자로 대체.
            batch = [t if t and t.strip() else " " for t in batch]
            resp = self._client.embeddings.create(model=self.name, input=batch)
            vectors.extend(item.embedding for item in resp.data)
        arr = np.asarray(vectors, dtype=np.float32)
        if arr.size:
            self.dim = arr.shape[1]
        return arr


class TfidfHashEmbedding(EmbeddingBackend):
    """오프라인 폴백: 문자 n-gram HashingVectorizer 기반 고정 차원 벡터.

    사전 학습된 의미 임베딩이 아니라 어휘 중첩 기반 근사치라 recall 품질이
    SentenceTransformer보다 낮다. 네트워크가 막힌 이 샌드박스에서 파이프라인
    구조/엔드투엔드 동작을 검증하기 위한 용도로만 사용.
    """

    def __init__(self, n_features: int = 512):
        from sklearn.feature_extraction.text import HashingVectorizer

        self._vectorizer = HashingVectorizer(
            n_features=n_features, alternate_sign=False,
            analyzer="char_wb", ngram_range=(2, 4), norm="l2",
        )
        self.name = "tfidf_hash_fallback"
        self.dim = n_features

    def encode(self, texts: list[str]) -> np.ndarray:
        return self._vectorizer.transform(texts).toarray()


def get_default_embedding_backend() -> EmbeddingBackend:
    """SentenceTransformer 우선 시도, 실패(네트워크 등)하면 폴백."""
    print(
        "[embeddings] SentenceTransformer 모델 로드 시도 중... "
        "(처음 실행이면 HuggingFace에서 모델을 내려받아 몇 분 걸릴 수 있습니다)",
        flush=True,
    )
    try:
        backend = SentenceTransformerEmbedding()
        print(f"[embeddings] SentenceTransformer 사용: {backend.name} (dim={backend.dim})")
        return backend
    except Exception as e:  # noqa: BLE001
        print(f"[embeddings] SentenceTransformer 로드 실패({e}) -> TfidfHashEmbedding 폴백")
        backend = TfidfHashEmbedding()
        print(f"[embeddings] 폴백 사용: {backend.name} (dim={backend.dim})")
        return backend
