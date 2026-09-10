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
from src.data_processing.merge_text import load_merged
from src.retrieval.embeddings import SentenceTransformerEmbedding
from src.retrieval.indexing import HybridIndex
from scripts.step26_streamlit_serving_prototype import _build_quick_replies
from scripts.step27_quick_answer_llm_polish import generate_quick_answer
from streamlit_demo.compound_queries import answer_period_budget_query


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

    merged = load_merged()
    child_chunks = [chunk for chunk in chunks if getattr(chunk, "strategy", "") != "parent"]
    doc_to_business: dict[str, str] = {}
    doc_metadata: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        doc_id = str(chunk.doc_id)
        metadata = getattr(chunk, "metadata", {}) or {}
        doc_to_business.setdefault(doc_id, _business_name(metadata))
        doc_metadata.setdefault(doc_id, dict(metadata))

    # 청크 메타데이터에는 검색에 필요한 최소 필드만 있어 공개일이 빠져 있다.
    # 최근 게시 공고 필터를 위해 병합 데이터의 공개일을 문서 메타데이터에 보강한다.
    for _index, row in merged.iterrows():
        doc_id = str(row.get("doc_id") or "")
        if not doc_id:
            continue
        metadata = doc_metadata.setdefault(doc_id, {})
        for key in ("공개 일자_dt", "공개 일자"):
            value = row.get(key)
            if value is not None:
                metadata[key] = value

    embedding = SentenceTransformerEmbedding()
    index = HybridIndex(chunks, persist=True, embedding_backend=embedding)
    return {
        "chunks": chunks,
        "merged": merged,
        "child_chunks": child_chunks,
        "catalog": sorted(doc_to_business.items()),
        "doc_metadata": doc_metadata,
        "doc_ids": set(doc_to_business),
        "index": index,
        "embedding_name": embedding.name,
    }


def _selected_document(runtime: dict[str, Any], doc_id: str) -> tuple[Any, str]:
    rows = runtime["merged"][runtime["merged"]["doc_id"] == doc_id]
    if rows.empty:
        raise KeyError(f"문서를 찾지 못했습니다: {doc_id}")
    row = rows.iloc[0]
    return row, str(row.get("text") or "")


def _candidate_excerpt(document_text: str, candidate: str, width: int = 800) -> str:
    needle = " ".join(candidate.split())[:120]
    compact = " ".join(document_text.split())
    position = compact.find(needle)
    if position < 0:
        return candidate
    return compact[max(0, position - width) : position + len(needle) + width]


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


def _scoped_runtime(runtime: dict[str, Any], selected_doc_ids: list[str]):
    if not selected_doc_ids:
        return runtime["index"], runtime["child_chunks"], runtime["catalog"]
    allowed = set(selected_doc_ids)
    child_chunks = [c for c in runtime["child_chunks"] if str(c.doc_id) in allowed]
    all_chunks = [c for c in runtime["chunks"] if str(c.doc_id) in allowed]
    index = HybridIndex(
        all_chunks,
        persist=False,
        embedding_backend=runtime["index"].embedding_backend,
    )
    catalog = [item for item in runtime["catalog"] if item[0] in allowed]
    return index, child_chunks, catalog


