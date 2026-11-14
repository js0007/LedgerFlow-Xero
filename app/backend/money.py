"""Exact decimal and minor-unit (AUD cents) monetary calculations."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Tuple

CENT_QUANT = Decimal("0.01")
UNIT_HUNDRED = Decimal("100")


def to_decimal(value: str | int | float | Decimal | None) -> Decimal:
    """Parse arbitrary scalar into Decimal cleanly without float drift where string/Decimal given."""
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value).strip())


def round_cents_decimal(dec: Decimal) -> int:
    """Round a dollar Decimal half-up to nearest integer cents."""
    cents_dec = (dec * UNIT_HUNDRED).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents_dec)


def cents_from_value(value: str | int | float | Decimal | None) -> int:
    """Convert a dollar scalar into integer cents."""
    return round_cents_decimal(to_decimal(value))


def decimal_str_from_cents(cents: int) -> str:
    """Format integer cents into canonical 2-decimal AUD string (e.g. '110.00', '-15.50')."""
    d = (Decimal(int(cents)) / UNIT_HUNDRED).quantize(CENT_QUANT, rounding=ROUND_HALF_UP)
    return f"{d:.2f}"


def whole_dollars_from_cents(cents: int) -> int:
    """Convert AUD cents to ATO Simpler BAS whole dollars (half-up for exact half dollars or integer division alignment)."""
    # Note: In live Xero AU Simpler BAS tests (E20, E24, E28, E35, E36), integer dollar amounts like 55, 110, 220, 5, 15, 25
    # divide cleanly; standard ATO BAS whole dollars drop cents toward zero (truncation) or round whole.
    # For half-up vs truncation consistency: ATO Form instructions say "leave out cents" (truncate toward zero).
    val = Decimal(int(cents)) / UNIT_HUNDRED
    return int(val)  # truncates fractional cents toward zero cleanly (e.g. 15.99 -> 15, -5.99 -> -5)


def compute_line_amounts(
    quantity: str | Decimal,
    unit_amount: str | Decimal,
    discount_pct: str | Decimal,
    tax_rate_decimal: str | Decimal,
    tax_mode: str,
) -> Tuple[int, int, int]:
    """Compute (net_cents, tax_cents, gross_cents) using Xero AU line-by-line rounding.

    Rules observed in E21 & Xero Central docs:
    - EXCLUSIVE: line_raw = qty * unit * (1 - disc/100); net = round_cents(line_raw);
      tax = round_cents(net_dollars * rate); gross = net + tax.
    - INCLUSIVE: gross = round_cents(line_raw); tax = round_cents(gross_dollars * rate / (1 + rate));
      net = gross - tax.
    - NO_TAX: net = gross = round_cents(line_raw); tax = 0.
    """
    qty_d = to_decimal(quantity)
    unit_d = to_decimal(unit_amount)
    disc_d = to_decimal(discount_pct)
    rate_d = to_decimal(tax_rate_decimal)

    factor = Decimal("1") - (disc_d / Decimal("100"))
    raw_amount = qty_d * unit_d * factor

    mode = (tax_mode or "EXCLUSIVE").upper()
    if mode == "NO_TAX" or rate_d == Decimal("0"):
        cents = round_cents_decimal(raw_amount)
        return cents, 0, cents

    if mode == "EXCLUSIVE":
        net_cents = round_cents_decimal(raw_amount)
        net_dollars = Decimal(net_cents) / UNIT_HUNDRED
        tax_cents = round_cents_decimal(net_dollars * rate_d)
        gross_cents = net_cents + tax_cents
        return net_cents, tax_cents, gross_cents

    if mode == "INCLUSIVE":
        gross_cents = round_cents_decimal(raw_amount)
        gross_dollars = Decimal(gross_cents) / UNIT_HUNDRED
        tax_cents = round_cents_decimal(gross_dollars * rate_d / (Decimal("1") + rate_d))
        net_cents = gross_cents - tax_cents
        return net_cents, tax_cents, gross_cents

    raise ValueError(f"Unsupported tax_mode: {tax_mode}")
