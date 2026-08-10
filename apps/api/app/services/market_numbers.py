from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
from typing import Any


INVALID_NUMERIC_STRINGS = {
    "",
    "nan",
    "+nan",
    "-nan",
    "inf",
    "+inf",
    "-inf",
    "infinity",
    "+infinity",
    "-infinity",
    "none",
    "null",
}


def safe_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return Decimal(str(value))
    if isinstance(value, str):
        normalized = value.strip()
        if normalized.lower() in INVALID_NUMERIC_STRINGS:
            return None
        try:
            parsed = Decimal(normalized)
        except InvalidOperation:
            return None
        return parsed if parsed.is_finite() else None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def safe_int(value: Any) -> int | None:
    parsed = safe_decimal(value)
    if parsed is None:
        return None
    return int(parsed)