def _render_global_search(
    runtime: dict[str, Any],
    client: Any,
    provider: str,
    model_name: str,
    model_ready: bool,
    evidence_rows: list[dict[str, Any]],
    show_sources: bool,
) -> None:
    st.header("🔎 전체 문서 찾기")
    st.caption("98개 RFP 전체 또는 선택 범위에서 통합 RAG로 검색하고 답변합니다.")
    scope_mode = st.radio(
        "검색 범위",
        ("all", "explicit", "metadata"),
        format_func={
            "all": "전체 98개 문서",
            "explicit": "문서 직접 선택",
            "metadata": "조건으로 문서 찾기",
        }.get,
        horizontal=True,
    )
    selected_doc_ids: list[str] = []
    if scope_mode == "explicit":
        selected_doc_ids = st.multiselect(
            "검색할 문서 (최대 20개)",
            [doc_id for doc_id, _name in runtime["catalog"]],
            max_selections=20,
        )
    elif scope_mode == "metadata":
        left, right = st.columns(2)
        keyword = left.text_input("사업명·기관·문서명")
        agency = right.text_input("발주기관")
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
    signature = (scope_mode, tuple(selected_doc_ids))
    if st.session_state.get("global_scope") != signature:
        st.session_state["global_scope"] = signature
        st.session_state["rag_history"] = []
    st.session_state.setdefault("rag_history", [])

    if st.session_state["rag_history"]:
        for entry in st.session_state["rag_history"]:
            with st.chat_message("user"):
                st.write(entry["question"])
            with st.chat_message("assistant"):
                st.write(entry["answer"])
                st.caption(entry["caption"])
                if show_sources and entry.get("hits"):
                    with st.expander(f"검색 근거 {len(entry['hits'])}개"):
                        for number, hit in enumerate(entry["hits"], start=1):
                            st.markdown(f"**{number}. {hit.doc_id}** `{hit.matched_by}`")
                            st.text(str(hit.text)[:1200])

    example = st.selectbox(
        "예시 질문",
        (
            "",
            "최근 3개월 동안 공개된 공고 중 예산이 10억 미만인 공고를 모두 찾아줘.",
            "사업기간이 3개월 이내이고 예산이 10억 미만인 사업을 모두 찾아줘.",
            "입찰 참가자격과 평가 기준을 근거와 함께 비교해줘.",
        ),
    )
    question = st.text_area(
        "전체 RFP에 질문하기",
        value=example,
        height=110,
        placeholder="예: 예산이 5억 이상 20억 미만인 공고를 정리해줘.",
    )
    ask = st.button(
        "전체 문서에서 답변 찾기",
        type="primary",
        disabled=not question.strip() or not scope_ready or not model_ready,
        use_container_width=True,
    )
    if not scope_ready:
        st.info("검색할 문서를 한 개 이상 선택해 주세요.")
    if ask:
        started = time.perf_counter()
        try:
            with st.spinner("통합 RAG가 문서를 검색하고 답변을 생성하는 중입니다..."):
                active_index, active_chunks, active_catalog = _scoped_runtime(
                    runtime, selected_doc_ids if scope_mode != "all" else []
                )
                compound = answer_period_budget_query(
                    question.strip(), active_catalog, runtime["doc_metadata"], active_chunks
                )
                hits = active_index.hybrid_search(
                    question.strip(), k=10, candidate_k=20, expand_to_parent=True
                )
                if compound is not None:
                    answer = compound.answer
                    selected_visual: list[dict[str, Any]] = []
                    response_path = "복합 조건 필터"
                else:
                    retrieved = list(dict.fromkeys(str(hit.doc_id) for hit in hits))
                    selected_visual = select_visual_evidence(
                        question.strip(), retrieved, evidence_rows
                    )
                    answer = ask_rfp_v9(
                        question.strip(),
                        EvidenceOpenAI(client, selected_visual),
                        active_index,
                        active_chunks,
                        active_catalog,
                        model_name=model_name,
                    )
                    answer = clean_citation(answer, runtime["doc_ids"], selected_visual)
                    response_path = "통합 RAG 생성"
        except Exception as exc:  # noqa: BLE001
            st.exception(exc)
        else:
            elapsed = time.perf_counter() - started
            caption = (
                f"처리 경로: {response_path} · {provider}/{model_name} · "
                f"{elapsed:.1f}초 · VLM 근거 {len(selected_visual)}건"
            )
            st.session_state["rag_history"].append(
                {"question": question.strip(), "answer": answer, "caption": caption, "hits": hits}
            )
            st.rerun()

    if st.button("전체 문서 대화 지우기"):
        st.session_state["rag_history"] = []
        st.rerun()


