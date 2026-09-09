#!/usr/bin/env python3
"""결정론적 골든셋 채점기 v3.

v2의 실행상태/기권/Set/인용 채점 구조를 유지하면서 다음을 보완한다.
1. 실제 기권 표현인 ``확인되지 않습니다``를 정상 인식한다.
2. Kiwi 형태소 분석으로 한국어 조사와 용언 어미 차이를 완화한다.
3. ``100분의 N``/``N%``, ``20억``/``20억원``을 제한적으로 동치 처리한다.

의미 채점기는 아니다. 골든셋이나 원본 답변은 수정하지 않는다.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import unicodedata
from pathlib import Path
from typing import Any


SCORER_VERSION = "3.0.1"
SCORING_SCHEMA_VERSION = "3.0"

_BASE_PATH = Path(__file__).with_name("_base.py")
if not _BASE_PATH.exists():
    _BASE_PATH = Path(__file__).resolve().parents[3] / "scoring_v2" / "evaluate_golden_testset_v2.py"
if not _BASE_PATH.exists():
    raise FileNotFoundError(
        "채점기 v3 기반 모듈을 찾을 수 없습니다. src/evaluation/scoring_v3 폴더 전체를 확인하세요."
    )
_SPEC = importlib.util.spec_from_file_location("_scorer_v2_base", _BASE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"채점기 v2 로더 생성 실패: {_BASE_PATH}")
_BASE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_BASE)
_V2_OPTION_MATCHES = _BASE.option_matches


read_jsonl = _BASE.read_jsonl
write_jsonl = _BASE.write_jsonl
select_rows = _BASE.select_rows
normalize_text = _BASE.normalize_text
string_list = _BASE.string_list
item_id = _BASE.item_id

_TRAILING_CITATION_RE = re.compile(
    r"(?:\n|\s)+(?:\[?\s*(?:근거(?:\s*문서)?|출처)\s*[:：]).*$",
    re.IGNORECASE | re.DOTALL,
)
_ABSTENTION_RE = re.compile(
    r"(?:"
    r"알\s*수\s*없|확인\s*(?:(?:할\s*수)?\s*없|되지\s*않)|"
    r"판단\s*(?:을\s*)?(?:해\s*드릴\s*)?(?:할\s*수|수)?\s*없|"
    r"판정\s*(?:을\s*)?(?:해\s*드릴\s*)?(?:할\s*수|수)?\s*없|"
    r"확정\s*(?:할\s*수)?\s*없|계산\s*(?:할\s*수)?\s*없|"
    r"예측\s*(?:할\s*수)?\s*없|제공\s*(?:(?:할\s*수)?\s*없|되지\s*않)|"
    r"수행\s*(?:할\s*수)?\s*없|답변\s*(?:할\s*수)?\s*없|"
    r"명시\s*(?:되어\s*)?(?:있지\s*않|되지\s*않)|"
    r"정보(?:가|는)?\s*없|자료(?:가|는)?\s*없|불가능"
    r")",
    re.IGNORECASE,
)


def classify_response(answer: str | None, execution_error: str | None = None) -> dict[str, Any]:
    """완전 기권, 부분 답변, 빈 응답, 실행 오류를 분리한다."""
    if execution_error and str(execution_error).strip():
        return {"response_status": "execution_error", "status_method": "explicit_error"}
    if answer is None or not str(answer).strip():
        return {"response_status": "empty_response", "status_method": "empty_guard"}

    body = _BASE._CITATION_LINE_RE.sub("", str(answer)).strip()
    body = _TRAILING_CITATION_RE.sub("", body).strip()
    # 문장 분리 전에 괄호 속 출처 파일명을 지운다. 파일명의 '.hwp' 마침표가
    # 문장 경계로 오인되어 '2025년...' 조각이 실질 답변처럼 남는 것을 막는다.
    body = re.sub(
        r"\([^)]*\.(?:hwp|hwpx|pdf|docx?)[^)]*\)", " ", body, flags=re.IGNORECASE
    )
    if not _ABSTENTION_RE.search(body):
        return {"response_status": "answered", "status_method": "heuristic_v3"}

    # 기권 문장이 아닌 별도 문장에 숫자나 실질 답변이 있으면 부분 답변이다.
    substantive = False
    for sentence in re.split(r"[.!?。！？\n]+", body):
        sentence = sentence.strip()
        if not sentence:
            continue
        if _ABSTENTION_RE.search(sentence):
            residue = _ABSTENTION_RE.sub(" ", sentence)
            # 기권 이유에 붙은 괄호 속 문서명(예: '2025년 ...hwp')은
            # 실질 답변 숫자가 아니다. 먼저 제거한 뒤 수치 답변 여부를 본다.
            residue = re.sub(r"\([^)]*\)", " ", residue)
            if re.search(r"\d[\d,.]*\s*(?:원|억|만|%|개월|일)", residue):
                substantive = True
            continue
        residue = normalize_text(sentence)
        if re.search(r"\d", residue) or len(residue) >= 15:
            substantive = True
    return {
        "response_status": "partial_answer" if substantive else "abstained",
        "status_method": "heuristic_v3",
    }


def canonicalize_equivalents(value: Any) -> str:
    """검증된 제한 범위의 표기 동치만 변환한다."""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(
        r"100\s*분의\s*(\d+(?:\.\d+)?)",
        lambda match: f"{match.group(1)}%",
        text,
    )
    # 한국어 금액 단위 바로 뒤의 '원' 유무만 동치 처리한다.
    text = re.sub(r"(\d+(?:\.\d+)?\s*(?:조|억|만|천))\s*원", r"\1", text)
    # 참여 가능/불가능의 자주 관찰된 서술형만 제한적으로 통일한다.
    text = re.sub(r"(참여|참가)\s*(?:할\s*)?수\s*없(?:습니다|다|음)?", r"\1 불가능", text)
    text = re.sub(r"(참여|참가)\s*(?:할\s*)?수\s*있(?:습니다|다|음)?", r"\1 가능", text)
    return text


_KIWI = None


def _kiwi():
    global _KIWI
    if _KIWI is None:
        try:
            from kiwipiepy import Kiwi
        except ImportError as exc:
            raise RuntimeError(
                "채점기 v3는 안전한 한국어 조사/어미 처리를 위해 kiwipiepy가 필요합니다. "
                "프로젝트 requirements를 설치하세요."
            ) from exc
        _KIWI = Kiwi()
    return _KIWI


def morph_tokens(value: Any) -> list[str]:
    """조사(J*)와 어미(E*)를 버리고 명사·용언의 형태소를 비교한다."""
    text = canonicalize_equivalents(value)
    tokens: list[str] = []
    for token in _kiwi().tokenize(text):
        tag = str(token.tag)
        if tag.startswith(("J", "E", "S")):
            continue
        if not tag.startswith(("N", "V", "M", "X", "SL", "SH", "SN")):
            continue
        form = normalize_text(token.form)
        if not form:
            continue
        if len(form) >= 2 or tag.startswith(("V", "SN")) or form.isascii():
            tokens.append(form)
    return tokens


def _percent_values(value: Any) -> set[str]:
    text = canonicalize_equivalents(value).replace(",", "")
    return {m.group(1).lstrip("0") or "0" for m in re.finditer(r"(\d+(?:\.\d+)?)\s*%", text)}


def _money_values(value: Any) -> set[tuple[str, str]]:
    text = canonicalize_equivalents(value).replace(",", "")
    return {
        (m.group(1).lstrip("0") or "0", m.group(2))
        for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(조|억|만|천)", text)
    }


def _comparators(value: Any) -> set[str]:
    return set(re.findall(r"이상|이하|초과|미만", canonicalize_equivalents(value)))


def _contradicts(option: Any, answer: Any) -> bool:
    option_text = re.sub(r"\s+", "", canonicalize_equivalents(option))
    answer_text = re.sub(r"\s+", "", canonicalize_equivalents(answer))
    pairs = (
        ("참여가능", "참여불가능"),
        ("참가가능", "참가불가능"),
        ("포함", "미포함"),
        ("충족", "미충족"),
    )
    return any(positive in option_text and negative in answer_text for positive, negative in pairs)


def option_matches(answer: str, option: str, token_threshold: float = 1.0) -> bool:
    """형태소와 수치 동치를 이용하는 결정론적 어휘 보조 채점."""
    answer_equiv = canonicalize_equivalents(answer)
    option_equiv = canonicalize_equivalents(option)
    if _contradicts(option_equiv, answer_equiv):
        return False

    option_comparators = _comparators(option_equiv)
    if option_comparators and not option_comparators.issubset(_comparators(answer_equiv)):
        return False
    # 일반 수치도 반드시 보존한다. 이를 생략하면 "본문 200페이지"를 단순히
    # "본문 페이지"라고만 답해도 형태소가 겹쳐 통과하는 오탐이 생긴다.
    option_numbers = _BASE._number_keys(option_equiv)
    if option_numbers and not option_numbers.issubset(_BASE._number_keys(answer_equiv)):
        return False
    option_percent = _percent_values(option_equiv)
    if option_percent and not option_percent.issubset(_percent_values(answer_equiv)):
        return False
    option_money = _money_values(option_equiv)
    if option_money and not option_money.issubset(_money_values(answer_equiv)):
        return False

    option_norm = normalize_text(option_equiv)
    answer_norm = normalize_text(answer_equiv)
    if option_norm and option_norm in answer_norm:
        return True

    # v2에서 이미 인정하던 표현은 그대로 보존한다. v3의 형태소 비교는
    # 기존 판정을 대체하는 것이 아니라, 조사/어미 차이로 놓친 경우만
    # 추가로 구제하는 보수적인 fallback이다.
    if _V2_OPTION_MATCHES(answer_equiv, option_equiv):
        return True

    required_tokens = morph_tokens(option_equiv)
    if not required_tokens:
        return bool(option_percent or option_money or _BASE._date_keys(option_equiv))
    answer_tokens = set(morph_tokens(answer_equiv))
    matched = sum(token in answer_tokens for token in required_tokens)
    return matched / len(required_tokens) >= token_threshold


def _configure_base() -> None:
    _BASE.SCORER_VERSION = SCORER_VERSION
    _BASE.SCORING_SCHEMA_VERSION = SCORING_SCHEMA_VERSION
    _BASE.classify_response = classify_response
    _BASE.option_matches = option_matches


def score_item(row: dict[str, Any], prediction: dict[str, Any]) -> dict[str, Any]:
    _configure_base()
    return _BASE.score_item(row, prediction)


def evaluate(
    golden_rows: list[dict[str, Any]], prediction_rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    _configure_base()
    details, summary = _BASE.evaluate(golden_rows, prediction_rows)
    summary["scorer_version"] = SCORER_VERSION
    summary["scoring_schema_version"] = SCORING_SCHEMA_VERSION
    summary["normalization"] = {
        "korean": "Kiwi POS-based josa/eomi removal",
        "percent": "100분의 N == N%",
        "money": "한국어 금액 단위 뒤의 원 표기 선택 허용",
        "comparators_preserved": ["이상", "이하", "초과", "미만"],
    }
    summary["limitations"] = [
        "lexical_fact_score는 의미 채점이 아닌 결정론적 보조지표입니다.",
        "형태소 정규화로 해결되지 않는 동의 표현은 골든셋 variant 또는 의미 채점이 필요합니다.",
        "partial_answer는 heuristic_v3 규칙 판정입니다.",
        "LLM correctness/faithfulness/completeness는 포함되지 않았습니다.",
    ]
    return details, summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="골든셋 공용 결정론적 채점기 v3")
    parser.add_argument("--golden", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--details-output", type=Path)
    parser.add_argument("--include-disabled", action="store_true")
    parser.add_argument("--task-type", default="all")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    golden = select_rows(read_jsonl(args.golden), args.task_type, args.include_disabled)
    predictions = read_jsonl(args.predictions)
    details, summary = evaluate(golden, predictions)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.details_output:
        write_jsonl(args.details_output, details)


if __name__ == "__main__":
    main()
