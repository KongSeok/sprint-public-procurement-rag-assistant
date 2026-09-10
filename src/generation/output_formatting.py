"""생성 답변의 표시 형식을 결정론적으로 정리하는 후처리 도구."""
from __future__ import annotations

import re


_CITATION_RE = re.compile(
    r"\[\s*근거\s*:\s*(.+)\](?=\s*(?:\n|$))", re.IGNORECASE
)


def move_citation_to_end(answer: str | None) -> str | None:
    """기존 근거 블록을 보존하면서 답변의 마지막 줄로 이동한다.

    근거가 없는 답변은 변경하지 않는다. 여러 근거 블록이 있으면 문서 순서를
    유지하면서 중복을 제거해 하나의 블록으로 합친다.
    """
    if answer is None:
        return None
    text = str(answer)
    matches = list(_CITATION_RE.finditer(text))
    if not matches:
        return text

    doc_ids: list[str] = []
    for match in matches:
        for value in match.group(1).split(","):
            doc_id = value.strip()
            if doc_id and doc_id not in doc_ids:
                doc_ids.append(doc_id)

    body = _CITATION_RE.sub("", text)
    body = re.sub(r"[ \t]+\n", "\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    citation = f"[근거: {', '.join(doc_ids)}]"
    return f"{body}\n\n{citation}" if body else citation
