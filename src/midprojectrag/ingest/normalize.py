from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any


COPY_PREFIX = "Copy of "


def normalize_filename(value: str) -> str:
    filename = value.strip()
    if filename.startswith(COPY_PREFIX):
        filename = filename[len(COPY_PREFIX) :]
    return unicodedata.normalize("NFC", filename)


def clean_cell(value: Any) -> str:
    if value is None:
        return ""
    return unicodedata.normalize("NFC", str(value).strip())


def normalize_amount(raw_value: str) -> tuple[str | None, list[str]]:
    value = clean_cell(raw_value)
    if not value:
        return None, ["amount_missing"]

    compact = re.sub(r"[,_\s원]", "", value)
    try:
        number = Decimal(compact)
    except InvalidOperation:
        return None, ["amount_invalid"]

    warnings: list[str] = []
    if number == 0:
        warnings.append("amount_sentinel_zero")
    elif number == 1:
        warnings.append("amount_sentinel_one")

    normalized = format(number, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized, warnings
