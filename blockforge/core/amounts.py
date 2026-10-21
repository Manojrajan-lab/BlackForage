"""Conversion between human coin amounts and integer base units.

Floats are never used: amounts are parsed from decimal text with exact
arithmetic and rejected if they need more precision than 8 decimal places.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from blockforge.consensus.params import COIN

DECIMALS = 8


class AmountError(ValueError):
    """Raised for malformed or out-of-range amounts."""


def to_base_units(text: str) -> int:
    """'1.5' -> 150_000_000. Rejects negatives, exponents and >8 decimals."""
    if not isinstance(text, str):
        raise AmountError("amount must be a string")
    text = text.strip()
    if not text or any(c not in "0123456789." for c in text) or text.count(".") > 1:
        raise AmountError("amount must be a plain non-negative decimal number")
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise AmountError("invalid amount") from exc
    scaled = value * COIN
    if scaled != scaled.to_integral_value():
        raise AmountError(f"amount has more than {DECIMALS} decimal places")
    units = int(scaled)
    if units >= (1 << 64):
        raise AmountError("amount too large")
    return units


def format_amount(units: int) -> str:
    """150_000_000 -> '1.50000000' (always 8 decimals, exact)."""
    if not isinstance(units, int) or isinstance(units, bool) or units < 0:
        raise AmountError("units must be a non-negative integer")
    whole, frac = divmod(units, COIN)
    return f"{whole}.{frac:0{DECIMALS}d}"