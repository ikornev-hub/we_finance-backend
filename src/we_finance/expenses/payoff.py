"""Цель «закрыть кредит к дате»: сколько ЧДП вносить в дни выплат (system/expenses.md §2.7).

Чистые функции поверх графика кредита: кредит, его ЧДП и дни выплат на входе — суммы и даты на
выходе. ЧДП в день выплаты = доля k от суммы выплаты на руки (пропорционально — решение заказчика
2026-10-27), режим — сокращение срока. k подбирается делением пополам по настоящему графику.
"""

import datetime as dt
from collections.abc import Sequence
from decimal import ROUND_CEILING, Decimal

from we_finance.credit.models import Loan, Prepayment, PrepaymentMode
from we_finance.credit.schedule import calculate
from we_finance.credit.state import state_from

ZERO = Decimal("0")
RUBLE = Decimal("1")

Payday = tuple[dt.date, Decimal]  # дата выплаты, сумма на руки


def balance_on(loan: Loan, prepayments: Sequence[Prepayment], day: dt.date) -> Decimal:
    """Остаток долга на дату так же, как в «Кредитах»: платёж в сам день ещё не учтён."""
    rows, applied = calculate(loan, prepayments)
    return state_from(loan, rows, applied, day).balance


def closing_date(loan: Loan, prepayments: Sequence[Prepayment]) -> dt.date:
    """Дата последнего платежа: кредит закрыт."""
    rows, _ = calculate(loan, prepayments)
    return rows[-1].date


def by_share(share: Decimal, paydays: Sequence[Payday]) -> list[Prepayment]:
    """ЧДП в каждый день выплаты: доля share от выплаты, вверх до рубля."""
    result = []
    for day, net in paydays:
        amount = (share * net).quantize(RUBLE, rounding=ROUND_CEILING)
        if amount > 0:
            result.append(Prepayment(day, amount, PrepaymentMode.REDUCE_TERM))
    return result


def solve_share(
    loan: Loan, prepayments: Sequence[Prepayment], paydays: Sequence[Payday], deadline: dt.date
) -> Decimal | None:
    """Наименьшая доля выплат, при которой кредит закрыт не позже deadline.

    0 — и так успевает по графику; None — не успеть даже всеми выплатами.
    """
    if closing_date(loan, prepayments) <= deadline:
        return ZERO
    usable = [payday for payday in paydays if payday[0] <= deadline]
    if not usable or closing_date(loan, [*prepayments, *by_share(Decimal(1), usable)]) > deadline:
        return None
    low, high = Decimal(0), Decimal(1)
    for _ in range(30):
        middle = (low + high) / 2
        if closing_date(loan, [*prepayments, *by_share(middle, usable)]) <= deadline:
            high = middle
        else:
            low = middle
    return high


def interest_total(loan: Loan, prepayments: Sequence[Prepayment]) -> Decimal:
    """Сколько процентов уйдёт банку за весь кредит."""
    rows, _ = calculate(loan, prepayments)
    return sum((row.interest for row in rows), ZERO)
