"""Display formatting only. No arithmetic on reported figures happens here."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

DASH = "–"


def money(value: Any) -> str:
    """Whole currency units, thousands separators, negatives in brackets."""
    if value is None:
        return DASH
    rounded = int(Decimal(value).quantize(Decimal("1")))
    return f"({abs(rounded):,})" if rounded < 0 else f"{rounded:,}"


def money_compact(value: Any, currency: str = "") -> str:
    """Short form for running text: 1.30m, 40.5k."""
    amount = abs(Decimal(value))
    if amount >= 1_000_000:
        text = f"{amount / 1_000_000:.2f}m"
    elif amount >= 1_000:
        text = f"{amount / 1_000:.1f}k"
    else:
        text = f"{amount:.0f}"
    return f"{currency} {text}".strip()


def cell(value: Any, kind: str) -> str:
    if value is None or value == "":
        return "" if kind in ("text", "status") else DASH
    if kind == "money":
        return money(value)
    if kind == "pct":
        return f"{Decimal(value):.1f}%"
    if kind == "days":
        return f"{Decimal(value):.1f}"
    if kind == "ratio":
        return f"{Decimal(value):.2f}"
    if kind == "int":
        return f"{int(value):,}"
    if kind == "date" and isinstance(value, date):
        return value.isoformat()
    return str(value)


def is_negative(value: Any) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool) and value < 0
