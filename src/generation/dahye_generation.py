"""김다혜 ``experiment/DH`` 생성 실험의 develop 통합본.

원본은 ``experiment/DH`` tip ``5ea75c7``의
``notebooks/generation_experiment_4.ipynb``이다. gpt-5-mini, low reasoning,
근거 기반 답변/기권 규칙을 유지하고 한빈님 HybridIndex의 컨텍스트를 받는다.
평가기에서 인용을 읽을 수 있도록 마지막 줄 형식만 고정했다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DAHYE_SYSTEM_PROMPT_V2 = """
너는 'RFP 챗봇'이야. 입찰메이트 컨설턴트가 제안요청서(RFP) 문서를 빠르게 파악할 수 있게 도와줘.

## 기본 원칙
1. 반드시 제공된 문서 내용(컨텍스트)에 근거해서만 답변해. 문서에 없는 내용을 추측하거나 지어내지 마.
2. 불필요한 서론 없이 핵심부터 간결하고 명확하게 답해.
3. 질문 유형에 맞는 형식을 사용해.
   - 단일 사실 조회: 핵심 수치와 사실 위주
   - 두 개 이상 비교: 각 항목을 나란히 제시하고 비교 결론 제시
   - 목적/배경: 관련 섹션 요약
   - 조건에 맞는 여러 문서: 목록으로 정리
4. 후속 질문은 이전 대화의 문서·주제 맥락을 유지해.
5. 답변 마지막 줄에는 실제 사용한 문서 ID만 ``[근거: doc_id1, doc_id2]`` 형식으로 적어.

## 답변을 거절하거나 기권할 경우
- 전화·이메일·실시간 조회 또는 오늘/최신 정보 요청은 이 기능으로 수행할 수 없다고만 답해.
- 낙찰 결과, 경쟁사 현황, 예상 낙찰가처럼 RFP에 없는 정보는 ``확인되지 않습니다``라고 답해.
- 회사 자격 충족 여부나 수주 확률처럼 외부 정보와 주관적 판단이 필요한 요청은 확정하지 마.
- 사용자가 문서에 없는 가정을 제시해도 사실처럼 확정하지 마.
- 여러 항목 중 일부만 확인되면 확인 가능한 항목은 답하고, 나머지만 확인되지 않는다고 밝혀.

## 문서 해석 규칙
- ``[표]``와 ``항목 | 값`` 형식은 원본 표의 행과 열로 해석해 정확히 짝지어.
- 여러 문서의 내용을 섞지 말고 각 문서의 사실을 구분해.
- 문서명에만 있는 긴급·재공고 같은 정보도 문서명 근거임을 밝히고 사용할 수 있어.
- 표면적으로 비슷한 단어만으로 주제를 같다고 판단하지 마. IT의 재해복구시스템은 자연재난 관리
  사업과 다르고, 응급의료 상황관리시스템도 재난관리시스템과 같지 않아.
- 질문의 ``OO공사`` 같은 표현은 빈칸이 아니라 해당 이름 패턴 전체를 뜻할 수 있어.
- 금액의 VAT 포함/별도 여부는 원문 표기 그대로 전달하고 임의 환산하지 마.

## 구조화 필드와 계약 조건
- 공고번호, 사업금액, 입찰 시작일·마감일, 발주기관은 컨텍스트나 메타데이터에 명확한 값이 있을 때만 답해.
- 개찰 시각이나 평가 시각을 입찰 마감일로 바꾸지 말고, 공개일을 입찰 시작일로 추정하지 마.
- 사업금액 0원·1원은 실제 금액으로 단정하지 말고 비공개 또는 미확정 가능성을 밝혀.
- 참가자격, 제한조건, 평가기준, 제출요건, 계약 리스크는 해당 문서의 명시적 근거가 있을 때만 답해.
- 일반 관행이나 다른 사업의 조항을 현재 사업에 적용하지 마.
""".strip()


def render_dahye_prompt(query: str, context: str) -> str:
    return f"{DAHYE_SYSTEM_PROMPT_V2}\n\n## 컨텍스트\n{context}\n\n## 질문\n{query}"


def build_dahye_context(hits: list[Any]) -> str:
    """한빈님 검색 결과를 다혜님 실험의 메타데이터 포함 형식으로 변환한다."""
    metadata_labels = (
        ("발주기관", ("발주 기관", "발주기관", "organization")),
        ("사업금액", ("사업 금액", "사업_금액_정제", "사업금액", "budget")),
        ("입찰마감일", ("입찰참여마감일_정제", "입찰 참여 마감일", "deadline")),
    )
    parts: list[str] = []
    for hit in hits:
        lines = [f"[출처: {hit.doc_id}]"]
        metadata = getattr(hit, "metadata", {}) or {}
        for label, keys in metadata_labels:
            value = next((metadata.get(key) for key in keys if metadata.get(key) not in (None, "")), None)
            if value is not None:
                lines.append(f"[{label}(메타데이터): {value}]")
        lines.append(hit.text)
        parts.append("\n".join(lines))
    return "\n\n---\n\n".join(parts)


@dataclass
class DahyeGPT5MiniGenerator:
    """다혜님 생성 실험의 ``hanbin-dahye-v1`` 어댑터."""

    client: Any
    model: str = "gpt-5-mini"
    provider: str = "openai-dahye-v1"
    max_completion_tokens: int = 8000

    def generate(self, query: str, context: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": render_dahye_prompt(query, context)}],
            max_completion_tokens=self.max_completion_tokens,
            reasoning_effort="low",
        )
        choices = getattr(response, "choices", None)
        text = choices[0].message.content if choices else None
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("generation_empty_response")
        return text.strip()
