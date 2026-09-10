from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from pathlib import Path
from typing import Protocol, Sequence

import streamlit as st

from midprojectrag.application import (
    AnswerResult,
    CatalogFilter,
    CatalogSearchResult,
    ConversationTurn,
    DocumentCard,
    RagApplicationService,
    RuntimeDescriptor,
    load_rag_application,
)


class QueryService(Protocol):
    runtime: RuntimeDescriptor

    def list_documents(self) -> tuple[DocumentCard, ...]: ...

    def list_document_cards(self) -> tuple[DocumentCard, ...]: ...

    def search_documents(self, filters: CatalogFilter) -> CatalogSearchResult: ...

    def get_document_card(self, doc_id: str) -> DocumentCard: ...

    def ask(
        self,
        *,
        question: str,
        history: Sequence[ConversationTurn] = (),
        doc_ids: Sequence[str] | None = None,
        approve_external_corpus_egress: bool = False,
    ) -> AnswerResult: ...


SAFE_ERROR_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
STARTUP_MESSAGES = {
    "runtime_config_load_failed": "Streamlit 런타임 설정 파일을 읽지 못했습니다.",
    "runtime_data_dir_missing": "private 데이터 디렉터리를 찾지 못했습니다.",
    "retrieval_manifest_hash_mismatch": "검색 manifest가 설정된 스냅샷과 다릅니다.",
    "chunks_file_hash_mismatch": "청크 파일이 설정된 스냅샷과 다릅니다.",
    "catalog_manifest_hash_mismatch": "표시용 메타데이터가 설정된 스냅샷과 다릅니다.",
    "correction_set_hash_mismatch": "메타데이터 감사 기록이 설정된 스냅샷과 다릅니다.",
    "correction_set_catalog_mismatch": "메타데이터와 감사 기록이 일치하지 않습니다.",
    "index_expected_config_mismatch": "인덱스와 모델·청크 설정이 일치하지 않습니다.",
}

STATE_LABELS = {
    "confirmed": "확인됨",
    "source_recorded": "데이터셋 기록",
    "source_not_stated": "원문 미기재",
    "not_applicable": "해당 없음",
    "unverified": "추가 확인 필요",
    "not_finalized": "미확정",
    "undisclosed": "비공개",
    "semantic_mismatch": "필드 의미 불일치",
    "suspect_sentinel": "의심 값",
    "unknown": "정보 없음",
}

