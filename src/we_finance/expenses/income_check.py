"""Сверка выплат из «Доходов» с поступлениями по выписке (system/expenses.md §2.5).

Чистые функции: выплаты по расчёту, поступления, периоды выписок и «сегодня» на входе.
"""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

# Зарплату переносят из-за выходных и праздников: ищем поступление в этом окне.
WINDOW_DAYS = 5


class CheckStatus(StrEnum):
    """Пришла ли выплата."""

    CONFIRMED = "confirmed"  # пришло ровно столько
    MISMATCH = "mismatch"  # пришло, но другая сумма
    MISSING = "missing"  # выписка за эти дни есть, а денег нет
    NO_STATEMENT = "no_statement"  # выписки за эти дни нет
    EXPECTED = "expected"  # дата ещё впереди


@dataclass(frozen=True)
class ExpectedPayment:
    """Выплата по расчёту «Доходов»."""

    date: dt.date
    kind: str  # advance, remainder, vacation, …
    amount: Decimal  # на руки


@dataclass(frozen=True)
class Receipt:
    """Поступление из выписки в категории «Доход»."""

    date: dt.date
    amount: Decimal
    description: str


@dataclass(frozen=True)
class IncomeCheck:
    """Итог сверки одной выплаты."""

    date: dt.date
    kind: str
    expected: Decimal
    status: CheckStatus
    operation_date: dt.date | None
    operation_amount: Decimal | None
    difference: Decimal | None  # пришло − ожидали


def _same_kind(payment: ExpectedPayment, receipt: Receipt) -> bool:
    """Аванс в выписке Альфы помечен словом «АВАНС»; всё остальное — нет."""
    is_advance = "АВАНС" in receipt.description.upper()
    return is_advance == (payment.kind == "advance")


def _pick(payment: ExpectedPayment, receipts: list[Receipt]) -> Receipt | None:
    """Лучшее поступление в окне: того же вида, ближе по дате, ближе по сумме."""
    near = [r for r in receipts if abs((r.date - payment.date).days) <= WINDOW_DAYS]
    if not near:
        return None
    return min(
        near,
        key=lambda r: (
            not _same_kind(payment, r),
            abs((r.date - payment.date).days),
            abs(r.amount - payment.amount),
        ),
    )


def check_income(
    payments: list[ExpectedPayment],
    receipts: list[Receipt],
    periods: list[tuple[dt.date, dt.date]],
    today: dt.date,
) -> list[IncomeCheck]:
    """Каждой выплате — своё поступление (одно поступление — одной выплате) и статус."""
    free = list(receipts)
    result = []
    for payment in sorted(payments, key=lambda p: p.date):
        receipt = _pick(payment, free)
        if receipt is not None:
            free.remove(receipt)
            status = (
                CheckStatus.CONFIRMED if receipt.amount == payment.amount else CheckStatus.MISMATCH
            )
            result.append(
                IncomeCheck(
                    payment.date,
                    payment.kind,
                    payment.amount,
                    status,
                    receipt.date,
                    receipt.amount,
                    receipt.amount - payment.amount,
                )
            )
            continue
        if payment.date > today:
            status = CheckStatus.EXPECTED
        elif any(start <= payment.date <= end for start, end in periods):
            status = CheckStatus.MISSING
        else:
            status = CheckStatus.NO_STATEMENT
        result.append(
            IncomeCheck(payment.date, payment.kind, payment.amount, status, None, None, None)
        )
    return result
