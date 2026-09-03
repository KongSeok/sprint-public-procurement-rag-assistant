"""Conservative lexical/numeric scoring, not a substitute for semantic judging.

Money/date normalization is exact. Particle matching is deliberately narrow;
unresolved paraphrases are left for the separately reported semantic evaluator.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import re
import unicodedata
from typing import Sequence

SCORER_VERSION = "bidfit-deterministic-v1-rc0"
_DATE = re.compile(r"(?<!\d)(\d{4})\s*(?:[-./]|년)\s*(\d{1,2})\s*(?:[-./]|월)\s*(\d{1,2})(?:\s*일)?(?!\d)")
_MONEY = re.compile(r"(?<![\w:])([+-]?(?:\d+(?:\.\d+)?\s*(?:조|억|천만|백만|십만|만|천|백|십)?\s*)+)원")
_PART = re.compile(r"(\d+(?:\.\d+)?)\s*(조|억|천만|백만|십만|만|천|백|십)?")
_UNITS = {"조": 10**12, "억": 10**8, "천만": 10**7, "백만": 10**6, "십만": 10**5, "만": 10**4, "천": 1000, "백": 100, "십": 10}
_TOKEN = re.compile(r"date:\d{4}-\d{2}-\d{2}|(?:money|percent):[+-]?\d+(?:\.\d+)?|[가-힣a-z_][가-힣a-z_0-9-]*|[+-]?\d+(?:\.\d+)?")
_PARTICLES = ("으로는", "에서는", "에게는", "으로", "에서", "에게", "까지", "부터", "은", "는", "이", "가", "을", "를", "와", "과", "의", "에", "도", "로")
_POLAR = re.compile(r"허용|가능|포함|의무|필수|인정|승인|불가|불허|금지|제외|아님|아니|않")
_NEGATION = re.compile(r"아님|아닙|아니|않")
_NEGATIVE_BASE = re.compile(r"불가|불허|불가능|금지|제외|미포함")
_UNKNOWN = re.compile(r"확인.{0,10}없|알.{0,6}없|근거.{0,10}부족|정보.{0,10}없|미확인|미기재|명시.{0,8}않|찾.{0,8}없")
_QUANTITY_LABELS = frozenset({"금액", "사업금액", "계약금액", "기간", "예산", "사업비", "시작", "마감", "일자", "시작일", "마감일"})


def _decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")


def normalize_text(text: str) -> str:
    if not isinstance(text, str):
        raise ValueError("answer_must_be_text")
    value = unicodedata.normalize("NFC", text).lower()
    value = re.sub(r"(?<!\d)([+-]?\d{1,3}(?:,\d{3})+)(?!\d)", lambda m: m[1].replace(",", ""), value)

    def normalize_date(match):
        try:
            return " date:" + date(*map(int, match.groups())).isoformat() + " "
        except ValueError:
            return match[0]  # Invalid dates are not repaired or guessed.

    value = _DATE.sub(normalize_date, value)

    def normalize_money(match):
        body = match[1].strip()
        sign = -1 if body.startswith("-") else 1
        parts = _PART.findall(body.lstrip("+-"))
        if not parts or any(not unit for _, unit in parts[:-1]):
            return match[0]  # "100 200원" is not a valid additive money expression.
        try:
            result = sum((Decimal(number) * _UNITS.get(unit, 1) for number, unit in parts), Decimal(0))
            return " money:" + _decimal(sign * result) + " "
        except InvalidOperation:
            return match[0]

    value = _MONEY.sub(normalize_money, value)
    value = re.sub(r"(?<![\w:])([+-]?\d+(?:\.\d+)?)\s*%", lambda m: " percent:" + _decimal(Decimal(m[1])) + " ", value)
    return re.sub(r"[ \t]+", " ", value).strip()


def _tokens(text: str) -> tuple[str, ...]:
    result = []
    for token in _TOKEN.findall(text):
        if token in _PARTICLES or token in {"입니다", "이다"}:
            continue
        if re.fullmatch(r"[가-힣]+", token):
            for ending in _PARTICLES:
                if token.endswith(ending) and len(token) - len(ending) >= 2:
                    token = token[:-len(ending)]
                    break
        result.append(token)
    return tuple(result)


def _clauses(text: str) -> tuple[str, ...]:
    return tuple(v.strip() for v in re.split(r"[\n;,]|(?<!\d)\.(?!\d)|(?:이며|이고|이지만|하지만|다만|반면)", text) if v.strip())


def _numeric(token: str) -> bool:
    return token.startswith(("money:", "date:", "percent:")) or bool(re.fullmatch(r"[+-]?\d+(?:\.\d+)?", token))


def _bindings(tokens: tuple[str, ...]) -> set[tuple[str, str]]:
    """Bind quantities to adjacent labels; do not accept A/B value swaps."""
    pairs = set()
    for i, token in enumerate(tokens):
        if not _numeric(token):
            continue
        neighbors = list(reversed(tokens[:i])) if i and not _numeric(tokens[i - 1]) else list(tokens[i + 1:])
        for label in neighbors:
            if _numeric(label) or label in {"중", "그리고"}:
                break
            pairs.add((label, token))
            if label not in _QUANTITY_LABELS:
                break
    return pairs


def fact_matches(answer: str, fact: str) -> bool:
    """Order-insensitive terms within a clause; numeric bindings/polarity retained."""
    raw_fact = unicodedata.normalize("NFC", fact).lower().strip()
    if re.search(r"\.(?:hwp|hwpx|pdf|docx|xlsx)$", raw_fact):
        raw_answer = unicodedata.normalize("NFC", answer).lower()
        return bool(re.search(r"(?<![\w.\]\[()\-])" + re.escape(raw_fact) + r"(?![\w.\-])", raw_answer))
    expected, actual = normalize_text(fact), normalize_text(answer)
    if not expected:
        return False
    required = _tokens(expected)
    if not required:
        return False
    for clause in _clauses(actual):
        tokens = _tokens(clause)
        if _UNKNOWN.search(clause):
            continue  # A question about a fact is not an assertion of that fact.
        if not set(required) <= set(tokens):
            continue
        expected_polarity = bool(_NEGATIVE_BASE.search(expected)) ^ (len(_NEGATION.findall(expected)) % 2 == 1)
        actual_polarity = bool(_NEGATIVE_BASE.search(clause)) ^ (len(_NEGATION.findall(clause)) % 2 == 1)
        if (_POLAR.search(expected) or _NEGATION.search(clause)) and expected_polarity != actual_polarity:
            continue
        has_number = any(_numeric(t) for t in required)
        if has_number:
            if not _bindings(required) <= _bindings(tokens):
                continue
        return True
    return False


@dataclass(frozen=True)
class AnswerScore:
    scorer_version: str
    fact_hits: tuple[bool, ...]
    fact_coverage: float | None
    answer_state: str
    reported_status: str | None
    evaluation_kind: str = "deterministic_heuristic_not_semantic"

    def to_dict(self) -> dict:
        return asdict(self)


def score_answer(answer: str, fact_groups: Sequence[Sequence[str] | str], *, status: str | None = None) -> AnswerScore:
    if isinstance(fact_groups, (str, bytes)):
        raise ValueError("fact_groups_must_be_sequence")
    hits = []
    for group in fact_groups:
        alternatives = (group,) if isinstance(group, str) else tuple(group)
        if not alternatives or any(not isinstance(f, str) or not f.strip() for f in alternatives):
            raise ValueError("invalid_fact_group")
        hits.append(any(fact_matches(answer, fact) for fact in alternatives))
    clauses = _clauses(normalize_text(answer))
    unknown = tuple(bool(_UNKNOWN.search(c)) for c in clauses)
    if status in {"error", "failed", "unavailable"}:
        state = "error"
    elif any(unknown):
        state = "partial_abstention" if any(not flag for flag in unknown) else "abstained"
    elif status in {"abstained", "abstain"}:
        state = "abstained"
    else:
        state = "answered" if answer.strip() else "empty"
    return AnswerScore(SCORER_VERSION, tuple(hits), sum(hits) / len(hits) if hits else None, state, status)