def _render_document_review(
    runtime: dict[str, Any], client: Any, provider: str, model_name: str, model_ready: bool
) -> None:
    st.header("📄 문서 한 건 빠른 검토")
    st.caption("문서를 고른 뒤 11종 빠른 질문 또는 문서 범위 자유 질문을 사용합니다.")
    search = st.text_input("문서명 검색", placeholder="예: 한국철도공사")
    doc_ids = [doc_id for doc_id, _name in runtime["catalog"]]
    if search.strip():
        doc_ids = [doc_id for doc_id in doc_ids if search.strip().lower() in doc_id.lower()]
    if not doc_ids:
        st.warning("검색 결과가 없습니다.")
        return
    selected_doc_id = st.selectbox(f"문서 ({len(doc_ids)}건)", doc_ids)
    if st.session_state.get("review_doc_id") != selected_doc_id:
        st.session_state["review_doc_id"] = selected_doc_id
        st.session_state["review_history"] = []
    st.session_state.setdefault("review_history", [])

    row, document_text = _selected_document(runtime, selected_doc_id)
    st.subheader(selected_doc_id)
    with st.chat_message("assistant"):
        st.write("자주 묻는 질문을 누르거나 아래에서 자유롭게 질문해 주세요.")
    quick_replies = _build_quick_replies()
    columns = st.columns(4)
    for index, quick in enumerate(quick_replies):
        if columns[index % 4].button(
            quick["label"], key=f"review_{quick['key']}", use_container_width=True
        ):
            candidates_fn = quick.get("candidates")
            candidates = candidates_fn(row, document_text) if candidates_fn else []
            st.session_state["review_history"].append(
                {
                    "kind": "button",
                    "question": quick["question"],
                    "answer": quick["render"](row, document_text),
                    "candidates": candidates,
                    "llm_answer": None,
                    "llm_matched": None,
                    "llm_error": None,
                }
            )
            st.rerun()

    for index, entry in enumerate(st.session_state["review_history"]):
        with st.chat_message("user"):
            st.write(entry["question"])
        with st.chat_message("assistant"):
            if entry.get("error"):
                st.error(entry["error"])
                continue
            st.markdown(entry["answer"])
            if entry["kind"] == "free" and entry.get("hits"):
                with st.expander(f"🔎 근거 보기 ({len(entry['hits'])}개)"):
                    for number, hit in enumerate(entry["hits"], start=1):
                        st.markdown(f"**{number}. {hit.doc_id}**")
                        st.text(str(hit.text)[:1200])
                continue
            candidates = entry.get("candidates") or []
            if candidates:
                with st.expander(f"🔎 후보 원문 보기 ({len(candidates)}개)"):
                    for number, candidate in enumerate(candidates, start=1):
                        st.markdown(f"**후보 {number}**")
                        st.text(_candidate_excerpt(document_text, str(candidate)))
                if entry.get("llm_answer"):
                    note = "확장 문맥 사용" if entry["llm_matched"] else "후보 문맥 사용"
                    st.info(f"🤖 **AI 요약** _({note})_\n\n{entry['llm_answer']}")
                elif entry.get("llm_error"):
                    st.error(f"AI 요약 실패: {entry['llm_error']}")
                    if st.button("다시 시도", key=f"retry_{index}"):
                        entry["llm_error"] = None
                        st.rerun()
                elif st.button(
                    "🤖 AI 요약 보기", key=f"summary_{index}", disabled=not model_ready
                ):
                    try:
                        with st.spinner("선택 문서의 후보 근거를 요약하는 중입니다..."):
                            summary, matched = generate_quick_answer(
                                client,
                                selected_doc_id,
                                entry["question"],
                                candidates,
                                model=model_name,
                            )
                    except Exception as exc:  # noqa: BLE001
                        entry["llm_error"] = str(exc)
                    else:
                        if summary:
                            entry["llm_answer"] = summary
                            entry["llm_matched"] = matched
                        else:
                            entry["llm_error"] = "모델이 답변을 생성하지 못했습니다."
                    st.rerun()

    free_question = st.chat_input(
        "이 문서에 대해 자유롭게 질문해보세요 (예: 제출 서류가 뭐가 필요해?)",
        disabled=not model_ready,
    )
    if free_question:
        try:
            with st.spinner("선택 문서에서 근거를 찾고 답변을 생성하는 중입니다..."):
                index, chunks, catalog = _scoped_runtime(runtime, [selected_doc_id])
                hits = index.hybrid_search(free_question, k=5, expand_to_parent=True)
                answer = ask_rfp_v9(
                    free_question, client, index, chunks, catalog, model_name=model_name
                )
                answer = clean_citation(answer, runtime["doc_ids"], [])
            entry = {
                "kind": "free",
                "question": free_question,
                "answer": answer,
                "hits": hits,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            entry = {
                "kind": "free",
                "question": free_question,
                "answer": "",
                "hits": [],
                "error": f"검색/답변 생성 실패: {exc}",
            }
        st.session_state["review_history"].append(entry)
        st.rerun()

    if st.button("🗑️ 문서 대화 지우기"):
        st.session_state["review_history"] = []
        st.rerun()
    with st.expander("ℹ️ 문서 빠른 검토 기능 안내"):
        st.markdown(
            "- 빠른 질문은 검증된 규칙 기반 후보 추출기를 사용하며 자동으로 정답을 확정하지 않습니다.\n"
            "- 후보가 있는 항목은 AI 요약을 선택적으로 호출할 수 있습니다.\n"
            "- 자유 질문은 선택한 문서 한 건만 검색하며 답변 아래에서 실제 검색 근거를 확인할 수 있습니다.\n"
            "- 예산·일정·발주기관·신청서식·하도급/공동수급·사업목적·참가자격·문의처·계약방식·계약보증금·평가배점을 지원합니다."
        )


def main() -> None:
    st.set_page_config(page_title="입찰메이트 RAG", page_icon="📄", layout="wide")
    st.title("📄 입찰메이트")
    with st.sidebar:
        st.header("시연 설정")
        app_mode = st.radio("기능", ("전체 문서 찾기", "문서 한 건 빠른 검토"))
        model_choice = st.selectbox(
            "생성 모델", _model_choices(), format_func=lambda value: MODEL_LABELS.get(value, value)
        )
        provider, model_name = _split_model_choice(model_choice)
        model_ready = provider != "future"
        if not model_ready:
            st.warning("로컬 모델은 백엔드 연결 전이라 실행할 수 없습니다.")
        use_visual = st.checkbox("기존 VLM 시각 근거 사용", value=True)
        show_sources = st.checkbox("검색 근거 표시", value=True)
        st.info(
            "VLM은 미리 생성한 Qwen3-VL 근거 캐시를 재사용합니다. "
            "새 이미지를 실시간 판독하는 데모는 아닙니다."
        )

    try:
        with st.spinner("검색 인덱스를 불러오는 중입니다..."):
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
    if app_mode == "전체 문서 찾기":
        _render_global_search(
            runtime, client, provider, model_name, model_ready, evidence_rows, show_sources
        )
    else:
        _render_document_review(runtime, client, provider, model_name, model_ready)


if __name__ == "__main__":
    main()
