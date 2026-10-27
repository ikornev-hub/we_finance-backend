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


def _receipt_kind(receipt: Receipt) -> str | None:
    """Вид поступления по словам в описании Альфы; None — по описанию не понять."""
    text = receipt.description.upper()
    if "АВАНС" in text:  # «АВАНС ПО ЗАРАБОТНОЙ ПЛАТЕ» — аванс, а не остаток
        return "advance"
    if "ОТПУСК" in text:
        return "vacation"
    if any(word in text for word in ("БОЛЬНИЧ", "ПОСОБ", "НЕТРУДОСП")):
        return "sick"
    if "ЗАРАБОТН" in text:
        return "remainder"
    return None


def _payment_kind(payment: ExpectedPayment) -> str:
    """Больничный от работодателя и от СФР в выписке не различить — один вид."""
    return "sick" if payment.kind.startswith("sick") else payment.kind


def _pick(payment: ExpectedPayment, receipts: list[Receipt]) -> Receipt | None:
    """Поступление в окне: явно другого вида не берём.

    Дальше — тот же вид, ближе по сумме, ближе по дате. Сумма важнее даты (#51):
    перевод в тот же день не должен перебивать отпускные днём раньше.
    """
    kind = _payment_kind(payment)
    near = [
        r
        for r in receipts
        if abs((r.date - payment.date).days) <= WINDOW_DAYS and _receipt_kind(r) in (None, kind)
    ]
    if not near:
        return None
    return min(
        near,
        key=lambda r: (
            _receipt_kind(r) != kind,
            abs(r.amount - payment.amount),
            abs((r.date - payment.date).days),
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
