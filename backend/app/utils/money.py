"""Money helpers.

Authoritative monetary values are ALWAYS integer paise. Floating point is
only ever used for display formatting, never for arithmetic that feeds an
order total or a payment amount.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def rupees_to_paise(rupees: float | int | str) -> int:
    """Convert a rupee amount to integer paise using banker-safe rounding."""
    value = (Decimal(str(rupees)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(value)


def paise_to_rupees(paise: int) -> Decimal:
    """Convert integer paise to a Decimal rupee amount (2dp)."""
    return (Decimal(int(paise)) / 100).quantize(Decimal("0.01"))


def format_inr(paise: int) -> str:
    """Format integer paise as a human string, e.g. ``₹2,499.00``."""
    rupees = paise_to_rupees(paise)
    whole, _, frac = f"{rupees:.2f}".partition(".")
    sign = "-" if whole.startswith("-") else ""
    whole = whole.lstrip("-")
    # Indian grouping: last 3 digits, then groups of 2.
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        grouped = ",".join(parts) + "," + tail
    else:
        grouped = whole
    return f"{sign}₹{grouped}.{frac}"


def calculate_percentage(amount_paise: int, percent: float | int) -> int:
    """Return ``percent`` of ``amount_paise`` as integer paise (rounded)."""
    value = (Decimal(int(amount_paise)) * Decimal(str(percent)) / 100).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(value)
