"""입찰메이트 전체 문서 RAG Streamlit 시연 앱.

기존 ``scripts/step26_streamlit_serving_prototype.py``는 선택한 문서 하나를
확인하는 프로토타입으로 보존한다. 이 앱은 검증에 사용한 전체
HybridIndex와 ``ask_rfp_v9`` 생성기를 연결한 별도 시연 진입점이다.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import streamlit as st


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from experiments.dahye_latest_20260909.answer_generation import ask_rfp_v9
from src.data_processing.chunking import load_chunks
from src.retrieval.embeddings import SentenceTransformerEmbedding
from src.retrieval.indexing import HybridIndex


DEFAULT_VISUAL_EVIDENCE = (
    ROOT / "output" / "experiments" / "b_plan_v3_vlm" / "visual_evidence.jsonl"
)
DEFAULT_MODELS = (
    "openai:gpt-5-mini",
    "openai:gpt-5-nano",
    "future:qwen3-8b",
    "future:qwen3.5-9b",
)
MODEL_LABELS = {
    "openai:gpt-5-mini": "GPT-5 mini — 사용 가능",
    "openai:gpt-5-nano": "GPT-5 nano — 사용 가능",
    "future:qwen3-8b": "Qwen3 8B — 로컬 백엔드 연결 예정",
    "future:qwen3.5-9b": "Qwen3.5 9B — 로컬 백엔드 연결 예정",
}
VISUAL_QUERY_WORDS = {
    "그림",
    "이미지",
    "도표",
    "표",
    "화면",
    "구성도",
    "흐름도",
    "다이어그램",
    "시각",
}


def _model_choices() -> list[str]:
    """`provider:model` 형식의 허용된 생성 런타임 목록."""
    raw = os.environ.get("BIDFIT_MODELS", "")
    configured = [item.strip() for item in raw.split(",") if item.strip()]
    return configured or list(DEFAULT_MODELS)


def _business_name(metadata: dict[str, Any]) -> str:
    return str(metadata.get("사업명") or metadata.get("사업_명") or "")


@st.cache_resource(show_spinner=False)
def load_runtime() -> dict[str, Any]:
    chunks = load_chunks()
    if not chunks:
        raise FileNotFoundError(
            "output/chunks.pkl이 없습니다. GCP 레포의 output 폴더에 놓아주세요."
        )

    child_chunks = [chunk for chunk in chunks if getattr(chunk, "strategy", "") != "parent"]
    doc_to_business: dict[str, str] = {}
    doc_metadata: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        doc_id = str(chunk.doc_id)
        metadata = getattr(chunk, "metadata", {}) or {}
        doc_to_business.setdefault(doc_id, _business_name(metadata))
        doc_metadata.setdefault(doc_id, dict(metadata))

    embedding = SentenceTransformerEmbedding()
    index = HybridIndex(chunks, persist=True, embedding_backend=embedding)
    return {
        "chunks": chunks,
        "child_chunks": child_chunks,
        "catalog": sorted(doc_to_business.items()),
        "doc_metadata": doc_metadata,
        "doc_ids": set(doc_to_business),
        "index": index,
        "embedding_name": embedding.name,
    }


@st.cache_resource(show_spinner=False)
def load_generation_client(provider: str):
    from openai import OpenAI
    if provider == "openai":
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            raise RuntimeError(
                "OPENAI_API_KEY가 없습니다. 레포 루트의 .env에 추가한 뒤 앱을 재시작하세요."
            )
        return OpenAI(api_key=key)
    if provider == "future":
        raise RuntimeError("선택한 로컬 모델은 UI만 준비됐으며 백엔드 연결 전입니다.")
    raise ValueError(f"지원하지 않는 생성 provider: {provider}")


def _split_model_choice(choice: str) -> tuple[str, str]:
    if ":" not in choice:
        return "openai", choice
    return tuple(choice.split(":", 1))  # type: ignore[return-value]


@st.cache_data(show_spinner=False)
def load_visual_evidence(path_text: str) -> list[dict[str, Any]]:
    path = Path(path_text)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("doc_id") and row.get("evidence_text") and not row.get("error"):
                rows.append(row)
    return rows


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[0-9A-Za-z가-힣]+", str(text).lower())
        if len(token) >= 2
    }


def select_visual_evidence(
    question: str,
    retrieved_doc_ids: list[str],
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """텍스트 검색이 찾은 문서의 기존 VLM 근거만 조건부로 사용한다."""
    if not rows:
        return []
    retrieved = set(retrieved_doc_ids)
    question_tokens = _tokens(question)
    explicitly_visual = bool(question_tokens & VISUAL_QUERY_WORDS)
    ranked: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        if str(row.get("doc_id")) not in retrieved:
            continue
        searchable = " ".join(
            str(row.get(key) or "")
            for key in ("query", "question", "evidence_text")
        )
        overlap = len(question_tokens & _tokens(searchable))
        if explicitly_visual or overlap > 0:
            ranked.append((overlap, row))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [row for _score, row in ranked[:2]]


class EvidenceCompletions:
    """실제 문서명으로만 VLM 근거를 생성 프롬프트에 추가한다."""

    def __init__(self, delegate: Any, evidence_rows: list[dict[str, Any]]):
        self.delegate = delegate
        self.evidence_rows = evidence_rows

    def create(self, **kwargs: Any):
        messages = [dict(message) for message in (kwargs.get("messages") or [])]
        if messages and self.evidence_rows:
            blocks = []
            for row in self.evidence_rows:
                blocks.append(
                    f"[시각 근거 문서: {row['doc_id']}]\n{row['evidence_text']}"
                )
            visual_context = "\n\n".join(blocks)
            prompt = str(messages[-1].get("content", ""))
            marker = "## 질문"
            insertion = f"## 기존 Qwen3-VL 시각 근거\n{visual_context}\n\n"
            if marker in prompt:
                prompt = prompt.replace(marker, insertion + marker, 1)
            else:
                prompt = insertion + prompt
            messages[-1]["content"] = prompt
            kwargs["messages"] = messages
        return self.delegate.create(**kwargs)


class EvidenceOpenAI:
    def __init__(self, client: Any, evidence_rows: list[dict[str, Any]]):
        self.chat = SimpleNamespace(
            completions=EvidenceCompletions(client.chat.completions, evidence_rows)
        )


_CITATION_AT_END = re.compile(r"\[\s*근거\s*:\s*(.+?)\]\s*$", re.DOTALL)


def clean_citation(answer: str, valid_doc_ids: set[str], visual_rows: list[dict[str, Any]]) -> str:
    """VLM 내부 ID는 제거하고 코퍼스의 실제 doc_id만 남긴다."""
    match = _CITATION_AT_END.search(answer or "")
    if not match:
        return answer
    cited = [item.strip() for item in match.group(1).split(",") if item.strip()]
    kept = list(dict.fromkeys(item for item in cited if item in valid_doc_ids))
    if not kept:
        kept = list(
            dict.fromkeys(
                str(row["doc_id"])
                for row in visual_rows
                if str(row.get("doc_id")) in valid_doc_ids
            )
        )
    if not kept:
        return answer
    return answer[: match.start()].rstrip() + f"\n\n[근거: {', '.join(kept)}]"


def main() -> None:
    st.set_page_config(page_title="입찰메이트 전체 RAG", page_icon="📄", layout="wide")
    st.title("📄 입찰메이트 전체 문서 RAG")
    st.caption(
        "98개 RFP 전체에서 KURE 벡터 검색과 BM25로 근거를 찾고, "
        "최신 통합 생성 파이프라인으로 답변합니다."
    )

    with st.sidebar:
        st.header("시연 설정")
        model_choice = st.selectbox(
            "생성 모델",
            _model_choices(),
            format_func=lambda value: MODEL_LABELS.get(value, value),
        )
        provider, model_name = _split_model_choice(model_choice)
        model_ready = provider != "future"
        if not model_ready:
            st.warning("로컬 모델은 선택 UI만 준비됐습니다. 지수님 백엔드 연결 후 활성화됩니다.")
        scope_mode = st.radio(
            "검색 범위",
            ("all", "explicit", "metadata"),
            format_func={
                "all": "전체 98개 문서",
                "explicit": "문서 직접 선택",
                "metadata": "조건으로 문서 찾기",
            }.get,
        )
        use_visual = st.checkbox("기존 VLM 시각 근거 사용", value=True)
        show_sources = st.checkbox("검색 근거 표시", value=True)
        st.info(
            "VLM은 미리 생성한 Qwen3-VL 근거 캐시를 재사용합니다. "
            "새 이미지를 실시간 판독하는 데모는 아닙니다."
        )

    try:
        with st.spinner("전체 문서 검색 인덱스를 불러오는 중입니다..."):
            runtime = load_runtime()
        client = load_generation_client(provider) if model_ready else None
    except Exception as exc:  # noqa: BLE001
        st.error(str(exc))
        st.stop()

    evidence_rows = load_visual_evidence(str(DEFAULT_VISUAL_EVIDENCE)) if use_visual else []
    st.success(
        f"문서 {len(runtime['doc_ids'])}개 · 청크 {len(runtime['chunks']):,}개 · "
        f"임베딩 {runtime['embedding_name']} · VLM 캐시 {len(evidence_rows)}건"
    )

    selected_doc_ids: list[str] = []
    with st.sidebar:
        if scope_mode == "explicit":
            selected_doc_ids = st.multiselect(
                "검색할 문서 (최대 20개)",
                [doc_id for doc_id, _name in runtime["catalog"]],
                max_selections=20,
            )
        elif scope_mode == "metadata":
            keyword = st.text_input("사업명·기관·문서명")
            agency = st.text_input("발주기관")
            matched: list[str] = []
            for doc_id, business_name in runtime["catalog"]:
                meta = runtime["doc_metadata"].get(doc_id, {})
                agency_name = str(meta.get("발주 기관") or meta.get("발주_기관") or "")
                haystack = f"{doc_id} {business_name} {agency_name}".lower()
                if keyword.strip() and keyword.strip().lower() not in haystack:
                    continue
                if agency.strip() and agency.strip().lower() not in agency_name.lower():
                    continue
                matched.append(doc_id)
            st.caption(f"조건 일치 {len(matched)}개")
            selected_doc_ids = st.multiselect(
                "질문에 사용할 문서 (최대 20개)", matched, max_selections=20
            )

    scope_ready = scope_mode == "all" or bool(selected_doc_ids)
    if not scope_ready:
        st.info("검색할 문서를 한 개 이상 선택해 주세요.")

    example = st.selectbox(
        "예시 질문",
        (
            "",
            "예산이 가장 큰 사업과 그 금액을 알려줘.",
            "3개월 이내로 끝나는 짧은 사업을 모두 알려줘.",
            "입찰 참가자격과 평가 기준을 근거와 함께 비교해줘.",
        ),
    )
    question = st.text_area(
        "전체 RFP에 질문하기",
        value=example,
        height=110,
        placeholder="예: 예산이 10억 이상인 지자체 사업을 정리해줘.",
    )

    if st.button(
        "선택 범위에서 답변 찾기",
        type="primary",
        disabled=not question.strip() or not scope_ready or not model_ready,
    ):
        started = time.perf_counter()
        try:
            with st.spinner("전체 문서를 검색하고 답변을 생성하는 중입니다..."):
                if scope_mode == "all":
                    active_index = runtime["index"]
                    active_chunks = runtime["child_chunks"]
                    active_catalog = runtime["catalog"]
                else:
                    allowed = set(selected_doc_ids)
                    active_chunks = [
                        chunk for chunk in runtime["child_chunks"] if str(chunk.doc_id) in allowed
                    ]
                    scoped_chunks = [
                        chunk for chunk in runtime["chunks"] if str(chunk.doc_id) in allowed
                    ]
                    active_index = HybridIndex(
                        scoped_chunks,
                        persist=False,
                        embedding_backend=runtime["index"].embedding_backend,
                    )
                    active_catalog = [item for item in runtime["catalog"] if item[0] in allowed]
                hits = active_index.hybrid_search(
                    question.strip(), k=10, candidate_k=20, expand_to_parent=True
                )
                retrieved_doc_ids = list(dict.fromkeys(str(hit.doc_id) for hit in hits))
                selected_visual = select_visual_evidence(
                    question.strip(), retrieved_doc_ids, evidence_rows
                )
                generation_client = EvidenceOpenAI(client, selected_visual)
                answer = ask_rfp_v9(
                    question.strip(),
                    generation_client,
                    active_index,
                    active_chunks,
                    active_catalog,
                    model_name=model_name,
                )
                answer = clean_citation(answer, runtime["doc_ids"], selected_visual)
            elapsed = time.perf_counter() - started
        except Exception as exc:  # noqa: BLE001
            st.exception(exc)
            st.stop()

        st.subheader("답변")
        st.write(answer)
        st.caption(
            f"생성 모델: {provider}/{model_name} · 검색 범위: {scope_mode} · 소요 시간: {elapsed:.1f}초 · "
            f"VLM 근거: {len(selected_visual)}건 사용"
        )

        if selected_visual:
            with st.expander("VLM 시각 근거"):
                for row in selected_visual:
                    st.markdown(f"**{row['doc_id']}**")
                    st.text(str(row["evidence_text"]))

        if show_sources:
            with st.expander("초기 전체 문서 검색 후보", expanded=True):
                for number, hit in enumerate(hits, start=1):
                    st.markdown(
                        f"**{number}. {hit.doc_id}**  "
                        f"`{hit.matched_by}` · score `{float(hit.score):.4f}`"
                    )
                    st.text(str(hit.text)[:1200])


if __name__ == "__main__":
    main()