FIELD_LABELS = {
    "notice_id_namespace": "공고 체계",
    "notice_number": "공고 번호",
    "notice_round": "공고 차수",
    "project_name": "사업명",
    "project_amount_raw": "사업 금액",
    "ordering_agency": "발주 기관",
    "published_at": "공개 일자",
    "bid_start_at": "입찰 시작",
    "bid_end_at": "입찰 마감",
    "bid_open_at": "개찰 일시",
    "proposal_evaluation_at": "제안서 평가",
    "source_format": "파일 형식",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _runtime_paths() -> tuple[Path, Path]:
    root = _repo_root()
    config_path = Path(
        os.getenv(
            "MIDPROJECTRAG_STREAMLIT_CONFIG",
            str(
                root
                / "configs"
                / "rag"
                / "api-small-nano-streamlit-refined98-page-v2.json"
            ),
        )
    )
    data_dir = Path(
        os.getenv("MIDPROJECTRAG_DATA_DIR", str(root / "resources" / "data_refined"))
    )
    return config_path, data_dir


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


@st.cache_resource(show_spinner=False)
def _cached_service(
    config_path: str, data_dir: str, config_sha256: str
) -> RagApplicationService:
    del config_sha256
    return load_rag_application(Path(config_path), Path(data_dir))


def _load_default_service() -> RagApplicationService:
    config_path, data_dir = _runtime_paths()
    try:
        config_sha256 = _file_sha256(config_path)
    except OSError as error:
        raise ValueError("runtime_config_load_failed") from error
    return _cached_service(str(config_path), str(data_dir), config_sha256)


def _safe_error_code(error: BaseException, fallback: str) -> str:
    value = str(error)
    return value if SAFE_ERROR_RE.fullmatch(value) else fallback


def _clear_conversation() -> None:
    st.session_state["messages"] = []
    st.session_state["history"] = []


def _fact_by_field(card: DocumentCard, field: str) -> object | None:
    for fact in getattr(card, "facts", ()):
        if getattr(fact, "field", None) == field:
            return fact
    return None


def _plain_text(value: object, fallback: str = "정보 없음", *, limit: int = 300) -> str:
    if value is None:
        return fallback
    normalized = unicodedata.normalize("NFC", str(value))
    cleaned = "".join(
        character
        for character in normalized
        if not unicodedata.category(character).startswith("C")
    )
    collapsed = " ".join(cleaned.split())
    return (collapsed or fallback)[:limit]


def _document_label(card: DocumentCard) -> str:
    project_name = _plain_text(card.project_name, "사업명 미상", limit=180)
    ordering_agency = _plain_text(card.ordering_agency, "발주기관 미상", limit=100)
    return f"{project_name} · {ordering_agency} · …{card.doc_id[-6:]}"


def _source_format_options(documents: Sequence[DocumentCard]) -> tuple[str, ...]:
    values: set[str] = set()
    for document in documents:
        fact = _fact_by_field(document, "source_format")
        value = getattr(fact, "normalized_value", None)
        if isinstance(value, str) and value:
            values.add(value)
    return tuple(sorted(values))


def _optional_nonnegative_int(value: str) -> int | None:
    stripped = value.strip()
    if not stripped:
        return None
    if not stripped.isdigit():
        raise ValueError("metadata_filter_invalid")
    return int(stripped)


def _metadata_filter(
    *,
    text: str,
    notice_id_namespace: str,
    notice_number: str,
    notice_round: str,
    agency: str,
    amount_min: str,
    amount_max: str,
    bid_end_from: str,
    bid_end_to: str,
    source_formats: Sequence[str],
) -> CatalogFilter:
    return CatalogFilter(
        text=text.strip() or None,
        notice_id_namespace=notice_id_namespace.strip() or None,
        notice_number=notice_number.strip() or None,
        notice_round=notice_round.strip() or None,
        agency=agency.strip() or None,
        amount_min_krw=_optional_nonnegative_int(amount_min),
        amount_max_krw=_optional_nonnegative_int(amount_max),
        bid_end_from=bid_end_from.strip() or None,
        bid_end_to=bid_end_to.strip() or None,
        source_formats=tuple(source_formats),
    )


def _metadata_lines(facts: Sequence[object]) -> list[str]:
    lines: list[str] = []
    for fact in facts:
        field = getattr(fact, "field", "")
        if field in {"project_name", "ordering_agency"}:
            continue
        state = str(getattr(fact, "state", "unknown"))
        value = getattr(fact, "value", None)
        display = (
            _plain_text(value)
            if value not in {None, ""}
            else STATE_LABELS.get(state, state)
        )
        evidence = tuple(getattr(fact, "evidence", ()))
        evidence_kinds = sorted(
            {
                str(getattr(item, "source_type", ""))
                for item in evidence
                if getattr(item, "source_type", "")
            }
        )
        checked_at = getattr(fact, "checked_at", None)
        audit = STATE_LABELS.get(state, state)
        evidence_label = ", ".join(evidence_kinds) if evidence_kinds else "catalog_record"
        checked_label = f" · {checked_at}" if checked_at else ""
        lines.append(
            f"{FIELD_LABELS.get(field, field)}: {display} [{audit}; {evidence_label}{checked_label}]"
        )
    return lines


def _render_metadata_card(card: DocumentCard) -> None:
    with st.container(border=True):
        st.text(_document_label(card))
        lines = _metadata_lines(getattr(card, "facts", ()))
        if lines:
            st.text("\n".join(lines))


def _locator(citation: object) -> str:
    page_start = getattr(citation, "page_start")
    page_end = getattr(citation, "page_end")
    if page_start is None:
        source_locator = _plain_text(
            getattr(citation, "source_locator", None),
            "",
            limit=1_000,
        )
        if source_locator:
            return f"구조 위치: {source_locator}"
        return "페이지 정보 없음"
    if page_end is None or page_end == page_start:
        return f"p.{page_start}"
    return f"pp.{page_start}–{page_end}"


def _render_assistant(message: dict[str, object]) -> None:
    status = message["status"]
    content = str(message["content"])
    if status == "answered":
        st.markdown(content)
    elif status == "abstained":
        st.warning(content)
        detail = message.get("detail")
        if detail:
            st.caption(str(detail))
    else:
        st.error(content)
    citations = message.get("citations", ())
    if citations:
        with st.expander(f"근거 문서 {len(citations)}건", expanded=True):
            for index, citation in enumerate(citations, start=1):
                section_path = getattr(citation, "section_path")
                section = " › ".join(section_path) if section_path else "섹션 정보 없음"
                st.text(
                    f"{index}. {getattr(citation, 'project_name')}\n"
                    f"{getattr(citation, 'ordering_agency')} · {_locator(citation)} · {section}"
                )
                metadata_lines = _metadata_lines(
                    getattr(getattr(citation, "metadata_card", None), "facts", ())
                )
                if metadata_lines:
                    st.caption("교정 메타데이터 (본문 페이지 인용과 별도)")
                    st.text("\n".join(metadata_lines))
    with st.expander("실행 정보"):
        columns = st.columns(4)
        columns[0].metric("검색", int(message["retrieval_count"]))
        columns[1].metric("인용", len(citations))
        columns[2].metric("총 지연", f"{float(message['total_ms']):,.0f} ms")
        columns[3].metric("비용", f"${float(message['cost_usd']):.6f}")
        cache_label = "hit" if message["cache_hit"] else "miss"
        st.caption(f"query embedding cache: {cache_label}")


def _assistant_message(result: AnswerResult) -> dict[str, object]:
    if result.status == "error":
        content = result.error_message or "검색 요청을 처리하지 못했습니다."
        detail = None
    else:
        content = result.answer
        detail = result.abstention_detail
    return {
        "role": "assistant",
        "status": result.status,
        "content": content,
        "detail": detail,
        "citations": result.citations,
        "retrieval_count": result.retrieval_count,
        "total_ms": result.total_ms,
        "cost_usd": result.cost_usd,
        "cache_hit": result.cache_hit,
    }


def main(service: QueryService | None = None) -> None:
    st.set_page_config(page_title="입찰메이트 RAG", page_icon="📑", layout="wide")
    st.title("입찰메이트 RAG 베이스라인")
    if service is None:
        try:
            with st.spinner("검증된 검색 인덱스를 불러오는 중입니다…"):
                service = _load_default_service()
        except Exception as error:
            code = _safe_error_code(error, "application_startup_failed")
            st.error(STARTUP_MESSAGES.get(code, "앱을 준비하지 못했습니다. 구성 검증이 필요합니다."))
            st.caption(f"안전 오류 코드: `{code}`")
            st.stop()

    runtime = service.runtime
    st.caption(
        f"제안요청서 {runtime.document_count}건에서 답을 찾고, 실제 근거 페이지 또는 구조 위치를 함께 표시합니다."
    )
    documents = service.list_documents()
    document_by_id = {document.doc_id: document for document in documents}
    try:
        metadata_cards = service.list_document_cards()
    except (AttributeError, RuntimeError):
        metadata_cards = ()
    if "messages" not in st.session_state:
        _clear_conversation()
    st.sidebar.header("검색 설정")
    st.sidebar.success(
        f"{runtime.embedding_model} / {runtime.generator_model}", icon="✅"
    )
    st.sidebar.caption(
        f"dense top-{runtime.retrieval_top_k} · context {runtime.context_top_k} · "
        f"citation {runtime.max_citations} · 문서 {runtime.document_count}건"
    )
    scope_options = (
        ("explicit", "metadata") if metadata_cards else ("all", "explicit")
    )
    scope_mode = st.sidebar.radio(
        "문서 범위",
        scope_options,
        format_func=lambda value: {
            "all": "전체 문서",
            "explicit": "문서 직접 선택",
            "metadata": "조건으로 찾은 문서",
        }[value],
    )
    selected_doc_ids: list[str] = []
    if scope_mode == "explicit":
        selected_doc_ids = st.sidebar.multiselect(
            "검색할 문서 (최대 20건)",
            options=[document.doc_id for document in documents],
            format_func=lambda doc_id: _document_label(document_by_id[doc_id]),
            max_selections=20,
        )
    elif scope_mode == "metadata":
        st.sidebar.subheader("메타데이터 필터")
        filter_text = st.sidebar.text_input("사업명·기관·공고번호")
        notice_id_namespace = st.sidebar.text_input("공고 번호 체계")
        notice_number = st.sidebar.text_input("공고 번호")
        notice_round = st.sidebar.text_input("공고 차수")
        agency = st.sidebar.text_input("발주 기관")
        amount_min = st.sidebar.text_input("최소 사업 금액 (원)")
        amount_max = st.sidebar.text_input("최대 사업 금액 (원)")
        bid_end_from = st.sidebar.text_input("입찰 마감 시작일 (YYYY-MM-DD)")
        bid_end_to = st.sidebar.text_input("입찰 마감 종료일 (YYYY-MM-DD)")
        source_formats = st.sidebar.multiselect(
            "파일 형식",
            options=list(_source_format_options(metadata_cards)),
            key="metadata_source_formats",
        )
        filter_signature = (
            filter_text,
            notice_id_namespace,
            notice_number,
            notice_round,
            agency,
            amount_min,
            amount_max,
            bid_end_from,
            bid_end_to,
            tuple(source_formats),
        )
        previous_filter = st.session_state.get("metadata_filter_signature")
        if previous_filter is not None and previous_filter != filter_signature:
            st.session_state["metadata_doc_ids"] = []
            _clear_conversation()
            st.sidebar.info("필터가 바뀌어 선택 문서와 대화 맥락을 초기화했습니다.")
        st.session_state["metadata_filter_signature"] = filter_signature
        try:
            catalog_filter = _metadata_filter(
                text=filter_text,
                notice_id_namespace=notice_id_namespace,
                notice_number=notice_number,
                notice_round=notice_round,
                agency=agency,
                amount_min=amount_min,
                amount_max=amount_max,
                bid_end_from=bid_end_from,
                bid_end_to=bid_end_to,
                source_formats=source_formats,
            )
            search_result = service.search_documents(catalog_filter)
        except ValueError as error:
            code = _safe_error_code(error, "metadata_filter_invalid")
            st.sidebar.error("필터 값을 확인해 주세요.")
            st.sidebar.caption(f"안전 오류 코드: `{code}`")
            search_result = CatalogSearchResult(documents=(), total_count=0)
        st.sidebar.metric("조건 일치", search_result.total_count)
        if search_result.total_count > 20:
            st.sidebar.caption(
                "결과를 자동으로 자르지 않았습니다. 질문에 사용할 문서를 최대 20건 직접 고르거나 필터를 좁혀 주세요."
            )
        selected_doc_ids = st.sidebar.multiselect(
            "질문에 사용할 문서 (최대 20건)",
            options=[document.doc_id for document in search_result.documents],
            format_func=lambda doc_id: _document_label(document_by_id[doc_id]),
            max_selections=20,
            key="metadata_doc_ids",
        )
    egress_approved = st.sidebar.checkbox(
        "질문·대화 기록·검색 근거를 OpenAI API로 전송하는 데 동의합니다.",
        value=False,
        help=(
            "개인 API 키를 사용합니다. 검색에는 최근 대화 최대 4턴, 답변 생성에는 "
            "최근 대화 최대 6턴과 상위 근거 청크를 전송합니다."
        ),
    )
    scope_signature = (scope_mode, tuple(selected_doc_ids))
    previous_scope = st.session_state.get("scope_signature")
    if previous_scope is not None and previous_scope != scope_signature:
        _clear_conversation()
        st.sidebar.info("문서 범위가 바뀌어 대화 맥락을 초기화했습니다.")
    st.session_state["scope_signature"] = scope_signature
    if st.sidebar.button("대화 초기화", use_container_width=True):
        _clear_conversation()
        st.rerun()

    if selected_doc_ids and metadata_cards:
        st.subheader("선택 문서 메타데이터")
        st.caption("감사된 메타데이터 상태와 본문 페이지 인용은 서로 다른 근거입니다.")
        for doc_id in selected_doc_ids:
            _render_metadata_card(service.get_document_card(doc_id))

    for message in st.session_state["messages"]:
        with st.chat_message(str(message["role"])):
            if message["role"] == "user":
                st.markdown(str(message["content"]))
            else:
                _render_assistant(message)

    scope_ready = scope_mode == "all" or bool(selected_doc_ids)
    if not egress_approved:
        st.info("왼쪽에서 OpenAI 전송 동의를 확인하면 질문 입력이 활성화됩니다.")
    elif not scope_ready:
        st.info("검색할 문서를 한 건 이상 선택해 주세요.")
    prompt = st.chat_input(
        "예: 이 사업의 예산과 주요 요구사항을 근거와 함께 알려줘",
        max_chars=4_000,
        disabled=not (egress_approved and scope_ready),
    )
    if not prompt:
        return
    user_message = {"role": "user", "content": prompt}
    st.session_state["messages"].append(user_message)
    with st.chat_message("user"):
        st.markdown(prompt)
    try:
        with st.chat_message("assistant"):
            with st.spinner("문서를 검색하고 근거를 검증하는 중입니다…"):
                result = service.ask(
                    question=prompt,
                    history=tuple(st.session_state["history"]),
                    doc_ids=selected_doc_ids if scope_mode != "all" else None,
                    approve_external_corpus_egress=egress_approved,
                )
            assistant_message = _assistant_message(result)
            _render_assistant(assistant_message)
    except Exception as error:
        code = _safe_error_code(error, "application_query_failed")
        assistant_message = {
            "role": "assistant",
            "status": "error",
            "content": "요청을 안전하게 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
            "detail": None,
            "citations": (),
            "retrieval_count": 0,
            "total_ms": 0.0,
            "cost_usd": 0.0,
            "cache_hit": False,
        }
        with st.chat_message("assistant"):
            st.error(str(assistant_message["content"]))
            st.caption(f"안전 오류 코드: `{code}`")
        st.session_state["messages"].append(assistant_message)
        return
    st.session_state["messages"].append(assistant_message)
    if result.status in {"answered", "abstained"}:
        history = list(st.session_state["history"])
        history.extend(
            [
                ConversationTurn(role="user", content=prompt),
                ConversationTurn(
                    role="assistant",
                    content=result.answer,
                    cited_doc_ids=result.cited_doc_ids,
                ),
            ]
        )
        st.session_state["history"] = history[-20:]


if __name__ == "__main__":
    main()
