"""Модуль приведения указанной суммы."""

from decimal import ROUND_HALF_UP, Decimal


def to_money(value: Decimal | int | str | float) -> Decimal:
    """Привести сумму к копейкам, половина копейки - вверх"""

    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
