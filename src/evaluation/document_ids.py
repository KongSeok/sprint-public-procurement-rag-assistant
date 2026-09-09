"""평가 실행에서 사용하는 문서 ID 추출 유틸리티."""
from __future__ import annotations

import re


_CONTEXT_DOCUMENT_LINE_RE = re.compile(r"^\[문서:\s*(.*)\]\s*$", re.MULTILINE)


def extract_context_doc_ids(context: str | None) -> list[str]:
    """컨텍스트의 ``[문서: doc_id]`` 표식에서 전체 문서 ID를 추출한다.

    줄 끝의 마지막 대괄호만 표식의 닫는 괄호로 취급하므로 파일명 내부의
    ``[재공고]``·``[긴급]`` 같은 태그를 보존한다.
    """
    if not context:
        return []
    values = (match.strip() for match in _CONTEXT_DOCUMENT_LINE_RE.findall(str(context)))
    return list(dict.fromkeys(value for value in values if value))
