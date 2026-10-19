"""НДФЛ: прогрессивная шкала и удержание с выплат нарастающим итогом."""

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from itertools import pairwise

SCALE = (
    (Decimal("0"), Decimal("0.13")),
    (Decimal("2400000"), Decimal("0.15")),
    (Decimal("5000000"), Decimal("0.18")),
    (Decimal("20000000"), Decimal("0.20")),
    (Decimal("50000000"), Decimal("0.22")),
)


def tax_on_total(income: Decimal) -> Decimal:
    """Налог по прогрессивной шкале со всего дохода за год, без округления."""
    bounds = [lower for lower, _ in SCALE] + [None]
    tax = Decimal("0")
    for (low, high), (_, rate) in zip(pairwise(bounds), SCALE, strict=True):
        top = income if high is None else min(income, high)
        if top > low:
            tax += (top - low) * rate
    return tax


def withhold(amounts: Sequence[Decimal]) -> list[Decimal]:
    """Налог с каждой выплаты по порядку: нарастающим итогом, в целых рублях."""
    income = Decimal("0")
    withheld = Decimal("0")
    result = []
    for amount in amounts:
        income += amount
        total_tax = tax_on_total(income).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        tax = total_tax - withheld
        withheld += tax
        result.append(tax)
    return result
